#!/usr/bin/env bash
# Memory backup script — runs daily at 4am via cron
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$WORKSPACE/data"
BACKUP_DIR="$DATA_DIR/backups"
LOG_FILE="$DATA_DIR/backup.log"
TODAY="$(date -u '+%Y-%m-%d')"
TIMESTAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

mkdir -p "$BACKUP_DIR"

log() { echo "$TIMESTAMP [backup] $1" >> "$LOG_FILE"; }

# Backup memory.db
if [ -f "$DATA_DIR/memory.db" ]; then
    cp "$DATA_DIR/memory.db" "$BACKUP_DIR/memory-${TODAY}.db"
    log "OK backed up memory.db ($(du -h "$BACKUP_DIR/memory-${TODAY}.db" | cut -f1))"
else
    log "WARN memory.db not found — skipped"
fi

# Backup messages.db
if [ -f "$DATA_DIR/messages.db" ]; then
    cp "$DATA_DIR/messages.db" "$BACKUP_DIR/messages-${TODAY}.db"
    log "OK backed up messages.db ($(du -h "$BACKUP_DIR/messages-${TODAY}.db" | cut -f1))"
else
    log "WARN messages.db not found — skipped"
fi

# Delete backups older than 7 days
DELETED=$(find "$BACKUP_DIR" -name "*.db" -mtime +7 -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    log "INFO deleted $DELETED old backup(s)"
fi

# Log disk usage
USAGE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
log "INFO backup dir usage: $USAGE"
