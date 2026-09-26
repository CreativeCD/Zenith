"""Comprehensive tests for full Telemetry Pipeline, schema validation, and real-time dashboard."""

import json

from harness.contracts import (
    AgentPhase,
    EventType,
    ResultStatus,
    TelemetryEvent,
)
from harness.telemetry import (
    TelemetryWriter,
    calculate_cost,
    validate_telemetry_schema,
)


def test_validate_telemetry_schema_success():
    event = TelemetryEvent(
        event_id="evt-1234",
        session_id="sess-001",
        step=1,
        phase=AgentPhase.PLAN,
        agent="orchestrator",
        event_type=EventType.PLAN_EMIT,
        tokens_in=500,
        tokens_out=100,
        result_status=ResultStatus.SUCCESS,
    )
    d = event.to_dict()
    assert validate_telemetry_schema(d) is True


def test_validate_telemetry_schema_missing_field():
    d = {"step": 1, "agent": "orchestrator"}
    assert validate_telemetry_schema(d) is False


def test_telemetry_all_18_event_types(tmp_path):
    writer = TelemetryWriter(output_dir=str(tmp_path), session_id="sess-test-18")

    all_event_types = [
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.LLM_TURN_START,
        EventType.LLM_TURN_END,
        EventType.VERIFICATION_PHASE,
        EventType.RECOVERY_EVENT,
        EventType.PLAN_REVISION,
        EventType.SUBAGENT_SPAWN,
        EventType.SUBAGENT_RESULT,
        EventType.SKILL_FETCH,
        EventType.CONTEXT_COMPRESSION,
        EventType.ROLLBACK,
        EventType.CHECKPOINT,
        EventType.DONE,
        EventType.FAILED,
        EventType.INIT,
        EventType.PLAN_EMIT,
        EventType.DONE_CANDIDATE,
        EventType.SESSION_START,
    ]

    for idx, etype in enumerate(all_event_types, start=1):
        writer.append(
            TelemetryEvent(
                step=idx,
                event_type=etype,
                phase=AgentPhase.ACT,
                tokens_in=100,
                tokens_out=50,
                tool="test_tool",
            )
        )

    log_path = tmp_path / "telemetry.jsonl"
    assert log_path.exists()

    with open(log_path, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == len(all_event_types)
    for record in lines:
        assert validate_telemetry_schema(record) is True
        assert record["session_id"] == "sess-test-18"


def test_telemetry_cumulative_token_and_cost_accounting(tmp_path):
    writer = TelemetryWriter(output_dir=str(tmp_path), model_name="gemini-2.5-flash")

    # 3 events with known tokens
    events = [
        (1000, 200),
        (500, 100),
        (2000, 300),
    ]

    expected_tokens = 0
    expected_cost = 0.0

    for idx, (tin, tout) in enumerate(events, start=1):
        step_cost = calculate_cost("gemini-2.5-flash", tin, tout)
        expected_tokens += (tin + tout)
        expected_cost += step_cost

        writer.append(
            TelemetryEvent(
                step=idx,
                event_type=EventType.LLM_TURN_END,
                phase=AgentPhase.ACT,
                tokens_in=tin,
                tokens_out=tout,
            )
        )

    assert writer.cumulative_tokens == expected_tokens
    assert round(writer.cumulative_cost_usd, 6) == round(expected_cost, 6)

    # Verify last record in file matches cumulative total
    log_path = tmp_path / "telemetry.jsonl"
    with open(log_path, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    last_record = records[-1]
    assert last_record["tokens_cumulative"] == expected_tokens
    assert round(last_record["cost_cumulative_usd"], 6) == round(expected_cost, 6)


def test_real_time_dashboard_formatting(tmp_path):
    writer = TelemetryWriter(output_dir=str(tmp_path), model_name="gemini-2.5-flash")
    event = TelemetryEvent(
        step=12,
        agent="coder",
        tool="apply_patch",
        tokens_in=4821,
        tokens_out=312,
        cost_usd=0.0008,
        context_tokens_used=6421,
        context_budget=32000,
        context_utilization_pct=20.1,
        result_status=ResultStatus.SUCCESS,
    )
    writer.append(event)
    dashboard_text = writer.render_dashboard(event)

    assert "[ZENITH] Step 12 | Agent: coder | Tool: apply_patch" in dashboard_text
    assert "Tokens: 4,821 in + 312 out = 5,133 this turn" in dashboard_text
    assert "Cost:   $0.0008 this turn" in dashboard_text
    assert "Context: 6,421 / 32,000 tokens (20.1% full)" in dashboard_text
    assert "Status: SUCCESS" in dashboard_text
    assert "Session total:" in dashboard_text
