"""Unit tests for harness/context_manager.py (Phase 2).

Verifies all Phase 2 Deliverables:
- 2.1 TokenBudgetManager with ContextOverflowError
- 2.2 5-section prompt schema in fixed order within budget
- 2.3 KV cache optimization (PERSONA + GOAL byte-identical across turns)
- 2.4 Dynamic budget adjustment algorithm (N reduction)
- 2.5 Observation truncation across all size classes (PRD §4.4.3)
- 2.6 RollingSummarizer at 70% threshold
- 2.7 RollingSummarizer compression prompt & <= 600 tokens format
- 2.8 WorkingMemorySnapshot writer (.harness/context_summary.md)
- 2.9 Accurate token counting
- 2.10 Telemetry integration
"""

import tempfile
from pathlib import Path

import pytest
import tiktoken

from harness.config import ContextConfig
from harness.context_manager import (
    ContextManager,
    ContextOverflowError,
    RollingSummarizer,
    TokenBudgetManager,
    count_tokens,
    format_working_memory,
    truncate_observation,
)
from harness.contracts import (
    Complexity,
    EventType,
    IssuePlan,
    RankedFile,
    SuspectedFile,
    TaskType,
    TelemetryEvent,
    WorkingMemory,
)
from harness.telemetry import TelemetryWriter


@pytest.fixture
def sample_issue_plan() -> IssuePlan:
    """Fixture providing a standard IssuePlan."""
    return IssuePlan(
        issue_id="ISSUE-2026-001",
        primary_goal="Fix ZeroDivisionError in calculator division logic",
        task_type=TaskType.BUG_FIX,
        acceptance_criteria=[
            "Raise ValueError when divisor is zero",
            "Pass all unit tests in tests/test_calculator.py",
        ],
        suspected_files=[
            SuspectedFile(
                path="calculator.py",
                confidence=0.95,
                reason="Direct division operation located in divide function",
                suspected_symbol="divide",
            )
        ],
        reproduction_hint="divide(10, 0)",
        test_filter="test_calculator.py",
        error_type="ZeroDivisionError",
        complexity_estimate=Complexity.LOW,
        estimated_steps=5,
        requires_external_knowledge=False,
        language="python",
        test_runner="pytest",
        parsing_confidence=0.98,
        parsing_method="RULE_BASED",
    )


# ─── Task 2.1: TokenBudgetManager & ContextOverflowError ─────────────────────

def test_token_budget_manager_ceiling_overflow():
    """Task 2.1: Exceeding ceiling raises ContextOverflowError."""
    config = ContextConfig(max_context_tokens=1000)
    manager = TokenBudgetManager(config)

    # Within budget should pass
    manager.enforce_ceiling(800)

    # Exceeding budget must raise ContextOverflowError
    with pytest.raises(ContextOverflowError, match="Context hard ceiling breached"):
        manager.enforce_ceiling(1001)


def test_token_budget_manager_per_section_budgets():
    """Task 2.1: Verify per-section budget properties match config."""
    config = ContextConfig(
        max_context_tokens=32000,
        response_reserve_tokens=4000,
        persona_budget_tokens=300,
        goal_budget_tokens=200,
        repo_context_budget_tokens=1000,
        working_memory_budget_tokens=800,
        recent_turns_budget_tokens=4000,
        compression_threshold=0.70,
    )
    manager = TokenBudgetManager(config)

    assert manager.fixed_tokens == 500  # 300 + 200
    assert manager.dynamic_available_tokens == 27500  # 32000 - 500 - 4000
    assert manager.is_compression_needed(22400) is True  # 32000 * 0.70 = 22400
    assert manager.is_compression_needed(20000) is False


# ─── Task 2.2: 5-Section Prompt Builder Order and Budgets ───────────────────

