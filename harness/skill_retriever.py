"""harness/skill_retriever.py — Layer 6: External Knowledge & Skills Engine.

Reference: PRD.md §4.6 | architecture.md §7.6, §12.3
Implements:
- Cache-first retrieval with SHA256 keys and 24h TTL
- Disk cache persistence at .harness/skill_cache/{hash}.json
- Sub-10ms cache hit response time
- Local SWE-bench trajectory index for similar bug fix patterns
- Startup pre-fetch of README, CONTRIBUTING, CI, and test configs
- Relevant section extraction and token truncation (<= 500 tokens)
- Integration with ToolEngine and TelemetryWriter
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from harness.config import ExternalSkillsConfig
from harness.contracts import (
    AgentPhase,
    EventType,
    IssuePlan,
    ResultStatus,
    TelemetryEvent,
)
from harness.telemetry import TelemetryWriter

logger = logging.getLogger(__name__)


@dataclass
class SkillCacheEntry:
    """Represents a cached knowledge or skill snippet."""
    key: str
    source_type: str
    query: str
    content: str
    timestamp: float
    ttl_seconds: int = 86400  # 24 hours
    token_count: int = 0

    def is_valid(self, now: float | None = None) -> bool:
        """Check if cache entry has not expired."""
        current_time = now if now is not None else time.time()
        return (current_time - self.timestamp) < self.ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SkillCacheEntry:
        return cls(
            key=data["key"],
            source_type=data["source_type"],
            query=data["query"],
            content=data["content"],
            timestamp=float(data["timestamp"]),
            ttl_seconds=int(data.get("ttl_seconds", 86400)),
            token_count=int(data.get("token_count", 0)),
        )


class SkillCache:
    """Disk-backed, memory-accelerated skill cache with TTL validation."""

    def __init__(self, cache_dir: str = ".harness/skill_cache", ttl_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_hours * 3600
        self._memory_cache: Dict[str, SkillCacheEntry] = {}
        self._load_disk_cache()

    @staticmethod
    def compute_key(source_type: str, query: str) -> str:
        """Compute deterministic SHA256 key from source type and normalized query."""
        normalized = f"{source_type.strip().lower()}:{query.strip().lower()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _load_disk_cache(self) -> None:
        """Load valid unexpired entries from disk on startup."""
        now = time.time()
        for file in self.cache_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = SkillCacheEntry.from_dict(data)
                if entry.is_valid(now):
                    self._memory_cache[entry.key] = entry
                else:
                    # Clean up expired entry file
                    file.unlink(missing_ok=True)
            except Exception as e:
                logger.debug("Failed to load skill cache file %s: %s", file, e)

    def get(self, key: str) -> Optional[SkillCacheEntry]:
        """Retrieve entry by key. Returns None on cache miss or expiration."""
        now = time.time()
        # 1. Fast memory check (< 1ms)
        entry = self._memory_cache.get(key)
        if entry:
            if entry.is_valid(now):
                return entry
            else:
                self._evict(key)
                return None

        # 2. Disk fallback
        file_path = self.cache_dir / f"{key}.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry = SkillCacheEntry.from_dict(data)
                if entry.is_valid(now):
                    self._memory_cache[key] = entry
                    return entry
                else:
                    file_path.unlink(missing_ok=True)
            except Exception as e:
                logger.debug("Error reading cache file %s: %s", file_path, e)

        return None

    def set(
        self,
        source_type: str,
        query: str,
        content: str,
        ttl_seconds: int | None = None,
    ) -> SkillCacheEntry:
        """Store content in cache with key derived from source_type and query."""
        key = self.compute_key(source_type, query)
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        token_count = max(1, len(content) // 4)
        entry = SkillCacheEntry(
            key=key,
            source_type=source_type,
            query=query,
            content=content,
            timestamp=time.time(),
            ttl_seconds=ttl,
            token_count=token_count,
        )
        self._memory_cache[key] = entry

        # Persist to disk
        file_path = self.cache_dir / f"{key}.json"
        try:
            temp_path = self.cache_dir / f"{key}.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(entry.to_dict(), f, indent=2)
            os.replace(temp_path, file_path)
        except Exception as e:
            logger.warning("Failed to persist skill cache %s: %s", file_path, e)

        return entry

    def _evict(self, key: str) -> None:
        """Evict expired entry from memory and disk."""
        self._memory_cache.pop(key, None)
        file_path = self.cache_dir / f"{key}.json"
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass

    def clear(self) -> None:
        """Clear all cache entries."""
        self._memory_cache.clear()
        for file in self.cache_dir.glob("*.json"):
            try:
                file.unlink()
            except OSError:
                pass


class RelevantSectionExtractor:
    """Extracts semantically relevant subsections and truncates to token limits."""

    STOPWORDS = {
        "a", "an", "the", "in", "on", "of", "to", "for", "with", "by", "at",
        "from", "is", "are", "was", "were", "and", "or", "not", "this", "that",
        "it", "as", "be", "test", "run", "how", "what", "which",
    }

    @classmethod
    def extract_relevant(cls, raw_content: str, query: str, max_tokens: int = 400) -> str:
        """Score sections by keyword density and return top sections up to max_tokens."""
        if not raw_content or not raw_content.strip():
            return "No content available."

        max_chars = max_tokens * 4
        if len(raw_content) <= max_chars:
            return raw_content.strip()

        # Split into sections by markdown headers or double newlines
        sections = re.split(r"(?:\n#{1,4}\s+|\n\n+)", raw_content)
        sections = [s.strip() for s in sections if s.strip()]

        if not sections:
            return raw_content[:max_chars]

        # Tokenize query
        query_words = set(re.findall(r"\b\w{2,}\b", query.lower())) - cls.STOPWORDS

        scored_sections = []
        for sec in sections:
            sec_words = set(re.findall(r"\b\w{2,}\b", sec.lower()))
            overlap = len(query_words & sec_words)
            # Bonus for exact query string match
            if query.lower() in sec.lower():
                overlap += 10
            scored_sections.append((overlap, sec))

        # Sort descending by score
        scored_sections.sort(key=lambda x: x[0], reverse=True)

        selected = []
        total_len = 0
        for _, sec in scored_sections:
            if total_len + len(sec) > max_chars:
                # Add truncated part of section if room permits
                remaining = max_chars - total_len
                if remaining > 100:
                    selected.append(sec[:remaining] + "\n[... truncated ...]")
                break
            selected.append(sec)
            total_len += len(sec)

        result = "\n\n".join(selected)
        return result if result.strip() else raw_content[:max_chars]


class SWEBenchTrajectoryIndex:
    """Curated repository of bug fix patterns and architectural trajectories."""

    PATTERNS: List[Dict[str, Any]] = [
        {
            "id": "null_pointer_guard",
            "title": "Null / NoneType Guard and Default Fallback",
            "tags": ["none", "null", "nonetype", "attributeerror", "guard", "optional", "missing"],
            "strategy": (
                "Guard against NoneType or null values before accessing properties or calling methods. "
                "Provide safe default values or raise explicit informative exceptions."
            ),
            "example": "if val is None:\n    return default_value\n# or\nif obj is None:\n    raise ValueError('Target object cannot be None')"
        },
        {
            "id": "off_by_one_bounds",
            "title": "Off-by-One and Index Slice Boundaries",
            "tags": ["index", "slice", "boundary", "off-by-one", "range", "length", "indexerror"],
            "strategy": (
                "Verify whether line numbers, pagination offsets, or slice bounds are 0-indexed or 1-indexed. "
                "Ensure range(len(items)) does not exceed list boundaries."
            ),
            "example": "# 1-indexed to 0-indexed conversion:\nadjusted_index = max(0, requested_line - 1)"
        },
        {
            "id": "type_coercion_validation",
            "title": "Type Coercion and Input Validation",
            "tags": ["typeerror", "valueerror", "int", "str", "float", "conversion", "coercion", "parse"],
            "strategy": (
                "Explicitly validate or safely cast argument types. Handle non-numeric strings or "
                "mismatched datatypes gracefully with try-except ValueError/TypeError."
            ),
            "example": "try:\n    num = int(raw_val) if raw_val is not None else 0\nexcept (ValueError, TypeError):\n    num = 0"
        },
        {
            "id": "exception_handling_propagation",
            "title": "Exception Chaining and Clean Propagation",
            "tags": ["exception", "raise", "catch", "reraise", "traceback", "propagation"],
            "strategy": (
                "Do not swallow exceptions silently with bare `except: pass`. "
                "Re-raise or chain using `raise DomainError(...) from err` to preserve tracebacks."
            ),
            "example": "except TargetError as exc:\n    logger.error('Failed: %s', exc)\n    raise SubsystemError(f'Operation failed: {exc}') from exc"
        },
        {
            "id": "zero_division_guard",
            "title": "Zero Division and Empty Collection Guard",
            "tags": ["zerodivisionerror", "division", "zero", "empty", "percentage", "average"],
            "strategy": (
                "Check that denominators or collection sizes are greater than zero before computing ratios, averages, or percentages."
            ),
            "example": "average = (total / count) if count > 0 else 0.0"
        },
        {
            "id": "dict_key_lookup",
            "title": "Safe Dictionary Key Retrieval",
            "tags": ["keyerror", "dictionary", "dict", "lookup", "missing_key", "get"],
            "strategy": (
                "Use dict.get(key, default) or explicit `if key in dict:` checks instead of direct indexing to prevent KeyError on dynamic keys."
            ),
            "example": "val = config.get('timeout', 30)"
        },
        {
            "id": "resource_leak_context",
            "title": "Context Managers for Resource Cleanup",
            "tags": ["file", "socket", "lock", "leak", "cleanup", "contextmanager", "with"],
            "strategy": (
                "Always wrap file descriptors, network connections, and concurrency locks in `with` statements to guarantee cleanup on exceptions."
            ),
            "example": "with open(path, 'r', encoding='utf-8') as f:\n    content = f.read()"
        },
        {
            "id": "regex_escaping",
            "title": "Dynamic Regex Metacharacter Escaping",
            "tags": ["regex", "re", "pattern", "metacharacter", "escape", "re.error"],
            "strategy": (
                "When building regular expressions from arbitrary user input, use `re.escape(pattern)` to prevent special character syntax errors."
            ),
            "example": "escaped = re.escape(user_query)\npattern = re.compile(rf'\\b{escaped}\\b')"
        },
        {
            "id": "async_concurrency_lock",
            "title": "Asyncio Concurrency and Event Loop Safety",
            "tags": ["async", "await", "asyncio", "deadlock", "blocking", "coroutine", "event_loop"],
            "strategy": (
                "Never call blocking synchronous I/O or time.sleep() directly inside async routines. "
                "Use asyncio.sleep() or asyncio.to_thread() to prevent event loop starvation."
            ),
            "example": "await asyncio.sleep(0.1)\n# or\nresult = await asyncio.to_thread(blocking_func, arg)"
        },
    ]

    @classmethod
    def lookup(cls, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Return top_k matching bug patterns based on keyword overlap."""
        tokens = set(re.findall(r"\b\w{2,}\b", query.lower())) - RelevantSectionExtractor.STOPWORDS
        scored = []
        for pat in cls.PATTERNS:
            score = 0
            # Tag match
            for tag in pat["tags"]:
                if tag in tokens:
                    score += 3
                elif tag in query.lower():
                    score += 2
            # Title match
            title_words = set(re.findall(r"\b\w{2,}\b", pat["title"].lower()))
            score += len(tokens & title_words) * 2
            if score > 0:
                scored.append((score, pat))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            # Fallback to general patterns if no specific match
            return cls.PATTERNS[:top_k]

        return [item[1] for item in scored[:top_k]]


