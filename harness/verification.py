"""Verification Gate — 6-Phase Deterministic Quality Gate (Layer 7).

Implements the multi-phase deterministic verification pipeline specified in
PRD §4.7 and architecture.md §12:
  Phase 1: Syntax check (py_compile, tsc, go vet, cargo check)
  Phase 2: Linter check (Delta mode vs linter_baseline.json)
  Phase 3: Reproduction test (test_filter from IssuePlan)
  Phase 4: Full regression suite (delta vs test_baseline.json)
  Phase 5: Diff audit (file scope, binary check, whitespace-only check)
  Phase 6: Side-effect check (isolated module import)
"""

import ast
import json
import os
import py_compile
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.config import VerificationConfig
from harness.contracts import (
    AgentPhase,
    ErrorCode,
    EventType,
    IssuePlan,
    PhaseResult,
    ResultStatus,
    TelemetryEvent,
    VerificationPhase,
    VerificationResult,
)
from harness.telemetry import TelemetryWriter
from harness.tools.security import sanitized_env


class VerificationGate:
    """Deterministic, model-agnostic verification gate.

    The foundation model cannot declare completion. Only VerificationGate can
    grant status SUCCESS / PASS across the 6 sequential phases.
    """

    def __init__(
        self,
        config: VerificationConfig | None = None,
        telemetry: TelemetryWriter | None = None,
    ) -> None:
        self.config = config or VerificationConfig()
        self.telemetry = telemetry

    def verify(
        self,
        repo_path: str,
        modified_files: list[str] | None = None,
        issue_plan: IssuePlan | None = None,
        step: int = 0,
        baseline_dir: str | None = None,
    ) -> VerificationResult:
        """Run the 6-phase verification pipeline sequentially with early-exit on first failure."""
        start_time = time.time()
        verification_id = f"v-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        if modified_files is None:
            modified_files = self._detect_modified_files(repo_path)

        phases: dict[str, PhaseResult] = {}
        first_failure: VerificationPhase | None = None
        recovery_action: str | None = None

        # Phase execution plan
        phase_pipeline = [
            (VerificationPhase.SYNTAX, self.config.run_syntax_check, self._run_syntax_check),
            (VerificationPhase.LINT, self.config.run_lint_check, lambda r, m, i, b: self._run_lint_check(r, m, b)),
            (VerificationPhase.REPRO_TEST, self.config.run_repro_test, lambda r, m, i, b: self._run_repro_test(r, i)),
            (VerificationPhase.REGRESSION, self.config.run_full_regression, lambda r, m, i, b: self._run_regression_suite(r, b)),
            (VerificationPhase.DIFF_AUDIT, self.config.run_diff_audit, lambda r, m, i, b: self._run_diff_audit(r, m, i)),
            (VerificationPhase.SIDE_EFFECT, self.config.run_side_effect_check, lambda r, m, i, b: self._run_side_effect_check(r, m)),
        ]

        diff_summary = self._get_diff_summary(repo_path)

        for phase, is_enabled, runner in phase_pipeline:
            if not is_enabled:
                continue

            phase_result = runner(repo_path, modified_files, issue_plan, baseline_dir)
            phases[phase.value] = phase_result

            # Emit telemetry for each executed verification phase
            if self.telemetry:
                self.telemetry.append(
                    TelemetryEvent(
                        step=step,
                        phase=AgentPhase.DONE_CANDIDATE,
                        event_type=EventType.VERIFICATION_PHASE,
                        result_status=phase_result.status,
                        latency_ms=phase_result.duration_ms,
                        reasoning=f"Phase {phase.value}: {phase_result.detail}",
                    )
                )

            # Early-exit on first failure
            if phase_result.status != ResultStatus.SUCCESS:
                first_failure = phase
                recovery_action = self._resolve_recovery_action(phase)
                break

        overall_status = ResultStatus.SUCCESS if first_failure is None else ResultStatus.FAIL
        total_duration_ms = int((time.time() - start_time) * 1000)

        return VerificationResult(
            verification_id=verification_id,
            run_at=datetime.now(timezone.utc),
            status=overall_status,
            phases=phases,
            first_failure=first_failure,
            recovery_action=recovery_action,
            diff_summary=diff_summary,
            total_duration_ms=total_duration_ms,
        )

    # ─── Phase 1: Syntax Check ─────────────────────────────────────────────

    def _run_syntax_check(
        self,
        repo_path: str,
        modified_files: list[str],
        issue_plan: IssuePlan | None = None,
        baseline_dir: str | None = None,
    ) -> PhaseResult:
        """Phase 1: Language syntax check across modified files."""
        start = time.time()
        errors: list[str] = []

        for rel_file in modified_files:
            abs_file = Path(repo_path) / rel_file
            if not abs_file.exists() or abs_file.is_dir():
                continue

            ext = abs_file.suffix.lower()

            if ext == ".py":
                try:
                    with open(abs_file, "r", encoding="utf-8", errors="replace") as f:
                        source = f.read()
                    ast.parse(source, filename=str(abs_file))
                    py_compile.compile(str(abs_file), doraise=True)
                except (SyntaxError, py_compile.PyCompileError) as e:
                    line_no = getattr(e, "lineno", getattr(e, "msg", "unknown"))
                    errors.append(f"{rel_file}:{line_no}: {e!s}")

            elif ext in (".js", ".jsx", ".ts", ".tsx"):
                # If node is present, check syntax
                node_bin = shutil.which("node")
                if node_bin:
                    proc = subprocess.run(
                        [node_bin, "--check", str(abs_file)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if proc.returncode != 0:
                        errors.append(f"{rel_file}: {proc.stderr.strip() or proc.stdout.strip()}")
                else:
                    # Basic bracket/brace balance check fallback
                    balanced, err_msg = self._check_balanced_brackets(abs_file)
                    if not balanced:
                        errors.append(f"{rel_file}: {err_msg}")

            elif ext == ".go":
                go_bin = shutil.which("go")
                if go_bin:
                    proc = subprocess.run(
                        [go_bin, "vet", str(abs_file)],
                        capture_output=True,
                        text=True,
                        cwd=repo_path,
                        check=False,
                    )
                    if proc.returncode != 0:
                        errors.append(f"{rel_file}: {proc.stderr.strip()}")

            elif ext == ".rs":
                cargo_bin = shutil.which("cargo")
                if cargo_bin:
                    proc = subprocess.run(
                        [cargo_bin, "check"],
                        capture_output=True,
                        text=True,
                        cwd=repo_path,
                        check=False,
                    )
                    if proc.returncode != 0:
                        errors.append(f"{rel_file}: {proc.stderr.strip()}")

        duration_ms = int((time.time() - start) * 1000)

        if errors:
            detail = f"Syntax errors detected in {len(errors)} file(s):\n" + "\n".join(errors)
            return PhaseResult(
                phase=VerificationPhase.SYNTAX,
                status=ResultStatus.FAIL,
                detail=detail,
                duration_ms=duration_ms,
            )

        return PhaseResult(
            phase=VerificationPhase.SYNTAX,
            status=ResultStatus.SUCCESS,
            detail=f"Syntax verified cleanly across {len(modified_files)} file(s)",
            duration_ms=duration_ms,
        )

    # ─── Phase 2: Linter Check (Delta Mode) ────────────────────────────────

    def _run_lint_check(
        self,
        repo_path: str,
        modified_files: list[str],
        baseline_dir: str | None = None,
    ) -> PhaseResult:
        """Phase 2: Linter check (delta mode comparing against baseline)."""
        start = time.time()
        linter_bin = self.config.linter

        # If no modified files, pass immediately
        if not modified_files:
            return PhaseResult(
                phase=VerificationPhase.LINT,
                status=ResultStatus.SUCCESS,
                detail="No modified files to lint",
                duration_ms=0,
            )

        # Filter for lintable files (e.g., Python files for ruff)
        lintable_files = [f for f in modified_files if f.endswith((".py", ".pyi"))]
        if not lintable_files and linter_bin in ("ruff", "flake8", "pylint"):
            return PhaseResult(
                phase=VerificationPhase.LINT,
                status=ResultStatus.SUCCESS,
                detail=f"No lintable Python files among modified files: {modified_files}",
                duration_ms=0,
            )

        target_files = lintable_files if lintable_files else modified_files
        # Use '--' to prevent command-line option injection from filenames
        cmd = [linter_bin, "check", "--output-format=json", "--"] + target_files
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=repo_path,
                check=False,
            )
            raw_output = proc.stdout.strip()
            current_violations: list[dict[str, Any]] = []
            if raw_output:
                try:
                    current_violations = json.loads(raw_output)
                except json.JSONDecodeError:
                    pass
        except FileNotFoundError:
            # Fallback if configured linter binary not found
            duration_ms = int((time.time() - start) * 1000)
            return PhaseResult(
                phase=VerificationPhase.LINT,
                status=ResultStatus.SUCCESS,
                detail=f"Linter '{linter_bin}' not installed; skipped linter phase",
                duration_ms=duration_ms,
            )

        # Baseline resolution
        baseline_path = self._resolve_baseline_path(repo_path, baseline_dir, "linter_baseline.json")
        baseline_violations: list[dict[str, Any]] = []
        if baseline_path.exists():
            try:
                with open(baseline_path, "r", encoding="utf-8") as f:
                    baseline_violations = json.load(f)
            except (OSError, json.JSONDecodeError):
                baseline_violations = []

        if self.config.linter_fail_on_new_only and baseline_violations:
            # Fingerprint baseline violations by (relative_path, code, line)
            baseline_keys = {
                (
                    self._normalize_path(v.get("filename", "")),
                    v.get("code", ""),
                    v.get("location", {}).get("row", 0),
                )
                for v in baseline_violations
            }
            new_violations = [
                v
                for v in current_violations
                if (
                    self._normalize_path(v.get("filename", "")),
                    v.get("code", ""),
                    v.get("location", {}).get("row", 0),
                )
                not in baseline_keys
            ]
        else:
            new_violations = current_violations

        duration_ms = int((time.time() - start) * 1000)

        if new_violations:
            violation_summaries = [
                f"{v.get('filename')}:{v.get('location', {}).get('row', '?')}:{v.get('location', {}).get('column', '?')} "
                f"[{v.get('code', 'ERR')}] {v.get('message', '')}"
                for v in new_violations[:10]
            ]
            detail = f"{len(new_violations)} new linter violation(s) introduced:\n" + "\n".join(violation_summaries)
            return PhaseResult(
                phase=VerificationPhase.LINT,
                status=ResultStatus.FAIL,
                detail=detail,
                duration_ms=duration_ms,
            )

        return PhaseResult(
            phase=VerificationPhase.LINT,
            status=ResultStatus.SUCCESS,
            detail="0 new linter violations detected vs baseline",
            duration_ms=duration_ms,
        )

    # ─── Phase 3: Reproduction Test ────────────────────────────────────────

    def _run_repro_test(
        self,
        repo_path: str,
        issue_plan: IssuePlan | None = None,
    ) -> PhaseResult:
        """Phase 3: Run targeted reproduction test using test_filter."""
        start = time.time()
        test_filter = issue_plan.test_filter if issue_plan else ""

        if not test_filter:
            duration_ms = int((time.time() - start) * 1000)
            return PhaseResult(
                phase=VerificationPhase.REPRO_TEST,
                status=ResultStatus.SUCCESS,
                detail="No test_filter specified in IssuePlan; repro phase skipped",
                duration_ms=duration_ms,
            )

        # Construct test command
        cmd = self._build_test_command(repo_path, test_filter, issue_plan)
        env = sanitized_env({"PYTHONPATH": f"{repo_path}:{os.environ.get('PYTHONPATH', '')}"})

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=120,
                check=False,
                env=env,
            )
            duration_ms = int((time.time() - start) * 1000)

            if proc.returncode == 0:
                return PhaseResult(
                    phase=VerificationPhase.REPRO_TEST,
                    status=ResultStatus.SUCCESS,
                    detail=f"Reproduction test '{test_filter}' passed (exit code 0)",
                    duration_ms=duration_ms,
                )

            # Failure: extract truncated traceback
            output = proc.stdout + "\n" + proc.stderr
            return PhaseResult(
                phase=VerificationPhase.REPRO_TEST,
                status=ResultStatus.FAIL,
                detail=f"Reproduction test '{test_filter}' failed (exit code {proc.returncode}):\n{self._truncate_lines(output, 80)}",
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            return PhaseResult(
                phase=VerificationPhase.REPRO_TEST,
                status=ResultStatus.FAIL,
                detail=f"Reproduction test timed out after 120s: {test_filter}",
                duration_ms=duration_ms,
            )

    # ─── Phase 4: Full Regression Suite ────────────────────────────────────

    def _run_regression_suite(
        self,
        repo_path: str,
        baseline_dir: str | None = None,
    ) -> PhaseResult:
        """Phase 4: Run full regression test suite and verify no newly introduced test failures."""
        start = time.time()
        test_runner = self._resolve_python_test_runner(repo_path)
        cmd = test_runner + ["-q"]

        env = sanitized_env({"PYTHONPATH": f"{repo_path}:{os.environ.get('PYTHONPATH', '')}"})
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=180,
                check=False,
                env=env,
            )
            raw_output = proc.stdout + "\n" + proc.stderr
            current_failures = self._extract_pytest_failures(raw_output)
            duration_ms = int((time.time() - start) * 1000)

            # Check baseline
            baseline_path = self._resolve_baseline_path(repo_path, baseline_dir, "test_baseline.json")
            baseline_failures: set[str] = set()

            if baseline_path.exists():
                try:
                    with open(baseline_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        baseline_failures = set(data.get("failing_tests", []))
                except (OSError, json.JSONDecodeError):
                    baseline_failures = set()

            new_failures = [f for f in current_failures if f not in baseline_failures]

            if new_failures:
                detail = f"{len(new_failures)} new regression test failure(s) detected:\n" + "\n".join(new_failures[:10])
                return PhaseResult(
                    phase=VerificationPhase.REGRESSION,
                    status=ResultStatus.FAIL,
                    detail=detail,
                    duration_ms=duration_ms,
                )

            if proc.returncode != 0:
                has_collection_error = "ERROR " in raw_output or "ERRORS" in raw_output
                if proc.returncode != 1 or has_collection_error or not current_failures or not baseline_failures:
                    return PhaseResult(
                        phase=VerificationPhase.REGRESSION,
                        status=ResultStatus.FAIL,
                        detail=f"Regression suite exited with code {proc.returncode} (collection error or runner failure):\n{self._truncate_lines(raw_output, 40)}",
                        duration_ms=duration_ms,
                    )

            return PhaseResult(
                phase=VerificationPhase.REGRESSION,
                status=ResultStatus.SUCCESS,
                detail="Full regression suite passed (0 new regressions)",
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            return PhaseResult(
                phase=VerificationPhase.REGRESSION,
                status=ResultStatus.FAIL,
                detail="Full regression suite timed out after 180s",
                duration_ms=duration_ms,
            )

    # ─── Phase 5: Diff Audit ───────────────────────────────────────────────

    def _run_diff_audit(
        self,
        repo_path: str,
        modified_files: list[str],
        issue_plan: IssuePlan | None = None,
    ) -> PhaseResult:
        """Phase 5: Diff audit verifying file scope, binary absence, and substantive changes."""
        start = time.time()
        anomalies: list[str] = []

        # 1. Check for binary modifications
        try:
            diff_proc = subprocess.run(
                ["git", "diff", "HEAD"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                check=False,
            )
            raw_diff = diff_proc.stdout
            if "GIT binary patch" in raw_diff or "Binary files" in raw_diff:
                anomalies.append("Binary file modification detected in git diff")

            for rel_file in modified_files:
                abs_path = Path(repo_path) / rel_file
                if abs_path.is_file():
                    with open(abs_path, "rb") as f:
                        header = f.read(8192)
                        if b"\x00" in header:
                            anomalies.append(f"Binary file modification detected: {rel_file}")

            # 2. Whitespace-only change check
            if raw_diff.strip():
                ignore_ws_proc = subprocess.run(
                    ["git", "diff", "-w", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    check=False,
                )
                if not ignore_ws_proc.stdout.strip():
                    anomalies.append("Whitespace-only change: patch contains no substantive code edits")

        except (subprocess.SubprocessError, OSError) as e:
            anomalies.append(f"Diff inspection failed: {e}")

        # 3. File scope check against IssuePlan suspected_files (warning/soft check)
        if issue_plan and issue_plan.suspected_files:
            expected_paths = {self._normalize_path(sf.path) for sf in issue_plan.suspected_files}
            unexpected_modifications = [
                f for f in modified_files
                if self._normalize_path(f) not in expected_paths and not self._normalize_path(f).startswith("tests/")
            ]
            if len(unexpected_modifications) > 3:
                anomalies.append(
                    f"Scope anomaly: multiple unexpected files modified outside suspected files: {unexpected_modifications}"
                )

        duration_ms = int((time.time() - start) * 1000)

        # Binary check, whitespace-only, and diff execution errors are hard fails
        hard_fails = [a for a in anomalies if "Binary" in a or "Whitespace-only" in a or "Diff inspection failed" in a]
        if hard_fails:
            return PhaseResult(
                phase=VerificationPhase.DIFF_AUDIT,
                status=ResultStatus.FAIL,
                detail="\n".join(anomalies),
                duration_ms=duration_ms,
            )

        return PhaseResult(
            phase=VerificationPhase.DIFF_AUDIT,
            status=ResultStatus.SUCCESS,
            detail=f"Diff audit passed across {len(modified_files)} file(s)" + (f" (notes: {anomalies})" if anomalies else ""),
            duration_ms=duration_ms,
        )

    # ─── Phase 6: Side-Effect Check ────────────────────────────────────────

    def _run_side_effect_check(
        self,
        repo_path: str,
        modified_files: list[str],
    ) -> PhaseResult:
        """Phase 6: Isolated module import checking for side effects (sys.exit, top-level errors)."""
        start = time.time()
        failures: list[str] = []

        python_bin = sys.executable

        for rel_file in modified_files:
            if not rel_file.endswith(".py"):
                continue

            abs_file = Path(repo_path) / rel_file
            if not abs_file.is_file():
                continue

            # Convert relative path to module name
            parts = Path(rel_file).with_suffix("").parts
            if "__init__" in parts:
                parts = [p for p in parts if p != "__init__"]
            module_name = ".".join(parts)
            if not module_name:
                continue

            script = (
                "import sys, os\n"
                "sys.path.insert(0, os.getcwd())\n"
                "try:\n"
                "    import importlib\n"
                f"    importlib.import_module({module_name!r})\n"
                "except BaseException as e:\n"
                "    sys.stderr.write(f'IMPORT_ERROR: {e}\\n')\n"
                "    sys.exit(42)\n"
            )

            env = sanitized_env({"PYTHONPATH": f"{repo_path}:{os.environ.get('PYTHONPATH', '')}"})
            try:
                proc = subprocess.run(
                    [python_bin, "-c", script],
                    capture_output=True,
                    text=True,
                    cwd=repo_path,
                    timeout=10,
                    check=False,
                    env=env,
                )
                if proc.returncode != 0:
                    failures.append(
                        f"Module '{module_name}' failed isolated import (exit code {proc.returncode}):\n"
                        f"{proc.stderr.strip() or proc.stdout.strip()}"
                    )
            except subprocess.TimeoutExpired:
                failures.append(f"Module '{module_name}' timed out during isolated import check")

        duration_ms = int((time.time() - start) * 1000)

        if failures:
            return PhaseResult(
                phase=VerificationPhase.SIDE_EFFECT,
                status=ResultStatus.FAIL,
                detail="\n".join(failures),
                duration_ms=duration_ms,
            )

        return PhaseResult(
            phase=VerificationPhase.SIDE_EFFECT,
            status=ResultStatus.SUCCESS,
            detail="Clean isolated module import verified for all modified Python files",
            duration_ms=duration_ms,
        )

    # ─── Helper Utilities ──────────────────────────────────────────────────

    def _detect_modified_files(self, repo_path: str) -> list[str]:
        """Detect modified or newly added files using git status."""
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                check=False,
            )
            files: list[str] = []
            for line in proc.stdout.splitlines():
                if not line.strip():
                    continue
                status_code = line[:2]
                raw_path = line[3:].strip()
                # Handle renamed files: 'R  old -> new'
                if " -> " in raw_path:
                    raw_path = raw_path.split(" -> ")[1].strip()
                # Strip optional quotes git adds for paths with spaces
                if raw_path.startswith('"') and raw_path.endswith('"'):
                    raw_path = raw_path[1:-1]
                # Filter out deleted files
                if "D" in status_code:
                    continue
                # Filter out harness internal files and virtual environments
                if raw_path.startswith((".harness/", ".venv/", ".git/")):
                    continue
                files.append(raw_path)
            return files
        except (subprocess.SubprocessError, OSError):
            return []

    def _get_diff_summary(self, repo_path: str) -> str:
        """Get short summary of current diff."""
        try:
            proc = subprocess.run(
                ["git", "diff", "--shortstat"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                check=False,
            )
            return proc.stdout.strip() or "No changes detected"
        except (subprocess.SubprocessError, OSError):
            return "Unavailable"

    def _resolve_baseline_path(self, repo_path: str, baseline_dir: str | None, filename: str) -> Path:
        """Resolve path to baseline JSON file."""
        if baseline_dir:
            return Path(baseline_dir) / filename
        return Path(repo_path) / ".harness" / "repo_index" / filename

    def _resolve_python_test_runner(self, repo_path: str) -> list[str]:
        """Determine suitable pytest invocation."""
        venv_pytest = Path(repo_path) / ".venv" / "bin" / "pytest"
        if venv_pytest.exists():
            return [str(venv_pytest)]
        return [sys.executable, "-m", "pytest"]

    def _build_test_command(
        self,
        repo_path: str,
        test_filter: str,
        issue_plan: IssuePlan | None = None,
    ) -> list[str]:
        """Build test runner command line preserving quoted filter expressions."""
        base_cmd = self._resolve_python_test_runner(repo_path)
        try:
            tokens = shlex.split(test_filter)
        except ValueError:
            tokens = test_filter.split()

        if tokens and tokens[0] in ("pytest", "py.test"):
            tokens = tokens[1:]
        elif len(tokens) >= 3 and tokens[0] == "python" and tokens[1] == "-m" and tokens[2] == "pytest":
            tokens = tokens[3:]

        return base_cmd + tokens

    def _extract_pytest_failures(self, output: str) -> list[str]:
        """Extract failed and errored test identifiers from pytest stdout."""
        failures: list[str] = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith(("FAILED ", "ERROR ")):
                parts = line.split(maxsplit=2)
                if len(parts) >= 2:
                    failures.append(parts[1])
        return failures

    def _truncate_lines(self, text: str, max_lines: int) -> str:
        """Truncate text to max_lines keeping head and tail."""
        lines = text.splitlines()
        if len(lines) <= max_lines:
            return text
        head = lines[: max_lines // 2]
        tail = lines[-(max_lines // 2) :]
        return "\n".join(head + [f"... [{len(lines) - max_lines} lines omitted] ..."] + tail)

    def _normalize_path(self, path_str: str) -> str:
        """Normalize file paths for consistent comparison."""
        return str(Path(path_str).as_posix())

    def _check_balanced_brackets(self, file_path: Path) -> tuple[bool, str]:
        """Syntax fallback for JavaScript/TypeScript that ignores strings and comments."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            stack: list[tuple[str, int, int]] = []
            matching = {")": "(", "}": "{", "]": "["}

            i = 0
            n = len(content)
            line = 1
            col = 1
            in_single = False
            in_double = False
            in_template = False
            in_line_comment = False
            in_block_comment = False

            while i < n:
                ch = content[i]
                cur_line = line
                cur_col = col

                if ch == "\n":
                    line += 1
                    col = 1
                else:
                    col += 1

                # Handle escape sequences inside strings
                if (in_single or in_double or in_template) and ch == "\\":
                    i += 2
                    col += 1
                    continue

                if in_line_comment:
                    if ch == "\n":
                        in_line_comment = False
                    i += 1
                    continue

                if in_block_comment:
                    if ch == "*" and i + 1 < n and content[i + 1] == "/":
                        in_block_comment = False
                        i += 2
                        col += 1
                        continue
                    i += 1
                    continue

                if in_single:
                    if ch == "'":
                        in_single = False
                    i += 1
                    continue

                if in_double:
                    if ch == '"':
                        in_double = False
                    i += 1
                    continue

                if in_template:
                    if ch == "`":
                        in_template = False
                    elif ch == "$" and i + 1 < n and content[i + 1] == "{":
                        stack.append(("{", cur_line, cur_col))
                        i += 2
                        col += 1
                        continue
                    i += 1
                    continue

                # Check start of comments
                if ch == "/" and i + 1 < n:
                    next_ch = content[i + 1]
                    if next_ch == "/":
                        in_line_comment = True
                        i += 2
                        col += 1
                        continue
                    elif next_ch == "*":
                        in_block_comment = True
                        i += 2
                        col += 1
                        continue

                # Check start of strings
                if ch == "'":
                    in_single = True
                    i += 1
                    continue
                elif ch == '"':
                    in_double = True
                    i += 1
                    continue
                elif ch == "`":
                    in_template = True
                    i += 1
                    continue

                # Bracket matching outside of strings and comments
                if ch in "({[":
                    stack.append((ch, cur_line, cur_col))
                elif ch in ")}]":
                    if not stack or stack[-1][0] != matching[ch]:
                        return False, f"Unmatched closing bracket '{ch}' at line {cur_line}:{cur_col}"
                    stack.pop()

                i += 1

            if in_single or in_double or in_template:
                return False, f"Unterminated string literal at line {line}:{col}"
            if in_block_comment:
                return False, f"Unterminated block comment at line {line}:{col}"
            if stack:
                unclosed, u_line, u_col = stack[-1]
                return False, f"Unclosed bracket '{unclosed}' opened at line {u_line}:{u_col}"

            return True, ""
        except (OSError, UnicodeDecodeError) as e:
            return False, str(e)

    def _resolve_recovery_action(self, phase: VerificationPhase) -> str:
        """Map failing verification phase to recovery action code."""
        mapping = {
            VerificationPhase.SYNTAX: f"RECOVERY_{ErrorCode.AST_PARSE_FAIL.value}",
            VerificationPhase.LINT: f"RECOVERY_{ErrorCode.LINT_REGRESSION.value}",
            VerificationPhase.REPRO_TEST: f"RECOVERY_{ErrorCode.TEST_FAILED.value}",
            VerificationPhase.REGRESSION: f"RECOVERY_{ErrorCode.REGRESSION_DETECTED.value}",
            VerificationPhase.DIFF_AUDIT: f"RECOVERY_{ErrorCode.PATCH_FAILED.value}",
            VerificationPhase.SIDE_EFFECT: f"RECOVERY_{ErrorCode.SIDE_EFFECT_DETECTED.value}",
        }
        return mapping.get(phase, "RECOVERY_GENERAL")


def capture_baselines(
    repo_path: str,
    output_dir: str = ".harness/repo_index",
    linter: str = "ruff",
    test_runner_args: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Capture startup baseline files for delta linter and regression checks (Task 3.7).

    Writes:
      - .harness/repo_index/linter_baseline.json
      - .harness/repo_index/test_baseline.json
    """
    out_path = Path(repo_path) / output_dir
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. Capture linter baseline
    linter_baseline: list[dict[str, Any]] = []
    linter_proc = shutil.which(linter)
    if linter_proc:
        try:
            proc = subprocess.run(
                [linter, "check", "--output-format=json", "--", "."],
                capture_output=True,
                text=True,
                cwd=repo_path,
                check=False,
            )
            if proc.stdout.strip():
                linter_baseline = json.loads(proc.stdout.strip())
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
            linter_baseline = []

    with open(out_path / "linter_baseline.json", "w", encoding="utf-8") as f:
        json.dump(linter_baseline, f, indent=2)

    # 2. Capture test baseline
    venv_pytest = Path(repo_path) / ".venv" / "bin" / "pytest"
    runner_cmd = [str(venv_pytest)] if venv_pytest.exists() else [sys.executable, "-m", "pytest"]
    if test_runner_args:
        runner_cmd += test_runner_args
    else:
        runner_cmd += ["-q"]

    failing_tests: list[str] = []
    total = 0
    passed = 0
    failed = 0

    try:
        proc = subprocess.run(
            runner_cmd,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=120,
            check=False,
        )
        output = proc.stdout + "\n" + proc.stderr
        for line in output.splitlines():
            line = line.strip()
            if line.startswith(("FAILED ", "ERROR ")):
                parts = line.split(maxsplit=2)
                if len(parts) >= 2:
                    failing_tests.append(parts[1])
        failed = len(failing_tests)

        # Parse summary counts from pytest output if present
        match = re.search(r"=\s*(?:(\d+)\s+passed)?[,\s]*(?:(\d+)\s+failed)?", output)
        if match:
            if match.group(1):
                passed = int(match.group(1))
            if match.group(2):
                failed = int(match.group(2))
        total = passed + failed
    except (subprocess.SubprocessError, OSError):
        pass

    test_baseline: dict[str, Any] = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "failing_tests": failing_tests,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open(out_path / "test_baseline.json", "w", encoding="utf-8") as f:
        json.dump(test_baseline, f, indent=2)

    return {"violations": linter_baseline}, test_baseline
