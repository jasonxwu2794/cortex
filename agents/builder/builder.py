"""
OpenClaw Distro — Builder Agent (Engineer)

The Builder generates code, executes commands, and manages files.
It operates in a sandboxed environment with NO internet access.

Key behaviors:
- Receives build/debug/tool tasks from the Brain
- Generates structured output (artifacts, code_output, claims)
- Can spawn sub-agents for multi-component parallel builds
- Flags factual claims for the Verifier to verify
- Reports execution results honestly, including errors
- Never writes to shared memory (read-only access)
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from agents.common.base_agent import BaseAgent
from agents.common.protocol import AgentRole, AgentMessage, TaskStatus
from agents.common.sub_agent import SubAgentPool, SubTask, SubResult

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))

# Threshold: if the LLM's plan has more than this many components, use sub-agents
MULTI_COMPONENT_THRESHOLD = 2

# Execution limits
# Aider integration — prefer aider for modifying existing files
AIDER_AVAILABLE = bool(subprocess.run(
    ["which", "aider"], capture_output=True, text=True
).returncode == 0)

EXEC_TIMEOUT_SECONDS = 30
EXEC_MAX_OUTPUT_BYTES = 100_000  # 100KB stdout/stderr cap

# File size guard
MAX_ARTIFACT_SIZE_BYTES = 500_000  # 500KB per file

# ─── Builder Prompts ──────────────────────────────────────────────────────────

BUILD_PROMPT = """\
You are the Builder agent. Generate code or file artifacts for this request.

Request: {request}

Context:
{context}

Workspace state: {workspace_state}

Respond with ONLY a valid JSON object:
{{
  "plan": "<brief description of what you'll build>",
  "artifacts": [
    {{
      "path": "<relative file path>",
      "content": "<full file content>",
      "action": "create|modify|delete",
      "language": "<python|bash|yaml|etc>"
    }}
  ],
  "execution": {{
    "command": "<optional shell command to run after creating files, or null>",
    "working_dir": "<relative to workspace, or null>"
  }},
  "claims": [
    "<any factual claim you make that should be verified>"
  ],
  "confidence": <0.0-1.0>,
  "needs_review": <true if this is risky or complex>,
  "notes": "<any caveats, uncertainties, or follow-up suggestions>"
}}

Rules:
- Never hardcode secrets or API keys — use environment variables
- Use parameterized queries for any database operations
- Validate all inputs
- Include error handling
- Write clear docstrings and comments
- If you're unsure about a factual claim (e.g. library API, algorithm complexity), add it to claims[]
"""

ARCHITECT_PROMPT = """\
You are planning a multi-component build. Break it into independent components
that can be built in parallel by sub-agents, then integrated.

Request: {request}

Context:
{context}

Define the architecture:
{{
  "components": [
    {{
      "id": "<unique_id>",
      "name": "<component name>",
      "description": "<what this component does>",
      "files": ["<file paths this component produces>"],
      "interfaces": {{
        "exports": ["<functions/classes this provides>"],
        "imports": ["<what it depends on from other components>"]
      }},
      "depends_on": ["<component ids this needs built first, or empty>"]
    }}
  ],
  "integration": {{
    "description": "<how to wire components together>",
    "test_command": "<command to verify integration>"
  }},
  "conventions": {{
    "naming": "<naming convention>",
    "imports": "<import style>",
    "error_handling": "<error handling pattern>"
  }}
}}
"""

COMPONENT_BUILD_PROMPT = """\
Build this specific component as part of a larger system.

Component: {component_name}
Description: {component_description}
Files to produce: {files}

Interface contracts (YOU MUST FOLLOW THESE EXACTLY):
- Exports: {exports}
- Imports from other components: {imports}

Conventions:
{conventions}

Respond with ONLY a JSON object:
{{
  "artifacts": [
    {{"path": "<path>", "content": "<content>", "action": "create", "language": "<lang>"}}
  ],
  "claims": [],
  "confidence": <0.0-1.0>,
  "notes": "<any concerns about the interfaces>"
}}
"""

DEBUG_PROMPT = """\
Diagnose and fix this issue.

Error/Problem: {request}

Code context:
{code_context}

Recent errors:
{errors}

