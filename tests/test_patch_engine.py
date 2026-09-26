"""Unit tests for harness/tools/editor.py apply_patch."""

from harness.contracts import ErrorCode, ResultStatus
from harness.tools.editor import apply_patch


def test_apply_patch_exact_block(tmp_path):
    f = tmp_path / "service.py"
    f.write_text("def run():\n    return 1\n")

    res = apply_patch(
        "service.py",
        repo_root=str(tmp_path),
        old_snippet="    return 1",
        new_snippet="    return 2",
    )
    assert res.status == ResultStatus.SUCCESS
    assert f.read_text() == "def run():\n    return 2\n"


def test_apply_patch_unified_diff(tmp_path):
    f = tmp_path / "util.py"
    f.write_text("def add(a, b):\n    return a - b\n")

    diff = """--- a/util.py
+++ b/util.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
    res = apply_patch("util.py", repo_root=str(tmp_path), patch_string=diff)
    assert res.status == ResultStatus.SUCCESS
    assert f.read_text() == "def add(a, b):\n    return a + b\n"


def test_apply_patch_syntax_error_rollback(tmp_path):
    f = tmp_path / "math_mod.py"
    original = "def compute():\n    return 42\n"
    f.write_text(original)

    # Intentionally introduce broken syntax: def compute( missing colon
    res = apply_patch(
        "math_mod.py",
        repo_root=str(tmp_path),
        old_snippet="def compute():",
        new_snippet="def compute(",
    )
    assert res.status == ResultStatus.FAIL
    assert res.error_code == ErrorCode.AST_PARSE_FAIL
    # Verify file was rolled back to original
    assert f.read_text() == original


def test_apply_patch_ambiguous_snippet(tmp_path):
    f = tmp_path / "repeat.py"
    # Same line appears twice
    f.write_text("x = 1\nx = 1\n")

    res = apply_patch(
        "repeat.py",
        repo_root=str(tmp_path),
        old_snippet="x = 1",
        new_snippet="x = 2",
    )
    assert res.status == ResultStatus.FAIL
    assert "appears 2 times" in res.raw_output
    # Unchanged
    assert f.read_text() == "x = 1\nx = 1\n"


def test_apply_patch_nonexistent_file(tmp_path):
    res = apply_patch("missing.py", repo_root=str(tmp_path), old_snippet="a", new_snippet="b")
    assert res.status == ResultStatus.FAIL
    assert "does not exist" in res.raw_output


def test_apply_patch_non_python_syntax_permitted(tmp_path):
    # Non-Python files (e.g. JS/Markdown) shouldn't fail with Python SyntaxError
    f = tmp_path / "config.json"
    f.write_text('{\n  "version": 1\n}\n')

    res = apply_patch(
        "config.json",
        repo_root=str(tmp_path),
        old_snippet='  "version": 1',
        new_snippet='  "version": 2',
    )
    assert res.status == ResultStatus.SUCCESS
    assert '"version": 2' in f.read_text()


def test_apply_patch_unified_diff_context_anchoring(tmp_path):
    """Verify unified diff with context replaces the correct occurrence when target line is repeated."""
    f = tmp_path / "multi_func.py"
    f.write_text("""def first():
    return 0

def second():
    return 0
""")

    diff = """--- a/multi_func.py
+++ b/multi_func.py
@@ -4,3 +4,3 @@
 def second():
-    return 0
+    return 42
"""
    res = apply_patch("multi_func.py", repo_root=str(tmp_path), patch_string=diff)
    assert res.status == ResultStatus.SUCCESS
    content = f.read_text()
    # first() was untouched
    assert "def first():\n    return 0" in content
    # second() was patched
    assert "def second():\n    return 42" in content


def test_apply_patch_unified_diff_mismatched_context(tmp_path):
    """Verify unified diff returns descriptive error when context lines do not match."""
    f = tmp_path / "code.py"
    f.write_text("x = 100\n")

    diff = """--- a/code.py
+++ b/code.py
@@ -1,2 +1,2 @@
 y = 999
-x = 100
+x = 200
"""
    res = apply_patch("code.py", repo_root=str(tmp_path), patch_string=diff)
    assert res.status == ResultStatus.FAIL
    assert res.error_code == ErrorCode.PATCH_FAILED
    assert "could not be matched" in res.raw_output or "Context lines" in res.raw_output


def test_apply_patch_exact_block_trailing_whitespace_tolerance(tmp_path):
    """Verify exact block replacement handles trailing whitespace differences gracefully."""
    f = tmp_path / "whitespace.py"
    f.write_text("def calculate():\n    total = 0\n    return total\n")

    # old_snippet has trailing whitespace on the second line
    old_snippet = "def calculate():\n    total = 0   \n    return total"
    new_snippet = "def calculate():\n    total = 100\n    return total"

    res = apply_patch(
        "whitespace.py",
        repo_root=str(tmp_path),
        old_snippet=old_snippet,
        new_snippet=new_snippet,
    )
    assert res.status == ResultStatus.SUCCESS
    assert "total = 100" in f.read_text()


def test_apply_patch_unified_diff_crlf_normalization(tmp_path):
    """Verify unified diff applies successfully to files with CRLF line endings."""
    f = tmp_path / "windows.py"
    f.write_bytes(b"def win_fn():\r\n    return False\r\n")

    diff = """--- a/windows.py
+++ b/windows.py
@@ -1,2 +1,2 @@
 def win_fn():
-    return False
+    return True
"""
    res = apply_patch("windows.py", repo_root=str(tmp_path), patch_string=diff)
    assert res.status == ResultStatus.SUCCESS
    assert "return True" in f.read_text()


