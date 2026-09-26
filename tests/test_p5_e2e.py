"""End-to-End integration test for Phase 5: Skills, Telemetry, and Auto-Report Generator."""

import json
import subprocess

from harness.adapters.base import ModelAdapter, ModelResponse
from harness.config import HarnessConfig
from harness.contracts import AgentPhase, ToolCall
from harness.orchestrator import Orchestrator
from harness.telemetry import validate_telemetry_schema


class MockP5Adapter(ModelAdapter):
    """Deterministic mock adapter exercising skill fetching, patching, and completion."""

    def __init__(self, broken_file: str, test_filter: str):
        super().__init__()
        self.broken_file = broken_file
        self.test_filter = test_filter
        self.turn = 0

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        tools: list | None = None,
    ) -> ModelResponse:
        self.turn += 1

        # Turn 1: Emit plan
        if self.turn == 1:
            plan_json = {
                "plan": [
                    {
                        "step": 1,
                        "description": "Fetch external skill for bug pattern",
                        "tool_prediction": "fetch_external_skill",
                        "expected_outcome": "Identify zero division guard pattern",
                    },
                    {
                        "step": 2,
                        "description": "Apply fix to calculator",
                        "tool_prediction": "apply_patch",
                        "expected_outcome": "Raise ZeroDivisionError on b == 0",
                    },
                    {
                        "step": 3,
                        "description": "Verify fix with pytest",
                        "tool_prediction": "run_test_suite",
                        "expected_outcome": "Test passes",
                    },
                ],
                "estimated_total_steps": 3,
                "risk_factors": ["None"],
                "rollback_checkpoints": [1],
            }
            return ModelResponse(
                content=json.dumps(plan_json),
                tokens_in=300,
                tokens_out=150,
            )

        # Turn 2: Call fetch_external_skill
        if self.turn == 2:
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        tool="fetch_external_skill",
                        reasoning="Look up SWE-bench pattern for zero division guard",
                        args={
                            "source_type": "swe_bench",
                            "query": "ZeroDivisionError empty list denominator zero",
                            "max_tokens": 300,
                        },
                    )
                ],
                tokens_in=450,
                tokens_out=60,
            )

        # Turn 3: Call apply_patch
        if self.turn == 3:
            old_code = "    def divide(self, a: float, b: float) -> float:\n        return a / b"
            new_code = "    def divide(self, a: float, b: float) -> float:\n        if b == 0:\n            raise ZeroDivisionError(\"division by zero\")\n        return a / b"
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        tool="apply_patch",
                        reasoning="Add guard to divide method to prevent ZeroDivisionError",
                        args={
                            "target_file": self.broken_file,
                            "old_snippet": old_code,
                            "new_snippet": new_code,
                        },
                    )
                ],
                tokens_in=500,
                tokens_out=80,
            )

        # Turn 4: Run test suite
        if self.turn == 4:
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        tool="run_test_suite",
                        reasoning="Run calculator test suite to verify bugfix",
                        args={"test_filter": self.test_filter},
                    )
                ],
                tokens_in=600,
                tokens_out=40,
            )

        # Turn 5: Emit DONE_CANDIDATE
        done_signal = {
            "status": "DONE_CANDIDATE",
            "confidence": 0.98,
            "evidence": [
                "fetch_external_skill provided zero division strategy",
                "Applied ZeroDivisionError guard",
                "pytest test_zero passed cleanly",
            ],
            "files_modified": [self.broken_file],
        }
        return ModelResponse(
            content=json.dumps(done_signal),
            tokens_in=650,
            tokens_out=80,
        )


