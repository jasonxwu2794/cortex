#!/usr/bin/env bash
# ============================================================================
# Step 2: OpenClaw Installation
# Install openclaw via npm, enable linger, verify gateway.
# ============================================================================

wizard_header "2" "OpenClaw Installation" "Installing the agent orchestration layer..."

# --- Check if already installed ---
if has_cmd openclaw; then
    CURRENT_VER="$(openclaw --version 2>/dev/null || echo 'unknown')"
    log_ok "OpenClaw already installed (v$CURRENT_VER)"

    if ! wizard_confirm "Reinstall/upgrade OpenClaw?"; then
        log_info "Keeping current installation"

        # Still enable linger
        if has_cmd loginctl; then
            loginctl enable-linger "$(whoami)" 2>/dev/null || true
            log_ok "Linger enabled (survives terminal disconnect)"
        fi

        state_set "openclaw_installed" "true"
        return 0 2>/dev/null || true
    fi
fi

# --- Install via npm ---
log_info "Installing OpenClaw via npm..."
wizard_spin "Installing openclaw globally..." npm install -g openclaw

if ! has_cmd openclaw; then
    wizard_fail "OpenClaw installation failed. Check npm permissions."
    exit 1
fi

log_ok "OpenClaw installed: $(openclaw --version 2>/dev/null || echo 'success')"

# --- Enable linger so gateway survives terminal disconnect ---
if has_cmd loginctl; then
    loginctl enable-linger "$(whoami)" 2>/dev/null || true
    log_ok "Linger enabled (survives terminal disconnect)"
fi

# --- Set up systemd user service (preferred) ---
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
if has_cmd systemctl; then
    log_info "Setting up systemd user service..."
    mkdir -p "$SYSTEMD_USER_DIR"

    OPENCLAW_BIN="$(which openclaw)"

    cat > "$SYSTEMD_USER_DIR/openclaw-gateway.service" << EOF
[Unit]
Description=OpenClaw Agent Gateway
After=network.target

[Service]
Type=simple
ExecStart=$OPENCLAW_BIN gateway start
Restart=on-failure
RestartSec=5
Environment=HOME=$HOME

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable openclaw-gateway.service 2>/dev/null || true
    log_ok "Systemd user service configured"
else
    log_info "systemd not available — you'll need to start OpenClaw manually:"
    gum style --foreground 212 --padding "0 2" "openclaw gateway start"
fi

# --- Install Aider (AI code editing tool) ---
log_info "Installing Aider (AI-powered code editor)..."
wizard_spin "Installing aider-chat..." python3 -m pip install --break-system-packages aider-chat 2>/dev/null || python3 -m pip install aider-chat

if has_cmd aider; then
    AIDER_VER="$(aider --version 2>/dev/null || echo 'installed')"
    log_ok "Aider installed: $AIDER_VER"
else
    log_warn "Aider installation may have failed — Builder will fall back to direct editing"
fi

state_set "aider_installed" "true"

wizard_success "OpenClaw installation complete!"
state_set "openclaw_installed" "true"
