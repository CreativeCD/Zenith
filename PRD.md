Refined PRD — SOTA Autonomous Coding-Agent Harness
Event: AI Harness Hackathon 2026 (LCC / Devclub) · Duration: 24 Hours
Status: Authoritative Master PRD (v2.0 Refined)
System Rule: If code and this file disagree, code must be updated to align with this document.

1. Mission & Philosophy
"You are not building an LLM wrapper. You are building the cognitive software engineering operating system around a foundation model."

Standard foundation models are powerful but brittle. They hallucinate paths, generate broken diffs, truncate outputs, lose long-term context, and self-report false success. The harness is the production-grade orchestration engine—tooling, state machine, context management, test verification, self-healing recovery, and financial/performance telemetry—that transforms a raw text-only model into an autonomous, reliable software engineer capable of solving real GitHub issues in arbitrary codebases.

2. Core Architecture (The 6-Layer Modular Harness)

                       ┌──────────────────────────────────────────┐
                       │            GitHub Issue Text             │
                       └────────────────────┬─────────────────────┘
                                            │
                                            ▼
                       ┌──────────────────────────────────────────┐
                       │   [1] Issue Triaging & Planning Engine   │
                       └────────────────────┬─────────────────────┘
                                            │
                                            ▼
 ┌──────────────────────────────────────────────────────────────────────────────────────┐
 │                              [2] Orchestrated Agent Loop                             │
 │  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────────┐  │
 │  │     PLAN     ├────►│     ACT      ├────►│   OBSERVE    ├────►│     REFLECT     │  │
 │  └──────────────┘     └──────┬───────┘     └──────────────┘     └─────────┬───────┘  │
 │                              │                                            │          │
 └──────────────────────────────┼────────────────────────────────────────────┼──────────┘
                                │                                            │
                                ▼                                            ▼
 ┌───────────────────────────────────────────────┐     ┌────────────────────────────────┐
 │             [3] Hardened Tool Engine          │     │    [4] Context & Memory Mgr    │
 │ • search_code   • read_file_range             │     │ • Token Budget Enforcer        │
 │ • apply_patch   • run_test_suite              │     │ • Rolling Summarizer           │
 │ • run_bash      • git_rollback                │     │ • Observation Truncator        │
 └──────────────────────┬────────────────────────┘     └────────────────────────────────┘
                        │
                        ▼
 ┌───────────────────────────────────────────────┐     ┌────────────────────────────────┐
 │     [5] Verification & Quality Gate           │◄────┤  [6] Recovery & Circuit        │
 │ • Test exit code 0 ground truth               │     │      Breaker Engine            │
 │ • Linter / Syntax checks                      │     │ • Anti-Loop Detection          │
 │ • Unintended side-effect check                │     │ • Error Taxonomy & Fallbacks   │
 └──────────────────────┬────────────────────────┘     └────────────────────────────────┘
                        │
                        ▼
 ┌───────────────────────────────────────────────┐
 │   [7] Telemetry, Cost Accounting & Report     │
 │ • JSONL Stream  • report.md Generator         │
 └───────────────────────────────────────────────┘
3. Deep-Dive Layer Specifications
Layer 1: Issue Parsing & Semantic Repository Navigator
Structured Issue Extraction: Parses issue title/body into a structured payload containing:
primary_goal: High-level task objective.
acceptance_criteria: Extracted bullet points or explicit test expectations.
suspected_files: Inferred paths, functions, or components mentioned in traceback or issue text.
reproduction_hint: Stack traces or reproduction instructions.
Lightweight Repo Indexing:
Generates a cached, token-cheap repository outline (file_tree.txt + top-level module symbols) upon startup.
Prevents the agent from dumping entire directories or large code files into the context window.
Layer 2: Tooling Suite & Atomic Execution Engine
Every tool call is wrapped in a strict JSON schema, validated before execution, and guaranteed atomic.

