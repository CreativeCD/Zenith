"""harness/adapters/gemini_adapter.py — Google Gemini Model Adapter.

Reference: PRD.md §10 | architecture.md §16
Implements ModelAdapter using Gemini API with structured outputs and KV cache exploitation.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from harness.adapters.base import ModelResponse


class GeminiAdapter:
    """Adapter for Google Gemini models (gemini-2.5-flash, gemini-2.5-pro)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-flash",
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("AI_API_KEY")
        self.model_name = model_name
        self.base_url = base_url
        self._client = None

    def _ensure_client(self) -> None:
        """Lazily initialize Google GenAI client."""
        if not self.api_key:
            raise EnvironmentError(
                "AI_API_KEY not configured. Provide it in .env or pass api_key to GeminiAdapter."
            )
        # Client initialization will be active when SDK is invoked

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
        use_structured_output: bool = True,
        seed: Optional[int] = 42,
    ) -> ModelResponse:
        """Execute chat completion with Gemini."""
        self._ensure_client()
        start_time = time.perf_counter()

        # In Phase 0 / offline mode, return a structured stub response
        # Full live API integration executes in Phase 4 / Phase 6
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        return ModelResponse(
            content="[GeminiAdapter Stub Initialized]",
            tool_calls=[],
            tokens_in=len(system_prompt.split()) + len(user_message.split()),
            tokens_out=10,
            latency_ms=latency_ms,
            model=self.model_name,
            finish_reason="stop",
        )
