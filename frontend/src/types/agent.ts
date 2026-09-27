import type { PhaseStatus } from './verification';

export type HarnessStatus = 'READY' | 'RUNNING' | 'VERIFIED' | 'FAILED';

export interface HarnessState {
  status: HarnessStatus;
  repo_path: string;
  repo_name: string;
  git_branch?: string;
  active_issue?: string;
  current_step: number;
  current_phase: string;
  verification: Record<string, PhaseStatus>;
  stats: {
    tokens_in: number;
    tokens_out: number;
    tokens_cumulative: number;
    cost_usd: number;
    cost_cumulative_usd: number;
    elapsed_seconds: number;
  };
}

export interface FileDiff {
  path: string;
  status: 'modified' | 'added' | 'deleted';
  diff: string;
  additions: number;
  deletions: number;
}

export interface DiffResponse {
  status_summary: string;
  diff_summary: string;
  full_diff: string;
  files: FileDiff[];
}
