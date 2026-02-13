"""
OpenClaw Distro — Guardian Agent (Quality + Security Gatekeeper)

The Guardian is fundamentally different from other agents:
- It is NOT delegated to by the Brain
- It is a middleware INTERCEPTOR that monitors ALL messages on the bus
- It can PASS, FLAG, or BLOCK any message/output
- It NEVER fragments into sub-agents (must see full picture)
- It tracks costs across all agents

Capabilities (Free Tier):
1. Credential scanning — regex + LLM review for secrets, API keys, tokens
2. Breaking change detection — analyze diffs for changed signatures/interfaces,
   verify callers are updated
3. Code convention enforcement — check against user-defined project rules
   (loaded from config); skips gracefully if none defined
4. Rollback decision logic — after repeated verification failures, decide:
   rollback, escalate to Cortex, or flag for human review

The Guardian overrides the standard run() loop to use listen_intercept(),
which subscribes to the "guardian:intercept" channel where ALL messages
are mirrored. It also listens on "agent:guardian" for direct queries
(e.g. cost report requests).

Verdicts:
- PASS: No issues found, message flows normally (default)
- FLAG: Issues found but non-critical, message flows with warnings attached
- BLOCK: Critical issue, message is stopped (secret leak, budget exceeded, etc.)
"""

import asyncio
import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from agents.common.base_agent import BaseAgent
from agents.common.protocol import AgentRole, AgentMessage, TaskStatus
from agents.common.usage_tracker import UsageTracker
from agents.common.secret_scanner import SECRET_PATTERNS as CENTRAL_SECRET_PATTERNS, scan_for_secrets

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

# Budget thresholds (percentage of daily token budget)
WARN_THRESHOLD_PCT = 50
ALERT_THRESHOLD_PCT = 80
BLOCK_THRESHOLD_PCT = 100

# Secret patterns (compiled once at import)
SECRET_PATTERNS = [
    # API keys
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), "API key (sk-...)"),
    (re.compile(r'sk-or-[a-zA-Z0-9]{20,}'), "OpenRouter API key"),
    (re.compile(r'sk-ant-[a-zA-Z0-9]{20,}'), "Anthropic API key"),
    (re.compile(r'ghp_[a-zA-Z0-9]{36}'), "GitHub personal access token"),
    (re.compile(r'gho_[a-zA-Z0-9]{36}'), "GitHub OAuth token"),
    (re.compile(r'github_pat_[a-zA-Z0-9_]{80,}'), "GitHub fine-grained token"),
    (re.compile(r'glpat-[a-zA-Z0-9\-]{20,}'), "GitLab personal access token"),
    (re.compile(r'xox[boaprs]-[a-zA-Z0-9\-]{10,}'), "Slack token"),
    (re.compile(r'AKIA[0-9A-Z]{16}'), "AWS access key"),
    (re.compile(r'[a-zA-Z0-9+/]{40}', re.ASCII), "Potential AWS secret key"),

    # Private keys
    (re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'), "Private key"),
    (re.compile(r'-----BEGIN PGP PRIVATE KEY BLOCK-----'), "PGP private key"),

    # Connection strings
    (re.compile(r'(?:postgres|mysql|mongodb)://\w+:[^@\s]+@'), "Database connection string with credentials"),

    # Generic patterns
    (re.compile(r'(?:password|passwd|pwd)\s*[=:]\s*["\'][^"\']{8,}["\']', re.IGNORECASE), "Hardcoded password"),
    (re.compile(r'(?:secret|token|key)\s*[=:]\s*["\'][a-zA-Z0-9+/=]{16,}["\']', re.IGNORECASE), "Hardcoded secret"),
]

# Prompt injection indicators
INJECTION_PATTERNS = [
    re.compile(r'ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions', re.IGNORECASE),
    re.compile(r'you\s+are\s+now\s+(?:a|an)\s+', re.IGNORECASE),
    re.compile(r'new\s+system\s+prompt', re.IGNORECASE),
    re.compile(r'override\s+(?:your|the)\s+(?:system|instructions)', re.IGNORECASE),
    re.compile(r'forget\s+(?:all|everything|your)\s+(?:previous|prior)', re.IGNORECASE),
    re.compile(r'disregard\s+(?:all|your|the)\s+(?:rules|instructions|guidelines)', re.IGNORECASE),
    re.compile(r'SYSTEM:\s*', re.IGNORECASE),  # Injected system message
    re.compile(r'\[INST\]|\[/INST\]|<\|im_start\|>|<\|im_end\|>'),  # Raw prompt tokens
]

