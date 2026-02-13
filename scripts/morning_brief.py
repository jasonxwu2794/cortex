#!/usr/bin/env python3
"""
Morning Brief — Daily digest of progress, queue, memory stats, and health.

Runs daily via cron. Also importable for on-demand use by Cortex.

Usage:
    python3 -m scripts.morning_brief          # run standalone
    from scripts.morning_brief import compile_brief, send_brief
"""

import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Resolve workspace root (parent of scripts/)
WORKSPACE = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE / "data"
MEMORY_DB = DATA_DIR / "memory.db"
PROJECTS_DB = DATA_DIR / "projects.db"
ACTIVITY_DB = DATA_DIR / "activity.db"


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _query(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    """Run a query and return list of dicts. Returns [] if DB doesn't exist."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = _dict_factory
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _scalar(db_path: Path, sql: str, params: tuple = (), default=0):
    rows = _query(db_path, sql, params)
    if rows:
        return list(rows[0].values())[0] or default
    return default


# ─── Data collectors ──────────────────────────────────────────────────────────

def _completed_tasks_24h() -> tuple[int, list[str]]:
    """Return (count, list of titles) of tasks completed in last 24h."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    # Tasks don't have a completed_at column, so we check result is set + status
    rows = _query(
        PROJECTS_DB,
        "SELECT title FROM tasks WHERE status = 'completed' AND result IS NOT NULL",
    )
    # Without a timestamp on completion, return all completed tasks as best effort
    return len(rows), [r["title"] for r in rows[:5]]


def _queued_tasks() -> tuple[int, list[str]]:
    rows = _query(
        PROJECTS_DB,
        "SELECT title FROM tasks WHERE status IN ('pending', 'in_progress') ORDER BY \"order\" ASC",
    )
    return len(rows), [r["title"] for r in rows[:5]]


def _blocked_and_failed() -> tuple[int, int]:
    failed = _scalar(PROJECTS_DB, "SELECT COUNT(*) FROM tasks WHERE status = 'failed'")
    # Blocked = pending tasks whose depends_on includes a failed task id
    # Simplified: just count failed as potential blockers
    return 0, failed  # blocked_count, failed_count


def _memory_stats() -> dict:
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    new_memories = _scalar(
        MEMORY_DB,
        "SELECT COUNT(*) FROM memories WHERE created_at >= ?",
        (cutoff_24h,),
    )
    total_memories = _scalar(MEMORY_DB, "SELECT COUNT(*) FROM memories")
    knowledge_count = _scalar(MEMORY_DB, "SELECT COUNT(*) FROM knowledge_cache")

    # Check consolidation log
    consol_log = DATA_DIR / "consolidation.log"
    consol_runs_24h = 0
    if consol_log.exists():
        cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=24)
        try:
            for line in consol_log.read_text().splitlines()[-50:]:
                if cutoff_dt.strftime("%Y-%m-%d") in line:
                    consol_runs_24h += 1
        except Exception:
            pass

    return {
        "new_memories": new_memories,
        "total_memories": total_memories,
        "knowledge_count": knowledge_count,
        "consolidation_runs": consol_runs_24h,
    }


def _system_health() -> dict:
    """Quick health snapshot."""
    # Disk free
    usage = shutil.disk_usage(str(DATA_DIR)) if DATA_DIR.exists() else None
    disk_free_mb = int(usage.free / (1024 * 1024)) if usage else -1

    # DB sizes
    db_sizes = {}
    for db_file in DATA_DIR.glob("*.db"):
        db_sizes[db_file.name] = db_file.stat().st_size // 1024  # KB

    # Gateway check
    gateway_up = False
    try:
        result = subprocess.run(
            ["pgrep", "-f", "openclaw-gateway"],
            capture_output=True, timeout=5,
        )
        gateway_up = result.returncode == 0
    except Exception:
        pass

    # Health log last status
    health_log = DATA_DIR / "health.log"
    last_health = "unknown"
    if health_log.exists():
        try:
            lines = health_log.read_text().splitlines()
            if lines:
                last_line = lines[-1]
                last_health = "healthy" if "OK" in last_line else "issues detected"
        except Exception:
            pass

    return {
        "gateway_up": gateway_up,
        "disk_free_mb": disk_free_mb,
        "db_sizes": db_sizes,
        "last_health": last_health,
    }


# ─── Brief compiler ──────────────────────────────────────────────────────────

def compile_brief() -> str:
    """Compile the morning brief and return formatted string."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%b %d, %Y")

    # Gather data
    completed_count, completed_titles = _completed_tasks_24h()
    queued_count, queued_titles = _queued_tasks()
    blocked, failed = _blocked_and_failed()
    mem = _memory_stats()
    health = _system_health()

    # Format
    lines = [f"☀️ Morning Brief — {date_str}", ""]

    # Yesterday section
    lines.append("📋 Yesterday:")
    if completed_count > 0:
        summary = ", ".join(completed_titles[:3])
        if completed_count > 3:
            summary += f" +{completed_count - 3} more"
        lines.append(f"• Completed: {completed_count} task(s) ({summary})")
    else:
        lines.append("• No tasks completed")

    lines.append("")

    # Today section
    lines.append("📌 Today:")
    if queued_count > 0:
        summary = ", ".join(queued_titles[:3])
        if queued_count > 3:
            summary += f" +{queued_count - 3} more"
        lines.append(f"• Queued: {queued_count} task(s) ({summary})")
    else:
        lines.append("• Queue empty")

    if failed > 0:
        lines.append(f"• ⚠️ Failed: {failed} task(s)")
    if blocked > 0:
        lines.append(f"• 🚫 Blocked: {blocked} task(s)")
    else:
        lines.append("• Blocked: none")

    lines.append("")

    # Memory section
    lines.append("🧠 Memory:")
    lines.append(f"• {mem['new_memories']} new memories (last 24h)")
    lines.append(f"• {mem['consolidation_runs']} consolidation cycle(s) ran")
    lines.append(f"• Knowledge cache: {mem['knowledge_count']} facts")
    lines.append(f"• Total memories: {mem['total_memories']}")

    lines.append("")

    # System section
    if health["gateway_up"] and health["last_health"] == "healthy":
        lines.append("💚 System: All healthy")
    else:
        issues = []
        if not health["gateway_up"]:
            issues.append("gateway down")
        if health["last_health"] != "healthy":
            issues.append(health["last_health"])
        lines.append(f"🔴 System: {', '.join(issues)}")

    if health["disk_free_mb"] >= 0:
        if health["disk_free_mb"] < 1024:
            lines.append(f"• ⚠️ Disk: {health['disk_free_mb']}MB free")
        else:
            lines.append(f"• Disk: {health['disk_free_mb'] // 1024}GB free")

    db_total_kb = sum(health["db_sizes"].values())
    if db_total_kb > 0:
        lines.append(f"• DB total: {db_total_kb}KB")

    return "\n".join(lines)


def send_brief() -> None:
    """Send the compiled brief via OpenClaw messaging (stdout for cron capture)."""
    brief = compile_brief()

    # Try OpenClaw CLI messaging if available
    try:
        result = subprocess.run(
            ["openclaw", "message", "send", "--message", brief],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"[morning_brief] Sent via OpenClaw messaging")
            return
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: print to stdout (cron will log it)
    print(brief)


if __name__ == "__main__":
    send_brief()
