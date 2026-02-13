"""
Project Manager — Structured project management for Brain agent.

Manages projects with hierarchy: Project → Feature → Task.
Includes idea backlog with domain tagging.
Uses SQLite for persistence.
"""

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class Project:
    id: str
    name: str
    description: str
    spec: str
    status: str  # planning, in_progress, completed, paused
    created_at: datetime
    domain: Optional[str] = None  # "ML", "Web", "DevOps", etc.

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


@dataclass
class Idea:
    id: str
    title: str
    description: str
    domain: Optional[str]  # optional tag: "ML", "Web", "DevOps", etc.
    created_at: datetime
    status: str  # backlog, promoted, archived

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


@dataclass
class Feature:
    id: str
    project_id: str
    title: str
    description: str
    order: int
    status: str = "pending"  # pending, in_progress, completed
    tasks: list = field(default_factory=list)  # nested Task objects (not persisted here)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class Task:
    id: str
    feature_id: str  # belongs to a feature
    project_id: str  # kept for convenience
    title: str
    description: str
    agent: str  # builder, researcher, verifier, guardian
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, in_progress, completed, failed, skipped
    result: Optional[str] = None
    order: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["depends_on"] = json.dumps(self.depends_on)
        return d


@dataclass
class ProjectStatus:
    project_id: str
    project_name: str
    status: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    current_task: Optional[Task]
    blockers: list[str]

    @property
    def progress_pct(self) -> float:
        if self.total_tasks == 0:
            return 0.0
        return (self.completed_tasks / self.total_tasks) * 100


# ─── SQL Schema ───────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    spec TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planning',
    created_at TEXT NOT NULL,
    domain TEXT
);

CREATE TABLE IF NOT EXISTS ideas (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    domain TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'backlog'
);

