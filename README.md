# Ajentic — Core (Open Source)

> **A self-hosted, single-user AI agent system with persistent memory — zero to running in one command.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-jasonwu--ai%2Fajentic-black?logo=github)](https://github.com/jasonwu-ai/ajentic)

---

## What Is Ajentic Core?

Ajentic is a personal AI assistant platform. **This repo is the open-source, self-hosted, single-user edition** — designed to run on a cheap VPS or your own machine, powered by your own API keys (or local models).

You get a team of 5 AI agents that talk to you on Telegram, **remember everything**, write code, research the web, verify facts, and keep themselves secure — all backed by a local SQLite database. No Docker. No Redis. No YAML files.

One install command launches a wizard. Minutes later, Cortex says hello.

---

## Product Family

Ajentic comes in three tiers:

| | **Core** (this repo) | **Cloud** | **Enterprise** |
|---|---|---|---|
| **What it is** | Open source, self-hosted, single user | Managed SaaS, multi-user, full features | Self-hosted teams, all Cloud features on-premise |
| **Repo** | [jasonwu-ai/ajentic](https://github.com/jasonwu-ai/ajentic) | [jasonwu-ai/ajentic-cloud](https://github.com/jasonwu-ai/ajentic-cloud) | Planned |
| **License** | Apache 2.0 | Proprietary SaaS | Paid |
| **Price** | Free (BYOK) | From $39/mo | Contact |
| **Multi-agent orchestration** | ✅ | ✅ | ✅ |
| **Semantic memory** | ✅ | ✅ | ✅ |
| **Web search, browser, code exec** | ✅ | ✅ | ✅ |
| **GitOps pipeline** | ✅ | ✅ | ✅ |
| **Project mode (ideas → tasks)** | ✅ | ✅ | ✅ |
| **Morning brief & scheduling** | ✅ | ✅ | ✅ |
| **War Room debates** | ✅ | ✅ | ✅ |
| **Multi-user & auth** | ❌ | ✅ | ✅ |
| **Web dashboard** | ❌ | ✅ | ✅ |
| **Team Chat (multi-bot groups)** | ❌ | ✅ | ✅ |
| **Email & Calendar plugins** | ❌ | ✅ | ✅ |
| **Finance, Trends, Sentiment plugins** | ❌ | ✅ | ✅ |
| **Docker sandbox** | ❌ | ✅ | ✅ |
| **Stripe billing & metering** | ❌ | ✅ | ❌ |
| **Managed hosting** | ❌ | ✅ | ❌ |

→ **Try Cloud:** [app.jasonwu.ai](https://app.jasonwu.ai) · [@AjenticCortex_bot](https://t.me/AjenticCortex_bot)

---

## Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/jasonwu-ai/ajentic/main/install.sh | bash
```

The interactive setup wizard walks you through:
1. Prerequisites check
2. Your identity and tech stack
3. API keys (or local model setup via Ollama/LM Studio)
4. Model selection per agent
5. Telegram bot setup (or CLI-only mode)
6. Tool selection (web search, GitHub, file access, code execution)
7. Deploy — Cortex says hello

Supports `--reconfigure` to update any setting later.

**Zero-API-key setup** — run entirely on local models (Ollama, LM Studio) with no cloud provider required.

---

## Features

| | Feature | Details |
|---|---------|---------|
| 🧠 | **5 Specialist Agents** | Cortex orchestrates, Builder codes, Researcher researches, Verifier verifies, Guardian protects |
| 💾 | **Semantic Memory** | ONNX embeddings (MiniLM-L6-v2), SQLite, three-tier memory with knowledge graph |
| 🔗 | **Knowledge Graph** | Memories link to related memories — entity co-occurrence, relationship tracking |
| 🔄 | **Memory That Grows** | Verified fact cache, auto-tagging, feedback-driven importance, consolidation |
| 🧙 | **One-Command Installer** | Beautiful TUI wizard powered by [gum](https://github.com/charmbracelet/gum) — no config files |
| ⚙️ | **Re-runnable Wizard** | Change models, add integrations, tweak personality — anytime with `--reconfigure` |
| 🔍 | **Web Search** | Tiered: Tavily → SearXNG → DuckDuckGo (zero-config fallback) |
| 🌐 | **Browser Automation** | Playwright-based: navigate, screenshot, click, type, eval |
| 💻 | **Code Execution** | Sandboxed shell execution with process management |
| 🔨 | **Builder Work Loop** | PLAN→ACT→OBSERVE→DECIDE cycle with auto-verification and pre-commit scanning |
| 🔧 | **GitOps** | Auto-commit, pre-commit credential scanning, rollback |
| 📋 | **Project Mode** | Idea backlog, spec writing, Feature→Task hierarchy, sprint management |
| 📊 | **5 AI Providers** | Anthropic, OpenAI, Google Gemini, DeepSeek, Kimi — mix and match per agent |
| 🏠 | **Local Models** | Ollama, LM Studio, or any OpenAI-compatible endpoint — zero API cost |
| 🛡️ | **Security** | Prompt injection defense (regex + LLM two-layer), credential scanning, PII sanitization |
| ☀️ | **Morning Brief** | Daily digest of goals, ideas, memory stats — delivered to Telegram |
| 🏥 | **Self-Maintaining** | Health checks every 30min, auto-restart, memory backups, log rotation |
| 💬 | **Multi-Platform** | Telegram, Discord, Signal, or CLI |

---

## The 5 Agents

| Agent | Role | What It Does |
|-------|------|-------------|
| 🧠 **Cortex** | Chief of Staff | Talks to you, routes tasks, delegates, synthesizes — the only agent you interact with directly |
| 🔨 **Builder** | Engineer | Code generation, file editing, git operations, debugging, work loop with auto-verification |
| 🔬 **Researcher** | Research & Synthesis | Live web search, URL fetching, multi-source synthesis, parallel sub-agent threads |
| 🔍 **Verifier** | QA & Fact-Checking | Claim verification, knowledge cache updates, builder output QA, correction surfacing |
| 🛡️ **Guardian** | Security Gate | Credential scanning, injection defense, breaking change detection, rollback decisions |

---

## Memory System

Three-tier memory with a scoring engine:

| Tier | What | Decay |
|------|------|-------|
| **Working Memory** | Current conversation context | Ephemeral |
| **Short-term Memory** | Recent interactions with embeddings | 7-day half-life |
| **Long-term Memory** | Consolidated knowledge clusters | Very slow decay |
| **Knowledge Cache** | Verified facts (Verifier + Researcher) | No decay |

Every memory gets a composite score: **semantic similarity × recency × importance**. Smart retrieval fits the top results within a 15% context window budget — nothing overflows.

Features: knowledge graph links, auto-tagging, deduplication (>0.92 cosine → boost instead of duplicate), conflict resolution, feedback-driven importance, consolidation cron jobs.

---

## Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| **VPS** | 1 vCPU, 2GB RAM | 2+ vCPU, 8GB RAM (~$6-12/mo on Hostinger/Hetzner) |
| **Python** | 3.10+ | 3.12+ |
| **Node.js** | 18+ | 22+ |
| **API keys** | At least one provider | Anthropic recommended |

**Cheapest setup:** Hetzner CAX11 (~€4/mo) + DeepSeek API (~$5/mo) = ~$9/mo total.

**Free setup:** Any machine + Ollama (local models) = $0/mo.

---

## Supported Models

| Provider | Notes |
|----------|-------|
| **Anthropic** | Claude Opus, Sonnet — recommended for Cortex/Guardian |
| **OpenAI** | GPT-4o, o1, o3 series |
| **Google** | Gemini 2.5 Pro/Flash |
| **DeepSeek** | Great for Builder — fast and cheap |
| **Kimi / Moonshot** | K2.5 — strong reasoning, low cost |
| **Groq** | Via OpenAI-compatible API |
| **Local (Ollama)** | qwen3, deepseek-r1, gemma3, phi4, any Ollama model |

---

## Project Structure

```
ajentic/
├── install.sh                  # Entry point — one curl, one command
├── wizard/
│   ├── wizard.sh               # Main wizard entry point (gum TUI)
│   └── steps/                  # Wizard steps (01–12)
├── agents/
│   ├── common/                 # Shared: base_agent, llm_client, protocol
│   ├── brain/                  # 🧠 Cortex — orchestrator + project management
│   ├── builder/                # 🔨 Code generation + Aider integration
│   ├── researcher/             # 🔬 Web research & synthesis
│   ├── verifier/               # 🔍 Claim verification & QA
│   └── guardian/               # 🛡️ Quality + security gatekeeper
├── memory/
│   ├── engine.py               # Memory orchestration
│   ├── knowledge_cache.py      # Verified facts (no decay)
│   ├── embeddings.py           # Local ONNX or API embeddings
│   ├── consolidation.py        # Background memory maintenance
│   └── retrieval.py            # Layered semantic search
├── scripts/
│   ├── morning_brief.py        # Daily digest delivery
│   ├── idea_surfacer.py        # Weekly idea suggestions
│   └── health_check.sh         # Auto-restart on failure
├── docs/
│   ├── ARCHITECTURE.md         # Deep technical design
│   ├── ROADMAP.md              # What's planned
│   └── WIZARD_SPEC.md          # Wizard design specification
└── tests/                      # 160+ integration, unit, and e2e tests
```

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1 — Foundation** | ✅ Done | Wizard, 5 agents, SQLite memory, knowledge graph, GitOps |
| **Phase 1.5 — Project Mode** | ✅ Done | Idea backlog, spec writing, Feature→Task pipeline, auto-commit |
| **Phase 2 — Pro Tier** | 🔮 Planned | Smart model routing, sprint velocity, branch-per-feature, CI/CD hooks |
| **Standalone Mode** | 🔮 Planned | Pure Python gateway — no Node.js dependency, built-in web chat |
| **Plugin System** | 🔮 Planned | Custom agents without forking |
| **Mission Control** | 🔮 Planned | Web UI for memory browser, agent activity, cost charts |

Many advanced features (email/calendar plugins, Team Chat, web dashboard, Docker sandbox, multi-user, billing) are available today in **[Ajentic Cloud](https://github.com/jasonwu-ai/ajentic-cloud)**. Core focuses on the best possible self-hosted, single-user experience.

→ **Full roadmap:** [docs/ROADMAP.md](docs/ROADMAP.md)

---

## Contributing

Apache 2.0 — contributions welcome!

1. Fork [jasonwu-ai/ajentic](https://github.com/jasonwu-ai/ajentic)
2. Create a feature branch
3. Submit a PR with a clear description

Good first areas: new tools, memory improvements, new channel adapters, documentation, local model integrations.

---

## Links

- **Core (this repo):** [github.com/jasonwu-ai/ajentic](https://github.com/jasonwu-ai/ajentic) — Apache 2.0
- **Cloud (full-featured SaaS):** [app.jasonwu.ai](https://app.jasonwu.ai) · [github.com/jasonwu-ai/ajentic-cloud](https://github.com/jasonwu-ai/ajentic-cloud)
- **Telegram bot:** [@AjenticCortex_bot](https://t.me/AjenticCortex_bot)
- **Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Roadmap:** [docs/ROADMAP.md](docs/ROADMAP.md)

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with 🧠 by humans and agents working together
</p>
