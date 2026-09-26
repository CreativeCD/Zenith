# Zenith — Implementation Phases & Sprint Plan
### AI Coding Harness Hackathon 2026

```
Total Duration : 24 Hours
Team           : Zenith
Reference PRD  : PRD.md (v4.0 — Elite Master) | architecture.md (v1.0)
Status         : ACTIVE — See logs.md for all progress entries
Last Synced    : 2026-09-26 (PRD v4.0 + Architecture v1.0)
```

---

## Phase Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  P0: Bootstrap & Infrastructure     [0h–2h]   Skeleton + config + contracts  │
│  P1: Core Tool Engine               [2h–6h]   All 15 tools + dedup + sandbox │
│  P2: Context & Memory System        [6h–10h]  5-section prompt + KV + comprs  │
│  P3: Verification & Recovery        [10h–14h] 6-phase gate + 10-code taxonomy │
│  P4: Repo Intelligence & Agents     [14h–18h] AST index + FAISS + subagents   │
│  P5: External Skills & Telemetry    [18h–21h] Skill cache + telemetry + report │
│  P6: Integration & Hardening        [21h–24h] E2E bench + Docker + submit     │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Total tracked tasks: 124** (across all phases)

---

## Cross-Phase Architecture Reference

From PRD §3.2 — every module feeds into this dependency graph:

```
cli.py
 ├── config.py                   [P0]
 ├── issue_parser.py             [P4]  — L1
 ├── repo_intelligence.py        [P4]  — L2
 ├── orchestrator.py             [P4]  — L5 (drives main loop)
 │    ├── context_manager.py     [P2]  — L4
 │    ├── tool_engine.py         [P1]  — L3
 │    ├── skill_retriever.py     [P5]  — L6
 │    ├── verification.py        [P3]  — L7
 │    └── recovery.py            [P3]  — L8
 ├── telemetry.py                [P5]  — L9
 └── report_generator.py         [P5]  — L9
```

---

## Phase 0: Bootstrap & Infrastructure `[0h – 2h]`

**Goal:** Establish the full project skeleton, data contracts (dataclasses), config system, and test scaffolding. Every teammate can work in parallel from here.

### Deliverables

| # | Task | PRD Ref | Done Criteria |
|---|---|---|---|
| 0.1 | Initialize git repo, `.gitignore`, `README.md`, `LICENSE` | §12 | `git log` shows initial commit |
| 0.2 | Create `Makefile` with `setup`, `run`, `test`, `clean`, `lint`, `docker-test` targets | §12.1 | `make setup` creates `.venv` cleanly on fresh machine |
| 0.3 | Create full project directory structure matching PRD spec | §12.3 | Directory tree matches exactly |
| 0.4 | Write `harness_config.yaml` with ALL 50+ default values from PRD §14 | §14 | Config parsed and validated by `config.py` without errors |
| 0.5 | Write `requirements.txt` with ALL pinned dependencies | §15 | `pip install -r requirements.txt` succeeds in empty venv |
| 0.6 | Scaffold `harness/cli.py` with `argparse` all flags (see PRD §12.2) | §12.2 | `python -m harness.cli --help` shows all flags |
| 0.7 | Implement all inter-layer data contracts as Python dataclasses in `harness/contracts.py` | §8 | All dataclasses serializable to/from JSON |
| 0.8 | Implement `TelemetryWriter` stub — `append(TelemetryEvent)` writes to JSONL | §4.9.1 | `TelemetryWriter.append(event)` writes valid JSON line |
| 0.9 | Set up structured logging (`logging.yaml`) — stdout + rotating file | — | Log entries include timestamp, level, module, message |
| 0.10 | Write `.env.example` with `AI_API_KEY` and `GITHUB_TOKEN` | §13.1 | File exists; `.env` in `.gitignore` |
| 0.11 | Write `ModelAdapter` protocol + stub `GeminiAdapter` | §10.2 | Protocol defined; `GeminiAdapter.complete()` raises `NotImplementedError` |
| 0.12 | Write baseline test suite stubs in `tests/` (one file per module) | §11.2 | `make test` runs 0 failures (all stubs skip) |
| 0.13 | Implement `harness/config.py` — loads YAML, applies CLI overrides, validates | §14 | Config loaded with correct types; CLI overrides apply correctly |

