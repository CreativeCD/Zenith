"""harness/telemetry.py — Append-Only Structured Telemetry & Cost Engine.

Reference: PRD.md §4.9 | architecture.md §19
Emits 18 JSONL event types, tracks cumulative token consumption & costs, and powers the real-time CLI dashboard.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from harness.contracts import (
    AgentPhase,
    ErrorCode,
    EventType,
    ResultStatus,
    TelemetryEvent,
)

logger = logging.getLogger(__name__)

# Cost per 1M tokens (Prompt, Completion)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}

MANDATORY_EVENT_FIELDS: List[str] = [
    "schema_version",
    "event_id",
    "session_id",
    "timestamp",
    "step",
    "phase",
    "agent",
    "event_type",
    "tokens_in",
    "tokens_out",
    "tokens_cumulative",
    "cost_usd",
    "cost_cumulative_usd",
    "latency_ms",
    "result_status",
]


def calculate_cost(model_name: str, tokens_in: int, tokens_out: int) -> float:
    """Calculate cost in USD based on model pricing per 1M tokens."""
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


def validate_telemetry_schema(record: dict[str, Any]) -> bool:
    """Validate that a serialized telemetry event conforms to the PRD §4.9.1 schema."""
    for field_name in MANDATORY_EVENT_FIELDS:
        if field_name not in record:
            return False
    return True


class TelemetryWriter:
    """Append-only JSONL telemetry logger with real-time stats and PRD §4.9 dashboard."""

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
        self.session_id = session_id or f"sess-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
        self.model_name = model_name
        self.stream_to_stdout = stream_to_stdout
        self.start_time = time.time()

        self.cumulative_tokens: int = 0
        self.cumulative_cost_usd: float = 0.0
        self.current_step: int = 0
        self.events_count: int = 0
        self.listeners: list[Any] = []

    def add_listener(self, listener: Any) -> None:
        """Register a callback for real-time telemetry events."""
        if listener not in self.listeners:
            self.listeners.append(listener)

    def remove_listener(self, listener: Any) -> None:
        """Unregister a telemetry event callback."""
        if listener in self.listeners:
            self.listeners.remove(listener)

    def append(self, event: TelemetryEvent) -> None:
        """Write a TelemetryEvent to the JSONL log file and update cumulative metrics."""
        if not event.event_id:
            event.event_id = f"evt-{uuid.uuid4().hex[:8]}"
        if not event.session_id:
            event.session_id = self.session_id
        if not event.timestamp:
            event.timestamp = datetime.now(timezone.utc)

        # Update step tracking
        if event.step:
            self.current_step = max(self.current_step, event.step)
        else:
            event.step = self.current_step

        # Calculate step cost if tokens are non-zero and cost was not explicitly provided
        if (event.tokens_in > 0 or event.tokens_out > 0) and event.cost_usd == 0.0:
            event.cost_usd = calculate_cost(
                self.model_name, event.tokens_in, event.tokens_out
            )

        # Update cumulative counters
        self.cumulative_tokens += (event.tokens_in + event.tokens_out)
        self.cumulative_cost_usd += event.cost_usd

        event.tokens_cumulative = self.cumulative_tokens
        event.cost_cumulative_usd = self.cumulative_cost_usd

        # Serialize
        record = event.to_dict()

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        self.events_count += 1

        # Notify active streaming listeners
        for listener in list(self.listeners):
            try:
                listener(record)
            except Exception:
                pass

        if self.stream_to_stdout:
            self._print_stream(event)

    # Convenience alias for append
    record = append

    def render_dashboard(self, event: TelemetryEvent | None = None) -> str:
        """Render real-time cost dashboard matching PRD §4.9.2 specification."""
        elapsed_sec = int(time.time() - self.start_time)
        mins, secs = divmod(elapsed_sec, 60)
        elapsed_str = f"{mins}m {secs}s"

        step = event.step if event else self.current_step
        agent = event.agent if event else "orchestrator"
        tool = (event.tool or event.event_type.value) if event else "orchestrator"
        tokens_in = event.tokens_in if event else 0
        tokens_out = event.tokens_out if event else 0
        turn_tokens = tokens_in + tokens_out
        turn_cost = event.cost_usd if event else 0.0
        used_ctx = event.context_tokens_used if event else 0
        budget_ctx = event.context_budget if event else 32000
        pct_ctx = event.context_utilization_pct if event else 0.0
        status = (
            event.result_status.value
            if (event and isinstance(event.result_status, ResultStatus))
            else (event.result_status if event else "SUCCESS")
        )

        lines = [
            f"[ZENITH] Step {step} | Agent: {agent} | Tool: {tool}",
            f"  Tokens: {tokens_in:,} in + {tokens_out:,} out = {turn_tokens:,} this turn",
            f"  Cost:   ${turn_cost:.4f} this turn | ${self.cumulative_cost_usd:.4f} cumulative",
            f"  Context: {used_ctx:,} / {budget_ctx:,} tokens ({pct_ctx:.1f}% full)",
            f"  Status: {status}",
            "  ─────────────────────────────────────────────",
            f"  [ZENITH] Session total: {self.cumulative_tokens:,} tokens | ${self.cumulative_cost_usd:.4f} | {elapsed_str} elapsed",
        ]
        return "\n".join(lines)

    def _print_stream(self, event: TelemetryEvent) -> None:
        """Pretty-print event to stdout for real-time monitoring."""
        timestamp = (
            event.timestamp.strftime("%H:%M:%S")
            if isinstance(event.timestamp, datetime)
            else str(event.timestamp)
        )
        status_color = "✅" if event.result_status == ResultStatus.SUCCESS else "❌"
        tokens_info = f"{event.tokens_cumulative:,} tok (${event.cost_cumulative_usd:.4f})"

        if event.event_type in (EventType.LLM_TURN_END, EventType.TOOL_RESULT):
            print(self.render_dashboard(event))
        elif event.event_type == EventType.TOOL_CALL:
            print(f"[{timestamp}] [S{event.step}] 🔧 TOOL CALL: {event.tool} | {tokens_info}")
        elif event.event_type == EventType.VERIFICATION_PHASE:
            print(f"[{timestamp}] [S{event.step}] {status_color} VERIFY    : {event.phase} -> {event.result_status}")
        elif event.event_type == EventType.RECOVERY_EVENT:
            print(f"[{timestamp}] [S{event.step}] ⚠️ RECOVERY  : {event.error_code} (Loop:{event.loop_count})")
        else:
            print(f"[{timestamp}] [S{event.step}] ℹ️ {event.event_type.value} [{event.agent}] | {tokens_info}")

    def log_event(
        self,
        event_type: EventType,
        step: int = 0,
        phase: AgentPhase = AgentPhase.INIT,
        agent: str = "orchestrator",
        reasoning: str | None = None,
        error_code: ErrorCode | None = None,
        **kwargs: Any,
    ) -> None:
        """Convenience method to log any TelemetryEvent with defaults."""
        self.append(
            TelemetryEvent(
                step=step,
                event_type=event_type,
                phase=phase,
                agent=agent,
                reasoning=reasoning,
                error_code=error_code,
                **kwargs,
            )
        )

    def log_session_start(self, issue_id: str, repo_path: str) -> None:
        self.append(
            TelemetryEvent(
                event_type=EventType.SESSION_START,
                phase=AgentPhase.INIT,
                reasoning=f"Starting harness run for issue: {issue_id} in {repo_path}",
            )
        )

    def log_tool_call(
        self,
        step: int,
        tool_name: str,
        args_hash: str,
        reasoning: str,
        tool_args: dict[str, Any] | None = None,
    ) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.TOOL_CALL,
                phase=AgentPhase.ACT,
                tool=tool_name,
                tool_args_hash=args_hash,
                tool_args=tool_args,
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
        tokens_in: int = 0,
        tokens_out: int = 0,
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
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )

    def log_llm_turn_start(self, step: int, phase: AgentPhase, agent: str = "orchestrator") -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.LLM_TURN_START,
                phase=phase,
                agent=agent,
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
        agent: str = "orchestrator",
    ) -> None:
        utilization = (context_tokens_used / budget * 100.0) if budget > 0 else 0.0
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.LLM_TURN_END,
                phase=phase,
                agent=agent,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                context_tokens_used=context_tokens_used,
                context_budget=budget,
                context_utilization_pct=utilization,
            )
        )

    def log_verification_phase(
        self,
        step: int,
        phase: str,
        status: ResultStatus,
        detail: str,
        duration_ms: int,
    ) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.VERIFICATION_PHASE,
                phase=AgentPhase.OBSERVE,
                result_status=status,
                reasoning=f"Phase {phase}: {detail}",
                latency_ms=duration_ms,
            )
        )

    def log_recovery_event(
        self,
        step: int,
        error_code: ErrorCode,
        action: str,
        loop_count: int = 0,
        revision_count: int = 0,
    ) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.RECOVERY_EVENT,
                phase=AgentPhase.REFLECT,
                error_code=error_code,
                reasoning=action,
                recovery_triggered=True,
                loop_count=loop_count,
                revision_count=revision_count,
            )
        )

    def log_plan_revision(self, step: int, reason: str, revision_count: int) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.PLAN_REVISION,
                phase=AgentPhase.PLAN,
                reasoning=reason,
                revision_count=revision_count,
            )
        )

    def log_subagent_spawn(self, step: int, role: str, budget: int) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.SUBAGENT_SPAWN,
                phase=AgentPhase.ACT,
                agent=role,
                context_budget=budget,
                reasoning=f"Spawned subagent {role} with budget {budget} tokens",
            )
        )

    def log_subagent_result(self, step: int, role: str, status: ResultStatus, latency_ms: int) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.SUBAGENT_RESULT,
                phase=AgentPhase.OBSERVE,
                agent=role,
                result_status=status,
                latency_ms=latency_ms,
            )
        )

    def log_done(self, step: int, confidence: float, files_modified: Optional[List[str]] = None) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.DONE,
                phase=AgentPhase.DONE,
                reasoning=f"Done confidence: {confidence:.2f}; files modified: {files_modified or []}",
                result_status=ResultStatus.SUCCESS,
            )
        )

    def log_failed(self, step: int, error_code: ErrorCode, reason: str) -> None:
        self.append(
            TelemetryEvent(
                step=step,
                event_type=EventType.FAILED,
                phase=AgentPhase.FAILED,
                error_code=error_code,
                reasoning=reason,
                result_status=ResultStatus.FAIL,
            )
        )
