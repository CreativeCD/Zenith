"""harness/adapters/gemini_adapter.py — Google Gemini Model Adapter.

Reference: PRD.md §10 | architecture.md §16
Implements ModelAdapter using the google-genai SDK (v2+) with:
- Async non-streaming chat completions
- Automatic retry with backoff for 429 (quota) and 503 (overload) errors
- Tool call parsing from Gemini function_call parts
- Real per-token cost estimation
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from harness.adapters.base import ModelResponse
from harness.contracts import ToolCall

logger = logging.getLogger(__name__)


class GeminiAdapter:
    """Adapter for Google Gemini models using the google-genai SDK (v2+)."""

    PRICING: dict[str, dict[str, float]] = {
        "gemini-3.5-flash":      {"input": 0.075, "output": 0.30},
        "gemini-3.5-flash-lite": {"input": 0.04,  "output": 0.15},
        "gemini-3.8-flash":      {"input": 0.075, "output": 0.30},
        "gemini-2.5-flash":      {"input": 0.075, "output": 0.30},
        "gemini-2.5-pro":        {"input": 1.25,  "output": 10.0},
    }

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-3.5-flash",
        base_url: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("AI_API_KEY")
        self.model_name = model_name
        self.base_url = base_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise OSError("AI_API_KEY not configured. Set it in .env file.")
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except ImportError as exc:
                raise ImportError("google-genai SDK not installed. Run: pip install google-genai") from exc
        return self._client

    def _compute_cost(self, tokens_in: int, tokens_out: int) -> float:
        pricing = self.PRICING.get(self.model_name, self.PRICING["gemini-3.5-flash"])
        return (tokens_in / 1_000_000) * pricing["input"] + (tokens_out / 1_000_000) * pricing["output"]

    def _parse_tool_calls(self, response_parts: list) -> list[ToolCall]:
        tool_calls: list[ToolCall] = []
        for part in response_parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                args = dict(fc.args) if fc.args else {}
                reasoning = args.pop("reasoning", "")
                tool_calls.append(ToolCall(tool=fc.name, reasoning=reasoning, args=args))
        return tool_calls

    def _parse_tool_calls_from_text(self, content: str) -> list[ToolCall]:
        tool_calls: list[ToolCall] = []
        try:
            json_blocks = re.findall(r'\{[^{}]*"tool"\s*:\s*"[^"]+[^{}]*\}', content, re.DOTALL)
            for block in json_blocks:
                try:
                    data = json.loads(block)
                    if "tool" in data:
                        tool_calls.append(ToolCall(
                            tool=data["tool"],
                            reasoning=data.get("reasoning", ""),
                            args=data.get("args", {}),
                        ))
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
        return tool_calls

    def _extract_retry_delay(self, exc: Exception) -> float | None:
        msg = str(exc)
        m = re.search(r"'retryDelay': '(\d+(?:\.\d+)?)s'", msg)
        if m:
            return float(m.group(1))
        m = re.search(r"retry in (\d+(?:\.\d+)?)s", msg, re.IGNORECASE)
        if m:
            return float(m.group(1))
        return None

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
        use_structured_output: bool = True,
        seed: int | None = 42,
        max_retries: int = 4,
    ) -> ModelResponse:
        """Execute async chat completion with retry/backoff on 429/503."""
        client = self._get_client()
        start_time = time.perf_counter()

        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "system_instruction": system_prompt,
        }
        contents = [
            types.Content(role="user", parts=[types.Part(text=user_message)])
        ]
        if tools:
            config_kwargs["tools"] = [
                types.Tool(function_declarations=[types.FunctionDeclaration(**t)])
                for t in tools
            ]

        generate_config = types.GenerateContentConfig(**config_kwargs)
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                response = await client.aio.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=generate_config,
                )
                latency_ms = int((time.perf_counter() - start_time) * 1000)

                content_text = ""
                tool_calls: list[ToolCall] = []
                if response.candidates:
                    candidate = response.candidates[0]
                    if candidate.content and candidate.content.parts:
                        parts = candidate.content.parts
                        text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
                        content_text = "\n".join(text_parts)
                        tool_calls = self._parse_tool_calls(parts)

                if not tool_calls and content_text:
                    tool_calls = self._parse_tool_calls_from_text(content_text)

                tokens_in = tokens_out = 0
                if response.usage_metadata:
                    tokens_in = response.usage_metadata.prompt_token_count or 0
                    tokens_out = response.usage_metadata.candidates_token_count or 0

                finish_reason = "stop"
                if response.candidates and response.candidates[0].finish_reason:
                    finish_reason = str(response.candidates[0].finish_reason.name).lower()

                cost_usd = self._compute_cost(tokens_in, tokens_out)
                logger.debug(
                    "Gemini %s | in=%d out=%d cost=$%.4f latency=%dms",
                    self.model_name, tokens_in, tokens_out, cost_usd, latency_ms,
                )
                return ModelResponse(
                    content=content_text,
                    tool_calls=tool_calls,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    model=self.model_name,
                    finish_reason=finish_reason,
                    cost_usd=cost_usd,
                )

            except Exception as exc:
                last_exc = exc
                exc_str = str(exc)
                is_retryable = any(x in exc_str for x in ("429", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))

                if not is_retryable or attempt >= max_retries:
                    break

                suggested = self._extract_retry_delay(exc)
                wait_sec = suggested if suggested else min(2 ** attempt * 5, 60)
                print(f"  ⏳ Rate limited — waiting {wait_sec:.0f}s (retry {attempt + 1}/{max_retries})...", flush=True)
                await asyncio.sleep(wait_sec)

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("GeminiAdapter failed after %d retries: %s", max_retries, last_exc)
        return ModelResponse(
            content=f"[GEMINI_ERROR: {last_exc!s}]",
            tool_calls=[],
            tokens_in=0,
            tokens_out=0,
            latency_ms=latency_ms,
            model=self.model_name,
            finish_reason="error",
            cost_usd=0.0,
        )