### Full Directory Structure

```
zenith/
├── Makefile
├── README.md
├── Dockerfile
├── harness_config.yaml
├── requirements.txt
├── .env.example
├── .gitignore
├── harness/
│   ├── __init__.py
│   ├── cli.py                   # Entry point — all CLI flags
│   ├── config.py                # Config loader + validator
│   ├── contracts.py             # All inter-layer dataclasses (PRD §8)
│   ├── telemetry.py             # JSONL event writer (L9)
│   ├── issue_parser.py          # L1: Issue Parsing + planning
│   ├── repo_intelligence.py     # L2: AST index + FAISS ranker + LSP
│   ├── tool_engine.py           # L3: All 15 tools + dedup + sandbox
│   ├── context_manager.py       # L4: 5-section prompt + token budget
│   ├── orchestrator.py          # L5: State machine + subagent pool
│   ├── skill_retriever.py       # L6: External skill cache
│   ├── verification.py          # L7: 6-phase gate
│   ├── recovery.py              # L8: Recovery engine + circuit breaker
│   ├── report_generator.py      # L9: report.md compiler
│   └── adapters/
│       ├── gemini_adapter.py    # Gemini function-calling adapter
│       ├── claude_adapter.py    # Anthropic adapter
│       └── openai_adapter.py    # OpenAI-compatible adapter
└── tests/
    ├── fixtures/                # Sample issues, repos, telemetry files
    │   ├── sample_issues/
    │   └── toy_repos/
    ├── test_issue_parser.py
    ├── test_repo_intelligence.py
    ├── test_tool_engine.py
    ├── test_context_manager.py
    ├── test_orchestrator.py
    ├── test_verification.py
    ├── test_recovery.py
    ├── test_telemetry.py
    └── test_report_generator.py
```

### P0 Exit Criteria
- [ ] `make setup` creates `.venv` cleanly on fresh machine (no errors)
- [ ] `make test` runs 0 failures (all stubs may skip)
- [ ] `python -m harness.cli --help` shows all 10 CLI flags
- [ ] All dataclasses in `contracts.py` serialize/deserialize correctly
- [ ] `TelemetryWriter.append(event)` writes valid JSON line to `.harness/telemetry.jsonl`

---

## Phase 1: Core Tool Engine `[2h – 6h]`

**Goal:** All 15 tools implemented with their full safeguards, sandboxing, and deduplication. LLM function-calling schema wired. Single-turn E2E validated.

### Deliverables

