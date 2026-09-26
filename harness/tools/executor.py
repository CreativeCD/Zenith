"""harness/tools/executor.py — Sandboxed Subprocess and Test Suite Runner.

Reference: PRD.md §4.3.2, §4.3.4 | architecture.md §9.4 | phases.md Tasks 1.10 & 1.11
Implements:
- run_bash_sandboxed: 30s timeout, 512MB memory limit, 12-pattern blocklist, 200-line output cap
- run_test_suite: pytest adapter, 120s timeout, test filter & path routing, 80-line output cap
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from harness.contracts import ErrorCode, ResultStatus, ToolResult
from harness.tools.security import SecurityError, check_command_blocklist, validate_path


def _truncate_lines(text: str, max_lines: int) -> str:
    """Intelligently truncate output text to max_lines keeping head and tail."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text

    head_count = max_lines // 2
    tail_count = max_lines - head_count
    omitted = len(lines) - max_lines

    truncated_lines = (
        lines[:head_count]
        + [f"... [truncated {omitted} lines; showing first {head_count} and last {tail_count} lines] ..."]
        + lines[-tail_count:]
    )
    return "\n".join(truncated_lines)


def _make_preexec(memory_limit_mb: int = 512):
    """Create a preexec_fn that sets a new process group and memory limit."""
    def preexec():
        # New process group so timeouts can kill all spawned sub-processes
        if hasattr(os, "setsid"):
            try:
                os.setsid()
            except Exception:
                pass

        # Set address space memory limit on platforms supporting resource
        try:
            import resource
            mem_bytes = memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except Exception:
            pass

    return preexec


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Terminate the process and any descendants in its process group."""
    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_bash_sandboxed(
    command: str,
    repo_root: str = ".",
    timeout_sec: int = 30,
) -> ToolResult:
    """Execute a bash command in a sandboxed subprocess with security checks and resource limits.

    Safeguards:
    - 12-pattern dangerous command blocklist validation
    - Enforced timeout (default 30 seconds)
    - 512MB address space memory limit via resource.setrlimit
    - Process group cleanup to terminate orphan child processes
    - 200-line output truncation
    """
    start_time = time.perf_counter()

    # 1. Empty command check
    if not command or not str(command).strip():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="run_bash_sandboxed",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output="TOOL_ERROR: Command string cannot be empty.",
            truncated_output="TOOL_ERROR: Command string cannot be empty.",
            exit_code=1,
            execution_time_ms=latency_ms,
        )

    # 2. Security blocklist check
    try:
        check_command_blocklist(command)
    except SecurityError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        blocked_msg = str(e)
        tokens = len(blocked_msg) // 4
        return ToolResult(
            tool="run_bash_sandboxed",
            args_hash="",
            status=ResultStatus.BLOCKED,
            raw_output=blocked_msg,
            truncated_output=blocked_msg,
            exit_code=126,
            error_code=ErrorCode.TOOL_BLOCKED,
            tokens_in_raw=tokens,
            tokens_in_truncated=tokens,
            execution_time_ms=latency_ms,
        )

    # 2. Path resolution
    try:
        resolved_root = validate_path(".", repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        err_msg = f"TOOL_ERROR: {e}"
        tokens = len(err_msg) // 4
        return ToolResult(
            tool="run_bash_sandboxed",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=err_msg,
            truncated_output=err_msg,
            exit_code=1,
            tokens_in_raw=tokens,
            tokens_in_truncated=tokens,
            execution_time_ms=latency_ms,
        )

    # 3. Choose execution shell
    bash_bin = shutil.which("bash") or "/bin/bash"
    if Path(bash_bin).exists():
        args = [bash_bin, "-c", command]
    else:
        try:
            args = shlex.split(command)
        except ValueError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            err_msg = f"TOOL_ERROR: Failed to parse command: {e}"
            return ToolResult(
                tool="run_bash_sandboxed",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=err_msg,
                truncated_output=err_msg,
                exit_code=1,
                execution_time_ms=latency_ms,
            )

    preexec = _make_preexec(memory_limit_mb=512)

    try:
        proc = subprocess.Popen(
            args,
            cwd=str(resolved_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=preexec,
        )
        stdout, _ = proc.communicate(timeout=timeout_sec)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        _kill_process_tree(proc)
        stdout = e.stdout or ""
        try:
            more_stdout, _ = proc.communicate(timeout=1)
            if more_stdout:
                stdout += more_stdout
        except Exception:
            pass
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        timeout_msg = (
            f"Command timed out after {timeout_sec}s.\n"
            f"Partial output before timeout:\n{stdout}".strip()
        )
        tokens = len(timeout_msg) // 4
        return ToolResult(
            tool="run_bash_sandboxed",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=timeout_msg,
            truncated_output=_truncate_lines(timeout_msg, 200),
            exit_code=124,
            error_code=ErrorCode.TIMEOUT,
            tokens_in_raw=tokens,
            tokens_in_truncated=tokens,
            execution_time_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        err_msg = f"TOOL_ERROR: Execution failed: {e}"
        return ToolResult(
            tool="run_bash_sandboxed",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=err_msg,
            truncated_output=err_msg,
            exit_code=1,
            execution_time_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    raw_output = stdout or ""
    truncated_output = _truncate_lines(raw_output, 200)

    status = ResultStatus.SUCCESS if exit_code == 0 else ResultStatus.FAIL

    return ToolResult(
        tool="run_bash_sandboxed",
        args_hash="",
        status=status,
        raw_output=raw_output,
        truncated_output=truncated_output,
        exit_code=exit_code,
        tokens_in_raw=len(raw_output) // 4,
        tokens_in_truncated=len(truncated_output) // 4,
        execution_time_ms=latency_ms,
    )


def run_test_suite(
    repo_root: str = ".",
    test_path: Optional[str] = None,
    test_filter: Optional[str] = None,
    flags: Optional[str] = None,
    timeout_sec: int = 120,
) -> ToolResult:
    """Run configured test runner (pytest by default) with filtering and truncation.

    Safeguards:
    - Path traversal guard on repo_root and test_path
    - 120-second hard execution timeout
    - 80-line output truncation (head and tail)
    - Returns exit code, pass/fail counts, and error trace
    """
    start_time = time.perf_counter()

    try:
        resolved_root = validate_path(".", repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        err_msg = f"TOOL_ERROR: {e}"
        return ToolResult(
            tool="run_test_suite",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=err_msg,
            truncated_output=err_msg,
            exit_code=1,
            execution_time_ms=latency_ms,
        )

    # Validate test_path if provided
    if test_path:
        try:
            validate_path(test_path, str(resolved_root))
        except ValueError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            err_msg = f"TOOL_ERROR: Invalid test path: {e}"
            return ToolResult(
                tool="run_test_suite",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=err_msg,
                truncated_output=err_msg,
                exit_code=1,
                execution_time_ms=latency_ms,
            )

    # Assemble test runner command
    if (resolved_root / "go.mod").exists():
        go_bin = shutil.which("go") or "go"
        cmd: List[str] = [go_bin, "test", "./..."]
    elif (resolved_root / "package.json").exists() and not any(
        (resolved_root / f).exists() for f in ["pyproject.toml", "setup.py", "setup.cfg", "pytest.ini"]
    ):
        npm_bin = shutil.which("npm") or "npm"
        cmd = [npm_bin, "test"]
    else:
        cmd = [sys.executable, "-m", "pytest"]

    if test_path:
        cmd.append(test_path)

    if test_filter:
        try:
            check_command_blocklist(test_filter)
        except SecurityError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="run_test_suite",
                args_hash="",
                status=ResultStatus.BLOCKED,
                raw_output=str(e),
                truncated_output=str(e),
                exit_code=126,
                error_code=ErrorCode.TOOL_BLOCKED,
                execution_time_ms=latency_ms,
            )
        cmd.extend(["-k", test_filter])

    if flags:
        try:
            check_command_blocklist(flags)
        except SecurityError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="run_test_suite",
                args_hash="",
                status=ResultStatus.BLOCKED,
                raw_output=str(e),
                truncated_output=str(e),
                exit_code=126,
                error_code=ErrorCode.TOOL_BLOCKED,
                execution_time_ms=latency_ms,
            )
        try:
            cmd.extend(shlex.split(flags))
        except ValueError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="run_test_suite",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"TOOL_ERROR: Invalid flags string: {e}",
                truncated_output=f"TOOL_ERROR: Invalid flags string: {e}",
                exit_code=1,
                execution_time_ms=latency_ms,
            )

    preexec = _make_preexec(memory_limit_mb=1024)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(resolved_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=preexec,
        )
        stdout, _ = proc.communicate(timeout=timeout_sec)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        _kill_process_tree(proc)
        stdout = e.stdout or ""
        try:
            more_stdout, _ = proc.communicate(timeout=1)
            if more_stdout:
                stdout += more_stdout
        except Exception:
            pass
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        timeout_msg = (
            f"Test suite execution timed out after {timeout_sec}s.\n"
            f"Partial output before timeout:\n{stdout}".strip()
        )
        tokens = len(timeout_msg) // 4
        return ToolResult(
            tool="run_test_suite",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=timeout_msg,
            truncated_output=_truncate_lines(timeout_msg, 80),
            exit_code=124,
            error_code=ErrorCode.TIMEOUT,
            tokens_in_raw=tokens,
            tokens_in_truncated=tokens,
            execution_time_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        err_msg = f"TOOL_ERROR: Test execution failed: {e}"
        return ToolResult(
            tool="run_test_suite",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=err_msg,
            truncated_output=err_msg,
            exit_code=1,
            execution_time_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    raw_output = stdout or ""
    truncated_output = _truncate_lines(raw_output, 80)

    status = ResultStatus.SUCCESS if exit_code == 0 else ResultStatus.FAIL
    error_code = None if exit_code == 0 else ErrorCode.TEST_FAILED

    return ToolResult(
        tool="run_test_suite",
        args_hash="",
        status=status,
        raw_output=raw_output,
        truncated_output=truncated_output,
        exit_code=exit_code,
        error_code=error_code,
        tokens_in_raw=len(raw_output) // 4,
        tokens_in_truncated=len(truncated_output) // 4,
        execution_time_ms=latency_ms,
    )
