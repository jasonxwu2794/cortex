# WIZARD_SPEC.md — Setup Wizard Design Specification

> Authored by T Builder 1 · February 2026
> Based on design discussion with Jason

---

## Overview

The wizard is the **primary onboarding experience** for the Memory-Enhanced Multi-Agent system. It transforms a bare VPS into a fully configured, personality-tuned, multi-agent AI assistant — without the user ever touching a YAML file.

### Design Principles

| Principle | Detail |
|-----------|--------|
| **Entry point** | `curl -fsSL https://raw.githubusercontent.com/jasonxwu2794/MemoryEnhancedMultiAgent/main/install.sh \| bash` |
| **TUI engine** | [gum](https://github.com/charmbracelet/gum) — beautiful, single binary (~5MB), worth the polish |
| **Re-runnable** | `./wizard.sh --reconfigure` — change anything, anytime, no manual config editing |
| **Target user** | Someone interested in AI agents, not deeply technical, running a $5–20/mo VPS |
| **Idempotent** | Safe to run multiple times; detects existing config and offers to update |

### Architecture

```
curl ... | bash
    └── install.sh
         ├── Downloads repo
         ├── Installs gum (if missing)
         └── Launches wizard.sh
              ├── Steps 1-4, 4b, 5-10: Interactive TUI
              └── Step 11: Generate configs & deploy
```

---

## Step 1: Prerequisites Check

**Purpose:** Ensure the system has everything needed before proceeding.

### Required Dependencies

| Dependency | Minimum Version | Notes |
|------------|----------------|-------|
| Python | 3.10+ | Core runtime |
| git | any | Repo management |
| curl | any | Downloads, API calls |
| Node.js | 18+ | OpenClaw runtime |
| gum | latest | TUI framework (auto-installed by `install.sh`) |

### Behavior

1. Check each dependency with version detection
2. Present results as a checklist (✅ / ❌)
3. For missing dependencies:
   - Show what will be installed
   - `gum confirm "Install missing dependencies?"` — proceed only with user consent
   - Use OS-appropriate package manager (`apt`, `dnf`, `pacman`)
4. Re-check after install; fail gracefully if anything still missing

### gum Components Used

- `gum spin` — progress spinner during checks
- `gum style` — formatted results table

---

## Step 2: OpenClaw Install

**Purpose:** Install and configure OpenClaw as the agent orchestration layer.

### Actions

1. `npm install -g openclaw`
2. `pip install aider-chat` — Aider is a **mandatory Builder tool** for git-aware code editing on existing codebases
3. Verify both: `openclaw --version` and `aider --version`
4. Create systemd service unit:
   ```
   [Unit]
   Description=OpenClaw Agent Gateway
   After=network.target

   [Service]
   Type=simple
   ExecStart=/usr/bin/openclaw gateway start
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
3. Enable and start the service
4. Verify the gateway is responding

### gum Components Used

- `gum spin` — installation progress
- Status confirmation with styled output

---

## Step 3: Configuration Mode

**Purpose:** Let the user decide how hands-on they want to be with setup.

### Options

| Mode | Description |
|------|-------------|
| ⚡ **Recommended** | Sensible defaults pre-filled. Walk through each step, tweak what you want. |
| ⚙️ **Custom** | Every field starts blank. Full control over every choice. |

### Behavior

- `gum choose` with descriptions
- **Recommended** pre-fills all subsequent steps with sensible defaults (Claude for Brain, DeepSeek for Builder, Standard memory, etc.)
- **Custom** leaves all fields blank — user chooses everything
- In both modes, every step is shown and editable — Recommended just saves time
- Choice is stored in config for `--reconfigure` awareness

---

## Step 4: About You (User Identity)

**Purpose:** Build the user profile that agents use for personalization and domain awareness.

### Prompts

| Field | Prompt | Example | Required |
|-------|--------|---------|----------|
| Name | "What's your name?" | Jason | Yes |
| Preferred name | "What should agents call you?" | Jase | Yes |
| Domain | "What's your domain or field?" | Machine Learning | Yes |
| Current work | "What are you currently working on?" | Building a multi-agent system | Optional |

### Generated Files

#### `USER.md`
Personal identity file — read by Brain agent in main sessions.

```markdown
# User Profile
- Name: Jason
- Call me: Jase
- Domain: Machine Learning
- Currently working on: Building a multi-agent system
```

#### `TEAM.md`
Shared domain context — read by **ALL** agents for domain awareness.

```markdown
# Team Context
## Domain
Machine Learning

## Current Focus
Building a multi-agent system

## User
- Name: Jason (Jase)
- Field: Machine Learning
```

> **Key distinction:** `USER.md` is personal (Brain only in main session). `TEAM.md` is shared (all agents, all sessions) for domain-relevant behavior without leaking personal details.

### gum Components Used

- `gum input` — text fields with placeholders
- `gum write` — multi-line "current work" field

---

## Step 4b: Tech Stack Preferences

**Purpose:** Capture the user's technology preferences so agents (especially Builder) default to the right language, frameworks, and tools.

### Prompts

| Field | Type | Options |
|-------|------|---------|
| Primary Language | Choose | Python, TypeScript/JS, Rust, Go, Java/Kotlin, Other |
| Frameworks | Multi-select (language-dependent) | Python: FastAPI, Django, Flask, PyTorch, LangChain; TS: Next.js, React, Express, Nest.js, Svelte; Rust: Actix, Axum, Tokio; Go: Gin, Echo, Fiber; Java: Spring Boot, Quarkus |
| Package Manager | Choose (language-dependent) | Python: pip, poetry, uv; TS: npm, pnpm, yarn, bun |
| Database | Choose | PostgreSQL, SQLite, MongoDB, MySQL, No preference |
| Other preferences | Free text (optional) | e.g. "prefer functional style", "always use Docker" |

### State Keys

All saved under `tech_stack.*`:
- `tech_stack.language`
- `tech_stack.frameworks`
- `tech_stack.package_manager`
- `tech_stack.database`
- `tech_stack.other`

### Generated Output

- Added to `TEAM.md` as a `## Tech Stack` section (shared with all agents)
- Added to Builder's `SOUL.md` as `## Tech Stack (from user preferences)` for default language/framework behavior

---

## Step 5: Brain Agent Personality

**Purpose:** Customize the user-facing agent's personality. Only Brain gets this — other agents maintain fixed professional personalities.

### Prompts

| Field | Type | Options / Default |
|-------|------|-------------------|
| Agent name | Text input | Default: "Brain" |
| Communication style | Choose | Casual / Professional / Balanced (default) |
| Verbosity | Choose | Concise / Detailed / Adaptive (default) |
| Personality notes | Free text (optional) | e.g. "be witty", "use humor", "talk like a pirate" |
| Agent transparency | Choose | Stealth (default) / Verbose |

### Verbose Mode

- **Stealth** (default): Brain presents unified responses without revealing agent coordination
- **Verbose**: Brain shows status messages when delegating (e.g. "🔨 Builder is working on that...") and notes which agent contributed to the response

Saved as `brain.verbose_mode` (`stealth` or `verbose`).

### SOUL.md Architecture — Two Layers

Brain's `SOUL.md` is generated with a clear separation:

```markdown
# SOUL.md — Brain 🧠

## === LOCKED LAYER (DO NOT MODIFY) ===
# These rules are system-critical and not user-configurable.

### Delegation Rules
- Route code tasks to Builder
- Route research to Researcher
- Route verification to Verifier
- Consult Guardian on safety-sensitive operations

### Context Scoping
- Read USER.md in main sessions only
- Read TEAM.md in all sessions
- Never share USER.md content in group contexts

### Memory Gating
- Write significant events to daily memory files
- Update MEMORY.md periodically with distilled learnings
- Never persist secrets unless explicitly asked

### Safety
- Never reveal internal agent coordination to users
- Never expose other agents' existence unprompted
- Present unified, single-assistant experience

### Response Synthesis
- Integrate sub-agent results into cohesive responses
- Attribute research findings naturally, not mechanically
- Maintain conversation continuity across delegations

## === CUSTOMIZABLE LAYER ===
# Generated by wizard. Re-run `./wizard.sh --reconfigure` to change.

### Identity
- Name: Brain
- Emoji: 🧠

### Tone
- Style: Balanced
- Verbosity: Adaptive

### Personality
- (user's free text notes here)
```

### Other Agents

Other agents do **NOT** get personality customization. They have fixed, professional `SOUL.md` files that:
- Define their specific role and capabilities
- Reference `TEAM.md` for domain awareness
- Maintain consistent, professional communication with Brain

---

## Step 6: Model Selection (Per Agent)

**Purpose:** Choose which LLM powers each agent. Defaults are set by the use case selection in Step 3.

### Agent Model Matrix

| Agent | Role | Recommended Models | Optimization |
|-------|------|--------------------|-------------|
| 🧠 **Brain** | Orchestrator, user-facing | Claude, Kimi, Qwen | Best reasoning, personality |
| 🔨 **Builder** | Code generation, execution | DeepSeek, Codestral | Fast + cheap for code |
| 🔬 **Researcher** (Researcher) | Research, synthesis | Qwen, Claude | Good at synthesis |
| ✅ **Verifier** (Verifier) | Verification, accuracy | Claude, Qwen | Precise, detail-oriented |
| 🛡️ **Guardian** | Security, safety review | Claude | Security-minded |

### Recommended Defaults

| Agent | Default Model |
|-------|--------------|
| Brain | Claude Sonnet 4 |
| Builder | DeepSeek |
| Researcher | Qwen Max |
| Verifier | Qwen Max |
| Guardian | Claude Sonnet 4 |

### Cost Estimates

Display approximate monthly costs per model choice (assuming moderate usage):

```
Model Selection — Brain 🧠

  Claude Sonnet 4   ~$15-30/mo  ████████░░  [Recommended]
  Kimi              ~$5-15/mo   █████░░░░░
  Qwen Max          ~$8-20/mo   ██████░░░░
  MiniMax           ~$5-12/mo   █████░░░░░
  Claude Opus 4     ~$40-80/mo  ██████████  [Premium]

  ↑↓ navigate  enter select  esc back
```

### gum Components Used

- `gum choose` — per-agent model selection
- `gum style` — cost estimate display
- Pre-selected defaults based on Step 3

---

## Step 7: API Keys

**Purpose:** Collect and validate only the API keys needed for the selected models.

### Behavior

1. Deduplicate: if Brain and Guardian both use Claude, ask for the Anthropic key once
2. For each required provider:
   - Show link to get the key (e.g. `https://console.anthropic.com/settings/keys`)
   - `gum input --password` for secure entry
   - **Validate immediately** with a lightweight API call
   - ✅ on success, ❌ with retry on failure
3. Store keys in OpenClaw's secure config (not in repo files)

### Provider Links

| Provider | Key URL |
|----------|---------|
| Anthropic (Claude) | `https://console.anthropic.com/settings/keys` |
| MiniMax | `https://www.minimaxi.com/platform` |
| DeepSeek | `https://platform.deepseek.com/api_keys` |
| Qwen (Alibaba) | `https://dashscope.console.aliyun.com/apiKey` |
| Moonshot (Kimi) | `https://platform.moonshot.cn/console/api-keys` |
| Mistral (Codestral) | `https://console.mistral.ai/api-keys` |

### gum Components Used

- `gum input --password` — masked key entry
- `gum spin` — validation spinner
- `gum style` — success/failure display

---

## Step 8: Memory Setup

**Purpose:** Configure how much context agents retain and recall.

### Tiers

| Tier | Description | Storage | Token Usage | Recall Quality |
|------|-------------|---------|-------------|----------------|
| 📚 **Full** | Everything — daily logs, long-term memory, cross-session recall | ~50-200MB/mo | Higher | Best |
| 📝 **Standard** | Balanced — daily logs, curated long-term memory | ~10-50MB/mo | Moderate | Good |
| 📌 **Minimal** | Essentials — key decisions and active context only | ~1-10MB/mo | Low | Basic |

### Embeddings

After tier selection, ask how to generate embeddings:

| Option | Description |
|--------|-------------|
| 🏠 **Local (free, private)** [Recommended] | MiniLM-L6-v2 (~80MB, runs on CPU). ~95% quality of API models. No API calls, no cost, data stays local. |
| ☁️ **API (slightly better, costs per call)** | OpenAI, Voyage, or Cohere embeddings. Maximum quality. Requires API key, costs per call. |

Default: **Local**. Wizard downloads MiniLM model during setup if selected.

### Behavior

- `gum choose` with trade-off descriptions
- Default set by Step 3 use case
- Configures memory retention policies, cleanup schedules, context window allocation, and embedding provider

---

## Step 9: Messaging Integration

**Purpose:** Connect the agent system to a communication platform.

### Options

| Platform | Setup Required |
|----------|---------------|
| 💬 **Telegram** | Create bot via @BotFather, provide token |
| 🎮 **Discord** | Create bot in Developer Portal, provide token + guild ID |
| 📱 **Signal** | Link signal-cli to phone number |
| 🖥️ **CLI only** | No setup — interact via terminal |

### Guided Setup Flow (Example: Telegram)

```
Telegram Bot Setup

  1. Open Telegram and message @BotFather
  2. Send /newbot and follow the prompts
  3. Copy the API token

  🔗 Open: https://t.me/BotFather

  Paste your bot token:
  ▋ _______________________________________________

  ⏳ Validating...
  ✅ Connected! Bot name: @YourAgentBot
```

### gum Components Used

- `gum choose` — platform selection
- `gum style` — step-by-step instructions
- `gum input --password` — token entry
- `gum spin` — validation

---

## Step 10: Tool Selection

**Purpose:** Enable/disable tools available to agents.

### Available Tools

| Tool | Description | Default by Use Case |
|------|-------------|---------------------|
| 🔍 **Web Search** | Brave Search API | All |
| 🐙 **GitHub** | Repo management, PRs, issues | Coding |
| 📁 **File Access** | Read/write workspace files | All |
| ⚡ **Code Execution** | Run code in sandboxed environment | Coding |
| 🌐 **Web Fetch** | Scrape and extract web content | Research |
| 📧 **Email** | Send/read emails (future) | General |

### Behavior

- Show use-case defaults as pre-selected toggles
- User can toggle each on/off
- Tools requiring additional API keys prompt for them
- `gum choose --no-limit` for multi-select

---

## Step 11: Generate & Deploy

**Purpose:** Take all wizard choices and produce a running system.

### Generated Artifacts

| File | Content |
|------|---------|
| `USER.md` | User identity (from Step 4) |
| `TEAM.md` | Shared domain context (from Step 4) |
| `agents/brain/SOUL.md` | Brain personality with locked + custom layers (from Step 5) |
| `agents/brain/config.yaml` | Brain agent config — model, tools, channel |
| `agents/builder/SOUL.md` | Builder role definition (fixed) |
| `agents/builder/config.yaml` | Builder agent config |
| `agents/researcher/SOUL.md` | Researcher/Researcher role definition (fixed) |
| `agents/researcher/config.yaml` | Researcher agent config |
| `agents/verifier/SOUL.md` | Verifier role definition (fixed) |
| `agents/verifier/config.yaml` | Verifier agent config |
| `agents/guardian/SOUL.md` | Guardian role definition (fixed) |
| `agents/guardian/config.yaml` | Guardian agent config |
| `openclaw.yaml` | Main OpenClaw gateway config |
| `.wizard-state.json` | Wizard state for `--reconfigure` |

### Deployment Sequence

1. Write all config files
2. Restart OpenClaw gateway (`systemctl restart openclaw`)
3. Start Brain agent
4. Brain sends **first message** on chosen platform:
   ```
   Hey Jase! 👋 I'm Brain, your AI assistant. I'm all set up and ready to help
   with your Machine Learning work. What would you like to start with?
   ```
5. Other agents (Builder, Researcher, Verifier, Guardian) are configured but **dormant** — they only spawn when Brain delegates to them

### gum Components Used

- `gum spin` — config generation progress
- `gum style` — deployment summary
- Final success banner with next steps

---

## Agent Identity Defaults

These are pre-set and not wizard-configurable (keeping the wizard focused):

| Agent | Emoji | Default Name | Role |
|-------|-------|-------------|------|
| 🧠 | Brain | Brain | Orchestrator, user-facing |
| 🔨 | Builder | Builder | Code generation, execution |
| 🔬 | Researcher | Researcher | Research, web synthesis |
| ✅ | Verifier | Verifier | Fact verification, accuracy |
| 🛡️ | Guardian | Guardian | Security review, safety |

> Only Brain's name is customizable (Step 5). Other agents use fixed identities.

---

## Reconfiguration Mode

Running `./wizard.sh --reconfigure`:

1. Loads `.wizard-state.json` with previous choices
2. Shows current config as defaults
3. User can skip through unchanged steps or modify any step
4. Only regenerates files for changed settings
5. Restarts affected services

### State File (`.wizard-state.json`)

```json
{
  "version": 1,
  "timestamp": "2026-02-13T02:30:00Z",
  "config_mode": "recommended",
  "user": {
    "name": "Jason",
    "preferred_name": "Jase",
    "domain": "Machine Learning",
    "current_work": "Building a multi-agent system"
  },
  "brain": {
    "name": "Brain",
    "style": "balanced",
    "verbosity": "adaptive",
    "personality_notes": "",
    "verbose_mode": "stealth"
  },
  "tech_stack": {
    "language": "python",
    "frameworks": "FastAPI,PyTorch",
    "package_manager": "poetry",
    "database": "PostgreSQL",
    "other": "prefer functional style"
  },
  "models": {
    "brain": "claude-sonnet-4",
    "builder": "deepseek-v3",
    "researcher": "qwen-max",
    "verifier": "qwen-max",
    "guardian": "claude-sonnet-4"
  },
  "memory_tier": "full",
  "messaging": "telegram",
  "tools": ["web_search", "github", "file_access", "code_execution"]
}
```

---

## Implementation Notes

### Why gum?

- Single binary, ~5MB, no dependencies
- Beautiful defaults — spinners, confirmations, styled text
- Cross-platform (Linux, macOS)
- Perfect for the "polished but not over-engineered" feel
- Alternative considered: whiptail/dialog — functional but ugly

### Error Handling

- Every step validates before proceeding
- Network failures retry with exponential backoff
- API key validation catches invalid keys early
- Partial completion saves state — resume on next run

### Security

- API keys stored via OpenClaw's secure config, never in plain-text repo files
- `.wizard-state.json` excluded from git (`.gitignore`)
- Tokens entered with masked input (`gum input --password`)
- `install.sh` verifies HTTPS and checksums where possible
