export type VerificationPhaseName =
  | 'SYNTAX'
  | 'LINT'
  | 'REPRO_TEST'
  | 'REGRESSION'
  | 'DIFF_AUDIT'
  | 'SIDE_EFFECT';

export type PhaseStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';

export interface PhaseInfo {
  name: VerificationPhaseName;
  label: string;
  status: PhaseStatus;
  detail?: string;
  durationMs?: number;
}

export const VERIFICATION_PHASES_META: { name: VerificationPhaseName; label: string }[] = [
  { name: 'SYNTAX', label: 'Syntax' },
  { name: 'LINT', label: 'Lint' },
  { name: 'REPRO_TEST', label: 'Reproduction Test' },
  { name: 'REGRESSION', label: 'Full Regression' },
  { name: 'DIFF_AUDIT', label: 'Diff Audit' },
  { name: 'SIDE_EFFECT', label: 'Side Effect' },
];
