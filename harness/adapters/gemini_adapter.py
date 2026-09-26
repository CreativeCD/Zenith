"""harness/adapters/gemini_adapter.py — Google Gemini Model Adapter with Multi-Key Rotation & Cascade.

Reference: PRD.md §10 | architecture.md §16
Implements ModelAdapter using the google-genai SDK (v2+) with:
- Multi-key rotation pool with per-key cooldowns (KeyPoolManager)
- Model cascade fallback (gemini-3.6-flash → gemini-3.5-flash → gemini-3.5-flash-lite)
- Per-phase reasoning effort control (thinkingConfig.thinkingBudget)
- Anti-truncation self-healing continuation loop (up to 3x)
- Real per-token cost estimation and telemetry
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
from harness.adapters.key_pool import KeyPoolManager
from harness.contracts import ToolCall

logger = logging.getLogger(__name__)


class GeminiAdapter:
    """Production adapter for Google Gemini models with key pool and cascade fallback."""

    PRICING: dict[str, dict[str, float]] = {
        "gemini-3.6-flash":      {"input": 0.075, "output": 0.30},
        "gemini-3.5-flash":      {"input": 0.075, "output": 0.30},
        "gemini-3.5-flash-lite": {"input": 0.04,  "output": 0.15},
        "gemini-3.8-flash":      {"input": 0.075, "output": 0.30},
        "gemini-2.5-flash":      {"input": 0.075, "output": 0.30},
        "gemini-2.5-pro":        {"input": 1.25,  "output": 10.0},
    }

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: list[str] | None = None,
        key_pool: KeyPoolManager | None = None,
        model_name: str = "gemini-3.6-flash",
        fallback_chain: list[str] | None = None,
        base_url: str | None = None,
        max_continuations: int = 3,
    ) -> None:
        if key_pool is not None:
            self.key_pool = key_pool
        elif api_keys:
            self.key_pool = KeyPoolManager(keys=api_keys)
        elif api_key:
            self.key_pool = KeyPoolManager(keys=[api_key])
        else:
            self.key_pool = KeyPoolManager()

        self.api_key = self.key_pool.keys[0] if self.key_pool.keys else api_key
        self.model_name = model_name
        self.fallback_chain = (
            fallback_chain
            if fallback_chain is not None
            else ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
        )
        self.base_url = base_url
        self.max_continuations = max_continuations
        self._clients: dict[str, Any] = {}

    def _get_client(self, api_key: str | None = None):
        """Get or create a cached google-genai Client for a specific key."""
        target_key = api_key or (self.key_pool.keys[0] if self.key_pool.keys else self.api_key)
        if not target_key:
            raise OSError("No Google AI Studio API key configured. Set AI_API_KEY in .env file.")
        if target_key not in self._clients:
            try:
                from google import genai
                self._clients[target_key] = genai.Client(api_key=target_key)
            except ImportError as exc:
                raise ImportError("google-genai SDK not installed. Run: pip install google-genai") from exc
        return self._clients[target_key]

    @property
    def _client(self):
        """Backward-compatible property for existing tests/references."""
        return self._get_client()

    def _compute_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        pricing = self.PRICING.get(model, self.PRICING.get("gemini-3.5-flash", {"input": 0.075, "output": 0.30}))
        return (tokens_in / 1_000_000) * pricing["input"] + (tokens_out / 1_000_000) * pricing["output"]

    def _get_thinking_config(self, effort: str, model_name: str) -> Any | None:
        """Map reasoning_effort to types.ThinkingConfig, taking model capabilities into account."""
        # Models with 'lite' do not support thinking budget
        if "lite" in model_name.lower():
            return None

        from google.genai import types

        effort_lower = (effort or "low").lower()
        if effort_lower == "none":
            return types.ThinkingConfig(thinking_budget=0)
        elif effort_lower == "low":
            return types.ThinkingConfig(thinking_budget=2048)
        elif effort_lower == "medium":
            return types.ThinkingConfig(thinking_budget=8192)
        elif effort_lower == "high":
            return types.ThinkingConfig(thinking_budget=24576)
        else:
            return types.ThinkingConfig(thinking_budget=2048)

    @staticmethod
    def _is_truncated(text: str) -> bool:
        """Detect if model response was prematurely truncated mid-stream or code-fence."""
        if not text:
            return False
        trimmed = text.strip()
        if len(trimmed) < 40:
            return False

        # 1. Unclosed markdown code fences (odd count of ```)
        fence_count = len(re.findall(r"```", trimmed))
        if fence_count % 2 != 0:
            return True

        # 2. Incomplete markdown formatting at the end
        if trimmed.endswith("**") or (trimmed.endswith("*") and not trimmed.endswith("**")) or trimmed.endswith("#"):
            return True

        # 3. Invalid end punctuation (cut mid-expression or punctuation)
        invalid_end_chars = {",", "-", "=", "+", "/", "\\", "(", "[", "{"}
        if trimmed[-1] in invalid_end_chars:
            return True

        # 4. Valid terminators
        valid_terminators = {".", "!", "?", "`", "}", "]", ")", '"', "'", ">", ";", ":", "\n"}
        last_line = trimmed.splitlines()[-1].strip()
        if not any(last_line.endswith(t) for t in valid_terminators):
            words = last_line.split()
            # If ending in mid-sentence word
            if len(words) >= 4 and words[-1].isalnum() and not last_line.startswith("#"):
                return True

        return False

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

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 65536,
        use_structured_output: bool = True,
        seed: int | None = 42,
        max_retries: int = 4,
        reasoning_effort: str = "low",
    ) -> ModelResponse:
        """Execute chat completion with multi-key rotation, model cascade fallback, and continuation."""
        start_time = time.perf_counter()

        from google.genai import types

        # Build list of models to try in sequence
        models_to_try = [self.model_name]
        for fallback in self.fallback_chain:
            if fallback not in models_to_try:
                models_to_try.append(fallback)

        last_exc: Exception | None = None
        key_pool = self.key_pool
        total_keys = max(1, key_pool.total_keys)

        for model_idx, current_model in enumerate(models_to_try):
            thinking_config = self._get_thinking_config(reasoning_effort, current_model)

            config_kwargs: dict[str, Any] = {
                "temperature": temperature,
                "max_output_tokens": min(max_output_tokens, 65536),
                "system_instruction": system_prompt,
            }
            if thinking_config is not None:
                config_kwargs["thinking_config"] = thinking_config

            if tools:
                config_kwargs["tools"] = [
                    types.Tool(function_declarations=[types.FunctionDeclaration(**t)])
                    for t in tools
                ]
                config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)

            generate_config = types.GenerateContentConfig(**config_kwargs)
            contents = [
                types.Content(role="user", parts=[types.Part(text=user_message)])
            ]

            # Try each key in pool for this model
            for attempt in range(total_keys):
                key_tuple = key_pool.get_next_key()
                if not key_tuple:
                    break
                active_key, active_idx = key_tuple
                client = self._get_client(active_key)

                try:
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=current_model,
                            contents=contents,
                            config=generate_config,
                        ),
                        timeout=30.0,
                    )
                    latency_ms = int((time.perf_counter() - start_time) * 1000)

                    # Successful response: record usage
                    key_pool.record_call(active_key)

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

                    # Anti-truncation continuation engine (Chunk 4)
                    continuation_count = 0
                    while (
                        self._is_truncated(content_text)
                        and continuation_count < self.max_continuations
                        and not tool_calls
                    ):
                        continuation_count += 1
                        logger.info(
                            "Detected truncated response on %s. Executing continuation %d/%d...",
                            current_model, continuation_count, self.max_continuations,
                        )
                        try:
                            # Continuation prompt with effort="none" for zero thinking latency
                            cont_config = types.GenerateContentConfig(
                                temperature=0.0,
                                max_output_tokens=32768,
                                system_instruction=system_prompt,
                            )
                            cont_contents = [
                                types.Content(role="user", parts=[types.Part(text=user_message)]),
                                types.Content(role="model", parts=[types.Part(text=content_text)]),
                                types.Content(role="user", parts=[types.Part(
                                    text="[SYSTEM NOTICE: Your previous output was cut off mid-response. "
                                         "Continue IMMEDIATELY from the exact character where you stopped. "
                                         "Do NOT repeat prior text. Do NOT apologize.]"
                                )]),
                            ]
                            cont_res = await client.aio.models.generate_content(
                                model=current_model,
                                contents=cont_contents,
                                config=cont_config,
                            )
                            if cont_res.candidates and cont_res.candidates[0].content:
                                c_parts = cont_res.candidates[0].content.parts
                                c_text = "\n".join([p.text for p in c_parts if hasattr(p, "text") and p.text])
                                if c_text.strip():
                                    content_text = content_text + "\n" + c_text.strip()
                                    if cont_res.usage_metadata:
                                        tokens_in += cont_res.usage_metadata.prompt_token_count or 0
                                        tokens_out += cont_res.usage_metadata.candidates_token_count or 0
                                else:
                                    break
                            else:
                                break
                        except Exception as cont_exc:
                            logger.warning("Continuation failed: %s", cont_exc)
                            break

                    # Re-parse tool calls if content was extended
                    if not tool_calls and content_text:
                        tool_calls = self._parse_tool_calls_from_text(content_text)

                    cost_usd = self._compute_cost(current_model, tokens_in, tokens_out)
                    logger.debug(
                        "Gemini %s (key #%d) | in=%d out=%d cost=$%.4f latency=%dms",
                        current_model, active_idx + 1, tokens_in, tokens_out, cost_usd, latency_ms,
                    )
                    return ModelResponse(
                        content=content_text,
                        tool_calls=tool_calls,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        latency_ms=latency_ms,
                        model=current_model,
                        finish_reason=finish_reason,
                        cost_usd=cost_usd,
                    )

                except (asyncio.TimeoutError, TimeoutError):
                    logger.warning("Request timed out on %s (key #%d). Trying next key...", current_model, active_idx + 1)
                    key_pool.mark_rate_limited(active_key, retry_delay=10.0)
                    print(f"  ⏱️ Request timed out on key #{active_idx + 1}. Switching to next key...", flush=True)
                    if attempt < total_keys - 1:
                        continue
                    if model_idx < len(models_to_try) - 1:
                        next_model = models_to_try[model_idx + 1]
                        print(f"  ⚡ Cascading to fallback model '{next_model}'...", flush=True)
                        break
                    continue

                except Exception as exc:
                    last_exc = exc
                    exc_str = str(exc)
                    is_rate_limit = any(x in exc_str for x in ("429", "503", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
                    is_auth_error = any(x in exc_str for x in ("401", "403", "API_KEY_INVALID", "PERMISSION_DENIED"))

                    if is_auth_error:
                        key_pool.mark_auth_error(active_key)
                        print(f"  ⚠️ Key #{active_idx + 1} authentication error. Cooling down 5m. Switching key...", flush=True)
                        continue

                    if is_rate_limit:
                        suggested_delay = key_pool.parse_retry_delay(exc_str)
                        cd_sec = key_pool.mark_rate_limited(active_key, suggested_delay)
                        print(
                            f"  🔄 Key #{active_idx + 1} rate-limited on {current_model} "
                            f"(retry in {cd_sec:.0f}s). Switching to next key...",
                            flush=True,
                        )

                        # If we have more keys to try for this model, continue to next key
                        if attempt < total_keys - 1:
                            continue

                        # All keys exhausted for this model!
                        if model_idx < len(models_to_try) - 1:
                            next_model = models_to_try[model_idx + 1]
                            print(
                                f"  ⚡ All {total_keys} keys exhausted on {current_model}. "
                                f"Cascading to fallback model '{next_model}'...",
                                flush=True,
                            )
                            break  # Break inner loop to try next model
                        else:
                            # Last model and all keys exhausted: check if shortest cooldown is brief
                            wait_rem = key_pool.shortest_cooldown_remaining()
                            if wait_rem > 0 and wait_rem <= 65.0:
                                print(
                                    f"  ⏳ All keys cooling down. Waiting {wait_rem:.1f}s for key cooldown...",
                                    flush=True,
                                )
                                await asyncio.sleep(wait_rem + 0.5)
                                # Retry once more
                                continue
                            break

                    # 400 Invalid Argument: might be thinking_config incompatibility
                    if "400" in exc_str and "thinking" in exc_str.lower() and thinking_config is not None:
                        logger.warning("Model %s rejected thinking_config. Retrying without thinking...", current_model)
                        thinking_config = None
                        config_kwargs.pop("thinking_config", None)
                        generate_config = types.GenerateContentConfig(**config_kwargs)
                        continue

                    # Unhandled non-retryable error
                    key_pool.record_error(active_key)
                    logger.error("Non-retryable error on key #%d (%s): %s", active_idx + 1, current_model, exc)
                    break

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("GeminiAdapter failed after model cascade and key pool exhaustion: %s", last_exc)
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
