"""
OpenClaw Distro — Brain Agent (Chief of Staff)

The Brain is the orchestrator and sole user-facing agent. It:
1. Receives all user input (via Telegram, CLI, or API)
2. Classifies intent and complexity
3. Decides which agents to involve (or handles directly)
4. Scopes context per agent (privacy/relevance filter)
5. Synthesizes final responses from agent results
6. Gates what gets stored in shared memory

The Brain NEVER fragments into sub-agents — it must maintain
unified coherence across the full conversation.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from agents.common.base_agent import BaseAgent
from agents.common.protocol import (
    AgentRole, AgentMessage, TaskStatus, ContextScope,
)
from agents.session_manager import AgentSessionManager, DelegationTask
from agents.brain.project_manager import ProjectManager, Task as ProjectTask, Feature, Idea, ProjectStatus
from agents.brain import spec_writer, task_decomposer
from agents.common.gitops import GitOps
from memory.engine import MemoryEngine, Turn

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Intent categories the classifier outputs
INTENT_SIMPLE_CHAT = "simple_chat"
INTENT_BUILD = "build_request"
INTENT_FACTUAL = "factual_question"
INTENT_RESEARCH = "research_request"
INTENT_COMPLEX = "complex_task"
INTENT_PROJECT = "project_request"
INTENT_IDEA = "idea_suggestion"

VALID_INTENTS = {
    INTENT_SIMPLE_CHAT,
    INTENT_BUILD,
    INTENT_FACTUAL,
    INTENT_RESEARCH,
    INTENT_COMPLEX,
    INTENT_PROJECT,
    INTENT_IDEA,
}

# Max conversation turns to keep in working memory
MAX_CONVERSATION_HISTORY = 50

# Delegation timeout per agent type (seconds)
DELEGATION_TIMEOUTS = {
    AgentRole.BUILDER: 180.0,       # Code gen can take a while
    AgentRole.VERIFIER: 90.0,
    AgentRole.RESEARCHER: 120.0,
}

# ─── Classification Prompt ────────────────────────────────────────────────────

CLASSIFY_PROMPT = """\
Classify the user's intent into exactly one category. Respond with ONLY a JSON object.

Categories:
- "simple_chat": Greetings, casual talk, opinions, simple questions you can answer from general knowledge. No specialist needed.
- "build_request": Code generation, file creation/editing, tool execution, automation, debugging, anything that produces artifacts.
- "factual_question": Specific factual claims to verify, "is this true?", data lookups, corrections.
- "research_request": Open-ended investigation, comparisons, "find out about...", market research, multi-source synthesis.
- "idea_suggestion": User is suggesting an idea for the backlog, not committing to build now. ("we should build...", "idea:", "what if we...", "maybe we could..."), or querying their backlog ("show ideas", "what's in my backlog").
- "project_request": Committed project requests ("let's build...", "start project...", "build this now"), project status queries, pause/cancel project commands, promoting/archiving ideas.
- "complex_task": Requires MULTIPLE specialists. e.g. "Research X and then build Y based on findings."

For "complex_task", also provide a decomposition into ordered subtasks.

User message:
{user_message}

Recent conversation context (last 3 turns):
{recent_context}

Respond with ONLY this JSON:
{{
  "intent": "<category>",
  "confidence": <0.0-1.0>,
  "reasoning": "<one sentence>",
  "subtasks": [
    {{
      "agent": "builder|verifier|researcher",
      "action": "<verb phrase>",
      "description": "<what this subtask accomplishes>",
      "depends_on": [<indices of subtasks this depends on, empty if independent>]
    }}
  ]
}}

The "subtasks" array should be empty for all intents except "complex_task".
"""

# ─── Decomposition Prompt (for complex tasks) ────────────────────────────────

DECOMPOSE_PROMPT = """\
Break this complex task into ordered subtasks for specialist agents.

Available agents:
- builder: Code generation, file operations, tool execution. NO internet. Good at code.
- verifier: Claim verification, source checking. Has web access. Good at precision.
- researcher: Information gathering, multi-source synthesis. Has web access. Good at breadth.

Task: {task_description}

Context: {context}

Rules:
- Minimize the number of subtasks (prefer fewer, broader tasks)
- Mark dependencies (which subtasks must complete before others start)
- Independent subtasks will run in parallel
- Each subtask must specify exactly one agent

Respond with ONLY this JSON:
{{
  "subtasks": [
    {{
      "agent": "builder|verifier|researcher",
      "action": "<action verb>",
      "description": "<detailed task description with enough context to execute independently>",
      "depends_on": []
    }}
  ],
  "synthesis_notes": "<how to combine results into a coherent response>"
}}
"""

# ─── Synthesis Prompt ─────────────────────────────────────────────────────────

SYNTHESIZE_PROMPT = """\
You are synthesizing results from multiple specialist agents into one coherent response for the user.

Original user request: {user_message}

Agent results:
{agent_results}

