"""BaseAgent — abstract base class for all agents in the system."""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

from agents.common.protocol import AgentRole, AgentMessage, TaskStatus, MessageBus
from agents.common.llm_client import LLMClient
from agents.common.sub_agent import SubAgentPool
from memory.engine import MemoryEngine

logger = logging.getLogger(__name__)

# Per-role permission matrix
_PERMISSIONS: dict[AgentRole, dict[str, bool]] = {
    AgentRole.BRAIN: {"write_memory": True, "access_web": False, "execute_code": False},
    AgentRole.BUILDER: {"write_memory": False, "access_web": False, "execute_code": True},
    AgentRole.VERIFIER: {"write_memory": False, "access_web": True, "execute_code": False},
    AgentRole.INVESTIGATOR: {"write_memory": False, "access_web": True, "execute_code": False},
    AgentRole.GUARDIAN: {"write_memory": False, "access_web": False, "execute_code": False},
}


class BaseAgent(ABC):
    """Abstract base for every agent in the multi-agent system.

    Subclasses must implement:
      - ``system_prompt`` (property)
      - ``handle_task(msg)``
    """

    role: AgentRole = AgentRole.BRAIN
    name: str = "base"
    model: str = "claude-sonnet-4-20250514"

    def __init__(
        self,
        *,
        memory: MemoryEngine | None = None,
        message_bus: MessageBus | None = None,
        llm: LLMClient | None = None,
    ):
        self.memory: Optional[MemoryEngine] = memory
        self.bus: MessageBus = message_bus or MessageBus()
        self.llm: LLMClient = llm or LLMClient(default_model=self.model)

        # Sub-agent pool (initialised if the subclass declares support)
        self.sub_pool: Optional[SubAgentPool] = None
        if self._supports_sub_agents():
            self.sub_pool = SubAgentPool(
                llm=self.llm,
                system_prompt=getattr(self, "sub_agent_system_prompt", ""),
            )

    def _supports_sub_agents(self) -> bool:
        """Override to return True if this agent uses sub-agents."""
        return False

    # ─── Abstract interface ───────────────────────────────────────────

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    async def handle_task(self, msg: AgentMessage) -> Optional[dict]: ...

    # ─── Lifecycle hooks ──────────────────────────────────────────────

    async def on_startup(self) -> None:
        """Called once when the agent starts. Override to initialise state."""

    async def on_shutdown(self) -> None:
        """Called on graceful shutdown. Override to clean up."""
        await self.llm.close()

    # ─── Permission checks ────────────────────────────────────────────

    @property
    def can_write_memory(self) -> bool:
        return _PERMISSIONS.get(self.role, {}).get("write_memory", False)

    @property
    def can_access_web(self) -> bool:
        return _PERMISSIONS.get(self.role, {}).get("access_web", False)

    @property
    def can_execute_code(self) -> bool:
        return _PERMISSIONS.get(self.role, {}).get("execute_code", False)

    # ─── Messaging helpers ────────────────────────────────────────────

    def send_to(
        self,
        agent: AgentRole,
        action: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Send a message to another agent via the message bus. Returns task_id."""
        msg = AgentMessage(
            from_agent=self.role,
            to_agent=agent,
            action=action,
            payload=payload,
            context=context or {},
        )
        self.bus.send(msg)
        return msg.task_id

    async def delegate(
        self,
        to_agent: AgentRole,
        action: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
        timeout: float = 120.0,
    ) -> AgentMessage:
        """Send a task and poll until it completes or times out.

        In a full system this would await an async event; here we
        poll the SQLite bus at short intervals (good enough for MVP).
        """
        task_id = self.send_to(to_agent, action, payload, context)

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            task = self.bus.get_task(task_id)
            if task and task.status in (
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.BLOCKED.value,
            ):
                return task
            await asyncio.sleep(0.5)

        # Timeout — return a failed message
        return AgentMessage(
            task_id=task_id,
            from_agent=to_agent,
            to_agent=self.role,
            action=action,
            status=TaskStatus.FAILED.value,
            error=f"Timeout after {timeout}s waiting for {to_agent.value}",
        )

    async def delegate_parallel(
        self,
        tasks: list[dict[str, Any]],
    ) -> list[AgentMessage]:
        """Delegate multiple tasks in parallel and collect results."""
        coros = [
            self.delegate(
                to_agent=t["to"],
                action=t["action"],
                payload=t["payload"],
                context=t.get("context", {}),
            )
            for t in tasks
        ]
        return await asyncio.gather(*coros)

    # ─── LLM convenience ─────────────────────────────────────────────

    async def llm_call(self, prompt: str, system_prompt: str | None = None) -> str:
        """Quick single-prompt LLM call. Returns text content."""
        result = await self.llm.generate(
            system=system_prompt or self.system_prompt,
            prompt=prompt,
        )
        return result["content"]
