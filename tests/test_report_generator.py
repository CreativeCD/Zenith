"""Unit tests for ReportGenerator ensuring all 8 required sections are produced."""

from harness.contracts import (
    AgentPhase,
    ErrorCode,
    EventType,
    ResultStatus,
    TelemetryEvent,
)
from harness.report_generator import ReportGenerator
from harness.telemetry import TelemetryWriter


def test_report_generator_all_8_sections(tmp_path):
    output_dir = tmp_path / ".harness"
    output_dir.mkdir()

    # Create telemetry writer and populate sample events
    writer = TelemetryWriter(output_dir=str(output_dir), model_name="gemini-2.5-flash")

    writer.append(
        TelemetryEvent(
            step=1,
            agent="scout",
            event_type=EventType.SUBAGENT_SPAWN,
            phase=AgentPhase.PLAN,
            reasoning="Spawned Scout to examine repository structure",
        )
    )
    writer.append(
        TelemetryEvent(
            step=2,
            agent="coder",
            tool="apply_patch",
            event_type=EventType.TOOL_CALL,
            phase=AgentPhase.ACT,
            reasoning="Apply fix to calculator divide method",
            tokens_in=1200,
            tokens_out=250,
        )
    )
    writer.append(
        TelemetryEvent(
            step=2,
            agent="coder",
            tool="apply_patch",
            event_type=EventType.TOOL_RESULT,
            phase=AgentPhase.OBSERVE,
            result_status=ResultStatus.SUCCESS,
            latency_ms=45,
        )
    )
    writer.append(
        TelemetryEvent(
            step=3,
            agent="orchestrator",
            event_type=EventType.RECOVERY_EVENT,
            phase=AgentPhase.REFLECT,
            error_code=ErrorCode.PATCH_FAILED,
            reasoning="Switched to block-replace mode and re-applied",
            result_status=ResultStatus.SUCCESS,
        )
    )
    writer.append(
        TelemetryEvent(
            step=4,
            agent="orchestrator",
            event_type=EventType.VERIFICATION_PHASE,
            phase=AgentPhase.OBSERVE,
            result_status=ResultStatus.SUCCESS,
            reasoning="Phase SYNTAX: 1 file checked",
        )
    )

    # Write a sample working memory summary
    (output_dir / "context_summary.md").write_text(
        "## Working Memory\n- Root cause: Missing ZeroDivisionError check.\n- Fix verified clean.",
        encoding="utf-8",
    )

    diff_sample = "--- a/calc.py\n+++ b/calc.py\n@@ -10,3 +10,6 @@\n+    if b == 0:\n+        raise ZeroDivisionError('Division by zero')"

    generator = ReportGenerator(
        output_dir=str(output_dir),
        repo_path=str(tmp_path),
        issue_id="ISSUE-101",
        primary_goal="Handle division by zero",
    )

    verification_data = {
        "phases": {
            "SYNTAX": {"status": "PASS", "detail": "All files clean"},
            "LINT": {"status": "PASS", "detail": "0 new violations"},
            "REPRO_TEST": {"status": "PASS", "detail": "test_zero_division passed"},
            "REGRESSION": {"status": "PASS", "detail": "15 passed, 0 failed"},
            "DIFF_AUDIT": {"status": "PASS", "detail": "1 file modified"},
            "SIDE_EFFECT": {"status": "PASS", "detail": "Clean import"},
        }
    }

    report_content = generator.generate(
        status="PASS",
        final_diff=diff_sample,
        verification_data=verification_data,
    )

    report_path = output_dir / "report.md"
    assert report_path.exists()

    # Check for all 8 mandatory sections
    assert "## 1. Executive Summary" in report_content
    assert "## 2. Step-by-Step Timeline" in report_content
    assert "## 3. Recovery Events" in report_content
    assert "## 4. Verification Results" in report_content
    assert "## 5. Final Diff Applied" in report_content
    assert "## 6. Agent Decisions Log" in report_content
    assert "## 7. Token & Cost Breakdown" in report_content
    assert "## 8. Lessons Learned" in report_content

    # Check Executive Summary contents
    assert "PASS" in report_content
    assert "Subagents Used" in report_content
    assert "Coder" in report_content or "Scout" in report_content

    # Check Diff
    assert "ZeroDivisionError" in report_content


def test_report_generator_crash_proof_on_fail_and_empty(tmp_path):
    output_dir = tmp_path / ".harness"
    output_dir.mkdir()

    # Empty telemetry, FAIL status (e.g. timeout or crashed run)
    generator = ReportGenerator(
        output_dir=str(output_dir),
        repo_path=str(tmp_path),
        issue_id="ISSUE-FAIL",
        primary_goal="Broken task",
    )

    report_content = generator.generate(
        status="FAIL",
        final_diff="",
        verification_data=None,
    )

    report_path = output_dir / "report.md"
    assert report_path.exists()

    assert "## 1. Executive Summary" in report_content
    assert "## 2. Step-by-Step Timeline" in report_content
    assert "## 3. Recovery Events" in report_content
    assert "## 4. Verification Results" in report_content
    assert "## 5. Final Diff Applied" in report_content
    assert "## 6. Agent Decisions Log" in report_content
    assert "## 7. Token & Cost Breakdown" in report_content
    assert "## 8. Lessons Learned" in report_content
    assert "FAIL" in report_content
