"""
screener/src/downloader.py - Resilient yfinance batch downloader with 50-chunking,
exponential backoff with jitter, pacing delays, single-ticker fallback, and OHLCV normalization.
"""
import logging
import math
import random
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd
import yfinance as yf
from screener.src import config
from screener.src.universe import sanitize_ticker, to_yfinance_symbol, from_yfinance_symbol

logger = logging.getLogger(__name__)


def chunk_tickers(tickers: List[str], chunk_size: int = config.BATCH_SIZE) -> List[List[str]]:
    """
    Splits universe into batches of <= chunk_size (default: 50).
    """
    if not tickers:
        return []
    return [tickers[i : i + chunk_size] for i in range(0, len(tickers), chunk_size)]


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = config.BACKOFF_BASE,
    max_delay: float = config.BACKOFF_MAX,
    jitter: bool = False,
) -> float:
    """
    Computes exponential backoff delay: min(base_delay * (2 ** attempt), max_delay).
    If jitter=True, adds uniform random jitter between 0.1s and 0.5s, capped at max_delay.
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    if jitter:
        jitter_val = random.uniform(0.1, 0.5)
        delay = min(delay + jitter_val, max_delay)
    return round(delay, 3)


def resolve_trading_friday(ref_date: Optional[Union[date, datetime]] = None) -> date:
    """
    Resolves weekend execution dates (Saturday/Sunday) to the latest preceding Friday trading day.
    Weekday: Monday is 0, Friday is 4, Saturday is 5, Sunday is 6.
    """
    d = ref_date if ref_date is not None else date.today()
    if isinstance(d, datetime):
        d = d.date()
    days_since_friday = (d.weekday() - 4) % 7
    return d - timedelta(days=days_since_friday)


def calculate_date_range(
    target_date: Optional[date] = None,
    mode: str = "delta"
) -> Tuple[date, date, date]:
    """
    Calculates (start_date, target_friday, yf_exclusive_end_date).
    - 'delta': 7 days prior to target Friday.
    - 'cold_start': 730 days (104 weeks / 2 years) prior to target Friday.
    Yahoo Finance 'end' is exclusive, so yf_exclusive_end_date is target_friday + 1 day.
    """
    friday = resolve_trading_friday(target_date)
    if mode == "cold_start":
        start_date = friday - timedelta(days=config.COLD_START_DAYS)
    else:
        start_date = friday - timedelta(days=config.DELTA_DAYS)
    yf_exclusive_end = friday + timedelta(days=1)
    return start_date, friday, yf_exclusive_end


def normalize_daily_bar(ticker: str, trade_date: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normalizes a single daily price record into a standardized dictionary
    guaranteeing PostgreSQL CHECK constraint compliance:
    - open >= 0, high >= low, high >= open, high >= close, low <= open, low <= close, volume >= 0.
    - Imputes adj_close from close if missing or NaN.
    """
    try:
        raw_close = row.get("Close") if "Close" in row else row.get("close")
        if raw_close is None or str(raw_close).lower() == "nan":
            return None
        close_p = float(raw_close)
        if math.isnan(close_p) or close_p <= 0:
            return None

        raw_open = row.get("Open") if "Open" in row else row.get("open")
        raw_high = row.get("High") if "High" in row else row.get("high")
        raw_low = row.get("Low") if "Low" in row else row.get("low")
        raw_adj = row.get("Adj Close") if "Adj Close" in row else row.get("adj_close")
        raw_vol = row.get("Volume") if "Volume" in row else row.get("volume")

        open_p = float(raw_open) if raw_open is not None and str(raw_open).lower() != "nan" else close_p
        high_p = float(raw_high) if raw_high is not None and str(raw_high).lower() != "nan" else close_p
        low_p = float(raw_low) if raw_low is not None and str(raw_low).lower() != "nan" else close_p
        adj_p = float(raw_adj) if raw_adj is not None and str(raw_adj).lower() != "nan" else close_p
        vol_i = int(float(raw_vol)) if raw_vol is not None and str(raw_vol).lower() != "nan" else 0

        # Enforce relational boundaries and positive values
        open_val = round(max(0.0, open_p), 4)
        close_val = round(close_p, 4)
        high_val = round(max(high_p, open_val, close_val), 4)
        low_val = round(max(0.0, min(low_p, open_val, close_val)), 4)
        adj_val = round(max(0.0, adj_p), 4)
        vol_val = max(0, vol_i)

        return {
            "ticker": sanitize_ticker(ticker),
            "trade_date": trade_date,
            "open": open_val,
            "high": high_val,
            "low": low_val,
            "close": close_val,
            "adj_close": adj_val,
            "volume": vol_val,
        }
    except Exception as e:
        logger.debug(f"Normalization failed for {ticker} on {trade_date}: {e}")
        return None


