"""Unified LLM client — multi-provider interface with standardized responses."""

from __future__ import annotations

import json
import os
import re
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Provider → (env var for API key, base URL, default model)
PROVIDERS: dict[str, tuple[str, str, str]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-sonnet-4-20250514"),
    "deepseek": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "deepseek-chat"),
    "qwen": ("QWEN_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "minimax": ("MINIMAX_API_KEY", "https://api.minimax.chat/v1", "abab6.5s-chat"),
    "kimi": ("KIMI_API_KEY", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1", "mistral-large-latest"),
}


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    usage: dict[str, int]
    raw: dict[str, Any] | None = None


def _detect_provider(model: str) -> str:
    """Guess provider from model name prefix."""
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
    if "mistral" in model_lower or "mixtral" in model_lower:
        return "mistral"
    return "anthropic"  # default


class LLMClient:
    """Multi-provider LLM client.

    Fully implements Anthropic Messages API. Other providers use
    OpenAI-compatible chat/completions endpoint (stubbed same shape).
    """

    def __init__(self, default_model: str | None = None, timeout: float = 120.0):
        self.default_model = default_model or os.getenv("LLM_DEFAULT_MODEL", "claude-sonnet-4-20250514")
        self.timeout = timeout
        self._http = httpx.AsyncClient(timeout=timeout)

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
    ) -> dict[str, Any]:
        """Generate a text response. Returns {"content": str, ...}."""
        model = model or self.default_model
        provider = _detect_provider(model)

        if prompt and not messages:
            messages = [{"role": "user", "content": prompt}]

        if provider == "anthropic":
            return await self._call_anthropic(model, system, messages or [], temperature, max_tokens)
        else:
            return await self._call_openai_compat(provider, model, system, messages or [], temperature, max_tokens)

    async def generate_json(
        self,
        *,
        prompt: str,
        system: str = "",
        temperature: float = 0.3,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Generate and parse a JSON response. Returns {"content": <parsed dict>, ...}."""
        result = await self.generate(
            system=system,
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = result["content"]

        # Try to extract JSON from response
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON block in text
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if match:
                parsed = json.loads(match.group(1).strip())
            else:
                # Try to find first { ... } block
                match = re.search(r"\{[\s\S]*\}", text)
                if match:
                    parsed = json.loads(match.group(0))
                else:
                    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")

        result["content"] = parsed
        return result

    async def close(self) -> None:
        await self._http.aclose()

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
            raise RuntimeError("ANTHROPIC_API_KEY not set")

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
        if not api_key:
            raise RuntimeError(f"{env_var} not set for provider {provider}")

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
