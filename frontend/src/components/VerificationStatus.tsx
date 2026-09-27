import React from 'react';
import type { PhaseStatus } from '../types/verification';
import { VERIFICATION_PHASES_META } from '../types/verification';
import { VerificationStep } from './VerificationStep';

interface VerificationStatusProps {
  phases: Record<string, PhaseStatus>;
}

export const VerificationStatus: React.FC<VerificationStatusProps> = ({
  phases,
}) => {
  const isRunning = Object.values(phases).some((s) => s === 'running');
  const allPassed = Object.values(phases).length > 0 && Object.values(phases).every((s) => s === 'passed');
  const hasFailed = Object.values(phases).some((s) => s === 'failed');

  let headerIcon = <span style={{ color: 'var(--text-muted)' }}>◌</span>;
  let headerLabel = 'Running verification';

  if (allPassed) {
    headerIcon = <span style={{ color: 'var(--status-success)' }}>✓</span>;
    headerLabel = 'Verification passed';
  } else if (hasFailed) {
    headerIcon = <span style={{ color: 'var(--status-fail)' }}>✕</span>;
    headerLabel = 'Verification failed';
  } else if (isRunning) {
    headerIcon = <span className="animate-pulse-slow" style={{ color: 'var(--text-primary)' }}>◌</span>;
    headerLabel = 'Running verification';
  }

  return (
    <div style={{ marginTop: '16px', marginBottom: '8px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontFamily: 'var(--font-mono)',
          fontSize: '13px',
          fontWeight: 600,
          color: 'var(--text-primary)',
          marginBottom: '4px',
        }}
      >
        {headerIcon}
        <span>{headerLabel}</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {VERIFICATION_PHASES_META.map((phaseMeta, idx) => {
          const isLast = idx === VERIFICATION_PHASES_META.length - 1;
          const status = phases[phaseMeta.name] || 'pending';
          return (
            <VerificationStep
              key={phaseMeta.name}
              label={phaseMeta.label}
              status={status}
              prefixChar={isLast ? '└─' : '├─'}
            />
          );
        })}
      </div>
    </div>
  );
};