def test_p5_full_e2e_lifecycle_and_report(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Git init
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "zenith@test.com"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.name", "Zenith"], cwd=str(repo_dir), check=True)

    # Create README and CONTRIBUTING for startup pre-fetch
    (repo_dir / "README.md").write_text("# Toy Calculator\nMath library.", encoding="utf-8")
    (repo_dir / "CONTRIBUTING.md").write_text("# Contributor Guide\nRun pytest.", encoding="utf-8")
    (repo_dir / "pytest.ini").write_text("[pytest]\naddopts = -v\n", encoding="utf-8")

    src_dir = repo_dir / "src"
    src_dir.mkdir()
    calc_py = src_dir / "calc.py"
    calc_py.write_text(
        "class Calculator:\n"
        "    def add(self, a: float, b: float) -> float:\n"
        "        return a + b\n\n"
        "    def divide(self, a: float, b: float) -> float:\n"
        "        return a / b\n",
        encoding="utf-8",
    )

    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    test_calc = tests_dir / "test_calc.py"
    test_calc.write_text(
        "import pytest\n"
        "from src.calc import Calculator\n\n"
        "def test_add():\n"
        "    c = Calculator()\n"
        "    assert c.add(1, 2) == 3\n\n"
        "def test_zero():\n"
        "    c = Calculator()\n"
        "    with pytest.raises(ZeroDivisionError):\n"
        "        c.divide(10, 0)\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)

    issue_text = (
        "Calculator.divide crashes with uncaught exception or wrong behavior on zero.\n"
        "Expected: Calculator.divide(10, 0) raises ZeroDivisionError.\n"
        "Test to reproduce: pytest tests/test_calc.py -k test_zero\n"
        "Target file: src/calc.py\n"
    )

    out_dir = tmp_path / ".harness"
    config = HarnessConfig(
        repo_path=str(repo_dir),
        dry_run=False,
    )
    config.telemetry.output_dir = str(out_dir)
    config.telemetry.stream_to_stdout = False
    config.verification.run_syntax_check = True
    config.verification.run_lint_check = False  # Keep focused on repro test
    config.verification.run_repro_test = True
    config.verification.run_full_regression = False
    config.verification.run_diff_audit = False
    config.verification.run_side_effect_check = False

    adapter = MockP5Adapter(broken_file="src/calc.py", test_filter="tests/test_calc.py -k test_zero")
    orchestrator = Orchestrator(config=config, model_adapter=adapter)

    # Execute autonomous run
    session_result = orchestrator.run(issue_text=issue_text)

    # 1. Verify session result is DONE
    assert session_result.status == AgentPhase.DONE
    assert session_result.exit_code == 0
    assert session_result.total_steps >= 3

    # 2. Verify startup prefetch created skill cache entries
    skill_cache_dir = out_dir / "skill_cache"
    assert skill_cache_dir.exists()
    cached_entries = list(skill_cache_dir.glob("*.json"))
    assert len(cached_entries) >= 4  # README, CONTRIBUTING, TEST_CONFIG, CI_CONFIG, etc.

    # 3. Verify telemetry events and schema
    telemetry_file = out_dir / "telemetry.jsonl"
    assert telemetry_file.exists()
    with open(telemetry_file, "r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]

    assert len(events) >= 5
    for evt in events:
        assert validate_telemetry_schema(evt) is True

    # Check for skill fetch event in telemetry
    skill_events = [e for e in events if e.get("event_type") == "SKILL_FETCH"]
    assert len(skill_events) >= 1

    # 4. Verify report.md was automatically generated with all 8 sections
    report_file = out_dir / "report.md"
    assert report_file.exists()
    report_text = report_file.read_text(encoding="utf-8")

    assert "## 1. Executive Summary" in report_text
    assert "## 2. Step-by-Step Timeline" in report_text
    assert "## 3. Recovery Events" in report_text
    assert "## 4. Verification Results" in report_text
    assert "## 5. Final Diff Applied" in report_text
    assert "## 6. Agent Decisions Log" in report_text
    assert "## 7. Token & Cost Breakdown" in report_text
    assert "## 8. Lessons Learned" in report_text

    assert "PASS" in report_text
    assert "ZeroDivisionError" in report_text
