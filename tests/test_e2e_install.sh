#!/usr/bin/env bash
# ============================================================================
# E2E Install Simulation Test
# Runs wizard steps 3-11 with mocked gum and pre-populated state,
# then verifies all expected outputs.
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PASS=0
FAIL=0
FAILURES=()

check() {
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then
        echo -e "  \033[32m✅ PASS\033[0m $desc"
        PASS=$((PASS + 1))
    else
        echo -e "  \033[31m❌ FAIL\033[0m $desc"
        FAIL=$((FAIL + 1))
        FAILURES+=("$desc")
    fi
}

# ============================================================
# 1. Set up clean test environment
# ============================================================
TEST_HOME="$(mktemp -d)"
trap 'rm -rf "$TEST_HOME"; rm -f "$PROJECT_DIR/.wizard-state.json"' EXIT

echo "=== Test home: $TEST_HOME ==="

# Mock .openclaw structure
mkdir -p "$TEST_HOME/.openclaw/agents/main/agent"
mkdir -p "$TEST_HOME/.openclaw/workspace"
echo '{"version":1}' > "$TEST_HOME/.openclaw/openclaw.json"
echo '{"version":1,"profiles":{},"lastGood":{},"usageStats":{}}' > "$TEST_HOME/.openclaw/agents/main/agent/auth-profiles.json"

# ============================================================
# 2. Create mock binaries
# ============================================================
mkdir -p "$TEST_HOME/bin"

# Mock gum
cat > "$TEST_HOME/bin/gum" << 'GUMEOF'
#!/usr/bin/env bash
CMD="${1:-}"; shift 2>/dev/null || true

case "$CMD" in
    choose)
        # Collect non-flag arguments (the actual options)
        OPTIONS=()
        SKIP_NEXT=0
        for arg in "$@"; do
            if [ "$SKIP_NEXT" = "1" ]; then SKIP_NEXT=0; continue; fi
            case "$arg" in
                --header|--selected|--height|--cursor) SKIP_NEXT=1; continue ;;
                --no-limit|--ordered) continue ;;
                --*) continue ;;
                *) OPTIONS+=("$arg") ;;
            esac
        done
        # Return first option
        if [ ${#OPTIONS[@]} -gt 0 ]; then
            echo "${OPTIONS[0]}"
        fi
        ;;
    input)
        IS_PASSWORD=0
        VALUE=""
        HAS_VALUE=0
        PLACEHOLDER=""
        SKIP_NEXT=0
        for arg in "$@"; do
            if [ "$SKIP_NEXT" = "1" ]; then
                case "$PREV_FLAG" in
                    --value) VALUE="$arg"; HAS_VALUE=1 ;;
                    --placeholder) PLACEHOLDER="$arg" ;;
                esac
                SKIP_NEXT=0; continue
            fi
            case "$arg" in
                --password) IS_PASSWORD=1 ;;
                --value|--placeholder|--prompt|--char-limit|--width) PREV_FLAG="$arg"; SKIP_NEXT=1 ;;
                *) ;;
            esac
        done
        if [ "$IS_PASSWORD" = "1" ]; then
            echo "sk-test-key-12345"
        elif [ "$HAS_VALUE" = "1" ]; then
            echo "$VALUE"
        elif [ -n "$PLACEHOLDER" ]; then
            echo "$PLACEHOLDER"
        else
            echo "test-input"
        fi
        ;;
    confirm)
        exit 0
        ;;
    spin)
        # Find -- and run command after it
        while [ $# -gt 0 ]; do
            if [ "$1" = "--" ]; then shift; "$@"; exit $?; fi
            shift
        done
        ;;
    style)
        # Echo non-flag args
        SKIP_NEXT=0
        for arg in "$@"; do
            if [ "$SKIP_NEXT" = "1" ]; then SKIP_NEXT=0; continue; fi
            case "$arg" in
                --border|--border-foreground|--foreground|--padding|--margin) SKIP_NEXT=1 ;;
                --bold) ;;
                *) echo "$arg" ;;
            esac
        done
        ;;
    write)
        echo ""
        ;;
    *)
        ;;
esac
GUMEOF
chmod +x "$TEST_HOME/bin/gum"

# Mock curl — return success for telegram, failure code for API validation
cat > "$TEST_HOME/bin/curl" << 'CURLEOF'
#!/usr/bin/env bash
# Detect telegram getMe calls
for arg in "$@"; do
    if [[ "$arg" == *"api.telegram.org"* ]]; then
        echo '{"ok":true,"result":{"username":"test_bot"}}'
        exit 0
    fi
done
# For -w '%{http_code}' calls, output 200
for arg in "$@"; do
    if [[ "$arg" == "%{http_code}" ]]; then
        echo "200"
        exit 0
    fi
done
echo "{}"
CURLEOF
chmod +x "$TEST_HOME/bin/curl"

# Mock systemctl and openclaw
cat > "$TEST_HOME/bin/systemctl" << 'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$TEST_HOME/bin/systemctl"

cat > "$TEST_HOME/bin/openclaw" << 'EOF'
#!/bin/bash
exit 0
EOF
chmod +x "$TEST_HOME/bin/openclaw"

export PATH="$TEST_HOME/bin:$PATH"

