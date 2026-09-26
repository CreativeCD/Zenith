"""Unit and integration tests for Layer 6: SkillRetriever, SkillCache, and Extractor."""

import time

from harness.contracts import IssuePlan, ToolCall
from harness.skill_retriever import (
    RelevantSectionExtractor,
    SWEBenchTrajectoryIndex,
    SkillCache,
    SkillRetriever,
)
from harness.telemetry import TelemetryWriter
from harness.tool_engine import ToolEngine


def test_skill_cache_hit_and_miss(tmp_path):
    cache = SkillCache(cache_dir=str(tmp_path / "cache"), ttl_hours=24)
    key = cache.compute_key("docs", "pytest usage")

    # 1. Miss initially
    assert cache.get(key) is None

    # 2. Set
    entry = cache.set("docs", "pytest usage", "Use pytest -k to filter tests.")
    assert entry.key == key

    # 3. Hit in < 10ms
    start = time.perf_counter()
    cached = cache.get(key)
    latency_ms = (time.perf_counter() - start) * 1000
    assert latency_ms < 10.0
    assert cached is not None
    assert cached.content == "Use pytest -k to filter tests."


def test_skill_cache_ttl_expiry(tmp_path):
    cache = SkillCache(cache_dir=str(tmp_path / "cache"), ttl_hours=1)
    key = cache.compute_key("docs", "expiring query")

    # Set with 0 second TTL (expired immediately)
    cache.set("docs", "expiring query", "Old content", ttl_seconds=0)

    # Immediately expired
    assert cache.get(key) is None


def test_skill_cache_disk_persistence(tmp_path):
    cache_dir = tmp_path / "skill_cache"
    cache1 = SkillCache(cache_dir=str(cache_dir), ttl_hours=24)
    cache1.set("github", "django query", "Django query guide")

    key = cache1.compute_key("github", "django query")
    disk_file = cache_dir / f"{key}.json"
    assert disk_file.exists()

    # Re-instantiate from disk
    cache2 = SkillCache(cache_dir=str(cache_dir), ttl_hours=24)
    retrieved = cache2.get(key)
    assert retrieved is not None
    assert retrieved.content == "Django query guide"


def test_relevant_section_extractor():
    sample_text = """
# Project Introduction
This is an awesome project for machine learning.

# Installation Guide
Run pip install mypkg to install all dependencies.

# Testing Instructions
Run pytest tests/ to execute all unit tests. Ensure python 3.11 is used.

# Troubleshooting
If you hit an ImportError, check your virtualenv.
"""
    # Query for testing
    extracted = RelevantSectionExtractor.extract_relevant(
        raw_content=sample_text,
        query="run tests with pytest",
        max_tokens=100,
    )
    assert "pytest" in extracted
    assert len(extracted) <= 400


def test_swebench_trajectory_index():
    matches = SWEBenchTrajectoryIndex.lookup("AttributeError object has no attribute None", top_k=2)
    assert len(matches) >= 1
    top = matches[0]
    assert "null" in top["id"].lower() or "none" in top["title"].lower() or "strategy" in top


def test_skill_retriever_prefetch_at_startup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# My Project\nAutonomous harness demo.", encoding="utf-8")
    (repo / "CONTRIBUTING.md").write_text("# Contributing\nRun tests before commit.", encoding="utf-8")
    (repo / "pytest.ini").write_text("[pytest]\naddopts = -v", encoding="utf-8")

    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\non: push\njobs: test", encoding="utf-8")

    from harness.contracts import Complexity, TaskType
    issue = IssuePlan(
        issue_id="test-1",
        primary_goal="Fix null pointer exception in auth service",
        task_type=TaskType.BUG_FIX,
        acceptance_criteria=["token is not None"],
        suspected_files=[],
        reproduction_hint="auth token is None causing AttributeError",
        test_filter="test_auth",
        error_type="AttributeError",
        complexity_estimate=Complexity.LOW,
        estimated_steps=4,
        requires_external_knowledge=True,
        language="python",
        test_runner="pytest",
        parsing_confidence=0.95,
        parsing_method="RULE_BASED",
    )

    retriever = SkillRetriever(cache_dir=str(tmp_path / "cache"))
    prefetched = retriever.prefetch_at_startup(repo_path=str(repo), issue_plan=issue)

    assert "README" in prefetched
    assert "CONTRIBUTING" in prefetched
    assert "CI_CONFIG" in prefetched
    assert "TEST_CONFIG" in prefetched
    assert "SWE_BENCH_TRAJECTORY" in prefetched

    # Verify second fetch is cache hit (< 10ms)
    start = time.perf_counter()
    readme_cached = retriever.fetch_skill("file", str(repo / "README.md"))
    assert (time.perf_counter() - start) * 1000 < 10.0
    assert "Autonomous harness demo" in readme_cached


def test_tool_engine_fetch_external_skill_integration(tmp_path):
    writer = TelemetryWriter(output_dir=str(tmp_path / "telemetry"))
    retriever = SkillRetriever(telemetry=writer, cache_dir=str(tmp_path / "cache"))
    engine = ToolEngine(repo_root=str(tmp_path), telemetry=writer, skill_retriever=retriever)

    call = ToolCall(
        tool="fetch_external_skill",
        reasoning="Look up trajectory for division by zero",
        args={
            "source_type": "swe_bench",
            "query": "ZeroDivisionError empty list average",
            "max_tokens": 300,
        },
    )
    result = engine.execute(call)
    assert result.status.value == "SUCCESS"
    assert "division" in result.raw_output.lower() or "guard" in result.raw_output.lower()
