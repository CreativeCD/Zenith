"""Unit tests for harness/semantic_compressor.py."""

from harness.semantic_compressor import SemanticCompressor


def test_clean_terminal_noise_ansi():
    raw = "\x1b[31mError:\x1b[0m \x1b[1mFile not found\x1b[0m\n\n\n\nline 2"
    cleaned = SemanticCompressor.clean_terminal_noise(raw)
    assert "\x1b" not in cleaned
    assert "Error: File not found" in cleaned
    assert cleaned.count("\n\n\n") == 0


def test_clean_terminal_noise_carriage_return():
    raw = "Downloading... [10%]\rDownloading... [50%]\rDownloading... [100%]\nDone!"
    cleaned = SemanticCompressor.clean_terminal_noise(raw)
    assert "Downloading... [100%]" in cleaned
    assert "Done!" in cleaned


def test_extract_code_signatures():
    code = """
import os

class BillingCalculator:
    def __init__(self):
        pass

    def calculate_discount(self, user):
        return 0.1

async def async_fetch():
    pass
"""
    sigs = SemanticCompressor.extract_code_signatures(code)
    assert "BillingCalculator" in sigs
    assert "calculate_discount" in sigs
    assert "async_fetch" in sigs


def test_compress_test_output_passing():
    compressor = SemanticCompressor()
    output = "collected 50 items\n" + "." * 50 + "\n50 passed in 1.23s\n"
    res = compressor.compress_test_output(output, exit_code=0)
    assert "Exit code: 0" in res
    assert "50 passed" in res
    assert "collected 50 items" not in res


def test_compress_test_output_failing():
    compressor = SemanticCompressor()
    output = """
============================= test session starts ==============================
collected 2 items
tests/test_calc.py .F

=================================== FAILURES ===================================
_________________________________ test_discount ________________________________
def test_discount():
>       assert calculate_discount() == 10
E       KeyError: 'tier'

tests/test_calc.py:12: KeyError
=========================== short test summary info ============================
FAILED tests/test_calc.py::test_discount - KeyError: 'tier'
========================= 1 failed, 1 passed in 0.12s ==========================
"""
    res = compressor.compress_test_output(output, exit_code=1)
    assert "Exit code: 1" in res
    assert "FAILED tests/test_calc.py::test_discount - KeyError: 'tier'" in res
    assert "KeyError" in res


def test_compress_observation_aging():
    compressor = SemanticCompressor(max_verbatim_lines=10, max_compact_lines=5)
    file_content = "\n".join(f"line {i}: def func_{i}(): pass" for i in range(30))

    # Age 0 (active turn): has head and tail
    obs_0 = compressor.compress_observation(
        tool="read_file_range",
        args={"file_path": "test.py", "start_line": 1, "end_line": 30},
        raw_output=file_content,
        age_in_turns=0,
    )
    # Total lines was 30 which is <= max_verbatim_lines(30 in standard, here 10)
    assert "line 0" in obs_0

    # Age 2 (older turn): dense outline summary
    obs_2 = compressor.compress_observation(
        tool="read_file_range",
        args={"file_path": "test.py", "start_line": 1, "end_line": 30},
        raw_output=file_content,
        age_in_turns=2,
    )
    assert "[Observed test.py L1-30" in obs_2
    assert "Symbols:" in obs_2


def test_compact_history():
    compressor = SemanticCompressor()
    long_obs = "\n".join(f"data line {i} with lots of verbose tokens" for i in range(50))

    history = [
        {"role": "user", "content": "find the bugs"},
        {"role": "model", "content": "I executed tool read_file_range"},
        {"role": "user", "content": f"Observation from `read_file_range`:\n{long_obs}"},
        {"role": "model", "content": "I executed tool search_code"},
        {"role": "user", "content": f"Observation from `search_code`:\n{long_obs}"},
        {"role": "model", "content": "I executed tool run_test_suite"},
        {"role": "user", "content": f"Observation from `run_test_suite`:\n{long_obs}"},
        {"role": "model", "content": "I executed tool apply_patch"},
        {"role": "user", "content": f"Observation from `apply_patch`:\n{long_obs}"},
        {"role": "model", "content": "I executed tool run_test_suite"},
        {"role": "user", "content": f"Observation from `run_test_suite`:\n{long_obs}"},
    ]

    # Keep only 2 recent pairs in full detail; older 3 must be compacted
    compacted, tokens_saved = compressor.compact_history(history, keep_recent_pairs=2)
    assert tokens_saved > 0
    assert len(compacted) == len(history)

    # First observation should be compacted
    assert "Observation from `read_file_range` (compacted):" in compacted[2]["content"]
    # Last observation should remain uncompacted
    assert "(compacted)" not in compacted[-1]["content"]
