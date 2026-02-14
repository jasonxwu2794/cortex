#!/usr/bin/env bash
# ============================================================================
# Step 1: Prerequisites Check
# Verify Python 3.10+, git, curl, Node.js 18+. Auto-install missing.
# ============================================================================

wizard_header "1" "Prerequisites Check" "Verifying system dependencies..."

# --- Define required dependencies ---
declare -A DEPS_STATUS
declare -A DEPS_VERSION
MISSING=()

check_dependency() {
    local name="$1" cmd="$2" min_ver="${3:-}" ver_args="${4:---version}"

    if ! has_cmd "$cmd"; then
        DEPS_STATUS[$name]="missing"
        DEPS_VERSION[$name]=""
        MISSING+=("$name")
        return
    fi

    if [ -n "$min_ver" ]; then
        local ver
        ver="$(get_version "$cmd" "$ver_args")" || ver=""
        DEPS_VERSION[$name]="$ver"
        if [ -n "$ver" ] && version_gte "$ver" "$min_ver"; then
            DEPS_STATUS[$name]="ok"
        else
            DEPS_STATUS[$name]="outdated"
            MISSING+=("$name")
        fi
    else
        DEPS_VERSION[$name]="$(get_version "$cmd" "$ver_args" 2>/dev/null || echo "installed")"
        DEPS_STATUS[$name]="ok"
    fi
}

# Run checks
check_dependency "Python 3.10+" "python3" "3.10" "--version"
check_dependency "git"          "git"     ""     "--version"
check_dependency "curl"         "curl"    ""     "--version"
check_dependency "Node.js 18+"  "node"    "18.0" "--version"

# --- Display results ---
results=""
for dep in "Python 3.10+" "git" "curl" "Node.js 18+"; do
    status="${DEPS_STATUS[$dep]}"
    ver="${DEPS_VERSION[$dep]}"
    case "$status" in
        ok)       results+="   ✅  $dep ($ver)\n" ;;
        missing)  results+="   ❌  $dep — not found\n" ;;
        outdated) results+="   ❌  $dep — found $ver, need newer\n" ;;
    esac
done

echo -e "$results"

# --- Install missing dependencies ---
if [ ${#MISSING[@]} -gt 0 ]; then
    log_warn "Missing dependencies: ${MISSING[*]}"
    echo ""

    if ! wizard_confirm "Install missing dependencies?"; then
        wizard_fail "Cannot continue without required dependencies."
        exit 1
    fi

    PKG_MGR="$(detect_pkg_manager)"
    log_info "Using package manager: $PKG_MGR"

    for dep in "${MISSING[@]}"; do
        case "$dep" in
            "Python 3.10+"*)
                case "$PKG_MGR" in
                    apt)    wizard_spin "Installing Python..." sh -c 'sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip' ;;
                    dnf)    wizard_spin "Installing Python..." sudo dnf install -y python3 python3-pip ;;
                    pacman) wizard_spin "Installing Python..." sudo pacman -Sy --noconfirm python python-pip ;;
                    brew)   wizard_spin "Installing Python..." brew install python@3.12 ;;
                    *)      log_error "Please install Python 3.10+ manually"; exit 1 ;;
                esac
                ;;
            "git")
                case "$PKG_MGR" in
                    apt)    wizard_spin "Installing git..." sudo apt-get install -y -qq git ;;
                    dnf)    wizard_spin "Installing git..." sudo dnf install -y git ;;
                    pacman) wizard_spin "Installing git..." sudo pacman -Sy --noconfirm git ;;
                    brew)   wizard_spin "Installing git..." brew install git ;;
                    *)      log_error "Please install git manually"; exit 1 ;;
                esac
                ;;
            "curl")
                case "$PKG_MGR" in
                    apt)    wizard_spin "Installing curl..." sudo apt-get install -y -qq curl ;;
                    dnf)    wizard_spin "Installing curl..." sudo dnf install -y curl ;;
                    pacman) wizard_spin "Installing curl..." sudo pacman -Sy --noconfirm curl ;;
                    brew)   wizard_spin "Installing curl..." brew install curl ;;
                    *)      log_error "Please install curl manually"; exit 1 ;;
                esac
                ;;
            "Node.js 18+"*)
                case "$PKG_MGR" in
                    apt)
                        wizard_spin "Installing Node.js 22.x..." bash -c "curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - > /tmp/node-install.log 2>&1 && sudo apt-get install -y -qq nodejs >> /tmp/node-install.log 2>&1"
                        ;;
                    dnf)
                        wizard_spin "Installing Node.js 22.x..." bash -c "curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo -E bash - > /tmp/node-install.log 2>&1 && sudo dnf install -y nodejs >> /tmp/node-install.log 2>&1"
                        ;;
                    pacman)
                        wizard_spin "Installing Node.js..." sudo pacman -Sy --noconfirm nodejs npm
                        ;;
                    brew)
                        wizard_spin "Installing Node.js..." brew install node
                        ;;
                    *)
                        log_error "Please install Node.js 18+ manually: https://nodejs.org"
                        exit 1
                        ;;
                esac
                ;;
        esac
    done

    # Re-check
    echo ""
    log_info "Re-checking dependencies..."
    RECHECK_FAIL=0
    for dep in "${MISSING[@]}"; do
        case "$dep" in
            "Python"*) has_cmd python3 || RECHECK_FAIL=1 ;;
            "git")     has_cmd git     || RECHECK_FAIL=1 ;;
            "curl")    has_cmd curl    || RECHECK_FAIL=1 ;;
            "Node.js"*)has_cmd node    || RECHECK_FAIL=1 ;;
        esac
    done

    if [ "$RECHECK_FAIL" = "1" ]; then
        wizard_fail "Some dependencies could not be installed. Please install them manually and re-run the wizard."
        exit 1
    fi

    wizard_success "All dependencies installed!"
else
    wizard_success "All dependencies satisfied!"
fi

# --- Ensure build tools are available (needed for Python packages with C extensions) ---
if command -v apt-get &>/dev/null; then
    if ! dpkg -l build-essential &>/dev/null 2>&1; then
        TOOLS_LOG="/tmp/build-tools-$$.log"
        wizard_spin "Installing build tools..." sh -c "sudo apt-get install -y -qq build-essential python3-dev jq > $TOOLS_LOG 2>&1"
        if [ $? -eq 0 ]; then
            log_ok "Build tools installed"
        else
            log_warn "Build tools had issues (non-critical)"
            cat "$TOOLS_LOG" 2>/dev/null
        fi
        rm -f "$TOOLS_LOG"
    fi
fi

# --- Ensure pip is available (Ubuntu may have Python without pip) ---
if ! python3 -m pip --version &>/dev/null; then
    if command -v apt-get &>/dev/null; then
        wizard_spin "Installing pip..." sh -c "sudo apt-get install -y -qq python3-pip 2>/dev/null"
    fi
    # Fallback: ensurepip
    if ! python3 -m pip --version &>/dev/null; then
        python3 -m ensurepip --upgrade 2>/dev/null || log_warn "Could not install pip — some features may not work"
    fi
fi

state_set "prerequisites_done" "true"
