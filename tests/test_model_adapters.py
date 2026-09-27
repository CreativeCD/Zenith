"""tests/test_model_adapters.py — Comprehensive tests for Model Adapters and Factory.

Covers:
TEST A — Existing Gemini adapter operation
TEST B — OpenAI-compatible text response parsing
TEST C — OpenAI-compatible tool call normalization
TEST D — Multiple tool calls normalization
TEST E — Malformed JSON tool arguments handling
TEST F — Provider adapter factory routing (Gemini, DeepSeek, Qwen, OpenAI, Unknown)
TEST G — Configuration loading (model ID, base URL, provider)
TEST H — Environment credentials resolution
TEST I — VerificationGate integrity (model cannot bypass verification)
"""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from harness.adapters import (
    GeminiAdapter,
    ModelAdapter,
    ModelResponse,
    OpenAICompatibleAdapter,
    get_model_adapter,
)
from harness.config import HarnessConfig, ModelConfig, load_config
from harness.contracts import ResultStatus, ToolCall
from harness.tool_engine import ToolEngine
from harness.verification import VerificationGate


# ─── TEST A: Existing Gemini Adapter ──────────────────────────────────────────

def test_a_gemini_adapter_instantiation_and_contract():
    """Verify GeminiAdapter implements ModelAdapter protocol and preserves configuration."""
    adapter = GeminiAdapter(
        api_key="test_mock_gemini_key",
        model_name="gemini-2.5-flash",
        fallback_chain=["gemini-3.5-flash"],
    )
    assert isinstance(adapter, ModelAdapter)
    assert adapter.model_name == "gemini-2.5-flash"
    assert adapter.api_key == "test_mock_gemini_key"
    assert adapter.fallback_chain == ["gemini-3.5-flash"]


# ─── TEST B: OpenAI-Compatible Text Response ──────────────────────────────────