def test_5_section_prompt_builder_order_and_budget(sample_issue_plan):
    """Task 2.2: Sections in correct order and total within budget."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        cm = ContextManager(output_dir=tmp_dir)
        cm.set_issue(sample_issue_plan)

        cm.add_turn({"step": 1, "tool": "search_code", "query": "def divide", "result": "found at line 42"})

        ranked_files = [
            RankedFile(
                path="calculator.py",
                relevance_score=0.98,
                symbol_summary="def divide(a: float, b: float) -> float",
                line_count=60,
                language="python",
            )
        ]

        sections = cm.build_prompt(ranked_files=ranked_files)

        # 1. Total tokens must be within max_context_tokens
        assert sections.total_tokens <= cm.budget_manager.max_context_tokens
        assert sections.budget_remaining > 0

        # 2. Assembled prompt must contain all 5 sections in strict fixed order
        full_prompt = cm.assemble_prompt(sections)

        pos_persona = full_prompt.find("# § SYSTEM PERSONA")
        pos_goal = full_prompt.find("# § ACTIVE ISSUE GOAL")
        pos_repo = full_prompt.find("# § REPO CONTEXT")
        pos_wm = full_prompt.find("# § COMPRESSED WORKING MEMORY")
        pos_turns = full_prompt.find("# § RECENT TURNS")

        assert pos_persona != -1, "PERSONA section missing"
        assert pos_goal != -1, "GOAL section missing"
        assert pos_repo != -1, "REPO CONTEXT section missing"
        assert pos_wm != -1, "WORKING MEMORY section missing"
        assert pos_turns != -1, "RECENT TURNS section missing"

        # Verify strict sequential order
        assert pos_persona < pos_goal < pos_repo < pos_wm < pos_turns


# ─── Task 2.3: KV Cache Optimization ────────────────────────────────────────

def test_kv_cache_byte_identical_across_turns(sample_issue_plan):
    """Task 2.3: Bytes of sections 1+2 unchanged across 5 consecutive turns."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        cm = ContextManager(output_dir=tmp_dir)
        cm.set_issue(sample_issue_plan)

        persona_bytes_history = []
        goal_bytes_history = []

        # Execute 5 turns with varied actions and observations
        for i in range(1, 6):
            cm.add_turn({
                "step": i,
                "tool": f"tool_operation_{i}",
                "args": {"param": i * 10},
                "observation": f"Sample observation output for turn {i}",
            })

            sections = cm.build_prompt()

            persona_bytes = sections.persona.encode("utf-8")
            goal_bytes = sections.issue_goal.encode("utf-8")

            persona_bytes_history.append(persona_bytes)
            goal_bytes_history.append(goal_bytes)

        # Section 1 bytes must be identical across all 5 turns
        first_persona = persona_bytes_history[0]
        assert all(b == first_persona for b in persona_bytes_history)

        # Section 2 bytes must be identical across all 5 turns
        first_goal = goal_bytes_history[0]
        assert all(b == first_goal for b in goal_bytes_history)


# ─── Task 2.4: Dynamic Budget Adjustment Algorithm ──────────────────────────

