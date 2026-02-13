"""Unified LLM client — multi-provider interface with standardized responses."""

from __future__ import annotations

import asyncio
import json
import os
import re
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from agents.common.retry import retry_with_backoff
from agents.common.errors import LLMError, ConfigError
from agents.common.usage_tracker import UsageTracker

logger = logging.getLogger(__name__)

# Model name → provider mapping for auto-detection
MODEL_TO_PROVIDER: dict[str, str] = {
    "claude-sonnet-4": "anthropic",
    "claude-sonnet-4-20250514": "anthropic",
    "claude-opus-4": "anthropic",
    "claude-opus-4-0514": "anthropic",
    "deepseek-v3": "deepseek",
    "deepseek-chat": "deepseek",
    "deepseek-coder": "deepseek",
    "qwen-max": "qwen",
    "qwen-plus": "qwen",
    "qwen-turbo": "qwen",
    "abab6.5s-chat": "minimax",
    "abab5.5-chat": "minimax",
    "moonshot-v1-8k": "kimi",
    "moonshot-v1-32k": "kimi",
    "moonshot-v1-128k": "kimi",
    "codestral-latest": "mistral",
    "codestral": "mistral",
    "mistral-large-latest": "mistral",
    "mistral-small-latest": "mistral",
}

# Module-level singleton usage tracker
_usage_tracker: UsageTracker | None = None


def get_usage_tracker() -> UsageTracker:
    """Get or create the singleton UsageTracker instance."""
    global _usage_tracker
    if _usage_tracker is None:
        _usage_tracker = UsageTracker()
    return _usage_tracker

