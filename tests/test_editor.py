"""Unit tests for harness/tools/editor.py (read_file_range, write_file)."""

from harness.contracts import ResultStatus
from harness.tools.editor import read_file_range, write_file


def test_read_file_range_basic(tmp_path):
    f = tmp_path / "sample.py"
    lines = [f"line_{i}" for i in range(1, 51)]
    f.write_text("\n".join(lines) + "\n")

    res = read_file_range("sample.py", 10, 15, repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "10: line_10" in res.raw_output
    assert "15: line_15" in res.raw_output
    assert "16: line_16" not in res.raw_output


def test_read_file_range_250_line_cap(tmp_path):
    f = tmp_path / "long.py"
    lines = [f"val_{i} = {i}" for i in range(1, 401)]
    f.write_text("\n".join(lines) + "\n")

    # Request 350 lines (1 to 350)
    res = read_file_range("long.py", 1, 350, repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "250: val_250 = 250" in res.raw_output
    assert "251: val_251" not in res.raw_output
    assert "capped at 250 lines" in res.raw_output


def test_read_file_range_invalid_bounds(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("a = 1\nb = 2\n")

    # start_line > end_line
    res = read_file_range("sample.py", 10, 5, repo_root=str(tmp_path))
    assert res.status == ResultStatus.FAIL
    assert "start_line" in res.raw_output

    # start_line < 1
    res2 = read_file_range("sample.py", 0, 5, repo_root=str(tmp_path))
    assert res2.status == ResultStatus.FAIL


def test_read_file_range_nonexistent(tmp_path):
    res = read_file_range("missing.py", 1, 10, repo_root=str(tmp_path))
    assert res.status == ResultStatus.FAIL
    assert "does not exist" in res.raw_output


def test_write_file_new_success(tmp_path):
    res = write_file("new_module.py", "x = 42\n", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert (tmp_path / "new_module.py").read_text() == "x = 42\n"


def test_write_file_creates_parent_directories(tmp_path):
    res = write_file("deep/nested/pkg/mod.py", "def fn(): pass\n", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert (tmp_path / "deep" / "nested" / "pkg" / "mod.py").is_file()


def test_write_file_refuses_overwrite(tmp_path):
    f = tmp_path / "existing.py"
    f.write_text("original = True\n")

    # Should refuse to overwrite existing file
    res = write_file("existing.py", "original = False\n", repo_root=str(tmp_path))
    assert res.status == ResultStatus.FAIL
    assert "already exists" in res.raw_output
    assert f.read_text() == "original = True\n"


def test_write_file_syntax_check_rollback(tmp_path):
    # Invalid Python syntax should fail AST check and remove created file
    broken_code = "def bad_syntax(:\n    pass\n"
    res = write_file("broken.py", broken_code, repo_root=str(tmp_path))
    assert res.status == ResultStatus.FAIL
    assert "Syntax error" in res.raw_output
    assert not (tmp_path / "broken.py").exists()


def test_read_file_range_rejects_binary_file(tmp_path):
    """Verify read_file_range rejects binary files containing null bytes."""
    bin_file = tmp_path / "blob.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03\xff")

    res = read_file_range("blob.bin", start_line=1, end_line=10, repo_root=str(tmp_path))
    assert res.status == ResultStatus.FAIL
    assert "cannot read binary file" in res.raw_output.lower()

