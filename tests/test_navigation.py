"""Unit tests for harness/tools/navigation.py (list_dir, search_code)."""

from harness.contracts import ResultStatus
from harness.tools.navigation import list_dir, search_code


def test_list_dir_excludes_junk(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n")
    (tmp_path / "README.md").write_text("# Test\n")

    res = list_dir(".", repo_root=str(tmp_path), depth=3)
    assert res.status == ResultStatus.SUCCESS
    assert "src/app.py" in res.raw_output
    assert "README.md" in res.raw_output
    assert ".git" not in res.raw_output
    assert "__pycache__" not in res.raw_output
    assert "node_modules" not in res.raw_output
    assert ".venv" not in res.raw_output


def test_list_dir_depth_cap(tmp_path):
    # Create deeply nested directory
    nested = tmp_path / "d1" / "d2" / "d3" / "d4" / "d5" / "d6"
    nested.mkdir(parents=True)
    (nested / "deep.py").write_text("deep")

    # Depth 2 should show d1/d2 but not d1/d2/d3/d4/d5/d6/deep.py
    res = list_dir(".", repo_root=str(tmp_path), depth=2)
    assert res.status == ResultStatus.SUCCESS
    assert "deep.py" not in res.raw_output

    # Hard cap at depth 4 even if requested 10
    res_deep = list_dir(".", repo_root=str(tmp_path), depth=10)
    assert res_deep.status == ResultStatus.SUCCESS
    # depth 4 stops at d4, shouldn't reach d6/deep.py
    assert "deep.py" not in res_deep.raw_output


def test_list_dir_invalid_path(tmp_path):
    res = list_dir("nonexistent_dir", repo_root=str(tmp_path))
    assert res.status == ResultStatus.FAIL
    assert "does not exist" in res.raw_output


def test_search_code_finds_matches(tmp_path):
    f1 = tmp_path / "calc.py"
    f1.write_text("def add(a, b):\n    return a + b\n")
    f2 = tmp_path / "util.py"
    f2.write_text("# utility functions\ndef add_suffix(s):\n    return s + '_end'\n")

    res = search_code("def add", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "calc.py" in res.raw_output
    assert "util.py" in res.raw_output
    assert "def add" in res.raw_output


def test_search_code_path_pattern(tmp_path):
    f1 = tmp_path / "calc.py"
    f1.write_text("target_token = 1\n")
    f2 = tmp_path / "other.txt"
    f2.write_text("target_token = 2\n")

    res = search_code("target_token", repo_root=str(tmp_path), path_pattern="*.py")
    assert res.status == ResultStatus.SUCCESS
    assert "calc.py" in res.raw_output
    assert "other.txt" not in res.raw_output


def test_search_code_50_match_cap(tmp_path):
    f = tmp_path / "many_matches.py"
    lines = [f"item_{i} = 'target_value'" for i in range(100)]
    f.write_text("\n".join(lines))

    res = search_code("target_value", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    # Output should indicate capping at 50
    assert "50 matches" in res.raw_output or len(res.raw_output.strip().split("\n")) <= 150


def test_list_dir_zero_depth(tmp_path):
    (tmp_path / "file.py").write_text("ok")
    # depth=0 or negative depth should safely fallback to depth=1
    res = list_dir(".", repo_root=str(tmp_path), depth=0)
    assert res.status == ResultStatus.SUCCESS
    assert "file.py" in res.raw_output


def test_search_code_hyphen_query(tmp_path):
    f = tmp_path / "flags.py"
    f.write_text("DEBUG_FLAG = '--enable-optimizations'\nVERBOSE = '-v'\n")

    res = search_code("-v", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "VERBOSE = '-v'" in res.raw_output


def test_search_code_binary_filter(tmp_path):
    # Binary file with target text should be skipped
    bin_file = tmp_path / "compiled.pyc"
    bin_file.write_bytes(b"\x00\x01TARGET_KEYWORD\x02")

    text_file = tmp_path / "source.py"
    text_file.write_text("TARGET_KEYWORD = True\n")

    res = search_code("TARGET_KEYWORD", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "source.py" in res.raw_output
    assert "compiled.pyc" not in res.raw_output


def test_search_code_path_pattern_traversal(tmp_path):
    """Verify search_code rejects path traversal inside path_pattern."""
    res = search_code("target", repo_root=str(tmp_path), path_pattern="../../etc/*")
    assert res.status == ResultStatus.FAIL
    assert "Path traversal" in res.raw_output


def test_search_code_invalid_repo_root(tmp_path):
    """Verify search_code rejects nonexistent or escaped repo_root."""
    res = search_code("target", repo_root=str(tmp_path / "nonexistent_dir"))
    assert res.status == ResultStatus.FAIL
    assert "does not exist" in res.raw_output
