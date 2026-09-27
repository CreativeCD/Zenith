import React, { useEffect, useRef } from 'react';
import type { TelemetryEvent } from '../types/events';
import type { PhaseStatus } from '../types/verification';
import { ToolEvent } from './ToolEvent';
import { VerificationStatus } from './VerificationStatus';

interface AgentStreamProps {
  events: TelemetryEvent[];
  verificationPhases: Record<string, PhaseStatus>;
  activeIssue?: string;
  currentStep?: number;
  isRunning?: boolean;
}

export const AgentStream: React.FC<AgentStreamProps> = ({
  events,
  verificationPhases,
  activeIssue = '',
  isRunning = false,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events, verificationPhases]);

  // Conversational response check
  const conversationalEvent = events.find((e) => e.event_type === 'CONVERSATIONAL');
  if (conversationalEvent) {
    return (
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '24px 32px',
          maxWidth: '920px',
          margin: '0 auto',
          width: '100%',
          fontFamily: 'var(--font-mono)',
        }}
      >
        <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '14px' }}>
          › {activeIssue || 'hi'}
        </div>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '13px',
            lineHeight: 1.6,
            color: 'var(--text-primary)',
            whiteSpace: 'pre-wrap',
            marginBottom: '20px',
          }}
        >
          {conversationalEvent.reasoning || conversationalEvent.final_response}
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>›</div>
        <div ref={bottomRef} style={{ height: '32px' }} />
      </div>
    );
  }

  // Extract edit tools vs test tools vs inspection tools
  const editTools = events.filter(
    (e) =>
      e.event_type === 'TOOL_CALL' &&
      ['apply_patch', 'write_file', 'git_rollback'].includes(e.tool || '')
  );

  const testTools = events.filter(
    (e) =>
      e.event_type === 'TOOL_CALL' &&
      ['run_test_suite', 'run_bash_sandboxed', 'run_tests'].includes(e.tool || '')
  );

  const inspectTools = events.filter(
    (e) =>
      e.event_type === 'TOOL_CALL' &&
      !['apply_patch', 'write_file', 'git_rollback', 'run_test_suite', 'run_bash_sandboxed', 'run_tests'].includes(
        e.tool || ''
      )
  );

  const hasPlan = events.some((e) => e.event_type === 'PLAN_EMIT');
  const hasRepoAnalysis = events.some((e) => e.event_type === 'REPO_ANALYSIS' || e.event_type === 'TOOL_CALL');
  const hasVerificationStarted = events.some(
    (e) => e.event_type === 'VERIFICATION_PHASE' || e.phase === 'DONE_CANDIDATE'
  );

  const doneEvent = events.find((e) => e.event_type === 'DONE');
  const failedEvent = events.find((e) => e.event_type === 'FAILED');

  const issueTitle = activeIssue ? activeIssue.split('\n')[0].replace(/^Title:\s*/i, '') : 'Autonomous Code Recovery';

  return (
    <div
      style={{
        flex: 1,
        overflowY: 'auto',
        padding: '24px 32px',
        maxWidth: '920px',
        margin: '0 auto',
        width: '100%',
        fontFamily: 'var(--font-mono)',
      }}
    >
      {/* Prompt line */}
      <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px' }}>
        › {issueTitle}
      </div>

      {/* Loading state before first events */}
      {isRunning && events.length === 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', margin: '16px 0' }}>
          <span className="terminal-spinner" />
          <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            Initializing autonomous recovery agent...
          </span>
        </div>
      )}

      {/* Planning step */}
      {hasPlan ? (
        <div style={{ margin: '8px 0', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 600 }}>
          <span style={{ color: 'var(--status-success)' }}>✓</span>
          <span style={{ color: 'var(--text-primary)' }}>Planning</span>
        </div>
      ) : isRunning && events.length > 0 ? (
        <div style={{ margin: '8px 0', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
          <span style={{ color: 'var(--status-running)' }} className="animate-pulse-slow">●</span>
          <span style={{ color: 'var(--text-muted)' }}>Planning...</span>
        </div>
      ) : null}

      {/* Repository analysis */}
      {hasRepoAnalysis && (
        <div style={{ margin: '8px 0', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 600 }}>
          <span style={{ color: 'var(--status-success)' }}>✓</span>
          <span style={{ color: 'var(--text-primary)' }}>Repository analysis</span>
        </div>
      )}

      {/* Inspecting repository tools */}
      {inspectTools.length > 0 && (
        <div style={{ margin: '16px 0 8px 0' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--text-primary)',
              marginBottom: '4px',
            }}
          >
            <span style={{ fontSize: '10px' }}>●</span>
            <span>Inspecting repository</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {inspectTools.map((evt, idx) => (
              <ToolEvent
                key={`inspect-${idx}`}
                event={evt}
                prefixChar={idx === inspectTools.length - 1 ? '└─' : '├─'}
              />
            ))}
          </div>
        </div>
      )}

      {/* Making changes / Patches */}
      {editTools.length > 0 && (
        <div style={{ margin: '16px 0 8px 0' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--text-primary)',
              marginBottom: '4px',
            }}
          >
            <span style={{ fontSize: '10px' }}>●</span>
            <span>Making changes</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {editTools.map((evt, idx) => (
              <ToolEvent
                key={`edit-${idx}`}
                event={evt}
                prefixChar={idx === editTools.length - 1 ? '└─' : '├─'}
              />
            ))}
          </div>
        </div>
      )}

      {/* Test Execution if any */}
      {testTools.length > 0 && (
        <div style={{ margin: '16px 0 8px 0' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--text-primary)',
              marginBottom: '4px',
            }}
          >
            <span style={{ fontSize: '10px' }}>●</span>
            <span>Executing test runner</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {testTools.map((evt, idx) => (
              <ToolEvent
                key={`test-${idx}`}
                event={evt}
                prefixChar={idx === testTools.length - 1 ? '└─' : '├─'}
              />
            ))}
          </div>
        </div>
      )}

      {/* 6-Phase Deterministic Verification Pipeline */}
      {hasVerificationStarted && (
        <VerificationStatus phases={verificationPhases} />
      )}

      {/* Final VERIFIED state */}
      {doneEvent && (
        <div style={{ marginTop: '20px', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '13px',
              fontWeight: 700,
              color: 'var(--status-success)',
              letterSpacing: '0.04em',
              marginBottom: '14px',
            }}
          >
            <span>✓</span>
            <span style={{ color: 'var(--text-primary)' }}>VERIFIED</span>
          </div>

          <div
            style={{
              fontSize: '13px',
              lineHeight: 1.6,
              color: 'var(--text-primary)',
              marginBottom: '16px',
              whiteSpace: 'pre-wrap',
            }}
          >
            {doneEvent.final_response || doneEvent.reasoning || 'Verification complete.'}
          </div>

          {doneEvent.files_modified && doneEvent.files_modified.length > 0 && (
            <div style={{ marginBottom: '16px' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                Changed:
              </div>
              {doneEvent.files_modified.map((f, i) => (
                <div key={i} style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  {f}
                </div>
              ))}
            </div>
          )}

          <div style={{ marginBottom: '18px' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Verified:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
              {['Syntax', 'Lint', 'Reproduction Test', 'Full Regression', 'Diff Audit', 'Side Effect'].map((name) => (
                <div key={name} style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '12px' }}>
                  <span style={{ width: '160px', color: 'var(--text-secondary)' }}>{name}</span>
                  <span style={{ color: 'var(--status-success)' }}>✓</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '16px' }}>
            ›
          </div>
        </div>
      )}

      {/* Final FAILED state */}
      {failedEvent && (
        <div style={{ marginTop: '20px', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '13px',
              fontWeight: 700,
              color: 'var(--status-fail)',
              marginBottom: '12px',
            }}
          >
            <span>✕</span>
            <span style={{ color: 'var(--text-primary)' }}>FAILED</span>
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '16px' }}>
            {failedEvent.reasoning || 'Verification gate failed.'}
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '16px' }}>
            ›
          </div>
        </div>
      )}

      <div ref={bottomRef} style={{ height: '32px' }} />
    </div>
  );
};
