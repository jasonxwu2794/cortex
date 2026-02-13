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
from memory.engine import MemoryEngine, Turn

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Intent categories the classifier outputs
INTENT_SIMPLE_CHAT = "simple_chat"
INTENT_BUILD = "build_request"
INTENT_FACTUAL = "factual_question"
INTENT_RESEARCH = "research_request"
INTENT_COMPLEX = "complex_task"

VALID_INTENTS = {
    INTENT_SIMPLE_CHAT,
    INTENT_BUILD,
    INTENT_FACTUAL,
    INTENT_RESEARCH,
    INTENT_COMPLEX,
}

# Max conversation turns to keep in working memory
MAX_CONVERSATION_HISTORY = 50

# Delegation timeout per agent type (seconds)
DELEGATION_TIMEOUTS = {
    AgentRole.BUILDER: 180.0,       # Code gen can take a while
    AgentRole.VERIFIER: 90.0,
    AgentRole.INVESTIGATOR: 120.0,
}

# ─── Classification Prompt ────────────────────────────────────────────────────

CLASSIFY_PROMPT = """\
Classify the user's intent into exactly one category. Respond with ONLY a JSON object.

Categories:
- "simple_chat": Greetings, casual talk, opinions, simple questions you can answer from general knowledge. No specialist needed.
- "build_request": Code generation, file creation/editing, tool execution, automation, debugging, anything that produces artifacts.
- "factual_question": Specific factual claims to verify, "is this true?", data lookups, corrections.
- "research_request": Open-ended investigation, comparisons, "find out about...", market research, multi-source synthesis.
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
      "agent": "builder|verifier|investigator",
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
- investigator: Information gathering, multi-source synthesis. Has web access. Good at breadth.

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
      "agent": "builder|verifier|investigator",
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

    def __init__(self, memory_db_path: str = "data/memory.db", **kwargs):
        memory = MemoryEngine(db_path=memory_db_path)
        super().__init__(memory=memory, **kwargs)
        self.conversation_history: list[dict] = []
        self._system_prompt_text: Optional[str] = None
        self.session_manager = AgentSessionManager()

    # ─── BaseAgent interface ──────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        if self._system_prompt_text is None:
            prompt_path = Path(__file__).parent / "system_prompt.md"
            if prompt_path.exists():
                self._system_prompt_text = prompt_path.read_text()
            else:
                self._system_prompt_text = (
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
        """
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
                agent=AgentRole.INVESTIGATOR,
                action="research",
                context_fn=self._scope_investigator_context,
            )

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
            classification = result["content"]

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

        try:
            result = await self.llm.generate(
                system=self.system_prompt,
                messages=messages,
                temperature=0.7,
            )
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
        agent_name = agent.value  # e.g. "builder", "investigator", "verifier"
        timeout = DELEGATION_TIMEOUTS.get(agent, 120.0)

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
                # Fallback: try handling directly
                return await self._handle_direct(user_message)

        except Exception as e:
            logger.error(f"Delegation to {agent_name} raised: {e}")
            return await self._handle_direct(user_message)

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
            return {
                "response": result["content"],
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

    def _scope_investigator_context(self, user_message: str) -> dict:
        """Prepare scoped context for the Investigator agent."""
        knowledge_gaps = []  # Could be populated from conversation analysis
        return ContextScope.for_investigator(
            query=user_message,
            knowledge_gaps=knowledge_gaps,
        )

    def _context_fn_for_agent(self, agent_role: AgentRole) -> callable:
        """Return the appropriate context scoping function for an agent."""
        mapping = {
            AgentRole.BUILDER: self._scope_builder_context,
            AgentRole.VERIFIER: self._scope_verifier_context,
            AgentRole.INVESTIGATOR: self._scope_investigator_context,
        }
        return mapping.get(agent_role, self._scope_investigator_context)

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
            "investigator": AgentRole.INVESTIGATOR,
            "guardian": AgentRole.GUARDIAN,
        }
        return mapping.get(agent_str, AgentRole.BUILDER)

    async def _handle_synthesis_request(self, msg: AgentMessage) -> dict:
        """Handle a synthesis request from another internal component."""
        results = msg.payload.get("results", {})
        user_message = msg.payload.get("original_request", "")
        return await self._synthesize_multi(user_message, results)