Tool Name	Parameters	Behavior & Safeguards
search_code	query, path_pattern, regex	Wraps ripgrep. Returns max 50 matches with 2 lines of context. Sanitizes input.
list_dir	path, recursive (bool)	Lists files up to depth 3 with file sizes. Excludes .git, node_modules, venv, __pycache__.
read_file_range	file_path, start_line, end_line	Reads specified line range. Hard capped at 300 lines per read to protect context budget.
apply_patch	patch_string or target_file, old_snippet, new_snippet	Dual-Mode Editor: Primary via unified diff / git apply. Fallback via exact block replacement with AST sanity check.
run_test_suite	test_path (optional), flags	Executes repo test runner (pytest/jest/unittest). Returns exit code, test count, passing/failing tests, and truncated stack traces.
run_bash_sandboxed	command, timeout_sec	Executes inside isolated subprocess with strict 30s timeout, memory limit, and disallowed command blocklist (rm -rf /, curl, sudo, chmod).
git_rollback	file_path (optional)	Instantly resets modified files to HEAD. Erases bad edits cleanly without context residue.
Layer 3: Context Manager & Memory Architecture
Token Budget Manager: Maintains strict token ceilings (e.g., 32k prompt window).
Observation Truncation Policy: Long tool outputs (e.g. 1000 lines of test failures) are automatically truncated:
Retains head (first 20 lines) and tail (last 40 lines containing error trace).
Summarizes middle: [... 940 lines of passing tests omitted ...].
Rolling Summarizer:
When context usage exceeds 70% threshold, older conversation turns are summarized into a concise .harness/context_summary.md state.
System prompt always includes: (1) System Persona, (2) Active Issue Goal, (3) Compressed Working Memory, (4) Recent N turns.
Layer 4: Multi-Stage Ground Truth Verification Layer
Ground Truth Rule: The model's opinion that a bug is fixed is UNTRUSTED. Verification relies exclusively on deterministic system exit codes.
Verification Pipeline:
Syntax Check: Parse edited files through language parser (e.g. python -m py_compile).
Reproduction Test Run: Run specific test associated with issue/bug.
Full Regression Test Run: Run full repo test suite to ensure zero regressions.
Diff Audit: Verify git diff contains only intended modifications without accidental file corruptions.
Layer 5: Recovery, Guardrails & Self-Healing Loop
Anti-Loop Circuit Breaker:
Keeps sliding hash window of last 5 tool calls + arguments.
If agent repeats exact same call with exact same parameters 2x, harness injects a mandatory Strategy Shift Warning:
"Loop detected: You have called tool 'apply_patch' with identical input twice and failed. You MUST step back, run git_rollback, and inspect surrounding context before making another edit."

Error Taxonomy & Auto-Remediation:
PATCH_FAILED: Auto-trigger file re-read around target line offsets + fallback to exact snippet replacement.
TEST_FAILED: Auto-feed exact stack trace + failing test file location directly into next reflection prompt.
TIMEOUT: Auto-kill subprocess and instruct agent to split command or run target test file only.
MAX_STEPS_EXCEEDED: Graceful exit with rollback to preserve repo sanity, logging STATUS: STEP_LIMIT_REACHED.
Layer 6: Telemetry, Financial Accounting & Auto-Reporting
Structured Event Logging (.harness/telemetry.jsonl):
Append-only log recording every turn, tool invocation, token count (input/output/total), cost ($ USD), latency (ms), error type, and recovery attempt.
Auto-Generated Execution Report (report.md):
Compiled automatically post-run from telemetry stream. Includes:
Executive Summary & Success Status (PASS / FAIL).
Total Cost ($), Total Tokens, Total Wall-Clock Time.
Step-by-step Timeline with error recovery annotations.
Final Unified Diff applied.
4. Hackathon Rubric & Specification Mapping
#	Official Rubric Line	Harness Implementation Engine	Verified Criteria
1	Understand SE Issue	IssueParser extracts goal, criteria, suspected files into structured JSON before first LLM call.	Pre-action JSON artifact exists in .harness/issue_plan.json.
2	Navigate Repository	search_code (ripgrep) + list_dir + lightweight repo tree outline. Never dumps full repo.	Tool telemetry proves no full-repo dumps occurred.
3	Intelligent Tool Use	Tool Call Deduplicator & Justification Enforcer requires reasoning parameter for every tool invocation.	Zero redundant file re-reads without intermediate edits.
4	Manage Context	ContextManager token budgeting + sliding window + observation truncation + rolling summarization.	Prompt token count never exceeds configured token cap.
5	Autonomous Recovery	RecoveryEngine taxonomy-based retry, anti-loop circuit breaker, auto git rollback on repeated failures.	Agent recovers from test/patch failures without human intervention.
6	Verified Code Changes	VerificationLayer runs git apply, pytest/unittest, and linter. Only exit code 0 marks task DONE.	git status clean + test suite passes 100%.
7	Efficiency & Telemetry	TelemetryTracker streams JSONL events and generates report.md with total token & financial cost.	report.md generated with cost/latency breakdown.
5. Non-Functional & Evaluator Compliance Requirements
Makefile Directives:
make setup: Creates virtual environment (.venv), installs all dependencies cleanly offline/online.
make run: Reads issue text/repo path from CLI args or default evaluation paths, launches harness.
make test: Runs harness unit & integration test suite.
make clean: Removes caches, logs, .venv, temporary test artifacts.
Environment & Security Compliance:
AI_API_KEY read strictly via os.environ.get("AI_API_KEY"). Never hardcoded, logged, or written to disk.
.env.example provided for developer convenience; no live secrets committed.
Model Configuration:
Model name, base URL, temperature, and seed declared in config.yaml or harness_config.py.
Temperature pinned to 0.0 or low value for maximum determinism and reproducibility.
6. Execution Command Line Interface (CLI)
The submission exposes a clean CLI via make run or python -m harness.cli:

