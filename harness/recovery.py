"""Recovery, Self-Healing & Circuit Breaker Engine (Layer 8).

Implements the 10-code failure taxonomy, 3-level circuit breaker, and 3-level
graceful degradation chain specified in PRD §4.8 and architecture.md §13:
  - 5-call hash-window anti-loop circuit breaker (WARNING / BLOCK / ESCALATE)
  - 10-code error taxonomy with deterministic remediation prompts
  - Graceful degradation: L1 auto-remediate -> L2 plan revision -> L3 graceful exit
  - Rollback checkpointing and state restoration
"""

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.config import AgentConfig
from harness.contracts import (
    AgentPhase,
    ErrorCode,
    EventType,
    PhaseResult,
    RecoveryAction,
    ResultStatus,
    TelemetryEvent,
    VerificationPhase,
    VerificationResult,
)
from harness.telemetry import TelemetryWriter


class CircuitBreaker:
    """5-call hash-window anti-loop circuit breaker (PRD §4.8.1).

    Maintains a ring buffer of tool-call fingerprints to detect:
      - Level 1: 2 identical calls non-consecutive within window -> WARNING
      - Level 2: 2 consecutive identical calls -> BLOCK + strategy shift
      - Level 3: loop_count >= max_loops (3) -> ESCALATE to plan revision
    """

    def __init__(self, window_size: int = 5, max_loops: int = 3) -> None:
        self.window_size = window_size
        self.max_loops = max_loops
        self.buffer: list[str] = []
        self.loop_count: int = 0
        self.last_tool: str | None = None
        self.last_args_str: str | None = None

    @staticmethod
    def compute_fingerprint(tool: str, args: dict[str, Any]) -> str:
        """Compute deterministic SHA256 fingerprint for tool and canonical args."""
        try:
            canonical_args = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            canonical_args = str(args)
        raw_key = f"{tool}:{canonical_args}".encode()
        return hashlib.sha256(raw_key).hexdigest()[:32]

    def record_and_evaluate(
        self,
        tool: str,
        args: dict[str, Any],
        step: int = 0,
    ) -> tuple[int, str | None]:
        """Evaluate new call against history.

        Returns (level, prompt_or_message):
          - Level 0: Allowed (no loop)
          - Level 1: Warning (repeated in window, not consecutive)
          - Level 2: Blocked (consecutive identical call, mandatory strategy shift)
          - Level 3: Escalated (loop limit reached, trigger plan revision)
        """
        fingerprint = self.compute_fingerprint(tool, args)
        self.last_tool = tool
        raw_args_str = json.dumps(args, default=str)
        self.last_args_str = raw_args_str if len(raw_args_str) <= 200 else raw_args_str[:197] + "..."

        # 1. Consecutive match -> Level 2 BLOCK or Level 3 ESCALATE
        if self.buffer and self.buffer[-1] == fingerprint:
            self.loop_count += 1
            if self.loop_count >= self.max_loops:
                msg = (
                    f"CIRCUIT BREAKER LEVEL 3 ESCALATION at step {step}: "
                    f"Tool '{tool}' executed identically {self.loop_count} times consecutively. "
                    "Halting tool execution. Mandatory PLAN REVISION required."
                )
                self._push_buffer(fingerprint)
                return 3, msg

            msg = (
                f"LOOP DETECTED at step {step}: `{tool}({self.last_args_str})` called twice identically.\n"
                "REQUIRED ACTIONS:\n"
                "1. Run git_rollback to restore clean state.\n"
                "2. Re-read the TARGET SECTION (±20 lines around your target).\n"
                "3. State in one sentence: what was DIFFERENT about what you found.\n"
                "4. Propose a DIFFERENT approach before any edit."
            )
            self._push_buffer(fingerprint)
            return 2, msg

        # Reset consecutive loop count when call is non-identical
        self.loop_count = 0

        # 2. Repeated call in window (non-consecutive) -> Level 1 WARNING
        window_count = self.buffer.count(fingerprint)
        if window_count >= 1:
            msg = (
                f"CIRCUIT BREAKER LEVEL 1 WARNING at step {step}: "
                f"You appear to be re-trying the same call `{tool}` seen earlier in the last "
                f"{self.window_size} steps. Verify that new information warrants re-running this."
            )
            self._push_buffer(fingerprint)
            return 1, msg

        # 3. Clean call
        self._push_buffer(fingerprint)
        return 0, None

    def reset_buffer(self) -> None:
        """Reset history buffer after intermediate code edit or rollback."""
        self.buffer.clear()
        self.loop_count = 0

    def _push_buffer(self, fingerprint: str) -> None:
        self.buffer.append(fingerprint)
        if len(self.buffer) > self.window_size:
            self.buffer.pop(0)


