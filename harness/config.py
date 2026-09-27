"""harness/config.py — Configuration Loader, Validator & Overrider.

Reference: PRD.md §14 | architecture.md §7.10
Loads harness_config.yaml, validates schema, applies CLI overrides, and loads secrets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env file at startup if present
# 1. Global ~/.zenith/.env (persists user API keys across all repos)
global_env = Path.home() / ".zenith" / ".env"
if global_env.exists():
    load_dotenv(global_env)
# 2. Local working directory .env
load_dotenv()


@dataclass
class ModelConfig:
    name: str = "gemini-2.5-flash"
    provider: str = "gemini"
    api_key_env: str | None = None
    base_url: str | None = None
    timeout: float = 60.0
    max_retries: int = 3
    plan_model: str | None = None
    temperature_plan: float = 0.1
    temperature_act: float = 0.0
    temperature_reflect: float = 0.05
    temperature_summarize: float = 0.0
    seed: int = 42
    max_output_tokens: int = 4096
    enable_thinking: bool = False
    use_structured_output: bool = True
    api_key: str | None = field(default=None, repr=False)
    api_keys: list[str] = field(default_factory=list, repr=False)
    fallback_chain: list[str] = field(
        default_factory=lambda: ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
    )
    reasoning_effort_plan: str = "high"
    reasoning_effort_act: str = "low"
    reasoning_effort_reflect: str = "medium"
    reasoning_effort_recovery: str = "high"
    reasoning_effort_summarize: str = "none"
    max_continuations: int = 3


@dataclass
class ContextConfig:
    max_context_tokens: int = 32000
    response_reserve_tokens: int = 4000
    persona_budget_tokens: int = 300
    goal_budget_tokens: int = 200
    repo_context_budget_tokens: int = 1000
    working_memory_budget_tokens: int = 800
    recent_turns_budget_tokens: int = 4000
    compression_threshold: float = 0.70
    observation_head_lines: int = 20
    observation_tail_lines: int = 50
    observation_mid_threshold: int = 300
    kv_cache_enabled: bool = True


@dataclass
class AgentConfig:
    max_steps: int = 25
    max_plan_revisions: int = 3
    max_loop_count: int = 3
    agent_mode: str = "auto"
    multi_agent_threshold: str = "MEDIUM"
    complexity_scoring: bool = True
    rollback_checkpoints: bool = True


@dataclass
class ToolsConfig:
    max_search_results: int = 50
    max_read_lines: int = 250
    max_symbol_output_lines: int = 50
    max_reference_locations: int = 30
    sandbox_timeout_sec: int = 30
    sandbox_memory_mb: int = 512
    test_suite_timeout_sec: int = 120
    test_output_lines: int = 80
    bash_output_lines: int = 200
    git_diff_lines: int = 500
    deduplicator_window: int = 10


@dataclass
class ExternalSkillsConfig:
    enabled: bool = True
    cache_ttl_hours: int = 24
    max_tokens_per_snippet: int = 500
    prefetch_at_startup: bool = True
    swebench_index_path: str = ".harness/swebench_index"
    github_api_token_env: str = "GITHUB_TOKEN"
    github_token: str | None = field(default=None, repr=False)


@dataclass
class VerificationConfig:
    run_syntax_check: bool = True
    run_lint_check: bool = True
    run_repro_test: bool = True
    run_full_regression: bool = True
    run_diff_audit: bool = True
    run_side_effect_check: bool = True
    linter: str = "ruff"
    linter_fail_on_new_only: bool = True


@dataclass
class TelemetryConfig:
    enabled: bool = True
    output_dir: str = ".harness"
    stream_to_stdout: bool = False
    include_full_prompts: bool = False
    schema_version: str = "1.0"


@dataclass
class ReportConfig:
    auto_generate: bool = True
    format: str = "markdown"
    include_cost_breakdown: bool = True
    include_diff: bool = True
    include_agent_decisions: bool = True


@dataclass
class HarnessConfig:
    repo_path: str = "."
    issue_path: str = "issue.txt"
    dry_run: bool = False
    trust: bool = False
    model: ModelConfig = field(default_factory=ModelConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    external_skills: ExternalSkillsConfig = field(default_factory=ExternalSkillsConfig)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    report: ReportConfig = field(default_factory=ReportConfig)

    def validate(self) -> None:
        """Validate paths, boundaries, and required environment credentials."""
        # API Key check (unless dry_run)
        if not self.dry_run and not self.model.api_keys and not self.model.api_key:
            provider = (self.model.provider or "gemini").lower()
            if provider == "gemini":
                from harness.adapters.key_pool import KeyPoolManager
                env_keys = KeyPoolManager._load_keys_from_env()
                if not env_keys:
                    raise OSError(
                        "AI_API_KEY environment variable is not set or empty. "
                        "Define AI_API_KEY in your environment or .env file."
                    )
                self.model.api_keys = env_keys
                self.model.api_key = env_keys[0]
            else:
                key_env = self.model.api_key_env
                resolved_key = os.environ.get(key_env) if key_env else None
                hint_env = key_env or "API_KEY"

                if not resolved_key:
                    if provider == "deepseek":
                        resolved_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
                        hint_env = key_env or "DEEPSEEK_API_KEY"
                    elif provider == "qwen":
                        resolved_key = (
                            os.environ.get("DASHSCOPE_API_KEY")
                            or os.environ.get("QWEN_API_KEY")
                            or os.environ.get("OPENAI_API_KEY")
                        )
                        hint_env = key_env or "DASHSCOPE_API_KEY (or QWEN_API_KEY)"
                    else:
                        resolved_key = os.environ.get("OPENAI_API_KEY")
                        hint_env = key_env or "OPENAI_API_KEY"

                if not resolved_key:
                    raise OSError(
                        f"API key for provider '{provider}' not found. "
                        f"Please set {hint_env} in your environment or configure model.api_key_env."
                    )
                self.model.api_key = resolved_key

        # Check required base_url for providers that lack a safe universal default
        provider = (self.model.provider or "gemini").lower()
        if provider == "qwen" and not self.model.base_url and not os.environ.get("DASHSCOPE_API_KEY"):
            raise ValueError(
                "base_url is required for provider 'qwen' (e.g. 'https://dashscope.aliyuncs.com/compatible-mode/v1' "
                "or your evaluator's endpoint). Please configure model.base_url in harness_config.yaml or pass --base-url."
            )

        # GitHub token resolution
        if not self.external_skills.github_token:
            token_env = self.external_skills.github_api_token_env
            self.external_skills.github_token = os.environ.get(token_env)

        # Output dir resolution
        Path(self.telemetry.output_dir).mkdir(parents=True, exist_ok=True)


def load_config(
    config_path: str | None = None,
    cli_args: dict[str, Any] | None = None
) -> HarnessConfig:
    """Load config from YAML file, apply defaults, and override with CLI args."""
    cfg = HarnessConfig()

    target_config = config_path or "harness_config.yaml"
    if Path(target_config).exists():
        with open(target_config, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        if "model" in raw:
            for k, v in raw["model"].items():
                if hasattr(cfg.model, k):
                    setattr(cfg.model, k, v)

        if "context" in raw:
            for k, v in raw["context"].items():
                if hasattr(cfg.context, k):
                    setattr(cfg.context, k, v)

        if "agent" in raw:
            for k, v in raw["agent"].items():
                if hasattr(cfg.agent, k):
                    setattr(cfg.agent, k, v)

        if "tools" in raw:
            for k, v in raw["tools"].items():
                if hasattr(cfg.tools, k):
                    setattr(cfg.tools, k, v)

        if "external_skills" in raw:
            for k, v in raw["external_skills"].items():
                if hasattr(cfg.external_skills, k):
                    setattr(cfg.external_skills, k, v)

        if "verification" in raw:
            for k, v in raw["verification"].items():
                if hasattr(cfg.verification, k):
                    setattr(cfg.verification, k, v)

        if "telemetry" in raw:
            for k, v in raw["telemetry"].items():
                if hasattr(cfg.telemetry, k):
                    setattr(cfg.telemetry, k, v)

        if "report" in raw:
            for k, v in raw["report"].items():
                if hasattr(cfg.report, k):
                    setattr(cfg.report, k, v)

    # Apply CLI Overrides
    if cli_args:
        if cli_args.get("repo"):
            cfg.repo_path = cli_args["repo"]
        if cli_args.get("trust") or cli_args.get("yes"):
            cfg.trust = True
        if cli_args.get("issue"):
            cfg.issue_path = cli_args["issue"]
        if cli_args.get("provider"):
            cfg.model.provider = cli_args["provider"]
        if cli_args.get("model"):
            cfg.model.name = cli_args["model"]
        if cli_args.get("base_url"):
            cfg.model.base_url = cli_args["base_url"]
        if cli_args.get("api_key_env"):
            cfg.model.api_key_env = cli_args["api_key_env"]
        if cli_args.get("max_steps") is not None:
            cfg.agent.max_steps = int(cli_args["max_steps"])
        if cli_args.get("temperature") is not None:
            temp = float(cli_args["temperature"])
            cfg.model.temperature_plan = temp
            cfg.model.temperature_act = temp
        if cli_args.get("token_budget") is not None:
            cfg.context.max_context_tokens = int(cli_args["token_budget"])
        if cli_args.get("agent_mode"):
            cfg.agent.agent_mode = cli_args["agent_mode"]
        if cli_args.get("verbose"):
            cfg.telemetry.stream_to_stdout = True
        if cli_args.get("quiet"):
            cfg.telemetry.stream_to_stdout = False
        if cli_args.get("dry_run"):
            cfg.dry_run = True
        if cli_args.get("no_external_skills"):
            cfg.external_skills.enabled = False
        if cli_args.get("output_dir"):
            cfg.telemetry.output_dir = cli_args["output_dir"]

    # Load target repo's .env if present and distinct
    if cfg.repo_path:
        repo_env = Path(cfg.repo_path) / ".env"
        if repo_env.exists():
            load_dotenv(repo_env)

    # Load API Keys from environment if present based on provider
    provider = (cfg.model.provider or "gemini").lower()
    if provider == "gemini":
        from harness.adapters.key_pool import KeyPoolManager
        env_keys = KeyPoolManager._load_keys_from_env()
        if env_keys:
            cfg.model.api_keys = env_keys
            cfg.model.api_key = env_keys[0]
        else:
            cfg.model.api_key = os.environ.get("AI_API_KEY")
    else:
        key_env = cfg.model.api_key_env
        if key_env and os.environ.get(key_env):
            cfg.model.api_key = os.environ.get(key_env)
        elif provider == "deepseek":
            cfg.model.api_key = (
                os.environ.get("DEEPSEEK_API_KEY")
                or os.environ.get("AI_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
            )
        elif provider == "qwen":
            cfg.model.api_key = (
                os.environ.get("DASHSCOPE_API_KEY")
                or os.environ.get("QWEN_API_KEY")
                or os.environ.get("AI_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
            )
        else:
            cfg.model.api_key = os.environ.get("AI_API_KEY") or os.environ.get("OPENAI_API_KEY")

    return cfg
