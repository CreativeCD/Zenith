"""harness/adapters — Pluggable model adapters for Zenith."""

from harness.adapters.base import ModelAdapter, ModelResponse
from harness.adapters.gemini_adapter import GeminiAdapter
from harness.adapters.key_pool import KeyPoolManager, KeyStats
from harness.adapters.multi_provider import MultiProviderAdapter, discover_provider_keys
from harness.adapters.openai_compat_adapter import OpenAICompatAdapter

__all__ = [
    "GeminiAdapter",
    "KeyPoolManager",
    "KeyStats",
    "ModelAdapter",
    "ModelResponse",
    "MultiProviderAdapter",
    "OpenAICompatAdapter",
    "discover_provider_keys",
]
