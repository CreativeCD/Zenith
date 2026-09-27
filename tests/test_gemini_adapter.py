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


def test_parse_tool_calls_from_text_ignores_prose_json():
    """A legitimate answer that embeds JSON in prose must NOT be hijacked as a tool call."""
    adapter = GeminiAdapter(api_key="mock_key")
    prose = (
        "To fix this, emit the following payload from your client:\n"
        'The {"tool": "hammer", "args": {"nails": 3}} object describes the workflow.\n'
        "Then run the tests."
    )
    assert adapter._parse_tool_calls_from_text(prose) == []

    # Fenced blocks and explicit invocation text still parse
    fenced = '```json\n{"tool": "list_dir", "args": {"path": "."}, "reasoning": "List"}\n```'
    calls = adapter._parse_tool_calls_from_text(fenced)
    assert len(calls) == 1 and calls[0].tool == "list_dir"


def test_build_contents_native_function_history():
    """Model tool_calls and user tool_responses become real function parts when thought_signature is present."""
    from google.genai import types
    from harness.contracts import ToolCall

    adapter = GeminiAdapter(api_key="mock_key")
    raw_fc_part = types.Part(
        function_call=types.FunctionCall(name="read_file_range", args={"file_path": "a.py", "start_line": 1, "end_line": 5}),
        thought_signature=b"mock_thought_sig",
    )
    tc = ToolCall(tool="read_file_range", reasoning="read", args={"file_path": "a.py", "start_line": 1, "end_line": 5}, raw_part=raw_fc_part)
    history = [
        {"role": "user", "content": "Fix the bug"},
        {
            "role": "model",
            "content": "Let me look.",
            "tool_calls": [tc],
            "raw_parts": [raw_fc_part],
        },
        {
            "role": "user",
            "tool_responses": [{"name": "read_file_range", "args": {}, "output": "x=1", "status": "SUCCESS", "exit_code": 0}],
        },
    ]
    contents = adapter._build_contents(history, user_message="")
    assert len(contents) == 3
    mc = contents[1]
    assert getattr(mc.parts[0], "text", None) == "Let me look."
    fc = getattr(mc.parts[1], "function_call", None)
    assert fc is not None and fc.name == "read_file_range"
    assert getattr(mc.parts[1], "thought_signature", None) == b"mock_thought_sig"
    rc = contents[2]
    fr = getattr(rc.parts[0], "function_response", None)
    assert fr is not None and fr.name == "read_file_range"
    assert fr.response["output"] == "x=1"


def test_build_contents_without_thought_signature_falls_back_to_text():
    """Missing thought_signature safely falls back to text representation to avoid Gemini 400."""
    from harness.contracts import ToolCall

    adapter = GeminiAdapter(api_key="mock_key")
    history = [
        {"role": "user", "content": "Fix the bug"},
        {
            "role": "model",
            "content": "Let me look.",
            "tool_calls": [ToolCall(tool="read_file_range", reasoning="read", args={"file_path": "a.py"})],
        },
        {
            "role": "user",
            "tool_responses": [{"name": "read_file_range", "args": {}, "output": "x=1", "status": "SUCCESS", "exit_code": 0}],
        },
    ]
    contents = adapter._build_contents(history, user_message="")
    assert len(contents) == 3
    mc = contents[1]
    assert "Invoked tool read_file_range" in mc.parts[0].text
    rc = contents[2]
    assert "Observation from `read_file_range`" in rc.parts[0].text


def test_streaming_complete_invokes_callbacks():
    """The streaming path surfaces text deltas through on_text and builds a ModelResponse."""
    adapter = GeminiAdapter(api_key="mock_key", model_name="gemini-3.5-flash-lite", fallback_chain=[])

    async def _stream_gen():
        for delta in ("Hel", "lo ", "world"):
            chunk = MagicMock()
            chunk.usage_metadata = None
            chunk.candidates = [MagicMock()]
            chunk.candidates[0].finish_reason = MagicMock(name="STOP")
            part = MagicMock()
            part.function_call = None
            part.thought = None
            part.text = delta
            chunk.candidates[0].content.parts = [part]
            yield chunk

    client = MagicMock()
    client.aio.models.generate_content_stream = AsyncMock(return_value=_stream_gen())
    adapter._clients["mock_key"] = client

    deltas: list[str] = []
    res = asyncio.run(adapter.complete(
        system_prompt="sys",
        user_message="hi",
        stream=True,
        on_text=deltas.append,
    ))
    assert "".join(deltas) == "Hello world"
    assert res.content == "Hello world"
    assert res.model == "gemini-3.5-flash-lite"


def test_build_contents_user_text_after_function_response_separate_content():
    """A user text prompt following a native function response turn must be in a separate Content."""
    from google.genai import types
    from harness.contracts import ToolCall

    adapter = GeminiAdapter(api_key="mock_key")
    raw_fc_part = types.Part(
        function_call=types.FunctionCall(name="emit_done_candidate", args={}),
        thought_signature=b"mock_thought_sig",
    )

    tc = ToolCall(tool="emit_done_candidate", reasoning="verified", args={}, raw_part=raw_fc_part)
    history = [
        {"role": "user", "content": "Fix the issue"},
        {"role": "model", "content": "", "tool_calls": [tc], "raw_parts": [raw_fc_part]},
        {
            "role": "user",
            "tool_responses": [{"name": "emit_done_candidate", "output": "DONE_CANDIDATE recorded", "status": "SUCCESS", "exit_code": 0}],
        },
        {"role": "user", "content": "Done candidate accepted. Synthesize your final summary now."},
    ]

    contents = adapter._build_contents(history, user_message="")
    assert len(contents) == 4
    # Content 2 is function response turn
    assert contents[2].role == "user"
    assert any(getattr(p, "function_response", None) is not None for p in contents[2].parts)
    assert not any(getattr(p, "text", None) for p in contents[2].parts)

    # Content 3 is separate user text turn (not merged into Content 2)
    assert contents[3].role == "user"
    assert len(contents[3].parts) == 1
    assert "Done candidate accepted" in contents[3].parts[0].text


def test_consume_stream_chunk_timeout_detection():
    """Streaming iterator that stalls longer than chunk_timeout raises or reports stream_error."""
    adapter = GeminiAdapter(api_key="mock_key")

    async def _stalling_stream():
        chunk = MagicMock()
        chunk.usage_metadata = None
        chunk.candidates = [MagicMock()]
        chunk.candidates[0].finish_reason = None
        part = MagicMock()
        part.function_call = None
        part.thought = None
        part.text = "I have"
        chunk.candidates[0].content.parts = [part]
        yield chunk
        # Simulate stall
        await asyncio.sleep(0.5)

    deltas: list[str] = []
    # Test with very short chunk_timeout of 0.05s
    res = asyncio.run(adapter._consume_stream(
        _stalling_stream(),
        on_text=deltas.append,
        chunk_timeout=0.05,
    ))
    assert res.get("finish_reason") == "stream_error"
    assert "I have" in res.get("text", "")
    assert isinstance(res.get("stream_error"), TimeoutError)



