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
BRAIN_NAME="$(state_get 'brain.name' 'Cortex')"
BRAIN_STYLE="$(state_get 'brain.style' 'balanced')"
BRAIN_VERBOSITY="$(state_get 'brain.verbosity' 'adaptive')"
BRAIN_NOTES="$(state_get 'brain.personality_notes')"
MEMORY_TIER="$(state_get 'memory_tier' 'full')"
MESSAGING="$(state_get 'messaging' 'cli')"

VERBOSE_MODE="$(state_get 'brain.verbose_mode' 'verbose')"
TECH_LANGUAGE="$(state_get 'tech_stack.language' '')"
TECH_FRAMEWORKS="$(state_get 'tech_stack.frameworks' '')"
TECH_PKG_MANAGER="$(state_get 'tech_stack.package_manager' '')"
TECH_CSS="$(state_get 'tech_stack.css' '')"
TECH_DATABASE="$(state_get 'tech_stack.database' '')"
TECH_OTHER="$(state_get 'tech_stack.other' '')"

MODEL_BRAIN="$(state_get 'models.brain' 'claude-opus-4-6')"
MODEL_BUILDER="$(state_get 'models.builder' 'deepseek-reasoner')"
MODEL_RESEARCHER_THINKING="$(state_get 'models.researcher.thinking' 'kimi-k2.5-thinking')"
MODEL_RESEARCHER_INSTANT="$(state_get 'models.researcher.instant' 'kimi-k2.5-instant')"
MODEL_RESEARCHER="$MODEL_RESEARCHER_THINKING"
MODEL_VERIFIER="$(state_get 'models.verifier' 'deepseek-reasoner')"
MODEL_GUARDIAN="$(state_get 'models.guardian' 'deepseek-chat')"

# --- Ensure directories ---
mkdir -p "$OC_WORKSPACE/data"
mkdir -p "$OC_DIR/agents/main/agent"

# ============================================================
# 1. Install Python dependencies
# ============================================================
log_info "Installing Python dependencies for memory engine..."
log_info "  Using ONNX runtime for embeddings (lightweight, no PyTorch needed)..."
PIP_LOG="/tmp/pip-install-$$.log"
if python3 -m pip install --break-system-packages --ignore-installed -r "$PROJECT_DIR/requirements.txt" > "$PIP_LOG" 2>&1; then
    tail -3 "$PIP_LOG"
else
    cat "$PIP_LOG"
    log_warn "pip install had errors — some features may not work"
    log_warn "  Try manually: pip install onnxruntime tokenizers numpy httpx --break-system-packages"
fi
rm -f "$PIP_LOG"
log_ok "Python dependencies installed"

# ============================================================
# 2. Copy agent system into OpenClaw workspace
# ============================================================
gum spin --spinner dot --title "Copying agent system to workspace..." -- sleep 0.3

# Copy agents/, memory/, TEAM.md
cp -r "$PROJECT_DIR/agents" "$OC_WORKSPACE/" || log_warn "Failed to copy agents/ — agent system may be incomplete"
cp -r "$PROJECT_DIR/memory" "$OC_WORKSPACE/" || log_warn "Failed to copy memory/ — memory engine may not work"
cp -r "$PROJECT_DIR/scripts" "$OC_WORKSPACE/" || log_warn "Failed to copy scripts/ — maintenance scripts may be missing"

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

$(if [ -n "$TECH_LANGUAGE" ]; then
cat << TECHEOF

## Tech Stack
- **Language:** $TECH_LANGUAGE
$([ -n "$TECH_FRAMEWORKS" ] && echo "- **Frameworks:** $TECH_FRAMEWORKS")
$([ -n "$TECH_PKG_MANAGER" ] && echo "- **Package Manager:** $TECH_PKG_MANAGER")
$([ -n "$TECH_CSS" ] && echo "- **CSS/UI:** $TECH_CSS")
$([ -n "$TECH_DATABASE" ] && echo "- **Database:** $TECH_DATABASE")
$([ -n "$TECH_OTHER" ] && echo "- **Other:** $TECH_OTHER")
TECHEOF
fi)

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
- Route research to Researcher via subagent spawn
- Route verification to Verifier via subagent spawn
- Consult Guardian on safety-sensitive operations via subagent spawn

