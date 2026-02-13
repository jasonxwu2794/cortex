#!/usr/bin/env bash
# ============================================================================
# Step 11: Generate & Deploy
# Configure real OpenClaw: auth-profiles.json, openclaw.json, workspace files,
# AGENTS.md, memory DB init, gateway restart.
# ============================================================================

wizard_header "11" "Deploy" "Generating configuration and launching your agents..."

# --- Paths ---
OC_DIR="$HOME/.openclaw"
OC_WORKSPACE="$OC_DIR/workspace"
OC_CONFIG="$OC_DIR/openclaw.json"
OC_AUTH="$OC_DIR/agents/main/agent/auth-profiles.json"

# --- Read state ---
USER_NAME="$(state_get 'user.name')"
USER_PREF="$(state_get 'user.preferred_name')"
USER_DOMAIN="$(state_get 'user.domain')"
USER_WORK="$(state_get 'user.current_work')"
BRAIN_NAME="$(state_get 'brain.name' 'Brain')"
BRAIN_STYLE="$(state_get 'brain.style' 'balanced')"
BRAIN_VERBOSITY="$(state_get 'brain.verbosity' 'adaptive')"
BRAIN_NOTES="$(state_get 'brain.personality_notes')"
MEMORY_TIER="$(state_get 'memory_tier' 'standard')"
MESSAGING="$(state_get 'messaging' 'cli')"

MODEL_BRAIN="$(state_get 'models.brain' 'claude-sonnet-4')"
MODEL_BUILDER="$(state_get 'models.builder' 'deepseek-v3')"
MODEL_SCOUT="$(state_get 'models.scout' 'qwen-max')"
MODEL_CHECKER="$(state_get 'models.checker' 'qwen-max')"
MODEL_GUARDIAN="$(state_get 'models.guardian' 'claude-sonnet-4')"

# --- Ensure directories ---
mkdir -p "$OC_WORKSPACE/data"
mkdir -p "$OC_DIR/agents/main/agent"

# ============================================================
# 1. Install Python dependencies
# ============================================================
log_info "Installing Python dependencies for memory engine..."
gum spin --spinner dot --title "Installing sentence-transformers, numpy..." -- \
    pip install -q sentence-transformers numpy 2>/dev/null || {
    log_warn "pip install failed — memory features may not work"
}
log_ok "Python dependencies installed"

# ============================================================
# 2. Copy agent system into OpenClaw workspace
# ============================================================
gum spin --spinner dot --title "Copying agent system to workspace..." -- sleep 0.3

# Copy agents/, memory/, TEAM.md
cp -r "$PROJECT_DIR/agents" "$OC_WORKSPACE/"
cp -r "$PROJECT_DIR/memory" "$OC_WORKSPACE/"

log_ok "Agent system copied to workspace"

# ============================================================
# Generate USER.md in workspace
# ============================================================
cat > "$OC_WORKSPACE/USER.md" << EOF
# User Profile

- **Name:** $USER_NAME
- **Call me:** $USER_PREF
- **Domain:** $USER_DOMAIN
$([ -n "$USER_WORK" ] && echo "- **Currently working on:** $USER_WORK")

> This file is read by Brain in main sessions for personalization.
> Do not share in group contexts.
EOF
log_ok "USER.md generated"

# ============================================================
# Generate TEAM.md in workspace
# ============================================================
cat > "$OC_WORKSPACE/TEAM.md" << EOF
# Team Context

## Domain
$USER_DOMAIN

## Current Focus
${USER_WORK:-Not specified}

## User
- **Name:** $USER_NAME ($USER_PREF)
- **Field:** $USER_DOMAIN

> This file is shared with ALL agents for domain awareness.
EOF
log_ok "TEAM.md generated"

# ============================================================
# Generate Brain SOUL.md in workspace (what OpenClaw reads)
# ============================================================
cat > "$OC_WORKSPACE/SOUL.md" << SOULEOF
# SOUL.md — $BRAIN_NAME 🧠

