/**
 * TypeScript interface definitions for StockSentinel backend.
 *
 * All interfaces are derived from the PostgreSQL schema defined in db/init.sql
 * and the API contracts documented in PROJECT.md.
 *
 * Column name mapping notes (schema → TypeScript):
 * - screener_signals.weekly_close  ← used as close_price in API responses
 * - screener_signals.entry_status  ← used as status in chart metrics
 * - screener_signals.current_price ← the latest price at scan time
 */

// ---------------------------------------------------------------------------
// Database Row Types (match init.sql column names exactly)
// ---------------------------------------------------------------------------

/** Matches the `stocks` table */
export interface StockInfo {
  ticker: string;
  name: string;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  is_active: boolean;
  in_russell3000: boolean;
  in_sp1500: boolean;
  created_at: string;
  updated_at: string;
}

/** Matches the `scan_jobs` table */
export interface ScanJob {
  id: number;
  job_type: string;
  /** PENDING | RUNNING | COMPLETED | FAILED */
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  started_at: string;
  completed_at: string | null;
  tickers_total: number;
  tickers_processed: number;
  tickers_failed: number;
  signals_found: number;
  error_message: string | null;
  telegram_alert_sent: boolean;
  created_at: string;
}

/** Matches the `screener_signals` table */
export interface ScreenerSignal {
  id: number;
  scan_id: number | null;
  scan_date: string;
  ticker: string;

  // Price / Pivot fields
  entry_price: number;
  max_buy_price: number;
  current_price: number;
  close_price?: number;
  stop_loss_price: number;
  diff_pct: number;

  /** IN_BUY_ZONE | EXTENDED | BELOW_ENTRY | STOPPED_OUT */
  entry_status: 'IN_BUY_ZONE' | 'EXTENDED' | 'BELOW_ENTRY' | 'STOPPED_OUT';
  status?: 'IN_BUY_ZONE' | 'EXTENDED' | 'BELOW_ENTRY' | 'STOPPED_OUT';

  // Weinstein / Volume indicators
  volume_surge_ratio: number;
  mrs_score: number;
  sma_30w: number;
  sma_30w_slope: number;
  prior_resistance_35w: number;
  weekly_close: number;
  weekly_volume: number;
  avg_volume_10w: number;
  stage: string;

  created_at: string;

  // Joined from stocks table (may be null if stock row missing)
  name?: string | null;
  sector?: string | null;
  industry?: string | null;
  market_cap?: number | null;
}

/** Matches one row from the `stock_daily_bars` table */
export interface DailyBar {
  ticker: string;
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  adj_close: number;
  volume: number;
}

// ---------------------------------------------------------------------------
// API Response Types (as specified in PROJECT.md §3 Interface Contracts)
// ---------------------------------------------------------------------------

/**
 * Candlestick bar formatted for TradingView Lightweight Charts.
 * `time` is an ISO-8601 date string (YYYY-MM-DD).
 */
export interface CandlestickBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

/** Single-value series point (SMA line, etc.) */
export interface SeriesPoint {
  time: string;
  value: number;
}

/** Volume histogram bar including colour coding */
export interface VolumeBar {
  time: string;
  value: number;
  /** Green when close >= open (up bar), red otherwise (down bar) */
  color: string;
}

/** Key price-level metrics used to draw price lines on the chart */
export interface ChartMetrics {
  entry_price: number;
  max_buy_price: number;
  stop_loss_price: number;
  /** entry_status from screener_signals */
  status: string;
  /** weekly_close from the latest screener signal */
  close_price: number;
}

/**
 * Full chart payload returned by GET /api/stock/:ticker/chart.
 * All arrays are sorted by ascending `time`.
 */
export interface ChartData {
  ticker: string;
  company_name: string;
  candlesticks: CandlestickBar[];
  /** 30-week SMA — null values are omitted (only points where sma30 IS NOT NULL) */
  sma30: SeriesPoint[];
  volume: VolumeBar[];
  metrics: ChartMetrics;
}

// ---------------------------------------------------------------------------
// Generic API Envelope
// ---------------------------------------------------------------------------

/** Standard error payload included in non-2xx responses */
export interface ApiError {
  code: string;
  message: string;
  /** Optional extra fields (e.g. job_id on 409 Conflict) */
  [key: string]: unknown;
}

/**
 * Generic API response envelope used by all endpoints.
 * On success: { success: true, data: T }
 * On failure: { success: false, error: ApiError }
 */
export type ApiResponse<T> =
  | { success: true; data: T }
  | { success: false; error: ApiError };

// ---------------------------------------------------------------------------
// Paginated Screener List Response
// ---------------------------------------------------------------------------
export interface ScreenerListData {
  scan_date: string;
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  signals: ScreenerSignal[];
}

// ---------------------------------------------------------------------------
// Stock Summary Response
// ---------------------------------------------------------------------------
export interface StockSummaryData {
  ticker: string;
  name: string;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
  exchange: string | null;
  latest_signal: ScreenerSignal | null;
  latest_daily_bar: DailyBar | null;
}
