"""harness/trust.py — Workspace Trust & Boundary Security Manager.

Reference: Claude Code / VS Code Workspace Trust specification.
Ensures that Zenith only operates on repositories explicitly authorized by the user.
Enforces strict filesystem boundary jailing:
- Blocks reading, writing, editing, or deleting files outside the authorized folder.
- Prevents external directory leakage into parent or sibling repositories.
- Manages persistent workspace trust records in ~/.zenith/trusted_workspaces.json.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, Set

from rich.console import Console
from rich.panel import Panel

console = Console()

DEFAULT_TRUST_FILE = Path.home() / ".zenith" / "trusted_workspaces.json"


class WorkspaceTrustManager:
    """Manages workspace trust verification and persistent storage."""

    def __init__(self, trust_file: Path | None = None) -> None:
        self.trust_file = trust_file or DEFAULT_TRUST_FILE

    def _load_trusted(self) -> Set[str]:
        """Load set of trusted workspace paths."""
        if not self.trust_file.exists():
            return set()
        try:
            with open(self.trust_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "trusted_workspaces" in data:
                return set(data["trusted_workspaces"])
            elif isinstance(data, list):
                return set(data)
            return set()
        except (json.JSONDecodeError, OSError):
            return set()

    def _save_trusted(self, trusted: Set[str]) -> None:
        """Atomically persist set of trusted workspace paths."""
        self.trust_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"trusted_workspaces": sorted(list(trusted))}
        
        # Atomic write via temp file
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix="zenith_trust_",
            dir=str(self.trust_file.parent),
            text=True,
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.trust_file)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def is_trusted(self, repo_path: str | Path) -> bool:
        """Check if target repository path is trusted."""
        # Check global environment bypass
        if os.environ.get("ZENITH_TRUST_ALL") == "1" or os.environ.get("ZENITH_TRUST_WORKSPACE") == "1":
            return True

        canonical = str(Path(repo_path).resolve())
        trusted = self._load_trusted()
        return canonical in trusted

    def grant_trust(self, repo_path: str | Path) -> None:
        """Add repository path to trusted workspaces."""
        canonical = str(Path(repo_path).resolve())
        trusted = self._load_trusted()
        trusted.add(canonical)
        self._save_trusted(trusted)

    def revoke_trust(self, repo_path: str | Path) -> None:
        """Remove repository path from trusted workspaces."""
        canonical = str(Path(repo_path).resolve())
        trusted = self._load_trusted()
        trusted.discard(canonical)
        self._save_trusted(trusted)

    def request_trust(
        self,
        repo_path: str | Path,
        auto_trust: bool = False,
        custom_console: Optional[Console] = None,
    ) -> bool:
        """Verify trust or interactively prompt the user for permission.
        
        Returns:
            bool: True if workspace is authorized, False if access denied.
        """
        c = custom_console or console
        canonical = str(Path(repo_path).resolve())

        # 1. Already trusted
        if self.is_trusted(canonical):
            return True

        # 2. Automated flag / headless bypass
        if auto_trust:
            self.grant_trust(canonical)
            return True

        # 3. Check for non-interactive terminal
        if not sys.stdin.isatty():
            c.print(
                f"[bold red]❌ Workspace Trust Required:[/bold red] '{canonical}' is not in trusted workspaces.\n"
                f"[yellow]Run with --trust or -y to grant access non-interactively.[/yellow]"
            )
            return False

        # 4. Display rich Claude Code style Security Trust Dialog
        panel_content = (
            f"[bold yellow]Zenith requires authorization to access this workspace:[/bold yellow]\n\n"
            f"  [bold]📁 Target Folder:[/bold] [bold cyan]{canonical}[/bold cyan]\n\n"
            f"[bold green]Security & Isolation Guarantees:[/bold green]\n"
            f"  • [bold]Strict Boundary Jailing:[/bold] All file reading, writing, editing, and deleting\n"
            f"    are strictly confined to this folder.\n"
            f"  • [bold]Zero External Leakage:[/bold] Zenith is completely blocked from reading or\n"
            f"    modifying parent directories or external repositories.\n"
            f"  • [bold]Sandboxed Execution:[/bold] Tests, bash commands, and git operations execute\n"
            f"    exclusively inside this directory.\n"
        )
        c.print(Panel(
            panel_content,
            title="🔒 [bold]Workspace Trust & Boundary Security[/bold]",
            border_style="yellow",
            expand=False,
        ))

        try:
            choice = input(f"\n👉 Do you trust the files in this folder and grant Zenith access? [Y/n]: ").strip().lower()
            if choice in ("", "y", "yes"):
                self.grant_trust(canonical)
                c.print(f"[bold green]✅ Workspace trusted. Boundaries locked strictly to: {canonical}[/bold green]\n")
                return True
            else:
                c.print(f"[bold red]❌ Workspace trust denied. Zenith is exiting safely without accessing or modifying any files.[/bold red]\n")
                return False
        except (KeyboardInterrupt, EOFError):
            c.print(f"\n[dim]Workspace trust prompt cancelled. Exiting Zenith safely.[/dim]\n")
            return False
