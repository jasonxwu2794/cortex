"""
OpenClaw Distro — Researcher Agent (Analyst / Librarian)

The Researcher gathers information from multiple sources in parallel and
synthesizes it into a coherent research brief.

Key difference from other agents: the Researcher ALWAYS uses sub-agents.
Every research query is decomposed into 3–6 independent investigation
threads that run in parallel, then synthesized.

Pipeline:
1. Decompose query into independent investigation threads
2. Spawn parallel sub-agents (one per thread)
3. Collect and evaluate results (source quality scoring)
4. Synthesize into a unified research brief
5. Cache high-confidence findings in the knowledge cache
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

MIN_THREADS = 3
MAX_THREADS = 6
DEFAULT_THREADS = 4

# Source quality tiers (used in scoring)
SOURCE_QUALITY = {
    "official_docs": 1.0,
    "peer_reviewed": 0.95,
    "official_blog": 0.85,
    "news_reputable": 0.75,
    "community_docs": 0.6,
    "forum_social": 0.4,
    "unknown": 0.3,
}

# ─── Prompts ──────────────────────────────────────────────────────────────────

DECOMPOSE_PROMPT = """\
Break this research query into {n} independent investigation threads.

Query: {query}

Known knowledge gaps:
{knowledge_gaps}

Preferred sources: {preferred_sources}

Rules for thread decomposition:
- Each thread must be answerable WITHOUT results from other threads
- Each thread should be specific enough for a focused investigation
- Minimize overlap between threads
- At least ONE thread must focus on risks, caveats, or counterarguments
- If the query involves comparison, dedicate one thread per option being compared

Respond with ONLY a JSON object:
{{
  "threads": [
    {{
      "id": "<short_id>",
      "focus": "<what this thread investigates>",
      "search_queries": ["<2-3 specific search queries>"],
      "expected_source_types": ["official_docs|peer_reviewed|official_blog|news_reputable|community_docs"],
      "is_risk_thread": false
    }}
  ],
  "thread_count": <number>,
  "reasoning": "<why this decomposition>"
}}
"""

INVESTIGATE_PROMPT = """\
You are a research sub-agent investigating one specific thread of a larger query.

Original query: {original_query}

Your investigation focus: {focus}

Suggested search queries: {search_queries}

Expected source types: {expected_source_types}

Investigate thoroughly using your knowledge. For each finding:
- Note the source type and reliability
- Distinguish facts from opinions
- Flag anything time-sensitive or potentially outdated

Respond with ONLY a JSON object:
{{
  "thread_id": "{thread_id}",
  "focus": "{focus}",
  "findings": [
    {{
      "finding": "<specific finding>",
      "confidence": <0.0-1.0>,
      "source": "<source URL or description>",
      "source_type": "<official_docs|peer_reviewed|official_blog|news_reputable|community_docs|forum_social|training_knowledge>",
      "is_time_sensitive": false,
      "relevance": "high|medium|low"
    }}
  ],
  "risks_found": [
    "<any risks, caveats, or counterarguments discovered>"
  ],
  "knowledge_gaps": [
    "<what you couldn't find or verify>"
  ],
  "facts_worth_caching": [
    {{
      "fact": "<verified factual statement>",
      "category": "<technical|financial|general|scientific|market>",
      "confidence": <0.0-1.0>,
      "source": "<source>"
    }}
  ]
}}
"""

SYNTHESIZE_PROMPT = """\
Synthesize these parallel research results into a coherent research brief.

Original query: {query}

Investigation results:
{thread_results}

Your job:
1. Merge findings across threads — remove duplicates, resolve contradictions
2. Weight findings by source quality (official docs > peer reviewed > blogs > forums)
3. Build a clear narrative that answers the original query
4. Highlight the strongest findings (high confidence + high-quality source)
5. Aggregate all risks and knowledge gaps
6. If threads found contradictory information, call it out explicitly
7. Produce comparison tables if the query involved comparing options

