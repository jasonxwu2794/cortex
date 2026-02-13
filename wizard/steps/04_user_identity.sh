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

# --- Timezone ---
DEF_TZ="$(state_get 'user.timezone' '')"
echo ""
gum style --foreground 240 "  Your timezone is used for scheduling (e.g. morning brief at 08:00 local time)"
TZ_CHOICE="$(gum choose --header "🕐 Select your timezone (or pick 'Other' to type):" \
    "UTC" \
    "US/Eastern" \
    "US/Central" \
    "US/Mountain" \
    "US/Pacific" \
    "Europe/London" \
    "Europe/Berlin" \
    "Europe/Paris" \
    "Asia/Tokyo" \
    "Asia/Shanghai" \
    "Asia/Kolkata" \
    "Asia/Singapore" \
    "Australia/Sydney" \
    "Australia/Melbourne" \
    "Pacific/Auckland" \
    "Other")" || TZ_CHOICE="UTC"

if [ "$TZ_CHOICE" = "Other" ]; then
    TIMEZONE="$(wizard_input "🕐 Enter your timezone" "e.g. America/New_York" "${DEF_TZ:-UTC}")"
    [ -z "$TIMEZONE" ] && TIMEZONE="UTC"
else
    TIMEZONE="$TZ_CHOICE"
fi

# --- City (optional, for weather) ---
DEF_CITY="$(state_get 'user.city' '')"
echo ""
gum style --foreground 240 "  (Optional — used for weather in your morning brief)"
CITY="$(wizard_input "🌤️ City for weather in morning brief?" "e.g. Melbourne (leave blank to skip)" "$DEF_CITY")"

# --- Save state ---
state_set "user.name" "$NAME"
state_set "user.preferred_name" "$PREFERRED"
state_set "user.domain" "$DOMAIN"
state_set "user.current_work" "$CURRENT_WORK"
state_set "user.timezone" "$TIMEZONE"
state_set "user.city" "$CITY"

# --- Summary ---
wizard_divider
gum style --bold "Your Profile:"
echo "  Name:       $NAME"
echo "  Call me:    $PREFERRED"
echo "  Domain:     $DOMAIN"
[ -n "$CURRENT_WORK" ] && echo "  Working on: $CURRENT_WORK"
echo "  Timezone:   $TIMEZONE"
[ -n "$CITY" ] && echo "  City:       $CITY (weather enabled)"

wizard_success "User identity saved!"
