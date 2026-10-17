/**
 * useScreener – Custom React hook for fetching and managing screener signal data.
 * Automatically re-fetches when filters change (debounced search handled at FilterBar level).
 */

import { useState, useEffect, useCallback } from 'react';
import { fetchScreenerLatest } from '../api/screenerApi.ts';
import type { ScreenerSignal, ScreenerFilters } from '../types/index.ts';

interface UseScreenerResult {
  signals: ScreenerSignal[];
  loading: boolean;
  error: string | null;
  total: number;
  totalPages: number;
  scanDate: string;
  marketRegime: string | null;
  refetch: () => void;
}

/**
 * Fetches screener signals from the API whenever filters change.
 *
 * @param filters - Sorting, filtering, and pagination params
 */
export function useScreenerData(filters: ScreenerFilters): UseScreenerResult {
  const [signals, setSignals] = useState<ScreenerSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [scanDate, setScanDate] = useState('');
  const [marketRegime, setMarketRegime] = useState<string | null>(null);
  const [fetchCount, setFetchCount] = useState(0);

  const refetch = useCallback(() => {
    setFetchCount((c) => c + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchScreenerLatest(filters);
        if (!cancelled) {
          setSignals(data.signals);
          setTotal(data.total);
          setTotalPages(data.total_pages);
          const cleanScanDate = data.scan_date ? (data.scan_date.includes('T') ? data.scan_date.split('T')[0] : data.scan_date) : '';
          setScanDate(cleanScanDate);
          setMarketRegime(data.market_regime ?? null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load screener data');
          setSignals([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    load();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    filters.date,
    filters.sector,
    filters.status,
    filters.search,
    filters.sort_by,
    filters.order,
    filters.page,
    filters.limit,
    fetchCount,
  ]);

  return { signals, loading, error, total, totalPages, scanDate, marketRegime, refetch };
}