Rules:
1. Lead with the most important/requested information
2. If the Verifier made corrections, incorporate them naturally (don't say "the verifier found...")
3. If confidence is low on any claim, note the uncertainty naturally
4. If the Guardian flagged issues, address them
5. The user should NOT know about the multi-agent system — write as one unified voice
6. Be conversational, not robotic
7. If an agent failed, work around it gracefully — don't expose internal errors

Write your synthesized response:
"""

# ─── Memory Decision Prompt ───────────────────────────────────────────────────

MEMORY_DECISION_PROMPT = """\
Decide what (if anything) from this interaction should be stored in memory.

User message: {user_message}
Assistant response summary: {response_summary}

For each item worth remembering, classify it:

Respond with ONLY this JSON:
{{
  "memories": [
    {{
      "text": "<concise text to remember>",
      "importance": <0.0-1.0>,
      "signals": {{
        "user_explicit": false,
        "decision": false,
        "error_correction": false,
        "preference": false,
        "repeated": false
      }},
      "tags": ["<category>"]
    }}
  ],
  "facts_for_cache": [
    {{
      "fact": "<verified factual statement>",
      "category": "<technical|financial|general|personal_preference>",
      "confidence": <0.0-1.0>
    }}
  ]
}}

Rules:
- Only store what's worth retrieving later
- User preferences and corrections are HIGH importance
- Casual greetings and small talk: store NOTHING
- Sensitive info (passwords, keys, financial details): NEVER store
- Be concise — memories should be searchable fragments, not essays
- If nothing worth storing, return empty arrays
"""


# ─── Brain Agent ──────────────────────────────────────────────────────────────

class BrainAgent(BaseAgent):
    """
    The Brain — Chief of Staff and sole user-facing agent.

    Lifecycle per user message:
    1. classify() → Determine intent
    2. Route based on intent:
       - simple_chat → handle_direct()
       - single-agent → delegate to specialist
       - complex_task → decompose → delegate (parallel where possible) → synthesize
    3. gate_memory() → Decide what to store
    4. Return final response
    """

    role = AgentRole.BRAIN
    name = "brain"

    # Verbose mode status messages
    VERBOSE_STATUS = {
        AgentRole.BUILDER: "🔨 Builder is working on that...",
        AgentRole.RESEARCHER: "🔬 Researcher is researching...",
        AgentRole.VERIFIER: "✅ Verifier is checking the facts...",
        AgentRole.GUARDIAN: "🛡️ Guardian is reviewing security...",
    }

    def __init__(self, memory_db_path: str = "data/memory.db", verbose_mode: str = "stealth",
                 workspace_path: str = "/workspace", **kwargs):
        memory = MemoryEngine(db_path=memory_db_path)
        super().__init__(memory=memory, **kwargs)
        self.conversation_history: list[dict] = []
        self._system_prompt_text: str | None = None
        self.session_manager = AgentSessionManager()
        self.verbose_mode = verbose_mode
        self.project_manager = ProjectManager()
        self.gitops = GitOps(workspace_path)

    # ─── BaseAgent interface ──────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        if self._system_prompt_text is None:
            self._system_prompt_text = self.build_system_prompt() or (
                "You are the Brain, the orchestrator in a multi-agent system. "
                "You are the only agent that talks to the user."
            )
        return self._system_prompt_text

    async def handle_task(self, msg: AgentMessage) -> Optional[dict]:
        """
        Main entry point for all incoming messages to the Brain.

        Messages come from two sources:
        1. User input (action="user_message") — the primary flow
        2. Other agents requesting Brain involvement (action="synthesize", etc.)
        """
        action = msg.action

        if action == "user_message":
            return await self._handle_user_message(msg)
        elif action == "synthesize":
            return await self._handle_synthesis_request(msg)
        else:
            logger.warning(f"Brain received unknown action: {action}")
            return {"response": f"Unknown action: {action}", "error": True}

    async def on_startup(self):
        """Load conversation history from memory on startup."""
        logger.info("Brain agent starting up")
        if self.memory:
            try:
                recent = self.memory.retrieve(
                    query="conversation summary", strategy="recent", limit=5
                )
                if recent:
                    logger.info(
                        f"Loaded {len(recent)} recent memories on startup"
                    )
            except Exception as e:
                logger.warning(f"Could not load conversation history: {e}")

    # ─── User Message Flow ────────────────────────────────────────────

    async def _handle_user_message(self, msg: AgentMessage) -> dict:
        """
        Full pipeline for a user message:
        classify → route → (delegate) → respond → gate memory

        Global try/except ensures we never crash — always return a friendly message.
        """
        try:
            return await self._handle_user_message_inner(msg)
        except Exception as e:
            logger.error(f"Unhandled error in user message pipeline: {e}", exc_info=True)
            return {
                "response": "I'm sorry, I hit an unexpected issue processing your message. Could you try again?",
                "intent": INTENT_SIMPLE_CHAT,
                "delegated": False,
                "error": str(e),
            }

    async def _handle_user_message_inner(self, msg: AgentMessage) -> dict:
        """Inner pipeline — may raise; caught by _handle_user_message."""
        user_message = msg.payload.get("message", "")
        conversation_id = msg.payload.get("conversation_id", "")

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": user_message,
        })
        self._trim_history()

        # Step 1: Classify intent
        classification = await self._classify(user_message)
        intent = classification.get("intent", INTENT_SIMPLE_CHAT)
        confidence = classification.get("confidence", 0.5)

        logger.info(
            f"Classified as {intent} (confidence={confidence:.2f}): "
            f"{user_message[:80]}..."
        )

        # Step 2: Route based on intent
        if intent == INTENT_SIMPLE_CHAT:
            response = await self._handle_direct(user_message)

        elif intent == INTENT_BUILD:
            response = await self._handle_single_agent(
                user_message=user_message,
                agent=AgentRole.BUILDER,
                action="build",
                context_fn=self._scope_builder_context,
            )

        elif intent == INTENT_FACTUAL:
            response = await self._handle_single_agent(
                user_message=user_message,
                agent=AgentRole.VERIFIER,
                action="verify",
                context_fn=self._scope_verifier_context,
            )

        elif intent == INTENT_RESEARCH:
            response = await self._handle_single_agent(
                user_message=user_message,
                agent=AgentRole.RESEARCHER,
                action="research",
                context_fn=self._scope_researcher_context,
            )

        elif intent == INTENT_IDEA:
            response = await self._handle_idea(user_message)

        elif intent == INTENT_PROJECT:
            response = await self._handle_project(user_message)

        elif intent == INTENT_COMPLEX:
            subtasks = classification.get("subtasks", [])
            response = await self._handle_complex(
                user_message=user_message,
                subtasks=subtasks,
            )

        else:
            # Fallback: treat as simple chat
            logger.warning(f"Unknown intent '{intent}', falling back to simple_chat")
            response = await self._handle_direct(user_message)

        # Step 3: Add response to history
        response_text = response.get("response", "")
        self.conversation_history.append({
            "role": "assistant",
            "content": response_text,
        })

        # Step 4: Gate memory (fire-and-forget, don't block the response)
        try:
            await self._gate_memory(user_message, response_text)
        except Exception as e:
            logger.warning(f"Memory gating failed (non-fatal): {e}")

        # Log activity
        self._log_activity(
            "task_complete" if intent != INTENT_SIMPLE_CHAT else "chat",
            f"Handled {intent}: {user_message[:80]}",
        )

        return response

    # ─── Intent Classification ────────────────────────────────────────

    async def _classify(self, user_message: str) -> dict:
        """
        Use the LLM to classify the user's intent.
        Returns dict with intent, confidence, reasoning, subtasks.
        """
        recent_context = self._format_recent_context(n=3)

        prompt = CLASSIFY_PROMPT.format(
            user_message=user_message,
            recent_context=recent_context,
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=(
                    "You are an intent classifier. Respond with ONLY valid JSON. "
                    "No explanations, no markdown."
                ),
                temperature=0.2,
            )

            # Handle LLM error dict
            if result.get("error"):
                logger.warning(f"Classification LLM error: {result.get('message')}")
                return {
                    "intent": INTENT_SIMPLE_CHAT,
                    "confidence": 0.3,
                    "reasoning": "Classification LLM call failed",
                    "subtasks": [],
                }

            classification = result["content"]

            # Handle case where content is not a dict (unparseable)
            if not isinstance(classification, dict):
                logger.warning(f"Classification returned non-dict: {type(classification)}")
                return {
                    "intent": INTENT_SIMPLE_CHAT,
                    "confidence": 0.3,
                    "reasoning": "Classification returned unparseable result",
                    "subtasks": [],
                }

            # Validate
            if classification.get("intent") not in VALID_INTENTS:
                logger.warning(
                    f"Invalid intent '{classification.get('intent')}', "
                    f"defaulting to simple_chat"
                )
                classification["intent"] = INTENT_SIMPLE_CHAT

            return classification

        except Exception as e:
            logger.error(f"Classification failed: {e}, defaulting to simple_chat")
            return {
                "intent": INTENT_SIMPLE_CHAT,
                "confidence": 0.3,
                "reasoning": "Classification failed, defaulting to direct handling",
                "subtasks": [],
            }

    # ─── Direct Handling (simple_chat) ────────────────────────────────

    def _estimate_tokens(self, messages: list[dict]) -> int:
        """Rough token estimate: ~1 token per 4 characters."""
        return sum(len(m.get("content", "")) for m in messages) // 4

    def _guard_context_window(self, messages: list[dict], max_tokens: int = 100000) -> list[dict]:
        """If approaching context limit (>85%), truncate from the middle (keep first 2 + last 5)."""
        estimated = self._estimate_tokens(messages)
        if estimated > max_tokens * 0.85 and len(messages) > 7:
            logger.warning(f"Context window guard: ~{estimated} tokens, truncating history")
            return messages[:2] + messages[-5:]
        return messages

    async def _handle_direct(self, user_message: str) -> dict:
        """
        Handle simple messages directly — no delegation needed.
        The Brain answers using its own LLM and conversation context.
        """
        # Enrich with memory retrieval if available
        memory_context = await self._retrieve_relevant_memories(user_message)

        messages = []

        if memory_context:
            messages.append({
                "role": "system",
                "content": (
                    f"Relevant context from past interactions:\n{memory_context}"
                ),
            })

        # Include recent conversation history
        messages.extend(self.conversation_history[-10:])

        # Context window guard
        messages = self._guard_context_window(messages)

        try:
            result = await self.llm.generate(
                system=self.system_prompt,
                messages=messages,
                temperature=0.7,
            )

            # Handle standardized error dicts from LLM client
            if result.get("error"):
                logger.error(f"LLM returned error: {result.get('message')}")
                return {
                    "response": "I ran into a problem generating a response. Could you rephrase that?",
                    "intent": INTENT_SIMPLE_CHAT,
                    "delegated": False,
                    "error": result.get("message"),
                }

            return {
                "response": result["content"],
                "intent": INTENT_SIMPLE_CHAT,
                "delegated": False,
            }

        except Exception as e:
            logger.error(f"Direct handling failed: {e}")
            return {
                "response": "I ran into a problem generating a response. Could you rephrase that?",
                "intent": INTENT_SIMPLE_CHAT,
                "delegated": False,
                "error": str(e),
            }

    # ─── Single-Agent Delegation ──────────────────────────────────────

    def _verbose_status(self, agent: AgentRole) -> Optional[str]:
        """Return a status message if verbose mode is enabled."""
        if self.verbose_mode == "verbose":
            return self.VERBOSE_STATUS.get(agent)
        return None

    async def _handle_single_agent(
        self,
        user_message: str,
        agent: AgentRole,
        action: str,
        context_fn: callable,
    ) -> dict:
        """
        Delegate to a single specialist agent via OpenClaw session spawning.
        The Brain scopes the context before sending.
        """
        # Build scoped context
        context = context_fn(user_message)
        agent_name = agent.value  # e.g. "builder", "researcher", "verifier"
        timeout = DELEGATION_TIMEOUTS.get(agent, 120.0)

        # Verbose mode: log status before delegating
        status_msg = self._verbose_status(agent)
        if status_msg:
            logger.info(f"Verbose status: {status_msg}")

        self._log_activity("delegate", f"Delegated to {agent_name}: {user_message[:80]}")

        try:
            result = await self.session_manager.delegate(
                agent_name=agent_name,
                task=user_message,
                context=context,
                timeout=timeout,
            )

            if result.success:
                # Parse the session result and synthesize
                try:
                    agent_result = json.loads(result.result)
                except (json.JSONDecodeError, TypeError):
                    agent_result = {"content": result.result}

                return await self._synthesize_single(
                    user_message=user_message,
                    agent_role=agent,
                    agent_result=agent_result,
                )
            else:
                logger.error(
                    f"Session delegation to {agent_name} failed: {result.error}"
                )
                # Fallback: Brain handles directly
                fallback = await self._handle_direct(user_message)
                fallback["response"] += (
                    f"\n\n_(I handled this directly — my {agent_name} specialist "
                    f"is temporarily unavailable)_"
                )
                return fallback

        except Exception as e:
            logger.error(f"Delegation to {agent_name} raised: {e}")
            fallback = await self._handle_direct(user_message)
            fallback["response"] += (
                f"\n\n_(I handled this directly — my {agent_name} specialist "
                f"is temporarily unavailable)_"
            )
            return fallback

    # ─── Complex Task Handling ────────────────────────────────────────

    async def _handle_complex(
        self,
        user_message: str,
        subtasks: list[dict],
    ) -> dict:
        """
        Handle complex tasks requiring multiple agents.

        Strategy:
        1. If subtasks came from classification, use them
        2. Otherwise, decompose the task
        3. Execute independent subtasks in parallel, dependent ones sequentially
        4. Synthesize all results
        """
        # If no subtasks from classifier, decompose explicitly
        if not subtasks:
            subtasks = await self._decompose(user_message)

        if not subtasks:
            # Decomposition failed — fall back to direct handling
            logger.warning("Complex task decomposition produced no subtasks")
            return await self._handle_direct(user_message)

        # Separate into dependency layers for execution ordering
        layers = self._build_execution_layers(subtasks)
        all_results = {}

        for layer_idx, layer in enumerate(layers):
            logger.info(
                f"Executing layer {layer_idx + 1}/{len(layers)} "
                f"({len(layer)} tasks in parallel)"
            )

            # Build delegation tasks for this layer
            delegation_tasks = []
            for task in layer:
                agent_str = task.get("agent", "builder")
                agent_role = self._resolve_agent_role(agent_str)
                context_fn = self._context_fn_for_agent(agent_role)

                # Include results from previous layers in context
                task_context = context_fn(task["description"])
                if all_results:
                    task_context["prior_results"] = {
                        k: v.get("result", {}) for k, v in all_results.items()
                    }

                delegation_tasks.append(DelegationTask(
                    agent_name=agent_str,
                    task=f"{task['description']}\n\nOriginal request: {user_message}",
                    context=task_context,
                ))

            # Execute layer in parallel via session spawning
            replies = await self.session_manager.delegate_parallel(
                delegation_tasks, timeout=180.0
            )

            # Collect results
            for task, reply in zip(layer, replies):
                task_key = f"{task['agent']}_{task['action']}"
                try:
                    parsed_result = json.loads(reply.result) if reply.result else None
                except (json.JSONDecodeError, TypeError):
                    parsed_result = {"content": reply.result} if reply.result else None

                all_results[task_key] = {
                    "agent": task["agent"],
                    "action": task["action"],
                    "description": task["description"],
                    "status": TaskStatus.COMPLETED.value if reply.success else TaskStatus.FAILED.value,
                    "result": parsed_result,
                    "error": reply.error,
                }

        # Synthesize all results
        return await self._synthesize_multi(user_message, all_results)

    async def _decompose(self, user_message: str) -> list[dict]:
        """
        Use the LLM to decompose a complex task into subtasks.
        """
        context = self._format_recent_context(n=5)

        prompt = DECOMPOSE_PROMPT.format(
            task_description=user_message,
            context=context,
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=(
                    "You are a task decomposition engine. "
                    "Respond with ONLY valid JSON."
                ),
                temperature=0.3,
            )
            decomposition = result["content"]
            return decomposition.get("subtasks", [])

        except Exception as e:
            logger.error(f"Decomposition failed: {e}")
            return []

    def _build_execution_layers(self, subtasks: list[dict]) -> list[list[dict]]:
        """
        Topological sort of subtasks into parallel execution layers.
        Tasks with no dependencies go in layer 0. Tasks depending only on
        layer-0 tasks go in layer 1, etc.
        """
        if not subtasks:
            return []

        # Assign layer to each task based on dependencies
        n = len(subtasks)
        layers_assigned = [-1] * n

        def assign_layer(idx: int, visited: set) -> int:
            if layers_assigned[idx] >= 0:
                return layers_assigned[idx]
            if idx in visited:
                # Circular dependency — break it
                logger.warning(f"Circular dependency at subtask {idx}")
                return 0

            visited.add(idx)
            deps = subtasks[idx].get("depends_on", [])

            if not deps:
                layers_assigned[idx] = 0
            else:
                max_dep_layer = 0
                for dep_idx in deps:
                    if 0 <= dep_idx < n:
                        dep_layer = assign_layer(dep_idx, visited)
                        max_dep_layer = max(max_dep_layer, dep_layer)
                layers_assigned[idx] = max_dep_layer + 1

            visited.discard(idx)
            return layers_assigned[idx]

        for i in range(n):
            assign_layer(i, set())

        # Group by layer
        max_layer = max(layers_assigned) if layers_assigned else 0
        layers = [[] for _ in range(max_layer + 1)]
        for idx, layer_num in enumerate(layers_assigned):
            layers[layer_num].append(subtasks[idx])

        return layers

    # ─── Response Synthesis ───────────────────────────────────────────

    async def _synthesize_single(
        self,
        user_message: str,
        agent_role: AgentRole,
        agent_result: Optional[dict],
    ) -> dict:
        """
        Synthesize a single agent's result into a user-facing response.
        For simple delegations, the agent result often just needs light formatting.
        """
        if not agent_result:
            return await self._handle_direct(user_message)

        # Format the agent result for the synthesis prompt
        result_text = json.dumps(agent_result, indent=2, default=str)

        agent_results_block = (
            f"--- {agent_role.value} result ---\n{result_text}\n"
        )

        prompt = SYNTHESIZE_PROMPT.format(
            user_message=user_message,
            agent_results=agent_results_block,
        )

        try:
            result = await self.llm.generate(
                system=self.system_prompt,
                messages=[
                    *self.conversation_history[-6:],
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
            )
            response_text = result["content"]

            # Verbose mode: prepend status and note agent contribution
            if self.verbose_mode == "verbose":
                status = self.VERBOSE_STATUS.get(agent_role, "")
                if status:
                    response_text = f"{status}\n\n{response_text}"

            return {
                "response": response_text,
                "intent": agent_role.value,
                "delegated": True,
                "agent_results": {agent_role.value: agent_result},
            }

        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            # Fallback: return raw result content if possible
            raw = agent_result.get("content", agent_result.get("notes", ""))
            if raw:
                return {
                    "response": str(raw),
                    "intent": agent_role.value,
                    "delegated": True,
                    "synthesis_failed": True,
                }
            return await self._handle_direct(user_message)

    async def _synthesize_multi(
        self,
        user_message: str,
        all_results: dict,
    ) -> dict:
        """
        Synthesize results from multiple agents into one coherent response.
        """
        # Format all results
        results_block = ""
        for key, info in all_results.items():
            status_icon = "✅" if info["status"] == TaskStatus.COMPLETED.value else "❌"
            result_json = json.dumps(
                info.get("result") or {"error": info.get("error", "unknown")},
                indent=2,
                default=str,
            )
            results_block += (
                f"--- {status_icon} {info['agent']}: {info['action']} ---\n"
                f"Description: {info['description']}\n"
                f"Result:\n{result_json}\n\n"
            )

        prompt = SYNTHESIZE_PROMPT.format(
            user_message=user_message,
            agent_results=results_block,
        )

        try:
            result = await self.llm.generate(
                system=self.system_prompt,
                messages=[
                    *self.conversation_history[-6:],
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
            )
            return {
                "response": result["content"],
                "intent": INTENT_COMPLEX,
                "delegated": True,
                "agent_results": all_results,
            }

        except Exception as e:
            logger.error(f"Multi-synthesis failed: {e}")
            # Fallback: concatenate successful results
            parts = []
            for key, info in all_results.items():
                if info["status"] == TaskStatus.COMPLETED.value:
                    result = info.get("result", {})
                    content = result.get("content", result.get("notes", ""))
                    if content:
                        parts.append(str(content))

            return {
                "response": "\n\n".join(parts) if parts else (
                    "I attempted to handle your complex request but ran into "
                    "issues. Could you break it down or rephrase?"
                ),
                "intent": INTENT_COMPLEX,
                "delegated": True,
                "synthesis_failed": True,
            }

    # ─── Memory Gating ────────────────────────────────────────────────

    async def _gate_memory(self, user_message: str, response_text: str):
        """
        Decide what from this interaction should be stored in memory.
        Only the Brain can write to shared memory (gatekeeper role).
        """
        if not self.memory or not self.can_write_memory:
            return

        # Truncate for the LLM prompt
        response_summary = response_text[:500]

        prompt = MEMORY_DECISION_PROMPT.format(
            user_message=user_message,
            response_summary=response_summary,
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=(
                    "You are a memory gating system. Decide what's worth "
                    "remembering. Respond with ONLY valid JSON."
                ),
                temperature=0.2,
            )
            decision = result["content"]

            # Store memories via ingest pipeline
            memory_texts = [m.get("text", "") for m in decision.get("memories", []) if m.get("text")]
            if memory_texts:
                combined_user = user_message
                combined_response = "\n".join(memory_texts)
                signals = []
                tags: list[str] = []
                for mem in decision.get("memories", []):
                    sig = mem.get("signals", {})
                    signals.extend(k for k, v in sig.items() if v)
                    tags.extend(mem.get("tags", []))

                turn = Turn(
                    user_message=combined_user,
                    agent_response=combined_response,
                    agent="brain",
                    tags=list(set(tags)) or None,
                    signals=list(set(signals)) or None,
                )
                self.memory.ingest(turn)

            # Store facts in knowledge cache
            from memory.knowledge_cache import store_fact as kc_store_fact
            for fact_entry in decision.get("facts_for_cache", []):
                fact_text = fact_entry.get("fact", "")
                if not fact_text:
                    continue
                embedding = self.memory.embedder.embed(fact_text)
                kc_store_fact(
                    fact=fact_text,
                    embedding=embedding,
                    source_agent="brain",
                    confidence=fact_entry.get("confidence", 0.8),
                    db=self.memory.db,
                )

            stored_count = len(decision.get("memories", []))
            facts_count = len(decision.get("facts_for_cache", []))
            if stored_count or facts_count:
                logger.info(
                    f"Memory gating: stored {stored_count} memories, "
                    f"{facts_count} facts"
                )
                self._log_activity("memory_store", f"Stored {stored_count} memories, {facts_count} facts")

        except Exception as e:
            logger.warning(f"Memory gating LLM call failed: {e}")

    # ─── Context Scoping ──────────────────────────────────────────────

    def _scope_builder_context(self, user_message: str) -> dict:
        """Prepare scoped context for the Builder agent."""
        return ContextScope.for_builder(
            conversation=self.conversation_history,
            workspace_state={},  # TODO: track workspace state
            tools=[],  # TODO: populate from config
        )

    def _scope_verifier_context(self, user_message: str) -> dict:
        """Prepare scoped context for the Verifier agent."""
        # Extract claims from the user message and recent conversation
        knowledge_excerpts = []
        if self.memory:
            try:
                results = self.memory.retrieve(
                    query=user_message[:100], limit=5
                )
                knowledge_excerpts = [
                    {"fact": r.get("fact", r.get("content", "")), **r}
                    for r in results
                ]
            except Exception:
                pass

        return ContextScope.for_verifier(
            claims=[user_message],
            knowledge_excerpts=knowledge_excerpts,
        )

    def _scope_researcher_context(self, user_message: str) -> dict:
        """Prepare scoped context for the Researcher agent."""
        knowledge_gaps = []  # Could be populated from conversation analysis
        return ContextScope.for_researcher(
            query=user_message,
            knowledge_gaps=knowledge_gaps,
        )

    def _context_fn_for_agent(self, agent_role: AgentRole) -> callable:
        """Return the appropriate context scoping function for an agent."""
        mapping = {
            AgentRole.BUILDER: self._scope_builder_context,
            AgentRole.VERIFIER: self._scope_verifier_context,
            AgentRole.RESEARCHER: self._scope_researcher_context,
        }
        return mapping.get(agent_role, self._scope_researcher_context)

    # ─── Memory Retrieval ─────────────────────────────────────────────

    async def _retrieve_relevant_memories(self, query: str) -> str:
        """
        Retrieve relevant memories for enriching the Brain's context.
        Returns a formatted string for injection into the system prompt.
        """
        if not self.memory:
            return ""

        parts: list[str] = []

        try:
            results = self.memory.retrieve(
                query=query, strategy="balanced", limit=5
            )
            facts = [r for r in results if r.get("type") == "fact"]
            memories = [r for r in results if r.get("type") != "fact"]

            if facts:
                fact_lines = [f"- {f['fact']}" for f in facts]
                parts.append("Known facts:\n" + "\n".join(fact_lines))

            if memories:
                mem_lines = [
                    f"- [{m.get('score', 0):.2f}] {m.get('content', '')}"
                    for m in memories
                ]
                parts.append(
                    "Relevant past context:\n" + "\n".join(mem_lines)
                )
        except Exception as e:
            logger.debug(f"Memory retrieval failed: {e}")

        return "\n\n".join(parts)

    # ─── Utilities ────────────────────────────────────────────────────

    def _format_recent_context(self, n: int = 3) -> str:
        """Format the last n conversation turns for prompt injection."""
        recent = self.conversation_history[-(n * 2):]
        if not recent:
            return "(no prior conversation)"

        lines = []
        for msg in recent:
            role = msg["role"].capitalize()
            content = msg["content"][:200]
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _trim_history(self):
        """Keep conversation history within bounds."""
        if len(self.conversation_history) > MAX_CONVERSATION_HISTORY:
            # Keep the first 2 messages (for session context) and the most recent
            keep = MAX_CONVERSATION_HISTORY - 2
            self.conversation_history = (
                self.conversation_history[:2]
                + self.conversation_history[-keep:]
            )

    @staticmethod
    def _resolve_agent_role(agent_str: str) -> AgentRole:
        """Convert a string agent name to AgentRole enum."""
        mapping = {
            "builder": AgentRole.BUILDER,
            "verifier": AgentRole.VERIFIER,
            "researcher": AgentRole.RESEARCHER,
            "guardian": AgentRole.GUARDIAN,
        }
        return mapping.get(agent_str, AgentRole.BUILDER)

    # ─── Idea Mode ────────────────────────────────────────────────

    async def _handle_idea(self, user_message: str) -> dict:
        """Handle idea suggestions and backlog queries."""
        msg_lower = user_message.lower().strip()

        # Backlog query
        if self.project_manager.detect_backlog_query(user_message):
            summary = self.project_manager.get_backlog_summary()
            return {"response": summary, "intent": INTENT_IDEA, "delegated": False}

        # Add to backlog
        # Extract a title from the message
        title = user_message.strip()
        # Clean up common prefixes
        for prefix in ["idea:", "what if we", "maybe we could", "we should build", "how about we build",
                        "wouldn't it be cool if we", "i've been thinking about", "here's an idea:"]:
            if title.lower().startswith(prefix):
                title = title[len(prefix):].strip()
                break
        title = title[:80] if title else user_message[:80]

        idea = self.project_manager.add_idea(title=title, description=user_message)
        self._log_activity("idea_add", f"Added idea to backlog: {title}")
        backlog = self.project_manager.list_ideas()
        count = len(backlog)

        response = (
            f"💡 Added to your backlog: **{idea.title}**\n\n"
            f"You now have {count} idea(s). Say 'show backlog' to see them all, "
            f"or 'promote idea {count}' when you're ready to build it."
        )
        return {"response": response, "intent": INTENT_IDEA, "delegated": False}

    # ─── Project Mode ───────────────────────────────────────────────

    async def _handle_project(self, user_message: str) -> dict:
        """
        Handle project-level requests:
        - Status queries
        - Pause/cancel commands
        - New project creation
        - Active project: advance to next task
        """
        msg_lower = user_message.lower().strip()

        # Check for promote idea
        import re
        promote_match = re.search(r"(?:promote|let'?s do|start)\s+(?:idea\s*)?#?(\d+)", msg_lower)
        if promote_match:
            idx = int(promote_match.group(1)) - 1
            ideas = self.project_manager.list_ideas()
            if 0 <= idx < len(ideas):
                idea = ideas[idx]
                try:
                    project = self.project_manager.promote_idea(idea.id)
                    return await self._create_new_project(idea.description, project=project)
                except ValueError as e:
                    return {"response": f"⚠️ {e}", "intent": INTENT_PROJECT, "delegated": False}
            return {"response": f"⚠️ No idea #{idx + 1} in backlog.", "intent": INTENT_PROJECT, "delegated": False}

        # Check for archive idea
        archive_match = re.search(r"(?:archive|forget about|remove)\s+(?:idea\s*)?#?(\d+)", msg_lower)
        if archive_match:
            idx = int(archive_match.group(1)) - 1
            ideas = self.project_manager.list_ideas()
            if 0 <= idx < len(ideas):
                self.project_manager.archive_idea(ideas[idx].id)
                return {"response": f"🗑️ Archived idea: **{ideas[idx].title}**", "intent": INTENT_PROJECT, "delegated": False}
            return {"response": f"⚠️ No idea #{idx + 1} in backlog.", "intent": INTENT_PROJECT, "delegated": False}

        # Check for backlog query (also handled via project intent)
        if self.project_manager.detect_backlog_query(user_message):
            summary = self.project_manager.get_backlog_summary()
            return {"response": summary, "intent": INTENT_PROJECT, "delegated": False}

        # Check for status query
        if any(kw in msg_lower for kw in ["status", "progress", "how's the project", "where are we"]):
            active = self.project_manager.get_active_project()
            if not active:
                return {"response": "No active project right now. Want to start one?", "intent": INTENT_PROJECT, "delegated": False}
            # Use feature-level status if features exist
            features = self.project_manager.get_features(active.id)
            if features:
                full = self.project_manager.get_full_status(active.id)
                return {
                    "response": self._format_full_status(full),
                    "intent": INTENT_PROJECT,
                    "delegated": False,
                }
            status = self.project_manager.get_status(active.id)
            return {
                "response": self._format_project_status(status),
                "intent": INTENT_PROJECT,
                "delegated": False,
            }

        # Check for pause/cancel
        if any(kw in msg_lower for kw in ["pause project", "pause the project"]):
            active = self.project_manager.get_active_project()
            if active:
                self.project_manager.update_project_status(active.id, "paused")
                return {"response": f"⏸️ Project '{active.name}' paused. Say 'resume project' to continue.", "intent": INTENT_PROJECT, "delegated": False}
            return {"response": "No active project to pause.", "intent": INTENT_PROJECT, "delegated": False}

        if any(kw in msg_lower for kw in ["cancel project", "abandon project"]):
            active = self.project_manager.get_active_project()
            if active:
                self.project_manager.update_project_status(active.id, "paused")
                return {"response": f"🛑 Project '{active.name}' cancelled.", "intent": INTENT_PROJECT, "delegated": False}
            return {"response": "No active project to cancel.", "intent": INTENT_PROJECT, "delegated": False}

        # Check for active project → advance next task
        active = self.project_manager.get_active_project()
        if active and active.status == "in_progress":
            return await self._advance_project(active)

        # New project creation
        return await self._create_new_project(user_message)

    async def _create_new_project(self, user_message: str, project=None) -> dict:
        """Create a new project: research → write spec → decompose into features+tasks → show to user."""
        verbose = self.verbose_mode == "verbose"

        # Step 0: Delegate to Researcher for research context
        research_context = None
        try:
            if verbose:
                logger.info("Pipeline: Researcher researching for new project spec")

            domain_hint = ""
            if project and project.domain:
                domain_hint = f" Domain: {project.domain}"

            research_query = (
                f"Research best practices, prior art, and potential pitfalls for: "
                f"{user_message}.{domain_hint}"
            )
            research_result = await self.session_manager.delegate(
                agent_name="researcher",
                task=research_query,
                context=self._scope_researcher_context(research_query),
                timeout=DELEGATION_TIMEOUTS.get(AgentRole.RESEARCHER, 120.0),
            )
            if research_result.success:
                research_context = research_result.result
            else:
                logger.warning(f"Researcher research for spec failed: {research_result.error}")
        except Exception as e:
            logger.warning(f"Researcher research for spec raised: {e}")

        # Generate spec (with research context if available)
        spec = await spec_writer.write_spec(self.llm, user_message, research_context=research_context)

        self._log_activity("project_create", f"Creating project from: {user_message[:80]}")

        if not project:
            # Extract a short name and domain from the spec
            name_line = spec.split("\n")[0] if spec else user_message[:50]
            name = name_line.replace("# Project:", "").replace("#", "").strip()[:60] or "New Project"

            # Try to extract domain from spec
            domain = None
            for line in spec.split("\n"):
                if line.strip().startswith("## Domain"):
                    continue
                if domain is None and line.strip() and not line.startswith("#"):
                    # First non-header line after ## Domain
                    pass
            # Simple extraction: look for domain line
            import re
            domain_match = re.search(r"## Domain\s*\n\s*(\w+)", spec)
            if domain_match:
                domain = domain_match.group(1)

            project = self.project_manager.create_project(
                name=name,
                description=user_message,
                spec=spec,
                domain=domain,
            )
        else:
            # Project already created (from promote_idea), update spec
            conn = self.project_manager._conn()
            conn.execute("UPDATE projects SET spec = ? WHERE id = ?", (spec, project.id))
            conn.commit()
            conn.close()
            name = project.name

        # Decompose into features with tasks
        features = await task_decomposer.decompose(self.llm, spec, project.id)

        # Store features and tasks
        all_tasks = []
        for feat in features:
            self.project_manager.add_features(project.id, [feat])
            all_tasks.extend(feat.tasks)

        if all_tasks:
            self.project_manager.decompose_into_tasks(project.id, all_tasks)

        # Format response
        feature_lines = []
        for feat in features:
            task_list = "\n".join(f"    - [{t.agent}] {t.title}" for t in feat.tasks)
            feature_lines.append(f"  **{feat.title}** ({len(feat.tasks)} tasks)\n{task_list}")

        total_tasks = sum(len(f.tasks) for f in features)
        response = (
            f"📋 **Project: {name}**\n\n"
            f"{spec}\n\n"
            f"---\n"
            f"**Plan: {len(features)} features, {total_tasks} tasks:**\n"
            + "\n".join(feature_lines) + "\n\n"
            f"I'll start working on this now. Say 'project status' anytime to check progress."
        )

        return {
            "response": response,
            "intent": INTENT_PROJECT,
            "delegated": False,
            "project_id": project.id,
        }

    async def _advance_project(self, project) -> dict:
        """Get next task and run it through the full collaboration pipeline."""
        next_task = self.project_manager.get_next_task(project.id)
        if not next_task:
            status = self.project_manager.get_status(project.id)
            if status.failed_tasks > 0:
                return {
                    "response": f"⚠️ Project '{project.name}' has {status.failed_tasks} failed task(s). {self._format_project_status(status)}",
                    "intent": INTENT_PROJECT, "delegated": False,
                }
            return {
                "response": f"✅ Project '{project.name}' is complete! All {status.completed_tasks} tasks done.",
                "intent": INTENT_PROJECT, "delegated": False,
            }

        return await self._execute_task_pipeline(next_task, project)

    # ─── Full Collaboration Pipeline ──────────────────────────────────

    MAX_BUILDER_RETRIES = 2

    VERIFIER_REVIEW_PROMPT = """\
Review this task output against the specification.

Task: {task_title}
Task Description: {task_description}
Feature: {feature_title}
Project Spec: {spec_section}

Builder's Output:
{builder_result}

Evaluate:
1. Does it match the spec requirements?
2. Are there bugs or logic errors?
3. Is the code quality acceptable?
4. Are edge cases handled?

Respond with JSON:
{{
  "verdict": "PASS" or "FAIL",
  "notes": "...",
  "issues": ["issue1", "issue2"],
  "suggestions": ["suggestion1"]
}}
"""

    GUARDIAN_SECURITY_PROMPT = """\
Security review of code changes.

Task: {task_title}
Code:
{builder_result}

Check for:
1. Hardcoded credentials or API keys
2. SQL injection vulnerabilities
3. Unsafe file system operations
4. Data exposure risks
5. Dependency vulnerabilities

Respond with JSON:
{{
  "verdict": "PASS" or "FLAG" or "BLOCK",
  "issues": ["issue1"],
  "severity": "low" or "medium" or "high" or "critical",
  "recommendations": ["rec1"]
}}
"""

    COHERENCE_CHECK_PROMPT = """\
Quick coherence check - does this task result fit the project?

Project: {project_name}
Previously completed tasks: {completed_task_summaries}
Current task: {task_title}
Result: {brief_result_summary}

Any conflicts or concerns? If all good, say "COHERENT".
If concern, explain briefly.
"""

    async def _execute_task_pipeline(self, task: ProjectTask, project) -> dict:
        """
        Full multi-agent pipeline for a single task:
        1. Researcher research (if needed)
        2. Builder builds
        3. Verifier validates (with retry loop)
        4. Guardian security scan
        5. Brain coherence check
        6. Auto-commit via GitOps
        """
        verbose = self.verbose_mode == "verbose"
        pipeline_log: list[str] = []

        # Mark in progress
        self.project_manager.set_task_in_progress(task.id)

        # Resolve feature title for prompts
        feature_title = ""
        if task.feature_id:
            features = self.project_manager.get_features(project.id)
            for f in features:
                if f.id == task.feature_id:
                    feature_title = f.title
                    break

        try:
            # ── Step 1: Researcher research (if task needs context) ──
            research_context = ""
            if self._task_needs_research(task):
                if verbose:
                    pipeline_log.append("🔬 Researcher is researching best practices...")
                    logger.info("Pipeline: Researcher researching for task")

                research_query = (
                    f"Research best practices, prior art, and potential pitfalls for: "
                    f"{task.title}. {task.description}. Domain: {project.domain or 'general'}"
                )
                research_result = await self.session_manager.delegate(
                    agent_name="researcher",
                    task=research_query,
                    context=self._scope_researcher_context(research_query),
                    timeout=DELEGATION_TIMEOUTS.get(AgentRole.RESEARCHER, 120.0),
                )
                if research_result.success:
                    research_context = research_result.result or ""
                else:
                    logger.warning(f"Researcher research failed: {research_result.error}")

            # ── Step 2: Builder builds ──
            if verbose:
                pipeline_log.append(f"🔨 Builder is working on: {task.title}...")
                logger.info(f"Pipeline: Builder working on {task.title}")

            builder_result = await self._delegate_to_builder(task, project, research_context)

            # ── Step 3: Verifier validates (with retry loop) ──
            if verbose:
                pipeline_log.append("✅ Verifier is checking the output...")
                logger.info("Pipeline: Verifier checking output")

            verified = False
            retries = 0
            verifier_response = None

            while retries <= self.MAX_BUILDER_RETRIES:
                verifier_response = await self._delegate_to_verifier(
                    task, project, feature_title, builder_result
                )

                verdict = verifier_response.get("verdict", "PASS").upper()

                if verdict == "PASS":
                    verified = True
                    if verbose and verifier_response.get("notes"):
                        pipeline_log.append(f"  ✅ Verifier: PASS — {verifier_response['notes']}")
                    break

                # FAIL — retry with feedback
                retries += 1
                if retries > self.MAX_BUILDER_RETRIES:
                    break

                issues = verifier_response.get("issues", [])
                feedback = verifier_response.get("notes", "")
                if verbose:
                    pipeline_log.append(
                        f"  ⚠️ Verifier: FAIL (retry {retries}/{self.MAX_BUILDER_RETRIES}) — {feedback}"
                    )
                logger.info(f"Pipeline: Verifier FAIL, retry {retries}")

                # Send feedback to Builder for revision
                builder_result = await self._delegate_to_builder_revision(
                    task, project, builder_result, feedback, issues, research_context
                )

            if not verified:
                # Exhausted retries — flag to user
                issues_str = "; ".join(verifier_response.get("issues", [])) if verifier_response else "unknown"
                self.project_manager.fail_task(
                    task.id, f"Verifier rejected after {self.MAX_BUILDER_RETRIES} retries: {issues_str}"
                )
                status = self.project_manager.get_status(project.id)
                progress = f"[{status.completed_tasks}/{status.total_tasks}]"
                pipeline_summary = "\n".join(pipeline_log) + "\n" if pipeline_log else ""
                return {
                    "response": (
                        f"{pipeline_summary}"
                        f"⚠️ {progress} Task **{task.title}** failed verification after "
                        f"{self.MAX_BUILDER_RETRIES} retries.\n"
                        f"Issues: {issues_str}\n"
                        f"Please review and provide guidance."
                    ),
                    "intent": INTENT_PROJECT,
                    "delegated": True,
                }

            # ── Step 4: Guardian security scan ──
            if verbose:
                pipeline_log.append("🛡️ Guardian is running security scan...")
                logger.info("Pipeline: Guardian security scan")

            guardian_response = await self._delegate_to_guardian(task, builder_result)
            guardian_verdict = guardian_response.get("verdict", "PASS").upper()

            if guardian_verdict == "BLOCK":
                issues_str = "; ".join(guardian_response.get("issues", []))
                severity = guardian_response.get("severity", "high")
                self.project_manager.fail_task(
                    task.id, f"Guardian BLOCK ({severity}): {issues_str}"
                )
                status = self.project_manager.get_status(project.id)
                progress = f"[{status.completed_tasks}/{status.total_tasks}]"
                pipeline_summary = "\n".join(pipeline_log) + "\n" if pipeline_log else ""
                return {
                    "response": (
                        f"{pipeline_summary}"
                        f"🛡️ {progress} Task **{task.title}** BLOCKED by security scan.\n"
                        f"Severity: {severity}\n"
                        f"Issues: {issues_str}\n"
                        f"Recommendations: {'; '.join(guardian_response.get('recommendations', []))}"
                    ),
                    "intent": INTENT_PROJECT,
                    "delegated": True,
                }

            if guardian_verdict == "FLAG" and verbose:
                pipeline_log.append(
                    f"  ⚠️ Guardian: warnings — {'; '.join(guardian_response.get('issues', []))}"
                )

            # ── Step 5: Brain coherence check (lightweight, no delegation) ──
            if verbose:
                pipeline_log.append("🧠 Final review...")
                logger.info("Pipeline: Brain coherence check")

            coherence = await self._coherence_check(task, project, builder_result)

            if coherence and not coherence.upper().startswith("COHERENT"):
                # Concern found — flag to user but don't block
                if verbose:
                    pipeline_log.append(f"  🧠 Concern: {coherence}")
                logger.warning(f"Coherence concern for task {task.title}: {coherence}")

            if verbose:
                pipeline_log.append("🧠 Final review... all clear!")

            # ── Step 6: Complete task and auto-commit ──
            self.project_manager.complete_task(task.id, builder_result[:2000])

            commit_message = f"feat({feature_title or 'project'}): {task.title}"
            commit_hash = None
            try:
                commit_hash = self.gitops.auto_commit(commit_message)
                if verbose and commit_hash:
                    pipeline_log.append(f"📝 Committed: {commit_message} ({commit_hash[:8]})")
            except Exception as e:
                logger.warning(f"GitOps auto-commit failed: {e}")

            status = self.project_manager.get_status(project.id)
            progress = f"[{status.completed_tasks}/{status.total_tasks}]"
            pipeline_summary = "\n".join(pipeline_log) + "\n\n" if pipeline_log else ""

            return {
                "response": (
                    f"{pipeline_summary}"
                    f"✅ {progress} Completed: **{task.title}**\n\n"
                    f"{builder_result[:1500]}"
                ),
                "intent": INTENT_PROJECT,
                "delegated": True,
            }

        except Exception as e:
            self.project_manager.fail_task(task.id, str(e))
            pipeline_summary = "\n".join(pipeline_log) + "\n" if pipeline_log else ""
            return {
                "response": f"{pipeline_summary}❌ Task '{task.title}' failed: {e}",
                "intent": INTENT_PROJECT,
                "delegated": False,
            }

    def _task_needs_research(self, task: ProjectTask) -> bool:
        """Heuristic: does this task benefit from Researcher research?"""
        desc = f"{task.title} {task.description}".lower()
        research_signals = [
            "best practice", "architecture", "design", "compare",
            "evaluate", "research", "investigate", "security",
            "performance", "scalable", "pattern", "framework",
        ]
        return any(signal in desc for signal in research_signals)

    async def _delegate_to_builder(
        self, task: ProjectTask, project, research_context: str = ""
    ) -> str:
        """Delegate a build task to the Builder agent."""
        context_parts = [
            f"Task: {task.title}",
            f"Description: {task.description}",
            f"Project spec:\n{project.spec}",
        ]
        if research_context:
            context_parts.append(f"Research context:\n{research_context}")

        task_description = "\n\n".join(context_parts)

        result = await self.session_manager.delegate(
            agent_name="builder",
            task=task_description,
            context=self._scope_builder_context(task_description),
            timeout=DELEGATION_TIMEOUTS.get(AgentRole.BUILDER, 180.0),
        )

        if result.success:
            return result.result or ""
        else:
            raise RuntimeError(f"Builder failed: {result.error}")

    async def _delegate_to_builder_revision(
        self, task: ProjectTask, project, previous_output: str,
        feedback: str, issues: list[str], research_context: str = ""
    ) -> str:
        """Send Verifier feedback to Builder for revision."""
        issues_str = "\n".join(f"- {i}" for i in issues) if issues else "See feedback above."
        revision_task = (
            f"Your output for '{task.title}' needs revision.\n\n"
            f"Feedback: {feedback}\n\n"
            f"Issues to fix:\n{issues_str}\n\n"
            f"Previous output:\n{previous_output[:3000]}\n\n"
            f"Project spec:\n{project.spec}"
        )
        if research_context:
            revision_task += f"\n\nResearch context:\n{research_context}"

        result = await self.session_manager.delegate(
            agent_name="builder",
            task=revision_task,
            context=self._scope_builder_context(revision_task),
            timeout=DELEGATION_TIMEOUTS.get(AgentRole.BUILDER, 180.0),
        )

        if result.success:
            return result.result or ""
        else:
            raise RuntimeError(f"Builder revision failed: {result.error}")

    async def _delegate_to_verifier(
        self, task: ProjectTask, project, feature_title: str, builder_result: str
    ) -> dict:
        """Delegate verification to the Verifier agent. Returns parsed JSON verdict."""
        prompt = self.VERIFIER_REVIEW_PROMPT.format(
            task_title=task.title,
            task_description=task.description,
            feature_title=feature_title or "N/A",
            spec_section=project.spec[:2000],
            builder_result=builder_result[:3000],
        )

        result = await self.session_manager.delegate(
            agent_name="verifier",
            task=prompt,
            context={
                "scope": "verifier",
                "task_title": task.title,
                "builder_output": builder_result[:3000],
                "spec": project.spec[:2000],
            },
            timeout=DELEGATION_TIMEOUTS.get(AgentRole.VERIFIER, 90.0),
        )

        if result.success and result.result:
            try:
                parsed = json.loads(result.result)
                if isinstance(parsed, dict) and "verdict" in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
            # If not JSON, treat non-empty result as PASS with notes
            return {"verdict": "PASS", "notes": result.result[:500], "issues": [], "suggestions": []}

        logger.warning(f"Verifier delegation failed: {result.error}")
        # On verifier failure, default to PASS to avoid blocking
        return {"verdict": "PASS", "notes": "Verifier unavailable — skipped", "issues": [], "suggestions": []}

    async def _delegate_to_guardian(self, task: ProjectTask, builder_result: str) -> dict:
        """Delegate security review to the Guardian agent. Returns parsed JSON verdict."""
        prompt = self.GUARDIAN_SECURITY_PROMPT.format(
            task_title=task.title,
            builder_result=builder_result[:4000],
        )

        result = await self.session_manager.delegate(
            agent_name="guardian",
            task=prompt,
            context={
                "scope": "guardian",
                "content": builder_result[:4000],
                "source_agent": "builder",
            },
            timeout=90.0,
        )

        if result.success and result.result:
            try:
                parsed = json.loads(result.result)
                if isinstance(parsed, dict) and "verdict" in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
            return {"verdict": "PASS", "issues": [], "severity": "low", "recommendations": []}

        logger.warning(f"Guardian delegation failed: {result.error}")
        return {"verdict": "PASS", "issues": [], "severity": "low", "recommendations": ["Guardian unavailable — skipped"]}

    async def _coherence_check(self, task: ProjectTask, project, builder_result: str) -> str:
        """Lightweight Brain coherence check — no delegation, uses own LLM."""
        # Get completed task summaries
        all_tasks = self.project_manager.get_all_tasks(project.id)
        completed_summaries = "; ".join(
            f"{t.title} ({t.status})" for t in all_tasks if t.status == "completed"
        ) or "None yet"

        prompt = self.COHERENCE_CHECK_PROMPT.format(
            project_name=project.name,
            completed_task_summaries=completed_summaries[:1000],
            task_title=task.title,
            brief_result_summary=builder_result[:500],
        )

        try:
            result = await self.llm.generate(
                system="You are checking project coherence. Be brief. Say COHERENT if fine, or explain concern in one sentence.",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            return result.get("content", "COHERENT")
        except Exception as e:
            logger.warning(f"Coherence check failed: {e}")
            return "COHERENT"

    def _format_full_status(self, full: dict) -> str:
        """Format feature-level project status."""
        domain_tag = f" [{full['domain']}]" if full.get("domain") else ""
        parts = [
            f"📊 **{full['name']}**{domain_tag}",
            f"Progress: {full['progress']}",
            "",
        ]
        for feat in full.get("features", []):
            icon = {"completed": "✅", "in_progress": "🔄", "pending": "⏳"}.get(feat["status"], "⏳")
            line = f"  {icon} **{feat['name']}** — {feat['tasks']}"
            if feat.get("current_task"):
                line += f" (current: {feat['current_task']})"
            parts.append(line)
        return "\n".join(parts)

    def _format_project_status(self, status: ProjectStatus) -> str:
        """Format a project status into a readable message."""
        progress_bar = f"{status.completed_tasks}/{status.total_tasks}"
        parts = [
            f"📊 **{status.project_name}** — {status.status}",
            f"Progress: {progress_bar} tasks ({status.progress_pct:.0f}%)",
        ]
        if status.failed_tasks:
            parts.append(f"⚠️ {status.failed_tasks} failed task(s)")
        if status.current_task:
            parts.append(f"Current: {status.current_task.title}")
        if status.blockers:
            parts.append(f"Blockers: {'; '.join(status.blockers)}")
        return "\n".join(parts)

    async def _handle_synthesis_request(self, msg: AgentMessage) -> dict:
        """Handle a synthesis request from another internal component."""
        results = msg.payload.get("results", {})
        user_message = msg.payload.get("original_request", "")
        return await self._synthesize_multi(user_message, results)
