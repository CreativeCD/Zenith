"""harness/issue_parser.py — Layer 1: Issue Parsing & Semantic Planning Engine.

Reference: PRD.md §4.1 | architecture.md §7.1
Transforms raw GitHub issue descriptions into machine-actionable IssuePlan dataclasses
using a two-pass extraction strategy (0-token rule-based Pass 1, LLM fallback Pass 2)
with complexity scoring and task-adaptive agent routing.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from harness.adapters.base import ModelAdapter
from harness.config import HarnessConfig
from harness.contracts import (
    AgentMode,
    Complexity,
    IssuePlan,
    SuspectedFile,
    TaskType,
)


# Exception names common in Python, JS, Java, and systems programming
EXCEPTION_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z0-9_]*(?:Exception|Error|Fault|Failure|Crash))\b"
    r"|(\bNullPointerException\b|\bKeyError\b|\bValueError\b|\bTypeError\b|\bAttributeError\b|\bIndexError\b|\bAssertionError\b)"
)

# Common test names in Python, JS/TS, Go, Rust
TEST_PATTERN = re.compile(
    r"\b(test_[a-zA-Z0-9_]+|[a-zA-Z0-9_]+_test|\bTest[A-Z][a-zA-Z0-9_]+)\b"
)

# File paths in source repositories
FILE_PATH_PATTERN = re.compile(
    r"\b(?:[a-zA-Z0-9_\-\.]+/)+[a-zA-Z0-9_\-\.]+\.(?:py|js|jsx|ts|tsx|go|rs|java|cpp|c|h)\b"
)

# Python traceback file lines
TRACEBACK_FILE_LINE_PATTERN = re.compile(
    r'File\s+"(?P<path>[^"]+)",\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<symbol>[a-zA-Z0-9_]+))?'
)

# External knowledge indicators (RFC, specs, PEP, protocols, CVEs)
EXTERNAL_KNOWLEDGE_PATTERN = re.compile(
    r"\b(RFC\s*\d+|PEP\s*\d+|CVE-\d+-\d+|standard|specification|protocol|external\s+api)\b",
    re.IGNORECASE,
)


def calculate_complexity(
    suspected_files_count: int,
    traceback_depth: int,
    requires_external_knowledge: bool,
    cross_module: bool,
    task_type: TaskType,
) -> tuple[float, Complexity]:
    """Calculate task complexity score and tier based on PRD §4.1.3 formula."""
    score = (
        (suspected_files_count * 2.0)
        + (traceback_depth * 1.5)
        + (3.0 if requires_external_knowledge else 0.0)
        + (2.0 if cross_module else 0.0)
        + (4.0 if task_type == TaskType.FEATURE else 0.0)
    )

    if score <= 4.0:
        complexity = Complexity.LOW
    elif score <= 9.0:
        complexity = Complexity.MEDIUM
    elif score <= 16.0:
        complexity = Complexity.HIGH
    else:
        complexity = Complexity.VERY_HIGH

    return score, complexity


def route_complexity(complexity: Complexity) -> dict[str, Any]:
    """Map complexity tier to agent mode, max steps, and subagent configuration (PRD §4.1.3)."""
    if complexity == Complexity.LOW:
        return {
            "agent_mode": AgentMode.SINGLE_REACT,
            "max_steps": 15,
            "estimated_steps": 12,
            "subagents": [],
        }
    elif complexity == Complexity.MEDIUM:
        return {
            "agent_mode": AgentMode.PLANNER_EXECUTOR,
            "max_steps": 25,
            "estimated_steps": 20,
            "subagents": ["scout", "coder"],
        }
    elif complexity == Complexity.HIGH:
        return {
            "agent_mode": AgentMode.MULTI_AGENT,
            "max_steps": 40,
            "estimated_steps": 30,
            "subagents": ["scout", "architect", "coder", "critic"],
        }
    else:  # VERY_HIGH
        return {
            "agent_mode": AgentMode.MULTI_AGENT_DEEP,
            "max_steps": 55,
            "estimated_steps": 45,
            "subagents": ["scout", "architect", "coder", "critic"],
        }


class IssueParser:
    """Two-pass issue parsing engine with rule-based heuristics and LLM fallback."""

    def __init__(
        self,
        config: HarnessConfig | None = None,
        model_adapter: ModelAdapter | None = None,
    ) -> None:
        self.config = config
        self.model_adapter = model_adapter

    def parse_issue(self, issue_input: str, repo_path: str = ".") -> IssuePlan:
        """Synchronously parse an issue text or issue file path."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(
                        asyncio.run,
                        self.parse_issue_async(issue_input, repo_path)
                    ).result()
            else:
                return asyncio.run(self.parse_issue_async(issue_input, repo_path))
        except Exception:
            return asyncio.run(self.parse_issue_async(issue_input, repo_path))

    async def parse_issue_async(self, issue_input: str, repo_path: str = ".") -> IssuePlan:
        """Asynchronously parse an issue text or file with Pass 1 rules and Pass 2 LLM."""
        raw_text = issue_input
        # Check if input is an existing file path
        if os.path.exists(issue_input) and os.path.isfile(issue_input):
            try:
                raw_text = Path(issue_input).read_text(encoding="utf-8")
            except Exception:
                raw_text = issue_input

        # ─── Pass 1: Rule-Based Extraction (0 LLM Tokens) ─────────────────
        suspected_files: list[SuspectedFile] = []
        seen_paths: set[str] = set()

        # 1. Traceback file lines
        traceback_matches = list(TRACEBACK_FILE_LINE_PATTERN.finditer(raw_text))
        traceback_depth = len(traceback_matches)

        for match in traceback_matches:
            path_str = match.group("path")
            symbol_str = match.group("symbol")
            clean_path = path_str.strip()
            # Normalize repo-relative path if absolute
            if os.path.isabs(clean_path):
                try:
                    clean_path = os.path.relpath(clean_path, repo_path)
                except ValueError:
                    pass

            if clean_path not in seen_paths and not clean_path.startswith("<"):
                seen_paths.add(clean_path)
                exists = (Path(repo_path) / clean_path).exists()
                suspected_files.append(
                    SuspectedFile(
                        path=clean_path,
                        confidence=0.95 if exists else 0.90,
                        reason=f"File line in traceback: {match.group(0)}",
                        suspected_symbol=symbol_str,
                    )
                )

        # 2. General file mentions in text
        for file_match in FILE_PATH_PATTERN.finditer(raw_text):
            p = file_match.group(0)
            if p not in seen_paths:
                exists = (Path(repo_path) / p).exists()
                if exists or "/" in p:
                    seen_paths.add(p)
                    suspected_files.append(
                        SuspectedFile(
                            path=p,
                            confidence=0.92 if exists else 0.85,
                            reason="Referenced in issue description",
                        )
                    )

        # 3. Error type extraction
        error_type: str | None = None
        error_conf = 0.50
        error_match = EXCEPTION_PATTERN.search(raw_text)
        if error_match:
            error_type = error_match.group(1) or error_match.group(2)
            error_conf = 0.92

        # 4. Reproduction hint extraction
        repro_hint = ""
        repro_conf = 0.50
        repro_search = re.search(
            r"(?:Steps to reproduce|To reproduce|Reproduction|Run):\s*\n*(.*?)(?:\n\n|\Z)",
            raw_text,
            re.IGNORECASE | re.DOTALL,
        )
        if repro_search:
            repro_hint = repro_search.group(1).strip()
            repro_conf = 0.95
        else:
            # Fallback: look for pytest/python commands
            cmd_match = re.search(r"(pytest\s+[^\n]+|python\s+[^\n]+)", raw_text)
            if cmd_match:
                repro_hint = cmd_match.group(1).strip()
                repro_conf = 0.85
            elif traceback_depth > 0:
                repro_hint = "Execute test or script triggering the traceback."
                repro_conf = 0.75

        # 5. Test filter extraction
        test_filter = ""
        test_conf = 0.50
        # Check command in text first (e.g. pytest tests/test_foo.py -k test_bar)
        test_cmd_match = re.search(r"pytest\s+([^\n`]+)", raw_text)
        if test_cmd_match:
            clean_cmd = test_cmd_match.group(1).strip().strip("`'\"")
            test_filter = f"pytest {clean_cmd}"
            test_conf = 0.90
        else:
            test_matches = TEST_PATTERN.findall(raw_text)
            if test_matches:
                # Pick the first test function or test file
                chosen_test = test_matches[0]
                test_filter = f"pytest -k {chosen_test}"
                test_conf = 0.85

        # 6. Task type extraction
        task_type = TaskType.BUG_FIX
        task_conf = 0.80
        text_lower = raw_text.lower()
        if any(w in text_lower for w in ["add feature", "implement new", "feature request", "support for", "add support"]):
            task_type = TaskType.FEATURE
            task_conf = 0.90
        elif any(w in text_lower for w in ["refactor", "cleanup", "reorganize"]):
            task_type = TaskType.REFACTOR
            task_conf = 0.88
        elif any(w in text_lower for w in ["add unit test", "flaky test", "test coverage"]):
            task_type = TaskType.TEST
            task_conf = 0.85
        elif any(w in text_lower for w in ["docstring", "documentation", "typo in doc", "readme"]):
            task_type = TaskType.DOCS
            task_conf = 0.88
        elif any(w in text_lower for w in ["slow", "latency", "performance", "optimize"]):
            task_type = TaskType.PERF
            task_conf = 0.85

        # 7. Primary goal & Acceptance criteria
        lines = [line_item.strip() for line_item in raw_text.splitlines() if line_item.strip()]
        first_line = lines[0] if lines else "Resolve issue"
        if first_line.lower().startswith("title:"):
            primary_goal = first_line[6:].strip()
        else:
            primary_goal = first_line

        acceptance_criteria: list[str] = []
        criteria_search = re.search(
            r"(?:Acceptance criteria|Expected behavior|Expected):\s*\n*(.*?)(?:\n\n|\Z)",
            raw_text,
            re.IGNORECASE | re.DOTALL,
        )
        if criteria_search:
            for item in criteria_search.group(1).splitlines():
                clean_item = re.sub(r"^[-*•\d\.]+\s*", "", item).strip()
                if clean_item:
                    acceptance_criteria.append(clean_item)

        if not acceptance_criteria:
            if error_type:
                acceptance_criteria.append(f"Fix error condition: {error_type}")
            else:
                acceptance_criteria.append(primary_goal)
            if test_filter:
                acceptance_criteria.append(f"Ensure test passes: {test_filter}")
            acceptance_criteria.append("No regressions introduced in test suite")

        # 8. Language & Test Runner
        language = "python"
        test_runner = "pytest"
        if any(f.path.endswith((".js", ".jsx", ".ts", ".tsx")) for f in suspected_files):
            language = "typescript" if any(f.path.endswith((".ts", ".tsx")) for f in suspected_files) else "javascript"
            test_runner = "jest"
        elif any(f.path.endswith(".go") for f in suspected_files):
            language = "go"
            test_runner = "go test"
        elif any(f.path.endswith(".rs") for f in suspected_files):
            language = "rust"
            test_runner = "cargo test"

        requires_ext = bool(EXTERNAL_KNOWLEDGE_PATTERN.search(raw_text))

        # Overall parsing confidence
        weights = [
            0.95 if suspected_files else 0.50,
            repro_conf,
            error_conf,
            test_conf,
            task_conf,
        ]
        parsing_confidence = round(sum(weights) / len(weights), 2)
        parsing_method = "RULE_BASED"

        # ─── Pass 2: LLM Fallback (Triggered only if confidence < 0.75) ─────
        if (parsing_confidence < 0.75 or not suspected_files) and self.model_adapter:
            try:
                extraction_prompt = (
                    "Extract the following fields from this GitHub issue in JSON format:\n"
                    "- primary_goal (one sentence string)\n"
                    "- task_type (BUG_FIX | FEATURE | REFACTOR | TEST | DOCS | PERF)\n"
                    "- error_type (exception name or null)\n"
                    "- suspected_files (list of file paths)\n"
                    "- reproduction_hint (string)\n"
                    "- test_filter (test command or string)\n\n"
                    f"Issue text:\n{raw_text[:2000]}"
                )
                import inspect
                call_kwargs: dict[str, Any] = {
                    "system_prompt": "You are an expert software engineering issue parser. Output valid JSON only.",
                    "user_message": extraction_prompt,
                    "temperature": 0.0,
                    "max_output_tokens": 500,
                }
                sig = inspect.signature(self.model_adapter.complete)
                accepts_var = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                if "reasoning_effort" in sig.parameters or accepts_var:
                    call_kwargs["reasoning_effort"] = "medium"
                if not accepts_var:
                    call_kwargs = {k: v for k, v in call_kwargs.items() if k in sig.parameters}
                response = await self.model_adapter.complete(**call_kwargs)
                if response.content:
                    # Clean up JSON if wrapped in markdown code blocks
                    content_clean = re.sub(r"^```(?:json)?\s*", "", response.content.strip())
                    content_clean = re.sub(r"\s*```$", "", content_clean)
                    parsed_llm = json.loads(content_clean)

                    if parsed_llm.get("primary_goal"):
                        primary_goal = str(parsed_llm["primary_goal"])
                    if parsed_llm.get("task_type") in TaskType.__members__:
                        task_type = TaskType(parsed_llm["task_type"])
                    if parsed_llm.get("error_type"):
                        error_type = str(parsed_llm["error_type"])
                    if parsed_llm.get("reproduction_hint"):
                        repro_hint = str(parsed_llm["reproduction_hint"])
                    if parsed_llm.get("test_filter"):
                        test_filter = str(parsed_llm["test_filter"])
                    if parsed_llm.get("suspected_files"):
                        for sf_path in parsed_llm["suspected_files"]:
                            if sf_path not in seen_paths:
                                seen_paths.add(sf_path)
                                suspected_files.append(
                                    SuspectedFile(
                                        path=sf_path,
                                        confidence=0.88,
                                        reason="Identified by LLM issue extraction",
                                    )
                                )
                    parsing_confidence = 0.85
                    parsing_method = "LLM_ASSISTED"
            except Exception:
                # LLM failure gracefully keeps rule-based extraction
                pass

        # ─── Complexity & Routing ──────────────────────────────────────────
        source_files = [
            f for f in suspected_files
            if not any(t in f.path.lower() for t in ["test_", "_test", "tests/"])
        ]
        source_count = len(source_files) if source_files else len(suspected_files)
        cross_module = len({Path(f.path).parent for f in source_files}) > 1
        _, complexity = calculate_complexity(
            suspected_files_count=source_count,
            traceback_depth=traceback_depth,
            requires_external_knowledge=requires_ext,
            cross_module=cross_module,
            task_type=task_type,
        )
        routing = route_complexity(complexity)

        issue_id = "issue"
        if os.path.exists(issue_input) and os.path.isfile(issue_input):
            issue_id = Path(issue_input).stem

        return IssuePlan(
            issue_id=issue_id,
            primary_goal=primary_goal,
            task_type=task_type,
            acceptance_criteria=acceptance_criteria,
            suspected_files=suspected_files,
            reproduction_hint=repro_hint,
            test_filter=test_filter,
            error_type=error_type,
            complexity_estimate=complexity,
            estimated_steps=routing["estimated_steps"],
            requires_external_knowledge=requires_ext,
            language=language,
            test_runner=test_runner,
            parsing_confidence=parsing_confidence,
            parsing_method=parsing_method,
        )
