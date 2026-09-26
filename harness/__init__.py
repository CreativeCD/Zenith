"""Zenith — SOTA Autonomous AI Coding Harness."""

from harness.context_manager import (
    ContextManager,
    ContextOverflowError,
    RollingSummarizer,
    TokenBudgetManager,
    TurnRecord,
    count_tokens,
    inject_recovery_prompt,
    inject_reflection_prompt,
    truncate_observation,
)

__version__ = "4.0.0"

__all__ = [
    "ContextManager",
    "ContextOverflowError",
    "RollingSummarizer",
    "TokenBudgetManager",
    "TurnRecord",
    "__version__",
    "count_tokens",
    "inject_recovery_prompt",
    "inject_reflection_prompt",
    "truncate_observation",
]
