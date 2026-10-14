"""
screener/src/sync.py - Orchestrator and coordinator for universe synchronization,
delta/cold-start yfinance downloads, Parquet local caching, and PostgreSQL daily upserting.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from screener.src import config, db, downloader, parquet_cache, universe

logger = logging.getLogger(__name__)


def get_latest_trading_friday(target_date: Optional[Union[date, datetime]] = None) -> date:
    """
    Returns the most recent Friday trading date relative to target_date (or today).
    """
    return downloader.resolve_trading_friday(target_date)


def run_sync(
    cold_start: bool = False,
    tickers: Optional[List[str]] = None,
    target_date: Optional[Union[date, datetime]] = None,
    force: bool = False,
    skip_unmodified: bool = True,
) -> Dict[str, Any]:
    """
    Executes end-to-end stock data synchronization:
    1. Upsert universe seed dataset into PostgreSQL 'stocks' table.
    2. Resolve target trading Friday and compute ingestion window (7-day delta vs 730-day cold start).
    3. Ingest SPY benchmark first (required for downstream Mansfield RS in M3).
    4. Ingest broader universe in 50-ticker batches with rate-limiting pacing and backoff.
    5. Merge and persist daily bars to local Snappy-compressed Parquet cache.
    6. Batch upsert daily bars to PostgreSQL 'stock_daily_bars' table.
    
    Args:
        cold_start: If True, syncs 730 days (2 years) of history; otherwise 7 days.
        tickers: Optional list of tickers to sync. If None, syncs all active universe stocks.
        target_date: Reference date for sync (defaults to current date).
        force: If True, re-fetches even if ticker cache is already up-to-date.
        skip_unmodified: If True, skips tickers whose Parquet cache has latest Friday.
        
    Returns:
        Dictionary containing synchronization execution metrics.
    """
    target_friday = get_latest_trading_friday(target_date)
    target_friday_str = target_friday.isoformat()
    mode = "cold_start" if cold_start else "delta"
    start_dt, _, yf_exclusive_end = downloader.calculate_date_range(target_friday, mode=mode)
    start_str = start_dt.isoformat()
    end_str = yf_exclusive_end.isoformat()

    logger.info(
        f"Initiating {mode.upper()} sync: target Friday {target_friday_str}, "
        f"window: {start_str} to {end_str} (exclusive)."
    )

    # Step 1: Synchronize stock master universe into PostgreSQL
    try:
        synced_stocks_count = universe.sync_universe_to_db()
        logger.info(f"Synchronized {synced_stocks_count} stocks into database.")
    except Exception as e:
        logger.warning(f"Could not sync universe to PostgreSQL ({e}). Continuing with cache.")

    # Determine universe tickers to sync
    all_tickers = tickers if tickers is not None else universe.get_active_universe()
    if not all_tickers:
        all_tickers = ["SPY"]

    # Normalize and deduplicate tickers
    canonical_tickers = [universe.sanitize_ticker(t) for t in all_tickers if t]
    canonical_tickers = list(dict.fromkeys(canonical_tickers))
    # Ensure SPY is in the list
    if "SPY" not in canonical_tickers:
        canonical_tickers.insert(0, "SPY")

    # Ensure all canonical tickers exist in stocks table to prevent foreign key violations
    try:
        db.ensure_stocks_exist(canonical_tickers)
    except Exception as e:
        logger.warning(f"Could not pre-seed canonical tickers into stocks table: {e}")

    total_downloaded_bars = 0
    total_upserted_bars = 0
    tickers_skipped = 0

    # Step 2: Ingest SPY benchmark first
    logger.info("Ingesting SPY benchmark ETF bars...")
    cached_spy = parquet_cache.load_from_parquet("SPY")
    spy_needs_fetch = force or cold_start or not cached_spy
    if not spy_needs_fetch and skip_unmodified:
        latest_spy_date = cached_spy[-1]["trade_date"] if cached_spy else None
        if latest_spy_date and latest_spy_date >= target_friday_str:
            logger.info(f"SPY cache is up-to-date ({latest_spy_date}). Skipping fetch.")
            spy_needs_fetch = False
        else:
            spy_needs_fetch = True

    if spy_needs_fetch:
        spy_res = downloader.download_batch_with_retry(["SPY"], start_str, end_str)
        spy_bars = spy_res.get("SPY", [])
        if spy_bars:
            merged_spy = parquet_cache.merge_daily_bars(cached_spy, spy_bars)
            parquet_cache.save_to_parquet("SPY", merged_spy)
            try:
                db.upsert_daily_bars(merged_spy)
            except Exception as e:
                logger.warning(f"Could not upsert SPY bars to PostgreSQL: {e}")
            total_downloaded_bars += len(spy_bars)
            total_upserted_bars += len(merged_spy)
    else:
        tickers_skipped += 1

    # Step 3: Ingest broader stock universe
    stock_tickers = [t for t in canonical_tickers if t != "SPY"]
    tickers_to_fetch = []

    for t in stock_tickers:
        if not force and not cold_start and skip_unmodified:
            if parquet_cache.is_cache_current(t, target_friday_str):
                tickers_skipped += 1
                continue
        tickers_to_fetch.append(t)

    logger.info(
        f"Universe size: {len(stock_tickers)}. Skipped up-to-date: {tickers_skipped}. "
        f"To fetch: {len(tickers_to_fetch)}."
    )

    if tickers_to_fetch:
        chunks = downloader.chunk_tickers(tickers_to_fetch, chunk_size=config.BATCH_SIZE)
        total_chunks = len(chunks)

        for idx, chunk in enumerate(chunks):
            logger.info(f"Syncing batch {idx + 1}/{total_chunks} ({len(chunk)} tickers)...")
            batch_res = downloader.download_batch_with_retry(chunk, start_str, end_str)

            bars_to_upsert = []
            for ticker, new_bars in batch_res.items():
                if not new_bars:
                    continue
                cached = parquet_cache.load_from_parquet(ticker)
                merged = parquet_cache.merge_daily_bars(cached, new_bars)
                parquet_cache.save_to_parquet(ticker, merged)
                bars_to_upsert.extend(new_bars)
                total_downloaded_bars += len(new_bars)

            if bars_to_upsert:
                try:
                    upserted = db.upsert_daily_bars(bars_to_upsert)
                    total_upserted_bars += upserted
                except Exception as e:
                    logger.warning(f"Failed to upsert bars batch into PostgreSQL: {e}")

            # Inter-chunk pacing delay
            if idx < total_chunks - 1 and config.RATE_LIMIT_DELAY > 0:
                downloader.time.sleep(config.RATE_LIMIT_DELAY)

    logger.info(
        f"Sync completed. Tickers total: {len(canonical_tickers)}, "
        f"Skipped: {tickers_skipped}, Downloaded bars: {total_downloaded_bars}, "
        f"Upserted bars: {total_upserted_bars}."
    )

    return {
        "mode": mode,
        "target_date": target_friday_str,
        "tickers_total": len(canonical_tickers),
        "tickers_synced": len(tickers_to_fetch) + (1 if spy_needs_fetch else 0),
        "tickers_skipped": tickers_skipped,
        "bars_downloaded": total_downloaded_bars,
        "bars_upserted": total_upserted_bars,
    }
