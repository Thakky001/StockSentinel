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


def evaluate_stage2_filter(
    close: float,
    sma_10w: Optional[float],
    sma_30w: Optional[float],
    sma_30w_slope: Optional[float],
    pivot_35w: Optional[float],
    tightness_pct: Optional[float],
    high_52w: Optional[float],
    vol_surge_ratio: Optional[float],
    mrs_score: Optional[float],
    mrs_score_prev4: Optional[float],
) -> Dict[str, Any]:
    """
    Evaluates Stage 2 Breakout V2 multi-factor filter according to mathematical spec:
    1. 30-Week SMA & 10-Week SMA:
       - close > sma_30w
       - sma_30w_slope >= 0.0% (4-week smoothed slope)
       - close > sma_10w (confirms short-term momentum)
    2. 35-Week Prior Resistance Pivot & Base Tightness:
       - close >= pivot_35w (breakout above prior 35w highs, excluding current week)
       - tightness_pct <= 20.0% (tight 4w consolidation base before breakout)
       - close >= high_52w * 0.85 (within 15% of 52-week high)
    3. Projected Volume Surge:
       - vol_surge_ratio >= 1.50 (current or projected weekly volume >= 1.5x 10w avg)
    4. Mansfield Relative Strength:
       - mrs_score > 0.0 (outperforming SPY)
       - mrs_score > mrs_score_prev4 (relative strength accelerating vs 4 weeks ago)
    """
    cond_1_trend = bool(
        sma_30w is not None
        and sma_10w is not None
        and sma_30w_slope is not None
        and close > sma_30w
        and sma_30w_slope >= 0.0
        and close > sma_10w
    )

    cond_2_breakout = bool(pivot_35w is not None and close >= pivot_35w)
    cond_2_tight_base = bool(
        tightness_pct is not None
        and high_52w is not None
        and tightness_pct <= 20.0
        and close >= (high_52w * 0.85)
    )

    cond_3_volume = bool(vol_surge_ratio is not None and vol_surge_ratio >= 1.50)

    cond_4_mrs = bool(
        mrs_score is not None
        and mrs_score > 0.0
        and (mrs_score_prev4 is None or mrs_score > mrs_score_prev4)
    )

    is_stage2 = (
        cond_1_trend
        and cond_2_breakout
        and cond_2_tight_base
        and cond_3_volume
        and cond_4_mrs
    )

    return {
        "is_stage2": is_stage2,
        "cond_1_trend": cond_1_trend,
        "cond_2_breakout": cond_2_breakout,
        "cond_2_tight_base": cond_2_tight_base,
        "cond_3_volume": cond_3_volume,
        "cond_4_mrs": cond_4_mrs,
    }


def calculate_target_and_risk(
    pivot_35w: float,
    current_price: float,
    atr_14w: Optional[float] = None,
    min_low_4w: Optional[float] = None,
    portfolio_size: float = 10000.0,
    risk_pct: float = 0.01,
) -> Dict[str, Any]:
    """
    Calculates V2 ATR-based Risk, Buy Zone & Position Sizing:
    - entry_price = round(pivot_35w, 4)
    - max_buy_price = round(entry_price * 1.05, 4) (+5% chase limit)
    - stop_loss_price:
        stop_atr = entry_price - (1.5 * atr_14w)
        stop_base = min_low_4w * 0.99
        stop_hard_cap = entry_price * 0.90 (-10% max risk cap)
        stop_loss = max(stop_hard_cap, min(stop_atr, stop_base))
    - diff_pct = ((current_price - entry_price) / entry_price) * 100
    - position sizing:
        risk_per_share = max(current_price - stop_loss, 0.01)
        dollar_risk = portfolio_size * risk_pct
        recommended_shares = floor(dollar_risk / risk_per_share)
    """
    entry_price = round(pivot_35w, 4)
    max_buy_price = round(entry_price * 1.05, 4)

    effective_atr = atr_14w if (atr_14w is not None and atr_14w > 0) else (entry_price * 0.05)
    stop_atr = entry_price - (1.5 * effective_atr)
    stop_base = (min_low_4w * 0.99) if (min_low_4w is not None and min_low_4w > 0) else stop_atr
    stop_hard_cap = entry_price * 0.90

    stop_loss = round(max(stop_hard_cap, min(stop_atr, stop_base)), 4)
    diff_pct = round(((current_price - entry_price) / entry_price) * 100.0, 4)

    risk_per_share = max(round(current_price - stop_loss, 4), 0.01)
    dollar_risk = portfolio_size * risk_pct
    recommended_shares = int(np.floor(dollar_risk / risk_per_share))

    return {
        "entry_price": entry_price,
        "max_buy_price": max_buy_price,
        "stop_loss_price": stop_loss,
        "current_price": round(current_price, 4),
        "diff_pct": diff_pct,
        "risk_per_share": risk_per_share,
        "recommended_shares": recommended_shares,
    }


