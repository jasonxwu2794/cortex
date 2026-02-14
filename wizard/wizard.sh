#!/usr/bin/env bash
# ============================================================================
# Memory-Enhanced Multi-Agent System — Setup Wizard
# Main orchestrator that runs each step in sequence.
# ============================================================================
set -euo pipefail

WIZARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$WIZARD_DIR/utils.sh"

# --- Parse arguments ---
RECONFIGURE=0
for arg in "$@"; do
    case "$arg" in
        --reconfigure|-r) RECONFIGURE=1 ;;
        --help|-h)
            echo "Usage: wizard.sh [--reconfigure]"
            echo "  --reconfigure  Load previous config and allow changes"
            exit 0
            ;;
    esac
done
export RECONFIGURE

# --- Welcome Banner ---
clear 2>/dev/null || true
gum style \
    --border double \
    --border-foreground 212 \
    --padding "2 6" \
    --margin "1 4" \
    --bold \
    --align center \
    " 🧠  Memory-Enhanced Multi-Agent System" \
    "" \
    "Setup Wizard" \
    "" \
    "$(if [ "$RECONFIGURE" = "1" ]; then echo "Reconfiguration Mode"; else echo "Fresh Install"; fi)"

echo ""

if [ "$RECONFIGURE" = "1" ] && [ -f "$STATE_FILE" ]; then
    log_info "Loading previous configuration from .wizard-state.json"
    echo ""
else
    # Initialize fresh state
    state_init
fi

# --- Step Files ---
STEPS=(
    "01_prerequisites.sh"
    "02_openclaw_install.sh"
    "03_config_mode.sh"
    "04_user_identity.sh"
    "04b_tech_stack.sh"
    "05_brain_personality.sh"
    "06_model_selection.sh"
    "07_api_keys.sh"
    "08_memory_setup.sh"
    "09_messaging.sh"
    "10_tools.sh"
    "11_deploy.sh"
)

TOTAL_STEPS=${#STEPS[@]}
CURRENT_STEP=0

for step_file in "${STEPS[@]}"; do
    CURRENT_STEP=$((CURRENT_STEP + 1))
    step_path="$WIZARD_DIR/steps/$step_file"

    if [ ! -f "$step_path" ]; then
        log_error "Step file missing: $step_file"
        exit 1
    fi

    # Show progress bar
    gum style --foreground 240 "  [$CURRENT_STEP/$TOTAL_STEPS] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Source and execute the step
    source "$step_path"

    # Save timestamp after each step
    state_save_timestamp

    # In reconfigure mode, ask if user wants to continue after each step
    if is_reconfigure && [ "$CURRENT_STEP" -lt "$TOTAL_STEPS" ]; then
        echo ""
        if ! gum confirm "Continue to next step?"; then
            log_info "Skipping to deployment..."
            # Jump to deploy step
            source "$WIZARD_DIR/steps/11_deploy.sh"
            state_save_timestamp
            break
        fi
    fi
done

echo ""
gum style \
    --border double \
    --border-foreground 2 \
    --padding "1 4" \
    --margin "1 4" \
    --bold \
    --foreground 2 \
    --align center \
    "🎉  Setup Complete!  " \
    "" \
    "Your multi-agent system is ready.   " \
    "Brain is online and waiting for your first message.   "
echo ""
