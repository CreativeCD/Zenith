"""Unit tests for harness/subagents/pool.py (Phase 4).

Validates Scout, Architect, Coder, and Critic subagents for context budget limits,
isolated inputs, and required output artifacts per PRD §4.5.3.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from harness.adapters.base import ModelResponse
from harness.contracts import Complexity, IssuePlan, SuspectedFile, TaskType
from harness.subagents.pool import (
    ArchitectSubagent,
    CoderSubagent,
    CriticSubagent,
    ScoutSubagent,
)


class MockModelAdapter:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.last_system_prompt = ""
        self.last_user_message = ""

    async def complete(self, system_prompt: str, user_message: str, **kwargs):
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        return ModelResponse(
            content=self.response_text,
            tokens_in=len(system_prompt.split()) + len(user_message.split()),
            tokens_out=len(self.response_text.split()),
            model="mock",
        )


def make_dummy_issue_plan() -> IssuePlan:
    return IssuePlan(
        issue_id="issue-123",
        primary_goal="Fix null token in AuthService",
        task_type=TaskType.BUG_FIX,
        acceptance_criteria=["auth.authenticate() handles null token without crash"],
        suspected_files=[SuspectedFile(path="src/auth/service.py", confidence=0.95, reason="Traceback")],
        reproduction_hint="pytest tests/test_auth.py",
        test_filter="pytest tests/test_auth.py",
        error_type="AttributeError",
        complexity_estimate=Complexity.MEDIUM,
        estimated_steps=20,
        requires_external_knowledge=False,
        language="python",
        test_runner="pytest",
        parsing_confidence=0.92,
        parsing_method="RULE_BASED",
    )


def test_scout_subagent_generates_report(tmp_path):
    mock_scout_out = (
        "## Relevant Files\n- src/auth/service.py\n\n"
        "## Key Symbols & Call Paths\n- AuthService.authenticate\n\n"
        "## Dependency Chain\n- src/auth/token.py\n\n"
        "## Suspected Root Cause Location\n- Line 78 in service.py\n\n"
        "## Recommended Fix Strategy\n- Add guard check for None before calling strip()."
    )
    adapter = MockModelAdapter(mock_scout_out)
    scout = ScoutSubagent(model_adapter=adapter, output_dir=str(tmp_path))

    plan = make_dummy_issue_plan()
    report_path = asyncio.run(scout.run_async(
        issue_plan=plan,
        file_tree="src/\n  auth/\n    service.py",
        module_symbols="service.py: class AuthService",
    ))

    assert Path(report_path).exists()
    content = Path(report_path).read_text()
    assert "## Relevant Files" in content
    assert "## Recommended Fix Strategy" in content


def test_architect_subagent_generates_plan(tmp_path):
    mock_arch_out = (
        "## Fix Strategy\n1. Modify service.py\n\n"
        "## Files to Modify\n- src/auth/service.py\n\n"
        "## Risk Factors\n- None\n\n"
        "## Test Verification Plan\n- Run pytest tests/test_auth.py"
    )
    adapter = MockModelAdapter(mock_arch_out)
    architect = ArchitectSubagent(model_adapter=adapter, output_dir=str(tmp_path))

    plan = make_dummy_issue_plan()
    plan_path = asyncio.run(architect.run_async(
        issue_plan=plan,
        scout_report="## Relevant Files\n- src/auth/service.py",
    ))

    assert Path(plan_path).exists()
    content = Path(plan_path).read_text()
    assert "## Fix Strategy" in content
    assert "## Files to Modify" in content


def test_coder_subagent_single_file_scope(tmp_path):
    diff_patch = (
        "--- a/src/auth/service.py\n"
        "+++ b/src/auth/service.py\n"
        "@@ -78,1 +78,2 @@\n"
        "- token_len = len(token.strip())\n"
        "+ if not token: return False\n"
        "+ token_len = len(token.strip())\n"
    )
    adapter = MockModelAdapter(diff_patch)
    coder = CoderSubagent(model_adapter=adapter, output_dir=str(tmp_path))

    # Coder should accept modifications only within assigned file
    patch_path = asyncio.run(coder.run_async(
        target_file="src/auth/service.py",
        file_content="token_len = len(token.strip())",
        architecture_plan="Add guard check for null token in src/auth/service.py",
        step=1,
    ))

    assert Path(patch_path).exists()
    content = Path(patch_path).read_text()
    assert "--- a/src/auth/service.py" in content


def test_coder_subagent_rejects_scope_creep(tmp_path):
    # Model mistakenly tries to edit an unassigned file
    diff_patch = (
        "--- a/src/db/models.py\n"
        "+++ b/src/db/models.py\n"
        "@@ -10,1 +10,1 @@\n"
    )
    adapter = MockModelAdapter(diff_patch)
    coder = CoderSubagent(model_adapter=adapter, output_dir=str(tmp_path))

    # Should raise ValueError for scope violation
    import pytest
    with pytest.raises(ValueError, match="Scope violation"):
        asyncio.run(coder.run_async(
            target_file="src/auth/service.py",
            file_content="...",
            architecture_plan="...",
            step=1,
        ))


def test_critic_subagent_evaluation(tmp_path):
    mock_critic_out = (
        "## Correctness Assessment\n- Patch addresses null token safely.\n\n"
        "## Edge Cases Uncovered\n- Empty string vs None handled properly.\n\n"
        "## Potential Regressions\n- None identified.\n\n"
        "## Recommendation: APPROVE\n- Ready for final verification."
    )
    adapter = MockModelAdapter(mock_critic_out)
    critic = CriticSubagent(model_adapter=adapter, output_dir=str(tmp_path))

    plan = make_dummy_issue_plan()
    report_path = asyncio.run(critic.run_async(
        issue_plan=plan,
        patches_applied=["src/auth/service.py: guarded null token"],
        test_results="pytest tests/test_auth.py PASSED",
    ))

    assert Path(report_path).exists()
    content = Path(report_path).read_text()
    assert "## Recommendation: APPROVE" in content
