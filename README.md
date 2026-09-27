# Zenith — Autonomous AI Coding Harness

> **SOTA Autonomous Coding Harness for Benchmark-Driven Software Engineering**  
> *Developed for LCC × DevClub AI Coding Harness Hackathon 2026*

---

## ⚡ Overview

Zenith is a multi-agent, token-optimized, contract-driven AI coding harness designed to autonomously resolve complex software engineering issues across real-world codebases. It features:

- **9-Layer Decoupled Architecture:** From issue parsing and AST-level repository intelligence to a 6-phase deterministic verification gate and recovery engine.
- **Formal State Machine:** 11 deterministic states with cycle-breaking circuit breakers and rollback checkpoints.
- **Extreme Token Efficiency:** Built-in Ponytail-style user prompt compression (anchor-preserving heuristic + validated LLM rewrite), byte-stable system prompt prefix for implicit KV cache reuse, structured subagent context isolation, and rolling working memory compaction.
- **Zero-Tolerance Verification:** Multi-phase gates (Syntax → Delta Linter → Reproduction Test → Full Regression → Diff Audit → Side-Effect Check).
- **Comprehensive Telemetry:** Append-only JSONL event stream, real-time token/cost dashboard, and auto-compiled 8-section audit reports.

---

## 📚 Technical Documentation

- **[Product Requirements Document (PRD.md)](./PRD.md)** — v4.0 Elite Master specification covering all 15 operational sections.
- **[System Architecture Document (architecture.md)](./architecture.md)** — Exhaustive technical blueprints, C4 models, DAGs, memory models, and 15 ADRs.
- **[Sprint Phases Plan (phases.md)](./phases.md)** — 124 tracked engineering tasks across 7 phases (P0 to P6).
- **[Development Logs (logs.md)](./logs.md)** — Real-time progress tracker and audit log.

---

## 🚀 Quick Start

### 1. Requirements
- Python 3.10+ (or 3.11/3.12)
- Git
- `ripgrep` (recommended for fast indexing)

### 2. Standard Evaluation Workflow (Hackathon 2026)
```bash
# 1. Clone repository
git clone <repo-url>
cd Zenith

# 2. Configure API key
export AI_API_KEY="<PROVIDED_API_KEY>"

# 3. Setup environment and install dependencies
make setup

# 4. Launch AI Harness (launches Claude Code-style interactive REPL/TUI)
make run

# 5. Execute evaluation test suite
make test
```

### 3. Execution Options

```bash
# Batch mode on target repository and issue file:
make run REPO_PATH=/path/to/target_repo ISSUE_PATH=/path/to/issue.txt

# Model Provider Overrides (DeepSeek, Qwen, Gemini, OpenAI):
make run PROVIDER=deepseek MODEL=deepseek-chat BASE_URL=https://api.deepseek.com/v1
make run PROVIDER=qwen MODEL=qwen-2.5-coder-32b

# Direct CLI execution:
python -m harness.cli \
  --repo /path/to/target_repo \
  --issue /path/to/issue.txt \
  --provider deepseek \
  --model deepseek-chat \
  --trust

# Fast dry-run inspection (0-token validation):
python -m harness.cli --dry-run --repo . --issue tests/fixtures/sample_issues/issue_001.txt
```

### 4. Running Tests & Benchmarks

```bash
# Run full unit & integration test suite (190 tests, 79% line coverage)
make test

# Run 5-archetype SWE-bench benchmark suite (100% pass rate: django, flask, numpy, sympy, astropy)
pytest -v tests/test_benchmarks.py

# Run code linter (100% clean ruff verification)
make lint

# Run containerized clean-clone test
make docker-test

# Clean build artifacts and virtualenv
make clean
```

### 5. Output Artifacts & Verification

After any run (whether `PASS`, `FAIL`, or `PARTIAL`), Zenith automatically outputs:
- **`.harness/report.md`** — Comprehensive 8-section audit report (Executive Summary, Timeline, Recovery Events, Verification Results, Final Diff Applied, Agent Decisions Log, Token & Cost Breakdown, Lessons Learned).
- **`.harness/telemetry.jsonl`** — Full append-only telemetry stream covering all 18 JSONL event types with microsecond timestamps and cumulative cost accounting.
- **`.harness/recovery_log.json`** — Deterministic recovery state machine trace and circuit breaker status.

## 🏗️ Architecture at a Glance

```
Layer 1: Issue Parser       — Rule-based & LLM fallback extraction + confidence scoring
Layer 2: Repo Intelligence  — Tree-sitter AST, FAISS ranking, LSP semantic navigation
Layer 3: Tool Engine        — 15 specialized tools, deduplicator, sandboxed subprocess
Layer 4: Context Manager    — 5-section prompt schema, KV cache prefix, rolling memory
Layer 5: Orchestrator       — Formal state machine, subagent pool (Planner/Nav/Coder/Verifier)
Layer 6: Skill Retriever    — SWE-bench solution search + offline SHA-256 caching
Layer 7: Verification Gate  — 6-phase deterministic testing (no self-grading)
Layer 8: Recovery Engine    — 10-code failure taxonomy + 3-level circuit breaker
Layer 9: Telemetry & Report — 18 event types, real-time stats, 8-section audit report
```

---

## 📄 License

This project is licensed under the [MIT License](./LICENSE).
