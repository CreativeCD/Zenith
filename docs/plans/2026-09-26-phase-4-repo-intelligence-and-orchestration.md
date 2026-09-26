# Phase 4: Repository Intelligence & Multi-Agent Orchestration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Layer 1 (Issue Parsing & Complexity Routing), Layer 2 (Repository Intelligence Engine & Semantic File Ranker), and Layer 5 (Multi-Agent Orchestrator with ReAct State Machine, Subagent Pool, and Rollback Checkpoints) as specified in `PRD.md` (§4.1, §4.2, §4.5) and `architecture.md` (§7.1, §7.2, §7.5).

---

## User Review Required

> [!IMPORTANT]
> **External Libraries vs. Native Fallbacks for Repo Intelligence:**
> `tree-sitter` and `faiss` / `sentence-transformers` are optional dependencies and not installed in the standard Python environment. To ensure 100% offline reliability, fast test suites (< 5s), and zero network dependencies, `harness/repo_intel.py` will implement:
> 1. Native Python `ast` parsing for Python files + deterministic regex symbol extractors for JS/TS/Go/Rust/Java (already validated in `harness/tools/ast_tools.py`).
> 2. An ultra-fast, zero-dependency BM25/TF-IDF vector ranker for file symbol summaries, with dynamic plugin support for `faiss` and `sentence-transformers` if they are present in the user's environment.
> This matches the PRD §4.2 requirement while guaranteeing seamless execution across all developer environments.

> [!IMPORTANT]
> **Strict Execution Policy:**
> Per workspace rules, the agent will **NEVER execute `git commit` or `git push`**. All working tree modifications and diffs will be staged and managed via git files (`.harness/checkpoint_{N}.diff`), leaving all commits and pushes under manual user control.

---

## Open Questions

None. The contracts in `harness/contracts.py` and requirements in `PRD.md` (§4.1, §4.2, §4.5) and `phases.md` (§Phase 4) are completely specified.

---

## Proposed Changes

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Zenith Phase 4 Architecture Map                      │
└────────────────────────────────────────────────────────────────────────┘

                           [Issue Text / File]
                                    │
                                    ▼
                     ┌─────────────────────────────┐
                     │   harness/issue_parser.py   │  (Layer 1)
                     │  - Pass 1: Rule-Based (0 tok)│
                     │  - Pass 2: LLM Fallback     │
                     │  - Complexity Scoring       │
                     │  - Task-Adaptive Routing    │
                     └──────────────┬──────────────┘
                                    │ IssuePlan
                                    ▼
 ┌───────────────────────────┐      │      ┌───────────────────────────┐
 │   harness/repo_intel.py   │◄─────┼─────►│ harness/subagents/pool.py │
 │ (Layer 2)                 │      │      │ (Layer 5 Subagents)       │
 │ - file_tree.txt           │      │      │ - Scout (8k budget)       │
 │ - module_symbols.json     │      │      │ - Architect (6k budget)   │
 │ - dependency_graph.json   │      │      │ - Coder (10k, 1-file max) │
 │ - test_map.json           │      │      │ - Critic (6k, eval/rev)   │
 │ - 3-Factor Semantic Ranker│      │      └─────────────┬─────────────┘
 └─────────────┬─────────────┘      │                    │
               │ RepoIndex /        │                    │ Subagent
               │ RankedFileSet      │                    │ Artifacts
               ▼                    ▼                    ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │                     harness/orchestrator.py                         │
 │ (Layer 5: ReAct State Machine & Conductor)                          │
 │                                                                     │
 │    INIT ──► PLAN ──► ACT ──► OBSERVE ──► REFLECT ──► DONE_CANDIDATE │
 │              ▲                             │               │        │
 │              └────── Plan Revision ────────┘               ▼        │
 │                                                        VERIFY       │
 │  Interconnects:                                       (Phase 3)     │
 │  - ContextManager (L4)                                     │        │
 │  - ToolEngine (L3)                                   PASS  │  FAIL  │
 │  - VerificationGate (L7)                                   ▼  ▼     │
 │  - RecoveryEngine (L8)                                   DONE REFLECT
 │  - TelemetryWriter (L9)                                             │
 └─────────────────────────────────────────────────────────────────────┘
