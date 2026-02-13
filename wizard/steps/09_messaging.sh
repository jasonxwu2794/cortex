#!/usr/bin/env bash
# ============================================================================
# Step 9: Messaging Integration
# Connect to Telegram, Discord, Signal, or CLI.
# ============================================================================

wizard_header "9" "Messaging" "Connect your agents to a communication platform."

PREV_PLATFORM="$(state_get 'messaging' '')"

PLATFORM_CHOICE="$(gum choose \
    "💬 Telegram — Bot via @BotFather" \
    "🎮 Discord — Bot via Developer Portal" \
    "📱 Signal — signal-cli linked to phone" \
    "🖥️  CLI only — Interact via terminal")"

case "$PLATFORM_CHOICE" in
    *Telegram*) PLATFORM="telegram" ;;
    *Discord*)  PLATFORM="discord"  ;;
    *Signal*)   PLATFORM="signal"   ;;
    *)          PLATFORM="cli"      ;;
esac

state_set "messaging" "$PLATFORM"

# --- Platform-specific setup ---
case "$PLATFORM" in
    telegram)
        wizard_divider
        gum style --bold --foreground 212 "Telegram Bot Setup"
        echo ""
        gum style --foreground 250 --padding "0 2" \
            "1. Open Telegram and message @BotFather" \
            "2. Send /newbot and follow the prompts" \
            "3. Copy the API token" \
            "" \
            "🔗 https://t.me/BotFather"
        echo ""

        while true; do
            TOKEN="$(wizard_password "  Bot token:")"
            if [ -z "$TOKEN" ]; then
                log_warn "Token is required."
                continue
            fi

            gum spin --spinner dot --title "  Validating bot token..." -- sleep 1
            RESP="$(curl -s "https://api.telegram.org/bot${TOKEN}/getMe" 2>/dev/null)" || RESP=""
            if echo "$RESP" | jq -e '.ok' &>/dev/null; then
                BOT_NAME="$(echo "$RESP" | jq -r '.result.username')"
                log_ok "Connected! Bot: @$BOT_NAME"
                state_set "telegram_token" "$TOKEN"
                state_set "telegram_bot" "$BOT_NAME"
                break
            else
                log_error "Invalid token. Please check and try again."
                if ! wizard_confirm "Try again?"; then
                    log_warn "Saving token without validation"
                    state_set "telegram_token" "$TOKEN"
                    break
                fi
            fi
        done
        ;;

    discord)
        wizard_divider
        gum style --bold --foreground 212 "Discord Bot Setup"
        echo ""
        gum style --foreground 250 --padding "0 2" \
            "1. Go to https://discord.com/developers/applications" \
            "2. Create a new application → Bot section" \
            "3. Copy the bot token" \
            "4. Enable Message Content Intent under Privileged Gateway Intents" \
            "5. Invite bot to your server with appropriate permissions"
        echo ""

        TOKEN="$(wizard_password "  Bot token:")"
        state_set "discord_token" "$TOKEN"

        GUILD_ID="$(wizard_input "  Server (Guild) ID:" "Right-click server → Copy Server ID")"
        state_set "discord_guild_id" "$GUILD_ID"

        log_ok "Discord configuration saved"
        ;;

    signal)
        wizard_divider
        gum style --bold --foreground 212 "Signal Setup"
        echo ""
        gum style --foreground 250 --padding "0 2" \
            "1. Install signal-cli: https://github.com/AsamK/signal-cli" \
            "2. Register or link to your phone number" \
            "3. Provide your phone number below"
        echo ""

        PHONE="$(wizard_input "  Phone number:" "+1234567890")"
        state_set "signal_phone" "$PHONE"
        log_ok "Signal configuration saved"
        ;;

    cli)
        log_ok "CLI mode — no additional setup needed"
        ;;
esac

wizard_success "Messaging configured: $PLATFORM"
