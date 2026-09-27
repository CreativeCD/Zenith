import React from 'react';
import type { PhaseStatus } from '../types/verification';

interface VerificationStepProps {
  label: string;
  status: PhaseStatus;
  prefixChar?: string;
  durationMs?: number;
}

export const VerificationStep: React.FC<VerificationStepProps> = ({
  label,
  status,
  prefixChar = '├─',
  durationMs,
}) => {
  const renderStatusIndicator = () => {
    switch (status) {
      case 'passed':
        return <span style={{ color: 'var(--status-success)' }}>✓</span>;
      case 'running':
        return <span style={{ color: 'var(--text-primary)' }} className="animate-pulse-slow">◌</span>;
      case 'failed':
        return <span style={{ color: 'var(--status-fail)' }}>✕</span>;
      case 'skipped':
      case 'pending':
      default:
        return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    }
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        justifyContent: 'space-between',
        paddingLeft: '16px',
        lineHeight: '22px',
        fontFamily: 'var(--font-mono)',
        fontSize: '12px',
        maxWidth: '420px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
        <span style={{ color: 'var(--text-muted)', userSelect: 'none' }}>{prefixChar}</span>
        <span style={{ color: status === 'pending' ? 'var(--text-muted)' : 'var(--text-primary)' }}>
          {label}
        </span>
        {durationMs !== undefined && durationMs > 0 && (
          <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>
            {durationMs}ms
          </span>
        )}
      </div>

      <div style={{ paddingRight: '8px' }}>
        {renderStatusIndicator()}
      </div>
    </div>
  );
};