| # | Task | PRD Ref | Done Criteria |
|---|---|---|---|
| **Navigation Tools** |
| 1.1 | `list_dir` — depth cap, exclusion list, file sizes | §4.3.2 | Unit test: excludes `.git`, caps at depth 4 |
| 1.2 | `search_code` — ripgrep, 50-match cap, sanitization, context lines | §4.3.2 | Unit test: ≤50 results; regex sanitized; test dirs filtered |
| 1.3 | `get_symbol` — Tree-sitter AST lookup, signature + docstring + line range | §4.3.2 | Unit test: extracts Python function signature correctly |
| 1.4 | `find_references` — all call sites with context, max 30 locations | §4.3.2 | Unit test: finds all calls to a test function |
| 1.5 | `get_imports` — all import statements from file via AST | §4.3.2 | Unit test: correctly lists all imports |
| 1.6 | `list_symbols` — all top-level names + line numbers from file | §4.3.2 | Unit test: returns all classes and functions |
| **Edit Tools** |
| 1.7 | `read_file_range` — 250-line cap, path validation, line numbers in output | §4.3.2 | Unit test: rejects non-existent path; caps at 250 lines |
| 1.8 | `apply_patch` dual-mode — unified diff primary + exact-block fallback + AST check | §4.3.2 | Unit test: applies clean patch; rolls back on broken AST |
| 1.9 | `write_file` — new files only, refuses overwrite, creates parent dirs | §4.3.2 | Unit test: refuses to overwrite existing file |
| **Execution Tools** |
| 1.10 | `run_test_suite` — pytest/jest/go test adapter, 120s timeout, 80-line truncated output | §4.3.2 | Integration test: runs pytest on toy repo, returns correct exit code |
| 1.11 | `run_bash_sandboxed` — 30s timeout, 512MB memory, 12-pattern blocklist, 200-line cap | §4.3.2, §4.3.4 | Unit test: blocks all 12 blocklist patterns; kills at 30s |
| **VCS Tools** |
| 1.12 | `git_rollback` — single file + all files modes, telemetry event emitted | §4.3.2 | Unit test: restores file to HEAD after intentional edit |
| 1.13 | `git_diff` — vs HEAD, 500-line cap | §4.3.2 | Unit test: returns correct diff after `apply_patch` |
| 1.14 | `git_status` — list of modified/added/deleted files | §4.3.2 | Unit test: correctly lists all modified files |
| **Guards** |
| 1.15 | `ToolCallDeduplicator` — SHA256 fingerprint, 10-call ring buffer | §4.3.3 | Unit test: blocks 2nd identical call; allows after intermediate edit |
| 1.16 | `reasoning` field validator — rejects calls without reasoning | §4.3.1 | Unit test: missing reasoning → error message returned |
| 1.17 | Path validator — rejects paths outside REPO_PATH + path traversal | §4.3.4 | Unit test: `../` and `/etc/` paths rejected |
| 1.18 | Wire all tools to LLM function-calling JSON schema definitions | §4.3.1 | All tool schemas validated by Pydantic |
| 1.19 | Single-turn E2E: read file → patch → run test → exit code 0 | §3.3 | Manual E2E: toy bug fixed in single agent turn |

### Key Technical Decisions (aligned with PRD §10)

- **Tree-sitter:** `tree-sitter` Python package with pre-compiled grammars for Python, JS, TS, Go, Rust.
- **ripgrep:** `subprocess` call to `rg` binary; fallback to `re` + file walker if not in PATH.
- **Sandbox:** `subprocess.Popen(args, shell=False)` + `resource.setrlimit` on Unix.
- **Patch mode:** Detect unified diff by `---`/`+++` prefix; fallback to exact block replace.
- **Function-calling schema:** Pydantic models → `model.model_json_schema()` for tool definitions.

### P1 Exit Criteria
- [ ] All 14 tool implementations pass unit tests (100% pass rate)
- [ ] All 3 guard layers (dedup, reasoning, path) pass unit tests
- [ ] All 12 blocklist patterns blocked correctly in sandbox
- [ ] Single-turn E2E: reads file → patches → runs test → exit code 0

---

## Phase 2: Context & Memory System `[6h – 10h]`

**Goal:** 5-section prompt builder with hard budget enforcement, rolling summarizer, observation truncation policy, KV cache optimization, and full sliding window.

### Deliverables

| # | Task | PRD Ref | Done Criteria |
|---|---|---|---|
| 2.1 | Implement `TokenBudgetManager` — per-section budgets from §4.4.2 | §4.4.2 | Unit test: exceeding ceiling raises `ContextOverflowError` |
| 2.2 | Implement 5-section prompt builder — PERSONA / GOAL / REPO_CTX / MEMORY / TURNS | §4.4.1 | Unit test: sections in correct order; total within budget |
| 2.3 | Implement KV cache optimization — PERSONA + GOAL byte-identical across turns | §6.2 | Unit test: bytes of sections 1+2 unchanged across 5 consecutive turns |
| 2.4 | Implement dynamic budget adjustment algorithm from PRD §4.4.2 | §4.4.2 | Unit test: N reduces dynamically when turns are long |
| 2.5 | Implement observation truncation for all 5 size classes in PRD §4.4.3 | §4.4.3 | Unit test: each size class produces correct head/tail/separator format |
| 2.6 | Implement `RollingSummarizer` — triggered at 70%, compresses oldest 50% of turns | §4.4.4 | Unit test: triggers at 70%; output captures goal + findings + edits |
| 2.7 | Implement Rolling Summarizer compression prompt template from PRD §4.4.4 | §4.4.4 | Compression output ≤ 600 tokens with all required fields |
| 2.8 | Implement `WorkingMemorySnapshot` writer — `.harness/context_summary.md` | §4.4.4 | File written after each compression event; readable by human |
| 2.9 | Implement token counting — model tokenizer or `tiktoken` approximation | §4.4.2 | Token counts within 5% of actual model count |
| 2.10 | Wire ContextManager into orchestrator loop — all prompts built via ContextManager | §3.3 | E2E: prompt token count logged in telemetry every turn |