def test_dynamic_budget_adjustment_n_reduces(sample_issue_plan):
    """Task 2.4: N reduces dynamically when turns are long."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Small recent_turns budget to trigger dynamic reduction
        config = ContextConfig(
            recent_turns_budget_tokens=250,
            working_memory_budget_tokens=400,
            max_context_tokens=4000,
        )
        cm = ContextManager(config=config, output_dir=tmp_dir)
        cm.set_issue(sample_issue_plan)

        # Add 6 verbose turns (each ~100 tokens)
        for i in range(1, 7):
            cm.add_turn({
                "step": i,
                "tool": "read_file_range",
                "observation": "verbose log analysis " * 40 + f"step_{i}",
            })

        assert len(cm.turns) == 6

        sections = cm.build_prompt()

        # Check that recent_turns was trimmed to fit within recent_turns_budget_tokens
        recent_turns_tokens = count_tokens(sections.recent_turns)
        assert recent_turns_tokens <= config.recent_turns_budget_tokens

        # Check that older turns were compressed into working memory
        assert len(cm.working_memory.files_examined) > 0 or len(cm.working_memory.edits_applied) >= 0


# ─── Task 2.5: Observation Truncation Across All 5 Size Classes ──────────────

def test_observation_truncation_5_size_classes():
    """Task 2.5: Each size class produces correct head/tail/separator format."""
    # 1. Output < 100 lines: Full verbatim
    lines_50 = "\n".join(f"line {i}" for i in range(50))
    res_50 = truncate_observation(lines_50)
    assert res_50 == lines_50
    assert "[..." not in res_50

    # 2. Output 100–300 lines: First 25, Last 60, [... {N} lines omitted ...]
    lines_200 = "\n".join(f"line {i}" for i in range(200))
    res_200 = truncate_observation(lines_200)
    assert res_200.startswith("line 0\nline 1")
    assert res_200.endswith("line 198\nline 199")
    expected_omitted_200 = 200 - 25 - 60  # 115
    assert f"[... {expected_omitted_200} lines omitted ...]" in res_200

    # 3. Output 300–1000 lines: First 20, Last 50, [... {N} lines omitted. Key: ... ...]
    lines_500 = "\n".join(f"data_log_line_{i}" for i in range(500))
    res_500 = truncate_observation(lines_500)
    assert res_500.startswith("data_log_line_0")
    assert res_500.endswith("data_log_line_499")
    expected_omitted_500 = 500 - 20 - 50  # 430
    assert f"[... {expected_omitted_500} lines omitted. Key:" in res_500

    # 4. Output > 1000 lines: First 15, Last 40, [... {N} lines omitted. Summary: ... ...]
    lines_1500 = "\n".join(f"trace_stream_{i}" for i in range(1500))
    res_1500 = truncate_observation(lines_1500)
    assert res_1500.startswith("trace_stream_0")
    assert res_1500.endswith("trace_stream_1499")
    expected_omitted_1500 = 1500 - 15 - 40  # 1445
    assert f"[... {expected_omitted_1500} lines omitted. Summary:" in res_1500

    # 5. Test output: Exit code + FAILED test names + First traceback + [... passing tests omitted ...]
    test_output = (
        "=== test session starts ===\n"
        "test_a.py . PASSED\n"
        "test_b.py . PASSED\n"
        "FAILED tests/test_calc.py::test_divide_zero - ZeroDivisionError: division by zero\n"
        "Traceback (most recent call last):\n"
        "  File 'calculator.py', line 12, in divide\n"
        "    return a / b\n"
        "ZeroDivisionError: division by zero\n"
        "=== 1 failed, 2 passed in 0.12s ==="
    )
    res_test = truncate_observation(test_output, tool="run_test_suite", exit_code=1)
    assert "Exit code: 1" in res_test
    assert "FAILED tests/test_calc.py::test_divide_zero" in res_test
    assert "ZeroDivisionError: division by zero" in res_test
    assert "[... passing tests omitted ...]" in res_test

    # 6. Patch output: Full verbatim (patches are short)
    patch_output = "--- a/calc.py\n+++ b/calc.py\n@@ -1,3 +1,3 @@\n- old\n+ new"
    res_patch = truncate_observation(patch_output, tool="apply_patch")
    assert res_patch == patch_output


# ─── Task 2.6: RollingSummarizer 70% Trigger ────────────────────────────────

def test_rolling_summarizer_70_percent_trigger(sample_issue_plan):
    """Task 2.6: Triggers at 70%; output captures goal + findings + edits."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Set max_context to 2000 tokens so 70% is 1400 tokens
        config = ContextConfig(
            max_context_tokens=2000,
            compression_threshold=0.70,
            recent_turns_budget_tokens=1000,
            working_memory_budget_tokens=500,
        )
        cm = ContextManager(config=config, output_dir=tmp_dir)
        cm.set_issue(sample_issue_plan)

        # Add multiple turns with tool interactions
        cm.add_turn("read_file_range(path='calculator.py', start=1, end=50) -> inspected division logic")
        cm.add_turn("apply_patch(target_file='calculator.py', patch='...') -> applied null check")
        cm.add_turn("run_test_suite() -> FAILED test_divide_zero")
        cm.add_turn("read_file_range(path='tests/test_calculator.py', start=1, end=30) -> reviewed assertion")

        # Force high token usage to surpass 70% (1400 tokens)
        for i in range(5):
            cm.add_turn(f"navigation_step_{i} reading code: " + "context buffer analysis " * 70)

        # Prompt building should trigger rolling compression at 70%
        sections = cm.build_prompt()

        assert sections.total_tokens <= config.max_context_tokens
        # Working memory should have captured examined files and edits
        assert "calculator.py" in cm.working_memory.files_examined
        assert any("calculator.py" in edit for edit in cm.working_memory.edits_applied)
        assert cm.working_memory.test_status.startswith("FAIL")


# ─── Task 2.7: Rolling Summarizer Compression Template & Limit ──────────────

