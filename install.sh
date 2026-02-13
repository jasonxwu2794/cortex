#!/usr/bin/env bash
# ============================================================================
# Memory-Enhanced Multi-Agent System — Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/jasonxwu2794/MemoryEnhancedMultiAgent/main/install.sh | bash
# ============================================================================
set -euo pipefail

REPO_URL="https://github.com/jasonxwu2794/MemoryEnhancedMultiAgent.git"
INSTALL_DIR="${INSTALL_DIR:-$HOME/MemoryEnhancedMultiAgent}"
GUM_VERSION="0.14.5"

# --- Colors (fallback before gum is available) ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { echo -e "${CYAN}ℹ${RESET}  $*"; }
ok()    { echo -e "${GREEN}✅${RESET} $*"; }
warn()  { echo -e "${YELLOW}⚠${RESET}  $*"; }
fail()  { echo -e "${RED}❌${RESET} $*"; exit 1; }

# --- Banner ---
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   Memory-Enhanced Multi-Agent System Installer   ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
echo ""

# --- Step 0: Ensure git and curl exist (needed to bootstrap) ---
for cmd in git curl; do
    if ! command -v $cmd &>/dev/null; then
        info "Installing $cmd..."
        if command -v apt-get &>/dev/null; then
            sudo apt-get update -qq && sudo apt-get install -y -qq $cmd
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y $cmd
        else
            fail "$cmd is required. Please install it manually."
        fi
    fi
done

# --- Step 1: Clone or update the repo ---
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Repository found at $INSTALL_DIR — updating..."
    cd "$INSTALL_DIR"
    git pull --ff-only || warn "Git pull failed — continuing with existing version"
else
    info "Cloning repository..."
    git clone "$REPO_URL" "$INSTALL_DIR" || fail "Failed to clone repository"
    cd "$INSTALL_DIR"
fi

ok "Repository ready at $INSTALL_DIR"

# --- Step 2: Install gum if missing ---
install_gum() {
    local arch
    arch="$(uname -m)"
    local os
    os="$(uname -s | tr '[:upper:]' '[:lower:]')"

    case "$arch" in
        x86_64)  arch="amd64" ;;
        aarch64|arm64) arch="arm64" ;;
        *) fail "Unsupported architecture: $arch" ;;
    esac

    case "$os" in
        linux)  os="Linux" ;;
        darwin) os="Darwin" ;;
        *) fail "Unsupported OS: $os" ;;
    esac

    local url="https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/gum_${GUM_VERSION}_${os}_${arch}.tar.gz"
    local tmp
    tmp="$(mktemp -d)"

    info "Downloading gum v${GUM_VERSION} for ${os}/${arch}..."
    curl -fsSL "$url" -o "$tmp/gum.tar.gz" || fail "Failed to download gum"
    tar -xzf "$tmp/gum.tar.gz" -C "$tmp" || fail "Failed to extract gum"

    # Install to /usr/local/bin or fall back to ~/.local/bin
    if [ -w /usr/local/bin ]; then
        cp "$tmp/gum" /usr/local/bin/gum
        chmod +x /usr/local/bin/gum
    else
        mkdir -p "$HOME/.local/bin"
        cp "$tmp/gum" "$HOME/.local/bin/gum"
        chmod +x "$HOME/.local/bin/gum"
        export PATH="$HOME/.local/bin:$PATH"
        warn "Installed gum to ~/.local/bin — make sure it's in your PATH"
    fi

    rm -rf "$tmp"
    ok "gum v${GUM_VERSION} installed"
}

if command -v gum &>/dev/null; then
    ok "gum already installed ($(gum --version 2>/dev/null || echo 'unknown version'))"
else
    info "gum not found — installing..."
    install_gum
fi

# Verify gum works
command -v gum &>/dev/null || fail "gum installation failed. Please install manually: https://github.com/charmbracelet/gum"

# --- Step 3: Launch the wizard ---
echo ""
info "Launching setup wizard..."
echo ""

chmod +x "$INSTALL_DIR/wizard/wizard.sh"
exec bash "$INSTALL_DIR/wizard/wizard.sh" "$@"