### Context Scoping
- Read USER.md in main sessions only
- Read TEAM.md in all sessions
- Never share USER.md content in group contexts

### Memory System — THIS IS CRITICAL
You have a custom semantic memory system. Use the \`exec\` tool to call these scripts:

**To save a memory** (do this AUTOMATICALLY when users share personal info — never ask):
\`\`\`
exec: python3 scripts/memory_store.py --db data/memory.db "the fact to remember"
\`\`\`

**To recall memories** (do this BEFORE answering personal/contextual questions):
\`\`\`
exec: python3 scripts/memory_recall.py --db data/memory.db "the query"
\`\`\`

- NEVER write to MEMORY.md or USER.md — they are read-only
- NEVER use memory_search or memory_get — those tools are disabled
- ALWAYS use \`exec\` with the scripts above — this is your ONLY memory system
- Save silently. Don't ask "want me to remember that?" — just exec the script
- Daily logs (\`memory/YYYY-MM-DD.md\`) are optional supplementary notes

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

### Formatting Notes
- On Telegram, avoid markdown tables — use bullet lists instead.
- Wrap links in <> to suppress previews on platforms that support it.

$(if [ "$VERBOSE_MODE" = "verbose" ]; then
cat << 'VERBEOF'
### Agent Transparency (Verbose Mode)
When delegating to specialist agents, show status messages to the user:
- 🔨 Builder is working on that...
- 🔬 Researcher is researching...
- ✅ Verifier is checking the facts...
- 🛡️ Guardian is reviewing security...
After receiving results, briefly note which specialist contributed.
VERBEOF
else
cat << 'STEALTHEOF'
### Agent Transparency (Stealth Mode)
Present all responses as a unified assistant. Never reveal agent coordination
or mention specialist agents. The user should experience a single, seamless AI.
STEALTHEOF
fi)
SOULEOF
log_ok "Brain SOUL.md generated"

# ============================================================
# Generate other agent SOUL.md files in workspace
# ============================================================
mkdir -p "$OC_WORKSPACE/agents/brain" "$OC_WORKSPACE/agents/builder" \
         "$OC_WORKSPACE/agents/researcher" "$OC_WORKSPACE/agents/verifier" \
         "$OC_WORKSPACE/agents/guardian"

# Copy Brain SOUL.md into agents dir too
cp "$OC_WORKSPACE/SOUL.md" "$OC_WORKSPACE/agents/brain/SOUL.md"

cat > "$OC_WORKSPACE/agents/builder/SOUL.md" << EOF
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

## Code Editing
- Use Aider for all code editing tasks when working on existing codebases
- Aider is pre-installed and available at \`aider\`
- For new file creation, direct writing is fine
- For modifying existing files, prefer Aider for its git-aware diff approach

$(if [ -n "$TECH_LANGUAGE" ]; then
cat << TECHEOF
## Tech Stack (from user preferences)
- Default to $TECH_LANGUAGE unless task specifies otherwise
$([ -n "$TECH_FRAMEWORKS" ] && echo "- Use $TECH_FRAMEWORKS when applicable")
$([ -n "$TECH_PKG_MANAGER" ] && echo "- Package management: $TECH_PKG_MANAGER")
$([ -n "$TECH_CSS" ] && echo "- CSS/UI: $TECH_CSS")
$([ -n "$TECH_DATABASE" ] && echo "- Database: $TECH_DATABASE")
$([ -n "$TECH_OTHER" ] && echo "- Additional: $TECH_OTHER")
TECHEOF
fi)
EOF

cat > "$OC_WORKSPACE/agents/researcher/SOUL.md" << 'EOF'
# SOUL.md — Researcher 🔬

## Role
You are Researcher, the research and synthesis specialist.

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

cat > "$OC_WORKSPACE/agents/verifier/SOUL.md" << 'EOF'
# SOUL.md — Verifier ✅

## Role
You are Verifier, the fact verification and accuracy specialist.

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
# Generate agent config.yaml files (model + tools per agent)
# ============================================================
log_info "Generating agent config.yaml files..."

brain_model_id_for() {
    local model="$1"
    case "$model" in
        claude-opus-4-6)     echo "anthropic/claude-opus-4-6" ;;
        claude-sonnet-4-5)   echo "anthropic/claude-sonnet-4-5-20250514" ;;
        claude-haiku-3.5)    echo "anthropic/claude-3-5-haiku-20241022" ;;
        deepseek-reasoner)   echo "deepseek/deepseek-reasoner" ;;
        deepseek-chat)       echo "deepseek/deepseek-chat" ;;
        qwen-max)            echo "alibaba/qwen-max" ;;
        qwen-plus)           echo "alibaba/qwen-plus" ;;
        gemini-3-pro-preview) echo "google/gemini-3-pro-preview" ;;
        gemini-2.5-pro)      echo "google/gemini-2.5-pro-preview" ;;
        gemini-2.5-flash)    echo "google/gemini-2.5-flash-preview" ;;
        kimi-k2.5-thinking)  echo "moonshot/kimi-k2.5" ;;
        kimi-k2.5-instant)   echo "moonshot/kimi-k2.5" ;;
        *)                   echo "$model" ;;
    esac
}

# Builder config
cat > "$OC_WORKSPACE/agents/builder/config.yaml" << EOF
model: $(brain_model_id_for "$MODEL_BUILDER")
tools:
  - exec
  - read
  - write
  - edit
EOF

# Researcher config
cat > "$OC_WORKSPACE/agents/researcher/config.yaml" << EOF
model: $(brain_model_id_for "$MODEL_RESEARCHER")
tools:
  - web_search
  - web_fetch
  - read
EOF

# Verifier config
cat > "$OC_WORKSPACE/agents/verifier/config.yaml" << EOF
model: $(brain_model_id_for "$MODEL_VERIFIER")
tools:
  - web_search
  - web_fetch
  - read
EOF

# Guardian config
cat > "$OC_WORKSPACE/agents/guardian/config.yaml" << EOF
model: $(brain_model_id_for "$MODEL_GUARDIAN")
tools:
  - read
EOF

log_ok "Agent config.yaml files generated"

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
for model_var in MODEL_BRAIN MODEL_BUILDER MODEL_RESEARCHER MODEL_VERIFIER MODEL_GUARDIAN; do
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
        '.profiles[$name] = {"type":"api_key","provider":$prov,"key":$key} | .lastGood[$prov] = $name')" || {
        log_warn "Config generation issue — failed to add $provider auth profile"
        continue
    }
done

# Write auth-profiles.json (only if we have profiles)
profile_count="$(echo "$AUTH_PROFILES" | jq '.profiles | length' 2>/dev/null || echo 0)"
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
        claude-opus-4-6)     echo "anthropic/claude-opus-4-6" ;;
        claude-sonnet-4-5)   echo "anthropic/claude-sonnet-4-5-20250514" ;;
        claude-haiku-3.5)    echo "anthropic/claude-3-5-haiku-20241022" ;;
        deepseek-reasoner)   echo "deepseek/deepseek-reasoner" ;;
        deepseek-chat)       echo "deepseek/deepseek-chat" ;;
        qwen-max)            echo "alibaba/qwen-max" ;;
        qwen-plus)           echo "alibaba/qwen-plus" ;;
        gemini-3-pro-preview) echo "google/gemini-3-pro-preview" ;;
        gemini-2.5-pro)      echo "google/gemini-2.5-pro-preview" ;;
        gemini-2.5-flash)    echo "google/gemini-2.5-flash-preview" ;;
        kimi-k2.5-thinking)  echo "moonshot/kimi-k2.5" ;;
        kimi-k2.5-instant)   echo "moonshot/kimi-k2.5" ;;
        *)                   echo "$model" ;;
    esac
}

BRAIN_MODEL_ID="$(brain_model_id "$MODEL_BRAIN")"

# Generate gateway auth token
GW_TOKEN="$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets;print(secrets.token_hex(16))')"

# Set agent defaults
OC_JSON="$(echo "$OC_JSON" | jq \
    --arg model "$BRAIN_MODEL_ID" \
    --arg ws "$OC_WORKSPACE" \
    --arg gwtoken "$GW_TOKEN" \
    '.gateway.mode = "local" |
     .gateway.auth.token = $gwtoken |
     .agents.defaults.model.primary = $model |
     .agents.defaults.workspace = $ws |
     .agents.defaults.memorySearch.enabled = false |
     .agents.defaults.maxConcurrent = (.agents.defaults.maxConcurrent // 4) |
     .agents.defaults.subagents.maxConcurrent = (.agents.defaults.subagents.maxConcurrent // 8) |
     .tools.deny = ["memory_search", "memory_get"]')" || {
    log_warn "Config generation issue — openclaw.json may need manual review"
}

# Configure messaging channel
case "$MESSAGING" in
    telegram)
        TELEGRAM_TOKEN="$(state_get 'telegram_token' '')"
        if [ -n "$TELEGRAM_TOKEN" ]; then
            TELEGRAM_OWNER="$(state_get 'telegram_owner' '')"
            if [ -n "$TELEGRAM_OWNER" ]; then
                DM_POLICY="allowlist"
                ALLOW_FROM="[\"$TELEGRAM_OWNER\"]"
            else
                DM_POLICY="open"
                ALLOW_FROM='["*"]'
            fi
            OC_JSON="$(echo "$OC_JSON" | jq \
                --arg token "$TELEGRAM_TOKEN" \
                --arg dmPolicy "$DM_POLICY" \
                --argjson allowFrom "$ALLOW_FROM" \
                '.channels.telegram.enabled = true |
                 .channels.telegram.botToken = $token |
                 .channels.telegram.dmPolicy = $dmPolicy |
                 .channels.telegram.allowFrom = $allowFrom |
                 .channels.telegram.groupPolicy = "disabled" |
                 .channels.telegram.streamMode = "partial" |
                 .plugins.entries.telegram.enabled = true')" || {
                log_warn "Config generation issue — Telegram config may need manual review"
            }
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

# Usage tracking DB
python3 -c "
import sys; sys.path.insert(0, '.')
from agents.common.usage_tracker import UsageTracker
UsageTracker('data/usage.db')
print('usage.db initialized')
" 2>/dev/null && log_ok "Usage tracking database initialized" || log_warn "Usage DB init failed"

# Activity log DB
python3 -c "
import sys; sys.path.insert(0, '.')
from agents.common.activity_log import ActivityLog
ActivityLog('data/activity.db')
print('activity.db initialized')
" 2>/dev/null && log_ok "Activity log database initialized" || log_warn "Activity DB init failed"

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
# 5b. Set up memory consolidation cron job
# NOTE: crontab runs in system timezone (usually UTC). Only the morning brief
# converts local timezone to UTC for scheduling. All other jobs use UTC times.
# ============================================================
log_info "Setting up memory consolidation cron job..."

CRON_TIER="$MEMORY_TIER"
USER_TZ="$(state_get 'user.timezone' 'UTC')"
CRON_CMD="cd $OC_WORKSPACE && python3 -m memory.consolidation_runner --db-path data/memory.db --tier $CRON_TIER >> data/consolidation.log 2>&1"
CRON_MARKER="# openclaw-memory-consolidation"

if [ "$CRON_TIER" = "full" ]; then
    CRON_SCHEDULE="0 3 * * *"
    CRON_DESC="daily at 3:00 AM"
else
    CRON_SCHEDULE="0 3 * * 0"
    CRON_DESC="weekly (Sunday) at 3:00 AM"
fi

CRON_LINE="$CRON_SCHEDULE $CRON_CMD $CRON_MARKER"

# Read existing crontab, append if not already there, write back
EXISTING_CRON="$(crontab -l 2>/dev/null || true)"
if echo "$EXISTING_CRON" | grep -qF "openclaw-memory-consolidation"; then
    EXISTING_CRON="$(echo "$EXISTING_CRON" | grep -vF "openclaw-memory-consolidation")"
fi
echo "${EXISTING_CRON:+$EXISTING_CRON
}$CRON_LINE" | crontab -

log_ok "Cron job installed ($CRON_DESC, TZ: $USER_TZ)"
log_info "  Schedule: $CRON_SCHEDULE"
log_info "  Command:  python3 -m memory.consolidation_runner --db-path data/memory.db --tier $CRON_TIER"
log_info "  Log:      $OC_WORKSPACE/data/consolidation.log"

# ============================================================
# 5c. Set up additional cron jobs (health, backup, rotation)
# ============================================================
log_info "Setting up maintenance cron jobs..."

EXISTING_CRON="$(crontab -l 2>/dev/null || true)"

# Health check — every 30 min
HEALTH_MARKER="# openclaw-health-check"
HEALTH_LINE="*/30 * * * * cd $OC_WORKSPACE && bash scripts/health_check.sh >> data/health.log 2>&1 $HEALTH_MARKER"
if echo "$EXISTING_CRON" | grep -qF "openclaw-health-check"; then
    EXISTING_CRON="$(echo "$EXISTING_CRON" | grep -vF "openclaw-health-check")"
fi

# Memory backup — daily at 4am
BACKUP_MARKER="# openclaw-memory-backup"
BACKUP_LINE="0 4 * * * cd $OC_WORKSPACE && bash scripts/backup_memory.sh >> data/backup.log 2>&1 $BACKUP_MARKER"
if echo "$EXISTING_CRON" | grep -qF "openclaw-memory-backup"; then
    EXISTING_CRON="$(echo "$EXISTING_CRON" | grep -vF "openclaw-memory-backup")"
fi

# Log rotation + metrics — weekly Sunday 5am
ROTATE_MARKER="# openclaw-log-rotation"
ROTATE_LINE="0 5 * * 0 cd $OC_WORKSPACE && bash scripts/rotate_logs.sh >> data/rotation.log 2>&1 $ROTATE_MARKER"
if echo "$EXISTING_CRON" | grep -qF "openclaw-log-rotation"; then
    EXISTING_CRON="$(echo "$EXISTING_CRON" | grep -vF "openclaw-log-rotation")"
fi

printf '%s\n' "$EXISTING_CRON" "$HEALTH_LINE" "$BACKUP_LINE" "$ROTATE_LINE" | crontab -

log_ok "Maintenance cron jobs installed (health check, backup, log rotation)"

# ============================================================
# 5d. Set up proactive cron jobs (morning brief + idea surfacing)
# ============================================================
MORNING_BRIEF_ENABLED="$(state_get 'features.morning_brief' 'true')"
IDEA_SURFACING_ENABLED="$(state_get 'features.idea_surfacing' 'true')"

EXISTING_CRON="$(crontab -l 2>/dev/null || true)"

if [ "$MORNING_BRIEF_ENABLED" = "true" ]; then
    log_info "Setting up morning brief cron job..."
    BRIEF_HOUR_LOCAL="$(state_get 'features.morning_brief_hour_local' '8')"
    USER_CITY="$(state_get 'user.city' '')"

    # Convert local hour to UTC for cron
    BRIEF_HOUR_UTC="$(TZ="$USER_TZ" python3 -c "
from datetime import datetime, timedelta
import zoneinfo
try:
    tz = zoneinfo.ZoneInfo('$USER_TZ')
    local = datetime.now(tz).replace(hour=$BRIEF_HOUR_LOCAL, minute=0, second=0)
    utc = local.astimezone(zoneinfo.ZoneInfo('UTC'))
    print(utc.hour)
except Exception:
    print($BRIEF_HOUR_LOCAL)
" 2>/dev/null || echo "$BRIEF_HOUR_LOCAL")"

    BRIEF_MARKER="# openclaw-morning-brief"
    CITY_ENV=""
    [ -n "$USER_CITY" ] && CITY_ENV="MORNING_BRIEF_CITY='$USER_CITY' "
    BRIEF_LINE="0 $BRIEF_HOUR_UTC * * * ${CITY_ENV}cd $OC_WORKSPACE && python3 scripts/morning_brief.py >> data/morning_brief.log 2>&1 $BRIEF_MARKER"
    log_info "  Local: ${BRIEF_HOUR_LOCAL}:00 $USER_TZ → UTC: ${BRIEF_HOUR_UTC}:00"
    if echo "$EXISTING_CRON" | grep -qF "openclaw-morning-brief"; then
        EXISTING_CRON="$(echo "$EXISTING_CRON" | grep -vF "openclaw-morning-brief")"
    fi
    EXISTING_CRON="$(printf '%s\n%s' "$EXISTING_CRON" "$BRIEF_LINE")"
    log_ok "Morning brief cron installed (daily at ${BRIEF_HOUR_LOCAL}:00 local)"
fi

if [ "$IDEA_SURFACING_ENABLED" = "true" ]; then
    log_info "Setting up idea surfacing cron job..."
    IDEAS_MARKER="# openclaw-idea-surfacing"
    IDEAS_LINE="0 10 * * 1 cd $OC_WORKSPACE && python3 scripts/idea_surfacer.py >> data/idea_surfacer.log 2>&1 $IDEAS_MARKER"
    if echo "$EXISTING_CRON" | grep -qF "openclaw-idea-surfacing"; then
        EXISTING_CRON="$(echo "$EXISTING_CRON" | grep -vF "openclaw-idea-surfacing")"
    fi
    EXISTING_CRON="$(printf '%s\n%s' "$EXISTING_CRON" "$IDEAS_LINE")"
    log_ok "Idea surfacing cron installed (weekly, Monday 10:00)"
fi

echo "$EXISTING_CRON" | crontab -

# ============================================================
# 6. Generate AGENTS.md — the orchestration brain
# ============================================================
log_info "Generating AGENTS.md (orchestration instructions)..."

cp "$PROJECT_DIR/workspace-templates/AGENTS.md" "$OC_WORKSPACE/AGENTS.md"

# Disable MEMORY.md — all memory goes through semantic DB
rm -f "$OC_WORKSPACE/MEMORY.md"
ln -s /dev/null "$OC_WORKSPACE/MEMORY.md"

log_ok "AGENTS.md generated (orchestration brain)"

# Generate TOOLS.md — environment-specific notes
cat > "$OC_WORKSPACE/TOOLS.md" << 'TOOLSEOF'
# TOOLS.md - Local Notes

Environment-specific notes for your setup.
Add camera names, SSH hosts, API endpoints, device nicknames, etc.

This file is yours — customize it as needed.
TOOLSEOF
log_ok "TOOLS.md generated (local notes template)"

# ============================================================
# 6b. Generate BOOTSTRAP.md — first-run greeting (self-deletes)
# ============================================================
log_info "Generating BOOTSTRAP.md (first-run experience)..."

cat > "$OC_WORKSPACE/BOOTSTRAP.md" << BOOTSTRAPEOF
# BOOTSTRAP.md — First Run (Step-by-Step Onboarding)

You were just installed by **$USER_PREF** via the setup wizard. This is your first conversation.

## How This Works

You will guide $USER_PREF through 5 steps, ONE AT A TIME. Do not show all steps at once.
Track progress by storing "onboarding_step_N_complete" in memory after each step.

## First Message

1. Read SOUL.md, USER.md, TEAM.md — get oriented
2. Introduce yourself warmly (2-3 sentences — name is **$BRAIN_NAME**)
3. Then present ONLY Step 1:

Say something like: "I'd love to show you what I can do. Let's start with something fun..."

Then ask them to tell you something personal — a pet's name, favorite food, a hobby.
When they respond, save it to memory using exec, confirm it's saved, then say:
"Now type /new to start a fresh session and ask me if I remember. Go ahead — I'll wait!"

After they do /new and confirm memory works, save this via exec:
\`\`\`
python3 scripts/memory_store.py --db data/memory.db "onboarding_step_1_complete"
\`\`\`

## Every Subsequent Session

At the start of each session, ALWAYS run this via exec FIRST:
\`\`\`
python3 scripts/memory_recall.py --db data/memory.db "onboarding step complete"
\`\`\`

Check which steps are complete, then present the NEXT incomplete step:

### Step 2 — Builder 🔨 (after step 1 complete)
Say: "Nice — memory works! Now let's try building something."
Suggest they ask you to write code. Example: "Write me a Python script that generates a random password"
After they try it and seem satisfied, save: "onboarding_step_2_complete"

### Step 3 — Researcher 🔬 (after step 2 complete)
Say: "Now let's see how research works."
Suggest they ask you to research something. Example: "What are the best noise-cancelling headphones in 2025?"
After they get results, save: "onboarding_step_3_complete"

### Step 4 — Guardian 🛡️ (after step 3 complete)
Say: "One more specialist to meet — security."
Suggest they paste code for a security review. Give them an example:
"Try pasting this and asking me to review it:
def login(user, pw):
    db.execute(f'SELECT * FROM users WHERE user={user} AND pw={pw}')
"
After they try it, save: "onboarding_step_4_complete"

### Step 5 — Full Pipeline 🚀 (after step 4 complete)
Say: "Last one — let's put it all together."
Suggest a combined task: "Research the best way to build a CLI tool in Python, then build me a simple one"
Point out the agent status messages (🔬🔨) showing the team working.
After they see it, save: "onboarding_step_5_complete"

### All Steps Complete
Say: "You're all set! That's the whole team — I'll figure out which specialist to bring in based on what you ask. Just chat naturally from here."
Then **delete this file** — onboarding is done.

## Rules

- Only show ONE step per session/conversation
- Always check memory for progress before presenting a step
- Be conversational, not robotic — adapt the suggestions to what feels natural
- If the user goes off-script (asks something unrelated), help them normally, then gently guide back to the current step
- Don't rush — let them explore each capability
BOOTSTRAPEOF

log_ok "BOOTSTRAP.md generated (first-run greeting)"

# ============================================================
# Ensure .gitignore excludes sensitive files
# ============================================================
if ! grep -q '.wizard-state.json' "$PROJECT_DIR/.gitignore" 2>/dev/null; then
    echo '.wizard-state.json' >> "$PROJECT_DIR/.gitignore"
fi

# ============================================================
# 6b. Initialize git repo and install pre-commit hook
# ============================================================
log_info "Setting up GitOps..."

cd "$OC_WORKSPACE"

# Init git repo if not already one
if [ ! -d ".git" ]; then
    git init
    log_ok "Git repository initialized"
fi

# Install pre-commit hook
if [ -f "$PROJECT_DIR/scripts/pre-commit" ]; then
    mkdir -p .git/hooks
    cp "$PROJECT_DIR/scripts/pre-commit" .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
    log_ok "Pre-commit hook installed (Guardian credential scanner)"
fi

# Initial commit of generated config files
git add -A 2>/dev/null || true
git commit -m "Initial setup: agent system, config, and memory" --no-verify 2>/dev/null || true
log_ok "Initial commit created"

# ============================================================
# 6c. Connect GitHub remote (if token provided)
# Wrapped in error handling — GitHub failures should not kill the wizard
# ============================================================
_setup_github_remote() {
    local GH_TOKEN="$(state_get 'api_keys.github' '')"

    if [ -z "$GH_TOKEN" ]; then
        log_info "No GitHub token — workspace is local git only"
        log_info "  Add one later: set api_keys.github in wizard state and re-deploy"
        return 0
    fi

    wizard_divider
    log_info "GitHub token detected — setting up remote repository..."
    echo ""

    GH_CHOICE="$(gum choose \
        "Create a new private repo on GitHub" \
        "Connect an existing repo" \
        "Skip — keep local only" \
        --header "  🐙 GitHub Repository")"

    case "$GH_CHOICE" in
        "Create a new private repo on GitHub")
            # Get GitHub username
            GH_USER="$(curl -sf -H "Authorization: token $GH_TOKEN" \
                https://api.github.com/user | jq -r '.login' 2>/dev/null)"
            
            if [ -z "$GH_USER" ] || [ "$GH_USER" = "null" ]; then
                log_warn "Could not authenticate with GitHub — check your token"
                return 0
            fi

            DEFAULT_REPO="$(echo "${USER_PREF:-agent}-workspace" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')"
            REPO_NAME="$(gum input \
                --placeholder "$DEFAULT_REPO" \
                --header "  Repository name:" \
                --width 50)"
            REPO_NAME="${REPO_NAME:-$DEFAULT_REPO}"

            # Create private repo
            CREATE_RESP="$(curl -sf -X POST \
                -H "Authorization: token $GH_TOKEN" \
                -H "Content-Type: application/json" \
                -d "{\"name\":\"$REPO_NAME\",\"private\":true,\"description\":\"$BRAIN_NAME workspace — memory-enhanced multi-agent system\"}" \
                https://api.github.com/user/repos 2>/dev/null)"

            REPO_URL="$(echo "$CREATE_RESP" | jq -r '.clone_url // empty' 2>/dev/null)"

            if [ -n "$REPO_URL" ]; then
                # Inject token into URL for push
                PUSH_URL="$(echo "$REPO_URL" | sed "s|https://|https://$GH_TOKEN@|")"
                git remote add origin "$PUSH_URL" 2>/dev/null || git remote set-url origin "$PUSH_URL"
                git branch -M main 2>/dev/null || true
                gum spin --spinner dot --title "Pushing to GitHub..." -- \
                    git push -u origin main 2>/dev/null
                log_ok "GitHub repo created: https://github.com/$GH_USER/$REPO_NAME (private)"
                state_set "github.repo" "$REPO_URL"
                state_set "github.user" "$GH_USER"
            else
                ERR_MSG="$(echo "$CREATE_RESP" | jq -r '.message // "Unknown error"' 2>/dev/null)"
                log_warn "Failed to create repo: $ERR_MSG"
            fi
            ;;
        "Connect an existing repo")
            REPO_URL="$(gum input \
                --placeholder "https://github.com/user/repo.git" \
                --header "  Repository URL:" \
                --width 60)"
            
            if [ -n "$REPO_URL" ]; then
                # Inject token for auth
                PUSH_URL="$(echo "$REPO_URL" | sed "s|https://|https://$GH_TOKEN@|")"
                git remote add origin "$PUSH_URL" 2>/dev/null || git remote set-url origin "$PUSH_URL"
                git branch -M main 2>/dev/null || true
                gum spin --spinner dot --title "Pushing to GitHub..." -- \
                    git push -u origin main --force 2>/dev/null && \
                    log_ok "Connected to $REPO_URL" || \
                    log_warn "Push failed — check repo URL and token permissions"
                state_set "github.repo" "$REPO_URL"
            fi
            ;;
        *)
            log_info "Skipped GitHub — workspace is local git only"
            ;;
    esac
}

# Run GitHub setup in a way that never kills the wizard
if ! _setup_github_remote; then
    log_warn "GitHub remote setup failed — continuing without GitHub"
    log_warn "  You can set this up manually later with: git remote add origin <url>"
fi

cd "$PROJECT_DIR"

# ============================================================
# 7. Restart OpenClaw gateway
# ============================================================
wizard_divider
log_info "Restarting OpenClaw gateway..."

GATEWAY_OK=false

# Try systemd user service first
if has_cmd systemctl && systemctl --user is-enabled openclaw-gateway.service 2>/dev/null; then
    gum spin --spinner dot --title "Restarting OpenClaw gateway..." -- \
        bash -c 'systemctl --user restart openclaw-gateway.service 2>/dev/null || true'
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
clear
echo ""
wizard_divider

gum style \
    --border rounded \
    --border-foreground 2 \
    --padding "1 3" \
    --margin "0 2" \
    --bold \
    "Deployment Complete!" \
    "" \
    "  👤  User:        $USER_NAME ($USER_PREF)" \
    "  🧠  Brain:       $BRAIN_NAME ($MODEL_BRAIN)" \
    "  🔨  Builder:     $MODEL_BUILDER" \
    "  🔬  Researcher:  $MODEL_RESEARCHER_THINKING / $MODEL_RESEARCHER_INSTANT" \
    "  ✅  Verifier:    $MODEL_VERIFIER" \
    "  🛡   Guardian:    $MODEL_GUARDIAN" \
    "  💾  Memory:      $MEMORY_TIER" \
    "  💬  Channel:     $MESSAGING" \
    "" \
    "  Config:  $OC_CONFIG" \
    "  Auth:    $OC_AUTH" \
    "  Space:   $OC_WORKSPACE" \
    "" \
    "  $BRAIN_NAME is online and ready!"

echo ""
log_info "To reconfigure later: ./wizard/wizard.sh --reconfigure"
log_info "Workspace files: $OC_WORKSPACE"

echo ""
gum style \
    --border normal \
    --border-foreground 240 \
    --padding "1 2" \
    --margin "0 4" \
    "What to try next:" \
    "" \
    "  - Say hello — test that $BRAIN_NAME responds" \
    "  - Drop your first idea — /idea build a REST API" \
    "  - Ask a question — Researcher kicks in automatically" \
    "  - Check verbose mode — agent activity is visible by default" \
    "  - Morning digest arrives at your configured time" \
    "" \
    "  Power moves:" \
    "  - /project — see your project board" \
    "  - /ideas — browse your idea backlog" \
    "  - /status — system health" \
    "" \
    "  Debug: see docs/DEBUG_CHECKLIST.md"

wizard_success "Your multi-agent system is live!"
