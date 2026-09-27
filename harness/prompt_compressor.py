"""harness/prompt_compressor.py — Built-in User Prompt Compression (Zenith speciality).

Inspired by Ponytail semantic compression. Condenses verbose user prompts BEFORE
they enter the model context, so every downstream turn pays for fewer tokens.

Two-stage pipeline:
  1. Deterministic heuristic compression (zero LLM tokens, always available):
     protects semantic anchors (code blocks, inline code, file paths, URLs,
     error/traceback lines) verbatim, then strips terminal noise, filler
     politeness, hedging, and duplicated lines/sentences.
  2. Optional LLM rewrite for very long prompts (temperature 0), with strict
     anchor-preservation validation — falls back to stage 1 if any anchor is
     lost or the call fails.

Compression is lossless-by-contract for anything task-bearing: if the savings
are below min_savings_ratio the original prompt is returned untouched.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Anchor patterns (protected verbatim) ────────────────────────────────────

CODE_FENCE_REGEX = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~")
INLINE_CODE_REGEX = re.compile(r"`[^`\n]+`")
URL_REGEX = re.compile(r"https?://[^\s'\"<>)]+")
FILE_PATH_REGEX = re.compile(
    r"(?:[\w.\-]+/)+[\w.\-]+[./]?|"
    r"\b[\w\-]+\.(?:py|js|jsx|ts|tsx|go|rs|java|c|cc|cpp|h|hpp|rb|php|swift|kt|"
    r"md|yaml|yml|json|toml|ini|cfg|txt|sh|bash|zsh|css|scss|html|xml|sql|ipynb)\b"
)
ERROR_LINE_REGEX = re.compile(
    r"^[ \t]*(?:Traceback \(most recent call last\):.*|"
    r"File \"[^\"]*\", line \d+.*|"
    r"[\w.]*(?:Error|Exception|Warning):.*|"
    r"(?:FAILED|ERROR)[ \t]+[\w./:\-\[\]]+.*)$",
    re.MULTILINE,
)

# ─── Filler / noise patterns (removed from unprotected text) ─────────────────

FILLER_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bi was wondering if you could\s+", re.IGNORECASE), ""),
    (re.compile(r"\bi was wondering if\s+", re.IGNORECASE), ""),
    (re.compile(r"\bi wonder if\s+", re.IGNORECASE), ""),
    (re.compile(r"\bcould you (?:please |maybe |possibly |kindly )?", re.IGNORECASE), ""),
    (re.compile(r"\bcan you (?:please |maybe |possibly |kindly )?", re.IGNORECASE), ""),
    (re.compile(r"\bwould you mind (?:please |maybe )?", re.IGNORECASE), ""),
    (re.compile(r"\bif you don'?t mind,?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bwhen(?:ever)? you (?:get a chance|have time),?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bsorry to bother you,?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bthanks? (?:so much )?in advance!?\.?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bif (?:it'?s |it is )?possible,?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bplease\s*,?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bkindly\s+", re.IGNORECASE), ""),
    (re.compile(r"\bplz\s+", re.IGNORECASE), ""),
    (re.compile(r"\bi think (?:that )?(?:maybe |probably )?", re.IGNORECASE), ""),
    (re.compile(r"\bjust wanted to\s+", re.IGNORECASE), ""),
    (re.compile(r"\bwanted to (?:ask|check|see) (?:if|whether)\s+", re.IGNORECASE), ""),
    (re.compile(r"\bhope (?:this |you )?(?:helps|are doing well)[.!]?\s*", re.IGNORECASE), ""),
    # Redundant intensifier duplication: "very very", "really really"
    (
        re.compile(
            r"\b(very|really|so|just|quite|extremely|totally|completely|absolutely|actually|literally)(\s+\1\b)+",
            re.IGNORECASE,
        ),
        r"\1",
    ),
]

MULTI_BLANK_REGEX = re.compile(r"\n{3,}")
MULTI_SPACE_REGEX = re.compile(r"[ \t]{2,}")
ANSI_ESCAPE_REGEX = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

LLM_COMPRESSION_PROMPT = (
    "You are a prompt compression engine for an AI coding agent. Compress the user prompt below.\n"
    "RULES:\n"
    "1. Keep EVERY file path, symbol name, URL, command, error message, and code snippet VERBATIM.\n"
    "2. Preserve all requirements, constraints, and acceptance criteria — never drop a task.\n"
    "3. Remove redundancy, filler, politeness, hedging, and repeated statements.\n"
    "4. Use terse imperative bullet points where the original is wordy prose.\n"
    "5. Output ONLY the compressed prompt, nothing else.\n\n"
    "USER PROMPT:\n"
)


@dataclass
class CompressionResult:
    original: str
    compressed: str
    method: str  # "none" | "heuristic" | "llm"
    chars_saved: int = 0
    tokens_saved: int = 0


class PromptCompressor:
    """Compresses user-supplied prompts before they enter the model context."""

    def __init__(
        self,
        enabled: bool = True,
        char_threshold: int = 400,
        use_llm: bool = True,
        llm_char_threshold: int = 2500,
        min_savings_ratio: float = 0.05,
        model_adapter=None,
    ) -> None:
        self.enabled = enabled
        self.char_threshold = char_threshold
        self.use_llm = use_llm
        self.llm_char_threshold = llm_char_threshold
        self.min_savings_ratio = min_savings_ratio
        self.model_adapter = model_adapter

    # ─── Public API ─────────────────────────────────────────────────────────

    def compress(self, text: str) -> CompressionResult:
        """Deterministic heuristic compression (zero LLM tokens)."""
        if not self.enabled or not text or len(text) < self.char_threshold:
            return CompressionResult(original=text or "", compressed=text or "", method="none")

        compressed = self._heuristic_compress(text)
        savings = len(text) - len(compressed)
        if savings <= 0 or savings / len(text) < self.min_savings_ratio:
            return CompressionResult(original=text, compressed=text, method="none")
        return CompressionResult(
            original=text,
            compressed=compressed,
            method="heuristic",
            chars_saved=savings,
            tokens_saved=savings // 4,
        )

    async def compress_async(self, text: str) -> CompressionResult:
        """Heuristic compression, upgraded to an LLM rewrite for very long prompts."""
        base = self.compress(text)
        if (
            not self.use_llm
            or self.model_adapter is None
            or not text
            or len(text) < self.llm_char_threshold
        ):
            return base

        try:
            llm_compressed = await self._llm_compress(text)
        except Exception as e:
            logger.warning("LLM prompt compression failed, using heuristic: %s", e)
            return base

        if llm_compressed is None:
            return base

        savings = len(text) - len(llm_compressed)
        if savings <= 0 or savings / len(text) < self.min_savings_ratio:
            return base
        return CompressionResult(
            original=text,
            compressed=llm_compressed,
            method="llm",
            chars_saved=savings,
            tokens_saved=savings // 4,
        )

    # ─── Heuristic stage ────────────────────────────────────────────────────

    def _heuristic_compress(self, text: str) -> str:
        protected, vault = self._protect_anchors(text)

        cleaned = ANSI_ESCAPE_REGEX.sub("", protected)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")

        # Strip filler phrases
        for pattern, repl in FILLER_PATTERNS:
            cleaned = pattern.sub(repl, cleaned)

        # Deduplicate sentences (exact matches, order preserved)
        cleaned = self._dedup_sentences(cleaned)

        # Deduplicate exact duplicate non-empty lines (order preserved)
        cleaned = self._dedup_lines(cleaned)

        # Whitespace normalization
        cleaned = MULTI_SPACE_REGEX.sub(" ", cleaned)
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = MULTI_BLANK_REGEX.sub("\n\n", cleaned)
        cleaned = cleaned.strip()

        return self._restore_anchors(cleaned, vault)

    @staticmethod
    def _dedup_sentences(text: str) -> str:
        # Per-line only: joining across lines would flatten the prompt's
        # paragraph/list structure.
        out_lines: List[str] = []
        for line in text.split("\n"):
            sentences = re.split(r"(?<=[.!?])\s+", line)
            if len(sentences) < 2:
                out_lines.append(line)
                continue
            seen: set[str] = set()
            kept: List[str] = []
            for s in sentences:
                key = re.sub(r"\s+", " ", s.strip().lower())
                if key and len(key) > 30 and key in seen:
                    continue
                if key:
                    seen.add(key)
                kept.append(s)
            out_lines.append(" ".join(kept))
        return "\n".join(out_lines)

    @staticmethod
    def _dedup_lines(text: str) -> str:
        lines = text.split("\n")
        seen: set[str] = set()
        out: List[str] = []
        for line in lines:
            key = line.strip().lower()
            if key and len(key) > 20 and key in seen:
                continue
            if key:
                seen.add(key)
            out.append(line)
        return "\n".join(out)

    # ─── Anchor protection ──────────────────────────────────────────────────

    @staticmethod
    def _protect_anchors(text: str) -> Tuple[str, List[str]]:
        vault: List[str] = []

        def stash(match: re.Match) -> str:
            vault.append(match.group(0))
            return f"\x00A{len(vault) - 1}\x00"

        protected = CODE_FENCE_REGEX.sub(stash, text)
        protected = INLINE_CODE_REGEX.sub(stash, protected)
        protected = URL_REGEX.sub(stash, protected)
        protected = ERROR_LINE_REGEX.sub(stash, protected)
        protected = FILE_PATH_REGEX.sub(stash, protected)
        return protected, vault

    @staticmethod
    def _restore_anchors(text: str, vault: List[str]) -> str:
        def unstash(match: re.Match) -> str:
            idx = int(match.group(1))
            return vault[idx] if idx < len(vault) else match.group(0)

        return re.sub(r"\x00A(\d+)\x00", unstash, text)

    def extract_anchors(self, text: str) -> List[str]:
        """Return all protected anchors found in text (for validation)."""
        _, vault = self._protect_anchors(text)
        return vault

    # ─── LLM stage ──────────────────────────────────────────────────────────

    async def _llm_compress(self, text: str) -> Optional[str]:
        response = await self.model_adapter.complete(
            system_prompt=(
                "You compress user prompts for an AI coding agent. You preserve every "
                "task-bearing token verbatim and output only the compressed prompt."
            ),
            user_message=LLM_COMPRESSION_PROMPT + text,
            temperature=0.0,
        )
        content = (response.content or "").strip()
        if not content or content.startswith("[GEMINI_ERROR"):
            return None

        # Hard validation: every anchor must survive the rewrite, and the
        # result must actually be shorter. Otherwise reject.
        if len(content) >= len(text):
            return None
        anchors = self.extract_anchors(text)
        missing = [a for a in anchors if a.strip() and a not in content]
        if missing:
            logger.info(
                "LLM compression dropped %d anchor(s); falling back to heuristic", len(missing)
            )
            return None
        return content
