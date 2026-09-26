"""Phase 4 End-to-End Integration Test: Full Autonomous Coding Loop.

Reference: PRD §11.3 | phases.md Task 4.24
Validates:
- Issue Parsing (L1) -> IssuePlan
- Repo Intelligence (L2) -> file tree & symbols
- Orchestrator (L5) -> PLAN -> ACT -> OBSERVE -> REFLECT -> DONE_CANDIDATE -> DONE
- VerificationGate (L7) -> All phases PASS
- Telemetry (L9) -> Event stream recorded
"""

from __future__ import annotations

import json

from harness.adapters.base import ModelResponse
from harness.config import HarnessConfig
from harness.contracts import AgentPhase, ResultStatus, ToolCall
from harness.orchestrator import Orchestrator


class MockE2EAdapter:
    def __init__(self, responses: list[ModelResponse]):
        self.responses = list(responses)

    async def complete(self, system_prompt: str, user_message: str, **kwargs):
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(
            content='{"status": "DONE_CANDIDATE", "confidence": 0.99, "evidence": ["Bug resolved and verified"], "files_modified": ["src/calculator.py"]}',
            tokens_in=50,
            tokens_out=25,
            model="mock-e2e",
        )


def test_p4_full_autonomous_loop(tmp_path):
    # 1. Setup mock repository structure
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True)

    src_dir = repo_dir / "src"
    src_dir.mkdir()
    calc_py = src_dir / "calculator.py"
    calc_py.write_text(
        "def divide(a: float, b: float) -> float:\n"
        "    return a / b\n"
    )

    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    test_calc_py = tests_dir / "test_calculator.py"
    test_calc_py.write_text(
        "from src.calculator import divide\n\n"
        "def test_divide_valid():\n"
        "    assert divide(10, 2) == 5\n\n"
        "def test_divide_by_zero():\n"
        "    assert divide(10, 0) == 0.0\n"
    )

    # 2. Issue description
    issue_text = (
        "Title: Fix ZeroDivisionError in divide() method\n\n"
        "Traceback:\n"
        '  File "src/math_ops.py", line 15, in compute\n'
        '  File "src/calculator.py", line 2, in divide\n'
        "    return a / b\n"
        "ZeroDivisionError: division by zero\n\n"
        "Steps to reproduce:\n"
        "Run `pytest tests/test_calculator.py -k test_divide_by_zero`\n"
    )

    # Fixed code patch
    fixed_code = (
        "def divide(a: float, b: float) -> float:\n"
        "    if b == 0:\n"
        "        return 0.0\n"
        "    return a / b\n"
    )

    # 3. Scripted Model Responses
    plan_json = json.dumps({
        "plan": [
            {"step": 1, "description": "Inspect calculator.py", "tool_prediction": "read_file_range", "expected_outcome": "Locate divide()"},
            {"step": 2, "description": "Apply fix to handle b == 0", "tool_prediction": "write_file", "expected_outcome": "Patch applied"},
        ],
        "estimated_total_steps": 3,
        "risk_factors": ["None"],
        "rollback_checkpoints": [1],
    })

    tool_call_resp = ModelResponse(
        content="Writing patch to calculator.py",
        tool_calls=[
            ToolCall(
                tool="apply_patch",
                reasoning="Fix zero division by returning 0.0 when b == 0",
                args={
                    "target_file": "src/calculator.py",
                    "old_snippet": "def divide(a: float, b: float) -> float:\n    return a / b\n",
                    "new_snippet": fixed_code,
                },
            )
        ],
    )

    done_candidate_resp = ModelResponse(
        content=json.dumps({
            "status": "DONE_CANDIDATE",
            "confidence": 0.99,
            "evidence": [
                "Handled b == 0 in src/calculator.py",
                "pytest tests/test_calculator.py -k test_divide_by_zero passed cleanly",
            ],
            "files_modified": ["src/calculator.py"],
        })
    )

    scout_resp = ModelResponse(
        content=(
            "## Relevant Files\n- src/calculator.py\n\n"
            "## Key Symbols & Call Paths\n- divide(a, b)\n\n"
            "## Dependency Chain\n- None\n\n"
            "## Suspected Root Cause Location\n- Line 2: division by zero when b == 0\n\n"
            "## Recommended Fix Strategy\n- Add guard check for b == 0"
        )
    )

    scripted_adapter = MockE2EAdapter([
        scout_resp,
        ModelResponse(content=plan_json),
        tool_call_resp,
        done_candidate_resp,
    ])

    # 4. Configure Harness
    config = HarnessConfig()
    config.repo_path = str(repo_dir)
    config.telemetry.output_dir = str(repo_dir / ".harness")
    # Only run repro test and syntax check for this isolated unit repo
    config.verification.run_syntax_check = True
    config.verification.run_lint_check = False
    config.verification.run_repro_test = True
    config.verification.run_full_regression = False
    config.verification.run_diff_audit = False
    config.verification.run_side_effect_check = False

    orchestrator = Orchestrator(config=config, model_adapter=scripted_adapter)

    # 5. Execute Run
    session_result = orchestrator.run(issue_text=issue_text)

    # 6. Verify Results
    assert session_result.status == AgentPhase.DONE
    assert session_result.exit_code == 0
    assert session_result.total_steps >= 2
    assert session_result.verification_result is not None
    assert session_result.verification_result.status == ResultStatus.SUCCESS

    # Verify artifacts created
    harness_dir = repo_dir / ".harness"
    assert (harness_dir / "plan.md").exists()
    assert (harness_dir / "telemetry.jsonl").exists()
    assert (harness_dir / "repo_index" / "file_tree.txt").exists()
    assert (harness_dir / "repo_index" / "module_symbols.json").exists()

    # Verify code was actually modified and fixed
    assert "if b == 0:" in calc_py.read_text()