### P2 Exit Criteria
- [ ] `TokenBudgetManager` enforces ALL section limits in unit tests
- [ ] Prompt token count ≤ `max_context_tokens` in every turn of E2E runs
- [ ] KV cache test: sections 1+2 byte-identical across 5 turns
- [ ] Rolling Summarizer triggers at exactly 70% threshold
- [ ] All 5 observation size classes truncated correctly
- [ ] `context_summary.md` written after each compression event

---

## Phase 3: Verification Gate & Recovery Engine `[10h – 14h]`

**Goal:** Full 6-phase VerificationGate, 10-code taxonomy RecoveryEngine, 3-level circuit breaker, graceful degradation chain.

### Deliverables

| # | Task | PRD Ref | Done Criteria |
|---|---|---|---|
| **Verification Gate — 6 Phases** |
| 3.1 | Phase 1: Syntax check — `py_compile`, `tsc --noEmit`, `go vet`, `cargo check` | §4.7.1 | Unit test: catches intentionally broken syntax in Python + JS |
| 3.2 | Phase 2: Linter check — delta mode (new violations only vs `linter_baseline.json`) | §4.7.1 | Unit test: pre-existing violations not reported; new violations caught |
| 3.3 | Phase 3: Reproduction test — `test_filter` from IssuePlan | §4.7.1 | Integration test: returns PASS/FAIL with exact stack trace |
| 3.4 | Phase 4: Full regression suite + `test_baseline.json` delta comparison | §4.7.1 | Integration test: detects 1 newly introduced failing test |
| 3.5 | Phase 5: Diff audit — file scope check, binary file check, whitespace-only check | §4.7.1 | Unit test: flags modification to files outside expected set |
| 3.6 | Phase 6: Side-effect check — isolated module import via `importlib` | §4.7.1 | Unit test: detects `sys.exit()` at module level |
| 3.7 | Baseline capture at startup — `linter_baseline.json` + `test_baseline.json` | §4.7.1 | Both files written before first agent turn |
| 3.8 | `VerificationResult` dataclass + JSON serialization (matches PRD §4.7.2 schema) | §4.7.2 | JSON output matches schema for all 6 phase combinations |
| 3.9 | Sequential phase execution with early-exit on first failure | §4.7.1 | Unit test: Phase 1 fail stops execution before Phase 2 |
| **Recovery Engine — 10-Code Taxonomy** |
| 3.10 | Anti-loop circuit breaker — 5-call hash ring, 3 trigger levels (WARNING / BLOCK / ESCALATE) | §4.8.1 | Unit test: Level 1/2/3 triggers at correct thresholds |
| 3.11 | Error taxonomy router — classifies event type to recovery strategy | §4.8.2 | Unit test: each of 10 error codes maps to correct handler |
| 3.12 | `PATCH_FAILED` recovery — re-read ±20 lines, switch to block mode, retry | §4.8.2 | Integration test: auto-switches patch mode, succeeds on retry |
| 3.13 | `AST_PARSE_FAIL` recovery — auto-rollback + inject exact parse error | §4.8.2 | Unit test: file restored; parse error injected |
| 3.14 | `LINT_REGRESSION` recovery — inject violation locations + force view | §4.8.2 | Unit test: violation lines injected into next prompt |
| 3.15 | `TEST_FAILED` recovery — inject stack trace + force test file read | §4.8.2 | Integration test: stack trace injected as structured context |
| 3.16 | `REGRESSION_DETECTED` recovery — diff of new failures + targeted rollback | §4.8.2 | Integration test: identifies and rolls back the regressing edit |
| 3.17 | `SIDE_EFFECT_DETECTED` recovery — inject offending lines + refactor guidance | §4.8.2 | Unit test: module-level `print()` detected and reported |
| 3.18 | `TIMEOUT` recovery — kill + targeted test filter guidance | §4.8.2 | Unit test: process killed; guidance injected |
| 3.19 | `MAX_STEPS_EXCEEDED` graceful exit — rollback all + partial report | §4.8.2 | Unit test: clean repo state preserved; `report.md` generated |
| 3.20 | Graceful degradation chain — L1 auto-remediate → L2 plan revision → L3 exit | §4.8.3 | Integration test: chain triggers correctly at each escalation threshold |
| 3.21 | Wire VerificationGate + RecoveryEngine into orchestrator state machine | §7 | E2E: agent fails test, auto-recovers, passes on 2nd attempt |

