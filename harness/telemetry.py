"""harness/telemetry.py — Append-Only Structured Telemetry & Cost Engine.

Reference: PRD.md §4.9 | architecture.md §19
Emits 18 JSONL event types, tracks cumulative token consumption & costs, and powers the real-time CLI dashboard.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from harness.contracts import (
    AgentPhase,
    ErrorCode,
    EventType,
    ResultStatus,
    TelemetryEvent,
)

# Cost per 1M tokens (Prompt, Completion)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}


def calculate_cost(model_name: str, tokens_in: int, tokens_out: int) -> float:
    """Calculate cost in USD based on model pricing per 1M tokens."""
    # Find matching pricing
    pricing = MODEL_PRICING.get(model_name)
    if not pricing:
        for k, v in MODEL_PRICING.items():
            if k in model_name:
                pricing = v
                break
    if not pricing:
        pricing = {"input": 0.10, "output": 0.40}  # conservative fallback

    cost_in = (tokens_in / 1_000_000.0) * pricing["input"]
    cost_out = (tokens_out / 1_000_000.0) * pricing["output"]
    return cost_in + cost_out


class TelemetryWriter:
    """Append-only JSONL telemetry logger with real-time stats."""

    def __init__(
        self,
        output_dir: str = ".harness",
        session_id: str | None = None,
        model_name: str = "gemini-2.5-flash",
        stream_to_stdout: bool = False,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.output_dir / "telemetry.jsonl"
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.model_name = model_name
        self.stream_to_stdout = stream_to_stdout

        self.cumulative_tokens: int = 0
        self.cumulative_cost_usd: float = 0.0
        self.current_step: int = 0
        self.events_count: int = 0

    def append(self, event: TelemetryEvent) -> None:
        """Write a TelemetryEvent to the JSONL log file and update cumulative metrics."""
        if not event.event_id:
            event.event_id = str(uuid.uuid4())[:12]
        if not event.session_id:
            event.session_id = self.session_id
        if not event.timestamp:
            event.timestamp = datetime.now(timezone.utc)

        # Update step
        if event.step:
            self.current_step = max(self.current_step, event.step)
        else:
            event.step = self.current_step

        # Calculate step cost if tokens present and cost is 0
        if (event.tokens_in > 0 or event.tokens_out > 0) and event.cost_usd == 0.0:
            event.cost_usd = calculate_cost(
                self.model_name, event.tokens_in, event.tokens_out
            )

        # Update cumulative
        self.cumulative_tokens += (event.tokens_in + event.tokens_out)
        self.cumulative_cost_usd += event.cost_usd

        event.tokens_cumulative = self.cumulative_tokens
        event.cost_cumulative_usd = self.cumulative_cost_usd

        # Serialize
        record = event.to_dict()

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        self.events_count += 1

        if self.stream_to_stdout:
            self._print_stream(event)

    def _print_stream(self, event: TelemetryEvent) -> None:
        """Pretty-print event to stdout for real-time monitoring."""
        timestamp = event.timestamp.strftime("%H:%M:%S") if isinstance(event.timestamp, datetime) else str(event.timestamp)
        status_color = "✅" if event.result_status == ResultStatus.SUCCESS else "❌"
        tokens_info = f"{event.tokens_cumulative:,} tok (${event.cost_cumulative_usd:.4f})"
        
        if event.event_type == EventType.TOOL_CALL:
            print(f"[{timestamp}] [S{event.step}] 🔧 TOOL CALL: {event.tool} | {tokens_info}")
        elif event.event_type == EventType.TOOL_RESULT:
            status = "OK" if event.result_status == ResultStatus.SUCCESS else f"ERR:{event.error_code}"
            print(f"[{timestamp}] [S{event.step}] {status_color} TOOL RES : {event.tool} [{status}] ({event.latency_ms}ms)")
        elif event.event_type == EventType.VERIFICATION_PHASE:
            print(f"[{timestamp}] [S{event.step}] 🧪 VERIFY    : {event.phase} -> {event.result_status}")
        elif event.event_type == EventType.RECOVERY_EVENT:
            print(f"[{timestamp}] [S{event.step}] ⚠️ RECOVERY  : {event.error_code} (Loop:{event.loop_count})")
        else:
            print(f"[{timestamp}] [S{event.step}] ℹ️ {event.event_type.value} [{event.agent}] | {tokens_info}")

    def log_session_start(self, issue_id: str, repo_path: str) -> None:
        self.append(
            TelemetryEvent(
                event_type=EventType.SESSION_START,
                phase=AgentPhase.INIT,
                reasoning=f"Starting harness run for issue: {issue_id} in {repo_path}",
            )
        )

    def log_tool_call(self, step: int, tool_name: str, args_hash: str, reasoning: str) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.TOOL_CALL,
                phase=AgentPhase.ACT,
                tool=tool_name,
                tool_args_hash=args_hash,
                reasoning=reasoning,
            )
        )

    def log_tool_result(
        self,
        step: int,
        tool_name: str,
        status: ResultStatus,
        latency_ms: int,
        error_code: ErrorCode | None = None,
    ) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.TOOL_RESULT,
                phase=AgentPhase.OBSERVE,
                tool=tool_name,
                result_status=status,
                latency_ms=latency_ms,
                error_code=error_code,
            )
        )

    def log_llm_turn(
        self,
        step: int,
        phase: AgentPhase,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        context_tokens_used: int,
        budget: int = 32000,
    ) -> None:
        utilization = (context_tokens_used / budget * 100.0) if budget > 0 else 0.0
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.LLM_TURN_END,
                phase=phase,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                context_tokens_used=context_tokens_used,
                context_budget=budget,
                context_utilization_pct=utilization,
            )
        )
