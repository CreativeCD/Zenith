"""Unit tests for harness/config.py."""

from harness.config import load_config


def test_load_config_defaults():
    cfg = load_config(config_path="non_existent.yaml")
    assert cfg.model.name == "gemini-2.5-flash"
    assert cfg.agent.max_steps == 25
    assert cfg.context.max_context_tokens == 32000
    assert cfg.verification.run_syntax_check is True


def test_load_config_cli_overrides():
    overrides = {
        "repo": "/tmp/custom_repo",
        "issue": "/tmp/issue.txt",
        "model": "gemini-2.5-pro",
        "max_steps": 15,
        "temperature": 0.2,
        "token_budget": 50000,
        "agent_mode": "multi",
        "dry_run": True,
    }
    cfg = load_config(cli_args=overrides)
    assert cfg.repo_path == "/tmp/custom_repo"
    assert cfg.issue_path == "/tmp/issue.txt"
    assert cfg.model.name == "gemini-2.5-pro"
    assert cfg.agent.max_steps == 15
    assert cfg.model.temperature_plan == 0.2
    assert cfg.context.max_context_tokens == 50000
    assert cfg.agent.agent_mode == "multi"
    assert cfg.dry_run is True
