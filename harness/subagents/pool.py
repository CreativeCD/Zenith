"""harness/subagents/pool.py — Multi-Agent Subagent Pool Architecture.

Reference: PRD.md §4.5.3 | architecture.md §7.5
Implements specialized, isolated subagent roles:
- Scout (8,000 token budget) -> .harness/scout_report.md
- Architect (6,000 token budget) -> .harness/architecture_plan.md
- Coder (10,000 token budget, single-file scope enforced) -> .harness/patch_{file}_{step}.diff
- Critic (6,000 token budget) -> .harness/critic_report.md
"""

from __future__ import annotations

import re
from pathlib import Path

from harness.adapters.base import ModelAdapter
from harness.contracts import IssuePlan, SubagentRole


def _truncate_to_budget(text: str, token_budget: int) -> str:
    """Approximate truncation to keep input within subagent budget."""
    words = text.split()
    # 1 word is approx 1.3 tokens
    max_words = int(token_budget * 0.75)
    if len(words) > max_words:
        return " ".join(words[:max_words]) + f"\n\n[... truncated to {token_budget} token budget ...]"
    return text


class SubagentBase:
    """Base class for isolated subagents with fixed context budgets."""

    def __init__(
        self,
        role: SubagentRole,
        budget_tokens: int,
        model_adapter: ModelAdapter,
        output_dir: str = ".harness",
    ) -> None:
        self.role = role
        self.budget_tokens = budget_tokens
        self.model_adapter = model_adapter
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)


class ScoutSubagent(SubagentBase):
    """Scout Agent: Explores repo index and identifies root causes and strategies."""

    def __init__(self, model_adapter: ModelAdapter, output_dir: str = ".harness") -> None:
        super().__init__(
            role=SubagentRole.SCOUT,
            budget_tokens=8000,
            model_adapter=model_adapter,
            output_dir=output_dir,
        )

    async def run_async(
        self,
        issue_plan: IssuePlan,
        file_tree: str,
        module_symbols: str,
    ) -> str:
        """Run scout exploration and output .harness/scout_report.md."""
        system_prompt = (
            "You are the Scout Subagent in Zenith. Your context budget is 8,000 tokens.\n"
            "Your responsibility is to explore the repository structure, analyze symbols, "
            "and identify root causes and recommended fix strategies.\n"
            "OUTPUT FORMAT (Strict Markdown):\n"
            "## Relevant Files\n"
            "## Key Symbols & Call Paths\n"
            "## Dependency Chain\n"
            "## Suspected Root Cause Location\n"
            "## Recommended Fix Strategy\n"
        )
        user_message = (
            f"Goal: {issue_plan.primary_goal}\n"
            f"Task Type: {issue_plan.task_type.value}\n"
            f"Reproduction: {issue_plan.reproduction_hint}\n"
            f"Error Type: {issue_plan.error_type}\n\n"
            f"[FILE TREE]\n{file_tree}\n\n"
            f"[MODULE SYMBOLS]\n{module_symbols}\n"
        )
        user_message = _truncate_to_budget(user_message, self.budget_tokens)

        response = await self.model_adapter.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            max_output_tokens=2048,
        )

        report_path = self.output_dir / "scout_report.md"
        report_path.write_text(response.content, encoding="utf-8")
        return str(report_path)


class ArchitectSubagent(SubagentBase):
    """Architect Agent: Converts scout findings into a precise step-by-step fix plan."""

    def __init__(self, model_adapter: ModelAdapter, output_dir: str = ".harness") -> None:
        super().__init__(
            role=SubagentRole.ARCHITECT,
            budget_tokens=6000,
            model_adapter=model_adapter,
            output_dir=output_dir,
        )

    async def run_async(
        self,
        issue_plan: IssuePlan,
        scout_report: str,
    ) -> str:
        """Run architect planning and output .harness/architecture_plan.md."""
        system_prompt = (
            "You are the Architect Subagent in Zenith. Your context budget is 6,000 tokens.\n"
            "You receive ONLY the IssuePlan and scout_report.md.\n"
            "OUTPUT FORMAT (Strict Markdown):\n"
            "## Fix Strategy\n"
            "## Files to Modify\n"
            "## Risk Factors\n"
            "## Test Verification Plan\n"
        )
        user_message = (
            f"Goal: {issue_plan.primary_goal}\n"
            f"Criteria: {', '.join(issue_plan.acceptance_criteria)}\n\n"
            f"[SCOUT REPORT]\n{scout_report}\n"
        )
        user_message = _truncate_to_budget(user_message, self.budget_tokens)

        response = await self.model_adapter.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            max_output_tokens=2048,
        )

        plan_path = self.output_dir / "architecture_plan.md"
        plan_path.write_text(response.content, encoding="utf-8")
        return str(plan_path)


