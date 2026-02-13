#!/usr/bin/env bash
# ============================================================================
# Step 3: Configuration Mode
# Ask user: Recommended (pre-filled) or Custom (blank).
# ============================================================================

wizard_header "3" "Configuration Mode" "How would you like to set things up?"

PREV_MODE="$(state_get 'config_mode' '')"

gum style --foreground 250 --padding "0 2" \
    "⚡ Recommended — Sensible defaults pre-filled. Just tweak what you want." \
    "⚙️  Custom — Every field starts blank. Full control over every choice."

echo ""

MODE=$(gum choose \
    "⚡ Recommended" \
    "⚙️  Custom")

case "$MODE" in
    *Recommended*) state_set "config_mode" "recommended" ; log_ok "Recommended mode — smart defaults will be pre-filled" ;;
    *Custom*)      state_set "config_mode" "custom"      ; log_ok "Custom mode — you're in full control" ;;
esac
