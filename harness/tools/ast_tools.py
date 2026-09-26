"""harness/tools/ast_tools.py — AST Symbol Navigation Tools.

Reference: PRD.md §4.2.2, §4.3.2 | architecture.md §9.3
Extracts function/class signatures, docstrings, imports, symbols, and references
without polluting the LLM context window with entire file bodies.
Supports Python AST parsing with regex fallbacks for JS/TS/Go/Rust/Java.
"""

from __future__ import annotations

import ast
import os
import re
import time
from pathlib import Path
from typing import List, Optional

from harness.contracts import ResultStatus, ToolResult
from harness.tools.navigation import BINARY_EXTENSIONS, JUNK_DIRS
from harness.tools.security import validate_path


def list_symbols(file_path: str, repo_root: str = ".") -> ToolResult:
    """List all top-level symbols (classes, functions, constants) with their line numbers."""
    start_time = time.perf_counter()

    try:
        resolved = validate_path(file_path, repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="list_symbols",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    if not resolved.exists():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="list_symbols",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: File '{file_path}' does not exist.",
            truncated_output=f"TOOL_ERROR: File '{file_path}' does not exist.",
            execution_time_ms=latency_ms,
        )

    if resolved.is_dir():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="list_symbols",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: '{file_path}' is a directory. Use list_dir instead.",
            truncated_output=f"TOOL_ERROR: '{file_path}' is a directory. Use list_dir instead.",
            execution_time_ms=latency_ms,
        )

    content = resolved.read_text(encoding="utf-8", errors="ignore")

    try:
        tree = ast.parse(content, filename=str(resolved))
        entries: List[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods = [m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
                methods_str = f" [methods: {', '.join(methods)}]" if methods else ""
                entries.append(f"Line {node.lineno:4d}: class {node.name}{methods_str}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                entries.append(f"Line {node.lineno:4d}: {prefix} {node.name}")
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        entries.append(f"Line {node.lineno:4d}: const {target.id}")
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    entries.append(f"Line {node.lineno:4d}: const {node.target.id}")
        raw_output = "\n".join(entries) if entries else "No top-level symbols found."
    except SyntaxError:
        # Fallback regex scanner for non-python or syntactically invalid files
        lines = content.splitlines()
        regex_entries: List[str] = []
        for i, line in enumerate(lines, 1):
            m = re.match(r"^(class|def|async def|const|export class|export function|function|async function|fn|func|pub fn|pub struct|struct|interface|type)\s+([A-Za-z0-9_]+)", line.strip())
            if m:
                regex_entries.append(f"Line {i:4d}: {m.group(0)}")
        raw_output = "\n".join(regex_entries) if regex_entries else "No top-level symbols found."

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    tokens_count = max(1, len(raw_output.split()))

    return ToolResult(
        tool="list_symbols",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=raw_output,
        truncated_output=raw_output,
        tokens_in_raw=tokens_count,
        tokens_in_truncated=tokens_count,
        execution_time_ms=latency_ms,
    )


def _get_symbol_regex(lines: List[str], file_path: str, symbol_name: str) -> Optional[str]:
    """Fallback scanner for non-Python code (JS/TS/Go/Rust/Java)."""
    pattern = re.compile(
        rf"\b(class|struct|interface|type|def|async def|function|async function|fn|func|pub fn|pub struct)\s+{re.escape(symbol_name)}\b"
    )

    for idx, line in enumerate(lines):
        if pattern.search(line):
            start_line = idx + 1
            output_lines = [
                f"Symbol: {symbol_name} in {file_path} [Line {start_line}]",
                line.strip(),
            ]
            # Include preceding doc comment if present
            comment_idx = idx - 1
            comments = []
            while comment_idx >= 0 and lines[comment_idx].strip().startswith(("//", "/*", "*", "#", "///")):
                comments.insert(0, f"    {lines[comment_idx].strip()}")
                comment_idx -= 1
            if comments:
                output_lines.insert(1, "\n".join(comments))

            # Include preview of next 5 lines
            preview_end = min(len(lines), idx + 6)
            output_lines.append("    # Preview:")
            for p_i in range(idx + 1, preview_end):
                output_lines.append(f"    {lines[p_i]}")

            return "\n".join(output_lines[:50])

    return None


def get_symbol(file_path: str, symbol_name: str, repo_root: str = ".") -> ToolResult:
    """Retrieve signature, docstring, and line range of a symbol (never entire body)."""
    start_time = time.perf_counter()

    if not symbol_name or not str(symbol_name).strip():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="get_symbol",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output="TOOL_ERROR: symbol_name cannot be empty.",
            truncated_output="TOOL_ERROR: symbol_name cannot be empty.",
            execution_time_ms=latency_ms,
        )

    clean_symbol = symbol_name.strip()

    try:
        resolved = validate_path(file_path, repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="get_symbol",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    if not resolved.exists():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="get_symbol",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: File '{file_path}' does not exist.",
            truncated_output=f"TOOL_ERROR: File '{file_path}' does not exist.",
            execution_time_ms=latency_ms,
        )

    if resolved.is_dir():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="get_symbol",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: '{file_path}' is a directory. Specify a code file.",
            truncated_output=f"TOOL_ERROR: '{file_path}' is a directory. Specify a code file.",
            execution_time_ms=latency_ms,
        )

    content = resolved.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()

    # Parse Class.method notation
    target_class: Optional[str] = None
    target_member: str = clean_symbol
    if "." in clean_symbol:
        target_class, target_member = clean_symbol.split(".", 1)

    try:
        tree = ast.parse(content, filename=str(resolved))
        matched_node: Optional[ast.AST] = None

        if target_class:
            class_node: Optional[ast.ClassDef] = None
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == target_class:
                    class_node = node
                    break
            if class_node:
                for member in class_node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == target_member:
                        matched_node = member
                        break
                    elif isinstance(member, ast.Assign):
                        for t in member.targets:
                            if isinstance(t, ast.Name) and t.id == target_member:
                                matched_node = member
                                break
                        if matched_node:
                            break
                    elif isinstance(member, ast.AnnAssign):
                        if isinstance(member.target, ast.Name) and member.target.id == target_member:
                            matched_node = member
                            break
        else:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == target_member:
                        matched_node = node
                        break
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id == target_member:
                            matched_node = node
                            break
                    if matched_node:
                        break
                elif isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name) and node.target.id == target_member:
                        matched_node = node
                        break

        if not matched_node:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="get_symbol",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"TOOL_ERROR: Symbol '{clean_symbol}' not found in '{file_path}'.",
                truncated_output=f"TOOL_ERROR: Symbol '{clean_symbol}' not found in '{file_path}'.",
                execution_time_ms=latency_ms,
            )

        output_lines: List[str] = []
        start_line = getattr(matched_node, "lineno", 1)
        end_line = getattr(matched_node, "end_lineno", start_line)

        output_lines.append(f"Symbol: {clean_symbol} in {file_path} [Lines {start_line}-{end_line}]")

        docstring = ast.get_docstring(matched_node) if hasattr(matched_node, "body") else None  # type: ignore[arg-type]

        if isinstance(matched_node, ast.ClassDef):
            output_lines.append(f"class {matched_node.name}:")
            if docstring:
                output_lines.append(f'    """{docstring}"""')
            output_lines.append("    # Methods:")
            for item in matched_node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig_line = lines[item.lineno - 1].strip() if item.lineno <= len(lines) else item.name
                    item_doc = ast.get_docstring(item)
                    doc_summary = f" — {item_doc.splitlines()[0]}" if item_doc else ""
                    output_lines.append(f"    - Line {item.lineno}: {sig_line}{doc_summary}")

        elif isinstance(matched_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(matched_node, ast.AsyncFunctionDef) else "def"
            sig_line = lines[matched_node.lineno - 1].strip() if matched_node.lineno <= len(lines) else f"{prefix} {matched_node.name}"
            output_lines.append(sig_line)
            if docstring:
                output_lines.append(f'    """{docstring}"""')
            # Return signature + first 3 lines of body
            body_start = matched_node.lineno
            body_end = min(end_line, body_start + 4)
            output_lines.append("    # Preview:")
            for idx in range(body_start, body_end):
                if idx < len(lines):
                    output_lines.append(f"    {lines[idx]}")

        elif isinstance(matched_node, (ast.Assign, ast.AnnAssign)):
            sig_line = lines[matched_node.lineno - 1].strip() if matched_node.lineno <= len(lines) else clean_symbol
            output_lines.append(sig_line)

        # Enforce 50 line hard cap (PRD §4.3.2)
        if len(output_lines) > 50:
            output_lines = output_lines[:50]
            output_lines.append("... (truncated: output capped at 50 lines)")

        raw_output = "\n".join(output_lines)

    except SyntaxError:
        # Fallback to regex symbol scanner for non-Python files
        regex_result = _get_symbol_regex(lines, file_path, clean_symbol)
        if regex_result:
            raw_output = regex_result
        else:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ToolResult(
                tool="get_symbol",
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"TOOL_ERROR: Symbol '{clean_symbol}' not found in '{file_path}'.",
                truncated_output=f"TOOL_ERROR: Symbol '{clean_symbol}' not found in '{file_path}'.",
                execution_time_ms=latency_ms,
            )

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    tokens_count = max(1, len(raw_output.split()))

    return ToolResult(
        tool="get_symbol",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=raw_output,
        truncated_output=raw_output,
        tokens_in_raw=tokens_count,
        tokens_in_truncated=tokens_count,
        execution_time_ms=latency_ms,
    )


def get_imports(file_path: str, repo_root: str = ".") -> ToolResult:
    """Extract all import statements from a file using AST analysis with multi-line support."""
    start_time = time.perf_counter()

    try:
        resolved = validate_path(file_path, repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="get_imports",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    if not resolved.exists():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="get_imports",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: File '{file_path}' does not exist.",
            truncated_output=f"TOOL_ERROR: File '{file_path}' does not exist.",
            execution_time_ms=latency_ms,
        )

    if resolved.is_dir():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="get_imports",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: '{file_path}' is a directory. Specify a code file.",
            truncated_output=f"TOOL_ERROR: '{file_path}' is a directory. Specify a code file.",
            execution_time_ms=latency_ms,
        )

    content = resolved.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()

    try:
        tree = ast.parse(content, filename=str(resolved))
        import_lines: List[str] = []
        import_nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        import_nodes.sort(key=lambda n: getattr(n, "lineno", 0))
        for node in import_nodes:
            start = node.lineno - 1
            end = getattr(node, "end_lineno", node.lineno)
            stmt = " ".join(line.strip() for line in lines[start:end] if line.strip())
            line_str = f"{node.lineno:3d}" if node.lineno == end else f"{node.lineno}-{end}"
            import_lines.append(f"Line {line_str}: {stmt}")
        raw_output = "\n".join(import_lines) if import_lines else "No imports found."
    except SyntaxError:
        # Fallback regex for non-Python files
        found: List[str] = []
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith(("import ", "from ", "const ", "require(", "use ")) and any(k in s for k in ("import", "require", "from", "use")):
                found.append(f"Line {i:3d}: {s}")
        raw_output = "\n".join(found) if found else "No imports found."

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    tokens_count = max(1, len(raw_output.split()))

    return ToolResult(
        tool="get_imports",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=raw_output,
        truncated_output=raw_output,
        tokens_in_raw=tokens_count,
        tokens_in_truncated=tokens_count,
        execution_time_ms=latency_ms,
    )


