#!/usr/bin/env bash
# Log rotation with metrics harvesting — runs weekly via cron
set -euo pipefail

WORKSPACE="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$WORKSPACE/data"
METRICS_FILE="$DATA_DIR/metrics.json"
TIMESTAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
PERIOD_END="$(date -u '+%Y-%m-%d')"

log() { echo "$TIMESTAMP [rotate] $1"; }

# Initialize metrics file if missing
if [ ! -f "$METRICS_FILE" ]; then
    echo '[]' > "$METRICS_FILE"
fi

# --- Harvest from consolidation.log ---
CONSOL_LOG="$DATA_DIR/consolidation.log"
CONSOLIDATIONS=0
MEMORIES_CONSOLIDATED=0
MEMORIES_PRUNED=0

if [ -f "$CONSOL_LOG" ]; then
    CONSOLIDATIONS=$(grep -c "Consolidation complete" "$CONSOL_LOG" 2>/dev/null || echo 0)
    MEMORIES_CONSOLIDATED=$(grep -oP 'consolidated=\K[0-9]+' "$CONSOL_LOG" 2>/dev/null | awk '{s+=$1}END{print s+0}')
    MEMORIES_PRUNED=$(grep -oP 'pruned=\K[0-9]+' "$CONSOL_LOG" 2>/dev/null | awk '{s+=$1}END{print s+0}')
fi

# --- Harvest from health.log ---
HEALTH_LOG="$DATA_DIR/health.log"
TOTAL_CHECKS=0
HEALTHY_CHECKS=0
RESTARTS=0
UPTIME_PCT=100.0

if [ -f "$HEALTH_LOG" ]; then
    TOTAL_CHECKS=$(grep -c '\[health\]' "$HEALTH_LOG" 2>/dev/null || echo 0)
    HEALTHY_CHECKS=$(grep -c '\[health\] OK' "$HEALTH_LOG" 2>/dev/null || echo 0)
    RESTARTS=$(grep -c 'restart' "$HEALTH_LOG" 2>/dev/null || echo 0)
    if [ "$TOTAL_CHECKS" -gt 0 ]; then
        UPTIME_PCT=$(python3 -c "print(round($HEALTHY_CHECKS / $TOTAL_CHECKS * 100, 1))" 2>/dev/null || echo "100.0")
    fi
fi

# --- Append metrics entry ---
python3 -c "
import json, sys
metrics_file = '$METRICS_FILE'
entry = {
    'period_end': '$PERIOD_END',
    'consolidations': $CONSOLIDATIONS,
    'memories_consolidated': $MEMORIES_CONSOLIDATED,
    'memories_pruned': $MEMORIES_PRUNED,
    'uptime_pct': $UPTIME_PCT,
    'restarts': $RESTARTS
}
try:
    with open(metrics_file) as f:
        data = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    data = []
data.append(entry)
with open(metrics_file, 'w') as f:
    json.dump(data, f, indent=2)
print(f'Metrics appended: {json.dumps(entry)}')
"

log "Metrics harvested for period ending $PERIOD_END"

# --- Trim logs to last 1000 lines ---
for logfile in "$CONSOL_LOG" "$HEALTH_LOG" "$DATA_DIR/backup.log" "$DATA_DIR/rotation.log"; do
    if [ -f "$logfile" ]; then
        LINES=$(wc -l < "$logfile")
        if [ "$LINES" -gt 1000 ]; then
            tail -1000 "$logfile" > "${logfile}.tmp" && mv "${logfile}.tmp" "$logfile"
            log "Trimmed $(basename "$logfile") from $LINES to 1000 lines"
        fi
    fi
done

log "Log rotation complete"
