# PRD — Autonomous Coding-Agent Harness
**Event:** AI Harness Hackathon 2026 (LCC / Devclub) · **Duration:** 24 hours
**Status:** Living document — update this file as decisions change. If code and this file disagree, this file is wrong; fix it immediately, don't let it drift.

---

## 1. Mission statement

> "You're not building an app. You're building the system that lets the model behave like a software engineer."

We are given a standardized, text-only foundation model. Our job is not to make the model smarter — we can't. Our job is to build the **harness**: the orchestration, tooling, memory, verification, and recovery logic that lets that fixed model reliably act like an engineer on a real repository. The harness is the product. The model is a commodity we plug into it.

---

## 2. Goals

1. Given a GitHub issue and a real repository, the harness understands the issue, locates the relevant code, makes a correct fix, and **proves** the fix works via the repo's own tests.
2. The harness recovers from its own failures (bad patch, failing test, tool error) without a human touching it mid-run.
3. Every run is observable after the fact: what the agent did, why, what it cost, and whether it succeeded — from logs alone, no re-running required.
4. The submission passes the evaluator's exact interface (`make setup && make run`) on a machine that has never seen the repo before.

## 3. Non-goals (explicitly out of scope)

- Multimodal input (image/audio/video) — the eval spec is text-only; do not spend hours here.
- A polished UI beyond a functional TUI/CLI — visual polish is not graded, reliability is.
- Supporting arbitrary/unknown foundation models — build against whatever model is prescribed; don't over-engineer model-swapping beyond "reads config, not hardcoded."
- Multi-agent swarms / parallel agents — added complexity with no rubric payoff at this scope; single agent loop first, only add subagents if time remains and there's a concrete isolation need.

## 4. Functional requirements (the rubric, made concrete)

| # | Rubric line | Definition of done |
|---|---|---|
| 1 | Understand a software-engineering issue | Issue text is parsed into a structured object (goal, acceptance criteria, suspected files) *before* any tool call is made |
| 2 | Navigate an existing repository | Agent uses `search_code`/`list_dir` to locate relevant files; never dumps the full repo into context |
| 3 | Use tools intelligently | No repeated redundant calls (e.g. re-reading a file already in context); every call is preceded by a stated reason |
| 4 | Manage context effectively | Context manager enforces a token budget per step; old turns are summarized, not silently dropped or endlessly accumulated |
| 5 | Recover from failures without human help | On any tool/test failure, the *error content* (not a generic retry) is fed back in; retries are bounded (max N) |
| 6 | Produce correct, verified code changes | Every code change is a diff, applied via git, and is only marked "done" after the repo's own tests pass |
| 7 | Use tokens/compute efficiently | Every step logs token count + latency; a run summary reports total cost per issue solved |

## 5. Non-functional / evaluation requirements (from the official spec — non-negotiable)

- `Makefile` at repo root exposing `make setup`, `make run`, `make test`, `make clean`. Minimum bar: `setup` and `run` must both succeed standalone.
- `AI_API_KEY` is read **only** from the environment at runtime (`os.environ`). Never hardcoded, never committed, never logged. `.env.example` only, no real `.env` committed.
- Text-only model I/O. No modality other than text may be required for the harness to run.
- Model/model family used must be declared in a visible config, swappable without editing source.
- Any randomness (temperature, seeds) must be documented/controllable — reproducibility is graded.
- If a TUI is built, `make run` must launch it directly — no undocumented extra command.
- The evaluator will not fix a broken setup; a submission that fails `make setup && make run` in a clean clone is scored as broken, full stop.

## 6. Architecture (the six layers)

```
Issue text
   │
   ▼
[1] Orchestrator ── state machine: PLAN → ACT → OBSERVE → REFLECT → VERIFY → DONE/RETRY
   │
   ▼
[2] Tool layer ── read_file · list_dir · search_code · apply_patch · run_bash/run_tests
   │
   ▼
[3] Context manager ── filesystem-as-memory, rolling summarization, token budget
   │
   ▼
[4] Verification layer ── git-applied diffs + repo's own test suite/linter as ground truth
   │
   ▼
[5] Recovery/guardrails ── bounded retries, error-type classification, timeouts, sandboxing
   │
   ▼
[6] Telemetry & reporting ── structured JSONL event log → auto-generated report.md
```

