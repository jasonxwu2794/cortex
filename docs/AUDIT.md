# Code Audit Report — MemoryEnhancedMultiAgent

**Date:** 2026-02-13
**Auditor:** T Builder 1
**Overall Health Score:** 7.0/10
**Critical Issues:** 3 | **Refactor Opportunities:** 12 | **Nice-to-haves:** 10

---

## 1. Summary

The codebase is well-structured for an MVP with clear separation of concerns across agents and memory layers. The main risks are around **SQLite connection management** (connections opened and never closed in hot paths), **duplicate patterns across DB-backed modules**, and a few **security gaps**. The code is readable, consistently documented, and shows good error handling philosophy (never crash the caller). However, several modules create new SQLite connections per operation without pooling or context managers, which will cause issues under load.

---

## 2. Critical Issues (Must Fix)

### C1: SQLite Connections Leaked in Hot Paths
**Severity:** HIGH
**Files:** `agents/common/usage_tracker.py`, `agents/common/activity_log.py`, `agents/brain/project_manager.py`
**Lines:** Every method that calls `self._conn()` — e.g., `usage_tracker.py:log_call()`, `activity_log.py:log()`, `project_manager.py` (nearly every method)

All three modules follow the pattern:
```python
conn = self._conn()
conn.execute(...)
conn.commit()
conn.close()
```

**Problem:** If an exception occurs between `_conn()` and `close()`, the connection leaks. Under load, this exhausts SQLite's connection limit and causes `OperationalError: too many open files`.

**Fix:** Use context managers (`with self._conn() as conn:`) or a single persistent connection like `MessageBus` does.

**Dependencies:** Affects all agents (every agent uses ActivityLog), all LLM calls (UsageTracker), and all project operations.

---

### C2: `MemoryEngine._get_existing_embeddings()` Loads ALL Embeddings Into Memory
**Severity:** HIGH
**File:** `memory/engine.py`, line ~180
**Method:** `_get_existing_embeddings()`

```python
rows = self.db.execute("SELECT id, embedding FROM memories WHERE embedding IS NOT NULL").fetchall()
```

This loads every embedding from the entire database into memory on **every ingest call**. With thousands of memories, this causes O(n²) behavior per ingest and potential OOM.

**Fix:** Use approximate nearest neighbor search (e.g., sqlite-vss) or limit to recent memories for dedup. At minimum, add a LIMIT or time-window filter.

**Dependencies:** `memory/engine.py:ingest()`, `memory/dedup.py`

---

### C3: `knowledge_cache.lookup_facts()` Full Table Scan
**Severity:** HIGH
**File:** `memory/knowledge_cache.py`, line ~35
**Method:** `lookup_facts()`

```python
rows = db.execute("SELECT id, fact, embedding, confidence, metadata FROM knowledge_cache").fetchall()
```

Same problem as C2 — scans the entire knowledge cache and deserializes all embeddings on every retrieval. This is O(n) per query with no indexing on vector similarity.

**Fix:** Same as C2 — vector index or at minimum a confidence/recency filter before loading.

**Dependencies:** `memory/engine.py:retrieve()`, `agents/verifier/verifier.py`, `agents/researcher/researcher.py`

---

## 3. Refactor Opportunities (Should Fix)

### R1: Duplicated SQLite Boilerplate (4 modules)
**Severity:** MEDIUM
**Files:** `usage_tracker.py`, `activity_log.py`, `project_manager.py`, `protocol.py` (MessageBus)

All four modules independently:
- Create directories with `os.makedirs()`
- Open connections with `sqlite3.connect()`
- Set `row_factory`
- Execute schema DDL
- Implement `_conn()` helper

**Recommendation:** Extract a `SQLiteStore` base class or utility that handles connection lifecycle, schema init, and WAL mode in one place.

**Dependencies:** Touching all 4 modules; should be done carefully with tests.

---

### R2: Duplicate Secret Patterns (GitOps + Guardian)
**Severity:** MEDIUM
**Files:** `agents/common/gitops.py` (lines 15-26), `agents/guardian/guardian.py` (lines 44-60), `scripts/pre-commit` (lines 42-55)

