/**
 * TypeScript interface definitions for StockSentinel.
 * These types are aligned with the backend API contract defined in PROJECT.md.
 */

/** A single screener signal returned from GET /api/screener/latest */
export interface ScreenerSignal {
  ticker: string;
  name: string;
  sector: string;
  industry: string;
  market_cap: number;
  scan_date: string;
  stage: string;
  close_price: number;
  entry_price: number;
  max_buy_price: number;
  stop_loss_price: number;
  diff_pct: number;
  status: 'IN_BUY_ZONE' | 'EXTENDED' | 'BELOW_ENTRY' | 'STOPPED_OUT';
  volume_surge_ratio: number;
  mrs_score: number;
  sma_30w: number;
  sma_30w_slope: number;
  prior_resistance_35w: number;
}

/** OHLCV candlestick data point for TradingView Lightweight Charts */
export interface CandlestickPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

/** Volume histogram bar for TradingView Lightweight Charts */
export interface VolumePoint {
  time: string;
  value: number;
  color: string;
}

/** 30-week SMA line data point */
export interface SmaPoint {
  time: string;
  value: number;
}

/** Key price metrics shown alongside the chart */
export interface ChartMetrics {
  entry_price: number;
  max_buy_price: number;
  stop_loss_price: number;
  status: string;
  close_price: number;
}

/** Full chart data response from GET /api/stock/:ticker/chart */
export interface ChartData {
  ticker: string;
  company_name: string;
  candlesticks: CandlestickPoint[];
  sma30: SmaPoint[];
  volume: VolumePoint[];
  metrics: ChartMetrics;
}

/** Paginated screener response from GET /api/screener/latest */
export interface ScreenerLatestResponse {
  scan_date: string;
  total: number;
  page: number;
  limit: number;
  total_pages: number;
  signals: ScreenerSignal[];
}

/** Scan job record from GET /api/screener/status */
export interface ScanJob {
  id: number;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED' | 'PENDING';
  started_at: string;
  completed_at: string | null;
  signals_found: number;
  error_message: string | null;
}

/** Watchlist item stored in localStorage */
export interface WatchlistItem {
  ticker: string;
  name: string;
  sector: string;
  addedAt: string;
  entry_price: number;
  current_price: number;
  status: ScreenerSignal['status'];
}

/** Filter parameters accepted by GET /api/screener/latest */
export interface ScreenerFilters {
  date?: string;
  sector?: string;
  status?: string;
  search?: string;
  sort_by?: string;
  order?: 'asc' | 'desc';
  page?: number;
  limit?: number;
}