**Design rule:** layers 4 and 5 are what "verified" and "recover without human help" actually mean. If either is stubbed out, those two rubric lines are not satisfied no matter what the demo looks like.

## 7. Tech stack (decided)

| Concern | Choice | Why |
|---|---|---|
| Language | Python | Fastest path to tool-calling + subprocess + git in 24h |
| Model interface | Structured tool-use/function-calling against the prescribed model | Avoids fragile free-text plan parsing |
| Patch application | `git apply` / `difflib` | Diffs only, never full-file rewrites — smaller blast radius, easy rollback |
| Sandbox | `subprocess` with resource/time limits (Docker if time allows) | Contains `run_bash`, the one genuinely dangerous tool |
| Verification | Target repo's own `pytest`/test runner + `ruff`/`flake8` | Ground truth is the repo's tests, not the model's opinion |
| Telemetry | Append-only JSONL log | Cheap, replayable, doubles as audit trail |
| Reporting | Script that renders `report.md` from the JSONL log | Report is generated evidence, not hand-written claims |

## 8. Milestones (24-hour plan)

| Time | Milestone | Exit criteria |
|---|---|---|
| 0–2h | Agent loop skeleton + 5 dumb tool stubs | Loop runs end-to-end on a no-op |
| 2–6h | Real tool-calling wired to model | One full cycle fixes a trivial synthetic bug in a toy repo |
| 6–10h | Verification layer | Test failures are fed back and change agent behavior |
| 10–14h | Context manager + guardrails | Survives a larger/messier repo without context overflow or infinite loop |
| 14–18h | Telemetry + auto-report | `report.md` generated from a real run's logs |
| 18–21h | Run against 3–5 unseen issues/repos | Failure modes found and fixed before judges find them |
| 21–24h | README, freeze, clean-clone dry run | `make setup && make run` succeeds from a fresh clone |

## 9. Risks and mitigations (loophole register)

| Risk | Mitigation | Owner | Status |
|---|---|---|---|
| Infinite retry loop | Hard step ceiling + wall-clock timeout, logged reason for termination | | Open |
| Context window overflow on larger repos | Filesystem-as-memory + summarization, tested against a repo bigger than the demo one | | Open |
| Hallucinated file paths | Validate every path against actual repo tree before acting | | Open |
| Partial/broken multi-file edit | Atomic patch application per logical change, rollback via git on partial failure | | Open |
| Unsafe `run_bash` execution | Sandboxed subprocess, resource/time limits, command allowlist | | Open |
| False "success" self-report | Test exit code is the only success signal, never model's own claim | | Open |
| Cost/token blowout | Per-issue token cap enforced in code, visible in telemetry | | Open |
| Non-deterministic demo run | Low/pinned temperature for agent loop, full run log kept for every attempt | | Open |
| Broken clean-clone setup | Dry run in a fresh clone before submission, per `SUBMISSION_CHECKLIST.md` | | Open |
| README/code mismatch | README written last, against actual final code, not the original plan | | Open |

*(Fill in "Owner" and flip "Status" to Done as you go — this table is meant to be edited live during the hackathon, not written once and ignored.)*

## 10. Success metrics

- **Correctness:** % of test issues where the harness produces a patch that passes the repo's test suite.
- **Autonomy:** number of failures recovered from without human intervention, per run.
- **Efficiency:** total tokens and wall-clock time per issue solved (from telemetry, not estimated).
- **Reproducibility:** variance in outcome across repeated runs of the same issue.
- **Compliance:** clean-clone `make setup && make run` succeeds with zero manual steps.

## 11. Open questions (resolve early, don't let these linger)

- [ ] Which model/model family is actually prescribed, and is it confirmed before we hardcode assumptions into prompts?
- [ ] What repo(s)/issue(s) will be used for the live evaluation — do we have a similar one to test against?
- [ ] TUI or plain CLI — decide now, don't leave it till hour 20.
- [ ] Who owns which layer (see section 6) — assign before coding starts to avoid overlap.

## 12. Appendix

- `Makefile`, `.env.example`, `SUBMISSION_CHECKLIST.md` — see repo root, generated to satisfy Section 5 above.
- Architecture and rubric mapping in this document supersede any verbal plan — if a teammate says "I thought we were doing X," this file is the tiebreaker.
