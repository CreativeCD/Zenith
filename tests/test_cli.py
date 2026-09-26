"""Unit tests for harness/cli.py."""

from harness.cli import build_parser, main


def test_cli_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.repo == "."
    assert args.issue == "issue.txt"
    assert args.max_steps == 25
    assert args.model is None  # Defaults to None; YAML config provides actual model
    assert args.agent_mode == "auto"
    assert args.dry_run is False


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
