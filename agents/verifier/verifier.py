"""
OpenClaw Distro — Verifier Agent (Editor / QA)

The Verifier verifies claims, detects hallucinations, and maintains the
knowledge cache of verified facts.

Verification pipeline per claim:
1. Knowledge cache lookup — already verified? If confidence ≥ 0.9, done.
2. Self-consistency check — ask the same question multiple ways; divergence = flag.
3. Web verification — search authoritative sources (has external network access).
4. Confidence scoring — 0.0–1.0 based on evidence quality.

For batch verification (3+ claims), sub-agents verify claims in parallel,
then the parent aggregates and cross-references results.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from agents.common.base_agent import BaseAgent
from agents.common.protocol import AgentRole, AgentMessage, TaskStatus
from agents.common.sub_agent import SubAgentPool, SubTask, SubResult

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Use sub-agents when this many claims need verification
BATCH_THRESHOLD = 3

# Below this confidence from the cache we re-verify anyway
CACHE_CONFIDENCE_THRESHOLD = 0.9

# ─── Prompts ──────────────────────────────────────────────────────────────────

EXTRACT_CLAIMS_PROMPT = """\
Extract individual, verifiable factual claims from this text.
Ignore opinions, greetings, and subjective statements.
Only extract claims that can be verified as true or false.

Text:
{text}

Respond with ONLY a JSON object:
{{
  "claims": [
    "<specific factual claim 1>",
    "<specific factual claim 2>"
  ]
}}

If there are no verifiable claims, return {{"claims": []}}.
"""

VERIFY_SINGLE_PROMPT = """\
Verify this specific factual claim. Be conservative — when uncertain, say so.

Claim: "{claim}"

Known facts from cache (may be relevant):
{known_facts}

Your verification process:
1. Check if the known facts already confirm or contradict this claim.
2. Assess whether this claim matches common hallucination patterns:
   - Fabricated API endpoints or function names
   - Invented statistics or percentages
   - Non-existent libraries or tools
   - Incorrect version numbers
   - Plausible but wrong formulas
   - Fabricated quotes or attributions
3. Use your training knowledge to assess the claim's plausibility.
4. Assign a confidence score based on evidence quality.

Respond with ONLY a JSON object:
{{
  "claim": "{claim}",
  "status": "verified|corrected|unverified|false",
  "confidence": <0.0-1.0>,
  "correction": "<corrected version if status is 'corrected', else null>",
  "sources": ["<source URLs or 'training knowledge'>"],
  "reasoning": "<brief explanation of your assessment>",
  "hallucination_risk": "<none|low|medium|high>",
  "new_fact": {{
    "fact": "<verified fact to cache, or null if unverified>",
    "category": "<technical|financial|general|scientific|historical>",
    "confidence": <0.0-1.0>
  }}
}}
"""

CONSISTENCY_CHECK_PROMPT = """\
I need to verify a claim by checking its consistency from multiple angles.
Ask the SAME underlying question in {n} different ways and answer each independently.

Claim to verify: "{claim}"

For each rephrasing, answer it independently based on your knowledge.
Then assess whether the answers are consistent.

Respond with ONLY a JSON object:
{{
  "rephrasings": [
    {{
      "question": "<rephrased question>",
      "answer": "<your answer>",
      "supports_claim": <true|false|null>
    }}
  ],
  "consistency": {{
    "all_agree": <true|false>,
    "agreement_ratio": <0.0-1.0>,
    "divergence_notes": "<explanation if answers disagree>"
  }}
}}
"""

AGGREGATE_PROMPT = """\
Aggregate these individual claim verification results into a final report.

Original request: {original_request}

Individual verifications:
{verifications_json}

Cross-reference the results:
1. Are any corrections contradictory?
2. Do the verifications paint a consistent picture?
3. Which facts are confident enough to cache?

