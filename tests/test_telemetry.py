"""Unit tests for harness/telemetry.py."""

import json
from harness.contracts import AgentPhase, EventType, TelemetryEvent
from harness.telemetry import TelemetryWriter, calculate_cost


def test_calculate_cost():
    # Gemini 2.5 Flash: $0.075 / 1M prompt, $0.30 / 1M completion
    cost = calculate_cost("gemini-2.5-flash", 1_000_000, 1_000_000)
    assert round(cost, 4) == 0.375


def test_telemetry_writer_append(tmp_path):
    writer = TelemetryWriter(output_dir=str(tmp_path), model_name="gemini-2.5-flash")
    
    event1 = TelemetryEvent(
        step=1,
        event_type=EventType.TOOL_CALL,
        phase=AgentPhase.ACT,
        tool="grep_search",
        tokens_in=1000,
        tokens_out=100,
    )
    writer.append(event1)

    log_file = tmp_path / "telemetry.jsonl"
    assert log_file.exists()

    with open(log_file, "r") as f:
        lines = f.readlines()
    assert len(lines) == 1

    parsed = json.loads(lines[0])
    assert parsed["step"] == 1
    assert parsed["tokens_cumulative"] == 1100
    assert parsed["cost_cumulative_usd"] > 0.0
