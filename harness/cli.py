"""harness/cli.py — CLI Entry Point for Zenith Harness.

Reference: PRD.md §12.2 | architecture.md §7.10
Parses command-line arguments, boots the configuration engine, and kicks off orchestration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from harness.config import HarnessConfig, load_config
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
        default="gemini-2.5-flash",
        help="Model identifier (e.g., gemini-2.5-flash, gemini-2.5-pro, claude-3-5-sonnet)",
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


def main(args_list: Optional[List[str]] = None) -> int:
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
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        return 1

    # Initialize Telemetry
    telemetry = TelemetryWriter(
        output_dir=config.telemetry.output_dir,
        model_name=config.model.name,
        stream_to_stdout=config.telemetry.stream_to_stdout,
    )

    telemetry.log_session_start(
        issue_id=Path(config.issue_path).stem if Path(config.issue_path).exists() else "unknown",
        repo_path=config.repo_path,
    )

    if config.telemetry.stream_to_stdout:
        print("\n" + "=" * 65)
        print("  ZENITH AI CODING HARNESS — SPRINT 2026")
        print(f"  Target Repo : {config.repo_path}")
        print(f"  Issue Path  : {config.issue_path}")
        print(f"  Model       : {config.model.name}")
        print(f"  Agent Mode  : {config.agent.agent_mode} (Max Steps: {config.agent.max_steps})")
        print(f"  Token Budget: {config.context.max_context_tokens:,} tokens")
        print(f"  Dry Run     : {config.dry_run}")
        print("=" * 65 + "\n")

    if config.dry_run:
        print("Dry run complete: configuration loaded, validated, and telemetry initialized.")
        return 0

    # In Phase 0, print ready status
    print("Zenith harness initialized. Ready for Phase 1 Core Tool Engine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