class CoderSubagent(SubagentBase):
    """Coder Agent: Implements unified diff patch constrained strictly to assigned target file."""

    def __init__(self, model_adapter: ModelAdapter, output_dir: str = ".harness") -> None:
        super().__init__(
            role=SubagentRole.CODER,
            budget_tokens=10000,
            model_adapter=model_adapter,
            output_dir=output_dir,
        )

    async def run_async(
        self,
        target_file: str,
        file_content: str,
        architecture_plan: str,
        step: int = 1,
    ) -> str:
        """Generate and save patch diff for the assigned file, enforcing single-file scope."""
        system_prompt = (
            "You are the Coder Subagent in Zenith. Your context budget is 10,000 tokens.\n"
            f"STRICT CONSTRAINT: You are assigned ONLY to file '{target_file}'.\n"
            "You MUST emit a unified diff modifying ONLY this file. Scope creep is strictly rejected.\n"
            "Output unified diff format (--- a/... +++ b/...) in code block or raw text.\n"
        )
        user_message = (
            f"Target File: {target_file}\n\n"
            f"[ARCHITECTURE PLAN]\n{architecture_plan}\n\n"
            f"[TARGET FILE CONTENT]\n{file_content}\n"
        )
        user_message = _truncate_to_budget(user_message, self.budget_tokens)

        response = await self.model_adapter.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            max_output_tokens=3000,
        )

        patch_content = response.content.strip()
        # Verify scope: Check file headers in diff
        modified_files = re.findall(r"^--- [ab]/(.+)$", patch_content, re.MULTILINE)
        for mf in modified_files:
            if Path(mf).as_posix() != Path(target_file).as_posix() and Path(mf).name != Path(target_file).name:
                raise ValueError(
                    f"Scope violation: Coder attempted to edit '{mf}' instead of assigned target '{target_file}'."
                )

        safe_name = target_file.replace("/", "_").replace("\\", "_")
        patch_file = self.output_dir / f"patch_{safe_name}_{step}.diff"
        patch_file.write_text(patch_content, encoding="utf-8")
        return str(patch_file)


class CriticSubagent(SubagentBase):
    """Critic Agent: Evaluates patch correctness, edge cases, and regressions."""

    def __init__(self, model_adapter: ModelAdapter, output_dir: str = ".harness") -> None:
        super().__init__(
            role=SubagentRole.CRITIC,
            budget_tokens=6000,
            model_adapter=model_adapter,
            output_dir=output_dir,
        )

    async def run_async(
        self,
        issue_plan: IssuePlan,
        patches_applied: list[str],
        test_results: str,
    ) -> str:
        """Evaluate patches and output .harness/critic_report.md."""
        system_prompt = (
            "You are the Critic Subagent in Zenith. Your context budget is 6,000 tokens.\n"
            "You evaluate patch correctness, potential regressions, and unhandled edge cases.\n"
            "OUTPUT FORMAT (Strict Markdown):\n"
            "## Correctness Assessment\n"
            "## Edge Cases Uncovered\n"
            "## Potential Regressions\n"
            "## Recommendation: APPROVE | REVISE (with specific guidance)\n"
        )
        user_message = (
            f"Goal: {issue_plan.primary_goal}\n"
            f"Acceptance Criteria:\n" + "\n".join(f"- {c}" for c in issue_plan.acceptance_criteria) + "\n\n"
            "[PATCHES APPLIED]\n" + "\n".join(patches_applied) + "\n\n"
            f"[TEST RESULTS]\n{test_results}\n"
        )
        user_message = _truncate_to_budget(user_message, self.budget_tokens)

        response = await self.model_adapter.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            max_output_tokens=2048,
        )

        critic_path = self.output_dir / "critic_report.md"
        critic_path.write_text(response.content, encoding="utf-8")
        return str(critic_path)
