"""
screener/src/screener.py - Core Screener Engine, Stage 2 Breakout Filters,
Target & Risk Calculations, Entry Status Classification, and Signal Persistence.
Features: F17 (Breakout Filter), F18 (Target/Risk Math), F19 (Entry Status), F20 (Persistence).
"""
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from screener.src import config, db, downloader, parquet_cache, universe
from screener.src.indicators import (
    align_weekly_bars,
    compute_mansfield_relative_strength,
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
    sma_30w: Optional[float],
    sma_30w_slope: Optional[float],
    pivot_35w: Optional[float],
    vol_surge_ratio: Optional[float],
    mrs_score: Optional[float],
) -> Dict[str, Any]:
    """
    Evaluates Stan Weinstein Stage 2 Breakout multi-factor filter.
    All 5 conditions must be True simultaneously:
    1. close > sma_30w (Price above 30w moving average)
    2. sma_30w_slope >= 0.0 (30w SMA is flat or rising)
    3. close >= pivot_35w (Price broke out above 35-week base resistance)
    4. vol_surge_ratio >= 1.50 (Institutional volume surge >= 1.5x 10w avg)
    5. mrs_score > 0.0 (Mansfield Relative Strength > 0 outperforming SPY)
    """
    cond_close_above_sma = (sma_30w is not None) and (close > sma_30w)
    cond_sma_rising = (sma_30w_slope is not None) and (sma_30w_slope >= 0.0)
    cond_pivot_breakout = (pivot_35w is not None) and (close >= pivot_35w)
    cond_volume_surge = (vol_surge_ratio is not None) and (vol_surge_ratio >= 1.50)
    cond_mrs_positive = (mrs_score is not None) and (mrs_score > 0.0)

    is_stage2 = (
        cond_close_above_sma
        and cond_sma_rising
        and cond_pivot_breakout
        and cond_volume_surge
        and cond_mrs_positive
    )

    return {
        "is_stage2": is_stage2,
        "cond_close_above_sma": cond_close_above_sma,
        "cond_sma_rising": cond_sma_rising,
        "cond_pivot_breakout": cond_pivot_breakout,
        "cond_volume_surge": cond_volume_surge,
        "cond_mrs_positive": cond_mrs_positive,
    }


def calculate_target_and_risk(
    pivot_35w: float,
    current_price: float,
    swing_low: Optional[float] = None
) -> Dict[str, float]:
    """
    Calculates entry target, max buy price (+5%), stop loss, and distance percentage:
    - entry_price = round(pivot_35w, 4)
    - max_buy_price = round(entry_price * 1.05, 4) (+5% chase limit)
    - stop_loss_price = round(swing_low, 4) if (swing_low and 0 < swing_low < entry_price)
                        else round(entry_price * 0.92, 4) (-8% default stop)
    - diff_pct = round(((current_price - entry_price) / entry_price) * 100.0, 4)
    """
    entry_price = round(pivot_35w, 4)
    max_buy_price = round(entry_price * 1.05, 4)

    if swing_low is not None and 0.0 < swing_low < entry_price:
        stop_loss_price = round(swing_low, 4)
    else:
        stop_loss_price = round(entry_price * 0.92, 4)

    diff_pct = round(((current_price - entry_price) / entry_price) * 100.0, 4)

    return {
        "entry_price": entry_price,
        "max_buy_price": max_buy_price,
        "stop_loss_price": stop_loss_price,
        "current_price": round(current_price, 4),
        "diff_pct": diff_pct,
    }


def classify_entry_status(
    current_price: float,
    entry_price: float,
    max_buy_price: float,
    stop_loss_price: float
) -> str:
    """
    Deterministic entry status categorization (mutually exclusive enum):
    - current_price < stop_loss_price          => 'STOPPED_OUT'
    - stop_loss_price <= current_price < entry => 'BELOW_ENTRY' (price == stop_loss is BELOW_ENTRY)
    - entry_price <= current_price <= max_buy  => 'IN_BUY_ZONE' (both bounds inclusive)
    - current_price > max_buy_price            => 'EXTENDED'
    """
    if current_price < stop_loss_price:
        return "STOPPED_OUT"
    elif current_price < entry_price:
        return "BELOW_ENTRY"
    elif current_price <= max_buy_price:
        return "IN_BUY_ZONE"
    else:
        return "EXTENDED"


# =============================================================================
# Database Persistence Helpers (Feature 20)
# =============================================================================