Respond with ONLY a JSON object:
{{
  "summary": "<2-3 paragraph synthesis answering the original query>",
  "key_findings": [
    {{
      "finding": "<finding>",
      "confidence": <0.0-1.0>,
      "sources": ["<source>"],
      "relevance": "high|medium|low"
    }}
  ],
  "comparisons": [
    {{
      "subject": "<X vs Y>",
      "criteria": ["<criterion1>", "<criterion2>"],
      "winner": "<contextual winner>",
      "details": "<explanation>"
    }}
  ],
  "risks_and_caveats": [
    "<aggregated risks>"
  ],
  "knowledge_gaps": [
    "<what we still don't know>"
  ],
  "contradictions": [
    "<any contradictions found between threads>"
  ],
  "recommended_next_steps": [
    "<suggested follow-up>"
  ],
  "facts_for_cache": [
    {{
      "fact": "<high-confidence finding>",
      "category": "<category>",
      "confidence": <0.0-1.0>,
      "source": "<source>"
    }}
  ],
  "overall_confidence": <0.0-1.0>,
  "source_quality_summary": "<how reliable the overall source base is>"
}}
"""


# ─── Researcher Agent ─────────────────────────────────────────────────────────

class ResearcherAgent(BaseAgent):
    """
    The Researcher — always-parallel investigation agent.

    Every request flows through:
    1. decompose → 2. parallel investigate → 3. synthesize → 4. cache facts
    """

    role = AgentRole.RESEARCHER
    name = "researcher"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._system_prompt_text: Optional[str] = None
        self._knowledge_cache_path = Path(
            os.environ.get("KNOWLEDGE_CACHE_PATH", "/data/knowledge")
        )

        # Dual-model routing: thinking model for decompose/synthesize, instant for sub-agents
        self.thinking_model = kwargs.get("thinking_model") or os.getenv(
            "RESEARCHER_THINKING_MODEL", "kimi-k2.5-thinking"
        )
        self.instant_model = kwargs.get("instant_model") or os.getenv(
            "RESEARCHER_INSTANT_MODEL", "kimi-k2.5-instant"
        )

    # ─── BaseAgent interface ──────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        if self._system_prompt_text is None:
            self._system_prompt_text = self.build_system_prompt() or (
                "You are the Researcher agent. Investigate thoroughly, "
                "synthesize from multiple sources, and flag knowledge gaps. "
                "Respond with ONLY valid JSON."
            )
        return self._system_prompt_text

    def _supports_sub_agents(self) -> bool:
        """Researcher ALWAYS uses sub-agents."""
        return True

    @property
    def sub_agent_system_prompt(self) -> str:
        return (
            "You are a research sub-agent investigating one specific thread. "
            "Be thorough but focused. Distinguish facts from opinions. "
            "Rate source quality. Respond with ONLY valid JSON."
        )

    async def handle_task(self, msg: AgentMessage) -> Optional[dict]:
        """Route incoming research tasks."""
        action = msg.action
        payload = msg.payload
        context = msg.context

        query = payload.get("message", "")
        original_request = payload.get("original_request", query)

        if action in ("research", "execute", "investigate"):
            return await self._handle_research(query, original_request, context)
        elif action == "compare":
            return await self._handle_research(query, original_request, context)
        else:
            logger.warning(f"Researcher received unknown action: {action}")
            return await self._handle_research(query, original_request, context)

    async def on_startup(self):
        """Ensure knowledge cache directory exists."""
        self._knowledge_cache_path.mkdir(parents=True, exist_ok=True)
        logger.info("Researcher agent ready")

    # ─── Main Research Pipeline ───────────────────────────────────────

    async def _handle_research(
        self, query: str, original_request: str, context: dict
    ) -> dict:
        """
        Full research pipeline:
        1. Decompose into investigation threads
        2. Run threads in parallel via sub-agents
        3. Evaluate and score source quality
        4. Synthesize into research brief
        5. Cache high-confidence findings
        """
        # Step 1: Decompose
        threads = await self._decompose(query, context)

        if not threads:
            logger.warning("Decomposition produced no threads, using fallback")
            threads = self._fallback_threads(query)

        logger.info(f"Research decomposed into {len(threads)} threads")

        # Step 2: Parallel investigation
        thread_results = await self._investigate_parallel(
            query, threads
        )

        # Step 3: Score source quality across all results
        scored_results = self._score_sources(thread_results)

        # Step 4: Synthesize
        report = await self._synthesize(query, scored_results)

        # Step 5: Cache high-confidence findings
        facts_to_cache = report.get("facts_for_cache", [])
        cached_count = 0
        for fact_entry in facts_to_cache:
            if self._cache_fact(fact_entry):
                cached_count += 1

        if cached_count:
            logger.info(f"Cached {cached_count} new facts from research")

        # Add metadata
        report["research_metadata"] = {
            "threads_planned": len(threads),
            "threads_succeeded": sum(
                1 for r in thread_results if r.get("success", False)
            ),
            "facts_cached": cached_count,
            "sub_agent_metrics": (
                self.sub_pool.get_metrics() if self.sub_pool else None
            ),
        }

        return report

    # ─── Decomposition ────────────────────────────────────────────────

    async def _decompose(self, query: str, context: dict) -> list[dict]:
        """
        Break the research query into independent investigation threads.
        """
        knowledge_gaps = context.get("knowledge_gaps", [])
        preferred_sources = context.get("preferred_sources", [])

        # Decide thread count based on query complexity
        n = self._estimate_thread_count(query)

        prompt = DECOMPOSE_PROMPT.format(
            query=query,
            n=n,
            knowledge_gaps=(
                "\n".join(f"- {g}" for g in knowledge_gaps)
                if knowledge_gaps else "(none identified)"
            ),
            preferred_sources=(
                ", ".join(preferred_sources)
                if preferred_sources else "any authoritative source"
            ),
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=(
                    "You are a research planner. Decompose queries into "
                    "independent, parallel investigation threads. "
                    "Respond with ONLY JSON."
                ),
                temperature=0.4,
                model=self.thinking_model,
            )
            decomposition = result["content"]
            threads = decomposition.get("threads", [])

            # Validate: ensure at least MIN_THREADS and at most MAX_THREADS
            if len(threads) < MIN_THREADS:
                logger.warning(
                    f"Only {len(threads)} threads, padding to {MIN_THREADS}"
                )
                threads = self._pad_threads(query, threads)
            elif len(threads) > MAX_THREADS:
                threads = threads[:MAX_THREADS]

            # Ensure at least one risk thread exists
            has_risk = any(t.get("is_risk_thread", False) for t in threads)
            if not has_risk and threads:
                threads[-1]["is_risk_thread"] = True
                threads[-1]["focus"] = (
                    f"Risks, caveats, and counterarguments for: {query[:100]}"
                )

            return threads

        except Exception as e:
            logger.error(f"Decomposition failed: {e}")
            return []

    def _estimate_thread_count(self, query: str) -> int:
        """Heuristic: estimate how many threads this query needs."""
        words = len(query.split())

        # Comparison queries get more threads
        comparison_keywords = ["vs", "versus", "compare", "comparison", "difference", "better"]
        is_comparison = any(kw in query.lower() for kw in comparison_keywords)

        if is_comparison:
            return min(MAX_THREADS, DEFAULT_THREADS + 1)
        elif words > 50:
            return MAX_THREADS
        elif words > 20:
            return DEFAULT_THREADS
        else:
            return MIN_THREADS

    def _fallback_threads(self, query: str) -> list[dict]:
        """Generate basic threads when LLM decomposition fails."""
        return [
            {
                "id": "main",
                "focus": f"Core answer to: {query[:200]}",
                "search_queries": [query[:100]],
                "expected_source_types": ["official_docs", "peer_reviewed"],
                "is_risk_thread": False,
            },
            {
                "id": "context",
                "focus": f"Background context and related information for: {query[:100]}",
                "search_queries": [f"{query[:80]} overview"],
                "expected_source_types": ["official_blog", "news_reputable"],
                "is_risk_thread": False,
            },
            {
                "id": "risks",
                "focus": f"Risks, limitations, and counterarguments for: {query[:100]}",
                "search_queries": [f"{query[:80]} risks problems"],
                "expected_source_types": ["community_docs", "news_reputable"],
                "is_risk_thread": True,
            },
        ]

    def _pad_threads(self, query: str, threads: list[dict]) -> list[dict]:
        """Pad an undersized thread list to MIN_THREADS."""
        existing_ids = {t.get("id", "") for t in threads}
        padded = list(threads)

        fallbacks = self._fallback_threads(query)
        for fb in fallbacks:
            if len(padded) >= MIN_THREADS:
                break
            if fb["id"] not in existing_ids:
                padded.append(fb)

        return padded

    # ─── Parallel Investigation ───────────────────────────────────────

    async def _investigate_parallel(
        self, query: str, threads: list[dict]
    ) -> list[dict]:
        """
        Run all investigation threads in parallel via sub-agents.
        Returns a list of thread results (success or failure per thread).
        """
        subtasks = []
        for thread in threads:
            prompt = INVESTIGATE_PROMPT.format(
                original_query=query[:300],
                focus=thread.get("focus", ""),
                search_queries=json.dumps(thread.get("search_queries", [])),
                expected_source_types=json.dumps(
                    thread.get("expected_source_types", [])
                ),
                thread_id=thread.get("id", "unknown"),
            )

            subtasks.append(SubTask(
                id=thread.get("id", f"thread_{len(subtasks)}"),
                description=prompt,
                context={"thread": thread},
                constraints={"max_findings": 10},
            ))

        logger.info(f"Launching {len(subtasks)} research threads in parallel")
        sub_results = await self.sub_pool.execute_parallel(subtasks, model=self.instant_model)

        # Parse results
        thread_results = []
        for thread, result in zip(threads, sub_results):
            if result.success:
                output = result.output
                if isinstance(output, str):
                    try:
                        output = json.loads(output)
                    except json.JSONDecodeError:
                        output = {"findings": [], "error": "Invalid JSON from sub-agent"}

                thread_results.append({
                    "thread_id": thread.get("id"),
                    "focus": thread.get("focus"),
                    "is_risk_thread": thread.get("is_risk_thread", False),
                    "success": True,
                    "findings": output.get("findings", []),
                    "risks_found": output.get("risks_found", []),
                    "knowledge_gaps": output.get("knowledge_gaps", []),
                    "facts_worth_caching": output.get("facts_worth_caching", []),
                    "duration_ms": result.duration_ms,
                    "tokens_used": result.tokens_used,
                })
            else:
                logger.warning(
                    f"Thread '{thread.get('id')}' failed: {result.error}"
                )
                thread_results.append({
                    "thread_id": thread.get("id"),
                    "focus": thread.get("focus"),
                    "is_risk_thread": thread.get("is_risk_thread", False),
                    "success": False,
                    "findings": [],
                    "risks_found": [],
                    "knowledge_gaps": [f"Investigation failed: {result.error}"],
                    "facts_worth_caching": [],
                    "duration_ms": result.duration_ms,
                    "tokens_used": 0,
                })

        succeeded = sum(1 for r in thread_results if r["success"])
        logger.info(
            f"Research threads: {succeeded}/{len(thread_results)} succeeded"
        )

        return thread_results

    # ─── Source Quality Scoring ────────────────────────────────────────

    def _score_sources(self, thread_results: list[dict]) -> list[dict]:
        """
        Score each finding's source quality and add a quality_score field.
        Also deduplicates findings that appear across threads.
        """
        seen_findings = set()

        for thread in thread_results:
            scored_findings = []
            for finding in thread.get("findings", []):
                # Deduplicate by finding text (rough)
                finding_key = finding.get("finding", "")[:100].lower().strip()
                if finding_key in seen_findings:
                    continue
                seen_findings.add(finding_key)

                # Score source quality
                source_type = finding.get("source_type", "unknown")
                quality = SOURCE_QUALITY.get(source_type, 0.3)
                finding["source_quality"] = quality

                # Adjust confidence based on source quality
                raw_confidence = finding.get("confidence", 0.5)
                finding["adjusted_confidence"] = round(
                    raw_confidence * 0.6 + quality * 0.4, 3
                )

                scored_findings.append(finding)

            thread["findings"] = scored_findings

        return thread_results

    # ─── Synthesis ────────────────────────────────────────────────────

    async def _synthesize(
        self, query: str, thread_results: list[dict]
    ) -> dict:
        """
        Synthesize parallel thread results into one coherent research brief.
        """
        # Format thread results for the synthesis prompt
        formatted_threads = []
        for thread in thread_results:
            status = "✅" if thread["success"] else "❌"
            risk_tag = " [RISK THREAD]" if thread.get("is_risk_thread") else ""
            block = (
                f"--- {status} Thread: {thread['focus']}{risk_tag} ---\n"
                f"Findings: {json.dumps(thread.get('findings', []), indent=2, default=str)}\n"
                f"Risks: {json.dumps(thread.get('risks_found', []))}\n"
                f"Gaps: {json.dumps(thread.get('knowledge_gaps', []))}\n"
            )
            formatted_threads.append(block)

        thread_results_str = "\n\n".join(formatted_threads)

        # Truncate if too long for context window
        if len(thread_results_str) > 12000:
            thread_results_str = thread_results_str[:12000] + "\n... (truncated)"

        prompt = SYNTHESIZE_PROMPT.format(
            query=query,
            thread_results=thread_results_str,
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=self.system_prompt,
                temperature=0.5,
                model=self.thinking_model,
            )
            report = result["content"]

            # Merge in facts from threads that the synthesis might have missed
            all_thread_facts = []
            for thread in thread_results:
                all_thread_facts.extend(thread.get("facts_worth_caching", []))

            existing_facts = {
                f.get("fact", "")[:80] for f in report.get("facts_for_cache", [])
            }
            for fact in all_thread_facts:
                if fact.get("fact", "")[:80] not in existing_facts:
                    report.setdefault("facts_for_cache", []).append(fact)

            # Merge risks from all threads
            all_risks = []
            for thread in thread_results:
                all_risks.extend(thread.get("risks_found", []))
            existing_risks = set(report.get("risks_and_caveats", []))
            for risk in all_risks:
                if risk not in existing_risks:
                    report.setdefault("risks_and_caveats", []).append(risk)

            # Merge knowledge gaps
            all_gaps = []
            for thread in thread_results:
                all_gaps.extend(thread.get("knowledge_gaps", []))
            existing_gaps = set(report.get("knowledge_gaps", []))
            for gap in all_gaps:
                if gap not in existing_gaps:
                    report.setdefault("knowledge_gaps", []).append(gap)

            return report

        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return self._fallback_synthesis(query, thread_results)

    def _fallback_synthesis(
        self, query: str, thread_results: list[dict]
    ) -> dict:
        """
        Direct synthesis without LLM — used when the synthesis call fails.
        Merges thread results mechanically.
        """
        all_findings = []
        all_risks = []
        all_gaps = []
        all_facts = []

        for thread in thread_results:
            for finding in thread.get("findings", []):
                all_findings.append({
                    "finding": finding.get("finding", ""),
                    "confidence": finding.get("adjusted_confidence", finding.get("confidence", 0.5)),
                    "sources": [finding.get("source", "unknown")],
                    "relevance": finding.get("relevance", "medium"),
                })
            all_risks.extend(thread.get("risks_found", []))
            all_gaps.extend(thread.get("knowledge_gaps", []))
            all_facts.extend(thread.get("facts_worth_caching", []))

        # Sort findings by confidence
        all_findings.sort(key=lambda f: f["confidence"], reverse=True)

        # Build a mechanical summary
        top_findings = all_findings[:5]
        summary_parts = [f.get("finding", "") for f in top_findings if f.get("finding")]
        summary = " ".join(summary_parts) if summary_parts else (
            f"Research on '{query[:100]}' completed with mixed results."
        )

        confidences = [f["confidence"] for f in all_findings] if all_findings else [0.0]
        overall = sum(confidences) / len(confidences)

        return {
            "summary": summary,
            "key_findings": all_findings[:10],
            "comparisons": [],
            "risks_and_caveats": list(set(all_risks)),
            "knowledge_gaps": list(set(all_gaps)),
            "contradictions": [],
            "recommended_next_steps": [],
            "facts_for_cache": all_facts,
            "overall_confidence": round(overall, 3),
            "source_quality_summary": "Fallback synthesis — source quality not evaluated",
        }

    # ─── Knowledge Cache ──────────────────────────────────────────────

    def _cache_fact(self, fact_entry: dict) -> bool:
        """Cache a high-confidence fact. Returns True if cached."""
        if not self.memory:
            return False

        fact_text = fact_entry.get("fact", "")
        confidence = fact_entry.get("confidence", 0.0)

        if not fact_text or confidence < 0.75:
            return False

        try:
            self.memory.store_fact(
                fact=fact_text,
                category=fact_entry.get("category", "general"),
                source=fact_entry.get("source"),
                confidence=confidence,
                verified_by="researcher",
                tags=fact_entry.get("tags", []),
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to cache fact: {e}")
            return False
