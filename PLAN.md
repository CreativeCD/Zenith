# Architectural Plan: Claude Code-Grade Workflow & Skills System for Zenith

**Goal**: Transform Zenith (`zicode` / `zencode`) from a basic conversational shell into a production-grade autonomous CLI coding harness matching Claude Code and modern AI coding agents:
1. **Context Window & Memory Architecture**: Strict 5-section prompt schema, token budgeting, sliding window, observation masking, and rolling working memory summarization.
2. **Systematic Issue & Bug Discovery ("Find Issues / Bugs")**: Deep codebase inspection across issues (`issue.txt`, `issues/*.md`), test runner failures, syntax/linter errors, and uncommitted git diffs.
3. **Claude Code-Style Multi-Turn Planning & Execution**: Explicit task planning (`1. Investigate`, `2. Patch`, `3. Verify`), live step progress, autonomous iteration, and zero self-looping.
4. **Skills System (Custom & Internet Skills)**: Native discovery of skills in `~/.zenith/skills/`, `.zenith/skills/`, and `.agents/skills/`, interactive `/skills` command, `/skills install <url_or_path>`, and `fetch_external_skill` integration.

---

## 1. System Components to Build / Upgrade

### Component 1: `harness/skills/manager.py` (Skills Engine)
- Discovers user-installed skills in:
  - Global: `~/.zenith/skills/<skill_name>/SKILL.md`
  - Workspace: `.zenith/skills/<skill_name>/SKILL.md` or `.agents/skills/<skill_name>/SKILL.md`
- Parses `SKILL.md` with YAML frontmatter (`name`, `description`) and markdown body.
- Installs skills from GitHub repos, raw URLs, or local directories (`/skills install <source>`).
- Provides prompt injection format so the agent knows what skills are available and their trigger conditions.
- Tool integration: Exposes `fetch_external_skill` and `get_skill` to `ToolEngine`.

### Component 2: `harness/interactive.py` (REPL Architecture Overhaul)
- Integrates `ContextManager` (Layer 4) for token-budgeted prompt assembly and rolling memory.
- Integrates `RepoIndexBuilder` (Layer 3) to provide immediate codebase awareness (file tree, language detection, test frameworks).
- Integrates `SkillManager` and `SkillRetriever` (Layer 6) into the interactive session.
- Upgrades `/debug` and natural language queries ("find issues", "find bugs", "fix errors") to run **Autonomous Diagnostic Engine**:
  1. Check for issue files (`issue.txt`, `issues/*.md`, `issues/*.txt`).
  2. Run test discovery (`pytest`, `npm test`, `go test`, `python -m unittest`).
  3. Run syntax audit (`py_compile` on modified/key files).
  4. Inspect git status and uncommitted changes.
  5. Formulate a multi-step plan and display it to the user.
  6. Execute the plan step-by-step with live progress (`Step 1/3: Reading tasks.py`, etc.).
  7. Run verification gate and summarize the solution cleanly.
- Adds built-in commands:
  - `/plan`: Generate an explicit multi-step plan before execution.
  - `/skills`: List all installed skills, view skill details, or install new skills.
  - `/context`: Show current context window token breakdown and active working memory.

### Component 3: Tool Engine & Memory Coordination
- Ensure `ToolEngine` initializes `SkillRetriever` and `SkillManager` in interactive mode.
- Update `TurnRecord` formatting so tool results are cleanly recorded without polluting or looping context.

---

## 2. Implementation Steps

1. **Implement `harness/skills/manager.py`**:
   - `SkillDefinition` dataclass (`name`, `description`, `instructions`, `path`).
   - `SkillManager` with `discover_skills()`, `get_skill()`, `install_skill()`, and `format_skills_for_prompt()`.
2. **Wire Skills into `ToolEngine` (`harness/tool_engine.py`)**:
   - Connect `SkillRetriever` and `SkillManager`.
   - Add `get_skill` tool to allow the model to read full skill instructions on-demand.
3. **Rebuild `ZenithREPL` in `harness/interactive.py`**:
   - Initialize `ContextManager`, `RepoIndexBuilder`, `SkillManager`, `VerificationGate`.
   - Build 5-section context window assembler.
   - Implement `autonomous_issue_scanner()` for "find issues / bugs".
   - Implement step-by-step planning and execution loop with clean visual feedback.
4. **Unit & Integration Testing**:
   - `tests/test_skills.py`: Discovery, parsing, installation, and prompt formatting.
   - `tests/test_interactive.py`: Context window assembly, issue scanner, and command handling.
   - Run full 227+ test suite.
5. **Real-world Verification in Evaluation Workspace**:
   - Test `zicode` in `ai-harness-eval-repo` with "find the issues and bugs".
   - Verify it detects `issues/ISSUE_01_easy.md`, plans the fix, edits the file, and runs tests cleanly.