### P3 Exit Criteria
- [ ] All 6 verification phases pass unit tests (correct PASS and FAIL for each)
- [ ] All 10 error codes route to correct recovery handler
- [ ] Circuit breaker Level 1/2/3 all trigger at correct thresholds
- [ ] Graceful degradation chain: L1 → L2 → L3 escalates correctly
- [ ] `VerificationResult` JSON matches schema in all 6-phase outcome combinations
- [ ] E2E: intentional PATCH_FAILED → auto-recovery → PASS in test repo

---

## Phase 4: Repository Intelligence & Multi-Agent Orchestration `[14h – 18h]`

**Goal:** Full RepoIntelligenceEngine (Tree-sitter + FAISS + dependency graph), IssueParser with complexity routing, and complete PLAN→ACT→OBSERVE→REFLECT state machine with subagent pool.

### Deliverables

| # | Task | PRD Ref | Done Criteria |
|---|---|---|---|
| **Repository Intelligence Engine — L2** |
| 4.1 | `RepoIndexBuilder` — `file_tree.txt` generation (depth-4, filtered) | §4.2.1 | Index for 300-file repo in < 5 seconds; token cost < 500 |
| 4.2 | `module_symbols.json` — Tree-sitter per-file symbol extraction (name + line range only) | §4.2.1 | Correctly extracts all top-level symbols from Python + JS files |
| 4.3 | `dependency_graph.json` — import/require directed graph builder | §4.2.1 | Graph correctly maps all imports in test repo |
| 4.4 | `test_map.json` — source file ↔ test file coverage mapper | §4.2.1 | Maps ≥ 80% of test files in test repo to source files |
| 4.5 | FAISS embedding index — embed file symbol summaries via `all-MiniLM-L6-v2` (local) | §4.2.3 | Index built for 100-file repo; similarity search returns relevant results |
| 4.6 | Semantic file ranker — 3-factor re-ranking (embedding + path match + dependency distance) | §4.2.3 | Correct top-3 files selected for 4/5 sample issues |
| 4.7 | Index cache invalidation — stale index detection via `git status` | §4.2.1 | Index rebuilt on code change; cache used when unchanged |
| 4.8 | LSP integration (optional) — connect to `pylsp` / `pyright` if available | §4.2.4 | Graceful fallback to Tree-sitter when LSP not found |
| **Issue Parsing Engine — L1** |
| 4.9 | `IssueParser` — rule-based Pass 1 with confidence scoring for all 6 fields | §4.1.1 | Correctly extracts all fields from 8/10 sample issues without LLM |
| 4.10 | `IssueParser` — LLM fallback Pass 2 (triggered only when any field < 0.75 confidence) | §4.1.1 | LLM NOT called for 7/10 simple sample issues |
| 4.11 | Complexity scorer — formula from PRD §4.1.3, produces LOW/MEDIUM/HIGH/VERY_HIGH | §4.1.3 | Correct classification on 10 sample issues |
| 4.12 | Task-adaptive routing — maps complexity to agent mode + max steps + subagent config | §4.1.3 | Correct mode selected for all 4 complexity levels |
| **Orchestration Loop — L5** |
| 4.13 | Full PLAN→ACT→OBSERVE→REFLECT state machine from PRD §4.5.1 | §4.5.1, §7.1 | State transitions correct; step counter works; DONE_CANDIDATE triggers verify |
| 4.14 | PLAN output parser — validates structured JSON plan from PRD §4.5.2 | §4.5.2 | Malformed plan rejected; valid plan stored in `.harness/plan.md` |
| 4.15 | DONE_CANDIDATE output parser — validates structured JSON signal | §4.5.2 | Missing evidence field → rejected; valid signal → triggers verification |
| 4.16 | Reflection prompt injector — REFLECT phase template from PRD §5.3 | §5.3 | Template injected with correct observation and goal fields |
| 4.17 | Scout subagent — isolated context (8k budget), `scout_report.md` output | §4.5.3 | Report contains: ranked files, symbols, dependency chain, root cause, strategy |
| 4.18 | Architect subagent — isolated context (6k budget), `architecture_plan.md` output | §4.5.3 | Plan contains: step-by-step fix, files to modify, risks, test plan |
| 4.19 | Coder subagent — isolated context (10k budget), single-file scope enforced | §4.5.3 | Correctly refuses to modify files outside its assigned scope |
| 4.20 | Critic subagent — isolated context (6k budget), `critic_report.md` output | §4.5.3 | Report contains: correctness assessment, edge cases, regressions, recommendation |
| 4.21 | Orchestrator routing — auto-selects agent mode by complexity score | §4.5.2 | LOW → `SINGLE_REACT`; MEDIUM → Scout+Coder; HIGH → full pool |
| 4.22 | Plan revision protocol — lesson injection, max 3 revisions, escalation trigger | §4.5.3 | 4th revision triggers GracefulExit |
| 4.23 | Rollback checkpoints — git diff snapshots at plan step markers | §4.5.4 | `.harness/checkpoint_{N}.diff` written at each designated checkpoint |
| 4.24 | E2E full multi-agent run on MEDIUM complexity bug in test repo | §11.3 | Scout → Coder → Verify → PASS; all subagent artifacts written |

