# Changelog — Ajentic Core

All notable changes to the Ajentic Core open-source repo.

**Repo:** [github.com/jasonwu-ai/ajentic](https://github.com/jasonwu-ai/ajentic)
**Cloud edition:** [github.com/jasonwu-ai/ajentic-cloud](https://github.com/jasonwu-ai/ajentic-cloud)

---

## [Unreleased]

### Changed
- **Branding update** — repo renamed from `cortex` / `jasonxwu2794/cortex` → `jasonwu-ai/ajentic`. GitHub URLs, install scripts, and all documentation updated.
- **License** — Apache 2.0 (previously listed as MIT in some places; Apache 2.0 was always the intended license)
- **README** — full rewrite: accurate feature list, product family table (Core / Cloud / Enterprise), correct GitHub links, Cloud comparison

---

## [0.2.0] — Phase 1.5: Project Mode & GitOps

### Added
- **Project Mode** — full idea → spec → feature → task pipeline
  - Idea backlog (`/idea drop <text>` captures casual ideas)
  - Spec writer (LLM-powered, research-backed via Researcher)
  - Task decomposer (features with nested tasks, agent assignments, dependencies)
  - Project → Feature → Task hierarchy with domain tagging
- **Full collaboration pipeline** — Researcher → Builder → Verifier (retry ×2) → Guardian scan → Cortex coherence review → auto-commit
- **GitOps (Free Tier)**
  - Auto-commit on task completion
  - Pre-commit credential scanning via Guardian
  - Rollback, status, and log commands
- **Knowledge graduation** — facts earn permanence: 0.8 → 0.95 → 1.0 via access count + age
- **Knowledge refresh** — monthly passive flagging of stale facts for re-verification

### Maintenance & Reliability
- Health check every 30min with auto-restart on failure
- Memory backup daily with 7-day rotation
- Log rotation weekly with metrics harvesting (`data/metrics.json`)
- Consolidation cron: daily (Full tier), weekly (Standard tier)

---

## [0.1.0] — Phase 1: Foundation

### Added
- **One-command installer** (`install.sh`) with interactive gum TUI wizard
  - 12 wizard steps: prereqs, OpenClaw install, config mode, user identity, tech stack, brain personality, model selection, API keys, memory setup, messaging, tools, deploy
  - Supports `--reconfigure` for updating settings
  - Generates all config files (`USER.md`, `TEAM.md`, `SOUL.md`, `openclaw.yaml`, etc.)

- **5-agent system**
  - 🧠 **Cortex** — orchestrator, main entry point, context scoping, memory gatekeeper
  - 🔨 **Builder** — code generation with Aider integration (git-aware)
  - 🔬 **Researcher** — parallel sub-agent web research, multi-source synthesis
  - 🔍 **Verifier** — claim verification, knowledge cache updates, QA
  - 🛡️ **Guardian** — security gate, credential scanning, injection defense, rollback decisions

- **Memory system** (full pipeline)
  - Three-tier memory: working / short-term / long-term
  - Local ONNX embeddings (MiniLM-L6-v2, ~80MB, free, private)
  - Scoring: semantic similarity + recency (7-day half-life) + importance
  - 4 retrieval strategies: balanced, recency, importance, exact
  - Context window budget (15% hard cap, priority-ranked)
  - Deduplication (>0.92 cosine → boost; 0.7–0.92 → link; <0.7 → novel)
  - Knowledge graph (`memory_links` table; relations: supersedes, related_to, contradicts, elaborates)
  - Knowledge cache (verified facts, no decay)
  - Turn processing pipeline (split, semantic chunking, bidirectional links)
  - Auto-tagging (domain, type, project, agent source)
  - Feedback-driven memory importance
  - Memory conflict resolution

- **Multi-provider LLM client**
  - Anthropic (Claude), DeepSeek, Qwen, Google Gemini, Kimi/Moonshot
  - Local models via Ollama/LM Studio (OpenAI-compatible)

- **SQLite message bus** — all inter-agent communication via SQLite tables
- **Sub-agent pools** — parallel LLM calls for Researcher and Builder
- **Context scoping** — each agent only receives the context it needs (token-efficient)
- **Prompt injection defense** — regex fast scan + LLM deep analysis two-layer system
- **Proactive automation**
  - Morning brief (`scripts/morning_brief.py`) — daily digest at 08:00
  - Idea surfacer (`scripts/idea_surfacer.py`) — weekly pattern analysis + suggestions

- **Test suite** — 160+ integration, unit, consolidation, graduation, and E2E install tests

### Supported Messaging Platforms
- Telegram (primary)
- Discord
- Signal
- CLI (no messaging platform required)
