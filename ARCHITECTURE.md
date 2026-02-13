# Memory-Enhanced Multi-Agent System — Architecture

## Project Vision

A multi-agent AI system that runs on OpenClaw, designed for someone interested in AI agents running on a ~$5-20 VPS. No Docker, no Redis, no complex infrastructure — just OpenClaw sessions and SQLite.

- **One-command installer** with TUI wizard (using `gum`)
- **5 AI agents** as OpenClaw sessions, orchestrated by Brain
- **Layered memory system** with SQLite for everything
- **Portable agent interface** — designed to migrate to Docker later if needed

## Quick Launch Architecture (v1)

Brain runs as the **main OpenClaw agent session**. When it needs other agents, it **spawns them as OpenClaw sub-sessions** (concurrent LLM calls within the parent session). All persistent state lives in **SQLite** — message history, memory, knowledge cache.

No containers. No Redis. No separate services. One process, one database file, multiple agent personalities.

## The 5 Agents

### 🧠 Brain (Chief of Staff)
- **Role**: Intent classification, task decomposition, delegation, response synthesis, memory gatekeeper
- **Model**: Best available (claude or similar)
- **Runs as**: Main OpenClaw session — the entry point for all user interaction
- **Permissions**: Delegates to all agents, reads/writes shared memory, owns conversation state
- **Sub-agents**: NEVER — must maintain unified coherence
- **Context receives**: Everything (it's the hub)

### 🔨 Builder (Engineer)
- **Role**: Code generation, file operations, tool execution, debugging
- **Model**: Fast code model (deepseek-chat or codestral)
- **Runs as**: Spawned session from Brain
- **Permissions**: Can execute code, NO internet, NO memory writes, flags factual claims
- **Sub-agents**: YES for multi-component builds (architect → parallel build → integration → test)
- **Context receives**: Recent code context, file state, available tools, interface contracts

### ✅ Verifier (Editor/QA)
- **Role**: Claim verification, source checking, consistency analysis, hallucination detection, knowledge cache updates
- **Model**: Precise reasoning model (qwen-max or claude)
- **Runs as**: Spawned session from Brain
- **Permissions**: Can search web, can update knowledge cache, NO code execution
- **Sub-agents**: YES for batch verification (parallel claim checking)
- **Context receives**: Claims to verify, knowledge cache excerpts, conversation claims

### 🔍 Investigator (Analyst/Librarian)
- **Role**: Proactive information gathering, multi-source synthesis, documentation reading, prior art discovery
- **Model**: Good at synthesis (qwen-max or similar)
- **Runs as**: Spawned session from Brain
- **Permissions**: Full web access, can read repos/docs, feeds knowledge cache
- **Sub-agents**: ALWAYS — research is embarrassingly parallel (3-6 threads per query, then synthesis)
- **Context receives**: Research query, known knowledge gaps, preferred source types

### 🛡️ Guardian (Security Lead)
- **Role**: Security review of Builder output, config validation, prompt injection detection, permissions monitoring, cost tracking
- **Model**: Precise model (claude or qwen-max)
- **Runs as**: Spawned session from Brain
- **Permissions**: Read-only on all agent outputs, can BLOCK actions, monitors costs
- **Sub-agents**: NEVER — must see full picture
- **Context receives**: Full output under review, permissions config, cost metrics

## Sub-Agent Design

Sub-agents are concurrent LLM calls within the parent agent's OpenClaw session. They share the session's tool access but get isolated context.

### Sub-Agent Decision Matrix
| Agent | Sub-Agents? | Trigger Condition |
|-------|-------------|-------------------|
| Brain | ✗ Never | N/A |
| Builder | ✓ Conditional | Multi-component builds only |
| Verifier | ✓ Conditional | Batch verification (3+ claims) |
| Investigator | ✓ Always | Every query → 3-6 parallel threads |
| Guardian | ✗ Never | N/A |

## Communication Protocol

All agent communication goes through **SQLite tables** acting as a message bus. Brain orchestrates all routing — no direct agent-to-agent communication.

### Message Format
```python
@dataclass
class AgentMessage:
    task_id: str          # UUID
    from_agent: AgentRole # brain, builder, verifier, investigator, guardian
    to_agent: AgentRole
    action: str           # "build", "verify", "research", "review", "synthesize"
    payload: dict         # Task-specific data
    context: dict         # SCOPED — only what this agent needs
    constraints: dict     # Budget limits, time limits, scope limits
    status: TaskStatus    # pending, in_progress, completed, failed, needs_review
    result: Optional[dict]
    created_at: datetime
```

### Context Scoping (Critical)
Brain acts as a privacy/relevance filter. Each agent ONLY receives the context it needs (see agent descriptions above). This keeps token usage efficient and prevents context pollution.

## Memory Architecture

### Three Tiers
1. **Working Memory** — Current conversation in the context window. Free, instant, ephemeral.
2. **Short-term Memory** — Recent interactions stored in SQLite with embeddings. Scored by recency (exponential decay, 7-day half-life) and importance.
3. **Long-term Memory** — Consolidated knowledge in SQLite. High importance, low decay. Created by consolidation jobs from short-term clusters.

### Knowledge Cache
Verified facts stored in SQLite with NO decay. Updated by Verifier and Investigator. Examples: confirmed API specs, validated user preferences, verified research findings. Always checked first during retrieval.

### Embeddings
- **Default: Local** — MiniLM-L6-v2 (~80MB, runs on CPU, free, private). ~95% quality of API models for similarity tasks.
- **Optional: API** — OpenAI, Voyage, or Cohere embeddings for maximum quality. Costs per call.
- Wizard lets user choose. Default is local.

### Scoring System
Each memory gets a composite score:
- **Semantic similarity**: Cosine distance between query embedding and memory embedding
- **Recency score**: Exponential decay with 7-day half-life. Formula: `recency = exp(-0.693 * days_old / 7)`
- **Importance score**: Heuristic based on signals:
  - User corrections/preferences: HIGH (0.8-1.0)
  - Decisions and commitments: HIGH (0.7-0.9)
  - Error corrections: HIGH (0.8)
  - Repeated topics: MEDIUM (boosted on each repetition)
  - General conversation: LOW (0.1-0.3)
  - Feedback-adjusted: User confirms ("that's right") boosts importance, user denies ("that's outdated") decays importance

### Retrieval Strategies
- `"balanced"`: 0.4 semantic + 0.3 recency + 0.3 importance
- `"recency"`: 0.3 semantic + 0.5 recency + 0.2 importance
- `"importance"`: 0.3 semantic + 0.2 recency + 0.5 importance
- `"exact"`: Check knowledge cache first, fallback to semantic search

### Context Window Budget
Hard cap prevents context overflow:
```
Total context window: 100%
├── System prompt + SOUL.md:     ~10%
├── Memory injection:            ~15% (hard cap)
│   ├── Knowledge cache hits:    priority 1
│   ├── Long-term memories:      priority 2
│   └── Short-term memories:     priority 3
├── Conversation history:        ~65%
└── Response buffer:             ~10%
```
Smart retrieval: rank all matching memories, include only top 3-5 that fit in budget. If conversation is long, memory gets squeezed. If short, memory gets more room.

### Turn Processing Pipeline
Every conversation turn (user query + agent response) is processed before storage:

**Step 1: Split the Turn**
Each turn produces two separate processing units — the user message and the agent response. They are never stored as a single blob.

**Step 2: Intelligent Chunking (long responses only)**
- Short responses (< 200 tokens) → stored as one chunk
- Long responses → split by **topic** using a cheap LLM call (DeepSeek/Qwen), not by character count
- Each chunk becomes its own memory with `part_of` links tying them together
- Retrieval can pull "OAuth2 discussion" without the unrelated "rate limiting" chunk from the same response

**Step 3: Metadata Stamping**
Every stored memory gets rich metadata:

User message metadata:
```json
{
  "type": "user_query",
  "timestamp": "2026-02-13T04:05:00Z",
  "user": "Jason",
  "turn_id": "turn_047",
  "tags": ["domain:auth", "type:request"],
  "links": {
    "response_id": "mem_048a"
  }
}
```

Agent response metadata:
```json
{
  "type": "agent_response",
  "timestamp": "2026-02-13T04:05:03Z",
  "agent": "brain",
  "turn_id": "turn_047",
  "chunk": "1/2",
  "tags": ["domain:auth", "topic:oauth2", "type:technical"],
  "links": {
    "query_id": "mem_047",
    "sibling": "mem_048b",
    "delegates": ["builder"]
  }
}
```

**Step 4: Standard Pipeline**
After splitting, chunking, and stamping → each piece goes through dedup check, importance scoring, embedding generation, and storage.

**Key properties:**
- Bidirectional links — trace from any response back to its query, or from a chunk to its siblings
- Semantic chunking — split at topic boundaries, not character counts
- Cost-controlled — only long responses trigger the chunking LLM call (cheap model)
- Nothing exists in isolation — every memory has context links

### Deduplication
On every new memory ingest:
1. **Exact/near duplicate** (similarity > 0.92) → Don't store. Boost importance of existing memory. Update timestamp.
2. **Related but different** (similarity 0.7-0.92) → Store new memory. Create link to related memory.
3. **Novel** (similarity < 0.7) → Store as fresh memory.

### Knowledge Graph (Lightweight)
SQLite table `memory_links`:
```sql
CREATE TABLE memory_links (
    memory_id_a TEXT,
    memory_id_b TEXT,
    relation_type TEXT,  -- 'supersedes', 'related_to', 'contradicts', 'elaborates'
    strength REAL,
    created_at TIMESTAMP
);
```
When Brain retrieves a memory, it follows links to pull related context. "User likes Python" → links to "User builds ML pipelines" → links to "User prefers PyTorch." One retrieval gives a cluster of connected knowledge.

### Memory Conflict Resolution
When new memory contradicts an existing one (detected via dedup check + LLM classification):
1. Mark old memory with relation `superseded_by` → new memory
2. Decay old memory's importance to near-zero (don't delete — audit trail)
3. New memory inherits old one's links
4. Guardian notified of conflict for logging

