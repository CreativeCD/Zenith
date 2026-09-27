"""harness/adapters/multi_provider.py — Multi-Provider Adapter with Auto Key Discovery.

Automatically discovers which API keys are present in the environment, builds
per-provider key pools, and routes requests to the active provider.

Supported providers and their environment variable conventions:
  ┌─────────────┬────────────────────────────────────────────────────────┐
  │ Provider    │ Environment Variables                                   │
  ├─────────────┼────────────────────────────────────────────────────────┤
  │ Gemini      │ AI_API_KEY, AI_API_KEY_1..N, GEMINI_API_KEY, GEMINI_KEY│
  │ DeepSeek    │ DEEPSEEK_API_KEY, DEEPSEEK_KEY, DEEPSEEK_API_KEY_1..N  │
  │ OpenAI      │ OPENAI_API_KEY, OPENAI_KEY, OPENAI_API_KEY_1..N        │
  └─────────────┴────────────────────────────────────────────────────────┘

Features:
  - Smart discovery: scans individual env vars, numbered suffixes (1..50),
    plural vars (e.g. DEEPSEEK_API_KEYS), and comma-delimited strings.
  - Multi-key pooling: whether 1, 3, or 8 keys are provided, ALL keys are
    loaded into the pool and rotated with fair round-robin and per-key cooldowns.
  - Automatic fallback: routes to whichever provider has valid credentials.
    If evaluation provides DeepSeek keys and no Gemini keys, DeepSeek is used.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from harness.adapters.base import ModelResponse
from harness.adapters.key_pool import KeyPoolManager
from harness.contracts import ToolCall

logger = logging.getLogger(__name__)

# Provider-specific environment variable patterns
_GEMINI_ENV_VARS = [
    "AI_API_KEY",
    "GEMINI_API_KEY",
    "GEMINI_KEY",
    "GOOGLE_API_KEY",
]

_DEEPSEEK_ENV_VARS = [
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_KEY",
]

_OPENAI_ENV_VARS = [
    "OPENAI_API_KEY",
    "OPENAI_KEY",
]


def _collect_keys(base_vars: list[str], numbered_prefix: str, max_n: int = 50) -> list[str]:
    """Collect all keys for a provider from env vars: base, plurals, numbered, and comma-separated."""
    raw: list[str] = []

    # 1. Base vars and plurals e.g. DEEPSEEK_API_KEY, DEEPSEEK_API_KEYS
    all_vars = list(base_vars)
    for v in base_vars:
        all_vars.append(f"{v}S")
        all_vars.append(f"{v}_LIST")

    for var in all_vars:
        v = os.environ.get(var, "").strip()
        if v:
            raw.append(v)

    # 2. Numbered variants e.g. DEEPSEEK_API_KEY_1 .. DEEPSEEK_API_KEY_50
    for i in range(1, max_n + 1):
        v = os.environ.get(f"{numbered_prefix}_{i}", "").strip()
        if v:
            raw.append(v)

    # 3. Dynamic scan across os.environ for any variable starting with prefix
    pfx_upper = numbered_prefix.upper() + "_"
    for k, v in os.environ.items():
        if k.upper().startswith(pfx_upper) and v.strip():
            raw.append(v.strip())

    # 4. Tokenize by comma, semicolon, newline, whitespace & deduplicate
    seen: set[str] = set()
    keys: list[str] = []
    for item in raw:
        if not item:
            continue
        tokens = re.split(r"[,;\n\r]+", item)
        for tok in tokens:
            cleaned = tok.strip().strip("'\"")
            if (
                cleaned
                and cleaned not in seen
                and not cleaned.startswith("REPLACE_WITH")
                and "your_" not in cleaned.lower()
            ):
                seen.add(cleaned)
                keys.append(cleaned)
    return keys


def discover_provider_keys() -> dict[str, list[str]]:
    """Return a dict of provider → list of valid API keys, in priority order."""
    gemini_keys = _collect_keys(_GEMINI_ENV_VARS, "AI_API_KEY")
    # Also collect GEMINI_API_KEY_1..N
    gemini_keys_extra = _collect_keys(["GEMINI_API_KEY"], "GEMINI_API_KEY")
    for k in gemini_keys_extra:
        if k not in gemini_keys:
            gemini_keys.append(k)

    deepseek_keys = _collect_keys(_DEEPSEEK_ENV_VARS, "DEEPSEEK_API_KEY")
    openai_keys = _collect_keys(_OPENAI_ENV_VARS, "OPENAI_API_KEY")

    logger.info(
        "Multi-provider key discovery: Gemini=%d, DeepSeek=%d, OpenAI=%d",
        len(gemini_keys), len(deepseek_keys), len(openai_keys),
    )
    return {
        "gemini": gemini_keys,
        "deepseek": deepseek_keys,
        "openai": openai_keys,
    }


class MultiProviderAdapter:
    """Routes LLM requests through the active provider with automatic failover.

    If evaluation provides DeepSeek keys (e.g. DEEPSEEK_API_KEY, DEEPSEEK_API_KEY_1..8)
    and no Gemini keys, DeepSeek is automatically selected.
    If Gemini keys exist, Gemini is used with fallback to DeepSeek.
    Within each provider, all available keys are pooled and rotated with fair round-robin.
    """

    def __init__(
        self,
        model_name: str | None = None,
        gemini_keys: list[str] | None = None,
        deepseek_keys: list[str] | None = None,
        openai_keys: list[str] | None = None,
        auto_discover: bool = True,
    ) -> None:
        if auto_discover:
            discovered = discover_provider_keys()
            g_keys = gemini_keys if gemini_keys is not None else discovered["gemini"]
            d_keys = deepseek_keys if deepseek_keys is not None else discovered["deepseek"]
            o_keys = openai_keys if openai_keys is not None else discovered["openai"]
        else:
            g_keys = gemini_keys or []
            d_keys = deepseek_keys or []
            o_keys = openai_keys or []

        # Provider preference: check env var or requested model name
        preferred_provider = (
            os.environ.get("PROVIDER")
            or os.environ.get("MODEL_PROVIDER")
            or os.environ.get("LLM_PROVIDER")
            or ""
        ).lower()

        if model_name:
            m_lower = model_name.lower()
            if "deepseek" in m_lower:
                preferred_provider = "deepseek"
            elif "gpt" in m_lower or "openai" in m_lower:
                preferred_provider = "openai"
            elif "gemini" in m_lower:
                preferred_provider = "gemini"

        self._adapters: list[tuple[str, Any]] = []
        self.total_cached_tokens = 0

        # Build DeepSeek adapter if keys available
        ds_adapter = None
        if d_keys:
            from harness.adapters.openai_compat_adapter import OpenAICompatAdapter
            ds_pool = KeyPoolManager(keys=d_keys)
            ds_model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
            ds_base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
            ds_adapter = OpenAICompatAdapter(
                key_pool=ds_pool,
                model_name=ds_model,
                fallback_chain=["deepseek-reasoner", "deepseek-chat"],
                base_url=ds_base_url,
                provider_name="DeepSeek",
            )

        # Build Gemini adapter if keys available
        gemini_adapter = None
        if g_keys:
            from harness.adapters.gemini_adapter import GeminiAdapter
            gemini_pool = KeyPoolManager(keys=g_keys)
            g_model = model_name if (model_name and "gemini" in model_name) else "gemini-3.5-flash-lite"
            gemini_adapter = GeminiAdapter(
                key_pool=gemini_pool,
                model_name=g_model,
                # gemini-2.5-flash returns 404 for new API users — never put it
                # in a fallback chain.
                fallback_chain=["gemini-3.5-flash", "gemini-3.6-flash"],
            )

        # Build OpenAI adapter if keys available
        oai_adapter = None
        if o_keys:
            from harness.adapters.openai_compat_adapter import OpenAICompatAdapter
            oai_pool = KeyPoolManager(keys=o_keys)
            oai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            oai_base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            oai_adapter = OpenAICompatAdapter(
                key_pool=oai_pool,
                model_name=oai_model,
                fallback_chain=["gpt-4o", "gpt-4.1-mini"],
                base_url=oai_base_url,
                provider_name="OpenAI",
            )

        # Order adapters based on user preference or key availability:
        # If DeepSeek is preferred OR (only DeepSeek has keys), place DeepSeek first
        if preferred_provider == "deepseek" and ds_adapter:
            self._adapters.append(("DeepSeek", ds_adapter))
            if gemini_adapter:
                self._adapters.append(("Gemini", gemini_adapter))
            if oai_adapter:
                self._adapters.append(("OpenAI", oai_adapter))
        elif preferred_provider == "openai" and oai_adapter:
            self._adapters.append(("OpenAI", oai_adapter))
            if gemini_adapter:
                self._adapters.append(("Gemini", gemini_adapter))
            if ds_adapter:
                self._adapters.append(("DeepSeek", ds_adapter))
        elif gemini_adapter:
            # Gemini first, DeepSeek second, OpenAI third
            self._adapters.append(("Gemini", gemini_adapter))
            if ds_adapter:
                self._adapters.append(("DeepSeek", ds_adapter))
            if oai_adapter:
                self._adapters.append(("OpenAI", oai_adapter))
        elif ds_adapter:
            # DeepSeek first when no Gemini keys
            self._adapters.append(("DeepSeek", ds_adapter))
            if oai_adapter:
                self._adapters.append(("OpenAI", oai_adapter))
        elif oai_adapter:
            # OpenAI first
            self._adapters.append(("OpenAI", oai_adapter))

        # Default pool points to the primary adapter's pool
        if self._adapters:
            self.key_pool = self._adapters[0][1].key_pool
            self.model_name = getattr(self._adapters[0][1], "model_name", "unknown")
            logger.info("MultiProviderAdapter initialized with primary: %s", self.provider_summary)
        else:
            self.key_pool = KeyPoolManager(keys=[])
            self.model_name = model_name or "gemini-3.5-flash-lite"
            logger.warning(
                "MultiProviderAdapter: No API keys found for any provider. "
                "Set AI_API_KEY (Gemini), DEEPSEEK_API_KEY (DeepSeek), or OPENAI_API_KEY (OpenAI)."
            )

    @property
    def active_provider(self) -> str:
        """Name of the primary provider currently handling requests."""
        return self._adapters[0][0] if self._adapters else "None"

    @property
    def total_keys(self) -> int:
        """Total keys available in the active provider's pool."""
        return self.key_pool.total_keys if self.key_pool else 0

    @property
    def all_total_keys(self) -> int:
        """Total keys available across all configured providers."""
        return sum(adapter.key_pool.total_keys for _, adapter in self._adapters)

    @property
    def provider_summary(self) -> str:
        """Human-readable summary of registered providers and their key counts."""
        if not self._adapters:
            return "No providers configured"
        parts = [
            f"{name} ({adapter.key_pool.total_keys} key{'s' if adapter.key_pool.total_keys != 1 else ''})"
            for name, adapter in self._adapters
        ]
        return " | ".join(parts)

    def _parse_tool_calls_from_text(self, content: str) -> list[ToolCall]:
        """Extract tool calls from text, delegating to active adapter or Gemini parser."""
        if self._adapters:
            active_adapter = self._adapters[0][1]
            if hasattr(active_adapter, "_parse_tool_calls_from_text"):
                return active_adapter._parse_tool_calls_from_text(content)
        from harness.adapters.gemini_adapter import GeminiAdapter
        return GeminiAdapter._parse_tool_calls_from_text(content)

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
        """Execute chat completion, cascading to next provider if errors occur."""
        last_response: ModelResponse | None = None

        for provider_name, adapter in self._adapters:
            if adapter.key_pool.total_keys == 0:
                continue

            try:
                response = await adapter.complete(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    use_structured_output=use_structured_output,
                    seed=seed,
                    max_retries=max_retries,
                    reasoning_effort=reasoning_effort,
                    history=history,
                    **kwargs,
                )
                self.total_cached_tokens += getattr(adapter, "total_cached_tokens", 0)

                # Check for provider failure marker
                if response.finish_reason == "error" or (
                    response.content and f"[{provider_name.upper()}_ERROR" in response.content
                ):
                    logger.warning(
                        "Provider '%s' returned error (%s). Trying next provider...",
                        provider_name, response.content[:100],
                    )
                    last_response = response
                    continue

                return response

            except Exception as exc:
                logger.warning("Provider '%s' raised exception: %s. Trying next...", provider_name, exc)
                last_response = ModelResponse(
                    content=f"[{provider_name.upper()}_ERROR: {exc!s}]",
                    tool_calls=[],
                    tokens_in=0,
                    tokens_out=0,
                    finish_reason="error",
                )
                continue

        if last_response:
            return last_response

        return ModelResponse(
            content="[MULTI_PROVIDER_ERROR: No API keys configured. Set AI_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY.]",
            tool_calls=[],
            tokens_in=0,
            tokens_out=0,
            finish_reason="error",
        )
