import React from 'react';
import type { HarnessStatus } from '../types/agent';

interface ZenithHeaderProps {
  repoPath: string;
  gitBranch?: string;
  status: HarnessStatus;
  currentStep?: number;
  activeIssueId?: string;
  onOpenCommandPalette: () => void;
  onToggleDiff: () => void;
  hasDiff?: boolean;
}

export const ZenithHeader: React.FC<ZenithHeaderProps> = ({
  repoPath,
  gitBranch = 'main',
  status,
  currentStep = 0,
  activeIssueId,
  onOpenCommandPalette,
  onToggleDiff,
  hasDiff = false,
}) => {
  // Format repo path display (e.g. ~/projects/my-repo)
  const displayPath = repoPath.replace(/^\/Users\/[^/]+/, '~');

  const renderStatus = () => {
    switch (status) {
      case 'RUNNING':
        return (
          <span style={{ color: 'var(--text-primary)', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ color: 'var(--text-primary)', fontSize: '10px' }}>●</span>
            <span style={{ fontWeight: 600, letterSpacing: '0.04em' }}>RUNNING</span>
            {activeIssueId && <span style={{ color: 'var(--text-muted)', marginLeft: '4px' }}>issue #{activeIssueId}</span>}
            {currentStep > 0 && <span style={{ color: 'var(--text-muted)' }}>[S{currentStep}]</span>}
          </span>
        );
      case 'VERIFIED':
        return (
          <span style={{ color: 'var(--status-success)', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            <span>✓</span>
            <span style={{ fontWeight: 600, letterSpacing: '0.04em' }}>VERIFIED</span>
          </span>
        );
      case 'FAILED':
        return (
          <span style={{ color: 'var(--status-fail)', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            <span>✕</span>
            <span style={{ fontWeight: 600, letterSpacing: '0.04em' }}>FAILED</span>
          </span>
        );
      case 'READY':
      default:
        return (
          <span style={{ color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ fontSize: '10px' }}>●</span>
            <span style={{ letterSpacing: '0.04em' }}>READY</span>
          </span>
        );
    }
  };

  return (
    <header
      style={{
        padding: '14px 24px',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        backgroundColor: 'var(--bg-primary)',
        userSelect: 'none',
        zIndex: 10,
      }}
    >
      <div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
          <h1
            style={{
              fontSize: '13px',
              fontWeight: 700,
              letterSpacing: '0.12em',
              color: 'var(--text-primary)',
              textTransform: 'uppercase',
              margin: 0,
            }}
          >
            ZENITH
          </h1>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Autonomous Code Verification & Recovery
          </span>
        </div>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--text-muted)',
            marginTop: '3px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span>{displayPath}</span>
          <span style={{ opacity: 0.4 }}>•</span>
          <span style={{ color: 'var(--text-secondary)' }}>git:{gitBranch}</span>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <button
          onClick={onToggleDiff}
          title="Toggle Git Diff Viewer"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: hasDiff ? 'var(--text-primary)' : 'var(--text-muted)',
            padding: '3px 8px',
            borderRadius: '3px',
            border: '1px solid var(--border-subtle)',
            backgroundColor: hasDiff ? 'var(--bg-surface-elevated)' : 'transparent',
            cursor: 'pointer',
            transition: 'all 0.15s ease',
          }}
        >
          diff {hasDiff && '●'}
        </button>

        <button
          onClick={onOpenCommandPalette}
          title="Command Palette (Cmd+K)"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--text-muted)',
            padding: '3px 8px',
            borderRadius: '3px',
            border: '1px solid var(--border-subtle)',
            backgroundColor: 'var(--bg-surface)',
            cursor: 'pointer',
          }}
        >
          ⌘K
        </button>

        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
          {renderStatus()}
        </div>
      </div>
    </header>
  );
};
