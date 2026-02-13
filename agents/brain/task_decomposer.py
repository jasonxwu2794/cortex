"""
Task Decomposer — Breaks a project spec into Features → Tasks.

Uses Brain's LLM to identify logical feature groupings,
then tasks within each feature.
"""

import json
import logging
import uuid
from typing import Optional

from agents.brain.project_manager import Task, Feature

logger = logging.getLogger(__name__)

DECOMPOSE_PROMPT = """\
Break this project specification into logical features, each containing ordered tasks.

Available agents:
- builder: Code generation, file creation, execution, debugging. NO internet access.
- researcher: Research, web search, information gathering. Has internet.
- verifier: Fact-checking, code review, testing. Has internet.
- guardian: Security review, credential checks, risk assessment.

Project Spec:
{spec}

Rules:
- Group related tasks into features (logical units of functionality)
- Order features by priority/dependency (foundational first)
- Within each feature, order tasks logically
- Each task should be completable independently once its dependencies are met
- Assign the most appropriate agent to each task
- Use task IDs like "task_1", "task_2", etc. for dependencies (global across features)
- Keep tasks focused — one clear deliverable per task
- Include verification/testing tasks within each feature

Respond with ONLY this JSON:
{{
  "features": [
    {{
      "title": "<feature name>",
      "description": "<what this feature accomplishes>",
      "tasks": [
        {{
          "id": "task_1",
          "title": "<short task title>",
          "description": "<detailed description with enough context to execute>",
          "agent": "builder|researcher|verifier|guardian",
          "depends_on": [],
          "order": 1
        }}
      ]
    }}
  ]
}}
"""


async def decompose(llm, spec: str, project_id: Optional[str] = None) -> list[Feature]:
    """
    Break a project spec into features with nested tasks.

    Args:
        llm: LLM client instance
        spec: The project specification markdown
        project_id: Optional project ID to assign to tasks

    Returns:
        List of Feature objects, each containing nested Task objects
    """
    prompt = DECOMPOSE_PROMPT.format(spec=spec)
    pid = project_id or "unknown"

    try:
        result = await llm.generate_json(
            prompt=prompt,
            system="You are a task decomposition engine. Break projects into features and tasks. Respond with ONLY valid JSON.",
            temperature=0.3,
        )

        if result.get("error"):
            logger.error(f"Task decomposition failed: {result.get('message')}")
            return _fallback_features(pid)

        content = result["content"]
        if not isinstance(content, dict):
            logger.warning(f"Decomposition returned non-dict: {type(content)}")
            return _fallback_features(pid)

        raw_features = content.get("features", [])
        if not raw_features:
            # Try legacy format (flat task list)
            raw_tasks = content.get("tasks", [])
            if raw_tasks:
                return _wrap_legacy_tasks(raw_tasks, pid)
            return _fallback_features(pid)

        # Convert to Feature objects with nested Tasks
        features = []
        global_order = 0
        for feat_idx, raw_feat in enumerate(raw_features):
            feat_id = str(uuid.uuid4())
            feat = Feature(
                id=feat_id,
                project_id=pid,
                title=raw_feat.get("title", f"Feature {feat_idx + 1}"),
                description=raw_feat.get("description", ""),
                order=feat_idx,
                status="pending",
                tasks=[],
            )

            for raw_task in raw_feat.get("tasks", []):
                global_order += 1
                task = Task(
                    id=raw_task.get("id", str(uuid.uuid4())),
                    feature_id=feat_id,
                    project_id=pid,
                    title=raw_task.get("title", "Untitled task"),
                    description=raw_task.get("description", ""),
                    agent=raw_task.get("agent", "builder"),
                    depends_on=raw_task.get("depends_on", []),
                    status="pending",
                    result=None,
                    order=raw_task.get("order", global_order),
                )
                feat.tasks.append(task)

            features.append(feat)

        logger.info(f"Decomposed spec into {len(features)} features with {global_order} total tasks")
        return features

    except Exception as e:
        logger.error(f"Task decomposition error: {e}")
        return _fallback_features(pid)


def _wrap_legacy_tasks(raw_tasks: list[dict], project_id: str) -> list[Feature]:
    """Wrap a flat task list into a single feature for backward compat."""
    feat_id = str(uuid.uuid4())
    tasks = []
    for raw in raw_tasks:
        task = Task(
            id=raw.get("id", str(uuid.uuid4())),
            feature_id=feat_id,
            project_id=project_id,
            title=raw.get("title", "Untitled task"),
            description=raw.get("description", ""),
            agent=raw.get("agent", "builder"),
            depends_on=raw.get("depends_on", []),
            status="pending",
            result=None,
            order=raw.get("order", 0),
        )
        tasks.append(task)

    feat = Feature(
        id=feat_id,
        project_id=project_id,
        title="Implementation",
        description="Main implementation feature",
        order=0,
        status="pending",
        tasks=tasks,
    )
    return [feat]


def _fallback_features(project_id: str) -> list[Feature]:
    """Minimal fallback when decomposition fails."""
    feat_id = str(uuid.uuid4())
    tasks = [
        Task(
            id="task_1",
            feature_id=feat_id,
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
            feature_id=feat_id,
            project_id=project_id,
            title="Verify and test",
            description="Test the implementation and verify it meets the spec.",
            agent="verifier",
            depends_on=["task_1"],
            status="pending",
            order=2,
        ),
    ]
    return [Feature(
        id=feat_id,
        project_id=project_id,
        title="Implementation",
        description="Main implementation",
        order=0,
        status="pending",
        tasks=tasks,
    )]