# SQL injection patterns in code artifacts
SQL_INJECTION_PATTERNS = [
    re.compile(r'f["\'].*(?:SELECT|INSERT|UPDATE|DELETE|DROP).*\{', re.IGNORECASE),
    re.compile(r'["\'].*(?:SELECT|INSERT|UPDATE|DELETE|DROP).*["\']\s*%\s*\(', re.IGNORECASE),
    re.compile(r'\.format\(.*(?:SELECT|INSERT|UPDATE|DELETE|DROP)', re.IGNORECASE),
    re.compile(r'execute\s*\(\s*f["\']', re.IGNORECASE),
]

# ─── Review Prompt ────────────────────────────────────────────────────────────

BREAKING_CHANGE_PROMPT = """\
Analyze this diff for breaking changes. Look for:
1. Changed function signatures (added/removed/reordered parameters)
2. Changed class interfaces (renamed methods, changed inheritance)
3. Changed API contracts (endpoints, request/response shapes)
4. Changed return types or error behavior

Diff:
{diff}

Affected files and their callers:
{caller_context}

Respond with ONLY a JSON object:
{{
  "breaking_changes": [
    {{
      "type": "signature_change|interface_change|api_change|behavior_change",
      "location": "<file:line or function name>",
      "description": "<what changed>",
      "callers_updated": <true|false|null>,
      "affected_callers": ["<list of files/functions that call this>"],
      "severity": "critical|high|medium|low"
    }}
  ],
  "summary": "<brief summary or 'No breaking changes detected'>"
}}
"""

CODE_CONVENTION_PROMPT = """\
Check this diff against the following project code conventions/rules.
Only flag clear violations — do not be overly pedantic.

Project rules:
{rules}

Diff:
{diff}

Respond with ONLY a JSON object:
{{
  "violations": [
    {{
      "rule": "<which rule was violated>",
      "location": "<file:line>",
      "description": "<what violates the rule>",
      "severity": "high|medium|low"
    }}
  ],
  "summary": "<brief summary or 'No violations found'>"
}}
"""

ROLLBACK_DECISION_PROMPT = """\
Verification has failed {failure_count} time(s) for this task. Analyze the situation and decide the next action.

Task context:
{task_context}

Failure history:
{failure_history}

Choose ONE action:
- "rollback" — if the changes are clearly broken and should be reverted
- "escalate" — if the issue is ambiguous and Cortex (orchestrator) should decide
- "flag_human" — if the issue requires human judgment (e.g., intentional breaking change, policy decision)

Respond with ONLY a JSON object:
{{
  "decision": "rollback|escalate|flag_human",
  "reasoning": "<why this decision>",
  "confidence": <0.0-1.0>,
  "details": "<additional context for whoever handles this>"
}}
"""

SECURITY_REVIEW_PROMPT = """\
Review this agent output for security issues. Be thorough but practical.

Agent: {from_agent}
Action: {action}
Output:
{output_text}

Check for:
1. Hardcoded secrets, API keys, tokens, passwords
2. SQL injection vulnerabilities (string formatting in queries)
3. Shell injection (unsanitized input in commands)
4. Path traversal (../ in file paths)
5. Excessive permissions or privilege escalation
6. Missing input validation
7. Unsafe dependencies or imports
8. Data exposure risks

For financial/trading code, also check:
9. Slippage protection on transactions
10. Rate limiting on API calls
11. Input bounds validation on amounts

Respond with ONLY a JSON object:
{{
  "verdict": "pass|flag|block",
  "issues": [
    {{
      "severity": "critical|high|medium|low|info",
      "category": "secret_leak|injection|permissions|vulnerability|best_practice",
      "description": "<what the issue is>",
      "location": "<where in the output>",
      "recommendation": "<how to fix>"
    }}
  ],
  "blocked_reason": "<if verdict is block, explain why. null otherwise>"
}}

Blocking policy:
- BLOCK only for: active secret exposure, code causing data loss, critical vulns with immediate exploit
- FLAG for: best practice violations, missing validation, suboptimal patterns
- PASS if no issues found
"""


# ─── Guardian Agent ───────────────────────────────────────────────────────────

