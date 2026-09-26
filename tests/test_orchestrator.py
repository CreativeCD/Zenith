"""Unit tests for harness/orchestrator.py (Phase 4).

Validates the ReAct state machine (PRD §4.5.1), structured PLAN & DONE_CANDIDATE
output parsers (PRD §4.5.2), reflection prompt injection (PRD §5.3),
rollback checkpoints (PRD §4.5.4), and plan revision escalation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.adapters.base import ModelResponse
from harness.config import HarnessConfig
from harness.contracts import (
    AgentPhase,
    Complexity,
    IssuePlan,
    SuspectedFile,
    TaskType,
    ToolCall,
)
from harness.orchestrator import (
    Orchestrator,
    parse_done_candidate,
    parse_plan,
)


class ScriptedMockModelAdapter:
    """Mock adapter returning a scripted sequence of responses for state transition tests."""

    def __init__(self, responses: list[ModelResponse]):
        self.responses = list(responses)
        self.call_history: list[dict] = []

    async def complete(self, system_prompt: str, user_message: str, **kwargs):
        self.call_history.append({"system": system_prompt, "user": user_message})
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(
            content='{"status": "DONE_CANDIDATE", "confidence": 0.95, "evidence": ["All fixed"], "files_modified": ["src/app.py"]}',
            tokens_in=50,
            tokens_out=20,
            model="mock",
        )


def make_test_issue_plan() -> IssuePlan:
    return IssuePlan(
        issue_id="test-bug-1",
        primary_goal="Fix bug in service.py",
        task_type=TaskType.BUG_FIX,
        acceptance_criteria=["Function returns valid status"],
        suspected_files=[SuspectedFile(path="src/service.py", confidence=0.90, reason="Traceback")],
        reproduction_hint="pytest tests/test_service.py",
        test_filter="pytest tests/test_service.py",
        error_type="ValueError",
        complexity_estimate=Complexity.LOW,
        estimated_steps=12,
        requires_external_knowledge=False,
        language="python",
        test_runner="pytest",
        parsing_confidence=0.90,
        parsing_method="RULE_BASED",
    )


def test_plan_output_parser_valid_and_invalid(tmp_path):
    valid_json = json.dumps({
        "plan": [
            {"step": 1, "description": "Locate error in service.py", "tool_prediction": "read_file_range", "expected_outcome": "See line 40"},
            {"step": 2, "description": "Apply null guard patch", "tool_prediction": "apply_patch", "expected_outcome": "File modified"}
        ],
        "estimated_total_steps": 4,
        "risk_factors": ["May break backward compatibility"],
        "rollback_checkpoints": [1, 2],
    })

    plan = parse_plan(valid_json, output_dir=str(tmp_path))
    assert len(plan.steps) == 2
    assert plan.estimated_total_steps == 4
    assert plan.rollback_checkpoints == [1, 2]
    assert (tmp_path / "plan.md").exists()

    # Invalid JSON missing steps
    with pytest.raises(ValueError, match="Invalid plan structure"):
        parse_plan('{"invalid": true}', output_dir=str(tmp_path))


def test_done_candidate_output_parser():
    valid_candidate = json.dumps({
        "status": "DONE_CANDIDATE",
        "confidence": 0.95,
        "evidence": [
            "Fixed null pointer guard at line 40",
            "pytest tests/test_service.py passed with 0 failures"
        ],
        "files_modified": ["src/service.py"]
    })

    candidate = parse_done_candidate(valid_candidate)
    assert candidate.confidence == 0.95
    assert len(candidate.evidence) == 2
    assert "src/service.py" in candidate.files_modified

    # Missing evidence field must be rejected (PRD §4.5.2)
    invalid_candidate = json.dumps({
        "status": "DONE_CANDIDATE",
        "confidence": 0.90,
        "evidence": [],
        "files_modified": ["src/service.py"]
    })
    with pytest.raises(ValueError, match="Missing or empty 'evidence'"):
        parse_done_candidate(invalid_candidate)


def test_reflection_prompt_injection():
    config = HarnessConfig()
    orchestrator = Orchestrator(config=config, model_adapter=None)

    prompt = orchestrator.format_reflection_prompt(
        last_observation="Line 40: token_len = len(token.strip())",
        goal="Fix NoneType crash in AuthService",
        current_step="1. Read line 40",
    )

    assert "Line 40: token_len" in prompt
    assert "Fix NoneType crash in AuthService" in prompt
    assert "Reflect on:" in prompt


def test_rollback_checkpoint_capture(tmp_path):
    config = HarnessConfig()
    config.telemetry.output_dir = str(tmp_path)
    config.repo_path = str(tmp_path)

    orchestrator = Orchestrator(config=config, model_adapter=None)
    # Create sample diff content
    checkpoint_file = orchestrator.capture_checkpoint(step=2, diff_content="--- a/src/app.py\n+++ b/src/app.py\n")

    assert Path(checkpoint_file).exists()
    assert (tmp_path / "checkpoint_2.diff").exists()
    assert "--- a/src/app.py" in Path(checkpoint_file).read_text()


def test_orchestrator_state_transitions(tmp_path):
    # Setup minimal mock repo
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    app_py = src_dir / "app.py"
    app_py.write_text("def run():\n    return 42\n")

    # Scripted sequence of 2 turns:
    # Turn 1 (PLAN): emits structured plan
    # Turn 2 (ACT): emits tool call
    # Turn 3 (ACT): emits DONE_CANDIDATE
    plan_json = json.dumps({
        "plan": [{"step": 1, "description": "Check app", "tool_prediction": "read_file_range", "expected_outcome": "content"}],
        "estimated_total_steps": 2,
        "risk_factors": [],
        "rollback_checkpoints": [1],
    })
    done_json = json.dumps({
        "status": "DONE_CANDIDATE",
        "confidence": 0.95,
        "evidence": ["Read app.py successfully and verified logic"],
        "files_modified": []
    })

    scripted_responses = [
        ModelResponse(content=plan_json),
        ModelResponse(
            content="Reading file now",
            tool_calls=[ToolCall(tool="read_file_range", reasoning="Inspect app.py", args={"file_path": "src/app.py", "start_line": 1, "end_line": 10})],
        ),
        ModelResponse(content=done_json),
    ]

    adapter = ScriptedMockModelAdapter(scripted_responses)
    config = HarnessConfig()
    config.repo_path = str(tmp_path)
    config.telemetry.output_dir = str(tmp_path / ".harness")
    config.verification.run_syntax_check = False
    config.verification.run_lint_check = False
    config.verification.run_repro_test = False
    config.verification.run_full_regression = False
    config.verification.run_diff_audit = False
    config.verification.run_side_effect_check = False

    orchestrator = Orchestrator(config=config, model_adapter=adapter)
    issue_text = (
        "Fix typo in src/app.py\n\n"
        "Steps to reproduce:\n"
        "Run `pytest tests/test_app.py -k test_typo` to reproduce.\n"
    )

    session_result = orchestrator.run(issue_text=issue_text)

    assert session_result.status == AgentPhase.DONE
    assert session_result.total_steps >= 1
    assert session_result.exit_code == 0
