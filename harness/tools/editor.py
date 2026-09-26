"""harness/tools/editor.py — File Reading, Writing & Dual-Mode Atomic Patch Engine.

Reference: PRD.md §4.3.2 | architecture.md §9.4
Implements read_file_range with line numbers & 250-line cap, write_file (new files only),
and apply_patch (unified diff primary, exact block fallback, AST check + atomic rollback).
"""

from __future__ import annotations

import ast
import os
import re
import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from harness.contracts import ErrorCode, ResultStatus, ToolResult
from harness.tools.security import validate_path


def _atomic_write(target_path: Path, content: str) -> None:
    """Atomically write text content using a temporary file in the same directory."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.parent / f".tmp_{target_path.name}_{uuid.uuid4().hex[:8]}"
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, target_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def read_file_range(
    file_path: str,
    start_line: int,
    end_line: int,
    repo_root: str = ".",
) -> ToolResult:
    """Read specific line range from a file with 1-indexed line numbers and 250-line hard cap."""
    start_time = time.perf_counter()

    try:
        resolved = validate_path(file_path, repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="read_file_range",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    if not resolved.exists():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="read_file_range",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: File '{file_path}' does not exist.",
            truncated_output=f"TOOL_ERROR: File '{file_path}' does not exist.",
            execution_time_ms=latency_ms,
        )

    if not resolved.is_file():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="read_file_range",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: Path '{file_path}' is a directory, not a file.",
            truncated_output=f"TOOL_ERROR: Path '{file_path}' is a directory, not a file.",
            execution_time_ms=latency_ms,
        )

    # Reject binary files
    try:
        with resolved.open("rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool="read_file_range",
                    args_hash="",
                    status=ResultStatus.FAIL,
                    raw_output=f"TOOL_ERROR: Cannot read binary file '{file_path}'.",
                    truncated_output=f"TOOL_ERROR: Cannot read binary file '{file_path}'.",
                    execution_time_ms=latency_ms,
                )
    except OSError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="read_file_range",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: Failed to open file '{file_path}': {e}",
            truncated_output=f"TOOL_ERROR: Failed to open file '{file_path}': {e}",
            execution_time_ms=latency_ms,
        )

    if start_line < 1:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="read_file_range",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: start_line must be >= 1 (got {start_line}).",
            truncated_output=f"TOOL_ERROR: start_line must be >= 1 (got {start_line}).",
            execution_time_ms=latency_ms,
        )

    if start_line > end_line:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="read_file_range",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: start_line ({start_line}) cannot be greater than end_line ({end_line}).",
            truncated_output=f"TOOL_ERROR: start_line ({start_line}) cannot be greater than end_line ({end_line}).",
            execution_time_ms=latency_ms,
        )

    lines: List[str] = []
    total_lines = 0
    with resolved.open("r", encoding="utf-8", errors="ignore") as f:
        for idx, line in enumerate(f, start=1):
            total_lines += 1
            if start_line <= idx <= min(end_line, start_line + 250 - 1):
                lines.append(f"{idx:4d}: {line.rstrip('\r\n')}")

    if start_line > total_lines:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="read_file_range",
            args_hash="",
            status=ResultStatus.SUCCESS,
            raw_output=f"(file has {total_lines} lines; start_line {start_line} is beyond end of file)",
            truncated_output=f"(file has {total_lines} lines; start_line {start_line} is beyond end of file)",
            execution_time_ms=latency_ms,
        )

    # Hard cap at 250 lines (PRD §4.3.2)
    max_read_lines = 250
    capped = (end_line > start_line + max_read_lines - 1)
    if capped:
        lines.append(f"... (truncated: read capped at {max_read_lines} lines; file has {total_lines} lines)")

    raw_output = "\n".join(lines)
    tokens_count = max(1, len(raw_output.split()))
    latency_ms = int((time.perf_counter() - start_time) * 1000)

    return ToolResult(
        tool="read_file_range",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=raw_output,
        truncated_output=raw_output,
        tokens_in_raw=tokens_count,
        tokens_in_truncated=tokens_count,
        execution_time_ms=latency_ms,
    )


def write_file(
    file_path: str,
    content: str,
    repo_root: str = ".",
) -> ToolResult:
    """Write a new file. Refuses to overwrite existing files (creates parent directories)."""
    start_time = time.perf_counter()

    try:
        resolved = validate_path(file_path, repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="write_file",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    # Refuse overwrite guarantee (PRD §4.3.2)
    if resolved.exists():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="write_file",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: File '{file_path}' already exists. Use apply_patch to edit existing files.",
            truncated_output=f"TOOL_ERROR: File '{file_path}' already exists. Use apply_patch to edit existing files.",
            execution_time_ms=latency_ms,
        )

    # AST syntax check before committing (if Python)
    if resolved.suffix.lower() == ".py":
        try:
            ast.parse(content, filename=str(resolved))
        except SyntaxError as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="write_file",
                args_hash="",
                status=ResultStatus.FAIL,
                error_code=ErrorCode.AST_PARSE_FAIL,
                raw_output=f"TOOL_ERROR: Syntax error in new file content: {e}. File was not created.",
                truncated_output=f"TOOL_ERROR: Syntax error in new file content: {e}. File was not created.",
                execution_time_ms=latency_ms,
            )

    try:
        _atomic_write(resolved, content)
    except OSError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="write_file",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: Failed to write file '{file_path}': {e}",
            truncated_output=f"TOOL_ERROR: Failed to write file '{file_path}': {e}",
            execution_time_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    msg = f"Successfully created new file '{file_path}' ({len(content.splitlines())} lines)."
    tokens_count = max(1, len(msg.split()))

    return ToolResult(
        tool="write_file",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=msg,
        truncated_output=msg,
        tokens_in_raw=tokens_count,
        tokens_in_truncated=tokens_count,
        execution_time_ms=latency_ms,
    )


def apply_patch(
    target_file: str,
    repo_root: str = ".",
    patch_string: Optional[str] = None,
    old_snippet: Optional[str] = None,
    new_snippet: Optional[str] = None,
) -> ToolResult:
    """Apply dual-mode patch (unified diff primary, exact block fallback) with atomic AST rollback."""
    start_time = time.perf_counter()

    try:
        resolved = validate_path(target_file, repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="apply_patch",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    if not resolved.exists():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="apply_patch",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: File '{target_file}' does not exist.",
            truncated_output=f"TOOL_ERROR: File '{target_file}' does not exist.",
            execution_time_ms=latency_ms,
        )

    if not resolved.is_file():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="apply_patch",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: Path '{target_file}' is a directory, not a file.",
            truncated_output=f"TOOL_ERROR: Path '{target_file}' is a directory, not a file.",
            execution_time_ms=latency_ms,
        )

    original_content = resolved.read_text(encoding="utf-8", errors="ignore")
    patched_content: Optional[str] = None

    # Mode 1: Unified Diff
    if patch_string and ("@@" in patch_string or patch_string.strip().startswith(("---", "+++", "diff"))):
        patched_res, diff_err = _apply_unified_diff(original_content, patch_string)
        if diff_err and old_snippet is None:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="apply_patch",
                args_hash="",
                status=ResultStatus.FAIL,
                error_code=ErrorCode.PATCH_FAILED,
                raw_output=diff_err,
                truncated_output=diff_err,
                execution_time_ms=latency_ms,
            )
        patched_content = patched_res

    # Mode 2: Exact Block Fallback
    if patched_content is None:
        if old_snippet is not None and new_snippet is not None:
            res_block, err_msg = _apply_exact_block(original_content, old_snippet, new_snippet, target_file)
            if err_msg:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                return ToolResult(
                    tool="apply_patch",
                    args_hash="",
                    status=ResultStatus.FAIL,
                    error_code=ErrorCode.PATCH_FAILED,
                    raw_output=err_msg,
                    truncated_output=err_msg,
                    execution_time_ms=latency_ms,
                )
            patched_content = res_block
        elif patch_string:
            # Maybe patch_string is an exact replacement or malformed diff; try simple search
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="apply_patch",
                args_hash="",
                status=ResultStatus.FAIL,
                error_code=ErrorCode.PATCH_FAILED,
                raw_output="TOOL_ERROR: Could not parse unified diff. Provide old_snippet and new_snippet for exact block replacement.",
                truncated_output="TOOL_ERROR: Could not parse unified diff. Provide old_snippet and new_snippet for exact block replacement.",
                execution_time_ms=latency_ms,
            )
        else:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="apply_patch",
                args_hash="",
                status=ResultStatus.FAIL,
                error_code=ErrorCode.PATCH_FAILED,
                raw_output="TOOL_ERROR: Either patch_string or (old_snippet + new_snippet) must be provided.",
                truncated_output="TOOL_ERROR: Either patch_string or (old_snippet + new_snippet) must be provided.",
                execution_time_ms=latency_ms,
            )

    # Check for unchanged content
    if patched_content == original_content:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="apply_patch",
            args_hash="",
            status=ResultStatus.FAIL,
            error_code=ErrorCode.PATCH_FAILED,
            raw_output=f"TOOL_ERROR: Patch produced no changes to '{target_file}'.",
            truncated_output=f"TOOL_ERROR: Patch produced no changes to '{target_file}'.",
            execution_time_ms=latency_ms,
        )

    # Step 3: Atomic AST Validation before committing changes
    if resolved.suffix.lower() == ".py":
        try:
            ast.parse(patched_content, filename=str(resolved))
        except SyntaxError as e:
            # Atomic rollback: do not write broken content
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="apply_patch",
                args_hash="",
                status=ResultStatus.FAIL,
                error_code=ErrorCode.AST_PARSE_FAIL,
                raw_output=f"TOOL_ERROR: Patch produced Python SyntaxError: {e}. Changes were rolled back.",
                truncated_output=f"TOOL_ERROR: Patch produced Python SyntaxError: {e}. Changes were rolled back.",
                execution_time_ms=latency_ms,
            )

    # Write patched content atomically
    try:
        _atomic_write(resolved, patched_content)
    except OSError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="apply_patch",
            args_hash="",
            status=ResultStatus.FAIL,
            error_code=ErrorCode.PATCH_FAILED,
            raw_output=f"TOOL_ERROR: Failed to write patched file: {e}",
            truncated_output=f"TOOL_ERROR: Failed to write patched file: {e}",
            execution_time_ms=latency_ms,
        )

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    msg = f"Successfully applied patch to '{target_file}'."
    tokens_count = max(1, len(msg.split()))

    return ToolResult(
        tool="apply_patch",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=msg,
        truncated_output=msg,
        tokens_in_raw=tokens_count,
        tokens_in_truncated=tokens_count,
        execution_time_ms=latency_ms,
    )


def _apply_exact_block(
    original: str,
    old_snippet: str,
    new_snippet: str,
    filename: str,
) -> tuple[Optional[str], Optional[str]]:
    """Replace unique exact snippet in original content."""
    # 1. Exact match
    count = original.count(old_snippet)
    if count == 1:
        return original.replace(old_snippet, new_snippet, 1), None
    elif count > 1:
        return (
            None,
            f"TOOL_ERROR: old_snippet appears {count} times in '{filename}'. "
            "Disambiguate by providing more surrounding lines of context.",
        )

    # 2. Try normalized line endings (\r\n vs \n)
    orig_norm = original.replace("\r\n", "\n")
    old_norm = old_snippet.replace("\r\n", "\n")
    new_norm = new_snippet.replace("\r\n", "\n")
    count_norm = orig_norm.count(old_norm)

    if count_norm == 1:
        return orig_norm.replace(old_norm, new_norm, 1), None
    elif count_norm > 1:
        return (
            None,
            f"TOOL_ERROR: old_snippet appears {count_norm} times in '{filename}'. "
            "Disambiguate by providing more surrounding lines of context.",
        )

    # 3. Try trailing-whitespace-normalized line match
    orig_lines = original.splitlines(keepends=True)
    old_lines = old_snippet.splitlines()
    if old_lines:
        old_stripped = [line.rstrip("\r\n ") for line in old_lines]
        matches = [
            i
            for i in range(len(orig_lines) - len(old_lines) + 1)
            if [orig_lines[i + j].rstrip("\r\n ") for j in range(len(old_lines))] == old_stripped
        ]
        if len(matches) == 1:
            match_idx = matches[0]
            target_slice = "".join(orig_lines[match_idx : match_idx + len(old_lines)])
            return original.replace(target_slice, new_snippet, 1), None
        elif len(matches) > 1:
            return (
                None,
                f"TOOL_ERROR: old_snippet appears {len(matches)} times in '{filename}'. "
                "Disambiguate by providing more surrounding lines of context.",
            )

    return (
        None,
        f"TOOL_ERROR: old_snippet not found in '{filename}'. "
        "Verify line contents using read_file_range before patching.",
    )


def _apply_unified_diff(original: str, patch_str: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse and apply unified diff hunks with proximity-anchored context replacement."""
    orig_lines = original.splitlines(keepends=True)
    patch_lines = patch_str.splitlines(keepends=True)

    # Extract hunks
    hunk_regex = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    hunks: List[List[str]] = []
    current_hunk: List[str] = []

    for line in patch_lines:
        if hunk_regex.match(line):
            if current_hunk:
                hunks.append(current_hunk)
            current_hunk = [line]
        elif current_hunk:
            current_hunk.append(line)

    if current_hunk:
        hunks.append(current_hunk)

    if not hunks:
        return None, "TOOL_ERROR: Could not parse unified diff. No @@ hunk headers found."

    def _find_all(haystack: str, needle: str) -> List[int]:
        pos = 0
        hits = []
        while True:
            idx_hit = haystack.find(needle, pos)
            if idx_hit == -1:
                break
            hits.append(idx_hit)
            pos = idx_hit + 1
        return hits

    # Apply each hunk in reverse order so line numbers remain valid
    result_lines = list(orig_lines)

    for hunk in reversed(hunks):
        header = hunk[0]
        m = hunk_regex.match(header)
        if not m:
            continue

        old_start = int(m.group(1))
        # 1-indexed to 0-indexed
        idx = max(0, old_start - 1)

        # Build hunk old and new blocks with context lines for precise anchoring
        old_hunk_lines = []
        new_hunk_lines = []
        del_lines = []
        add_lines = []

        for hline in hunk[1:]:
            if hline.startswith("-"):
                line_content = hline[1:]
                old_hunk_lines.append(line_content)
                del_lines.append(line_content)
            elif hline.startswith("+"):
                line_content = hline[1:]
                new_hunk_lines.append(line_content)
                add_lines.append(line_content)
            elif hline.startswith(" "):
                line_content = hline[1:]
                old_hunk_lines.append(line_content)
                new_hunk_lines.append(line_content)

        old_context_block = "".join(old_hunk_lines)
        new_context_block = "".join(new_hunk_lines)
        old_del_block = "".join(del_lines)
        new_add_block = "".join(add_lines)

        full_content = "".join(result_lines)
        applied = False
        has_context_lines = any(hline.startswith(" ") for hline in hunk[1:])

        # Check exact context match
        if old_context_block and old_context_block in full_content:
            hits = _find_all(full_content, old_context_block)
            if len(hits) > 1:
                best_pos = min(hits, key=lambda pos: abs(full_content[:pos].count("\n") - idx))
                full_content = full_content[:best_pos] + new_context_block + full_content[best_pos + len(old_context_block):]
            else:
                full_content = full_content.replace(old_context_block, new_context_block, 1)
            result_lines = full_content.splitlines(keepends=True)
            applied = True
        elif not has_context_lines and old_del_block and old_del_block in full_content:
            hits = _find_all(full_content, old_del_block)
            if len(hits) > 1:
                best_pos = min(hits, key=lambda pos: abs(full_content[:pos].count("\n") - idx))
                full_content = full_content[:best_pos] + new_add_block + full_content[best_pos + len(old_del_block):]
            else:
                full_content = full_content.replace(old_del_block, new_add_block, 1)
            result_lines = full_content.splitlines(keepends=True)
            applied = True
        elif "\r\n" in full_content and old_context_block:
            # Check with normalized CRLF line endings
            norm_full = full_content.replace("\r\n", "\n")
            norm_old = old_context_block.replace("\r\n", "\n")
            norm_new = new_context_block.replace("\r\n", "\n")
            if norm_old in norm_full:
                hits = _find_all(norm_full, norm_old)
                if len(hits) > 1:
                    best_pos = min(hits, key=lambda pos: abs(norm_full[:pos].count("\n") - idx))
                    norm_full = norm_full[:best_pos] + norm_new + norm_full[best_pos + len(norm_old):]
                else:
                    norm_full = norm_full.replace(norm_old, norm_new, 1)
                full_content = norm_full.replace("\n", "\r\n")
                result_lines = full_content.splitlines(keepends=True)
                applied = True
        elif not old_del_block and add_lines:
            # Pure insertion at index
            result_lines[idx:idx] = add_lines
            applied = True

        if not applied:
            return None, (
                f"TOOL_ERROR: Unified diff hunk starting at line {old_start} could not be matched. "
                "Context lines do not match target file. Use read_file_range to inspect lines."
            )

    return "".join(result_lines), None
