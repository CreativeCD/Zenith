"""tests/test_prompt_compressor.py — Unit tests for the built-in user prompt compressor.

Covers: threshold gating, filler removal, anchor preservation (code blocks,
inline code, file paths, URLs, error lines), deduplication, disabled mode,
and the LLM stage with anchor-loss fallback.
"""

import asyncio

from harness.adapters.base import ModelResponse
from harness.prompt_compressor import PromptCompressor
from harness.semantic_compressor import SemanticCompressor


VERBOSE_PROMPT = (
    "Hey there! I was wondering if you could please take a look at this problem I have been having. "
    "So basically, could you please investigate why the parser crashes? "
    "The parser crashes whenever I run the reproduction steps below, and honestly it is very frustrating. "
    "The parser crashes whenever I run the reproduction steps below, and honestly it is very frustrating.\n\n"
    "The error I keep seeing in my terminal output is this one:\n"
    "ValueError: invalid literal for int() with base 10: 'abc'\n\n"
    "The relevant file is harness/issue_parser.py and there is also a helper in harness/tools/editor.py "
    "that might matter. You can see the docs at https://example.com/docs/parser#usage for reference.\n\n"
    "Here is the snippet that fails:\n"
    "```python\n"
    "def parse(x):\n"
    "    return int(x)  # please do not change this comment\n"
    "```\n\n"
    "Please fix the bug, and thanks in advance! If possible, keep the public API unchanged. "
    "Keep the public API unchanged. Would you mind also adding a regression test for the `parse` function?"
)


def test_short_prompt_never_touched():
    pc = PromptCompressor(char_threshold=400)
    res = pc.compress("fix the bug")
    assert res.method == "none"
    assert res.compressed == "fix the bug"


def test_disabled_returns_original():
    pc = PromptCompressor(enabled=False, char_threshold=10)
    res = pc.compress(VERBOSE_PROMPT)
    assert res.method == "none"
    assert res.compressed == VERBOSE_PROMPT


def test_filler_and_duplicates_removed():
    pc = PromptCompressor(char_threshold=100, min_savings_ratio=0.01)
    res = pc.compress(VERBOSE_PROMPT)
    assert res.method == "heuristic"
    assert res.chars_saved > 0
    assert res.tokens_saved == res.chars_saved // 4
    out = res.compressed.lower()
    assert "i was wondering" not in out
    assert "could you please" not in out
    assert "thanks in advance" not in out
    assert "please fix the bug" not in out
    # exact duplicate sentence collapsed to one occurrence
    assert out.count("the parser crashes whenever i run the reproduction steps below") == 1
    # the protected comment inside the code fence still contains "please"
    assert "please do not change this comment" in out


def test_anchors_preserved_verbatim():
    pc = PromptCompressor(char_threshold=100, min_savings_ratio=0.01)
    out = pc.compress(VERBOSE_PROMPT).compressed
    assert "```python\ndef parse(x):\n    return int(x)  # please do not change this comment\n```" in out
    assert "harness/issue_parser.py" in out
    assert "harness/tools/editor.py" in out
    assert "https://example.com/docs/parser#usage" in out
    assert "ValueError: invalid literal for int() with base 10: 'abc'" in out
    assert "`parse`" in out


def test_min_savings_ratio_guards_against_distortion():
    text = "x " * 300  # 600 chars, nothing compressible beyond whitespace
    pc = PromptCompressor(char_threshold=100, min_savings_ratio=0.5)
    res = pc.compress(text.strip())
    assert res.method == "none"


class _MockAdapter:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        return ModelResponse(content=self.reply)


def test_llm_stage_used_when_anchors_survive():
    compressed_reply = (
        "Fix ValueError in harness/issue_parser.py (helper: harness/tools/editor.py).\n"
        "ValueError: invalid literal for int() with base 10: 'abc'\n"
        "Docs: https://example.com/docs/parser#usage\n"
        "```python\n"
        "def parse(x):\n"
        "    return int(x)  # please do not change this comment\n"
        "```\n"
        "Keep public API unchanged; add regression test for `parse`."
    )
    adapter = _MockAdapter(compressed_reply)
    pc = PromptCompressor(char_threshold=100, llm_char_threshold=200, model_adapter=adapter)
    res = asyncio.run(pc.compress_async(VERBOSE_PROMPT))
    assert res.method == "llm"
    assert adapter.calls == 1
    assert res.compressed == compressed_reply.strip()


def test_llm_stage_falls_back_when_anchors_dropped():
    adapter = _MockAdapter("Fix the parser bug and add tests.")  # lost all anchors
    pc = PromptCompressor(char_threshold=100, llm_char_threshold=200, model_adapter=adapter)
    res = asyncio.run(pc.compress_async(VERBOSE_PROMPT))
    assert res.method == "heuristic"
    assert "harness/issue_parser.py" in res.compressed


def test_llm_stage_skipped_for_short_prompts():
    adapter = _MockAdapter("should not be called")
    pc = PromptCompressor(char_threshold=50, llm_char_threshold=5000, model_adapter=adapter)
    res = asyncio.run(pc.compress_async(VERBOSE_PROMPT))
    assert adapter.calls == 0
    assert res.method in ("none", "heuristic")


def test_compact_history_uses_args_header_for_paths():
    """Aged read_file_range summaries must keep the file path via the args header."""
    sc = SemanticCompressor()
    body = "\n".join(f"{i:4d}: line {i}" for i in range(1, 121))
    history = [
        {"role": "user", "content": 'Observation from `read_file_range` args={"file_path":"harness/cli.py","start_line":10,"end_line":130}:\n' + body},
        {"role": "model", "content": "ok"},
        {"role": "user", "content": "Observation from `search_code`:\n" + body},
        {"role": "model", "content": "ok"},
        {"role": "user", "content": "Observation from `list_dir`:\n" + body},
        {"role": "model", "content": "ok"},
        {"role": "user", "content": "Observation from `git_status`:\n" + body},
        {"role": "model", "content": "ok"},
        {"role": "user", "content": "Observation from `run_test_suite`:\n" + body},
    ]
    compacted, saved = sc.compact_history(history, keep_recent_pairs=2)
    first = compacted[0]["content"]
    assert "(compacted)" in first
    assert "harness/cli.py" in first
    assert "L10-L130" in first or "L10-130" in first
    assert saved > 0