Respond with ONLY a JSON object:
{{
  "verifications": [
    {{
      "claim": "<claim text>",
      "status": "verified|corrected|unverified|false",
      "confidence": <0.0-1.0>,
      "correction": "<or null>",
      "sources": [],
      "reasoning": "<brief>"
    }}
  ],
  "overall_confidence": <0.0-1.0>,
  "corrections_needed": ["<list of claims that need correction in the original>"],
  "cross_reference_notes": "<any inconsistencies found across verifications>",
  "new_facts_for_cache": [
    {{
      "fact": "<verified fact>",
      "category": "<category>",
      "confidence": <0.0-1.0>,
      "source": "<source>"
    }}
  ]
}}
"""


# ─── Verifier Agent ───────────────────────────────────────────────────────

class VerifierAgent(BaseAgent):
    """
    The Verifier — Editor and QA agent.

    Modes:
    1. Single claim verification (direct LLM call + cache check)
    2. Batch verification (parallel sub-agents, one per claim)
    3. Consistency check (multi-angle questioning of a single claim)
    """

    role = AgentRole.VERIFIER
    name = "verifier"
    model = "deepseek-reasoner"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._system_prompt_text: Optional[str] = None
        self._knowledge_cache_path = Path(
            os.environ.get("KNOWLEDGE_CACHE_PATH", "/data/knowledge")
        )

    # ─── BaseAgent interface ──────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        if self._system_prompt_text is None:
            self._system_prompt_text = self.build_system_prompt() or (
                "You are the Verifier agent. Verify claims conservatively. "
                "Return structured JSON with verifications and confidence scores."
            )
        return self._system_prompt_text

    def _supports_sub_agents(self) -> bool:
        """Verifier uses sub-agents for batch verification."""
        return True

    @property
    def sub_agent_system_prompt(self) -> str:
        return (
            "You are a Verifier sub-agent. Verify a single factual claim. "
            "Be conservative — when uncertain, say 'unverified' not 'verified'. "
            "Respond with ONLY valid JSON."
        )

    async def handle_task(self, msg: AgentMessage) -> Optional[dict]:
        """Route incoming verification tasks."""
        action = msg.action
        payload = msg.payload
        context = msg.context

        if action == "verify":
            return await self._handle_verify(payload, context)
        elif action == "consistency_check":
            claim = payload.get("claim", payload.get("message", ""))
            return await self._handle_consistency_check(claim)
        elif action == "execute":
            # Generic action from complex task decomposition
            return await self._handle_verify(payload, context)
        else:
            logger.warning(f"Verifier received unknown action: {action}")
            return await self._handle_verify(payload, context)

    async def on_startup(self):
        """Ensure knowledge cache directory exists."""
        self._knowledge_cache_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Verifier knowledge cache: {self._knowledge_cache_path}")

    # ─── Verify Flow ──────────────────────────────────────────────────

    async def _handle_verify(self, payload: dict, context: dict) -> dict:
        """
        Main verification pipeline:
        1. Extract claims from the message or use pre-extracted claims
        2. Check each claim against the knowledge cache
        3. For uncached claims: verify (single or batch parallel)
        4. Update knowledge cache with high-confidence results
        5. Return structured verification report
        """
        message = payload.get("message", "")

        # Claims might come pre-extracted from the Brain's context
        claims = context.get("claims_to_verify", [])

        # If claims is just a single string (the user message), extract claims from it
        if len(claims) == 1 and claims[0] == message:
            claims = await self._extract_claims(message)
        elif not claims:
            claims = await self._extract_claims(message)

        if not claims:
            return {
                "verifications": [],
                "overall_confidence": 1.0,
                "corrections_needed": [],
                "new_facts_for_cache": [],
                "notes": "No verifiable factual claims found in the input.",
            }

        logger.info(f"Verifying {len(claims)} claim(s)")

        # Phase 1: Check knowledge cache
        cached_results = []
        uncached_claims = []

        for claim in claims:
            cached = self._check_cache(claim)
            if cached and cached.get("confidence", 0) >= CACHE_CONFIDENCE_THRESHOLD:
                cached_results.append({
                    "claim": claim,
                    "status": "verified",
                    "confidence": cached["confidence"],
                    "correction": None,
                    "sources": [cached.get("source", "knowledge cache")],
                    "reasoning": f"Previously verified (cached, confidence={cached['confidence']})",
                })
                logger.debug(f"Cache hit for: {claim[:60]}...")
            else:
                uncached_claims.append(claim)

        # Phase 2: Verify uncached claims
        if uncached_claims:
            if len(uncached_claims) >= BATCH_THRESHOLD and self.sub_pool:
                fresh_results = await self._batch_verify(uncached_claims, context)
            else:
                fresh_results = await self._sequential_verify(uncached_claims, context)
        else:
            fresh_results = []

        # Combine
        all_verifications = cached_results + fresh_results

        # Phase 3: Aggregate and cross-reference
        report = await self._aggregate(message, all_verifications)

        # Phase 4: Update knowledge cache with high-confidence new facts
        new_facts = report.get("new_facts_for_cache", [])
        for fact_entry in new_facts:
            self._store_fact(fact_entry)

        return report

    # ─── Claim Extraction ─────────────────────────────────────────────

    async def _extract_claims(self, text: str) -> list[str]:
        """Use the LLM to extract verifiable claims from free text."""
        prompt = EXTRACT_CLAIMS_PROMPT.format(text=text[:2000])

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system="Extract factual claims. Respond with ONLY JSON.",
                temperature=0.1,
            )
            claims = result["content"].get("claims", [])
            logger.info(f"Extracted {len(claims)} claims from text")
            return claims
        except Exception as e:
            logger.warning(f"Claim extraction failed: {e}")
            # Fallback: treat the whole text as one claim
            return [text[:500]] if text.strip() else []

    # ─── Sequential Verification ──────────────────────────────────────

    async def _sequential_verify(
        self, claims: list[str], context: dict
    ) -> list[dict]:
        """Verify claims one by one (for small batches)."""
        results = []
        known_facts = self._format_known_facts(context)

        for claim in claims:
            verification = await self._verify_single(claim, known_facts)
            results.append(verification)

        return results

    async def _verify_single(self, claim: str, known_facts: str) -> dict:
        """
        Verify a single claim through the full pipeline:
        1. LLM verification with known facts context
        2. If confidence is borderline (0.4–0.7), run consistency check
        """
        prompt = VERIFY_SINGLE_PROMPT.format(
            claim=claim,
            known_facts=known_facts or "(no cached facts available)",
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=self.system_prompt,
                temperature=0.2,
            )
            verification = result["content"]
        except Exception as e:
            logger.warning(f"Verification failed for claim: {e}")
            return {
                "claim": claim,
                "status": "unverified",
                "confidence": 0.0,
                "correction": None,
                "sources": [],
                "reasoning": f"Verification failed: {e}",
            }

        # If borderline confidence, run consistency check to strengthen/weaken
        confidence = verification.get("confidence", 0.5)
        if 0.4 <= confidence <= 0.7:
            consistency = await self._run_consistency_check(claim)
            if consistency:
                agreement = consistency.get("consistency", {}).get("agreement_ratio", 0.5)
                # Adjust confidence based on consistency
                if agreement >= 0.9:
                    verification["confidence"] = min(confidence + 0.15, 1.0)
                    verification["reasoning"] += " (consistency check: strong agreement)"
                elif agreement <= 0.4:
                    verification["confidence"] = max(confidence - 0.2, 0.0)
                    verification["status"] = "unverified"
                    verification["reasoning"] += " (consistency check: significant divergence)"

        return verification

    # ─── Batch Verification (Parallel Sub-Agents) ─────────────────────

    async def _batch_verify(
        self, claims: list[str], context: dict
    ) -> list[dict]:
        """
        Verify multiple claims in parallel using sub-agents.
        Each sub-agent handles one claim independently.
        """
        known_facts = self._format_known_facts(context)

        subtasks = []
        for i, claim in enumerate(claims):
            prompt = VERIFY_SINGLE_PROMPT.format(
                claim=claim,
                known_facts=known_facts or "(no cached facts available)",
            )
            subtasks.append(SubTask(
                id=f"verify_{i}",
                description=prompt,
                context={"claim": claim},
                constraints={"max_sources": 3},
            ))

        logger.info(f"Batch verifying {len(subtasks)} claims in parallel")
        sub_results = await self.sub_pool.execute_parallel(subtasks)

        # Parse sub-agent results
        verifications = []
        for claim, result in zip(claims, sub_results):
            if result.success:
                output = result.output
                if isinstance(output, str):
                    try:
                        output = json.loads(output)
                    except json.JSONDecodeError:
                        output = {}

                verifications.append({
                    "claim": claim,
                    "status": output.get("status", "unverified"),
                    "confidence": output.get("confidence", result.confidence),
                    "correction": output.get("correction"),
                    "sources": output.get("sources", []),
                    "reasoning": output.get("reasoning", ""),
                })
            else:
                verifications.append({
                    "claim": claim,
                    "status": "unverified",
                    "confidence": 0.0,
                    "correction": None,
                    "sources": [],
                    "reasoning": f"Sub-agent failed: {result.error}",
                })

        return verifications

    # ─── Consistency Check ────────────────────────────────────────────

    async def _handle_consistency_check(self, claim: str) -> dict:
        """
        Standalone consistency check — ask the same question multiple ways
        and check if the answers agree.
        """
        result = await self._run_consistency_check(claim)
        if result is None:
            return {
                "claim": claim,
                "consistency": {"all_agree": False, "agreement_ratio": 0.0},
                "error": "Consistency check failed",
            }
        result["claim"] = claim
        return result

    async def _run_consistency_check(self, claim: str) -> Optional[dict]:
        """Run a multi-angle consistency check on a single claim."""
        prompt = CONSISTENCY_CHECK_PROMPT.format(claim=claim, n=3)

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=(
                    "You are checking claim consistency. Rephrase and answer "
                    "independently. Respond with ONLY JSON."
                ),
                temperature=0.4,  # Slightly higher for diverse rephrasings
            )
            return result["content"]
        except Exception as e:
            logger.warning(f"Consistency check failed: {e}")
            return None

    # ─── Aggregation ──────────────────────────────────────────────────

    async def _aggregate(
        self, original_request: str, verifications: list[dict]
    ) -> dict:
        """
        Aggregate individual verifications into a final report.
        Cross-references results and computes overall confidence.
        """
        if not verifications:
            return {
                "verifications": [],
                "overall_confidence": 1.0,
                "corrections_needed": [],
                "new_facts_for_cache": [],
            }

        # For small batches, skip the LLM aggregation and compute directly
        if len(verifications) <= 2:
            return self._simple_aggregate(verifications)

        # For larger batches, use LLM to cross-reference
        verifications_json = json.dumps(verifications, indent=2, default=str)

        prompt = AGGREGATE_PROMPT.format(
            original_request=original_request[:500],
            verifications_json=verifications_json,
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=(
                    "Aggregate verification results. Cross-reference for "
                    "consistency. Respond with ONLY JSON."
                ),
                temperature=0.2,
            )
            return result["content"]
        except Exception as e:
            logger.warning(f"Aggregation LLM failed: {e}, using simple aggregate")
            return self._simple_aggregate(verifications)

    def _simple_aggregate(self, verifications: list[dict]) -> dict:
        """
        Direct aggregation without LLM — for small batches or as fallback.
        """
        corrections_needed = []
        new_facts = []
        confidences = []

        for v in verifications:
            conf = v.get("confidence", 0.0)
            confidences.append(conf)

            if v.get("status") in ("corrected", "false"):
                corrections_needed.append(v.get("claim", ""))

            # Cache high-confidence verified facts
            if v.get("status") == "verified" and conf >= 0.85:
                new_facts.append({
                    "fact": v["claim"],
                    "category": "general",
                    "confidence": conf,
                    "source": (v.get("sources") or ["verification"])[0],
                })

            # Also cache corrections
            if v.get("status") == "corrected" and v.get("correction") and conf >= 0.8:
                new_facts.append({
                    "fact": v["correction"],
                    "category": "general",
                    "confidence": conf,
                    "source": (v.get("sources") or ["correction"])[0],
                })

        overall = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "verifications": verifications,
            "overall_confidence": round(overall, 3),
            "corrections_needed": corrections_needed,
            "new_facts_for_cache": new_facts,
        }

    # ─── Knowledge Cache ──────────────────────────────────────────────

    def _check_cache(self, claim: str) -> Optional[dict]:
        """
        Check if a claim (or something close) is in the knowledge cache.
        Uses the memory engine's lookup_facts if available.
        """
        if not self.memory:
            return None

        try:
            # Search by text similarity in the knowledge cache
            results = self.memory.lookup_facts(
                query=claim[:100],
                min_confidence=0.5,
                limit=3,
            )
            if results:
                # Return the best match
                return {
                    "fact": results[0]["fact"],
                    "confidence": results[0]["confidence"],
                    "source": results[0].get("source", "cache"),
                    "category": results[0].get("category", "general"),
                }
        except Exception as e:
            logger.debug(f"Cache lookup failed: {e}")

        return None

    def _store_fact(self, fact_entry: dict):
        """Store a verified fact in the knowledge cache."""
        if not self.memory:
            return

        fact_text = fact_entry.get("fact", "")
        if not fact_text:
            return

        try:
            self.memory.store_fact(
                fact=fact_text,
                category=fact_entry.get("category", "general"),
                source=fact_entry.get("source"),
                confidence=fact_entry.get("confidence", 0.8),
                verified_by="verifier",
                tags=fact_entry.get("tags", []),
            )
            logger.debug(f"Cached fact: {fact_text[:60]}...")
        except Exception as e:
            logger.warning(f"Failed to cache fact: {e}")

    def _format_known_facts(self, context: dict) -> str:
        """Format known facts from context for injection into prompts."""
        known = context.get("known_facts", [])
        if not known:
            return ""

        if isinstance(known, list) and known:
            if isinstance(known[0], dict):
                lines = [f"- {f.get('fact', str(f))}" for f in known]
            else:
                lines = [f"- {f}" for f in known]
            return "\n".join(lines)

        return str(known)