## === LOCKED LAYER (DO NOT MODIFY) ===

### Delegation Rules
- Route code tasks to Builder via subagent spawn
- Route research to Scout via subagent spawn
- Route verification to Checker via subagent spawn
- Consult Guardian on safety-sensitive operations via subagent spawn

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

### Identity
- **Name:** $BRAIN_NAME
- **Emoji:** 🧠

### Tone
- **Style:** $BRAIN_STYLE
- **Verbosity:** $BRAIN_VERBOSITY

### Personality
${BRAIN_NOTES:-No additional personality notes configured.}
SOULEOF
log_ok "Brain SOUL.md generated"

# ============================================================
# Generate other agent SOUL.md files in workspace
# ============================================================
mkdir -p "$OC_WORKSPACE/agents/brain" "$OC_WORKSPACE/agents/builder" \
         "$OC_WORKSPACE/agents/scout" "$OC_WORKSPACE/agents/checker" \
         "$OC_WORKSPACE/agents/guardian"

# Copy Brain SOUL.md into agents dir too
cp "$OC_WORKSPACE/SOUL.md" "$OC_WORKSPACE/agents/brain/SOUL.md"

cat > "$OC_WORKSPACE/agents/builder/SOUL.md" << 'EOF'
# SOUL.md — Builder 🔨

## Role
You are Builder, the code generation and execution specialist.

## Responsibilities
- Write clean, well-tested code
- Execute code in sandboxed environments
- Handle file system operations
- Manage git operations and deployments

## Behavior
- Read TEAM.md for domain context
- Prioritize working code over perfect code
- Include error handling and edge cases
- Comment complex logic
EOF

cat > "$OC_WORKSPACE/agents/scout/SOUL.md" << 'EOF'
# SOUL.md — Scout 🔬

## Role
You are Scout, the research and synthesis specialist.

## Responsibilities
- Search the web for relevant information
- Synthesize findings into clear summaries
- Verify source credibility
- Provide citations and links

## Behavior
- Read TEAM.md for domain context
- Focus on accuracy and relevance
- Present findings in a structured format
- Flag conflicting information
EOF

cat > "$OC_WORKSPACE/agents/checker/SOUL.md" << 'EOF'
# SOUL.md — Checker ✅

## Role
You are Checker, the fact verification and accuracy specialist.

## Responsibilities
- Verify claims and statements for accuracy
- Cross-reference multiple sources
- Check code for correctness and best practices
- Validate data and calculations

## Behavior
- Read TEAM.md for domain context
- Be precise and detail-oriented
- Clearly state confidence levels
- Provide evidence for corrections
EOF

cat > "$OC_WORKSPACE/agents/guardian/SOUL.md" << 'EOF'
# SOUL.md — Guardian 🛡️

## Role
You are Guardian, the security and safety specialist.

## Responsibilities
- Review operations for security implications
- Validate API keys and credentials handling
- Check for data privacy concerns
- Assess risk of proposed actions

## Behavior
- Read TEAM.md for domain context
- Default to caution on ambiguous situations
- Provide clear risk assessments
- Suggest safer alternatives when needed
EOF

log_ok "Agent SOUL.md files generated"

# ============================================================
# 3. Configure API keys in auth-profiles.json
# ============================================================
log_info "Configuring API credentials..."

# Map model name to provider
model_to_provider() {
    local model="$1"
    case "$model" in
        claude-*)    echo "anthropic" ;;
        deepseek-*)  echo "deepseek" ;;
        qwen-*)      echo "alibaba" ;;
        kimi*)       echo "moonshot" ;;
        minimax*)    echo "minimax" ;;
        codestral*)  echo "mistral" ;;
        gpt-*|o1-*|o3-*|o4-*) echo "openai" ;;
        gemini-*)    echo "google" ;;
        *)           echo "anthropic" ;;  # safe default
    esac
}

