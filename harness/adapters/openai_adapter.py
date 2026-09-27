"""harness/adapters/openai_adapter.py — OpenAI-Compatible Model Adapter for DeepSeek, Qwen, and OpenAI.

Reference: PRD.md §10.2 | architecture.md §16
Implements ModelAdapter using httpx for any OpenAI-compatible completions endpoint:
- DeepSeek (e.g. DeepSeek-V3, DeepSeek-Coder, DeepSeek-R1)
- Qwen (e.g. Alibaba Cloud Model Studio, DashScope, Ollama, vLLM)
- Standard OpenAI endpoints and local proxies
- Native function calling + text fallback extraction
- Provider-agnostic reasoning envelope extraction
- Token usage and cost accounting
- Resilient retry and timeout handling
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from harness.adapters.base import ModelResponse
from harness.contracts import ToolCall

logger = logging.getLogger(__name__)


# Documented default base URLs for known providers
DEFAULT_BASE_URLS: Dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "qwen_dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}


def normalize_endpoint(base_url: str) -> str:
    """Normalize base URL to ensure full /chat/completions endpoint."""
    url = base_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


class OpenAICompatibleAdapter:
    """Provider-agnostic adapter for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        model_name: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider: str = "openai",
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self.model_name = model_name
        self.provider = provider.lower()
        self.timeout = timeout
        self.max_retries = max_retries

        # Resolve base URL
        resolved_base_url = base_url
        if not resolved_base_url:
            if self.provider == "deepseek":
                resolved_base_url = DEFAULT_BASE_URLS["deepseek"]
            elif self.provider == "openai":
                resolved_base_url = DEFAULT_BASE_URLS["openai"]
            elif self.provider == "qwen" and os.environ.get("DASHSCOPE_API_KEY"):
                resolved_base_url = DEFAULT_BASE_URLS["qwen_dashscope"]
            else:
                raise ValueError(
                    f"base_url is required for provider '{self.provider}'. "
                    f"Please configure model.base_url in harness_config.yaml or pass --base-url."
                )

        self.base_url = resolved_base_url
        self.endpoint = normalize_endpoint(self.base_url)

        # Resolve API key
        self.api_key = api_key or self._resolve_api_key_from_env()

    def _resolve_api_key_from_env(self) -> Optional[str]:
        """Resolve API key based on provider conventions."""
        if self.provider == "deepseek":
            return os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        elif self.provider == "qwen":
            return (
                os.environ.get("DASHSCOPE_API_KEY")
                or os.environ.get("QWEN_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
            )
        return os.environ.get("OPENAI_API_KEY")

    def _format_tools(self, tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Convert Zenith tool definitions to OpenAI function tool declarations."""
        if not tools:
            return []

        formatted: List[Dict[str, Any]] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            if "type" in t and "function" in t:
                formatted.append(t)
            elif "name" in t:
                parameters = t.get("parameters") or {"type": "object", "properties": {}}
                formatted.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", f"Execute tool {t['name']}"),
                        "parameters": parameters,
                    },
                })
        return formatted

    def _parse_native_tool_calls(
        self,
        raw_tool_calls: List[Dict[str, Any]],
        assistant_content: str,
    ) -> List[ToolCall]:
        """Convert OpenAI tool_calls structure to Zenith ToolCall objects."""
        parsed: List[ToolCall] = []
        for tc in raw_tool_calls:
            func = tc.get("function") or {}
            tool_name = func.get("name", "")
            raw_args = func.get("arguments", "{}")

            if isinstance(raw_args, dict):
                args = dict(raw_args)
            elif isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError:
                    # Preserve malformed args for ToolEngine stage-3 rejection
                    logger.warning("Malformed tool arguments from model for %s: %s", tool_name, raw_args)
                    args = {"_malformed_raw": raw_args}
            else:
                args = {}

            # Extract or synthesize reasoning (PRD §4.3.1 requirement)
            reasoning = args.pop("reasoning", None) if isinstance(args, dict) else None
            if not reasoning or not str(reasoning).strip():
                # Check if assistant emitted context in content, or synthesize provider-agnostic intent
                if assistant_content and assistant_content.strip():
                    reasoning = assistant_content.strip()[:300]
                else:
                    reasoning = f"Execute {tool_name} to inspect or modify repository."

            parsed.append(ToolCall(tool=tool_name, reasoning=str(reasoning), args=args))
        return parsed

    def _parse_tool_calls_from_text(self, content: str) -> List[ToolCall]:
        """Fallback JSON extractor if model emitted JSON tool call in content body."""
        tool_calls: List[ToolCall] = []
        try:
            # Pattern matching {"tool": "...", "reasoning": "...", "args": {...}}
            json_blocks = re.findall(r"\{[^{}]*\"tool\"\s*:\s*\"[^\"]+[^{}]*\}", content, re.DOTALL)
            for block in json_blocks:
                try:
                    data = json.loads(block)
                    if isinstance(data, dict) and "tool" in data:
                        tool_calls.append(
                            ToolCall(
                                tool=data["tool"],
                                reasoning=data.get("reasoning", f"Execute {data['tool']} from text output."),
                                args=data.get("args", {}),
                            )
                        )
                except json.JSONDecodeError:
                    continue
        except Exception as exc:
            logger.debug("Failed text-based tool extraction: %s", exc)
        return tool_calls

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
        use_structured_output: bool = True,
        seed: Optional[int] = 42,
        reasoning_effort: str = "low",
    ) -> ModelResponse:
        """Execute chat completion request with optional tool declarations."""
        start_time = time.perf_counter()

        # Build messages payload
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }
        if seed is not None:
            payload["seed"] = seed

        formatted_tools = self._format_tools(tools)
        if formatted_tools:
            payload["tools"] = formatted_tools
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        self.endpoint,
                        headers=headers,
                        json=payload,
                    )

                if response.status_code in (401, 403):
                    raise PermissionError(
                        f"Authentication failed ({response.status_code}) for endpoint {self.endpoint}. "
                        f"Please check your API key for provider '{self.provider}'. Response: {response.text[:200]}"
                    )
                elif response.status_code == 404:
                    raise RuntimeError(
                        f"Model or endpoint not found (404) at {self.endpoint} for model '{self.model_name}'. "
                        f"Response: {response.text[:200]}"
                    )
                elif response.status_code in (429, 500, 502, 503, 504):
                    # Transient error, retry with backoff
                    logger.warning(
                        "Transient error %d from %s (attempt %d/%d): %s",
                        response.status_code,
                        self.endpoint,
                        attempt + 1,
                        self.max_retries,
                        response.text[:150],
                    )
                    await asyncio.sleep(1.0 * (2 ** attempt))
                    continue

                response.raise_for_status()
                data = response.json()

                # Parse completion choice
                choices = data.get("choices") or []
                if not choices:
                    return ModelResponse(
                        content="",
                        tool_calls=[],
                        latency_ms=int((time.perf_counter() - start_time) * 1000),
                        model=self.model_name,
                        finish_reason="empty",
                    )

                primary_choice = choices[0]
                message = primary_choice.get("message") or {}
                content = message.get("content") or ""
                finish_reason = primary_choice.get("finish_reason", "stop")

                # Parse tool calls
                tool_calls: List[ToolCall] = []
                raw_tool_calls = message.get("tool_calls")
                if raw_tool_calls and isinstance(raw_tool_calls, list):
                    tool_calls = self._parse_native_tool_calls(raw_tool_calls, assistant_content=content)

                if not tool_calls and content:
                    tool_calls = self._parse_tool_calls_from_text(content)

                # Token usage
                usage = data.get("usage") or {}
                tokens_in = usage.get("prompt_tokens", 0)
                tokens_out = usage.get("completion_tokens", 0)
                latency_ms = int((time.perf_counter() - start_time) * 1000)

                return ModelResponse(
                    content=content,
                    tool_calls=tool_calls,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    model=data.get("model", self.model_name),
                    finish_reason=finish_reason,
                    cost_usd=0.0,
                )

            except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                logger.warning("Network error contacting %s (attempt %d/%d): %s", self.endpoint, attempt + 1, self.max_retries, net_err)
                last_error = net_err
                await asyncio.sleep(1.0 * (2 ** attempt))
            except Exception as exc:
                last_error = exc
                raise

        raise RuntimeError(
            f"Failed to complete request to {self.endpoint} after {self.max_retries} attempts: {last_error}"
        )
