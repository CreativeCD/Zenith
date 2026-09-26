"""harness/adapters/base.py — Model Adapter Protocol and Response Contracts.

Reference: PRD.md §10.2 | architecture.md §16
Abstracts all LLM interactions behind a provider-agnostic interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from harness.contracts import ToolCall


@dataclass
class ModelResponse:
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    model: str = ""
    finish_reason: str = "stop"


@runtime_checkable
class ModelAdapter(Protocol):
    """Protocol that every model provider adapter must implement."""

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
        """Execute chat completion request with optional tool declarations."""
        ...
