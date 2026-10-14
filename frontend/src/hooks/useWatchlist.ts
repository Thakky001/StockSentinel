/**
 * useWatchlist – LocalStorage-backed watchlist hook with cross-tab sync.
 * Storage key: 'stocksentinel_watchlist_v1'
 */

import { useState, useEffect, useCallback } from 'react';
import type { WatchlistItem, ScreenerSignal } from '../types/index.ts';

const STORAGE_KEY = 'stocksentinel_watchlist_v1';

function readStorage(): WatchlistItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as WatchlistItem[]) : [];
  } catch {
    return [];
  }
}

function writeStorage(items: WatchlistItem[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

interface UseWatchlistResult {
  watchlist: WatchlistItem[];
  addToWatchlist: (signal: ScreenerSignal) => void;
  removeFromWatchlist: (ticker: string) => void;
  isWatchlisted: (ticker: string) => boolean;
  clearWatchlist: () => void;
}

/**
 * Manages a persistent watchlist in localStorage.
 * Syncs state across browser tabs via the 'storage' event.
 */
export function useWatchlist(): UseWatchlistResult {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>(readStorage);

  // Sync across tabs when another tab modifies localStorage
  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) {
        setWatchlist(readStorage());
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const addToWatchlist = useCallback((signal: ScreenerSignal) => {
    setWatchlist((prev) => {
      // Prevent duplicates
      if (prev.some((item) => item.ticker === signal.ticker)) return prev;
      const newItem: WatchlistItem = {
        ticker: signal.ticker,
        name: signal.name,
        sector: signal.sector,
        addedAt: new Date().toISOString(),
        entry_price: signal.entry_price,
        current_price: signal.close_price,
        status: signal.status,
      };
      const updated = [newItem, ...prev];
      writeStorage(updated);
      return updated;
    });
  }, []);

  const removeFromWatchlist = useCallback((ticker: string) => {
    setWatchlist((prev) => {
      const updated = prev.filter((item) => item.ticker !== ticker);
      writeStorage(updated);
      return updated;
    });
  }, []);

  const isWatchlisted = useCallback(
    (ticker: string) => watchlist.some((item) => item.ticker === ticker),
    [watchlist]
  );

  const clearWatchlist = useCallback(() => {
    writeStorage([]);
    setWatchlist([]);
  }, []);

  return { watchlist, addToWatchlist, removeFromWatchlist, isWatchlisted, clearWatchlist };
}
