#!/usr/bin/env bash
# Health check script — runs every 30 minutes via cron
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$WORKSPACE/data"
LOG_FILE="$DATA_DIR/health.log"
ISSUES=0
TIMESTAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

mkdir -p "$DATA_DIR"

log() { echo "$TIMESTAMP [health] $1" >> "$LOG_FILE"; }

# 1. Check OpenClaw gateway
GATEWAY_UP=false
if systemctl --user is-active --quiet openclaw-gateway.service 2>/dev/null; then
    GATEWAY_UP=true
elif pgrep -f openclaw-gateway >/dev/null 2>&1; then
    GATEWAY_UP=true
fi

if [ "$GATEWAY_UP" = true ]; then
    log "OK gateway running"
else
    log "WARN gateway DOWN — attempting restart"
    ISSUES=1
    if systemctl --user restart openclaw-gateway.service 2>/dev/null; then
        log "INFO gateway restarted via systemd"
    elif command -v openclaw >/dev/null 2>&1; then
        openclaw gateway restart 2>/dev/null || openclaw gateway start 2>/dev/null || true
        log "INFO gateway restart attempted via CLI"
    else
        log "ERROR could not restart gateway"
    fi
fi

# 2. Check memory DB
if python3 -c "import sqlite3; sqlite3.connect('$DATA_DIR/memory.db').execute('SELECT 1')" 2>/dev/null; then
    log "OK memory DB accessible"
else
    log "ERROR memory DB unreachable"
    ISSUES=1
fi

# 3. Disk space check (warn if <1GB free)
FREE_KB=$(df "$DATA_DIR" --output=avail 2>/dev/null | tail -1 | tr -d ' ' || echo "0")
FREE_MB=$((FREE_KB / 1024))
if [ "$FREE_MB" -lt 1024 ]; then
    log "WARN disk space low: ${FREE_MB}MB free"
    ISSUES=1
else
    log "OK disk space: ${FREE_MB}MB free"
fi

exit $ISSUES
