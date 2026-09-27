"""harness/adapters/gemini_adapter.py — Google Gemini Model Adapter with Multi-Key Rotation & Cascade.

Reference: PRD.md §10 | architecture.md §16
Implements ModelAdapter using the google-genai SDK (v2+) with:
- Multi-key rotation pool with per-key cooldowns (KeyPoolManager)
- Model cascade fallback (gemini-3.6-flash → gemini-3.5-flash → gemini-3.5-flash-lite)
- Per-phase reasoning effort control (thinkingConfig.thinkingBudget)
- Native function-calling turn structure (functionCall / functionResponse parts)
- Optional streaming with live text / thought-summary callbacks
- Anti-truncation self-healing continuation loop (up to 3x)
- Real per-token cost estimation and telemetry
"""

from __future__ import annotations

import asyncio
import json
import logging
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
        model_name: str = "gemini-3.5-flash-lite",
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
        self.total_cached_tokens = 0

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

    def _compute_cost(self, model: str, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> float:
        pricing = self.PRICING.get(model, self.PRICING.get("gemini-3.5-flash", {"input": 0.075, "output": 0.30}))
        # Cached prompt tokens are billed at 25% of the input rate (Gemini
        # implicit caching discount); don't overstate cost by ignoring them.
        cached = min(tokens_cached, tokens_in)
        uncached = tokens_in - cached
        return (
            (uncached / 1_000_000) * pricing["input"]
            + (cached / 1_000_000) * pricing["input"] * 0.25
            + (tokens_out / 1_000_000) * pricing["output"]
        )

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
                if not reasoning or not str(reasoning).strip():
                    reasoning = f"Execute {fc.name} to inspect or modify codebase"
                tool_calls.append(ToolCall(tool=fc.name, reasoning=reasoning, args=args, raw_part=part))
        return tool_calls

    def _parse_tool_calls_from_text(self, content: str) -> list[ToolCall]:
        """Parse tool calls ONLY from explicit machine-format declarations.

        Accepts:
        1. Fenced blocks: ```json {"tool": "...", "args": {...}} ``` (bare ``` too)
        2. Explicit invocation text: "Invoked tool X with args {...}" / "Tool Call: X {...}"

        Deliberately does NOT scan arbitrary prose for JSON objects containing a
        "tool" key — a legitimate answer that embeds example JSON must never be
        hijacked and executed as a real tool call.
        """
        tool_calls: list[ToolCall] = []
        if not content:
            return tool_calls

        import ast

        # 1. Fenced code blocks containing a tool declaration
        for match in re.finditer(r"```(?:json|tool)?\s*(\{.*?\})\s*```", content, re.DOTALL):
            raw = match.group(1)
            data = None
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                try:
                    data = ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    data = None
            if isinstance(data, dict) and "tool" in data:
                reasoning = data.get("reasoning") or f"Execute {data['tool']}"
                tool_calls.append(ToolCall(
                    tool=data["tool"],
                    reasoning=str(reasoning),
                    args=data.get("args", {}) or {},
                ))

        # 2. Textual invocation pattern: "Invoked tool <name> with args { ... }"
        pattern = re.compile(
            r"(?:Invoked tool|Tool Call:?)\s*[`'\"]?(\w+)[`'\"]?\s+with args\s*(\{.*?\})",
            re.DOTALL
        )
        for match in pattern.finditer(content):
            tool_name = match.group(1)
            raw_args_str = match.group(2)
            args = None
            try:
                args = ast.literal_eval(raw_args_str)
            except Exception:
                try:
                    args = json.loads(raw_args_str.replace("'", '"'))
                except Exception:
                    args = None
            if isinstance(args, dict):
                reasoning = args.pop("reasoning", None) or f"Execute {tool_name}"
                tool_calls.append(ToolCall(
                    tool=tool_name,
                    reasoning=str(reasoning),
                    args=args,
                ))

        return tool_calls

    # ─── Native Function-Calling Content Builder ─────────────────────────────

    @staticmethod
    def _build_contents(history: list[dict[str, Any]] | None, user_message: str = "") -> list[Any]:
        """Convert conversation history into Gemini Content objects.

        Preserves native function calls when their cryptographic thought_signature
        is present (required by Gemini 2.0+ / 3.x models). If thought_signature
        is missing (or for cross-model / compacted history), cleanly formats
        turns as standard text so the Gemini API never throws
        '400 INVALID_ARGUMENT: Function call is missing a thought_signature'.
        """
        from google.genai import types

        contents: list[Any] = []
        prev_was_native_call = False

        for msg in history or []:
            role_raw = str(msg.get("role", "user"))
            role = "user" if role_raw in ("user", "human", "tool") else "model"

            # ── Observation turn ──
            responses = msg.get("tool_responses")
            if isinstance(responses, list) and responses:
                if prev_was_native_call:
                    parts = []
                    for r in responses:
                        payload = {
                            "output": str(r.get("output", "")),
                            "status": str(r.get("status", "SUCCESS")),
                        }
                        exit_code = r.get("exit_code")
                        payload["exit_code"] = exit_code if isinstance(exit_code, (int, float)) else "n/a"
                        parts.append(types.Part.from_function_response(
                            name=str(r.get("name", "unknown")),
                            response=payload,
                        ))
                    contents.append(types.Content(role="user", parts=parts))
                    prev_was_native_call = False
                    continue
                else:
                    obs_text = str(msg.get("content", "") or "")
                    if not obs_text.strip():
                        obs_items = []
                        for r in responses:
                            obs_items.append(f"Observation from `{r.get('name', 'unknown')}`:\n{r.get('output', '')}")
                        obs_text = "\n\n".join(obs_items)
                    if obs_text.strip():
                        if contents and contents[-1].role == "user":
                            contents[-1].parts.append(types.Part(text=obs_text))
                        else:
                            contents.append(types.Content(role="user", parts=[types.Part(text=obs_text)]))
                    prev_was_native_call = False
                    continue

            # ── Model tool-call turn ──
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                raw_parts = msg.get("raw_parts") or []
                fc_candidates = [p for p in raw_parts if getattr(p, "function_call", None) is not None]
                if not fc_candidates:
                    tcs_parts = [getattr(tc, "raw_part", None) for tc in tool_calls]
                    if all(p is not None and getattr(p, "function_call", None) is not None for p in tcs_parts):
                        fc_candidates = tcs_parts

                # Strictly require thought_signature on every function_call part!
                can_use_native = (
                    bool(fc_candidates)
                    and len(fc_candidates) == len(tool_calls)
                    and all(getattr(p, "thought_signature", None) for p in fc_candidates)
                )

                if can_use_native:
                    parts = []
                    text = str(msg.get("content", "") or "")
                    if text.strip():
                        parts.append(types.Part(text=text))
                    parts.extend(fc_candidates)
                    contents.append(types.Content(role="model", parts=parts))
                    prev_was_native_call = True
                    continue
                else:
                    text = str(msg.get("content", "") or "")
                    calls_str = []
                    for tc in tool_calls:
                        args = {k: v for k, v in (dict(getattr(tc, "args", {}) or {})).items() if k != "reasoning"}
                        calls_str.append(f"Invoked tool {getattr(tc, 'tool', '')} with args {json.dumps(args)}")
                    call_text = "\n".join(calls_str)
                    full_text = f"{text}\n{call_text}".strip() if text else call_text
                    if contents and contents[-1].role == "model":
                        contents[-1].parts.append(types.Part(text=full_text))
                    else:
                        contents.append(types.Content(role="model", parts=[types.Part(text=full_text)]))
                    prev_was_native_call = False
                    continue

            # ── Plain text entry: merge into previous Content when roles match ──
            text = str(msg.get("content", "") or "")
            if not text.strip():
                continue
            if contents and contents[-1].role == role and not any(getattr(p, "function_response", None) for p in contents[-1].parts):
                contents[-1].parts.append(types.Part(text=text))
            else:
                contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
            prev_was_native_call = False

        # Trailing user message: append to the last user Content if safe
        if user_message and user_message.strip():
            if contents and contents[-1].role == "user" and not any(getattr(p, "function_response", None) for p in contents[-1].parts):
                contents[-1].parts.append(types.Part(text=user_message))
            else:
                contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

        if not contents:
            contents = [types.Content(role="user", parts=[types.Part(text=user_message or "Hello")])]
        elif contents[-1].role != "user":
            # The API requires the conversation to end with a user turn.
            contents.append(types.Content(role="user", parts=[types.Part(
                text="Continue with your next step, or give your final answer now."
            )]))

        return contents

    # ─── Streaming Consumer ──────────────────────────────────────────────────

    async def _consume_stream(
        self,
        stream_iter: Any,
        on_text: Any = None,
        on_thought: Any = None,
        chunk_timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Consume an async chunk iterator, invoking callbacks on each delta.

        Returns a dict with text, thought_text, fc_parts, raw_parts, usage, finish_reason.
        On a mid-stream error after output has been received, returns the
        partial payload with a "stream_error" key instead of raising, so the
        caller can salvage what was already displayed.
        """
        text_parts: list[str] = []
        thought_parts: list[str] = []
        fc_parts: list[Any] = []
        raw_parts: list[Any] = []
        usage: Any = None
        finish_reason = "stop"

        try:
            aiter = stream_iter.__aiter__()
            while True:
                try:
                    chunk = await asyncio.wait_for(aiter.__anext__(), timeout=chunk_timeout)
                except StopAsyncIteration:
                    break
                except (asyncio.TimeoutError, TimeoutError) as te:
                    logger.warning("Stream chunk reading timed out after %.1fs", chunk_timeout)
                    raise TimeoutError(f"Stream chunk timeout after {chunk_timeout}s") from te

                if getattr(chunk, "usage_metadata", None):
                    usage = chunk.usage_metadata
                candidates = getattr(chunk, "candidates", None)
                if not candidates:
                    continue
                cand = candidates[0]
                if getattr(cand, "finish_reason", None):
                    try:
                        finish_reason = str(cand.finish_reason.name).lower()
                    except AttributeError:
                        finish_reason = str(cand.finish_reason).lower()
                content = getattr(cand, "content", None)
                parts = getattr(content, "parts", None) if content else None
                if not parts:
                    continue
                for part in parts:
                    raw_parts.append(part)
                    if getattr(part, "function_call", None):
                        fc_parts.append(part)
                    elif getattr(part, "thought", None) and getattr(part, "text", None):
                        thought_parts.append(part.text)
                        if on_thought:
                            try:
                                on_thought(part.text)
                            except Exception:
                                pass
                    elif getattr(part, "text", None):
                        text_parts.append(part.text)
                        if on_text:
                            try:
                                on_text(part.text)
                            except Exception:
                                pass
        except Exception as exc:
            if text_parts or thought_parts or fc_parts:
                return {
                    "text": "".join(text_parts) if text_parts else "",
                    "thought_text": "".join(thought_parts) if thought_parts else "",
                    "fc_parts": fc_parts,
                    "raw_parts": raw_parts,
                    "usage": usage,
                    "finish_reason": "stream_error",
                    "stream_error": exc,
                }
            raise

        return {
            "text": "".join(text_parts) if text_parts else "",
            "thought_text": "".join(thought_parts) if thought_parts else "",
            "fc_parts": fc_parts,
            "raw_parts": raw_parts,
            "usage": usage,
            "finish_reason": finish_reason,
        }

    async def complete(
        self,
        system_prompt: str,
        user_message: str = "",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 65536,
        use_structured_output: bool = True,
        seed: int | None = 42,
        max_retries: int = 4,
        reasoning_effort: str = "low",
        history: list[dict[str, str]] | None = None,
        stream: bool = False,
        on_text: Any = None,
        on_thought: Any = None,
        include_thoughts: bool | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Execute chat completion with multi-key rotation, model cascade fallback, and continuation.

        Args:
            stream: Use generate_content_stream for live token delivery.
            on_text: Optional callback(delta: str) fired per streamed text delta.
            on_thought: Optional callback(delta: str) fired per thought-summary delta.
            include_thoughts: Request thought summaries (None = auto when on_thought given).
        """
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

        # Contents are model-independent — build once (native function-calling aware)
        contents = self._build_contents(history, user_message)

        for model_idx, current_model in enumerate(models_to_try):
            thinking_config = self._get_thinking_config(reasoning_effort, current_model)
            want_thoughts = include_thoughts if include_thoughts is not None else (on_thought is not None)
            if thinking_config is not None and want_thoughts:
                budget = thinking_config.thinking_budget or 2048
                thinking_config = types.ThinkingConfig(
                    thinking_budget=max(1024, budget),
                    include_thoughts=True,
                )

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

            # Try each key in pool for this model
            for attempt in range(total_keys):
                key_tuple = key_pool.get_next_key()
                if not key_tuple:
                    break
                active_key, active_idx = key_tuple
                client = self._get_client(active_key)

                try:
                    if stream:
                        try:
                            stream_iter = await asyncio.wait_for(
                                client.aio.models.generate_content_stream(
                                    model=current_model,
                                    contents=contents,
                                    config=generate_config,
                                ),
                                timeout=30.0,
                            )
                        except Exception as init_exc:
                            logger.warning("Stream init failed on %s: %s", current_model, init_exc)
                            raise

                        try:
                            result = await asyncio.wait_for(
                                self._consume_stream(stream_iter, on_text=on_text, on_thought=on_thought, chunk_timeout=25.0),
                                timeout=120.0,
                            )
                        except Exception as stream_exc:
                            # Nothing streamed yet — safe to rotate keys / models.
                            logger.warning("Stream failed before any output on %s: %s", current_model, stream_exc)
                            raise

                        if result.get("stream_error"):
                            exc = result["stream_error"]
                            logger.warning("Stream interrupted mid-response on %s: %s", current_model, exc)
                            last_exc = exc
                            clean_text = (result.get("text") or "").strip()
                            if (len(clean_text) < 40 or self._is_truncated(clean_text)) and not result.get("fc_parts"):
                                logger.info("Partial stream output too short or truncated (%r). Falling back to retry...", clean_text)
                                raise exc

                            latency_ms = int((time.perf_counter() - start_time) * 1000)
                            return ModelResponse(
                                content=result["text"],
                                tool_calls=self._parse_tool_calls(result["fc_parts"]),
                                tokens_in=0,
                                tokens_out=0,
                                latency_ms=latency_ms,
                                model=current_model,
                                finish_reason="stream_error",
                                cost_usd=0.0,
                            )
                        latency_ms = int((time.perf_counter() - start_time) * 1000)
                        key_pool.record_call(active_key)

                        content_text = result["text"]
                        tool_calls: list[ToolCall] = self._parse_tool_calls(result["fc_parts"])
                        tokens_in = tokens_out = tokens_cached = 0
                        if result["usage"]:
                            um = result["usage"]
                            tokens_in = um.prompt_token_count or 0
                            tokens_out = um.candidates_token_count or 0
                            cached_raw = getattr(um, "cached_content_token_count", 0)
                            tokens_cached = cached_raw if isinstance(cached_raw, int) else 0
                        self.total_cached_tokens += tokens_cached
                        finish_reason = result["finish_reason"]

                        cost_usd = self._compute_cost(current_model, tokens_in, tokens_out, tokens_cached)
                        return ModelResponse(
                            content=content_text,
                            tool_calls=tool_calls,
                            tokens_in=tokens_in,
                            tokens_out=tokens_out,
                            tokens_cached=tokens_cached,
                            latency_ms=latency_ms,
                            model=current_model,
                            finish_reason=finish_reason,
                            cost_usd=cost_usd,
                            raw_parts=result.get("raw_parts", []),
                        )

                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=current_model,
                            contents=contents,
                            config=generate_config,
                        ),
                        timeout=120.0,
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
                        if tool_calls:
                            content_text = ""

                    tokens_in = tokens_out = tokens_cached = 0
                    if response.usage_metadata:
                        tokens_in = response.usage_metadata.prompt_token_count or 0
                        tokens_out = response.usage_metadata.candidates_token_count or 0
                        cached_raw = getattr(response.usage_metadata, "cached_content_token_count", 0)
                        tokens_cached = cached_raw if isinstance(cached_raw, int) else 0
                    self.total_cached_tokens += tokens_cached

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
                            # Continue from the full conversation, not just the
                            # last user message — otherwise the continuation
                            # loses every tool observation before it.
                            cont_contents = list(contents) + [
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
                        if tool_calls:
                            content_text = ""

                    cost_usd = self._compute_cost(current_model, tokens_in, tokens_out, tokens_cached)
                    logger.debug(
                        "Gemini %s (key #%d) | in=%d out=%d cached=%d cost=$%.4f latency=%dms",
                        current_model, active_idx + 1, tokens_in, tokens_out, tokens_cached, cost_usd, latency_ms,
                    )
                    return ModelResponse(
                        content=content_text,
                        tool_calls=tool_calls,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        tokens_cached=tokens_cached,
                        latency_ms=latency_ms,
                        model=current_model,
                        finish_reason=finish_reason,
                        cost_usd=cost_usd,
                        raw_parts=list(parts),
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
                    # Transient server-side failures deserve the same key/model
                    # rotation as rate limits instead of aborting the cascade.
                    is_server_error = any(x in exc_str for x in ("500", "INTERNAL", "DEADLINE_EXCEEDED"))
                    is_auth_error = any(x in exc_str for x in ("401", "403", "API_KEY_INVALID", "PERMISSION_DENIED"))

                    if is_auth_error:
                        key_pool.mark_auth_error(active_key)
                        print(f"  ⚠️ Key #{active_idx + 1} authentication error. Cooling down 5m. Switching key...", flush=True)
                        continue

                    if is_rate_limit or is_server_error:
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
