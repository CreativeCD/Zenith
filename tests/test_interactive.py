"""Unit tests for harness/interactive.py."""

import asyncio
from pathlib import Path
import pytest

from harness.config import HarnessConfig
from harness.contracts import IssuePlan
from harness.interactive import ZenithREPL
from harness.skills.manager import SkillDefinition


@pytest.fixture
def dummy_config(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 51):
        monkeypatch.delenv(f"AI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"DEEPSEEK_API_KEY_{i}", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = HarnessConfig()
    config.model.api_keys = []
    config.model.api_key = None
    config.repo_path = str(tmp_path)
    config.telemetry.output_dir = str(tmp_path / ".harness")
    return config


def test_repl_init(dummy_config):
    repl = ZenithREPL(config=dummy_config)
    assert repl.repo_path == str(dummy_config.repo_path)
    assert repl.session_active is True
    assert len(repl.history) == 0
    assert repl.skill_manager is not None
    assert repl.context_manager is not None


def test_repl_casual_greeting(dummy_config, monkeypatch):
    """Greetings now go through execute_autonomous_loop (LLM-driven)."""
    repl = ZenithREPL(config=dummy_config)
    called = []

    async def mock_loop(prompt):
        called.append(prompt)
        repl.history.append({"role": "user", "content": prompt})
        repl.history.append({"role": "model", "content": "Hello! I'm Zenith."})

    monkeypatch.setattr(repl, "execute_autonomous_loop", mock_loop)
    asyncio.run(repl.process_user_message("hi"))
    assert len(called) == 1
    assert called[0] == "hi"
    assert len(repl.history) == 2
    assert repl.history[1]["role"] == "model"


def test_repl_casual_exit(dummy_config):
    repl = ZenithREPL(config=dummy_config)
    asyncio.run(repl.process_user_message("bye"))
    assert repl.session_active is False


def test_profile_repository(dummy_config, tmp_path):
    repl = ZenithREPL(config=dummy_config)
    # 1. Initially empty directory
    profile = repl.profile_repository()
    assert profile["stack"] == "General"

    # 2. Add README and package manifest
    readme = tmp_path / "README.md"
    readme.write_text("# My Awesome Tool\nAn intelligent CLI tool for data processing.", encoding="utf-8")
    pkg = tmp_path / "pyproject.toml"
    pkg.write_text("[project]\nname = 'awesome-tool'", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print('hello')", encoding="utf-8")

    profile2 = repl.profile_repository()
    assert profile2["stack"] == "Python"
    assert profile2["manifest"] == "pyproject.toml"
    assert "My Awesome Tool" in profile2["readme_summary"]
    assert profile2["total_source_files"] >= 1
    assert "src" in profile2["source_dirs"]


def test_discover_issues(dummy_config, tmp_path):
    repl = ZenithREPL(config=dummy_config)

    # Empty initially
    assert repl.discover_issues() == []

    # 1. Single root issue.txt
    issue_txt = tmp_path / "issue.txt"
    issue_txt.write_text("Title: Broken discount calculation\nAcceptance Criteria:\n- Fix it", encoding="utf-8")
    issues = repl.discover_issues()
    assert len(issues) == 1
    assert issues[0][0] == "issue.txt"

    # 2. Issues in directory
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    issue_file = issues_dir / "ISSUE_01_easy.md"
    issue_file.write_text("Title: Zero division bug\nAcceptance Criteria:\n- Return 0", encoding="utf-8")

    issues2 = repl.discover_issues()
    assert len(issues2) == 2


def test_load_issue(dummy_config, tmp_path):
    repl = ZenithREPL(config=dummy_config)
    issue_file = tmp_path / "issue.txt"
    issue_file.write_text(
        "Title: KeyError in calculate_discount\n"
        "## Description\nMissing tier raises KeyError\n"
        "## Acceptance Criteria\n1. Return 0.0 on missing tier\n",
        encoding="utf-8",
    )

    plan = repl.load_issue(issue_file)
    assert isinstance(plan, IssuePlan)
    assert repl.active_issue is not None
    assert "KeyError" in plan.primary_goal or "calculate_discount" in plan.primary_goal
    assert repl.context_manager.issue_plan is not None


def test_formulate_and_render_plan(dummy_config):
    repl = ZenithREPL(config=dummy_config)
    plan = repl.formulate_plan(
        goal="Fix calculate_discount KeyError",
        suspected_files=["billing/discounts.py"],
        has_test_failure=True,
    )
    assert len(plan) == 4
    assert plan[0]["step"] == 1
    assert "billing/discounts.py" in plan[0]["desc"]
    assert plan[3]["desc"].startswith("Run test suite")
    # Check render does not throw
    repl.render_plan(plan)


def test_skills_listing_and_details(dummy_config, tmp_path):
    repl = ZenithREPL(config=dummy_config)

    # Mock discovered skills
    fake_skill = SkillDefinition(
        name="test-skill",
        description="A test skill for unit tests.",
        instructions="# Test Skill Instructions\nFollow these steps.",
        path=tmp_path / "test-skill" / "SKILL.md",
        source_type="global",
    )
    repl.skill_manager._skills_cache = {"test-skill": fake_skill}
    repl.skill_manager.discover_skills = lambda: {"test-skill": fake_skill}

    # Test display doesn't raise
    repl.show_skills()
    repl.show_skill_details("test-skill")
    repl.show_skill_details("non-existent")


def test_context_display(dummy_config):
    repl = ZenithREPL(config=dummy_config)
    repl.context_manager.update_working_memory(
        file_examined=("test.py", "Found syntax bug"),
        edit_applied="Patched test.py line 12",
        test_status="All tests passing",
    )
    # Test show_context does not raise
    repl.show_context()


def test_natural_language_audit_routing(dummy_config, monkeypatch):
    """Broad audit keywords still route to autonomous_investigation."""
    repl = ZenithREPL(config=dummy_config)
    called = []

    async def mock_investigation(query=""):
        called.append(query)

    monkeypatch.setattr(repl, "autonomous_investigation", mock_investigation)

    # These still trigger autonomous_investigation via audit_triggers
    queries = [
        "scan project",
        "audit repo",
        "deep dive",
        "diagnose",
    ]

    for q in queries:
        asyncio.run(repl.process_user_message(q))

    assert len(called) == len(queries)


def test_natural_language_skills_routing(dummy_config, monkeypatch):
    repl = ZenithREPL(config=dummy_config)
    show_called = []
    install_called = []

    monkeypatch.setattr(repl, "show_skills", lambda: show_called.append(True))
    monkeypatch.setattr(repl, "install_skill_interactive", lambda src: install_called.append(src))

    asyncio.run(repl.process_user_message("list skills"))
    assert len(show_called) == 1

    asyncio.run(repl.process_user_message("install skill https://github.com/example/skill"))
    assert len(install_called) == 1
    assert install_called[0] == "https://github.com/example/skill"


def test_repl_auto_debug_alias(dummy_config, monkeypatch):
    repl = ZenithREPL(config=dummy_config)
    called = []

    async def mock_investigation(query=""):
        called.append(True)

    monkeypatch.setattr(repl, "autonomous_investigation", mock_investigation)
    asyncio.run(repl.auto_debug())
    assert len(called) == 1


def test_is_conversational_or_informational(dummy_config):
    repl = ZenithREPL(config=dummy_config)

    # Informational and conversational queries
    assert repl._is_conversational_or_informational("what is ur name") is True
    assert repl._is_conversational_or_informational("what is your name") is True
    assert repl._is_conversational_or_informational("what is this flolder name") is True
    assert repl._is_conversational_or_informational("what is this folder name") is True
    assert repl._is_conversational_or_informational("what repo is this") is True
    assert repl._is_conversational_or_informational("who are you") is True
    assert repl._is_conversational_or_informational("what are you doing") is True
    assert repl._is_conversational_or_informational("hi") is True
    assert repl._is_conversational_or_informational("hello") is True
    assert repl._is_conversational_or_informational("thank you") is True

    # Engineering / action tasks should NOT be conversational
    assert repl._is_conversational_or_informational("fix the bug in priority.py") is False
    assert repl._is_conversational_or_informational("find issues in the repo") is False
    assert repl._is_conversational_or_informational("run test suite") is False
    assert repl._is_conversational_or_informational("patch broken calculation") is False


def test_all_messages_go_through_llm(dummy_config, monkeypatch):
    """Verify arbitrary messages (greetings, questions, tasks) all hit execute_autonomous_loop."""
    repl = ZenithREPL(config=dummy_config)
    called = []

    async def mock_loop(prompt):
        called.append(prompt)

    monkeypatch.setattr(repl, "execute_autonomous_loop", mock_loop)

    # All of these should go through the LLM, not hardcoded handlers
    messages = [
        "what is ur name",
        "hi",
        "hello",
        "what are you doing",
        "fix the bug in calc.py",
        "create a new feature for user profiles",
        "what is this folder name",
        "improve the login performance",
        "find bugs in the code",
    ]
    for msg in messages:
        asyncio.run(repl.process_user_message(msg))

    assert len(called) == len(messages)


def test_show_and_select_issues(dummy_config, tmp_path):
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    i1 = issues_dir / "ISSUE_01_easy.md"
    i1.write_text("# [Bug] Sorting tasks\n## Acceptance criteria\nSort high first", encoding="utf-8")
    i2 = issues_dir / "ISSUE_02_medium.md"
    i2.write_text("# [Bug] Active tasks completion\n## Acceptance criteria\nFilter active", encoding="utf-8")
    i3 = issues_dir / "ISSUE_03_hard.md"
    i3.write_text("# [Bug] Saving tasks clobbers categories\n## Acceptance criteria\nDo not clobber", encoding="utf-8")

    repl = ZenithREPL(config=dummy_config)
    repl.show_issues()

    # Select by 1-based index
    matched3 = repl.select_issue("3")
    assert matched3 is not None
    assert matched3[0] == "issues/ISSUE_03_hard.md"
    assert repl.active_issue is not None
    assert "clobbers" in repl.active_issue.primary_goal or "Saving tasks" in repl.active_issue.primary_goal

    # Select by keyword
    matched2 = repl.select_issue("medium")
    assert matched2 is not None
    assert matched2[0] == "issues/ISSUE_02_medium.md"

    # Select by name
    matched1 = repl.select_issue("ISSUE_01_easy.md")
    assert matched1 is not None
    assert matched1[0] == "issues/ISSUE_01_easy.md"


def test_match_issue_query(dummy_config, tmp_path):
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    (issues_dir / "ISSUE_01_easy.md").write_text("# Easy bug", encoding="utf-8")
    (issues_dir / "ISSUE_02_medium.md").write_text("# Medium bug", encoding="utf-8")
    (issues_dir / "ISSUE_03_hard.md").write_text("# Hard bug", encoding="utf-8")

    repl = ZenithREPL(config=dummy_config)

    assert repl._match_issue("solve issue 3")[0] == "issues/ISSUE_03_hard.md"
    assert repl._match_issue("fix issue #2")[0] == "issues/ISSUE_02_medium.md"
    assert repl._match_issue("issue 1")[0] == "issues/ISSUE_01_easy.md"
    assert repl._match_issue("solve hard issue")[0] == "issues/ISSUE_03_hard.md"
    assert repl._match_issue("fix easy issue")[0] == "issues/ISSUE_01_easy.md"
    assert repl._match_issue("random chat without issue") is None


def test_repl_init_with_issue_path(dummy_config, tmp_path):
    issue_file = tmp_path / "custom_issue.md"
    issue_file.write_text("# Custom bug\nGoal: fix everything", encoding="utf-8")

    dummy_config.issue_path = str(issue_file)
    repl = ZenithREPL(config=dummy_config)

    assert repl.active_issue is not None
    assert repl.active_issue_path == issue_file


def test_welcome_banner_with_issues(dummy_config, tmp_path):
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    (issues_dir / "ISSUE_01_easy.md").write_text("# Easy bug", encoding="utf-8")
    (issues_dir / "ISSUE_02_medium.md").write_text("# Medium bug", encoding="utf-8")

    repl = ZenithREPL(config=dummy_config)
    repl.print_welcome_banner()


