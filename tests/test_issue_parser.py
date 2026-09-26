"""Unit tests for harness/issue_parser.py (Phase 4).

Validates rule-based extraction, LLM fallback, complexity scoring,
and task-adaptive routing per PRD §4.1.
"""

from __future__ import annotations

from harness.adapters.base import ModelResponse
from harness.contracts import AgentMode, Complexity, TaskType
from harness.issue_parser import IssueParser, calculate_complexity, route_complexity


SAMPLE_TRACEBACK_ISSUE = """
Title: Bug in auth service: NoneType token causes crash

Traceback (most recent call last):
  File "src/auth/service.py", line 78, in authenticate
    token_len = len(token.strip())
AttributeError: 'NoneType' object has no attribute 'strip'

Steps to reproduce:
Run `pytest tests/test_auth.py -k test_null_token` to reproduce the crash.
"""

SAMPLE_FEATURE_ISSUE = """
Title: Add support for OAuth2 PKCE verification flow

We need to implement the PKCE verification flow according to RFC 7636.
Files to update:
- src/auth/oauth.py
- src/auth/pkce.py

Acceptance criteria:
- Generate code challenge from verifier using SHA-256
- Reject invalid code challenges
- Add unit tests for PKCE exchange
"""

SAMPLE_SIMPLE_BUG = """
Fix typo in docstring of math_utils.py.
"""


def test_issue_parser_traceback_extraction(tmp_path):
    # Setup test file in tmp repo
    auth_dir = tmp_path / "src" / "auth"
    auth_dir.mkdir(parents=True)
    auth_file = auth_dir / "service.py"
    auth_file.write_text("def authenticate(token):\n    pass\n")

    parser = IssueParser()
    plan = parser.parse_issue(SAMPLE_TRACEBACK_ISSUE, repo_path=str(tmp_path))

    assert plan.task_type == TaskType.BUG_FIX
    assert plan.error_type == "AttributeError"
    assert "tests/test_auth.py" in plan.test_filter or "test_null_token" in plan.test_filter
    assert "pytest" in plan.reproduction_hint
    assert any(sf.path == "src/auth/service.py" for sf in plan.suspected_files)
    assert plan.parsing_confidence >= 0.80
    assert plan.parsing_method == "RULE_BASED"


def test_issue_parser_feature_request(tmp_path):
    parser = IssueParser()
    plan = parser.parse_issue(SAMPLE_FEATURE_ISSUE, repo_path=str(tmp_path))

    assert plan.task_type == TaskType.FEATURE
    assert plan.requires_external_knowledge is True  # RFC 7636 detected
    assert len(plan.suspected_files) >= 1
    assert len(plan.acceptance_criteria) >= 2


def test_calculate_complexity_thresholds():
    # LOW: score <= 4
    low_score, low_comp = calculate_complexity(
        suspected_files_count=1,
        traceback_depth=0,
        requires_external_knowledge=False,
        cross_module=False,
        task_type=TaskType.BUG_FIX,
    )
    assert low_score == 2.0
    assert low_comp == Complexity.LOW

    # MEDIUM: score 5-9
    med_score, med_comp = calculate_complexity(
        suspected_files_count=2,
        traceback_depth=2,
        requires_external_knowledge=False,
        cross_module=False,
        task_type=TaskType.BUG_FIX,
    )
    # 2*2 + 2*1.5 = 7.0
    assert med_score == 7.0
    assert med_comp == Complexity.MEDIUM

    # HIGH: score 10-16
    high_score, high_comp = calculate_complexity(
        suspected_files_count=2,
        traceback_depth=2,
        requires_external_knowledge=True,
        cross_module=True,
        task_type=TaskType.BUG_FIX,
    )
    # 2*2 + 2*1.5 + 3 + 2 = 12.0
    assert high_score == 12.0
    assert high_comp == Complexity.HIGH

    # VERY_HIGH: score 17+
    vhigh_score, vhigh_comp = calculate_complexity(
        suspected_files_count=4,
        traceback_depth=3,
        requires_external_knowledge=True,
        cross_module=True,
        task_type=TaskType.FEATURE,
    )
    # 4*2 (8) + 3*1.5 (4.5) + 3 + 2 + 4 = 21.5
    assert vhigh_score == 21.5
    assert vhigh_comp == Complexity.VERY_HIGH


def test_task_adaptive_routing():
    low_route = route_complexity(Complexity.LOW)
    assert low_route["agent_mode"] == AgentMode.SINGLE_REACT
    assert low_route["max_steps"] == 15
    assert low_route["subagents"] == []

    med_route = route_complexity(Complexity.MEDIUM)
    assert med_route["agent_mode"] == AgentMode.PLANNER_EXECUTOR
    assert med_route["max_steps"] == 25
    assert "scout" in med_route["subagents"]
    assert "coder" in med_route["subagents"]

    high_route = route_complexity(Complexity.HIGH)
    assert high_route["agent_mode"] == AgentMode.MULTI_AGENT
    assert high_route["max_steps"] == 40
    assert "critic" in high_route["subagents"]

    vhigh_route = route_complexity(Complexity.VERY_HIGH)
    assert vhigh_route["agent_mode"] == AgentMode.MULTI_AGENT_DEEP
    assert vhigh_route["max_steps"] == 55


class MockAdapter:
    def __init__(self, response_json: str):
        self.response_json = response_json
        self.called = False

    async def complete(self, *args, **kwargs):
        self.called = True
        return ModelResponse(
            content=self.response_json,
            tokens_in=100,
            tokens_out=50,
            model="mock",
        )


def test_llm_fallback_invoked_on_low_confidence():
    import asyncio

    mock_llm_json = '{"primary_goal": "Clarified goal", "task_type": "BUG_FIX", "error_type": "CustomError"}'
    adapter = MockAdapter(mock_llm_json)

    parser = IssueParser(model_adapter=adapter)
    # Ambiguous short issue with low confidence
    plan = asyncio.run(parser.parse_issue_async("Something is wrong somewhere in the code.", repo_path="."))

    # LLM should be invoked because rule-based confidence was low
    assert adapter.called is True
    assert plan.parsing_method == "LLM_ASSISTED"
