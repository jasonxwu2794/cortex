#!/usr/bin/env bash
# ============================================================================
# Cortex — Setup Wizard
# Main orchestrator that runs each step in sequence.
# ============================================================================
set -euo pipefail

cleanup() {
    echo ""
    echo ""
    gum style --foreground 240 "  Setup cancelled. Re-run anytime with:"
    echo ""
    gum style --foreground 212 --padding "0 2" "  bash <(curl -sL https://raw.githubusercontent.com/jasonxwu2794/MemoryEnhancedMultiAgent/main/install.sh)"
    echo ""
    exit 130
}
trap cleanup INT

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
echo ""
CORTEX_ART=(
    "   ██████╗ ██████╗ ██████╗ ████████╗███████╗██╗  ██╗"
    "  ██╔════╝██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝"
    "  ██║     ██║   ██║██████╔╝   ██║   █████╗   ╚███╔╝ "
    "  ██║     ██║   ██║██╔══██╗   ██║   ██╔══╝   ██╔██╗ "
    "  ╚██████╗╚██████╔╝██║  ██║   ██║   ███████╗██╔╝ ██╗"
    "   ╚═════╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝"
)
echo ""
for line in "${CORTEX_ART[@]}"; do
    gum style --foreground 212 "    $line"
    sleep 0.08
done
gum style --foreground 240 --align center --margin "0 4" \
    "by Ajentic" \
    "" \
    "$(if [ "$RECONFIGURE" = "1" ]; then echo "Reconfiguration Mode"; else echo "Setup Wizard"; fi)"
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

# Step names corresponding to each step file
STEP_NAMES=(
    "Prerequisites"
    "OpenClaw Install"
    "Configuration Mode"
    "User Identity"
    "Tech Stack"
    "Brain Personality"
    "Model Selection"
    "API Keys"
    "Memory Setup"
    "Messaging"
    "Tools"
    "Deploy"
)

for step_file in "${STEPS[@]}"; do
    CURRENT_STEP=$((CURRENT_STEP + 1))
    step_path="$WIZARD_DIR/steps/$step_file"

    if [ ! -f "$step_path" ]; then
        log_error "Step file missing: $step_file"
        exit 1
    fi

    # Show progress bar
    wizard_progress "$CURRENT_STEP" "${STEP_NAMES[$((CURRENT_STEP - 1))]}"

    # Source and execute the step
    STEP_START=$(date +%s)
    source "$step_path"
    STEP_END=$(date +%s)
    elapsed=$((STEP_END - STEP_START))
    gum style --foreground 240 "  completed in ${elapsed}s"

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
    "Setup Complete!" \
    "" \
    "Cortex is ready." \
    "Your brain is online and waiting for your first message."
echo ""
