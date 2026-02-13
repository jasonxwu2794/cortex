"""
Spec Writer — Generates structured SPEC.md from a user's project idea.

Uses Brain's LLM to create a well-structured project specification.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

SPEC_PROMPT = """\
Write a clear, structured project specification based on the user's idea.

User's idea: {idea}

{research_section}

Generate a SPEC.md in this exact format:

# Project: <name>

## Overview
<2-3 sentence summary of what this project does and why>

## Requirements
### Must Have
- <requirement 1>
- <requirement 2>
...

### Nice to Have
- <optional feature 1>
...

## Architecture Decisions
- <key decision 1 and rationale>
- <key decision 2 and rationale>
...

## Out of Scope
- <thing explicitly NOT included>
...

## Success Criteria
- [ ] <measurable criterion 1>
- [ ] <measurable criterion 2>
...

Rules:
- Be specific and actionable
- Keep requirements concise (one line each)
- Architecture decisions should explain WHY, not just WHAT
- Success criteria must be verifiable
- Stay practical — this is for a single developer with AI assistance
"""


async def write_spec(llm, idea: str, research_context: Optional[str] = None) -> str:
    """
    Generate a SPEC.md from a user's project idea.

    Args:
        llm: LLM client instance
        idea: The user's project description/idea
        research_context: Optional research findings to inform the spec

    Returns:
        Markdown string containing the full spec
    """
    research_section = ""
    if research_context:
        research_section = f"Research context (from Investigator):\n{research_context}"

    prompt = SPEC_PROMPT.format(idea=idea, research_section=research_section)

    try:
        result = await llm.generate(
            system="You are a technical specification writer. Write clear, actionable specs. Output ONLY the markdown spec, no preamble.",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )

        if result.get("error"):
            logger.error(f"Spec generation failed: {result.get('message')}")
            return _fallback_spec(idea)

        return result["content"]

    except Exception as e:
        logger.error(f"Spec writer error: {e}")
        return _fallback_spec(idea)


def _fallback_spec(idea: str) -> str:
    """Generate a minimal spec when LLM fails."""
    return f"""# Project: {idea[:60]}

## Overview
{idea}

## Requirements
### Must Have
- To be determined after further discussion

## Architecture Decisions
- To be determined

## Out of Scope
- To be determined

## Success Criteria
- [ ] Project builds and runs successfully
- [ ] Core functionality works as described
"""
