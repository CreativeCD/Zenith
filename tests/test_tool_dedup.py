"""Unit tests for harness/tools/dedup.py."""

from harness.tools.dedup import ToolCallDeduplicator


def test_missing_reasoning_empty():
    dedup = ToolCallDeduplicator()
    msg = dedup.check_and_record("read_file_range", {"file_path": "a.py"}, "")
    assert msg is not None
    assert "Missing required field 'reasoning'" in msg


def test_missing_reasoning_none():
    dedup = ToolCallDeduplicator()
    msg = dedup.check_and_record("read_file_range", {"file_path": "a.py"}, None)
    assert msg is not None
    assert "Missing required field 'reasoning'" in msg


def test_duplicate_call_blocked():
    dedup = ToolCallDeduplicator(window_size=10)
    args = {"file_path": "src/auth.py", "start_line": 1, "end_line": 50}
    
    # First call allowed
    msg1 = dedup.check_and_record("read_file_range", args, "Checking auth logic", step=1)
    assert msg1 is None

    # Second identical call blocked
    msg2 = dedup.check_and_record("read_file_range", args, "Re-reading auth logic", step=2)
    assert msg2 is not None
    assert "DEDUP: read_file_range" in msg2
    assert "was already called at step 1" in msg2
    assert "observation from step 1" in msg2
    assert "{stored_step}" not in msg2


def test_reset_on_edit():
    dedup = ToolCallDeduplicator(window_size=10)
    args = {"file_path": "src/auth.py", "start_line": 1, "end_line": 50}

    dedup.check_and_record("read_file_range", args, "Initial read", step=1)
    
    # Apply patch notifies edit
    dedup.check_and_record("apply_patch", {"target_file": "src/auth.py"}, "Patching bug", step=2)

    # Re-read is now permitted because file was modified
    msg3 = dedup.check_and_record("read_file_range", args, "Read after patch", step=3)
    assert msg3 is None


def test_ring_buffer_eviction():
    dedup = ToolCallDeduplicator(window_size=2)
    dedup.check_and_record("read_file_range", {"file_path": "1.py"}, "Read 1", step=1)
    dedup.check_and_record("read_file_range", {"file_path": "2.py"}, "Read 2", step=2)
    dedup.check_and_record("read_file_range", {"file_path": "3.py"}, "Read 3", step=3)

    # 1.py was evicted from the 2-slot window, so re-reading 1.py is permitted
    msg = dedup.check_and_record("read_file_range", {"file_path": "1.py"}, "Read 1 again", step=4)
    assert msg is None


def test_dedup_non_serializable_args(tmp_path):
    dedup = ToolCallDeduplicator()
    # Passing a Path object inside args should not crash json serialization
    args = {"path_obj": tmp_path / "file.py"}
    msg1 = dedup.check_and_record("read_file_range", args, "Reading with Path obj", step=1)
    assert msg1 is None
    msg2 = dedup.check_and_record("read_file_range", args, "Re-reading with Path obj", step=2)
    assert msg2 is not None
    assert "DEDUP" in msg2


def test_dedup_stats():
    dedup = ToolCallDeduplicator()
    dedup.check_and_record("read_file_range", {"f": "1.py"}, "read 1", step=1)
    dedup.check_and_record("read_file_range", {"f": "1.py"}, "read 1 again", step=2)
    assert dedup.total_calls_checked == 2
    assert dedup.total_calls_blocked == 1
