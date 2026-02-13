#!/usr/bin/env python3
"""
Idea Surfacer — Weekly pattern analysis that suggests ideas for the backlog.

Runs weekly via cron (Monday). Also importable for on-demand use.

Usage:
    python3 -m scripts.idea_surfacer
    from scripts.idea_surfacer import surface_ideas, notify_ideas
"""

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Resolve workspace root
WORKSPACE = Path(__file__).resolve().parent.parent
DATA_DIR = WORKSPACE / "data"
MEMORY_DB = DATA_DIR / "memory.db"
PROJECTS_DB = DATA_DIR / "projects.db"

# Add workspace to path for imports
sys.path.insert(0, str(WORKSPACE))

logger = logging.getLogger(__name__)


def _dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _query(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
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


# ─── Pattern analysis ─────────────────────────────────────────────────────────

def _knowledge_graph_patterns() -> list[str]:
    """Find frequently referenced topics and related_to clusters."""
    patterns = []

    # Top related_to clusters
    rows = _query(
        MEMORY_DB,
        """SELECT m.content, COUNT(ml.memory_id_b) as link_count
           FROM memory_links ml
           JOIN memories m ON m.id = ml.memory_id_a
           WHERE ml.relation_type = 'related_to'
           GROUP BY ml.memory_id_a
           ORDER BY link_count DESC
           LIMIT 5""",
    )
    for r in rows:
        content_preview = r["content"][:100] if r["content"] else ""
        patterns.append(f"Frequently linked topic ({r['link_count']} connections): {content_preview}")

    # Recent high-importance memories
    rows = _query(
        MEMORY_DB,
        """SELECT content, tags FROM memories
           WHERE importance >= 0.7
           ORDER BY created_at DESC
           LIMIT 10""",
    )
    for r in rows:
        tags = r.get("tags", "") or ""
        patterns.append(f"High-importance: {r['content'][:80]} [tags: {tags}]")

    return patterns


def _dropped_threads() -> list[str]:
    """Find topics mentioned in memories but not tracked as projects/tasks."""
    threads = []

    # Get recent memory topics (last 2 weeks)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    memories = _query(
        MEMORY_DB,
        "SELECT content, tags FROM memories WHERE created_at >= ? ORDER BY importance DESC LIMIT 20",
        (cutoff,),
    )

    # Get existing project/idea names
    projects = _query(PROJECTS_DB, "SELECT name FROM projects")
    ideas = _query(PROJECTS_DB, "SELECT title FROM ideas WHERE status = 'backlog'")
    existing = {p["name"].lower() for p in projects} | {i["title"].lower() for i in ideas}

    for mem in memories:
        content = mem["content"][:120] if mem["content"] else ""
        # Simple heuristic: if content mentions building/creating something not in projects
        lower = content.lower()
        if any(kw in lower for kw in ["should", "could", "want to", "need to", "idea", "improve"]):
            if not any(name in lower for name in existing if name):
                threads.append(f"Untracked mention: {content}")

    return threads[:5]


def _tech_stack_suggestions() -> list[str]:
    """Check TEAM.md for common improvement patterns."""
    suggestions = []
    team_md = WORKSPACE / "TEAM.md"
    if not team_md.exists():
        return suggestions

    content = team_md.read_text().lower()

    checks = [
        ("express", "rate limiting", "Express app without rate limiting — consider express-rate-limit"),
        ("fastapi", "cors", "FastAPI without CORS config mentioned — review CORS setup"),
        ("react", "testing", "React project without testing mentioned — consider React Testing Library"),
        ("node", "typescript", "Node.js without TypeScript — consider migrating for type safety"),
        ("python", "type hints", "Python without type hints mentioned — consider mypy/pyright"),
        ("sqlite", "backup", "SQLite without backup strategy — consider WAL mode + daily backups"),
        ("api", "authentication", "API without auth mentioned — consider JWT/OAuth2"),
        ("docker", "health check", "Docker without health checks — add HEALTHCHECK instructions"),
    ]

    for tech, missing, suggestion in checks:
        if tech in content and missing not in content:
            suggestions.append(suggestion)

    return suggestions[:3]


# ─── Idea generation ──────────────────────────────────────────────────────────

