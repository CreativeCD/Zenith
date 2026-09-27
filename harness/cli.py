"""harness/cli.py — CLI Entry Point for Zenith Harness.

Reference: PRD.md §12.2 | architecture.md §7.10
Parses command-line arguments, boots the configuration engine, and kicks off orchestration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.config import HarnessConfig, load_config
from harness.context_manager import ContextManager
from harness.telemetry import TelemetryWriter


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for Zenith."""
    parser = argparse.ArgumentParser(
        prog="zenith",
        description="Zenith — Autonomous AI Coding Harness for Benchmark-Driven Software Engineering",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--repo",
        type=str,
        default=".",
        help="Path to target repository to repair or inspect",
    )
    parser.add_argument(
        "--issue",
        type=str,
        default="issue.txt",
        help="Path to file containing GitHub issue description or prompt",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=25,
        help="Maximum agent turns before halting",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model override (default: uses harness_config.yaml setting)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for action turns",
    )
    parser.add_argument(
        "--token-budget",
        type=int,
        default=32000,
        help="Total context window token budget",
    )
    parser.add_argument(
        "--agent-mode",
        type=str,
        choices=["auto", "single", "multi"],
        default="auto",
        help="Agent mode: auto-select by complexity, single ReAct agent, or full multi-agent pool",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Stream real-time cost, token utilization, and telemetry events to stdout",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Run silently without streaming live telemetry",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute issue parsing and repository indexing only; skip LLM code modification",
    )
    parser.add_argument(
        "--no-external-skills",
        action="store_true",
        help="Disable external skill retriever (run in strictly offline mode)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".harness",
        help="Directory to write telemetry, diffs, and execution report",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="harness_config.yaml",
        help="Path to harness YAML configuration file",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Launch interactive Claude Code style terminal REPL",
    )

    parser.add_argument(
        "--trust",
        "-y",
        "--yes",
        action="store_true",
        help="Grant workspace trust to the target repository without interactive prompt",
    )

    return parser


def main(args_list: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(args_list)

    # Convert args to dictionary for config loader
    cli_overrides = vars(args)

    try:
        config: HarnessConfig = load_config(
            config_path=args.config,
            cli_args=cli_overrides,
        )
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        return 1

    # Check for interactive REPL mode:
    # If explicitly requested (-i / --interactive) OR run as a standalone command with no args
    is_bare_invocation = (args_list is None and len(sys.argv) <= 1)
    is_interactive = getattr(args, "interactive", False) or is_bare_invocation

    # Workspace Trust & Boundary Verification
    from harness.trust import WorkspaceTrustManager
    trust_mgr = WorkspaceTrustManager()
    resolved_repo = str(Path(config.repo_path).resolve())

    auto_trust = (
        getattr(args, "trust", False)
        or getattr(args, "yes", False)
        or getattr(args, "dry_run", False)
        or config.trust
    )
    if not trust_mgr.request_trust(resolved_repo, auto_trust=auto_trust):
        return 1

    # In batch mode, validate credentials and environment immediately
    if not is_interactive:
        try:
            config.validate()
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"Error loading configuration: {e}", file=sys.stderr)
            return 1

    if is_interactive:
        from harness.interactive import launch_interactive_repl
        return launch_interactive_repl(config=config)

    # Initialize Telemetry
    telemetry = TelemetryWriter(
        output_dir=config.telemetry.output_dir,
        model_name=config.model.name,
        stream_to_stdout=config.telemetry.stream_to_stdout,
    )

    # Initialize Layer 4: Context & Memory Manager
    context_mgr = ContextManager(
        config=config.context,
        output_dir=config.telemetry.output_dir,
    )

    issue_content = ""
    issue_file = Path(config.issue_path)
    if issue_file.exists() and issue_file.is_file():
        try:
            issue_content = issue_file.read_text(encoding="utf-8")
        except OSError:
            issue_content = config.issue_path
    else:
        issue_content = config.issue_path

    telemetry.log_session_start(
        issue_id=issue_file.stem if issue_file.exists() else "unknown",
        repo_path=config.repo_path,
    )

    if config.telemetry.stream_to_stdout:
        print("\n" + "=" * 65)
        print("  ZENITH AI CODING HARNESS — SPRINT 2026")
        print(f"  Target Repo : {config.repo_path}")
        print(f"  Issue Path  : {config.issue_path}")
        print(f"  Model       : {config.model.name}")
        print(f"  Agent Mode  : {config.agent.agent_mode} (Max Steps: {config.agent.max_steps})")
        print(f"  Token Budget: {config.context.max_context_tokens:,} tokens (KV Cache: {config.context.kv_cache_enabled})")
        print(f"  Dry Run     : {config.dry_run}")
        print("=" * 65 + "\n")

    if config.dry_run:
        from harness.issue_parser import IssueParser
        from harness.repo_intel import RepoIndexBuilder, SemanticRanker

        parser = IssueParser(config=config)
        plan = parser.parse_issue(issue_content, repo_path=config.repo_path)

        builder = RepoIndexBuilder(
            repo_path=config.repo_path,
            output_dir=f"{config.telemetry.output_dir}/repo_index",
        )
        repo_index = builder.build_index()

        ranker = SemanticRanker()
        suspected_paths = [f.path for f in plan.suspected_files]
        ranked_files = ranker.rank_files(
            query=plan.primary_goal,
            repo_index=repo_index,
            repo_path=config.repo_path,
            suspected_files=suspected_paths,
            top_n=5,
        )

        context_mgr.set_issue(plan)
        prompt_sections = context_mgr.build_prompt(ranked_files=ranked_files)

        print("Dry run complete:")
        print(f"  Issue Goal   : {plan.primary_goal}")
        print(f"  Complexity   : {plan.complexity_estimate.value} ({plan.estimated_steps} steps estimated)")
        print(f"  Top Files    : {[f.path for f in ranked_files.files]}")
        print(f"  Prompt Budget: {prompt_sections.total_tokens} tokens assembled.")
        return 0

    from harness.orchestrator import Orchestrator

    orchestrator = Orchestrator(config=config)
    session_result = orchestrator.run(issue_text=issue_content)

    print("\n" + "=" * 65)
    is_success = session_result.status.value in ("DONE", "SUCCESS", "PASS")
    icon = "✅" if is_success else "❌"
    print(f"  {icon} ZENITH AI RUN COMPLETED: {session_result.status.value} (Exit: {session_result.exit_code})")
    print("=" * 65)
    print(f"  • Steps Taken  : {session_result.total_steps}")
    print(f"  • Tokens Used  : {session_result.total_tokens:,}")
    print(f"  • Total Cost   : ${session_result.total_cost_usd:.4f} USD")
    print(f"  • Duration     : {session_result.total_wall_time_ms / 1000:.1f}s")

    v_res = session_result.verification_result
    if v_res and hasattr(v_res, "phases") and v_res.phases:
        print("\n  📋 Verification Gates:")
        for phase_name, p_res in v_res.phases.items():
            stat = getattr(p_res, "status", "PASS")
            if hasattr(stat, "value"):
                stat = stat.value
            pass_icon = "✅ PASS" if str(stat).upper() in ("PASS", "SUCCESS") else "❌ FAIL"
            detail = getattr(p_res, "detail", "") or getattr(p_res, "errors", "")
            print(f"    • {phase_name:<12}: {pass_icon} — {detail}")

    report_path = Path(config.telemetry.output_dir) / "report.md"
    if report_path.exists():
        print(f"\n  📄 Execution Report: {report_path.resolve()}")
    print("=" * 65 + "\n")

    return session_result.exit_code


if __name__ == "__main__":
    sys.exit(main())
