"""harness/adapters/factory.py — Model Adapter Factory for Zenith.

Reference: PRD.md §10.2 | architecture.md §16
Selects and configures the appropriate ModelAdapter instance based on provider metadata:
- 'gemini'   -> GeminiAdapter
- 'deepseek' -> OpenAICompatibleAdapter (provider='deepseek')
- 'qwen'     -> OpenAICompatibleAdapter (provider='qwen')
- 'openai'   -> OpenAICompatibleAdapter (provider='openai')
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from harness.adapters.base import ModelAdapter
from harness.adapters.gemini_adapter import GeminiAdapter
from harness.adapters.openai_adapter import OpenAICompatibleAdapter

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("gemini", "openai", "deepseek", "qwen")


def get_model_adapter(
    config: Any = None,
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_key_env: Optional[str] = None,
    timeout: float = 60.0,
    max_retries: int = 3,
) -> ModelAdapter:
    """Factory function to instantiate the configured ModelAdapter.

    Args:
        config: ModelConfig or HarnessConfig instance (optional).
        provider: Provider identifier ('gemini', 'openai', 'deepseek', 'qwen').
        model_name: Model ID string.
        base_url: Custom API endpoint.
        api_key: Direct API key (optional).
        api_key_env: Environment variable name holding the API key.
        timeout: Request timeout in seconds.
        max_retries: Transient error retry attempts.

    Returns:
        Configured ModelAdapter instance adhering to Zenith's protocol.
    """
    # Extract settings from config object if supplied
    model_cfg = getattr(config, "model", config) if config is not None else None

    resolved_provider = (
        provider
        or (getattr(model_cfg, "provider", None) if model_cfg else None)
        or ""
    ).strip().lower()

    resolved_model = (
        model_name
        or (getattr(model_cfg, "name", None) if model_cfg else None)
        or "gemini-2.5-flash"
    )

    resolved_base_url = (
        base_url
        or (getattr(model_cfg, "base_url", None) if model_cfg else None)
    )

    resolved_api_key_env = (
        api_key_env
        or (getattr(model_cfg, "api_key_env", None) if model_cfg else None)
    )

    resolved_api_key = api_key or (getattr(model_cfg, "api_key", None) if model_cfg else None)
    if not resolved_api_key and resolved_api_key_env:
        resolved_api_key = os.environ.get(resolved_api_key_env)

    # Infer provider if not explicitly given
    if not resolved_provider:
        lower_name = resolved_model.lower()
        if "deepseek" in lower_name:
            resolved_provider = "deepseek"
        elif "qwen" in lower_name:
            resolved_provider = "qwen"
        elif resolved_base_url and "deepseek" in resolved_base_url.lower():
            resolved_provider = "deepseek"
        elif resolved_base_url and "dashscope" in resolved_base_url.lower():
            resolved_provider = "qwen"
        elif resolved_base_url:
            resolved_provider = "openai"
        elif lower_name.startswith("gemini"):
            resolved_provider = "gemini"
        else:
            resolved_provider = "gemini"

    # Route to provider adapter
    if resolved_provider == "gemini":
        api_keys = getattr(model_cfg, "api_keys", []) if model_cfg else []
        fallback_chain = getattr(model_cfg, "fallback_chain", None) if model_cfg else None
        max_continuations = getattr(model_cfg, "max_continuations", 3) if model_cfg else 3
        return GeminiAdapter(
            api_key=resolved_api_key,
            api_keys=api_keys,
            model_name=resolved_model,
            fallback_chain=fallback_chain,
            base_url=resolved_base_url,
            max_continuations=max_continuations,
        )

    elif resolved_provider in ("openai", "deepseek", "qwen"):
        return OpenAICompatibleAdapter(
            model_name=resolved_model,
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            provider=resolved_provider,
            timeout=timeout,
            max_retries=max_retries,
        )

    else:
        raise ValueError(
            f"Unsupported model provider: '{resolved_provider}'. "
            f"Supported providers are: {', '.join(SUPPORTED_PROVIDERS)}."
        )