### P4 Exit Criteria
- [ ] Repo index builds in < 10 seconds for 500-file repo
- [ ] Semantic ranking selects correct top-3 files for 4/5 test issues
- [ ] Rule-based IssueParser handles 8/10 sample issues without LLM
- [ ] Full ReAct loop (single-agent) solves 3/5 sample bugs
- [ ] Multi-agent flow (Scout → Coder → Critic) completes for 1 MEDIUM complexity bug
- [ ] All 4 complexity levels route to correct agent mode

---

## Phase 5: External Skills, Telemetry & Report Generator `[18h – 21h]`

**Goal:** External skill retriever with startup pre-fetch and 24h cache. Full telemetry pipeline with real-time cost dashboard. Auto-report generator with all 8 required sections.

### Deliverables

| # | Task | PRD Ref | Done Criteria |
|---|---|---|---|
| **External Skill Retriever — L6** |
| 5.1 | `ExternalSkillRetriever` — cache-first pipeline from PRD §4.6.2 | §4.6.2 | Cache HIT returns in < 10ms; cache MISS fetches + stores |
| 5.2 | SHA256 cache key + 24h TTL expiry | §4.6.2 | Expired entry triggers re-fetch; fresh entry returns from cache |
| 5.3 | Skill cache storage — `.harness/skill_cache/{hash}.json` | §12.3 | Each cached entry is a valid JSON with content + timestamp |
| 5.4 | `fetch_external_skill` tool integration | §4.3.2 | Agent can call tool and receive compressed snippet ≤ 500 tokens |
| 5.5 | Startup pre-fetch — parallel async fetch of README, CONTRIBUTING, CI config, test config | §4.6.3 | All 4 targets cached before first agent turn |
| 5.6 | SWE-bench trajectory local index — top-3 similar issue lookup | §4.6.1, §9.3 | Returns relevant trajectory for 3/5 sample issues |
| 5.7 | Relevant section extractor — extract only relevant subsection from raw fetched content | §4.6.2 | Extracted section is semantically relevant (manual review) |
| **Telemetry Pipeline — L9** |
| 5.8 | Full `TelemetryWriter` — all 18 event types, all fields from PRD §4.9.1 | §4.9.1 | Every event type written correctly; JSON schema validated |
| 5.9 | Real-time token + cost accounting per turn (cumulative fields updated each event) | §4.9.1 | Token + cost totals match sum of individual events |
| 5.10 | Real-time cost dashboard (stdout in `--verbose` mode) — PRD §4.9.2 format | §4.9.2 | Dashboard renders correctly with all 4 metric lines |
| 5.11 | Session ID generation + all events tagged with session_id | §4.9.1 | All events in one run share the same session_id |
| **Report Generator — L9** |
| 5.12 | `ReportGenerator` — compiles `telemetry.jsonl` → `report.md` | §4.9.3 | Report generated correctly from sample telemetry fixture |
| 5.13 | Report Section 1: Executive summary (all fields from PRD §4.9.3) | §4.9.3 | All 7 metric rows present and correct |
| 5.14 | Report Section 2: Step-by-step timeline table | §4.9.3 | One row per LLM_TURN event, sorted by step |
| 5.15 | Report Section 3: Recovery events (error code + action + outcome) | §4.9.3 | All recovery events from telemetry present |
| 5.16 | Report Section 4: Verification results (all 6 phases, PASS/FAIL) | §4.9.3 | All 6 phase results present with detail |
| 5.17 | Report Section 5: Final diff (git_diff output in code block) | §4.9.3 | Diff rendered correctly in fenced code block |
| 5.18 | Report Section 6: Agent decisions log | §4.9.3 | Key plan decisions from telemetry extracted |
| 5.19 | Report Section 7: Token + cost breakdown (per-agent, per-phase) | §4.9.3 | Breakdown table present; totals match section 1 |
| 5.20 | Report Section 8: Lessons learned (from `context_summary.md`) | §4.9.3 | Final working memory snapshot embedded |
| 5.21 | Report generated even on FAIL/PARTIAL — no crash path skips report | §15 | Report.md exists after GracefulExit run |
| 5.22 | E2E: Full successful run produces complete report.md with all 8 sections | — | Human review confirms all sections correct |