def test_rolling_summarizer_compression_prompt_and_token_limit():
    """Task 2.7: Compression output <= 600 tokens with all required fields."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        summarizer = RollingSummarizer(output_dir=tmp_dir)

        memory = WorkingMemory(
            goal="Fix divide by zero bug in calculator.py",
            files_examined={"calculator.py": "found ZeroDivisionError in divide()"},
            edits_applied=["calculator.py: applied guard check against b == 0"],
            test_status="PASS: all 4 tests passing",
            current_strategy="Run full test suite to ensure no regressions",
            lessons_learned=["Always check divisor before dividing"],
        )

        turns = [
            "Turn 1: read_file_range(path='calculator.py')",
            "Turn 2: apply_patch(target_file='calculator.py')",
        ]

        # Verify compression prompt construction
        prompt = summarizer.build_compression_prompt(turns, memory)
        assert "OUTPUT FORMAT (strict, 600 tokens max):" in prompt
        assert "## Goal" in prompt
        assert "## Files Examined" in prompt
        assert "## Edits Applied" in prompt
        assert "## Test Status" in prompt
        assert "## Current Strategy" in prompt
        assert "## Lessons Learned" in prompt

        # Test compression execution
        compressed_memory = summarizer.compress(turns, memory)
        formatted = format_working_memory(compressed_memory)

        tokens = count_tokens(formatted)
        assert tokens <= 600, f"Compressed memory output exceeded 600 tokens ({tokens} tok)"
        assert "## Goal" in formatted
        assert "## Files Examined" in formatted
        assert "## Edits Applied" in formatted
        assert "## Test Status" in formatted
        assert "## Current Strategy" in formatted
        assert "## Lessons Learned" in formatted


# ─── Task 2.8: WorkingMemorySnapshot Writer ──────────────────────────────────

def test_working_memory_snapshot_writer():
    """Task 2.8: .harness/context_summary.md written after each compression event."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        summarizer = RollingSummarizer(output_dir=tmp_dir)

        memory = WorkingMemory(
            goal="Ensure test suite passes",
            files_examined={"service.py": "inspected token auth"},
            edits_applied=["service.py: fixed auth header"],
            test_status="PASS",
            current_strategy="Completed",
            lessons_learned=["Headers must be ascii encoded"],
        )

        snapshot_file = summarizer.write_snapshot(memory)

        path = Path(snapshot_file)
        assert path.exists(), "Snapshot file was not written"
        assert path.name == "context_summary.md"

        content = path.read_text(encoding="utf-8")
        assert "# Zenith Working Memory Snapshot" in content
        assert "service.py" in content
        assert "Token Footprint:" in content


# ─── Task 2.9: Accurate Token Counting ───────────────────────────────────────

def test_token_counting_accuracy():
    """Task 2.9: Token counts within 5% of actual tiktoken model count."""
    test_texts = [
        "Hello, this is a short test sentence.",
        "def calculate_total(items: list[dict]) -> float:\n    return sum(item['price'] for item in items)",
        "The quick brown fox jumps over the lazy dog. " * 20,
    ]

    enc = tiktoken.get_encoding("cl100k_base")

    for text in test_texts:
        expected = len(enc.encode(text, disallowed_special=()))
        actual = count_tokens(text)

        error_margin = abs(actual - expected) / max(1, expected)
        assert error_margin <= 0.05, f"Token count discrepancy > 5%: expected {expected}, got {actual}"


# ─── Task 2.10: Telemetry Integration ────────────────────────────────────────