Respond with ONLY a JSON object:
{{
  "diagnosis": "<what's wrong and why>",
  "artifacts": [
    {{"path": "<file>", "content": "<fixed content>", "action": "modify", "language": "<lang>"}}
  ],
  "execution": {{
    "command": "<command to verify the fix, or null>",
    "working_dir": null
  }},
  "claims": [],
  "confidence": <0.0-1.0>,
  "root_cause": "<underlying root cause>",
  "notes": "<prevention suggestions>"
}}
"""


# ─── Builder Agent ────────────────────────────────────────────────────────────

class BuilderAgent(BaseAgent):
    """
    The Builder — Engineer agent for code generation and execution.

    Handles three modes:
    1. Simple build: single LLM call → artifacts + optional execution
    2. Debug: diagnosis → fix → verify
    3. Multi-component: architect → parallel sub-agent builds → integrate → test
    """

    role = AgentRole.BUILDER
    name = "builder"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._system_prompt_text: Optional[str] = None
        self._workspace = WORKSPACE_DIR

    # ─── BaseAgent interface ──────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        if self._system_prompt_text is None:
            self._system_prompt_text = self.build_system_prompt() or (
                "You are the Builder agent. Generate clean, functional code. "
                "Return structured JSON with artifacts, claims, and confidence."
            )
        return self._system_prompt_text

    def _supports_sub_agents(self) -> bool:
        """Builder supports sub-agents for multi-component builds."""
        return True

    @property
    def sub_agent_system_prompt(self) -> str:
        return (
            "You are a Builder sub-agent. You build one specific component "
            "of a larger system. Follow the interface contracts EXACTLY. "
            "Respond with ONLY valid JSON containing artifacts and claims."
        )

    async def handle_task(self, msg: AgentMessage) -> Optional[dict]:
        """Route incoming tasks to the appropriate build mode."""
        action = msg.action
        request = msg.payload.get("message", "")
        context = msg.context

        logger.info(f"Builder handling '{action}': {request[:80]}...")

        if action == "build":
            return await self._handle_build(request, context)
        elif action == "debug":
            return await self._handle_debug(request, context)
        elif action == "execute":
            # Direct execution request (e.g. from complex task decomposition)
            return await self._handle_build(request, context)
        elif action == "tool":
            return await self._handle_tool(request, context)
        else:
            logger.warning(f"Builder received unknown action: {action}")
            return await self._handle_build(request, context)

    async def on_startup(self):
        """Ensure workspace directory exists."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        logger.info(f"Builder workspace: {self._workspace}")

    # ─── Build Mode ───────────────────────────────────────────────────

    async def _handle_build(self, request: str, context: dict) -> dict:
        """
        Main build flow:
        1. Ask LLM to plan and generate artifacts
        2. If multi-component, delegate to sub-agents
        3. Write artifacts to workspace
        4. Optionally execute
        5. Return structured result
        """
        workspace_state = self._get_workspace_state()

        # Format context
        context_str = self._format_context(context)

        prompt = BUILD_PROMPT.format(
            request=request,
            context=context_str,
            workspace_state=json.dumps(workspace_state, indent=2),
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=self.system_prompt,
                temperature=0.3,
            )
            build_plan = result["content"]
        except Exception as e:
            logger.error(f"Build LLM call failed: {e}")
            return self._error_result(f"Failed to generate build plan: {e}")

        # Check if this should be a multi-component build
        artifacts = build_plan.get("artifacts", [])
        if len(artifacts) > MULTI_COMPONENT_THRESHOLD and self.sub_pool:
            logger.info(
                f"Multi-component build detected ({len(artifacts)} artifacts), "
                f"considering sub-agent approach"
            )
            multi_result = await self._try_multi_component(request, context)
            if multi_result is not None:
                return multi_result
            # If multi-component approach failed, fall through to single build

        # Single build: write artifacts and optionally execute
        return await self._execute_build_plan(build_plan)

    async def _execute_build_plan(self, build_plan: dict) -> dict:
        """Write artifacts to disk and optionally execute a command."""
        artifacts = build_plan.get("artifacts", [])
        written_files = []
        errors = []

        # Write artifacts (prefer Aider for modifications to existing files)
        for artifact in artifacts:
            try:
                if self._use_aider_for_modification(artifact):
                    written = self._apply_with_aider(artifact)
                else:
                    written = self._write_artifact(artifact)
                written_files.append(written)
            except Exception as e:
                errors.append(f"Failed to write {artifact.get('path', '?')}: {e}")

        # Execute command if specified
        code_output = None
        execution = build_plan.get("execution") or {}
        command = execution.get("command")

        if command and self.can_execute_code:
            working_dir = execution.get("working_dir")
            code_output = self._run_command(command, working_dir)

        return {
            "plan": build_plan.get("plan", ""),
            "artifacts": written_files,
            "code_output": code_output,
            "claims": build_plan.get("claims", []),
            "confidence": build_plan.get("confidence", 0.5),
            "needs_review": build_plan.get("needs_review", False),
            "notes": build_plan.get("notes", ""),
            "errors": errors if errors else None,
        }

    # ─── Multi-Component Build ────────────────────────────────────────

    async def _try_multi_component(
        self, request: str, context: dict
    ) -> Optional[dict]:
        """
        Attempt a multi-component parallel build:
        1. Architect: define components and interfaces
        2. Parallel build: sub-agents build each component
        3. Integrate: merge and wire components
        4. Test: run integration check

        Returns None if it decides single-build is better.
        """
        context_str = self._format_context(context)

        # Step 1: Architect
        arch_prompt = ARCHITECT_PROMPT.format(
            request=request,
            context=context_str,
        )

        try:
            arch_result = await self.llm.generate_json(
                prompt=arch_prompt,
                system=self.system_prompt,
                temperature=0.3,
            )
            architecture = arch_result["content"]
        except Exception as e:
            logger.warning(f"Architecture planning failed: {e}, falling back")
            return None

        components = architecture.get("components", [])
        if len(components) < 2:
            # Not worth parallelizing
            return None

        conventions = architecture.get("conventions", {})
        conventions_str = json.dumps(conventions, indent=2)

        # Step 2: Build components in parallel via sub-agents
        subtasks = []
        for comp in components:
            prompt = COMPONENT_BUILD_PROMPT.format(
                component_name=comp["name"],
                component_description=comp["description"],
                files=json.dumps(comp.get("files", [])),
                exports=json.dumps(comp.get("interfaces", {}).get("exports", [])),
                imports=json.dumps(comp.get("interfaces", {}).get("imports", [])),
                conventions=conventions_str,
            )
            subtasks.append(SubTask(
                id=comp["id"],
                description=prompt,
                context={"component": comp},
                constraints={"max_files": 5, "max_lines_per_file": 500},
            ))

        logger.info(f"Parallel build: {len(subtasks)} components")
        sub_results = await self.sub_pool.execute_parallel(subtasks)

        # Step 3: Collect and write all artifacts
        all_artifacts = []
        all_claims = []
        all_errors = []
        overall_confidence = 1.0

        for comp, result in zip(components, sub_results):
            if not result.success:
                all_errors.append(
                    f"Component '{comp['name']}' failed: {result.error}"
                )
                continue

            # Parse the sub-agent output
            output = result.output
            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except json.JSONDecodeError:
                    all_errors.append(
                        f"Component '{comp['name']}' returned invalid JSON"
                    )
                    continue

            # Write artifacts
            for artifact in output.get("artifacts", []):
                try:
                    written = self._write_artifact(artifact)
                    all_artifacts.append(written)
                except Exception as e:
                    all_errors.append(
                        f"Failed to write {artifact.get('path', '?')}: {e}"
                    )

            all_claims.extend(output.get("claims", []))
            comp_confidence = output.get("confidence", 0.5)
            overall_confidence = min(overall_confidence, comp_confidence)

        # Step 4: Integration test if specified
        code_output = None
        integration = architecture.get("integration", {})
        test_cmd = integration.get("test_command")

        if test_cmd and self.can_execute_code:
            code_output = self._run_command(test_cmd)

        return {
            "plan": f"Multi-component build: {len(components)} components",
            "architecture": architecture,
            "artifacts": all_artifacts,
            "code_output": code_output,
            "claims": all_claims,
            "confidence": overall_confidence,
            "needs_review": len(all_errors) > 0,
            "notes": "; ".join(all_errors) if all_errors else "All components built successfully",
            "errors": all_errors if all_errors else None,
            "sub_agent_metrics": self.sub_pool.get_metrics() if self.sub_pool else None,
        }

    # ─── Debug Mode ───────────────────────────────────────────────────

    async def _handle_debug(self, request: str, context: dict) -> dict:
        """
        Diagnose and fix an issue.
        1. Analyze the error with code context
        2. Generate a fix
        3. Optionally verify the fix by running a command
        """
        code_context = "\n".join(context.get("recent_code", []))
        errors = "\n".join(context.get("recent_errors", []))

        prompt = DEBUG_PROMPT.format(
            request=request,
            code_context=code_context or "(no code context provided)",
            errors=errors or "(no error logs provided)",
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=self.system_prompt,
                temperature=0.2,
            )
            debug_plan = result["content"]
        except Exception as e:
            logger.error(f"Debug LLM call failed: {e}")
            return self._error_result(f"Failed to diagnose: {e}")

        # Write fix artifacts
        artifacts = debug_plan.get("artifacts", [])
        written = []
        write_errors = []
        for artifact in artifacts:
            try:
                written.append(self._write_artifact(artifact))
            except Exception as e:
                write_errors.append(str(e))

        # Verify fix
        code_output = None
        execution = debug_plan.get("execution") or {}
        command = execution.get("command")
        if command and self.can_execute_code:
            code_output = self._run_command(command)

        return {
            "diagnosis": debug_plan.get("diagnosis", ""),
            "root_cause": debug_plan.get("root_cause", ""),
            "artifacts": written,
            "code_output": code_output,
            "claims": debug_plan.get("claims", []),
            "confidence": debug_plan.get("confidence", 0.5),
            "needs_review": debug_plan.get("needs_review", False),
            "notes": debug_plan.get("notes", ""),
            "errors": write_errors if write_errors else None,
        }

    # ─── Tool Execution ───────────────────────────────────────────────

    async def _handle_tool(self, request: str, context: dict) -> dict:
        """
        Execute a specific tool or MCP command.
        For now, this is a thin wrapper around command execution.
        Future: integrate with MCP tool registry.
        """
        # Extract command from the request via LLM
        try:
            result = await self.llm.generate_json(
                prompt=(
                    f"Extract the shell command to execute from this request. "
                    f"If no clear command, generate one.\n\n"
                    f"Request: {request}\n\n"
                    f"Respond with: {{\"command\": \"<cmd>\", \"description\": \"<what it does>\"}}"
                ),
                system="Extract or generate a safe shell command. Respond with ONLY JSON.",
                temperature=0.1,
            )
            tool_plan = result["content"]
        except Exception as e:
            return self._error_result(f"Tool planning failed: {e}")

        command = tool_plan.get("command", "")
        if not command:
            return self._error_result("No command could be determined")

        code_output = self._run_command(command)

        return {
            "plan": tool_plan.get("description", command),
            "artifacts": [],
            "code_output": code_output,
            "claims": [],
            "confidence": 0.7,
            "needs_review": False,
            "notes": "",
        }

    # ─── File Operations ──────────────────────────────────────────────

    def _use_aider_for_modification(self, artifact: dict) -> bool:
        """
        Decide whether to use Aider for a file modification.
        Prefer Aider for modifying existing files in git repos.
        """
        if not AIDER_AVAILABLE:
            return False
        if artifact.get("action") != "modify":
            return False
        path_str = artifact.get("path", "")
        full_path = (self._workspace / path_str).resolve()
        return full_path.exists()

    def _apply_with_aider(self, artifact: dict) -> dict:
        """
        Use Aider to apply a modification to an existing file.
        Falls back to direct write on failure.
        """
        path_str = artifact.get("path", "")
        content = artifact.get("content", "")
        full_path = (self._workspace / path_str).resolve()

        # Use aider in architect mode with the change description
        cmd = (
            f"cd {self._workspace} && aider --yes --no-auto-commits "
            f"--message 'Update {path_str} with the following content' "
            f"{full_path}"
        )
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=60, cwd=str(self._workspace),
            )
            if result.returncode == 0:
                logger.info(f"Aider modified: {path_str}")
                return {"path": path_str, "action": "modify", "via": "aider"}
        except Exception as e:
            logger.warning(f"Aider failed for {path_str}: {e}, falling back to direct write")

        # Fallback to direct write
        return self._write_artifact(artifact)

    def _write_artifact(self, artifact: dict) -> dict:
        """
        Write a single artifact to the workspace.
        Returns metadata about what was written.
        """
        path_str = artifact.get("path", "")
        content = artifact.get("content", "")
        action = artifact.get("action", "create")

        if not path_str:
            raise ValueError("Artifact has no path")

        # Sanitize path — prevent directory traversal
        clean_path = Path(path_str).resolve()
        # Ensure it stays within workspace
        full_path = (self._workspace / path_str).resolve()
        if not str(full_path).startswith(str(self._workspace.resolve())):
            raise PermissionError(
                f"Path escapes workspace: {path_str}"
            )

        # Size guard
        if len(content.encode("utf-8")) > MAX_ARTIFACT_SIZE_BYTES:
            raise ValueError(
                f"Artifact too large: {len(content)} bytes "
                f"(max {MAX_ARTIFACT_SIZE_BYTES})"
            )

        if action == "delete":
            if full_path.exists():
                full_path.unlink()
                logger.info(f"Deleted: {full_path}")
            return {"path": path_str, "action": "delete"}

        # Create parent directories
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        full_path.write_text(content, encoding="utf-8")
        logger.info(f"Wrote {action}: {full_path} ({len(content)} bytes)")

        return {
            "path": path_str,
            "action": action,
            "size_bytes": len(content.encode("utf-8")),
            "language": artifact.get("language", ""),
        }

    def _get_workspace_state(self) -> dict:
        """
        Snapshot of the current workspace for context.
        Returns a tree of files with sizes.
        """
        if not self._workspace.exists():
            return {"files": [], "total_size": 0}

        files = []
        total_size = 0
        try:
            for f in sorted(self._workspace.rglob("*")):
                if f.is_file():
                    size = f.stat().st_size
                    rel = str(f.relative_to(self._workspace))
                    files.append({"path": rel, "size": size})
                    total_size += size
        except Exception as e:
            logger.warning(f"Workspace scan failed: {e}")

        return {
            "files": files[:100],  # Cap at 100 files
            "total_size": total_size,
            "truncated": len(files) > 100,
        }

    # ─── Command Execution ────────────────────────────────────────────

    def _run_command(
        self, command: str, working_dir: str = None
    ) -> dict:
        """
        Execute a command in the sandbox.
        Enforces timeout and output size limits.
        """
        if not self.can_execute_code:
            return {
                "stdout": "",
                "stderr": "Code execution is disabled for this agent",
                "exit_code": -1,
            }

        cwd = self._workspace
        if working_dir:
            cwd = (self._workspace / working_dir).resolve()
            if not str(cwd).startswith(str(self._workspace.resolve())):
                return {
                    "stdout": "",
                    "stderr": f"Working directory escapes sandbox: {working_dir}",
                    "exit_code": -1,
                }

        logger.info(f"Executing: {command[:100]} (cwd={cwd})")

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=EXEC_TIMEOUT_SECONDS,
                cwd=str(cwd),
                env={
                    **os.environ,
                    "HOME": str(self._workspace),
                    "WORKSPACE": str(self._workspace),
                },
            )

            stdout = proc.stdout[:EXEC_MAX_OUTPUT_BYTES]
            stderr = proc.stderr[:EXEC_MAX_OUTPUT_BYTES]

            if proc.returncode != 0:
                logger.warning(
                    f"Command exited {proc.returncode}: {stderr[:200]}"
                )

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
            }

        except subprocess.TimeoutExpired:
            logger.warning(f"Command timed out after {EXEC_TIMEOUT_SECONDS}s")
            return {
                "stdout": "",
                "stderr": f"Timeout after {EXEC_TIMEOUT_SECONDS}s",
                "exit_code": -1,
            }
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

    # ─── Utilities ────────────────────────────────────────────────────

    def _format_context(self, context: dict) -> str:
        """Format the scoped context dict into a readable string for prompts."""
        parts = []

        recent_code = context.get("recent_code", [])
        if recent_code:
            parts.append("Recent code:\n" + "\n---\n".join(recent_code[-3:]))

        recent_errors = context.get("recent_errors", [])
        if recent_errors:
            parts.append("Recent errors:\n" + "\n".join(recent_errors[-3:]))

        tools = context.get("available_tools", [])
        if AIDER_AVAILABLE and "aider" not in [str(t) for t in tools]:
            tools.append("aider")
        if tools:
            parts.append("Available tools: " + ", ".join(str(t) for t in tools))

        prior = context.get("prior_results", {})
        if prior:
            parts.append(
                "Results from prior tasks:\n"
                + json.dumps(prior, indent=2, default=str)[:2000]
            )

        return "\n\n".join(parts) if parts else "(no additional context)"

    @staticmethod
    def _error_result(error: str) -> dict:
        """Construct a standardized error result."""
        return {
            "plan": "",
            "artifacts": [],
            "code_output": None,
            "claims": [],
            "confidence": 0.0,
            "needs_review": True,
            "notes": error,
            "errors": [error],
        }
