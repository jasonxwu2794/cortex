#!/usr/bin/env bash
# ============================================================================
# Step 4: User Identity
# Collect name, preferred name, domain, current work. Generate USER.md & TEAM.md.
# ============================================================================

wizard_header "4" "About You" "Tell us about yourself so your agents can personalize their help."

# --- Defaults ---
DEF_NAME="$(state_get 'user.name' '')"
DEF_PREF="$(state_get 'user.preferred_name' '')"
DEF_DOMAIN="$(state_get 'user.domain' '')"
DEF_WORK="$(state_get 'user.current_work' '')"

if is_recommended && [ -z "$DEF_DOMAIN" ]; then
    DEF_DOMAIN="Software Engineering"
fi

# --- Collect info ---
NAME=""
while [ -z "$NAME" ]; do
    NAME="$(wizard_input "👤 What's your name?" "e.g. Jason" "$DEF_NAME")"
    [ -z "$NAME" ] && log_warn "Name is required."
done

PREFERRED=""
while [ -z "$PREFERRED" ]; do
    PREFERRED="$(wizard_input "💬 What should agents call you?" "e.g. Jase" "${DEF_PREF:-$NAME}")"
    [ -z "$PREFERRED" ] && log_warn "Preferred name is required."
done

DOMAIN=""
while [ -z "$DOMAIN" ]; do
    DOMAIN="$(wizard_input "🎯 What's your domain or field?" "e.g. Machine Learning" "$DEF_DOMAIN")"
    [ -z "$DOMAIN" ] && log_warn "Domain is required."
done

echo ""
gum style --foreground 240 "  (Optional — press Enter to skip)"
CURRENT_WORK="$(wizard_input "🔨 What are you currently working on?" "e.g. Building a multi-agent system" "$DEF_WORK")"

# --- Save state ---
state_set "user.name" "$NAME"
state_set "user.preferred_name" "$PREFERRED"
state_set "user.domain" "$DOMAIN"
state_set "user.current_work" "$CURRENT_WORK"

# --- Summary ---
wizard_divider
gum style --bold "Your Profile:"
echo "  Name:       $NAME"
echo "  Call me:    $PREFERRED"
echo "  Domain:     $DOMAIN"
[ -n "$CURRENT_WORK" ] && echo "  Working on: $CURRENT_WORK"

wizard_success "User identity saved!"