class RecoveryEngine:
    """10-code error taxonomy and 3-level graceful degradation engine (PRD §4.8)."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        telemetry: TelemetryWriter | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.telemetry = telemetry
        self.circuit_breaker = CircuitBreaker(
            window_size=5,
            max_loops=self.config.max_loop_count,
        )
        self.step_count: int = 0
        self.revision_count: int = 0
        self.checkpoints: dict[int, str] = {}
        self.failure_history: list[ErrorCode] = []

    def classify_error(
        self,
        error_code: ErrorCode | str,
        context: dict[str, Any] | None = None,
        step: int = 0,
    ) -> RecoveryAction:
        """Route failure event to taxonomy remediation strategy (Tasks 3.11–3.19)."""
        ctx = context or {}
        if isinstance(error_code, str):
            try:
                code_enum = ErrorCode(error_code)
            except ValueError:
                code_enum = ErrorCode.PATCH_FAILED
        else:
            code_enum = error_code

        self.failure_history.append(code_enum)
        if len(self.failure_history) > 50:
            self.failure_history = self.failure_history[-50:]

        # Build prompt using specific taxonomy templates
        if code_enum == ErrorCode.PATCH_FAILED:
            action = self._remediate_patch_failed(ctx, step)
        elif code_enum == ErrorCode.AST_PARSE_FAIL:
            action = self._remediate_ast_parse_fail(ctx, step)
        elif code_enum == ErrorCode.LINT_REGRESSION:
            action = self._remediate_lint_regression(ctx, step)
        elif code_enum == ErrorCode.TEST_FAILED:
            action = self._remediate_test_failed(ctx, step)
        elif code_enum == ErrorCode.REGRESSION_DETECTED:
            action = self._remediate_regression_detected(ctx, step)
        elif code_enum == ErrorCode.SIDE_EFFECT_DETECTED:
            action = self._remediate_side_effect_detected(ctx, step)
        elif code_enum == ErrorCode.TIMEOUT:
            action = self._remediate_timeout(ctx, step)
        elif code_enum == ErrorCode.TOOL_BLOCKED:
            action = self._remediate_tool_blocked(ctx, step)
        elif code_enum == ErrorCode.LOOP_DETECTED:
            action = self._remediate_loop_detected(ctx, step)
        elif code_enum == ErrorCode.MAX_STEPS_EXCEEDED:
            action = self._remediate_max_steps_exceeded(ctx, step)
        else:
            action = RecoveryAction(
                error_code=code_enum,
                level=1,
                action_description=f"Generic recovery for {code_enum.value}",
                injection_prompt=f"Error encountered at step {step}: {ctx.get('detail', 'Unknown')}. Re-examine context and try an alternative approach.",
            )

        if self.telemetry:
            self.telemetry.append(
                TelemetryEvent(
                    step=step,
                    phase=AgentPhase.REFLECT,
                    event_type=EventType.RECOVERY_EVENT,
                    error_code=code_enum,
                    recovery_triggered=True,
                    loop_count=self.circuit_breaker.loop_count,
                    revision_count=self.revision_count,
                    reasoning=action.action_description,
                )
            )

        return action

    def handle_verification_result(
        self,
        verification_result: VerificationResult,
        step: int = 0,
        repo_path: str | None = None,
    ) -> RecoveryAction | None:
        """Convert a failing VerificationResult into a structured RecoveryAction."""
        if verification_result.status == ResultStatus.SUCCESS:
            return None

        first_fail = verification_result.first_failure
        phase_res: PhaseResult | None = None
        if first_fail and first_fail.value in verification_result.phases:
            phase_res = verification_result.phases[first_fail.value]

        detail = phase_res.detail if phase_res else "Verification failed"

        mapping = {
            VerificationPhase.SYNTAX: ErrorCode.AST_PARSE_FAIL,
            VerificationPhase.LINT: ErrorCode.LINT_REGRESSION,
            VerificationPhase.REPRO_TEST: ErrorCode.TEST_FAILED,
            VerificationPhase.REGRESSION: ErrorCode.REGRESSION_DETECTED,
            VerificationPhase.DIFF_AUDIT: ErrorCode.PATCH_FAILED,
            VerificationPhase.SIDE_EFFECT: ErrorCode.SIDE_EFFECT_DETECTED,
        }

        # Extract target_file from detail if available (e.g. for SYNTAX failure)
        target_file = None
        if first_fail == VerificationPhase.SYNTAX:
            lines = detail.splitlines()
            if len(lines) > 1 and ":" in lines[1]:
                target_file = lines[1].split(":", 1)[0].strip()

        context: dict[str, Any] = {
            "detail": detail,
            "verification_result": verification_result,
        }
        if target_file:
            context["target_file"] = target_file

        error_code = mapping.get(first_fail, ErrorCode.TEST_FAILED)
        action = self.classify_error(
            error_code=error_code,
            context=context,
            step=step,
        )

        # If rollback is required by the action, perform it with target
        if action.rollback_required and repo_path:
            self.rollback(repo_path, scope=action.rollback_scope, target=target_file)

        return action

    def escalate_degradation(
        self,
        error_code: ErrorCode,
        consecutive_failures: int,
        context: dict[str, Any] | None = None,
        step: int = 0,
    ) -> RecoveryAction:
        """Apply 3-level graceful degradation chain (Task 3.20).

        Level 1: Auto-remediation (1st & 2nd consecutive failure)
        Level 2: Plan revision (3rd consecutive failure)
        Level 3: Graceful exit (revision_count >= max_plan_revisions or step >= max_steps)
        """
        ctx = context or {}

        # Check for Level 3: Graceful exit conditions
        if (
            self.revision_count >= self.config.max_plan_revisions
            or step >= self.config.max_steps
        ):
            return self._remediate_max_steps_exceeded(ctx, step)

        # Check for Level 2: Plan revision
        if consecutive_failures >= 3 or error_code == ErrorCode.LOOP_DETECTED:
            self.revision_count += 1
            if self.revision_count >= self.config.max_plan_revisions:
                return self._remediate_max_steps_exceeded(ctx, step)

            lessons = "\n".join([f"- Attempted {c.value} which failed." for c in self.failure_history[-3:]])
            prompt = (
                f"PLAN REVISION TRIGGERED (Revision {self.revision_count}/{self.config.max_plan_revisions}) at step {step}:\n"
                f"Auto-remediation failed {consecutive_failures} times for {error_code.value}.\n"
                "LESSONS LEARNED:\n"
                f"{lessons}\n\n"
                "REQUIRED ACTION:\n"
                "Roll back to the previous safe checkpoint. Revise your strategy and emit a NEW PLAN JSON. "
                "Do NOT repeat the failed approaches."
            )
            return RecoveryAction(
                error_code=error_code,
                level=2,
                action_description="Escalated to Level 2: Plan Revision",
                injection_prompt=prompt,
                rollback_required=True,
                rollback_scope="checkpoint",
            )

        # Level 1: Auto-remediation
        return self.classify_error(error_code, ctx, step)

    # ─── Rollback & Checkpoint System ──────────────────────────────────────

    def create_checkpoint(self, repo_path: str, checkpoint_id: int) -> str:
        """Capture diff snapshot at designated plan step (PRD §4.5.4)."""
        harness_dir = Path(repo_path) / ".harness"
        harness_dir.mkdir(parents=True, exist_ok=True)
        diff_file = harness_dir / f"checkpoint_{checkpoint_id}.diff"

        try:
            proc = subprocess.run(
                ["git", "diff", "HEAD"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                check=False,
            )
            diff_content = proc.stdout
        except (subprocess.SubprocessError, OSError):
            diff_content = ""

        with open(diff_file, "w", encoding="utf-8") as f:
            f.write(diff_content)

        self.checkpoints[checkpoint_id] = diff_content

        if self.telemetry:
            self.telemetry.append(
                TelemetryEvent(
                    step=checkpoint_id,
                    event_type=EventType.CHECKPOINT,
                    reasoning=f"Captured checkpoint diff at step {checkpoint_id}",
                )
            )

        return str(diff_file)

    def rollback(
        self,
        repo_path: str,
        scope: str = "file",
        target: str | None = None,
    ) -> bool:
        """Execute git rollback with specified scope ('file', 'all', 'checkpoint')."""
        try:
            repo_root = Path(repo_path).resolve()
            if scope == "file" and target:
                target_path = (repo_root / target).resolve()
                # Security: prevent path traversal outside repository root
                if not str(target_path).startswith(str(repo_root)):
                    return False

                # Check if target is tracked in git
                ls_proc = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", "--", target],
                    cwd=repo_path,
                    capture_output=True,
                    check=False,
                )
                if ls_proc.returncode == 0:
                    subprocess.run(
                        ["git", "checkout", "HEAD", "--", target],
                        check=True,
                        cwd=repo_path,
                        capture_output=True,
                    )
                else:
                    # Untracked file: remove it cleanly
                    if target_path.is_file():
                        target_path.unlink()
                    elif target_path.is_dir():
                        shutil.rmtree(target_path)

            elif scope == "all":
                subprocess.run(
                    ["git", "checkout", "HEAD", "--", "."],
                    check=True,
                    cwd=repo_path,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "clean", "-fd", "-e", ".harness", "-e", ".venv"],
                    check=True,
                    cwd=repo_path,
                    capture_output=True,
                )
            elif scope == "checkpoint":
                # Rollback uncommitted changes to clean working tree
                subprocess.run(
                    ["git", "checkout", "HEAD", "--", "."],
                    check=True,
                    cwd=repo_path,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "clean", "-fd", "-e", ".harness", "-e", ".venv"],
                    check=True,
                    cwd=repo_path,
                    capture_output=True,
                )
                # If target checkpoint id is specified, try restoring that diff
                if target:
                    try:
                        cid = int(target)
                        diff_text = self.checkpoints.get(cid)
                        if diff_text:
                            subprocess.run(
                                ["git", "apply", "--whitespace=nowarn"],
                                input=diff_text,
                                text=True,
                                cwd=repo_path,
                                check=True,
                                capture_output=True,
                            )
                    except (ValueError, subprocess.SubprocessError):
                        pass

            self.circuit_breaker.reset_buffer()

            if self.telemetry:
                self.telemetry.append(
                    TelemetryEvent(
                        event_type=EventType.ROLLBACK,
                        reasoning=f"Rollback executed with scope: {scope} (target: {target})",
                    )
                )
            return True
        except (subprocess.SubprocessError, OSError):
            return False

    def execute_graceful_exit(
        self,
        repo_path: str,
        reason: str = "MAX_STEPS_EXCEEDED",
    ) -> dict[str, Any]:
        """Execute controlled Level 3 shutdown: rollback all + preserve diagnostic state."""
        self.rollback(repo_path, scope="all")
        result = {
            "status": "FAILED",
            "exit_code": 1,
            "reason": reason,
            "revisions_used": self.revision_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if self.telemetry:
            self.telemetry.append(
                TelemetryEvent(
                    event_type=EventType.FAILED,
                    phase=AgentPhase.FAILED,
                    result_status=ResultStatus.FAIL,
                    reasoning=f"Graceful exit executed: {reason}",
                )
            )

        return result

    # ─── 10 Taxonomy Prompt Generators ────────────────────────────────────

    def _remediate_patch_failed(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        target_file = ctx.get("target_file", ctx.get("file", "target_file.py"))
        line = ctx.get("target_line", 50)
        start_line = max(1, line - 20)
        end_line = line + 20
        err = ctx.get("detail", "Patch could not be applied cleanly.")

        prompt = (
            f"PATCH_FAILED at step {step}:\n"
            f"Error: {err}\n"
            "The patch was not applied. The file is unchanged.\n\n"
            "REQUIRED RECOVERY STEPS:\n"
            f"1. Run: read_file_range(\"{target_file}\", {start_line}, {end_line})\n"
            "2. Identify the EXACT current content at your target location\n"
            "3. Reformulate your patch using the exact-block replacement format:\n"
            f"   {{\"tool\": \"apply_patch\", \"args\": {{\"target_file\": \"{target_file}\", \"old_snippet\": \"EXACT_CURRENT_TEXT\", \"new_snippet\": \"NEW_TEXT\"}}}}"
        )
        return RecoveryAction(
            error_code=ErrorCode.PATCH_FAILED,
            level=1,
            action_description="PATCH_FAILED: Switch to exact-block replacement mode",
            injection_prompt=prompt,
            rollback_required=False,
        )

    def _remediate_ast_parse_fail(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        file_path = ctx.get("target_file", ctx.get("file", "unknown_file.py"))
        err = ctx.get("detail", "Syntax error detected in modified file")

        prompt = (
            f"AST_PARSE_FAIL at step {step}:\n"
            f"File: {file_path}\n"
            f"Syntax Error: {err}\n"
            f"Automatic rollback applied: {file_path} has been restored to HEAD.\n\n"
            "REQUIRED RECOVERY STEPS:\n"
            "1. Review the syntax error details and line number above.\n"
            "2. Re-read the file snippet before attempting another edit.\n"
            "3. Ensure your replacement syntax is valid before re-applying."
        )
        return RecoveryAction(
            error_code=ErrorCode.AST_PARSE_FAIL,
            level=1,
            action_description="AST_PARSE_FAIL: Auto-rollback file and inject syntax error",
            injection_prompt=prompt,
            rollback_required=True,
            rollback_scope="file",
        )

    def _remediate_lint_regression(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        violations = ctx.get("detail", "New linter violations introduced")
        prompt = (
            f"LINT_REGRESSION at step {step}:\n"
            "New linter violations introduced by your changes:\n"
            f"{violations}\n\n"
            "REQUIRED RECOVERY STEPS:\n"
            "1. View the specific lines flagged by the linter.\n"
            "2. Fix formatting, unused imports, or style violations without changing program logic.\n"
            "3. Re-run verification."
        )
        return RecoveryAction(
            error_code=ErrorCode.LINT_REGRESSION,
            level=1,
            action_description="LINT_REGRESSION: Inject violation locations for delta repair",
            injection_prompt=prompt,
            rollback_required=False,
        )

    def _remediate_test_failed(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        failing_tests = ctx.get("failing_tests", "Reproduction test case")
        trace = ctx.get("detail", "Test assertion failure")
        prompt = (
            f"TEST_FAILED at step {step}:\n"
            "Exit code: 1\n"
            f"Failing tests: {failing_tests}\n"
            f"Stack trace:\n{trace}\n\n"
            "REQUIRED RECOVERY STEPS:\n"
            "1. Read the failing test file to understand what it expects.\n"
            "2. Identify which line of your patch caused the failure.\n"
            "3. Consider: is the test wrong, or is your implementation wrong?\n"
            "4. Run git_diff to review your current changes."
        )
        return RecoveryAction(
            error_code=ErrorCode.TEST_FAILED,
            level=1,
            action_description="TEST_FAILED: Inject stack trace and test guidance",
            injection_prompt=prompt,
            rollback_required=False,
        )

    def _remediate_regression_detected(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        regressions = ctx.get("detail", "Previously passing tests failed")
        prompt = (
            f"REGRESSION_DETECTED at step {step}:\n"
            "The patch caused new test failures in previously passing tests:\n"
            f"{regressions}\n\n"
            "REQUIRED RECOVERY STEPS:\n"
            "1. Review the regression failures above.\n"
            "2. Run git_diff to identify which change broke existing behavior.\n"
            "3. Roll back the regressing edit or adjust the patch to preserve backward compatibility."
        )
        return RecoveryAction(
            error_code=ErrorCode.REGRESSION_DETECTED,
            level=2,
            action_description="REGRESSION_DETECTED: Rollback regressing edit and preserve compatibility",
            injection_prompt=prompt,
            rollback_required=True,
            rollback_scope="checkpoint",
        )

    def _remediate_side_effect_detected(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        detail = ctx.get("detail", "Module import produced unexpected top-level side effects")
        prompt = (
            f"SIDE_EFFECT_DETECTED at step {step}:\n"
            "Module import produced unexpected side effects:\n"
            f"{detail}\n\n"
            "REQUIRED RECOVERY STEPS:\n"
            "1. Inspect module-level code for top-level print statements, sys.exit(), or execution logic.\n"
            "2. Refactor side-effect logic into functions or protect under `if __name__ == '__main__':`."
        )
        return RecoveryAction(
            error_code=ErrorCode.SIDE_EFFECT_DETECTED,
            level=1,
            action_description="SIDE_EFFECT_DETECTED: Refactor module-level execution to functions",
            injection_prompt=prompt,
            rollback_required=False,
        )

    def _remediate_timeout(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        timeout = ctx.get("timeout_sec", 30)
        prompt = (
            f"TIMEOUT at step {step}:\n"
            f"The command/test exceeded the maximum execution time limit ({timeout}s) and was terminated.\n\n"
            "REQUIRED RECOVERY STEPS:\n"
            "1. Use a more targeted test filter (e.g. run a specific test case instead of full suite).\n"
            "2. Check for potential infinite loops, deadlocks, or slow I/O operations."
        )
        return RecoveryAction(
            error_code=ErrorCode.TIMEOUT,
            level=1,
            action_description="TIMEOUT: Kill process and guide toward targeted test filter",
            injection_prompt=prompt,
            rollback_required=False,
        )

    def _remediate_tool_blocked(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        command = ctx.get("command", "disallowed command")
        prompt = (
            f"TOOL_BLOCKED at step {step}:\n"
            f"Command disallowed by security policy: {command}\n\n"
            "REQUIRED RECOVERY STEPS:\n"
            "1. Use permitted tools only.\n"
            "2. Avoid shell pipes, privilege escalation, or destructive commands."
        )
        return RecoveryAction(
            error_code=ErrorCode.TOOL_BLOCKED,
            level=1,
            action_description="TOOL_BLOCKED: Enforce security blocklist and suggest safe alternatives",
            injection_prompt=prompt,
            rollback_required=False,
        )

    def _remediate_loop_detected(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        tool = ctx.get("tool", "tool")
        args = ctx.get("args", "args")
        prompt = (
            f"LOOP DETECTED at step {step}: `{tool}({args})` called twice identically.\n"
            "REQUIRED ACTIONS:\n"
            "1. Run git_rollback to restore clean state.\n"
            "2. Re-read the TARGET SECTION (±20 lines around your target).\n"
            "3. State in one sentence: what was DIFFERENT about what you found.\n"
            "4. Propose a DIFFERENT approach before any edit."
        )
        return RecoveryAction(
            error_code=ErrorCode.LOOP_DETECTED,
            level=2,
            action_description="LOOP_DETECTED: Mandatory strategy shift injection",
            injection_prompt=prompt,
            rollback_required=False,
        )

    def _remediate_max_steps_exceeded(self, ctx: dict[str, Any], step: int) -> RecoveryAction:
        max_steps = self.config.max_steps
        prompt = (
            f"MAX_STEPS_EXCEEDED at step {step}:\n"
            f"Maximum allowed steps ({max_steps}) reached.\n"
            "Harness will execute graceful exit: rollback all unverified changes and compile partial report."
        )
        return RecoveryAction(
            error_code=ErrorCode.MAX_STEPS_EXCEEDED,
            level=3,
            action_description="MAX_STEPS_EXCEEDED: Execute graceful exit and full rollback",
            injection_prompt=prompt,
            rollback_required=True,
            rollback_scope="all",
        )
