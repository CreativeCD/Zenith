import { useState, useEffect, useRef, useCallback } from 'react';
import type { TelemetryEvent } from '../types/events';
import type { HarnessState, HarnessStatus } from '../types/agent';
import type { PhaseStatus } from '../types/verification';

export function useAgentStream() {
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [harnessState, setHarnessState] = useState<HarnessState>({
    status: 'READY',
    repo_path: '~/projects/Zenith',
    repo_name: 'Zenith',
    git_branch: 'main',
    active_issue: '',
    current_step: 0,
    current_phase: 'INIT',
    verification: {
      SYNTAX: 'pending',
      LINT: 'pending',
      REPRO_TEST: 'pending',
      REGRESSION: 'pending',
      DIFF_AUDIT: 'pending',
      SIDE_EFFECT: 'pending',
    },
    stats: {
      tokens_in: 0,
      tokens_out: 0,
      tokens_cumulative: 0,
      cost_usd: 0,
      cost_cumulative_usd: 0,
      elapsed_seconds: 0,
    },
  });

  const eventSourceRef = useRef<EventSource | null>(null);

  // Sync latest status from server
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        setHarnessState((prev) => ({
          ...prev,
          status: data.status as HarnessStatus,
          repo_path: data.repo_path || prev.repo_path,
          repo_name: data.repo_name || prev.repo_name,
          git_branch: data.git_branch || prev.git_branch,
          active_issue: data.active_issue || prev.active_issue,
          current_step: data.current_step ?? prev.current_step,
          current_phase: data.current_phase || prev.current_phase,
          verification: {
            ...prev.verification,
            ...(data.verification || {}),
          },
          stats: data.stats || prev.stats,
        }));
      }
    } catch {
      // Server may be booting or offline
    }
  }, []);

  useEffect(() => {
    fetchStatus();

    // Setup Server-Sent Events stream
    const es = new EventSource('/api/events');
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const parsed: TelemetryEvent = JSON.parse(event.data);
        setEvents((prev) => {
          // Avoid duplicate event ids if re-sent
          if (parsed.event_id && prev.some((e) => e.event_id === parsed.event_id)) {
            return prev;
          }
          return [...prev, parsed];
        });

        // Update harness state based on event
        setHarnessState((prev) => {
          const nextState = { ...prev };

          if (parsed.step !== undefined) {
            nextState.current_step = parsed.step;
          }
          if (parsed.phase) {
            nextState.current_phase = parsed.phase;
          }
          if (parsed.tokens_cumulative !== undefined) {
            nextState.stats.tokens_cumulative = parsed.tokens_cumulative;
          }
          if (parsed.cost_cumulative_usd !== undefined) {
            nextState.stats.cost_cumulative_usd = parsed.cost_cumulative_usd;
          }

          if (parsed.event_type === 'SESSION_START') {
            nextState.status = 'RUNNING';
          } else if (parsed.event_type === 'DONE') {
            nextState.status = 'VERIFIED';
          } else if (parsed.event_type === 'FAILED') {
            nextState.status = 'FAILED';
          }

          // Handle verification phase events
          if (parsed.event_type === 'VERIFICATION_PHASE' && parsed.phase) {
            const phaseName = parsed.phase;
            const resStatus = parsed.result_status;
            let status: PhaseStatus = 'running';
            if (resStatus === 'SUCCESS') status = 'passed';
            else if (resStatus === 'FAIL' || resStatus === 'BLOCKED' || resStatus === 'TIMEOUT') status = 'failed';
            else if (resStatus === 'RUNNING') status = 'running';

            nextState.verification = {
              ...nextState.verification,
              [phaseName]: status,
            };
          }

          return nextState;
        });
      } catch (err) {
        console.error('Error parsing SSE event:', err);
      }
    };

    es.onerror = () => {
      // Reconnect handled automatically by EventSource browser standard
    };

    return () => {
      es.close();
    };
  }, [fetchStatus]);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  return {
    events,
    harnessState,
    setHarnessState,
    fetchStatus,
    clearEvents,
  };
}
