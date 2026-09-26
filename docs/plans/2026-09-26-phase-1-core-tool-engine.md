# Phase 1: Core Tool Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all 15 specialized tools, security guards, deduplication ring buffer, sandboxed execution, and LLM function-calling registry required for Layer 3 (Hardened Tool Engine).

**Architecture:** A modular, layered Tool Engine where every tool inherits from a common interface, enforces atomic path and security guards, computes SHA256 call fingerprints for a 10-call deduplicator, and logs typed `ToolResult` contracts to telemetry. Editing tools provide dual-mode unified diff and exact-block patching with immediate AST syntax verification and rollback.

**Tech Stack:** Python 3.10+, `pathlib`, `ast` / `tree-sitter`, `subprocess`, `hashlib`, `re`, `pytest`.

**Spec:** `PRD.md` (§4.3, §13.2, §14) | `architecture.md` (§9, §18) | `phases.md` (§Phase 1)

## Global Constraints

- **CRITICAL USER CONSTRAINT:** DO NOT execute `git commit` or `git push`. The user will review, commit, and push changes themselves.
- **SECURITY BOUNDARY:** Never allow file access outside `repo_path`. Reject path traversal (`../`, `/..`).
- **COMMAND BLOCKLIST:** Enforce all 12 forbidden regex patterns before executing commands in sandbox.
- **OUTPUT CAPS:** Enforce hard truncation caps: `read_file_range` ≤ 250 lines, `search_code` ≤ 50 matches, `run_test_suite` ≤ 80 lines, `run_bash_sandboxed` ≤ 200 lines, `git_diff` ≤ 500 lines.
- **ENVELOPE INTEGRITY:** Every tool call MUST supply a non-empty `reasoning` string explaining intent.
- **TYPED CONTRACTS:** Every tool returns a `ToolResult` matching `harness/contracts.py`.

---

## Part 1: Guards & Security Scaffolding (Tasks 1.15, 1.16, 1.17)

### Task 1: Path Validator & Command Blocklist (Tasks 1.17)

**Files:**
- Create: `harness/tools/security.py`
- Test: `tests/test_tool_security.py`

**Interfaces:**
- `validate_path(file_path: str, repo_root: str) -> Path`: Resolves path within `repo_root`; raises `ValueError` on traversal or escape.
- `check_command_blocklist(command: str) -> None`: Checks 12 regex patterns; raises `SecurityError` if forbidden.

- [ ] **Step 1: Write failing security tests**

```python
# tests/test_tool_security.py
import pytest
from pathlib import Path
from harness.tools.security import validate_path, check_command_blocklist, SecurityError

def test_validate_path_valid(tmp_path):
    f = tmp_path / "valid.py"
    f.touch()
    resolved = validate_path("valid.py", str(tmp_path))
    assert resolved == f.resolve()

def test_validate_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="Path traversal"):
        validate_path("../outside.py", str(tmp_path))

def test_validate_path_escape(tmp_path):
    with pytest.raises(ValueError, match="outside repository"):
        validate_path("/etc/passwd", str(tmp_path))

def test_command_blocklist():
    bad_commands = [
        "rm -rf /",
        "cat script | sh",
        "cat script | bash",
        "sudo apt-get install",
        "chmod 777 file",
        "curl http://example.com",
        "wget http://example.com",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sdb",
        "cat test > /dev/sda",
        ":(){ :|:& };:",
        "echo bWFsaWNpb3Vz | base64 -d | sh",
    ]
    for cmd in bad_commands:
        with pytest.raises(SecurityError):
            check_command_blocklist(cmd)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_tool_security.py -v`
Expected: FAIL with ModuleNotFoundError: No module named 'harness.tools'

