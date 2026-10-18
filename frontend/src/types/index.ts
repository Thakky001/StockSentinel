/**
 * TypeScript interface definitions for StockSentinel.
 * These types are aligned with the backend API contract defined in PROJECT.md.
 */

export type StatusType =
  | 'IN_BUY_ZONE'
  | 'EXTENDED'
  | 'PROFIT_RUN'
  | 'TRAILING_WARNING'
  | 'BELOW_ENTRY'
  | 'STOPPED_OUT';

export type MarketRegime = 'BULL_MARKET' | 'CAUTION_MARKET' | 'BEAR_MARKET';

export interface ScoreBreakdown {
  mrs_pts: number;
  vol_pts: number;
  entry_pts: number;
  tightness_pts: number;
  closing_range_pct: number;
  penalty_pts: number;
  penalty_reasons: string[];
}

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
  current_price?: number;
  entry_price: number;
  max_buy_price: number;
  stop_loss_price: number;
  diff_pct: number;
  status: StatusType;
  entry_status?: StatusType;
  volume_surge_ratio: number;
  mrs_score: number;
  sma_30w: number;
  sma_30w_slope: number;
  prior_resistance_35w: number;

  // V2 & V2.1 Mathematical Enhancements
  quality_score?: number | null;
  quality_grade?: string | null;
  initial_breakout_score?: number | null;
  current_action_score?: number | null;
  score_badge?: string | null;
  score_breakdown?: ScoreBreakdown | null;
  sma_10w?: number | null;
  base_tightness_pct?: number | null;
  atr_14w?: number | null;
  market_regime?: MarketRegime | string | null;
  recommended_shares?: number | null;
  risk_per_share?: number | null;
  active_stop_loss?: number | null;
  highest_price_since_entry?: number | null;
  peak_gain_pct?: number | null;
  current_gain_pct?: number | null;
  earnings_warning?: string | null;
  breakout_date?: string | null;
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
  market_regime?: MarketRegime | string | null;
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
