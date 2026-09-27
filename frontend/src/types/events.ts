export type AgentPhase =
  | 'INIT'
  | 'PLAN'
  | 'ACT'
  | 'OBSERVE'
  | 'REFLECT'
  | 'DONE_CANDIDATE'
  | 'DONE'
  | 'FAILED';

export type EventType =
  | 'SESSION_START'
  | 'CONVERSATIONAL'
  | 'TOOL_CALL'
  | 'TOOL_RESULT'
  | 'LLM_TURN_START'
  | 'LLM_TURN_END'
  | 'VERIFICATION_PHASE'
  | 'RECOVERY_EVENT'
  | 'PLAN_REVISION'
  | 'SUBAGENT_SPAWN'
  | 'SUBAGENT_RESULT'
  | 'SKILL_FETCH'
  | 'CONTEXT_COMPRESSION'
  | 'ROLLBACK'
  | 'CHECKPOINT'
  | 'PLAN_EMIT'
  | 'PLAN_START'
  | 'REPO_ANALYSIS'
  | 'DONE_CANDIDATE'
  | 'DONE'
  | 'FAILED'
  | 'FILE_CHANGED';

export interface PlanStepItem {
  step: number;
  description: string;
  tool_prediction: string;
  expected_outcome?: string;
}

export interface TelemetryEvent {
  schema_version?: string;
  event_id?: string;
  session_id?: string;
  timestamp: string;
  step: number;
  phase: AgentPhase;
  agent: string;
  event_type: EventType;
  tool?: string | null;
  tool_args_hash?: string | null;
  tool_args?: Record<string, any> | null;
  reasoning?: string | null;
  tokens_in?: number;
  tokens_out?: number;
  tokens_cumulative?: number;
  cost_usd?: number;
  cost_cumulative_usd?: number;
  latency_ms?: number;
  result_status?: string;
  error_code?: string | null;
  recovery_triggered?: boolean;
  loop_count?: number;
  revision_count?: number;
  plan_steps?: PlanStepItem[];
  evidence?: string[];
  files_modified?: string[];
  final_response?: string;
}
