#!/usr/bin/env bash
# ============================================================================
# Step 8: Memory Setup
# Choose memory tier: Full or Standard.
# ============================================================================

wizard_header "8" "Memory Setup" "How much context should your agents remember?"

# --- Use Defaults Option ---
echo ""
QUICK_CHOICE="$(gum choose \
    "Use recommended defaults" \
    "Customize manually")"

if [ "$QUICK_CHOICE" = "Use recommended defaults" ]; then
    state_set "memory_tier" "full"
    log_ok "Memory tier: full (recommended)"
    wizard_success "Memory configuration saved!"
    return 0 2>/dev/null || exit 0
fi

PREV_TIER="$(state_get 'memory_tier' '')"
if [ -z "$PREV_TIER" ] && is_recommended; then
    PREV_TIER="full"
fi

gum style --foreground 240 --padding "0 2" \
    "📚 Full     — Everything: daily logs, long-term memory, cross-session recall" \
    "             Storage: ~50-200MB/mo  |  Token usage: Higher  |  Recall: Best" \
    "" \
    "📝 Standard — Balanced: daily logs + curated long-term memory" \
    "             Storage: ~10-50MB/mo   |  Token usage: Moderate |  Recall: Good"

echo ""

OPT_FULL="📚 Full — Maximum recall (recommended)"
OPT_STD="📝 Standard — Balanced, lower cost"

SELECTED_OPT="$OPT_FULL"
if [ "$PREV_TIER" = "standard" ]; then
    SELECTED_OPT="$OPT_STD"
fi

TIER_CHOICE="$(gum choose --selected "$SELECTED_OPT" "$OPT_FULL" "$OPT_STD")"

case "$TIER_CHOICE" in
    *Full*)     TIER="full"     ;;
    *)          TIER="standard" ;;
esac

state_set "memory_tier" "$TIER"
log_ok "Memory tier: $TIER"

wizard_success "Memory configuration saved!"
