"""harness/tools/security.py — Path Validation & Subprocess Command Security Guards.

Reference: PRD.md §4.3.4, §13.2 | architecture.md §18
Enforces zero path traversal outside repo root and blocks forbidden dangerous command patterns.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

# 12 Forbidden command patterns as specified in PRD §4.3.4 (hardened against evasion)
BLOCKED_PATTERNS: List[str] = [
    r"\brm\b(?=.*-[a-zA-Z-]*r)(?=.*-[a-zA-Z-]*f).*\s+[\"']?(?:/(?:\S*|$)|~|\$HOME)",  # Recursive delete on root, home, or absolute paths
    r"\|\s*(?:\S*/)?(?:sh|bash|zsh|dash|ksh)\b",  # Pipe to shell (including /bin/sh, /usr/bin/bash, zsh, dash, ksh)
    r"\bsudo\b",                     # Privilege escalation
    r"chmod\s+[0-7]*7[0-7]{2}",      # World-writable permission grant
    r"\bcurl\b",                     # Outbound network access
    r"\bwget\b",                     # Outbound network access
    r"\bdd\b",                       # Low-level disk writer
    r"\bmkfs\b",                     # Filesystem formatting
    r">\s*[\"']?/dev/(?:sd|hd|vd|nvme)",  # Raw block device write (handles quotes, modern disk names)
    r":\(\)\s*\{.*:\|:&\s*\};:|:\(\)\{.*\|.*&.*\}",  # Fork bomb
    r"base64.*\|.*(?:sh|bash|zsh|dash|ksh)",      # Obfuscated shell execution
    r"\b(?:nc|netcat)\b",                         # Netcat network shells/exfiltration
    r"\b(?:ssh|scp|sftp|rsync)\b",                # Remote file transfer and shells
    r"\b(?:nslookup|dig)\b",                      # DNS tunneling and reconnaissance
    r"python[0-9.]*\s+-c\s+.*(?:urllib|requests|socket|http\.client)",  # Python network exfiltration
    r"\bpip\s+install\b",                         # Arbitrary package installation in sandbox
]

PATH_TRAVERSAL_REGEX = re.compile(r"(^|[/\\])\.\.([/\\]|$)")


class SecurityError(Exception):
    """Raised when an operation violates harness security policies."""
    pass


def validate_path(file_path: str, repo_root: str) -> Path:
    """Validate that a target file path resides strictly inside repo_root.
    
    Raises:
        ValueError: If path attempts directory traversal or points outside repo_root.
    """
    if not file_path or not str(file_path).strip():
        raise ValueError("File path cannot be empty.")

    clean_path = str(file_path).strip()

    # Check for directory traversal tokens (platform-independent)
    if PATH_TRAVERSAL_REGEX.search(clean_path) or any(part == ".." for part in Path(clean_path).parts):
        raise ValueError(f"Path traversal detected in path: '{file_path}'")

    root = Path(repo_root).resolve()
    target = Path(clean_path)
    if not target.is_absolute():
        target = (root / target).resolve()
    else:
        target = target.resolve()

    try:
        # Check if target is relative to root
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"Target path '{file_path}' points outside repository root '{repo_root}'.")

    return target


def check_command_blocklist(command: str) -> None:
    """Inspect shell command against the 12 security blocklist patterns.
    
    Raises:
        SecurityError: If command matches any blocked pattern.
    """
    if not command:
        return

    cmd_normalized = command.strip()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cmd_normalized, flags=re.IGNORECASE):
            raise SecurityError(
                f"Command blocked by security policy: matches pattern '{pattern}'"
            )


# Env var names that commonly hold secrets. Sandboxed subprocesses must never
# inherit these: a command as simple as `echo $AI_API_KEY > file` followed by
# read_file_range would exfiltrate the key.
SECRET_ENV_REGEX = re.compile(
    r"(?i)(API_?KEY|SECRET|TOKEN|PASSW(?:OR)?D|CREDENTIAL|PRIVATE_?KEY|ACCESS_?KEY|SESSION_?KEY|\bAUTH\b)"
)


def sanitized_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return os.environ minus secret-bearing variables, plus optional extras."""
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV_REGEX.search(k)}
    if extra:
        env.update(extra)
    return env
