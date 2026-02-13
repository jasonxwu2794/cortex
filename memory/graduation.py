"""Knowledge graduation system.

Manages the lifecycle of knowledge cache facts:
- Promotion: frequently accessed, old facts get higher confidence
- Decay: stale, unused facts lose confidence
- Re-verification flagging: low-confidence facts get flagged
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add graduation columns if they don't exist."""
    cursor = conn.execute("PRAGMA table_info(knowledge_cache)")
    columns = {row[1] for row in cursor.fetchall()}
    if "last_accessed_at" not in columns:
        conn.execute("ALTER TABLE knowledge_cache ADD COLUMN last_accessed_at TIMESTAMP")
    if "access_count" not in columns:
        conn.execute("ALTER TABLE knowledge_cache ADD COLUMN access_count INTEGER DEFAULT 0")
    conn.commit()


def run_graduation(db_path: str | Path) -> dict:
    """Run graduation rules on all knowledge cache facts.

    Returns summary: {promoted: N, decayed: N, flagged_for_reverify: N}
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _ensure_columns(conn)

    now = datetime.utcnow()
    promoted = 0
    decayed = 0
    flagged_for_reverify = 0

    rows = conn.execute(
        "SELECT id, fact, confidence, metadata, access_count, last_accessed_at, verified_at "
        "FROM knowledge_cache"
    ).fetchall()

    for row in rows:
        fact_id = row["id"]
        confidence = row["confidence"] or 0.8
        access_count = row["access_count"] or 0
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        verified_at = row["verified_at"]
        last_accessed_at = row["last_accessed_at"]

        # Calculate age from verified_at or fall back to now
        if verified_at:
            try:
                age = now - datetime.fromisoformat(verified_at)
            except (ValueError, TypeError):
                age = timedelta(days=0)
        else:
            age = timedelta(days=0)

        # Calculate time since last access
        if last_accessed_at:
            try:
                since_access = now - datetime.fromisoformat(last_accessed_at)
            except (ValueError, TypeError):
                since_access = timedelta(days=999)
        else:
            since_access = timedelta(days=999)

        has_contradictions = metadata.get("contradicted", False)
        new_confidence = confidence
        action = None

        # Skip permanent facts
        if confidence >= 1.0:
            continue

        # Promotion: permanent (confidence 1.0)
        if (access_count >= 10 and age.days > 90 and not has_contradictions):
            new_confidence = 1.0
            action = "promoted_permanent"
            promoted += 1
        # Promotion: well-established (confidence 0.95)
        elif (access_count >= 3 and age.days > 30 and not has_contradictions
              and confidence < 0.95):
            new_confidence = 0.95
            action = "promoted_established"
            promoted += 1
        # Decay: not accessed in 180 days
        elif since_access.days > 180 and confidence < 1.0:
            new_confidence = round(max(0.0, confidence - 0.1), 2)
            action = "decayed"
            decayed += 1

        # Flag for re-verification if confidence dropped below 0.5
        if new_confidence < 0.5:
            metadata["needs_reverify"] = True
            flagged_for_reverify += 1
            action = "flagged_reverify"

        # Update if changed
        if new_confidence != confidence or action:
            meta_str = json.dumps(metadata)
            conn.execute(
                "UPDATE knowledge_cache SET confidence = ?, metadata = ? WHERE id = ?",
                (new_confidence, meta_str, fact_id),
            )
            log.info(
                "Graduation: fact %s — %s (confidence %.2f → %.2f, access_count=%d, age=%dd)",
                fact_id, action, confidence, new_confidence, access_count, age.days,
            )

    conn.commit()
    conn.close()

    summary = {
        "promoted": promoted,
        "decayed": decayed,
        "flagged_for_reverify": flagged_for_reverify,
    }
    log.info("Graduation complete: %s", summary)
    return summary
