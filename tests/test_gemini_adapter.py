"""tests/test_gemini_adapter.py — Unit tests for GeminiAdapter with key pool & cascade."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from harness.adapters.gemini_adapter import GeminiAdapter
from harness.adapters.key_pool import KeyPoolManager


def test_gemini_adapter_pricing_and_init():
    adapter = GeminiAdapter(
        api_keys=["key1", "key2"],
        model_name="gemini-3.6-flash",
        fallback_chain=["gemini-3.5-flash", "gemini-3.5-flash-lite"],
    )
    assert "gemini-3.6-flash" in adapter.PRICING
    assert adapter.PRICING["gemini-3.6-flash"]["output"] == 0.30
    assert adapter.key_pool.total_keys == 2
    assert adapter.model_name == "gemini-3.6-flash"
    assert adapter.fallback_chain == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]


def test_is_truncated():
    # Odd backticks -> truncated
    odd_code = "Here is the code:\n```python\ndef test():\n    return 42\n"
    assert GeminiAdapter._is_truncated(odd_code) is True

    # Even backticks + ended -> not truncated
    even_code = "Here is the code:\n```python\ndef test():\n    return 42\n```\n"
    assert GeminiAdapter._is_truncated(even_code) is False

    # Incomplete bolding
    bold_cut = "This is a very important **message that was cut"
    assert GeminiAdapter._is_truncated(bold_cut) is True

    # Proper sentence termination
    complete_text = "The task has been successfully verified and all tests pass with zero errors."
    assert GeminiAdapter._is_truncated(complete_text) is False


def test_thinking_config_mapping():
    adapter = GeminiAdapter(api_key="mock_key", model_name="gemini-3.6-flash")

    high_cfg = adapter._get_thinking_config("high", "gemini-3.6-flash")
    assert high_cfg.thinking_budget == 24576

    med_cfg = adapter._get_thinking_config("medium", "gemini-3.6-flash")
    assert med_cfg.thinking_budget == 8192

    low_cfg = adapter._get_thinking_config("low", "gemini-3.6-flash")
    assert low_cfg.thinking_budget == 2048

    none_cfg = adapter._get_thinking_config("none", "gemini-3.6-flash")
    assert none_cfg.thinking_budget == 0

    # Flash-lite should return None
    lite_cfg = adapter._get_thinking_config("high", "gemini-3.5-flash-lite")
    assert lite_cfg is None


def test_key_failover_on_429():
    pool = KeyPoolManager(keys=["key1", "key2"])
    adapter = GeminiAdapter(
        key_pool=pool,
        model_name="gemini-3.6-flash",
        fallback_chain=[],
    )

    mock_client1 = MagicMock()
    mock_client1.aio.models.generate_content = AsyncMock(
        side_effect=Exception("429 RESOURCE_EXHAUSTED retryDelay: '15s'")
    )

    mock_resp = MagicMock()
    mock_resp.candidates = [
        MagicMock(
            content=MagicMock(parts=[MagicMock(text="Success from key 2.")]),
            finish_reason=MagicMock(name="STOP"),
        )
    ]
    mock_resp.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)

    mock_client2 = MagicMock()
    mock_client2.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    adapter._clients["key1"] = mock_client1
    adapter._clients["key2"] = mock_client2

    res = asyncio.run(adapter.complete("system prompt", "user query"))
    assert "Success from key 2" in res.content
    assert pool._stats["key1"].errors == 1
    assert pool._stats["key1"].is_cooling_down is True
    assert pool._stats["key2"].calls == 1


def test_model_cascade_fallback_on_all_keys_exhausted():
    pool = KeyPoolManager(keys=["key1"])
    adapter = GeminiAdapter(
        key_pool=pool,
        model_name="gemini-3.6-flash",
        fallback_chain=["gemini-3.5-flash"],
    )

    mock_client = MagicMock()
    call_count = 0

    async def side_effect(model, contents, config):
        nonlocal call_count
        call_count += 1
        if model == "gemini-3.6-flash":
            raise Exception("429 RESOURCE_EXHAUSTED retry in 40s")
        # On fallback model, succeed
        resp = MagicMock()
        resp.candidates = [
            MagicMock(
                content=MagicMock(parts=[MagicMock(text="Success from cascade fallback.")]),
                finish_reason=MagicMock(name="STOP"),
            )
        ]
        resp.usage_metadata = MagicMock(prompt_token_count=10, candidates_token_count=5)
        return resp

    mock_client.aio.models.generate_content = AsyncMock(side_effect=side_effect)
    adapter._clients["key1"] = mock_client

    res = asyncio.run(adapter.complete("system prompt", "user query"))
    assert "Success from cascade fallback" in res.content
    assert res.model == "gemini-3.5-flash"


def test_parse_tool_calls_text_python_dict():
    adapter = GeminiAdapter(api_key="mock_key")
    text = "Zenith >\nInvoked tool read_file_range with args {'end_line': 250, 'file_path': 'src/taskmanager/tasks.py', 'reasoning': 'Read tasks.py to check active_tasks', 'start_line': 1}"
    calls = adapter._parse_tool_calls_from_text(text)
    assert len(calls) == 1
    assert calls[0].tool == "read_file_range"
    assert calls[0].reasoning == "Read tasks.py to check active_tasks"
    assert calls[0].args["file_path"] == "src/taskmanager/tasks.py"
    assert calls[0].args["start_line"] == 1
    assert calls[0].args["end_line"] == 250


def test_parse_tool_calls_reasoning_fallback():
    adapter = GeminiAdapter(api_key="mock_key")
    mock_part = MagicMock()
    mock_part.function_call.name = "run_test_suite"
    mock_part.function_call.args = {}
    calls = adapter._parse_tool_calls([mock_part])
    assert len(calls) == 1
    assert calls[0].tool == "run_test_suite"
    assert calls[0].reasoning is not None
    assert len(calls[0].reasoning) > 0
