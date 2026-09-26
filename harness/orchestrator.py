"""harness/orchestrator.py — Layer 5: Multi-Agent Orchestrator Loop.

Reference: PRD.md §4.5 | architecture.md §7.5
Implements the ReAct state machine (INIT -> PLAN -> ACT -> OBSERVE -> REFLECT -> DONE_CANDIDATE -> DONE/FAILED),
subagent pool coordination, rollback checkpoint snapshots, and structured output parsing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from harness.adapters.base import ModelAdapter, ModelResponse
from harness.adapters.gemini_adapter import GeminiAdapter
from harness.config import HarnessConfig
from harness.context_manager import ContextManager
from harness.contracts import (
    AgentPhase,
    AgentPlan,
    Complexity,
    DoneCandidate,
    ErrorCode,
    EventType,
    PlanStep,
    ResultStatus,
    SessionResult,
    ToolCall,
)
from harness.issue_parser import IssueParser
from harness.recovery import RecoveryEngine
from harness.repo_intel import RepoIndexBuilder, SemanticRanker
from harness.report_generator import ReportGenerator
from harness.skill_retriever import SkillRetriever
from harness.subagents.pool import (
    ArchitectSubagent,
    CoderSubagent,
    CriticSubagent,
    ScoutSubagent,
)
from harness.telemetry import TelemetryWriter
from harness.tool_engine import ToolEngine
from harness.verification import VerificationGate

logger = logging.getLogger(__name__)


def parse_plan(content: str, output_dir: str = ".harness") -> AgentPlan:
    """Parse and validate structured JSON plan from model response (PRD §4.5.2)."""
    clean_json = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    clean_json = re.sub(r"\s*```$", "", clean_json, flags=re.MULTILINE)

    # Find the outermost JSON object if surrounded by extra commentary
    json_match = re.search(r"\{[\s\S]*\}", clean_json)
    if json_match:
        clean_json = json_match.group(0)

    try:
        data = json.loads(clean_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid plan structure: {e}") from e

    if not isinstance(data, dict) or "plan" not in data or not isinstance(data["plan"], list):
        raise ValueError("Invalid plan structure: Missing 'plan' step array.")

    steps: list[PlanStep] = []
    for item in data["plan"]:
        steps.append(
            PlanStep(
                step=int(item.get("step", len(steps) + 1)),
                description=str(item.get("description", "")),
                tool_prediction=str(item.get("tool_prediction", "")),
                expected_outcome=str(item.get("expected_outcome", "")),
            )
        )

    estimated_steps = int(data.get("estimated_total_steps", len(steps)))
    risk_factors = [str(r) for r in data.get("risk_factors", [])]
    checkpoints = [int(c) for c in data.get("rollback_checkpoints", [])]

    plan = AgentPlan(
        steps=steps,
        estimated_total_steps=estimated_steps,
        risk_factors=risk_factors,
        rollback_checkpoints=checkpoints,
    )

    # Write .harness/plan.md artifact
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    plan_file = out_path / "plan.md"

    md_lines = [
        "# Execution Plan",
        f"**Estimated Total Steps:** {plan.estimated_total_steps}",
        f"**Rollback Checkpoints:** {plan.rollback_checkpoints}",
        "",
        "## Steps",
        "| Step | Description | Predicted Tool | Expected Outcome |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for s in plan.steps:
        md_lines.append(f"| {s.step} | {s.description} | `{s.tool_prediction}` | {s.expected_outcome} |")

    if plan.risk_factors:
        md_lines.extend(["", "## Risk Factors"])
        for rf in plan.risk_factors:
            md_lines.append(f"- {rf}")

    plan_file.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return plan


def parse_done_candidate(content: str) -> DoneCandidate:
    """Parse and validate DONE_CANDIDATE structured signal (PRD §4.5.2)."""
    clean_json = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.MULTILINE)
    clean_json = re.sub(r"\s*```$", "", clean_json, flags=re.MULTILINE)

    json_match = re.search(r"\{[\s\S]*\}", clean_json)
    if json_match:
        clean_json = json_match.group(0)

    try:
        data = json.loads(clean_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid DONE_CANDIDATE structure: {e}") from e

    if not isinstance(data, dict) or data.get("status") != "DONE_CANDIDATE":
        raise ValueError("Response is not a valid DONE_CANDIDATE structure.")

    evidence = [str(e) for e in data.get("evidence", []) if str(e).strip()]
    if not evidence:
        raise ValueError("Missing or empty 'evidence' list in DONE_CANDIDATE signal.")

    confidence = float(data.get("confidence", 0.0))
    files_modified = [str(f) for f in data.get("files_modified", [])]

    return DoneCandidate(
        confidence=confidence,
        evidence=evidence,
        files_modified=files_modified,
    )


class Orchestrator:
    """Conductor engine driving the autonomous ReAct coding loop and subagents."""

    def __init__(
        self,
        config: HarnessConfig | None = None,
        model_adapter: ModelAdapter | None = None,
    ) -> None:
        self.config = config or HarnessConfig()
        self.model_adapter = model_adapter or GeminiAdapter(
            api_key=self.config.model.api_key,
            api_keys=self.config.model.api_keys,
            model_name=self.config.model.name,
            fallback_chain=self.config.model.fallback_chain,
            max_continuations=getattr(self.config.model, "max_continuations", 3),
        )

        out_dir = self.config.telemetry.output_dir
        repo_p = self.config.repo_path

        self.issue_parser = IssueParser(config=self.config, model_adapter=self.model_adapter)
        self.repo_index_builder = RepoIndexBuilder(
            repo_path=repo_p,
            output_dir=os.path.join(out_dir, "repo_index"),
        )
        self.semantic_ranker = SemanticRanker()
        self.context_manager = ContextManager(config=self.config.context, output_dir=out_dir)
        self.telemetry = TelemetryWriter(
            output_dir=out_dir,
            model_name=self.config.model.name,
            stream_to_stdout=self.config.telemetry.stream_to_stdout,
        )
        self.skill_retriever = SkillRetriever(
            config=self.config.external_skills,
            telemetry=self.telemetry,
            cache_dir=os.path.join(out_dir, "skill_cache"),
        )
        self.tool_engine = ToolEngine(
            repo_root=repo_p,
            telemetry=self.telemetry,
            skill_retriever=self.skill_retriever,
        )
        self.report_generator = ReportGenerator(
            output_dir=out_dir,
            repo_path=repo_p,
        )
        self.verification_gate = VerificationGate(
            config=self.config.verification,
            telemetry=self.telemetry,
        )
        self.recovery_engine = RecoveryEngine(
            config=self.config.agent,
            telemetry=self.telemetry,
        )

        self.current_phase = AgentPhase.INIT
        self.current_step = 0
        self.revision_count = 0
        self.loop_count = 0
        self.checkpoints: dict[int, str] = {}

    def format_reflection_prompt(
        self,
        last_observation: str,
        goal: str,
        current_step: str,
    ) -> str:
        """Format REFLECT phase template per PRD §5.3."""
        return (
            "You just observed:\n"
            f"{last_observation}\n\n"
            f"Active Goal: {goal}\n"
            f"Current Plan Step: {current_step}\n\n"
            "Reflect on:\n"
            "1. Did the tool call achieve its expected outcome?\n"
            "2. Did we discover new information, symbols, or error patterns?\n"
            "3. What is the immediate next action, or are we ready to emit DONE_CANDIDATE?\n"
        )

    def capture_checkpoint(self, step: int, diff_content: str | None = None) -> str:
        """Capture git diff snapshot at designated plan step (PRD §4.5.4)."""
        out_dir = Path(self.config.telemetry.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_file = out_dir / f"checkpoint_{step}.diff"

        if diff_content is None:
            # Run git diff via tool engine
            res = self.tool_engine.execute(ToolCall(tool="git_diff", reasoning="Capture checkpoint", args={}))
            diff_content = res.raw_output

        checkpoint_file.write_text(diff_content or "", encoding="utf-8")
        self.checkpoints[step] = str(checkpoint_file)
        self.telemetry.log_event(
            event_type=EventType.CHECKPOINT,
            step=step,
            phase=self.current_phase,
        )
        return str(checkpoint_file)

    def run(self, issue_text: str) -> SessionResult:
        """Synchronously execute the full orchestrator session."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(
                        asyncio.run,
                        self.run_async(issue_text)
                    ).result()
            else:
                return asyncio.run(self.run_async(issue_text))
        except Exception:
            return asyncio.run(self.run_async(issue_text))

    async def _call_model(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.0,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str = "low",
    ) -> ModelResponse:
        """Call model adapter with parameter filtering for mock/legacy adapters."""
        import inspect
        kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "temperature": temperature,
        }
        if tools is not None:
            kwargs["tools"] = tools

        sig = inspect.signature(self.model_adapter.complete)
        accepts_var = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if "reasoning_effort" in sig.parameters or accepts_var:
            kwargs["reasoning_effort"] = reasoning_effort

        if not accepts_var:
            kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}

        return await self.model_adapter.complete(**kwargs)

    async def run_async(self, issue_text: str) -> SessionResult:
        """Asynchronously execute full autonomous ReAct state machine."""
        start_time = time.perf_counter()
        total_tokens = 0
        cost_usd = 0.0
        total_cost_usd = 0.0

        # ─── 1. INIT Phase ─────────────────────────────────────────────────
        self.current_phase = AgentPhase.INIT
        self.telemetry.log_session_start(
            issue_id="issue",
            repo_path=self.config.repo_path,
        )

        issue_plan = await self.issue_parser.parse_issue_async(
            issue_text,
            repo_path=self.config.repo_path,
        )
        repo_index = self.repo_index_builder.build_index()

        suspected_paths = [f.path for f in issue_plan.suspected_files]
        ranked_files = self.semantic_ranker.rank_files(
            query=issue_plan.primary_goal,
            repo_index=repo_index,
            repo_path=self.config.repo_path,
            suspected_files=suspected_paths,
            top_n=5,
        )

        # Populate ContextManager sections
        self.context_manager.set_issue(issue_plan)
        self.ranked_files = ranked_files

        # ── PRD §2 rubric item 1: Write issue_plan.json BEFORE turn 1 ────────
        try:
            out_dir = Path(self.config.telemetry.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            issue_plan_path = out_dir / "issue_plan.json"
            issue_plan_path.write_text(issue_plan.to_json(indent=2), encoding="utf-8")
            logger.info("issue_plan.json written → %s", issue_plan_path)
        except Exception as e:
            logger.warning("Could not write issue_plan.json: %s", e)

        # Startup Pre-fetch (Layer 6)
        if self.config.external_skills.enabled and self.config.external_skills.prefetch_at_startup:
            try:
                self.skill_retriever.prefetch_at_startup(
                    repo_path=self.config.repo_path,
                    issue_plan=issue_plan,
                )
            except Exception:
                pass

        # ─── 2. Multi-Agent Subagent Coordination (MEDIUM / HIGH / VERY_HIGH) ─
        subagent_out_dir = self.config.telemetry.output_dir
        if issue_plan.complexity_estimate in (Complexity.MEDIUM, Complexity.HIGH, Complexity.VERY_HIGH):
            scout = ScoutSubagent(model_adapter=self.model_adapter, output_dir=subagent_out_dir)
            tree_text = Path(repo_index.file_tree_path).read_text(encoding="utf-8") if Path(repo_index.file_tree_path).exists() else ""
            sym_text = Path(repo_index.module_symbols_path).read_text(encoding="utf-8") if Path(repo_index.module_symbols_path).exists() else ""
            try:
                scout_report_path = await scout.run_async(issue_plan, tree_text, sym_text)
                self.telemetry.log_event(
                    event_type=EventType.SUBAGENT_SPAWN,
                    agent="scout",
                    step=self.current_step,
                    phase=self.current_phase,
                )
                if issue_plan.complexity_estimate in (Complexity.HIGH, Complexity.VERY_HIGH):
                    architect = ArchitectSubagent(model_adapter=self.model_adapter, output_dir=subagent_out_dir)
                    scout_report_content = Path(scout_report_path).read_text(encoding="utf-8")
                    arch_report_path = await architect.run_async(issue_plan, scout_report_content)
                    self.telemetry.log_event(
                        event_type=EventType.SUBAGENT_SPAWN,
                        agent="architect",
                        step=self.current_step,
                        phase=self.current_phase,
                    )
                    # Coder + Critic for HIGH/VERY_HIGH (PRD §4.5 routing table)
                    arch_report_content = Path(arch_report_path).read_text(encoding="utf-8") if Path(arch_report_path).exists() else scout_report_content
                    coder = CoderSubagent(model_adapter=self.model_adapter, output_dir=subagent_out_dir)
                    # Use first suspected file as primary coder target
                    primary_file = issue_plan.suspected_files[0].path if issue_plan.suspected_files else "unknown.py"
                    try:
                        file_content = Path(self.config.repo_path, primary_file).read_text(encoding="utf-8")
                    except OSError:
                        file_content = "[file not readable]"
                    await coder.run_async(
                        target_file=primary_file,
                        file_content=file_content,
                        architecture_plan=arch_report_content,
                        step=self.current_step,
                    )
                    self.telemetry.log_event(
                        event_type=EventType.SUBAGENT_SPAWN,
                        agent="coder",
                        step=self.current_step,
                        phase=self.current_phase,
                    )
                    critic = CriticSubagent(model_adapter=self.model_adapter, output_dir=subagent_out_dir)
                    await critic.run_async(
                        issue_plan=issue_plan,
                        patches_applied=[arch_report_content],
                        test_results="Pre-run — tests not yet executed.",
                    )
                    self.telemetry.log_event(
                        event_type=EventType.SUBAGENT_SPAWN,
                        agent="critic",
                        step=self.current_step,
                        phase=self.current_phase,
                    )
            except Exception as e:
                logger.warning("Subagent coordination failed (non-fatal): %s", e)

        # ─── 3. PLAN Phase ─────────────────────────────────────────────────
        self.current_phase = AgentPhase.PLAN

        # Build tool definitions ONCE — passed to every model call so Gemini can emit function_calls
        tool_definitions = self.tool_engine.get_tool_definitions()

        plan_prompt = (
            "Emit the initial structured execution plan in JSON format (PRD §4.5.2):\n"
            "{\n"
            '  "plan": [\n'
            '    {"step": 1, "description": "...", "tool_prediction": "read_file_range", "expected_outcome": "..."}\n'
            "  ],\n"
            '  "estimated_total_steps": 6,\n'
            '  "risk_factors": ["..."],\n'
            '  "rollback_checkpoints": [1, 3]\n'
            "}\n"
        )
        prompt_sections = self.context_manager.build_prompt(ranked_files=self.ranked_files)
        plan_response = await self._call_model(
            system_prompt=prompt_sections.persona,
            user_message=prompt_sections.issue_goal + "\n\n" + plan_prompt,
            temperature=self.config.model.temperature_plan,
            reasoning_effort=self.config.model.reasoning_effort_plan,
        )
        total_tokens += plan_response.tokens_in + plan_response.tokens_out
        total_cost_usd += getattr(plan_response, "cost_usd", 0.0)

        try:
            agent_plan = parse_plan(plan_response.content, output_dir=self.config.telemetry.output_dir)
        except Exception:
            # Fallback initial plan
            agent_plan = AgentPlan(
                steps=[
                    PlanStep(step=1, description="Inspect suspected files", tool_prediction="read_file_range", expected_outcome="Locate root cause"),
                    PlanStep(step=2, description="Apply repair patch", tool_prediction="apply_patch", expected_outcome="Fix issue"),
                ],
                estimated_total_steps=issue_plan.estimated_steps,
                risk_factors=[],
                rollback_checkpoints=[1],
            )

        self.telemetry.log_event(
            event_type=EventType.PLAN_EMIT,
            step=self.current_step,
            phase=self.current_phase,
        )

        # ─── 4. ReAct Execution Loop ───────────────────────────────────────
        last_observation = ""
        verification_result = None

        while self.current_step < self.config.agent.max_steps and self.current_phase not in (
            AgentPhase.DONE,
            AgentPhase.FAILED,
        ):
            # Checkpoint trigger
            if self.current_step in agent_plan.rollback_checkpoints:
                self.capture_checkpoint(self.current_step)

            # ACT Phase
            self.current_phase = AgentPhase.ACT
            current_step_desc = f"Step {self.current_step + 1}"
            if self.current_step < len(agent_plan.steps):
                current_step_desc = f"{agent_plan.steps[self.current_step].step}. {agent_plan.steps[self.current_step].description}"

            user_msg = ""
            if last_observation:
                user_msg = self.format_reflection_prompt(
                    last_observation=last_observation,
                    goal=issue_plan.primary_goal,
                    current_step=current_step_desc,
                )
            else:
                user_msg = f"Begin execution for goal: {issue_plan.primary_goal}. Next step: {current_step_desc}"

            effort = self.config.model.reasoning_effort_act
            if hasattr(self, "recovery_engine") and getattr(self.recovery_engine, "in_recovery", False):
                effort = self.config.model.reasoning_effort_recovery
            elif last_observation:
                effort = self.config.model.reasoning_effort_reflect

            prompt_sections = self.context_manager.build_prompt(ranked_files=self.ranked_files)
            turn_start = time.perf_counter()
            turn_response = await self._call_model(
                system_prompt=prompt_sections.persona,
                user_message=user_msg,
                temperature=self.config.model.temperature_act,
                tools=tool_definitions,
                reasoning_effort=effort,
            )
            turn_latency_ms = int((time.perf_counter() - turn_start) * 1000)
            total_tokens += turn_response.tokens_in + turn_response.tokens_out
            total_cost_usd += getattr(turn_response, "cost_usd", 0.0)

            # Log LLM turn to telemetry
            self.telemetry.log_llm_turn(
                step=self.current_step,
                phase=self.current_phase,
                tokens_in=turn_response.tokens_in,
                tokens_out=turn_response.tokens_out,
                latency_ms=turn_latency_ms,
                context_tokens_used=prompt_sections.total_tokens,
                budget=self.config.context.max_context_tokens,
                agent="orchestrator",
            )

            content = turn_response.content.strip()

            # Check for DONE_CANDIDATE signal
            if '"status": "DONE_CANDIDATE"' in content or '"status":"DONE_CANDIDATE"' in content:
                try:
                    done_candidate = parse_done_candidate(content)
                    self.current_phase = AgentPhase.DONE_CANDIDATE
                    self.telemetry.log_event(
                        event_type=EventType.DONE_CANDIDATE,
                        step=self.current_step,
                        phase=self.current_phase,
                    )

                    # Trigger Verification Gate (Phase 3)
                    verification_result = self.verification_gate.verify(
                        repo_path=self.config.repo_path,
                        modified_files=done_candidate.files_modified,
                        issue_plan=issue_plan,
                        step=self.current_step,
                    )

                    # Log verification phases to telemetry
                    if hasattr(verification_result, "phases") and isinstance(verification_result.phases, dict):
                        for phase_name, p in verification_result.phases.items():
                            self.telemetry.log_verification_phase(
                                step=self.current_step,
                                phase=phase_name,
                                status=getattr(p, "status", ResultStatus.SUCCESS),
                                detail=getattr(p, "detail", ""),
                                duration_ms=getattr(p, "duration_ms", 0),
                            )

                    if verification_result.status == ResultStatus.SUCCESS:
                        self.current_step += 1
                        self.current_phase = AgentPhase.DONE
                        self.telemetry.log_event(
                            event_type=EventType.DONE,
                            step=self.current_step,
                            phase=self.current_phase,
                        )
                        break
                    else:
                        # Verification failed! Trigger RecoveryEngine (Phase 3)
                        recovery_action = self.recovery_engine.handle_verification_result(
                            verification_result=verification_result,
                            step=self.current_step,
                            repo_path=self.config.repo_path,
                        )
                        self.telemetry.log_event(
                            event_type=EventType.RECOVERY_EVENT,
                            step=self.current_step,
                            phase=self.current_phase,
                            error_code=recovery_action.error_code,
                        )

                        if recovery_action.level == 1:
                            # Auto-remediate: inject error into context
                            self.current_phase = AgentPhase.REFLECT
                            last_observation = (
                                f"Verification failed: {verification_result.phases}.\n"
                                f"{recovery_action.injection_prompt}"
                            )
                        elif recovery_action.level == 2:
                            # Plan revision
                            self.revision_count += 1
                            if self.revision_count > self.config.agent.max_plan_revisions:
                                self.current_phase = AgentPhase.FAILED
                                break
                            self.current_phase = AgentPhase.PLAN
                            last_observation = f"Plan revision needed: {recovery_action.action_description}"
                        else:  # Level 3: Exit
                            self.current_phase = AgentPhase.FAILED
                            break
                except ValueError as ve:
                    last_observation = f"DONE_CANDIDATE rejected: {ve}. Please provide required evidence."
                    self.current_phase = AgentPhase.REFLECT

            elif turn_response.tool_calls:
                # Execute tool call
                t_call = turn_response.tool_calls[0]
                self.telemetry.log_tool_call(
                    step=self.current_step,
                    tool_name=t_call.tool,
                    args_hash=t_call.fingerprint or "",
                    reasoning=t_call.reasoning,
                )

                tool_res = self.tool_engine.execute(t_call)
                self.current_phase = AgentPhase.OBSERVE
                self.context_manager.process_tool_result(tool_res)
                self.telemetry.log_tool_result(
                    step=self.current_step,
                    tool_name=tool_res.tool,
                    status=tool_res.status,
                    latency_ms=tool_res.execution_time_ms,
                    error_code=tool_res.error_code,
                )

                if tool_res.error_code == ErrorCode.LOOP_DETECTED:
                    rec_action = self.recovery_engine.classify_error(
                        error_code=ErrorCode.LOOP_DETECTED,
                        context={"tool": t_call.tool, "args": t_call.args, "detail": tool_res.truncated_output},
                        step=self.current_step,
                    )
                    last_observation = (
                        f"{tool_res.truncated_output}\n\n"
                        f"[RECOVERY STRATEGY SHIFT]\n{rec_action.injection_prompt}"
                    )
                else:
                    last_observation = tool_res.truncated_output
                self.current_phase = AgentPhase.REFLECT

            else:
                # Fallback: check if content contains tool call or done candidate in text
                last_observation = content[:500]
                self.current_phase = AgentPhase.REFLECT

            self.current_step += 1

        if self.current_phase != AgentPhase.DONE:
            self.current_phase = AgentPhase.FAILED

        # Always generate report.md unconditionally upon run completion (Task 5.21)
        try:
            from harness.tools.vcs import git_diff
            diff_res = git_diff(repo_root=self.config.repo_path)
            final_diff_str = diff_res.raw_output if diff_res else ""
        except Exception:
            final_diff_str = ""

        try:
            v_data = verification_result.to_dict() if verification_result else None
            self.report_generator.issue_id = getattr(issue_plan, "problem_statement", "issue")[:40]
            self.report_generator.primary_goal = getattr(issue_plan, "primary_goal", "Resolve issue")
            self.report_generator.generate(
                status=self.current_phase.value,
                final_diff=final_diff_str,
                verification_data=v_data,
            )
        except Exception as e:
            logger.error("Failed to generate report.md: %s", e)

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        exit_code = 0 if self.current_phase == AgentPhase.DONE else 1

        return SessionResult(
            status=self.current_phase,
            exit_code=exit_code,
            total_steps=self.current_step,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
            total_wall_time_ms=elapsed_ms,
            verification_result=verification_result,
        )