# Provider → (env var for API key, base URL, default model)
PROVIDERS: dict[str, tuple[str, str, str]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-sonnet-4-20250514"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
    "qwen": ("QWEN_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "minimax": ("MINIMAX_API_KEY", "https://api.minimax.chat/v1", "abab6.5s-chat"),
    "kimi": ("KIMI_API_KEY", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1", "mistral-large-latest"),
}

# Standardized error result factory
def _error_result(message: str, provider: str = "") -> dict[str, Any]:
    return {"error": True, "message": message, "provider": provider, "content": ""}


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    usage: dict[str, int]
    raw: dict[str, Any] | None = None


def _detect_provider(model: str) -> str:
    """Detect provider from model name, using exact mapping first then heuristics."""
    # Exact match
    if model in MODEL_TO_PROVIDER:
        return MODEL_TO_PROVIDER[model]
    # Heuristic fallback
    model_lower = model.lower()
    if "claude" in model_lower:
        return "anthropic"
    if "deepseek" in model_lower:
        return "deepseek"
    if "qwen" in model_lower:
        return "qwen"
    if "minimax" in model_lower or "abab" in model_lower:
        return "minimax"
    if "moonshot" in model_lower or "kimi" in model_lower:
        return "kimi"
    if "mistral" in model_lower or "mixtral" in model_lower or "codestral" in model_lower:
        return "mistral"
    return "anthropic"  # default


class LLMClient:
    """Multi-provider LLM client with comprehensive error handling.

    All errors return standardized error dicts instead of raising.
    Includes retry logic for transient failures.
    """

    def __init__(
        self,
        default_model: str | None = None,
        timeout: float = 60.0,
        code_timeout: float = 180.0,
        agent_name: str = "unknown",
    ):
        self.default_model = default_model or os.getenv("LLM_DEFAULT_MODEL", "claude-sonnet-4-20250514")
        self.timeout = timeout
        self.code_timeout = code_timeout
        self.agent_name = agent_name
        self._http = httpx.AsyncClient(timeout=timeout)
        self._usage_tracker = get_usage_tracker()

    # ─── Public API ───────────────────────────────────────────────────

    async def generate(
        self,
        *,
        system: str = "",
        messages: list[dict] | None = None,
        prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        is_code: bool = False,
    ) -> dict[str, Any]:
        """Generate a text response. Returns {"content": str, ...} or error dict."""
        model = model or self.default_model
        provider = _detect_provider(model)

        if prompt and not messages:
            messages = [{"role": "user", "content": prompt}]

        start_ms = time.monotonic_ns() // 1_000_000
        try:
            if provider == "anthropic":
                result = await self._call_with_resilience(
                    self._call_anthropic, provider,
                    model, system, messages or [], temperature, max_tokens,
                    is_code=is_code,
                )
            else:
                result = await self._call_with_resilience(
                    self._call_openai_compat, provider,
                    provider, model, system, messages or [], temperature, max_tokens,
                    is_code=is_code,
                )
            duration_ms = int(time.monotonic_ns() // 1_000_000 - start_ms)
            self._track_usage(result, model, provider, duration_ms)
            return result
        except Exception as e:
            duration_ms = int(time.monotonic_ns() // 1_000_000 - start_ms)
            logger.error(f"Unhandled LLM error for {provider}: {e}")
            try:
                self._usage_tracker.log_call(
                    agent=self.agent_name, model=model, provider=provider,
                    input_tokens=0, output_tokens=0, duration_ms=duration_ms,
                    success=False, error_message=str(e),
                )
            except Exception:
                pass
            return _error_result(f"Unexpected error: {e}", provider)

    async def generate_json(
        self,
        *,
        prompt: str,
        system: str = "",
        temperature: float = 0.3,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Generate and parse a JSON response. Returns {"content": <parsed dict>, ...} or error dict."""
        result = await self.generate(
            system=system,
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if result.get("error"):
            return result

        text = result["content"]

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if match:
                try:
                    parsed = json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    return _error_result(f"Could not parse JSON from response: {text[:200]}", result.get("provider", ""))
            else:
                match = re.search(r"\{[\s\S]*\}", text)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        return _error_result(f"Could not parse JSON from response: {text[:200]}", result.get("provider", ""))
                else:
                    return _error_result(f"No JSON found in response: {text[:200]}", result.get("provider", ""))

        result["content"] = parsed
        return result

    def _track_usage(self, result: dict, model: str, provider: str, duration_ms: int):
        """Log usage from a completed LLM call."""
        try:
            if result.get("error"):
                self._usage_tracker.log_call(
                    agent=self.agent_name, model=model, provider=provider,
                    input_tokens=0, output_tokens=0, duration_ms=duration_ms,
                    success=False, error_message=result.get("message", ""),
                )
                return
            usage = result.get("usage", {})
            input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
            output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
            self._usage_tracker.log_call(
                agent=self.agent_name, model=model, provider=provider,
                input_tokens=input_tokens, output_tokens=output_tokens,
                duration_ms=duration_ms, success=True,
            )
        except Exception as e:
            logger.debug(f"Usage tracking failed (non-fatal): {e}")

    async def close(self) -> None:
        await self._http.aclose()

    # ─── Resilience wrapper ───────────────────────────────────────────

    async def _call_with_resilience(
        self, fn, provider: str, *args, is_code: bool = False, **kwargs
    ) -> dict[str, Any]:
        """Wrap an API call with retry/error handling."""
        timeout = self.code_timeout if is_code else self.timeout

        try:
            return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)

        except asyncio.TimeoutError:
            logger.warning(f"Timeout for {provider} ({timeout}s), retrying with extended timeout")
            try:
                return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout * 2)
            except (asyncio.TimeoutError, Exception) as e:
                return _error_result(f"Request timed out after retry ({timeout * 2}s)", provider)

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                logger.error(f"API key invalid for {provider}")
                return _error_result(f"API key invalid for {provider}", provider)
            elif status == 429:
                # Exponential backoff retry for rate limits
                for attempt, delay in enumerate([2, 4, 8]):
                    logger.warning(f"Rate limited by {provider}, retry {attempt + 1}/3 after {delay}s")
                    await asyncio.sleep(delay)
                    try:
                        return await fn(*args, **kwargs)
                    except httpx.HTTPStatusError as retry_e:
                        if retry_e.response.status_code != 429:
                            return _error_result(f"HTTP {retry_e.response.status_code} from {provider}", provider)
                return _error_result(f"Rate limited by {provider} after 3 retries", provider)
            elif status in (500, 502, 503):
                logger.warning(f"Server error {status} from {provider}, retrying once after 3s")
                await asyncio.sleep(3)
                try:
                    return await fn(*args, **kwargs)
                except Exception as retry_e:
                    return _error_result(f"Server error {status} from {provider} after retry: {retry_e}", provider)
            else:
                return _error_result(f"HTTP {status} from {provider}: {e}", provider)

        except httpx.TimeoutException:
            logger.warning(f"httpx timeout for {provider}, retrying once")
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                return _error_result(f"Timeout from {provider} after retry: {e}", provider)

        except Exception as e:
            return _error_result(f"Unexpected error from {provider}: {e}", provider)

    # ─── Anthropic Messages API ───────────────────────────────────────

    async def _call_anthropic(
        self,
        model: str,
        system: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return _error_result("ANTHROPIC_API_KEY not set", "anthropic")

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            body["system"] = system

        resp = await self._http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block["text"]

        return {
            "content": content,
            "model": data.get("model", model),
            "provider": "anthropic",
            "usage": data.get("usage", {}),
            "raw": data,
        }

    # ─── OpenAI-compatible (DeepSeek, Qwen, Kimi, Mistral, MiniMax) ──

    async def _call_openai_compat(
        self,
        provider: str,
        model: str,
        system: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        env_var, base_url, _ = PROVIDERS[provider]
        api_key = os.environ.get(env_var, "")
        # Fallback env vars for providers with multiple key names
        if not api_key and provider == "qwen":
            api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        elif not api_key and provider == "kimi":
            api_key = os.environ.get("MOONSHOT_API_KEY", "")
        if not api_key:
            return _error_result(f"{env_var} not set for provider {provider}", provider)

        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)

        resp = await self._http.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": oai_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        return {
            "content": content,
            "model": data.get("model", model),
            "provider": provider,
            "usage": data.get("usage", {}),
            "raw": data,
        }
