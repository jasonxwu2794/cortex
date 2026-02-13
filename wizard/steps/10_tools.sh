#!/usr/bin/env bash
# ============================================================================
# Step 10: Tool Selection
# Multi-select available tools for agents.
# ============================================================================

wizard_header "10" "Tools" "Select which tools your agents can use."

# --- Tool options ---
TOOL_OPTS=(
    "🔍 Web Search — Search the web via Brave API"
    "🐙 GitHub — Repo management, PRs, issues"
    "📁 File Access — Read/write workspace files"
    "⚡ Code Execution — Run code in sandbox"
    "🌐 Web Fetch — Scrape and extract web content"
)

# Defaults for recommended mode
if is_recommended; then
    DEFAULT_SELECTED=("🔍 Web Search — Search the web via Brave API" "📁 File Access — Read/write workspace files" "⚡ Code Execution — Run code in sandbox" "🌐 Web Fetch — Scrape and extract web content")
else
    DEFAULT_SELECTED=()
fi

echo ""
gum style --foreground 240 "  Use space to toggle, enter to confirm"
echo ""

# Build selected args
SELECTED_ARGS=()
for opt in "${TOOL_OPTS[@]}"; do
    for sel in "${DEFAULT_SELECTED[@]}"; do
        if [ "$opt" = "$sel" ]; then
            SELECTED_ARGS+=(--selected "$opt")
            break
        fi
    done
done

CHOICES="$(gum choose --no-limit "${SELECTED_ARGS[@]}" "${TOOL_OPTS[@]}")" || CHOICES=""

# Parse selections into tool slugs
TOOLS_JSON="["
FIRST=1
while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in
        *"Web Search"*)     SLUG="web_search" ;;
        *"GitHub"*)         SLUG="github" ;;
        *"File Access"*)    SLUG="file_access" ;;
        *"Code Execution"*) SLUG="code_execution" ;;
        *"Web Fetch"*)      SLUG="web_fetch" ;;
        *) continue ;;
    esac
    [ "$FIRST" = "1" ] && FIRST=0 || TOOLS_JSON+=","
    TOOLS_JSON+="\"$SLUG\""
done <<< "$CHOICES"
TOOLS_JSON+="]"

state_set_json "tools" "$TOOLS_JSON"

# Additional API keys for tools
if echo "$TOOLS_JSON" | grep -q "web_search"; then
    echo ""
    gum style --foreground 240 "  Web Search requires a Brave Search API key"
    gum style --foreground 240 "  Get one at: https://api.search.brave.com/app/keys"
    BRAVE_KEY="$(wizard_password "  Brave API key (Enter to skip):")"
    if [ -n "$BRAVE_KEY" ]; then
        state_set "api_keys.brave" "$BRAVE_KEY"
        log_ok "Brave Search key saved"
    fi
fi

if echo "$TOOLS_JSON" | grep -q "github"; then
    echo ""
    gum style --foreground 240 "  GitHub requires a personal access token"
    gum style --foreground 240 "  Create one at: https://github.com/settings/tokens"
    GH_TOKEN="$(wizard_password "  GitHub token (Enter to skip):")"
    if [ -n "$GH_TOKEN" ]; then
        state_set "api_keys.github" "$GH_TOKEN"
        log_ok "GitHub token saved"
    fi
fi

# ─── Proactive Features ───────────────────────────────────────────────────────
echo ""
gum style --foreground 214 --bold "  ☀️ Proactive Features"
echo ""

MORNING_BRIEF="$(gum confirm --default=yes "  Enable Morning Brief? (daily digest of progress, queue, health)" && echo "true" || echo "false")"
state_set "features.morning_brief" "$MORNING_BRIEF"

if [ "$MORNING_BRIEF" = "true" ]; then
    BRIEF_HOUR="$(gum input --placeholder "8" --prompt "  Morning brief hour (0-23, UTC): " --value "8")"
    state_set "features.morning_brief_hour" "${BRIEF_HOUR:-8}"
    log_ok "Morning Brief enabled (daily at ${BRIEF_HOUR:-8}:00 UTC)"
else
    log_info "Morning Brief disabled"
fi

IDEA_SURFACING="$(gum confirm --default=yes "  Enable Auto Idea Surfacing? (weekly pattern analysis → backlog ideas)" && echo "true" || echo "false")"
state_set "features.idea_surfacing" "$IDEA_SURFACING"

if [ "$IDEA_SURFACING" = "true" ]; then
    log_ok "Idea Surfacing enabled (weekly, Monday)"
else
    log_info "Idea Surfacing disabled"
fi

wizard_success "Tools configured!"
