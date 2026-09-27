"""harness/interactive.py — Interactive Claude Code Style REPL for Zenith.

Provides:
- Claude Code-grade autonomous engineering workflow on ANY cloned GitHub repository
- Automatic repository profiling (language, stack, manifest, architecture from README)
- Dynamic execution & health checks ("run the project to itself" to detect failures)
- Deep-dive codebase audit for bugs, logic loopholes, and missing error handling
- Context window preparation, token budgeting, and working memory management
- Multi-step task planning ([ ] 1. Explore, [ ] 2. Patch, [ ] 3. Verify)
- Custom and internet skills integration (/skills, /skills install <url>, get_skill)
- Live step-by-step tool execution with deduplication and loop prevention
- Rich terminal UI with markdown rendering, syntax highlighting, and command history
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from harness.adapters.gemini_adapter import GeminiAdapter
from harness.config import HarnessConfig
from harness.context_manager import (
    ContextManager,
    TurnRecord,
    count_tokens,
    format_working_memory,
    truncate_observation,
)
from harness.contracts import (
    Complexity,
    ErrorCode,
    IssuePlan,
    ResultStatus,
    SuspectedFile,
    TaskType,
    ToolCall,
    ToolResult,
)
from harness.issue_parser import IssueParser
from harness.repo_intel import RepoIndexBuilder
from harness.semantic_compressor import SemanticCompressor
from harness.skills.manager import SkillDefinition, SkillManager
from harness.tool_engine import ToolEngine
from harness.tools.executor import run_test_suite
from harness.tools.navigation import list_dir, search_code
from harness.tools.vcs import git_diff, git_rollback, git_status

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style as PromptStyle
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

console = Console()


SYSTEM_REPL_PROMPT = """You are Zenith, an expert autonomous AI software engineer (inspired by Claude Code).
You operate directly inside the repository at: {repo_path}

CORE OPERATIONAL RULES:
1. Strict Jailed Boundary: You are strictly jailed to {repo_path}. All file reads, writes, edits, and test runs must stay inside this repository.
2. Intent & Tool Calling:
   - When the user is chatting, greeting you, or asking general/status questions (e.g. "what are you doing?", "what can you do?", "how does this work?"):
     Respond directly, concisely, and naturally in markdown text. Do NOT call tools for conversational queries.
   - When given an engineering task (inspecting, debugging, auditing, writing features, running tests):
     Call the appropriate native function tools systematically.
   - NEVER output pseudo-tool text such as "Invoked tool ... with args ..." or "Action: ...". Use native function calls.
   - Call get_skill(skill_name='...') if you need detailed instructions for an installed skill.
3. Deep-Dive Engineering Discipline:
   - Understand the project's intended architecture, design, and behavior from its README, config, and source files.
   - Investigate the root causes of any runtime crashes, logic loopholes, unhandled edge cases, or broken assumptions.
   - Apply clean, idiomatic, minimal patches via apply_patch (or write_file).
   - Run tests or verification checks via run_test_suite to ensure 0 failures and complete regression safety.
4. Transparency:
   - Keep actions focused, purposeful, and quiet.
   - Synthesize your findings clearly when the task is verified.
5. Autonomous Completion:
   - Once you have gathered sufficient information, inspected the necessary files, or verified a fix, call emit_done_candidate or synthesize your final findings in clear markdown and conclude without calling further tools.

