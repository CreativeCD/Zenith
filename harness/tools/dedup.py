"""harness/tools/dedup.py — Tool Call Deduplicator & Reasoning Envelope Guard.

Reference: PRD.md §4.3.1, §4.3.3 | architecture.md §9.2
Prevents redundant LLM tool queries (e.g. repeated file reads) via a 10-call ring buffer,
and ensures every tool invocation states a clear reasoning intent.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any, Dict, Optional, Tuple


class ToolCallDeduplicator:
    """Ring-buffer deduplicator for tool calls with state-invalidation on edits."""

    def __init__(self, window_size: int = 10, capacity: Optional[int] = None):
        self.window_size = capacity if capacity is not None else window_size
        # Stores tuples of (fingerprint, step, tool_name, args_str)
        self.ring_buffer: deque[Tuple[str, int, str, str]] = deque(maxlen=self.window_size)
        self.total_calls_checked: int = 0
        self.total_calls_blocked: int = 0

    @staticmethod
    def compute_fingerprint(tool_name: str, args: Dict[str, Any]) -> str:
        """Compute deterministic SHA256 hash of tool name and canonical JSON args (excluding reasoning)."""
        norm_args = {k: v for k, v in args.items() if k != "reasoning"} if isinstance(args, dict) else args
        canonical_args = json.dumps(norm_args, sort_keys=True, separators=(",", ":"), default=str)
        payload = f"{tool_name}:{canonical_args}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def check_and_record(
        self,
        tool_name: str,
        args: Dict[str, Any],
        reasoning: Optional[str] = None,
        step: int = 0,
    ) -> Optional[str]:
        """Validate envelope reasoning and check for duplicate execution.

        Returns:
            None if the tool call is permitted.
            Error message string if rejected.
        """
        self.total_calls_checked += 1

        # 1. Reasoning validation (PRD §4.3.1)
        if not reasoning or not str(reasoning).strip():
            return (
                "TOOL_ERROR: Missing required field 'reasoning'. "
                "Describe your intent before calling any tool."
            )

        # 2. Mutating tools are never blocked by deduplication
        if tool_name in {"apply_patch", "write_file", "git_rollback", "edit_file"}:
            self.notify_file_modified()
            return None

        # 3. Compute fingerprint
        fingerprint = self.compute_fingerprint(tool_name, args)

        # 4. Check ring buffer
        for stored_fp, stored_step, stored_tool, stored_args_str in self.ring_buffer:
            if stored_fp == fingerprint:
                self.total_calls_blocked += 1
                return (
                    f"DEDUP: {stored_tool}({stored_args_str}) was already called at step {stored_step}. "
                    f"File unchanged. Use your observation from step {stored_step}. "
                    "Do not re-read unchanged files."
                )

        # 5. Record in buffer
        canonical_args = json.dumps(args, sort_keys=True, default=str)
        self.ring_buffer.append((fingerprint, step, tool_name, canonical_args))
        return None

    def notify_file_modified(self) -> None:
        """Invalidate ring buffer when repository files are edited."""
        self.ring_buffer.clear()


def validate_envelope(call_dict: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate that tool call envelope contains tool, reasoning, and args."""
    if not isinstance(call_dict, dict):
        return False, "Tool call must be a dictionary/JSON object."
    if "tool" not in call_dict or not call_dict["tool"]:
        return False, "Missing 'tool' field in envelope."
    reasoning = call_dict.get("reasoning")
    if not reasoning or not str(reasoning).strip():
        return False, "Missing or empty required field 'reasoning'."
    if "args" not in call_dict or not isinstance(call_dict.get("args"), dict):
        return False, "Missing or invalid 'args' field in envelope."
    return True, None

