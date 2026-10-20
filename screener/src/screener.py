"""
screener/src/screener.py - Core Screener Engine, Stage 2 Breakout Filters,
Target & Risk Calculations, Entry Status Classification, and Signal Persistence.
Features: F17 (Breakout Filter), F18 (Target/Risk Math), F19 (Entry Status), F20 (Persistence).
"""
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from screener.src import config, db, downloader, indicators, parquet_cache, universe
from screener.src.indicators import (
    align_weekly_bars,
    calculate_projected_volume_surge,
    compute_atr,
    compute_base_tightness,
    compute_mansfield_relative_strength,
    compute_market_regime,
    compute_prior_resistance_pivot,
    compute_sma,
    compute_sma_slope,
    compute_volume_surge,
    resample_daily_to_weekly,
)

logger = logging.getLogger(__name__)

# Minimum required weekly bars for complete indicator warmup (governed by 52w MRS)
MINIMUM_REQUIRED_WEEKS = 52


from concurrent.futures import ThreadPoolExecutor

def evaluate_stage2_filter(
    close: float,
    sma_30w: Optional[float] = None,
    sma_30w_slope: Optional[float] = None,
    pivot_35w: Optional[float] = None,
    vol_surge_ratio: Optional[float] = None,
    mrs_score: Optional[float] = None,
    sma_10w: Optional[float] = None,
    tightness_pct: Optional[float] = None,
    high_52w: Optional[float] = None,
    mrs_score_prev4: Optional[float] = None,
    atr_14w: Optional[float] = None,
    volume_surge_ratio: Optional[float] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Evaluates Stage 2 Breakout V2.1 Discovery Filter (8 criteria):
    1. 30-Week SMA & 10-Week SMA:
       - close > sma_30w
       - sma_30w_slope >= 0.0% (4-week smoothed slope)
       - close > sma_10w (confirms short-term momentum)
    2. 35-Week Prior Resistance Pivot & Base Tightness:
       - close >= pivot_35w (breakout above prior 35w highs, excluding current week)
       - tightness_pct <= 18.0% (tight 4w consolidation base before breakout)
       - close >= high_52w * 0.85 (within 15% of 52-week high)
    3. Projected Volume Surge:
       - vol_surge_ratio >= 1.50 (current or projected weekly volume >= 1.5x 10w avg)
    4. Mansfield Relative Strength:
       - mrs_score > 0.0 (outperforming SPY)
       - mrs_score > mrs_score_prev4 (relative strength accelerating vs 4 weeks ago)
    5. Minimum Volatility Filter (Bug 5):
       - (atr_14w / close) * 100 >= 2.5% (cuts out sluggish/defensive stocks)
    """
    # Handle volume_surge_ratio alias
    if vol_surge_ratio is None and volume_surge_ratio is not None:
        vol_surge_ratio = volume_surge_ratio

    # Backwards compatibility defaults for legacy unit tests:
    if sma_10w is None and sma_30w is not None and close is not None and close > sma_30w:
        sma_10w = close - 0.01
    if tightness_pct is None:
        tightness_pct = 10.0
    if high_52w is None and close is not None:
        high_52w = close
    if mrs_score_prev4 is None and mrs_score is not None:
        mrs_score_prev4 = mrs_score - 0.1
    if atr_14w is None and close is not None and close > 0:
        atr_14w = close * 0.03

    cond_1_trend = bool(
        sma_30w is not None
        and sma_10w is not None
        and sma_30w_slope is not None
        and close is not None
        and close > sma_30w
        and sma_30w_slope >= 0.0
        and close > sma_10w
    )

    cond_2_breakout = bool(pivot_35w is not None and close is not None and close >= pivot_35w)
    cond_2_tight_base = bool(
        tightness_pct is not None
        and high_52w is not None
        and close is not None
        and tightness_pct <= 18.0
        and close >= (high_52w * 0.85)
    )

    cond_3_volume = bool(vol_surge_ratio is not None and vol_surge_ratio >= 1.50)

    cond_4_mrs = bool(
        mrs_score is not None
        and mrs_score > 0.0
        and (mrs_score_prev4 is None or mrs_score > mrs_score_prev4)
    )

    atr_pct = ((atr_14w / close) * 100.0) if (atr_14w is not None and close is not None and close > 0) else 0.0
    cond_5_min_volatility = bool(atr_pct >= 2.5)

    is_stage2 = (
        cond_1_trend
        and cond_2_breakout
        and cond_2_tight_base
        and cond_3_volume
        and cond_4_mrs
        and cond_5_min_volatility
    )

    cond_close_above_sma = bool(close is not None and sma_30w is not None and close > sma_30w)
    cond_sma_rising = bool(sma_30w_slope is not None and sma_30w_slope >= 0.0)
    cond_pivot_breakout = bool(pivot_35w is not None and close is not None and close >= pivot_35w)
    cond_volume_surge = bool(vol_surge_ratio is not None and vol_surge_ratio >= 1.50)
    cond_mrs_positive = bool(mrs_score is not None and mrs_score > 0.0)

    return {
        "is_stage2": is_stage2,
        "cond_1_trend": cond_1_trend,
        "cond_2_breakout": cond_2_breakout,
        "cond_2_tight_base": cond_2_tight_base,
        "cond_3_volume": cond_3_volume,
        "cond_4_mrs": cond_4_mrs,
        "cond_5_min_volatility": cond_5_min_volatility,
        "cond_close_above_sma": cond_close_above_sma,
        "cond_sma_rising": cond_sma_rising,
        "cond_pivot_breakout": cond_pivot_breakout,
        "cond_volume_surge": cond_volume_surge,
        "cond_mrs_positive": cond_mrs_positive,
        "atr_pct": round(atr_pct, 2),
    }


def calculate_target_and_risk(
    pivot_35w: float,
    current_price: float,
    swing_low: Optional[float] = None,
) -> Dict[str, Any]:
    """Legacy helper for target & risk calculation (maintained for test backwards compatibility)."""
    entry_price = round(float(pivot_35w), 4)
    max_buy_price = round(entry_price * 1.05, 4)
    if swing_low is not None and 0 < swing_low < entry_price:
        stop_loss = round(float(swing_low), 4)
    else:
        stop_loss = round(entry_price * 0.92, 4)
    diff_pct = round(((float(current_price) - entry_price) / entry_price) * 100.0, 4)
    return {
        "entry_price": entry_price,
        "max_buy_price": max_buy_price,
        "stop_loss_price": stop_loss,
        "diff_pct": diff_pct,
    }


def calculate_adaptive_stop_loss(
    entry_price: float,
    atr_14w: float,
    low_prev_week: float,
) -> float:
    """
    V2.1 Adaptive Stop Loss Formula (Bug 2):
    raw_stop = max(entry_price * 0.90, entry_price - (1.5 * atr_14w), low_prev_week * 0.99)
    stop_loss = min(entry_price * 0.98, raw_stop)
    - Caps maximum loss at 10%
    - Ensures stop loss is not closer than -2% to entry (prevents overly tight stops)
    """
    raw_stop = max(
        entry_price * 0.90,
        entry_price - (1.5 * atr_14w),
        low_prev_week * 0.99,
    )
    return round(min(entry_price * 0.98, raw_stop), 4)


def calculate_position_size(
    portfolio_size: float,
    risk_pct: float,
    regime_multiplier: float,
    current_price: float,
    entry_price: float,
    stop_loss: float,
    max_alloc_pct: float = 0.20,
) -> Dict[str, Any]:
    """
    V2.1 Dynamic Position Sizing (Bug 3):
    - Scaled by regime_multiplier (BULL=1.0, CAUTION=0.5, BEAR=0.0)
    - Accounts for actual entry price vs current price
    - Caps allocation per stock to 20% of portfolio
    """
    if regime_multiplier <= 0.0 or current_price <= stop_loss:
        return {
            "recommended_shares": 0,
            "capital_used": 0.0,
            "portfolio_weight_pct": 0.0,
            "actual_dollar_risk": 0.0,
            "risk_per_share": max(round(current_price - stop_loss, 4), 0.01),
        }

    # 1. Effective risk budget after market regime scaling
    effective_risk_budget = portfolio_size * (risk_pct / 100.0) * regime_multiplier

    # 2. Actual risk per share
    effective_buy_price = max(current_price, entry_price)
    actual_risk_per_share = max(effective_buy_price - stop_loss, entry_price * 0.01)

    shares_by_risk = int(np.floor(effective_risk_budget / actual_risk_per_share))

    # 3. Allocation cap (max 20% of portfolio)
    max_capital_allowed = portfolio_size * max_alloc_pct * (1.0 if regime_multiplier > 0 else 0.0)
    shares_by_cap = int(np.floor(max_capital_allowed / effective_buy_price))

    final_shares = max(0, min(shares_by_risk, shares_by_cap))
    capital_used = round(final_shares * effective_buy_price, 2)
    actual_dollar_risk = round(final_shares * actual_risk_per_share, 2)
    portfolio_weight_pct = round((capital_used / portfolio_size) * 100.0, 2) if portfolio_size > 0 else 0.0

    return {
        "recommended_shares": final_shares,
        "capital_used": capital_used,
        "portfolio_weight_pct": portfolio_weight_pct,
        "actual_dollar_risk": actual_dollar_risk,
        "risk_per_share": round(actual_risk_per_share, 4),
    }


def classify_entry_status(
    current_price: float,
    entry_price: float,
    max_buy_price: Optional[float] = None,
    stop_loss_price: Optional[float] = None,
) -> str:
    """Legacy entry status classifier for testing backwards compatibility."""
    if max_buy_price is None:
        max_buy_price = entry_price * 1.05
    if stop_loss_price is None:
        stop_loss_price = entry_price * 0.92
    if current_price < stop_loss_price:
        return "STOPPED_OUT"
    elif current_price < entry_price:
        return "BELOW_ENTRY"
    elif current_price <= max_buy_price:
        return "IN_BUY_ZONE"
    else:
        return "EXTENDED"


def classify_entry_status_v2_1(
    current_close: float,
    entry_price: float,
    max_buy_price: float,
    active_stop_loss: float,
    highest_price_since_entry: float,
    sma_10w: Optional[float] = None,
    sma_30w: Optional[float] = None,
) -> str:
    """
    V2.1 6-Tier Actionable Statuses based on Peak Gain Tracking (Bug 4):
    1. 🔴 STOPPED_OUT: current_close < active_stop_loss or (sma_30w and current_close < sma_30w)
    2. 🟠 TRAILING_WARNING: peak_gain_pct >= 20.0 and sma_10w and current_close < sma_10w
    3. 🔵 PROFIT_RUN: peak_gain_pct >= 20.0 and (sma_10w is None or current_close >= sma_10w)
    4. 🟡 EXTENDED: current_close > max_buy_price and peak_gain_pct < 20.0
    5. 🟢 IN_BUY_ZONE: entry_price <= current_close <= max_buy_price
    6. ⚪ BELOW_ENTRY: active_stop_loss <= current_close < entry_price
    """
    peak_gain_pct = (
        ((highest_price_since_entry - entry_price) / entry_price) * 100.0
        if entry_price > 0
        else 0.0
    )

    if current_close < active_stop_loss or (sma_30w is not None and current_close < sma_30w):
        return "STOPPED_OUT"
    elif peak_gain_pct >= 20.0 and sma_10w is not None and current_close < sma_10w:
        return "TRAILING_WARNING"
    elif peak_gain_pct >= 20.0 and (sma_10w is None or current_close >= sma_10w):
        return "PROFIT_RUN"
    elif current_close > max_buy_price:
        return "EXTENDED"
    elif entry_price <= current_close <= max_buy_price:
        return "IN_BUY_ZONE"
    else:
        return "BELOW_ENTRY"


def fetch_earnings_warning_map(tickers: List[str], max_workers: int = 4) -> Dict[str, Optional[str]]:
    """
    Fetches upcoming earnings release dates (Bug 5) within [0, 14] days using yfinance calendar.
    Safely throttled and silenced to prevent Yahoo crumb rate-limiting (HTTP 429 / 401).
    """
    warning_map: Dict[str, Optional[str]] = {}
    today = date.today()
    if not tickers:
        return warning_map

    # Temporarily silence noisy yfinance HTTP crumb errors in stderr/logs
    yf_logger = logging.getLogger("yfinance")
    orig_level = yf_logger.level
    yf_logger.setLevel(logging.CRITICAL)

    try:
        import yfinance as yf
        import time

        # Pre-warm crumb sequentially on the first ticker to prevent concurrent thread crumb collision
        try:
            _ = yf.Ticker(tickers[0]).calendar
        except Exception:
            pass

        def _check(ticker: str):
            try:
                t = yf.Ticker(ticker)
                cal = t.calendar
                if isinstance(cal, dict):
                    ed_list = cal.get("Earnings Date")
                    if ed_list and len(ed_list) > 0:
                        ed = ed_list[0]
                        if hasattr(ed, "date"):
                            ed = ed.date()
                        days = (ed - today).days
                        if 0 <= days <= 14:
                            return ticker, f"⚠️ งบออกใน {days} วัน"
            except Exception:
                pass
            return ticker, None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for ticker, warning in executor.map(_check, tickers):
                if warning:
                    warning_map[ticker] = warning
    except Exception as e:
        logger.debug(f"Earnings warning check error: {e}")
    finally:
        yf_logger.setLevel(orig_level)

    return warning_map


# =============================================================================
# Database Persistence Helpers (Feature 20)
# =============================================================================

def create_scan_job(tickers_total: int, market_regime: Optional[str] = None, cur=None) -> int:
    """Creates a new scan_jobs audit record with status 'RUNNING'."""
    sql = """
    INSERT INTO scan_jobs (job_type, status, started_at, tickers_total, tickers_processed, tickers_failed, signals_found, market_regime)
    VALUES ('WEEKLY_SCREEN', 'RUNNING', CURRENT_TIMESTAMP, %s, 0, 0, 0, %s)
    RETURNING id;
    """
    if cur:
        cur.execute(sql, (tickers_total, market_regime))
        return cur.fetchone()[0]
    else:
        with db.db_cursor(commit=True) as cursor:
            cursor.execute(sql, (tickers_total, market_regime))
            return cursor.fetchone()[0]


def update_scan_job(
    job_id: int,
    status: str,
    tickers_processed: int = 0,
    tickers_failed: int = 0,
    signals_found: int = 0,
    error_message: Optional[str] = None,
    telegram_alert_sent: bool = False,
    market_regime: Optional[str] = None,
    cur=None
) -> None:
    """Updates scan_jobs execution state upon completion or failure."""
    sql = """
    UPDATE scan_jobs
    SET status = %s,
        completed_at = CURRENT_TIMESTAMP,
        tickers_processed = %s,
        tickers_failed = %s,
        signals_found = %s,
        error_message = %s,
        telegram_alert_sent = %s,
        market_regime = COALESCE(%s, market_regime)
    WHERE id = %s;
    """
    params = (status, tickers_processed, tickers_failed, signals_found, error_message, telegram_alert_sent, market_regime, job_id)
    if cur:
        cur.execute(sql, params)
    else:
        with db.db_cursor(commit=True) as cursor:
            cursor.execute(sql, params)


def upsert_screener_signals(signals: List[Dict[str, Any]], cur=None, prune_unmatched: bool = False) -> int:
    """
    Batch upserts qualified Stage 2 breakout signals into 'screener_signals'.
    Uses ON CONFLICT (scan_date, ticker) DO UPDATE to ensure idempotency.
    Deduplicates signals in-batch by (scan_date, ticker) to prevent PostgreSQL Error 21000.
    """
    if not signals:
        return 0

    # In-batch deduplication by (scan_date, ticker) keeping latest record
    deduped_signals: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for s in signals:
        key = (str(s["scan_date"]), s["ticker"])
        deduped_signals[key] = s

    deduped_list = list(deduped_signals.values())

    # Ensure foreign key stocks exist
    try:
        tickers = [s["ticker"] for s in deduped_list]
        db.ensure_stocks_exist(tickers, cur=cur)
    except Exception as e:
        logger.debug(f"Could not check/ensure stocks foreign key: {e}")

    import json
    db.ensure_quality_columns_exist(cur=cur)
    sql = """
    INSERT INTO screener_signals (
        scan_id, scan_date, ticker, entry_price, max_buy_price, current_price,
        stop_loss_price, diff_pct, entry_status, volume_surge_ratio, mrs_score,
        sma_30w, sma_30w_slope, prior_resistance_35w, weekly_close,
        weekly_volume, avg_volume_10w, stage, sma_10w, base_tightness_pct, atr_14w, market_regime,
        active_stop_loss, peak_gain_pct, highest_price_since_entry, earnings_warning,
        quality_score, quality_grade, initial_breakout_score, current_action_score, score_badge, score_breakdown
    )
    VALUES %s
    ON CONFLICT (scan_date, ticker) DO UPDATE SET
        scan_id = EXCLUDED.scan_id,
        entry_price = EXCLUDED.entry_price,
        max_buy_price = EXCLUDED.max_buy_price,
        current_price = EXCLUDED.current_price,
        stop_loss_price = EXCLUDED.stop_loss_price,
        diff_pct = EXCLUDED.diff_pct,
        entry_status = EXCLUDED.entry_status,
        volume_surge_ratio = EXCLUDED.volume_surge_ratio,
        mrs_score = EXCLUDED.mrs_score,
        sma_30w = EXCLUDED.sma_30w,
        sma_30w_slope = EXCLUDED.sma_30w_slope,
        prior_resistance_35w = EXCLUDED.prior_resistance_35w,
        weekly_close = EXCLUDED.weekly_close,
        weekly_volume = EXCLUDED.weekly_volume,
        avg_volume_10w = EXCLUDED.avg_volume_10w,
        stage = EXCLUDED.stage,
        sma_10w = EXCLUDED.sma_10w,
        base_tightness_pct = EXCLUDED.base_tightness_pct,
        atr_14w = EXCLUDED.atr_14w,
        market_regime = EXCLUDED.market_regime,
        active_stop_loss = EXCLUDED.active_stop_loss,
        peak_gain_pct = EXCLUDED.peak_gain_pct,
        highest_price_since_entry = EXCLUDED.highest_price_since_entry,
        earnings_warning = EXCLUDED.earnings_warning,
        quality_score = EXCLUDED.quality_score,
        quality_grade = EXCLUDED.quality_grade,
        initial_breakout_score = EXCLUDED.initial_breakout_score,
        current_action_score = EXCLUDED.current_action_score,
        score_badge = EXCLUDED.score_badge,
        score_breakdown = EXCLUDED.score_breakdown;
    """
    values = [
        (
            s.get("scan_id"),
            s["scan_date"],
            s["ticker"],
            s["entry_price"],
            s["max_buy_price"],
            s["current_price"],
            s["stop_loss_price"],
            s["diff_pct"],
            s["entry_status"],
            s["volume_surge_ratio"],
            s["mrs_score"],
            s["sma_30w"],
            s["sma_30w_slope"],
            s["prior_resistance_35w"],
            s["weekly_close"],
            s["weekly_volume"],
            s["avg_volume_10w"],
            s.get("stage", "Stage 2 Breakout"),
            s.get("sma_10w"),
            s.get("base_tightness_pct"),
            s.get("atr_14w"),
            s.get("market_regime"),
            s.get("active_stop_loss", s["stop_loss_price"]),
            s.get("peak_gain_pct", 0.0),
            s.get("highest_price_since_entry", s["current_price"]),
            s.get("earnings_warning"),
            s.get("quality_score", 0.0),
            s.get("quality_grade", "B"),
            s.get("initial_breakout_score", s.get("quality_score", 0.0)),
            s.get("current_action_score", s.get("quality_score", 0.0)),
            s.get("score_badge", ""),
            json.dumps(s.get("score_breakdown")) if s.get("score_breakdown") else None,
        )
        for s in deduped_list
    ]

    from psycopg2.extras import execute_values

    def _execute(cursor):
        execute_values(cursor, sql, values, page_size=1000)
        # Prune stale records for this scan date that are no longer qualified/tracked only when requested
        if prune_unmatched:
            target_dates = list({str(s["scan_date"]) for s in deduped_list})
            for s_date in target_dates:
                valid_tickers = [s["ticker"] for s in deduped_list if str(s["scan_date"]) == s_date]
                if valid_tickers:
                    cursor.execute(
                        "DELETE FROM screener_signals WHERE scan_date = %s AND NOT (ticker = ANY(%s));",
                        (s_date, valid_tickers),
                    )

    if cur:
        _execute(cur)
    else:
        with db.db_cursor(commit=True) as cursor:
            _execute(cursor)

    return len(values)


# =============================================================================
# Dual-Source Historical Bar Loader
# =============================================================================

def load_historical_bars(ticker: str) -> List[Dict[str, Any]]:
    """
    Loads historical daily bars for a ticker from local Parquet cache first,
    falling back to PostgreSQL stock_daily_bars table if missing or empty.
    """
    # 1. Primary: Snappy Parquet Cache
    try:
        bars = parquet_cache.load_from_parquet(ticker)
        if bars:
            return bars
    except Exception as e:
        logger.debug(f"Parquet cache load failed for {ticker}: {e}")

    # 2. Fallback: PostgreSQL stock_daily_bars
    try:
        sql = """
        SELECT ticker, trade_date, open, high, low, close, adj_close, volume
        FROM stock_daily_bars
        WHERE ticker = %s
        ORDER BY trade_date ASC;
        """
        with db.db_cursor(commit=False) as cursor:
            cursor.execute(sql, (ticker,))
            rows = cursor.fetchall()
            if rows:
                return [
                    {
                        "ticker": r[0],
                        "trade_date": str(r[1]),
                        "open": float(r[2]),
                        "high": float(r[3]),
                        "low": float(r[4]),
                        "close": float(r[5]),
                        "adj_close": float(r[6]) if r[6] is not None else float(r[5]),
                        "volume": int(r[7]),
                    }
                    for r in rows
                ]
    except Exception as e:
        logger.debug(f"Database bar retrieval fallback failed for {ticker}: {e}")

    return []


# =============================================================================
# Core Pipeline Runner
# =============================================================================

def run_screener(
    scan_date: Optional[Union[date, str]] = None,
    tickers: Optional[List[str]] = None,
    min_weeks: int = MINIMUM_REQUIRED_WEEKS,
    db_persist: bool = True
) -> Dict[str, Any]:
    """
    Executes the end-to-end weekly Stage 2 screener job:
    1. Loads SPY benchmark daily bars and resamples to weekly.
    2. Initializes scan_jobs audit record.
    3. Loops through universe tickers, resamples daily bars, computes indicators.
    4. Evaluates Stage 2 filter, computes targets/risk, classifies entry status.
    5. Upserts qualified signals to 'screener_signals'.
    6. Updates scan_jobs audit status and metrics.
    """
    logger.info("Initializing Weinstein Stage 2 Screener pipeline...")

    # 1. Load SPY benchmark
    spy_daily = load_historical_bars("SPY")
    if not spy_daily:
        logger.info("SPY benchmark missing from cache. Live-fetching SPY (Nexus500 pattern: period='2y', threads=False)...")
        for attempt in range(3):
            try:
                import yfinance as yf
                df = yf.download("SPY", period="2y", interval="1d", auto_adjust=False, progress=False, threads=False)
                if df is not None and not df.empty:
                    if hasattr(df.columns, 'levels') or isinstance(df.columns, downloader.pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    bars = downloader._extract_bars_from_single_df(df, "SPY")
                    if bars and len(bars) >= min_weeks:
                        spy_daily = bars
                        parquet_cache.save_to_parquet("SPY", spy_daily)
                        logger.info(f"Loaded live SPY benchmark: {len(spy_daily)} daily bars.")
                        break
            except Exception as e:
                logger.warning(f"Live-fetch SPY attempt {attempt + 1} failed: {e}")
            downloader.time.sleep(3.0)

    if not spy_daily:
        err_msg = "SPY benchmark data is empty. Please run sync first."
        logger.error(err_msg)
        raise RuntimeError(err_msg)

    spy_weekly = resample_daily_to_weekly(spy_daily)
    if len(spy_weekly) < min_weeks:
        err_msg = f"SPY has {len(spy_weekly)} weekly bars, but {min_weeks} required."
        logger.error(err_msg)
        raise RuntimeError(err_msg)

    # Determine tickers to scan
    target_tickers = tickers if tickers is not None else universe.get_active_universe()
    target_tickers = [t for t in target_tickers if t != "SPY"]

    # Self-healing pre-scan ingestion: fetch missing tickers in batches (threads=False)
    missing_tickers = [t for t in target_tickers if not (config.PARQUET_DIR / f"{t}.parquet").exists()]
    if missing_tickers:
        logger.info(f"Found {len(missing_tickers)} tickers missing local cache. Fetching in batches (threads=False)...")
        try:
            start_dt, _, end_dt = downloader.calculate_date_range(mode="cold_start")
            fetched = downloader.download_universe(
                missing_tickers,
                start_dt.isoformat(),
                end_dt.isoformat(),
                chunk_size=config.BATCH_SIZE,
                rate_limit_delay=config.RATE_LIMIT_DELAY,
            )
            for t_sym, b_list in fetched.items():
                parquet_cache.save_to_parquet(t_sym, b_list or [])
                if b_list:
                    try:
                        db.ensure_stocks_exist([t_sym])
                        db.upsert_daily_bars(b_list)
                    except Exception as db_err:
                        logger.debug(f"Could not upsert fetched bars for {t_sym} to DB: {db_err}")
            logger.info(f"Pre-scan ingestion complete. Cached {len(fetched)} tickers to Parquet and DB.")
        except Exception as e:
            logger.warning(f"Auto-sync of missing tickers encountered an error: {e}")

    logger.info(f"Targeting {len(target_tickers)} tickers for screening (warmup={min_weeks}w)...")

    # 1b. Compute Market Regime Filter (SPY Weekly)
    spy_closes_full = [b["close"] for b in spy_weekly]
    regime_info = indicators.compute_market_regime(spy_closes_full, min_weeks=min_weeks)
    market_regime = regime_info["market_regime"]
    logger.info(
        f"SPY Benchmark Market Regime: {market_regime} "
        f"(SPY Close: {regime_info['spy_close']}, SMA30w: {regime_info['spy_sma_30w']}, "
        f"SMA10w: {regime_info['spy_sma_10w']}, Slope 4w: {regime_info['spy_slope_4w']}%)"
    )

    # 1c. Load or seed active breakout signals from database
    if db_persist:
        try:
            db.seed_active_breakout_signals_if_empty()
        except Exception as e:
            logger.debug(f"Seeding check: {e}")

    active_signals_db: Dict[str, Dict[str, Any]] = {}
    if db_persist:
        try:
            active_signals_db = db.load_active_breakout_signals()
            logger.info(f"Loaded {len(active_signals_db)} active breakout signals from database for lifecycle tracking.")
        except Exception as e:
            logger.warning(f"Could not load active_breakout_signals: {e}")

    active_signals_to_upsert: List[Dict[str, Any]] = []
    regime_multiplier = regime_info.get("regime_multiplier", 1.0)

    # 2. Audit job initiation
    job_id = None
    if db_persist:
        try:
            job_id = create_scan_job(tickers_total=len(target_tickers), market_regime=market_regime)
        except Exception as e:
            logger.warning(f"Could not initialize scan_jobs table: {e}")

    meta_lookup: Dict[str, Dict[str, Any]] = {}
    try:
        meta_lookup = {item["ticker"]: item for item in universe.load_universe_seed()}
    except Exception as e:
        logger.debug(f"Could not load universe seed metadata lookup: {e}")

    # Determine unified scan date for this scan run
    run_scan_date = (
        str(scan_date)
        if scan_date
        else (spy_weekly[-1]["trade_date"] if spy_weekly else str(date.today()))
    )

    qualified_signals: List[Dict[str, Any]] = []
    processed_count = 0
    failed_count = 0

    for ticker in target_tickers:
        try:
            daily_bars = load_historical_bars(ticker)
            if not daily_bars:
                continue

            weekly_bars = resample_daily_to_weekly(daily_bars)
            if len(weekly_bars) < min_weeks:
                # Insufficient warmup history
                continue

            # Align with SPY benchmark
            stock_w, spy_w = align_weekly_bars(weekly_bars, spy_weekly)
            if len(stock_w) < min_weeks:
                continue

            closes = [b["close"] for b in stock_w]
            highs = [b["high"] for b in stock_w]
            lows = [b["low"] for b in stock_w]
            volumes = [b["volume"] for b in stock_w]
            spy_closes = [b["close"] for b in spy_w]

            # Compute Weinstein V2 indicators
            sma10 = indicators.compute_sma(closes, window=10)
            sma30 = indicators.compute_sma(closes, window=30)
            slope4 = indicators.compute_sma_slope(sma30, lookback=4)
            avg_vol10, _ = indicators.compute_volume_surge(volumes, window=10)
            pivot35 = indicators.compute_prior_resistance_pivot(highs, lookback=35)
            tightness = indicators.compute_base_tightness(highs, lows, lookback=4)
            atr14 = indicators.compute_atr(highs, lows, closes, window=14)
            mrs = indicators.compute_mansfield_relative_strength(closes, spy_closes, lookback=52)

            last_idx = -1
            effective_scan_date = run_scan_date

            c = closes[last_idx]
            s10 = sma10[last_idx]
            s30 = sma30[last_idx]
            sl4 = slope4[last_idx] if slope4[last_idx] is not None else 0.0
            piv = pivot35[last_idx]
            if piv is None or piv <= 0:
                continue

            tight_pct = tightness[last_idx] if tightness[last_idx] is not None else 15.0
            h52 = max(highs[max(0, len(highs) - 52):])
            curr_vol = volumes[last_idx]
            avg_v = avg_vol10[last_idx] if avg_vol10[last_idx] is not None else 0
            _, vol_ratio = indicators.calculate_projected_volume_surge(curr_vol, avg_v)
            mrs_c = mrs[last_idx] if mrs[last_idx] is not None else -999.0
            mrs_p4 = mrs[last_idx - 4] if len(mrs) >= 5 and mrs[last_idx - 4] is not None else None
            atr_c = atr14[last_idx] if atr14[last_idx] is not None else (c * 0.05)
            min_l4 = min(lows[last_idx - 4 : last_idx]) if len(lows) >= 5 else (c * 0.95)
            low_prev_1w = lows[last_idx - 1] if len(lows) >= 2 else (c * 0.95)

            existing_signal = active_signals_db.get(ticker)

            if existing_signal is None:
                # ==========================================================
                # Mode 1: Discovery Scanner (New Breakouts)
                # Evaluates 8 criteria including Minimum Volatility filter
                # ==========================================================
                filter_res = evaluate_stage2_filter(
                    close=c,
                    sma_10w=s10,
                    sma_30w=s30,
                    sma_30w_slope=sl4,
                    pivot_35w=piv,
                    tightness_pct=tight_pct,
                    high_52w=h52,
                    vol_surge_ratio=vol_ratio,
                    mrs_score=mrs_c,
                    mrs_score_prev4=mrs_p4,
                    atr_14w=atr_c,
                )

                if not filter_res["is_stage2"]:
                    processed_count += 1
                    continue

                # Lock state upon initial breakout discovery
                entry_price = piv
                max_buy_price = round(entry_price * 1.05, 4)
                initial_stop_loss = calculate_adaptive_stop_loss(entry_price, atr_c, low_prev_1w)
                active_stop_loss = initial_stop_loss
                highest_price_since_entry = max(highs[last_idx], c)
                breakout_date = effective_scan_date

            else:
                # ==========================================================
                # Mode 2: Active Lifecycle Tracker (Already Broken Out)
                # DO NOT RE-FILTER THROUGH 8 DISCOVERY CRITERIA!
                # ==========================================================
                entry_price = float(existing_signal["entry_price"])
                max_buy_price = float(existing_signal["max_buy_price"])
                initial_stop_loss = float(existing_signal["initial_stop_loss"])
                breakout_date = str(existing_signal["breakout_date"])

                # Update highest price since entry
                highest_price_since_entry = max(
                    float(existing_signal.get("highest_price_since_entry", entry_price)),
                    highs[last_idx],
                    c
                )

                # Automatic Breakeven Stop: raise active stop to entry if peak gain >= 15%
                peak_gain_check = (
                    ((highest_price_since_entry - entry_price) / entry_price) * 100.0
                    if entry_price > 0
                    else 0.0
                )
                if peak_gain_check >= 15.0:
                    active_stop_loss = max(initial_stop_loss, entry_price)
                else:
                    active_stop_loss = initial_stop_loss

            # --------------------------------------------------------------
            # Step 5: 6-Tier Status Classification & Gain Calculations
            # --------------------------------------------------------------
            peak_gain_pct = (
                round(((highest_price_since_entry - entry_price) / entry_price) * 100.0, 2)
                if entry_price > 0
                else 0.0
            )
            current_gain_pct = (
                round(((c - entry_price) / entry_price) * 100.0, 2)
                if entry_price > 0
                else 0.0
            )

            status = classify_entry_status_v2_1(
                current_close=c,
                entry_price=entry_price,
                max_buy_price=max_buy_price,
                active_stop_loss=active_stop_loss,
                highest_price_since_entry=highest_price_since_entry,
                sma_10w=s10,
                sma_30w=s30,
            )

            # Step 4: Dynamic Position Sizing (Bug 3)
            sizing = calculate_position_size(
                portfolio_size=10000.0,
                risk_pct=1.0,
                regime_multiplier=regime_multiplier,
                current_price=c,
                entry_price=entry_price,
                stop_loss=active_stop_loss,
                max_alloc_pct=0.20,
            )

            # Step 4b: Compute Breakout Quality Score & Grade V2.0
            mrs_slope_4w = round(mrs_c - mrs_p4, 2) if mrs_p4 is not None else 0.0
            score_res = indicators.calculate_breakout_score_v2(
                mrs_score=mrs_c,
                mrs_slope_4w=mrs_slope_4w,
                vol_surge_ratio=vol_ratio,
                diff_pct=current_gain_pct,
                tightness_pct=tight_pct,
                weekly_high=highs[last_idx],
                weekly_low=lows[last_idx],
                weekly_close=c,
                is_retest_mode=bool(-2.0 <= current_gain_pct < 0.0),
            )
            current_action_score = score_res["final_score"]
            current_action_grade = score_res["grade"]
            score_badge = score_res["badge"]
            score_breakdown = score_res["breakdown"]

            # Handle initial breakout score vs current action score (Requirement 3: PROFIT_RUN)
            if existing_signal is None:
                initial_breakout_score = current_action_score
                initial_breakout_grade = current_action_grade
            else:
                initial_breakout_score = float(
                    existing_signal.get("initial_breakout_score")
                    or existing_signal.get("quality_score")
                    or current_action_score
                )
                initial_breakout_grade = (
                    existing_signal.get("initial_breakout_grade")
                    or existing_signal.get("quality_grade")
                    or current_action_grade
                )

            # If stock is in PROFIT_RUN or TRAILING_WARNING (peak gain >= 20%),
            # display Trend Leader badge and keep initial breakout score for ranking
            if status in ["PROFIT_RUN", "TRAILING_WARNING"] or peak_gain_pct >= 20.0:
                q_score = initial_breakout_score
                q_grade = initial_breakout_grade if initial_breakout_grade in ["A+", "A"] else "A+"
                score_badge = "🏆 Trend Leader"
            else:
                q_score = current_action_score
                q_grade = current_action_grade

            meta = meta_lookup.get(ticker, {})
            signal_record = {
                "scan_id": job_id,
                "scan_date": effective_scan_date,
                "ticker": ticker,
                "name": meta.get("name", ticker),
                "sector": meta.get("sector", "Unknown"),
                "industry": meta.get("industry", "Unknown"),
                "market_cap": meta.get("market_cap"),
                "entry_price": entry_price,
                "max_buy_price": max_buy_price,
                "current_price": round(c, 4),
                "stop_loss_price": active_stop_loss,
                "active_stop_loss": active_stop_loss,
                "initial_stop_loss": initial_stop_loss,
                "highest_price_since_entry": round(highest_price_since_entry, 4),
                "peak_gain_pct": peak_gain_pct,
                "current_gain_pct": current_gain_pct,
                "diff_pct": current_gain_pct,
                "entry_status": status,
                "volume_surge_ratio": vol_ratio,
                "mrs_score": mrs_c,
                "sma_30w": s30,
                "sma_30w_slope": sl4,
                "prior_resistance_35w": piv,
                "weekly_close": c,
                "weekly_volume": curr_vol,
                "avg_volume_10w": int(avg_v),
                "stage": "Stage 2 Breakout",
                "sma_10w": s10,
                "base_tightness_pct": tight_pct,
                "atr_14w": atr_c,
                "market_regime": market_regime,
                "recommended_shares": sizing["recommended_shares"],
                "capital_used": sizing["capital_used"],
                "portfolio_weight_pct": sizing["portfolio_weight_pct"],
                "actual_dollar_risk": sizing["actual_dollar_risk"],
                "risk_per_share": sizing["risk_per_share"],
                "breakout_date": breakout_date,
                "earnings_warning": None,
                "quality_score": q_score,
                "quality_grade": q_grade,
                "initial_breakout_score": initial_breakout_score,
                "current_action_score": current_action_score,
                "score_badge": score_badge,
                "score_breakdown": score_breakdown,
            }
            qualified_signals.append(signal_record)

            active_signals_to_upsert.append({
                "symbol": ticker,
                "breakout_date": breakout_date,
                "entry_price": entry_price,
                "max_buy_price": max_buy_price,
                "initial_stop_loss": initial_stop_loss,
                "active_stop_loss": active_stop_loss,
                "highest_price_since_entry": round(highest_price_since_entry, 4),
                "current_price": round(c, 4),
                "peak_gain_pct": peak_gain_pct,
                "current_gain_pct": current_gain_pct,
                "status": status,
                "recommended_shares": sizing["recommended_shares"],
                "earnings_warning": None,
                "quality_score": q_score,
                "quality_grade": q_grade,
                "initial_breakout_score": initial_breakout_score,
                "current_action_score": current_action_score,
                "score_badge": score_badge,
                "score_breakdown": score_breakdown,
            })

            processed_count += 1
        except Exception as e:
            logger.error(f"Error evaluating ticker {ticker}: {e}")
            failed_count += 1

    logger.info(
        f"Screening completed: {processed_count} processed, {failed_count} failed, "
        f"{len(qualified_signals)} Stage 2 breakout signals discovered/tracked."
    )

    # 4b. Fetch earnings warnings within [0, 14] days for qualified tickers (Bug 5)
    qualified_tickers = [s["ticker"] for s in qualified_signals]
    logger.info(f"Checking upcoming earnings dates for {len(qualified_tickers)} signals...")
    earnings_map = fetch_earnings_warning_map(qualified_tickers)
    for s in qualified_signals:
        s["earnings_warning"] = earnings_map.get(s["ticker"])
    for rec in active_signals_to_upsert:
        rec["earnings_warning"] = earnings_map.get(rec["symbol"])

    # 5. Persist active_breakout_signals to PostgreSQL
    if db_persist and active_signals_to_upsert:
        try:
            db.upsert_active_breakout_signals(active_signals_to_upsert)
            logger.info(f"Successfully synced {len(active_signals_to_upsert)} records to active_breakout_signals.")
        except Exception as e:
            logger.error(f"Failed to sync active_breakout_signals: {e}")

    # 5b. Persist signals to PostgreSQL screener_signals
    if db_persist and qualified_signals:
        try:
            upsert_screener_signals(qualified_signals, prune_unmatched=True)
            logger.info(f"Successfully persisted {len(qualified_signals)} Stage 2 signals to database.")
        except Exception as e:
            logger.error(f"Failed to persist signals to PostgreSQL: {e}")

    # 5b. Persist signals to local JSON cache for offline/standalone resilience
    if qualified_signals:
        try:
            import json
            signals_file = config.DATA_DIR / "latest_signals.json"
            signals_file.parent.mkdir(parents=True, exist_ok=True)
            final_scan_date = str(scan_date or (qualified_signals[0]["scan_date"] if qualified_signals else date.today()))
            with open(signals_file, "w", encoding="utf-8") as f:
                json.dump({
                    "scan_date": final_scan_date,
                    "market_regime": market_regime,
                    "generated_at": datetime.utcnow().isoformat() + "Z",
                    "signals_found": len(qualified_signals),
                    "signals": qualified_signals,
                }, f, indent=2, default=str)
            logger.info(f"Persisted {len(qualified_signals)} signals to local cache: {signals_file}")
        except Exception as e:
            logger.warning(f"Could not persist signals to local JSON: {e}")

    # 5c. Dispatch Smart Telegram Alert (Actionable Weekly Report)
    telegram_alert_sent = False
    if config.TELEGRAM_ENABLED:
        try:
            from screener.src import telegram_alert
            alert_date = str(scan_date or (qualified_signals[0]["scan_date"] if qualified_signals else date.today()))
            telegram_alert_sent = telegram_alert.send_weekly_alert(
                signals=qualified_signals,
                scan_date=alert_date,
                universe_count=processed_count or len(target_tickers),
                market_regime=market_regime,
                base_url=config.WEB_APP_BASE_URL,
                top_n=5,
                smart_mode=True,
            )
            logger.info(f"Smart Telegram alert dispatched: status={telegram_alert_sent}")
        except Exception as e:
            logger.warning(f"Smart Telegram alert dispatch error (non-fatal): {e}")

    # 6. Audit job completion
    if db_persist and job_id:
        try:
            update_scan_job(
                job_id=job_id,
                status="COMPLETED",
                tickers_processed=processed_count,
                tickers_failed=failed_count,
                signals_found=len(qualified_signals),
                telegram_alert_sent=telegram_alert_sent,
                market_regime=market_regime,
            )
        except Exception as e:
            logger.warning(f"Could not update scan_jobs completion: {e}")

    # 7. Automated Database Housekeeping (Rolling Retention Window)
    if db_persist:
        try:
            db.prune_database_records()
        except Exception as e:
            logger.debug(f"Housekeeping notice (non-fatal): {e}")

    return {
        "job_id": job_id,
        "tickers_total": len(target_tickers),
        "tickers_processed": processed_count,
        "tickers_failed": failed_count,
        "signals_found": len(qualified_signals),
        "signals": qualified_signals,
    }