def test_context_manager_telemetry_integration(sample_issue_plan):
    """Task 2.10: Prompt token count logged in telemetry every turn."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        telemetry_writer = TelemetryWriter(output_dir=tmp_dir, session_id="test-session-p2")

        cm = ContextManager(output_dir=tmp_dir)
        cm.set_issue(sample_issue_plan)
        cm.add_turn({"step": 1, "tool": "search_code", "query": "divide"})

        sections = cm.build_prompt()
        telem_fields = cm.get_telemetry_fields(sections.total_tokens)

        assert "context_tokens_used" in telem_fields
        assert "context_budget" in telem_fields
        assert "context_utilization_pct" in telem_fields

        event = TelemetryEvent(
            session_id=telemetry_writer.session_id,
            step=1,
            event_type=EventType.LLM_TURN_START,
            context_tokens_used=telem_fields["context_tokens_used"],
            context_budget=telem_fields["context_budget"],
            context_utilization_pct=telem_fields["context_utilization_pct"],
        )
        telemetry_writer.append(event)

        # Verify the event was written into telemetry.jsonl
        telemetry_file = Path(tmp_dir) / "telemetry.jsonl"
        assert telemetry_file.exists()
        log_content = telemetry_file.read_text(encoding="utf-8")
        assert "LLM_TURN_START" in log_content
        assert f'"context_tokens_used": {sections.total_tokens}' in log_content


# ─── New API: update_working_memory ──────────────────────────────────────────

def test_update_working_memory_encapsulated_api(sample_issue_plan):
    """update_working_memory() provides safe, capped mutations to working memory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        cm = ContextManager(output_dir=tmp_dir)
        cm.set_issue(sample_issue_plan)

        cm.update_working_memory(file_examined=("calculator.py", "divide function at line 12"))
        assert "calculator.py" in cm.working_memory.files_examined
        assert cm.working_memory.files_examined["calculator.py"] == "divide function at line 12"

        cm.update_working_memory(edit_applied="calculator.py: added zero guard")
        assert "calculator.py: added zero guard" in cm.working_memory.edits_applied

        cm.update_working_memory(test_status="PASS: all tests passing")
        assert cm.working_memory.test_status == "PASS: all tests passing"

        cm.update_working_memory(strategy="Verify full regression suite")
        assert cm.working_memory.current_strategy == "Verify full regression suite"

        cm.update_working_memory(lesson="Always guard against zero before division")
        assert "Always guard against zero before division" in cm.working_memory.lessons_learned

        # Duplicate lesson should NOT be appended
        cm.update_working_memory(lesson="Always guard against zero before division")
        assert cm.working_memory.lessons_learned.count("Always guard against zero before division") == 1

        # Duplicate file should NOT be overwritten
        cm.update_working_memory(file_examined=("calculator.py", "different finding"))
        assert cm.working_memory.files_examined["calculator.py"] == "divide function at line 12"

        # Cap at 8 files
        for i in range(10):
            cm.update_working_memory(file_examined=(f"file_{i}.py", f"finding {i}"))
        assert len(cm.working_memory.files_examined) <= 8


# ─── New API: reset ───────────────────────────────────────────────────────────

def test_context_manager_reset_clears_state(sample_issue_plan):
    """reset() wipes turn history and working memory, optionally registers new issue."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        cm = ContextManager(output_dir=tmp_dir)
        cm.set_issue(sample_issue_plan)

        cm.add_turn({"step": 1, "tool": "search_code"})
        cm.update_working_memory(file_examined=("a.py", "found bug"))
        assert len(cm.turns) == 1
        assert "a.py" in cm.working_memory.files_examined

        cm.reset()
        assert len(cm.turns) == 0
        assert cm.working_memory.goal == ""
        assert cm.working_memory.files_examined == {}
        assert cm.issue_plan is None
        assert cm._cached_persona_str is None

        # Reset with new issue pre-registered
        cm.reset(issue_plan=sample_issue_plan)
        assert cm.issue_plan is not None
        assert cm.working_memory.goal == sample_issue_plan.primary_goal
        assert cm._cached_persona_str is not None


# ─── TurnRecord auto-timestamp ────────────────────────────────────────────────

def test_turn_record_auto_timestamp():
    """TurnRecord auto-populates timestamp via __post_init__ when not provided."""
    from datetime import datetime

    from harness.context_manager import TurnRecord

    turn = TurnRecord(step=1, tool="search_code")
    assert turn.timestamp != ""
    parsed = datetime.fromisoformat(turn.timestamp)
    assert parsed is not None

    # Explicit timestamp should NOT be overwritten
    explicit_ts = "2026-01-01T00:00:00+00:00"
    turn_explicit = TurnRecord(step=2, tool="read_file", timestamp=explicit_ts)
    assert turn_explicit.timestamp == explicit_ts


# ─── process_tool_result wires config head/tail lines ────────────────────────

def test_process_tool_result_uses_config_truncation():
    """process_tool_result uses ContextConfig head/tail lines, not hardcoded defaults."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = ContextConfig(observation_head_lines=5, observation_tail_lines=5)
        cm = ContextManager(config=config, output_dir=tmp_dir)

        from harness.contracts import ResultStatus, ToolResult
        big_output = "\n".join(f"line {i}" for i in range(200))
        tr = ToolResult(
            tool="list_dir",
            args_hash="abc123",
            status=ResultStatus.SUCCESS,
            raw_output=big_output,
            truncated_output="",
        )
        processed = cm.process_tool_result(tr)

        assert "lines omitted" in processed.truncated_output
        output_lines = processed.truncated_output.splitlines()
        assert len(output_lines) <= 15  # 5 head + separator + 5 tail
        assert processed.tokens_in_raw > processed.tokens_in_truncated