# ============================================================
# 3. Pre-populate wizard state
# ============================================================
cat > "$PROJECT_DIR/.wizard-state.json" << 'STATEEOF'
{
  "version": 1,
  "config_mode": "recommended",
  "user": {"name": "TestUser", "preferred_name": "Testy", "domain": "Software Engineering", "current_work": "Building an AI system"},
  "brain": {"name": "Brain", "style": "balanced", "verbosity": "adaptive", "personality_notes": ""},
  "models": {"brain": "claude-sonnet-4", "builder": "deepseek-v3", "investigator": "qwen-max", "verifier": "qwen-max", "guardian": "claude-sonnet-4"},
  "providers": {"brain": "anthropic", "builder": "deepseek", "investigator": "alibaba", "verifier": "alibaba", "guardian": "anthropic"},
  "api_keys": {"anthropic": "sk-test-anthropic-key", "deepseek": "sk-test-deepseek-key", "alibaba": "sk-test-alibaba-key"},
  "memory_tier": "full",
  "embeddings": "local",
  "messaging": "telegram",
  "telegram_token": "1234567890:ABCDEFtest-token",
  "tools": ["web_search", "file_access", "code_execution"]
}
STATEEOF

# ============================================================
# 4. Override HOME and source utils
# ============================================================
export HOME="$TEST_HOME"

source "$PROJECT_DIR/wizard/utils.sh"

# Re-override after sourcing
export PROJECT_DIR
STATE_FILE="$PROJECT_DIR/.wizard-state.json"

# ============================================================
# 5. Run steps 3-10, then 11
# ============================================================
echo ""
echo "=== Running wizard steps 3-11 ==="
echo ""

# Steps 3-10 are interactive collection; since state is pre-populated,
# we still run them but they'll just re-confirm values via mock gum.
# Step 06 is problematic because mock gum choose returns first option text
# which may not parse to a valid model slug. Since state is pre-populated,
# let's skip steps that would overwrite good state with mock garbage.
# We run: 03 (config mode), 04 (user identity), 05 (brain personality),
# skip 06/07/09/10 (they need interactive choices that mock can't replicate well),
# run 08 (memory), and 11 (deploy - the big one that generates everything).

for step_num in 03 04 05 08 11; do
    STEP_FILE="$(ls "$PROJECT_DIR/wizard/steps/${step_num}_"*.sh 2>/dev/null | head -1)"
    if [ -z "$STEP_FILE" ]; then
        echo "⚠️  Step $step_num not found, skipping"
        continue
    fi
    echo "--- Running step $step_num: $(basename "$STEP_FILE") ---"
    source "$STEP_FILE" 2>&1 || echo "  ⚠️  Step $step_num had errors (may be non-fatal)"
    echo ""
done

# ============================================================
# 6. Verify outputs
# ============================================================
echo ""
echo "=== Verification ==="
echo ""

OC_WS="$TEST_HOME/.openclaw/workspace"
OC_AUTH="$TEST_HOME/.openclaw/agents/main/agent/auth-profiles.json"
OC_CONFIG="$TEST_HOME/.openclaw/openclaw.json"

check "USER.md exists" test -f "$OC_WS/USER.md"
check "USER.md contains TestUser" grep -q "TestUser" "$OC_WS/USER.md"
check "TEAM.md exists" test -f "$OC_WS/TEAM.md"
check "TEAM.md contains Software Engineering" grep -q "Software Engineering" "$OC_WS/TEAM.md"

check "Brain SOUL.md exists" test -f "$OC_WS/SOUL.md"
check "SOUL.md has locked layer" grep -q "LOCKED LAYER" "$OC_WS/SOUL.md"
check "SOUL.md has customizable layer" grep -q "CUSTOMIZABLE LAYER" "$OC_WS/SOUL.md"

check "agents/brain/SOUL.md exists" test -f "$OC_WS/agents/brain/SOUL.md"
check "agents/builder/SOUL.md exists" test -f "$OC_WS/agents/builder/SOUL.md"
check "agents/investigator/SOUL.md exists" test -f "$OC_WS/agents/investigator/SOUL.md"
check "agents/verifier/SOUL.md exists" test -f "$OC_WS/agents/verifier/SOUL.md"
check "agents/guardian/SOUL.md exists" test -f "$OC_WS/agents/guardian/SOUL.md"

check "AGENTS.md exists" test -f "$OC_WS/AGENTS.md"
check "AGENTS.md has delegation instructions" grep -q "Delegation Rules" "$OC_WS/AGENTS.md"

check "auth-profiles.json exists" test -f "$OC_AUTH"
check "auth-profiles.json has anthropic" jq -e '.profiles["anthropic:default"]' "$OC_AUTH"
check "auth-profiles.json has deepseek" jq -e '.profiles["deepseek:default"]' "$OC_AUTH"
check "auth-profiles.json has alibaba" jq -e '.profiles["alibaba:default"]' "$OC_AUTH"

check "openclaw.json exists" test -f "$OC_CONFIG"
check "openclaw.json has model config" jq -e '.agents.defaults.models.default' "$OC_CONFIG"
check "openclaw.json has telegram" jq -e '.channels.telegram.enabled' "$OC_CONFIG"

check "data/memory.db exists" test -f "$OC_WS/data/memory.db"
check "data/messages.db exists" test -f "$OC_WS/data/messages.db"

check "agents/ copied to workspace" test -d "$OC_WS/agents"
check "memory/ copied to workspace" test -d "$OC_WS/memory"

check ".gitignore contains .wizard-state.json" grep -q '.wizard-state.json' "$PROJECT_DIR/.gitignore"

# ============================================================
# 7. Report
# ============================================================
echo ""
echo "========================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================"
if [ $FAIL -gt 0 ]; then
    echo ""
    echo "  Failures:"
    for f in "${FAILURES[@]}"; do
        echo "    - $f"
    done
fi

exit $FAIL
