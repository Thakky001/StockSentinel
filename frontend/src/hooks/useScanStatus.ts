/**
 * useScanStatus – Polling hook for screener scan job status.
 * Polls GET /api/screener/status every 5 seconds.
 * Automatically increases poll frequency when a scan is RUNNING.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchScreenerStatus, triggerScreener } from '../api/screenerApi.ts';
import type { ScanJob } from '../types/index.ts';

interface UseScanStatusResult {
  job: ScanJob | null;
  isRunning: boolean;
  triggerScan: () => Promise<void>;
  loading: boolean;
  error: string | null;
}

const POLL_INTERVAL_IDLE = 5000;   // 5 seconds when idle
const POLL_INTERVAL_RUNNING = 2000; // 2 seconds when scan is active

/**
 * Polls the scan status endpoint and exposes a trigger function.
 * Adapts polling frequency based on whether a scan is currently running.
 */
export function useScanStatus(): UseScanStatusResult {
  const [job, setJob] = useState<ScanJob | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isRunning = job?.status === 'RUNNING' || job?.status === 'PENDING';

  const poll = useCallback(async () => {
    try {
      const status = await fetchScreenerStatus();
      setJob(status);
      setError(null);
    } catch (err) {
      // Non-fatal – don't surface polling errors aggressively
      console.warn('Scan status poll failed:', err);
    }
  }, []);

  // Adjust polling interval based on current scan state
  useEffect(() => {
    // Initial fetch
    poll();

    const interval = isRunning ? POLL_INTERVAL_RUNNING : POLL_INTERVAL_IDLE;

    intervalRef.current = setInterval(poll, interval);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [poll, isRunning]);

  const triggerScan = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await triggerScreener();
      // Immediately poll to get the new RUNNING status
      await poll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to trigger scan');
    } finally {
      setLoading(false);
    }
  }, [poll]);

  return { job, isRunning, triggerScan, loading, error };
}