The same secret detection regex patterns are defined in **three separate places** with slight variations:
- GitOps has string patterns
- Guardian has compiled regex patterns
- Pre-commit hook has bash patterns

**Recommendation:** Single source of truth in a shared module (e.g., `agents/common/secrets.py`), with export formats for Python and bash.

**Dependencies:** `gitops.py`, `guardian.py`, `scripts/pre-commit`

---

### R3: Inconsistent DB Connection Patterns
**Severity:** MEDIUM
**Files:** All SQLite-using modules

| Module | Pattern |
|--------|---------|
| `MessageBus` | Persistent connection (`self._db`) |
| `MemoryEngine` | Persistent connection (`self.db`) |
| `UsageTracker` | New connection per call (`self._conn()`) |
| `ActivityLog` | New connection per call (`self._conn()`) |
| `ProjectManager` | New connection per call (`self._conn()`) |

**Recommendation:** Standardize on one pattern. For single-process use, persistent connection with WAL mode is best. For multi-process, connection-per-call but with context managers.

---

### R4: `MemoryEngine` Missing `store_fact()` and `lookup_facts()` Methods
**Severity:** MEDIUM
**Files:** `memory/engine.py`, `agents/researcher/researcher.py` (line ~400), `agents/verifier/verifier.py` (line ~340)

Both Researcher and Verifier call `self.memory.store_fact()` and `self.memory.lookup_facts()`, but `MemoryEngine` has no such methods. The `knowledge_cache` module has standalone functions `store_fact()` and `lookup_facts()`. The engine's `retrieve()` method calls `lookup_facts()` directly as a module-level function.

**Problem:** If Researcher/Verifier actually run, they'll get `AttributeError`. This is dead code that was never integration-tested.

**Fix:** Add `store_fact()` and `lookup_facts()` wrapper methods to `MemoryEngine`.

**Dependencies:** `agents/researcher/researcher.py`, `agents/verifier/verifier.py`

---

### R5: `APIEmbedder` is a Dead Stub
**Severity:** LOW
**File:** `memory/embeddings.py`, lines 25-35

`APIEmbedder.embed()` raises `NotImplementedError`. The `get_embedder()` factory can create one, but it will crash immediately. Contains a TODO that was never implemented.

**Fix:** Either implement it or remove the class and add a clear error message in `get_embedder()`.

---

### R6: System Prompt Loading Pattern Duplicated Across All Agents
**Severity:** MEDIUM
**Files:** `brain.py`, `builder.py`, `researcher.py`, `verifier.py`, `guardian.py`

Every agent has identical logic:
```python
if self._system_prompt_text is None:
    prompt_path = Path(__file__).parent / "system_prompt.md"
    if prompt_path.exists():
        self._system_prompt_text = prompt_path.read_text()
    else:
        self._system_prompt_text = "fallback..."
```

**Recommendation:** Move to `BaseAgent` as a default implementation with an overridable fallback string.

---

### R7: `retry_with_backoff` Imported But Never Used
**Severity:** LOW
**File:** `agents/common/llm_client.py`, line 10

`from agents.common.retry import retry_with_backoff` is imported but the client implements its own retry logic inline in `_call_with_resilience()`.

**Fix:** Either use `retry_with_backoff` or remove the import.

---

### R8: `AIDER_AVAILABLE` Runs `which` at Import Time
**Severity:** MEDIUM
**File:** `agents/builder/builder.py`, line ~30

```python
AIDER_AVAILABLE = bool(subprocess.run(
    ["which", "aider"], capture_output=True, text=True
).returncode == 0)
```

This runs a subprocess **at module import time**, which:
1. Slows down imports
2. Fails on systems without `which` (Windows)
3. Makes testing harder

**Fix:** Lazy check on first use.

---

### R9: Hardcoded Paths and Values
**Severity:** MEDIUM
**Files:** Various

