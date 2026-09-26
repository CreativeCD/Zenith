"""tests/test_p1_e2e.py — Phase 1 Single-Turn E2E Integration Test.

Reference: PRD.md §3.3, §4.3 | phases.md Task 1.19
Validates full end-to-end tool pipeline:
1. Initial test failure reproduction
2. Symbol lookup / file reading
3. Dual-mode patch application with AST validation
4. Git diff inspection
5. Test suite verification returning exit code 0
6. Rollback verification
"""

import subprocess
from harness.contracts import ResultStatus, ToolCall
from harness.tool_engine import ToolEngine


def _setup_e2e_repo(tmp_path):
    """Setup a git-tracked toy repository with a reproducible bug."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "e2e@zenith.ai"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Zenith E2E"], cwd=tmp_path, check=True, capture_output=True)

    calc = tmp_path / "calculator.py"
    calc.write_text("""def divide(a: float, b: float) -> float:
    # Buggy implementation: raises ZeroDivisionError on b == 0
    return a / b
""")

    test_calc = tmp_path / "test_calculator.py"
    test_calc.write_text("""from calculator import divide

def test_divide_zero_safe():
    assert divide(10.0, 0.0) == 0.0

def test_divide_normal():
    assert divide(10.0, 2.0) == 5.0
""")

    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial buggy commit"], cwd=tmp_path, check=True, capture_output=True)


def test_single_turn_e2e_bugfix_lifecycle(tmp_path):
    """Verify single-turn bugfix workflow: read -> repro -> patch -> verify -> diff."""
    _setup_e2e_repo(tmp_path)
    engine = ToolEngine(repo_root=str(tmp_path))

    # 1. Reproduce failure before patch
    repro_call = ToolCall(
        tool="run_test_suite",
        reasoning="Reproduce the failure by running test suite against initial code",
        args={"test_path": "test_calculator.py"},
    )
    res_repro = engine.execute(repro_call)
    assert res_repro.status == ResultStatus.FAIL
    assert res_repro.exit_code != 0
    assert "ZeroDivisionError" in res_repro.raw_output or "failed" in res_repro.raw_output.lower()

    # 2. Locate and inspect the function
    symbol_call = ToolCall(
        tool="get_symbol",
        reasoning="Extract symbol definition for divide in calculator.py",
        args={"file_path": "calculator.py", "symbol_name": "divide"},
    )
    res_symbol = engine.execute(symbol_call)
    assert res_symbol.status == ResultStatus.SUCCESS
    assert "def divide" in res_symbol.raw_output

    # 3. Read specific lines
    read_call = ToolCall(
        tool="read_file_range",
        reasoning="Inspect source lines of divide function",
        args={"file_path": "calculator.py", "start_line": 1, "end_line": 6},
    )
    res_read = engine.execute(read_call)
    assert res_read.status == ResultStatus.SUCCESS
    assert "1: def divide" in res_read.raw_output

    # 4. Apply fix via apply_patch
    patch_call = ToolCall(
        tool="apply_patch",
        reasoning="Fix division by zero to return 0.0 safely",
        args={
            "target_file": "calculator.py",
            "old_snippet": "    return a / b",
            "new_snippet": "    if b == 0:\n        return 0.0\n    return a / b",
        },
    )
    res_patch = engine.execute(patch_call)
    assert res_patch.status == ResultStatus.SUCCESS

    # 5. Check git diff
    diff_call = ToolCall(
        tool="git_diff",
        reasoning="Review git diff of applied fix against HEAD",
        args={"file_path": "calculator.py"},
    )
    res_diff = engine.execute(diff_call)
    assert res_diff.status == ResultStatus.SUCCESS
    assert "+    if b == 0:" in res_diff.raw_output

    # 6. Verify with test suite — must now succeed with exit code 0
    verify_call = ToolCall(
        tool="run_test_suite",
        reasoning="Confirm test suite passes with exit code 0 after applying fix",
        args={"test_path": "test_calculator.py"},
    )
    res_verify = engine.execute(verify_call)
    assert res_verify.status == ResultStatus.SUCCESS
    assert res_verify.exit_code == 0
    assert "2 passed" in res_verify.raw_output or "passed" in res_verify.raw_output.lower()

    # 7. Rollback verification
    rb_call = ToolCall(
        tool="git_rollback",
        reasoning="Rollback changes to clean HEAD state",
        args={"file_path": "calculator.py"},
    )
    res_rb = engine.execute(rb_call)
    assert res_rb.status == ResultStatus.SUCCESS
    # Ensure bug returned
    assert "if b == 0" not in (tmp_path / "calculator.py").read_text()
