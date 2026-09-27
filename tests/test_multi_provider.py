"""tests/test_multi_provider.py — Unit tests for Multi-Provider Adapter and Key Pools.

Validates:
1. Automatic key discovery for DeepSeek, Gemini, and OpenAI.
2. Multi-key pooling (1 key, 3 keys, 8 keys) via numbered env vars and comma-separation.
3. Dynamic provider routing (DeepSeek used when Gemini is absent during evaluation).
4. Fair round-robin rotation across multiple keys in the pool.
5. HarnessConfig validation accepting DeepSeek keys in evaluation mode.
6. Fallback tool-call parsing from textual model output.
7. Real-time SSE streaming for OpenAI/DeepSeek with on_text and on_thought callbacks.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch
import pytest

from harness.adapters.key_pool import KeyPoolManager
from harness.adapters.multi_provider import MultiProviderAdapter, discover_provider_keys
from harness.adapters.openai_compat_adapter import OpenAICompatAdapter
from harness.config import HarnessConfig


# ─── 1. Key Discovery Tests ───────────────────────────────────────────────────

def test_discover_provider_keys_empty():
    with patch.dict(os.environ, {}, clear=True):
        res = discover_provider_keys()
        assert res["gemini"] == []
        assert res["deepseek"] == []
        assert res["openai"] == []


def test_discover_provider_keys_filters_placeholders():
    env = {
        "DEEPSEEK_API_KEY": "your_deepseek_api_key_here",
        "AI_API_KEY": "REPLACE_WITH_KEY",
        "OPENAI_API_KEY": "",
    }
    with patch.dict(os.environ, env, clear=True):
        res = discover_provider_keys()
        assert res["deepseek"] == []
        assert res["gemini"] == []
        assert res["openai"] == []


def test_discover_deepseek_8_keys_numbered():
    """Verify that if 8 DeepSeek keys are provided (DEEPSEEK_API_KEY_1..8), all 8 are detected."""
    env = {f"DEEPSEEK_API_KEY_{i}": f"sk-deepseek-key-{i}" for i in range(1, 9)}
    with patch.dict(os.environ, env, clear=True):
        res = discover_provider_keys()
        assert len(res["deepseek"]) == 8
        assert res["deepseek"] == [f"sk-deepseek-key-{i}" for i in range(1, 9)]
        assert res["gemini"] == []
        assert res["openai"] == []


def test_discover_deepseek_comma_separated():
    """Verify comma/semicolon-separated keys are parsed into distinct pool entries."""
    env = {
        "DEEPSEEK_API_KEY": "sk-key-a, sk-key-b; sk-key-c\nsk-key-d",
    }
    with patch.dict(os.environ, env, clear=True):
        res = discover_provider_keys()
        assert len(res["deepseek"]) == 4
        assert res["deepseek"] == ["sk-key-a", "sk-key-b", "sk-key-c", "sk-key-d"]


def test_discover_gemini_and_deepseek_simultaneously():
    env = {
        "AI_API_KEY": "gemini-key-1",
        "AI_API_KEY_1": "gemini-key-2",
        "DEEPSEEK_API_KEY": "sk-deepseek-1",
        "DEEPSEEK_API_KEY_1": "sk-deepseek-2",
        "DEEPSEEK_API_KEY_2": "sk-deepseek-3",
    }
    with patch.dict(os.environ, env, clear=True):
        res = discover_provider_keys()
        assert len(res["gemini"]) == 2
        assert len(res["deepseek"]) == 3


# ─── 2. MultiProviderAdapter Routing & Pooling Tests ─────────────────────────

def test_adapter_selects_deepseek_when_only_deepseek_keys_present():
    """Simulates evaluation environment where only DeepSeek keys are available."""
    env = {
        "DEEPSEEK_API_KEY_1": "sk-eval-1",
        "DEEPSEEK_API_KEY_2": "sk-eval-2",
        "DEEPSEEK_API_KEY_3": "sk-eval-3",
    }
    with patch.dict(os.environ, env, clear=True):
        adapter = MultiProviderAdapter()
        assert adapter.active_provider == "DeepSeek"
        assert adapter.total_keys == 3
        assert "DeepSeek (3 keys)" in adapter.provider_summary
        assert adapter.model_name == "deepseek-chat"


def test_adapter_pools_all_8_deepseek_keys():
    """Ensures that when 8 keys are present, all 8 are pooled and rotated."""
    keys = [f"sk-test-key-{i}" for i in range(1, 9)]
    adapter = MultiProviderAdapter(
        deepseek_keys=keys,
        auto_discover=False,
    )
    assert adapter.active_provider == "DeepSeek"
    assert adapter.total_keys == 8

    # Test round-robin across all 8 keys
    seen_keys = []
    for _ in range(8):
        k, idx = adapter.key_pool.get_next_key()
        seen_keys.append(k)

    assert seen_keys == keys


def test_adapter_selects_gemini_when_gemini_keys_present():
    adapter = MultiProviderAdapter(
        gemini_keys=["gem-k1", "gem-k2"],
        deepseek_keys=[],
        auto_discover=False,
    )
    assert adapter.active_provider == "Gemini"
    assert adapter.total_keys == 2
    assert "Gemini (2 keys)" in adapter.provider_summary


def test_adapter_user_override_provider_preference():
    """PROVIDER=deepseek should prioritize DeepSeek even if Gemini keys exist."""
    env = {
        "AI_API_KEY": "gemini-1",
        "DEEPSEEK_API_KEY": "sk-deepseek-1",
        "PROVIDER": "deepseek",
    }
    with patch.dict(os.environ, env, clear=True):
        adapter = MultiProviderAdapter()
        assert adapter.active_provider == "DeepSeek"
        assert adapter.total_keys == 1


# ─── 3. Tool Parsing Fallback in OpenAI/DeepSeek Adapter ──────────────────────

def test_openai_compat_parse_tool_calls_from_text():
    raw_markdown = (
        "Let me inspect the file.\n\n"
        "```json\n"
        "{\n"
        '  "tool": "read_file",\n'
        '  "args": {"path": "src/main.py", "start_line": 1, "end_line": 50},\n'
        '  "reasoning": "Inspect entrypoint"\n'
        "}\n"
        "```"
    )
    calls = OpenAICompatAdapter._parse_tool_calls_from_text(raw_markdown)
    assert len(calls) == 1
    assert calls[0].tool == "read_file"
    assert calls[0].args == {"path": "src/main.py", "start_line": 1, "end_line": 50}
    assert calls[0].reasoning == "Inspect entrypoint"


def test_multiprovider_delegates_tool_parsing():
    adapter = MultiProviderAdapter(
        deepseek_keys=["sk-mock"],
        auto_discover=False,
    )
    raw_text = 'Tool Call: apply_patch with args {"patch": "diff --git..."}'
    calls = adapter._parse_tool_calls_from_text(raw_text)
    assert len(calls) == 1
    assert calls[0].tool == "apply_patch"


# ─── 4. HarnessConfig Validation with DeepSeek Keys ─────────────────────────

def test_config_validate_succeeds_with_only_deepseek_keys():
    """SWE-bench / eval runners provide DEEPSEEK_API_KEY. Validation must pass."""
    env = {
        "DEEPSEEK_API_KEY_1": "sk-eval-ds-1",
        "DEEPSEEK_API_KEY_2": "sk-eval-ds-2",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = HarnessConfig()
        cfg.validate()
        assert cfg.model.api_keys == ["sk-eval-ds-1", "sk-eval-ds-2"]
        assert cfg.model.api_key == "sk-eval-ds-1"
        assert cfg.model.name == "deepseek-chat"


def test_config_validate_raises_when_no_provider_keys():
    with patch.dict(os.environ, {}, clear=True):
        cfg = HarnessConfig()
        with pytest.raises(OSError) as exc_info:
            cfg.validate()
        assert "DEEPSEEK_API_KEY" in str(exc_info.value)
        assert "AI_API_KEY" in str(exc_info.value)


# ─── 5. KeyPoolManager Multi-Prefix and Comma Support ─────────────────────────

def test_key_pool_manager_loads_comma_separated():
    pool = KeyPoolManager(keys=["key1, key2 , key3"])
    assert pool.total_keys == 3
    assert pool.keys == ["key1", "key2", "key3"]


def test_key_pool_manager_loads_mixed_list():
    pool = KeyPoolManager(keys=["key1", "key2,key3", "key4"])
    assert pool.total_keys == 4
    assert pool.keys == ["key1", "key2", "key3", "key4"]


# ─── 6. Streaming Callback Verification ───────────────────────────────────────

def test_openai_compat_streaming_text_and_thought():
    """Verify that SSE stream triggers on_text and on_thought callbacks."""
    adapter = OpenAICompatAdapter(api_key="sk-test-mock", model_name="deepseek-reasoner")

    sse_lines = [
        'data: {"choices": [{"delta": {"reasoning_content": "Thinking step 1... "}}]}',
        'data: {"choices": [{"delta": {"reasoning_content": "Found the bug."}}]}',
        'data: {"choices": [{"delta": {"content": "Here is "}}]}',
        'data: {"choices": [{"delta": {"content": "the solution."}}]}',
        'data: [DONE]',
    ]

    async def _mock_aiter_lines():
        for line in sse_lines:
            yield line

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = _mock_aiter_lines

    class MockStreamContext:
        async def __aenter__(self):
            return mock_resp
        async def __aexit__(self, *args):
            pass

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=MockStreamContext())

    class MockClientContext:
        async def __aenter__(self):
            return mock_client
        async def __aexit__(self, *args):
            pass

    text_chunks: list[str] = []
    thought_chunks: list[str] = []

    with patch("httpx.AsyncClient", return_value=MockClientContext()):
        res = asyncio.run(adapter.complete(
            system_prompt="sys",
            user_message="hi",
            stream=True,
            on_text=text_chunks.append,
            on_thought=thought_chunks.append,
        ))

    assert "".join(text_chunks) == "Here is the solution."
    assert "".join(thought_chunks) == "Thinking step 1... Found the bug."
    assert res.content == "Here is the solution."


def test_openai_compat_streaming_tool_calls():
    """Verify streamed tool call deltas are accumulated into ToolCall objects."""
    adapter = OpenAICompatAdapter(api_key="sk-test-mock", model_name="deepseek-chat")

    sse_lines = [
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "read_file_range", "arguments": "{\\"file_path\\": \\"main.py\\""}}]}}]}',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ", \\"start_line\\": 1, \\"end_line\\": 10}"}}]}}]}',
        'data: [DONE]',
    ]

    async def _mock_aiter_lines():
        for line in sse_lines:
            yield line

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = _mock_aiter_lines

    class MockStreamContext:
        async def __aenter__(self):
            return mock_resp
        async def __aexit__(self, *args):
            pass

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=MockStreamContext())

    class MockClientContext:
        async def __aenter__(self):
            return mock_client
        async def __aexit__(self, *args):
            pass

    with patch("httpx.AsyncClient", return_value=MockClientContext()):
        res = asyncio.run(adapter.complete(
            system_prompt="sys",
            user_message="hi",
            stream=True,
        ))

    assert len(res.tool_calls) == 1
    assert res.tool_calls[0].tool == "read_file_range"
    assert res.tool_calls[0].args == {"file_path": "main.py", "start_line": 1, "end_line": 10}
