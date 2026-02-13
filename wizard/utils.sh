#!/usr/bin/env bash
# ============================================================================
# Wizard Utilities — Shared functions for all wizard steps
# ============================================================================

# --- Paths ---
WIZARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$WIZARD_DIR/.." && pwd)"
STATE_FILE="$PROJECT_DIR/.wizard-state.json"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# --- Logging ---
log_info()  { echo -e "${CYAN}ℹ ${RESET} $*"; }
log_ok()    { echo -e "${GREEN}✅${RESET}  $*"; }
log_warn()  { echo -e "${YELLOW}⚠ ${RESET} $*"; }
log_error() { echo -e "${RED}❌${RESET} $*"; }

# --- gum Wrappers ---

# Display a styled header for a wizard step
wizard_header() {
    local step_num="$1"
    local title="$2"
    local subtitle="${3:-}"
    echo ""
    gum style \
        --border rounded \
        --border-foreground 212 \
        --padding "1 3" \
        --margin "0 2" \
        --bold \
        "Step $step_num: $title" \
        "$subtitle"
    echo ""
}

# Display a section divider
wizard_divider() {
    echo ""
    gum style --foreground 240 "────────────────────────────────────────"
    echo ""
}

# Ask user to confirm before proceeding
wizard_confirm() {
    local prompt="${1:-Continue?}"
    gum confirm "$prompt"
}

# Text input with optional default and placeholder
wizard_input() {
    local prompt="$1"
    local placeholder="${2:-}"
    local default_val="${3:-}"
    local args=(--prompt "$prompt " --placeholder "$placeholder")
    if [ -n "$default_val" ]; then
        args+=(--value "$default_val")
    fi
    gum input "${args[@]}"
}

# Password/masked input
wizard_password() {
    local prompt="$1"
    gum input --prompt "$prompt " --password
}

# Multi-line text input
wizard_write() {
    local placeholder="${1:-}"
    local default_val="${2:-}"
    local args=(--placeholder "$placeholder")
    if [ -n "$default_val" ]; then
        args+=(--value "$default_val")
    fi
    gum write "${args[@]}"
}

# Single choice selection
wizard_choose() {
    local header="${1:-}"
    shift
    if [ -n "$header" ]; then
        gum style --foreground 212 "$header"
    fi
    gum choose "$@"
}

# Multi-select
wizard_choose_multi() {
    local header="${1:-}"
    shift
    if [ -n "$header" ]; then
        gum style --foreground 212 "$header"
    fi
    gum choose --no-limit "$@"
}

# Spinner while running a command
wizard_spin() {
    local title="$1"
    shift
    gum spin --spinner dot --title "$title" -- "$@"
}

# Display a success banner
wizard_success() {
    local message="$1"
    gum style \
        --foreground 2 \
        --border rounded \
        --border-foreground 2 \
        --padding "1 3" \
        --margin "0 2" \
        "✅ $message"
}

# Display an error banner
wizard_fail() {
    local message="$1"
    gum style \
        --foreground 1 \
        --border rounded \
        --border-foreground 1 \
        --padding "1 3" \
        --margin "0 2" \
        "❌ $message"
}

# --- State Management ---

# Initialize state file if it doesn't exist
state_init() {
    if [ ! -f "$STATE_FILE" ]; then
        echo '{"version":1}' > "$STATE_FILE"
    fi
}

# Read a value from state (dot notation: "user.name")
state_get() {
    local key="$1"
    local default="${2:-}"
    if [ ! -f "$STATE_FILE" ]; then
        echo "$default"
        return
    fi
    local val
    val="$(jq -r ".$key // empty" "$STATE_FILE" 2>/dev/null)" || true
    if [ -z "$val" ] || [ "$val" = "null" ]; then
        echo "$default"
    else
        echo "$val"
    fi
}

# Write a value to state
state_set() {
    local key="$1"
    local value="$2"
    state_init
    local tmp
    tmp="$(mktemp)"
    jq --arg v "$value" ".$key = \$v" "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
}

# Write a JSON object/array to state
state_set_json() {
    local key="$1"
    local json_value="$2"
    state_init
    local tmp
    tmp="$(mktemp)"
    jq --argjson v "$json_value" ".$key = \$v" "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
}

# Save timestamp to state
state_save_timestamp() {
    state_set "timestamp" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

# --- Dependency Checks ---

# Check if a command exists
has_cmd() {
    command -v "$1" &>/dev/null
}

# Get version number from a command (extracts first semver-like match)
get_version() {
    local cmd="$1"
    shift
    "$cmd" "$@" 2>&1 | grep -oP '\d+\.\d+(\.\d+)?' | head -1
}

# Compare semver: returns 0 if $1 >= $2
version_gte() {
    local v1="$1" v2="$2"
    [ "$(printf '%s\n' "$v2" "$v1" | sort -V | head -1)" = "$v2" ]
}

# --- OS Detection ---

detect_pkg_manager() {
    if has_cmd apt-get; then
        echo "apt"
    elif has_cmd dnf; then
        echo "dnf"
    elif has_cmd yum; then
        echo "yum"
    elif has_cmd pacman; then
        echo "pacman"
    elif has_cmd brew; then
        echo "brew"
    else
        echo "unknown"
    fi
}

# --- Misc ---

# Check if running in reconfigure mode
is_reconfigure() {
    [ "${RECONFIGURE:-0}" = "1" ]
}

# Check if recommended mode
is_recommended() {
    [ "$(state_get 'config_mode')" = "recommended" ]
}