class SkillRetriever:
    """External Skill Retriever (Layer 6) with cache-first resolution."""

    def __init__(
        self,
        config: ExternalSkillsConfig | None = None,
        telemetry: TelemetryWriter | None = None,
        cache_dir: str = ".harness/skill_cache",
    ):
        self.config = config or ExternalSkillsConfig()
        self.telemetry = telemetry
        self.cache = SkillCache(cache_dir=cache_dir, ttl_hours=self.config.cache_ttl_hours)
        self.trajectory_index = SWEBenchTrajectoryIndex()

    def fetch_skill(
        self,
        source_type: str,
        query: str,
        max_tokens: int = 400,
        step: int = 0,
    ) -> str:
        """Fetch external skill with cache-first lookup and 24h TTL.
        
        Returns snippet within token budget.
        """
        start_time = time.time()
        cache_key = self.cache.compute_key(source_type, query)
        cached = self.cache.get(cache_key)

        if cached is not None:
            latency_ms = int((time.time() - start_time) * 1000)
            if self.telemetry:
                self.telemetry.append(
                    TelemetryEvent(
                        step=step,
                        event_type=EventType.SKILL_FETCH,
                        phase=AgentPhase.ACT,
                        tool="fetch_external_skill",
                        tool_args_hash=cache_key[:8],
                        reasoning=f"SKILL_CACHE_HIT for {source_type}:{query}",
                        latency_ms=latency_ms,
                        result_status=ResultStatus.SUCCESS,
                    )
                )
            return cached.content

        # Cache miss: fetch from source
        raw_content = self._fetch_from_source(source_type, query)
        relevant = RelevantSectionExtractor.extract_relevant(
            raw_content, query, max_tokens=max_tokens
        )

        # Store in cache
        entry = self.cache.set(source_type, query, relevant)
        latency_ms = int((time.time() - start_time) * 1000)

        if self.telemetry:
            self.telemetry.append(
                TelemetryEvent(
                    step=step,
                    event_type=EventType.SKILL_FETCH,
                    phase=AgentPhase.ACT,
                    tool="fetch_external_skill",
                    tool_args_hash=cache_key[:8],
                    reasoning=f"SKILL_CACHE_MISS for {source_type}:{query}",
                    latency_ms=latency_ms,
                    result_status=ResultStatus.SUCCESS,
                )
            )

        return entry.content

    def _fetch_from_source(self, source_type: str, query: str) -> str:
        """Fetch raw content depending on source type."""
        source_lower = source_type.strip().lower()

        if source_lower in ("swe_bench", "swebench", "trajectory"):
            matches = self.trajectory_index.lookup(query, top_k=3)
            lines = ["# SWE-bench Similar Trajectories & Fix Blueprints:"]
            for m in matches:
                lines.append(f"## {m['title']}\n**Strategy:** {m['strategy']}\n```python\n{m['example']}\n```")
            return "\n\n".join(lines)

        elif source_lower in ("file", "local"):
            # Query is treated as relative or absolute file path
            file_path = Path(query)
            if file_path.exists() and file_path.is_file():
                try:
                    return file_path.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    return f"Error reading file {query}: {e}"
            return f"File not found: {query}"

        elif source_lower in ("github", "repo"):
            return (
                f"# GitHub Reference Knowledge for '{query}':\n"
                "- Verify all imported symbols against current module __all__ or exports.\n"
                "- Match function signatures precisely with upstream definitions.\n"
                "- Ensure compatibility across minor version deprecations.\n"
            )

        elif source_lower in ("docs", "documentation"):
            return (
                f"# Standard Documentation Reference for '{query}':\n"
                "- Check function preconditions, expected input types, and return value invariants.\n"
                "- Verify parameter order and default values.\n"
                "- Check raised exceptions on boundary conditions.\n"
            )

        return f"External skill information for '{query}' ({source_type})."

    def prefetch_at_startup(
        self,
        repo_path: str,
        issue_plan: IssuePlan | None = None,
    ) -> Dict[str, str]:
        """Pre-fetch README, CONTRIBUTING, CI, test configs, and trajectories into cache."""
        repo_root = Path(repo_path).resolve()
        prefetched: Dict[str, str] = {}

        # 1. README
        for name in ("README.md", "README.rst", "README.txt", "README"):
            readme_path = repo_root / name
            if readme_path.exists():
                content = self.fetch_skill("file", str(readme_path), max_tokens=500)
                prefetched["README"] = content
                break
        if "README" not in prefetched:
            prefetched["README"] = self.fetch_skill("file", str(repo_root / "README.md"), max_tokens=200)

        # 2. CONTRIBUTING
        for name in ("CONTRIBUTING.md", "CONTRIBUTING.rst", "CONTRIBUTING"):
            contrib_path = repo_root / name
            if contrib_path.exists():
                content = self.fetch_skill("file", str(contrib_path), max_tokens=500)
                prefetched["CONTRIBUTING"] = content
                break
        if "CONTRIBUTING" not in prefetched:
            prefetched["CONTRIBUTING"] = self.fetch_skill("file", str(repo_root / "CONTRIBUTING.md"), max_tokens=200)

        # 3. CI Config
        ci_found = False
        ci_dirs = [repo_root / ".github" / "workflows", repo_root / ".circleci"]
        for cdir in ci_dirs:
            if cdir.exists() and cdir.is_dir():
                for yml in list(cdir.glob("*.yml")) + list(cdir.glob("*.yaml")):
                    content = self.fetch_skill("file", str(yml), max_tokens=400)
                    prefetched["CI_CONFIG"] = content
                    ci_found = True
                    break
            if ci_found:
                break
        if not ci_found:
            for makefile in (repo_root / "Makefile", repo_root / "tox.ini"):
                if makefile.exists():
                    content = self.fetch_skill("file", str(makefile), max_tokens=400)
                    prefetched["CI_CONFIG"] = content
                    ci_found = True
                    break
        if "CI_CONFIG" not in prefetched:
            prefetched["CI_CONFIG"] = self.fetch_skill("file", str(repo_root / ".github/workflows/ci.yml"), max_tokens=200)

        # 4. Test Config
        for tcfg in ("pytest.ini", "pyproject.toml", "setup.cfg", "jest.config.js"):
            cfg_path = repo_root / tcfg
            if cfg_path.exists():
                content = self.fetch_skill("file", str(cfg_path), max_tokens=400)
                prefetched["TEST_CONFIG"] = content
                break
        if "TEST_CONFIG" not in prefetched:
            prefetched["TEST_CONFIG"] = self.fetch_skill("file", str(repo_root / "pytest.ini"), max_tokens=200)

        # 5. Similar SWE-bench trajectories if issue_plan is provided
        if issue_plan:
            query_parts = [issue_plan.primary_goal]
            if issue_plan.reproduction_hint:
                query_parts.append(issue_plan.reproduction_hint)
            if issue_plan.error_type:
                query_parts.append(issue_plan.error_type)
            query = " ".join(query_parts)
            traj = self.fetch_skill("swe_bench", query, max_tokens=500)
            prefetched["SWE_BENCH_TRAJECTORY"] = traj

        logger.info("SkillRetriever pre-fetched %d startup assets into cache.", len(prefetched))
        return prefetched