def create_scan_job(tickers_total: int, cur=None) -> int:
    """Creates a new scan_jobs audit record with status 'RUNNING'."""
    sql = """
    INSERT INTO scan_jobs (job_type, status, started_at, tickers_total, tickers_processed, tickers_failed, signals_found)
    VALUES ('WEEKLY_SCREEN', 'RUNNING', CURRENT_TIMESTAMP, %s, 0, 0, 0)
    RETURNING id;
    """
    if cur:
        cur.execute(sql, (tickers_total,))
        return cur.fetchone()[0]
    else:
        with db.db_cursor(commit=True) as cursor:
            cursor.execute(sql, (tickers_total,))
            return cursor.fetchone()[0]


def update_scan_job(
    job_id: int,
    status: str,
    tickers_processed: int = 0,
    tickers_failed: int = 0,
    signals_found: int = 0,
    error_message: Optional[str] = None,
    telegram_alert_sent: bool = False,
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
        telegram_alert_sent = %s
    WHERE id = %s;
    """
    params = (status, tickers_processed, tickers_failed, signals_found, error_message, telegram_alert_sent, job_id)
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
        weekly_volume, avg_volume_10w, stage
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
        stage = EXCLUDED.stage;
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

    # 2. Audit job initiation
    job_id = None
    if db_persist:
        try:
            job_id = create_scan_job(tickers_total=len(target_tickers))
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
            volumes = [b["volume"] for b in stock_w]
            spy_closes = [b["close"] for b in spy_w]

            # Compute Weinstein indicators
            sma30 = compute_sma(closes, window=30)
            slope = compute_sma_slope(sma30, lookback=1)
            avg_vol10, surge = compute_volume_surge(volumes, window=10)
            pivot35 = compute_prior_resistance_pivot(highs, lookback=35)
            mrs = compute_mansfield_relative_strength(closes, spy_closes, lookback=52)

            last_idx = -1
            effective_scan_date = run_scan_date

            filter_res = evaluate_stage2_filter(
                close=closes[last_idx],
                sma_30w=sma30[last_idx],
                sma_30w_slope=slope[last_idx],
                pivot_35w=pivot35[last_idx],
                vol_surge_ratio=surge[last_idx],
                mrs_score=mrs[last_idx],
            )

            is_qualified = filter_res["is_stage2"]

            # Stan Weinstein Stage 2 Continuation & Setup Detection:
            # If the stock didn't break out on the exact current bar, check if it had a Stage 2 breakout
            # in recent weeks (last 8 weeks) OR is in an active Stage 2 Uptrend in the Buy Zone / Pullback Setup
            if not is_qualified:
                c = closes[last_idx]
                s30 = sma30[last_idx]
                sl = slope[last_idx]
                piv = pivot35[last_idx]
                m = mrs[last_idx]
                if s30 and c > s30 and sl and sl >= 0 and m and m > 0 and piv:
                    diff_pct = (c - piv) / piv * 100
                    had_recent_breakout = False
                    for b_idx in range(-1, max(-9, -len(stock_w)), -1):
                        r_b = evaluate_stage2_filter(
                            close=closes[b_idx],
                            sma_30w=sma30[b_idx],
                            sma_30w_slope=slope[b_idx],
                            pivot_35w=pivot35[b_idx],
                            vol_surge_ratio=surge[b_idx],
                            mrs_score=mrs[b_idx],
                        )
                        if r_b["is_stage2"]:
                            had_recent_breakout = True
                            break
                    if had_recent_breakout or (-12.0 <= diff_pct <= 20.0):
                        is_qualified = True

            if is_qualified:
                risk = calculate_target_and_risk(
                    pivot_35w=pivot35[last_idx],
                    current_price=closes[last_idx]
                )
                status = classify_entry_status(
                    current_price=risk["current_price"],
                    entry_price=risk["entry_price"],
                    max_buy_price=risk["max_buy_price"],
                    stop_loss_price=risk["stop_loss_price"]
                )

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
                    "volume_surge_ratio": surge[last_idx],
                    "mrs_score": mrs[last_idx],
                    "sma_30w": sma30[last_idx],
                    "sma_30w_slope": slope[last_idx],
                    "prior_resistance_35w": pivot35[last_idx],
                    "weekly_close": closes[last_idx],
                    "weekly_volume": volumes[last_idx],
                    "avg_volume_10w": int(avg_vol10[last_idx]) if avg_vol10[last_idx] is not None else 0,
                    "stage": "Stage 2 Breakout",
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
