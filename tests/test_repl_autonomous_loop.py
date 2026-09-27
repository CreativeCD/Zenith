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

    # Verify history recorded tool and observation
    assert len(repl.history) == 4
    assert repl.history[1]["role"] == "model"
    assert repl.history[2]["role"] == "user"
    assert "Observation from `read_file_range`" in repl.history[2]["content"]
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

    # The oldest observation should be compacted because keep_recent_pairs is 3
    # Check that older observation was compacted
    first_obs_msg = [m for m in repl.history if "Observation from `search_code`" in m.get("content", "")][0]
    assert "(compacted)" in first_obs_msg["content"]

