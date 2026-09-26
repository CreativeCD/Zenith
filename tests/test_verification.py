"""Comprehensive test suite for Layer 7 Verification Gate (Phase 3).

Tests:
  - Task 3.1: Syntax check (Python + JS, broken and clean)
  - Task 3.2: Linter delta mode (pre-existing vs newly introduced violations)
  - Task 3.3: Reproduction test execution (pass vs fail with stack trace)
  - Task 3.4: Full regression suite delta check (detect new failing test)
  - Task 3.5: Diff audit (binary check, whitespace-only check, valid diff)
  - Task 3.6: Side-effect check (sys.exit on import vs clean import)
  - Task 3.7: Startup baseline capture (linter_baseline.json and test_baseline.json)
  - Task 3.8: VerificationResult serialization schema compliance
  - Task 3.9: Sequential execution with early-exit on first failure
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.config import VerificationConfig
from harness.contracts import (
    Complexity,
    IssuePlan,
    PhaseResult,
    ResultStatus,
    SuspectedFile,
    TaskType,
    VerificationPhase,
    VerificationResult,
)
from harness.verification import VerificationGate, capture_baselines


def test_syntax_check_python_clean(tmp_path: Path):
    """Task 3.1: Syntax check passes on valid Python file."""
    code_file = tmp_path / "valid.py"
    code_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")

    gate = VerificationGate()
    result = gate._run_syntax_check(str(tmp_path), ["valid.py"])

    assert result.phase == VerificationPhase.SYNTAX
    assert result.status == ResultStatus.SUCCESS
    assert "Syntax verified" in result.detail


def test_syntax_check_python_broken(tmp_path: Path):
    """Task 3.1: Syntax check detects invalid Python syntax."""
    code_file = tmp_path / "broken.py"
    code_file.write_text("def broken_func(\n    return 42\n")  # Unclosed paren

    gate = VerificationGate()
    result = gate._run_syntax_check(str(tmp_path), ["broken.py"])

    assert result.phase == VerificationPhase.SYNTAX
    assert result.status == ResultStatus.FAIL
    assert "Syntax errors detected" in result.detail
    assert "broken.py" in result.detail


def test_syntax_check_javascript_clean_and_broken(tmp_path: Path):
    """Task 3.1: Syntax check handles JavaScript bracket balancing."""
    clean_js = tmp_path / "clean.js"
    clean_js.write_text("function test() { return [1, 2, 3]; }")

    broken_js = tmp_path / "broken.js"
    broken_js.write_text("function test() { return [1, 2, 3; }")  # Unclosed bracket

    gate = VerificationGate()
    res_clean = gate._run_syntax_check(str(tmp_path), ["clean.js"])
    assert res_clean.status == ResultStatus.SUCCESS

    res_broken = gate._run_syntax_check(str(tmp_path), ["broken.js"])
    assert res_broken.status == ResultStatus.FAIL
    assert "broken.js" in res_broken.detail


def test_linter_check_delta_mode(tmp_path: Path):
    """Task 3.2: Pre-existing violations are ignored; new violations are flagged."""
    baseline_dir = tmp_path / ".harness" / "repo_index"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    baseline_violations = [
        {"filename": "app.py", "code": "E501", "location": {"row": 10, "column": 80}, "message": "Line too long"}
    ]
    with open(baseline_dir / "linter_baseline.json", "w", encoding="utf-8") as f:
        json.dump(baseline_violations, f)

    gate = VerificationGate()

    # Scenario A: Only pre-existing violation -> PASS
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps([
                {"filename": "app.py", "code": "E501", "location": {"row": 10, "column": 80}, "message": "Line too long"}
            ]),
        )
        res_pass = gate._run_lint_check(str(tmp_path), ["app.py"], baseline_dir=str(baseline_dir))
        assert res_pass.status == ResultStatus.SUCCESS
        assert "0 new linter violations" in res_pass.detail

    # Scenario B: Newly introduced violation -> FAIL
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps([
                {"filename": "app.py", "code": "E501", "location": {"row": 10, "column": 80}, "message": "Line too long"},
                {"filename": "app.py", "code": "F401", "location": {"row": 1, "column": 1}, "message": "'os' imported but unused"},
            ]),
        )
        res_fail = gate._run_lint_check(str(tmp_path), ["app.py"], baseline_dir=str(baseline_dir))
        assert res_fail.status == ResultStatus.FAIL
        assert "1 new linter violation" in res_fail.detail
        assert "F401" in res_fail.detail


def test_reproduction_test_pass_and_fail(tmp_path: Path):
    """Task 3.3: Reproduction test returns PASS or FAIL with trace."""
    gate = VerificationGate()

    plan = IssuePlan(
        issue_id="ISSUE-001",
        primary_goal="Fix addition in calculator",
        task_type=TaskType.BUG_FIX,
        acceptance_criteria=["add(2, 2) == 4"],
        suspected_files=[SuspectedFile(path="calculator.py", confidence=1.0, reason="Bug in add")],
        reproduction_hint="pytest tests/test_calc.py",
        test_filter="tests/test_calc.py",
        error_type="AssertionError",
        complexity_estimate=Complexity.LOW,
        estimated_steps=5,
        requires_external_knowledge=False,
        language="python",
        test_runner="pytest",
        parsing_confidence=0.95,
        parsing_method="RULE_BASED",
    )

    # Subprocess returns 0 -> PASS
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="1 passed", stderr="")
        res_pass = gate._run_repro_test(str(tmp_path), plan)
        assert res_pass.status == ResultStatus.SUCCESS

    # Subprocess returns 1 -> FAIL with stack trace
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="FAILED tests/test_calc.py::test_add - AssertionError: 5 != 4",
            stderr="Traceback (most recent call last):\n  File 'test_calc.py', line 5",
        )
        res_fail = gate._run_repro_test(str(tmp_path), plan)
        assert res_fail.status == ResultStatus.FAIL
        assert "AssertionError" in res_fail.detail


def test_regression_suite_delta_check(tmp_path: Path):
    """Task 3.4: Full regression suite detects newly failing tests vs baseline."""
    baseline_dir = tmp_path / ".harness" / "repo_index"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    with open(baseline_dir / "test_baseline.json", "w", encoding="utf-8") as f:
        json.dump({"failing_tests": ["tests/test_old.py::test_known_failure"]}, f)

    gate = VerificationGate()

    # Scenario A: No new failing tests
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="FAILED tests/test_old.py::test_known_failure\n1 failed, 10 passed in 0.5s",
            stderr="",
        )
        res_pass = gate._run_regression_suite(str(tmp_path), baseline_dir=str(baseline_dir))
        assert res_pass.status == ResultStatus.SUCCESS
        assert "0 new regressions" in res_pass.detail

    # Scenario B: Newly introduced test failure
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=(
                "FAILED tests/test_old.py::test_known_failure\n"
                "FAILED tests/test_core.py::test_auth_broken\n"
                "2 failed, 9 passed in 0.6s"
            ),
            stderr="",
        )
        res_fail = gate._run_regression_suite(str(tmp_path), baseline_dir=str(baseline_dir))
        assert res_fail.status == ResultStatus.FAIL
        assert "new regression test failure" in res_fail.detail
        assert "test_auth_broken" in res_fail.detail


def test_diff_audit_binary_and_whitespace(tmp_path: Path):
    """Task 3.5: Diff audit flags binary files and whitespace-only changes."""
    gate = VerificationGate()

    # 1. Binary file detection
    binary_file = tmp_path / "asset.bin"
    binary_file.write_bytes(b"\x00\x01\x02\x03\x04")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="diff --git a/asset.bin b/asset.bin")
        res_bin = gate._run_diff_audit(str(tmp_path), ["asset.bin"])
        assert res_bin.status == ResultStatus.FAIL
        assert "Binary" in res_bin.detail

    # 2. Whitespace-only detection
    normal_file = tmp_path / "code.py"
    normal_file.write_text("print('hello')\n")

    def mock_diff(cmd, **kwargs):
        if "-w" in cmd:
            return MagicMock(returncode=0, stdout="")  # No change when ignoring whitespace
        return MagicMock(returncode=0, stdout="--- a/code.py\n+++ b/code.py\n@@ -1 +1 @@\n-print('hello')\n+  print('hello')")

    with patch("subprocess.run", side_effect=mock_diff):
        res_ws = gate._run_diff_audit(str(tmp_path), ["code.py"])
        assert res_ws.status == ResultStatus.FAIL
        assert "Whitespace-only" in res_ws.detail


def test_side_effect_check(tmp_path: Path):
    """Task 3.6: Side-effect check catches sys.exit() or crashes on module import."""
    gate = VerificationGate()

    # File with top-level sys.exit
    bad_mod = tmp_path / "bad_mod.py"
    bad_mod.write_text("import sys\nsys.exit(99)\n")

    res_bad = gate._run_side_effect_check(str(tmp_path), ["bad_mod.py"])
    assert res_bad.status == ResultStatus.FAIL
    assert "bad_mod" in res_bad.detail

    # Clean file
    good_mod = tmp_path / "good_mod.py"
    good_mod.write_text("def helper():\n    return 'clean'\n")

    res_good = gate._run_side_effect_check(str(tmp_path), ["good_mod.py"])
    assert res_good.status == ResultStatus.SUCCESS


def test_baseline_capture_startup(tmp_path: Path):
    """Task 3.7: capture_baselines writes both baseline JSON files."""
    out_dir = tmp_path / ".harness" / "repo_index"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="FAILED tests/test_init.py::test_stub\n1 failed",
            stderr="",
        )
        _linter_data, _test_data = capture_baselines(str(tmp_path), output_dir=".harness/repo_index")

    assert (out_dir / "linter_baseline.json").exists()
    assert (out_dir / "test_baseline.json").exists()

    with open(out_dir / "test_baseline.json", "r", encoding="utf-8") as f:
        loaded_test_baseline = json.load(f)
        assert "tests/test_init.py::test_stub" in loaded_test_baseline["failing_tests"]


def test_verification_result_schema_serialization():
    """Task 3.8: VerificationResult serialization matches contract schema."""
    phases = {
        VerificationPhase.SYNTAX.value: PhaseResult(
            phase=VerificationPhase.SYNTAX,
            status=ResultStatus.SUCCESS,
            detail="clean",
            duration_ms=10,
        ),
        VerificationPhase.REPRO_TEST.value: PhaseResult(
            phase=VerificationPhase.REPRO_TEST,
            status=ResultStatus.FAIL,
            detail="AssertionError",
            duration_ms=50,
        ),
    }

    v_res = VerificationResult(
        verification_id="v-20260926-001",
        run_at=datetime.now(timezone.utc),
        status=ResultStatus.FAIL,
        phases=phases,
        first_failure=VerificationPhase.REPRO_TEST,
        recovery_action="RECOVERY_TEST_FAILED",
        diff_summary="1 file changed",
        total_duration_ms=60,
    )

    data = v_res.to_dict()
    assert data["status"] == "FAIL"
    assert data["first_failure"] == "REPRO_TEST"
    assert data["recovery_action"] == "RECOVERY_TEST_FAILED"
    assert "SYNTAX" in data["phases"]
    assert "REPRO_TEST" in data["phases"]
    assert data["phases"]["SYNTAX"]["status"] == "SUCCESS"

    json_str = v_res.to_json()
    assert '"RECOVERY_TEST_FAILED"' in json_str


def test_early_exit_on_first_failure(tmp_path: Path):
    """Task 3.9: First failure immediately halts subsequent verification phases."""
    # Create broken syntax Python file
    broken = tmp_path / "broken.py"
    broken.write_text("def invalid_syntax(\n")

    gate = VerificationGate(
        config=VerificationConfig(
            run_syntax_check=True,
            run_lint_check=True,
            run_repro_test=True,
            run_full_regression=True,
            run_diff_audit=True,
            run_side_effect_check=True,
        )
    )

    result = gate.verify(str(tmp_path), modified_files=["broken.py"])

    assert result.status == ResultStatus.FAIL
    assert result.first_failure == VerificationPhase.SYNTAX
    # Only SYNTAX phase was executed
    assert list(result.phases.keys()) == [VerificationPhase.SYNTAX.value]
    assert result.recovery_action == "RECOVERY_AST_PARSE_FAIL"


def test_syntax_check_javascript_strings_and_comments_no_false_positive(tmp_path: Path):
    """Verify JS bracket parser ignores brackets in strings, template literals, and comments."""
    js_file = tmp_path / "app.js"
    js_file.write_text(
        'const greeting = "Hello :)";\n'
        'const regexPattern = "/[(]/";\n'
        '// Function with unclosed bracket ( in comment\n'
        '/* Block comment with { [ unclosed */\n'
        'const template = `Value: ${1 + 2} :)`;\n'
        'function run() { return true; }\n'
    )
    gate = VerificationGate()
    result = gate._run_syntax_check(str(tmp_path), ["app.js"])
    assert result.status == ResultStatus.SUCCESS
    assert "Syntax verified" in result.detail


def test_side_effect_check_catches_sys_exit_zero(tmp_path: Path):
    """Verify side-effect check catches sys.exit(0) as a failure."""
    mod = tmp_path / "exit_zero.py"
    mod.write_text("import sys\nsys.exit(0)\n")
    gate = VerificationGate()
    result = gate._run_side_effect_check(str(tmp_path), ["exit_zero.py"])
    assert result.status == ResultStatus.FAIL
    assert "exit_zero" in result.detail


def test_regression_suite_catches_collection_failure(tmp_path: Path):
    """Verify regression suite detects test runner collection failure (exit 2)."""
    gate = VerificationGate()

    # Scenario A: Collection error with test ID -> caught as new failure
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout="ERROR tests/test_core.py - SyntaxError during collection\n1 error in 0.1s",
            stderr="",
        )
        result = gate._run_regression_suite(str(tmp_path))
        assert result.status == ResultStatus.FAIL
        assert "tests/test_core.py" in result.detail

    # Scenario B: Runner crash / unparseable collection error
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout="ERRORS\nFatal syntax error during collection\n",
            stderr="",
        )
        result = gate._run_regression_suite(str(tmp_path))
        assert result.status == ResultStatus.FAIL
        assert "collection error" in result.detail


def test_linter_empty_and_non_python_files_fast_path(tmp_path: Path):
    """Verify linter returns SUCCESS quickly when no files or only non-Python files modified."""
    gate = VerificationGate()
    res_empty = gate._run_lint_check(str(tmp_path), [])
    assert res_empty.status == ResultStatus.SUCCESS
    assert "No modified files" in res_empty.detail

    res_txt = gate._run_lint_check(str(tmp_path), ["README.md", "notes.txt"])
    assert res_txt.status == ResultStatus.SUCCESS
    assert "No lintable Python files" in res_txt.detail