```

---

### Component 1: Issue Parsing Engine — Layer 1 (`harness/issue_parser.py`)

#### [NEW] `harness/issue_parser.py`
- Implements two-pass extraction:
  - **Pass 1: Rule-Based Extraction (0 LLM tokens)**:
    - Extracts `suspected_files` with confidence scoring ($\ge 0.90$) matching repo files and traceback lines.
    - Extracts `reproduction_hint` ($\ge 0.95$) from "Steps to reproduce", tracebacks, test commands.
    - Extracts `error_type` ($\ge 0.92$) using standard exception class patterns.
    - Extracts `test_filter` ($\ge 0.88$) matching `test_*` function and file patterns.
    - Extracts `task_type` ($\ge 0.80$) via semantic keyword matching (`BUG_FIX`, `FEATURE`, `REFACTOR`, `TEST`, `DOCS`, `PERF`).
    - Detects target programming language and default test runner (`pytest`, `jest`, etc.).
  - **Pass 2: LLM Fallback**:
    - Triggered *only* if any core field confidence $< 0.75$.
    - Sends structured extraction prompt ($< 500$ tokens) to `ModelAdapter`.
  - **Complexity Scoring Formula (PRD §4.1.3)**:
    ```python
    complexity_score = (
        len(suspected_files) * 2 +
        traceback_depth * 1.5 +
        (1 if requires_external_knowledge else 0) * 3 +
        (1 if cross_module else 0) * 2 +
        (1 if task_type == TaskType.FEATURE else 0) * 4
    )
    ```
    - Score $0-4 \rightarrow$ `LOW`
    - Score $5-9 \rightarrow$ `MEDIUM`
    - Score $10-16 \rightarrow$ `HIGH`
    - Score $17+ \rightarrow$ `VERY_HIGH`
  - **Task-Adaptive Routing (PRD §4.1.3)**:
    - `LOW`: `SINGLE_REACT`, max steps 15, no subagents.
    - `MEDIUM`: `PLANNER_EXECUTOR`, max steps 25, Scout + Coder.
    - `HIGH`: `MULTI_AGENT`, max steps 40, Scout + Architect + Coder + Critic.
    - `VERY_HIGH`: `MULTI_AGENT_DEEP`, max steps 55, Scout + Architect + Coder×N + Critic.
  - Returns `IssuePlan` matching `harness/contracts.py`.

#### [MODIFY] `tests/test_issue_parser.py`
- Replace existing 9-line stub with full unit test suite:
  - `test_issue_parser_traceback_extraction()`: Extracts file, line, exception, and test name from Python traceback.
  - `test_issue_parser_feature_request()`: Correctly identifies `FEATURE` and sets appropriate criteria.
  - `test_issue_parser_complexity_scoring()`: Verifies exact mathematical score and thresholds for all 4 tiers.
  - `test_issue_parser_adaptive_routing()`: Verifies agent mode, max steps, and subagent selection.
  - `test_issue_parser_llm_fallback_trigger()`: Tests that high-confidence issues skip LLM entirely, and low-confidence issues invoke LLM adapter.

---

### Component 2: Repository Intelligence Engine — Layer 2 (`harness/repo_intel.py`)

#### [NEW] `harness/repo_intel.py`
- Implements:
  - `RepoIndexBuilder`:
    - Builds `.harness/repo_index/file_tree.txt`: Depth-4 condensed directory tree, filtering out `JUNK_DIRS` (`.git`, `__pycache__`, `.venv`, `node_modules`, `dist`, `build`, etc.). Token cost $< 500$ tokens for 500-file repo.
    - Builds `.harness/repo_index/module_symbols.json`: Top-level symbol catalog (classes, methods, functions, line ranges) per file using `ast` (with regex fallback for other languages).
    - Builds `.harness/repo_index/dependency_graph.json`: Directed import graph mapping `module -> [imported_modules]`.
    - Builds `.harness/repo_index/test_map.json`: Source file $\leftrightarrow$ test file coverage mapper based on naming conventions (`test_<name>.py`, `<name>_test.py`) and import tracing.
    - Cache invalidation: Hashes `git status --porcelain` and directory mtimes; skips re-indexing if unchanged.
  - `SemanticRanker`:
    - Implements BM25/TF-IDF token-frequency vector ranking across all file symbol summaries (with optional FAISS / sentence-transformers acceleration when available).
    - Implements 3-factor re-ranking formula (PRD §4.2.3):
      1. Embedding / keyword cosine similarity (weight: 0.5)
      2. Exact path/symbol match from `IssuePlan.suspected_files` (weight: 0.3)
      3. Import distance in dependency graph from `suspected_files` (weight: 0.2)
    - Returns `RankedFileSet` containing top-$N$ `RankedFile` instances with concise symbol summaries ready for prompt injection.

#### [MODIFY] `tests/test_repo_intelligence.py`
- Replace existing 9-line stub with full unit test suite:
  - `test_repo_index_builder_file_tree()`: Validates tree generation, depth limit, and exclusion filtering.
  - `test_module_symbols_generation()`: Validates extraction of classes, functions, and line ranges.
  - `test_dependency_graph_and_test_map()`: Validates import edges and source-to-test mapping.
  - `test_semantic_file_ranker_3_factor()`: Validates that top-3 relevant files are selected based on query, suspected files, and graph proximity.
  - `test_index_cache_invalidation()`: Verifies that cached index is reused when git status is clean, and rebuilt on modification.

---

### Component 3: Subagent Pool (`harness/subagents/pool.py`)

#### [NEW] `harness/subagents/pool.py`
- Implements isolated subagents with fixed context budgets and structured file outputs:
  - `ScoutSubagent` (PRD §4.5.3):
    - Context budget: 8,000 tokens.
    - Input: `IssuePlan` + `file_tree.txt` + `module_symbols.json`.
    - Output: `.harness/scout_report.md` (Relevant Files, Key Symbols & Call Paths, Dependency Chain, Suspected Root Cause, Recommended Fix Strategy).
  - `ArchitectSubagent` (PRD §4.5.3):
    - Context budget: 6,000 tokens.
    - Input: `IssuePlan` + `scout_report.md`.
    - Output: `.harness/architecture_plan.md` (Fix Strategy step-by-step, Files to Modify, Risk Factors, Test Verification Plan).
  - `CoderSubagent` (PRD §4.5.3):
    - Context budget: 10,000 tokens.
    - Input: `architecture_plan.md` + target file snippet.
    - Strict constraint: Scope limited strictly to assigned target file.
    - Output: `.harness/patch_{file}_{step}.diff`.
  - `CriticSubagent` (PRD §4.5.3):
    - Context budget: 6,000 tokens.
    - Input: `IssuePlan` + all patches + test results.
    - Output: `.harness/critic_report.md` (Correctness Assessment, Edge Cases, Potential Regressions, Recommendation: `APPROVE` or `REVISE`).

#### [NEW] `tests/test_subagents.py`
- Tests token budgets, prompt schemas, and output file artifacts for Scout, Architect, Coder, and Critic.

---

### Component 4: Multi-Agent Orchestrator Loop — Layer 5 (`harness/orchestrator.py`)

#### [NEW] `harness/orchestrator.py`
- Implements the complete ReAct State Machine:
  `INIT -> PLAN -> ACT -> OBSERVE -> REFLECT -> DONE_CANDIDATE -> DONE / FAILED`
- Integrates all subsystems:
  - `IssueParser` (L1) $\rightarrow$ creates `IssuePlan`
  - `RepoIndexBuilder` & `SemanticRanker` (L2) $\rightarrow$ builds index & injects top-ranked files into repo context
  - `ContextManager` (L4) $\rightarrow$ constructs 5-section prompts, truncates observations, injects recovery prompts
  - `ToolEngine` (L3) $\rightarrow$ executes tools with 10-call deduplicator and sandbox security
  - `VerificationGate` (L7) $\rightarrow$ validates 6 phases on `DONE_CANDIDATE`
  - `RecoveryEngine` (L8) $\rightarrow$ handles verification failures and circuit breakers
  - `TelemetryWriter` (L9) $\rightarrow$ logs all 18 event types in real time
- Key Features:
  - Structured `AgentPlan` parser: Parses and validates `{"plan": [...], "estimated_total_steps": 8, "rollback_checkpoints": [3, 6]}`. Saves to `.harness/plan.md`.
  - Structured `DoneCandidate` parser: Validates `{"status": "DONE_CANDIDATE", "confidence": 0.95, "evidence": [...], "files_modified": [...]}`. Triggers `VerificationGate`.
  - Reflection Prompt Injector: Formats and injects the `REFLECT` phase prompt (PRD §5.3) after each tool observation.
  - Plan Revision Protocol: Lesson injection, incrementing `revision_count` (max 3 revisions before graceful exit).
  - Rollback Checkpoints: Captures `git diff` at plan step markers into `.harness/checkpoint_{N}.diff`. On failure/escalation, rolls back to the last safe checkpoint.
  - Single-Agent vs Multi-Agent Execution Modes: Dispatches `SINGLE_REACT` directly, or coordinates Scout $\rightarrow$ Architect $\rightarrow$ Coder $\rightarrow$ Critic subagent pipeline for `MEDIUM` and `HIGH` issues.

#### [MODIFY] `tests/test_orchestrator.py`
- Replace existing 9-line stub with full unit and state transition test suite:
  - `test_orchestrator_state_transitions()`: Validates `INIT -> PLAN -> ACT -> OBSERVE -> REFLECT -> DONE_CANDIDATE -> DONE`.
  - `test_plan_output_parser_valid_and_invalid()`: Tests valid structured JSON plan vs malformed JSON plan rejection.
  - `test_done_candidate_output_parser()`: Tests valid candidate triggering verification vs rejected candidate missing evidence.
  - `test_reflection_prompt_injection()`: Validates reflection template formatting.
  - `test_plan_revision_limit_and_escalation()`: Tests max 3 revisions transitioning to graceful exit on 4th.
  - `test_rollback_checkpoint_capture()`: Verifies `.harness/checkpoint_{N}.diff` snapshot generation.

---

### Component 5: Integration & CLI Wiring

#### [MODIFY] `harness/cli.py`
- Wire `IssueParser`, `RepoIndexBuilder`, and `Orchestrator` into the `zenith run` execution flow.
- Add `--issue-text` support in addition to `--issue` file path.

#### [MODIFY] `harness/__init__.py`
- Export `IssueParser`, `RepoIndexBuilder`, `SemanticRanker`, `Orchestrator`, `ScoutSubagent`, `ArchitectSubagent`, `CoderSubagent`, `CriticSubagent`.

#### [NEW] `tests/test_p4_e2e.py`
- End-to-end integration test:
  - Sets up a mock repository with a bug and a failing test.
  - Runs the full Orchestrator loop using `GeminiAdapter` stub / mock adapter.
  - Verifies: Issue parsed $\rightarrow$ Repo indexed $\rightarrow$ Plan generated $\rightarrow$ Tool executed $\rightarrow$ Checkpoint saved $\rightarrow$ Verification executed $\rightarrow$ Final session result returned.

---

## Verification Plan

### Automated Tests
1. **Unit tests for Issue Parser:**
   ```bash
   pytest tests/test_issue_parser.py -v
   ```
2. **Unit tests for Repo Intelligence:**
   ```bash
   pytest tests/test_repo_intelligence.py -v
   ```
3. **Unit tests for Subagents:**
   ```bash
   pytest tests/test_subagents.py -v
   ```
4. **Unit tests for Orchestrator State Machine:**
   ```bash
   pytest tests/test_orchestrator.py -v
   ```
5. **Phase 4 End-to-End Integration:**
   ```bash
   pytest tests/test_p4_e2e.py -v
   ```
6. **Full Suite Regression & Linting:**
   ```bash
   pytest -v
   ruff check harness/ tests/
   ```

### Manual Verification
1. Inspect generated `.harness/repo_index/` (`file_tree.txt`, `module_symbols.json`, `dependency_graph.json`, `test_map.json`).
2. Run `python -m harness.cli --repo . --dry-run` to verify full indexing and prompt preparation on the Zenith repo itself.
3. Verify that zero linter errors or warnings are emitted.