@pytest.mark.asyncio
async def test_b_openai_text_response():
    """Mock an OpenAI-compatible text completion response and verify ModelResponse normalization."""
    mock_payload = {
        "id": "chatcmpl-test-123",
        "object": "chat.completion",
        "model": "deepseek-coder",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "I have analyzed the session handling in src/auth/login.js.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 150,
            "completion_tokens": 30,
            "total_tokens": 180,
        },
    }

    adapter = OpenAICompatibleAdapter(
        model_name="deepseek-coder",
        api_key="mock_deepseek_key",
        base_url="https://api.deepseek.com/v1",
        provider="deepseek",
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        response = await adapter.complete(
            system_prompt="You are Zenith.",
            user_message="Analyze session timeout issue.",
        )

        assert isinstance(response, ModelResponse)
        assert response.content == "I have analyzed the session handling in src/auth/login.js."
        assert len(response.tool_calls) == 0
        assert response.tokens_in == 150
        assert response.tokens_out == 30
        assert response.finish_reason == "stop"
        assert response.model == "deepseek-coder"


# ─── TEST C: OpenAI-Compatible Tool Call ──────────────────────────────────────

@pytest.mark.asyncio
async def test_c_openai_tool_call_normalization():
    """Mock a response containing an OpenAI function call and verify ToolCall normalization."""
    mock_payload = {
        "id": "chatcmpl-call-456",
        "model": "qwen-2.5-coder-32b",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Searching for session token validation.",
                    "tool_calls": [
                        {
                            "id": "call_abc123",
                            "type": "function",
                            "function": {
                                "name": "search_code",
                                "arguments": json.dumps({
                                    "query": "session",
                                    "path": "src/auth",
                                    "reasoning": "Find where session tokens are created and validated.",
                                }),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 200, "completion_tokens": 50},
    }

    adapter = OpenAICompatibleAdapter(
        model_name="qwen-2.5-coder-32b",
        api_key="mock_dashscope_key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider="qwen",
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        response = await adapter.complete(
            system_prompt="You are Zenith.",
            user_message="Search for session auth.",
        )

        assert len(response.tool_calls) == 1
        tc = response.tool_calls[0]
        assert isinstance(tc, ToolCall)
        assert tc.tool == "search_code"
        assert tc.reasoning == "Find where session tokens are created and validated."
        assert tc.args["query"] == "session"
        assert tc.args["path"] == "src/auth"
        # Reasoning was extracted out of args for the envelope
        assert "reasoning" not in tc.args


# ─── TEST D: Multiple Tool Calls Normalization ────────────────────────────────

@pytest.mark.asyncio
async def test_d_multiple_tool_calls():
    """Verify that multiple tool calls emitted in a single turn are normalized cleanly."""
    mock_payload = {
        "id": "chatcmpl-multi-789",
        "model": "deepseek-coder",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_symbol",
                                "arguments": json.dumps({
                                    "file_path": "src/auth/login.js",
                                    "symbol_name": "getUserSession",
                                    "reasoning": "Inspect session validator function.",
                                }),
                            },
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "find_references",
                                "arguments": json.dumps({
                                    "symbol_name": "getUserSession",
                                    "reasoning": "Find call sites for getUserSession.",
                                }),
                            },
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 250, "completion_tokens": 80},
    }

    adapter = OpenAICompatibleAdapter(
        model_name="deepseek-coder",
        api_key="mock_key",
        base_url="https://api.deepseek.com/v1",
        provider="deepseek",
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        response = await adapter.complete("prompt", "message")
        assert len(response.tool_calls) == 2
        assert response.tool_calls[0].tool == "get_symbol"
        assert response.tool_calls[0].args["symbol_name"] == "getUserSession"
        assert response.tool_calls[1].tool == "find_references"


# ─── TEST E: Malformed JSON Tool Arguments ────────────────────────────────────

@pytest.mark.asyncio
async def test_e_malformed_tool_arguments_handling():
    """Verify malformed JSON tool arguments do not crash adapter and fail safe in ToolEngine."""
    mock_payload = {
        "id": "chatcmpl-err-000",
        "model": "deepseek-coder",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Attempting file read",
                    "tool_calls": [
                        {
                            "id": "call_bad",
                            "type": "function",
                            "function": {
                                "name": "read_file_range",
                                "arguments": '{"file_path": "login.js", "start_line": 10, BROKEN_JSON',
                            },
                        }
                    ],
                },
            }
        ],
    }

    adapter = OpenAICompatibleAdapter(
        model_name="deepseek-coder",
        api_key="mock_key",
        base_url="https://api.deepseek.com/v1",
        provider="deepseek",
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_payload
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        response = await adapter.complete("prompt", "message")
        assert len(response.tool_calls) == 1
        bad_call = response.tool_calls[0]
        assert bad_call.tool == "read_file_range"
        # Arguments preserved raw under _malformed_raw without crashing
        assert "_malformed_raw" in bad_call.args

        # Verify ToolEngine rejects this call rather than executing it
        engine = ToolEngine(repo_root=".")
        result = engine.execute(bad_call)
        assert result.status == ResultStatus.FAIL


# ─── TEST F: Provider Factory Routing ─────────────────────────────────────────

def test_f_provider_factory_routing():
    """Verify get_model_adapter correctly routes Gemini, DeepSeek, Qwen, OpenAI, and raises on unknown."""
    # 1. Gemini
    g_adapter = get_model_adapter(
        provider="gemini",
        model_name="gemini-2.5-flash",
        api_key="mock_g_key",
    )
    assert isinstance(g_adapter, GeminiAdapter)
    assert g_adapter.model_name == "gemini-2.5-flash"

    # 2. DeepSeek
    d_adapter = get_model_adapter(
        provider="deepseek",
        model_name="deepseek-coder",
        api_key="mock_d_key",
        base_url="https://api.deepseek.com/v1",
    )
    assert isinstance(d_adapter, OpenAICompatibleAdapter)
    assert d_adapter.provider == "deepseek"
    assert d_adapter.model_name == "deepseek-coder"
    assert d_adapter.endpoint == "https://api.deepseek.com/v1/chat/completions"

    # 3. Qwen
    q_adapter = get_model_adapter(
        provider="qwen",
        model_name="qwen-2.5-coder-32b",
        api_key="mock_q_key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    assert isinstance(q_adapter, OpenAICompatibleAdapter)
    assert q_adapter.provider == "qwen"
    assert q_adapter.model_name == "qwen-2.5-coder-32b"

    # 4. OpenAI
    o_adapter = get_model_adapter(
        provider="openai",
        model_name="gpt-4o",
        api_key="mock_o_key",
        base_url="https://api.openai.com/v1",
    )
    assert isinstance(o_adapter, OpenAICompatibleAdapter)
    assert o_adapter.provider == "openai"

    # 5. Unknown provider raises clear error
    with pytest.raises(ValueError, match="Unsupported model provider: 'unknown_vendor'"):
        get_model_adapter(provider="unknown_vendor", model_name="foo")


# ─── TEST G: Configuration Loading ────────────────────────────────────────────

def test_g_configuration_loading(tmp_path):
    """Verify provider, model ID, and base_url are loaded from config and CLI overrides."""
    # Create test yaml config
    cfg_file = tmp_path / "custom_harness_config.yaml"
    cfg_file.write_text(
        """
model:
  provider: "deepseek"
  name: "deepseek-v3"
  base_url: "https://custom.endpoint.com/v1"
  api_key_env: "CUSTOM_DEEPSEEK_KEY"
""",
        encoding="utf-8",
    )

    loaded = load_config(config_path=str(cfg_file))
    assert loaded.model.provider == "deepseek"
    assert loaded.model.name == "deepseek-v3"
    assert loaded.model.base_url == "https://custom.endpoint.com/v1"
    assert loaded.model.api_key_env == "CUSTOM_DEEPSEEK_KEY"

    # CLI overrides take precedence
    cli_overridden = load_config(
        config_path=str(cfg_file),
        cli_args={
            "provider": "qwen",
            "model": "qwen-2.5-coder",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
    )
    assert cli_overridden.model.provider == "qwen"
    assert cli_overridden.model.name == "qwen-2.5-coder"
    assert cli_overridden.model.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


# ─── TEST H: Environment Credentials Resolution ───────────────────────────────

def test_h_environment_credentials_resolution(monkeypatch):
    """Verify API keys are resolved via configured api_key_env or provider defaults."""
    monkeypatch.setenv("MY_SPECIAL_EVAL_KEY", "eval_secret_key_123")
    cfg = HarnessConfig(
        model=ModelConfig(
            provider="deepseek",
            name="deepseek-coder",
            api_key_env="MY_SPECIAL_EVAL_KEY",
            base_url="https://api.deepseek.com/v1",
        )
    )
    cfg.validate()
    assert cfg.model.api_key == "eval_secret_key_123"

    adapter = get_model_adapter(cfg.model)
    assert adapter.api_key == "eval_secret_key_123"


# ─── TEST I: VerificationGate Integrity ───────────────────────────────────────

def test_i_verification_gate_cannot_be_bypassed(tmp_path):
    """Verify that a model response cannot declare VERIFIED without passing VerificationGate."""
    from harness.config import VerificationConfig

    # Create a file with intentional syntax error
    bad_py = tmp_path / "broken.py"
    bad_py.write_text("def broken_syntax(:\n   pass", encoding="utf-8")

    # Configure gate with syntax check enabled
    v_config = VerificationConfig(
        run_syntax_check=True,
        run_lint_check=False,
        run_repro_test=False,
        run_full_regression=False,
        run_diff_audit=False,
        run_side_effect_check=False,
    )
    gate = VerificationGate(config=v_config)
    result = gate.verify(repo_path=str(tmp_path), modified_files=["broken.py"])

    # Even if an LLM outputs "I am verified", VerificationGate deterministically fails
    assert result.status == ResultStatus.FAIL
    assert "broken.py" in str(result.phases.get("SYNTAX", ""))
