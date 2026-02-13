"""
Task Decomposer — Breaks a project spec into ordered, assignable tasks.

Uses Brain's LLM to identify what needs building, in what order,
and which agent handles each task.
"""

import json
import logging
import uuid
from typing import Optional

from agents.brain.project_manager import Task

logger = logging.getLogger(__name__)

DECOMPOSE_PROMPT = """\
Break this project specification into ordered tasks for a multi-agent system.

Available agents:
- builder: Code generation, file creation, execution, debugging. NO internet access.
- investigator: Research, web search, information gathering. Has internet.
- verifier: Fact-checking, code review, testing. Has internet.
- guardian: Security review, credential checks, risk assessment.

Project Spec:
{spec}

Rules:
- Order tasks logically (design before implementation, implementation before testing)
- Each task should be completable independently once its dependencies are met
- Assign the most appropriate agent to each task
- Use task IDs like "task_1", "task_2", etc. for dependencies
- Keep tasks focused — one clear deliverable per task
- Include a verification/testing task at the end

Respond with ONLY this JSON:
{{
  "tasks": [
    {{
      "id": "task_1",
      "title": "<short task title>",
      "description": "<detailed description with enough context to execute>",
      "agent": "builder|investigator|verifier|guardian",
      "depends_on": [],
      "order": 1
    }}
  ]
}}
"""


async def decompose(llm, spec: str, project_id: Optional[str] = None) -> list[Task]:
    """
    Break a project spec into ordered tasks.

    Args:
        llm: LLM client instance
        spec: The project specification markdown
        project_id: Optional project ID to assign to tasks

    Returns:
        List of Task objects ready for storage
    """
    prompt = DECOMPOSE_PROMPT.format(spec=spec)
    pid = project_id or "unknown"

    try:
        result = await llm.generate_json(
            prompt=prompt,
            system="You are a task decomposition engine. Break projects into clear, ordered tasks. Respond with ONLY valid JSON.",
            temperature=0.3,
        )

        if result.get("error"):
            logger.error(f"Task decomposition failed: {result.get('message')}")
            return _fallback_tasks(pid)

        content = result["content"]
        if not isinstance(content, dict):
            logger.warning(f"Decomposition returned non-dict: {type(content)}")
            return _fallback_tasks(pid)

        raw_tasks = content.get("tasks", [])
        if not raw_tasks:
            return _fallback_tasks(pid)

        # Convert to Task objects
        tasks = []
        for raw in raw_tasks:
            task = Task(
                id=raw.get("id", str(uuid.uuid4())),
                project_id=pid,
                title=raw.get("title", "Untitled task"),
                description=raw.get("description", ""),
                agent=raw.get("agent", "builder"),
                depends_on=raw.get("depends_on", []),
                status="pending",
                result=None,
                order=raw.get("order", 0),
            )
            tasks.append(task)

        logger.info(f"Decomposed spec into {len(tasks)} tasks")
        return tasks

    except Exception as e:
        logger.error(f"Task decomposition error: {e}")
        return _fallback_tasks(pid)


def _fallback_tasks(project_id: str) -> list[Task]:
    """Minimal fallback when decomposition fails."""
    return [
        Task(
            id="task_1",
            project_id=project_id,
            title="Implement project",
            description="Build the project based on the specification.",
            agent="builder",
            depends_on=[],
            status="pending",
            order=1,
        ),
        Task(
            id="task_2",
            project_id=project_id,
            title="Verify and test",
            description="Test the implementation and verify it meets the spec.",
            agent="verifier",
            depends_on=["task_1"],
            status="pending",
            order=2,
        ),
    ]
