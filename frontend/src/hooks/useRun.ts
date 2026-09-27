import { useState, useCallback } from 'react';

interface StartRunOptions {
  issue?: string;
  repo?: string;
  agent_mode?: string;
  dry_run?: boolean;
  dev_demo?: boolean;
  model?: string;
}

export function useRun(onStarted?: () => void) {
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startRun = useCallback(
    async (options: StartRunOptions = {}) => {
      setIsRunning(true);
      setError(null);
      try {
        const res = await fetch('/api/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(options),
        });

        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || `Run failed: ${res.statusText}`);
        }

        onStarted?.();
        return true;
      } catch (err: any) {
        setError(err.message || 'Failed to start agent run');
        setIsRunning(false);
        return false;
      }
    },
    [onStarted]
  );

  const stopRun = useCallback(async () => {
    try {
      await fetch('/api/stop', { method: 'POST' });
      setIsRunning(false);
    } catch (err: any) {
      setError(err.message || 'Failed to stop agent run');
    }
  }, []);

  return {
    isRunning,
    error,
    startRun,
    stopRun,
    setError,
  };
}