def _extract_bars_from_single_df(df: pd.DataFrame, ticker: str) -> List[Dict[str, Any]]:
    """Extracts OHLCV bars from a single-ticker DataFrame."""
    if df is None or df.empty:
        return []

    bars = []
    # Format trade_date string safely stripping timezones
    if hasattr(df.index, "tz") and df.index.tz is not None:
        dates = df.index.tz_convert("America/New_York").strftime("%Y-%m-%d")
    else:
        dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10] for d in df.index]

    for d_str, (_, row) in zip(dates, df.iterrows()):
        bar = normalize_daily_bar(ticker, d_str, row.to_dict())
        if bar:
            bars.append(bar)
    return bars


def download_single_ticker(
    ticker: str,
    start_date: str,
    end_date: str,
    max_retries: int = config.MAX_RETRIES,
) -> Dict[str, Any]:
    """
    Downloads daily bars for a single ticker with backoff retry.
    Isolates errors for delisted/unregistered tickers.
    """
    yf_sym = to_yfinance_symbol(ticker)
    attempt = 0
    df = None
    last_error = None

    while attempt < max_retries:
        try:
            logger.debug(f"Downloading single ticker {ticker} ({yf_sym}), attempt {attempt + 1}")
            df = yf.download(
                tickers=yf_sym,
                start=start_date,
                end=end_date,
                threads=False,
                progress=False,
                auto_adjust=False,
            )
            if df is not None and not df.empty:
                break
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Error fetching single ticker {ticker}: {e}")

        attempt += 1
        if attempt < max_retries:
            delay = calculate_backoff_delay(attempt, jitter=True)
            time.sleep(delay)

    if df is None or df.empty:
        return {
            "ticker": ticker,
            "success": False,
            "bars": [],
            "error": last_error or "No data returned (possibly delisted or invalid ticker)",
        }

    bars = _extract_bars_from_single_df(df, ticker)
    if not bars:
        return {
            "ticker": ticker,
            "success": False,
            "bars": [],
            "error": "DataFrame returned zero valid bars after normalization",
        }

    return {
        "ticker": ticker,
        "success": True,
        "bars": bars,
        "error": None,
    }


