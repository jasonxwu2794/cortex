#!/usr/bin/env bash
# ============================================================================
# Step 6: Model Selection
# Per-agent model selection with cost estimates.
# ============================================================================

wizard_header "6" "Model Selection" "Choose which AI model powers each agent."

# --- Model definitions ---
MODELS=(
    "Claude Sonnet 4|claude-sonnet-4|anthropic|~\$15-30/mo|████████░░"
    "Claude Opus 4|claude-opus-4|anthropic|~\$40-80/mo|██████████"
    "Kimi|kimi|moonshot|~\$5-15/mo|█████░░░░░"
    "Qwen Max|qwen-max|alibaba|~\$8-20/mo|██████░░░░"
    "MiniMax|minimax|minimax|~\$5-12/mo|█████░░░░░"
    "DeepSeek|deepseek-v3|deepseek|~\$3-10/mo|████░░░░░░"
    "Codestral|codestral|mistral|~\$5-15/mo|█████░░░░░"
)

# --- Agents to configure ---
declare -A AGENT_LABELS=(
    [brain]="🧠 Brain (Orchestrator, user-facing)"
    [builder]="🔨 Builder (Code generation)"
    [researcher]="🔬 Researcher (Research, synthesis)"
    [verifier]="✅ Verifier (Fact verification)"
    [guardian]="🛡️ Guardian (Security review)"
)

# --- Recommended defaults ---
declare -A DEFAULTS=(
    [brain]="Claude Sonnet 4"
    [builder]="DeepSeek"
    [researcher]="Qwen Max"
    [verifier]="Qwen Max"
    [guardian]="Claude Sonnet 4"
)

AGENT_ORDER=(brain builder researcherverifierguardian)

# Build display names for gum choose
MODEL_NAMES=()
for m in "${MODELS[@]}"; do
    IFS='|' read -r name slug provider cost bar <<< "$m"
    MODEL_NAMES+=("$name  $cost  $bar")
done

for agent in "${AGENT_ORDER[@]}"; do
    wizard_divider
    gum style --bold --foreground 212 "${AGENT_LABELS[$agent]}"
    echo ""

    # Get previous/default selection
    PREV="$(state_get "models.$agent" '')"
    if [ -z "$PREV" ] && is_recommended; then
        PREV="${DEFAULTS[$agent]}"
    fi

    # Build --selected flag if we have a previous/default
    SELECTED_FLAG=()
    if [ -n "$PREV" ]; then
        for entry in "${MODEL_NAMES[@]}"; do
            if [[ "$entry" == "$PREV"* ]]; then
                SELECTED_FLAG=(--selected "$entry")
                break
            fi
        done
    fi

    # Show cost table and let user choose
    CHOICE="$(gum choose --header "Select model:" "${SELECTED_FLAG[@]}" "${MODEL_NAMES[@]}")"

    # Extract model slug from choice
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

    state_set "models.$agent" "$CHOSEN_SLUG"
    state_set "providers.$agent" "$CHOSEN_PROVIDER"
    log_ok "$agent → $CHOSEN_NAME ($CHOSEN_SLUG)"
done

wizard_divider
wizard_success "Model selection complete!"
