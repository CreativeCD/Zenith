import React from 'react';
import type { HarnessStatus } from '../types/agent';

interface RepositoryContextProps {
  status: HarnessStatus;
  verificationEnabled?: boolean;
}

export const RepositoryContext: React.FC<RepositoryContextProps> = ({
  status,
  verificationEnabled = true,
}) => {
  return (
    <div
      style={{
        position: 'absolute',
        bottom: '84px',
        right: '28px',
        fontFamily: 'var(--font-mono)',
        fontSize: '11px',
        lineHeight: '18px',
        color: 'var(--text-muted)',
        textAlign: 'right',
        userSelect: 'none',
        pointerEvents: 'none',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }}>
        <span
          style={{
            fontSize: '8px',
            color:
              status === 'VERIFIED'
                ? 'var(--status-success)'
                : status === 'RUNNING'
                ? 'var(--text-primary)'
                : 'var(--status-ready)',
          }}
        >
          ●
        </span>
        <span style={{ letterSpacing: '0.05em', fontWeight: 500 }}>{status}</span>
      </div>
      {verificationEnabled && (
        <div style={{ color: 'var(--text-muted)', opacity: 0.7 }}>
          verification enabled
        </div>
      )}
    </div>
  );
};