def download_batch_with_retry(
    chunk_tickers: List[str],
    start_date: str,
    end_date: str,
    max_retries: int = config.MAX_RETRIES,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Downloads daily bars for a batch of <= 50 tickers using yfinance with exponential backoff.
    If the batch call fails or misses certain tickers, invokes single-ticker fallback
    to isolate failures without failing healthy tickers.
    
    Returns:
        Dict mapping canonical ticker -> list of normalized daily bar dictionaries.
    """
    if not chunk_tickers:
        return {}

    # Handle single-ticker chunk directly
    if len(chunk_tickers) == 1:
        single_res = download_single_ticker(chunk_tickers[0], start_date, end_date, max_retries)
        return {chunk_tickers[0]: single_res["bars"]}

    yf_symbols = [to_yfinance_symbol(t) for t in chunk_tickers]
    results: Dict[str, List[Dict[str, Any]]] = {t: [] for t in chunk_tickers}
    attempt = 0
    df = None
    batch_failed = False

    while attempt < max_retries:
        try:
            logger.info(f"Downloading batch of {len(chunk_tickers)} tickers (attempt {attempt + 1})...")
            df = yf.download(
                tickers=yf_symbols,
                start=start_date,
                end=end_date,
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=False,
            )
            if df is not None and not df.empty:
                break
        except Exception as e:
            logger.warning(f"Batch download attempt {attempt + 1} encountered exception: {e}")

        attempt += 1
        if attempt < max_retries:
            delay = calculate_backoff_delay(attempt, jitter=True)
            time.sleep(delay)

    if df is None or df.empty:
        logger.warning(f"Batch download failed after {max_retries} attempts. Falling back to single-ticker downloads.")
        batch_failed = True

    if not batch_failed and df is not None:
        # Multi-ticker DataFrame parsing
        is_multi_index = isinstance(df.columns, pd.MultiIndex)
        for ticker in chunk_tickers:
            yf_sym = to_yfinance_symbol(ticker)
            try:
                sub_df = None
                if is_multi_index:
                    if yf_sym in df.columns.levels[0]:
                        sub_df = df[yf_sym]
                    elif len(df.columns.levels) > 1 and yf_sym in df.columns.levels[1]:
                        sub_df = df.xs(yf_sym, axis=1, level=1)
                elif len(chunk_tickers) == 1:
                    sub_df = df
                else:
                    # Multi-ticker batch returned single-level DataFrame: ambiguous attribution
                    logger.debug(f"Batch returned single-level DataFrame; isolating {ticker} via single download.")
                    res = download_single_ticker(ticker, start_date, end_date, max_retries=1)
                    results[ticker] = res["bars"]
                    continue

                if sub_df is not None and not sub_df.empty:
                    bars = _extract_bars_from_single_df(sub_df, ticker)
                    if bars:
                        results[ticker] = bars
                    else:
                        # Fallback for empty sub_df
                        res = download_single_ticker(ticker, start_date, end_date, max_retries=1)
                        results[ticker] = res["bars"]
                else:
                    # Single-ticker fallback for missing ticker in batch
                    res = download_single_ticker(ticker, start_date, end_date, max_retries=1)
                    results[ticker] = res["bars"]
            except Exception as e:
                logger.warning(f"Error parsing {ticker} from batch ({e}). Attempting single-ticker fallback.")
                res = download_single_ticker(ticker, start_date, end_date, max_retries=1)
                results[ticker] = res["bars"]
    else:
        # Catastrophic batch failure: execute single-ticker fallback for each ticker
        for ticker in chunk_tickers:
            res = download_single_ticker(ticker, start_date, end_date, max_retries=2)
            results[ticker] = res["bars"]

    return results


def download_universe(
    tickers: List[str],
    start_date: str,
    end_date: str,
    chunk_size: int = config.BATCH_SIZE,
    rate_limit_delay: float = config.RATE_LIMIT_DELAY,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Downloads historical daily bars for an entire universe of tickers.
    Splits into 50-ticker chunks and sleeps rate_limit_delay + jitter between chunks.
    """
    all_results: Dict[str, List[Dict[str, Any]]] = {}
    chunks = chunk_tickers(tickers, chunk_size=chunk_size)
    total_chunks = len(chunks)
    logger.info(f"Total tickers: {len(tickers)}, partitioned into {total_chunks} chunks of <= {chunk_size}.")

    for idx, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {idx + 1}/{total_chunks} ({len(chunk)} tickers)...")
        chunk_results = download_batch_with_retry(chunk, start_date, end_date)
        all_results.update(chunk_results)

        # Rate-limiting inter-chunk pacing (skip after final chunk)
        if idx < total_chunks - 1 and rate_limit_delay > 0:
            pacing = rate_limit_delay + random.uniform(0.1, 0.4)
            time.sleep(pacing)

    return all_results


class YFinanceDownloader:
    """
    Object-oriented wrapper for the resilient batch downloader.
    """
    def __init__(
        self,
        batch_size: int = config.BATCH_SIZE,
        rate_limit_delay: float = config.RATE_LIMIT_DELAY,
        max_retries: int = config.MAX_RETRIES,
        backoff_base: float = config.BACKOFF_BASE,
        backoff_max: float = config.BACKOFF_MAX,
    ):
        self.batch_size = batch_size
        self.rate_limit_delay = rate_limit_delay
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max

    chunk_tickers = staticmethod(chunk_tickers)
    calculate_backoff_delay = staticmethod(calculate_backoff_delay)
    resolve_trading_friday = staticmethod(resolve_trading_friday)
    calculate_date_range = staticmethod(calculate_date_range)
    normalize_daily_bar = staticmethod(normalize_daily_bar)

    def download_batch(self, chunk: List[str], start_date: str, end_date: str) -> Dict[str, List[Dict[str, Any]]]:
        return download_batch_with_retry(chunk, start_date, end_date, self.max_retries)

    def download_universe(self, tickers: List[str], start_date: str, end_date: str) -> Dict[str, List[Dict[str, Any]]]:
        return download_universe(
            tickers,
            start_date,
            end_date,
            chunk_size=self.batch_size,
            rate_limit_delay=self.rate_limit_delay,
        )