### Consolidation
**Daily job (Full tier) / Weekly job (Standard tier):**
1. Scan short-term memories older than 7 days
2. Cluster by similarity (group related memories)
3. LLM summarizes each cluster into one long-term memory (uses cheapest model — DeepSeek or Qwen)
4. Summary gets importance = max(cluster importance scores)
5. Delete originals from short-term, keep links to summary
6. Update knowledge graph links to point to consolidated memory

**Full tier:** Daily consolidation, keeps everything
**Standard tier:** Weekly consolidation, prunes low-importance memories (below 0.3 threshold)

### Cross-Agent Memory
- Investigator discovers info during research → writes to knowledge cache
- Verifier verifies claims → writes to knowledge cache
- Brain reads knowledge cache automatically on next relevant query
- System gets smarter over time without user doing anything

### Feedback-Driven Importance
When Brain retrieves a memory and user responds:
- Positive signal ("exactly", "that's right") → boost importance by 0.1
- Negative signal ("that's outdated", "wrong") → decay importance by 0.3 or mark superseded
- Brain detects these signals naturally during conversation, no explicit UI needed

### Memory Permissions
- **Brain**: Read + write shared memory (gatekeeper)
- **Builder**: Read shared memory only
- **Verifier**: Read shared memory, write knowledge cache
- **Investigator**: Read shared memory, write knowledge cache
- **Guardian**: Read all memory (audit), no writes