bash

# Basic usage against a target repository and issue file
make run REPO_PATH=/path/to/target_repo ISSUE_PATH=/path/to/issue.txt
# Direct CLI usage with options
python -m harness/cli \
  --repo /path/to/target_repo \
  --issue /path/to/issue.txt \
  --max-steps 25 \
  --model gemini-2.5-flash \
  --verbose
7. 24-Hour Implementation Plan & Milestones

 [0h - 2h] Foundation & Infrastructure
 ├── Core CLI skeleton & Makefile (make setup/run/test/clean)
 ├── Config parser, logging setup, telemetry JSONL writer
 └── Dumb tool stubs & baseline test suite
 [2h - 6h] Hardened Tooling Engine & Model Interface
 ├── Implement search_code, read_file_range, apply_patch, run_test_suite, run_bash
 ├── Wire structured function calling to prescribed model API
 └── Validate single-turn tool calling against toy repository
 [6h - 10h] Verification & Recovery System
 ├── Build Multi-Stage Verification Gate (exit code 0 validator)
 ├── Implement Failure Taxonomy & Error Feedback loop
 └── Build Anti-Loop Circuit Breaker & Git Rollback mechanism
 [10h - 14h] Context Manager & Memory Architecture
 ├── Token Budgeting & Sliding Window Context Manager
 ├── Observation Truncation Engine (head/tail logs)
 └── Rolling Summarizer for long-horizon tasks
 [14h - 18h] Telemetry & Auto-Report Generator
 ├── Real-time JSONL event stream writer
 ├── Markdown report generator (`report.md`) with cost breakdown
 └── End-to-end integration run on complex multi-file bug
 [18h - 21h] Stress Testing & Unseen Repo Benchmarks
 ├── Run harness against 5 distinct open-source repository bugs
 ├── Tweak recovery prompts, line offsets, patch fallbacks based on real failures
 └── Optimize token efficiency and step count
 [21h - 24h] Freeze, Verification & Clean Clone Dry Run
 ├── Full repo dry run in fresh container / clean clone
 ├── Audit README, Makefile, .env.example compliance
 └── Code freeze & submission tag creation
8. Risk Register & Loophole Mitigations
Risk	Cause	Mitigation Strategy	Owner / Status
Infinite Retry Loop	Model repeatedly attempts failing patch	Anti-Loop detector (hash window) forces strategy shift or auto-rollback after 2 identical attempts.	Lead Architect / Active
Context Overflow	Massive test output or reading large files	Hard cap on read_file_range (300 lines) + head/tail observation truncation.	Context Spec / Active
Hallucinated File Paths	Model guesses non-existent file locations	Pre-tool path validation against repo tree; returns clear file-not-found error to model.	Tooling Spec / Active
Broken Patch Offsets	Unified diff line numbers shifted	Dual-mode editor: unified diff primary, exact block replace with AST check fallback.	Tooling Spec / Active
Unsafe Command Execution	Model attempts destructive bash command	Sandboxed subprocess with command blocklist (rm -rf, curl, sudo) & 30s timeout.	Security Spec / Active
False Success Self-Report	Model claims bug fixed without testing	Exit code of target repo test runner is sole arbiter of DONE status. Model text ignored.	Verifier Spec / Active
Clean Clone Setup Failure	Environment or dependency mismatch	Automated verification in Docker/clean virtualenv during dry run stage.	DevOps Spec / Active
9. Success Metrics & Evaluator Benchmarks
Pass Rate: % of benchmark issues resolved with exit code 0 test passing. Target: >85%.
Autonomy Rate: % of runs requiring zero human intervention after issue input. Target: 100%.
Recovery Rate: % of tool/patch errors successfully self-healed by harness. Target: >80%.
Token Efficiency: Average token usage per resolved issue. Target: <50k total tokens.
Clean Clone Success: make setup && make run succeeds out-of-the-box on clean environment. Target: 100% Compliance.