async def _generate_ideas_with_llm(context: str) -> list[dict]:
    """Use LLM to generate 1-2 idea suggestions from collected context."""
    try:
        from agents.common.llm_client import LLMClient

        client = LLMClient(agent_name="idea_surfacer")
        result = await client.generate_json(
            system="You are an AI project idea generator. Given context about a user's work patterns, knowledge graph, and tech stack, suggest 1-2 concrete, actionable project ideas. Return JSON: {\"ideas\": [{\"title\": \"...\", \"description\": \"...\", \"domain\": \"...\"}]}",
            prompt=f"Based on this analysis of the user's recent work and patterns, suggest 1-2 ideas:\n\n{context}",
            temperature=0.8,
            max_tokens=1024,
        )

        if result.get("error"):
            logger.warning(f"LLM error: {result.get('message')}")
            return []

        content = result.get("content", {})
        if isinstance(content, dict):
            return content.get("ideas", [])
        return []

    except Exception as e:
        logger.error(f"Failed to generate ideas via LLM: {e}")
        return []


def _add_ideas_to_backlog(ideas: list[dict]) -> list[str]:
    """Add ideas to the project manager backlog. Returns list of titles added."""
    try:
        from agents.brain.project_manager import ProjectManager
        pm = ProjectManager(db_path=str(PROJECTS_DB))
        titles = []
        for idea in ideas:
            title = idea.get("title", "Untitled idea")
            desc = idea.get("description", "")
            domain = idea.get("domain")
            # Tag as auto-suggested
            desc_tagged = f"{desc}\n\nsource: auto-suggested"
            pm.add_idea(title=title, description=desc_tagged, domain=domain)
            titles.append(title)
        return titles
    except Exception as e:
        logger.error(f"Failed to add ideas to backlog: {e}")
        return []


# ─── Public API ───────────────────────────────────────────────────────────────

def surface_ideas() -> list[dict]:
    """
    Analyze patterns and generate idea suggestions.
    Returns list of idea dicts with title, description, domain.
    """
    # Collect context
    sections = []

    patterns = _knowledge_graph_patterns()
    if patterns:
        sections.append("Knowledge graph patterns:\n" + "\n".join(f"- {p}" for p in patterns))

    threads = _dropped_threads()
    if threads:
        sections.append("Dropped threads (mentioned but untracked):\n" + "\n".join(f"- {t}" for t in threads))

    tech = _tech_stack_suggestions()
    if tech:
        sections.append("Tech stack improvements:\n" + "\n".join(f"- {t}" for t in tech))

    if not sections:
        logger.info("No patterns found to generate ideas from")
        return []

    context = "\n\n".join(sections)

    # Generate ideas via LLM
    ideas = asyncio.run(_generate_ideas_with_llm(context))

    if not ideas:
        # Fallback: use tech suggestions directly as ideas
        ideas = []
        for suggestion in tech[:2]:
            ideas.append({
                "title": suggestion.split("—")[0].strip() if "—" in suggestion else suggestion[:60],
                "description": suggestion,
                "domain": "DevOps",
            })

    return ideas


def notify_ideas(ideas: list[dict], titles: list[str]) -> None:
    """Send notification about new ideas to messaging."""
    if not titles:
        return

    count = len(titles)
    title_list = ", ".join(titles)
    message = f"💡 I added {count} idea(s) to your backlog: {title_list}. Review with /ideas"

    # Try OpenClaw messaging
    try:
        result = subprocess.run(
            ["openclaw", "message", "send", "--message", message],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"[idea_surfacer] Notification sent via OpenClaw")
            return
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: stdout
    print(message)


def run():
    """Full pipeline: surface ideas → add to backlog → notify."""
    print(f"[idea_surfacer] Running at {datetime.now(timezone.utc).isoformat()}")

    ideas = surface_ideas()
    if not ideas:
        print("[idea_surfacer] No ideas generated this cycle")
        return

    titles = _add_ideas_to_backlog(ideas)
    if titles:
        print(f"[idea_surfacer] Added {len(titles)} idea(s): {', '.join(titles)}")
        notify_ideas(ideas, titles)
    else:
        print("[idea_surfacer] Failed to add ideas to backlog")


if __name__ == "__main__":
    run()
