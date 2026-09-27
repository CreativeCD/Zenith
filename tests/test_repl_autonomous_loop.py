"""Unit tests for ZenithREPL autonomous loop execution, loop prevention, and memory."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from harness.adapters.base import ModelResponse
from harness.config import HarnessConfig
from harness.contracts import ErrorCode, ResultStatus, ToolCall, ToolResult
from harness.interactive import ZenithREPL


@pytest.fixture
def dummy_config(tmp_path):
    config = HarnessConfig()
    config.repo_path = str(tmp_path)
    config.telemetry.output_dir = str(tmp_path / ".harness")
    return config


def test_autonomous_loop_text_response(dummy_config):
    """Test that text response immediately terminates loop cleanly."""
    repl = ZenithREPL(config=dummy_config)
    repl.adapter.complete = AsyncMock(return_value=ModelResponse(
        content="All systems analyzed and operational.",
        tool_calls=[],
        tokens_in=10,
        tokens_out=20,
    ))

    asyncio.run(repl.execute_autonomous_loop("What is this repo?"))

    assert len(repl.history) == 2
    assert repl.history[0]["role"] == "user"
    assert repl.history[1]["role"] == "model"
    assert "operational" in repl.history[1]["content"]


def test_autonomous_loop_tool_execution_and_plan_update(dummy_config, tmp_path):
    """Test tool execution updates plan and working memory."""
    repl = ZenithREPL(config=dummy_config)
    repl.active_plan = repl.formulate_plan("Fix bug", [], False)

    # First turn calls read_file_range, second turn returns text
    responses = [
        ModelResponse(
            content="",
            tool_calls=[ToolCall(tool="read_file_range", reasoning="Inspect file", args={"file_path": "main.py", "start_line": 1, "end_line": 10})],
            tokens_in=10,
            tokens_out=15,
        ),
        ModelResponse(
            content="Finished analysis.",
            tool_calls=[],
            tokens_in=10,
            tokens_out=10,
        ),
    ]
    repl.adapter.complete = AsyncMock(side_effect=responses)

    # Mock tool execution
    repl.tool_engine.execute = MagicMock(return_value=ToolResult(
        tool="read_file_range",
        args_hash="abc",
        status=ResultStatus.SUCCESS,
        raw_output="print('hello')",
        truncated_output="print('hello')",
    ))

    asyncio.run(repl.execute_autonomous_loop("Inspect the main file"))

    # Verify plan step 1 was marked in_progress
    assert repl.active_plan[0]["status"] == "in_progress"

    # Verify working memory was updated
    assert "main.py" in repl.context_manager.working_memory.files_examined

    # Verify history recorded native tool call + observation structure
    assert len(repl.history) == 4
    assert repl.history[1]["role"] == "model"
    assert repl.history[1]["tool_calls"][0].tool == "read_file_range"
    assert repl.history[2]["role"] == "user"
    obs = repl.history[2]["tool_responses"][0]
    assert obs["name"] == "read_file_range"
    assert "print('hello')" in obs["output"]
    assert repl.history[3]["role"] == "model"


def test_autonomous_loop_dedup_prevention(dummy_config):
    """Test that consecutive loop detection stops runaway loops."""
    repl = ZenithREPL(config=dummy_config)

    # Model attempts same tool call repeatedly
    tc = ToolCall(tool="read_file_range", reasoning="Read", args={"file_path": "a.py", "start_line": 1, "end_line": 10})
    repeated_response = ModelResponse(
        content="",
        tool_calls=[tc],
        tokens_in=10,
        tokens_out=15,
    )
    repl.adapter.complete = AsyncMock(return_value=repeated_response)

    # Tool engine returns LOOP_DETECTED
    repl.tool_engine.execute = MagicMock(return_value=ToolResult(
        tool="read_file_range",
        args_hash="abc",
        status=ResultStatus.FAIL,
        error_code=ErrorCode.LOOP_DETECTED,
        raw_output="DEDUP: Already called at step 1",
        truncated_output="DEDUP: Already called at step 1",
    ))

    # Should break cleanly after 3 consecutive loop detections
    asyncio.run(repl.execute_autonomous_loop("Start inspection"))

    # Verified it didn't run 40 turns!
    assert repl.adapter.complete.call_count <= 4


def test_autonomous_loop_history_compaction(dummy_config):
    """Test that older observations are compacted as turns advance."""
    repl = ZenithREPL(config=dummy_config)

    # 4 tool calls followed by a textual conclusion
    responses = [
        ModelResponse(content="", tool_calls=[ToolCall(tool="search_code", reasoning="Find", args={"query": f"term_{i}"})], tokens_in=5, tokens_out=5)
        for i in range(4)
    ]
    responses.append(ModelResponse(content="Analysis complete.", tool_calls=[], tokens_in=5, tokens_out=5))
    repl.adapter.complete = AsyncMock(side_effect=responses)

    repl.tool_engine.execute = MagicMock(return_value=ToolResult(
        tool="search_code",
        args_hash="123",
        status=ResultStatus.SUCCESS,
        raw_output="found 10 matching lines in billing.py\nline 1\nline 2",
        truncated_output="found 10 matching lines in billing.py\nline 1\nline 2",
    ))

    asyncio.run(repl.execute_autonomous_loop("Perform search investigation"))

    # The oldest tool_responses observation should be compacted because
    # keep_recent_pairs is 3 (dense semantic summary replaces raw output)
    all_obs = [m for m in repl.history if m.get("tool_responses")]
    assert all_obs, "expected native tool_responses entries in history"
    first_obs = all_obs[0]["tool_responses"][0]
    assert first_obs.get("compacted") is True
    assert "term_0" in first_obs["output"] or "search_code" in first_obs["output"]


def test_autonomous_loop_mimicry_nudge(dummy_config):
    """Prose that narrates a tool call gets a corrective nudge, not acceptance."""
    repl = ZenithREPL(config=dummy_config)

    responses = [
        # Turn 1: model narrates instead of calling
        ModelResponse(content="I executed tool read_file_range to inspect the file.", tool_calls=[], tokens_in=5, tokens_out=5),
        # Turn 2: model actually calls the tool
        ModelResponse(content="", tool_calls=[ToolCall(tool="list_dir", reasoning="List", args={"path": "."})], tokens_in=5, tokens_out=5),
        # Turn 3: final text
        ModelResponse(content="Done inspecting.", tool_calls=[], tokens_in=5, tokens_out=5),
    ]
    repl.adapter.complete = AsyncMock(side_effect=responses)
    repl.tool_engine.execute = MagicMock(return_value=ToolResult(
        tool="list_dir",
        args_hash="x",
        status=ResultStatus.SUCCESS,
        raw_output="files",
        truncated_output="files",
    ))

    asyncio.run(repl.execute_autonomous_loop("Inspect"))

    # The nudge was appended between the mimicked reply and the real call
    contents = [m.get("content", "") for m in repl.history]
    assert any("CORRECTION" in c for c in contents)
    # The final text answer WAS accepted as the loop conclusion
    assert contents[-1] == "Done inspecting."


def test_autonomous_loop_final_synthesis_on_budget_exhaustion(dummy_config):
    """When the step budget runs out mid-task, a forced no-tools synthesis happens."""
    repl = ZenithREPL(config=dummy_config)
    repl.config.agent.max_steps = 4

    tool_resp = ModelResponse(
        content="",
        tool_calls=[ToolCall(tool="search_code", reasoning="Search", args={"query": "x"})],
        tokens_in=5, tokens_out=5,
    )
    responses = [tool_resp] * 4 + [ModelResponse(content="Budget synthesis summary.", tool_calls=[], tokens_in=5, tokens_out=5)]
    repl.adapter.complete = AsyncMock(side_effect=responses)
    repl.tool_engine.execute = MagicMock(return_value=ToolResult(
        tool="search_code",
        args_hash="x",
        status=ResultStatus.SUCCESS,
        raw_output="hits",
        truncated_output="hits",
    ))

    asyncio.run(repl.execute_autonomous_loop("Do the thing"))

    # The 5th adapter call is the forced synthesis (no tools passed)
    assert repl.adapter.complete.call_count == 5
    final_kwargs = repl.adapter.complete.call_args_list[-1].kwargs
    assert final_kwargs.get("tools") is None
    assert repl.history[-1]["content"] == "Budget synthesis summary."


def test_degenerate_tool_prose_detection():
    """The mimicry detector flags narration, not legitimate answers."""
    from harness.interactive import ZenithREPL

    assert ZenithREPL._is_degenerate_tool_prose("I executed tool read_file_range to check the file.")
    assert ZenithREPL._is_degenerate_tool_prose('{"tool": "list_dir", "args": {"path": "."}}')
    assert ZenithREPL._is_degenerate_tool_prose("Invoked tool search_code with args {'query': 'x'}")
    # Legitimate prose must NOT be flagged
    assert not ZenithREPL._is_degenerate_tool_prose("I executed the plan in three phases and here is what I found in the repository.")
    assert not ZenithREPL._is_degenerate_tool_prose("The tests pass. calc.py had an off-by-one discount bug which I fixed.")
    assert not ZenithREPL._is_degenerate_tool_prose("")


def test_autonomous_loop_emit_done_candidate_smooth_synthesis(dummy_config):
    """When emit_done_candidate is called, the loop transitions to synthesis with tools=None and finishes cleanly."""
    repl = ZenithREPL(config=dummy_config)
    repl.active_plan = repl.formulate_plan("Fix bug", [], False)

    tc = ToolCall(
        tool="emit_done_candidate",
        reasoning="All tests pass and edge cases are verified",
        args={
            "confidence": 1.0,
            "evidence": ["test_priority passed cleanly", "tie-breaking verified"],
            "files_modified": ["src/taskmanager/priority.py"],
        },
    )
    responses = [
        ModelResponse(content="", tool_calls=[tc], tokens_in=10, tokens_out=15),
        ModelResponse(content="I have resolved the issue by implementing tie-breaking in priority sorting.", tool_calls=[], tokens_in=15, tokens_out=25),
    ]
    repl.adapter.complete = AsyncMock(side_effect=responses)
    repl.tool_engine.execute = MagicMock(return_value=ToolResult(
        tool="emit_done_candidate",
        args_hash="done123",
        status=ResultStatus.SUCCESS,
        raw_output='{"status": "DONE_CANDIDATE"}',
        truncated_output="DONE_CANDIDATE recorded",
    ))

    asyncio.run(repl.execute_autonomous_loop("Solve priority issue"))

    # Verified 2 calls: tool call turn, then synthesis turn
    assert repl.adapter.complete.call_count == 2
    # Verify tools=None on the synthesis turn
    synthesis_call_kwargs = repl.adapter.complete.call_args_list[1].kwargs
    assert synthesis_call_kwargs.get("tools") is None
    # Verified plan was marked completed
    assert repl.active_plan[3]["status"] == "completed"
    # History includes final markdown synthesis
    assert "tie-breaking" in repl.history[-1]["content"]


def test_autonomous_loop_emit_done_candidate_empty_synthesis_fallback(dummy_config):
    """If the LLM returns empty text after emit_done_candidate, fallback summary is used."""
    repl = ZenithREPL(config=dummy_config)
    repl.active_plan = repl.formulate_plan("Fix bug", [], False)

    tc = ToolCall(
        tool="emit_done_candidate",
        reasoning="Implemented safe persistence to prevent data loss.",
        args={
            "confidence": 0.95,
            "evidence": ["save_tasks atomic write passed"],
            "files_modified": ["src/taskmanager/storage.py"],
        },
    )
    responses = [
        ModelResponse(content="", tool_calls=[tc], tokens_in=10, tokens_out=15),
        # Model returns empty string on synthesis
        ModelResponse(content="", tool_calls=[], tokens_in=10, tokens_out=0),
    ]
    repl.adapter.complete = AsyncMock(side_effect=responses)
    repl.tool_engine.execute = MagicMock(return_value=ToolResult(
        tool="emit_done_candidate",
        args_hash="done456",
        status=ResultStatus.SUCCESS,
        raw_output='{"status": "DONE_CANDIDATE"}',
        truncated_output="DONE_CANDIDATE recorded",
    ))

    asyncio.run(repl.execute_autonomous_loop("Fix storage"))

    # Must complete cleanly without looping or getting stuck
    assert repl.adapter.complete.call_count == 2
    assert "Implemented safe persistence" in repl.history[-1]["content"]


def test_format_tool_status_line(dummy_config):
    """Tool status lines format with clear icons and styled details."""
    repl = ZenithREPL(config=dummy_config)

    # Success patch
    tc_patch = ToolCall(tool="apply_patch", reasoning="patch", args={"target_file": "foo.py"})
    res_patch = ToolResult(tool="apply_patch", args_hash="", status=ResultStatus.SUCCESS, raw_output="ok", truncated_output="ok")
    line = repl._format_tool_status_line(tc_patch, res_patch)
    assert "✔" in line
    assert "foo.py" in line

    # Failed patch
    res_fail = ToolResult(tool="apply_patch", args_hash="", status=ResultStatus.FAIL, raw_output="err", truncated_output="Hunk #1 failed")
    line_fail = repl._format_tool_status_line(tc_patch, res_fail)
    assert "✖" in line_fail
    assert "Patch rejected" in line_fail

    # Passing test suite
    tc_test = ToolCall(tool="run_test_suite", reasoning="test", args={})
    res_test = ToolResult(tool="run_test_suite", args_hash="", status=ResultStatus.SUCCESS, exit_code=0, raw_output="passed", truncated_output="passed")
    line_test = repl._format_tool_status_line(tc_test, res_test)
    assert "✔" in line_test
    assert "passed cleanly" in line_test


def test_system_prompt_includes_live_environment_grounding(dummy_config, tmp_path):
    """System prompt must be grounded with real repo facts, stack, manifest, and git status."""
    readme = tmp_path / "README.md"
    readme.write_text("# Test Repo\nDocumentation.", encoding="utf-8")
    reqs = tmp_path / "requirements.txt"
    reqs.write_text("pytest\n", encoding="utf-8")
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    (issues_dir / "ISSUE_01_easy.md").write_text("# Easy bug", encoding="utf-8")

    repl = ZenithREPL(config=dummy_config)
    prompt = repl._build_system_prompt()

    assert f"Repository: {tmp_path.name}" in prompt
    assert f"Root Path: {tmp_path.resolve()}" in prompt
    assert "Python" in prompt
    assert "requirements.txt" in prompt
    assert "pytest" in prompt
    assert "issues/ISSUE_01_easy.md" in prompt
    assert "No Canned Chatbot Boilerplate" in prompt


def test_is_chatbot_deflection_logic(dummy_config):
    """Verify deflection detection separates genuine greetings from lazy chatbot deflections."""
    repl = ZenithREPL(config=dummy_config)

    # Casual greeting / identity queries should NOT be flagged as deflection
    assert repl._is_chatbot_deflection("Hello! How can I help you?", "hi") is False
    assert repl._is_chatbot_deflection("I am Zenith, your AI assistant.", "who are you") is False
    assert repl._is_chatbot_deflection("Understood, standing by.", "thanks") is False

    # Technical or project status requests receiving a canned chatbot greeting MUST be flagged
    assert repl._is_chatbot_deflection(
        "Hello! I'm Zenith, your expert autonomous AI software engineer. How can I help you today?",
        "project status"
    ) is True
    assert repl._is_chatbot_deflection(
        "I'm currently inspecting the repository. Whether you want to debug an issue, add a feature, or run tests, just let me know!",
        "what are the bugs?"
    ) is True
    assert repl._is_chatbot_deflection(
        "What would you like to build or fix in this project today?",
        "run tests"
    ) is True

    # Real technical answers to project status should NOT be flagged
    assert repl._is_chatbot_deflection(
        "### Project Status\nOn branch main. All 14 tests passing. 1 file modified.",
        "project status"
    ) is False


def test_autonomous_loop_corrects_chatbot_deflection(dummy_config):
    """When a model gives a canned greeting on an engineering prompt, loop nudges it to call tools."""
    repl = ZenithREPL(config=dummy_config)

    # Turn 1: model deflects with canned greeting
    # Turn 2: model calls git_status
    # Turn 3: model synthesizes final answer
    responses = [
        ModelResponse(
            content="Hello! I'm Zenith, your expert autonomous AI software engineer. How can I help you today?",
            tool_calls=[],
            tokens_in=10,
            tokens_out=25,
        ),
        ModelResponse(
            content="",
            tool_calls=[ToolCall(tool="git_status", reasoning="Checking working tree", args={})],
            tokens_in=30,
            tokens_out=15,
        ),
        ModelResponse(
            content="### Repository Status\nBranch: main. Working tree clean.",
            tool_calls=[],
            tokens_in=45,
            tokens_out=20,
        ),
    ]
    repl.adapter.complete = AsyncMock(side_effect=responses)
    repl.tool_engine.execute = MagicMock(return_value=ToolResult(
        tool="git_status",
        args_hash="123",
        status=ResultStatus.SUCCESS,
        raw_output="Working tree clean",
        truncated_output="Working tree clean",
    ))

    asyncio.run(repl.execute_autonomous_loop("project status"))

    # Turn 1 correction turn was appended
    user_nudges = [h for h in repl.history if h.get("role") == "user" and "CORRECTION: Do not provide a generic greeting" in str(h.get("content"))]
    assert len(user_nudges) == 1
    # Tool was invoked
    tool_turns = [h for h in repl.history if h.get("role") == "model" and h.get("tool_calls")]
    assert len(tool_turns) == 1
    assert tool_turns[0]["tool_calls"][0].tool == "git_status"
    # Final answer reached
    assert "Repository Status" in repl.history[-1]["content"]



