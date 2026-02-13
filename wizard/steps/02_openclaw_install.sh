#!/usr/bin/env bash
# ============================================================================
# Step 2: OpenClaw Installation
# Install openclaw via npm, set up systemd service, verify gateway.
# ============================================================================

wizard_header "2" "OpenClaw Installation" "Installing the agent orchestration layer..."

# --- Check if already installed ---
if has_cmd openclaw; then
    CURRENT_VER="$(openclaw --version 2>/dev/null || echo 'unknown')"
    log_ok "OpenClaw already installed (v$CURRENT_VER)"

    if ! wizard_confirm "Reinstall/upgrade OpenClaw?"; then
        log_info "Keeping current installation"
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

# --- Set up systemd service ---
if [ -d /etc/systemd/system ] && has_cmd systemctl; then
    log_info "Setting up systemd service..."

    OPENCLAW_BIN="$(which openclaw)"

    sudo tee /etc/systemd/system/openclaw.service > /dev/null << EOF
[Unit]
Description=OpenClaw Agent Gateway
After=network.target

[Service]
Type=simple
ExecStart=$OPENCLAW_BIN gateway start
Restart=on-failure
RestartSec=5
Environment=HOME=$HOME
WorkingDirectory=$PROJECT_DIR

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable openclaw.service
    sudo systemctl start openclaw.service

    # Brief pause to let gateway start
    sleep 3

    # Verify gateway
    if systemctl is-active --quiet openclaw.service; then
        log_ok "OpenClaw service running"
    else
        log_warn "Service may still be starting — will verify later"
    fi
else
    log_info "systemd not available — you'll need to start OpenClaw manually:"
    gum style --foreground 212 --padding "0 2" "openclaw gateway start"
fi

wizard_success "OpenClaw installation complete!"
state_set "openclaw_installed" "true"
