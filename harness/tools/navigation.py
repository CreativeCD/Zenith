"""harness/tools/navigation.py — Directory Listing & Code Search Navigation Tools.

Reference: PRD.md §4.3.2 | architecture.md §9.1
Implements list_dir with depth capping & junk exclusion, and search_code with ripgrep + python fallback.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from harness.contracts import ResultStatus, ToolResult
from harness.tools.security import validate_path

JUNK_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".tox",
    ".eggs",
    ".pytest_cache",
    ".ruff_cache",
    ".harness",
    ".idea",
    ".vscode",
}

TEST_DIR_PATTERNS = {"tests", "test", "spec", "__tests__"}

BINARY_EXTENSIONS = {
    ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar",
    ".gz", ".exe", ".bin", ".dylib", ".so", ".a", ".o", ".woff", ".woff2",
    ".ttf", ".eot", ".mp3", ".mp4", ".db", ".sqlite", ".sqlite3"
}


def _format_size(size_bytes: int) -> str:
    """Format bytes into readable size string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def list_dir(
    path: str = ".",
    repo_root: str = ".",
    depth: int = 3,
    recursive: bool = False,
) -> ToolResult:
    """List files and subdirectories with sizes, depth cap, and exclusion list."""
    start_time = time.perf_counter()

    try:
        target_path = validate_path(path, repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="list_dir",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    if not target_path.exists():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="list_dir",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: Directory '{path}' does not exist.",
            truncated_output=f"TOOL_ERROR: Directory '{path}' does not exist.",
            execution_time_ms=latency_ms,
        )

    if not target_path.is_dir():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="list_dir",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: Path '{path}' is a file, not a directory.",
            truncated_output=f"TOOL_ERROR: Path '{path}' is a file, not a directory.",
            execution_time_ms=latency_ms,
        )

    # Hard cap depth between 1 and 4 (PRD §4.3.2)
    max_depth = max(1, min(depth, 4)) if (recursive or depth > 1) else 1
    root_resolved = Path(repo_root).resolve()

    lines: List[str] = []
    max_items = 500

    def _walk(curr: Path, current_depth: int) -> None:
        if current_depth > max_depth or len(lines) >= max_items:
            return

        try:
            entries = sorted(curr.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except (PermissionError, OSError):
            return

        for entry in entries:
            if len(lines) >= max_items:
                lines.append(f"... (truncated: directory listing capped at {max_items} items)")
                return

            if entry.name in JUNK_DIRS or entry.name.endswith(".egg-info"):
                continue

            try:
                rel = entry.relative_to(root_resolved)
                indent = "  " * (current_depth - 1)

                if entry.is_dir():
                    lines.append(f"{indent}[DIR]  {rel}/")
                    _walk(entry, current_depth + 1)
                else:
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        size = 0
                    lines.append(f"{indent}[FILE] {rel} ({_format_size(size)})")
            except (PermissionError, OSError):
                continue

    _walk(target_path, 1)

    raw_output = "\n".join(lines) if lines else "(empty directory)"
    tokens_raw = max(1, len(raw_output.split()))
    latency_ms = int((time.perf_counter() - start_time) * 1000)

    return ToolResult(
        tool="list_dir",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=raw_output,
        truncated_output=raw_output,
        tokens_in_raw=tokens_raw,
        tokens_in_truncated=tokens_raw,
        execution_time_ms=latency_ms,
    )


def search_code(
    query: str,
    repo_root: str = ".",
    path_pattern: Optional[str] = None,
    regex: bool = False,
    context_lines: int = 2,
    include_tests: bool = False,
) -> ToolResult:
    """Search codebase using ripgrep when available, with pure Python fallback."""
    start_time = time.perf_counter()

    if not query or not query.strip():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="search_code",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output="TOOL_ERROR: Query string cannot be empty.",
            truncated_output="TOOL_ERROR: Query string cannot be empty.",
            execution_time_ms=latency_ms,
        )

    try:
        root_path = validate_path(".", repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="search_code",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    if not root_path.exists() or not root_path.is_dir():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="search_code",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: Repository root '{repo_root}' does not exist or is not a directory.",
            truncated_output=f"TOOL_ERROR: Repository root '{repo_root}' does not exist or is not a directory.",
            execution_time_ms=latency_ms,
        )

    if path_pattern and (".." in path_pattern):
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="search_code",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: Path traversal detected in path_pattern: '{path_pattern}'.",
            truncated_output=f"TOOL_ERROR: Path traversal detected in path_pattern: '{path_pattern}'.",
            execution_time_ms=latency_ms,
        )

    context_lines = max(0, min(context_lines, 20))
    max_matches = 50

    # 1. Try ripgrep if binary available
    rg_binary = shutil.which("rg")
    if rg_binary:
        rg_result = _search_with_ripgrep(
            rg_binary=rg_binary,
            query=query,
            root_path=root_path,
            path_pattern=path_pattern,
            regex=regex,
            context_lines=context_lines,
            include_tests=include_tests,
            max_matches=max_matches,
        )
        if rg_result is not None:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            tokens_count = max(1, len(rg_result.split()))
            return ToolResult(
                tool="search_code",
                args_hash="",
                status=ResultStatus.SUCCESS,
                raw_output=rg_result,
                truncated_output=rg_result,
                tokens_in_raw=tokens_count,
                tokens_in_truncated=tokens_count,
                execution_time_ms=latency_ms,
            )

    # 2. Pure Python fallback search
    py_result = _search_with_python(
        query=query,
        root_path=root_path,
        path_pattern=path_pattern,
        regex=regex,
        context_lines=context_lines,
        include_tests=include_tests,
        max_matches=max_matches,
    )
    latency_ms = int((time.perf_counter() - start_time) * 1000)
    tokens_count = max(1, len(py_result.split()))

    return ToolResult(
        tool="search_code",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=py_result,
        truncated_output=py_result,
        tokens_in_raw=tokens_count,
        tokens_in_truncated=tokens_count,
        execution_time_ms=latency_ms,
    )


