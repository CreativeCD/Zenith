# Model Provider Configuration Guide

Zenith is model-provider agnostic. The autonomous agent core, 14-tool execution engine, 6-phase deterministic verification gate, and CLI stream operate independently of the underlying LLM provider.

---

## Architecture Overview

```
                         ZENITH
                            │
                       Orchestrator
                            │
                    get_model_adapter()
                            │
             ┌──────────────┼──────────────┐
             ↓              ↓              ↓
       GeminiAdapter  OpenAICompatible   ...
                         Adapter
                            │
                    ┌───────┴────────┐
                    ↓                ↓
                 DeepSeek          Qwen
                    │                │
                    └───────┬────────┘
                            ↓
                      ModelResponse
                            ↓
                       ToolEngine
                            ↓
                    VerificationGate
                            ↓
                      Telemetry/SSE
                            ↓
                           CLI
```

---

## Configuration Methods

Providers can be configured via:
1. `harness_config.yaml`
2. CLI flags (`--provider`, `--model`, `--base-url`, `--api-key-env`)
3. Environment variables

### 1. Google Gemini

**Configuration (`harness_config.yaml`):**
```yaml
model:
  provider: "gemini"
  name: "gemini-2.5-flash"  # or gemini-3.5-flash, gemini-2.5-pro
  fallback_chain:
    - "gemini-3.5-flash"
    - "gemini-3.5-flash-lite"
```

**Environment Variable:**
```bash
export AI_API_KEY="your-gemini-api-key"
```

---

### 2. DeepSeek

Zenith interfaces with any OpenAI-compatible DeepSeek inference endpoint (official DeepSeek API, local vLLM, Ollama, or third-party inference proxy).

**Configuration (`harness_config.yaml`):**
```yaml
model:
  provider: "deepseek"
  name: "<evaluator-deepseek-model-id>"  # e.g. "deepseek-coder", "deepseek-chat"
  base_url: "https://api.deepseek.com/v1" # or evaluator proxy endpoint
  api_key_env: "DEEPSEEK_API_KEY"
```

**CLI Execution:**
```bash
python -m harness.cli --provider deepseek --model <model-id> --base-url https://api.deepseek.com/v1
```

**Environment Variable:**
```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
```

---

### 3. Qwen (Alibaba Cloud Model Studio / DashScope / vLLM / Ollama)

Qwen models are accessed through OpenAI-compatible endpoints.

**Configuration (`harness_config.yaml`):**
```yaml
model:
  provider: "qwen"
  name: "<evaluator-qwen-model-id>"  # e.g. "qwen2.5-coder-32b-instruct"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1" # or custom evaluator endpoint
  api_key_env: "DASHSCOPE_API_KEY"
```

**CLI Execution:**
```bash
python -m harness.cli --provider qwen --model <model-id> --base-url <endpoint-url> --api-key-env DASHSCOPE_API_KEY
```

**Environment Variable:**
```bash
export DASHSCOPE_API_KEY="your-dashscope-api-key"
# or export QWEN_API_KEY="..."
```

---

### 4. Custom Evaluator Endpoint (Generic OpenAI-Compatible)

For any private evaluator harness, proxy, or local server:

**Configuration (`harness_config.yaml`):**
```yaml
model:
  provider: "openai"
  name: "<evaluator-assigned-model>"
  base_url: "http://<evaluator-host>:<port>/v1"
  api_key_env: "EVAL_API_KEY"
```

**CLI Execution:**
```bash
python -m harness.cli --provider openai --model custom-model --base-url http://127.0.0.1:8000/v1 --api-key-env EVAL_API_KEY
```

---

## Key Contracts & Behavioral Guarantees

1. **Deterministic Verification Gate**: The LLM has zero authority to declare completion or set verification to `PASS`. Emitting `DONE_CANDIDATE` submits the changes to real subprocess tests (`pytest`, `ruff`, AST validation, diff scope containment, and side-effect imports).
2. **Provider-Agnostic Tool Calls**: Tool calls are normalized into `ToolCall(tool=..., reasoning=..., args=...)`. If a model omits the `reasoning` field in its arguments, Zenith safely synthesizes a provider-agnostic intent description so execution proceeds without requiring vendor-proprietary reasoning tokens.
3. **Zero Source Code Modifications**: Evaluators can seamlessly switch between Gemini, DeepSeek, Qwen, or custom endpoints purely through YAML or CLI parameters.
