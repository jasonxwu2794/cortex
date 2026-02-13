"""
Agent Session Manager — Delegates tasks to specialist agents via OpenClaw session spawning.

Instead of using the SQLite message bus for inter-agent communication, this module
spawns isolated OpenClaw sub-sessions for each agent. Each session gets:
- The agent's SOUL.md as system context
- TEAM.md for shared domain awareness
- Scoped task context from Brain
- Only the tools the agent is permitted to use
- The model configured for that agent
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── Agent Configuration ──────────────────────────────────────────────────────

# Default tool sets per agent
AGENT_TOOL_SETS: dict[str, list[str]] = {
    "builder": ["exec", "read", "write", "edit"],
    "researcher": ["web_search", "web_fetch", "read"],
    "verifier": ["web_search", "web_fetch", "read"],
    "guardian": ["read"],
}

# Default SOUL.md paths (relative to workspace)
AGENT_SOUL_PATHS: dict[str, str] = {
    "builder": "agents/builder/SOUL.md",
    "researcher": "agents/researcher/SOUL.md",
    "verifier": "agents/verifier/SOUL.md",
    "guardian": "agents/guardian/SOUL.md",
}


@dataclass
class AgentConfig:
    """Configuration for a specialist agent."""
    name: str
    model: str
    soul_path: str
    tools: list[str]

    @classmethod
    def from_config_file(cls, name: str, workspace: str | Path) -> "AgentConfig":
        """Load agent config from agents/{name}/config.yaml, with fallbacks."""
        workspace = Path(workspace)
        config_path = workspace / "agents" / name / "config.yaml"

        model = ""
        soul_path = AGENT_SOUL_PATHS.get(name, f"agents/{name}/SOUL.md")
        tools = AGENT_TOOL_SETS.get(name, ["read"])

        if config_path.exists():
            try:
                import yaml
                with open(config_path) as f:
                    cfg = yaml.safe_load(f) or {}
                model = cfg.get("model", "")
                if cfg.get("tools"):
                    tools = cfg["tools"]
                if cfg.get("soul_path"):
                    soul_path = cfg["soul_path"]
            except Exception as e:
                logger.warning(f"Failed to load config for {name}: {e}")

        return cls(name=name, model=model, soul_path=soul_path, tools=tools)


@dataclass
class DelegationTask:
    """A task to delegate to a specialist agent."""
    agent_name: str
    task: str
    context: dict[str, Any] | None = None


@dataclass
class DelegationResult:
    """Result from a delegated agent session."""
    agent_name: str
    success: bool
    result: str
    session_key: str
    error: str | None = None


class AgentSessionManager:
    """
    Manages spawning and communicating with specialist agent sessions.

    Uses OpenClaw's session_spawn to create isolated sessions for each agent.
    Each session runs with its own model, system prompt (SOUL.md), and tool set.
    """

    def __init__(self, workspace: str | Path | None = None):
        self.workspace = Path(workspace or os.environ.get(
            "OPENCLAW_WORKSPACE",
            os.path.expanduser("~/.openclaw/workspace")
        ))
        self._agent_configs: dict[str, AgentConfig] = {}
        self._active_sessions: dict[str, str] = {}  # session_key -> agent_name

    def _get_config(self, agent_name: str) -> AgentConfig:
        """Get or load the configuration for an agent."""
        if agent_name not in self._agent_configs:
            self._agent_configs[agent_name] = AgentConfig.from_config_file(
                agent_name, self.workspace
            )
        return self._agent_configs[agent_name]

    def _build_system_prompt(self, agent_name: str, context: dict[str, Any] | None = None) -> str:
        """
        Build the full system prompt for an agent session.

        Includes:
        1. The agent's SOUL.md content
        2. TEAM.md shared context
        3. Scoped task context from Brain
        """
        config = self._get_config(agent_name)
        parts: list[str] = []

        # Load SOUL.md
        soul_path = self.workspace / config.soul_path
        if soul_path.exists():
            parts.append(soul_path.read_text().strip())
        else:
            parts.append(f"You are the {agent_name} agent. Complete the assigned task.")

        # Load TEAM.md
        team_path = self.workspace / "TEAM.md"
        if team_path.exists():
            parts.append(f"\n## Team Context\n{team_path.read_text().strip()}")

        # Add scoped context
        if context:
            parts.append(f"\n## Task Context\n```json\n{json.dumps(context, indent=2, default=str)}\n```")

        return "\n\n".join(parts)

    async def delegate(
        self,
        agent_name: str,
        task: str,
        context: dict[str, Any] | None = None,
        timeout: float = 120.0,
    ) -> DelegationResult:
        """
        Spawn an isolated OpenClaw session for a specialist agent and send it a task.

        This creates a new session with:
        - The agent's configured model
        - The agent's SOUL.md + TEAM.md as system context
        - Only the tools the agent is permitted to use
        - The scoped task as the initial message

        Returns the agent's response when the session completes.
        """
        config = self._get_config(agent_name)
        session_key = f"{agent_name}_{uuid.uuid4().hex[:8]}"
        system_prompt = self._build_system_prompt(agent_name, context)

        logger.info(f"Delegating to {agent_name} (session={session_key}, model={config.model})")

        try:
            # Build the spawn command for OpenClaw CLI
            # This uses `openclaw sessions spawn` to create an isolated session
            spawn_args = {
                "label": session_key,
                "model": config.model,
                "system": system_prompt,
                "tools": config.tools,
                "message": task,
            }

            # Use subprocess to call openclaw CLI for session spawning
            # In production, this would use the OpenClaw Python SDK or API
            result = await self._run_session(spawn_args, timeout=timeout)

            self._active_sessions[session_key] = agent_name

            return DelegationResult(
                agent_name=agent_name,
                success=True,
                result=result,
                session_key=session_key,
            )

        except asyncio.TimeoutError:
            logger.error(f"Session {session_key} timed out after {timeout}s")
            return DelegationResult(
                agent_name=agent_name,
                success=False,
                result="",
                session_key=session_key,
                error=f"Timeout after {timeout}s",
            )
        except Exception as e:
            logger.error(f"Session {session_key} failed: {e}")
            return DelegationResult(
                agent_name=agent_name,
                success=False,
                result="",
                session_key=session_key,
                error=str(e),
            )

    async def delegate_parallel(
        self,
        tasks: list[DelegationTask],
        timeout: float = 120.0,
    ) -> list[DelegationResult]:
        """
        Spawn multiple agent sessions concurrently and collect their results.

        Independent tasks run in parallel. If one agent fails, others still
        return their results (fail-partial, not fail-all).
        """
        # Default timeouts per agent type
        default_timeouts = {
            "builder": 120.0,
            "verifier": 90.0,
            "researcher": 90.0,
        }

        coros = [
            self.delegate(
                agent_name=t.agent_name,
                task=t.task,
                context=t.context,
                timeout=default_timeouts.get(t.agent_name, timeout),
            )
            for t in tasks
        ]
        raw_results = await asyncio.gather(*coros, return_exceptions=True)

        results: list[DelegationResult] = []
        for task, result in zip(tasks, raw_results):
            if isinstance(result, Exception):
                logger.error(f"Parallel delegation to {task.agent_name} raised: {result}")
                results.append(DelegationResult(
                    agent_name=task.agent_name,
                    success=False,
                    result="",
                    session_key="",
                    error=str(result),
                ))
            else:
                results.append(result)
        return results

    async def _run_session(self, spawn_args: dict, timeout: float) -> str:
        """
        Execute an agent session via OpenClaw.

        In the OpenClaw environment, this spawns a sub-session using the
        sessions_spawn API. The session runs to completion and returns its
        final response.

        For now, this uses the CLI interface. A future version could use
        the OpenClaw Python SDK directly.
        """
        # Build the openclaw session spawn command
        cmd_parts = ["openclaw", "sessions", "spawn"]

        if spawn_args.get("label"):
            cmd_parts.extend(["--label", spawn_args["label"]])
        if spawn_args.get("model"):
            cmd_parts.extend(["--model", spawn_args["model"]])

        # Write system prompt to a temp file to avoid shell escaping issues
        import tempfile
        system_file = None
        try:
            if spawn_args.get("system"):
                system_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False
                )
                system_file.write(spawn_args["system"])
                system_file.close()
                cmd_parts.extend(["--system-file", system_file.name])

            if spawn_args.get("tools"):
                for tool in spawn_args["tools"]:
                    cmd_parts.extend(["--tool", tool])

            if spawn_args.get("message"):
                cmd_parts.extend(["--message", spawn_args["message"]])

            # Run with timeout
            proc = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else f"Exit code {proc.returncode}"
                raise RuntimeError(f"Session failed: {error_msg}")

            return stdout.decode().strip()

        finally:
            if system_file and os.path.exists(system_file.name):
                os.unlink(system_file.name)

    def get_active_sessions(self) -> dict[str, str]:
        """Return a copy of active session mappings."""
        return dict(self._active_sessions)