CREATE TABLE IF NOT EXISTS features (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    "order" INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    feature_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT 'builder',
    depends_on TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    "order" INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (feature_id) REFERENCES features(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_feature ON tasks(feature_id);
CREATE INDEX IF NOT EXISTS idx_features_project ON features(project_id);
CREATE INDEX IF NOT EXISTS idx_ideas_status ON ideas(status);
"""

# Migration: add columns if missing (for existing DBs)
MIGRATIONS = [
    "ALTER TABLE projects ADD COLUMN domain TEXT",
    "ALTER TABLE tasks ADD COLUMN feature_id TEXT NOT NULL DEFAULT ''",
]

# ─── Project Detection Heuristics ─────────────────────────────────────────────

PROJECT_TRIGGERS = [
    "i want to build",
    "let's create",
    "let's build",
    "can you make",
    "can you build",
    "build me",
    "create a",
    "develop a",
    "i need an app",
    "i need a tool",
    "i need a system",
    "make me a",
    "help me build",
    "let's make",
    "start a project",
    "new project",
    "build this now",
    "start project",
]

IDEA_TRIGGERS = [
    "we should build",
    "idea:",
    "what if we",
    "maybe we could",
    "how about we build",
    "wouldn't it be cool",
    "i've been thinking about",
    "here's an idea",
]

BACKLOG_TRIGGERS = [
    "what's in my backlog",
    "show ideas",
    "show backlog",
    "list ideas",
    "what ideas do i have",
    "my ideas",
    "idea backlog",
]

MULTI_STEP_INDICATORS = [
    "with",
    "that has",
    "including",
    "and also",
    "step 1",
    "first",
    "then",
    "finally",
    "multiple",
    "features",
    "components",
]


# ─── ProjectManager ──────────────────────────────────────────────────────────

class ProjectManager:
    """Manages structured projects with feature hierarchy and idea backlog."""

    def __init__(self, db_path: str = "data/projects.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA_SQL)
        # Run migrations for existing databases
        for migration in MIGRATIONS:
            try:
                conn.execute(migration)
            except sqlite3.OperationalError:
                pass  # Column already exists
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── Detection ────────────────────────────────────────────────────

    def detect_project(self, user_message: str) -> bool:
        """Heuristic check: does this message look like a project request?"""
        msg_lower = user_message.lower().strip()
        has_trigger = any(t in msg_lower for t in PROJECT_TRIGGERS)
        if not has_trigger:
            return False
        complexity = sum(1 for ind in MULTI_STEP_INDICATORS if ind in msg_lower)
        return complexity >= 1 or len(msg_lower) > 80

    def detect_idea(self, user_message: str) -> bool:
        """Heuristic check: does this message suggest an idea (not a committed project)?"""
        msg_lower = user_message.lower().strip()
        return any(t in msg_lower for t in IDEA_TRIGGERS)

    def detect_backlog_query(self, user_message: str) -> bool:
        """Heuristic check: is the user asking about their idea backlog?"""
        msg_lower = user_message.lower().strip()
        return any(t in msg_lower for t in BACKLOG_TRIGGERS)

    # ─── Idea Backlog ─────────────────────────────────────────────────

    def add_idea(self, title: str, description: str, domain: Optional[str] = None) -> Idea:
        """Add an idea to the backlog."""
        idea = Idea(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            domain=domain,
            created_at=datetime.utcnow(),
            status="backlog",
        )
        conn = self._conn()
        conn.execute(
            "INSERT INTO ideas (id, title, description, domain, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (idea.id, idea.title, idea.description, idea.domain, idea.created_at.isoformat(), idea.status),
        )
        conn.commit()
        conn.close()
        logger.info(f"Added idea '{title}' to backlog")
        return idea

    def list_ideas(self, domain: Optional[str] = None) -> list[Idea]:
        """List ideas from the backlog, optionally filtered by domain."""
        conn = self._conn()
        if domain:
            rows = conn.execute(
                "SELECT * FROM ideas WHERE status = 'backlog' AND domain = ? ORDER BY created_at DESC",
                (domain,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ideas WHERE status = 'backlog' ORDER BY created_at DESC"
            ).fetchall()
        conn.close()
        return [self._row_to_idea(r) for r in rows]

    def promote_idea(self, idea_id: str) -> Project:
        """Promote an idea to an active project."""
        conn = self._conn()
        row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Idea {idea_id} not found")
        idea = self._row_to_idea(row)
        conn.execute("UPDATE ideas SET status = 'promoted' WHERE id = ?", (idea_id,))
        conn.commit()
        conn.close()

        project = self.create_project(
            name=idea.title,
            description=idea.description,
            spec="",  # Spec will be generated later
            domain=idea.domain,
        )
        logger.info(f"Promoted idea '{idea.title}' to project {project.id}")
        return project

    def archive_idea(self, idea_id: str) -> None:
        """Archive an idea (remove from active backlog)."""
        conn = self._conn()
        conn.execute("UPDATE ideas SET status = 'archived' WHERE id = ?", (idea_id,))
        conn.commit()
        conn.close()
        logger.info(f"Archived idea {idea_id}")

    def get_backlog_summary(self) -> str:
        """Formatted backlog summary for display."""
        ideas = self.list_ideas()
        if not ideas:
            return "📭 Your idea backlog is empty. Share some ideas and I'll save them!"

        lines = ["💡 **Idea Backlog:**\n"]
        for i, idea in enumerate(ideas, 1):
            domain_tag = f" [{idea.domain}]" if idea.domain else ""
            lines.append(f"  {i}. **{idea.title}**{domain_tag}")
            if idea.description:
                desc_short = idea.description[:100] + ("..." if len(idea.description) > 100 else "")
                lines.append(f"     {desc_short}")
        lines.append(f"\n_{len(ideas)} idea(s) in backlog. Say 'promote idea N' to start building._")
        return "\n".join(lines)

    # ─── Project CRUD ─────────────────────────────────────────────────

    def create_project(self, name: str, description: str, spec: str, domain: Optional[str] = None) -> Project:
        """Create a new project. Only one active project allowed (free tier)."""
        active = self.get_active_project()
        if active:
            raise ValueError(
                f"Active project already exists: '{active.name}'. "
                f"Complete or pause it first (free tier: 1 project at a time)."
            )

        project = Project(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            spec=spec,
            status="planning",
            created_at=datetime.utcnow(),
            domain=domain,
        )

        conn = self._conn()
        conn.execute(
            "INSERT INTO projects (id, name, description, spec, status, created_at, domain) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project.id, project.name, project.description, project.spec, project.status,
             project.created_at.isoformat(), project.domain),
        )
        conn.commit()
        conn.close()
        logger.info(f"Created project '{name}' ({project.id})")
        return project

    def get_active_project(self) -> Optional[Project]:
        """Get the single active project (planning or in_progress)."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM projects WHERE status IN ('planning', 'in_progress') ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_project(row)

    def update_project_status(self, project_id: str, status: str):
        conn = self._conn()
        conn.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
        conn.commit()
        conn.close()

    # ─── Feature Management ───────────────────────────────────────────

    def add_features(self, project_id: str, features: list[Feature]) -> None:
        """Store features for a project."""
        conn = self._conn()
        for feat in features:
            conn.execute(
                'INSERT INTO features (id, project_id, title, description, "order", status) VALUES (?, ?, ?, ?, ?, ?)',
                (feat.id, project_id, feat.title, feat.description, feat.order, feat.status),
            )
        conn.commit()
        conn.close()
        logger.info(f"Added {len(features)} features to project {project_id}")

    def get_features(self, project_id: str) -> list[Feature]:
        """Get all features for a project, ordered."""
        conn = self._conn()
        rows = conn.execute(
            'SELECT * FROM features WHERE project_id = ? ORDER BY "order" ASC', (project_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_feature(r) for r in rows]

    def complete_feature(self, feature_id: str) -> None:
        """Mark a feature as completed (auto-check: all tasks must be done)."""
        conn = self._conn()
        remaining = conn.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE feature_id = ? AND status NOT IN ('completed', 'skipped')",
            (feature_id,),
        ).fetchone()
        if remaining["cnt"] > 0:
            conn.close()
            raise ValueError(f"Feature {feature_id} still has {remaining['cnt']} incomplete task(s)")
        conn.execute("UPDATE features SET status = 'completed' WHERE id = ?", (feature_id,))
        conn.commit()
        conn.close()
        logger.info(f"Feature {feature_id} completed")

    def _auto_complete_feature(self, feature_id: str) -> None:
        """Auto-complete feature if all its tasks are done."""
        if not feature_id:
            return
        conn = self._conn()
        remaining = conn.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE feature_id = ? AND status NOT IN ('completed', 'skipped')",
            (feature_id,),
        ).fetchone()
        if remaining["cnt"] == 0:
            conn.execute("UPDATE features SET status = 'completed' WHERE id = ?", (feature_id,))
            conn.commit()
            logger.info(f"Auto-completed feature {feature_id}")
        conn.close()

    # ─── Task Management ──────────────────────────────────────────────

    def decompose_into_tasks(self, project_id: str, tasks: list[Task]) -> None:
        """Store ordered tasks with dependencies for a project."""
        conn = self._conn()
        for task in tasks:
            conn.execute(
                'INSERT INTO tasks (id, feature_id, project_id, title, description, agent, depends_on, status, result, "order") '
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id, task.feature_id, project_id, task.title, task.description,
                    task.agent, json.dumps(task.depends_on), task.status,
                    task.result, task.order,
                ),
            )
        conn.commit()
        conn.close()
        self.update_project_status(project_id, "in_progress")
        logger.info(f"Decomposed project {project_id} into {len(tasks)} tasks")

    def get_next_task(self, project_id: str) -> Optional[Task]:
        """Get next actionable task (dependencies all completed)."""
        conn = self._conn()
        rows = conn.execute(
            'SELECT * FROM tasks WHERE project_id = ? AND status = ? ORDER BY "order" ASC',
            (project_id, "pending"),
        ).fetchall()
        conn.close()

        for row in rows:
            task = self._row_to_task(row)
            if self._dependencies_met(project_id, task.depends_on):
                return task
        return None

    def complete_task(self, task_id: str, result: str) -> None:
        """Mark a task completed and store its result."""
        conn = self._conn()
        conn.execute(
            "UPDATE tasks SET status = 'completed', result = ? WHERE id = ?",
            (result, task_id),
        )
        conn.commit()

        row = conn.execute("SELECT project_id, feature_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row:
            pid = row["project_id"]
            fid = row["feature_id"]

            # Auto-complete feature if all its tasks done
            if fid:
                self._auto_complete_feature(fid)

            # Check if all tasks done → complete project
            remaining = conn.execute(
                "SELECT COUNT(*) as cnt FROM tasks WHERE project_id = ? AND status NOT IN ('completed', 'skipped')",
                (pid,),
            ).fetchone()
            if remaining["cnt"] == 0:
                conn.execute("UPDATE projects SET status = 'completed' WHERE id = ?", (pid,))
                conn.commit()
                logger.info(f"Project {pid} completed!")

        conn.close()

    def fail_task(self, task_id: str, error: str) -> None:
        conn = self._conn()
        conn.execute("UPDATE tasks SET status = 'failed', result = ? WHERE id = ?", (error, task_id))
        conn.commit()
        conn.close()

    def set_task_in_progress(self, task_id: str) -> None:
        conn = self._conn()
        conn.execute("UPDATE tasks SET status = 'in_progress' WHERE id = ?", (task_id,))
        # Also mark the feature as in_progress
        row = conn.execute("SELECT feature_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row and row["feature_id"]:
            conn.execute(
                "UPDATE features SET status = 'in_progress' WHERE id = ? AND status = 'pending'",
                (row["feature_id"],),
            )
        conn.commit()
        conn.close()

    def get_all_tasks(self, project_id: str) -> list[Task]:
        conn = self._conn()
        rows = conn.execute(
            'SELECT * FROM tasks WHERE project_id = ? ORDER BY "order" ASC', (project_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_task(r) for r in rows]

    # ─── Enhanced Status ──────────────────────────────────────────────

    def get_status(self, project_id: str) -> ProjectStatus:
        """Summary: X/Y tasks done, current task, blockers."""
        conn = self._conn()
        proj_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj_row:
            conn.close()
            raise ValueError(f"Project {project_id} not found")

        tasks = conn.execute(
            'SELECT * FROM tasks WHERE project_id = ? ORDER BY "order" ASC', (project_id,)
        ).fetchall()
        conn.close()

        task_list = [self._row_to_task(r) for r in tasks]
        completed = [t for t in task_list if t.status == "completed"]
        failed = [t for t in task_list if t.status == "failed"]

        current = None
        for t in task_list:
            if t.status == "in_progress":
                current = t
                break
        if not current:
            current = self.get_next_task(project_id)

        blockers = []
        failed_ids = {t.id for t in failed}
        for t in task_list:
            if t.status == "pending":
                blocked_by = [d for d in t.depends_on if d in failed_ids]
                if blocked_by:
                    blockers.append(f"Task '{t.title}' blocked by failed: {blocked_by}")

        return ProjectStatus(
            project_id=project_id,
            project_name=proj_row["name"],
            status=proj_row["status"],
            total_tasks=len(task_list),
            completed_tasks=len(completed),
            failed_tasks=len(failed),
            current_task=current,
            blockers=blockers,
        )

    def get_full_status(self, project_id: str) -> dict:
        """Returns nested status: project → features → tasks with completion counts."""
        conn = self._conn()
        proj_row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj_row:
            conn.close()
            raise ValueError(f"Project {project_id} not found")

        features = conn.execute(
            'SELECT * FROM features WHERE project_id = ? ORDER BY "order" ASC', (project_id,)
        ).fetchall()

        all_tasks = conn.execute(
            'SELECT * FROM tasks WHERE project_id = ? ORDER BY "order" ASC', (project_id,)
        ).fetchall()
        conn.close()

        # Group tasks by feature
        tasks_by_feature: dict[str, list] = {}
        for t in all_tasks:
            fid = t["feature_id"] or ""
            tasks_by_feature.setdefault(fid, []).append(self._row_to_task(t))

        feature_statuses = []
        completed_features = 0
        for f in features:
            feat = self._row_to_feature(f)
            feat_tasks = tasks_by_feature.get(feat.id, [])
            done = sum(1 for t in feat_tasks if t.status in ("completed", "skipped"))
            total = len(feat_tasks)

            current_task_name = None
            for t in feat_tasks:
                if t.status == "in_progress":
                    current_task_name = t.title
                    break
            if not current_task_name:
                for t in feat_tasks:
                    if t.status == "pending":
                        current_task_name = t.title
                        break

            feat_info = {
                "name": feat.title,
                "status": feat.status,
                "tasks": f"{done}/{total}",
            }
            if current_task_name and feat.status != "completed":
                feat_info["current_task"] = current_task_name

            if feat.status == "completed":
                completed_features += 1
            feature_statuses.append(feat_info)

        total_features = len(features)
        return {
            "name": proj_row["name"],
            "domain": proj_row["domain"],
            "progress": f"{completed_features}/{total_features} features done",
            "features": feature_statuses,
        }

    # ─── Helpers ──────────────────────────────────────────────────────

    def _dependencies_met(self, project_id: str, depends_on: list[str]) -> bool:
        if not depends_on:
            return True
        conn = self._conn()
        placeholders = ",".join("?" for _ in depends_on)
        rows = conn.execute(
            f"SELECT id, status FROM tasks WHERE id IN ({placeholders})",
            depends_on,
        ).fetchall()
        conn.close()
        return all(r["status"] in ("completed", "skipped") for r in rows)

    @staticmethod
    def _row_to_project(row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            spec=row["spec"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            domain=row["domain"] if "domain" in row.keys() else None,
        )

    @staticmethod
    def _row_to_task(row) -> Task:
        deps = row["depends_on"]
        if isinstance(deps, str):
            try:
                deps = json.loads(deps)
            except json.JSONDecodeError:
                deps = []
        return Task(
            id=row["id"],
            feature_id=row["feature_id"] if "feature_id" in row.keys() else "",
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            agent=row["agent"],
            depends_on=deps,
            status=row["status"],
            result=row["result"],
            order=row["order"],
        )

    @staticmethod
    def _row_to_idea(row) -> Idea:
        return Idea(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            domain=row["domain"],
            created_at=datetime.fromisoformat(row["created_at"]),
            status=row["status"],
        )

    @staticmethod
    def _row_to_feature(row) -> Feature:
        return Feature(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            order=row["order"],
            status=row["status"],
        )
