"""harness/interactive.py — Interactive Claude Code Style REPL for Zenith.

Provides:
- Natural conversational chat ('hi', 'bye', general coding questions)
- Auto-debugging without requiring an issue.txt file (/debug, 'find bugs', 'fix tests')
- Step-by-step tool execution with live feedback (reading files, applying patches, running tests)
- Rich terminal UI with syntax highlighting, markdown rendering, and command history
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any, List

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from harness.adapters.gemini_adapter import GeminiAdapter
from harness.config import HarnessConfig
from harness.contracts import ResultStatus, ToolCall, ToolResult
from harness.tool_engine import ToolEngine
from harness.tools.executor import run_test_suite
from harness.tools.navigation import list_dir, search_code
from harness.tools.vcs import git_diff, git_status

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style as PromptStyle
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

console = Console()


SYSTEM_REPL_PROMPT = """You are Zenith, an expert autonomous AI software engineer and interactive coding partner (inspired by Claude Code).
You are operating directly inside the repository at: {repo_path}

Repository Guidelines:
1. Always inspect files and run tests strictly in the current repository ({repo_path}) using your tools (search_code, list_dir, read_file_range, run_test_suite).
2. NEVER assume files, issues, or bugs from other projects. Only refer to files and test results that genuinely exist in this repository.
3. Strict Boundary Security: You are strictly jailed to {repo_path}. All file creations, edits, reads, deletions, and commands MUST stay within this directory. Never access parent folders or other repositories.
4. If the user mentions an issue or issue file, read that file in this repository to understand the problem.
5. When asked to find bugs or fix tests, run the test suite to observe real failures in this repository, locate the root cause, and apply minimal, clean fixes.
6. Autonomous Tool Execution:
   - When you need to read or edit files, search code, or run tests, ALWAYS call the corresponding function tool.
   - NEVER write text like "Invoked tool ... with args ..." or print tool arguments in your text responses.
   - Continue iterating autonomously until the task is completely diagnosed, fixed, and verified.