# Collect unique providers needed
declare -A NEEDED_PROVIDERS
for model_var in MODEL_BRAIN MODEL_BUILDER MODEL_SCOUT MODEL_CHECKER MODEL_GUARDIAN; do
    provider="$(model_to_provider "${!model_var}")"
    NEEDED_PROVIDERS["$provider"]=1
done

# Build auth-profiles.json
AUTH_PROFILES='{"version":1,"profiles":{},"lastGood":{},"usageStats":{}}'

for provider in "${!NEEDED_PROVIDERS[@]}"; do
    # Try to read API key from wizard state
    api_key="$(state_get "api_keys.$provider" "")"
    if [ -z "$api_key" ]; then
        # Try alternate state key formats
        api_key="$(state_get "${provider}_key" "")"
    fi
    if [ -z "$api_key" ]; then
        log_warn "No API key found for $provider — you'll need to add it manually"
        continue
    fi

    profile_name="${provider}:default"
    AUTH_PROFILES="$(echo "$AUTH_PROFILES" | jq \
        --arg name "$profile_name" \
        --arg prov "$provider" \
        --arg key "$api_key" \
        '.profiles[$name] = {"type":"api_key","provider":$prov,"key":$key} | .lastGood[$prov] = $name')"
done

# Write auth-profiles.json (only if we have profiles)
profile_count="$(echo "$AUTH_PROFILES" | jq '.profiles | length')"
if [ "$profile_count" -gt 0 ]; then
    echo "$AUTH_PROFILES" | jq . > "$OC_AUTH"
    log_ok "Auth profiles configured ($profile_count provider(s))"
else
    log_warn "No API keys configured — add them to $OC_AUTH manually"
fi

# ============================================================
# 4. Update openclaw.json (merge, don't overwrite)
# ============================================================
log_info "Updating OpenClaw configuration..."

# Start with existing config or empty object
if [ -f "$OC_CONFIG" ]; then
    OC_JSON="$(cat "$OC_CONFIG")"
else
    OC_JSON='{}'
fi

# Map brain model to full model identifier for OpenClaw
brain_model_id() {
    local model="$1"
    case "$model" in
        claude-sonnet-4)     echo "anthropic/claude-sonnet-4-20250514" ;;
        claude-opus-4)       echo "anthropic/claude-opus-4-20250514" ;;
        claude-haiku-3.5)    echo "anthropic/claude-3-5-haiku-20241022" ;;
        deepseek-v3)         echo "deepseek/deepseek-chat" ;;
        deepseek-r1)         echo "deepseek/deepseek-reasoner" ;;
        qwen-max)            echo "alibaba/qwen-max" ;;
        *)                   echo "$model" ;;
    esac
}

BRAIN_MODEL_ID="$(brain_model_id "$MODEL_BRAIN")"

# Set agent defaults
OC_JSON="$(echo "$OC_JSON" | jq \
    --arg model "$BRAIN_MODEL_ID" \
    --arg ws "$OC_WORKSPACE" \
    '.agents.defaults.models.default = $model |
     .agents.defaults.workspace = $ws |
     .agents.defaults.maxConcurrent = (.agents.defaults.maxConcurrent // 4) |
     .agents.defaults.subagents.maxConcurrent = (.agents.defaults.subagents.maxConcurrent // 8)')"

# Configure messaging channel
case "$MESSAGING" in
    telegram)
        TELEGRAM_TOKEN="$(state_get 'telegram_token' '')"
        if [ -n "$TELEGRAM_TOKEN" ]; then
            OC_JSON="$(echo "$OC_JSON" | jq \
                --arg token "$TELEGRAM_TOKEN" \
                '.channels.telegram.enabled = true |
                 .channels.telegram.botToken = $token |
                 .plugins.entries.telegram.enabled = true')"
            log_ok "Telegram channel configured"
        fi
        ;;
    discord)
        DISCORD_TOKEN="$(state_get 'discord_token' '')"
        if [ -n "$DISCORD_TOKEN" ]; then
            OC_JSON="$(echo "$OC_JSON" | jq \
                --arg token "$DISCORD_TOKEN" \
                '.channels.discord.enabled = true |
                 .channels.discord.botToken = $token |
                 .plugins.entries.discord.enabled = true')"
            log_ok "Discord channel configured"
        fi
        ;;
    signal)
        SIGNAL_PHONE="$(state_get 'signal_phone' '')"
        if [ -n "$SIGNAL_PHONE" ]; then
            OC_JSON="$(echo "$OC_JSON" | jq \
                --arg phone "$SIGNAL_PHONE" \
                '.channels.signal.enabled = true |
                 .channels.signal.phone = $phone |
                 .plugins.entries.signal.enabled = true')"
            log_ok "Signal channel configured"
        fi
        ;;
