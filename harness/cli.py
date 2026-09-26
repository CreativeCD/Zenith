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
        default="gemini-3.5-flash-lite",
        help="Model (gemini-3.5-flash-lite for free tier, gemini-3.5-flash for paid)",
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
        "--verbose",
        action="store_true",
        help="Stream real-time cost, token utilization, and telemetry events to stdout",
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
        config.validate()
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        return 1

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
    print(f"Zenith harness run finished: {session_result.status.value} (Exit: {session_result.exit_code}, Steps: {session_result.total_steps}).")
    return session_result.exit_code


if __name__ == "__main__":
    sys.exit(main())
