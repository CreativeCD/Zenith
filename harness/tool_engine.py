"""harness/tool_engine.py — Centralized Tool Execution Pipeline and Function Schemas.

Reference: PRD.md §4.3 | architecture.md §9 | phases.md Task 1.18
Implements:
- 14 core tools dispatch with unified error contracts
- 8-stage execution pipeline (PRD §4.3.1)
- Mandatory 'reasoning' envelope validation
- ToolCallDeduplicator integration with cache invalidation on edits
- Pydantic models for Gemini / OpenAI / Anthropic tool declarations
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from harness.contracts import (
    AgentPhase,
    ErrorCode,
    EventType,
    ResultStatus,
    TelemetryEvent,
    ToolCall,
    ToolResult,
)
from harness.skill_retriever import SkillRetriever
from harness.telemetry import TelemetryWriter
from harness.tools.ast_tools import (
    find_references,
    get_imports,
    get_symbol,
    list_symbols,
)
from harness.tools.dedup import ToolCallDeduplicator, validate_envelope
from harness.tools.editor import apply_patch, read_file_range, write_file
from harness.tools.executor import run_bash_sandboxed, run_test_suite
from harness.tools.navigation import list_dir, search_code
from harness.tools.vcs import git_diff, git_rollback, git_status

logger = logging.getLogger(__name__)


def _safe_int(val: Any, default: int) -> int:
    """Safely convert value to integer, returning default on failure or None."""
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


# ─── Pydantic Tool Argument Schemas ──────────────────────────────────────────

class ListDirArgs(BaseModel):
    """List directory contents with depth cap (default 2, max 4), excluding junk files like .git and node_modules."""
    reasoning: str = Field(description="Step-by-step reasoning for exploring directory contents.")
    path: str = Field(default=".", description="Relative directory path to inspect.")
    depth: int = Field(default=2, description="Maximum directory traversal depth (capped at 4).")


class SearchCodeArgs(BaseModel):
    """Search repository files using fast ripgrep (or python fallback) returning matching lines with context (capped at 50 matches)."""
    reasoning: str = Field(description="Step-by-step reasoning for performing code search.")
    query: str = Field(description="Literal text or regex string to locate across the repo.")
    path: Optional[str] = Field(default=None, description="Optional subdirectory to restrict search.")


class GetSymbolArgs(BaseModel):
    """Extract signature, docstring, and preview lines for a class, function, or method (supports Class.method syntax; never whole file)."""
    reasoning: str = Field(description="Reasoning for extracting this specific symbol definition.")
    file_path: str = Field(description="Relative path of file containing the symbol.")
    symbol_name: str = Field(description="Name of class, function, or method (supports Class.method).")


class FindReferencesArgs(BaseModel):
    """Find all call sites, occurrences, and usages of a symbol across a file or directory tree with line numbers and context."""
    reasoning: str = Field(description="Reasoning for locating call sites of this symbol.")
    file_path: str = Field(description="Relative file or directory path to scan for references.")
    symbol_name: str = Field(description="Name of symbol to search call sites for.")
    context_lines: int = Field(default=3, description="Number of surrounding lines to show.")


class GetImportsArgs(BaseModel):
    """Extract all import statements and dependencies from a code file using AST parsing (supports multiline and conditional imports)."""
    reasoning: str = Field(description="Reasoning for inspecting file imports.")
    file_path: str = Field(description="Relative path to file.")


class ListSymbolsArgs(BaseModel):
    """List all top-level classes, functions, and constants defined in a source code file with their 1-indexed line numbers."""
    reasoning: str = Field(description="Reasoning for cataloging all top-level symbols.")
    file_path: str = Field(description="Relative path to file.")


class ReadFileRangeArgs(BaseModel):
    """Read a specific range of lines from a file with 1-indexed line numbers. Window capped at 250 lines to preserve context tokens."""
    reasoning: str = Field(description="Reasoning for reading this specific range.")
    file_path: str = Field(description="Relative path to file.")
    start_line: int = Field(description="1-indexed starting line number.")
    end_line: int = Field(description="1-indexed ending line number (window capped at 250 lines).")


class WriteFileArgs(BaseModel):
    """Write a new file to disk. Creates parent directories automatically. Strictly refuses to overwrite existing files (use apply_patch for edits)."""
    reasoning: str = Field(description="Reasoning for creating this new file.")
    file_path: str = Field(description="Relative path for new file (refuses overwrite if exists).")
    content: str = Field(description="Complete text content to write.")


class ApplyPatchArgs(BaseModel):
    """Apply changes to an existing file using either unified diff hunks (with context anchoring) or exact block replacement. Validates syntax and rolls back on error."""
    reasoning: str = Field(description="Reasoning for applying this code patch.")
    target_file: str = Field(description="Relative path of file to patch.")
    patch_string: Optional[str] = Field(default=None, description="Unified diff patch content.")
    old_snippet: Optional[str] = Field(default=None, description="Exact snippet to replace (exact mode).")
    new_snippet: Optional[str] = Field(default=None, description="Replacement snippet (exact mode).")


class RunTestSuiteArgs(BaseModel):
    """Execute the test suite runner (pytest, go test, npm test) with optional test filter (-k expression) and file path. 120s timeout, 80-line output cap."""
    reasoning: str = Field(description="Reasoning for executing tests.")
    test_path: Optional[str] = Field(default=None, description="Path to specific test file or directory.")
    test_filter: Optional[str] = Field(default=None, description="Test expression filter (-k expression).")
    flags: Optional[str] = Field(default=None, description="Additional runner CLI flags.")
    timeout_sec: int = Field(default=120, description="Test execution timeout in seconds.")


class RunBashSandboxedArgs(BaseModel):
    """Run a command in a sandboxed bash subprocess with 30s timeout, 512MB memory limit, and 12-pattern safety blocklist. Output capped at 200 lines."""
    reasoning: str = Field(description="Reasoning for executing sandboxed bash command.")
    command: str = Field(description="Shell command to run.")
    timeout_sec: int = Field(default=30, description="Maximum execution time in seconds.")


class GitStatusArgs(BaseModel):
    """Inspect git working tree status vs HEAD to verify modified, staged, and untracked files."""
    reasoning: str = Field(description="Reasoning for checking working tree status.")


class GitDiffArgs(BaseModel):
    """Inspect uncommitted diff changes against HEAD, optionally restricted to a specific file. Truncated at 500 lines."""
    reasoning: str = Field(description="Reasoning for inspecting diff against HEAD.")
    file_path: Optional[str] = Field(default=None, description="Optional single file to restrict diff to.")


class GitRollbackArgs(BaseModel):
    """Revert uncommitted modifications to clean HEAD state for a single file or the entire repository. Cleans untracked files and directories."""
    reasoning: str = Field(description="Reasoning for reverting changes to clean HEAD.")
    file_path: Optional[str] = Field(default=None, description="Optional single file to revert (all if omitted).")


class FetchExternalSkillArgs(BaseModel):
    """Fetch external documentation, SWE-bench problem patterns, or GitHub library skills from the cache or retriever."""
    reasoning: str = Field(description="Reasoning for fetching external skill or doc.")
    source_type: str = Field(description="Skill source: 'swe_bench' | 'github' | 'docs'.")
    query: str = Field(description="Search query or skill topic.")
    max_tokens: int = Field(default=400, description="Maximum tokens to return.")


# Registry mapping tool names to schemas and docstrings
TOOL_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "list_dir": ListDirArgs,
    "search_code": SearchCodeArgs,
    "get_symbol": GetSymbolArgs,
    "find_references": FindReferencesArgs,
    "get_imports": GetImportsArgs,
    "list_symbols": ListSymbolsArgs,
    "read_file_range": ReadFileRangeArgs,
    "write_file": WriteFileArgs,
    "apply_patch": ApplyPatchArgs,
    "run_bash_sandboxed": RunBashSandboxedArgs,
    "run_test_suite": RunTestSuiteArgs,
    "git_status": GitStatusArgs,
    "git_diff": GitDiffArgs,
    "git_rollback": GitRollbackArgs,
    "fetch_external_skill": FetchExternalSkillArgs,
}


# ─── Unified Tool Engine ─────────────────────────────────────────────────────

class ToolEngine:
    """Orchestrates validation, deduplication, sandboxed execution, and telemetry for all tools."""

    def __init__(
        self,
        repo_root: str = ".",
        deduplicator: Optional[ToolCallDeduplicator] = None,
        telemetry: Optional[TelemetryWriter] = None,
        skill_retriever: Optional[SkillRetriever] = None,
    ):
        self.repo_root = str(Path(repo_root).resolve())
        self.deduplicator = deduplicator or ToolCallDeduplicator(capacity=10)
        self.telemetry = telemetry
        self.skill_retriever = skill_retriever or SkillRetriever(
            telemetry=self.telemetry,
            cache_dir=str(Path(self.repo_root) / ".harness" / "skill_cache"),
        )

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return function calling declarations compatible with Gemini, OpenAI, and Claude."""
        definitions = []
        for name, model_cls in TOOL_SCHEMAS.items():
            schema = model_cls.model_json_schema()
            definitions.append({
                "name": name,
                "description": model_cls.__doc__ or f"Execute {name}",
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", ["reasoning"]),
                },
            })
        return definitions

    def execute(self, tool_call: ToolCall, step: int = 0) -> ToolResult:
        """Execute a tool call through the 8-stage verification pipeline."""
        tool_name = tool_call.tool
        args = tool_call.args or {}
        reasoning = tool_call.reasoning

        # Populate fingerprint on caller's tool_call object if empty
        if not tool_call.fingerprint:
            tool_call.fingerprint = self.deduplicator.compute_fingerprint(tool_name, args)

        # Stage 1 & 2: Mandatory Reasoning envelope validation
        envelope = {
            "tool": tool_name,
            "reasoning": reasoning,
            "args": args,
        }
        is_valid_envelope, env_error = validate_envelope(envelope)
        if not is_valid_envelope:
            return ToolResult(
                tool=tool_name,
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"REASONING_REQUIRED: {env_error}",
                truncated_output=f"REASONING_REQUIRED: {env_error}",
                error_code=ErrorCode.TOOL_BLOCKED,
            )

        # Stage 3: Schema recognition check
        if tool_name not in TOOL_SCHEMAS:
            return ToolResult(
                tool=tool_name,
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"TOOL_ERROR: Unknown tool '{tool_name}'. Available: {list(TOOL_SCHEMAS.keys())}",
                truncated_output=f"TOOL_ERROR: Unknown tool '{tool_name}'.",
                error_code=ErrorCode.TOOL_BLOCKED,
            )

        # Stage 4: Deduplication check
        dedup_err = self.deduplicator.check_and_record(tool_name, args, reasoning=reasoning, step=step)
        if dedup_err:
            return ToolResult(
                tool=tool_name,
                args_hash=tool_call.fingerprint,
                status=ResultStatus.FAIL,
                raw_output=dedup_err,
                truncated_output=dedup_err,
                error_code=ErrorCode.LOOP_DETECTED,
            )

        # Stage 5 & 6: Dispatch tool execution
        try:
            result = self._dispatch(tool_name, args, step=step)
        except Exception as e:
            logger.exception("Unexpected exception dispatching tool '%s': %s", tool_name, e)
            result = ToolResult(
                tool=tool_name,
                args_hash="",
                status=ResultStatus.FAIL,
                raw_output=f"TOOL_ERROR: Unexpected execution failure in {tool_name}: {e}",
                truncated_output=f"TOOL_ERROR: Unexpected execution failure in {tool_name}: {e}",
                error_code=ErrorCode.TOOL_BLOCKED,
            )

        # Attach computed args fingerprint to result
        result.args_hash = tool_call.fingerprint

        # Stage 7: Invalidate read cache if a mutating tool succeeded
        if tool_name in ("apply_patch", "write_file", "git_rollback") and result.status == ResultStatus.SUCCESS:
            self.deduplicator.notify_file_modified()

        # Ensure token estimates are populated for Phase 2 Context Manager and Telemetry
        if result.tokens_in_raw == 0 and result.raw_output:
            result.tokens_in_raw = max(1, len(result.raw_output) // 4)
        if result.tokens_in_truncated == 0 and result.truncated_output:
            result.tokens_in_truncated = max(1, len(result.truncated_output) // 4)

        # Stage 8: Telemetry event recording
        if self.telemetry:
            try:
                event = TelemetryEvent(
                    event_type=EventType.TOOL_RESULT,
                    step=step,
                    phase=AgentPhase.OBSERVE,
                    tool=tool_name,
                    tool_args_hash=result.args_hash,
                    reasoning=reasoning,
                    result_status=result.status,
                    latency_ms=result.execution_time_ms,
                    error_code=result.error_code,
                    tokens_in=result.tokens_in_raw,
                    tokens_out=result.tokens_in_truncated,
                )
                self.telemetry.append(event)
            except Exception as e:
                logger.warning("Failed to record tool telemetry: %s", e)

        return result

    def _dispatch(self, tool_name: str, args: Dict[str, Any], step: int = 0) -> ToolResult:
        """Route verified call to corresponding tool implementation."""
        root = self.repo_root

        if tool_name == "list_dir":
            return list_dir(
                path=args.get("path", "."),
                depth=_safe_int(args.get("depth"), 2),
                repo_root=root,
            )

        elif tool_name == "search_code":
            return search_code(
                query=args.get("query", ""),
                path_pattern=args.get("path") or args.get("path_pattern"),
                repo_root=root,
            )

        elif tool_name == "get_symbol":
            return get_symbol(
                file_path=args.get("file_path", ""),
                symbol_name=args.get("symbol_name", ""),
                repo_root=root,
            )

        elif tool_name == "find_references":
            return find_references(
                file_path=args.get("file_path", ""),
                symbol_name=args.get("symbol_name", ""),
                repo_root=root,
                context_lines=_safe_int(args.get("context_lines"), 3),
            )

        elif tool_name == "get_imports":
            return get_imports(
                file_path=args.get("file_path", ""),
                repo_root=root,
            )

        elif tool_name == "list_symbols":
            return list_symbols(
                file_path=args.get("file_path", ""),
                repo_root=root,
            )

        elif tool_name == "read_file_range":
            return read_file_range(
                file_path=args.get("file_path", ""),
                start_line=_safe_int(args.get("start_line"), 1),
                end_line=_safe_int(args.get("end_line"), 1),
                repo_root=root,
            )

        elif tool_name == "write_file":
            return write_file(
                file_path=args.get("file_path", ""),
                content=args.get("content", ""),
                repo_root=root,
            )

        elif tool_name == "apply_patch":
            return apply_patch(
                target_file=args.get("target_file", ""),
                repo_root=root,
                patch_string=args.get("patch_string"),
                old_snippet=args.get("old_snippet"),
                new_snippet=args.get("new_snippet"),
            )

        elif tool_name == "run_bash_sandboxed":
            return run_bash_sandboxed(
                command=args.get("command", ""),
                repo_root=root,
                timeout_sec=_safe_int(args.get("timeout_sec"), 30),
            )

        elif tool_name == "run_test_suite":
            return run_test_suite(
                repo_root=root,
                test_path=args.get("test_path"),
                test_filter=args.get("test_filter"),
                flags=args.get("flags"),
                timeout_sec=_safe_int(args.get("timeout_sec"), 120),
            )

        elif tool_name == "git_status":
            return git_status(repo_root=root)

        elif tool_name == "git_diff":
            return git_diff(
                repo_root=root,
                file_path=args.get("file_path"),
            )

        elif tool_name == "git_rollback":
            return git_rollback(
                repo_root=root,
                file_path=args.get("file_path"),
            )

        elif tool_name == "fetch_external_skill":
            source_type = str(args.get("source_type") or "swe_bench")
            q = str(args.get("query") or "")
            max_tokens = _safe_int(args.get("max_tokens"), 400)
            snippet = self.skill_retriever.fetch_skill(
                source_type=source_type,
                query=q,
                max_tokens=max_tokens,
                step=step,
            )
            return ToolResult(
                tool="fetch_external_skill",
                args_hash="",
                status=ResultStatus.SUCCESS,
                raw_output=snippet,
                truncated_output=snippet,
                tokens_in_raw=max(1, len(snippet) // 4),
                tokens_in_truncated=max(1, len(snippet) // 4),
            )

        return ToolResult(
            tool=tool_name,
            args_hash="",
            status=ResultStatus.FAIL,
            raw_output=f"Unimplemented tool: {tool_name}",
            truncated_output=f"Unimplemented tool: {tool_name}",
            error_code=ErrorCode.TOOL_BLOCKED,
        )