def find_references(
    file_path: str,
    symbol_name: str,
    repo_root: str = ".",
    context_lines: int = 3,
) -> ToolResult:
    """Find call sites and references to a symbol with accurate line numbers and directory support."""
    start_time = time.perf_counter()

    if not symbol_name or not str(symbol_name).strip():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="find_references",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output="TOOL_ERROR: symbol_name cannot be empty.",
            truncated_output="TOOL_ERROR: symbol_name cannot be empty.",
            execution_time_ms=latency_ms,
        )

    try:
        resolved = validate_path(file_path, repo_root)
    except ValueError as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="find_references",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: {e}",
            truncated_output=f"TOOL_ERROR: {e}",
            execution_time_ms=latency_ms,
        )

    if not resolved.exists():
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolResult(
            tool="find_references",
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"TOOL_ERROR: Path '{file_path}' does not exist.",
            truncated_output=f"TOOL_ERROR: Path '{file_path}' does not exist.",
            execution_time_ms=latency_ms,
        )

    pattern = re.compile(rf"\b{re.escape(symbol_name.strip())}\b")
    references: List[str] = []
    max_locations = 30
    locations_count = 0
    root_resolved = Path(repo_root).resolve()

    def _scan_file(p: Path, rel_label: str) -> None:
        nonlocal locations_count
        if p.suffix.lower() in BINARY_EXTENSIONS:
            return
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return

        file_lines = content.splitlines()
        for idx, line in enumerate(file_lines):
            if pattern.search(line):
                locations_count += 1
                start_idx = max(0, idx - context_lines)
                end_idx = min(len(file_lines), idx + context_lines + 1)
                references.append(f"--- Reference at {rel_label}:{idx + 1} ---")
                for ctx_i in range(start_idx, end_idx):
                    prefix = ">" if ctx_i == idx else " "
                    references.append(f"{ctx_i + 1:4d}:{prefix} {file_lines[ctx_i]}")

                if locations_count >= max_locations:
                    return

    if resolved.is_dir():
        for dirpath, dirnames, filenames in os.walk(resolved):
            dirnames[:] = [d for d in dirnames if d not in JUNK_DIRS and not d.endswith(".egg-info")]
            for fname in sorted(filenames):
                target_file = Path(dirpath) / fname
                rel_label = str(target_file.relative_to(root_resolved))
                _scan_file(target_file, rel_label)
                if locations_count >= max_locations:
                    break
            if locations_count >= max_locations:
                break
    else:
        _scan_file(resolved, file_path)

    if locations_count >= max_locations:
        references.append(f"\n... (capped at {max_locations} locations)")

    raw_output = "\n".join(references) if references else f"No references found for '{symbol_name}' in '{file_path}'."
    latency_ms = int((time.perf_counter() - start_time) * 1000)
    tokens_count = max(1, len(raw_output.split()))

    return ToolResult(
        tool="find_references",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output=raw_output,
        truncated_output=raw_output,
        tokens_in_raw=tokens_count,
        tokens_in_truncated=tokens_count,
        execution_time_ms=latency_ms,
    )
