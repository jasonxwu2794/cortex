#!/usr/bin/env bash
# ============================================================================
# Step 6: Model Selection
# Per-agent model selection with cost estimates.
# ============================================================================

wizard_header "6" "Model Selection" "Choose which AI model powers each agent."

# --- Model definitions ---
MODELS=(
    "Claude Opus 4.6|claude-opus-4-6|anthropic|~\$40-80/mo|██████████|💰💰💰 Best brain money can buy"
    "Claude Sonnet 4.5|claude-sonnet-4-5|anthropic|~\$15-30/mo|████████░░|Save ~40% vs Opus"
    "DeepSeek V3.2 Reasoner|deepseek-reasoner|deepseek|~\$2-8/mo|██████░░░░|🏆 Best coding value (74% Aider)"
    "DeepSeek V3.2 Chat|deepseek-chat|deepseek|~\$1-5/mo|████░░░░░░|Fast + cheap, no thinking"
    "Gemini 3 Pro|gemini-3-pro-preview|google|~\$15-40/mo|█████████░|🔥 #3 Arena coding, premium"
    "Gemini 2.5 Pro|gemini-2.5-pro|google|~\$10-30/mo|████████░░|83% Aider, 1M context"
    "Qwen3 Max|qwen-max|alibaba|~\$5-15/mo|██████░░░░|Complex tasks, 262K context"
    "Qwen3 Plus|qwen-plus|alibaba|~\$2-6/mo|████░░░░░░|1M context, never recharge 😂"
    "Kimi K2.5 Thinking|kimi-k2.5-thinking|moonshot|~\$3-10/mo|██████░░░░|Deep reasoning, Arena #18"
    "Kimi K2.5 Instant|kimi-k2.5-instant|moonshot|~\$2-6/mo|█████░░░░░|Fast, Arena #24, coding #4"
    "Gemini 2.5 Flash|gemini-2.5-flash|google|~\$1-5/mo|████░░░░░░|Fast + cheap, 1M context"
)

# --- Agents to configure ---
declare -A AGENT_LABELS=(
    [brain]="🧠 Cortex (Orchestrator, user-facing)"
    [builder]="🔨 Builder (Code generation)"
    [researcher]="🔬 Researcher (uses 2 models: deep + fast)"
    [verifier]="✅ Verifier (Fact verification)"
    [guardian]="🛡️ Guardian (Quality + security gatekeeper)"
)

# --- Recommended defaults ---
declare -A DEFAULTS=(
    [brain]="Claude Opus 4.6"
    [builder]="DeepSeek V3.2 Reasoner"
    [researcher_thinking]="Kimi K2.5 Thinking"
    [researcher_instant]="Kimi K2.5 Instant"
    [verifier]="DeepSeek V3.2 Reasoner"
    [guardian]="Qwen3 Plus"
)

AGENT_ORDER=(brain builder researcher verifier guardian)

# Build display names for gum choose
MODEL_NAMES=()
for m in "${MODELS[@]}"; do
    IFS='|' read -r name slug provider cost bar <<< "$m"
    MODEL_NAMES+=("$name  $cost  $bar")
done

_select_model() {
    local header="$1"
    local default_name="$2"

    SELECTED_FLAG=()
    if [ -n "$default_name" ]; then
        for entry in "${MODEL_NAMES[@]}"; do
            if [[ "$entry" == "$default_name"* ]]; then
                SELECTED_FLAG=(--selected "$entry")
                break
            fi
        done
    fi

    CHOICE="$(gum choose --header "$header" "${SELECTED_FLAG[@]}" "${MODEL_NAMES[@]}")"
    CHOSEN_NAME="$(echo "$CHOICE" | sed 's/  .*//')"
    CHOSEN_SLUG=""
    CHOSEN_PROVIDER=""
    for m in "${MODELS[@]}"; do
        IFS='|' read -r name slug provider cost bar <<< "$m"
        if [ "$name" = "$CHOSEN_NAME" ]; then
            CHOSEN_SLUG="$slug"
            CHOSEN_PROVIDER="$provider"
            break
        fi
    done
}

for agent in "${AGENT_ORDER[@]}"; do
    wizard_divider
    gum style --bold --foreground 212 "${AGENT_LABELS[$agent]}"
    echo ""

    if [ "$agent" = "researcher" ]; then
        # Researcher uses dual-model routing: thinking + instant
        PREV_T="$(state_get "models.researcher.thinking" '')"
        if [ -z "$PREV_T" ] && is_recommended; then
            PREV_T="${DEFAULTS[researcher_thinking]}"
        fi
        _select_model "Select THINKING model (for planning & synthesis):" "$PREV_T"
        state_set "models.researcher.thinking" "$CHOSEN_SLUG"
        state_set "providers.researcher.thinking" "$CHOSEN_PROVIDER"
        log_ok "researcher (thinking) → $CHOSEN_NAME ($CHOSEN_SLUG)"

        PREV_I="$(state_get "models.researcher.instant" '')"
        if [ -z "$PREV_I" ] && is_recommended; then
            PREV_I="${DEFAULTS[researcher_instant]}"
        fi
        _select_model "Select INSTANT model (for parallel investigations):" "$PREV_I"
        state_set "models.researcher.instant" "$CHOSEN_SLUG"
        state_set "providers.researcher.instant" "$CHOSEN_PROVIDER"
        log_ok "researcher (instant) → $CHOSEN_NAME ($CHOSEN_SLUG)"
    else
        # Standard single-model selection
        PREV="$(state_get "models.$agent" '')"
        if [ -z "$PREV" ] && is_recommended; then
            PREV="${DEFAULTS[$agent]}"
        fi

        _select_model "Select model:" "$PREV"
        state_set "models.$agent" "$CHOSEN_SLUG"
        state_set "providers.$agent" "$CHOSEN_PROVIDER"
        log_ok "$agent → $CHOSEN_NAME ($CHOSEN_SLUG)"
    fi
done

wizard_divider
wizard_success "Model selection complete!"
