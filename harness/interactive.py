"""harness/interactive.py — Interactive Claude Code Style REPL for Zenith.

Provides:
- Claude Code-grade autonomous engineering workflow
- Context window preparation, token budgeting, and working memory management
- Multi-step task planning ([ ] 1. Explore, [ ] 2. Patch, [ ] 3. Verify)
- Autonomous Diagnostic & Issue Engine ("find the issues, find bugs and errors", /debug)
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
2. Autonomous Tool Calling:
   - When inspecting files, editing code, or running tests, ALWAYS call the appropriate function tool.
   - NEVER output pseudo-tool text such as "Invoked tool ... with args ..." or "Action: ...". Use native tool calls.
   - Call get_skill(skill_name='...') if you need detailed instructions for an installed skill.
3. Multi-Step Engineering Discipline:
   - Step 1: Inspect suspected files to identify the exact root cause.
   - Step 2: Formulate a minimal, idiomatic fix satisfying all acceptance criteria without breaking existing tests.
   - Step 3: Apply the patch cleanly via apply_patch.
   - Step 4: Run the test suite via run_test_suite to verify 0 failures and regression safety.
4. Transparency:
   - Explain your rationale concisely before or after taking tool actions.
   - Synthesize your findings clearly when the task is verified.

{skills_block}
"""