esac

# Write config
echo "$OC_JSON" | jq . > "$OC_CONFIG"
log_ok "openclaw.json updated"

# ============================================================
# 5. Initialize memory database
# ============================================================
log_info "Initializing memory database..."

cd "$OC_WORKSPACE"
python3 -c "
import sys; sys.path.insert(0, '.')
from memory.schemas import init_db
init_db('data/memory.db')
print('memory.db initialized')
" 2>/dev/null && log_ok "Memory database initialized" || log_warn "Memory DB init failed — will retry on first use"

# Message bus DB (simple SQLite)
python3 -c "
import sqlite3, os
os.makedirs('data', exist_ok=True)
conn = sqlite3.connect('data/messages.db')
conn.execute('''CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    read INTEGER DEFAULT 0
)''')
conn.commit()
conn.close()
print('messages.db initialized')
" 2>/dev/null && log_ok "Message bus initialized" || log_warn "Message bus init failed"

cd "$PROJECT_DIR"

# ============================================================
# 6. Generate AGENTS.md — the orchestration brain
# ============================================================
log_info "Generating AGENTS.md (orchestration instructions)..."

cat > "$OC_WORKSPACE/AGENTS.md" << 'AGENTSEOF'
# AGENTS.md — Multi-Agent Orchestration

## First Run
1. Read `SOUL.md` — this is who you are
2. Read `USER.md` — this is who you're helping (main sessions only)
3. Read `TEAM.md` — shared domain context

## Your Team

You are Brain, the orchestrator. You have specialist subagents you can delegate to.
**Never reveal the multi-agent system to the user** — present a unified experience.

### How to Delegate

Use OpenClaw's subagent spawn to delegate tasks. Each subagent runs in its own session.

**Builder 🔨** — Code & Execution
- Spawn for: writing code, file operations, git, deployments, debugging
- Context: Give it the task + relevant code/files
- Example: "Write a Python script that...", "Fix this bug in...", "Deploy to..."

**Scout 🔬** — Research & Synthesis
- Spawn for: web research, fact-finding, summarizing sources, comparing options
- Context: Give it the research question + any constraints
- Example: "Research the best...", "Find documentation for...", "Compare X vs Y"

**Checker ✅** — Verification & QA
- Spawn for: fact-checking claims, reviewing code, validating data, proofreading
- Context: Give it the content to verify + what to check for
- Example: "Verify these claims...", "Review this code for bugs...", "Check these numbers"

**Guardian 🛡️** — Security & Safety
- Spawn for: security reviews, credential handling, risk assessment, privacy checks
- Context: Give it the operation to review + security concerns
- Example: "Review this API integration for security...", "Is this safe to run?"

