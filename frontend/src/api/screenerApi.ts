/**
 * Typed API functions for all StockSentinel backend endpoints.
 * Each function maps to a specific REST route defined in PROJECT.md § Interface Contracts.
 */

import apiFetch from './client.ts';
import type {
  ScreenerLatestResponse,
  ScanJob,
  ChartData,
  ScreenerFilters,
} from '../types/index.ts';

// ---------------------------------------------------------------------------
// Screener endpoints
// ---------------------------------------------------------------------------

/**
 * Fetch the latest screener signals with optional filtering, sorting, and pagination.
 * Maps to: GET /api/screener/latest
 */
export async function fetchScreenerLatest(
  params: ScreenerFilters = {}
): Promise<ScreenerLatestResponse> {
  const query = new URLSearchParams();
  if (params.date) query.set('date', params.date);
  if (params.sector) query.set('sector', params.sector);
  if (params.status) query.set('status', params.status);
  if (params.search) query.set('search', params.search);
  if (params.sort_by) query.set('sort_by', params.sort_by);
  if (params.order) query.set('order', params.order);
  if (params.page !== undefined) query.set('page', String(params.page));
  if (params.limit !== undefined) query.set('limit', String(params.limit));

  const qs = query.toString();
  return apiFetch<ScreenerLatestResponse>(`/screener/latest${qs ? `?${qs}` : ''}`);
}

/**
 * Fetch all available scan dates (descending).
 * Maps to: GET /api/screener/dates
 */
export async function fetchScreenerDates(): Promise<string[]> {
  const data = await apiFetch<{ dates: string[] }>('/screener/dates');
  return data.dates;
}

/**
 * Fetch the latest scan job status for polling.
 * Maps to: GET /api/screener/status
 */
export async function fetchScreenerStatus(): Promise<ScanJob | null> {
  return apiFetch<ScanJob | null>('/screener/status');
}

/**
 * Trigger a new screener scan run.
 * Will return 409 Conflict if a scan is already running.
 * Maps to: POST /api/screener/trigger
 */
export async function triggerScreener(): Promise<{ job_id: number; status: string; message: string }> {
  return apiFetch<{ job_id: number; status: string; message: string }>('/screener/trigger', {
    method: 'POST',
  });
}

// ---------------------------------------------------------------------------
// Stock endpoints
// ---------------------------------------------------------------------------

/**
 * Fetch OHLCV + SMA30 chart data for a given ticker.
 * Maps to: GET /api/stock/:ticker/chart?weeks=N
 *
 * @param ticker - Stock ticker symbol (e.g., 'AAPL')
 * @param weeks - Number of weeks of history to return (default: 52)
 */
export async function fetchStockChart(ticker: string, weeks = 52): Promise<ChartData> {
  return apiFetch<ChartData>(`/stock/${encodeURIComponent(ticker)}/chart?weeks=${weeks}`);
}

/**
 * Fetch summary info for a stock (sector, market cap, latest signal, latest daily bar).
 * Maps to: GET /api/stock/:ticker/summary
 */
export async function fetchStockSummary(ticker: string): Promise<unknown> {
  return apiFetch<unknown>(`/stock/${encodeURIComponent(ticker)}/summary`);
}

// ---------------------------------------------------------------------------
// Notification endpoints
// ---------------------------------------------------------------------------

/**
 * Send a test Telegram notification to verify bot credentials.
 * Maps to: POST /api/notifications/telegram-test
 */
export async function sendTelegramTest(): Promise<{ message: string; telegram_message_id?: number }> {
  return apiFetch<{ message: string; telegram_message_id?: number }>('/notifications/telegram-test', {
    method: 'POST',
  });
}
