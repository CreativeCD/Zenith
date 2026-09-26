# Zenith — System Architecture Document
### AI Coding Harness Hackathon 2026

```
Version    : 1.0
Reference  : PRD.md (v4.0 — Elite Master)
Companion  : phases.md (v2.0) | logs.md
Last Update: 2026-09-26
Status     : Authoritative technical reference — complements PRD
```

---

## Table of Contents

1. [Architecture Philosophy](#1-architecture-philosophy)
2. [System Context & Boundaries](#2-system-context--boundaries)
3. [Component Architecture (C4 Model)](#3-component-architecture)
4. [Module Dependency Graph](#4-module-dependency-graph)
5. [Data Flow Architecture](#5-data-flow-architecture)
6. [State Machine Specification](#6-state-machine-specification)
7. [Layer-by-Layer Technical Design](#7-layer-by-layer-technical-design)
8. [Inter-Component Data Contracts](#8-inter-component-data-contracts)
9. [Tool Engine Internals](#9-tool-engine-internals)
10. [Multi-Agent Orchestration Internals](#10-multi-agent-orchestration-internals)
11. [Context Window Memory Model](#11-context-window-memory-model)
12. [Verification Pipeline Internals](#12-verification-pipeline-internals)
13. [Recovery Engine Internals](#13-recovery-engine-internals)
14. [Token Economy & Cost Model](#14-token-economy--cost-model)
15. [Concurrency & Async Architecture](#15-concurrency--async-architecture)
16. [Model Adapter Interface](#16-model-adapter-interface)
17. [File System Layout & Artifact Spec](#17-file-system-layout)
18. [Security Architecture](#18-security-architecture)
19. [Observability & Telemetry Architecture](#19-observability--telemetry-architecture)
20. [Failure Mode Analysis (FMEA)](#20-failure-mode-analysis)
21. [Technology Stack & Dependencies](#21-technology-stack--dependencies)
22. [Architecture Decision Records (ADRs)](#22-architecture-decision-records)

---

## 1. Architecture Philosophy

### 1.1 Governing Principles

```
┌──────────────────────────────────────────────────────────────────┐
│                  ZENITH ARCHITECTURE TENETS                       │
│                                                                    │
│  1. LAYERED ISOLATION  — Each layer has a single responsibility   │
│  2. CONTRACT-DRIVEN    — All inter-layer data uses typed schemas  │
│  3. TOKEN-FIRST        — Every design choice optimizes token use  │
│  4. FAIL-FORWARD       — Recovery paths exist for every failure   │
│  5. OBSERVABLE          — Nothing happens silently; all is logged  │
│  6. PLUGGABLE           — Model, tools, verification are swappable│
│  7. DETERMINISTIC       — Same input → same output (temp=0, seed) │
│  8. LEAST-PRIVILEGE     — Tools only access what is needed        │
│  9. CACHE-EVERYWHERE    — No redundant computation or I/O         │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 What Zenith Is NOT

| Not | Instead |
|---|---|
| An LLM wrapper with a while loop | A production-grade orchestration engine with a formal state machine |
| A monolithic single-context agent | A multi-agent system with context isolation per specialization |
| A best-effort system that hopes for the right answer | A deterministic verification pipeline where only exit codes matter |
| A system that reads entire files | A symbol-level semantic navigation engine that reads signatures only |
| A stateless agent that loses history | A memory-managed system with rolling compression and working memory |

---

## 2. System Context & Boundaries

### 2.1 Context Diagram (C4 Level 1)

```
                          ┌──────────────┐
                          │  Evaluator   │
                          │  (Human or   │
                          │   CI system) │
                          └──────┬───────┘
                                 │
                      issues.txt │ repo_path
                                 │
                                 ▼
┌───────────────────────────────────────────────────────────────┐
│                    ZENITH HARNESS                              │
│                                                                │
│  Input:  GitHub issue text + repository path                   │
│  Output: Verified code patch + report.md + telemetry.jsonl    │
│                                                                │
│  Boundaries:                                                   │
│  • File system access: ONLY within repo_path + .harness/      │
│  • Network access: ONLY via model API + fetch_external_skill  │
│  • Execution: sandboxed subprocess with blocklist + limits    │
└──────┬────────────┬──────────────┬───────────────┬────────────┘
       │            │              │               │
       ▼            ▼              ▼               ▼
  ┌─────────┐ ┌──────────┐ ┌──────────┐  ┌──────────────┐
  │Foundation│ │ Target   │ │  Skill   │  │  Test Runner │
  │ Model   │ │ Repo FS  │ │ Sources  │  │ (pytest etc) │
  │ (API)   │ │ (local)  │ │ (cached) │  │ (subprocess) │
  └─────────┘ └──────────┘ └──────────┘  └──────────────┘
```

### 2.2 External Interfaces

| Interface | Protocol | Auth | Rate Limit | Failure Mode |
|---|---|---|---|---|
| **Foundation Model API** | HTTPS REST / SDK | `AI_API_KEY` env var | Per-model (e.g., 1000 RPM) | Exponential backoff with 3 retries |
| **Target Repository** | Local filesystem | None (in-process) | N/A | `FILE_NOT_FOUND` error → agent notified |
| **GitHub API** (optional) | HTTPS REST | `GITHUB_TOKEN` env var (optional) | 60 req/hr unauthenticated; 5000/hr with token | Cache fallback; continue without |
| **Test Runner** | Subprocess stdout/stderr/exit code | None | N/A | 120s timeout → `TIMEOUT` error |
| **ripgrep** | Subprocess | None | N/A | Fallback to Python regex scanner |

### 2.3 Trust Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│  TRUSTED ZONE (Zenith-controlled)                            │
│                                                               │
│  Config parser, State machine, ContextManager,               │
│  VerificationGate, RecoveryEngine, TelemetryWriter           │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  SANDBOXED ZONE (restricted)                             │ │
│  │  run_bash_sandboxed, run_test_suite                      │ │
│  │  Limits: 30s timeout, 512MB RAM, blocklist, shell=False  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  UNTRUSTED ZONE (model output)                           │ │
│  │  ALL model responses: validated, sanitized, constrained  │ │
│  │  Tool calls: reasoning required, path checked, deduped   │ │
│  │  DONE claims: IGNORED — only VerificationGate decides    │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Component Architecture (C4 Model)

### 3.1 Container Diagram (C4 Level 2)

```
┌───────────────────────────────────────────────────────────────────────────┐
│                          ZENITH HARNESS (Python Process)                   │
│                                                                            │
│  ┌─────────┐   ┌──────────────┐   ┌──────────────────────────────────┐   │
│  │  CLI    │──►│   Config     │──►│       ORCHESTRATOR               │   │
│  │ (entry) │   │   Loader     │   │                                  │   │
│  └─────────┘   └──────────────┘   │  State: INIT→PLAN→ACT→OBSERVE   │   │
│                                    │         →REFLECT→DONE/FAILED    │   │
│                                    │                                  │   │
│                                    │  Drives all component            │   │
│                                    │  interactions below              │   │
│                                    └─────────┬────────────────────────┘   │
│                                              │                             │
│            ┌─────────────────────────────────┼─────────────────────────┐  │
│            │                                 │                         │  │
│            ▼                                 ▼                         ▼  │
│  ┌──────────────────┐   ┌──────────────────────────┐   ┌──────────────┐  │
│  │  ISSUE PARSER    │   │    TOOL ENGINE            │   │  CONTEXT     │  │
│  │  (L1)            │   │    (L3)                   │   │  MANAGER     │  │
│  │                  │   │                           │   │  (L4)        │  │
│  │  Rule-based      │   │  15 tools + 3 guards     │   │              │  │
│  │  + LLM fallback  │   │  Dedup · Sandbox · Log   │   │  5-section   │  │
│  │  → IssuePlan     │   │                           │   │  prompt      │  │
│  └──────────────────┘   └──────────────────────────┘   │  Token mgr   │  │
│                                                          │  Summarizer  │  │
│  ┌──────────────────┐   ┌──────────────────────────┐   └──────────────┘  │
│  │  REPO INTEL      │   │    SKILL RETRIEVER       │                     │
│  │  ENGINE (L2)     │   │    (L6)                  │                     │
│  │                  │   │                           │   ┌──────────────┐  │
│  │  Tree-sitter     │   │  Cache-first pipeline    │   │  TELEMETRY   │  │
│  │  FAISS index     │   │  Startup pre-fetch       │   │  WRITER      │  │
│  │  Dependency graph│   │  Skill cache (24h TTL)   │   │  (L9)        │  │
│  │  Test map        │   │                           │   │              │  │
│  └──────────────────┘   └──────────────────────────┘   │  JSONL       │  │
│                                                          │  stream      │  │
│  ┌──────────────────┐   ┌──────────────────────────┐   │  Cost track  │  │
│  │  VERIFICATION    │   │    RECOVERY ENGINE       │   └──────────────┘  │
│  │  GATE (L7)       │◄─┤    (L8)                  │                     │
│  │                  │   │                           │   ┌──────────────┐  │
│  │  6-phase         │   │  Circuit breaker         │   │  REPORT      │  │
│  │  pipeline        │   │  10-code taxonomy        │   │  GENERATOR   │  │
│  │  Syntax→Lint→    │   │  3-level degradation     │   │  (L9)        │  │
│  │  Test→Regress→   │   │  Auto-rollback           │   │              │  │
│  │  Diff→SideEffect │   │                           │   │  Markdown    │  │
│  └──────────────────┘   └──────────────────────────┘   │  8-section   │  │
│                                                          └──────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    MODEL ADAPTER (L10 — pluggable)                   │  │
│  │   GeminiAdapter  │  ClaudeAdapter  │  OpenAIAdapter  │  OllamaAdapt │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Component Responsibilities (Single-Responsibility Principle)

| Component | Single Responsibility | Inputs | Outputs |
|---|---|---|---|
| `cli.py` | Parse CLI args, load config, wire components, call `Orchestrator.run()` | argv, env vars | Exit code 0 or 1 |
| `config.py` | Load + validate `harness_config.yaml`, merge CLI overrides | YAML + CLI | `HarnessConfig` dataclass |
| `contracts.py` | Define all inter-layer typed schemas | — | Dataclass types |
| `issue_parser.py` | Transform issue text → `IssuePlan` JSON | Raw issue text | `IssuePlan` |
| `repo_intelligence.py` | Build + cache + query repo index (AST, embeddings, graph) | Repo path | `RepoIndex`, `RankedFileSet` |
| `tool_engine.py` | Execute tools atomically, validate, sandbox, deduplicate | `ToolCall` from model | `ToolResult` |
| `context_manager.py` | Build 5-section prompt within budget, truncate, compress | Turns + state | `PromptSections` |
| `orchestrator.py` | Drive state machine, spawn subagents, enforce transitions | All components | `SessionResult` |
| `skill_retriever.py` | Fetch + cache + compress external knowledge | Query + source type | Compressed snippet |
| `verification.py` | Run 6-phase deterministic quality gate | Modified files list | `VerificationResult` |
| `recovery.py` | Classify errors, apply remediation, drive circuit breaker | Error event | `RecoveryAction` |
| `telemetry.py` | Append-only JSONL event stream + real-time cost tracking | `TelemetryEvent` | `.harness/telemetry.jsonl` |
| `report_generator.py` | Compile telemetry → human-readable 8-section `report.md` | `telemetry.jsonl` | `.harness/report.md` |
| `adapters/*.py` | Translate `PromptSections` → model-specific API call | `PromptSections` | `ModelResponse` |

---

## 4. Module Dependency Graph

### 4.1 Import DAG (Directed Acyclic Graph)

```
                           cli.py
                         ╱   │   ╲
                        ╱    │    ╲
                  config.py  │   contracts.py ◄──── (imported by ALL modules)
                             │
                       orchestrator.py
                    ╱    ╱   │   ╲    ╲
                   ╱    ╱    │    ╲    ╲
    issue_parser.py  repo_intel.py  │  telemetry.py  report_gen.py
                                    │
                              ┌─────┼──────┐
                              │     │      │
                    context_mgr.py  │  verification.py
                              │     │      │
                         tool_engine.py    │
                              │    │       │
                    skill_retriever.py  recovery.py
                              │
                      adapters/
                    ╱    │     ╲
           gemini.py claude.py openai.py
```

### 4.2 Key Design Constraint: No Circular Imports

```
RULE: The dependency arrow is strictly top-down.
Lower modules NEVER import from higher modules.

Allowed:  orchestrator → tool_engine (orchestrator calls tools)
Forbidden: tool_engine → orchestrator (tool must not call back to loop)

Communication upward is via RETURN VALUES and DATA CONTRACTS only.
```

### 4.3 Dependency Injection Pattern

```python
# cli.py — wiring entrypoint (Composition Root)
def main():
    config = Config.load("harness_config.yaml", cli_overrides)
    adapter = resolve_model_adapter(config.model)  # pluggable
    telemetry = TelemetryWriter(config.telemetry)
    tool_engine = ToolEngine(config.tools, telemetry)
    context_mgr = ContextManager(config.context, adapter)
    skill_retriever = SkillRetriever(config.external_skills, telemetry)
    verification = VerificationGate(config.verification, telemetry)
    recovery = RecoveryEngine(config.agent, telemetry)
    repo_intel = RepoIntelligenceEngine(config, telemetry)
    issue_parser = IssueParser(config, adapter, telemetry)
    report_gen = ReportGenerator(config.report)

    orchestrator = Orchestrator(
        config=config,
        adapter=adapter,
        tool_engine=tool_engine,
        context_mgr=context_mgr,
        skill_retriever=skill_retriever,
        verification=verification,
        recovery=recovery,
        repo_intel=repo_intel,
        issue_parser=issue_parser,
        telemetry=telemetry,
        report_gen=report_gen,
    )

    result = orchestrator.run(repo_path=config.repo_path, issue_text=config.issue_text)
    report_gen.generate(telemetry.events_path)
    sys.exit(0 if result.status == SessionStatus.DONE else 1)
```

---

## 5. Data Flow Architecture

### 5.1 End-to-End Data Flow (Happy Path)

```
INPUT                          PROCESSING                           OUTPUT
─────                          ──────────                           ──────

issue.txt ──────►  IssueParser  ──────────►  IssuePlan JSON ───────► .harness/issue_plan.json
                        │
                        ▼
repo_path  ──────►  RepoIntelEngine  ─────►  RepoIndex  ──────────► .harness/repo_index/
                        │                        │
                        ▼                        │
                  [Complexity Router]             │
                        │                        │
              ┌─────────┼─────────┐              │
              │         │         │              │
              ▼         ▼         ▼              │
          SINGLE     PLANNER   MULTI             │
          REACT      EXECUTOR  AGENT             │
              │         │         │              │
              └─────────┼─────────┘              │
                        │                        │
                        ▼                        ▼
                  Orchestrator Loop ◄───── ContextManager
                  (PLAN→ACT→OBSERVE→REFLECT)     │
                        │                        │
                   Each ACT turn:                │
                        │                        │
                        ├──► ToolEngine ──► ToolResult ──► TelemetryEvent
                        │         │                              │
                        │         ▼                              ▼
                        │    .harness/telemetry.jsonl       Cost Tracker
                        │
                        ├──► SkillRetriever (if needed)
                        │         │
                        │         ▼
                        │    .harness/skill_cache/*.json
                        │
                  DONE_CANDIDATE signal
                        │
                        ▼
                  VerificationGate ──────► VerificationResult
                        │                        │
                   ┌────┴────┐                   ▼
                   │         │            Recovery (if FAIL)
                  PASS     FAIL                  │
                   │         │                   │
                   │         └───────────► RE-ENTER REFLECT
                   │
                   ▼
              ReportGenerator ──────────► .harness/report.md
                   │
                   ▼
              exit(0)
```

### 5.2 Data Flow Per Agent Turn

```
Step 1: BUILD PROMPT
  ContextManager.build_prompt(
    persona     = fixed_template,              # 300 tokens
    issue_goal  = IssuePlan.compressed(),       # 200 tokens
    repo_context = RankedFileSet.top_5(),       # ≤ 1,000 tokens
    memory      = WorkingMemory.current(),      # ≤ 800 tokens
    recent_turns = TurnBuffer.last_N(),         # ≤ 4,000 tokens
  ) → PromptSections                           # ≤ 32,000 total

Step 2: MODEL CALL
  adapter.complete(PromptSections, tool_schemas) → ModelResponse
    ModelResponse = {
      reasoning: str,
      tool_call: Optional[ToolCall],
      done_candidate: Optional[DoneCandidate],
    }

Step 3: VALIDATE
  If tool_call:
    3a. ReasoningValidator.check(tool_call.reasoning)    → pass/reject
    3b. PathValidator.check(tool_call.args.file_path)    → pass/reject
    3c. ToolCallDeduplicator.check(tool_call.fingerprint) → pass/reject

Step 4: EXECUTE
  tool_result = ToolEngine.execute(tool_call)
    → Sandboxed, timed, atomic, AST-validated

Step 5: TRUNCATE
  truncated = ContextManager.truncate_observation(tool_result.raw_output)

Step 6: LOG
  TelemetryWriter.append(TelemetryEvent(...))

Step 7: TRANSITION
  StateMachine.transition(current_state, tool_result)
    → ACT→OBSERVE→REFLECT (normal)
    → DONE_CANDIDATE (agent signals completion)
    → FAILED (step limit or loop limit exceeded)
```

### 5.3 Multi-Agent Data Flow

```
Orchestrator
     │
     │  spawn with: IssuePlan + file_tree.txt + module_symbols.json
     ▼
  Scout Agent  ──────────► .harness/scout_report.md
     │                          │
     │ read scout_report        │
     ▼                          ▼
  Architect Agent ───────► .harness/architecture_plan.md
     │                          │
     │ read plan + target file  │
     ▼                          ▼
  Coder Agent(s) ─────────► .harness/patch_{file}_{step}.diff
     │                          │
     │ read patches + tests     │
     ▼                          ▼
  Critic Agent ────────────► .harness/critic_report.md
     │                          │
     │ APPROVE or REVISE        │
     ▼                          │
  Orchestrator applies patches  │
     │                          │
     ▼                          ▼
  VerificationGate         All artifacts in .harness/
```

**Key constraint:** Each subagent receives **only its designated inputs** — never the full orchestrator context. This is how we achieve context isolation and token efficiency.

---

## 6. State Machine Specification

### 6.1 States

| State | Description | Entry Condition | Exit Condition |
|---|---|---|---|
| `INIT` | Load config, parse issue, build repo index, capture baselines | Program start | `IssuePlan` + `RepoIndex` ready |
| `PLAN` | Generate ordered step list with tool predictions | `INIT` complete or plan revision triggered | Plan JSON emitted and validated |
| `ACT` | Execute exactly ONE tool call | Plan step selected | Tool returns result |
| `OBSERVE` | Truncate and log tool result | Tool execution complete | Truncated result available |
| `REFLECT` | Analyze result, decide next action | Observation processed | Next state selected |
| `DONE_CANDIDATE` | Agent signals completion → trigger VerificationGate | Agent emits `DONE_CANDIDATE` JSON | All 6 verification phases run |
| `DONE` | All phases passed → generate report → exit 0 | `VerificationGate.status == PASS` | Report written, process exits |
| `FAILED` | Graceful exit → rollback → partial report → exit 1 | Max steps/loops/revisions exceeded | Rollback + report, process exits |

### 6.2 Full Transition Table

```
┌───────────────┬────────────────────────┬──────────────────┬──────────────────┐
│ Current State  │ Event / Condition      │ Next State       │ Actions          │
├───────────────┼────────────────────────┼──────────────────┼──────────────────┤
│ INIT          │ IssuePlan ready         │ PLAN             │ Write issue_plan │
│ PLAN          │ Plan JSON valid         │ ACT              │ Write plan.md    │
│ PLAN          │ Plan JSON invalid       │ PLAN (retry)     │ Inject format err│
│ ACT           │ Tool result received    │ OBSERVE          │ —                │
│ ACT           │ step_count >= max_steps │ FAILED           │ GracefulExit     │
│ OBSERVE       │ Truncation complete     │ REFLECT          │ Log telemetry    │
│ REFLECT       │ Next step chosen        │ ACT              │ —                │
│ REFLECT       │ DONE_CANDIDATE emitted  │ DONE_CANDIDATE   │ —                │
│ REFLECT       │ REVISE_PLAN emitted     │ PLAN             │ Inject lessons   │
│ REFLECT       │ revision_count >= max   │ FAILED           │ GracefulExit     │
│ REFLECT       │ loop_count >= max       │ PLAN (or FAILED) │ Escalate         │
│ DONE_CANDIDATE│ Verify: ALL PASS        │ DONE             │ Flush telemetry  │
│ DONE_CANDIDATE│ Verify: any FAIL        │ REFLECT          │ Inject recovery  │
│ DONE          │ —                       │ (exit 0)         │ Write report.md  │
│ FAILED        │ —                       │ (exit 1)         │ Rollback + report│
└───────────────┴────────────────────────┴──────────────────┴──────────────────┘
```

### 6.3 Guard Conditions (Enforced by Orchestrator)

```python
class Guards:
    step_count: int = 0           # Incremented on each ACT
    loop_count: int = 0           # Incremented on circuit breaker trigger
    revision_count: int = 0       # Incremented on REVISE_PLAN
    verification_attempts: int = 0 # Incremented on each DONE_CANDIDATE

    MAX_STEPS: int          # from config.agent.max_steps (default: 25)
    MAX_LOOPS: int          # from config.agent.max_loop_count (default: 3)
    MAX_REVISIONS: int      # from config.agent.max_plan_revisions (default: 3)
    MAX_VERIFY_ATTEMPTS: int = 3  # Verification retries before FAILED
```

### 6.4 State Machine ASCII Diagram

```
                         ┌─────────┐
                         │  INIT   │
                         └────┬────┘
                              │
                              ▼
         ┌──────────────►┌─────────┐◄───────────────────────┐
         │               │  PLAN   │                         │
         │               └────┬────┘                         │
         │                    │                              │
         │                    ▼                              │
         │               ┌─────────┐    step >= max         │
         │        ┌─────►│   ACT   ├──────────────────► FAILED
         │        │      └────┬────┘                         │
         │        │           │                              │
         │        │           ▼                              │
         │        │      ┌──────────┐                       │
         │        │      │ OBSERVE  │                       │
         │        │      └────┬─────┘                       │
         │        │           │                              │
         │        │           ▼                              │
         │        │      ┌──────────┐   loop >= max         │
         │        │  ┌───┤ REFLECT  ├───────────────────────┘
         │   next │  │   └──┬───┬───┘
         │   step │  │      │   │
         │        └──┘      │   │ DONE_CANDIDATE
         │                  │   │
         │ REVISE_PLAN      │   ▼
         │ (rev < max)      │ ┌───────────────┐
         └──────────────────┘ │DONE_CANDIDATE │
                              │ → 6-phase     │
                              │   verify      │
                              └──┬─────────┬──┘
                           PASS  │         │ FAIL
                                 ▼         ▼
                           ┌──────┐   RecoveryEngine
                           │ DONE │   → inject feedback
                           │ exit0│   → re-enter REFLECT
                           └──────┘
```

---

## 7. Layer-by-Layer Technical Design

### 7.1 Layer Architecture Summary

```
  Layer   Name                           Key Class                  Config Prefix
  ─────   ────                           ─────────                  ─────────────
  L1      Issue Parsing & Planning       IssueParser                —
  L2      Repository Intelligence        RepoIntelligenceEngine     —
  L3      Hardened Tool Engine           ToolEngine                 tools.*
  L4      Context & Memory Manager       ContextManager             context.*
  L5      Multi-Agent Orchestrator       Orchestrator               agent.*
  L6      External Skill Retriever       SkillRetriever             external_skills.*
  L7      Verification Gate              VerificationGate           verification.*
  L8      Recovery Engine                RecoveryEngine             agent.*
  L9      Telemetry & Reporting          TelemetryWriter, ReportGen telemetry.*, report.*
  L10     Model Adapter Layer            ModelAdapter               model.*
```

### 7.2 Layer Interaction Matrix

```
             L1   L2   L3   L4   L5   L6   L7   L8   L9   L10
   L1 Issue   ·    →    ·    ·    ←    ·    ·    ·    →     →
   L2 Repo    ←    ·    ·    →    ←    ·    ·    ·    →     ·
   L3 Tools   ·    ←    ·    →    ←    ·    ←    ·    →     ·
   L4 Context ·    ←    ←    ·    ←    ←    ·    ·    →     →
   L5 Orch    →    →    →    →    ·    →    →    →    →     →
   L6 Skills  ·    ·    ·    →    ←    ·    ·    ·    →     ·
   L7 Verify  ·    ·    →    ·    ←    ·    ·    →    →     ·
   L8 Recover ·    ·    ·    ·    ←    ·    ←    ·    →     ·
   L9 Telem   ←    ←    ←    ←    ←    ←    ←    ←    ·     ←
   L10 Model  ←    ·    ·    ←    ←    ·    ·    ·    ←     ·

   → = "calls / sends data to"
   ← = "receives data / calls from"
   ·  = "no direct interaction"
```

### 7.3 Layer Protocol: Request → Process → Response

Every layer interaction follows this protocol:

```
Caller                                    Callee Layer
  │                                            │
  ├── validate input (typed contract) ────────►│
  │                                            ├── process
  │                                            ├── emit TelemetryEvent
  │◄────── typed response contract ────────────┤
  │                                            │
  └── handle error_code if present             │
```

---

## 8. Inter-Component Data Contracts

### 8.1 Type System Overview

```python
# contracts.py — Single source of truth for ALL typed interfaces

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict
from datetime import datetime

# ─── Enums ────────────────────────────────────────────────

class TaskType(Enum):
    BUG_FIX = "BUG_FIX"
    FEATURE = "FEATURE"
    REFACTOR = "REFACTOR"
    TEST = "TEST"
    DOCS = "DOCS"
    PERF = "PERF"

class Complexity(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"

class AgentMode(Enum):
    SINGLE_REACT = "SINGLE_REACT"
    PLANNER_EXECUTOR = "PLANNER_EXECUTOR"
    MULTI_AGENT = "MULTI_AGENT"
    MULTI_AGENT_DEEP = "MULTI_AGENT_DEEP"

class AgentPhase(Enum):
    INIT = "INIT"
    PLAN = "PLAN"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    REFLECT = "REFLECT"
    DONE_CANDIDATE = "DONE_CANDIDATE"
    DONE = "DONE"
    FAILED = "FAILED"

class ResultStatus(Enum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"

class ErrorCode(Enum):
    PATCH_FAILED = "PATCH_FAILED"
    AST_PARSE_FAIL = "AST_PARSE_FAIL"
    LINT_REGRESSION = "LINT_REGRESSION"
    TEST_FAILED = "TEST_FAILED"
    REGRESSION_DETECTED = "REGRESSION_DETECTED"
    SIDE_EFFECT_DETECTED = "SIDE_EFFECT_DETECTED"
    TIMEOUT = "TIMEOUT"
    TOOL_BLOCKED = "TOOL_BLOCKED"
    LOOP_DETECTED = "LOOP_DETECTED"
    MAX_STEPS_EXCEEDED = "MAX_STEPS_EXCEEDED"

class VerificationPhase(Enum):
    SYNTAX = "SYNTAX"
    LINT = "LINT"
    REPRO_TEST = "REPRO_TEST"
    REGRESSION = "REGRESSION"
    DIFF_AUDIT = "DIFF_AUDIT"
    SIDE_EFFECT = "SIDE_EFFECT"

class EventType(Enum):
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    LLM_TURN_START = "LLM_TURN_START"
    LLM_TURN_END = "LLM_TURN_END"
    VERIFICATION_PHASE = "VERIFICATION_PHASE"
    RECOVERY_EVENT = "RECOVERY_EVENT"
    PLAN_REVISION = "PLAN_REVISION"
    SUBAGENT_SPAWN = "SUBAGENT_SPAWN"
    SUBAGENT_RESULT = "SUBAGENT_RESULT"
    SKILL_FETCH = "SKILL_FETCH"
    CONTEXT_COMPRESSION = "CONTEXT_COMPRESSION"
    ROLLBACK = "ROLLBACK"
    CHECKPOINT = "CHECKPOINT"
    DONE = "DONE"
    FAILED = "FAILED"
    INIT = "INIT"
    PLAN_EMIT = "PLAN_EMIT"
    DONE_CANDIDATE = "DONE_CANDIDATE"
    SESSION_START = "SESSION_START"

class SubagentRole(Enum):
    SCOUT = "scout"
    ARCHITECT = "architect"
    CODER = "coder"
    CRITIC = "critic"
```

### 8.2 Core Data Contracts

```python
# ─── L1: Issue Parser ─────────────────────────────

@dataclass
class SuspectedFile:
    path: str
    confidence: float               # 0.0 – 1.0
    reason: str
    suspected_symbol: Optional[str] = None

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
    parsing_method: str             # "RULE_BASED" | "LLM_ASSISTED"

# ─── L2: Repo Intelligence ────────────────────────

@dataclass
class RankedFile:
    path: str
    relevance_score: float          # 0.0 – 1.0
    symbol_summary: str             # Signatures only, no bodies
    line_count: int
    language: str

@dataclass
class RankedFileSet:
    files: List[RankedFile]         # Sorted by relevance_score desc
    total_indexed: int
    index_tokens_cost: int

@dataclass
class RepoIndex:
    file_tree_path: str
    module_symbols_path: str
    dependency_graph_path: str
    test_map_path: str
    embedding_index_path: str
    total_files: int
    build_time_ms: int

# ─── L3: Tool Engine ──────────────────────────────

@dataclass
class ToolCall:
    tool: str
    reasoning: str
    args: Dict
    fingerprint: str                # SHA256(tool + canonical(args))

@dataclass
class ToolResult:
    tool: str
    args_hash: str
    status: ResultStatus
    raw_output: str
    truncated_output: str
    exit_code: Optional[int]
    error_code: Optional[ErrorCode]
    tokens_in_raw: int
    tokens_in_truncated: int
    execution_time_ms: int

# ─── L4: Context Manager ──────────────────────────

@dataclass
class PromptSections:
    persona: str                    # Fixed, ~300 tokens
    issue_goal: str                 # Fixed per issue, ~200 tokens
    repo_context: str               # Dynamic, ≤ 1,000 tokens
    working_memory: str             # Rolling, ≤ 800 tokens
    recent_turns: str               # Last N raw turns, ≤ 4,000 tokens
    total_tokens: int
    budget_remaining: int

@dataclass
class WorkingMemory:
    goal: str
    files_examined: Dict[str, str]  # {path: finding}
    edits_applied: List[str]
    test_status: str
    current_strategy: str
    lessons_learned: List[str]

# ─── L5: Orchestrator ─────────────────────────────

@dataclass
class PlanStep:
    step: int
    description: str
    tool_prediction: str
    expected_outcome: str

@dataclass
class AgentPlan:
    steps: List[PlanStep]
    estimated_total_steps: int
    risk_factors: List[str]
    rollback_checkpoints: List[int]

@dataclass
class DoneCandidate:
    confidence: float
    evidence: List[str]
    files_modified: List[str]

@dataclass
class SessionResult:
    status: AgentPhase              # DONE or FAILED
    exit_code: int
    total_steps: int
    total_tokens: int
    total_cost_usd: float
    total_wall_time_ms: int
    verification_result: Optional['VerificationResult']

# ─── L7: Verification Gate ────────────────────────

@dataclass
class PhaseResult:
    phase: VerificationPhase
    status: ResultStatus
    detail: str
    duration_ms: int

@dataclass
class VerificationResult:
    verification_id: str
    run_at: datetime
    status: ResultStatus            # PASS or FAIL
    phases: Dict[VerificationPhase, PhaseResult]
    first_failure: Optional[VerificationPhase]
    recovery_action: Optional[str]
    diff_summary: str
    total_duration_ms: int

# ─── L8: Recovery Engine ──────────────────────────

@dataclass
class RecoveryAction:
    error_code: ErrorCode
    level: int                      # 1 = auto-remediate, 2 = plan revision, 3 = exit
    action_description: str
    injection_prompt: str           # Text injected into next agent turn
    rollback_required: bool
    rollback_scope: str             # "file" | "all" | "checkpoint"

# ─── L9: Telemetry ────────────────────────────────

@dataclass
class TelemetryEvent:
    schema_version: str = "1.0"
    event_id: str = ""
    session_id: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    step: int = 0
    phase: AgentPhase = AgentPhase.INIT
    agent: str = "orchestrator"
    event_type: EventType = EventType.INIT
    tool: Optional[str] = None
    tool_args_hash: Optional[str] = None
    reasoning: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cumulative: int = 0
    cost_usd: float = 0.0
    cost_cumulative_usd: float = 0.0
    latency_ms: int = 0
    result_status: ResultStatus = ResultStatus.SUCCESS
    error_code: Optional[ErrorCode] = None
    recovery_triggered: bool = False
    loop_count: int = 0
    revision_count: int = 0
    context_tokens_used: int = 0
    context_budget: int = 32000
    context_utilization_pct: float = 0.0
```

---

## 9. Tool Engine Internals

### 9.1 Tool Execution Pipeline

```
Model emits ToolCall JSON
         │
         ▼
┌─────────────────────────────┐
│  1. JSON Schema Validation  │  Reject malformed calls immediately
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  2. Reasoning Validator     │  Reject if reasoning field is empty
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  3. Path Validator          │  Reject if path outside REPO_PATH
│     (for file-based tools)  │  Reject if path contains ../
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  4. ToolCallDeduplicator    │  Reject if fingerprint seen
│     (10-call ring buffer)   │  within window without edit
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  5. Security Blocklist      │  Reject if command matches
│     (for bash/test tools)   │  any of 12 blocked patterns
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  6. EXECUTE (atomic)        │
│     • File ops: try/except  │
│     • Subprocess: sandbox   │
│     • Patch: apply + AST    │
│       validate + rollback   │
│       on failure            │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  7. Post-Execute AST Check  │  For apply_patch and write_file:
│     (for edit tools only)   │  run syntax parser on modified file
│                             │  if FAIL: auto-rollback + return error
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  8. Telemetry Emit          │  Append TelemetryEvent with result
└─────────────┬───────────────┘
              │
              ▼
         ToolResult
```

### 9.2 Tool Categories & Sandbox Levels

```
┌──────────────┬──────────────────────┬───────────────────────┐
│ Category     │ Tools                │ Sandbox Level         │
├──────────────┼──────────────────────┼───────────────────────┤
│ READ-ONLY    │ list_dir             │ None                  │
│              │ search_code          │ (ripgrep subprocess)  │
│              │ read_file_range      │ None                  │
│              │ get_symbol           │ None (in-process AST) │
│              │ find_references      │ None (in-process AST) │
│              │ get_imports          │ None (in-process AST) │
│              │ list_symbols         │ None (in-process AST) │
│              │ git_diff             │ (git subprocess)      │
│              │ git_status           │ (git subprocess)      │
├──────────────┼──────────────────────┼───────────────────────┤
│ WRITE        │ apply_patch          │ File + AST validation │
│              │ write_file           │ Path validation       │
│              │ git_rollback         │ File / all scope      │
├──────────────┼──────────────────────┼───────────────────────┤
│ EXECUTE      │ run_bash_sandboxed   │ FULL SANDBOX          │
│              │ run_test_suite       │ FULL SANDBOX          │
│              │                      │ (timeout + memory +   │
│              │                      │  blocklist + shell=F) │
├──────────────┼──────────────────────┼───────────────────────┤
│ NETWORK      │ fetch_external_skill │ Cache-first + TTL     │
│              │                      │ Rate-limited          │
└──────────────┴──────────────────────┴───────────────────────┘
```

---

## 10. Multi-Agent Orchestration Internals

### 10.1 Agent Spawning Decision Tree

```
IssuePlan.complexity_estimate
    │
    ├── LOW ──────────► SINGLE_REACT mode
    │                   • One agent, full loop
    │                   • Max steps: 15
    │
    ├── MEDIUM ────────► PLANNER_EXECUTOR mode
    │                   • Spawn: Scout + Coder
    │                   • Max steps: 25
    │
    ├── HIGH ──────────► MULTI_AGENT mode
    │                   • Spawn: Scout + Architect + Coder + Critic
    │                   • Max steps: 40
    │
    └── VERY_HIGH ────► MULTI_AGENT_DEEP mode
                        • Spawn: Scout + Architect + Coder×N + Critic
                        • Max steps: 55
                        • One Coder per file to modify
```

### 10.2 Context Isolation Boundaries

```
┌────────────────────────────────────────────────────────────────┐
│ Orchestrator Context (full)                                     │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ HAS: IssuePlan, RepoIndex, plan history, all telemetry    │   │
│ └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │ Scout Context  │  │ Architect Ctx   │  │ Coder Context  │  │
│  │ (8k budget)    │  │ (6k budget)     │  │ (10k budget)   │  │
│  │                │  │                 │  │                │  │
│  │ HAS:           │  │ HAS:            │  │ HAS:           │  │
│  │ • IssuePlan    │  │ • IssuePlan     │  │ • arch_plan.md │  │
│  │ • file_tree    │  │ • scout_report  │  │ • target file  │  │
│  │ • symbols.json │  │                 │  │   snippet ONLY │  │
│  │                │  │ NOT:            │  │                │  │
│  │ NOT:           │  │ • file contents │  │ NOT:           │  │
│  │ • file bodies  │  │ • file_tree     │  │ • other files  │  │
│  │ • test results │  │ • test results  │  │ • scout_report │  │
│  │ • prior plans  │  │ • prior plans   │  │ • plan history │  │
│  └────────────────┘  └─────────────────┘  └────────────────┘  │
│                                                                  │
│  ┌────────────────┐                                             │
│  │ Critic Context │                                             │
│  │ (6k budget)    │                                             │
│  │                │                                             │
│  │ HAS:           │                                             │
│  │ • IssuePlan    │                                             │
│  │ • all patches  │                                             │
│  │ • test results │                                             │
│  │                │                                             │
│  │ NOT:           │                                             │
│  │ • scout_report │                                             │
│  │ • arch_plan    │                                             │
│  │ • file_tree    │                                             │
│  └────────────────┘                                             │
└────────────────────────────────────────────────────────────────┘
```

### 10.3 Subagent Communication Protocol

```
Orchestrator                       Subagent
     │                                │
     ├── spawn(role, input_files) ──►│  (new clean context)
     │                                │
     │                                ├── process with own agent loop
     │                                │   (can use tools: read, search, get_symbol)
     │                                │   (CANNOT use: apply_patch, write_file, git_*)
     │                                │
     │◄── structured .md output ──────┤  (Scout: scout_report.md)
     │                                │  (Architect: architecture_plan.md)
     │                                │  (Coder: patch.diff)
     │                                │  (Critic: critic_report.md)
     │                                │
     └── parse + validate output      │
                                      └── context discarded
```

---

## 11. Context Window Memory Model

### 11.1 5-Section Memory Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     CONTEXT WINDOW                       │
│                  (max: 32,000 tokens)                    │
│                                                          │
│  ┌─────────────────────────┐                            │
│  │ § PERSONA (300 tok)     │ ◄── KV cache reuse         │
│  │ Fixed across all turns  │     (byte-identical)       │
│  ├─────────────────────────┤                            │
│  │ § GOAL (200 tok)        │ ◄── KV cache reuse         │
│  │ Fixed per issue         │     (byte-identical)       │
│  ├─────────────────────────┤                            │
│  │ § REPO CONTEXT (≤1000)  │ ◄── Dynamic                │
│  │ Top-5 ranked files      │     Trimmed by score       │
│  │ + external skill snippet│                            │
│  ├─────────────────────────┤                            │
│  │ § WORKING MEMORY (≤800) │ ◄── Rolling compression    │
│  │ Compressed older turns  │     Triggered at 70%       │
│  │ Goal|Files|Edits|Tests  │     threshold              │
│  ├─────────────────────────┤                            │
│  │ § RECENT TURNS (≤4000)  │ ◄── Sliding window         │
│  │ Last N raw turns        │     N adjusted to fit      │
│  │ (verbatim for accuracy) │                            │
│  ├─────────────────────────┤                            │
│  │ [RESPONSE RESERVE 4000] │ ◄── Not sent to model      │
│  │ Reserved for output     │     Budget headroom        │
│  └─────────────────────────┘                            │
└─────────────────────────────────────────────────────────┘
```

### 11.2 Memory Lifecycle

```
Turn 1:  All sections fit within budget.
         recent_turns = [turn_1]

Turn 2:  recent_turns = [turn_1, turn_2]

Turn N:  recent_turns growing → approaching RECENT_TURNS_BUDGET
         │
         ▼
Turn N+1: TokenBudgetManager detects overflow
         │
         ├── Move oldest raw turn to WorkingMemory (compress)
         │   working_memory += compress(turn_oldest)
         │   recent_turns.pop_left()
         │
         └── If working_memory > WORKING_MEMORY_BUDGET:
             │
             └── Lossy re-compress working_memory
                 (discard verbose findings, keep decisions + edits + tests)

Turn M:  Context usage >= 70% of MAX_CONTEXT_TOKENS
         │
         └── RollingSummarizer triggered
             Compress oldest 50% of raw turns into WorkingMemory block
             Write .harness/context_summary.md
```

---

## 12. Verification Pipeline Internals

### 12.1 Pipeline Execution Flow

```
Modified files from git_status
              │
              ▼
  ┌────────────────────┐
  │ Phase 1: SYNTAX    │──── FAIL ──► Stop. Return PATCH_FAILED.
  │ py_compile / tsc   │
  └────────┬───────────┘
           │ PASS
           ▼
  ┌────────────────────┐
  │ Phase 2: LINT      │──── FAIL ──► Return LINT_REGRESSION
  │ ruff (delta mode)  │             (with violation locations)
  └────────┬───────────┘
           │ PASS
           ▼
  ┌────────────────────┐
  │ Phase 3: REPRO     │──── FAIL ──► Return TEST_FAILED
  │ test_filter only   │             (with stack trace)
  └────────┬───────────┘
           │ PASS
           ▼
  ┌────────────────────┐
  │ Phase 4: REGRESSION│──── FAIL ──► Return REGRESSION_DETECTED
  │ full suite - base  │             (with diff of new failures)
  └────────┬───────────┘
           │ PASS
           ▼
  ┌────────────────────┐
  │ Phase 5: DIFF AUDIT│──── FAIL ──► Return DIFF_ANOMALY (soft)
  │ scope + binary +   │
  │ whitespace checks  │
  └────────┬───────────┘
           │ PASS
           ▼
  ┌────────────────────┐
  │ Phase 6: SIDE-EFF  │──── FAIL ──► Return SIDE_EFFECT_DETECTED
  │ importlib isolate  │
  └────────┬───────────┘
           │ PASS
           ▼
  ALL PASS → VerificationResult(status=PASS)
```

### 12.2 Baseline Capture (At Startup)

```python
def capture_baselines(repo_path):
    """Run BEFORE any agent modifications. Creates baseline files."""

    # Lint baseline: capture all pre-existing violations
    linter_output = run_linter(repo_path)
    save_json(".harness/repo_index/linter_baseline.json", linter_output)

    # Test baseline: capture any pre-existing failing tests
    test_result = run_test_suite(repo_path, timeout=120)
    failing_tests = extract_failures(test_result)
    save_json(".harness/repo_index/test_baseline.json", {
        "total": test_result.total,
        "passed": test_result.passed,
        "failed": test_result.failed,
        "failing_tests": failing_tests,
        "timestamp": now().isoformat()
    })
```

---

## 13. Recovery Engine Internals

### 13.1 3-Level Recovery Architecture

```
                         FAILURE EVENT
                              │
                              ▼
                    ┌──────────────────┐
                    │ Error Classifier │
                    │ (10-code taxonomy)│
                    └────────┬─────────┘
                             │
                   ┌─────────┼──────────┐
                   │         │          │
                   ▼         ▼          ▼
             ┌──────────┐ ┌──────┐ ┌──────────┐
             │ LEVEL 1  │ │  L2  │ │ LEVEL 3  │
             │ Auto-    │ │ Plan │ │ Graceful │
             │ Remediate│ │ Rev  │ │ Exit     │
             └────┬─────┘ └──┬───┘ └────┬─────┘
                  │          │          │
            Re-enter     Re-enter    Rollback
            REFLECT       PLAN       + report
                  │          │          │
                  │          │          ▼
                  │          │      exit(1)
                  ▼          ▼
            Continue loop
```

### 13.2 Circuit Breaker Ring Buffer

```
RingBuffer(capacity=5):

  Position:  [0]   [1]   [2]   [3]   [4]
  Content:   fp_A  fp_B  fp_A  fp_C  fp_A
                                        ↑
                                     current

  Check algorithm:
    new_fingerprint = hash(tool + args)

    consecutive_match = (buffer[-1] == new_fingerprint)
    window_match_count = buffer.count(new_fingerprint)

    if consecutive_match:
        → LEVEL 2: BLOCK + strategy shift injection
        loop_count += 1
    elif window_match_count >= 2:
        → LEVEL 1: WARNING (no block)

    if loop_count >= 3:
        → LEVEL 3: ESCALATE to plan revision
```

---

## 14. Token Economy & Cost Model

### 14.1 Token Flow Diagram

```
                           MODEL CALL
                     ┌──────────┬──────────┐
                     │ INPUT    │  OUTPUT   │
                     │ tokens   │  tokens   │
                     └────┬─────┴────┬──────┘
                          │          │
  ┌───────────────────────┤          │
  │                       │          │
  ▼                       ▼          ▼
PERSONA (300)      + REPO_CTX (≤1k) │
GOAL    (200)      + MEMORY   (≤800)│
                   + TURNS    (≤4k) │
                   ────────────────── │
                   = PROMPT   (≤8k)  = RESPONSE (≤4k)
                          │          │
                          ▼          ▼
                    COST = (prompt × $0.075/M) + (response × $0.30/M)
                          │
                          ▼
                 CUMULATIVE TRACKED IN telemetry.jsonl
                          │
                          ▼
                    REPORTED IN report.md
```

### 14.2 Token Savings Waterfall (per 40k-token run vs naive approach)

```
Naive agent (estimated):         120,000 tokens
─────────────────────────────────────────────────
  T1: Symbol reads vs full files     -40,000 tokens
  T2: Top-5 ranking vs full index    -12,000 tokens
  T3: Observation truncation          -8,000 tokens
  T4: Rolling compression             -6,000 tokens
  T5: Context isolation (subagents)   -5,000 tokens
  T7: Deduplication                   -4,000 tokens
  T8: Rule-based parsing              -3,000 tokens
  T6: Skill cache                     -1,000 tokens
  T9: Fixed prompt schema             -1,000 tokens
─────────────────────────────────────────────────
  Total savings:                     -80,000 tokens
  Zenith target:                      40,000 tokens
  Reduction:                             67%
```

---

## 15. Concurrency & Async Architecture

### 15.1 Async Execution Model

```python
# Zenith uses asyncio for three purposes:
# 1. Startup pre-fetch (parallel skill cache population)
# 2. Model API calls (non-blocking I/O)
# 3. Subprocess timeout enforcement

import asyncio

async def main():
    # Phase 1: Parallel startup
    issue_plan, repo_index = await asyncio.gather(
        parse_issue(issue_text),
        build_repo_index(repo_path),
    )
    await prefetch_skills(repo_path, issue_plan)

    # Phase 2: Sequential agent loop (no parallelism in main loop)
    # Agent loop is STRICTLY sequential:
    #   PLAN → ACT → OBSERVE → REFLECT → ...
    # This is by design — each step depends on the previous result.

    result = await orchestrator.run(issue_plan, repo_index)
```

### 15.2 Subprocess Management

```python
async def run_sandboxed(command: List[str], timeout: int = 30) -> ToolResult:
    """Execute subprocess with hard limits."""

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=set_resource_limits,  # Memory: 512MB
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult(status=ResultStatus.TIMEOUT, error_code=ErrorCode.TIMEOUT, ...)

    return ToolResult(
        status=ResultStatus.SUCCESS if proc.returncode == 0 else ResultStatus.FAIL,
        raw_output=truncate_output(stdout.decode() + stderr.decode()),
        exit_code=proc.returncode,
    )
```

---

## 16. Model Adapter Interface

### 16.1 Protocol Definition

```python
from typing import Protocol, List

class ModelAdapter(Protocol):
    """Pluggable foundation model interface."""

    async def complete(
        self,
        prompt: PromptSections,
        tools: List[ToolSchema],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        """Send prompt + tools, receive structured response."""
        ...

    def count_tokens(self, text: str) -> int:
        """Count tokens for the given text."""
        ...

    def supports_kv_cache(self) -> bool:
        """True if model can cache prefix tokens across turns."""
        ...

    def supports_structured_output(self) -> bool:
        """True if model supports JSON schema response format."""
        ...

    def max_context_tokens(self) -> int:
        """Maximum input token window."""
        ...

    def model_name(self) -> str:
        """Human-readable model identifier."""
        ...
```

### 16.2 Adapter Dispatch

```python
def resolve_model_adapter(config: ModelConfig) -> ModelAdapter:
    """Factory: pick adapter based on config.model.name."""

    name = config.name.lower()

    if "gemini" in name:
        return GeminiAdapter(config)
    elif "claude" in name:
        return ClaudeAdapter(config)
    elif "gpt" in name or "o1" in name or "o3" in name:
        return OpenAIAdapter(config)
    elif "ollama" in name or "localhost" in config.base_url:
        return LocalOllamaAdapter(config)
    else:
        raise ValueError(f"Unknown model: {config.name}. Add an adapter.")
```

---

## 17. File System Layout

### 17.1 Project Structure (Source)

```
zenith/
├── Makefile                          # Build targets: setup, run, test, clean, lint
├── Dockerfile                        # Clean-clone verification container
├── README.md                         # Setup + run instructions for evaluators
├── harness_config.yaml               # All 50+ runtime parameters
├── requirements.txt                  # Pinned dependencies
├── .env.example                      # AI_API_KEY=your_key_here
├── .gitignore                        # .env, .venv, .harness/, __pycache__
│
├── harness/                          # Source code
│   ├── __init__.py
│   ├── cli.py                        # Entry point + arg parsing
│   ├── config.py                     # Config loader + validator
│   ├── contracts.py                  # ALL inter-layer dataclasses
│   ├── telemetry.py                  # JSONL writer + cost tracker
│   ├── issue_parser.py               # L1
│   ├── repo_intelligence.py          # L2
│   ├── tool_engine.py                # L3
│   ├── context_manager.py            # L4
│   ├── orchestrator.py               # L5
│   ├── skill_retriever.py            # L6
│   ├── verification.py               # L7
│   ├── recovery.py                   # L8
│   ├── report_generator.py           # L9
│   └── adapters/                     # L10
│       ├── __init__.py
│       ├── base.py                   # ModelAdapter protocol
│       ├── gemini_adapter.py
│       ├── claude_adapter.py
│       └── openai_adapter.py
│
└── tests/                            # Test suite
    ├── fixtures/                     # Sample data for tests
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

### 17.2 Runtime Artifacts (`.harness/` — per run)

```
.harness/
├── issue_plan.json                   # IssuePlan (written before turn 1)
├── plan.md                           # Agent's ordered step plan
├── scout_report.md                   # Scout findings (multi-agent only)
├── architecture_plan.md              # Architect plan (HIGH+ only)
├── patch_{file}_{step}.diff          # Coder patches (multi-agent only)
├── critic_report.md                  # Critic assessment (multi-agent only)
├── telemetry.jsonl                   # Append-only event stream
├── context_summary.md                # Latest working memory snapshot
├── checkpoint_{N}.diff               # Rollback checkpoint diffs
├── skill_cache/                      # External knowledge cache
│   └── {SHA256_hash}.json
├── repo_index/                       # Cached repository index
│   ├── file_tree.txt
│   ├── module_symbols.json
│   ├── dependency_graph.json
│   ├── test_map.json
│   ├── linter_baseline.json
│   ├── test_baseline.json
│   └── embedding_index/
│       ├── index.faiss
│       └── metadata.json
└── report.md                         # Auto-generated final report
```

---

## 18. Security Architecture

### 18.1 Defense-in-Depth Layers

```
Layer 1: INPUT VALIDATION
  ├── CLI args: validated types, path existence checks
  ├── Config: schema validation with sensible defaults
  └── Issue text: sanitized for injection (no code execution)

Layer 2: MODEL OUTPUT VALIDATION
  ├── Tool calls: JSON schema validated before execution
  ├── Reasoning field: required (reject if empty)
  ├── Path arguments: must be within REPO_PATH (no ../)
  └── DONE claims: completely ignored by verification gate

Layer 3: TOOL EXECUTION GUARDS
  ├── ToolCallDeduplicator: blocks redundant calls
  ├── Security blocklist: 12 regex patterns
  ├── Path traversal detector: rejects ../ patterns
  └── Output limits: hard caps on all tool outputs

Layer 4: SUBPROCESS SANDBOX
  ├── shell=False: no shell injection
  ├── Explicit args list: no wildcard expansion
  ├── Timeout: hard 30s kill (120s for test suite)
  ├── Memory limit: 512MB RSS
  └── No network access inside sandbox

Layer 5: FILE SYSTEM SCOPE
  ├── All file tools scoped to REPO_PATH
  ├── .harness/ directory for all artifacts
  └── No writes outside REPO_PATH + .harness/

Layer 6: SECRET MANAGEMENT
  ├── AI_API_KEY: only from os.environ
  ├── Never written to disk, logs, telemetry
  ├── .env in .gitignore
  └── Automated grep audit in CI
```

### 18.2 Threat Model

| Threat | Attack Vector | Mitigation |
|---|---|---|
| **Command injection** | Model generates `; rm -rf /` in bash args | `shell=False` + explicit args + blocklist |
| **Path traversal** | Model reads `../../etc/passwd` | Pre-tool path validation + regex check |
| **Secret exfiltration** | Model tries to `curl` API key | Network blocked in sandbox + key never in context |
| **Infinite resource use** | Model loops or spawns expensive commands | Step limit + timeout + memory limit + circuit breaker |
| **Fork bomb** | Model runs `:(){ :|:& };:` | Blocklist match + shell=False |
| **Code injection via patch** | Model injects malicious code into repo | AST parse after every patch; side-effect check in verification |
| **False success report** | Model claims fix without testing | DONE_CANDIDATE → VerificationGate only |

---

## 19. Observability & Telemetry Architecture

### 19.1 Event Flow

```
  Component Action
       │
       ├── TelemetryEvent created (with all 25 fields)
       │
       ▼
  TelemetryWriter.append()
       │
       ├── Write JSON line to .harness/telemetry.jsonl (immediate)
       ├── Update cumulative counters (tokens, cost)
       ├── If --verbose: print real-time dashboard line to stdout
       │
       ▼
  (At session end)
       │
       ▼
  ReportGenerator.generate()
       │
       ├── Read .harness/telemetry.jsonl
       ├── Aggregate: total tokens, cost, steps, duration
       ├── Group by: agent, phase, error code
       ├── Generate 8 sections of report.md
       │
       ▼
  .harness/report.md
```

### 19.2 Key Metrics Tracked

| Metric | Source | Aggregation | Displayed In |
|---|---|---|---|
| Tokens per turn | `TelemetryEvent.tokens_in/out` | Sum per session | report.md §1, §7 |
| Cost per turn | `TelemetryEvent.cost_usd` | Sum per session | report.md §1, §7 |
| Context utilization % | `TelemetryEvent.context_utilization_pct` | Max per session | Verbose dashboard |
| Recovery events | `TelemetryEvent.recovery_triggered` | Count per session | report.md §3 |
| Loop count | `TelemetryEvent.loop_count` | Max per session | Verbose dashboard |
| Revision count | `TelemetryEvent.revision_count` | Max per session | Verbose dashboard |
| Verification phases | `VerificationResult.phases` | All 6 phase statuses | report.md §4 |
| Step count | `TelemetryEvent.step` | Max per session | report.md §1 |
| Wall-clock time | Session start/end timestamps | Delta | report.md §1 |
| Subagent usage | `SUBAGENT_SPAWN` / `SUBAGENT_RESULT` events | Count per role | report.md §6 |

---

## 20. Failure Mode Analysis (FMEA)

| Failure Mode | Cause | Detection | Severity | Mitigation | Recovery Path |
|---|---|---|---|---|---|
| Model refuses to call tools | Bad system prompt or model confusion | No TOOL_CALL in response for 3 consecutive turns | HIGH | Inject explicit tool-use reminder prompt | Re-enter PLAN with guidance |
| Model calls nonexistent tool | Hallucinated tool name | JSON schema validation fails | MEDIUM | Return error with list of valid tools | Re-enter REFLECT |
| AST parser crashes on exotic syntax | Unsupported language construct | Exception in tree-sitter parse | LOW | Fallback to regex-based symbol extraction | Continue without AST for that file |
| FAISS index empty | No embeddable files in repo | `len(embedding_index) == 0` | MEDIUM | Fallback to file_tree.txt + path matching | Reduced ranking quality |
| Test suite hangs indefinitely | Infinite loop in test code | 120s timeout | MEDIUM | Kill process + TIMEOUT error | Agent uses more targeted test filter |
| Git state corrupted | Concurrent access or broken patch | `git status` returns unexpected state | HIGH | `git checkout -- .` hard reset | Re-enter from clean state |
| API rate limit hit | Too many model calls | HTTP 429 response | MEDIUM | Exponential backoff (1s, 2s, 4s, 8s, 16s) | Retry up to 5 times |
| Disk full | Large telemetry or test output | `IOError` on write | LOW | Truncate telemetry to last 1000 events | Continue with reduced logging |
| Memory exhaustion | Embedding index for huge repo | `MemoryError` | LOW | Limit index to top-500 files by size | Continue with partial index |
| Model returns empty response | API error or content filter | Empty `ModelResponse` | MEDIUM | Retry with lower temperature | Re-enter REFLECT if persistent |

---

## 21. Technology Stack & Dependencies

### 21.1 Runtime Dependencies

| Package | Purpose | Version (Pinned) |
|---|---|---|
| `google-generativeai` | Gemini API SDK | ≥ 0.8.0 |
| `tree-sitter` | AST parsing for symbol extraction | ≥ 0.21.0 |
| `tree-sitter-python` | Python grammar for tree-sitter | ≥ 0.21.0 |
| `tree-sitter-javascript` | JS/TS grammar | ≥ 0.21.0 |
| `faiss-cpu` | Embedding similarity search index | ≥ 1.7.0 |
| `sentence-transformers` | File summary embeddings (all-MiniLM-L6-v2) | ≥ 2.2.0 |
| `tiktoken` | Token counting (fallback) | ≥ 0.5.0 |
| `pyyaml` | Config file parsing | ≥ 6.0 |
| `pydantic` | Data validation + JSON schemas | ≥ 2.0 |
| `httpx` | Async HTTP for skill fetching | ≥ 0.25.0 |
| `python-dotenv` | .env file loading | ≥ 1.0 |

### 21.2 Development Dependencies

| Package | Purpose |
|---|---|
| `pytest` | Test runner |
| `pytest-asyncio` | Async test support |
| `pytest-cov` | Coverage reporting |
| `ruff` | Linter for harness source |

### 21.3 External Binaries (Optional)

| Binary | Purpose | Fallback |
|---|---|---|
| `rg` (ripgrep) | Fast code search | Python `re` + file walker |
| `git` | VCS operations | Required (no fallback) |

---

## 22. Architecture Decision Records (ADRs)

| ADR# | Decision | Context | Alternatives Considered | Rationale |
|---|---|---|---|---|
| ADR-001 | 9-layer modular architecture | Need clear ownership per concern | 6-layer (merged repo intel into orchestrator) | Merged layers too coupled; 9 layers map cleanly to hackathon rubric dimensions |
| ADR-002 | 6-phase sequential verification gate | Need deterministic success criteria | 3-phase (skip linter + side-effect) | Fewer phases miss regressions and lint pollution |
| ADR-003 | Multi-agent subagent pool with context isolation | Single-agent context degrades on complex tasks | Single monolithic agent | Context pollution proven to degrade accuracy; isolation saves ~50% tokens |
| ADR-004 | Rule-based issue parsing with LLM fallback | Most issues have extractable patterns | Pure LLM parsing for all | Wastes 1-2 LLM calls per issue on trivial extractions |
| ADR-005 | 5-section fixed prompt schema | Need predictable token usage | Freeform prompt construction | Freeform causes unpredictable bloat and impossible-to-debug context issues |
| ADR-006 | Tree-sitter AST for symbol resolution | Need semantic navigation, not grep | ripgrep only | Grep has no semantic understanding; hallucinated line numbers |
| ADR-007 | ToolCallDeduplicator with 10-call ring buffer | Most common waste: re-reading unchanged files | No deduplication | Wastes 20-30% of tokens in practice |
| ADR-008 | 3-level circuit breaker with hash window of 5 | Need to catch both immediate and oscillating loops | Simple 2-consecutive detection | Misses A→B→A oscillation patterns |
| ADR-009 | External skill cache with 24h TTL | Same docs re-fetched across runs | No caching | Redundant network calls + latency + rate limit risk |
| ADR-010 | KV cache exploitation via byte-identical prefix | Free token savings on models that support it | Dynamic prefix sections | Zero cost; 10k tokens saved on 20-turn run |
| ADR-011 | `asyncio` for startup parallelism only | Startup pre-fetch is embarrassingly parallel | Threading / multiprocessing | asyncio is cleaner for I/O-bound tasks; main loop is sequential by design |
| ADR-012 | `contracts.py` as single type file | Need typed interfaces between all layers | Types scattered across modules | Single file prevents circular imports and is easy to audit |
| ADR-013 | Dependency injection via composition root | Need testability and pluggability | Global singletons | DI enables unit testing with mocks; adapters are swappable |
| ADR-014 | Rollback checkpoints at plan-designated steps | Need targeted recovery, not just HEAD reset | Always rollback to HEAD | Preserves partial useful work from early plan steps |
| ADR-015 | ModelAdapter protocol for model swapping | Hackathon may require model changes mid-event | Hardcoded Gemini calls | Protocol allows hot-swapping model without code changes |

---

*Document Version: 1.0*
*Last Updated: 2026-09-26*
*Reference PRD: v4.0 (Elite Master)*
*All section numbers in PRD references use § notation*
