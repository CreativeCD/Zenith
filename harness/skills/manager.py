"""harness/skills/manager.py — Custom & Internet Skills Engine for Zenith.

Reference: Claude Code / Antigravity Skills specification.
Discovers, loads, installs, and injects agent skills into Zenith's context window.
Supports:
- Global user skills in ~/.zenith/skills/<skill_name>/SKILL.md
- Project-local skills in <repo>/.zenith/skills/ and <repo>/.agents/skills/
- Skill installation from Git repos, local paths, and raw markdown URLs
- Token-efficient prompt serialization for the context manager
"""

from __future__ import annotations

import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import yaml

DEFAULT_GLOBAL_SKILLS_DIR = Path.home() / ".zenith" / "skills"


@dataclass
class SkillDefinition:
    """Represents a discovered skill with instructions and metadata."""
    name: str
    description: str
    instructions: str
    path: Path
    source_type: str = "global"  # "global" or "workspace"

    def to_summary_str(self) -> str:
        """Format 1-line summary for prompt injection."""
        return f"- **`{self.name}`**: {self.description}"


class SkillManager:
    """Manages skill discovery, loading, installation, and prompt formatting."""

    def __init__(
        self,
        repo_root: str | Path = ".",
        global_skills_dir: Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.global_skills_dir = global_skills_dir or DEFAULT_GLOBAL_SKILLS_DIR
        self._skills_cache: Dict[str, SkillDefinition] = {}

    def _parse_skill_file(self, file_path: Path, source_type: str) -> SkillDefinition | None:
        """Parse SKILL.md file extracting frontmatter and body."""
        if not file_path.exists() or not file_path.is_file():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return None

        name = file_path.parent.name
        description = "Custom engineering skill."
        body = content

        # Check for YAML frontmatter between --- and ---
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if fm_match:
            frontmatter_text = fm_match.group(1)
            body = fm_match.group(2).strip()
            try:
                fm_data = yaml.safe_load(frontmatter_text)
                if isinstance(fm_data, dict):
                    name = str(fm_data.get("name", name)).strip()
                    description = str(fm_data.get("description", description)).strip()
            except Exception:
                pass
        else:
            # Extract first heading and paragraph if no frontmatter
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            for line in lines:
                if line.startswith("# "):
                    name = line.replace("# ", "").strip().lower().replace(" ", "-")
                    break
            for line in lines:
                if not line.startswith("#"):
                    description = line[:200]
                    break

        return SkillDefinition(
            name=name,
            description=description,
            instructions=body,
            path=file_path,
            source_type=source_type,
        )

    def discover_skills(self) -> Dict[str, SkillDefinition]:
        """Scan global and workspace directories for skills."""
        discovered: Dict[str, SkillDefinition] = {}

        # 1. Global skills (~/.zenith/skills/<skill_name>/SKILL.md)
        if self.global_skills_dir.exists():
            for skill_dir in self.global_skills_dir.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skill = self._parse_skill_file(skill_file, source_type="global")
                        if skill:
                            discovered[skill.name] = skill

        # 2. Workspace skills (.zenith/skills/ and .agents/skills/)
        workspace_candidates = [
            self.repo_root / ".zenith" / "skills",
            self.repo_root / ".agents" / "skills",
            self.repo_root / "skills",
        ]
        for candidate_dir in workspace_candidates:
            if candidate_dir.exists() and candidate_dir.is_dir():
                for skill_dir in candidate_dir.iterdir():
                    if skill_dir.is_dir():
                        skill_file = skill_dir / "SKILL.md"
                        if skill_file.exists():
                            skill = self._parse_skill_file(skill_file, source_type="workspace")
                            if skill:
                                discovered[skill.name] = skill

        self._skills_cache = discovered
        return discovered

    def get_skill(self, name: str) -> SkillDefinition | None:
        """Retrieve a specific skill by name."""
        if not self._skills_cache:
            self.discover_skills()
        return self._skills_cache.get(name)

    def install_skill(self, source: str, name: Optional[str] = None) -> SkillDefinition:
        """Install a skill from a local folder, git repo URL, or direct URL.
        
        Args:
            source: Local path, git URL, or raw SKILL.md URL.
            name: Optional override name for the skill.
        """
        self.global_skills_dir.mkdir(parents=True, exist_ok=True)
        source_clean = source.strip()

        # Case 1: Local directory path
        local_path = Path(source_clean).resolve()
        if local_path.exists() and local_path.is_dir():
            target_name = name or local_path.name
            target_dir = self.global_skills_dir / target_name
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(local_path, target_dir)
            skill = self._parse_skill_file(target_dir / "SKILL.md", source_type="global")
            if not skill:
                raise ValueError(f"Directory '{source}' does not contain a valid SKILL.md")
            self._skills_cache[skill.name] = skill
            return skill

        # Case 2: Git repository (https://github.com/...)
        if source_clean.startswith(("http://", "https://", "git@")) and source_clean.endswith(".git") or "github.com" in source_clean:
            inferred_name = name or source_clean.rstrip("/").split("/")[-1].replace(".git", "")
            target_dir = self.global_skills_dir / inferred_name
            if target_dir.exists():
                shutil.rmtree(target_dir)
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", source_clean, str(target_dir)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except Exception as e:
                raise RuntimeError(f"Failed to clone skill repository '{source_clean}': {e}")

            skill_file = target_dir / "SKILL.md"
            if not skill_file.exists():
                # Check root directory or README
                readme = target_dir / "README.md"
                if readme.exists():
                    shutil.copyfile(readme, skill_file)
                else:
                    skill_file.write_text(f"---\nname: {inferred_name}\ndescription: Installed skill from {source_clean}\n---\nCustom skill instructions.")

            skill = self._parse_skill_file(skill_file, source_type="global")
            if not skill:
                raise ValueError(f"Failed to parse skill from cloned repo '{source_clean}'")
            self._skills_cache[skill.name] = skill
            return skill

        # Case 3: Raw URL to a SKILL.md file
        if source_clean.startswith(("http://", "https://")):
            inferred_name = name or "custom-skill"
            target_dir = self.global_skills_dir / inferred_name
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file = target_dir / "SKILL.md"
            try:
                req = urllib.request.Request(source_clean, headers={"User-Agent": "Zenith-AI-Harness"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw_bytes = resp.read()
                    target_file.write_bytes(raw_bytes)
            except Exception as e:
                raise RuntimeError(f"Failed to download skill file from '{source_clean}': {e}")

            skill = self._parse_skill_file(target_file, source_type="global")
            if not skill:
                raise ValueError(f"Downloaded file from '{source_clean}' is not a valid SKILL.md")
            self._skills_cache[skill.name] = skill
            return skill

        raise ValueError(f"Invalid skill source '{source}'. Must be a local folder, git URL, or HTTP URL.")

    def format_skills_for_prompt(self, max_tokens: int = 400) -> str:
        """Format concise skills catalog for agent system prompt."""
        skills = self.discover_skills()
        if not skills:
            return ""

        lines = [
            "## Available Installed Skills:",
            "You have access to specialized external skills. When a user's task matches a skill's description, follow its instructions:",
        ]
        for skill in skills.values():
            lines.append(f"- **`{skill.name}`**: {skill.description}")

        lines.append("\nTo load full skill instructions, use tool `get_skill(skill_name)`. You can also use `fetch_external_skill` to retrieve online trajectories or documentation.")
        return "\n".join(lines)
