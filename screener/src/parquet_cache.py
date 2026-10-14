"""
screener/src/parquet_cache.py - Local Parquet caching with Snappy compression,
merge deduplication, and file corruption resilience.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import pyarrow as pa
import pyarrow.parquet as pq
from screener.src import config
from screener.src.universe import sanitize_ticker

logger = logging.getLogger(__name__)


def get_parquet_path(ticker: str) -> Path:
    """
    Returns the absolute path to a ticker's Parquet cache file.
    Creates parent directories if they do not exist.
    Dual-class tickers with dot are preserved: e.g. data/parquet/BRK.B.parquet.
    """
    clean_ticker = sanitize_ticker(ticker)
    config.PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    return config.PARQUET_DIR / f"{clean_ticker}.parquet"


def save_to_parquet(ticker: str, bars: List[Dict[str, Any]]) -> bool:
    """
    Saves daily bars to a Snappy-compressed Parquet file, sorting ascending by trade_date.
    
    Args:
        ticker: Canonical stock ticker symbol.
        bars: List of daily bar dictionaries.
        
    Returns:
        True if successfully saved, False otherwise.
    """
    if not bars:
        return False

    clean_ticker = sanitize_ticker(ticker)
    path = get_parquet_path(clean_ticker)

    try:
        # Sort chronologically ascending
        sorted_bars = sorted(bars, key=lambda b: b["trade_date"])
        
        # Enforce canonical schema
        table = pa.Table.from_pylist(sorted_bars)
        pq.write_table(
            table,
            path,
            compression="snappy",
            use_dictionary=True,
        )
        return True
    except Exception as e:
        logger.error(f"Failed to write Parquet cache for {clean_ticker} at {path}: {e}")
        return False


def load_from_parquet(ticker: str) -> List[Dict[str, Any]]:
    """
    Loads daily bars from Parquet cache.
    Resilient to zero-byte or corrupted files: logs a warning, cleans up the damaged file,
    and returns an empty list to prompt a re-fetch.
    """
    clean_ticker = sanitize_ticker(ticker)
    path = get_parquet_path(clean_ticker)

    if not path.exists():
        return []

    # Detect 0-byte or empty file corruption
    try:
        if path.stat().st_size == 0:
            logger.warning(f"Detected zero-byte Parquet file for {clean_ticker} at {path}. Removing corrupt file.")
            path.unlink(missing_ok=True)
            return []
    except Exception as e:
        logger.warning(f"Error checking file size for {clean_ticker}: {e}")
        return []

    try:
        table = pq.read_table(path)
        return table.to_pylist()
    except Exception as e:
        logger.warning(f"Corrupted Parquet cache detected for {clean_ticker} ({e}). Removing corrupt file.")
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return []


def merge_daily_bars(
    existing_bars: List[Dict[str, Any]],
    new_bars: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merges historical and newly fetched daily bars, deduplicating by trade_date.
    Newer values overwrite existing entries on date collision (handling corporate actions/adjustments).
    Returns list sorted chronologically ascending by trade_date.
    """
    merged: Dict[str, Dict[str, Any]] = {b["trade_date"]: dict(b) for b in existing_bars}
    for b in new_bars:
        merged[b["trade_date"]] = dict(b)

    return sorted(list(merged.values()), key=lambda x: x["trade_date"])


def get_latest_cached_trade_date(ticker: str) -> Optional[str]:
    """
    Returns the latest trade_date recorded in the ticker's Parquet cache, or None if empty.
    """
    bars = load_from_parquet(ticker)
    if not bars:
        return None
    return bars[-1]["trade_date"]


def is_cache_current(ticker: str, target_date: str) -> bool:
    """
    Checks if a ticker's cache already has data up to or beyond target_date.
    """
    latest = get_latest_cached_trade_date(ticker)
    if not latest:
        return False
    return latest >= target_date
