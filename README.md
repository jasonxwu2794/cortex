# 🧠 Memory-Enhanced Multi-Agent System

> **Zero to AI agent team in one command. No config files. No PhD required.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-green.svg)]()
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)]()

---

## What Is This?

A team of 5 AI agents that live on your VPS, talk to you on Telegram, and **never forget anything**. One install command runs a beautiful setup wizard. Minutes later, you're chatting with Brain — your personal AI chief of staff — backed by a Builder, Scout, Checker, and Guardian that work behind the scenes.

No Docker. No Redis. No YAML files. Just one SQLite database and a system that gets smarter every conversation.

---

## ✨ Features

| | Feature | Details |
|---|---------|---------|
| 🧠 | **5 Specialized Agents** | Brain orchestrates, Builder codes, Scout researches, Checker verifies, Guardian protects |
| 💾 | **Advanced Memory System** | Importance scoring, semantic search, deduplication, automatic consolidation |
| 🧙 | **One-Command Installer** | Beautiful TUI wizard powered by [gum](https://github.com/charmbracelet/gum) — no config files to edit |
| 🔗 | **Knowledge Graph** | Memories link to related memories — "likes Python" connects to "builds ML pipelines" |
| 🤖 | **Multi-Provider AI** | Claude, DeepSeek, Qwen, MiniMax, Kimi, Codestral — mix and match per agent |
| 💬 | **Your Platform** | Telegram, Discord, Signal, or CLI |
| ⚙️ | **Re-runnable Wizard** | Change models, add integrations, tweak personality — anytime, no manual editing |
| 🛡️ | **Guardian Agent** | Monitors security, validates configs, tracks costs |
| 🔄 | **Memory That Grows** | Knowledge cache of verified facts, auto-tagging, feedback-driven importance |

---

## 🚀 Quick Start

```bash
curl -fsSL https://raw.githubusercontent.com/jasonxwu2794/MemoryEnhancedMultiAgent/main/install.sh | bash
```

**What happens next:**

1. **Wizard launches** — a beautiful terminal UI walks you through setup
2. **Pick your style** — choose models, memory tier, messaging platform, and Brain's personality
3. **Enter API keys** — wizard validates each one in real time
4. **Agents deploy** — Brain says hello on your chosen platform:

```
Hey! 👋 I'm Brain, your AI assistant. I'm all set up and ready to help
with your work. What would you like to start with?
```

That's it. You're talking to a 5-agent AI system with persistent memory.

---

## 🏗️ Architecture Overview

### The 5 Agents

| Agent | Role | What It Does |
|-------|------|-------------|
| 🧠 **Brain** | Chief of Staff | Talks to you, classifies intent, delegates tasks, synthesizes responses |
| 🔨 **Builder** | Engineer | Generates code, runs tools, debugs — sandboxed, no internet access |
| 🔬 **Scout** | Researcher | Searches the web, reads docs, synthesizes findings in parallel |
| ✅ **Checker** | Fact Checker | Verifies claims, catches hallucinations, updates the knowledge cache |
| 🛡️ **Guardian** | Security Lead | Reviews Builder output, monitors costs, blocks unsafe actions |

### How They Work Together

```
         You
          │
          ▼
    ┌───────────┐
    │  🧠 Brain  │◄── Memory Engine (SQLite)
    └─────┬─────┘
          │ delegates
    ┌─────┼─────────────┐
    ▼     ▼     ▼       ▼
  🔨     🔬    ✅      🛡️
Builder Scout Checker Guardian
```

- Brain is the **only agent you talk to** — it presents a unified experience
- Other agents are spawned on-demand as sub-sessions
- All communication flows through a **SQLite message bus**
- Each agent only sees the context it needs (token-efficient)

---

## 🧠 Memory System

The memory system is what makes this project special. Your agents don't just respond — they **remember**.

### Three Tiers + Knowledge Cache

| Tier | What | Decay |
|------|------|-------|
| **Working Memory** | Current conversation context | Ephemeral |
| **Short-term Memory** | Recent interactions with embeddings | 7-day half-life |
| **Long-term Memory** | Consolidated knowledge clusters | Very slow decay |
| **Knowledge Cache** | Verified facts from Checker & Scout | **No decay** |

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
- **🏠 Local embeddings** — MiniLM-L6-v2 runs on CPU, free, private, ~95% quality of API models

---

## 🧙 Wizard Steps

The wizard walks you through everything. No config files. Re-run anytime with `./wizard.sh --reconfigure`.

1. **Prerequisites check** — Python, Node.js, git (installs what's missing)
2. **OpenClaw install** — sets up the agent runtime + systemd service
3. **Configuration mode** — ⚡ Recommended (defaults) or ⚙️ Custom (full control)
4. **About you** — name, domain, current work (personalizes all agents)
5. **Brain's personality** — communication style, verbosity, custom notes
6. **Model selection** — pick an LLM for each agent with cost estimates
7. **API keys** — guided entry with instant validation
8. **Memory tier** — Full / Standard / Minimal + embedding choice
9. **Messaging platform** — Telegram, Discord, Signal, or CLI
10. **Tool selection** — web search, GitHub, file access, code execution
11. **Deploy** — generates configs, starts agents, Brain says hello

---

## 📋 Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| **VPS** | 1 vCPU, 2GB RAM | 2+ vCPU, 8GB RAM |
| **Python** | 3.10+ | 3.11+ |
| **Node.js** | 18+ | 22+ |
| **git** | any | any |
| **Cost** | ~$5/mo VPS + ~$10/mo API | ~$15/mo VPS + ~$30/mo API |

You'll need an API key for at least one provider: [Anthropic](https://console.anthropic.com/settings/keys), [DeepSeek](https://platform.deepseek.com/api_keys), [Alibaba (Qwen)](https://dashscope.console.aliyun.com/apiKey), [MiniMax](https://www.minimaxi.com/platform), [Moonshot (Kimi)](https://platform.moonshot.cn/console/api-keys), or [Mistral](https://console.mistral.ai/api-keys).

---

## 📁 Project Structure

```
MemoryEnhancedMultiAgent/
├── install.sh                  # Entry point — one curl, one command
├── wizard/
│   ├── tui.sh                  # Main wizard (gum TUI)
│   ├── steps/                  # Individual wizard steps (01-11)
│   ├── templates/              # Jinja2 config templates
│   └── generate_configs.sh
├── agents/
│   ├── common/                 # Shared interface, protocol, LLM client
│   ├── brain/                  # 🧠 Orchestrator
│   ├── builder/                # 🔨 Code & tools
│   ├── researcher/             # 🔬 Scout
│   ├── fact_checker/           # ✅ Checker
│   └── guardian/               # 🛡️ Security & costs
├── memory/
│   ├── engine.py               # Memory orchestration
│   ├── sqlite_store.py         # Vector + structured storage
│   ├── scored_memory.py        # Importance + recency scoring
│   ├── knowledge_cache.py      # Verified facts (no decay)
│   ├── embeddings.py           # Local or API embeddings
│   ├── consolidation.py        # Background memory maintenance
│   └── retrieval.py            # Layered search
├── configs/
│   ├── base/                   # Default configs
│   ├── overlays/               # Use-case presets
│   └── user/                   # Your overrides (gitignored)
├── tools/                      # Tool registry + installers
├── ARCHITECTURE.md             # Deep technical design
├── ROADMAP.md                  # What's planned
└── WIZARD_SPEC.md              # Wizard design specification
```

---

## 🗺️ Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| **Quick Launch** | 🔨 In Progress | OpenClaw sessions, SQLite, wizard — running on a $5 VPS |
| **Hardened Build** | 📋 Planned | Docker containers with network isolation per agent |
| **Plugin System** | 📋 Planned | Add custom agents without forking |
| **Mission Control** | 📋 Planned | Web UI for monitoring agents, memory, and costs |
| **Model Fallback Chains** | 📋 Planned | Auto-failover between providers |

---

## 🤝 Contributing

This project is in early development. Contributions welcome! Check [ARCHITECTURE.md](ARCHITECTURE.md) for the technical design and [ROADMAP.md](ROADMAP.md) for what's next.

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
