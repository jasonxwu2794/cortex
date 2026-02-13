"""Agent communication protocol — message types, roles, and SQLite message bus."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ─── Enums ────────────────────────────────────────────────────────────────────

class AgentRole(Enum):
    BRAIN = "brain"
    BUILDER = "builder"
    VERIFIER = "verifier"
    RESEARCHER = "researcher"
    GUARDIAN = "guardian"


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


# ─── Context Scoping ─────────────────────────────────────────────────────────

class ContextScope:
    """Factory for agent-specific scoped context dicts.

    Each agent type receives only the context it needs — no more.
    """

    @staticmethod
    def for_builder(
        conversation: list[dict],
        workspace_state: dict | None = None,
        tools: list[str] | None = None,
    ) -> dict:
        # Builder gets recent conversation + workspace info, no private data
        recent = conversation[-6:] if conversation else []
        return {
            "scope": "builder",
            "conversation": recent,
            "workspace_state": workspace_state or {},
            "tools": tools or [],
        }

    @staticmethod
    def for_verifier(
        claims: list[str],
        knowledge_excerpts: list[dict] | None = None,
    ) -> dict:
        return {
            "scope": "verifier",
            "claims": claims,
            "knowledge_excerpts": knowledge_excerpts or [],
        }

    @staticmethod
    def for_researcher(
        query: str,
        knowledge_gaps: list[str] | None = None,
    ) -> dict:
        return {
            "scope": "researcher",
            "query": query,
            "knowledge_gaps": knowledge_gaps or [],
        }

    @staticmethod
    def for_guardian(content: str, source_agent: str) -> dict:
        return {
            "scope": "guardian",
            "content": content,
            "source_agent": source_agent,
        }


# ─── Message ──────────────────────────────────────────────────────────────────

@dataclass
class AgentMessage:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    from_agent: AgentRole = AgentRole.BRAIN
    to_agent: AgentRole = AgentRole.BRAIN
    action: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    status: str = TaskStatus.PENDING.value
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def block(self, reason: str) -> None:
        """Mark this message as blocked by the Guardian."""
        self.status = TaskStatus.BLOCKED.value
        self.error = reason

    def to_json(self) -> str:
        d = asdict(self)
        d["from_agent"] = self.from_agent.value if isinstance(self.from_agent, AgentRole) else self.from_agent
        d["to_agent"] = self.to_agent.value if isinstance(self.to_agent, AgentRole) else self.to_agent
        return json.dumps(d, default=str)

    @classmethod
    def from_json(cls, raw: str) -> "AgentMessage":
        d = json.loads(raw)
        d["from_agent"] = AgentRole(d["from_agent"])
        d["to_agent"] = AgentRole(d["to_agent"])
        return cls(**d)


# ─── SQLite Message Bus ──────────────────────────────────────────────────────

MESSAGE_BUS_SCHEMA = """
CREATE TABLE IF NOT EXISTS message_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    action TEXT NOT NULL,
    payload JSON,
    context JSON,
    constraints JSON,
    status TEXT DEFAULT 'pending',
    result JSON,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mq_to_agent ON message_queue(to_agent);
CREATE INDEX IF NOT EXISTS idx_mq_status ON message_queue(status);
CREATE INDEX IF NOT EXISTS idx_mq_task_id ON message_queue(task_id);
"""


class MessageBus:
    """SQLite-backed message bus for inter-agent communication."""

    def __init__(self, db_path: str | Path = "data/messages.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(MESSAGE_BUS_SCHEMA)
        self._db.commit()

    def send(self, message: AgentMessage) -> None:
        """Enqueue a message."""
        self._db.execute(
            "INSERT INTO message_queue "
            "(task_id, from_agent, to_agent, action, payload, context, constraints, status, result, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message.task_id,
                message.from_agent.value,
                message.to_agent.value,
                message.action,
                json.dumps(message.payload, default=str),
                json.dumps(message.context, default=str),
                json.dumps(message.constraints, default=str),
                message.status,
                json.dumps(message.result, default=str) if message.result else None,
                message.error,
                message.created_at,
            ),
        )
        self._db.commit()

    def receive(self, agent: AgentRole, limit: int = 10) -> list[AgentMessage]:
        """Poll for pending messages addressed to *agent*."""
        rows = self._db.execute(
            "SELECT * FROM message_queue WHERE to_agent = ? AND status = 'pending' "
            "ORDER BY id ASC LIMIT ?",
            (agent.value, limit),
        ).fetchall()

        messages: list[AgentMessage] = []
        for row in rows:
            msg = AgentMessage(
                task_id=row["task_id"],
                from_agent=AgentRole(row["from_agent"]),
                to_agent=AgentRole(row["to_agent"]),
                action=row["action"],
                payload=json.loads(row["payload"] or "{}"),
                context=json.loads(row["context"] or "{}"),
                constraints=json.loads(row["constraints"] or "{}"),
                status=row["status"],
                result=json.loads(row["result"]) if row["result"] else None,
                error=row["error"],
                created_at=row["created_at"],
            )
            messages.append(msg)

            # Mark as in_progress
            self._db.execute(
                "UPDATE message_queue SET status = 'in_progress', updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), row["id"]),
            )
        self._db.commit()
        return messages

    def update_status(
        self, task_id: str, status: TaskStatus, result: dict | None = None, error: str | None = None
    ) -> None:
        """Update status (and optionally result/error) for a task."""
        self._db.execute(
            "UPDATE message_queue SET status = ?, result = ?, error = ?, updated_at = ? "
            "WHERE task_id = ?",
            (
                status.value,
                json.dumps(result, default=str) if result else None,
                error,
                datetime.now(timezone.utc).isoformat(),
                task_id,
            ),
        )
        self._db.commit()

    def get_task(self, task_id: str) -> AgentMessage | None:
        """Fetch the latest message for a task_id."""
        row = self._db.execute(
            "SELECT * FROM message_queue WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if not row:
            return None
        return AgentMessage(
            task_id=row["task_id"],
            from_agent=AgentRole(row["from_agent"]),
            to_agent=AgentRole(row["to_agent"]),
            action=row["action"],
            payload=json.loads(row["payload"] or "{}"),
            context=json.loads(row["context"] or "{}"),
            constraints=json.loads(row["constraints"] or "{}"),
            status=row["status"],
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            created_at=row["created_at"],
        )

    def close(self) -> None:
        self._db.close()
