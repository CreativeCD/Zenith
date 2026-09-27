"""Unit tests for harness/skills/manager.py."""

from pathlib import Path
import pytest

from harness.skills.manager import SkillDefinition, SkillManager


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "global_skills"
    d.mkdir()
    return d


@pytest.fixture
def repo_dir(tmp_path):
    r = tmp_path / "test_repo"
    r.mkdir()
    return r


def test_discover_skills_empty(skills_dir, repo_dir):
    mgr = SkillManager(repo_root=repo_dir, global_skills_dir=skills_dir)
    assert mgr.discover_skills() == {}


def test_discover_global_skill(skills_dir, repo_dir):
    skill_dir = skills_dir / "code-reviewer"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("""---
name: code-reviewer
description: Reviews code changes for security and performance.
---
# Code Review Guidelines
Check for SQL injection, XSS, and unhandled errors.
""")

    mgr = SkillManager(repo_root=repo_dir, global_skills_dir=skills_dir)
    skills = mgr.discover_skills()
    assert "code-reviewer" in skills
    skill = skills["code-reviewer"]
    assert skill.name == "code-reviewer"
    assert skill.description == "Reviews code changes for security and performance."
    assert "Check for SQL injection" in skill.instructions
    assert skill.source_type == "global"


def test_discover_workspace_skill(skills_dir, repo_dir):
    ws_skill_dir = repo_dir / ".zenith" / "skills" / "repo-expert"
    ws_skill_dir.mkdir(parents=True)
    (ws_skill_dir / "SKILL.md").write_text("""---
name: repo-expert
description: Specialized domain knowledge for this specific project.
---
Project specific conventions and architectural patterns.
""")

    mgr = SkillManager(repo_root=repo_dir, global_skills_dir=skills_dir)
    skills = mgr.discover_skills()
    assert "repo-expert" in skills
    assert skills["repo-expert"].source_type == "workspace"


def test_install_skill_from_local_dir(skills_dir, repo_dir, tmp_path):
    src_dir = tmp_path / "my-custom-skill"
    src_dir.mkdir()
    (src_dir / "SKILL.md").write_text("""---
name: my-custom-skill
description: Custom user installed skill.
---
Instructions here.
""")

    mgr = SkillManager(repo_root=repo_dir, global_skills_dir=skills_dir)
    installed = mgr.install_skill(str(src_dir))
    assert installed.name == "my-custom-skill"
    assert (skills_dir / "my-custom-skill" / "SKILL.md").exists()
    assert mgr.get_skill("my-custom-skill") is not None


def test_format_skills_for_prompt(skills_dir, repo_dir):
    skill_dir = skills_dir / "debugger"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("""---
name: debugger
description: Systematic root cause analysis.
---
Debugging steps...
""")

    mgr = SkillManager(repo_root=repo_dir, global_skills_dir=skills_dir)
    prompt_str = mgr.format_skills_for_prompt()
    assert "## Available Installed Skills:" in prompt_str
    assert "**`debugger`**: Systematic root cause analysis." in prompt_str
    assert "get_skill" in prompt_str
