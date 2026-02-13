#!/usr/bin/env bash
# ============================================================================
# Step 8: Memory Setup
# Choose memory tier: Full, Standard, or Minimal.
# ============================================================================

wizard_header "8" "Memory Setup" "How much context should your agents remember?"

PREV_TIER="$(state_get 'memory_tier' '')"
if [ -z "$PREV_TIER" ] && is_recommended; then
    PREV_TIER="standard"
fi

gum style --foreground 250 --padding "0 2" \
    "📚 Full     — Everything: daily logs, long-term memory, cross-session recall" \
    "             Storage: ~50-200MB/mo  |  Token usage: Higher  |  Recall: Best" \
    "" \
    "📝 Standard — Balanced: daily logs + curated long-term memory" \
    "             Storage: ~10-50MB/mo   |  Token usage: Moderate |  Recall: Good" \
    "" \
    "📌 Minimal  — Essentials: key decisions and active context only" \
    "             Storage: ~1-10MB/mo    |  Token usage: Low      |  Recall: Basic"

echo ""

TIER_CHOICE="$(gum choose \
    "📚 Full — Maximum recall, higher cost" \
    "📝 Standard — Balanced (recommended)" \
    "📌 Minimal — Low overhead, basic recall")"

case "$TIER_CHOICE" in
    *Full*)     TIER="full"     ;;
    *Minimal*)  TIER="minimal"  ;;
    *)          TIER="standard" ;;
esac

state_set "memory_tier" "$TIER"
log_ok "Memory tier: $TIER"

wizard_success "Memory configuration saved!"