### Auto-Tagging
Every memory is automatically tagged on ingest by Brain's gating process:
- **Domain tags**: `domain:python`, `domain:ml`, `domain:devops`
- **Type tags**: `type:preference`, `type:decision`, `type:fact`, `type:correction`, `type:project`
- **Project tags**: `project:ml-pipeline`, `project:api-refactor`
- **Agent tags**: `source:investigator`, `source:verifier` (auto-set by source agent)

Tags are stored in the metadata JSON column and indexed for fast filtering. Retrieval can filter by tag before scoring, e.g., "find all memories tagged `project:ml-pipeline` with importance > 0.5."

Tags are inferred automatically — user never has to tag anything manually.

### SQLite Schema Overview
```sql
-- Core memories table
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    embedding BLOB,
    tier TEXT CHECK(tier IN ('short_term', 'long_term')),
    importance REAL DEFAULT 0.5,
    tags TEXT,  -- comma-separated tags for fast filtering
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    source_agent TEXT,
    metadata JSON
);

-- Verified facts (no decay)
CREATE TABLE knowledge_cache (
    id TEXT PRIMARY KEY,
    fact TEXT NOT NULL,
    embedding BLOB,
    source TEXT,
    verified_by TEXT,
    verified_at TIMESTAMP,
    confidence REAL DEFAULT 1.0,
    metadata JSON
);

-- Knowledge graph links
CREATE TABLE memory_links (
    memory_id_a TEXT,
    memory_id_b TEXT,
    relation_type TEXT,
    strength REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Config System

### Three-Layer Precedence (highest → lowest)
1. **User overrides** (`configs/user/local.yaml`) — never auto-modified
2. **Distro defaults** (`configs/overlays/{use_case}/`) — auto-updated with distro
3. **Base defaults** (`configs/base/`) — auto-updated

## Wizard Flow

### Prerequisites
1. Install OpenClaw (wizard handles this if not present)
2. Run guided setup

### Steps
1. OpenClaw installation check/install
2. Use case selection (General, Coding, Research, Custom)
3. Model selection per agent (with sensible defaults)
4. API key entry (guided, per provider)
5. Memory tier selection (Full / Standard / Minimal)
6. Tool selection (MCP servers, integrations)
7. Integration setup (Telegram, Discord, etc.)
8. Agent mode (Full 5-agent, Trio, Solo)
9. Generate configs → start OpenClaw sessions

## Agent Interface (Portability)

Each agent implements a common interface so the execution backend can change without rewriting agent logic:

```python
class AgentInterface:
    """Portable agent interface — today OpenClaw sessions, tomorrow Docker."""
    
    async def send_message(self, msg: AgentMessage) -> None: ...
    async def receive_message(self) -> AgentMessage: ...
    async def spawn_sub_agent(self, context: dict) -> SubAgentHandle: ...
    async def read_memory(self, query: str, strategy: str) -> list[Memory]: ...
    async def write_memory(self, memory: Memory) -> None: ...
