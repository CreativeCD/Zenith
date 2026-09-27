import { useState, useCallback } from 'react';
import type { DiffResponse } from '../types/agent';

export function useVerification() {
  const [isVerifying, setIsVerifying] = useState(false);
  const [diffData, setDiffData] = useState<DiffResponse | null>(null);
  const [isLoadingDiff, setIsLoadingDiff] = useState(false);

  const runVerification = useCallback(async (repo?: string) => {
    setIsVerifying(true);
    try {
      const res = await fetch('/api/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo }),
      });
      const data = await res.json();
      return data;
    } catch (err) {
      console.error('Error triggering verification gate:', err);
      return null;
    } finally {
      setIsVerifying(false);
    }
  }, []);

  const fetchDiff = useCallback(async () => {
    setIsLoadingDiff(true);
    try {
      const res = await fetch('/api/diff');
      if (res.ok) {
        const data: DiffResponse = await res.json();
        setDiffData(data);
        return data;
      }
    } catch (err) {
      console.error('Error fetching git diff:', err);
    } finally {
      setIsLoadingDiff(false);
    }
    return null;
  }, []);

  return {
    isVerifying,
    diffData,
    isLoadingDiff,
    runVerification,
    fetchDiff,
    setDiffData,
  };
}
