"""Unit tests for harness/contracts.py."""

import json

from harness.contracts import (
    AgentPhase,
    Complexity,
    EventType,
    IssuePlan,
    ResultStatus,
    SuspectedFile,
    TaskType,
    TelemetryEvent,
    ToolResult,
)


def test_issue_plan_serialization():
    plan = IssuePlan(
        issue_id="issue_001",
        primary_goal="Fix zero division error",
        task_type=TaskType.BUG_FIX,
        acceptance_criteria=["Return 0 when dividing by zero"],
        suspected_files=[
            SuspectedFile(path="math.py", confidence=0.9, reason="Traceback matches")
        ],
        reproduction_hint="pytest tests/test_math.py",
        test_filter="test_div",
        error_type="ZeroDivisionError",
        complexity_estimate=Complexity.LOW,
        estimated_steps=4,
        requires_external_knowledge=False,
        language="python",
        test_runner="pytest",
        parsing_confidence=0.95,
        parsing_method="RULE_BASED",
    )

    data = plan.to_dict()
    assert data["issue_id"] == "issue_001"
    assert data["task_type"] == "BUG_FIX"
    assert data["complexity_estimate"] == "LOW"
    assert len(data["suspected_files"]) == 1

    json_str = plan.to_json()
    parsed = json.loads(json_str)
    assert parsed["issue_id"] == "issue_001"


def test_tool_result_serialization():
    res = ToolResult(
        tool="read_file",
        args_hash="abc12345",
        status=ResultStatus.SUCCESS,
        raw_output="def foo(): pass",
        truncated_output="def foo(): pass",
        tokens_in_raw=10,
        tokens_in_truncated=10,
        execution_time_ms=15,
    )
    data = res.to_dict()
    assert data["tool"] == "read_file"
    assert data["status"] == "SUCCESS"


def test_telemetry_event_serialization():
    event = TelemetryEvent(
        event_id="evt_01",
        session_id="sess_01",
        step=1,
        phase=AgentPhase.ACT,
        event_type=EventType.TOOL_CALL,
        tool="run_command",
        tokens_in=500,
        tokens_out=50,
        cost_usd=0.0001,
    )
    data = event.to_dict()
    assert data["event_id"] == "evt_01"
    assert data["phase"] == "ACT"
    assert data["event_type"] == "TOOL_CALL"
    assert "timestamp" in data
