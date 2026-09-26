"""harness/tools/vcs.py — Git Version Control Tools.

Reference: PRD.md §4.3.2 | architecture.md §9.4 | phases.md Tasks 1.12–1.14
Implements:
- git_status: porcelain status of working directory vs HEAD
- git_diff: diff vs HEAD with optional single-file filter and 500-line cap
- git_rollback: resets single file or entire tree to clean HEAD state
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import List, Optional

from harness.contracts import ResultStatus, ToolResult
from harness.tools.security import validate_path


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


def git_status(repo_root: str = ".") -> ToolResult:
    """Return working tree status vs HEAD (modified, staged, untracked)."""
    start_time = time.perf_counter()

    try:
        resolved_root = validate_path(".", repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="git_status",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(resolved_root),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="git_status",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output="TOOL_ERROR: git status timed out after 15s.",
            truncated_output="TOOL_ERROR: git status timed out after 15s.",
            execution_time_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="git_status",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: git status failed: {e}",
            truncated_output=f"TOOL_ERROR: git status failed: {e}",
            execution_time_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - start_time) * 1000)

    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
        return ToolResult(
            tool="git_status",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"GIT_ERROR: {err}",
            truncated_output=f"GIT_ERROR: {err}",
            exit_code=proc.returncode,
            execution_time_ms=latency_ms,
        )

    output = proc.stdout.strip()
    if not output:
        raw_output = "Working tree clean. No modified, added, or untracked files."
    else:
        raw_output = output

    truncated_output = _truncate_lines(raw_output, 200)

    return ToolResult(
        tool="git_status",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=raw_output,
        truncated_output=truncated_output,
        exit_code=0,
        tokens_in_raw=len(raw_output) // 4,
        tokens_in_truncated=len(truncated_output) // 4,
        execution_time_ms=latency_ms,
    )


def git_diff(
    repo_root: str = ".",
    file_path: Optional[str] = None,
) -> ToolResult:
    """Return diff against HEAD, optionally restricted to a specific file, capped at 500 lines."""
    start_time = time.perf_counter()

    try:
        resolved_root = validate_path(".", repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="git_diff",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    cmd: List[str] = ["git", "diff", "HEAD"]
    if file_path:
        try:
            validate_path(file_path, str(resolved_root))
        except ValueError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="git_diff",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"TOOL_ERROR: {e}",
                truncated_output=f"TOOL_ERROR: {e}",
                execution_time_ms=latency_ms,
            )
        cmd.extend(["--", file_path])

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(resolved_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="git_diff",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output="TOOL_ERROR: git diff timed out after 30s.",
            truncated_output="TOOL_ERROR: git diff timed out after 30s.",
            execution_time_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="git_diff",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: git diff failed: {e}",
            truncated_output=f"TOOL_ERROR: git diff failed: {e}",
            execution_time_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - start_time) * 1000)

    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
        return ToolResult(
            tool="git_diff",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"GIT_ERROR: {err}",
            truncated_output=f"GIT_ERROR: {err}",
            exit_code=proc.returncode,
            execution_time_ms=latency_ms,
        )

    raw_output = proc.stdout
    truncated_output = _truncate_lines(raw_output, 500)

    return ToolResult(
        tool="git_diff",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=raw_output,
        truncated_output=truncated_output,
        exit_code=0,
        tokens_in_raw=len(raw_output) // 4,
        tokens_in_truncated=len(truncated_output) // 4,
        execution_time_ms=latency_ms,
    )


def git_rollback(
    repo_root: str = ".",
    file_path: Optional[str] = None,
) -> ToolResult:
    """Roll back single file or entire repository to clean HEAD state."""
    start_time = time.perf_counter()

    try:
        resolved_root = validate_path(".", repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="git_rollback",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    if file_path:
        try:
            target_path = validate_path(file_path, str(resolved_root))
        except ValueError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="git_rollback",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"TOOL_ERROR: {e}",
                truncated_output=f"TOOL_ERROR: {e}",
                execution_time_ms=latency_ms,
            )

        # Restore single file
        try:
            proc = subprocess.run(
                ["git", "checkout", "HEAD", "--", file_path],
                cwd=str(resolved_root),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="git_rollback",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output="TOOL_ERROR: git rollback timed out after 15s.",
                truncated_output="TOOL_ERROR: git rollback timed out after 15s.",
                execution_time_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="git_rollback",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"TOOL_ERROR: git rollback failed: {e}",
                truncated_output=f"TOOL_ERROR: git rollback failed: {e}",
                execution_time_ms=latency_ms,
            )

        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            # If not a git repository, fail immediately without touching files
            if "not a git repository" in err.lower():
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool="git_rollback",
                    args_hash="",
                    status=ResultStatus.FAIL,
                    raw_output=f"GIT_ERROR: {err}",
                    truncated_output=f"GIT_ERROR: {err}",
                    exit_code=proc.returncode,
                    execution_time_ms=latency_ms,
                )

            # File might be untracked (never committed to HEAD)
            if target_path.exists():
                try:
                    if target_path.is_dir():
                        shutil.rmtree(target_path)
                        raw_output = f"Removed untracked directory '{file_path}'."
                    else:
                        target_path.unlink()
                        raw_output = f"Removed untracked file '{file_path}'."
                except Exception as e:
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    return ToolResult(
                        tool="git_rollback",
                        args_hash="",
                        status=ResultStatus.FAIL,
                        raw_output=f"TOOL_ERROR: Failed to remove untracked path: {e}",
                        truncated_output=f"TOOL_ERROR: Failed to remove untracked path: {e}",
                        execution_time_ms=latency_ms,
                    )
            else:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool="git_rollback",
                    args_hash="",
                    status=ResultStatus.FAIL,
                    raw_output=f"GIT_ERROR: {err}",
                    truncated_output=f"GIT_ERROR: {err}",
                    exit_code=proc.returncode,
                    execution_time_ms=latency_ms,
                )
        else:
            raw_output = f"Successfully rolled back '{file_path}' to HEAD."
    else:
        # Revert all modified files
        try:
            proc1 = subprocess.run(
                ["git", "checkout", "HEAD", "--", "."],
                cwd=str(resolved_root),
                capture_output=True,
                text=True,
                timeout=20,
            )
            # Clean all untracked files & directories, preserving harness metadata
            proc2 = subprocess.run(
                ["git", "clean", "-fd", "-e", ".harness"],
                cwd=str(resolved_root),
                capture_output=True,
                text=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="git_rollback",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output="TOOL_ERROR: git rollback timed out after 20s.",
                truncated_output="TOOL_ERROR: git rollback timed out after 20s.",
                execution_time_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="git_rollback",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"TOOL_ERROR: git rollback failed: {e}",
                truncated_output=f"TOOL_ERROR: git rollback failed: {e}",
                execution_time_ms=latency_ms,
            )

        if proc1.returncode != 0 or proc2.returncode != 0:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            err = proc1.stderr.strip() or proc2.stderr.strip() or "Rollback failed"
            return ToolResult(
                tool="git_rollback",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"GIT_ERROR: {err}",
                truncated_output=f"GIT_ERROR: {err}",
                exit_code=proc1.returncode or proc2.returncode,
                execution_time_ms=latency_ms,
            )

        raw_output = "Successfully rolled back all repository files and removed untracked files to clean HEAD."

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    return ToolResult(
        tool="git_rollback",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=raw_output,
        truncated_output=raw_output,
        exit_code=0,
        tokens_in_raw=len(raw_output) // 4,
        tokens_in_truncated=len(raw_output) // 4,
        execution_time_ms=latency_ms,
    )