def classify_entry_status(
    current_price: float,
    entry_price: float,
    max_buy_price: float,
    stop_loss_price: float,
    sma_10w: Optional[float] = None,
    sma_30w: Optional[float] = None,
) -> str:
    """
    6-Tier Actionable Status for Stage 2 Trend Riding:
    1. 🔴 STOPPED_OUT: current_price < stop_loss_price or (sma_30w and current_price < sma_30w)
    2. 🔵 PROFIT_RUN: gain_pct >= 15.0% and (sma_10w and current_price >= sma_10w)
    3. 🟠 TRAILING_WARNING: gain_pct >= 15.0% and (sma_10w and current_price < sma_10w)
    4. 🟡 EXTENDED: current_price > max_buy_price and gain_pct < 15.0%
    5. 🟢 IN_BUY_ZONE: entry_price <= current_price <= max_buy_price (favorable entry point)
    6. ⚪ BELOW_ENTRY: near pivot (-6% to 0%) or pulled back above stop_loss
    """
    gain_pct = ((current_price - entry_price) / entry_price) * 100.0

    if current_price < stop_loss_price or (sma_30w is not None and current_price < sma_30w):
        return "STOPPED_OUT"
    elif gain_pct >= 15.0 and sma_10w is not None and current_price >= sma_10w:
        return "PROFIT_RUN"
    elif gain_pct >= 15.0 and sma_10w is not None and current_price < sma_10w:
        return "TRAILING_WARNING"
    elif current_price > max_buy_price:
        return "EXTENDED"
    elif entry_price <= current_price <= max_buy_price:
        return "IN_BUY_ZONE"
    else:
        return "BELOW_ENTRY"


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


def upsert_screener_signals(signals: List[Dict[str, Any]], cur=None) -> int:
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

    sql = """
    INSERT INTO screener_signals (
        scan_id, scan_date, ticker, entry_price, max_buy_price, current_price,
        stop_loss_price, diff_pct, entry_status, volume_surge_ratio, mrs_score,
        sma_30w, sma_30w_slope, prior_resistance_35w, weekly_close,
        weekly_volume, avg_volume_10w, stage, sma_10w, base_tightness_pct, atr_14w, market_regime
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
        market_regime = EXCLUDED.market_regime;
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
        )
        for s in deduped_list
    ]

    from psycopg2.extras import execute_values
    if cur:
        execute_values(cur, sql, values, page_size=1000)
    else:
        with db.db_cursor(commit=True) as cursor:
            execute_values(cursor, sql, values, page_size=1000)

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

            # Trace initial breakout pivot in recent 16 weeks if in active run
            entry_pivot = piv
            for k in range(1, min(17, len(closes))):
                idx = len(closes) - 1 - k
                if idx >= 35 and pivot35[idx] and closes[idx] >= pivot35[idx] and closes[idx] < c:
                    entry_pivot = pivot35[idx]
                    break

            risk = calculate_target_and_risk(
                pivot_35w=entry_pivot,
                current_price=c,
                atr_14w=atr_c,
                min_low_4w=min_l4,
                portfolio_size=10000.0,
                risk_pct=0.01,
            )

            status = classify_entry_status(
                current_price=risk["current_price"],
                entry_price=risk["entry_price"],
                max_buy_price=risk["max_buy_price"],
                stop_loss_price=risk["stop_loss_price"],
                sma_10w=s10,
                sma_30w=s30,
            )

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
            )

            is_qualified = False
            in_stage2 = (c > s30) and (sl4 >= 0.0) and (mrs_c > 0.0)
            if filter_res["is_stage2"]:
                is_qualified = True
                status = "IN_BUY_ZONE"
            elif in_stage2 and status in ("IN_BUY_ZONE", "PROFIT_RUN", "TRAILING_WARNING", "EXTENDED"):
                is_qualified = True
            elif in_stage2 and status == "BELOW_ENTRY" and risk["diff_pct"] >= -6.0:
                is_qualified = True

            if is_qualified:
                meta = meta_lookup.get(ticker, {})
                signal_record = {
                    "scan_id": job_id,
                    "scan_date": effective_scan_date,
                    "ticker": ticker,
                    "name": meta.get("name", ticker),
                    "sector": meta.get("sector", "Unknown"),
                    "industry": meta.get("industry", "Unknown"),
                    "market_cap": meta.get("market_cap"),
                    "entry_price": risk["entry_price"],
                    "max_buy_price": risk["max_buy_price"],
                    "current_price": risk["current_price"],
                    "stop_loss_price": risk["stop_loss_price"],
                    "diff_pct": risk["diff_pct"],
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
                    "recommended_shares": risk["recommended_shares"],
                    "risk_per_share": risk["risk_per_share"],
                }
                qualified_signals.append(signal_record)

            processed_count += 1
        except Exception as e:
            logger.error(f"Error evaluating ticker {ticker}: {e}")
            failed_count += 1

    logger.info(
        f"Screening completed: {processed_count} processed, {failed_count} failed, "
        f"{len(qualified_signals)} Stage 2 breakout signals discovered."
    )

    # 5. Persist signals to PostgreSQL
    if db_persist and qualified_signals:
        try:
            upsert_screener_signals(qualified_signals)
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

    # 6. Audit job completion
    if db_persist and job_id:
        try:
            update_scan_job(
                job_id=job_id,
                status="COMPLETED",
                tickers_processed=processed_count,
                tickers_failed=failed_count,
                signals_found=len(qualified_signals),
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
