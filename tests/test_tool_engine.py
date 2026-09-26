"""tests/test_tool_engine.py — Unit & Integration Tests for Unified ToolEngine.

Reference: PRD.md §4.3 | architecture.md §9 | phases.md Task 1.18
Tests:
- Tool registration and Pydantic function-calling schemas
- Execution pipeline across all tools
- Deduplicator enforcement and cache invalidation on edits
- Mandatory reasoning envelope validation
- Unknown tool handling
- Telemetry hook emission
"""

import sys
from harness.contracts import ErrorCode, ResultStatus, ToolCall
from harness.tool_engine import ToolEngine


def test_tool_engine_schemas(tmp_path):
    """Verify tool definitions produce valid function calling schemas with required reasoning."""
    engine = ToolEngine(repo_root=str(tmp_path))
    defs = engine.get_tool_definitions()

    assert len(defs) >= 14
    tool_names = {d["name"] for d in defs}
    expected_tools = {
        "list_dir",
        "search_code",
        "get_symbol",
        "find_references",
        "get_imports",
        "list_symbols",
        "read_file_range",
        "write_file",
        "apply_patch",
        "run_bash_sandboxed",
        "run_test_suite",
        "git_status",
        "git_diff",
        "git_rollback",
    }
    assert expected_tools.issubset(tool_names)

    for d in defs:
        assert "description" in d
        assert "parameters" in d
        params = d["parameters"]
        assert params.get("type") == "object"
        assert "reasoning" in params.get("properties", {})
        assert "reasoning" in params.get("required", [])


def test_tool_engine_missing_reasoning(tmp_path):
    """Verify tool calls missing a reasoning argument are blocked."""
    engine = ToolEngine(repo_root=str(tmp_path))
    call = ToolCall(
        tool="list_dir",
        reasoning="",  # Empty reasoning
        args={"path": "."},
    )
    res = engine.execute(call)
    assert res.status in (ResultStatus.FAIL, ResultStatus.BLOCKED)
    assert "reasoning" in res.raw_output.lower()


def test_tool_engine_unknown_tool(tmp_path):
    """Verify unrecognized tool returns failure."""
    engine = ToolEngine(repo_root=str(tmp_path))
    call = ToolCall(
        tool="non_existent_tool_xyz",
        reasoning="Testing unknown tool",
        args={},
    )
    res = engine.execute(call)
    assert res.status == ResultStatus.FAIL
    assert "unknown tool" in res.raw_output.lower()


def test_tool_engine_deduplication_and_reset_on_edit(tmp_path):
    """Verify ToolCallDeduplicator blocks repeated calls, and unblocks after an edit."""
    engine = ToolEngine(repo_root=str(tmp_path))
    f = tmp_path / "app.py"
    f.write_text("x = 1\n")

    # 1. First read
    call1 = ToolCall(
        tool="read_file_range",
        reasoning="First read of app.py",
        args={"file_path": "app.py", "start_line": 1, "end_line": 1},
    )
    res1 = engine.execute(call1)
    assert res1.status == ResultStatus.SUCCESS
    assert "1: x = 1" in res1.raw_output

    # 2. Duplicate read immediately after
    call2 = ToolCall(
        tool="read_file_range",
        reasoning="Second read of app.py",
        args={"file_path": "app.py", "start_line": 1, "end_line": 1},
    )
    res2 = engine.execute(call2)
    assert res2.status == ResultStatus.FAIL
    assert res2.error_code == ErrorCode.LOOP_DETECTED
    assert "already called" in res2.raw_output.lower()

    # 3. Intervening edit via apply_patch
    patch_call = ToolCall(
        tool="apply_patch",
        reasoning="Update x to 2",
        args={
            "target_file": "app.py",
            "old_snippet": "x = 1",
            "new_snippet": "x = 2",
        },
    )
    patch_res = engine.execute(patch_call)
    assert patch_res.status == ResultStatus.SUCCESS

    # 4. Now reading the same range is permitted because file was modified
    call3 = ToolCall(
        tool="read_file_range",
        reasoning="Third read of app.py after edit",
        args={"file_path": "app.py", "start_line": 1, "end_line": 1},
    )
    res3 = engine.execute(call3)
    assert res3.status == ResultStatus.SUCCESS
    assert "1: x = 2" in res3.raw_output


def test_tool_engine_execution_flow(tmp_path):
    """Verify tool engine correctly routes execution tools."""
    engine = ToolEngine(repo_root=str(tmp_path))

    import shlex
    py_exec = shlex.quote(sys.executable)
    call = ToolCall(
        tool="run_bash_sandboxed",
        reasoning="Run simple echo in sandbox",
        args={"command": f"{py_exec} -c 'print(\"hello from engine\")'"},
    )
    res = engine.execute(call)
    assert res.status == ResultStatus.SUCCESS
    assert "hello from engine" in res.raw_output


def test_tool_engine_telemetry_integration(tmp_path):
    """Verify ToolEngine records TelemetryEvent into TelemetryWriter successfully."""
    from harness.telemetry import TelemetryWriter

    telemetry = TelemetryWriter(output_dir=str(tmp_path / ".harness"))
    engine = ToolEngine(repo_root=str(tmp_path), telemetry=telemetry)

    call = ToolCall(
        tool="list_dir",
        reasoning="List root directory",
        args={"path": "."},
    )
    res = engine.execute(call)
    assert res.status == ResultStatus.SUCCESS
    assert telemetry.events_count >= 1
    log_file = tmp_path / ".harness" / "telemetry.jsonl"
    assert log_file.exists()
    assert "TOOL_RESULT" in log_file.read_text()


def test_tool_engine_null_and_malformed_args(tmp_path):
    """Verify ToolEngine safely handles null or string-typed integers without raising TypeError."""
    engine = ToolEngine(repo_root=str(tmp_path))
    (tmp_path / "test.py").write_text("print(1)\n")

    call = ToolCall(
        tool="read_file_range",
        reasoning="Read with null bounds and string numbers",
        args={
            "file_path": "test.py",
            "start_line": "1",
            "end_line": None,
        },
    )
    res = engine.execute(call)
    assert res.status == ResultStatus.SUCCESS
    assert "print(1)" in res.raw_output


def test_tool_engine_schema_descriptions_not_empty(tmp_path):
    """Verify every registered tool schema produces a rich descriptive prompt."""
    engine = ToolEngine(repo_root=str(tmp_path))
    defs = engine.get_tool_definitions()

    for d in defs:
        desc = d["description"]
        assert desc is not None
        # Must be longer than generic fallback like 'Execute list_dir'
        assert len(desc) > 20, f"Description for {d['name']} was too short: '{desc}'"


def test_tool_engine_dynamic_step_and_fingerprint(tmp_path):
    """Verify ToolEngine populates fingerprint on tool_call and propagates step to telemetry and dedup."""
    from harness.telemetry import TelemetryWriter

    telemetry = TelemetryWriter(output_dir=str(tmp_path / ".harness"))
    engine = ToolEngine(repo_root=str(tmp_path), telemetry=telemetry)

    call = ToolCall(
        tool="list_dir",
        reasoning="Step 7 directory list",
        args={"path": "."},
    )
    assert call.fingerprint == ""

    res = engine.execute(call, step=7)
    assert res.status == ResultStatus.SUCCESS
    assert call.fingerprint != ""
    assert res.args_hash == call.fingerprint

    # Telemetry should record step 7
    log_file = tmp_path / ".harness" / "telemetry.jsonl"
    lines = log_file.read_text().splitlines()
    assert any('"step": 7' in line for line in lines)