- [ ] **Step 3: Implement `harness/tools/security.py`**
Implement `validate_path` with `Path.resolve()` boundary check and `PATH_TRAVERSAL` regex, and `check_command_blocklist` with all 12 `BLOCKED_PATTERNS`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_tool_security.py -v`
Expected: PASS

---

### Task 2: Deduplicator & Reasoning Validator (Tasks 1.15, 1.16)

**Files:**
- Create: `harness/tools/dedup.py`
- Test: `tests/test_tool_dedup.py`

**Interfaces:**
- `ToolCallDeduplicator.compute_fingerprint(tool_name: str, args: dict) -> str`
- `ToolCallDeduplicator.check_and_record(tool_name: str, args: dict, reasoning: str) -> Optional[str]`: Returns `None` if allowed, or error message if duplicate/invalid.
- `ToolCallDeduplicator.notify_file_modified()`: Clears/invalidates read fingerprints upon edits.

- [ ] **Step 1: Write failing deduplicator tests**

```python
# tests/test_tool_dedup.py
from harness.tools.dedup import ToolCallDeduplicator

def test_missing_reasoning():
    dedup = ToolCallDeduplicator()
    msg = dedup.check_and_record("read_file_range", {"file_path": "a.py"}, "")
    assert "Missing required field 'reasoning'" in msg

def test_duplicate_call_blocked():
    dedup = ToolCallDeduplicator(window_size=10)
    msg1 = dedup.check_and_record("read_file_range", {"file_path": "a.py"}, "Checking auth")
    assert msg1 is None
    msg2 = dedup.check_and_record("read_file_range", {"file_path": "a.py"}, "Checking auth again")
    assert msg2 is not None
    assert "DEDUP" in msg2

def test_reset_on_edit():
    dedup = ToolCallDeduplicator(window_size=10)
    dedup.check_and_record("read_file_range", {"file_path": "a.py"}, "Initial read")
    dedup.notify_file_modified()
    msg = dedup.check_and_record("read_file_range", {"file_path": "a.py"}, "Read after edit")
    assert msg is None
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_tool_dedup.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `harness/tools/dedup.py`**
Implement `ToolCallDeduplicator` with collections.deque(maxlen=10) ring buffer and SHA-256 canonical arg hashing.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_tool_dedup.py -v`
Expected: PASS

---

## Part 2: Navigation Tools (Tasks 1.1–1.6)

### Task 3: Directory Listing & Code Search (`list_dir`, `search_code`) (Tasks 1.1, 1.2)

**Files:**
- Create: `harness/tools/navigation.py`
- Test: `tests/test_navigation.py`

**Interfaces:**
- `list_dir(path: str, repo_root: str, depth: int = 3, recursive: bool = False) -> ToolResult`
- `search_code(query: str, repo_root: str, path_pattern: Optional[str] = None, regex: bool = False, context_lines: int = 2, include_tests: bool = False) -> ToolResult`

- [ ] **Step 1: Write failing tests for `list_dir` and `search_code`**

```python
# tests/test_navigation.py
from harness.tools.navigation import list_dir, search_code
from harness.contracts import ResultStatus

