"""Unit tests for harness/cli.py."""

from harness.cli import build_parser, main


def test_cli_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.repo == "."
    assert args.issue == "issue.txt"
    # None means "not overridden on CLI" — YAML config provides actual values
    assert args.max_steps is None
    assert args.model is None
    assert args.temperature is None
    assert args.token_budget is None
    assert args.agent_mode is None
    assert args.output_dir is None
    assert args.dry_run is False


def test_cli_yaml_not_clobbered_by_defaults(tmp_path, monkeypatch):
    """CLI defaults must not override tuned harness_config.yaml values."""
    import yaml

    from harness.config import load_config

    cfg_file = tmp_path / "harness_config.yaml"
    cfg_file.write_text(yaml.safe_dump({
        "agent": {"max_steps": 15},
        "context": {"max_context_tokens": 128000},
        "model": {"temperature_act": 0.4},
    }))
    monkeypatch.chdir(tmp_path)
    config = load_config(config_path=str(cfg_file), cli_args=vars(build_parser().parse_args([])))
    assert config.agent.max_steps == 15
    assert config.context.max_context_tokens == 128000
    assert config.model.temperature_act == 0.4


def test_cli_dry_run_execution(tmp_path):
    issue_file = tmp_path / "issue.txt"
    issue_file.write_text("Test issue description")

    exit_code = main([
        "--repo", str(tmp_path),
        "--issue", str(issue_file),
        "--output-dir", str(tmp_path / ".harness"),
        "--dry-run"
    ])
    assert exit_code == 0


def test_cli_trust_flag(tmp_path):
    issue_file = tmp_path / "issue.txt"
    issue_file.write_text("Test issue description")

    exit_code = main([
        "--repo", str(tmp_path),
        "--issue", str(issue_file),
        "--output-dir", str(tmp_path / ".harness"),
        "--trust",
        "--dry-run"
    ])
    assert exit_code == 0


def test_cli_trust_rejection(tmp_path, monkeypatch):
    issue_file = tmp_path / "issue.txt"
    issue_file.write_text("Test issue description")

    # Mock trust manager to deny
    monkeypatch.setattr("harness.trust.WorkspaceTrustManager.request_trust", lambda self, p, auto_trust=False: False)

    exit_code = main([
        "--repo", str(tmp_path),
        "--issue", str(issue_file),
        "--output-dir", str(tmp_path / ".harness"),
    ])
    assert exit_code == 1