class GuardianAgent(BaseAgent):
    """
    The Guardian — security interceptor and cost tracker.

    Unlike other agents, the Guardian:
    - Polls the SQLite message bus for all completed messages
    - Also handles direct queries (cost reports, audit)
    - Never uses sub-agents
    - Can BLOCK messages from reaching their destination
    """

    role = AgentRole.GUARDIAN
    name = "guardian"
    model = "qwen-plus"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._system_prompt_text: Optional[str] = None
        self._usage_tracker = UsageTracker()

        # Cost tracking
        self._daily_token_budget = int(
            os.environ.get("COST_BUDGET_DAILY_TOKENS", "1000000")
        )
        self._token_counts: dict[str, int] = defaultdict(int)  # agent -> tokens today
        self._hourly_counts: dict[str, int] = defaultdict(int)  # agent -> tokens this hour
        self._cost_reset_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._hour_reset: int = datetime.now(timezone.utc).hour

        # Security event log (in-memory ring buffer)
        self._security_log: list[dict] = []
        self._max_log_entries = 1000

        # Stats
        self._messages_scanned = 0
        self._issues_found = 0
        self._blocks_issued = 0

    # ─── BaseAgent interface ──────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        if self._system_prompt_text is None:
            self._system_prompt_text = self.build_system_prompt() or (
                "You are the Guardian agent. Review outputs for security "
                "issues. You can PASS, FLAG, or BLOCK. Be thorough."
            )
        return self._system_prompt_text

    def _supports_sub_agents(self) -> bool:
        """Guardian NEVER uses sub-agents."""
        return False

    async def run(self):
        """
        Override the standard run loop.

        The Guardian runs TWO tasks concurrently:
        1. Intercept polling — polls SQLite bus for completed messages to review
        2. Direct polling — receives queries like cost reports, audit requests
        3. Cost reset — periodic counter resets
        """
        await self.on_startup()

        try:
            await asyncio.gather(
                self._run_intercept_loop(),
                self._run_direct_loop(),
                self._run_cost_reset_loop(),
            )
        except asyncio.CancelledError:
            logger.info("Guardian shutting down")
        finally:
            await self.on_shutdown()

    async def _run_intercept_loop(self):
        """Poll SQLite bus for all completed messages to review."""
        logger.info("Guardian intercept loop started — polling all traffic")
        self._last_scanned_id = 0
        while True:
            try:
                rows = self.bus._db.execute(
                    "SELECT * FROM message_queue WHERE id > ? AND from_agent != 'guardian' "
                    "ORDER BY id ASC LIMIT 20",
                    (self._last_scanned_id,),
                ).fetchall()
                for row in rows:
                    self._last_scanned_id = row["id"]
                    msg = self.bus.get_task(row["task_id"])
                    if msg:
                        await self._handle_intercept(msg)
            except Exception as e:
                logger.warning(f"Intercept poll error: {e}")
            await asyncio.sleep(1.0)

    async def _run_direct_loop(self):
        """Poll for direct queries addressed to the Guardian."""
        logger.info("Guardian direct query loop started")
        while True:
            try:
                messages = self.bus.receive(AgentRole.GUARDIAN, limit=5)
                for msg in messages:
                    result = await self.handle_task(msg)
                    if result:
                        self.bus.update_status(
                            msg.task_id, TaskStatus.COMPLETED, result=result
                        )
            except Exception as e:
                logger.warning(f"Direct poll error: {e}")
            await asyncio.sleep(1.0)

    async def _run_cost_reset_loop(self):
        """Periodically reset hourly counters and check daily rollover."""
        while True:
            await asyncio.sleep(60)  # Check every minute
            now = datetime.now(timezone.utc)

            # Hourly reset
            if now.hour != self._hour_reset:
                self._hourly_counts.clear()
                self._hour_reset = now.hour

            # Daily reset
            today = now.strftime("%Y-%m-%d")
            if today != self._cost_reset_date:
                logger.info(
                    f"Daily cost reset. Yesterday's total: "
                    f"{sum(self._token_counts.values())} tokens"
                )
                self._token_counts.clear()
                self._cost_reset_date = today

    async def handle_task(self, msg: AgentMessage) -> Optional[dict]:
        """Handle direct queries to the Guardian (cost reports, audit, etc.)."""
        action = msg.action

        if action == "cost_report":
            return self._generate_cost_report()
        elif action == "audit":
            return self._generate_audit_report(
                msg.payload.get("task_id"),
                msg.payload.get("last_n", 50),
            )
        elif action == "security_scan":
            # Manual scan request
            return await self._deep_scan(msg.payload)
        else:
            return self._generate_cost_report()

    # ─── Intercept Handler ────────────────────────────────────────────

    async def _handle_intercept(self, msg: AgentMessage):
        """
        Called for EVERY message on the bus. This is the core security loop.

        For most messages: quick regex scan (fast, no LLM call).
        For Builder outputs with artifacts: full LLM security review.
        """
        self._messages_scanned += 1
        self._rotate_cost_counters()

        # Track token usage from message metadata
        self._track_tokens(msg)

        # Skip scanning our own messages to avoid infinite loops
        from_val = msg.from_agent.value if isinstance(msg.from_agent, AgentRole) else msg.from_agent
        if from_val == AgentRole.GUARDIAN.value:
            return

        # Skip pending/in-progress messages (scan results, not requests)
        if msg.status in (TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value):
            return

        # Determine scan depth based on message content
        has_artifacts = bool(
            msg.result and msg.result.get("artifacts")
        )
        has_code = bool(
            msg.result and (
                msg.result.get("code_output")
                or msg.result.get("artifacts")
            )
        )
        from_builder = from_val == AgentRole.BUILDER.value

        # Phase 1: Fast regex scan (always)
        regex_issues = self._fast_scan(msg)

        # Phase 2: Cost budget check (always)
        cost_issues = self._check_budget()

        # Phase 3: Prompt injection check (always on payloads)
        injection_issues = self._check_injection(msg)

        # Combine fast-scan issues
        all_issues = regex_issues + cost_issues + injection_issues

        # Phase 4: Deep LLM scan (only for Builder outputs with code/artifacts)
        if from_builder and has_code:
            try:
                llm_issues = await self._llm_security_review(msg)
                all_issues.extend(llm_issues)
            except Exception as e:
                logger.warning(f"LLM security review failed: {e}")

        # Determine verdict
        verdict = self._determine_verdict(all_issues)

        if all_issues:
            self._issues_found += len(all_issues)
            self._log_security_event(msg, verdict, all_issues)

        if verdict == "block":
            self._blocks_issued += 1
            logger.warning(
                f"BLOCKED message from {msg.from_agent} "
                f"[task:{msg.task_id[:8]}]: "
                f"{all_issues[0]['description']}"
            )
            # Block the message by publishing a block status
            block_reason = "; ".join(
                i["description"] for i in all_issues
                if i["severity"] == "critical"
            )
            msg.block(block_reason or "Security review failed")
            self.bus.update_status(msg.task_id, TaskStatus.BLOCKED, error=msg.error)

        elif verdict == "flag":
            logger.info(
                f"FLAGGED message from {msg.from_agent} "
                f"[task:{msg.task_id[:8]}]: "
                f"{len(all_issues)} issue(s)"
            )
            # Attach warnings to the message metadata
            msg.metadata["guardian_flags"] = all_issues

    # ─── Fast Regex Scanning ──────────────────────────────────────────

    def _fast_scan(self, msg: AgentMessage) -> list[dict]:
        """
        Fast regex-based scan of message content.
        Checks for secrets, obvious vulnerabilities in all text fields.
        """
        issues = []

        # Collect all text to scan
        texts_to_scan = self._extract_scannable_text(msg)

        for text, location in texts_to_scan:
            # Secret detection
            for pattern, description in SECRET_PATTERNS:
                matches = pattern.findall(text)
                if matches:
                    # Filter out false positives (short matches, common strings)
                    real_matches = [
                        m for m in matches
                        if len(m) > 10 and m not in ("true", "false", "null")
                    ]
                    if real_matches:
                        issues.append({
                            "severity": "critical",
                            "category": "secret_leak",
                            "description": f"Possible {description} detected",
                            "location": location,
                            "recommendation": "Use environment variables instead of hardcoding secrets",
                        })

            # SQL injection in code
            for pattern in SQL_INJECTION_PATTERNS:
                if pattern.search(text):
                    issues.append({
                        "severity": "high",
                        "category": "injection",
                        "description": "Possible SQL injection: string formatting in SQL query",
                        "location": location,
                        "recommendation": "Use parameterized queries instead of string formatting",
                    })

            # Path traversal
            if "../" in text and ("open(" in text or "Path(" in text or "read" in text):
                issues.append({
                    "severity": "high",
                    "category": "vulnerability",
                    "description": "Possible path traversal vulnerability",
                    "location": location,
                    "recommendation": "Resolve paths and validate they stay within allowed directories",
                })

        return issues

    def _extract_scannable_text(self, msg: AgentMessage) -> list[tuple[str, str]]:
        """Extract all text content from a message for scanning."""
        texts = []

        # Scan payload
        payload_str = json.dumps(msg.payload, default=str)
        texts.append((payload_str, "payload"))

        # Scan context
        context_str = json.dumps(msg.context, default=str)
        texts.append((context_str, "context"))

        # Scan result (most important — this is the output)
        if msg.result:
            result_str = json.dumps(msg.result, default=str)
            texts.append((result_str, "result"))

            # Scan individual artifacts more carefully
            for i, artifact in enumerate(msg.result.get("artifacts", [])):
                content = artifact.get("content", "")
                if content:
                    texts.append((content, f"artifact[{i}]:{artifact.get('path', '?')}"))

            # Scan code output
            stdout = msg.result.get("code_output", {})
            if isinstance(stdout, dict):
                if stdout.get("stdout"):
                    texts.append((stdout["stdout"], "stdout"))
                if stdout.get("stderr"):
                    texts.append((stdout["stderr"], "stderr"))

        return texts

    # ─── Prompt Injection Detection ───────────────────────────────────

    def _check_injection(self, msg: AgentMessage) -> list[dict]:
        """Check for prompt injection attempts in message payloads."""
        issues = []

        # Scan payload and context for injection patterns
        scan_texts = [
            (json.dumps(msg.payload, default=str), "payload"),
            (json.dumps(msg.context, default=str), "context"),
        ]

        for text, location in scan_texts:
            for pattern in INJECTION_PATTERNS:
                if pattern.search(text):
                    issues.append({
                        "severity": "high",
                        "category": "injection",
                        "description": f"Prompt injection pattern detected in {location}",
                        "location": location,
                        "recommendation": "Sanitize user input before passing to agents",
                    })
                    break  # One injection finding per text block is enough

        return issues

    # ─── Cost Budget Checks ───────────────────────────────────────────

    def _check_budget(self) -> list[dict]:
        """Check current token usage against budget thresholds."""
        issues = []
        total_today = sum(self._token_counts.values())
        pct = (total_today / self._daily_token_budget * 100) if self._daily_token_budget else 0

        if pct >= BLOCK_THRESHOLD_PCT:
            issues.append({
                "severity": "critical",
                "category": "cost",
                "description": (
                    f"Daily token budget EXCEEDED: {total_today:,} / "
                    f"{self._daily_token_budget:,} ({pct:.1f}%)"
                ),
                "location": "cost_tracker",
                "recommendation": "Wait until daily reset or increase budget",
            })
        elif pct >= ALERT_THRESHOLD_PCT:
            issues.append({
                "severity": "high",
                "category": "cost",
                "description": (
                    f"Approaching daily budget: {total_today:,} / "
                    f"{self._daily_token_budget:,} ({pct:.1f}%)"
                ),
                "location": "cost_tracker",
                "recommendation": "Reduce usage or increase budget",
            })
        elif pct >= WARN_THRESHOLD_PCT:
            issues.append({
                "severity": "medium",
                "category": "cost",
                "description": (
                    f"Budget at {pct:.1f}%: {total_today:,} / "
                    f"{self._daily_token_budget:,} tokens"
                ),
                "location": "cost_tracker",
                "recommendation": "Monitor usage",
            })

        return issues

    def _track_tokens(self, msg: AgentMessage):
        """Extract and track token usage from a message."""
        usage = msg.metadata.get("usage", {})
        tokens = usage.get("total_tokens", 0)

        if tokens > 0:
            agent = msg.from_agent.value if isinstance(msg.from_agent, AgentRole) else msg.from_agent
            self._token_counts[agent] += tokens
            self._hourly_counts[agent] += tokens

    def _rotate_cost_counters(self):
        """Check if we need to reset counters (called on each intercept)."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        if today != self._cost_reset_date:
            self._token_counts.clear()
            self._cost_reset_date = today

        if now.hour != self._hour_reset:
            self._hourly_counts.clear()
            self._hour_reset = now.hour

    # ─── LLM Security Review ─────────────────────────────────────────

    async def _llm_security_review(self, msg: AgentMessage) -> list[dict]:
        """
        Deep security review using the LLM for Builder outputs.
        Only called for messages with code artifacts.
        """
        # Format the output for review
        output_text = json.dumps(msg.result, indent=2, default=str)

        # Truncate if too long
        if len(output_text) > 8000:
            output_text = output_text[:8000] + "\n... (truncated)"

        prompt = SECURITY_REVIEW_PROMPT.format(
            from_agent=msg.from_agent,
            action=msg.action,
            output_text=output_text,
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system=self.system_prompt,
                temperature=0.1,  # Low temp for precise security analysis
            )
            review = result["content"]
            return review.get("issues", [])

        except Exception as e:
            logger.warning(f"LLM security review failed: {e}")
            return []

    # ─── Deep Scan (manual request) ───────────────────────────────────

    async def _deep_scan(self, payload: dict) -> dict:
        """
        Full security scan requested directly (not via intercept).
        Used for manual security audits of configs, code, etc.
        """
        content = payload.get("content", "")
        content_type = payload.get("type", "code")

        # Run all scan types
        # Create a fake message for the scanning functions
        fake_msg = AgentMessage(
            from_agent=AgentRole.GUARDIAN,
            to_agent=AgentRole.GUARDIAN,
            action="scan",
            result={"artifacts": [{"content": content, "path": "manual_scan"}]},
        )

        regex_issues = self._fast_scan(fake_msg)
        injection_issues = self._check_injection(fake_msg)

        # LLM review
        llm_issues = []
        try:
            review_prompt = SECURITY_REVIEW_PROMPT.format(
                from_agent="manual",
                action="security_scan",
                output_text=content[:8000],
            )
            result = await self.llm.generate_json(
                prompt=review_prompt,
                system=self.system_prompt,
                temperature=0.1,
            )
            llm_issues = result["content"].get("issues", [])
        except Exception as e:
            logger.warning(f"Deep scan LLM review failed: {e}")

        all_issues = regex_issues + injection_issues + llm_issues
        verdict = self._determine_verdict(all_issues)

        return {
            "verdict": verdict,
            "issues": all_issues,
            "cost_report": self._build_cost_report(),
            "blocked_reason": (
                "; ".join(i["description"] for i in all_issues if i["severity"] == "critical")
                if verdict == "block" else None
            ),
        }

    # ─── Breaking Change Detection ───────────────────────────────────

    async def detect_breaking_changes(self, diff: str, caller_context: str = "") -> list[dict]:
        """
        Analyze a diff for breaking changes: changed function signatures,
        class interfaces, or API contracts. Checks if callers are updated.

        Args:
            diff: The git diff or code diff to analyze.
            caller_context: Content of files that call the changed code.

        Returns:
            List of issue dicts for any breaking changes found.
        """
        if not diff or not diff.strip():
            return []

        prompt = BREAKING_CHANGE_PROMPT.format(
            diff=diff[:6000],
            caller_context=caller_context[:4000] if caller_context else "(caller context not available)",
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system="You are a code review expert. Detect breaking changes precisely. Respond with ONLY JSON.",
                temperature=0.1,
            )
            breaking_changes = result["content"].get("breaking_changes", [])

            issues = []
            for bc in breaking_changes:
                if bc.get("callers_updated") is False:
                    severity = bc.get("severity", "high")
                else:
                    severity = "medium" if bc.get("callers_updated") is None else "low"

                issues.append({
                    "severity": severity,
                    "category": "breaking_change",
                    "description": f"Breaking change ({bc.get('type', 'unknown')}): {bc.get('description', '')}",
                    "location": bc.get("location", "unknown"),
                    "recommendation": f"Update callers: {', '.join(bc.get('affected_callers', [])[:5])}",
                })
            return issues

        except Exception as e:
            logger.warning(f"Breaking change detection failed: {e}")
            return []

    # ─── Code Convention Enforcement ──────────────────────────────────

    def _load_convention_rules(self) -> Optional[str]:
        """
        Load user-defined code convention rules from config.
        Looks for rules in (in order):
        1. GUARDIAN_CONVENTION_RULES env var (inline rules)
        2. configs/user/conventions.yaml or .convention-rules
        3. .guardian-rules in project root

        Returns None if no rules are defined (skip gracefully).
        """
        # 1. Environment variable
        env_rules = os.environ.get("GUARDIAN_CONVENTION_RULES")
        if env_rules and env_rules.strip():
            return env_rules.strip()

        # 2. Config files
        rule_paths = [
            Path("configs/user/conventions.yaml"),
            Path(".convention-rules"),
            Path(".guardian-rules"),
        ]
        for rule_path in rule_paths:
            try:
                if rule_path.exists():
                    content = rule_path.read_text().strip()
                    if content:
                        logger.info(f"Loaded convention rules from {rule_path}")
                        return content
            except Exception as e:
                logger.debug(f"Could not read {rule_path}: {e}")

        return None

    async def enforce_code_conventions(self, diff: str) -> list[dict]:
        """
        Check a diff against user-defined project code conventions.
        Skips gracefully if no rules are defined.

        Args:
            diff: The git diff to check.

        Returns:
            List of issue dicts for convention violations.
        """
        rules = self._load_convention_rules()
        if not rules:
            logger.debug("No convention rules defined — skipping convention enforcement")
            return []

        if not diff or not diff.strip():
            return []

        prompt = CODE_CONVENTION_PROMPT.format(
            rules=rules[:3000],
            diff=diff[:6000],
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system="You are a code style reviewer. Check against the given rules. Respond with ONLY JSON.",
                temperature=0.1,
            )
            violations = result["content"].get("violations", [])

            issues = []
            for v in violations:
                issues.append({
                    "severity": v.get("severity", "low"),
                    "category": "convention_violation",
                    "description": f"Convention violation ({v.get('rule', 'unknown')}): {v.get('description', '')}",
                    "location": v.get("location", "unknown"),
                    "recommendation": f"Follow project rule: {v.get('rule', '')}",
                })
            return issues

        except Exception as e:
            logger.warning(f"Convention enforcement failed: {e}")
            return []

    # ─── Rollback Decision Logic ──────────────────────────────────────

    async def make_rollback_decision(
        self,
        task_context: str,
        failure_count: int = 2,
        failure_history: str = "",
    ) -> dict:
        """
        When verification has failed repeatedly, decide the next action:
        - rollback: revert the changes
        - escalate: pass to Cortex for orchestrator-level decision
        - flag_human: require human review

        Args:
            task_context: Description of the task and what was attempted.
            failure_count: Number of verification failures (typically ≥2).
            failure_history: Description of what failed and why.

        Returns:
            Structured decision dict with decision, reasoning, confidence, details.
        """
        prompt = ROLLBACK_DECISION_PROMPT.format(
            failure_count=failure_count,
            task_context=task_context[:3000],
            failure_history=failure_history[:3000] if failure_history else "(no detailed history available)",
        )

        try:
            result = await self.llm.generate_json(
                prompt=prompt,
                system="You are a release gatekeeper. Make conservative decisions. Respond with ONLY JSON.",
                temperature=0.2,
            )
            decision = result["content"]

            # Validate and normalize
            valid_decisions = ("rollback", "escalate", "flag_human")
            if decision.get("decision") not in valid_decisions:
                decision["decision"] = "escalate"  # safe default
                decision["reasoning"] = (decision.get("reasoning", "") +
                    " (decision normalized to 'escalate' due to unrecognized value)")

            return {
                "decision": decision.get("decision", "escalate"),
                "reasoning": decision.get("reasoning", ""),
                "confidence": min(max(decision.get("confidence", 0.5), 0.0), 1.0),
                "details": decision.get("details", ""),
                "failure_count": failure_count,
            }

        except Exception as e:
            logger.warning(f"Rollback decision failed: {e}")
            # Conservative fallback: escalate to Cortex
            return {
                "decision": "escalate",
                "reasoning": f"Rollback decision LLM call failed ({e}); escalating as safety measure.",
                "confidence": 0.3,
                "details": "Automatic escalation due to decision engine failure.",
                "failure_count": failure_count,
            }

    # ─── Aggregated Review (called from intercept or direct) ──────────

    async def review(
        self,
        msg: AgentMessage,
        diff: str = "",
        caller_context: str = "",
        verification_failure_count: int = 0,
        task_context: str = "",
        failure_history: str = "",
    ) -> dict:
        """
        Full quality + security review aggregating all Guardian capabilities.

        Runs:
        1. Credential scanning (fast regex)
        2. Prompt injection check
        3. Cost budget check
        4. LLM security review (for Builder code output)
        5. Breaking change detection (if diff provided)
        6. Code convention enforcement (if diff provided and rules exist)
        7. Rollback decision (if verification has failed ≥2 times)

        Returns aggregated result with verdict, issues, and optional rollback decision.
        """
        all_issues = []

        # 1. Fast regex credential scan
        all_issues.extend(self._fast_scan(msg))

        # 2. Prompt injection check
        all_issues.extend(self._check_injection(msg))

        # 3. Cost budget check
        all_issues.extend(self._check_budget())

        # 4. LLM security review for code artifacts
        from_val = msg.from_agent.value if isinstance(msg.from_agent, AgentRole) else msg.from_agent
        has_code = bool(msg.result and (msg.result.get("code_output") or msg.result.get("artifacts")))
        if from_val == AgentRole.BUILDER.value and has_code:
            try:
                llm_issues = await self._llm_security_review(msg)
                all_issues.extend(llm_issues)
            except Exception as e:
                logger.warning(f"LLM security review failed in review(): {e}")

        # 5. Breaking change detection
        if diff:
            bc_issues = await self.detect_breaking_changes(diff, caller_context)
            all_issues.extend(bc_issues)

        # 6. Code convention enforcement
        if diff:
            conv_issues = await self.enforce_code_conventions(diff)
            all_issues.extend(conv_issues)

        # 7. Rollback decision logic
        rollback_decision = None
        if verification_failure_count >= 2:
            rollback_decision = await self.make_rollback_decision(
                task_context=task_context,
                failure_count=verification_failure_count,
                failure_history=failure_history,
            )

        verdict = self._determine_verdict(all_issues)

        return {
            "verdict": verdict,
            "issues": all_issues,
            "issue_count": len(all_issues),
            "rollback_decision": rollback_decision,
            "cost_report": self._build_cost_report(),
            "blocked_reason": (
                "; ".join(i["description"] for i in all_issues if i["severity"] == "critical")
                if verdict == "block" else None
            ),
        }

    # ─── Verdict Logic ────────────────────────────────────────────────

    def _determine_verdict(self, issues: list[dict]) -> str:
        """
        Determine the overall verdict based on issues found.
        
        BLOCK only for critical issues:
        - Active secret/credential exposure
        - Code causing data loss
        - Critical vulns with immediate exploit
        - Budget hard-limit exceeded
        """
        if not issues:
            return "pass"

        severities = {i.get("severity", "info") for i in issues}

        if "critical" in severities:
            return "block"
        elif "high" in severities:
            return "flag"
        elif "medium" in severities:
            return "flag"
        else:
            return "pass"

    # ─── Reporting ────────────────────────────────────────────────────

    def _generate_cost_report(self) -> dict:
        """Generate a cost tracking report using persistent UsageTracker."""
        return {
            "verdict": "pass",
            "issues": [],
            "cost_report": self._build_cost_report(),
            "persistent_report": self._usage_tracker.get_cost_report(),
            "blocked_reason": None,
        }

    def _build_cost_report(self) -> dict:
        """Build the cost report dict."""
        total_today = sum(self._token_counts.values())
        total_hour = sum(self._hourly_counts.values())
        budget_remaining = max(0, self._daily_token_budget - total_today)
        pct_remaining = (
            (budget_remaining / self._daily_token_budget * 100)
            if self._daily_token_budget else 0
        )

        return {
            "tokens_this_hour": total_hour,
            "tokens_today": total_today,
            "daily_budget": self._daily_token_budget,
            "budget_remaining_pct": round(pct_remaining, 1),
            "per_agent_today": dict(self._token_counts),
            "per_agent_this_hour": dict(self._hourly_counts),
            "stats": {
                "messages_scanned": self._messages_scanned,
                "issues_found": self._issues_found,
                "blocks_issued": self._blocks_issued,
            },
        }

    def _generate_audit_report(
        self, task_id: Optional[str] = None, last_n: int = 50
    ) -> dict:
        """Generate an audit report of recent security events."""
        events = self._security_log[-last_n:]

        if task_id:
            events = [e for e in events if e.get("task_id", "").startswith(task_id)]

        return {
            "verdict": "pass",
            "issues": [],
            "audit_log": events,
            "stats": {
                "messages_scanned": self._messages_scanned,
                "issues_found": self._issues_found,
                "blocks_issued": self._blocks_issued,
                "log_entries": len(self._security_log),
            },
            "cost_report": self._build_cost_report(),
            "blocked_reason": None,
        }

    # ─── Security Event Log ───────────────────────────────────────────

    def _log_security_event(
        self, msg: AgentMessage, verdict: str, issues: list[dict]
    ):
        """Record a security event in the in-memory ring buffer."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_id": msg.task_id,
            "from_agent": msg.from_agent.value if isinstance(msg.from_agent, AgentRole) else msg.from_agent,
            "to_agent": msg.to_agent.value if isinstance(msg.to_agent, AgentRole) else msg.to_agent,
            "action": msg.action,
            "verdict": verdict,
            "issue_count": len(issues),
            "severities": [i.get("severity") for i in issues],
            "categories": [i.get("category") for i in issues],
            "summary": issues[0]["description"] if issues else "",
        }

        self._security_log.append(event)

        # Ring buffer: trim if over limit
        if len(self._security_log) > self._max_log_entries:
            self._security_log = self._security_log[-self._max_log_entries:]
