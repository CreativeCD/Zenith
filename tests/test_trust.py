"""Unit tests for harness/trust.py."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from harness.trust import WorkspaceTrustManager


@pytest.fixture
def trust_file(tmp_path):
    return tmp_path / "trusted_workspaces.json"


@pytest.fixture
def trust_mgr(trust_file):
    return WorkspaceTrustManager(trust_file=trust_file)


def test_init_untrusted(trust_mgr, tmp_path):
    repo = tmp_path / "repo1"
    repo.mkdir()
    assert trust_mgr.is_trusted(repo) is False


def test_grant_and_is_trusted(trust_mgr, tmp_path):
    repo = tmp_path / "repo1"
    repo.mkdir()
    trust_mgr.grant_trust(repo)
    assert trust_mgr.is_trusted(repo) is True
    assert trust_mgr.is_trusted(str(repo)) is True

    # Check persistence
    mgr2 = WorkspaceTrustManager(trust_file=trust_mgr.trust_file)
    assert mgr2.is_trusted(repo) is True


def test_revoke_trust(trust_mgr, tmp_path):
    repo = tmp_path / "repo1"
    repo.mkdir()
    trust_mgr.grant_trust(repo)
    assert trust_mgr.is_trusted(repo) is True

    trust_mgr.revoke_trust(repo)
    assert trust_mgr.is_trusted(repo) is False


def test_env_var_bypass(trust_mgr, tmp_path, monkeypatch):
    repo = tmp_path / "repo1"
    repo.mkdir()
    assert trust_mgr.is_trusted(repo) is False

    monkeypatch.setenv("ZENITH_TRUST_WORKSPACE", "1")
    assert trust_mgr.is_trusted(repo) is True


def test_request_trust_auto_trust(trust_mgr, tmp_path):
    repo = tmp_path / "repo2"
    repo.mkdir()
    assert trust_mgr.is_trusted(repo) is False

    result = trust_mgr.request_trust(repo, auto_trust=True)
    assert result is True
    assert trust_mgr.is_trusted(repo) is True


def test_request_trust_interactive_accept(trust_mgr, tmp_path, monkeypatch):
    repo = tmp_path / "repo3"
    repo.mkdir()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    result = trust_mgr.request_trust(repo)
    assert result is True
    assert trust_mgr.is_trusted(repo) is True


def test_request_trust_interactive_accept_default_enter(trust_mgr, tmp_path, monkeypatch):
    repo = tmp_path / "repo4"
    repo.mkdir()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    result = trust_mgr.request_trust(repo)
    assert result is True
    assert trust_mgr.is_trusted(repo) is True


def test_request_trust_interactive_reject(trust_mgr, tmp_path, monkeypatch):
    repo = tmp_path / "repo5"
    repo.mkdir()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    result = trust_mgr.request_trust(repo)
    assert result is False
    assert trust_mgr.is_trusted(repo) is False


def test_request_trust_interactive_ctrl_c(trust_mgr, tmp_path, monkeypatch):
    repo = tmp_path / "repo6"
    repo.mkdir()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def raise_interrupt(prompt):
        raise KeyboardInterrupt()

    monkeypatch.setattr("builtins.input", raise_interrupt)

    result = trust_mgr.request_trust(repo)
    assert result is False
    assert trust_mgr.is_trusted(repo) is False


def test_request_trust_non_interactive_fails(trust_mgr, tmp_path, monkeypatch):
    repo = tmp_path / "repo7"
    repo.mkdir()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    result = trust_mgr.request_trust(repo)
    assert result is False
    assert trust_mgr.is_trusted(repo) is False
