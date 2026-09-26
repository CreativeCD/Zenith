# Zenith — Autonomous AI Coding Harness

> **SOTA Autonomous Coding Harness for Benchmark-Driven Software Engineering**  
> *Developed for LCC × DevClub AI Coding Harness Hackathon 2026*

---

## ⚡ Overview

Zenith is a multi-agent, token-optimized, contract-driven AI coding harness designed to autonomously resolve complex software engineering issues across real-world codebases. It features:

- **9-Layer Decoupled Architecture:** From issue parsing and AST-level repository intelligence to a 6-phase deterministic verification gate and recovery engine.
- **Formal State Machine:** 11 deterministic states with cycle-breaking circuit breakers and rollback checkpoints.
- **Extreme Token Efficiency:** Byte-identical prompt prefix KV cache reuse, structured subagent context isolation, and rolling working memory compaction.
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

### 2. Environment Setup
```bash
# Clone the repository
git clone <repo-url>
cd Zenith

# Set up environment and install dependencies
make setup

# Configure API keys
cp .env.example .env
# Edit .env and insert your AI_API_KEY
```

### 3. Execution
```bash
# Standard evaluation run (compatible with hackathon evaluation harness)
make run REPO_PATH=/path/to/target_repo ISSUE_PATH=/path/to/issue.txt

# Or invoke directly via CLI
python -m harness.cli \
  --repo /path/to/target_repo \
  --issue /path/to/issue.txt \
  --max-steps 25 \
  --model gemini-2.5-flash \
  --verbose
```

### 4. Running Tests & Quality Gates
```bash
# Run unit & integration test suite
make test

# Run code linter
make lint

# Run containerized clean-clone test
make docker-test

# Clean build artifacts and virtualenv
make clean
```

---

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
