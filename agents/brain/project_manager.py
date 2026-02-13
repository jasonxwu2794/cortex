"""
Project Manager — Structured project management for Brain agent (Free Tier).

Manages a single active project with ordered tasks, dependencies, and status tracking.
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
    spec: str  # Full spec markdown
    status: str  # planning, in_progress, completed, paused
    created_at: datetime

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


@dataclass
class Task:
    id: str
    project_id: str
    title: str
    description: str
    agent: str  # builder, investigator, verifier, guardian
    depends_on: list[str] = field(default_factory=list)  # task IDs
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
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT 'builder',
    depends_on TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    "order" INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

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
]

# Multi-step indicators (suggest project-level complexity)
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
    """Manages structured projects with task decomposition and tracking."""

    def __init__(self, db_path: str = "data/projects.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA_SQL)
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

        # Check for project triggers
        has_trigger = any(t in msg_lower for t in PROJECT_TRIGGERS)
        if not has_trigger:
            return False

        # Bonus: check for multi-step complexity
        complexity = sum(1 for ind in MULTI_STEP_INDICATORS if ind in msg_lower)

        # Trigger + any complexity indicator, or message is long enough
        return complexity >= 1 or len(msg_lower) > 80

    # ─── Project CRUD ─────────────────────────────────────────────────

    def create_project(self, name: str, description: str, spec: str) -> Project:
        """Create a new project. Only one active project allowed (free tier)."""
        # Check for existing active project
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
        )

        conn = self._conn()
        conn.execute(
            "INSERT INTO projects (id, name, description, spec, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project.id, project.name, project.description, project.spec, project.status, project.created_at.isoformat()),
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

    # ─── Task Management ──────────────────────────────────────────────

    def decompose_into_tasks(self, project_id: str, tasks: list[Task]) -> None:
        """Store ordered tasks with dependencies for a project."""
        conn = self._conn()
        for task in tasks:
            conn.execute(
                'INSERT INTO tasks (id, project_id, title, description, agent, depends_on, status, result, "order") '
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task.id, project_id, task.title, task.description,
                    task.agent, json.dumps(task.depends_on), task.status,
                    task.result, task.order,
                ),
            )
        conn.commit()
        conn.close()

        # Move project to in_progress
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

        # Check if all tasks done → complete project
        row = conn.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row:
            pid = row["project_id"]
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
        conn.commit()
        conn.close()

    def get_all_tasks(self, project_id: str) -> list[Task]:
        conn = self._conn()
        rows = conn.execute(
            'SELECT * FROM tasks WHERE project_id = ? ORDER BY "order" ASC', (project_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_task(r) for r in rows]

    # ─── Status ───────────────────────────────────────────────────────

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

        # Find current task (in_progress or next pending)
        current = None
        for t in task_list:
            if t.status == "in_progress":
                current = t
                break
        if not current:
            current = self.get_next_task(project_id)

        # Find blockers (tasks that are failed and block others)
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
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            agent=row["agent"],
            depends_on=deps,
            status=row["status"],
            result=row["result"],
            order=row["order"],
        )
