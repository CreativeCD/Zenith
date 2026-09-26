"""Unit tests for harness/interactive.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from harness.config import HarnessConfig
from harness.interactive import ZenithREPL


@pytest.fixture
def dummy_config(tmp_path):
    config = HarnessConfig()
    config.repo_path = str(tmp_path)
    config.telemetry.output_dir = str(tmp_path / ".harness")
    return config


def test_repl_init(dummy_config):
    repl = ZenithREPL(config=dummy_config)
    assert repl.repo_path == str(dummy_config.repo_path)
    assert repl.session_active is True
    assert len(repl.history) == 0


def test_repl_casual_greeting(dummy_config):
    repl = ZenithREPL(config=dummy_config)
    asyncio.run(repl.process_user_message("hi"))
    assert len(repl.history) == 2
    assert repl.history[0]["role"] == "user"
    assert repl.history[1]["role"] == "model"
    assert "Zenith" in repl.history[1]["content"]


def test_repl_casual_exit(dummy_config):
    repl = ZenithREPL(config=dummy_config)
    asyncio.run(repl.process_user_message("bye"))
    assert repl.session_active is False


def test_repl_auto_debug_all_pass(dummy_config, monkeypatch):
    repl = ZenithREPL(config=dummy_config)
    from harness.contracts import ResultStatus, ToolResult

    dummy_tool_res = ToolResult(
        tool="run_test_suite",
        args_hash="",
        status=ResultStatus.SUCCESS,
        raw_output="5 passed in 0.1s",
        truncated_output="5 passed in 0.1s",
        exit_code=0,
    )
    monkeypatch.setattr("harness.interactive.run_test_suite", lambda repo_root: dummy_tool_res)

    asyncio.run(repl.auto_debug())