class ZenithREPL:
    """Claude Code style interactive terminal REPL for Zenith."""

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self.repo_path = str(Path(config.repo_path).resolve())
        self.skill_manager = SkillManager(repo_root=self.repo_path)
        self.context_manager = ContextManager(
            output_dir=str(Path(self.repo_path) / ".harness"),
            adapter=None,
        )
        self.repo_index_builder = RepoIndexBuilder(repo_path=self.repo_path)
        self.adapter = GeminiAdapter(
            model_name=config.model.name,
            key_pool=None,
        )
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

    def print_welcome_banner(self) -> None:
        """Render a sleek startup banner."""
        repo_name = Path(self.repo_path).name
        key_count = self.adapter.key_pool.total_keys
        model_name = self.config.model.name
        skills_count = len(self.skill_manager.discover_skills())

        # Check if an issue file is already present
        issues = self.discover_issues()
        issue_status = f"[bold green]{len(issues)} issue file(s) detected[/bold green]" if issues else "[dim]None detected (ready for queries)[/dim]"

        banner_text = (
            f"[bold cyan]⚡ ZENITH CODE[/bold cyan] [dim]— Autonomous AI Engineer (Claude Code style)[/dim]\n"
            f"[bold]Repo[/bold]     : [green]{repo_name}[/green] [dim]({self.repo_path})[/dim]\n"
            f"[bold]Trust[/bold]    : [bold green]🔒 Verified & Jailed strictly to this folder[/bold green]\n"
            f"[bold]Model[/bold]    : [cyan]{model_name}[/cyan] [dim]({key_count} active keys)[/dim]\n"
            f"[bold]Skills[/bold]   : [cyan]{skills_count} installed[/cyan] [dim](Type /skills to list or install)[/dim]\n"
            f"[bold]Issues[/bold]   : {issue_status}\n"
            f"[bold]Commands[/bold] : Type [bold cyan]/help[/bold cyan] for commands, [bold cyan]/debug[/bold cyan] to auto-detect & fix bugs, [bold red]exit[/bold red] to quit."
        )
        console.print(Panel(banner_text, border_style="cyan", expand=False))
        console.print("")

    def print_help(self) -> None:
        """Display interactive commands help."""
        table = Table(title="Zenith Interactive Commands", border_style="dim")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")

        table.add_row("/debug, /scan", "Autonomous Diagnostic Engine: detect issues, failing tests, and fix bugs")
        table.add_row("/plan <task>", "Formulate a multi-step plan before execution (Claude Code style)")
        table.add_row("/skills", "List all installed custom & internet skills")
        table.add_row("/skills show <name>", "Display detailed instructions for an installed skill")
        table.add_row("/skills install <src>", "Install a skill from GitHub, URL, or local folder")
        table.add_row("/context", "Display token usage breakdown and working memory")
        table.add_row("/test", "Run repo test suite (pytest) and show results")
        table.add_row("/diff", "Display git diff of uncommitted changes")
        table.add_row("/status", "Show git status of the working tree")
        table.add_row("/rollback", "Revert uncommitted changes cleanly to HEAD")
        table.add_row("/clear", "Clear terminal screen and chat view")
        table.add_row("/help", "Show this help menu")
        table.add_row("exit, quit, bye", "Exit the interactive session")

        console.print(table)
        console.print("\n[dim]💡 Tip: You can also chat naturally! E.g. 'find the issues and bugs in the project', 'explain discounts.py', or 'install skill https://...'.[/dim]\n")

    # ─── VIRTUAL FILESYSTEM & ISSUE DISCOVERY ─────────────────────────────────

    def discover_issues(self) -> list[tuple[str, Path]]:
        """Scan repository for issue files (issue.txt, issues/*.md, tasks, etc.)."""
        root = Path(self.repo_path)
        found: list[tuple[str, Path]] = []

        # 1. Root single files
        root_candidates = [
            "issue.txt", "issues.txt", "ISSUE.md", "problem.txt",
            "bug.txt", "bugs.txt", "task.txt", "TASK.md", "instructions.txt",
        ]
        for name in root_candidates:
            p = root / name
            if p.is_file() and p.stat().st_size > 0:
                found.append((name, p))

        # 2. Issue directories
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

        # Working memory panel
        console.print(Panel(wm_str, title="Working Memory (Active State)", border_style="blue"))

    # ─── DIRECT REPO ACTIONS ─────────────────────────────────────────────────

    def run_tests_direct(self) -> ToolResult:
        """Run pytest directly on the target repo."""
        with console.status("[bold cyan]🧪 Running test suite...[/bold cyan]", spinner="dots"):
            res = run_test_suite(repo_root=self.repo_path)
        if res.exit_code == 0:
            console.print("[bold green]✅ All tests passed cleanly![/bold green]")
        else:
            console.print(f"[bold red]❌ Test suite failed (Exit code: {res.exit_code})[/bold red]")
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
                "desc": f"Inspect suspected codebase location{suspected_hint} and understand context",
            },
            {
                "step": 2,
                "status": "pending",
                "desc": "Identify root cause and formulate minimal, robust fix adhering to acceptance criteria",
            },
            {
                "step": 3,
                "status": "pending",
                "desc": "Apply clean patch using apply_patch / write_file",
            },
            {
                "step": 4,
                "status": "pending",
                "desc": "Run test suite to verify 0 failures and ensure no regressions",
            },
        ]
        self.active_plan = plan
        return plan

    async def autonomous_investigation(self, query: str = "") -> None:
        """Autonomous Diagnostic Engine: scans issues, tests, syntax, and fixes bugs."""
        console.print("\n[bold cyan]🔍 Autonomous Diagnostic & Issue Engine Activated[/bold cyan]")
        console.print("[dim]Scanning repository for issues, test failures, and bug specifications...[/dim]\n")

        # ── Step 1: Discover and Load Issue Specifications
        discovered = self.discover_issues()
        active_issue_file: Path | None = None
        issue_plan: IssuePlan | None = None

        if discovered:
            # Select first active issue file
            active_label, active_issue_file = discovered[0]
            console.print(f"[bold green]🎯 Found issue specification:[/bold green] [cyan]{active_label}[/cyan]")
            issue_plan = self.load_issue(active_issue_file)

            criteria_bullets = "\n".join(f"  • {c}" for c in issue_plan.acceptance_criteria) or "  • Fix bug cleanly"
            suspected_names = [sf.path for sf in issue_plan.suspected_files]
            suspected_str = ", ".join(suspected_names) if suspected_names else "To be discovered"

            panel_content = (
                f"[bold]Title[/bold]              : {issue_plan.primary_goal}\n"
                f"[bold]File[/bold]               : {active_label}\n"
                f"[bold]Suspected Path[/bold]     : [yellow]{suspected_str}[/yellow]\n"
                f"[bold]Complexity[/bold]         : {issue_plan.complexity_estimate.value}\n"
                f"[bold]Acceptance Criteria[/bold]:\n{criteria_bullets}"
            )
            console.print(Panel(panel_content, title="Active Target Issue", border_style="cyan"))
        else:
            console.print("[dim]No explicit issue files (issue.txt / issues/*.md) found. Checking test suite...[/dim]")

        # ── Step 2: Diagnostic Baseline Test Suite Run
        console.print("[dim]Running test runner to establish baseline failure state...[/dim]")
        test_res = run_test_suite(repo_root=self.repo_path)
        has_test_failure = (test_res.exit_code != 0)

        if has_test_failure:
            console.print(f"[bold red]❌ Baseline test failure confirmed (Exit code: {test_res.exit_code})[/bold red]")
            console.print(Panel(test_res.truncated_output[:1000], title="Failure Traceback", border_style="red"))
            self.context_manager.update_working_memory(
                test_status=f"FAILING (exit code {test_res.exit_code})",
            )
        else:
            console.print("[green]ℹ️ Existing test suite currently passes.[/green]")
            if issue_plan:
                console.print("[dim]The issue specifies an untested bug or regression that requires reproduction.[/dim]")
            self.context_manager.update_working_memory(
                test_status="PASSING (Baseline). Bug reproduction or regression test required.",
            )

        # ── Step 3: Syntax Sanity Scan
        syntax_errors: list[str] = []
        for root, _, files in os.walk(self.repo_path):
            if any(j in root for j in (".git", ".harness", "__pycache__", ".venv", "venv")):
                continue
            for f in files:
                if f.endswith(".py"):
                    full_p = Path(root) / f
                    try:
                        compile(full_p.read_text(encoding="utf-8"), str(full_p), "exec")
                    except SyntaxError as e:
                        rel = os.path.relpath(str(full_p), self.repo_path)
                        syntax_errors.append(f"{rel}:{e.lineno}: {e.msg}")

        if syntax_errors:
            console.print(f"[bold red]⚠️  Detected {len(syntax_errors)} Python syntax error(s):[/bold red]")
            for se in syntax_errors[:5]:
                console.print(f"   [red]• {se}[/red]")

        # If nothing is broken and no issue file exists
        if not issue_plan and not has_test_failure and not syntax_errors:
            diff_res = git_diff(repo_root=self.repo_path)
            if diff_res.status == ResultStatus.SUCCESS and diff_res.raw_output and not diff_res.raw_output.startswith("Working tree clean"):
                console.print("\n[yellow]No explicit issues found, but uncommitted changes exist:[/yellow]")
                self.show_diff()
            else:
                console.print("\n[bold green]✅ Clean repository audit![/bold green] All tests pass, no syntax errors, and no issue files found.")
                console.print("[dim]If there is a specific feature or bug you want me to work on, describe it or use /plan <goal>.[/dim]\n")
            return

        # ── Step 4: Formulate Action Plan
        goal = issue_plan.primary_goal if issue_plan else "Investigate and resolve repository test/syntax failures"
        suspected_files = [sf.path for sf in issue_plan.suspected_files] if issue_plan else []
        plan = self.formulate_plan(goal, suspected_files, has_test_failure)
        self.render_plan(plan)

        # Update working memory strategy
        self.context_manager.update_working_memory(
            strategy=f"Execute 4-step plan for '{goal}'",
        )

        # ── Step 5: Build Autonomous Agent Prompt & Execute
        issue_context_str = ""
        if active_issue_file and active_issue_file.exists():
            issue_context_str = f"\n\nISSUE SPECIFICATION ({active_issue_file.name}):\n```\n{active_issue_file.read_text(encoding='utf-8')}\n```"

        test_failure_context = ""
        if has_test_failure:
            test_failure_context = f"\n\nCURRENT TEST FAILURE:\n```\n{test_res.truncated_output[:1500]}\n```"

        syntax_context = ""
        if syntax_errors:
            syntax_context = f"\n\nSYNTAX ERRORS DETECTED:\n" + "\n".join(syntax_errors)

        investigation_prompt = (
            f"GOAL: {goal}\n"
            f"{issue_context_str}"
            f"{test_failure_context}"
            f"{syntax_context}\n\n"
            f"ACTION PLAN:\n"
            f"1. Read and inspect the relevant source file(s) around the failure location.\n"
            f"2. Diagnose the root cause against the acceptance criteria.\n"
            f"3. Apply a clean, minimal patch using apply_patch (or write_file).\n"
            f"4. Run run_test_suite to verify that tests pass cleanly.\n\n"
            f"Please execute Step 1 now by reading the suspected file or running tests."
        )

        await self.execute_autonomous_loop(investigation_prompt)

    async def auto_debug(self) -> None:
        """Backward-compatible alias for autonomous_investigation."""
        await self.autonomous_investigation()

    # ─── AUTONOMOUS TOOL EXECUTION LOOP ───────────────────────────────────────

    async def execute_autonomous_loop(self, initial_prompt: str) -> None:
        """Multi-turn autonomous execution loop with deduplication, loop prevention, and memory."""
        self.history.append({"role": "user", "content": initial_prompt})

        max_turns = 14
        current_turn = 0
        executed_tool_signatures: list[str] = []

        system_prompt = self._build_system_prompt()

        while current_turn < max_turns:
            current_turn += 1
            self.step_counter += 1

            # Prepare working memory summary for system prompt
            wm_text = format_working_memory(self.context_manager.working_memory)
            full_system_prompt = f"{system_prompt}\n\n{wm_text}"

            with console.status(f"[bold cyan]🧠 Step {current_turn}/{max_turns}: Thinking & planning...[/bold cyan]", spinner="dots"):
                response = await self.adapter.complete(
                    system_prompt=full_system_prompt,
                    user_message="",
                    history=self.history,
                    tools=self.tool_definitions,
                    temperature=0.1,
                )

            # Text-to-tool parsing fallback
            if not response.tool_calls and response.content:
                parsed_calls = self.adapter._parse_tool_calls_from_text(response.content)
                if parsed_calls:
                    response.tool_calls = parsed_calls
                    response.content = ""

            # Check for tool calls
            if response.tool_calls:
                for tc in response.tool_calls:
                    if not tc.reasoning or not str(tc.reasoning).strip():
                        tc.reasoning = f"Execute {tc.tool}"

                    # ── Loop prevention check ──
                    sig = f"{tc.tool}:{json.dumps(tc.args, sort_keys=True)}"
                    if len(executed_tool_signatures) >= 2 and executed_tool_signatures[-1] == sig and executed_tool_signatures[-2] == sig:
                        console.print(f"[bold yellow]⚠️  Loop Prevention:[/bold yellow] Repeated call to `{tc.tool}` with identical args. Breaking cycle.")
                        self.history.append({"role": "user", "content": f"You called `{tc.tool}` with identical args multiple times. Synthesize what you learned or proceed to the next step."})
                        continue

                    executed_tool_signatures.append(sig)

                    console.print(f"  [cyan]🛠️  Tool Call:[/cyan] [bold]{tc.tool}[/bold] [dim]({tc.reasoning})[/dim]")
                    tool_res = self.tool_engine.execute(tc)

                    # Process observation truncation through ContextManager
                    tool_res = self.context_manager.process_tool_result(tool_res)

                    if tool_res.status == ResultStatus.SUCCESS:
                        stat_color = "green"
                        stat_icon = "✅"
                    else:
                        stat_color = "red"
                        stat_icon = "❌"

                    preview = tool_res.truncated_output.strip()
                    if len(preview) > 240:
                        preview = preview[:240] + "..."
                    console.print(f"     [{stat_color}]{stat_icon} {tool_res.tool}:[/] [dim]{preview}[/dim]")

                    # ── Update Working Memory based on tool executed ──
                    if tc.tool == "read_file_range":
                        fp = tc.args.get("file_path", "")
                        self.context_manager.update_working_memory(
                            file_examined=(fp, f"Read lines {tc.args.get('start_line')}-{tc.args.get('end_line')}"),
                        )
                    elif tc.tool == "apply_patch":
                        tf = tc.args.get("target_file", "")
                        self.context_manager.update_working_memory(
                            edit_applied=f"Patched {tf}",
                        )
                    elif tc.tool == "write_file":
                        fp = tc.args.get("file_path", "")
                        self.context_manager.update_working_memory(
                            edit_applied=f"Created {fp}",
                        )
                    elif tc.tool == "run_test_suite":
                        stat_str = "PASSING (0 errors)" if tool_res.exit_code == 0 else f"FAILING (exit code {tool_res.exit_code})"
                        self.context_manager.update_working_memory(
                            test_status=stat_str,
                        )

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
                    tool_feedback = (
                        f"Tool `{tc.tool}` executed with status {tool_res.status.value}.\n"
                        f"Output:\n{tool_res.truncated_output}"
                    )
                    self.history.append({"role": "model", "content": f"I executed tool `{tc.tool}` ({tc.reasoning})"})
                    self.history.append({"role": "user", "content": f"Observation from `{tc.tool}`:\n{tool_feedback}"})

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

        # ── Final Verification Gate ──
        diff_res = git_diff(repo_root=self.repo_path)
        if diff_res.status == ResultStatus.SUCCESS and diff_res.raw_output and not diff_res.raw_output.startswith("Working tree clean"):
            console.print("\n[bold green]══════════════════════════════════════════════════════════════════════[/bold green]")
            console.print("[bold green]🎉 TASK COMPLETED & CODE PATCH APPLIED![/bold green]")
            console.print("[bold green]══════════════════════════════════════════════════════════════════════[/bold green]")
            syntax = Syntax(diff_res.raw_output, "diff", theme="monokai", line_numbers=True)
            console.print(Panel(syntax, title="Verified Git Diff", border_style="green"))

            final_tests = run_test_suite(repo_root=self.repo_path)
            if final_tests.exit_code == 0:
                console.print("[bold green]✅ Test suite verification: ALL TESTS PASSING CLEANLY[/bold green]\n")
            else:
                console.print(f"[bold yellow]⚠️  Verification note: Test suite returned exit code {final_tests.exit_code}[/bold yellow]\n")

    # ─── NATURAL LANGUAGE ROUTER ─────────────────────────────────────────────

    async def process_user_message(self, user_msg: str) -> None:
        """Process natural language request or route to specialized engines."""
        cleaned = user_msg.strip().lower()

        # 1. Casual Greetings
        if cleaned in ("hi", "hello", "hey", "hola", "greetings", "yo"):
            reply = "Hello! I'm Zenith, your AI engineering assistant. What would you like to build, inspect, or fix in this repository today?"
            console.print(f"\n[bold cyan]Zenith ❯[/bold cyan] {reply}\n")
            self.history.append({"role": "user", "content": user_msg})
            self.history.append({"role": "model", "content": reply})
            return

        # 2. Exits
        if cleaned in ("bye", "goodbye", "cya", "exit", "quit"):
            console.print("\n[bold cyan]Zenith ❯[/bold cyan] Goodbye! Happy coding! 🚀\n")
            self.session_active = False
            return

        # 3. Autonomous Diagnostic Engine Triggers ("find the issues, find bugs and errors", /debug, etc.)
        issue_triggers = [
            "find issue", "find the issue", "find issues", "find the issues",
            "find bug", "find the bug", "find bugs", "find the bugs",
            "find error", "find the error", "find errors", "find the errors",
            "scan project", "scan repo", "audit project", "diagnose",
            "fix issue", "fix the issue", "fix bugs", "fix the bug",
            "fix error", "fix failing", "what are the issues", "what are the bugs",
        ]
        if any(trig in cleaned for trig in issue_triggers):
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
        """Prompt user for Gemini API key if no keys are found in environment."""
        if self.adapter.key_pool.total_keys > 0:
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

                if cmd_lower in ("/debug", "/scan", "/audit", "/issues"):
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
