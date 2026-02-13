# ROADMAP

## Phase 1: Foundation ✅

### Setup & Installation
- [x] `install.sh` entry point
- [x] Wizard TUI (gum) — 12 steps: prereqs, OpenClaw install, config mode, user identity, tech stack, brain personality, model selection, API keys, memory setup, messaging, tools, deploy
- [x] Tech stack wizard step (language, frameworks, package manager, DB)
- [x] Stealth/verbose mode toggle for agent transparency
- [x] Deploy step wires real OpenClaw config (`openclaw.json`, `auth-profiles.json`)
- [x] Linger enabled (survives terminal disconnect)
- [x] Python packaging (`pyproject.toml`, requirements, Makefile, `.gitignore`)
- [x] README.md

### Memory Engine
- [x] Full pipeline: ingest → split → chunk → stamp metadata → dedup → score → embed → store
- [x] Three-tier memory: working, short-term, long-term
- [x] Scoring: semantic similarity + recency (7-day half-life) + importance
- [x] 4 retrieval strategies (balanced, recency, importance, exact)
- [x] Context window budget (15% hard cap, priority-ranked)
- [x] Deduplication with similarity thresholds (>0.92 boost, 0.7–0.92 link, <0.7 novel)
- [x] Knowledge graph (`memory_links` table; relations: supersedes, related_to, contradicts, elaborates)
- [x] Knowledge cache (verified facts, no decay)
- [x] Turn processing pipeline (split, semantic chunking, bidirectional links)
- [x] Auto-tagging (domain, type, project, agent source)
- [x] Feedback-driven memory importance
- [x] Memory conflict resolution (supersede old, decay importance, transfer links)
- [x] Local embeddings (MiniLM-L6-v2) default, API optional

### Agent System
- [x] SQLite schema — memory tables, knowledge cache, message bus, projects
- [x] Agent protocol — SQLite message bus, `AgentMessage`, `BaseAgent`
- [x] LLM client — multi-provider (Anthropic, DeepSeek, Qwen, Google Gemini full; Kimi/MiniMax OpenAI-compat)
- [x] Sub-agent pools for parallel LLM calls
- [x] All 5 agents wired: Cortex 🧠, Builder 🔨, Researcher 🔬, Verifier ✅, Guardian 🛡️
- [x] Cortex (Brain) as main OpenClaw session
- [x] Session manager — `delegate()`, `delegate_parallel()` via OpenClaw sessions
- [x] Context scoping — each agent only sees what Cortex passes
- [x] Aider for Builder (git-aware code editing; supports DeepSeek V3.2, Gemini 2.5/3 Pro, Claude)

### Reliability
- [x] Error handling — retries with backoff, graceful degradation, context guard at 85%, DB recovery
- [x] Custom exceptions + retry utility

### Tests
- [x] Integration tests (83+)
- [x] Consolidation tests (14)
- [x] Project tests (29)
- [x] Graduation tests (10)
- [x] E2E install simulation test (26 checks)

---

## Phase 1.5: Project Mode & GitOps ✅

### Project Management
- [x] Idea backlog (casual ideas saved, promoted when ready)
- [x] Project → Feature → Task hierarchy
- [x] Domain tagging for projects
- [x] Spec writer (LLM-powered, research-backed via Researcher)
- [x] Task decomposer (features with nested tasks, agent assignments, dependencies)
- [x] Full collaboration pipeline: Researcher → Builder → Verifier (retry ×2) → Guardian scan → Cortex coherence → auto-commit

### GitOps (Free Tier)
- [x] Auto-commit on task completion
- [x] Pre-commit credential scanning (Guardian)
- [x] Rollback, status, log commands

### Maintenance & Reliability
- [x] Health check every 30 min with auto-restart
- [x] Memory backup daily, 7-day rotation
- [x] Log rotation weekly with metrics harvesting (`data/metrics.json`)
- [x] Consolidation cron (daily Full, weekly Standard) — clusters short-term → long-term summaries
- [x] Knowledge graduation (facts earn permanence: 0.8 → 0.95 → 1.0 via access + age)
- [x] Knowledge refresh (monthly passive flagging of stale facts for re-verification)

---

## Phase 2: Pro Tier 🔮

- [ ] Weekly strategic review (auto-generated summary of progress, blockers, velocity)
- [ ] Smart brief scheduling (learn when user is active, deliver at optimal time)
- [ ] Team digest (multi-user summary for collaborative projects)
- [ ] Cost reports in morning brief (LLM spend breakdown by agent/provider)
- [ ] Parallel task execution (Builder + Researcher simultaneously)
- [ ] Multiple concurrent projects with priority management
- [ ] Sprint planning with velocity tracking
- [ ] Dependency graph visualization
- [ ] Branch-per-feature with automated PR creation + Guardian review
- [ ] CI/CD pipeline (auto-test, auto-deploy on merge)
- [ ] War Room mode — agents discuss/debate in a visible group chat in real-time
- [ ] Smart model routing (cheap models for simple tasks, expensive for complex)
- [ ] Team analytics (agent performance, bottleneck detection, improvement tracking)
- [ ] One-command rollback with diff preview
- [ ] Multi-repo project management
- [ ] GitHub Actions integration
- [ ] Remote GitOps (push to VPS from GitHub)
- [ ] Custom code editing engine (model-agnostic, replaces Aider dependency)
  - Search/replace block parser (~50 lines, works with ANY LLM)
  - Tree-sitter repo mapping for intelligent context
  - Unlocks models not supported by Aider (Kimi K2.5, future models)
  - Zero external dependency for code editing
- [ ] Full model flexibility — any OpenAI-compatible or native API model for any agent
- [ ] Smart model routing v2 (auto-select based on task complexity + Arena/Aider benchmarks)
- [ ] Guardian Pro capabilities:
  - Dependency vulnerability audit (CVE database lookups)
  - License compliance checking (flag GPL/AGPL in MIT projects, etc.)
  - Attack surface review (endpoint exposure, auth gaps, input validation coverage)
  - Post-commit health checks with test runner integration (run tests after Guardian approves, auto-rollback on failure)
  - Memory sanitization (scan at write time, periodic sweep of existing memories, quarantine flagged content for human review)

---

## Future: Hardened Build 🐳

- [ ] Dockerfiles per agent
- [ ] Docker Compose orchestration
- [ ] Network isolation (sandbox for Builder, external for Researcher/Verifier)
- [ ] Resource limits per container (CPU, memory, disk)
- [ ] Optional Redis message bus (replaces SQLite for multi-container)
- [ ] Volume-based memory sharing with permissions
- [ ] Health checks and auto-restart per container

---

## Future: Plugin System 🔌

- [ ] Agent plugin spec (interface, manifest, permissions declaration)
- [ ] Plugin discovery and installation via wizard
- [ ] Sandboxed plugin execution
- [ ] Community plugin registry

---

## Future: Mission Control Frontend 🖥️

- [ ] Real-time agent activity dashboard
- [ ] Message bus inspector
- [ ] Memory browser and search
- [ ] Cost tracking charts
- [ ] Config editor with validation
- [ ] Project/feature/task board view
- [ ] Session management (start/stop/restart agents)

---

## Future: Model Fallback Chains ⛓️

- [ ] Primary → fallback → emergency model chain per agent
- [ ] Automatic failover on rate limit, timeout, or error
- [ ] Cost-aware routing
- [ ] Quality monitoring — detect degraded responses and escalate
- [ ] Provider health tracking
- [ ] Day-one support for new models (no waiting for Aider compatibility)
- [ ] Benchmark-aware model suggestions (auto-recommend based on latest Aider/Arena data)