{skills_block}
"""


class ZenithREPL:
    """Claude Code style interactive terminal REPL for Zenith."""

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self.repo_path = str(Path(config.repo_path).resolve())
        self.skill_manager = SkillManager(repo_root=self.repo_path)
        self.semantic_compressor = SemanticCompressor()
        self.context_manager = ContextManager(
            config=getattr(config, "context", None),
            output_dir=str(Path(self.repo_path) / ".harness"),
            adapter=None,
        )
        self.repo_index_builder = RepoIndexBuilder(repo_path=self.repo_path)
        from harness.adapters.factory import get_model_adapter
        self.adapter = get_model_adapter(config.model)
        self.context_manager.adapter = self.adapter
        self.tool_engine = ToolEngine(
            repo_root=self.repo_path,
            skill_manager=self.skill_manager,
        )
        self.tool_definitions = self.tool_engine.get_tool_definitions()
        self.history: list[dict[str, str]] = []
        self.active_issue: IssuePlan | None = None
        self.active_plan: list[dict[str, Any]] = []
        self.session_active = True
        self.step_counter = 0

        # Initialize prompt session
        hist_file = Path.home() / ".zenith_history"
        if HAS_PROMPT_TOOLKIT:
            pt_style = PromptStyle.from_dict({
                "prompt": "#00d7af bold",
                "arrow": "#5f87d7 bold",
            })
            self.prompt_session = PromptSession(
                history=FileHistory(str(hist_file)),
                style=pt_style,
            )
        else:
            self.prompt_session = None

    def _build_system_prompt(self) -> str:
        """Construct system prompt with jailed repo path and installed skills."""
        skills_summary = self.skill_manager.format_skills_for_prompt()
        if skills_summary.strip():
            skills_block = f"INSTALLED SKILLS:\n{skills_summary}\nCall get_skill(skill_name='<name>') to load full instructions for any skill."
        else:
            skills_block = "No custom skills installed. You can install skills using /skills install <url_or_repo>."

        return SYSTEM_REPL_PROMPT.format(
            repo_path=self.repo_path,
            skills_block=skills_block,
        )

    # ─── GENERAL REPOSITORY INTELLIGENCE & PROFILING ───────────────────────────

    def profile_repository(self) -> dict[str, Any]:
        """Dynamically inspect and profile any repository without hardcoding.

        Extracts:
        - Project stack (Python, Node/TS, Go, Rust, etc.)
        - Manifest details (package.json, pyproject.toml, etc.)
        - README documentation and intended functionality
        - Source files and directories
        - Test runner and build scripts
        """
        root = Path(self.repo_path)
        profile: dict[str, Any] = {
            "name": root.name,
            "path": str(root),
            "stack": "General",
            "manifest": "",
            "readme_summary": "",
            "readme_file": "",
            "test_runner": "None",
            "source_dirs": [],
            "test_dirs": [],
            "source_files": [],
            "total_source_files": 0,
        }

        # 1. Detect Stack and Manifest
        if (root / "package.json").exists():
            profile["stack"] = "Node.js / TypeScript" if any(root.glob("tsconfig*.json")) else "Node.js / JavaScript"
            profile["manifest"] = "package.json"
            profile["test_runner"] = "npm test"
        elif any((root / f).exists() for f in ("pyproject.toml", "setup.py", "requirements.txt", "Pipfile")):
            profile["stack"] = "Python"
            profile["manifest"] = "pyproject.toml" if (root / "pyproject.toml").exists() else "setup.py"
            profile["test_runner"] = "pytest"
        elif (root / "go.mod").exists():
            profile["stack"] = "Go"
            profile["manifest"] = "go.mod"
            profile["test_runner"] = "go test ./..."
        elif (root / "Cargo.toml").exists():
            profile["stack"] = "Rust"
            profile["manifest"] = "Cargo.toml"
            profile["test_runner"] = "cargo test"

        # 2. Read README / Architecture documentation
        readme_candidates = ["README.md", "README.rst", "README.txt", "README", "docs/index.md", "architecture.md"]
        for rc in readme_candidates:
            rp = root / rc
            if rp.is_file() and rp.stat().st_size > 0:
                try:
                    lines = rp.read_text(encoding="utf-8", errors="ignore").splitlines()
                    non_empty = [l.strip() for l in lines if l.strip()][:40]
                    profile["readme_summary"] = "\n".join(non_empty)
                    profile["readme_file"] = rc
                    break
                except Exception:
                    pass

        # 3. Discover source directories and key files
        src_candidates = ["src", "lib", "app", "harness", "pkg", "cmd", "billing", "core"]
        for sc in src_candidates:
            sp = root / sc
            if sp.is_dir():
                profile["source_dirs"].append(sc)

        test_candidates = ["tests", "test", "__tests__", "spec"]
        for tc in test_candidates:
            tp = root / tc
            if tp.is_dir():
                profile["test_dirs"].append(tc)

        # Count total source code files
        code_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".php"}
        all_files = []
        for r, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".harness", "__pycache__", ".venv", "venv", "dist", "build")]
            for f in files:
                p = Path(r) / f
                if p.suffix in code_exts:
                    all_files.append(str(p.relative_to(root)))
        profile["source_files"] = all_files[:60]
        profile["total_source_files"] = len(all_files)

        return profile

    def print_welcome_banner(self) -> None:
        """Render a sleek startup banner showcasing repository intelligence."""
        profile = self.profile_repository()
        repo_name = profile["name"]
        key_pool = getattr(self.adapter, "key_pool", None)
        key_count = key_pool.total_keys if key_pool else (1 if getattr(self.adapter, "api_key", None) else 0)
        model_name = self.config.model.name
        skills_count = len(self.skill_manager.discover_skills())

        stack_str = f"[bold green]{profile['stack']}[/bold green]"
        if profile["test_runner"] != "None":
            stack_str += f" [dim]({profile['test_runner']} detected)[/dim]"

        file_count_str = f"[cyan]{profile['total_source_files']} source files[/cyan]"
        if profile["source_dirs"]:
            file_count_str += f" [dim]({', '.join(profile['source_dirs'])})[/dim]"

        readme_preview = ""
        if profile.get("readme_summary"):
            first_line = profile["readme_summary"].splitlines()[0]
            clean_first = first_line.lstrip("#").strip()
            if clean_first:
                readme_preview = f"\n[bold]Overview[/bold] : [dim]{clean_first[:80]}[/dim]"

        banner_text = (
            f"[bold cyan]⚡ ZENITH CODE[/bold cyan] [dim]— Autonomous AI Engineer (Claude Code style)[/dim]\n"
            f"[bold]Repo[/bold]     : [green]{repo_name}[/green] [dim]({self.repo_path})[/dim]\n"
            f"[bold]Project[/bold]  : {stack_str} • {file_count_str}\n"
            f"[bold]Trust[/bold]    : [bold green]🔒 Verified & Jailed strictly to this folder[/bold green]\n"
            f"[bold]Model[/bold]    : [cyan]{model_name}[/cyan] [dim]({key_count} active keys)[/dim]\n"
            f"[bold]Skills[/bold]   : [cyan]{skills_count} installed[/cyan] [dim](Type /skills to list)[/dim]{readme_preview}\n"
            f"[bold]Commands[/bold] : Type [bold cyan]/scan[/bold cyan] to deep-dive audit codebase, [bold cyan]/plan <goal>[/bold cyan] to plan, [bold cyan]/help[/bold cyan] for all commands."
        )
        console.print(Panel(banner_text, border_style="cyan", expand=False))
        console.print("")

    def print_help(self) -> None:
        """Display interactive commands help."""
        table = Table(title="Zenith Interactive Commands", border_style="dim")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")

        table.add_row("/scan, /audit, /debug", "Deep-dive audit codebase: run project, find bugs, loopholes & fix them")
        table.add_row("/plan <task>", "Formulate an explicit multi-step plan before execution")
        table.add_row("/skills", "List all installed custom & internet skills")
        table.add_row("/skills show <name>", "Display detailed instructions for an installed skill")
        table.add_row("/skills install <src>", "Install a skill from GitHub, URL, or local folder")
        table.add_row("/context", "Display token usage breakdown and working memory")
        table.add_row("/test", "Run repo test suite and show results")
        table.add_row("/diff", "Display git diff of uncommitted changes")
        table.add_row("/status", "Show git status of the working tree")
        table.add_row("/rollback", "Revert uncommitted changes cleanly to HEAD")
        table.add_row("/clear", "Clear terminal screen and chat view")
        table.add_row("/help", "Show this help menu")
        table.add_row("exit, quit, bye", "Exit the interactive session")

        console.print(table)
        console.print("\n[dim]💡 Tip: You can also chat naturally! E.g. 'find the issues and bugs in the project', 'where are the loopholes?', or 'install skill https://...'.[/dim]\n")

    # ─── OPTIONAL ISSUE SPECIFICATION DISCOVERY ─────────────────────────────────

    def discover_issues(self) -> list[tuple[str, Path]]:
        """Optional scan for issue files if user happens to have one."""
        root = Path(self.repo_path)
        found: list[tuple[str, Path]] = []

        root_candidates = [
            "issue.txt", "issues.txt", "ISSUE.md", "problem.txt",
            "bug.txt", "bugs.txt", "task.txt", "TASK.md", "instructions.txt",
        ]
        for name in root_candidates:
            p = root / name
            if p.is_file() and p.stat().st_size > 0:
                found.append((name, p))

        issue_dirs = ["issues", ".issues", "eval_issues", "tasks", ".tasks"]
        for dname in issue_dirs:
            dp = root / dname
            if dp.is_dir():
                for f in sorted(dp.glob("*")):
                    if f.is_file() and f.suffix in (".md", ".txt") and f.stat().st_size > 0:
                        found.append((f"{dname}/{f.name}", f))

        return found

    def load_issue(self, issue_path: Path) -> IssuePlan:
        """Parse issue file into an IssuePlan and configure ContextManager."""
        parser = IssueParser()
        plan = parser.parse_issue(str(issue_path), repo_path=self.repo_path)
        self.active_issue = plan
        self.context_manager.set_issue(plan)
        return plan

    # ─── SKILLS MANAGEMENT ───────────────────────────────────────────────────

    def show_skills(self) -> None:
        """Display table of all discovered skills."""
        skills = self.skill_manager.discover_skills()
        if not skills:
            console.print("[dim]No skills installed yet.[/dim]")
            console.print("To install a skill: [bold cyan]/skills install <github_repo_or_url>[/bold cyan]\n")
            return

        table = Table(title="Installed Skills", border_style="cyan")
        table.add_column("Skill Name", style="bold cyan", no_wrap=True)
        table.add_column("Source", style="green", no_wrap=True)
        table.add_column("Description", style="white")

        for name, sk in sorted(skills.items()):
            table.add_row(name, sk.source_type, sk.description)

        console.print(table)
        console.print("\n[dim]To view instructions: /skills show <name>  |  To install: /skills install <source>[/dim]\n")

    def show_skill_details(self, skill_name: str) -> None:
        """Show full markdown instructions for a skill."""
        sk = self.skill_manager.get_skill(skill_name)
        if not sk:
            console.print(f"[bold red]Skill '{skill_name}' not found.[/bold red]")
            return

        console.print(Panel(
            Markdown(sk.instructions),
            title=f"Skill: {sk.name} ({sk.source_type})",
            border_style="cyan",
        ))

    def install_skill_interactive(self, source: str) -> None:
        """Install a skill from a URL, Git repo, or local path."""
        with console.status(f"[bold cyan]Installing skill from {source}...[/bold cyan]", spinner="dots"):
            installed = self.skill_manager.install_skill(source)

        if installed:
            console.print(f"[bold green]✅ Successfully installed skill: '{installed.name}'[/bold green]")
            console.print(f"   [dim]Location: {installed.path}[/dim]")
            console.print(f"   [dim]Description: {installed.description}[/dim]\n")
        else:
            console.print(f"[bold red]❌ Failed to install skill from '{source}'. Please check URL or path.[/bold red]\n")

    # ─── CONTEXT & WORKING MEMORY DISPLAY ─────────────────────────────────────

    def show_context(self) -> None:
        """Display current context token breakdown and working memory."""
        wm_str = format_working_memory(self.context_manager.working_memory)
        persona_str = self.context_manager.build_persona_section()
        goal_str = self.context_manager.build_goal_section()
        turns_str = self.context_manager.render_turns(self.context_manager.turns)

        persona_tok = count_tokens(persona_str)
        goal_tok = count_tokens(goal_str)
        wm_tok = count_tokens(wm_str)
        turns_tok = count_tokens(turns_str)
        total_tok = persona_tok + goal_tok + wm_tok + turns_tok
        max_tok = self.context_manager.budget_manager.max_context_tokens

        table = Table(title="Context Window Token Breakdown", border_style="dim")
        table.add_column("Section", style="cyan")
        table.add_column("Tokens", style="bold green", justify="right")
        table.add_column("% of Budget", style="dim", justify="right")

        table.add_row("§1 System Persona", str(persona_tok), f"{(persona_tok/max_tok)*100:.1f}%")
        table.add_row("§2 Active Goal", str(goal_tok), f"{(goal_tok/max_tok)*100:.1f}%")
        table.add_row("§3 Working Memory", str(wm_tok), f"{(wm_tok/max_tok)*100:.1f}%")
        table.add_row("§5 Recent Turns", str(turns_tok), f"{(turns_tok/max_tok)*100:.1f}%")
        table.add_row("[bold]Total In-Use[/bold]", f"[bold]{total_tok}[/bold]", f"[bold]{(total_tok/max_tok)*100:.1f}%[/bold]")

        console.print(table)
        console.print(Panel(wm_str, title="Working Memory (Active State)", border_style="blue"))

    # ─── DIRECT REPO ACTIONS ─────────────────────────────────────────────────

    def run_tests_direct(self) -> ToolResult:
        """Run project tests directly."""
        with console.status("[bold cyan]🧪 Running test runner...[/bold cyan]", spinner="dots"):
            res = run_test_suite(repo_root=self.repo_path)
        if res.exit_code == 0:
            console.print("[bold green]✅ All tests passed cleanly![/bold green]")
        else:
            console.print(f"[bold red]❌ Tests failed (Exit code: {res.exit_code})[/bold red]")
        console.print(Panel(res.truncated_output, title="Test Output", border_style="dim"))
        return res

    def show_diff(self) -> None:
        """Show current git diff."""
        res = git_diff(repo_root=self.repo_path)
        if res.status == ResultStatus.SUCCESS and res.raw_output and not res.raw_output.startswith("Working tree clean"):
            syntax = Syntax(res.raw_output, "diff", theme="monokai", line_numbers=True)
            console.print(Panel(syntax, title="Git Diff", border_style="green"))
        else:
            console.print("[dim]Working tree clean. No uncommitted diffs.[/dim]")

    def show_status(self) -> None:
        """Show current git status."""
        res = git_status(repo_root=self.repo_path)
        console.print(Panel(res.raw_output, title="Git Status", border_style="blue"))

    def rollback_changes(self) -> None:
        """Roll back all uncommitted changes."""
        confirm = input("⚠️  Revert all uncommitted working tree changes? (y/N): ").strip().lower()
        if confirm == "y":
            res = git_rollback(repo_root=self.repo_path)
            console.print(f"[bold yellow]{res.raw_output}[/bold yellow]")
        else:
            console.print("[dim]Rollback cancelled.[/dim]")

    # ─── CLAUDE CODE STYLE PLANNING & ISSUE ENGINE ────────────────────────────

    def render_plan(self, plan: list[dict[str, Any]]) -> None:
        """Display multi-step execution plan."""
        table = Table(title="📋 Action Plan", border_style="cyan")
        table.add_column("Step", style="bold cyan", width=6)
        table.add_column("Status", width=12)
        table.add_column("Description", style="white")

        for item in plan:
            stat = item.get("status", "pending")
            if stat == "completed":
                stat_str = "[bold green]✅ Done[/bold green]"
            elif stat == "in_progress":
                stat_str = "[bold yellow]🔄 Active[/bold yellow]"
            else:
                stat_str = "[dim]⏳ Pending[/dim]"
            table.add_row(str(item["step"]), stat_str, item["desc"])

        console.print(table)
        console.print("")

    def formulate_plan(
        self,
        goal: str,
        suspected_files: list[str],
        has_test_failure: bool,
    ) -> list[dict[str, Any]]:
        """Formulate a 4-step Claude Code style plan."""
        suspected_hint = f" ({', '.join(suspected_files)})" if suspected_files else ""
        plan = [
            {
                "step": 1,
                "status": "pending",
                "desc": f"Deep-dive inspect codebase{suspected_hint} to understand intended logic and flow",
            },
            {
                "step": 2,
                "status": "pending",
                "desc": "Identify flaws, broken edge cases, unhandled errors, and loopholes",
            },
            {
                "step": 3,
                "status": "pending",
                "desc": "Apply clean, minimal patches to fix issues and close loopholes",
            },
            {
                "step": 4,
                "status": "pending",
                "desc": "Run test suite / project verification to ensure all checks pass with 0 regressions",
            },
        ]
        self.active_plan = plan
        return plan

    async def autonomous_investigation(self, query: str = "") -> None:
        """Deep-dive codebase audit and autonomous bug/loophole repair engine.

        Operates on ANY arbitrary cloned repository without requiring any issue.txt file:
        1. Reads project README, architecture, manifests (package.json, pyproject.toml, etc.) to understand intended design.
        2. Runs test suite or execution checks to observe runtime health, crashes, or failures.
        3. Scans source tree for syntax errors, broken imports, missing dependencies, or unhandled exceptions.
        4. Dispatches autonomous AI agent to inspect core logic flows, identify loopholes, edge-case vulnerabilities, and bugs.
        5. Formulates a concrete action plan and autonomously repairs and verifies the codebase.
        """
        console.print("\n[bold cyan]🔬 Deep Codebase Audit & Autonomous Investigation Activated[/bold cyan]")
        console.print("[dim]Profiling repository architecture, intended behavior, and runtime health...[/dim]\n")

        # ── Step 1: Profile the Repository & Read Blueprint ──
        profile = self.profile_repository()
        stack_desc = profile["stack"]
        total_files = profile["total_source_files"]
        source_dirs = ", ".join(profile["source_dirs"]) if profile["source_dirs"] else "root"

        profile_table = Table(title="Repository Blueprint", border_style="cyan")
        profile_table.add_column("Property", style="bold cyan")
        profile_table.add_column("Details", style="white")
        profile_table.add_row("Repository", f"{profile['name']} ({self.repo_path})")
        profile_table.add_row("Stack / Ecosystem", stack_desc)
        profile_table.add_row("Source Structure", f"{total_files} source files in {source_dirs}")
        if profile.get("manifest"):
            profile_table.add_row("Manifest File", profile["manifest"])
        if profile.get("readme_file"):
            profile_table.add_row("Documentation", profile["readme_file"])

        console.print(profile_table)

        # ── Step 2: Dynamic Execution Check ("Run it to itself") ──
        console.print("\n[dim]Running dynamic health checks & test runner...[/dim]")
        test_res = run_test_suite(repo_root=self.repo_path)
        has_test_failures = (test_res.exit_code != 0)

        if has_test_failures:
            console.print(f"[bold red]❌ Dynamic Execution Failure Detected (Exit code: {test_res.exit_code})[/bold red]")
            console.print(Panel(test_res.truncated_output[:1200], title="Failure Traceback / Test Errors", border_style="red"))
            self.context_manager.update_working_memory(
                test_status=f"FAILING (exit code {test_res.exit_code}): {test_res.truncated_output[:200]}",
            )
        else:
            if "collected 0 items" in test_res.raw_output or test_res.raw_output.strip().startswith("No tests"):
                console.print("[yellow]ℹ️  No automated test suite discovered. Proceeding to source code audit.[/yellow]")
                self.context_manager.update_working_memory(
                    test_status="NO_TESTS_FOUND: Code audit required",
                )
            else:
                console.print(f"[bold green]✅ Test Suite Cleanly Executed[/bold green] [dim]({test_res.truncated_output[:100]}...)[/dim]")
                console.print("[dim]Proceeding to deep-dive source audit for logic loopholes, unhandled edge cases, and missing features.[/dim]")
                self.context_manager.update_working_memory(
                    test_status="PASSING: Inspecting for logic loopholes & unhandled edge cases",
                )

        # ── Step 3: Static & Syntax Sanity Audit ──
        syntax_errors: list[str] = []
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".harness", "__pycache__", ".venv", "venv", "dist", "build")]
            for f in files:
                if f.endswith(".py"):
                    full_p = Path(root) / f
                    try:
                        compile(full_p.read_text(encoding="utf-8", errors="ignore"), str(full_p), "exec")
                    except SyntaxError as e:
                        rel = os.path.relpath(str(full_p), self.repo_path)
                        syntax_errors.append(f"{rel}:{e.lineno}: {e.msg}")

        if syntax_errors:
            console.print(f"[bold red]⚠️  Detected {len(syntax_errors)} Syntax / Compilation Error(s):[/bold red]")
            for se in syntax_errors[:5]:
                console.print(f"   [red]• {se}[/red]")

        # ── Step 4: Optional Issue Specification Context (if user supplied one) ──
        optional_issue_text = ""
        discovered_issues = self.discover_issues()
        if discovered_issues:
            label, ipath = discovered_issues[0]
            try:
                optional_issue_text = f"\n\nOPTIONAL ISSUE SPECIFICATION ({label}):\n```\n{ipath.read_text(encoding='utf-8')[:2000]}\n```"
            except Exception:
                pass

        # ── Step 5: Formulate Action Plan ──
        goal = query.strip() or f"Deep audit of {profile['name']} to identify bugs, loopholes, and missing features"
        plan = self.formulate_plan(
            goal=goal,
            suspected_files=profile["source_files"][:5],
            has_test_failure=has_test_failures,
        )
        self.render_plan(plan)

        # ── Step 6: Dispatch Autonomous Agent Deep-Dive ──
        readme_snippet = profile.get("readme_summary", "No README available.")[:1500]
        test_snippet = test_res.truncated_output[:1200]
        source_files_preview = ", ".join(profile["source_files"][:25])

        investigation_prompt = (
            f"AUDIT GOAL: {goal}\n\n"
            f"REPOSITORY BLUEPRINT:\n"
            f"- Project Name: {profile['name']}\n"
            f"- Stack: {profile['stack']}\n"
            f"- Manifest: {profile.get('manifest', 'None')}\n"
            f"- Source Files: {source_files_preview}\n\n"
            f"PROJECT DOCUMENTATION & INTENDED BEHAVIOR:\n"
            f"```\n{readme_snippet}\n```\n\n"
            f"DYNAMIC RUNTIME & TEST OUTPUT:\n"
            f"```\n{test_snippet}\n```\n\n"
            f"SYNTAX & COMPILATION CHECK:\n"
            f"{'Syntax errors: ' + ', '.join(syntax_errors) if syntax_errors else 'No syntax errors detected.'}\n"
            f"{optional_issue_text}\n\n"
            f"AUDIT INSTRUCTIONS:\n"
            f"1. Use search_code, list_dir, and read_file_range to inspect the main entry points, core logic, and key files.\n"
            f"2. Check if the project is actually working according to its intended plan and requirements.\n"
            f"3. Find where it has bugs, runtime crashes, missing error handling, unhandled edge cases, or logic loopholes.\n"
            f"4. If bugs or loopholes are found, apply minimal, clean patches using apply_patch / write_file.\n"
            f"5. Run run_test_suite (or execute the project) to verify that everything works cleanly with zero regressions.\n"
            f"6. Conclude with a complete markdown summary of issues found, files inspected, and fixes applied when done. Do not continue calling tools once your verification is complete.\n\n"
            f"Start your deep-dive inspection now."
        )

        await self.execute_autonomous_loop(investigation_prompt)

    async def auto_debug(self) -> None:
        """Backward-compatible alias for autonomous_investigation."""
        await self.autonomous_investigation()

    # ─── AUTONOMOUS TOOL EXECUTION LOOP ───────────────────────────────────────

    def _format_tool_status_line(self, tc: ToolCall, tool_res: ToolResult) -> str:
        """Format a clean, concise single-line tool status indicator like Claude Code."""
        if tool_res.error_code == ErrorCode.LOOP_DETECTED:
            return f"  [yellow]⚠️  Loop Prevention:[/] [dim]{tc.tool} already called with these args. Skipping repeat.[/dim]"

        icon = "✅" if tool_res.status == ResultStatus.SUCCESS else "❌"

        if tc.tool == "read_file_range":
            fp = tc.args.get("file_path", "")
            start = tc.args.get("start_line", 1)
            end = tc.args.get("end_line", "")
            return f"  {icon} [cyan]Read file:[/] [bold]{fp}[/bold] [dim](lines {start}-{end})[/dim]"
        elif tc.tool == "search_code":
            q = tc.args.get("query", "")
            return f"  {icon} [cyan]Search code:[/] [bold]'{q}'[/bold]"
        elif tc.tool == "list_dir":
            p = tc.args.get("path", ".") or "."
            return f"  {icon} [cyan]List dir:[/] [bold]{p}[/bold]"
        elif tc.tool in ("run_test_suite", "run_bash_sandboxed"):
            cmd_desc = tc.args.get("command", "pytest") if tc.tool == "run_bash_sandboxed" else "test suite"
            exit_code_str = f"exit {tool_res.exit_code}" if tool_res.exit_code is not None else ""
            return f"  {icon} [cyan]Run {cmd_desc}:[/] [dim]({exit_code_str})[/dim]"
        elif tc.tool == "apply_patch":
            tf = tc.args.get("target_file", "")
            return f"  {icon} [green]Applied patch:[/] [bold]{tf}[/bold]"
        elif tc.tool == "write_file":
            fp = tc.args.get("file_path", "")
            return f"  {icon} [green]Wrote file:[/] [bold]{fp}[/bold]"
        elif tc.tool == "git_diff":
            return f"  {icon} [cyan]Inspect git diff[/cyan]"
        elif tc.tool == "get_symbol":
            sym = tc.args.get("symbol_name", "")
            return f"  {icon} [cyan]Get symbol:[/] [bold]{sym}[/bold]"
        elif tc.tool == "emit_done_candidate":
            return f"  {icon} [bold green]Emit done candidate (verification complete)[/bold green]"
        else:
            return f"  {icon} [cyan]{tc.tool}[/cyan] [dim]({tool_res.status.value})[/dim]"

    async def execute_autonomous_loop(self, initial_prompt: str) -> None:
        """Multi-turn autonomous execution loop with deduplication, loop prevention, and memory."""
        self.history.append({"role": "user", "content": initial_prompt})

        max_turns = max(getattr(self.config.agent, "max_steps", 40), 40)
        current_turn = 0
        loop_detections_in_a_row = 0
        modified_files: set[str] = set()

        system_prompt = self._build_system_prompt()

        while current_turn < max_turns:
            current_turn += 1
            self.step_counter += 1

            # 1. Semantic Input Compression: compact older observations to preserve context
            self.history, tokens_saved = self.semantic_compressor.compact_history(
                self.history,
                keep_recent_pairs=3,
            )

            # 2. Prepare working memory summary with active directives
            wm_text = format_working_memory(self.context_manager.working_memory)
            directives = []
            if self.context_manager.working_memory.files_examined:
                files_str = ", ".join(f"`{f}`" for f in list(self.context_manager.working_memory.files_examined.keys())[:8])
                directives.append(f"- Already inspected: {files_str}. Do NOT re-read these sections unless modified.")
            if self.context_manager.working_memory.edits_applied:
                edits_str = "; ".join(self.context_manager.working_memory.edits_applied[:5])
                directives.append(f"- Edits applied: {edits_str}. Verify with run_test_suite or git_diff.")
            if self.context_manager.working_memory.test_status and "PASSING" in self.context_manager.working_memory.test_status:
                directives.append("- Test suite is PASSING. Avoid redundant re-runs without code modifications.")

            if directives:
                wm_text += "\n\n### ACTIVE EXECUTION DIRECTIVES\n" + "\n".join(directives)

            full_system_prompt = f"{system_prompt}\n\n{wm_text}"

            # 3. Context token budget check & snapshot
            total_prompt_tokens = count_tokens(full_system_prompt) + sum(count_tokens(str(m.get("content", ""))) for m in self.history)
            if self.context_manager.budget_manager.is_compression_needed(total_prompt_tokens):
                self.context_manager.summarizer.write_snapshot(self.context_manager.working_memory)
                self.history, _ = self.semantic_compressor.compact_history(self.history, keep_recent_pairs=2)

            with console.status(f"[bold cyan]🧠 Step {current_turn}/{max_turns}: Thinking & inspecting...[/bold cyan]", spinner="dots"):
                response = await self.adapter.complete(
                    system_prompt=full_system_prompt,
                    user_message="",
                    history=self.history,
                    tools=self.tool_definitions,
                    temperature=0.1,
                )

            # Text-to-tool parsing fallback
            if not response.tool_calls and response.content and hasattr(self.adapter, "_parse_tool_calls_from_text"):
                parsed_calls = self.adapter._parse_tool_calls_from_text(response.content)
                if parsed_calls:
                    response.tool_calls = parsed_calls
                    response.content = ""

            # Check for tool calls
            if response.tool_calls:
                for tc in response.tool_calls:
                    if not tc.reasoning or not str(tc.reasoning).strip():
                        tc.reasoning = f"Execute {tc.tool}"

                    tool_res = self.tool_engine.execute(tc)
                    tool_res = self.context_manager.process_tool_result(tool_res)

                    console.print(self._format_tool_status_line(tc, tool_res))

                    if tool_res.error_code == ErrorCode.LOOP_DETECTED:
                        loop_detections_in_a_row += 1
                        tool_feedback = (
                            f"Tool `{tc.tool}` blocked by Loop Prevention:\n{tool_res.truncated_output}\n"
                            f"You already executed this exact call. DO NOT repeat it. "
                            f"Synthesize what you have learned from your observations or move to the next phase."
                        )
                    else:
                        loop_detections_in_a_row = 0
                        tool_feedback = (
                            f"Tool `{tc.tool}` executed with status {tool_res.status.value}.\n"
                            f"Output:\n{tool_res.truncated_output}"
                        )

                    # ── Handle emit_done_candidate early completion ──
                    if tc.tool == "emit_done_candidate":
                        turn_rec = TurnRecord(
                            step=self.step_counter,
                            tool=tc.tool,
                            reasoning=tc.reasoning,
                            args=tc.args,
                            observation="DONE_CANDIDATE recorded",
                            status=tool_res.status,
                            exit_code=tool_res.exit_code,
                        )
                        self.context_manager.add_turn(turn_rec)
                        self.history.append({"role": "model", "content": f"I executed tool `{tc.tool}` ({tc.reasoning})"})
                        self.history.append({"role": "user", "content": "Done candidate accepted. Synthesize your final summary."})
                        if self.active_plan and len(self.active_plan) > 3:
                            self.active_plan[3]["status"] = "completed"
                        break

                    # ── Update Working Memory based on tool executed ──
                    if tc.tool == "read_file_range":
                        fp = tc.args.get("file_path", "")
                        self.context_manager.update_working_memory(
                            file_examined=(fp, f"Read lines {tc.args.get('start_line')}-{tc.args.get('end_line')}"),
                        )
                    elif tc.tool == "search_code":
                        q = tc.args.get("query", "")
                        self.context_manager.update_working_memory(
                            strategy=f"Searched for '{q}'",
                        )
                    elif tc.tool == "apply_patch":
                        tf = tc.args.get("target_file", "")
                        if tool_res.status == ResultStatus.SUCCESS:
                            modified_files.add(tf)
                        self.context_manager.update_working_memory(
                            edit_applied=f"Patched {tf}",
                        )
                    elif tc.tool == "write_file":
                        fp = tc.args.get("file_path", "")
                        if tool_res.status == ResultStatus.SUCCESS:
                            modified_files.add(fp)
                        self.context_manager.update_working_memory(
                            edit_applied=f"Created {fp}",
                        )
                    elif tc.tool == "run_test_suite":
                        stat_str = "PASSING (0 errors)" if tool_res.exit_code == 0 else f"FAILING (exit code {tool_res.exit_code})"
                        self.context_manager.update_working_memory(
                            test_status=stat_str,
                        )

                    # ── Update Active Action Plan dynamically ──
                    if self.active_plan:
                        if tc.tool in ("read_file_range", "search_code", "list_dir", "get_symbol"):
                            if self.active_plan[0]["status"] == "pending":
                                self.active_plan[0]["status"] = "in_progress"
                        elif tc.tool in ("apply_patch", "write_file"):
                            self.active_plan[0]["status"] = "completed"
                            if len(self.active_plan) > 1:
                                self.active_plan[1]["status"] = "completed"
                            if len(self.active_plan) > 2:
                                self.active_plan[2]["status"] = "completed"
                            if len(self.active_plan) > 3:
                                self.active_plan[3]["status"] = "in_progress"
                        elif tc.tool == "run_test_suite":
                            if len(self.active_plan) > 3:
                                if tool_res.exit_code == 0:
                                    self.active_plan[3]["status"] = "completed"
                                else:
                                    self.active_plan[3]["status"] = "in_progress"

                    # ── Record TurnRecord in ContextManager ──
                    turn_rec = TurnRecord(
                        step=self.step_counter,
                        tool=tc.tool,
                        reasoning=tc.reasoning,
                        args=tc.args,
                        observation=tool_res.truncated_output,
                        status=tool_res.status,
                        exit_code=tool_res.exit_code,
                    )
                    self.context_manager.add_turn(turn_rec)

                    # Append to conversational history for next turn
                    self.history.append({"role": "model", "content": f"I executed tool `{tc.tool}` ({tc.reasoning})"})
                    self.history.append({"role": "user", "content": f"Observation from `{tc.tool}`:\n{tool_feedback}"})

                # If model hit 3 consecutive loop detections, force termination with summary
                if loop_detections_in_a_row >= 3:
                    console.print("\n[bold yellow]⚠️  Loop limit reached. Synthesizing current findings...[/bold yellow]\n")
                    break

                # Continue next tool iteration
                continue

            # Model produced a textual answer / summary
            if response.content:
                console.print(f"\n[bold cyan]Zenith ❯[/bold cyan]")
                md = Markdown(response.content)
                console.print(md)
                console.print("")
                self.history.append({"role": "model", "content": response.content})
                break
            else:
                break

        # ── Final Verification Gate (ONLY if files were modified in THIS loop execution) ──
        if modified_files:
            diff_res = git_diff(repo_root=self.repo_path)
            if diff_res.status == ResultStatus.SUCCESS and diff_res.raw_output and not diff_res.raw_output.startswith("Working tree clean"):
                syntax = Syntax(diff_res.raw_output, "diff", theme="monokai", line_numbers=True)
                console.print(Panel(syntax, title="Verified Git Diff", border_style="green"))

                final_tests = run_test_suite(repo_root=self.repo_path)
                if final_tests.exit_code == 0:
                    console.print("[bold green]✅ Test suite verification: ALL TESTS PASSING CLEANLY[/bold green]\n")
                else:
                    console.print(f"[bold yellow]⚠️  Verification note: Test suite returned exit code {final_tests.exit_code}[/bold yellow]\n")

    # ─── NATURAL LANGUAGE ROUTER ─────────────────────────────────────────────

    def _is_conversational_or_informational(self, msg: str) -> bool:
        """Determine if a user message is a conversational query, greeting, or identity/folder question."""
        cleaned = msg.strip().lower()
        words = set(re.findall(r"\w+", cleaned))

        # 1. Greetings
        greetings = {"hi", "hello", "hey", "hola", "yo", "howdy", "sup", "greetings"}
        if cleaned in greetings or any(cleaned.startswith(f"{g} ") for g in greetings):
            return True

        # 2. Pleasantries / acknowledgments
        pleasantries = {"thanks", "thank you", "ok", "okay", "cool", "nice", "awesome", "great", "sure", "got it", "fine"}
        if cleaned in pleasantries:
            return True

        # 3. Identity & self-inquiries ("what is ur name", "who are you", "what are you", "who made you")
        if any(phrase in cleaned for phrase in (
            "your name", "ur name", "who are you", "who r u", "what are you", "what r u",
            "what can you do", "tell me about yourself", "who made you", "what is zenith"
        )):
            return True

        # 4. Status inquiries ("what are you doing", "what r u doing", "what's up", "how are you")
        if any(phrase in cleaned for phrase in (
            "what are you doing", "what r u doing", "what are u doing", "what you doing",
            "what are you working on", "what is your status", "whats up", "what's up",
            "how are you", "how are you doing", "how r u", "how do you work", "how does it work"
        )):
            return True

        # 5. Repo / folder / directory inquiries ("what is this folder name", "what folder is this", "what is the repo name")
        action_verbs = {"fix", "repair", "edit", "change", "modify", "patch", "write", "create", "delete", "remove", "add", "run", "test", "debug"}
        if not words.intersection(action_verbs):
            if any(phrase in cleaned for phrase in (
                "folder name", "flolder name", "directory name", "repo name", "repository name",
                "project name", "what folder", "what repo", "what project", "where am i", "current folder", "current directory"
            )):
                return True

        return False

    async def handle_conversational_message(self, user_msg: str) -> None:
        """Handle conversational chit-chat, greetings, and status inquiries dynamically via LLM."""
        self.history.append({"role": "user", "content": user_msg})

        profile = self.profile_repository()
        repo_name = profile["name"]
        stack = profile["stack"]
        active_issue_str = f"Active task: {self.active_issue.primary_goal}" if self.active_issue else "No active task currently."
        files_examined_list = list(self.context_manager.working_memory.files_examined.keys())
        examined_str = f"Files inspected: {', '.join(files_examined_list)}" if files_examined_list else "No files inspected yet."

        system_prompt = (
            f"You are Zenith, an expert AI software engineering assistant (inspired by Claude Code).\n"
            f"You are operating in repository '{repo_name}' ({stack}).\n"
            f"Repository root directory: {self.repo_path}\n"
            f"Current state: {active_issue_str}. {examined_str}.\n\n"
            f"CONVERSATIONAL GUIDELINES:\n"
            f"- The user is chatting with you or asking an informational question (greeting, identity/name, status, folder/repository info, or general discussion).\n"
            f"- Respond directly, concisely, and naturally as an intelligent engineering partner.\n"
            f"- DO NOT call tools or emit tool JSON. Answer conversationally in markdown text.\n"
            f"- If the user asks for your name or identity, state that your name is Zenith, an autonomous AI software engineer.\n"
            f"- If the user asks about the folder, directory, or repository name, tell them the repository name is '{repo_name}' located at '{self.repo_path}'.\n"
            f"- If the user asks what you are doing, explain your current state in {repo_name}, mention what you can do (inspect code, diagnose bugs, run test suites, apply fixes), and invite them to give you a task or issue to work on.\n"
            f"- Be conversational, helpful, and natural (avoid repetitive canned phrases)."
        )

        reply = ""
        # If adapter has keys, call the LLM!
        has_keys = bool(
            getattr(self.adapter, "api_key", None)
            or (getattr(self.adapter, "key_pool", None) and self.adapter.key_pool.total_keys > 0)
        )
        if has_keys:
            with console.status("[bold cyan]Zenith is thinking...[/bold cyan]", spinner="dots"):
                try:
                    response = await self.adapter.complete(
                        system_prompt=system_prompt,
                        user_message="",
                        history=self.history,
                        temperature=0.7,
                    )
                    if response.content and not response.content.startswith("[GEMINI_ERROR"):
                        reply = response.content.strip()
                except Exception:
                    pass

        # Fallback if no API key or API call failed
        if not reply:
            cleaned = user_msg.strip().lower()
            if any(cleaned.startswith(g) for g in ("hi", "hello", "hey", "hola", "yo", "greetings", "howdy", "sup")):
                reply = f"Hello! I'm Zenith, your AI engineering assistant in **{repo_name}**. What would you like to build, inspect, or fix in this project today?"
            elif any(k in cleaned for k in ("name", "who are you", "what are you", "what can you do", "ur name", "your name")):
                reply = f"I am Zenith, an expert autonomous AI software engineer. I'm operating in **{repo_name}** ({stack}). How can I help you today?"
            elif any(k in cleaned for k in ("folder", "flolder", "directory", "repo", "project name", "where am i")):
                reply = f"The folder name (or repository name) is **{repo_name}** (`{self.repo_path}`)."
            elif "what" in cleaned and ("doing" in cleaned or "working on" in cleaned or "status" in cleaned):
                reply = f"I'm currently standing by in **{repo_name}** ({stack}). I'm ready to inspect code, diagnose bugs, run tests, or implement fixes. What task would you like to work on?"
            elif any(k in cleaned for k in ("thanks", "thank you", "ok", "okay", "cool", "nice", "awesome", "great", "sure", "got it")):
                reply = f"You're welcome! Let me know if you want me to inspect code, run tests, or solve any issues in **{repo_name}**."
            else:
                reply = f"I'm here in **{repo_name}** and ready to help. You can ask me to find bugs, inspect files, or run tests."

        console.print(f"\n[bold cyan]Zenith ❯[/bold cyan] {reply}\n")
        self.history.append({"role": "model", "content": reply})

    async def process_user_message(self, user_msg: str) -> None:
        """Process natural language request or route to specialized engines."""
        cleaned = user_msg.strip().lower()

        # 1. Exits
        if cleaned in ("bye", "goodbye", "cya", "exit", "quit"):
            console.print("\n[bold cyan]Zenith ❯[/bold cyan] Goodbye! Happy coding! 🚀\n")
            self.session_active = False
            return

        # 2. Conversational Queries, Greetings, Identity & Folder Questions (dynamic via LLM)
        if self._is_conversational_or_informational(user_msg):
            await self.handle_conversational_message(user_msg)
            return

        # 3. Deep Codebase Audit & Autonomous Investigation Triggers
        investigation_triggers = [
            "find issue", "find the issue", "find issues", "find the issues",
            "find bug", "find the bug", "find bugs", "find the bugs",
            "find error", "find the error", "find errors", "find the errors",
            "scan project", "scan repo", "audit project", "audit repo", "audit codebase",
            "deep dive", "diagnose", "where are the loopholes", "find loopholes",
            "fix issue", "fix the issue", "fix bugs", "fix the bug",
            "fix error", "fix failing", "what are the issues", "what are the bugs",
            "what is missing", "check if the project is working", "is the project working",
        ]
        if any(trig in cleaned for trig in investigation_triggers):
            await self.autonomous_investigation(query=user_msg)
            return

        # 4. Skills Query Triggers ("what skills", "list skills", "install skill")
        if cleaned.startswith("install skill "):
            src = user_msg.strip()[14:].strip()
            self.install_skill_interactive(src)
            return

        if any(trig in cleaned for trig in ("what skills", "list skills", "show skills", "installed skills")):
            self.show_skills()
            return

        # 5. General autonomous coding loop
        await self.execute_autonomous_loop(user_msg)

    # ─── API KEY SETUP & SESSION RUNNER ───────────────────────────────────────

    def _ensure_api_key(self) -> bool:
        """Prompt user for API key if no keys are found in environment."""
        has_keys = bool(
            getattr(self.adapter, "api_key", None)
            or (getattr(self.adapter, "key_pool", None) and self.adapter.key_pool.total_keys > 0)
        )
        if has_keys:
            return True

        console.print(Panel(
            "[yellow bold]🔑 No Google Gemini API key found![/yellow bold]\n\n"
            "Zenith requires [bold cyan]1 free API key[/bold cyan] from Google AI Studio.\n"
            "Get your free key in 15 seconds at: [bold link=https://aistudio.google.com/]https://aistudio.google.com/[/bold link]",
            border_style="yellow",
            expand=False,
        ))

        try:
            key_input = input("\n👉 Paste your Gemini API key (or press Ctrl+C to cancel): ").strip()
            if not key_input:
                console.print("[red]No key provided. Exiting.[/red]")
                return False

            zenith_env_dir = Path.home() / ".zenith"
            zenith_env_dir.mkdir(parents=True, exist_ok=True)
            env_path = zenith_env_dir / ".env"
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nAI_API_KEY={key_input}\n")
            os.environ["AI_API_KEY"] = key_input

            from harness.adapters.key_pool import KeyPoolManager
            self.adapter.key_pool = KeyPoolManager(keys=[key_input])
            console.print("[bold green]✅ API key saved globally to ~/.zenith/.env! You're ready to code.[/bold green]\n")
            return True
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Cancelled.[/dim]")
            return False

    async def start(self) -> None:
        """Main interactive REPL loop."""
        from harness.trust import WorkspaceTrustManager
        trust_mgr = WorkspaceTrustManager()
        auto_trust = getattr(self.config, "trust", False)
        if not trust_mgr.request_trust(self.repo_path, auto_trust=auto_trust):
            return

        self.print_welcome_banner()

        if not self._ensure_api_key():
            return

        while self.session_active:
            try:
                if HAS_PROMPT_TOOLKIT and self.prompt_session:
                    user_input = await self.prompt_session.prompt_async([
                        ("class:arrow", "zenith "),
                        ("class:prompt", "❯ "),
                    ])
                else:
                    user_input = input("zenith ❯ ")

                user_input = user_input.strip()
                if not user_input:
                    continue

                # ── Built-in slash commands ──
                cmd_lower = user_input.lower()

                if cmd_lower in ("exit", "quit", ":q"):
                    console.print("[dim]Exiting Zenith. Goodbye![/dim]")
                    break

                if cmd_lower == "/help":
                    self.print_help()
                    continue

                if cmd_lower == "/clear":
                    os.system("clear")
                    self.print_welcome_banner()
                    continue

                if cmd_lower in ("/scan", "/audit", "/debug", "/issues"):
                    await self.autonomous_investigation()
                    continue

                if cmd_lower == "/test":
                    self.run_tests_direct()
                    continue

                if cmd_lower == "/diff":
                    self.show_diff()
                    continue

                if cmd_lower == "/status":
                    self.show_status()
                    continue

                if cmd_lower == "/rollback":
                    self.rollback_changes()
                    continue

                if cmd_lower == "/context":
                    self.show_context()
                    continue

                if cmd_lower == "/skills":
                    self.show_skills()
                    continue

                if cmd_lower.startswith("/skills show "):
                    sname = user_input[13:].strip()
                    self.show_skill_details(sname)
                    continue

                if cmd_lower.startswith("/skills install "):
                    src = user_input[16:].strip()
                    self.install_skill_interactive(src)
                    continue

                if cmd_lower.startswith("/plan"):
                    goal_arg = user_input[5:].strip() or "Describe what you would like to plan"
                    plan = self.formulate_plan(goal_arg, [], False)
                    self.render_plan(plan)
                    continue

                # Process natural language request
                await self.process_user_message(user_input)

            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Session interrupted. Exiting Zenith.[/dim]")
                break
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")


def launch_interactive_repl(config: HarnessConfig) -> int:
    """Launch the interactive REPL synchronously."""
    repl = ZenithREPL(config=config)
    try:
        asyncio.run(repl.start())
        return 0
    except Exception as e:
        console.print(f"[bold red]REPL Error:[/bold red] {e}")
        return 1
