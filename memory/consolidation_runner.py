#!/usr/bin/env python3
"""Standalone consolidation runner for cron execution.

Usage:
    python3 -m memory.consolidation_runner --db-path data/memory.db --tier full
    python3 -m memory.consolidation_runner --db-path data/memory.db --tier standard --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [consolidation] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Memory consolidation runner")
    parser.add_argument("--db-path", required=True, help="Path to memory SQLite database")
    parser.add_argument("--tier", choices=["full", "standard"], default="full", help="Memory tier")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be done without modifying DB")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    if not db_path.exists():
        log.error("Database not found: %s", db_path)
        return 1

    try:
        from memory.consolidation import run_consolidation

        log.info("Starting %s-tier consolidation on %s", args.tier, db_path)
        start = time.monotonic()
        summary = run_consolidation(str(db_path), tier=args.tier, dry_run=args.dry_run)
        elapsed = time.monotonic() - start

        log.info(
            "Consolidation complete in %.1fs — consolidated=%d clusters=%d pruned=%d",
            elapsed,
            summary.get("consolidated", 0),
            summary.get("clusters", 0),
            summary.get("pruned", 0),
        )
        if args.dry_run:
            log.info("(dry-run mode — no changes written)")
        else:
            # Run knowledge graduation after consolidation
            try:
                from memory.graduation import run_graduation

                grad_summary = run_graduation(str(db_path))
                log.info(
                    "Graduation complete — promoted=%d decayed=%d flagged=%d",
                    grad_summary.get("promoted", 0),
                    grad_summary.get("decayed", 0),
                    grad_summary.get("flagged_for_reverify", 0),
                )
            except Exception:
                log.exception("Graduation failed (non-fatal)")
        return 0
    except Exception:
        log.exception("Consolidation failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