### P5 Exit Criteria
- [ ] `fetch_external_skill` returns cache hit for all 4 startup pre-fetched resources
- [ ] Every telemetry event validated against PRD §4.9.1 schema (automated check)
- [ ] `report.md` generated automatically after: PASS run, FAIL run, GracefulExit run
- [ ] All 8 report sections present in all run types
- [ ] Token + cost cumulative totals match sum of individual events

---

## Phase 6: Integration, Hardening & Submission `[21h – 24h]`

**Goal:** Full E2E benchmark on real repos, Docker clean-clone verification, performance tuning, and final submission.

### Deliverables

| # | Task | PRD Ref | Done Criteria |
|---|---|---|---|
| **Benchmarking** |
| 6.1 | Run harness against SWE-bench Lite sample — Run #1: django/django (LOW) | §17.3 | Result logged in logs.md |
| 6.2 | Run harness against SWE-bench Lite sample — Run #2: flask/flask (MEDIUM) | §17.3 | Result logged in logs.md |
| 6.3 | Run harness against SWE-bench Lite sample — Run #3: numpy/numpy (MEDIUM) | §17.3 | Result logged in logs.md |
| 6.4 | Run harness against SWE-bench Lite sample — Run #4: sympy/sympy (HIGH) | §17.3 | Result logged in logs.md |
| 6.5 | Run harness against SWE-bench Lite sample — Run #5: astropy/astropy (HIGH) | §17.3 | Result logged in logs.md |
| **Optimization** |
| 6.6 | Analyze telemetry from 6.1–6.5: identify top-3 token waste patterns | §6 | Analysis written in logs.md |
| 6.7 | Tune observation truncation thresholds based on real run outputs | §4.4.3 | Token usage reduced ≥ 10% vs baseline on re-run |
| 6.8 | Tune recovery prompts based on real failure patterns | §5.4 | Recovery rate improved ≥ 10% on re-run |
| 6.9 | Tune complexity scorer thresholds based on observed routing accuracy | §4.1.3 | All 5 benchmark issues routed to correct agent mode |
| **Hardening** |
| 6.10 | Full clean clone dry run: `git clone → make setup → make run` | §15 | Succeeds with zero manual intervention in < 10 minutes |
| 6.11 | Full clean clone dry run inside Docker container | §12.1 | `docker build && docker run` succeeds |
| 6.12 | Security audit: grep for hardcoded secrets, log leaks, unsafe calls | §13.1 | Zero findings |
| 6.13 | `make test` — zero failures, line coverage > 70% | §11 | Coverage report shows > 70% |
| 6.14 | Audit `README.md` — evaluator can run by following README alone | §12.2 | New team member dry-runs README; succeeds |
| 6.15 | Final submission: code freeze + tag `v1.0.0` + push | — | `git tag v1.0.0` pushed; submission confirmed |

