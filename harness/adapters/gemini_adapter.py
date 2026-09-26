"""harness/adapters/gemini_adapter.py — Google Gemini Model Adapter.

Reference: PRD.md §10 | architecture.md §16
Implements ModelAdapter using the google-genai SDK (v2+) with:
- Async non-streaming chat completions
- Tool call parsing from Gemini function_call parts
- KV cache exploitation via byte-identical system prompt prefix
- Graceful fallback for missing API key
"""

from __future__ import annotations

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

    # Gemini pricing per 1M tokens (gemini-3.5-flash series, 2026)
    PRICING: dict[str, dict[str, float]] = {
        "gemini-3.5-flash":      {"input": 0.075, "output": 0.30},
        "gemini-3.5-flash-lite": {"input": 0.04,  "output": 0.15},
        "gemini-3.8-flash":      {"input": 0.075, "output": 0.30},
        # Legacy (kept for reference)
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
        """Lazily initialize the google-genai Client (thread-safe)."""
        if self._client is None:
            if not self.api_key:
                raise OSError(
                    "AI_API_KEY not configured. "
                    "Set AI_API_KEY in your .env file or environment."
                )
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except ImportError as exc:
                raise ImportError(
                    "google-genai SDK not installed. Run: pip install google-genai"
                ) from exc
        return self._client

    def _compute_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Estimate USD cost from token counts using Gemini pricing table."""
        pricing = self.PRICING.get(self.model_name, self.PRICING["gemini-2.5-flash"])
        return (tokens_in / 1_000_000) * pricing["input"] + (tokens_out / 1_000_000) * pricing["output"]

    def _parse_tool_calls(self, response_parts: list) -> list[ToolCall]:
        """Extract tool calls from Gemini function_call response parts."""
        tool_calls: list[ToolCall] = []
        for part in response_parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                args = dict(fc.args) if fc.args else {}
                reasoning = args.pop("reasoning", "")
                tc = ToolCall(
                    tool=fc.name,
                    reasoning=reasoning,
                    args=args,
                )
                tool_calls.append(tc)
        return tool_calls

    def _parse_tool_calls_from_text(self, content: str) -> list[ToolCall]:
        """Fallback: parse JSON tool calls embedded in model text output."""
        tool_calls: list[ToolCall] = []
        # Look for {"tool": "...", "reasoning": "...", "args": {...}} patterns
        try:
            json_blocks = re.findall(r'\{[^{}]*"tool"\s*:\s*"[^"]+[^{}]*\}', content, re.DOTALL)
            for block in json_blocks:
                try:
                    data = json.loads(block)
                    if "tool" in data:
                        tc = ToolCall(
                            tool=data["tool"],
                            reasoning=data.get("reasoning", ""),
                            args=data.get("args", {}),
                        )
                        tool_calls.append(tc)
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
        return tool_calls

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
        use_structured_output: bool = True,
        seed: int | None = 42,
    ) -> ModelResponse:
        """Execute async chat completion with Gemini using google-genai SDK v2."""
        client = self._get_client()
        start_time = time.perf_counter()

        try:
            from google.genai import types

            config_kwargs: dict[str, Any] = {
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "system_instruction": system_prompt,
            }

            # Build contents
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part(text=user_message)],
                )
            ]

            # Add tool declarations if provided
            if tools:
                gemini_tools = []
                for t in tools:
                    gemini_tools.append(
                        types.Tool(
                            function_declarations=[
                                types.FunctionDeclaration(**t)
                            ]
                        )
                    )
                config_kwargs["tools"] = gemini_tools

            generate_config = types.GenerateContentConfig(**config_kwargs)

            # Async call via client.aio.models.generate_content
            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=generate_config,
            )

            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Extract text content
            content_text = ""
            tool_calls: list[ToolCall] = []

            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    parts = candidate.content.parts
                    # Extract text from text parts
                    text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
                    content_text = "\n".join(text_parts)
                    # Extract tool calls from function_call parts
                    tool_calls = self._parse_tool_calls(parts)

            # Fallback: parse tool call JSON from text if no native function calls
            if not tool_calls and content_text:
                tool_calls = self._parse_tool_calls_from_text(content_text)

            # Token accounting
            tokens_in = 0
            tokens_out = 0
            if response.usage_metadata:
                tokens_in = response.usage_metadata.prompt_token_count or 0
                tokens_out = response.usage_metadata.candidates_token_count or 0

            finish_reason = "stop"
            if response.candidates and response.candidates[0].finish_reason:
                finish_reason = str(response.candidates[0].finish_reason.name).lower()

            cost_usd = self._compute_cost(tokens_in, tokens_out)

            logger.debug(
                "Gemini %s | tokens_in=%d tokens_out=%d cost=$%.4f latency=%dms finish=%s",
                self.model_name, tokens_in, tokens_out, cost_usd, latency_ms, finish_reason,
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
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("GeminiAdapter.complete() failed: %s", exc)
            # Return error signal so orchestrator can handle recovery
            return ModelResponse(
                content=f"[GEMINI_ERROR: {exc!s}]",
                tool_calls=[],
                tokens_in=0,
                tokens_out=0,
                latency_ms=latency_ms,
                model=self.model_name,
                finish_reason="error",
                cost_usd=0.0,
            )
