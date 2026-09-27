"""harness/semantic_compressor.py — Semantic Input & Observation Compression Layer.

Inspired by Ponytail (semantic LLM prompt & context compression):
1. Normalizes and strips terminal noise (ANSI escapes, carriage returns, progress artifacts)
2. Preserves semantic anchors: error types, failed assertions, file paths, line numbers, function signatures
3. Multi-tiered aging compression:
   - Turn t (active/current): Cleaned verbatim observation (up to head/tail limit)
   - Turn t-1 (previous): Compacted observation (omits passing noise, keeps critical frames)
   - Turn <= t-2 (older): Dense semantic summary (tool name, target file, key findings, status)
4. History compactor that prevents context explosion in multi-turn agent loops.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


# Regex for ANSI escape sequences (colors, cursor control)
ANSI_ESCAPE_REGEX = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Regex for common progress bars and spinner artifacts
PROGRESS_ARTIFACT_REGEX = re.compile(r"(\r|\n)\s*\[?\s*\d+%\s*\]?.*?(?=\r|\n|$)")

# Regex for Python/JS/TS class and function definitions (handles optional line number prefixes)
DEF_REGEX = re.compile(
    r"^\s*(?:(?:\d+|line\s+\d+)[:|\s]\s*)?(?:def|class|async\s+def|function|export\s+(?:default\s+)?(?:class|function))\s+([A-Za-z0-9_]+)",
    re.MULTILINE,
)


class SemanticCompressor:
    """Semantic observation and history compressor for token-optimized agent execution."""

    def __init__(self, max_verbatim_lines: int = 120, max_compact_lines: int = 40):
        self.max_verbatim_lines = max_verbatim_lines
        self.max_compact_lines = max_compact_lines

    @staticmethod
    def clean_terminal_noise(text: str) -> str:
        """Strip ANSI escapes, backspaces, carriage returns, and duplicate empty lines."""
        if not text:
            return ""

        # 1. Strip ANSI escape sequences
        cleaned = ANSI_ESCAPE_REGEX.sub("", text)

        # 2. Handle carriage return overwrites (\r) by keeping only the last segment of overwritten lines
        lines = []
        for line in cleaned.splitlines():
            if "\r" in line:
                segments = [s for s in line.split("\r") if s.strip()]
                line = segments[-1] if segments else ""
            lines.append(line.rstrip())

        # 3. Collapse multiple consecutive empty lines to at most 1 empty line
        result_lines: list[str] = []
        consecutive_empty = 0
        for line in lines:
            if not line.strip():
                consecutive_empty += 1
                if consecutive_empty <= 1:
                    result_lines.append("")
            else:
                consecutive_empty = 0
                result_lines.append(line)

        return "\n".join(result_lines).strip()

    @staticmethod
    def extract_code_signatures(code_text: str) -> list[str]:
        """Extract top-level and method definitions from code text."""
        signatures = []
        for match in DEF_REGEX.finditer(code_text):
            sig_name = match.group(1)
            signatures.append(sig_name)
        return signatures[:12]

    def compress_test_output(self, output: str, exit_code: Optional[int] = None) -> str:
        """Compress test suite output preserving failed test names and root cause traces."""
        cleaned = self.clean_terminal_noise(output)
        if not cleaned:
            return "Test output was empty."

        lines = cleaned.splitlines()

        # Success case
        if exit_code == 0 or ("passed" in cleaned.lower() and not any(kw in cleaned for kw in ("FAILED", "FAIL:", "ERROR:"))):
            summary_match = re.search(r"(\d+\s+passed[^\n\r]*)", cleaned, re.IGNORECASE)
            summary = summary_match.group(1) if summary_match else "All tests passed cleanly."
            return f"Exit code: 0\nStatus: {summary}"

        # Failure case: isolate failed test lines and first traceback
        failed_tests = []
        traceback_lines = []
        in_traceback = False
        summary_line = ""

        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(prefix) for prefix in ("FAILED ", "FAIL: ", "ERROR: ")):
                failed_tests.append(stripped)
            elif "Traceback (most recent call last):" in line:
                in_traceback = True
                traceback_lines.append(line)
            elif in_traceback:
                traceback_lines.append(line)
                # Traceback usually ends with an unindented ExceptionName: message
                if line and not line.startswith(" ") and not line.startswith("  ") and ":" in line:
                    in_traceback = False
            elif any(kw in line.lower() for kw in ("failed in", "short test summary info", "failures ==")):
                summary_line = line.strip()

        result_parts = [f"Exit code: {exit_code if exit_code is not None else 1}"]
        if failed_tests:
            result_parts.append("Failed tests:\n" + "\n".join(f"- {t}" for t in failed_tests[:8]))
        if traceback_lines:
            result_parts.append("Root cause traceback:\n" + "\n".join(traceback_lines[:30]))
        if summary_line and not failed_tests:
            result_parts.append(f"Summary: {summary_line}")

        if len(result_parts) > 1:
            return "\n\n".join(result_parts)

        # Fallback if specific failure structure wasn't extracted: take head + tail
        if len(lines) > 40:
            return "\n".join(lines[:15] + [f"[... {len(lines) - 30} lines omitted ...]"] + lines[-15:])
        return cleaned

    def compress_observation(
        self,
        tool: str,
        args: Dict[str, Any],
        raw_output: str,
        exit_code: Optional[int] = None,
        age_in_turns: int = 0,
    ) -> str:
        """Compress tool output based on its semantic nature and turn age.

        Args:
            tool: Name of the tool executed (e.g. 'read_file_range', 'run_test_suite')
            args: Arguments passed to the tool
            raw_output: Raw text output from tool execution
            exit_code: Exit code if subprocess
            age_in_turns: How many turns ago this tool was executed (0 = current turn)
        """
        cleaned = self.clean_terminal_noise(raw_output)
        if not cleaned:
            return "[Empty output]"

        # Special semantic handlers
        if tool in ("run_test_suite", "run_bash_sandboxed"):
            if "pytest" in str(args) or "test" in str(args) or "unittest" in str(args):
                cleaned = self.compress_test_output(cleaned, exit_code=exit_code)

        lines = cleaned.splitlines()

        # ── Turn age 0: Active / Most Recent Observation ──
        if age_in_turns == 0:
            if len(lines) <= self.max_verbatim_lines:
                return cleaned
            # Head + Tail with informative omission notice
            head = lines[:30]
            tail = lines[-50:]
            omitted = len(lines) - 80
            return "\n".join(head + [f"[... {omitted} lines omitted for context efficiency ...]"] + tail)

        # ── Turn age 1: Previous Turn Observation ──
        if age_in_turns == 1:
            if tool == "read_file_range":
                fp = args.get("file_path", "file")
                start = args.get("start_line", 1)
                end = args.get("end_line", len(lines))
                sigs = self.extract_code_signatures(cleaned)
                sig_desc = f" (Symbols: {', '.join(sigs)})" if sigs else ""
                if len(lines) > self.max_compact_lines:
                    head = lines[:15]
                    tail = lines[-15:]
                    return f"[File: {fp} L{start}-L{end}{sig_desc}]\n" + "\n".join(head + ["..."] + tail)
                return cleaned
            if len(lines) > self.max_compact_lines:
                head = lines[:10]
                tail = lines[-15:]
                omitted = len(lines) - 25
                return "\n".join(head + [f"[... {omitted} lines compressed ...]"] + tail)
            return cleaned

        # ── Turn age >= 2: Older Observation (Dense Semantic Summary) ──
        if tool == "read_file_range":
            fp = args.get("file_path", "file")
            start = args.get("start_line", 1)
            end = args.get("end_line", "")
            sigs = self.extract_code_signatures(cleaned)
            sig_desc = f" (Symbols: {', '.join(sigs)})" if sigs else ""
            preview = lines[0][:80] if lines else ""
            return f"[Observed {fp} L{start}-{end}{sig_desc}: {preview}...]"

        if tool in ("run_test_suite", "run_bash_sandboxed"):
            status_word = "PASSING" if exit_code == 0 else f"FAILING(exit={exit_code})"
            first_line = lines[0][:100] if lines else ""
            return f"[Test {status_word}: {first_line}]"

        if tool == "search_code":
            query = args.get("query", "")
            match_count = len(lines)
            return f"[search_code('{query}'): Found {match_count} matches]"

        if tool in ("apply_patch", "write_file", "git_rollback"):
            target = args.get("target_file", args.get("file_path", ""))
            return f"[{tool} on {target}: Succeeded]"

        # Default dense summary
        summary = lines[0][:100] if lines else "Done"
        return f"[{tool}: {summary}]"

    def compact_history(
        self,
        history: List[Dict[str, str]],
        keep_recent_pairs: int = 4,
    ) -> Tuple[List[Dict[str, str]], int]:
        """Compact older tool observation pairs in conversation history.

        Args:
            history: Full list of message dicts (role, content)
            keep_recent_pairs: How many recent tool exchanges to keep in full detail

        Returns:
            (compacted_history, estimated_tokens_saved)
        """
        if not history:
            return history, 0

        # Identify tool observation user messages:
        # Pattern: role == 'user' and content.startswith('Observation from `')
        obs_indices = [
            i for i, msg in enumerate(history)
            if msg.get("role") == "user" and "Observation from `" in msg.get("content", "")
        ]

        if len(obs_indices) <= keep_recent_pairs:
            return list(history), 0

        # Indices that need compaction: all except the last keep_recent_pairs
        to_compact = obs_indices[:-keep_recent_pairs]
        compacted: List[Dict[str, str]] = []
        tokens_saved = 0

        # Age calculation: relative to latest observation
        total_obs = len(obs_indices)

        for i, msg in enumerate(history):
            if i in to_compact:
                obs_pos = obs_indices.index(i)
                age = total_obs - 1 - obs_pos
                content = msg.get("content", "")
                original_len = len(content)

                # Header formats:
                #   "Observation from `{tool}` args={json}:\n..."  (current)
                #   "Observation from `{tool}`:\n..."              (legacy)
                first_line, sep, body = content.partition("\n")
                header_match = re.match(
                    r"Observation from `(\w+)`(?: args=(\{.*\}))?:$", first_line
                )
                if header_match and sep:
                    tool_name = header_match.group(1)
                    raw_args = header_match.group(2)
                    try:
                        parsed_args = json.loads(raw_args) if raw_args else {}
                        if not isinstance(parsed_args, dict):
                            parsed_args = {}
                    except (ValueError, TypeError):
                        parsed_args = {}
                    compact_body = self.compress_observation(
                        tool=tool_name,
                        args=parsed_args,
                        raw_output=body,
                        age_in_turns=age,
                    )
                    new_content = f"Observation from `{tool_name}` (compacted):\n{compact_body}"
                else:
                    # Generic compaction
                    lines = content.splitlines()
                    new_content = "\n".join(lines[:3] + [f"[... {max(0, len(lines) - 4)} lines compacted ...]"] + lines[-1:])

                new_len = len(new_content)
                tokens_saved += max(0, (original_len - new_len) // 4)
                compacted.append({"role": "user", "content": new_content})
            else:
                compacted.append(dict(msg))

        return compacted, tokens_saved
