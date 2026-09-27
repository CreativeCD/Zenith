import React from 'react';
import type { TelemetryEvent } from '../types/events';

interface AgentEventProps {
  event: TelemetryEvent;
}

export const AgentEvent: React.FC<AgentEventProps> = ({ event }) => {
  const { event_type, reasoning, plan_steps, files_modified, error_code } = event;

  if (event_type === 'PLAN_EMIT') {
    return (
      <div style={{ margin: '14px 0 8px 0' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontFamily: 'var(--font-mono)',
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--text-primary)',
          }}
        >
          <span style={{ color: 'var(--status-success)' }}>✓</span>
          <span>Planning</span>
        </div>
        {reasoning && (
          <div
            style={{
              paddingLeft: '24px',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              color: 'var(--text-muted)',
              marginTop: '2px',
            }}
          >
            {reasoning}
          </div>
        )}
        {plan_steps && plan_steps.length > 0 && (
          <div style={{ paddingLeft: '24px', marginTop: '6px' }}>
            {plan_steps.map((s, idx) => (
              <div
                key={idx}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '12px',
                  color: 'var(--text-secondary)',
                  lineHeight: '20px',
                }}
              >
                <span style={{ color: 'var(--text-muted)' }}>{s.step}.</span> {s.description}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (event_type === 'RECOVERY_EVENT') {
    return (
      <div style={{ margin: '12px 0 8px 0' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontFamily: 'var(--font-mono)',
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--status-fail)',
          }}
        >
          <span>⚠️</span>
          <span>Recovery triggered: {error_code || 'Error detected'}</span>
        </div>
        {reasoning && (
          <div
            style={{
              paddingLeft: '24px',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              color: 'var(--text-muted)',
              marginTop: '2px',
            }}
          >
            {reasoning}
          </div>
        )}
      </div>
    );
  }

  if (event_type === 'DONE_CANDIDATE') {
    return (
      <div style={{ margin: '14px 0 8px 0' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontFamily: 'var(--font-mono)',
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--text-primary)',
          }}
        >
          <span style={{ color: 'var(--status-success)' }}>✓</span>
          <span>Candidate patch synthesized</span>
        </div>
        {files_modified && files_modified.length > 0 && (
          <div
            style={{
              paddingLeft: '24px',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              color: 'var(--text-secondary)',
              marginTop: '4px',
            }}
          >
            Modified: {files_modified.join(', ')}
          </div>
        )}
      </div>
    );
  }

  if (event_type === 'SESSION_START') {
    return (
      <div style={{ margin: '10px 0 6px 0' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontFamily: 'var(--font-mono)',
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--text-primary)',
          }}
        >
          <span style={{ color: 'var(--text-primary)', fontSize: '10px' }}>●</span>
          <span>Starting autonomous session</span>
        </div>
        {reasoning && (
          <div
            style={{
              paddingLeft: '20px',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              color: 'var(--text-muted)',
              marginTop: '2px',
            }}
          >
            {reasoning}
          </div>
        )}
      </div>
    );
  }

  if (event_type === 'CONVERSATIONAL') {
    return (
      <div style={{ margin: '14px 0', fontFamily: 'var(--font-sans)', fontSize: '15px', lineHeight: 1.6, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
        {reasoning}
      </div>
    );
  }

  if (event_type === 'DONE') {
    return (
      <div style={{ margin: '16px 0 10px 0', fontFamily: 'var(--font-mono)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 700, color: 'var(--status-success)' }}>
          <span>✓</span>
          <span>Verification complete</span>
        </div>
        {reasoning && (
          <div style={{ marginTop: '8px', fontSize: '13px', lineHeight: 1.6, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
            {reasoning}
          </div>
        )}
      </div>
    );
  }

  if (event_type === 'FAILED') {
    return (
      <div style={{ margin: '16px 0 10px 0', fontFamily: 'var(--font-mono)', padding: '10px 14px', backgroundColor: 'var(--diff-del-bg)', border: '1px solid var(--diff-del-border)', borderRadius: '4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 700, color: 'var(--status-fail)' }}>
          <span>✕</span>
          <span>Agent run failed</span>
        </div>
        {reasoning && (
          <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--text-primary)' }}>
            {reasoning}
          </div>
        )}
      </div>
    );
  }

  return null;
};
