# 🧠 Memory-Enhanced Multi-Agent System

> **Zero to AI agent team in one command. No config files. No PhD required.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-green.svg)]()
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)]()

---

## What Is This?

A team of 5 AI agents that live on your VPS, talk to you on Telegram, and **never forget anything**. One install command runs a beautiful setup wizard. Minutes later, you're chatting with Cortex — your personal AI chief of staff — backed by a Builder, Researcher, Verifier, and Guardian that work behind the scenes.

No Docker. No Redis. No YAML files. Just one SQLite database and a system that gets smarter every conversation.

---

## ✨ Features

| | Feature | Details |
|---|---------|---------|
| 🧠 | **5 Specialized Agents** | Cortex orchestrates, Builder codes, Researcher researches, Verifier verifies, Guardian protects |
| 💾 | **Advanced Memory System** | Importance scoring, semantic search, deduplication, automatic consolidation |
| 🧙 | **One-Command Installer** | Beautiful TUI wizard powered by [gum](https://github.com/charmbracelet/gum) — no config files to edit |
| 🔗 | **Knowledge Graph** | Memories link to related memories — "likes Python" connects to "builds ML pipelines" |
| 🤖 | **Multi-Provider AI** | Claude, DeepSeek, Qwen, Gemini, Kimi — mix and match per agent |
| 💬 | **Your Platform** | Telegram, Discord, Signal, or CLI |
| ⚙️ | **Re-runnable Wizard** | Change models, add integrations, tweak personality — anytime, no manual editing |
| 🛡️ | **Guardian Agent** | Credential scanning, breaking change detection, code conventions, rollback decisions |
| 🔄 | **Memory That Grows** | Knowledge cache of verified facts, auto-tagging, feedback-driven importance |
| 📋 | **Project Mode** | Idea backlog, spec writing, Feature→Task hierarchy |
| 🔨 | **Collaboration Pipeline** | Researcher→Builder→Verifier→Guardian→Cortex review chain |
| 🔧 | **GitOps** | Auto-commit, pre-commit security scanning, rollback |
| 💻 | **Tech Stack Aware** | Wizard asks your language/frameworks, Builder knows your stack |
| ✏️ | **Aider Integration** | Git-aware code editing for Builder |
| 👁️ | **Transparent Mode** | Optional verbose mode shows agent activity |
| 🏥 | **Self-Maintaining** | Health checks, auto-restart, backups, log rotation, metrics |
| 📈 | **Knowledge Graduation** | Facts earn permanence through use and time |
| 🔒 | **Prompt Injection Defense** | Pattern scanning, content tagging, system prompt hardening |
| ☀️ | **Morning Brief** | Daily digest of progress, queue, health — delivered to your platform |
| 💡 | **Auto Idea Surfacing** | Weekly pattern analysis suggests ideas for your backlog |

---

## 🖥️ VPS Setup

You'll need a cheap VPS to run this. Here's the easiest path:

1. **Get a VPS** — [Hostinger KVM 2](https://www.hostinger.com/vps-hosting) (~$6-12/mo) with **Ubuntu 22.04 or 24.04**, 2 vCPU, 8GB RAM. Pick the region closest to you.
2. **Open the terminal** — in your Hostinger dashboard, click your VPS → **Terminal** button. You're in.
3. **Update the OS** (fresh box housekeeping):
```bash
apt update && apt upgrade -y
```

**Have these ready before you start:**
- 🔑 An API key from at least one provider ([Anthropic](https://console.anthropic.com/settings/keys) or [DeepSeek](https://platform.deepseek.com/api_keys) recommended)
- 💬 A Telegram bot token (message [@BotFather](https://t.me/BotFather) on Telegram to create one) — or use Discord/Signal/CLI instead
- 🐙 A GitHub **classic** personal access token with `repo` scope — for GitOps auto-commit + backup ([create one here](https://github.com/settings/tokens/new?scopes=repo&description=cortex-workspace))
  > ⚠️ **Use a Classic token**, not fine-grained. Fine-grained tokens can't create new repos without extra config.

That's it. Now run the installer 👇

---

## 🚀 Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/jasonxwu2794/MemoryEnhancedMultiAgent/main/install.sh | bash
```

**What happens next:**

1. **Wizard launches** — a beautiful terminal UI walks you through setup
2. **Pick your style** — choose models, memory tier, messaging platform, and Cortex's personality
3. **Enter API keys** — wizard validates each one in real time
4. **Agents deploy** — Cortex says hello on your chosen platform:

```
Hey! 👋 I'm Cortex, your AI assistant. I'm all set up and ready to help
with your work. What would you like to start with?
```

That's it. You're talking to a 5-agent AI system with persistent memory.

---

## 🏗️ Architecture Overview

### The 5 Agents

| Agent | Role | What It Does |
|-------|------|-------------|
| 🧠 **Cortex** | Chief of Staff | Talks to you, classifies intent, delegates tasks, synthesizes responses |
| 🔨 **Builder** | Engineer | Generates code, runs tools, debugs — sandboxed, no internet access |
| 🔬 **Researcher** | Research & Synthesis | Searches the web, reads docs, synthesizes findings in parallel |
| ✅ **Verifier** | Quality Assurance | Verifies claims, catches hallucinations, updates the knowledge cache |
| 🛡️ **Guardian** | Quality + Security Gate | Credential scanning, breaking change detection, convention enforcement, rollback decisions |

### How They Work Together

```
         You
          │
          ▼
    ┌───────────┐
    │ 🧠 Cortex  │◄── Memory Engine (SQLite)
    └─────┬─────┘
          │ delegates
    ┌─────┼─────────────┐
    ▼     ▼     ▼       ▼
  🔨     🔬    ✅      🛡️
Builder Researcher Verifier Guardian
```

- Cortex is the **only agent you talk to** — it presents a unified experience
- Other agents are spawned on-demand as sub-sessions
- All communication flows through a **SQLite message bus**
- Each agent only sees the context it needs (token-efficient)

---

## 📋 How Projects Work

Projects turn ideas into shipped code through a structured pipeline:

1. **💡 Idea** — you drop an idea into the backlog (`/idea build a REST API`)
2. **📝 Spec** — promote an idea → Researcher gathers context → Cortex writes a spec → you approve
3. **🔀 Decompose** — spec breaks down into **Features**, each feature into **Tasks**
4. **🔨 Build loop** — for each task:
   - **Builder** writes the code (with Aider for git-aware edits)
   - **Verifier** validates correctness
   - **Guardian** runs security checks
   - **Cortex** reviews for coherence
   - **Auto-commit** on success
5. **📊 Track** — progress is tracked at every level (idea → feature → task)

---

## 🧠 Memory System

The memory system is what makes this project special. Your agents don't just respond — they **remember**.

### Memory Layers

| Tier | What | Decay |
|------|------|-------|
| **Working Memory** | Current conversation context | Ephemeral |
| **Short-term Memory** | Recent interactions with embeddings | 7-day half-life |
| **Long-term Memory** | Consolidated knowledge clusters | Very slow decay |
| **Knowledge Cache** | Verified facts from Verifier & Researcher | **No decay** |

### Scoring System

Every memory gets a composite score combining:
- **Semantic similarity** — how relevant is this to the current query?
- **Recency** — exponential decay with 7-day half-life
- **Importance** — user corrections score high, casual chat scores low

### Smart Features

- **🔗 Knowledge Graph** — memories link to related memories (`related_to`, `supersedes`, `contradicts`, `elaborates`)
- **📝 Auto-tagging** — domain, type, and project tags inferred automatically
- **🧹 Deduplication** — near-duplicates boost existing memories instead of creating clutter
- **🔄 Consolidation** — old short-term memories get clustered and summarized into long-term memory
- **👍 Feedback-driven** — "that's right" boosts importance, "that's outdated" decays it
- **🏠 Local embeddings** — MiniLM-L6-v2 via ONNX Runtime (~50MB, no PyTorch needed), free, private, ~95% quality of API models

---

## 🏥 Self-Maintaining

The system keeps itself healthy without babysitting:

| | What | Details |
|---|------|---------|
| 💓 | **Health Checks** | Every 30 minutes — monitors agents, memory, disk; auto-restarts on failure |
| 💾 | **Memory Backups** | Daily snapshots with 7-day rotation |
| 📊 | **Metrics Harvesting** | Weekly collection of usage stats, costs, memory growth |
| 📈 | **Knowledge Graduation** | Facts earn permanence through repeated use and time — from short-term → long-term → permanent |
| 🔄 | **Consolidation** | Short-term memories are periodically clustered into long-term summaries |
| 📜 | **Log Rotation** | Automatic cleanup so logs don't eat your disk |

---

## 🧙 Wizard Steps

The wizard walks you through everything. No config files. Re-run anytime with `./wizard.sh --reconfigure`.

1. **Prerequisites check** — Python, Node.js, git (installs what's missing)
2. **OpenClaw install** — sets up the agent runtime + systemd service
3. **Configuration mode** — ⚡ Recommended (defaults) or ⚙️ Custom (full control)
4. **About you** — name, domain, current work (personalizes all agents)
5. **Tech stack** — language, frameworks, tools
6. **Cortex's personality** — communication style, verbosity
7. **Model selection** — pick an LLM for each agent
8. **API keys** — guided entry with instant validation
9. **Memory tier** — Full / Standard + embedding choice
10. **Messaging platform** — Telegram, Discord, Signal, or CLI
11. **Tool selection** — web search, GitHub, file access, code execution
12. **Deploy** — generates configs, starts agents, Cortex says hello

---

## 📋 Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| **VPS** | 1 vCPU, 2GB RAM | 2+ vCPU, 8GB RAM |
| **Python** | 3.10+ | 3.11+ |
| **Node.js** | 18+ | 22+ |
| **git** | any | any |
| **Cost** | ~$5/mo VPS + ~$10/mo API | ~$15/mo VPS + ~$30/mo API |

You'll need an API key for at least one provider: [Anthropic](https://console.anthropic.com/settings/keys), [DeepSeek](https://platform.deepseek.com/api_keys), [Alibaba (Qwen)](https://dashscope.console.aliyun.com/apiKey), [Google (Gemini)](https://aistudio.google.com/apikey), or [Moonshot (Kimi)](https://platform.moonshot.cn/console/api-keys).

---

## 📁 Project Structure

```
MemoryEnhancedMultiAgent/
├── install.sh                    # Entry point — one curl, one command
├── Makefile                      # Dev commands (test, lint, install)
├── pyproject.toml                # Python project config
├── requirements.txt              # Production dependencies
├── wizard/
│   ├── wizard.sh                 # Main wizard entry point
│   ├── utils.sh                  # Shared TUI helpers
│   └── steps/                    # Wizard steps (01–12)
│       ├── 01_prerequisites.sh
│       ├── 04b_tech_stack.sh     # Language/framework selection
│       ├── 08_memory_setup.sh    # Memory tier + embeddings
│       ├── 11_deploy.sh          # Generate configs, start agents
│       └── ...
├── agents/
│   ├── session_manager.py        # Agent lifecycle & session routing
│   ├── common/                   # Shared: base_agent, llm_client, protocol, gitops, retry, content_tags
│   ├── brain/                    # 🧠 Cortex + project management
│   │   ├── brain.py              # Orchestrator
│   │   ├── project_manager.py    # Idea backlog, project tracking
│   │   ├── spec_writer.py        # Spec generation from ideas
│   │   └── task_decomposer.py    # Feature→Task breakdown
│   ├── builder/                  # 🔨 Code generation (+ Aider integration)
│   ├── researcher/               # 🔬 Web research & synthesis
│   ├── verifier/                 # ✅ Claim verification & QA
│   └── guardian/                 # 🛡️ Quality + security gatekeeper
├── memory/
│   ├── engine.py                 # Memory orchestration
│   ├── schemas.py                # Data models
│   ├── scoring.py                # Importance + recency scoring
│   ├── retrieval.py              # Layered search
│   ├── embeddings.py             # Local or API embeddings
│   ├── knowledge_cache.py        # Verified facts (no decay)
│   ├── dedup.py                  # Near-duplicate detection
│   ├── chunker.py                # Text chunking for long content
│   ├── consolidation.py          # Short-term → long-term summaries
│   ├── graduation.py             # Facts earn permanence over time
│   └── knowledge_refresh.py      # Periodic fact re-validation
├── scripts/
│   ├── health_check.sh           # Auto-restart on failure
│   ├── backup_memory.sh          # Daily memory snapshots
│   ├── rotate_logs.sh            # Log cleanup
│   ├── pre-commit                # Security scanning hook
│   ├── morning_brief.py          # Daily digest to messaging platform
│   └── idea_surfacer.py          # Weekly idea suggestions for backlog
├── tests/                        # Unit, integration, and e2e tests
└── docs/
    ├── ARCHITECTURE.md           # Deep technical design
    ├── ROADMAP.md                # What's planned
    └── WIZARD_SPEC.md            # Wizard design specification
```

---

## 🗺️ Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 1 — Quick Launch** | ✅ Done | OpenClaw sessions, SQLite, wizard — running on a $5 VPS |
| **Phase 1.5 — Project Mode & GitOps** | ✅ Done | Idea backlog, spec writing, Feature→Task pipeline, auto-commit, pre-commit hooks |
| **Pro Tier** | 📋 Planned | Advanced memory strategies, multi-project support |
| **Hardened Build** | 📋 Planned | Docker containers with network isolation per agent |
| **Plugin System** | 📋 Planned | Add custom agents without forking |
| **Mission Control** | 📋 Planned | Web UI for monitoring agents, memory, and costs |
| **Model Fallback Chains** | 📋 Planned | Auto-failover between providers |
| **Standalone Mode** | 📋 Planned | Pure Python gateway, web chat UI, no OpenClaw dependency |

---

## 🤝 Contributing

This project is in early development. Contributions welcome! Check [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the technical design and [ROADMAP.md](ROADMAP.md) for what's next.

1. Fork the repo
2. Create a feature branch
3. Submit a PR with a clear description

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with 🧠 by humans and agents working together
</p>
