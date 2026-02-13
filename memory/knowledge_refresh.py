"""Knowledge refresh — flags stale facts for passive re-verification.

Monthly job that marks facts needing re-verification without proactively
burning API credits. Facts get re-checked next time Brain encounters a
related topic.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


def run_refresh(db_path: str | Path) -> dict:
    """Flag facts eligible for refresh.

    Eligible: confidence < 1.0 AND (age > 90 days AND accessed recently, OR needs_reverify)

    Returns summary: {flagged: N, already_permanent: N, skipped: N}
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    now = datetime.utcnow()
    flagged = 0
    already_permanent = 0
    skipped = 0

    rows = conn.execute(
        "SELECT id, confidence, metadata, verified_at, last_accessed_at "
        "FROM knowledge_cache"
    ).fetchall()

    for row in rows:
        fact_id = row["id"]
        confidence = row["confidence"] or 0.8
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}

        # Permanent facts are exempt
        if confidence >= 1.0:
            already_permanent += 1
            continue

        # Already flagged
        if metadata.get("needs_reverify"):
            skipped += 1
            continue

        verified_at = row["verified_at"]
        last_accessed_at = row["last_accessed_at"]

        # Calculate age
        if verified_at:
            try:
                age = now - datetime.fromisoformat(verified_at)
            except (ValueError, TypeError):
                age = timedelta(days=0)
        else:
            age = timedelta(days=0)

        # Recently accessed = within last 30 days
        recently_accessed = False
        if last_accessed_at:
            try:
                since_access = now - datetime.fromisoformat(last_accessed_at)
                recently_accessed = since_access.days <= 30
            except (ValueError, TypeError):
                pass

        # Flag if: old + recently accessed (user cares about this fact)
        should_flag = age.days > 90 and recently_accessed

        if should_flag:
            metadata["needs_reverify"] = True
            conn.execute(
                "UPDATE knowledge_cache SET metadata = ? WHERE id = ?",
                (json.dumps(metadata), fact_id),
            )
            flagged += 1
            log.info("Refresh: flagged fact %s for re-verification (age=%dd)", fact_id, age.days)
        else:
            skipped += 1

    conn.commit()
    conn.close()

    summary = {"flagged": flagged, "already_permanent": already_permanent, "skipped": skipped}
    log.info("Knowledge refresh complete: %s", summary)
    return summary
