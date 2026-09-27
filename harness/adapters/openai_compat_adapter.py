"""harness/adapters/openai_compat_adapter.py — OpenAI-Compatible Model Adapter.

Works with any provider that exposes an OpenAI v1 REST API:
  - DeepSeek  (https://api.deepseek.com/v1 or https://api.deepseek.com)
  - OpenAI    (https://api.openai.com/v1)
  - Any other OpenAI-compatible endpoint (OpenRouter, local Ollama, vLLM, etc.)

Features:
  - Full multi-key rotation pool with fair round-robin and per-key rate-limit cooldowns
  - Real-time Server-Sent Events (SSE) streaming support (`stream=True`, `on_text`, `on_thought`)
  - DeepSeek-R1 reasoning support via `reasoning_content` delta streaming
  - Native tool/function-calling via standard OpenAI tools schema
  - Robust text-to-tool parsing fallback for responses formatted in markdown or JSON
  - Model cascade fallback (e.g. deepseek-chat → deepseek-reasoner)
  - Per-token cost accounting
"""

from __future__ import annotations

import ast
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


class OpenAICompatAdapter:
    """Adapter for any OpenAI-compatible REST API (DeepSeek, OpenAI, etc.)."""

    # USD per 1M tokens
    PRICING: dict[str, dict[str, float]] = {
        # DeepSeek
        "deepseek-chat":     {"input": 0.14, "output": 0.28},
        "deepseek-reasoner": {"input": 0.55, "output": 2.19},
        "deepseek-coder":    {"input": 0.14, "output": 0.28},
        # OpenAI
        "gpt-4o":            {"input": 2.50, "output": 10.00},
        "gpt-4o-mini":       {"input": 0.15, "output": 0.60},
        "gpt-4.1":           {"input": 2.00, "output": 8.00},
        "gpt-4.1-mini":      {"input": 0.40, "output": 1.60},
        "gpt-4.1-nano":      {"input": 0.10, "output": 0.40},
        # Generic fallback
        "default":           {"input": 0.50, "output": 1.50},
    }

    def __init__(
        self,
        api_key: str | None = None,
        api_keys: list[str] | None = None,
        key_pool: KeyPoolManager | None = None,
        model_name: str = "deepseek-chat",
        fallback_chain: list[str] | None = None,
        base_url: str = "https://api.deepseek.com/v1",
        max_continuations: int = 2,
        provider_name: str = "DeepSeek",
    ) -> None:
        if key_pool is not None:
            self.key_pool = key_pool
        elif api_keys:
            self.key_pool = KeyPoolManager(keys=api_keys)
        elif api_key:
            self.key_pool = KeyPoolManager(keys=[api_key])
        else:
            self.key_pool = KeyPoolManager(keys=[])

        self.model_name = model_name
        self.fallback_chain = fallback_chain or []
        self.base_url = base_url.rstrip("/")
        self.max_continuations = max_continuations
        self.provider_name = provider_name
        self.total_cached_tokens = 0

    def _compute_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        pricing = self.PRICING.get(model, self.PRICING["default"])
        return (
            (tokens_in / 1_000_000) * pricing["input"]
            + (tokens_out / 1_000_000) * pricing["output"]
        )

    def _build_messages(
        self,
        system_prompt: str,
        user_message: str,
        history: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Convert Zenith history + system prompt into standard OpenAI messages."""
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            for msg in history:
                role = msg.get("role", "user")
                # Handle tool responses in history
                if "tool_responses" in msg:
                    for tr in msg["tool_responses"]:
                        fn_name = tr.get("name", "tool")
                        out = str(tr.get("output", ""))
                        messages.append({
                            "role": "user",
                            "content": f"[Tool Observation for `{fn_name}`]:\n{out}",
                        })
                    continue

                content = msg.get("content", msg.get("text", ""))
                if content is None:
                    content = ""
                content_str = str(content)
                if not content_str.strip():
                    continue

                # Gemini uses "model" — OpenAI uses "assistant"
                oai_role = "assistant" if role == "model" else "user"
                messages.append({"role": oai_role, "content": content_str})

        if user_message and user_message.strip():
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] += "\n\n" + user_message.strip()
            else:
                messages.append({"role": "user", "content": user_message.strip()})

        # Ensure valid conversation shape
        if not messages:
            messages.append({"role": "user", "content": "Hello"})
        elif messages[-1]["role"] == "assistant":
            messages.append({"role": "user", "content": "Please proceed."})

        return messages

    def _parse_tool_calls(self, response_message: dict[str, Any]) -> list[ToolCall]:
        """Parse OpenAI-format tool_calls from a response message dict."""
        tool_calls: list[ToolCall] = []
        raw_tool_calls = response_message.get("tool_calls") or []
        for tc in raw_tool_calls:
            if tc.get("type") != "function":
                continue
            fn = tc.get("function", {})
            name = fn.get("name", "")
            if not name:
                continue
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}
            if not isinstance(args, dict):
                args = {}
            reasoning = args.pop("reasoning", None) or f"Execute {name}"
            tool_calls.append(ToolCall(tool=name, reasoning=str(reasoning), args=args))
        return tool_calls

    @staticmethod
    def _parse_tool_calls_from_text(content: str) -> list[ToolCall]:
        """Extract tool calls from markdown code blocks or text invocation patterns."""
        if not content:
            return []

        tool_calls: list[ToolCall] = []

        # 1. Look for ```json blocks containing {"tool": ...}
        code_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        for raw in code_blocks:
            raw = raw.strip()
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
            re.DOTALL,
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

    async def complete(
        self,
        system_prompt: str,
        user_message: str = "",
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 8192,
        use_structured_output: bool = True,
        seed: int | None = 42,
        max_retries: int = 4,
        reasoning_effort: str = "low",
        history: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Execute chat completion via OpenAI-compatible REST API with key rotation and optional streaming."""
        import httpx

        stream = bool(kwargs.get("stream", False))
        on_text = kwargs.get("on_text")
        on_thought = kwargs.get("on_thought")

        start_time = time.perf_counter()
        models_to_try = [self.model_name] + [m for m in self.fallback_chain if m != self.model_name]
        messages = self._build_messages(system_prompt, user_message, history)
        last_exc: Exception | None = None
        key_pool = self.key_pool
        total_keys = max(1, key_pool.total_keys)

        for model_idx, current_model in enumerate(models_to_try):
            payload: dict[str, Any] = {
                "model": current_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": min(max_output_tokens, 8192),
            }
            if seed is not None:
                payload["seed"] = seed
            if tools:
                oai_tools = []
                for t in tools:
                    params = t.get("parameters", {"type": "object", "properties": {}})
                    oai_tools.append({
                        "type": "function",
                        "function": {
                            "name": t.get("name", ""),
                            "description": t.get("description", ""),
                            "parameters": params,
                        },
                    })
                payload["tools"] = oai_tools
                payload["tool_choice"] = "auto"

            for attempt in range(total_keys):
                key_tuple = key_pool.get_next_key()
                if not key_tuple:
                    break
                active_key, active_idx = key_tuple

                headers = {
                    "Authorization": f"Bearer {active_key}",
                    "Content-Type": "application/json",
                }
                if stream:
                    headers["Accept"] = "text/event-stream"

                stream_started = False
                accumulated_text: list[str] = []

                try:
                    if stream:
                        payload["stream"] = True
                        payload["stream_options"] = {"include_usage": True}
                        accumulated_tool_calls: dict[int, dict[str, Any]] = {}
                        tokens_in = 0
                        tokens_out = 0
                        finish_reason = "stop"

                        async with httpx.AsyncClient(timeout=120.0) as client:
                            async with client.stream(
                                "POST",
                                f"{self.base_url}/chat/completions",
                                headers=headers,
                                json=payload,
                            ) as resp:
                                if resp.status_code >= 400:
                                    err_body = await resp.aread()
                                    try:
                                        err_json = json.loads(err_body)
                                        err = err_json.get("error", {})
                                        err_msg = err.get("message", str(err))
                                    except Exception:
                                        err_msg = err_body.decode(errors="replace")
                                    raise RuntimeError(f"{resp.status_code}: {err_msg}")

                                async for line in resp.aiter_lines():
                                    line = line.strip()
                                    if not line or not line.startswith("data:"):
                                        continue
                                    data_str = line[5:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(data_str)
                                    except json.JSONDecodeError:
                                        continue

                                    stream_started = True

                                    if "usage" in chunk and chunk["usage"]:
                                        tokens_in = chunk["usage"].get("prompt_tokens", tokens_in)
                                        tokens_out = chunk["usage"].get("completion_tokens", tokens_out)

                                    choices = chunk.get("choices") or []
                                    if not choices:
                                        continue
                                    c = choices[0]
                                    if c.get("finish_reason"):
                                        finish_reason = c["finish_reason"]

                                    delta = c.get("delta") or {}

                                    # 1. Thought / reasoning delta (DeepSeek-R1)
                                    reasoning_delta = delta.get("reasoning_content") or delta.get("thought")
                                    if reasoning_delta and on_thought:
                                        try:
                                            on_thought(reasoning_delta)
                                        except Exception:
                                            pass

                                    # 2. Text content delta
                                    text_delta = delta.get("content")
                                    if text_delta:
                                        accumulated_text.append(text_delta)
                                        if on_text:
                                            try:
                                                on_text(text_delta)
                                            except Exception:
                                                pass

                                    # 3. Tool call deltas
                                    tc_deltas = delta.get("tool_calls") or []
                                    for tc_d in tc_deltas:
                                        idx = tc_d.get("index", 0)
                                        if idx not in accumulated_tool_calls:
                                            accumulated_tool_calls[idx] = {
                                                "name": "",
                                                "arguments": "",
                                            }
                                        fn = tc_d.get("function") or {}
                                        if "name" in fn and fn["name"]:
                                            accumulated_tool_calls[idx]["name"] += fn["name"]
                                        if "arguments" in fn and fn["arguments"]:
                                            accumulated_tool_calls[idx]["arguments"] += fn["arguments"]

                        content_text = "".join(accumulated_text)
                        tool_calls: list[ToolCall] = []
                        for idx in sorted(accumulated_tool_calls.keys()):
                            fn_info = accumulated_tool_calls[idx]
                            fn_name = fn_info["name"].strip()
                            if not fn_name:
                                continue
                            try:
                                fn_args = json.loads(fn_info["arguments"])
                            except Exception:
                                fn_args = {}
                            if not isinstance(fn_args, dict):
                                fn_args = {}
                            reasoning = fn_args.pop("reasoning", None) or f"Execute {fn_name}"
                            tool_calls.append(ToolCall(tool=fn_name, reasoning=str(reasoning), args=fn_args))

                        if tool_calls:
                            content_text = ""
                        elif not tool_calls and content_text:
                            parsed_text_tools = self._parse_tool_calls_from_text(content_text)
                            if parsed_text_tools:
                                tool_calls = parsed_text_tools
                                content_text = ""

                        if tokens_in == 0:
                            tokens_in = len(json.dumps(messages)) // 4
                        if tokens_out == 0:
                            tokens_out = len(content_text) // 4

                        key_pool.record_call(active_key)
                        latency_ms = int((time.perf_counter() - start_time) * 1000)
                        cost_usd = self._compute_cost(current_model, tokens_in, tokens_out)
                        return ModelResponse(
                            content=content_text,
                            tool_calls=tool_calls,
                            tokens_in=tokens_in,
                            tokens_out=tokens_out,
                            tokens_cached=0,
                            latency_ms=latency_ms,
                            model=current_model,
                            finish_reason=finish_reason,
                            cost_usd=cost_usd,
                        )

                    # Non-streaming path
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        resp = await client.post(
                            f"{self.base_url}/chat/completions",
                            headers=headers,
                            json=payload,
                        )
                        resp_json = resp.json()

                    if resp.status_code >= 400 or "error" in resp_json:
                        err = resp_json.get("error", {})
                        if isinstance(err, dict):
                            err_msg = err.get("message", str(err))
                            err_code = str(err.get("code", resp.status_code))
                        else:
                            err_msg = str(err)
                            err_code = str(resp.status_code)
                        raise RuntimeError(f"{err_code}: {err_msg}")

                    key_pool.record_call(active_key)
                    latency_ms = int((time.perf_counter() - start_time) * 1000)

                    choice = (resp_json.get("choices") or [{}])[0]
                    response_message = choice.get("message", {})
                    content_text = response_message.get("content") or ""
                    tool_calls = self._parse_tool_calls(response_message)
                    if tool_calls:
                        content_text = ""

                    # Fallback to text parsing if no formal tool calls were returned
                    if not tool_calls and content_text:
                        parsed_text_tools = self._parse_tool_calls_from_text(content_text)
                        if parsed_text_tools:
                            tool_calls = parsed_text_tools
                            content_text = ""

                    usage = resp_json.get("usage", {})
                    tokens_in = usage.get("prompt_tokens", 0)
                    tokens_out = usage.get("completion_tokens", 0)
                    finish_reason = choice.get("finish_reason", "stop") or "stop"

                    cost_usd = self._compute_cost(current_model, tokens_in, tokens_out)
                    logger.debug(
                        "%s %s (key #%d) | in=%d out=%d cost=$%.4f latency=%dms",
                        self.provider_name, current_model, active_idx + 1,
                        tokens_in, tokens_out, cost_usd, latency_ms,
                    )
                    return ModelResponse(
                        content=content_text,
                        tool_calls=tool_calls,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        tokens_cached=0,
                        latency_ms=latency_ms,
                        model=current_model,
                        finish_reason=finish_reason,
                        cost_usd=cost_usd,
                    )

                except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException):
                    if stream and stream_started:
                        logger.warning("Stream dropped mid-response on %s key #%d.", current_model, active_idx + 1)
                        return ModelResponse(
                            content="".join(accumulated_text),
                            tool_calls=[],
                            tokens_in=0,
                            tokens_out=len("".join(accumulated_text)) // 4,
                            latency_ms=int((time.perf_counter() - start_time) * 1000),
                            model=current_model,
                            finish_reason="stream_error",
                            cost_usd=0.0,
                        )
                    key_pool.mark_rate_limited(active_key, retry_delay=10.0)
                    logger.warning("Timeout on %s key #%d. Trying next key...", current_model, active_idx + 1)
                    if attempt < total_keys - 1:
                        continue
                    break

                except Exception as exc:
                    if stream and stream_started:
                        logger.warning("Stream exception mid-response on %s key #%d: %s", current_model, active_idx + 1, exc)
                        return ModelResponse(
                            content="".join(accumulated_text),
                            tool_calls=[],
                            tokens_in=0,
                            tokens_out=len("".join(accumulated_text)) // 4,
                            latency_ms=int((time.perf_counter() - start_time) * 1000),
                            model=current_model,
                            finish_reason="stream_error",
                            cost_usd=0.0,
                        )

                    last_exc = exc
                    exc_str = str(exc)
                    is_rate_limit = any(x in exc_str for x in ("429", "RATE_LIMIT", "quota", "Too Many Requests"))
                    is_server_error = any(x in exc_str for x in ("500", "502", "503", "504", "INTERNAL", "Server Error"))
                    is_auth_error = any(x in exc_str for x in ("401", "403", "API_KEY_INVALID", "Unauthorized", "Authentication"))

                    if is_auth_error:
                        key_pool.mark_auth_error(active_key)
                        logger.warning("Auth error on %s key #%d. Cooling down 5m.", current_model, active_idx + 1)
                        continue

                    if is_rate_limit or is_server_error:
                        suggested_delay = key_pool.parse_retry_delay(exc_str)
                        cd_sec = key_pool.mark_rate_limited(active_key, suggested_delay)
                        logger.warning(
                            "%s key #%d rate-limited/error (retry in %.0fs). Next key...",
                            current_model, active_idx + 1, cd_sec,
                        )
                        if attempt < total_keys - 1:
                            continue
                        if model_idx < len(models_to_try) - 1:
                            break  # cascade to fallback model
                        break

                    key_pool.record_error(active_key)
                    logger.error("Non-retryable error on %s key #%d: %s", current_model, active_idx + 1, exc)
                    break

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("%s adapter failed after all keys and models: %s", self.provider_name, last_exc)
        err_content = f"[{self.provider_name.upper()}_ERROR: {last_exc!s}]"
        return ModelResponse(
            content=err_content,
            tool_calls=[],
            tokens_in=0,
            tokens_out=0,
            latency_ms=latency_ms,
            model=self.model_name,
            finish_reason="error",
            cost_usd=0.0,
        )
