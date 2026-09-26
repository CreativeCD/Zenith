"""tests/test_vcs.py — Unit tests for VCS Tools (git_status, git_diff, git_rollback).

Reference: PRD.md §4.3.2 | phases.md Tasks 1.12–1.14
Tests git_status, git_diff (500-line cap, single file filter), and git_rollback (file & all modes).
"""

import subprocess
from harness.contracts import ResultStatus
from harness.tools.vcs import git_diff, git_rollback, git_status


def _init_git_repo(path):
    """Helper to initialize a dummy git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "zenith@devclub.ai"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Zenith Agent"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    f = path / "main.py"
    f.write_text("def hello():\n    return 'v1'\n")
    subprocess.run(["git", "add", "main.py"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return f


def test_git_status_clean(tmp_path):
    """Verify git_status reports clean tree when no changes exist."""
    _init_git_repo(tmp_path)
    res = git_status(repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "clean" in res.raw_output.lower() or res.raw_output.strip() == ""


def test_git_status_modified_and_untracked(tmp_path):
    """Verify git_status accurately detects modified and untracked files."""
    f = _init_git_repo(tmp_path)
    f.write_text("def hello():\n    return 'v2'\n")

    new_f = tmp_path / "extra.py"
    new_f.write_text("x = 100\n")

    res = git_status(repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "main.py" in res.raw_output
    assert "extra.py" in res.raw_output


def test_git_diff_clean(tmp_path):
    """Verify git_diff returns empty/clean result when repo is unmodified."""
    _init_git_repo(tmp_path)
    res = git_diff(repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert res.raw_output.strip() == "" or "no changes" in res.raw_output.lower()


def test_git_diff_modified(tmp_path):
    """Verify git_diff captures diff lines against HEAD."""
    f = _init_git_repo(tmp_path)
    f.write_text("def hello():\n    return 'v2_modified'\n")

    res = git_diff(repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "-    return 'v1'" in res.raw_output
    assert "+    return 'v2_modified'" in res.raw_output


def test_git_diff_specific_file(tmp_path):
    """Verify git_diff filters diff to only the requested file."""
    f1 = _init_git_repo(tmp_path)
    f2 = tmp_path / "other.py"
    f2.write_text("initial other\n")
    subprocess.run(["git", "add", "other.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add other"], cwd=tmp_path, check=True, capture_output=True)

    f1.write_text("f1 modified\n")
    f2.write_text("f2 modified\n")

    res = git_diff(repo_root=str(tmp_path), file_path="main.py")
    assert res.status == ResultStatus.SUCCESS
    assert "main.py" in res.raw_output
    assert "other.py" not in res.raw_output


def test_git_diff_500_line_truncation(tmp_path):
    """Verify diffs exceeding 500 lines are truncated in truncated_output."""
    f = _init_git_repo(tmp_path)
    # Write 700 lines
    f.write_text("\n".join([f"line_{i} = {i}" for i in range(700)]))

    res = git_diff(repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    lines = res.raw_output.strip().splitlines()
    assert len(lines) >= 500

    truncated_lines = res.truncated_output.strip().splitlines()
    assert len(truncated_lines) <= 502
    assert "truncated" in res.truncated_output.lower()


def test_git_rollback_single_file(tmp_path):
    """Verify git_rollback restores single specified file while preserving others."""
    f1 = _init_git_repo(tmp_path)
    f2 = tmp_path / "second.py"
    f2.write_text("second v1\n")
    subprocess.run(["git", "add", "second.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add second"], cwd=tmp_path, check=True, capture_output=True)

    # Modify both
    f1.write_text("f1 broken\n")
    f2.write_text("second modified\n")

    res = git_rollback(repo_root=str(tmp_path), file_path="main.py")
    assert res.status == ResultStatus.SUCCESS
    assert "def hello():" in f1.read_text()
    assert "second modified" in f2.read_text()  # Untouched


def test_git_rollback_all_files(tmp_path):
    """Verify git_rollback with no file_path reverts all modifications and untracked files."""
    f = _init_git_repo(tmp_path)
    f.write_text("modified code\n")

    untracked = tmp_path / "untracked.py"
    untracked.write_text("junk\n")

    res = git_rollback(repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "def hello():" in f.read_text()
    assert not untracked.exists()


def test_git_operations_not_a_repo(tmp_path):
    """Verify git operations return FAIL gracefully when directory is not a git repo."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    res = git_status(repo_root=str(empty_dir))
    assert res.status == ResultStatus.FAIL
    assert "git" in res.raw_output.lower() or "not a git repository" in res.raw_output.lower()


def test_git_rollback_untracked_directory(tmp_path):
    """Verify git_rollback cleanly removes an untracked directory without IsADirectoryError."""
    _init_git_repo(tmp_path)
    new_dir = tmp_path / "new_dir"
    new_dir.mkdir()
    (new_dir / "child.py").write_text("child code\n")

    res = git_rollback(repo_root=str(tmp_path), file_path="new_dir")
    assert res.status == ResultStatus.SUCCESS
    assert not new_dir.exists()


def test_git_rollback_non_git_repo_does_not_delete_file(tmp_path):
    """Verify git_rollback in a non-git directory fails gracefully without deleting files."""
    not_git = tmp_path / "not_git"
    not_git.mkdir()
    important_file = not_git / "important.py"
    important_file.write_text("important data\n")

    res = git_rollback(repo_root=str(not_git), file_path="important.py")
    assert res.status == ResultStatus.FAIL
    assert "not a git repository" in res.raw_output.lower()
    # File must still exist!
    assert important_file.exists()
    assert important_file.read_text() == "important data\n"

