# Phase 5 Implementation Plan: External Skills, Telemetry & Report Generator

## 1. Overview & Architecture Reference
- **PRD References**: §4.6 (Layer 6: External Knowledge & Skills), §4.9 (Layer 9: Telemetry & Cost Accounting), §12.3, §14
- **Architecture References**: §7.6 (SkillRetriever), §7.9 (Telemetry & ReportGenerator), §12, §19
- **Phases Reference**: `phases.md` § Phase 5 (Tasks 5.1 through 5.22)

---

## 2. Key Modules to Build & Upgrade

### Part 1: External Skill Retriever (`harness/skill_retriever.py`)
1. **`SkillCache`**:
   - Location: `.harness/skill_cache/{sha256_hash}.json`
   - Cache key: `SHA256(f"{source_type}:{query.strip().lower()}")`
   - 24-hour TTL validation (`CACHE_TTL_HOURS = 24`)
   - Instant cache hit (< 10ms), returns content without network/disk reload overhead.
2. **`RelevantSectionExtractor`**:
   - Scores subsections/paragraphs against the query via token frequency / BM25.
   - Truncates and summarizes to `max_tokens` (default 500 tokens).
3. **`SWEBenchTrajectoryIndex`**:
   - Curated local index of common software engineering bug patterns and fixes (e.g., off-by-one, null checking, type conversions, exception propagation, async deadlocks, division by zero).
   - Top-3 similarity search for matching patterns.
4. **`SkillRetriever`**:
   - Methods:
     - `fetch_skill(source_type: str, query: str, max_tokens: int = 400) -> str`
     - `prefetch_at_startup(repo_path: str, issue_plan: IssuePlan | None = None) -> dict[str, str]` (pre-fetches `README`, `CONTRIBUTING`, CI workflows, and test configs in parallel)
     - `get_swebench_trajectory(query: str, top_k: int = 3) -> str`
5. **Tool Integration**:
   - Connect `fetch_external_skill` in `ToolEngine` to `SkillRetriever`.

### Part 2: Telemetry Pipeline & Real-Time Dashboard (`harness/telemetry.py`)
1. **Schema Validation & Full 18+ Event Types**:
   - Support all 18 `EventType` enums: `TOOL_CALL`, `TOOL_RESULT`, `LLM_TURN_START`, `LLM_TURN_END`, `VERIFICATION_PHASE`, `RECOVERY_EVENT`, `PLAN_REVISION`, `SUBAGENT_SPAWN`, `SUBAGENT_RESULT`, `SKILL_FETCH`, `CONTEXT_COMPRESSION`, `ROLLBACK`, `CHECKPOINT`, `DONE`, `FAILED`, `INIT`, `PLAN_EMIT`, `DONE_CANDIDATE`, `SESSION_START`.
   - Ensure every field required by PRD §4.9.1 is present and typed.
2. **Cumulative Token & Cost Accounting**:
   - Update `tokens_cumulative` and `cost_cumulative_usd` with strict invariance (cumulative equals sum of past events).
3. **Real-Time Cost Dashboard (`--verbose` mode)**:
   - Formatted per PRD §4.9.2:
     ```
     [ZENITH] Step {step} | Agent: {agent} | Tool: {tool}
       Tokens: {in} in + {out} out = {total} this turn
       Cost:   ${turn_cost:.4f} this turn | ${cum_cost:.4f} cumulative
       Context: {used} / {budget} tokens ({pct:.1f}% full)
       Status: {status}
       ─────────────────────────────────────────────
       [ZENITH] Session total: {cum_tokens:,} tokens | ${cum_cost:.4f} | {elapsed} elapsed
     ```
4. **Session ID Generation**:
   - Unique per session: `sess-YYYYMMDD-{uuid[:6]}`.

### Part 3: Auto-Report Generator (`harness/report_generator.py`)
Compiles `telemetry.jsonl` into `.harness/report.md` with all 8 mandatory sections:
1. **Executive Summary**: Status, Total Steps, Wall-Clock Time, Tokens, Cost, Recovery Events count, Subagents Used.
2. **Step-by-Step Timeline**: Table of all steps, agents, tools, results, tokens, and cost.
3. **Recovery Events**: Table of triggered error codes, recovery actions, and outcomes.
4. **Verification Results**: Table of all 6 verification phases (`SYNTAX`, `LINT`, `REPRO_TEST`, `REGRESSION`, `DIFF_AUDIT`, `SIDE_EFFECT`) with status and details.
5. **Final Diff Applied**: Fenced `diff` code block from git diff.
6. **Agent Decisions Log**: Key plan decisions and reasoning excerpts extracted from telemetry events.
7. **Token & Cost Breakdown**: Per-agent and per-phase breakdown table.
8. **Lessons Learned**: Embedded working memory summary and failed approach post-mortem.

**Crash-Proof Guarantee**:
- Generated on any outcome: `PASS`, `FAIL`, or `PARTIAL (STEP_LIMIT / PLAN_REVISION_LIMIT)`.

---

## 3. Step-by-Step Implementation Plan

### Step 1: `harness/skill_retriever.py`
- Build `SkillCacheEntry`, `SkillCache`, `RelevantSectionExtractor`, `SWEBenchTrajectoryIndex`, and `SkillRetriever`.
- Implement `fetch_skill`, `prefetch_at_startup`, and caching with 24h TTL.
- Wire into `harness/tool_engine.py` for `fetch_external_skill`.

### Step 2: Telemetry Enhancement (`harness/telemetry.py`)
- Enhance `TelemetryWriter` to support full event validation, dashboard formatting per PRD §4.9.2, and session tracking.
- Add helper logging methods for all event types (`log_verification_phase`, `log_recovery_event`, `log_skill_fetch`, `log_subagent`, etc.).

### Step 3: `harness/report_generator.py`
- Implement `ReportGenerator` class reading `telemetry.jsonl`, `context_summary.md`, and git diff.
- Format all 8 sections cleanly according to PRD §4.9.3.
- Ensure graceful handling of missing or partial telemetry data.

### Step 4: Orchestrator & CLI Integration
- Wire `prefetch_at_startup` into `Orchestrator.run()` or `cli.py` before Turn 1.
- Wire `ReportGenerator.generate()` into `Orchestrator.run()` `finally:` block so report generation never fails or gets skipped.
- Expose `--verbose` dashboard in CLI and Orchestrator.

### Step 5: Test Suite
- `tests/test_skill_retriever.py`
- `tests/test_telemetry_full.py`
- `tests/test_report_generator.py`
- `tests/test_p5_e2e.py`
- Full verification: `pytest -v`, `ruff check harness/ tests/`.
