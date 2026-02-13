#!/usr/bin/env bash
# ============================================================================
# Step 7: API Keys
# Deduplicate providers, collect keys with masked input, validate.
# ============================================================================

wizard_header "7" "API Keys" "Enter API keys for your selected model providers."

# --- Provider metadata ---
declare -A PROVIDER_NAMES=(
    [anthropic]="Anthropic (Claude)"
    [moonshot]="Moonshot (Kimi)"
    [alibaba]="Alibaba (Qwen)"
    [minimax]="MiniMax"
    [deepseek]="DeepSeek"
    [mistral]="Mistral (Codestral)"
)

declare -A PROVIDER_URLS=(
    [anthropic]="https://console.anthropic.com/settings/keys"
    [moonshot]="https://platform.moonshot.cn/console/api-keys"
    [alibaba]="https://dashscope.console.aliyun.com/apiKey"
    [minimax]="https://www.minimaxi.com/platform"
    [deepseek]="https://platform.deepseek.com/api_keys"
    [mistral]="https://console.mistral.ai/api-keys"
)

declare -A PROVIDER_VALIDATE_URL=(
    [anthropic]="https://api.anthropic.com/v1/messages"
    [moonshot]="https://api.moonshot.cn/v1/models"
    [alibaba]="https://dashscope.aliyuncs.com/api/v1/models"
    [minimax]="https://api.minimax.chat/v1/models"
    [deepseek]="https://api.deepseek.com/v1/models"
    [mistral]="https://api.mistral.ai/v1/models"
)

# --- Collect unique providers from model selection ---
REQUIRED_PROVIDERS=()
declare -A SEEN_PROVIDERS

for agent in brain builder investigator verifier guardian; do
    provider="$(state_get "providers.$agent" '')"
    if [ -n "$provider" ] && [ -z "${SEEN_PROVIDERS[$provider]:-}" ]; then
        REQUIRED_PROVIDERS+=("$provider")
        SEEN_PROVIDERS[$provider]=1
    fi
done

if [ ${#REQUIRED_PROVIDERS[@]} -eq 0 ]; then
    log_warn "No providers detected — skipping API key setup"
    return 0 2>/dev/null || true
fi

log_info "You need API keys for ${#REQUIRED_PROVIDERS[@]} provider(s):"
echo ""

# --- Collect and validate each key ---
for provider in "${REQUIRED_PROVIDERS[@]}"; do
    name="${PROVIDER_NAMES[$provider]:-$provider}"
    url="${PROVIDER_URLS[$provider]:-}"
    validate_url="${PROVIDER_VALIDATE_URL[$provider]:-}"

    wizard_divider
    gum style --bold --foreground 212 "🔑 $name"
    if [ -n "$url" ]; then
        gum style --foreground 240 "  Get your key: $url"
    fi
    echo ""

    # Retry loop
    while true; do
        API_KEY="$(wizard_password "  API Key:")"

        if [ -z "$API_KEY" ]; then
            log_warn "Key cannot be empty."
            continue
        fi

        # Validate the key
        VALID=0
        if [ -n "$validate_url" ]; then
            gum spin --spinner dot --title "  Validating $name key..." -- sleep 1

            HTTP_CODE=""
            case "$provider" in
                anthropic)
                    HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
                        -H "x-api-key: $API_KEY" \
                        -H "anthropic-version: 2023-06-01" \
                        -H "content-type: application/json" \
                        -d '{"model":"claude-sonnet-4-20250514","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}' \
                        "$validate_url" 2>/dev/null)" || true
                    # 200 = success, 400 = valid key but bad request is fine
                    [[ "$HTTP_CODE" =~ ^(200|400)$ ]] && VALID=1
                    ;;
                *)
                    HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
                        -H "Authorization: Bearer $API_KEY" \
                        "$validate_url" 2>/dev/null)" || true
                    [[ "$HTTP_CODE" =~ ^(200|201)$ ]] && VALID=1
                    ;;
            esac
        else
            # No validation endpoint — accept the key
            VALID=1
        fi

        if [ "$VALID" = "1" ]; then
            log_ok "$name — key validated ✅"
            state_set "api_keys.$provider" "$API_KEY"
            break
        else
            log_error "Validation failed (HTTP $HTTP_CODE). Please check your key."
            if ! wizard_confirm "Try again?"; then
                log_warn "Skipping validation — saving key as-is"
                state_set "api_keys.$provider" "$API_KEY"
                break
            fi
        fi
    done
done

wizard_divider
wizard_success "All API keys configured!"
