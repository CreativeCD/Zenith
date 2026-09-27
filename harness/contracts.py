"""harness/contracts.py — Single source of truth for ALL typed data contracts.

Reference: PRD.md §8 | architecture.md §8
Every inter-layer boundary communicates strictly using these dataclasses.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# ─── Enums ─────────────────────────────────────────────────────────────

class TaskType(str, Enum):
    BUG_FIX = "BUG_FIX"
    FEATURE = "FEATURE"
    REFACTOR = "REFACTOR"
    TEST = "TEST"
    DOCS = "DOCS"
    PERF = "PERF"
    CONVERSATIONAL = "CONVERSATIONAL"


class RequestType(str, Enum):
    CONVERSATIONAL_REQUEST = "CONVERSATIONAL_REQUEST"
    CODE_TASK = "CODE_TASK"
    COMMAND = "COMMAND"


class Complexity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class AgentMode(str, Enum):
    SINGLE_REACT = "SINGLE_REACT"
    PLANNER_EXECUTOR = "PLANNER_EXECUTOR"
    MULTI_AGENT = "MULTI_AGENT"
    MULTI_AGENT_DEEP = "MULTI_AGENT_DEEP"


class AgentPhase(str, Enum):
    INIT = "INIT"
    PLAN = "PLAN"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    REFLECT = "REFLECT"
    DONE_CANDIDATE = "DONE_CANDIDATE"
    DONE = "DONE"
    FAILED = "FAILED"


class ResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"


class ErrorCode(str, Enum):
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


class VerificationPhase(str, Enum):
    SYNTAX = "SYNTAX"
    LINT = "LINT"
    REPRO_TEST = "REPRO_TEST"
    REGRESSION = "REGRESSION"
    DIFF_AUDIT = "DIFF_AUDIT"
    SIDE_EFFECT = "SIDE_EFFECT"


class EventType(str, Enum):
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
    PLAN_START = "PLAN_START"
    PLAN_EMIT = "PLAN_EMIT"
    REPO_ANALYSIS = "REPO_ANALYSIS"
    DONE_CANDIDATE = "DONE_CANDIDATE"
    SESSION_START = "SESSION_START"
    CONVERSATIONAL = "CONVERSATIONAL"


class SubagentRole(str, Enum):
    SCOUT = "scout"
    ARCHITECT = "architect"
    CODER = "coder"
    CRITIC = "critic"


class HarnessState(str, Enum):
    INITIALIZING = "INITIALIZING"
    PARSING_ISSUE = "PARSING_ISSUE"
    INDEXING_REPO = "INDEXING_REPO"
    PLANNING = "PLANNING"
    ACTING = "ACTING"
    REFLECTING = "REFLECTING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    COMPRESSING_CONTEXT = "COMPRESSING_CONTEXT"
    GENERATING_REPORT = "GENERATING_REPORT"
    HALTED = "HALTED"


# ─── Base Serialization Helper ──────────────────────────────────────────

def _serialize_value(val: Any) -> Any:
    if isinstance(val, Enum):
        return val.value
    elif isinstance(val, datetime):
        return val.isoformat()
    elif isinstance(val, list):
        return [_serialize_value(x) for x in val]
    elif isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}
    elif is_dataclass(val):
        return {k: _serialize_value(v) for k, v in asdict(val).items()}
    return val


@dataclass
class ContractBase:
    def to_dict(self) -> dict[str, Any]:
        return _serialize_value(self)

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ─── L1: Issue Parser Contracts ────────────────────────────────────────

@dataclass
class ClassificationResult(ContractBase):
    request_type: RequestType
    category: str = "general"
    confidence: float = 1.0
    reasoning: str = ""
    direct_response: str = ""


@dataclass
class SuspectedFile(ContractBase):
    path: str
    confidence: float               # 0.0 – 1.0
    reason: str
    suspected_symbol: str | None = None


@dataclass
class IssuePlan(ContractBase):
    issue_id: str
    primary_goal: str
    task_type: TaskType
    acceptance_criteria: list[str]
    suspected_files: list[SuspectedFile]
    reproduction_hint: str
    test_filter: str
    error_type: str | None
    complexity_estimate: Complexity
    estimated_steps: int
    requires_external_knowledge: bool
    language: str
    test_runner: str
    parsing_confidence: float
    parsing_method: str             # "RULE_BASED" | "LLM_ASSISTED"


# ─── L2: Repo Intelligence Contracts ───────────────────────────────────

@dataclass
class RankedFile(ContractBase):
    path: str
    relevance_score: float          # 0.0 – 1.0
    symbol_summary: str             # Signatures only, no bodies
    line_count: int
    language: str


@dataclass
class RankedFileSet(ContractBase):
    files: list[RankedFile]         # Sorted by relevance_score desc
    total_indexed: int
    index_tokens_cost: int


@dataclass
class RepoIndex(ContractBase):
    file_tree_path: str
    module_symbols_path: str
    dependency_graph_path: str
    test_map_path: str
    embedding_index_path: str
    total_files: int
    build_time_ms: int


# ─── L3: Tool Engine Contracts ─────────────────────────────────────────

@dataclass
class ToolCall(ContractBase):
    tool: str
    reasoning: str
    args: dict[str, Any]
    fingerprint: str = ""           # SHA256(tool + canonical(args))


@dataclass
class ToolResult(ContractBase):
    tool: str
    args_hash: str
    status: ResultStatus
    raw_output: str
    truncated_output: str
    exit_code: int | None = None
    error_code: ErrorCode | None = None
    tokens_in_raw: int = 0
    tokens_in_truncated: int = 0
    execution_time_ms: int = 0


# ─── L4: Context Manager Contracts ─────────────────────────────────────

@dataclass
class PromptSections(ContractBase):
    persona: str                    # Fixed, ~300 tokens
    issue_goal: str                 # Fixed per issue, ~200 tokens
    repo_context: str               # Dynamic, <= 1,000 tokens
    working_memory: str             # Rolling, <= 800 tokens
    recent_turns: str               # Last N raw turns, <= 4,000 tokens
    total_tokens: int
    budget_remaining: int


@dataclass
class WorkingMemory(ContractBase):
    goal: str
    files_examined: dict[str, str] = field(default_factory=dict)  # {path: finding}
    edits_applied: list[str] = field(default_factory=list)
    test_status: str = "PENDING"
    current_strategy: str = ""
    lessons_learned: list[str] = field(default_factory=list)


# ─── L5: Orchestrator Contracts ────────────────────────────────────────

@dataclass
class PlanStep(ContractBase):
    step: int
    description: str
    tool_prediction: str
    expected_outcome: str


@dataclass
class AgentPlan(ContractBase):
    steps: list[PlanStep]
    estimated_total_steps: int
    risk_factors: list[str]
    rollback_checkpoints: list[int]


@dataclass
class DoneCandidate(ContractBase):
    confidence: float
    evidence: list[str]
    files_modified: list[str]


# ─── L7: Verification Gate Contracts ───────────────────────────────────

@dataclass
class PhaseResult(ContractBase):
    phase: VerificationPhase
    status: ResultStatus
    detail: str
    duration_ms: int


@dataclass
class VerificationResult(ContractBase):
    verification_id: str
    run_at: datetime
    status: ResultStatus            # SUCCESS or FAIL
    phases: dict[str, PhaseResult] = field(default_factory=dict)
    first_failure: VerificationPhase | None = None
    recovery_action: str | None = None
    diff_summary: str = ""
    total_duration_ms: int = 0


# ─── L8: Recovery Engine Contracts ─────────────────────────────────────

@dataclass
class RecoveryAction(ContractBase):
    error_code: ErrorCode
    level: int                      # 1 = auto-remediate, 2 = plan revision, 3 = exit
    action_description: str
    injection_prompt: str           # Text injected into next agent turn
    rollback_required: bool = False
    rollback_scope: str = "none"    # "none" | "file" | "all" | "checkpoint"


# ─── L9: Telemetry Contracts ───────────────────────────────────────────

@dataclass
class TelemetryEvent(ContractBase):
    schema_version: str = "1.0"
    event_id: str = ""
    session_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    step: int = 0
    phase: AgentPhase = AgentPhase.INIT
    agent: str = "orchestrator"
    event_type: EventType = EventType.INIT
    tool: str | None = None
    tool_args_hash: str | None = None
    tool_args: dict[str, Any] | None = None
    reasoning: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cumulative: int = 0
    cost_usd: float = 0.0
    cost_cumulative_usd: float = 0.0
    latency_ms: int = 0
    result_status: ResultStatus = ResultStatus.SUCCESS
    error_code: ErrorCode | None = None
    recovery_triggered: bool = False
    loop_count: int = 0
    revision_count: int = 0
    context_tokens_used: int = 0
    context_budget: int = 32000
    context_utilization_pct: float = 0.0
    evidence: list[str] | None = None
    files_modified: list[str] | None = None
    final_response: str | None = None


@dataclass
class SessionResult(ContractBase):
    status: AgentPhase              # DONE or FAILED
    exit_code: int
    total_steps: int
    total_tokens: int
    total_cost_usd: float
    total_wall_time_ms: int
    verification_result: VerificationResult | None = None
    final_response: str = ""
    modified_files: list[str] = field(default_factory=list)