| Hardcoded Value | File | Should Be |
|----------------|------|-----------|
| `"data/memory.db"` | engine.py, brain.py | Config/env var |
| `"data/messages.db"` | protocol.py | Config/env var |
| `"data/usage.db"` | usage_tracker.py | Config/env var |
| `"data/activity.db"` | activity_log.py | Config/env var |
| `"data/projects.db"` | project_manager.py | Config/env var |
| `"/workspace"` | builder.py, brain.py | Config/env var |
| `"/data/knowledge"` | researcher.py, verifier.py | Config/env var |
| `"claude-sonnet-4-20250514"` | base_agent.py, llm_client.py | Config |
| `1_000_000` daily token budget | guardian.py | Config |

**Recommendation:** Create a central `config.py` or use a config file that all modules reference.

---

### R10: `MessageBus` and `AgentSessionManager` Are Parallel Delegation Systems
**Severity:** MEDIUM
**Files:** `protocol.py` (MessageBus), `session_manager.py` (AgentSessionManager)

The Brain uses `AgentSessionManager` for delegation (spawning openclaw sessions), while `BaseAgent` provides `delegate()` using the SQLite `MessageBus`. The Guardian uses `MessageBus` directly. These are two separate communication channels that don't interact.

**Recommendation:** Document which system is canonical. The session manager appears to be the production path; the MessageBus might be the MVP/testing path. Clarify or unify.

---

### R11: `consolidation.py` Uses String Concatenation for Summaries Instead of LLM
**Severity:** LOW
**File:** `memory/consolidation.py`, `summarize_cluster()` method

The consolidation module explicitly avoids LLM calls (suitable for cron), but the resulting summaries are mechanical concatenations that may not be coherent. The comment says "No LLM needed — suitable for cron" but this produces low-quality long-term memories.

**Recommendation:** Consider an optional LLM-enhanced consolidation mode for when quality matters more than cost.

---

### R12: `schemas.py` and `graduation.py` Both Do Column Migration
**Severity:** LOW
**Files:** `memory/schemas.py` (lines 45-52), `memory/graduation.py` (`_ensure_columns()`)

Both files add `last_accessed_at` and `access_count` columns to `knowledge_cache`. The migration in `schemas.py:init_db()` and `graduation.py:_ensure_columns()` do the same thing redundantly.

**Fix:** Single migration point in `schemas.py`.

---

## 4. Nice-to-Haves (Could Fix)

### N1: Type Hint Gaps
- `brain.py:_context_fn_for_agent()` returns `callable` (should be `Callable`)
- `brain.py:_handle_single_agent()` parameter `context_fn: callable` (should be `Callable`)
- `project_manager.py:Feature.tasks` typed as `list` (should be `list[Task]`)
- `web_search.py:WebSearchClient.__init__()` parameter `backend` has no type hint
- `consolidation.py` functions lack return type hints on helper functions

### N2: Missing `__all__` Exports
- `agents/common/__init__.py` is empty — should export key classes
- `agents/__init__.py` is empty — should export agent classes
- `memory/__init__.py` only exports `MemoryEngine` and `consolidation_runner`

### N3: `datetime.utcnow()` Deprecated
**Files:** `usage_tracker.py`, `activity_log.py`, `graduation.py`, `knowledge_refresh.py`, `project_manager.py`

`datetime.utcnow()` is deprecated in Python 3.12+. Should use `datetime.now(timezone.utc)`.

Some files already use `datetime.now(timezone.utc)` (e.g., `scoring.py`, `chunker.py`), creating inconsistency.

### N4: No Logging in `memory/schemas.py`, `memory/scoring.py`, `memory/dedup.py`
These modules have no logging, making debugging harder.

### N5: `BuilderAgent._write_artifact()` Creates `clean_path` But Never Uses It
**File:** `agents/builder/builder.py`, line ~510
```python
clean_path = Path(path_str).resolve()  # unused
full_path = (self._workspace / path_str).resolve()
```

### N6: Tests Reference `agents.investigator.investigator` (Non-existent Module)
**File:** `tests/test_integration.py`

The integration test imports `InvestigatorAgent` from `agents.investigator.investigator`, but this module doesn't exist in the codebase (the role is `RESEARCHER` not `INVESTIGATOR`). This test would fail.

