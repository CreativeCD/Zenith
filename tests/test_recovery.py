"""Comprehensive test suite for Layer 8 Recovery Engine & Circuit Breaker (Phase 3).

Tests:
  - Task 3.10: Circuit breaker (Level 1 WARNING, Level 2 BLOCK, Level 3 ESCALATE)
  - Task 3.11: Error taxonomy router for all 10 ErrorCode variants
  - Task 3.12: PATCH_FAILED recovery template and prompt
  - Task 3.13: AST_PARSE_FAIL recovery and auto-rollback flag
  - Task 3.14: LINT_REGRESSION recovery with violation locations
  - Task 3.15: TEST_FAILED recovery with stack trace injection
  - Task 3.16: REGRESSION_DETECTED recovery with checkpoint rollback
  - Task 3.17: SIDE_EFFECT_DETECTED recovery with refactor instructions
  - Task 3.18: TIMEOUT recovery with targeted filter guidance
  - Task 3.19: MAX_STEPS_EXCEEDED graceful exit and full rollback
  - Task 3.20: Graceful degradation chain (L1 -> L2 -> L3)
  - Task 3.21: Wire VerificationGate + RecoveryEngine integration
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.config import AgentConfig
from harness.contracts import (
    ErrorCode,
    PhaseResult,
    ResultStatus,
    VerificationPhase,
    VerificationResult,
)
from harness.recovery import CircuitBreaker, RecoveryEngine


def test_circuit_breaker_levels():
    """Task 3.10: Circuit breaker triggers at Level 1, 2, and 3."""
    cb = CircuitBreaker(window_size=5, max_loops=3)

    # 1. Clean first call -> Level 0
    level, _ = cb.record_and_evaluate("search_code", {"query": "auth"}, step=1)
    assert level == 0

    # 2. Distinct call -> Level 0
    level, _ = cb.record_and_evaluate("read_file_range", {"file": "auth.py", "start": 1, "end": 20}, step=2)
    assert level == 0

    # 3. Repeated non-consecutive call in window -> Level 1 (WARNING)
    level, msg = cb.record_and_evaluate("search_code", {"query": "auth"}, step=3)
    assert level == 1
    assert "LEVEL 1 WARNING" in msg

    # 4. Consecutive identical call -> Level 2 (BLOCK)
    level, msg = cb.record_and_evaluate("search_code", {"query": "auth"}, step=4)
    assert level == 2
    assert "LOOP DETECTED" in msg
    assert cb.loop_count == 1

    # 5. Consecutive identical call again -> Level 2 (BLOCK)
    level, msg = cb.record_and_evaluate("search_code", {"query": "auth"}, step=5)
    assert level == 2
    assert cb.loop_count == 2

    # 6. Consecutive identical call reaching threshold -> Level 3 (ESCALATE)
    level, msg = cb.record_and_evaluate("search_code", {"query": "auth"}, step=6)
    assert level == 3
    assert "LEVEL 3 ESCALATION" in msg
    assert cb.loop_count >= 3


def test_circuit_breaker_reset_buffer():
    """Task 3.10: Buffer reset on edit clears history."""
    cb = CircuitBreaker(window_size=5, max_loops=3)
    cb.record_and_evaluate("read_file_range", {"file": "app.py"}, step=1)
    cb.record_and_evaluate("read_file_range", {"file": "app.py"}, step=2)
    assert cb.loop_count == 1

    cb.reset_buffer()
    assert cb.loop_count == 0
    assert len(cb.buffer) == 0


def test_error_taxonomy_all_10_codes():
    """Task 3.11: Router handles all 10 error codes with appropriate RecoveryAction."""
    engine = RecoveryEngine()

    all_codes = [
        ErrorCode.PATCH_FAILED,
        ErrorCode.AST_PARSE_FAIL,
        ErrorCode.LINT_REGRESSION,
        ErrorCode.TEST_FAILED,
        ErrorCode.REGRESSION_DETECTED,
        ErrorCode.SIDE_EFFECT_DETECTED,
        ErrorCode.TIMEOUT,
        ErrorCode.TOOL_BLOCKED,
        ErrorCode.LOOP_DETECTED,
        ErrorCode.MAX_STEPS_EXCEEDED,
    ]

    for code in all_codes:
        action = engine.classify_error(code, context={"detail": "sample error context"}, step=5)
        assert action.error_code == code
        assert action.injection_prompt != ""
        assert action.action_description != ""
        assert action.level in (1, 2, 3)


def test_remediation_patch_failed():
    """Task 3.12: PATCH_FAILED switches to exact-block replacement mode."""
    engine = RecoveryEngine()
    ctx = {"target_file": "src/calc.py", "target_line": 40, "detail": "Hunk #1 failed"}
    action = engine.classify_error(ErrorCode.PATCH_FAILED, context=ctx, step=3)

    assert action.level == 1
    assert "src/calc.py" in action.injection_prompt
    assert "read_file_range" in action.injection_prompt
    assert "old_snippet" in action.injection_prompt
    assert not action.rollback_required


def test_remediation_ast_parse_fail():
    """Task 3.13: AST_PARSE_FAIL flags rollback and injects syntax details."""
    engine = RecoveryEngine()
    ctx = {"target_file": "src/parser.py", "detail": "invalid syntax at line 22"}
    action = engine.classify_error(ErrorCode.AST_PARSE_FAIL, context=ctx, step=7)

    assert action.level == 1
    assert action.rollback_required is True
    assert action.rollback_scope == "file"
    assert "AST_PARSE_FAIL at step 7" in action.injection_prompt
    assert "src/parser.py" in action.injection_prompt


def test_remediation_lint_regression():
    """Task 3.14: LINT_REGRESSION injects violation locations."""
    engine = RecoveryEngine()
    ctx = {"detail": "src/main.py:15:1 [F401] 'os' imported but unused"}
    action = engine.classify_error(ErrorCode.LINT_REGRESSION, context=ctx, step=4)

    assert action.level == 1
    assert "LINT_REGRESSION at step 4" in action.injection_prompt
    assert "src/main.py:15:1" in action.injection_prompt


def test_remediation_test_failed():
    """Task 3.15: TEST_FAILED injects stack trace and test file read instruction."""
    engine = RecoveryEngine()
    ctx = {"failing_tests": "tests/test_auth.py::test_login", "detail": "AssertionError: 401 != 200"}
    action = engine.classify_error(ErrorCode.TEST_FAILED, context=ctx, step=6)

    assert action.level == 1
    assert "TEST_FAILED at step 6" in action.injection_prompt
    assert "tests/test_auth.py::test_login" in action.injection_prompt
    assert "AssertionError: 401 != 200" in action.injection_prompt


def test_remediation_regression_detected():
    """Task 3.16: REGRESSION_DETECTED triggers Level 2 checkpoint rollback."""
    engine = RecoveryEngine()
    ctx = {"detail": "tests/test_billing.py::test_invoice"}
    action = engine.classify_error(ErrorCode.REGRESSION_DETECTED, context=ctx, step=9)

    assert action.level == 2
    assert action.rollback_required is True
    assert action.rollback_scope == "checkpoint"
    assert "REGRESSION_DETECTED at step 9" in action.injection_prompt


def test_remediation_side_effect_detected():
    """Task 3.17: SIDE_EFFECT_DETECTED instructs refactoring module-level code."""
    engine = RecoveryEngine()
    ctx = {"detail": "sys.exit(1) executed during module load"}
    action = engine.classify_error(ErrorCode.SIDE_EFFECT_DETECTED, context=ctx, step=2)

    assert action.level == 1
    assert "SIDE_EFFECT_DETECTED at step 2" in action.injection_prompt
    assert "sys.exit" in action.injection_prompt


def test_remediation_timeout():
    """Task 3.18: TIMEOUT suggests more targeted test filtering."""
    engine = RecoveryEngine()
    ctx = {"timeout_sec": 60}
    action = engine.classify_error(ErrorCode.TIMEOUT, context=ctx, step=8)

    assert action.level == 1
    assert "TIMEOUT at step 8" in action.injection_prompt
    assert "60s" in action.injection_prompt


def test_remediation_max_steps_exceeded():
    """Task 3.19: MAX_STEPS_EXCEEDED initiates Level 3 rollback all."""
    engine = RecoveryEngine(config=AgentConfig(max_steps=15))
    action = engine.classify_error(ErrorCode.MAX_STEPS_EXCEEDED, step=15)

    assert action.level == 3
    assert action.rollback_required is True
    assert action.rollback_scope == "all"
    assert "MAX_STEPS_EXCEEDED" in action.injection_prompt


def test_graceful_degradation_chain():
    """Task 3.20: Escalates from Level 1 auto-remediation -> Level 2 plan revision -> Level 3 exit."""
    engine = RecoveryEngine(config=AgentConfig(max_steps=25, max_plan_revisions=2))

    # Failure 1: Level 1 auto-remediation
    act1 = engine.escalate_degradation(ErrorCode.TEST_FAILED, consecutive_failures=1, step=5)
    assert act1.level == 1

    # Failure 2: Level 1 auto-remediation
    act2 = engine.escalate_degradation(ErrorCode.TEST_FAILED, consecutive_failures=2, step=6)
    assert act2.level == 1

    # Failure 3: Level 2 Plan revision
    act3 = engine.escalate_degradation(ErrorCode.TEST_FAILED, consecutive_failures=3, step=7)
    assert act3.level == 2
    assert "PLAN REVISION TRIGGERED" in act3.injection_prompt
    assert engine.revision_count == 1

    # Consecutive failure again reaches next plan revision
    act4 = engine.escalate_degradation(ErrorCode.TEST_FAILED, consecutive_failures=3, step=10)
    assert act4.level == 3
    assert act4.error_code == ErrorCode.MAX_STEPS_EXCEEDED
    assert engine.revision_count >= 2


def test_handle_verification_result_integration(tmp_path: Path):
    """Task 3.21: VerificationResult integrates seamlessly with RecoveryEngine."""
    engine = RecoveryEngine()

    # Successful verification -> None
    v_pass = VerificationResult(
        verification_id="v-1",
        run_at=datetime.now(timezone.utc),
        status=ResultStatus.SUCCESS,
    )
    assert engine.handle_verification_result(v_pass) is None

    # Failed reproduction test verification -> TEST_FAILED RecoveryAction
    v_fail = VerificationResult(
        verification_id="v-2",
        run_at=datetime.now(timezone.utc),
        status=ResultStatus.FAIL,
        first_failure=VerificationPhase.REPRO_TEST,
        phases={
            VerificationPhase.REPRO_TEST.value: PhaseResult(
                phase=VerificationPhase.REPRO_TEST,
                status=ResultStatus.FAIL,
                detail="AssertionError in test_subtraction",
                duration_ms=45,
            )
        },
    )

    action = engine.handle_verification_result(v_fail, step=4)
    assert action is not None
    assert action.error_code == ErrorCode.TEST_FAILED
    assert "test_subtraction" in action.injection_prompt


def test_checkpoint_and_rollback(tmp_path: Path):
    """Checkpoint creation and git rollback operation."""
    engine = RecoveryEngine()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="diff --git a/test.py b/test.py")
        diff_path = engine.create_checkpoint(str(tmp_path), checkpoint_id=1)
        assert Path(diff_path).exists()
        assert 1 in engine.checkpoints

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        success = engine.rollback(str(tmp_path), scope="all")
        assert success is True


def test_execute_graceful_exit(tmp_path: Path):
    """Graceful exit resets state and returns failure metadata."""
    engine = RecoveryEngine()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        exit_meta = engine.execute_graceful_exit(str(tmp_path), reason="MAX_STEPS_EXCEEDED")
        assert exit_meta["status"] == "FAILED"
        assert exit_meta["exit_code"] == 1
        assert exit_meta["reason"] == "MAX_STEPS_EXCEEDED"


def test_circuit_breaker_loop_count_resets_on_distinct_call():
    """Verify loop_count resets to 0 when a distinct tool call is made."""
    cb = CircuitBreaker(window_size=5, max_loops=3)
    cb.record_and_evaluate("search_code", {"query": "auth"}, step=1)
    cb.record_and_evaluate("search_code", {"query": "auth"}, step=2)
    assert cb.loop_count == 1

    # Interleaving distinct call
    cb.record_and_evaluate("read_file_range", {"file": "auth.py"}, step=3)
    assert cb.loop_count == 0

    # Repeat call now starts consecutive count again from 1, NOT 2
    level, _ = cb.record_and_evaluate("read_file_range", {"file": "auth.py"}, step=4)
    assert level == 2
    assert cb.loop_count == 1


def test_rollback_untracked_file_deleted(tmp_path: Path):
    """Verify rollback on an untracked file safely deletes it instead of failing git checkout."""
    untracked_file = tmp_path / "new_broken_file.py"
    untracked_file.write_text("broken")

    engine = RecoveryEngine()
    with patch("subprocess.run") as mock_run:
        # git ls-files --error-unmatch returns non-zero for untracked files
        mock_run.return_value = MagicMock(returncode=1)
        res = engine.rollback(str(tmp_path), scope="file", target="new_broken_file.py")
        assert res is True
        assert not untracked_file.exists()


def test_handle_verification_result_extracts_target_file_and_rolls_back(tmp_path: Path):
    """Verify handle_verification_result extracts target_file from syntax error detail."""
    engine = RecoveryEngine()
    v_fail = VerificationResult(
        verification_id="v-syntax",
        run_at=datetime.now(timezone.utc),
        status=ResultStatus.FAIL,
        first_failure=VerificationPhase.SYNTAX,
        phases={
            VerificationPhase.SYNTAX.value: PhaseResult(
                phase=VerificationPhase.SYNTAX,
                status=ResultStatus.FAIL,
                detail="Syntax errors detected in 1 file(s):\nsrc/calc.py:10: invalid syntax",
                duration_ms=20,
            )
        },
    )

    with patch.object(engine, "rollback") as mock_rollback:
        action = engine.handle_verification_result(v_fail, step=3, repo_path=str(tmp_path))
        assert action is not None
        assert action.error_code == ErrorCode.AST_PARSE_FAIL
        assert "src/calc.py" in action.injection_prompt
        mock_rollback.assert_called_once_with(str(tmp_path), scope="file", target="src/calc.py")