7. Be concise, transparent, and direct. Explain actions before or after using tools.
"""


class ZenithREPL:
    """Claude Code style interactive terminal REPL for Zenith."""

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config
        self.repo_path = str(Path(config.repo_path).resolve())
        self.system_prompt = SYSTEM_REPL_PROMPT.format(repo_path=self.repo_path)
        self.adapter = GeminiAdapter(
            model_name=config.model.name,
            key_pool=None,
        )
        self.tool_engine = ToolEngine(
            repo_root=self.repo_path,
        )
        self.tool_definitions = self.tool_engine.get_tool_definitions()
        self.history: list[dict[str, str]] = []
        self.session_active = True

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

    def print_welcome_banner(self) -> None:
        """Render a sleek startup banner."""
        repo_name = Path(self.repo_path).name
        key_count = self.adapter.key_pool.total_keys
        model_name = self.config.model.name

        banner_text = (
            f"[bold cyan]⚡ ZENITH CODE[/bold cyan] [dim]— Autonomous AI Engineer (Claude Code style)[/dim]\n"
            f"[bold]Repo[/bold]     : [green]{repo_name}[/green] [dim]({self.repo_path})[/dim]\n"
            f"[bold]Trust[/bold]    : [bold green]🔒 Verified & Jailed strictly to this folder[/bold green]\n"
            f"[bold]Model[/bold]    : [cyan]{model_name}[/cyan] [dim](Key Pool: {key_count} active keys)[/dim]\n"
            f"[bold]Help[/bold]     : Type [bold cyan]/help[/bold cyan] for commands, [bold cyan]/debug[/bold cyan] to auto-detect & fix bugs, [bold red]exit[/bold red] to quit."
        )
        console.print(Panel(banner_text, border_style="cyan", expand=False))
        console.print("")

    def print_help(self) -> None:
        """Display interactive commands help."""
        table = Table(title="Zenith Interactive Commands", border_style="dim")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")

        table.add_row("/debug", "Auto-scan repo for failing tests and repair bugs autonomously")
        table.add_row("/test", "Run repo test suite (pytest) and show results")
        table.add_row("/diff", "Display git diff of uncommitted changes")
        table.add_row("/status", "Show git status of the working tree")
        table.add_row("/clear", "Clear terminal screen and chat view")
        table.add_row("/help", "Show this help menu")
        table.add_row("exit, quit, bye", "Exit the interactive session")

        console.print(table)
        console.print("\n[dim]💡 Tip: You can also chat naturally! E.g. 'find bugs in billing', 'explain discounts.py', or 'add a test for X'.[/dim]\n")

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

    async def auto_debug(self) -> None:
        """Autonomous debugging without requiring any issue.txt file."""
        console.print("[bold cyan]🔍 Auto-Debug: Scanning repository for broken tests and failures...[/bold cyan]")
        test_res = run_test_suite(repo_root=self.repo_path)

        if test_res.exit_code == 0:
            console.print("[bold green]✅ No failing tests found! All existing tests are currently passing.[/bold green]")
            diff_res = git_diff(repo_root=self.repo_path)
            if diff_res.status == ResultStatus.SUCCESS and diff_res.raw_output and not diff_res.raw_output.startswith("Working tree clean"):
                console.print("\n[yellow]However, you have uncommitted changes in your working tree:[/yellow]")
                syntax = Syntax(diff_res.truncated_output, "diff", theme="monokai")
                console.print(Panel(syntax, title="Uncommitted Diff", border_style="yellow"))
                console.print("Would you like me to inspect or test these specific changes?")
            else:
                console.print("[dim]If there is a subtle bug or edge case not covered by tests, tell me what happens and what you expect, and I will write a reproduction test and fix it![/dim]")
            return

        # We found a failure!
        console.print(f"[bold red]❌ Found failing tests in repo![/bold red]")
        console.print(Panel(test_res.truncated_output[:1200], title="Failure Traceback", border_style="red"))

        # Ask the agent to diagnose and fix
        prompt = (
            f"The repository test suite failed with exit code {test_res.exit_code}.\n"
            f"Here is the test failure output:\n\n```\n{test_res.truncated_output}\n```\n\n"
            f"Please investigate the root cause using tools (read_file_range, search_code), apply a minimal patch to fix the bug, and re-run the tests to verify the fix."
        )
        await self.process_user_message(prompt, auto_mode=True)

    async def process_user_message(self, user_msg: str, auto_mode: bool = False) -> None:
        """Process user message through multi-turn conversational tool loop."""
        # Check for casual greetings or exits first
        cleaned = user_msg.strip().lower()
        if not auto_mode:
            if cleaned in ("hi", "hello", "hey", "hola"):
                console.print("\n[bold cyan]Zenith ❯[/bold cyan] Hello! I'm Zenith, your AI engineering assistant. What would you like to build, inspect, or fix in this repository today?\n")
                self.history.append({"role": "user", "content": user_msg})
                self.history.append({"role": "model", "content": "Hello! I'm Zenith, your AI engineering assistant. What would you like to build, inspect, or fix in this repository today?"})
                return

            if cleaned in ("bye", "goodbye", "cya"):
                console.print("\n[bold cyan]Zenith ❯[/bold cyan] Goodbye! Happy coding! 🚀\n")
                self.session_active = False
                return

            if "find bugs" in cleaned or "debug" in cleaned or "fix tests" in cleaned or "fix failing" in cleaned:
                await self.auto_debug()
                return

        self.history.append({"role": "user", "content": user_msg})

        # Agent execution loop (up to 8 tool iterations per turn)
        max_tool_turns = 10
        current_turn = 0

        while current_turn < max_tool_turns:
            current_turn += 1
            with console.status("[bold cyan]🧠 Thinking & inspecting...[/bold cyan]", spinner="dots"):
                response = await self.adapter.complete(
                    system_prompt=self.system_prompt,
                    user_message="",
                    history=self.history,
                    tools=self.tool_definitions,
                    temperature=0.1,
                )

            # If model produced text instead of calling tools, check if text was a tool invocation
            if not response.tool_calls and response.content:
                parsed_calls = self.adapter._parse_tool_calls_from_text(response.content)
                if parsed_calls:
                    response.tool_calls = parsed_calls
                    response.content = ""

            # Check if model emitted tool calls
            if response.tool_calls:
                for tc in response.tool_calls:
                    if not tc.reasoning or not str(tc.reasoning).strip():
                        tc.reasoning = f"Execute {tc.tool}"

                    console.print(f"  [cyan]🛠️  Tool Call:[/cyan] [bold]{tc.tool}[/bold] [dim]({tc.reasoning})[/dim]")
                    # Execute tool
                    tool_res = self.tool_engine.execute(tc)

                    if tool_res.status == ResultStatus.SUCCESS:
                        stat_color = "green"
                        stat_icon = "✅"
                    else:
                        stat_color = "red"
                        stat_icon = "❌"

                    preview = tool_res.truncated_output.strip()
                    if len(preview) > 300:
                        preview = preview[:300] + "..."
                    console.print(f"     [{stat_color}]{stat_icon} {tool_res.tool}:[/] [dim]{preview}[/dim]")

                    # Append tool execution result into conversation history
                    tool_feedback = (
                        f"Tool `{tc.tool}` executed with status {tool_res.status.value}.\n"
                        f"Output:\n{tool_res.raw_output}"
                    )
                    self.history.append({"role": "model", "content": f"I executed tool `{tc.tool}` ({tc.reasoning})"})
                    self.history.append({"role": "user", "content": f"Observation from `{tc.tool}`:\n{tool_feedback}"})

                # Loop again to let the model review tool results and formulate final response or next action
                continue

            # Model produced textual answer
            if response.content:
                console.print(f"\n[bold cyan]Zenith ❯[/bold cyan]")
                md = Markdown(response.content)
                console.print(md)
                console.print("")
                self.history.append({"role": "model", "content": response.content})
                break
            else:
                break

    def _ensure_api_key(self) -> bool:
        """Prompt user for Gemini API key if no keys are found in environment."""
        if self.adapter.key_pool.total_keys > 0:
            return True

        console.print(Panel(
            "[yellow bold]🔑 No Google Gemini API key found![/yellow bold]\n\n"
            "Zenith only requires [bold cyan]1 free API key[/bold cyan] from Google AI Studio.\n"
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
        """Main REPL loop."""
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

                # Handle built-in slash commands
                if user_input.lower() in ("exit", "quit", ":q"):
                    console.print("[dim]Exiting Zenith. Goodbye![/dim]")
                    break

                if user_input == "/help":
                    self.print_help()
                    continue

                if user_input == "/clear":
                    os.system("clear")
                    self.print_welcome_banner()
                    continue

                if user_input == "/test":
                    self.run_tests_direct()
                    continue

                if user_input == "/diff":
                    self.show_diff()
                    continue

                if user_input == "/status":
                    self.show_status()
                    continue

                if user_input == "/debug":
                    await self.auto_debug()
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
