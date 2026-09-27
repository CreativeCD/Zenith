import React from 'react';
import type { HarnessState } from '../types/agent';

interface RunStatusProps {
  state: HarnessState;
}

export const RunStatus: React.FC<RunStatusProps> = ({ state }) => {
  const { stats, current_step, current_phase } = state;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '16px',
        fontFamily: 'var(--font-mono)',
        fontSize: '11px',
        color: 'var(--text-muted)',
        padding: '6px 12px',
        backgroundColor: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: '3px',
      }}
    >
      <span>Step: {current_step}</span>
      <span>Phase: {current_phase}</span>
      {stats.tokens_cumulative > 0 && (
        <span>Tokens: {stats.tokens_cumulative.toLocaleString()}</span>
      )}
      {stats.cost_cumulative_usd > 0 && (
        <span>Cost: ${stats.cost_cumulative_usd.toFixed(4)}</span>
      )}
    </div>
  );
};