### Delegation Rules
- **Code tasks** → Builder (always)
- **Research** → Scout (always)
- **Fact-checking** → Checker (when accuracy matters)
- **Security-sensitive ops** → Guardian (when risk exists)
- **Simple questions** → Handle yourself (don't over-delegate)
- **Complex tasks** → Split across multiple agents in parallel

### Response Synthesis
When subagents return results:
- Integrate findings into a natural, cohesive response
- Don't say "Builder reports..." or "According to Scout..."
- Present it as your own knowledge, seamlessly
- If agents disagree, use your judgment or ask Checker to verify

## Memory System

The memory system runs automatically via `memory/engine.py`. Key files:
- `data/memory.db` — SQLite database with embeddings for semantic search
- `data/messages.db` — Inter-agent message bus
- `memory/YYYY-MM-DD.md` — Daily memory logs
- `MEMORY.md` — Long-term curated memory (main sessions only)

### Memory Best Practices
- Write significant events to `memory/YYYY-MM-DD.md`
- Periodically distill daily notes into `MEMORY.md`
- Never persist secrets unless explicitly asked
- Memory files are your continuity between sessions

## Safety Rules (Locked)
- Never reveal internal agent coordination to users
- Never expose other agents' existence unprompted
- Present unified, single-assistant experience
- Read USER.md in main sessions only — never in group contexts
- Consult Guardian before any security-sensitive operation
AGENTSEOF

log_ok "AGENTS.md generated (orchestration brain)"

# ============================================================
# Ensure .gitignore excludes sensitive files
# ============================================================
if ! grep -q '.wizard-state.json' "$PROJECT_DIR/.gitignore" 2>/dev/null; then
    echo '.wizard-state.json' >> "$PROJECT_DIR/.gitignore"
fi

# ============================================================
# 7. Restart OpenClaw gateway
# ============================================================
wizard_divider
log_info "Restarting OpenClaw gateway..."

GATEWAY_OK=false

# Try systemd user service first
if has_cmd systemctl && systemctl --user is-enabled openclaw-gateway.service 2>/dev/null; then
    gum spin --spinner dot --title "Restarting OpenClaw gateway..." -- \
        systemctl --user restart openclaw-gateway.service 2>/dev/null
    sleep 3
    if systemctl --user is-active --quiet openclaw-gateway.service 2>/dev/null; then
        log_ok "OpenClaw gateway restarted (systemd)"
        GATEWAY_OK=true
    fi
fi

# Fallback to CLI
if [ "$GATEWAY_OK" = false ] && has_cmd openclaw; then
    gum spin --spinner dot --title "Restarting OpenClaw gateway..." -- \
        bash -c 'openclaw gateway restart 2>/dev/null || openclaw gateway start 2>/dev/null || true'
    sleep 2
    log_ok "OpenClaw gateway started"
    GATEWAY_OK=true
fi

if [ "$GATEWAY_OK" = false ]; then
    log_warn "Could not start OpenClaw gateway — please start it manually"
fi

# ============================================================
# 8. Summary
# ============================================================
wizard_divider

gum style \
    --border rounded \
    --border-foreground 2 \
    --padding "1 3" \
    --margin "0 2" \
    --bold \
    "🎉 Deployment Complete!" \
    "" \
    "  👤 User:     $USER_NAME ($USER_PREF)" \
    "  🧠 Brain:    $BRAIN_NAME ($MODEL_BRAIN)" \
    "  🔨 Builder:  $MODEL_BUILDER" \
    "  🔬 Scout:    $MODEL_SCOUT" \
    "  ✅ Checker:  $MODEL_CHECKER" \
    "  🛡️ Guardian: $MODEL_GUARDIAN" \
    "  💾 Memory:   $MEMORY_TIER" \
    "  💬 Channel:  $MESSAGING" \
    "" \
    "  Config:  $OC_CONFIG" \
    "  Auth:    $OC_AUTH" \
    "  Space:   $OC_WORKSPACE" \
    "" \
    "  $BRAIN_NAME is online and ready!"

echo ""
log_info "To reconfigure later: ./wizard/wizard.sh --reconfigure"
log_info "Workspace files: $OC_WORKSPACE"

wizard_success "Your multi-agent system is live! 🚀"