### Final Submission Checklist

- [ ] **Pass rate:** ≥ 4/5 internal benchmark runs PASS
- [ ] **Autonomy:** Zero `input()` calls; no manual steps in README
- [ ] **Clean clone:** `make setup && make run` works in Docker (confirmed)
- [ ] **Tests:** `make test` → 0 failures, > 70% line coverage
- [ ] **Report:** `report.md` generated after every run type (PASS / FAIL / PARTIAL)
- [ ] **Security:** `grep -r "sk-\|AI_API_KEY=" harness/` → zero results
- [ ] **README:** Complete with setup, config, run, output instructions
- [ ] **Config:** `harness_config.yaml` with all 50+ params; `--dry-run` works
- [ ] **Tag:** `git tag v1.0.0` created and pushed
- [ ] **Submission:** Confirmation received from evaluator

---

## Cross-Phase Dependencies

```
P0 (Bootstrap + Contracts)
  └─► P1 (Tool Engine)          — needs CLI + config + dataclasses
       ├─► P2 (Context Manager) — needs tools implemented
       └─► P3 (Verify+Recovery) — needs tools + test runner
            └─► P4 (Agents)     — needs P1 + P2 + P3 all complete
                 └─► P5 (Telemetry + Skills) — needs orchestrator to emit events
                      └─► P6 (Hardening) — needs full stack E2E working
```

## Parallel Work Tracks Within Each Phase

| Phase | Track A (can start immediately) | Track B (can start simultaneously) |
|---|---|---|
| P0 | Config + CLI + Makefile | Contracts + dataclasses + stubs |
| P1 | Navigation + Edit tools (1.1–1.9) | Execution + VCS + guards (1.10–1.19) |
| P2 | Token budget + 5-section builder (2.1–2.5) | Rolling summarizer + KV cache (2.6–2.10) |
| P3 | VerificationGate 6 phases (3.1–3.9) | RecoveryEngine 10 codes (3.10–3.20) |
| P4 | RepoIntelligenceEngine (4.1–4.8) | IssueParser + Orchestrator (4.9–4.24) |
| P5 | ExternalSkillRetriever (5.1–5.7) | Telemetry + ReportGenerator (5.8–5.22) |
| P6 | Benchmark runs (6.1–6.5) | Optimization + hardening (6.6–6.15) |

---

## Task Summary by Phase

| Phase | Tasks | New vs v3.0 |
|---|---|---|
| P0 | 13 | +3 (contracts.py, ModelAdapter, Dockerfile) |
| P1 | 19 | +8 (get_symbol, find_references, get_imports, list_symbols, git_status, LINT_REGRESSION/SIDE_EFFECT recovery, path validator) |
| P2 | 10 | +1 (KV cache optimization task 2.3) |
| P3 | 21 | +5 (LINT_REGRESSION, SIDE_EFFECT_DETECTED, 3-level circuit breaker, degradation chain, baseline capture) |
| P4 | 24 | +10 (VERY_HIGH complexity mode, structured output parsers, reflection template, rollback checkpoints, LSP integration, IssueParser confidence scoring) |
| P5 | 22 | +9 (SWE-bench index, section extractor, 8-section report, verbose dashboard, session ID) |
| P6 | 15 | +3 (Docker test, optimization tasks, README audit) |
| **TOTAL** | **124** | **+39 new tasks vs v3.0** |

---

*Document Version: 2.0 (synced with PRD v4.0)*
*Last Updated: 2026-09-26*
*Cross-reference: All task PRD Ref fields point to PRD.md (v4.0) sections*