def _search_with_ripgrep(
    rg_binary: str,
    query: str,
    root_path: Path,
    path_pattern: Optional[str],
    regex: bool,
    context_lines: int,
    include_tests: bool,
    max_matches: int,
) -> Optional[str]:
    """Execute search via ripgrep command line."""
    cmd = [
        rg_binary,
        "-n",
        f"-C{context_lines}",
        f"--max-count={max_matches}",
    ]
    if not regex:
        cmd.append("-F")
    if path_pattern:
        cmd.extend(["-g", path_pattern])

    # Ignore junk dirs
    for d in JUNK_DIRS:
        cmd.extend(["-g", f"!{d}/*"])

    if not include_tests:
        for t in TEST_DIR_PATTERNS:
            cmd.extend(["-g", f"!{t}/*", "-g", f"!*_{t}.py", "-g", f"!{t}_*.py"])

    cmd.extend(["--", query, str(root_path)])

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        output = proc.stdout.strip()
        if not output:
            return "No matches found."

        # Relativize paths in output
        root_str = str(root_path).rstrip(os.sep) + os.sep
        output = output.replace(root_str, "")

        lines = output.splitlines()
        if len(lines) > 200:
            lines = lines[:200]
            output = "\n".join(lines) + f"\n... (truncated: results capped at {max_matches} matches)"

        return output
    except Exception:
        return None


def _search_with_python(
    query: str,
    root_path: Path,
    path_pattern: Optional[str],
    regex: bool,
    context_lines: int,
    include_tests: bool,
    max_matches: int,
) -> str:
    """Fallback search using Python directory traversal."""
    pattern = None
    if regex:
        try:
            pattern = re.compile(query, flags=re.IGNORECASE)
        except re.error as e:
            return f"TOOL_ERROR: Invalid regular expression: {e}"

    results: List[str] = []
    match_count = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        # In-place filter out junk directories
        dirnames[:] = [
            d for d in dirnames
            if d not in JUNK_DIRS and not d.endswith(".egg-info")
            and (include_tests or d not in TEST_DIR_PATTERNS)
        ]

        for fname in sorted(filenames):
            file_full = Path(dirpath) / fname
            rel_path = file_full.relative_to(root_path)

            if path_pattern and not (fnmatch.fnmatch(fname, path_pattern) or fnmatch.fnmatch(str(rel_path), path_pattern)):
                continue

            if file_full.suffix.lower() in BINARY_EXTENSIONS:
                continue

            if not include_tests and (
                fname.startswith("test_")
                or fname.endswith("_test.py")
                or fname in {"test.py", "tests.py", "conftest.py"}
            ):
                continue

            try:
                content = file_full.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            file_lines = content.splitlines()
            for idx, line in enumerate(file_lines):
                matched = bool(pattern.search(line)) if pattern else (query in line)
                if matched:
                    match_count += 1
                    start_idx = max(0, idx - context_lines)
                    end_idx = min(len(file_lines), idx + context_lines + 1)

                    results.append(f"--- {rel_path}:{idx + 1} ---")
                    for ctx_i in range(start_idx, end_idx):
                        prefix = ">" if ctx_i == idx else " "
                        results.append(f"{rel_path}:{ctx_i + 1}:{prefix} {file_lines[ctx_i]}")

                    if match_count >= max_matches:
                        results.append(f"\n... (capped at {max_matches} matches)")
                        return "\n".join(results)

    return "\n".join(results) if results else "No matches found."
