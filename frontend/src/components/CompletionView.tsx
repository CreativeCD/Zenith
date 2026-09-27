import React from 'react';
import type { PhaseStatus } from '../types/verification';
import { VERIFICATION_PHASES_META } from '../types/verification';

interface CompletionViewProps {
  isSuccess: boolean;
  issueTitle?: string;
  issueId?: string;
  phases?: Record<string, PhaseStatus>;
  finalResponse?: string;
  filesModified?: string[];
  failureDetail?: string;
  failedPhase?: string;
  affectedFile?: string;
  onViewDiff: () => void;
  onRunAgain: () => void;
  onInspectFailure?: () => void;
}

export const CompletionView: React.FC<CompletionViewProps> = ({
  isSuccess,
  issueTitle,
  phases,
  finalResponse,
  filesModified,
  failureDetail,
  failedPhase,
  affectedFile,
  onViewDiff,
  onRunAgain,
  onInspectFailure,
}) => {
  if (isSuccess) {
    return (
      <div
        style={{
          borderTop: '1px solid var(--border-subtle)',
          paddingTop: '20px',
          marginTop: '16px',
          fontFamily: 'var(--font-mono)',
        }}
      >
        <div
          style={{
            fontSize: '13px',
            fontWeight: 700,
            color: 'var(--status-success)',
            letterSpacing: '0.04em',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            marginBottom: '14px',
          }}
        >
          <span>✓</span>
          <span>Verification complete</span>
        </div>

        {issueTitle && (
          <div style={{ fontSize: '13px', color: 'var(--text-primary)', marginBottom: '14px' }}>
            {issueTitle}
          </div>
        )}

        {finalResponse && (
          <div
            style={{
              fontSize: '13px',
              lineHeight: '1.6',
              color: 'var(--text-primary)',
              marginBottom: '16px',
              whiteSpace: 'pre-wrap',
            }}
          >
            {finalResponse}
          </div>
        )}

        {filesModified && filesModified.length > 0 && (
          <div style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Changed:
            </div>
            {filesModified.map((f, i) => (
              <div key={i} style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                {f}
              </div>
            ))}
          </div>
        )}

        {phases && (
          <div style={{ marginBottom: '18px' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Verified:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
              {VERIFICATION_PHASES_META.map((pm) => (
                <div
                  key={pm.name}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    fontSize: '12px',
                    color: 'var(--text-secondary)',
                  }}
                >
                  <span>{pm.label}</span>
                  <span style={{ color: 'var(--status-success)' }}>✓</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={onViewDiff}
            style={{
              padding: '6px 14px',
              borderRadius: '3px',
              border: '1px solid var(--border-medium)',
              backgroundColor: 'var(--bg-surface-elevated)',
              color: 'var(--text-primary)',
              fontSize: '12px',
              fontWeight: 500,
              cursor: 'pointer',
              transition: 'background 0.15s ease',
            }}
          >
            View Diff
          </button>
          <button
            onClick={onRunAgain}
            style={{
              padding: '6px 14px',
              borderRadius: '3px',
              border: '1px solid var(--border-subtle)',
              backgroundColor: 'transparent',
              color: 'var(--text-secondary)',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            Run Again
          </button>
        </div>
      </div>
    );
  }

  // Failure State
  return (
    <div
      style={{
        borderTop: '1px solid var(--border-subtle)',
        paddingTop: '20px',
        marginTop: '16px',
        fontFamily: 'var(--font-mono)',
      }}
    >
      <div
        style={{
          fontSize: '14px',
          fontWeight: 700,
          color: 'var(--status-fail)',
          letterSpacing: '0.04em',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          marginBottom: '10px',
        }}
      >
        <span>✕</span>
        <span>VERIFICATION FAILED</span>
      </div>

      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
        Failed Phase: <span style={{ color: 'var(--status-fail)' }}>{failedPhase || 'Verification Gate'}</span>
      </div>

      {affectedFile && (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
          Affected File: <span style={{ color: 'var(--text-primary)' }}>{affectedFile}</span>
        </div>
      )}

      {failureDetail && (
        <div
          style={{
            margin: '10px 0 14px 0',
            padding: '10px 12px',
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '4px',
            fontSize: '11px',
            color: 'var(--text-secondary)',
            whiteSpace: 'pre-wrap',
            maxHeight: '160px',
            overflowY: 'auto',
          }}
        >
          {failureDetail}
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '16px' }}>
        {onInspectFailure && (
          <button
            onClick={onInspectFailure}
            style={{
              padding: '6px 14px',
              borderRadius: '3px',
              border: '1px solid var(--border-medium)',
              backgroundColor: 'var(--bg-surface-elevated)',
              color: 'var(--text-primary)',
              fontSize: '12px',
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            Inspect Failure
          </button>
        )}
        <button
          onClick={onRunAgain}
          style={{
            padding: '6px 14px',
            borderRadius: '3px',
            border: '1px solid var(--border-subtle)',
            backgroundColor: 'transparent',
            color: 'var(--text-primary)',
            fontSize: '12px',
            cursor: 'pointer',
          }}
        >
          Retry
        </button>
        <button
          onClick={onViewDiff}
          style={{
            padding: '6px 14px',
            borderRadius: '3px',
            border: '1px solid var(--border-subtle)',
            backgroundColor: 'transparent',
            color: 'var(--text-secondary)',
            fontSize: '12px',
            cursor: 'pointer',
          }}
        >
          View Diff
        </button>
      </div>
    </div>
  );
};
