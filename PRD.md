# Zenith — SOTA Autonomous Coding-Agent Harness
### Product Requirements Document (v4.0 — Elite Master)

```
Event    : LCC × DevClub AI Coding Harness Hackathon 2026
Duration : 24 Hours  |  Team: Zenith
Version  : 4.0 — Elite Master (expanded from v3.0)
Status   : AUTHORITATIVE MASTER PRD — All code must align to this document
Rule     : If code and this document disagree, code MUST be updated.
Theme    : Same model. Different harnesses. Your engineering makes the difference.
```

---

## Table of Contents

1. [Mission & Philosophy](#1-mission--philosophy)
2. [Hackathon Compliance Map](#2-hackathon-compliance-map)
3. [System Architecture — 9-Layer Cognitive Harness](#3-system-architecture)
4. [Layer Deep-Dives](#4-layer-deep-dives)
5. [Prompt Engineering Specification](#5-prompt-engineering-specification)
6. [Token Optimization Strategy](#6-token-optimization-strategy)
7. [State Machine & Formal Control Flow](#7-state-machine--formal-control-flow)
8. [Inter-Layer Data Contracts (Schemas)](#8-inter-layer-data-contracts)
9. [External Resources & Skill Acquisition](#9-external-resources--skill-acquisition)
10. [Model-Specific Optimization](#10-model-specific-optimization)
11. [Harness Test Strategy](#11-harness-test-strategy)
12. [CLI & Makefile Specification](#12-cli--makefile-specification)
13. [Security & Compliance](#13-security--compliance)
14. [Configuration Specification](#14-configuration-specification)
15. [Non-Functional Requirements](#15-non-functional-requirements)
16. [Risk Register & Mitigations](#16-risk-register--mitigations)
17. [Success Metrics & Benchmarks](#17-success-metrics--benchmarks)
18. [Glossary](#18-glossary)

---

## 1. Mission & Philosophy

> *"You are not building an LLM wrapper. You are building the cognitive software engineering operating system around a foundation model."*

### 1.1 Problem Statement (from Hackathon Brief)

Build an **autonomous coding-agent harness** around a standardized foundation model that can:
- **Understand** software-engineering tasks from raw GitHub issues
- **Navigate** an existing repository without dumping raw files
- **Intelligently use tools** with zero redundancy and full justification
- **Manage context and memory** under hard token budgets
- **Orchestrate model interactions** through a principled multi-stage loop
- **Recover autonomously** from all failure modes
- Produce **correct, verified changes** with **efficient use of resources**

The harness must transform a raw foundation model into an autonomous software engineer capable of solving real GitHub issues across arbitrary codebases. **The model is fixed; the harness is the differentiator.**

### 1.2 Core Design Principles

| Principle | Implementation Mandate |
|---|---|
| **Correctness First** | Only deterministic exit codes from the test runner decide `DONE`. Model claims are untrusted and ignored. |
| **Evidence Over Claims** | Every action, decision, and assertion is logged and traceable in `telemetry.jsonl`. |
| **Efficiency Matters** | Token budgets are hard-enforced. Redundant reads are forbidden. Context is surgically compressed. |
| **Semantic Over Syntactic** | AST/LSP symbol navigation instead of raw grep+file dumps. Symbols, not files. |
| **Fail Gracefully, Always** | Every error has a taxonomy-based recovery path. No silent failures. Auto-rollback on catastrophe. |
| **Skill Reuse > Reinvention** | Reference implementations (SWE-agent, Agentless, OpenHands) inform design via indexed skill libraries. |
| **Minimal Footprint** | The harness never touches files outside REPO_PATH. Every tool call is the least-privileged option. |
| **Observability by Default** | Nothing happens silently. Every turn, cost, decision, and failure is emitted to the JSONL stream in real time. |
| **Reproducibility** | Temperature 0, seeded runs. Same input → same output. Test harness is independently verifiable. |

### 1.3 Competitive Differentiation Strategy

What separates Zenith from a naive ReAct loop:

```
Naive Agent Loop               Zenith Harness
─────────────────              ──────────────────────────────────────
Full file reads            →   Symbol-level AST reads (80-95% token saving)
Monolithic context         →   5-section structured prompt with hard budgets
Single-agent ReAct         →   Multi-agent pool with context isolation
Grep-based navigation      →   Semantic embedding ranker + LSP call graph
Self-declared DONE         →   6-phase deterministic VerificationGate
Hope-based retry           →   Taxonomy-driven RecoveryEngine with rollback
No loop detection          →   Hash-window circuit breaker (5-call window)
Fetch docs on every run    →   24h skill cache with startup pre-fetch
Flat telemetry log         →   Structured JSONL + auto report.md generator
Fixed step limit exit      →   Graceful degradation with partial-result report
```

---

## 2. Hackathon Compliance Map

| # | Official Rubric Requirement | Zenith Engine | Verification Criterion |
|---|---|---|---|
| 1 | **Understand SE Issue** | `IssueParser` → `IssuePlan` JSON (goal, criteria, files, reproduction, complexity) | `.harness/issue_plan.json` exists before turn 1 |
| 2 | **Navigate Repository** | `RepoIntelligenceEngine`: Tree-sitter AST + ripgrep + embedding ranker + LSP call-graph | Telemetry shows zero unfiltered full-directory reads |
| 3 | **Intelligent Tool Use** | Mandatory `reasoning` field. `ToolCallDeduplicator`. Least-privilege tool selection. | Zero identical sequential calls without intermediate edit |
| 4 | **Manage Context** | `ContextManager`: 5-section prompt, hard ceiling, rolling summarizer, head/tail truncation | Prompt token count ≤ `MAX_CONTEXT_TOKENS` every turn |
| 5 | **Orchestrate Model** | PLAN→ACT→OBSERVE→REFLECT state machine. Multi-agent delegation by complexity score. | Coherent multi-turn plans. Plan revisions on failure. |
| 6 | **Autonomous Recovery** | `RecoveryEngine`: 10-code taxonomy, circuit breaker, git rollback, strategy-shift injection | Self-heals from all defined failure modes without human input |
| 7 | **Verified Code Changes** | 6-Phase `VerificationGate`: Syntax→Lint→Repro→Regression→Diff Audit→Side-Effect | `git status` clean + test suite 100% pass at `DONE` |
| 8 | **Resource Efficiency** | `TokenOptimizer` + 9-technique cost reduction + `ExternalSkillRetriever` cache | Avg tokens/issue < 40k. Cost in `report.md`. |

---

## 3. System Architecture

### 3.1 High-Level 9-Layer Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                     INPUT: GitHub Issue Text                          │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  [L1] Issue Parsing & Semantic Planning Engine                        │
│  • Rule-based + LLM fallback extraction → IssuePlan JSON             │
│  • Acceptance criteria, reproduction hints, complexity scorer         │
│  • Task-adaptive planner: routes to single/multi-agent mode           │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  [L2] Repository Intelligence Engine                                  │
│  • Cached repo outline: file_tree.txt + module_symbols.json           │
│  • Lazy Tree-sitter AST index per language                            │
│  • Dependency graph (import/require chains)                           │
│  • Test map (source file ↔ test file)                                 │
│  • Semantic file ranker (FAISS embedding search)                      │
│  • Optional: LSP go-to-definition + real-time diagnostics             │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  [L3] Hardened Tool Engine (Atomic · Schema-Validated · Sandboxed)    │
│                                                                        │
│  Navigation:  list_dir · search_code · get_symbol · find_references   │
│  Edit:        read_file_range · apply_patch · write_file              │
│  Execution:   run_test_suite · run_bash_sandboxed                     │
│  VCS:         git_rollback · git_diff · git_status                    │
│  Knowledge:   fetch_external_skill                                    │
│                                                                        │
│  Guards: ToolCallDeduplicator · reasoning validator · path validator  │
└──────┬────────────────────────────────────────────────┬──────────────┘
       │                                                │
       ▼                                                ▼
┌─────────────────────────┐             ┌──────────────────────────────┐
│  [L4] Context &         │             │  [L6] External Skill &       │
│  Memory Manager         │             │  Knowledge Retriever          │
│                         │             │                              │
│  • 5-section prompt     │             │  • Startup pre-fetch          │
│  • Token budget enforce │             │  • SWE-bench trajectory index │
│  • Sliding window       │             │  • GitHub issue+PR pairs      │
│  • Rolling summarizer   │             │  • Official docs fetcher      │
│  • Observation truncate │             │  • 24h local cache (FAISS)    │
└─────────────────────────┘             └──────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  [L5] Multi-Agent Orchestration Loop                                  │
│                                                                        │
│  State machine: PLAN ──► ACT ──► OBSERVE ──► REFLECT ──► loop/DONE   │
│                                                                        │
│  Subagent pool (isolated contexts):                                    │
│    Scout Agent  │  Architect Agent  │  Coder Agent  │  Critic Agent   │
│                                                                        │
│  Plan revision protocol (max 3) → RecoveryEngine escalation           │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  [L7] 6-Phase Verification & Quality Gate                             │
│  P1: Syntax · P2: Lint · P3: Repro Test · P4: Full Regression        │
│  P5: Diff Audit · P6: Side-Effect Check                               │
│  → VerificationResult JSON → PASS (DONE) or FAIL (RecoveryEngine)    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │                    ▲
                               │    ┌───────────────┘ recovery feedback
                               ▼    │
┌──────────────────────────────────────────────────────────────────────┐
│  [L8] Recovery, Self-Healing & Circuit Breaker                        │
│  • 5-call hash-window anti-loop circuit breaker                       │
│  • 10-code error taxonomy with auto-remediation strategies            │
│  • Graceful degradation chain: retry → plan revision → graceful exit  │
│  • Auto git rollback on all catastrophic error states                 │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  [L9] Telemetry, Cost Accounting & Report Generator                   │
│  • Append-only JSONL: every turn, tool, token, cost, latency          │
│  • Real-time cost dashboard (stdout if --verbose)                     │
│  • Auto-compiled report.md: 8 sections, full diff, verification log  │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 Component Dependency Graph

```
cli.py
 ├── config.py
 ├── issue_parser.py       → [L1]
 ├── repo_intelligence.py  → [L2]
 ├── orchestrator.py       → [L5]  (drives main loop)
 │    ├── context_manager.py  → [L4]
 │    ├── tool_engine.py      → [L3]
 │    ├── skill_retriever.py  → [L6]
 │    ├── verification.py     → [L7]
 │    └── recovery.py         → [L8]
 ├── telemetry.py          → [L9]
 └── report_generator.py   → [L9]
```

### 3.3 Request/Response Lifecycle (Single Turn)

```
1. Orchestrator builds prompt via ContextManager (5 sections, within budget)
2. Prompt sent to foundation model (structured function-calling mode)
3. Model returns: { reasoning, tool_name, tool_args } OR { status: DONE_CANDIDATE }
4. ToolCallDeduplicator checks fingerprint cache → block or allow
5. reasoning field validator → reject if missing
6. path validator → reject if outside REPO_PATH
7. Tool executes (sandboxed, with timeout)
8. ToolResult truncated by ContextManager observation policy
9. TelemetryWriter appends event (tokens, cost, latency, result)
10. If DONE_CANDIDATE → VerificationGate (6 phases)
    → PASS: flush telemetry, generate report.md, exit 0
    → FAIL: RecoveryEngine classifies error, injects remediation, re-enters REFLECT
11. If RecoveryEngine cannot resolve → GracefulExit → partial report.md, exit 1
```

---

## 4. Layer Deep-Dives

### 4.1 Layer 1: Issue Parsing & Semantic Planning Engine

**Responsibility:** Transform raw GitHub issue text into a structured, machine-actionable `IssuePlan` before ANY LLM inference is performed on the actual coding task.

#### 4.1.1 Two-Pass Extraction Strategy

**Pass 1: Rule-Based Extraction (0 LLM tokens)**

Regex and heuristic patterns extract with confidence scores:

| Field | Pattern | Confidence if matched |
|---|---|---|
| `suspected_files` | Python/JS file paths, module names in traceback | 0.90 |
| `reproduction_hint` | Lines after "Steps to reproduce:" or traceback blocks | 0.95 |
| `error_type` | Exception class names (NullPointerException, KeyError...) | 0.92 |
| `test_filter` | Test function names in traceback (test_foo, test_bar) | 0.88 |
| `task_type` | Keywords: "fix", "bug", "regression", "add feature", "refactor" | 0.80 |

**Pass 2: LLM Extraction (triggered only if any field confidence < 0.75)**

Single lightweight prompt (< 500 tokens) fills only the low-confidence fields. Template:

```
Extract the following fields from this GitHub issue. Return JSON only.
Fields needed: {low_confidence_fields}
Issue text: {issue_text}
```

**Result:** For > 70% of issues, zero LLM tokens are spent on parsing.

#### 4.1.2 IssuePlan Schema (Full)

```json
{
  "issue_id": "string",
  "primary_goal": "One clear sentence. What must be fixed/built?",
  "task_type": "BUG_FIX | FEATURE | REFACTOR | TEST | DOCS | PERF",
  "acceptance_criteria": ["measurable criterion 1", "measurable criterion 2"],
  "suspected_files": [
    {
      "path": "src/auth/service.py",
      "confidence": 0.92,
      "reason": "Full module path in traceback line 3",
      "suspected_symbol": "authenticate"
    }
  ],
  "reproduction_hint": "python -m pytest tests/test_auth.py::test_null_token",
  "test_filter": "pytest tests/test_auth.py -k test_null_token",
  "error_type": "NullPointerException | KeyError | etc.",
  "complexity_estimate": "LOW | MEDIUM | HIGH",
  "estimated_steps": 12,
  "requires_external_knowledge": false,
  "language": "python | javascript | typescript | java | go | rust",
  "test_runner": "pytest | jest | unittest | cargo | go test",
  "parsing_confidence": 0.91,
  "parsing_method": "RULE_BASED | LLM_ASSISTED"
}
```

#### 4.1.3 Task-Adaptive Routing

| Complexity | Task Types | Agent Mode | Max Steps | Subagents Spawned |
|---|---|---|---|---|
| LOW | BUG_FIX, DOCS | `SINGLE_REACT` | 15 | None |
| MEDIUM | BUG_FIX, REFACTOR, TEST | `PLANNER_EXECUTOR` | 25 | Scout + Coder |
| HIGH | FEATURE, PERF, complex BUG_FIX | `MULTI_AGENT` | 40 | Scout + Architect + Coder + Critic |
| VERY_HIGH | Multi-file FEATURE, large REFACTOR | `MULTI_AGENT_DEEP` | 55 | Scout + Architect + Coder×N + Critic |

**Complexity Scoring Formula:**

```python
complexity_score = (
    len(suspected_files) * 2 +
    traceback_depth * 1.5 +
    (1 if requires_external_knowledge else 0) * 3 +
    (1 if 'cross_module' in error_context else 0) * 2 +
    (1 if task_type == 'FEATURE' else 0) * 4
)
# LOW: 0-4  |  MEDIUM: 5-9  |  HIGH: 10-16  |  VERY_HIGH: 17+
```

---

### 4.2 Layer 2: Repository Intelligence Engine

**Responsibility:** Build a token-cheap, semantically rich repo model. Never dump raw files into context.

#### 4.2.1 Index Architecture (Startup, Cached)

```
.harness/repo_index/
├── file_tree.txt              # Condensed directory tree, depth-4, excludes junk dirs
├── module_symbols.json        # Per-file: classes, functions, exports, line ranges
├── dependency_graph.json      # Directed import/require graph (module → [modules])
├── test_map.json              # Source file → covering test files
├── linter_baseline.json       # Pre-patch linter findings (for delta comparison)
├── test_baseline.json         # Pre-run failing tests (for regression detection)
└── embedding_index/           # FAISS index + metadata for semantic file ranking
    ├── index.faiss
    └── metadata.json          # Maps vector index → file path + symbol summary
```

**Generation strategy:**
- `file_tree.txt`: Walk with `pathlib`, filter exclusions, format as tree. < 500 tokens for 500-file repo.
- `module_symbols.json`: Tree-sitter parse per file, extract only top-level names + line offsets. < 1,500 tokens for 500-file repo.
- `embedding_index`: Embed each file's symbol summary (not full content). Use `sentence-transformers/all-MiniLM-L6-v2` (local, no API cost).
- All indices persisted in `.harness/repo_index/` and invalidated if `git status` shows changes.

#### 4.2.2 Tree-Sitter AST Engine

Supported languages and grammars:

| Language | Grammar Package | Key Queries |
|---|---|---|
| Python | `tree-sitter-python` | `function_definition`, `class_definition`, `import_statement` |
| JavaScript/TypeScript | `tree-sitter-javascript` / `tree-sitter-typescript` | `function_declaration`, `class_declaration`, `import_declaration` |
| Java | `tree-sitter-java` | `method_declaration`, `class_declaration`, `import_declaration` |
| Go | `tree-sitter-go` | `function_declaration`, `type_declaration`, `import_spec` |
| Rust | `tree-sitter-rust` | `function_item`, `struct_item`, `use_declaration` |

**Key operations exposed as tools:**
- `get_symbol(file, name)` → signature + docstring + line range (never full file)
- `find_references(file, name)` → call sites with N lines of context
- `get_imports(file)` → all imports/requires in the file
- `list_symbols(file)` → all top-level names + types in the file

#### 4.2.3 Semantic File Ranker

```python
RankingPipeline:
  1. Embed issue text using all-MiniLM-L6-v2
  2. Query FAISS index for top-20 nearest file summaries
  3. Re-rank by:
     a. Embedding cosine similarity (weight: 0.5)
     b. Exact path/symbol match from IssuePlan.suspected_files (weight: 0.3)
     c. Import distance from suspected_files in dependency graph (weight: 0.2)
  4. Return top-N (default N=5) as ranked FileSet
  5. FileSet → injected into SECTION 3 (Repo Context) of prompt
```

#### 4.2.4 LSP Integration (Optional Enhancement)

When a compatible language server is installed:

| Feature | Tool | Benefit |
|---|---|---|
| Go-to-definition | `textDocument/definition` | Resolves symbol across files without reading them |
| Find references | `textDocument/references` | Complete call graph without grep |
| Real-time diagnostics | `textDocument/publishDiagnostics` | Type errors visible before running tests |
| Hover info | `textDocument/hover` | Type signatures inline |

LSP is activated if found; harness degrades gracefully to Tree-sitter only if not available.

---

### 4.3 Layer 3: Hardened Tool Engine

**Responsibility:** Minimal, powerful, safe tool surface. Every tool: schema-validated, atomic, sandboxed, deduplicated, logged.

#### 4.3.1 Tool Interface Contract

Every LLM tool call MUST conform to this envelope:

```json
{
  "tool": "tool_name",
  "reasoning": "Why this tool? What specific information are you seeking?",
  "args": { ... }
}
```

Calls without `reasoning` are **rejected** with:
```
TOOL_ERROR: Missing required field 'reasoning'. Describe your intent before calling any tool.
```

#### 4.3.2 Complete Tool Specification

**Navigation Tools**

| Tool | Args | Behavior | Hard Limits |
|---|---|---|---|
| `list_dir` | `path`, `depth?=3`, `recursive?=false` | Lists files+dirs. Excludes: `.git`, `node_modules`, `venv`, `__pycache__`, `dist`, `build`, `.tox`. Shows sizes. | depth ≤ 4 |
| `search_code` | `query`, `path_pattern?`, `regex?=false`, `context_lines?=2`, `include_tests?=false` | Wraps ripgrep. Sanitizes query. Filters test/vendor unless `include_tests=true`. | 50 matches max |
| `get_symbol` | `file_path`, `symbol_name` | AST lookup: returns signature + docstring + line range. No full file. | output ≤ 50 lines |
| `find_references` | `file_path`, `symbol_name`, `context_lines?=3` | Returns all call sites with context. | 30 locations max |
| `get_imports` | `file_path` | Returns all import statements in file. | — |
| `list_symbols` | `file_path` | Returns all top-level names (class/fn) with line numbers. | — |

**Edit Tools**

| Tool | Args | Behavior | Hard Limits |
|---|---|---|---|
| `read_file_range` | `file_path`, `start_line`, `end_line` | Returns lines with line numbers. Validates path exists. | 250 lines max |
| `apply_patch` | `target_file`, `patch_string` OR `old_snippet`+`new_snippet` | Dual-mode: unified diff primary, exact block fallback. AST parse after apply. Atomic rollback on parse failure. | — |
| `write_file` | `file_path`, `content` | New files only. Refuses to overwrite. Creates parent directories. | Path must be within REPO_PATH |

**Execution Tools**

| Tool | Args | Behavior | Hard Limits |
|---|---|---|---|
| `run_test_suite` | `test_path?`, `test_filter?`, `flags?`, `timeout_sec?=120` | Runs configured test runner. Returns exit code + pass/fail counts + truncated trace. | 120s timeout; output: 80 lines |
| `run_bash_sandboxed` | `command`, `timeout_sec?=30` | Subprocess with `shell=False`. Hard timeout. Memory limit. Blocklist enforced. | 30s; 512MB; 200 lines output |

**VCS Tools**

| Tool | Args | Behavior |
|---|---|---|
| `git_rollback` | `file_path?` | Resets file (or all files if omitted) to HEAD. Telemetry: rollback event with reason. |
| `git_diff` | `file_path?` | Current diff vs HEAD. Capped at 500 lines. |
| `git_status` | — | Returns list of modified/added/deleted files vs HEAD. |

**Knowledge Tool**

| Tool | Args | Behavior | Hard Limits |
|---|---|---|---|
| `fetch_external_skill` | `source_type`, `query`, `max_tokens?=400` | Cache-first. Fetches from SWE-bench/docs/GitHub. Compresses to max_tokens. | 500 tokens; 24h cache |

#### 4.3.3 Tool Call Deduplicator

```
Fingerprint = SHA256(tool_name + canonical(args))

Algorithm:
  1. On each tool call, compute fingerprint
  2. Check recent_fingerprints ring buffer (capacity: 10 entries)
  3. If fingerprint in buffer AND no apply_patch/write_file since last occurrence:
     → Reject with DEDUP_BLOCKED message:
       "DEDUP: {tool}({args}) was already called at step {N}. File unchanged.
        Use your observation from step {N}. Do not re-read unchanged files."
  4. Else: add fingerprint to buffer, allow call
```

#### 4.3.4 Security Blocklist (Comprehensive)

```python
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",         # Recursive delete from root
    r"\|\s*sh\b",            # Pipe to shell
    r"\|\s*bash\b",          # Pipe to bash
    r"sudo\b",               # Privilege escalation
    r"chmod\s+[0-7]*7[0-7]{2}", # World-writable
    r"\bcurl\b",             # External network
    r"\bwget\b",             # External network
    r"\bdd\b",               # Disk destroyer
    r"\bmkfs\b",             # Filesystem formatter
    r">\s*/dev/sd",          # Write to block device
    r":()\{.*\|.*&.*\}",     # Fork bomb
    r"base64.*\|.*sh",       # Obfuscated shell
]
PATH_TRAVERSAL = r"\.\./|/\.\."  # Directory traversal
```

---

### 4.4 Layer 4: Token-Optimized Context & Memory Manager

**Responsibility:** Surgical context construction. Maximum information density per token. Hard ceiling never breached.

#### 4.4.1 5-Section Prompt Schema (Fixed Order, Fixed Budgets)

```
┌──────────────────────────────────────────────────────────────────┐
│ § SYSTEM PERSONA                        Budget: 300 tok (fixed)  │
│   Role: autonomous SE agent. Rules: reasoning required, tools    │
│   only, DONE_CANDIDATE signal format, no self-declared success.  │
├──────────────────────────────────────────────────────────────────┤
│ § ACTIVE ISSUE GOAL                     Budget: 200 tok (fixed)  │
│   primary_goal + acceptance_criteria only.                       │
│   NOT full issue text (too many tokens).                         │
├──────────────────────────────────────────────────────────────────┤
│ § REPO CONTEXT                          Budget: 1,000 tok (dyn)  │
│   Top-5 ranked file summaries (symbol signatures, NOT content).  │
│   + relevant external skill snippet (if applicable, ≤500 tok).  │
│   Trimmed by dropping lowest-ranking files first when tight.     │
├──────────────────────────────────────────────────────────────────┤
│ § COMPRESSED WORKING MEMORY             Budget: 800 tok (rolling)│
│   Structured summary of all turns > recent window.              │
│   Format: Goal | Files | Findings | Edits | Tests | Strategy.   │
│   Re-compressed (lossy) if exceeds 800 tok.                     │
├──────────────────────────────────────────────────────────────────┤
│ § RECENT TURNS (raw)                    Budget: 4,000 tok (dyn)  │
│   Last N turns verbatim (N adjusted to fit budget).             │
│   Oldest raw turns moved to Working Memory when tight.           │
└──────────────────────────────────────────────────────────────────┘
  Response Reserve:   4,000 tok
  ─────────────────────────────
  HARD CEILING:      32,000 tok  (configurable)
```

#### 4.4.2 Dynamic Budget Adjustment Algorithm

```python
def build_prompt(turns, working_memory, repo_context, issue_goal):
    fixed = PERSONA_TOKENS + GOAL_TOKENS   # 500 tok fixed
    reserve = RESPONSE_RESERVE             # 4,000 tok reserved
    available = MAX_CONTEXT - fixed - reserve  # 27,500 tok dynamic

    # Priority order: recent_turns > working_memory > repo_context
    recent_turns_tokens = count_tokens(turns[-N:])

    while recent_turns_tokens > RECENT_TURNS_BUDGET:
        # Compress oldest raw turn into working memory
        working_memory = compress_turn(turns[-N], working_memory)
        N -= 1
        recent_turns_tokens = count_tokens(turns[-N:])

    if count_tokens(working_memory) > WORKING_MEMORY_BUDGET:
        working_memory = lossy_compress(working_memory)

    remaining = available - recent_turns_tokens - count_tokens(working_memory)
    repo_context = trim_to_budget(repo_context, remaining)

    return assemble_prompt(PERSONA, issue_goal, repo_context, working_memory, turns[-N:])
```

#### 4.4.3 Observation Truncation Policy (Detailed)

| Scenario | Head | Tail | Separator |
|---|---|---|---|
| Output < 100 lines | Full verbatim | — | — |
| Output 100–300 lines | First 25 lines | Last 60 lines | `[... {N} lines omitted ...]` |
| Output 300–1000 lines | First 20 lines | Last 50 lines | `[... {N} lines omitted. Key: {auto_summary} ...]` |
| Output > 1000 lines | First 15 lines | Last 40 lines | `[... {N} lines omitted. Summary: {LLM_compress} ...]` |
| Test output (any length) | Exit code + FAILED test names | First exception traceback only | `[... passing tests omitted ...]` |
| Patch output | Full (patches are short) | — | — |

#### 4.4.4 Rolling Summarizer Implementation

**Trigger:** Context usage ≥ 70% of `MAX_CONTEXT_TOKENS`.

**Compression prompt** (sent as a separate, low-temperature call — NOT part of main agent turn):

```
You are compressing an autonomous coding agent's working memory. Be lossless for:
decisions made, edits applied, test results, lessons learned.
Be lossy for: reasoning steps, repeated observations, verbose tool outputs.

OUTPUT FORMAT (strict, 600 tokens max):
## Goal
{one sentence}
## Files Examined
{file: key finding} (one per line, max 8)
## Edits Applied
{file:line → what changed} (one per line, max 5)
## Test Status
{PASS/FAIL: specific test names and error codes}
## Current Strategy
{one sentence: what we're doing next and why}
## Lessons Learned
{bullet list of failed approaches and why they failed}

[TURNS TO COMPRESS]
{oldest_50pct_of_turns}
```

---

### 4.5 Layer 5: Multi-Agent Orchestration Loop

**Responsibility:** Drive the full reasoning-to-action cycle. Delegate via subagent pool for complex tasks.

#### 4.5.1 State Machine (Formal)

```
States: INIT | PLAN | ACT | OBSERVE | REFLECT | DONE_CANDIDATE | DONE | FAILED

Transitions:
  INIT        → PLAN          (always, after IssuePlan + RepoIndex ready)
  PLAN        → ACT           (plan emitted as ordered step list)
  ACT         → OBSERVE       (tool call executed)
  OBSERVE     → REFLECT       (tool result received and truncated)
  REFLECT     → ACT           (next step chosen)
  REFLECT     → PLAN          (plan revision triggered, revision_count < max)
  REFLECT     → DONE_CANDIDATE (agent emits {"status": "DONE_CANDIDATE"})
  DONE_CANDIDATE → DONE       (VerificationGate: all 6 phases PASS)
  DONE_CANDIDATE → REFLECT    (VerificationGate: any phase FAIL → RecoveryEngine)
  REFLECT     → FAILED        (revision_count >= max OR loop_count >= max)
  FAILED      → (GracefulExit: rollback + partial report)

Guards:
  ACT:             step_count < max_steps
  PLAN (revision): revision_count < max_plan_revisions
  REFLECT→ACT:     loop_count < max_loop_count per step
```

#### 4.5.2 Structured Output Contracts

**PLAN output** (agent must emit this exact structure):

```json
{
  "plan": [
    {"step": 1, "description": "...", "tool_prediction": "search_code", "expected_outcome": "..."},
    {"step": 2, "description": "...", "tool_prediction": "get_symbol",   "expected_outcome": "..."}
  ],
  "estimated_total_steps": 8,
  "risk_factors": ["patch may affect related auth module"],
  "rollback_checkpoints": [3, 6]
}
```

**DONE_CANDIDATE output** (agent must emit this structure to exit):

```json
{
  "status": "DONE_CANDIDATE",
  "confidence": 0.95,
  "evidence": [
    "Applied null-check patch to src/auth/service.py line 78",
    "Reproduction test test_null_token passed",
    "No other files modified"
  ],
  "files_modified": ["src/auth/service.py"]
}
```

#### 4.5.3 Subagent Pool Architecture

```
Orchestrator
│  Full context: IssuePlan + RepoIndex + plan history
│  Responsibilities: routing, plan revision, final verification trigger
│
├── Scout Agent (spawned for MEDIUM+ complexity)
│   Context budget: 8,000 tokens
│   Input: IssuePlan + file_tree.txt + module_symbols.json
│   Output: .harness/scout_report.md
│   Format:
│     ## Relevant Files (ranked)
│     ## Key Symbols & Call Paths
│     ## Dependency Chain
│     ## Suspected Root Cause Location
│     ## Recommended Fix Strategy
│
├── Architect Agent (spawned for HIGH complexity)
│   Context budget: 6,000 tokens
│   Input: IssuePlan + scout_report.md ONLY
│   Output: .harness/architecture_plan.md
│   Format:
│     ## Fix Strategy (step-by-step)
│     ## Files to Modify
│     ## Risk Factors
│     ## Test Verification Plan
│
├── Coder Agent (one per sub-task; spawned for MEDIUM+)
│   Context budget: 10,000 tokens
│   Input: architecture_plan.md + read_file_range of TARGET FILE ONLY
│   Output: .harness/patch_{file}_{step}.diff
│   Constraint: Modifies ONLY the assigned file. No scope creep.
│
└── Critic Agent (spawned after all Coder patches)
    Context budget: 6,000 tokens
    Input: IssuePlan + all patches + test results
    Output: .harness/critic_report.md
    Format:
      ## Correctness Assessment
      ## Edge Cases Uncovered
      ## Potential Regressions
      ## Recommendation: APPROVE | REVISE (with specific guidance)
```

#### 4.5.4 Rollback Checkpoints

The Planner designates `rollback_checkpoints` in the plan (e.g., after steps 3, 6).

- At each checkpoint, `git_diff` is captured and stored as `.harness/checkpoint_{N}.diff`.
- On `PLAN_REVISION` or `GracefulExit`, the harness rolls back to the most recent safe checkpoint (not necessarily HEAD) to preserve partial useful work.

---

### 4.6 Layer 6: External Skill & Knowledge Retriever

**Responsibility:** Fetch, compress, and cache relevant external knowledge. Zero per-query LLM cost for cache hits.

#### 4.6.1 Retrieval Sources & Trigger Conditions

| Source | Content Type | Trigger | Fetch Method |
|---|---|---|---|
| **SWE-bench trajectories** | Successful fix patterns for similar bugs | `task_type=BUG_FIX` AND `parsing_confidence < 0.75` | Local embedding index of trajectory corpus |
| **GitHub API: issue+PR pairs** | Real-world fix for same library | Library name extracted from traceback | GitHub Search API (rate-limited, cached) |
| **Official documentation** | API reference, usage examples | Agent calls `fetch_external_skill(source_type="DOCS", ...)` | HTTP fetch → section extraction → compress |
| **OpenHands/SWE-agent strategies** | Tool-use patterns from SOTA agents | `complexity_estimate = HIGH` | Local curated knowledge base |
| **Repo CONTRIBUTING.md / README.md** | Project conventions, test commands | Always — startup pre-fetch | Direct file read (within REPO_PATH) |
| **CI configuration** | Test runner commands, env setup | Always — startup pre-fetch | `.github/workflows/`, `Makefile`, `tox.ini` |

#### 4.6.2 Retrieval Pipeline (Cache-First)

```python
def fetch_skill(source_type, query, max_tokens=400):
    cache_key = SHA256(source_type + normalize(query))
    cached = skill_cache.get(cache_key)

    if cached and (now() - cached.timestamp) < CACHE_TTL:
        telemetry.log(event="SKILL_CACHE_HIT", key=cache_key)
        return cached.content                      # Zero network cost

    # Cache miss: fetch, extract, compress
    raw = fetch_from_source(source_type, query)    # HTTP / local file
    relevant = extract_relevant_section(raw, query)  # Embedding similarity
    compressed = compress_to_tokens(relevant, max_tokens)  # Truncate + summarize

    skill_cache.set(cache_key, compressed, ttl=CACHE_TTL_HOURS)
    telemetry.log(event="SKILL_CACHE_MISS", key=cache_key, source=source_type)
    return compressed
```

#### 4.6.3 Startup Pre-Fetch (Zero Latency on Agent Turn 1)

```python
def prefetch_at_startup(repo_path):
    # These run before the first LLM call, fully parallel
    tasks = [
        fetch_and_cache("FILE", f"{repo_path}/README.md"),
        fetch_and_cache("FILE", f"{repo_path}/CONTRIBUTING.md"),
        fetch_and_cache("FILE", find_ci_config(repo_path)),
        fetch_and_cache("FILE", find_test_config(repo_path)),   # pytest.ini, pyproject.toml
        fetch_top_swebench_trajectories(issue_embedding, top_k=3),
    ]
    asyncio.gather(*tasks)   # Parallel fetch
```

---

### 4.7 Layer 7: 6-Phase Verification & Quality Gate

**Responsibility:** Deterministic, model-agnostic verification. Exit code 0 from the test suite is the sole ground truth.

**Invariant:** The agent cannot declare DONE. Only VerificationGate can grant `STATUS: DONE`.

#### 4.7.1 Phase Execution Order (Sequential, Early-Exit on Fail)

```
Phase 1: SYNTAX CHECK
  Tool: language parser (python -m py_compile / tsc --noEmit / go vet / cargo check)
  Input: List of files modified by git_diff
  Pass: All files parse cleanly
  Fail: PATCH_FAILED → no further phases run → immediate recovery trigger

Phase 2: LINTER CHECK (Delta Mode)
  Tool: ruff / flake8 / eslint / golint
  Method: Run linter on repo → diff against linter_baseline.json from startup
  Pass: Zero NEW violations introduced by our patch (pre-existing violations ignored)
  Fail: LINT_REGRESSION → recovery with specific violation locations injected

Phase 3: REPRODUCTION TEST
  Tool: run_test_suite(test_filter=IssuePlan.test_filter)
  Pass: exit_code == 0 AND all specified tests pass
  Fail: TEST_FAILED → exact stack trace injected into recovery prompt

Phase 4: FULL REGRESSION SUITE
  Tool: run_test_suite() (no filter)
  Method: Compare failures to test_baseline.json from startup
  Pass: Zero NEW test failures (pre-existing failures are allowed)
  Fail: REGRESSION_DETECTED → diff of new failures injected into recovery

Phase 5: DIFF AUDIT
  Tool: git_diff + git_status
  Checks:
    a. Files modified are a subset of IssuePlan.suspected_files (or justified in telemetry)
    b. No binary files accidentally modified
    c. No new files added without being in the plan
    d. No whitespace-only changes (cosmetic pollution)
  Pass: All checks clean OR anomalies are documented in telemetry
  Fail (hard): Unintended binary file modification

Phase 6: SIDE-EFFECT CHECK
  Tool: run_bash_sandboxed (import module in isolation)
  Python: importlib.import_module(modified_module)
  Checks: No module-level sys.exit(), no undeclared env var reads, no print side effects
  Pass: Clean import
  Fail: SIDE_EFFECT_DETECTED → agent must refactor module-level code
```

#### 4.7.2 VerificationResult Schema

```json
{
  "verification_id": "v-20260926-001",
  "run_at": "2026-09-26T14:32:00Z",
  "status": "PASS | FAIL",
  "phases": {
    "SYNTAX":      {"status": "PASS", "files_checked": 2, "errors": []},
    "LINT":        {"status": "PASS", "new_violations": 0},
    "REPRO_TEST":  {"status": "PASS", "tests_run": 1, "passed": 1},
    "REGRESSION":  {"status": "FAIL", "new_failures": ["test_admin_auth"], "detail": "..."},
    "DIFF_AUDIT":  {"status": "PASS", "files_modified": 1, "anomalies": []},
    "SIDE_EFFECT": {"status": "PASS", "imports_clean": true}
  },
  "first_failure": "REGRESSION",
  "recovery_action": "RECOVERY_REGRESSION_DETECTED",
  "diff_summary": "1 file changed, 3 insertions(+)",
  "total_duration_ms": 8400
}
```

---

### 4.8 Layer 8: Recovery, Self-Healing & Circuit Breaker

**Responsibility:** Detect all failure modes, apply taxonomy-driven remediation, and prevent unproductive looping.

#### 4.8.1 Anti-Loop Circuit Breaker (Hash Window)

```
Window: last 5 tool calls (ring buffer of fingerprints)

Trigger levels:
  Level 1 (2 identical calls, non-consecutive):
    → WARNING injection: "You appear to be re-trying the same approach."
    → No blocking

  Level 2 (2 consecutive identical calls):
    → BLOCK the call
    → MANDATORY STRATEGY SHIFT injection:
      "LOOP DETECTED at step {N}: `{tool}({args})` called twice identically.
       REQUIRED ACTIONS:
       1. Run git_rollback to restore clean state.
       2. Re-read the TARGET SECTION (±20 lines around your target).
       3. State in one sentence: what was DIFFERENT about what you found.
       4. Propose a DIFFERENT approach before any edit."
    → loop_count += 1

  Level 3 (loop_count >= 3):
    → ESCALATE to PLAN_REVISION (inject all loop attempts as lessons_learned)
    → If revision_count also >= max_plan_revisions: GracefulExit
```

#### 4.8.2 Error Taxonomy (10 Codes)

| Error Code | Trigger | Auto-Remediation | Fallback if Fails |
|---|---|---|---|
| `PATCH_FAILED` | `git apply` returns non-zero | Re-read ±20 lines. Switch to exact-block mode. Retry once. | git_rollback → TEST_FAILED flow |
| `AST_PARSE_FAIL` | Syntax check Phase 1 fails | Auto-rollback file. Inject parse error with line number. | Plan revision |
| `LINT_REGRESSION` | New linter violations introduced | Inject violation locations. Force agent to view those specific lines. | — |
| `TEST_FAILED` | Reproduction test fails | Inject full stack trace + failing test file path. Force test file read before edit. | Plan revision |
| `REGRESSION_DETECTED` | New test failures vs baseline | Inject diff of new failures. Force agent to identify regressing edit. Targeted rollback. | git_rollback all |
| `SIDE_EFFECT_DETECTED` | Module import causes side effects | Inject offending lines. Instruct to refactor module-level code to functions. | — |
| `TIMEOUT` | Tool exceeds time limit | Kill process. Instruct to use more targeted test filter or split command. | — |
| `TOOL_BLOCKED` | Blocklisted command attempted | Log security event. Inject: "Command disallowed. Use permitted tools only." | — |
| `LOOP_DETECTED` | Circuit breaker Level 2+ triggered | Strategy-shift injection (see 4.8.1). | GracefulExit |
| `MAX_STEPS_EXCEEDED` | step_count ≥ max_steps | Graceful exit: git_rollback + `STATUS: STEP_LIMIT_REACHED` + partial report. | — |

#### 4.8.3 Graceful Degradation Chain

```
Failure Event
     │
     ▼
[Level 1: Auto-Remediation]
  Apply taxonomy remediation strategy
  Re-enter REFLECT with structured error context
     │
     ├── SUCCESS → continue loop
     │
     ▼
[Level 2: Plan Revision]  (if auto-remediation fails 3x for same step)
  git_rollback to last checkpoint
  Re-enter PLAN with:
    - All failed approaches as lessons_learned
    - Error codes as context
    - Explicit constraint: "Do NOT repeat approach X"
     │
     ├── SUCCESS → continue new plan
     │
     ▼
[Level 3: Graceful Exit]  (if revision_count >= max_plan_revisions)
  git_rollback ALL changes to HEAD
  Write STATUS: PLAN_REVISION_LIMIT to telemetry
  Generate diagnostic report.md (full error chain, all attempts logged)
  Exit with code 1
```

---

### 4.9 Layer 9: Telemetry, Cost Accounting & Report Generator

**Responsibility:** Full observability. Nothing is unlogged. Report generated even on failure.

#### 4.9.1 Telemetry Event Schema (Full)

```json
{
  "schema_version": "1.0",
  "event_id": "evt-0042",
  "session_id": "sess-20260926-001",
  "timestamp": "2026-09-26T14:32:11.441Z",
  "step": 12,
  "phase": "ACT",
  "agent": "coder | scout | architect | critic | orchestrator",
  "event_type": "TOOL_CALL | TOOL_RESULT | LLM_TURN_START | LLM_TURN_END | VERIFICATION_PHASE | RECOVERY_EVENT | PLAN_REVISION | SUBAGENT_SPAWN | SUBAGENT_RESULT | SKILL_FETCH | DONE | FAILED",
  "tool": "apply_patch | null",
  "tool_args_hash": "a3f7b92",
  "reasoning": "Adding null check to prevent NPE",
  "tokens_in": 4821,
  "tokens_out": 312,
  "tokens_cumulative": 24100,
  "cost_usd": 0.000842,
  "cost_cumulative_usd": 0.031200,
  "latency_ms": 1240,
  "result_status": "SUCCESS | FAIL | BLOCKED | TIMEOUT",
  "error_code": null,
  "recovery_triggered": false,
  "loop_count": 0,
  "revision_count": 0,
  "context_tokens_used": 6421,
  "context_budget": 32000,
  "context_utilization_pct": 20.1
}
```

#### 4.9.2 Real-Time Cost Dashboard (--verbose mode)

```
[ZENITH] Step 12 | Agent: coder | Tool: apply_patch
  Tokens: 4,821 in + 312 out = 5,133 this turn
  Cost:   $0.0008 this turn | $0.031 cumulative
  Context: 6,421 / 32,000 tokens (20.1% full)
  Status: SUCCESS
  ─────────────────────────────────────────────
  [ZENITH] Session total: 24,100 tokens | $0.031 | 4m 12s elapsed
```

#### 4.9.3 Auto-Generated Report (8 Required Sections)

`report.md` is generated from `telemetry.jsonl` via `ReportGenerator`:

```markdown
# Zenith Execution Report
## Issue: {issue_id} — {primary_goal}
## Status: ✅ PASS | ❌ FAIL | ⚠️ PARTIAL (STEP_LIMIT)

---
## 1. Executive Summary
| Metric          | Value              |
|---|---|
| Status          | PASS               |
| Total Steps     | 18                 |
| Wall-Clock Time | 4m 32s             |
| Tokens (total)  | 38,412             |
| Cost            | $0.042 USD         |
| Recovery Events | 1 (PATCH_FAILED)   |
| Subagents Used  | Scout, Coder       |

## 2. Step-by-Step Timeline
| Step | Agent    | Tool/Action    | Result | Tokens | Cost   |
|------|----------|----------------|--------|--------|--------|
| 1    | planner  | PLAN           | ✅     | 2,100  | $0.003 |
| ...

## 3. Recovery Events
| Step | Error Code    | Recovery Action            | Outcome   |
|------|---------------|----------------------------|-----------|
| 9    | PATCH_FAILED  | Switched to block-replace  | RESOLVED  |

## 4. Verification Results
| Phase          | Status | Detail                        |
|----------------|--------|-------------------------------|
| Syntax         | ✅ PASS | 1 file checked                |
| Lint           | ✅ PASS | 0 new violations              |
| Repro Test     | ✅ PASS | test_null_token passed        |
| Regression     | ✅ PASS | 142 passed, 0 new failures    |
| Diff Audit     | ✅ PASS | 1 file, 3 insertions          |
| Side-Effect    | ✅ PASS | Clean import                  |

## 5. Final Diff Applied
```diff
--- a/src/auth/service.py
+++ b/src/auth/service.py
@@ -76,6 +76,9 @@
+    if token is None:
+        raise ValueError("Authentication token cannot be None")
```

## 6. Agent Decisions Log
{key plan decisions and reasoning excerpts from telemetry}

## 7. Token & Cost Breakdown
{per-agent, per-phase breakdown table}

## 8. Lessons Learned (from Working Memory)
{final context_summary.md content}
```

---

## 5. Prompt Engineering Specification

### 5.1 System Persona Template (Fixed, ~300 tokens)

```
You are Zenith, an autonomous software engineering agent.
Your mission: solve the GitHub issue described in §ISSUE GOAL by reading, editing, and testing code.

RULES (non-negotiable):
1. Every tool call MUST include a "reasoning" field explaining WHY.
2. Use the LEAST invasive tool for each need (get_symbol before read_file_range; search_code before list_dir).
3. NEVER re-read a file section you already read unless you have edited it since.
4. NEVER claim the issue is fixed. Emit {"status": "DONE_CANDIDATE"} and let verification decide.
5. If a patch fails twice, run git_rollback and try a different approach.
6. Focus ONLY on the suspected location. Do not modify files unrelated to the issue.
7. Emit a valid JSON plan at the start of each PLAN phase.

OUTPUT FORMAT:
- Tool calls: {"tool": "name", "reasoning": "why", "args": {...}}
- Done signal: {"status": "DONE_CANDIDATE", "confidence": 0.0–1.0, "evidence": [...], "files_modified": [...]}
- Plan revision: {"action": "REVISE_PLAN", "reason": "what failed and why", "lesson_learned": "..."}
```

### 5.2 Prompt Anti-Patterns to Actively Avoid

| Anti-Pattern | Problem | Zenith Prevention |
|---|---|---|
| "Read the entire file first" | Wastes 80-95% of tokens | `get_symbol` forced before `read_file_range` |
| "List all files in the project" | Full repo dump | `list_dir` scoped to suspected directories only |
| "I fixed it, we're done" | False success | DONE_CANDIDATE signal → VerificationGate required |
| "Let me try this edit again" | Identical patch loop | ToolCallDeduplicator + circuit breaker |
| Long reasoning in tool args | Token waste | Reasoning field has 80-token soft limit |
| Verbose success confirmations | Token waste | Structured JSON output format enforced |

### 5.3 Reflection Prompt Template (REFLECT phase injection)

```
## Reflection Prompt
You just executed: {tool}({args})
Result status: {SUCCESS | FAIL}
Observation (truncated):
{observation}

Based on this observation:
1. Did this advance you toward: "{primary_goal}"? (yes/no + one sentence why)
2. What is your CURRENT understanding of the root cause?
3. What is your NEXT action? (state the specific tool and args you will use next)
4. Are you closer to DONE_CANDIDATE? (yes/no)

Respond with your next tool call OR {"status": "DONE_CANDIDATE", ...}
```

### 5.4 Recovery Injection Templates

**PATCH_FAILED injection:**
```
PATCH_FAILED at step {N}:
Error: {exact_error_from_git_apply}
The patch was not applied. The file is unchanged.

REQUIRED RECOVERY STEPS:
1. Run: read_file_range("{file}", {target_line-20}, {target_line+20})
2. Identify the EXACT current content at your target location
3. Reformulate your patch using the exact-block replacement format:
   {"tool": "apply_patch", "args": {"target_file": "...", "old_snippet": "EXACT_CURRENT_TEXT", "new_snippet": "NEW_TEXT"}}
```

**TEST_FAILED injection:**
```
TEST_FAILED at step {N}:
Exit code: 1
Failing tests: {test_names}
Stack trace:
{truncated_stack_trace}

REQUIRED RECOVERY STEPS:
1. Read the failing test file to understand what it expects
2. Identify which line of your patch caused the failure
3. Consider: is the test wrong, or is your implementation wrong?
4. Run git_diff to review your current changes
```

---

## 6. Token Optimization Strategy

Token efficiency is a **first-class engineering constraint** — not an afterthought.

### 6.1 The 9-Technique Optimization Stack

| # | Technique | Token Savings | Implementation |
|---|---|---|---|
| T1 | `get_symbol` / `find_references` instead of `read_file_range` | 80–95% per read | Tree-sitter AST index |
| T2 | Semantic file ranking (top-5 in context, not full index) | 60% vs full repo index | FAISS embedding search |
| T3 | Observation head/tail truncation | 70% on long tool outputs | ContextManager |
| T4 | Rolling context compression at 70% threshold | 75% per compressed turn | Rolling Summarizer |
| T5 | Subagent context isolation (each agent: minimal subset) | 50% vs monolithic | Multi-agent architecture |
| T6 | Skill cache (24h TTL, no re-fetch) | 100% on repeated queries | Local FAISS + JSON store |
| T7 | ToolCallDeduplicator (blocks redundant reads) | 100% on duplicate calls | Fingerprint ring buffer |
| T8 | Rule-based issue parsing (no LLM for simple extraction) | Eliminates 1-2 LLM calls per run | Regex + heuristic parser |
| T9 | 5-section fixed prompt schema (no verbose instruction bloat) | 20% on system prompt | Prompt template literals |

### 6.2 KV Cache Exploitation

For models that support KV caching (Gemini, Claude):
- **SYSTEM PERSONA** and **ACTIVE ISSUE GOAL** sections are placed first and kept byte-identical across turns.
- This allows the model's KV cache to skip re-processing those tokens on every turn.
- Estimated saving: 500 input tokens × number-of-turns. For 20-turn run: **10,000 tokens saved** at zero quality cost.

### 6.3 Token Budget Hard Targets

| Metric | Target | Hard Limit | Action if Exceeded |
|---|---|---|---|
| Total tokens / resolved issue | < 40,000 | 80,000 | Abort + log `TOKEN_LIMIT_WARNING` |
| Prompt tokens per turn | < 8,000 | 32,000 | Emergency context compression |
| Repo context section | < 1,000 | 2,000 | Drop lowest-ranking files |
| Working memory | < 800 | 1,500 | Lossy re-compression |
| External skill snippet | < 500 | 1,000 | Truncate to first 500 |
| System persona | 300 | 400 | Fixed (do not grow) |

### 6.4 Cost Accounting Model

```
cost_per_turn = (tokens_in * price_per_input_token) + (tokens_out * price_per_output_token)

Default prices (Gemini 2.5 Flash):
  input:  $0.000000075 / token   (i.e., $0.075 / 1M tokens)
  output: $0.000000300 / token   (i.e., $0.300 / 1M tokens)

Target for 40k-token run:
  input ~32k tokens:  $0.0024
  output ~8k tokens:  $0.0024
  Total:              ~$0.005 per resolved issue  (well under $0.10 target)
```

---

## 7. State Machine & Formal Control Flow

### 7.1 Complete State Transition Diagram

```
                    ┌─────────────────┐
                    │      INIT       │
                    │  Load config,   │
                    │  parse issue,   │
                    │  build index    │
                    └────────┬────────┘
                             │ IssuePlan ready
                             ▼
                    ┌─────────────────┐
              ┌────►│      PLAN       │◄──────────────────────┐
              │     │  Emit step list │                       │
              │     └────────┬────────┘                       │
              │              │ plan emitted                   │
              │              ▼                                │
              │     ┌─────────────────┐    step_count        │
              │     │       ACT       │    >= max_steps       │
              │     │  Execute one    ├──────────────────►FAILED
              │     │  tool call      │                       │
              │     └────────┬────────┘                       │
              │              │ tool result                    │
              │              ▼                                │
              │     ┌─────────────────┐                      │
              │     │    OBSERVE      │                      │
              │     │  Truncate +     │                      │
              │     │  log result     │                      │
              │     └────────┬────────┘                      │
              │              │ observation ready             │
              │              ▼                               │
              │     ┌─────────────────┐                     │
              │     │    REFLECT      │ loop_count          │
              │     │  Analyze,       │ >= max ────────────►│
              │     │  decide next    │                     │
              │     └──┬──────┬───────┘                     │
              │        │      │ DONE_CANDIDATE              │
              │  next  │      ▼                             │
              │  step  │  ┌──────────────────┐             │
              └────────┘  │  DONE_CANDIDATE  │             │
  REVISE_PLAN │           │  6-Phase Verify  │             │
   (revision  │           └───┬──────────────┘             │
    count < N)│               │         │ any phase FAIL   │
              └───────────────┘    ┌────▼──────────────┐   │
                PASS (all phases)  │  RecoveryEngine   │   │
                     │             └────┬──────────────┘   │
                     ▼                  │ recovery action   │
               ┌──────────┐            │→ re-enter REFLECT │
               │   DONE   │            └───────────────────┘
               │ report +  │
               │ exit 0    │          ┌──────────┐
               └──────────┘          │  FAILED  │
                                      │ rollback │
                                      │ report + │
                                      │ exit 1   │
                                      └──────────┘
```

### 7.2 Recovery Integration Points

| From State | Failure Type | Recovery Level | Transition To |
|---|---|---|---|
| ACT | TOOL_BLOCKED | L1: block + guide | REFLECT |
| ACT | TIMEOUT | L1: kill + rephrase | REFLECT |
| OBSERVE | AST_PARSE_FAIL | L1: rollback + inject parse error | REFLECT |
| DONE_CANDIDATE | TEST_FAILED | L1: inject trace | REFLECT |
| DONE_CANDIDATE | PATCH_FAILED | L1: re-read + switch mode | REFLECT |
| DONE_CANDIDATE | REGRESSION_DETECTED | L2: rollback to checkpoint + plan revision | PLAN |
| REFLECT | LOOP_DETECTED (Level 3) | L2: plan revision | PLAN |
| PLAN | revision_count >= max | L3: graceful exit | FAILED |
| ACT | step_count >= max_steps | L3: graceful exit | FAILED |

---

## 8. Inter-Layer Data Contracts

### 8.1 IssuePlan → RepoIntelligenceEngine

```python
@dataclass
class IssuePlan:
    issue_id: str
    primary_goal: str
    task_type: TaskType
    acceptance_criteria: List[str]
    suspected_files: List[SuspectedFile]
    reproduction_hint: str
    test_filter: str
    error_type: Optional[str]
    complexity_estimate: Complexity
    estimated_steps: int
    requires_external_knowledge: bool
    language: str
    test_runner: str
    parsing_confidence: float
    parsing_method: str
```

### 8.2 RepoIndex → ContextManager

```python
@dataclass
class RankedFileSet:
    files: List[RankedFile]   # Sorted by relevance score desc
    total_indexed: int
    index_tokens_cost: int    # Tokens used to build this set

@dataclass
class RankedFile:
    path: str
    relevance_score: float
    symbol_summary: str       # Signatures only, no bodies
    line_count: int
    language: str
```

### 8.3 ToolResult → ContextManager

```python
@dataclass
class ToolResult:
    tool: str
    args_hash: str
    status: ResultStatus      # SUCCESS | FAIL | BLOCKED | TIMEOUT
    raw_output: str
    truncated_output: str     # After observation truncation
    exit_code: Optional[int]
    error_code: Optional[ErrorCode]
    tokens_in_raw: int        # Tokens in raw output (before truncation)
    tokens_in_truncated: int  # Tokens after truncation
```

### 8.4 VerificationResult → RecoveryEngine

```python
@dataclass
class VerificationResult:
    verification_id: str
    run_at: datetime
    status: VerificationStatus  # PASS | FAIL
    phases: Dict[Phase, PhaseResult]
    first_failure: Optional[Phase]
    recovery_action: Optional[str]
    diff_summary: str
    total_duration_ms: int
```

### 8.5 TelemetryEvent (Common Fields)

```python
@dataclass
class TelemetryEvent:
    schema_version: str = "1.0"
    event_id: str              # evt-{sequence}
    session_id: str
    timestamp: datetime
    step: int
    phase: AgentPhase
    agent: str
    event_type: EventType
    tokens_in: int
    tokens_out: int
    tokens_cumulative: int
    cost_usd: float
    cost_cumulative_usd: float
    latency_ms: int
    result_status: ResultStatus
    error_code: Optional[ErrorCode]
    recovery_triggered: bool
    context_utilization_pct: float
```

---

## 9. External Resources & Skill Acquisition

### 9.1 Reference Implementations

| Repository | Key Techniques to Adapt | Priority |
|---|---|---|
| **SWE-agent** (Princeton NLP) | ACI design, file viewer, edit commands, re-tries | HIGH |
| **Agentless** | Two-phase localization + patch (no loop). Highly efficient. | HIGH |
| **OpenHands** | Sandboxed Docker execution, CodeAct, multi-agent patterns | MEDIUM |
| **Aider** | Architect+Editor split, repo map token efficiency | HIGH |
| **AutoCodeRover** | AST-based localization, spectrum-based fault localization | MEDIUM |
| **SWE-bench** | Benchmark format, trajectory corpus, evaluation harness | HIGH |

### 9.2 Key Research Papers

| Paper | Relevance |
|---|---|
| *SWE-bench: Can LMs Resolve Real-World GitHub Issues?* (Jimenez et al., 2023) | Benchmark design, evaluation methodology |
| *Agentless: Demystifying LLM-based SE Agents* (Xia et al., 2024) | Token-efficient two-phase approach |
| *SWE-agent: ACI Enable Automated SE* (Yang et al., 2024) | ACI design, tool surface design |
| *CodeAct: Executable Code Actions Elicit Better LLM Agents* (Wang et al., 2024) | Code-as-action paradigm |
| *ReAct: Synergizing Reasoning and Acting* (Yao et al., 2022) | Core loop pattern |
| *Tree-of-Thought Prompting* (Yao et al., 2023) | Multi-path exploration for HIGH complexity |
| *HyperAgent: Generalist SE Agent* (Phan et al., 2024) | Multi-agent specialization patterns |

### 9.3 Local SWE-Bench Trajectory Corpus

Pre-built index of successful trajectory patterns from SWE-bench lite:
- Indexed by: error type, language, library name, fix pattern
- Used by: `ExternalSkillRetriever` during planning for `BUG_FIX` tasks
- Format: compressed JSON with issue → fix strategy → diff pattern
- Size target: < 50MB local index

---

## 10. Model-Specific Optimization

### 10.1 Gemini 2.5 Flash Optimizations (Primary Target)

| Feature | Optimization |
|---|---|
| **KV Cache** | Pin PERSONA + GOAL sections byte-identical across all turns → cache reuse on turns 2–N |
| **Structured output** | Use `response_mime_type: application/json` + JSON schema for tool calls → zero parsing errors |
| **Thinking tokens** | Enable for PLAN phase only (high-value reasoning). Disable for ACT/OBSERVE (pure execution). |
| **Temperature** | `0.0` for ACT, OBSERVE. `0.1` for PLAN and REFLECT (slight creativity for plan revision). |
| **Flash vs Pro routing** | Use Flash for ACT/OBSERVE turns. Route PLAN for HIGH complexity to Pro if available. |
| **Context window** | Flash: 1M tokens max. We target < 32k to ensure fast response latency. |

### 10.2 Model-Agnostic Compatibility Layer

The harness exposes a `ModelAdapter` interface so the foundation model can be swapped:

```python
class ModelAdapter(Protocol):
    def complete(self, prompt: PromptSections, tools: List[ToolSchema]) -> ModelResponse: ...
    def count_tokens(self, text: str) -> int: ...
    def supports_kv_cache(self) -> bool: ...
    def supports_structured_output(self) -> bool: ...
    def max_context_tokens(self) -> int: ...

# Implementations:
class GeminiAdapter(ModelAdapter): ...
class ClaudeAdapter(ModelAdapter): ...
class OpenAIAdapter(ModelAdapter): ...
class LocalOllamaAdapter(ModelAdapter): ...
```

### 10.3 Temperature Schedule

| Phase | Temperature | Rationale |
|---|---|---|
| PLAN (initial) | 0.1 | Slight creativity to explore non-obvious fix strategies |
| PLAN (revision) | 0.2 | Higher for plan revision — must diverge from failed approaches |
| ACT | 0.0 | Pure execution — deterministic tool selection |
| OBSERVE | 0.0 | No generation — just receive |
| REFLECT | 0.05 | Minimal creativity — analytical reasoning preferred |
| Summarization | 0.0 | Deterministic compression |
| Issue parsing LLM | 0.0 | Structured extraction |

---

## 11. Harness Test Strategy

### 11.1 Test Pyramid

```
                    ╱ E2E (SWE-bench integration) ╲
                   ╱──────────────────────────────╲
                  ╱       Integration Tests         ╲
                 ╱  (tool + verification + recovery)  ╲
                ╱────────────────────────────────────╲
               ╱            Unit Tests                ╲
              ╱  (each layer component independently)  ╲
             ╱──────────────────────────────────────────╲
```

### 11.2 Unit Tests (per component)

| Module | Key Tests |
|---|---|
| `issue_parser.py` | Rule-based extraction on 10 sample issues; LLM fallback triggers correctly |
| `repo_intelligence.py` | File tree excludes junk dirs; symbol extraction is correct; ranking selects right files |
| `tool_engine.py` | Each tool: valid input passes; invalid input fails gracefully; blocklist enforced; 250-line cap respected |
| `context_manager.py` | Budget enforcement; truncation correct for all size classes; summarizer triggers at 70% |
| `verification.py` | Each phase: correctly passes clean code; correctly fails intentionally broken code |
| `recovery.py` | Circuit breaker triggers at correct level; taxonomy routes correctly; graceful exit clean |
| `telemetry.py` | All event types serialize correctly; cumulative fields correct; file appended (not overwritten) |
| `report_generator.py` | All 8 sections present in output; cost and token totals correct |

### 11.3 Integration Tests

| Test Scenario | Input | Expected Outcome |
|---|---|---|
| Simple bug fix | Toy Python repo + NullPointerError issue | PASS in < 10 steps, < 10k tokens |
| Patch failure recovery | Toy repo + issue where first patch fails | Auto-recovers in ≤ 2 attempts |
| Loop detection | Agent configured to always make identical calls | Circuit breaker triggers at step 2 |
| Context overflow | Large test output (2000 lines) | Truncation applies; no context overflow error |
| Regression introduction | Fix that breaks unrelated test | REGRESSION_DETECTED raised; rollback applied |
| Clean clone | Fresh virtualenv + `make setup && make run` | Completes without errors |

### 11.4 E2E Benchmark Tests (SWE-bench Lite Sample)

Run harness against 5 real GitHub issues from SWE-bench Lite before submission. Log all results in `logs.md`.

| Run# | Repo | Issue | Expected Complexity | Pass Target |
|---|---|---|---|---|
| 1 | `django/django` | Simple model field bug | LOW | ✅ PASS |
| 2 | `flask/flask` | Blueprint routing edge case | MEDIUM | ✅ PASS |
| 3 | `numpy/numpy` | Array dtype coercion bug | MEDIUM | ✅ PASS |
| 4 | `sympy/sympy` | Math expression parsing bug | HIGH | ✅ PASS |
| 5 | `astropy/astropy` | FITS header parsing bug | HIGH | ✅ PASS |

---

## 12. CLI & Makefile Specification

### 12.1 Makefile Targets

```makefile
# All targets must work in a clean clone — no pre-installed dependencies

.PHONY: setup run test clean lint docker-test

setup:       ## Create .venv, install all pinned dependencies from requirements.txt
run:         ## REPO_PATH=... ISSUE_PATH=... — launch full harness
test:        ## Run unit + integration test suite with coverage
clean:       ## Remove .venv, .harness/, __pycache__, *.egg-info, dist/
lint:        ## Run ruff on harness source code
docker-test: ## Build Docker image and run full clean-clone test inside container
```

### 12.2 CLI Interface

```bash
# Standard evaluation invocation (what evaluators will run)
make run REPO_PATH=/path/to/target_repo ISSUE_PATH=/path/to/issue.txt

# Direct CLI — all options
python -m harness.cli \
  --repo        /path/to/target_repo \
  --issue       /path/to/issue.txt \
  --max-steps   25 \
  --model       gemini-2.5-flash \
  --temperature 0.0 \
  --token-budget 40000 \
  --agent-mode  auto \           # auto | single | multi
  --verbose \                    # Real-time cost dashboard
  --dry-run \                    # Parse + plan only, zero LLM inference
  --no-external-skills \         # Disable ExternalSkillRetriever (offline mode)
  --output-dir  .harness         # Where to write all artifacts
```

### 12.3 Output File Manifest (Per Run)

```
.harness/
├── issue_plan.json               # IssuePlan (written before turn 1)
├── plan.md                       # Agent-emitted step plan
├── scout_report.md               # Scout subagent findings (if multi-agent)
├── architecture_plan.md          # Architect subagent plan (if HIGH complexity)
├── patch_{file}_{step}.diff      # Per-Coder-agent output (if multi-agent)
├── critic_report.md              # Critic subagent review (if multi-agent)
├── telemetry.jsonl               # Append-only event stream (all turns)
├── context_summary.md            # Latest rolling working memory snapshot
├── checkpoint_{N}.diff           # Diff snapshots at plan rollback checkpoints
├── skill_cache/                  # Cached external knowledge (by query hash)
│   └── {SHA256_hash}.json
├── repo_index/                   # Cached repository index
│   ├── file_tree.txt
│   ├── module_symbols.json
│   ├── dependency_graph.json
│   ├── test_map.json
│   ├── linter_baseline.json
│   ├── test_baseline.json
│   └── embedding_index/
└── report.md                     # Final auto-generated execution report
```

---

## 13. Security & Compliance

### 13.1 API Key Handling

```python
# ONLY valid pattern:
api_key = os.environ.get("AI_API_KEY")
if not api_key:
    raise EnvironmentError(
        "AI_API_KEY not set. Add it to your .env file (see .env.example). "
        "Never hardcode keys in source code."
    )

# FORBIDDEN — any of these is a submission disqualifier:
api_key = "sk-..."                    # Hardcoded
print(f"Using key: {api_key}")        # Logged to stdout
telemetry.log(api_key=api_key)        # Written to telemetry
open(".harness/config").write(api_key) # Written to disk
```

### 13.2 Sandbox Execution Rules

| Control | Specification | Implementation |
|---|---|---|
| Process isolation | `shell=False`, explicit `args` list | `subprocess.Popen(args, shell=False)` |
| Timeout | Hard wall-clock kill | `asyncio.wait_for` with `SIGKILL` on expiry |
| Memory limit | 512MB RSS | `resource.setrlimit(RLIMIT_AS, (512*1024*1024, 512*1024*1024))` |
| Network access | Blocked in sandbox | `BLOCKED_PATTERNS` + subprocess isolation |
| File system scope | Strictly within REPO_PATH | Path validation before every tool call |
| Path traversal | Rejected with error | Regex check `r"\.\./|/\.\."` |
| Command blocklist | 12 patterns blocked | `BLOCKED_PATTERNS` regex match |

### 13.3 Submission Compliance Checklist

- [ ] `AI_API_KEY` ONLY from `os.environ` — never hardcoded
- [ ] `.env` in `.gitignore` — `.env.example` committed
- [ ] `grep -r "sk-\|AI_API_KEY=" harness/` returns zero results
- [ ] `make setup && make run` works on clean clone
- [ ] No network calls inside sandboxed execution
- [ ] All tool outputs validated before passing to context

---

## 14. Configuration Specification

Full `harness_config.yaml` — single source of truth for all runtime parameters:

```yaml
# harness_config.yaml — Zenith v4.0
# All values overridable by CLI flags or environment variables.

model:
  name: "gemini-2.5-flash"          # Primary model
  plan_model: null                   # If set, use for PLAN phase (e.g., gemini-2.5-pro)
  base_url: null                     # null = default SDK endpoint
  temperature_plan: 0.1
  temperature_act: 0.0
  temperature_reflect: 0.05
  temperature_summarize: 0.0
  seed: 42                           # For reproducibility
  max_output_tokens: 4096
  enable_thinking: false             # Enable only for PLAN on HIGH complexity
  use_structured_output: true        # JSON schema mode for tool calls

context:
  max_context_tokens: 32000
  response_reserve_tokens: 4000
  persona_budget_tokens: 300
  goal_budget_tokens: 200
  repo_context_budget_tokens: 1000
  working_memory_budget_tokens: 800
  recent_turns_budget_tokens: 4000
  compression_threshold: 0.70        # Trigger Rolling Summarizer at 70% full
  observation_head_lines: 20
  observation_tail_lines: 50
  observation_mid_threshold: 300     # Lines: switch from no-trunc to head/tail mode
  kv_cache_enabled: true             # Keep PERSONA+GOAL byte-identical for cache reuse

agent:
  max_steps: 25                      # Override with --max-steps
  max_plan_revisions: 3
  max_loop_count: 3
  agent_mode: "auto"                 # auto | single | multi
  multi_agent_threshold: "MEDIUM"    # Complexity that triggers multi-agent
  complexity_scoring: true
  rollback_checkpoints: true

tools:
  max_search_results: 50
  max_read_lines: 250
  max_symbol_output_lines: 50
  max_reference_locations: 30
  sandbox_timeout_sec: 30
  sandbox_memory_mb: 512
  test_suite_timeout_sec: 120
  test_output_lines: 80
  bash_output_lines: 200
  git_diff_lines: 500
  deduplicator_window: 10            # Fingerprint ring buffer size

external_skills:
  enabled: true
  cache_ttl_hours: 24
  max_tokens_per_snippet: 500
  prefetch_at_startup: true
  swebench_index_path: ".harness/swebench_index"
  github_api_token_env: "GITHUB_TOKEN"   # Optional; increases rate limit

verification:
  run_syntax_check: true
  run_lint_check: true
  run_repro_test: true
  run_full_regression: true
  run_diff_audit: true
  run_side_effect_check: true
  linter: "ruff"                     # ruff | flake8 | eslint | golint
  linter_fail_on_new_only: true      # Only fail on new violations

telemetry:
  enabled: true
  output_dir: ".harness"
  stream_to_stdout: false            # Enable with --verbose
  include_full_prompts: false        # Debug only — increases file size dramatically
  schema_version: "1.0"

report:
  auto_generate: true
  include_diff: true
  include_timeline: true
  include_cost_breakdown: true
  include_lessons_learned: true
```

---

## 15. Non-Functional Requirements

| Requirement | Target | Hard Limit | Measurement |
|---|---|---|---|
| **Pass Rate** | > 85% benchmark issues | — | Exit code 0 + target test passes |
| **Autonomy Rate** | 100% zero-human-intervention | — | No `input()` calls; no manual steps |
| **Recovery Rate** | > 80% self-healing | — | RecoveryEngine success events in telemetry |
| **Token Efficiency** | < 40k tokens/resolved issue | 80k | Sum of tokens_in + tokens_out in report.md |
| **Cost per Issue** | < $0.08 USD | $0.20 | cost_cumulative_usd in report.md |
| **Wall-Clock Speed** | < 10 min per issue | 20 min | Timestamp delta: INIT → DONE |
| **Clean Clone Success** | 100% `make setup && make run` | — | Docker container test |
| **Test Coverage** | > 70% line coverage (harness code) | — | `make test` coverage report |
| **Security Compliance** | Zero secrets in code/logs/output | — | Automated grep in CI |
| **Regression Rate** | < 5% introduced by our patches | — | Phase 4 delta vs baseline |
| **False DONE Rate** | 0% | — | VerificationGate prevents all |
| **Index Build Time** | < 10 sec for 500-file repo | 30 sec | Timed during startup |
| **Report Generation** | Always generated (even on FAIL) | — | `report.md` exists after every run |

---

## 16. Risk Register & Mitigations

| Risk | Likelihood | Impact | Root Cause | Mitigation | Layer | Status |
|---|---|---|---|---|---|---|
| Infinite retry loop | HIGH | HIGH | Model repeatedly attempts failing patch | Anti-loop hash window → strategy shift → plan revision → graceful exit | L8 | Active |
| Context overflow | MEDIUM | HIGH | Large test output or file reads | Hard ceiling + head/tail truncation + rolling compression | L4 | Active |
| Hallucinated file paths | HIGH | MEDIUM | Model guesses non-existent paths | Pre-tool path validation against repo tree; `FILE_NOT_FOUND` error | L3 | Active |
| Broken patch offsets | HIGH | MEDIUM | Unified diff line numbers shifted by prior edits | Dual-mode: unified diff → exact block replace (AST-validated) | L3 | Active |
| Unsafe shell commands | LOW | CRITICAL | Model attempts `rm -rf` or network exfil | Sandboxed subprocess + 12-pattern blocklist + timeout + memory limit | L3/L8 | Active |
| False success self-report | HIGH | HIGH | Model claims fix without testing | DONE_CANDIDATE gate → VerificationGate only arbiter | L7 | Active |
| Regression introduction | MEDIUM | HIGH | Fix breaks unrelated tests | Phase 4 full regression + baseline comparison | L7 | Active |
| Clean clone setup failure | MEDIUM | CRITICAL | Dependency or env mismatch | Pinned `requirements.txt` + Docker dry-run in P6 | L9 | Active |
| Token cost overrun | MEDIUM | MEDIUM | Complex repo with many large files | 9-technique optimization stack + hard ceiling | L4 | Active |
| External resource unavailable | LOW | LOW | GitHub API rate limit or network down | Local cache first; continue without external skill if unavailable | L6 | Active |
| Subagent context pollution | LOW | HIGH | Scout findings polluting coder context | Strict context isolation; handoff via structured `.harness/*.md` files | L5 | Active |
| KV cache miss | LOW | LOW | Prompt bytes changed between turns | Strict byte-identical PERSONA+GOAL template; variable sections at end | L4 | Active |
| LSP server unavailable | MEDIUM | LOW | Language server not installed in target env | Graceful fallback to Tree-sitter only; LSP is enhancement, not requirement | L2 | Active |
| SWE-bench index stale | LOW | LOW | Index not updated for new library versions | TTL + explicit cache-bust flag `--refresh-skills` | L6 | Active |

---

## 17. Success Metrics & Benchmarks

### 17.1 Primary (Hackathon Scoring)

| Metric | Target | Measurement Method |
|---|---|---|
| **Pass Rate** | > 85% | `exit_code == 0` AND target test passes AND no regressions |
| **Autonomy Rate** | 100% | Zero `input()` calls; no manual README steps required |
| **Recovery Rate** | > 80% | `recovery_triggered=true` events with `result_status=SUCCESS` in telemetry |
| **Token Efficiency** | < 40k avg tokens/issue | `tokens_cumulative` at `DONE` event in telemetry |
| **Clean Clone Success** | 100% | `make setup && make run` in fresh Docker container |

### 17.2 Secondary (Engineering Quality)

| Metric | Target |
|---|---|
| New regression rate (from our patches) | < 5% |
| False DONE claims bypassing VerificationGate | 0% |
| Average cost per resolved issue | < $0.08 USD |
| Average wall-clock time per issue | < 8 minutes |
| Harness own unit test line coverage | > 70% |
| Index build time (500-file repo) | < 10 seconds |

### 17.3 Internal Benchmark Targets (pre-submission)

Run 5 SWE-bench Lite issues. Record in `logs.md`. Target: ≥ 4/5 pass.

| # | Repo | Issue Type | Complexity | Token Target | Cost Target |
|---|---|---|---|---|---|
| 1 | django/django | Bug Fix | LOW | < 20k | < $0.02 |
| 2 | flask/flask | Bug Fix | MEDIUM | < 30k | < $0.03 |
| 3 | numpy/numpy | Bug Fix | MEDIUM | < 35k | < $0.04 |
| 4 | sympy/sympy | Bug Fix | HIGH | < 45k | < $0.05 |
| 5 | astropy/astropy | Bug Fix | HIGH | < 50k | < $0.06 |

---

## 18. Glossary

| Term | Definition |
|---|---|
| **Harness** | The complete orchestration system wrapping the foundation model — tools, context, memory, recovery, verification |
| **IssuePlan** | Structured JSON artifact produced by IssueParser before any LLM coding call |
| **RepoIndex** | Token-cheap cached representation of repository structure, symbols, and dependencies |
| **DONE_CANDIDATE** | Agent signal that it believes task is complete; transfers control to VerificationGate |
| **VerificationGate** | 6-phase deterministic pipeline; sole arbiter of task completion |
| **RecoveryEngine** | Taxonomy-based failure classification and auto-remediation orchestrator |
| **Circuit Breaker** | Anti-loop mechanism detecting repeated identical tool calls via 5-call hash window |
| **Working Memory** | Rolling compressed summary of prior conversation turns injected as Section 4 of prompt |
| **Subagent** | Specialized child agent with isolated, minimal context and narrowly scoped mission |
| **Skill Cache** | Local TTL-based store of fetched and compressed external knowledge snippets |
| **Telemetry** | Append-only JSONL event log capturing every turn, action, token, cost, and latency |
| **Tool Fingerprint** | SHA256 of tool name + normalized args; used by ToolCallDeduplicator ring buffer |
| **ACI** | Agent-Computer Interface — abstraction between model outputs and physical tool execution |
| **SWE-bench** | Standard benchmark of real GitHub issues for evaluating coding agent performance |
| **KV Cache** | Model-side key-value cache that reuses computation for byte-identical prefix tokens |
| **FileSet (Ranked)** | Top-N files selected by semantic ranking; injected into prompt Repo Context section |
| **GracefulExit** | Controlled harness shutdown: git rollback + partial report + exit code 1 |
| **Rollback Checkpoint** | Git diff snapshot taken at designated plan steps; used for targeted recovery |
| **ModelAdapter** | Protocol interface allowing any foundation model to be plugged into the harness |
| **Complexity Score** | Integer score determining agent mode routing (single/multi-agent) |

---

*Document Version: 4.0 — Elite Master*
*Upgraded from: v3.0 (2026-09-26)*
*Last Updated: 2026-09-26*
*Owner: Zenith Team*
*Next Review: After Phase 1 completion — see logs.md*