def test_list_dir_excludes_junk(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')")
    
    res = list_dir(".", repo_root=str(tmp_path), depth=3)
    assert res.status == ResultStatus.SUCCESS
    assert "src/app.py" in res.raw_output
    assert ".git" not in res.raw_output
    assert "__pycache__" not in res.raw_output

def test_search_code_ripgrep_fallback(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("def find_me_here():\n    return 42\n")
    res = search_code("find_me_here", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "sample.py" in res.raw_output
    assert "find_me_here" in res.raw_output
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_navigation.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `list_dir` and `search_code` in `harness/tools/navigation.py`**
Implement directory walker with exclusion filter and ripgrep/Python fallback search capped at 50 matches.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_navigation.py -v`
Expected: PASS

---

### Task 4: Symbol Navigation Tools via AST (`get_symbol`, `find_references`, `get_imports`, `list_symbols`) (Tasks 1.3–1.6)

**Files:**
- Create: `harness/tools/ast_tools.py`
- Test: `tests/test_ast_tools.py`

**Interfaces:**
- `get_symbol(file_path: str, symbol_name: str, repo_root: str) -> ToolResult`
- `find_references(file_path: str, symbol_name: str, repo_root: str, context_lines: int = 3) -> ToolResult`
- `get_imports(file_path: str, repo_root: str) -> ToolResult`
- `list_symbols(file_path: str, repo_root: str) -> ToolResult`

- [ ] **Step 1: Write failing AST navigation tests**

```python
# tests/test_ast_tools.py
from harness.tools.ast_tools import get_symbol, find_references, get_imports, list_symbols
from harness.contracts import ResultStatus

SAMPLE_CODE = '''import os
from sys import path

class DataHandler:
    """Handles raw data."""
    def process(self, x: int) -> int:
        return x * 2

def execute():
    handler = DataHandler()
    return handler.process(10)
'''

def test_ast_symbol_tools(tmp_path):
    f = tmp_path / "module.py"
    f.write_text(SAMPLE_CODE)
    
    # 1. list_symbols
    syms = list_symbols("module.py", repo_root=str(tmp_path))
    assert syms.status == ResultStatus.SUCCESS
    assert "DataHandler" in syms.raw_output
    assert "execute" in syms.raw_output

    # 2. get_symbol
    sym = get_symbol("module.py", "DataHandler", repo_root=str(tmp_path))
    assert sym.status == ResultStatus.SUCCESS
    assert "Handles raw data" in sym.raw_output
    assert "class DataHandler" in sym.raw_output

    # 3. get_imports
    imports = get_imports("module.py", repo_root=str(tmp_path))
    assert imports.status == ResultStatus.SUCCESS
    assert "import os" in imports.raw_output
    assert "from sys import path" in imports.raw_output

    # 4. find_references
    refs = find_references("module.py", "process", repo_root=str(tmp_path))
    assert refs.status == ResultStatus.SUCCESS
    assert "handler.process(10)" in refs.raw_output
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_ast_tools.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `harness/tools/ast_tools.py`**
Use Python standard `ast` with Tree-sitter enhancement for extracting functions, classes, signatures, imports, and call references.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_ast_tools.py -v`
Expected: PASS

---

## Part 3: Edit Tools (Tasks 1.7–1.9)

### Task 5: File Reading & Writing (`read_file_range`, `write_file`) (Tasks 1.7, 1.9)

**Files:**
- Create: `harness/tools/editor.py`
- Test: `tests/test_editor.py`

**Interfaces:**
- `read_file_range(file_path: str, start_line: int, end_line: int, repo_root: str) -> ToolResult`
- `write_file(file_path: str, content: str, repo_root: str) -> ToolResult`

- [ ] **Step 1: Write failing tests for read and write**

```python
# tests/test_editor.py
from harness.tools.editor import read_file_range, write_file
from harness.contracts import ResultStatus

def test_read_file_range(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("\n".join([f"line_{i}" for i in range(1, 300)]))
    
    res = read_file_range("code.py", 10, 20, repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "10: line_10" in res.raw_output
    assert "20: line_20" in res.raw_output
    assert "21: line_21" not in res.raw_output

def test_read_file_range_limit_250(tmp_path):
    f = tmp_path / "big.py"
    f.write_text("\n".join([f"line_{i}" for i in range(1, 400)]))
    
    res = read_file_range("big.py", 1, 350, repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    # Capped at 250 lines
    assert "250: line_250" in res.raw_output
    assert "251: line_251" not in res.raw_output

def test_write_file_no_overwrite(tmp_path):
    f = tmp_path / "existing.py"
    f.write_text("initial")
    
    # Refuses overwrite
    res = write_file("existing.py", "new", repo_root=str(tmp_path))
    assert res.status == ResultStatus.FAIL
    assert "already exists" in res.raw_output

def test_write_file_new_creates_dirs(tmp_path):
    res = write_file("sub/dir/new.py", "content", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert (tmp_path / "sub" / "dir" / "new.py").read_text() == "content"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_editor.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `read_file_range` and `write_file` in `harness/tools/editor.py`**
Enforce 250-line cap, 1-indexed formatted output, parent directory creation, and non-overwrite guarantee.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_editor.py -v`
Expected: PASS

---

### Task 6: Dual-Mode Atomic Patch Engine (`apply_patch`) (Task 1.8)

**Files:**
- Modify: `harness/tools/editor.py`
- Test: `tests/test_patch_engine.py`

**Interfaces:**
- `apply_patch(target_file: str, repo_root: str, patch_string: Optional[str] = None, old_snippet: Optional[str] = None, new_snippet: Optional[str] = None) -> ToolResult`
- Automatically validates syntax (via `ast.parse` for python) after applying; automatically rolls back if syntax fails.

- [ ] **Step 1: Write failing patch engine tests**

```python
# tests/test_patch_engine.py
from harness.tools.editor import apply_patch
from harness.contracts import ResultStatus, ErrorCode

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
    assert "return a + b" in f.read_text()

def test_apply_patch_syntax_error_rollback(tmp_path):
    f = tmp_path / "math_mod.py"
    original = "def compute():\n    return 42\n"
    f.write_text(original)
    
    # Introduce broken syntax: def compute() missing colon
    res = apply_patch(
        "math_mod.py",
        repo_root=str(tmp_path),
        old_snippet="def compute():",
        new_snippet="def compute(",
    )
    assert res.status == ResultStatus.FAIL
    assert res.error_code == ErrorCode.AST_PARSE_FAIL
    # Verify file was rolled back
    assert f.read_text() == original
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_patch_engine.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `apply_patch` in `harness/tools/editor.py`**
Implement unified diff parser (hunk-based) and exact string match fallback, followed by post-edit AST check and rollback on parse failure.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_patch_engine.py -v`
Expected: PASS

---

## Part 4: Execution Tools (Tasks 1.10, 1.11)

### Task 7: Sandboxed Subprocess & Test Runner (`run_test_suite`, `run_bash_sandboxed`) (Tasks 1.10, 1.11)

**Files:**
- Create: `harness/tools/executor.py`
- Test: `tests/test_executor.py`

**Interfaces:**
- `run_bash_sandboxed(command: str, repo_root: str, timeout_sec: int = 30) -> ToolResult`
- `run_test_suite(repo_root: str, test_path: Optional[str] = None, test_filter: Optional[str] = None, flags: Optional[str] = None, timeout_sec: int = 120) -> ToolResult`

- [ ] **Step 1: Write failing execution tool tests**

```python
# tests/test_executor.py
from harness.tools.executor import run_bash_sandboxed, run_test_suite
from harness.contracts import ResultStatus, ErrorCode

def test_run_bash_sandboxed_success(tmp_path):
    res = run_bash_sandboxed("echo 'sandbox test'", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "sandbox test" in res.raw_output

def test_run_bash_sandboxed_blocked_command(tmp_path):
    res = run_bash_sandboxed("rm -rf /", repo_root=str(tmp_path))
    assert res.status == ResultStatus.BLOCKED
    assert res.error_code == ErrorCode.TOOL_BLOCKED

def test_run_test_suite_toy_repo(tmp_path):
    # Setup test file
    test_f = tmp_path / "test_ok.py"
    test_f.write_text("def test_pass(): assert True\n")
    res = run_test_suite(repo_root=str(tmp_path), test_path="test_ok.py")
    assert res.status == ResultStatus.SUCCESS
    assert res.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_executor.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `harness/tools/executor.py`**
Implement sandboxed subprocess (`shell=False` or shlex split, timeout enforcement, output head/tail truncation at 80/200 lines, memory limits).

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_executor.py -v`
Expected: PASS

---

## Part 5: VCS Tools (Tasks 1.12–1.14)

### Task 8: Git VCS Operations (`git_rollback`, `git_diff`, `git_status`) (Tasks 1.12–1.14)

**Files:**
- Create: `harness/tools/vcs.py`
- Test: `tests/test_vcs.py`

**Interfaces:**
- `git_diff(repo_root: str, file_path: Optional[str] = None) -> ToolResult`
- `git_status(repo_root: str) -> ToolResult`
- `git_rollback(repo_root: str, file_path: Optional[str] = None) -> ToolResult`

- [ ] **Step 1: Write failing VCS tests**

```python
# tests/test_vcs.py
import subprocess
from harness.tools.vcs import git_diff, git_status, git_rollback
from harness.contracts import ResultStatus

def test_vcs_operations(tmp_path):
    # Initialize git repo in tmp_path
    subprocess.run(["git", "init"], cwd=tmp_path, check=True)
    f = tmp_path / "tracked.py"
    f.write_text("v1\n")
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True)
    
    # Modify
    f.write_text("v2\n")
    
    # 1. git_status
    stat = git_status(repo_root=str(tmp_path))
    assert stat.status == ResultStatus.SUCCESS
    assert "tracked.py" in stat.raw_output

    # 2. git_diff
    diff = git_diff(repo_root=str(tmp_path))
    assert diff.status == ResultStatus.SUCCESS
    assert "+v2" in diff.raw_output

    # 3. git_rollback
    rb = git_rollback(repo_root=str(tmp_path), file_path="tracked.py")
    assert rb.status == ResultStatus.SUCCESS
    assert f.read_text() == "v1\n"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_vcs.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `harness/tools/vcs.py`**
Implement safe git operations using subprocess with `repo_root` CWD and 500-line cap on diffs.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_vcs.py -v`
Expected: PASS

---

## Part 6: Unified Tool Engine & Function Schemas (Tasks 1.18)

### Task 9: Unified Tool Engine Registry & Function Schemas (Task 1.18)

**Files:**
- Create: `harness/tool_engine.py`
- Test: `tests/test_tool_engine.py` (replace stub)

**Interfaces:**
- `ToolEngine(repo_root: str, deduplicator_window: int = 10, deduplicator: Optional[ToolCallDeduplicator] = None)`
- `ToolEngine.execute(tool_call: ToolCall) -> ToolResult`
- `ToolEngine.get_tool_definitions() -> List[Dict[str, Any]]`: Returns Gemini/OpenAI-compatible function calling declarations for all 14 tools.

- [ ] **Step 1: Write comprehensive tool engine tests in `tests/test_tool_engine.py`**
Test dispatch for all tools, deduplication integration, envelope validation, and schema generation.

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_tool_engine.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `harness/tool_engine.py`**
Unify all navigation, edit, execution, and VCS tools into a centralized dispatcher with telemetry hooks and JSON schemas.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_tool_engine.py -v`
Expected: PASS

---

## Part 7: Single-Turn E2E Validation (Task 1.19)

### Task 10: Single-Turn E2E Integration Test (Task 1.19)

**Files:**
- Create: `tests/test_p1_e2e.py`

**Interfaces:**
- Test end-to-end: Read broken file → apply patch → run test runner → exit code 0.

- [ ] **Step 1: Write single-turn E2E integration test**

```python
# tests/test_p1_e2e.py
from harness.tool_engine import ToolEngine
from harness.contracts import ToolCall, ResultStatus

def test_single_turn_e2e_bugfix(tmp_path):
    # Setup toy math repo
    calc_file = tmp_path / "calculator.py"
    calc_file.write_text("""def divide(a: float, b: float) -> float:
    return a / b
""")
    test_file = tmp_path / "test_calc.py"
    test_file.write_text("""from calculator import divide
def test_div_zero():
    assert divide(10, 0) == 0
""")

    engine = ToolEngine(repo_root=str(tmp_path))

    # 1. Read file
    read_call = ToolCall(tool="read_file_range", reasoning="Read divide func", args={"file_path": "calculator.py", "start_line": 1, "end_line": 10})
    res_read = engine.execute(read_call)
    assert res_read.status == ResultStatus.SUCCESS

    # 2. Apply patch
    patch_call = ToolCall(
        tool="apply_patch",
        reasoning="Fix division by zero to return 0",
        args={
            "target_file": "calculator.py",
            "old_snippet": "    return a / b",
            "new_snippet": "    if b == 0:\n        return 0\n    return a / b",
        }
    )
    res_patch = engine.execute(patch_call)
    assert res_patch.status == ResultStatus.SUCCESS

    # 3. Run test suite
    test_call = ToolCall(tool="run_test_suite", reasoning="Verify fix", args={"test_path": "test_calc.py"})
    res_test = engine.execute(test_call)
    assert res_test.status == ResultStatus.SUCCESS
    assert res_test.exit_code == 0
```

- [ ] **Step 2: Run test to verify it passes**
Run: `pytest tests/test_p1_e2e.py -v`
Expected: PASS

---

## Final Verification Checklist for Phase 1

- [ ] Run full test suite: `pytest -v tests/` (all Phase 0 and Phase 1 tests pass, future stubs skipped)
- [ ] Run linter: `ruff check harness/ tests/` (100% clean)
- [ ] Update `logs.md` with Phase 1 log entries and check off all P1 exit criteria
- [ ] **CRITICAL:** Do NOT run `git commit` or `git push` (user will commit themselves)