### N7: `__pycache__` Committed to Repository
**Files:** `tests/__pycache__/` contains `.pyc` files. Add `__pycache__/` to `.gitignore`.

### N8: Shell Scripts Missing `shellcheck` Compliance
The wizard scripts and maintenance scripts work but could benefit from `shellcheck` validation. Some use unquoted variables in loops.

### N9: `LLMResponse` Dataclass Defined But Never Used
**File:** `agents/common/llm_client.py`, line 31. The `LLMResponse` dataclass is defined but the client returns plain dicts instead.

### N10: `guardian.py` Potential False Positive on AWS Secret Key Pattern
**File:** `agents/guardian/guardian.py`, line ~54
```python
(re.compile(r'[a-zA-Z0-9+/]{40}', re.ASCII), "Potential AWS secret key"),
```
This matches any 40-character base64 string, which will fire on commit hashes, UUIDs, etc. Very noisy.

---

## 5. Dependencies Map

| Issue | Affects |
|-------|---------|
| C1 (Connection leaks) | All agents, all LLM calls, all project operations |
| C2 (Full embedding scan) | Memory ingest performance, scales with data |
| C3 (Knowledge cache scan) | Retrieval performance, Verifier, Researcher |
| R1 (SQLite boilerplate) | 4 modules, but can be refactored incrementally |
| R2 (Duplicate secrets) | 3 files, low coupling |
| R4 (Missing engine methods) | Researcher, Verifier — currently dead paths |
| R6 (System prompt loading) | 5 agent files |
| R9 (Hardcoded paths) | All modules, deployment flexibility |
| R10 (Dual delegation) | Brain, BaseAgent, Guardian — architectural decision |
| N3 (utcnow deprecated) | 5 files, simple find-replace |
| N6 (Missing investigator) | Tests won't pass |

---

## 6. Recommended Priority Order

| Priority | Issue | Impact | Effort | Notes |
|----------|-------|--------|--------|-------|
| 1 | **C1** Connection leaks | High | Low | Add context managers or persistent connections |
| 2 | **C2** Full embedding load | High | Medium | Add LIMIT/window filter |
| 3 | **C3** Knowledge cache scan | High | Medium | Same approach as C2 |
| 4 | **R4** Missing engine methods | Medium | Low | Add 2 wrapper methods |
| 5 | **N6** Fix test imports | Medium | Low | Rename investigator → researcher |
| 6 | **R9** Hardcoded paths | Medium | Medium | Central config module |
| 7 | **R1** SQLite boilerplate | Medium | Medium | Extract shared base |
| 8 | **R6** System prompt duplication | Low | Low | Move to BaseAgent |
| 9 | **R2** Duplicate secret patterns | Low | Low | Single shared module |
| 10 | **N3** utcnow deprecation | Low | Low | Simple search-replace |
| 11 | **R7** Unused import | Low | Trivial | Delete one line |
| 12 | **R8** Import-time subprocess | Low | Low | Lazy evaluation |

---

## 7. Circular Import Analysis

**No circular imports detected.** The dependency graph is clean:

```
memory.* ← agents.common.* ← agents.{brain,builder,researcher,verifier,guardian}
                             ↑
                    agents.session_manager
```

`memory/` has no imports from `agents/`. Agent modules import from `common/` and `memory/` but not from each other (except Brain imports from `session_manager` and `brain/` submodules). Clean layering.

---

## 8. Module Structure Assessment

**Verdict: Clean and well-organized.**

- Clear separation: `memory/` for persistence, `agents/common/` for shared infra, `agents/{role}/` for specialists
- Each agent has its own directory with `__init__.py` and main module
- Brain's submodules (`spec_writer`, `task_decomposer`, `project_manager`) are properly scoped
- Wizard steps are numbered and sequential
- Scripts are task-focused with clear purposes

**One concern:** `agents/session_manager.py` sits at the `agents/` level rather than in `agents/common/` or `agents/brain/`, despite being used exclusively by Brain. Consider moving it.