```

The v1 implementation uses OpenClaw session spawning. A future Docker implementation would swap the transport layer while keeping agent logic identical.

## File Structure

```
memory-enhanced-multi-agent/
├── install.sh                          # Entry point — checks/installs OpenClaw, launches wizard
├── wizard/
│   ├── tui.sh                          # Main wizard (gum-based)
│   ├── steps/
│   │   ├── 01_openclaw_check.sh        # Verify/install OpenClaw
│   │   ├── 02_use_case.sh
│   │   ├── 03_model_selection.sh
│   │   ├── 04_api_keys.sh
│   │   ├── 05_memory_setup.sh
│   │   ├── 06_tools_install.sh
│   │   ├── 07_integrations.sh
│   │   └── 08_agent_mode.sh
│   ├── templates/
│   │   ├── agent_configs.yaml.j2
│   │   ├── session_configs.yaml.j2     # OpenClaw session definitions
│   │   └── .env.j2
│   └── generate_configs.sh
├── agents/
│   ├── common/
│   │   ├── interface.py                # AgentInterface (portable)
│   │   ├── protocol.py                 # AgentMessage, SQLite message bus
│   │   ├── base_agent.py               # Shared agent scaffolding
│   │   ├── sub_agent.py                # SubAgentPool (concurrent LLM calls)
│   │   └── llm_client.py               # Unified LLM interface
│   ├── brain/
│   │   ├── brain.py
│   │   ├── classifier.py
│   │   ├── decomposer.py
│   │   ├── synthesizer.py
│   │   └── system_prompt.md
│   ├── builder/
│   │   ├── builder.py
│   │   ├── sandbox.py
│   │   ├── tool_runner.py
│   │   └── system_prompt.md
│   ├── verifier/
│   │   ├── verifier.py
│   │   ├── consistency.py
│   │   ├── web_verifier.py
│   │   └── system_prompt.md
│   ├── investigator/
│   │   ├── investigator.py
│   │   ├── source_evaluator.py
│   │   ├── synthesizer.py
│   │   └── system_prompt.md
│   └── guardian/
│       ├── guardian.py
│       ├── security_scanner.py
│       ├── cost_tracker.py
│       └── system_prompt.md
├── memory/
│   ├── engine.py                       # MemoryEngine orchestration
│   ├── sqlite_store.py                 # SQLite for vectors + structured data
│   ├── scored_memory.py                # Importance + recency scoring
│   ├── knowledge_cache.py              # Verified facts (SQLite)
│   ├── embeddings.py                   # Embedding generation
│   ├── consolidation.py                # Background memory maintenance
│   ├── schemas/
│   │   └── sqlite_schema.sql           # All tables: messages, memory, knowledge, embeddings
│   └── retrieval.py                    # Layered search
├── configs/
│   ├── base/
│   │   ├── agents.yaml                 # Agent definitions + model assignments
│   │   ├── routing_rules.yaml          # Brain routing logic
│   │   ├── permissions.yaml            # Agent permissions matrix
│   │   └── system-prompts/
│   ├── overlays/
│   │   ├── coding-assistant/
│   │   ├── research-agent/
│   │   └── general-purpose/
│   └── user/                           # gitignored
│       └── local.yaml
├── updater/
│   ├── auto_update.sh
│   └── config_merger.py
├── tools/
│   ├── registry.yaml
│   └── installers/
│       ├── mcp_filesystem.sh
│       ├── mcp_github.sh
│       ├── mcp_browser.sh
│       └── web_search.sh
├── data/                               # Runtime data (gitignored)
│   ├── memory.db                       # SQLite: memory, knowledge cache, message bus
│   └── sessions/                       # OpenClaw session state
├── Makefile
├── ARCHITECTURE.md                     # This file
├── ROADMAP.md
└── README.md
```

## Implementation Phases

### Phase 1 — Wizard + Single Agent
- Wizard (gum TUI) with OpenClaw install check
- Config generation from templates
- Brain agent running as main OpenClaw session
- Basic SQLite schema for message bus + memory
- Single-agent mode working end-to-end

### Phase 2 — Memory System
- SQLite-backed vector store with embeddings
- Knowledge cache + scoring tables
- Retrieval API with importance/recency scoring
- Embedding generation (local or API)
- Hook into Brain's conversation flow

### Phase 3 — Multi-Agent Sessions
- Agent interface implementation for OpenClaw sessions
- Brain spawns Builder, Verifier, Investigator, Guardian as sessions
- SQLite message bus for communication
- Context scoping through Brain
- Sub-agent pools for Builder and Investigator

### Phase 4 — Polish + Hardening
- Cost tracking
- Memory consolidation background job
- Tool registry + guided installers
- Config auto-updater
- Error recovery and graceful degradation

## Key Design Decisions

1. **OpenClaw sessions** (not Docker) — zero infrastructure overhead, runs on a $5 VPS, easy to understand
2. **SQLite for everything** (not Redis + LanceDB + Postgres) — one file, zero config, sufficient for single-user scale
3. **Brain as main session** — natural hub, user talks to Brain, Brain delegates via spawned sessions
4. **Portable agent interface** — abstract the transport so we can move to Docker containers later without rewriting agents
5. **gum for TUI** — single binary, beautiful defaults, shell-native
6. **Sub-agents as concurrent calls** (not separate sessions) — lightweight, fast, shared model connection
7. **Guardian as interceptor** — sees all traffic through Brain, can block, doesn't need its own delegation chain
8. **Context scoping through Brain** — each agent gets only what it needs, keeping token usage efficient
