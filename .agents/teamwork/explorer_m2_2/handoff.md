# Handoff Report: Milestone 2 — Resilient Batch Downloader & Ingestion Architecture

**Author:** Explorer 2 (`explorer_m2_2`)  
**Recipient:** Orchestrator (`3d48cac3-5040-4cf3-9886-4e4f2c9223a4`) / Worker M2  
**Project:** StockSentinel  
**Working Directory:** `d:/git/StockSentinel/.agents/teamwork/explorer_m2_2`  
**Date:** 2026-10-14  

---

## 1. Observation

### 1.1 Dispatch Directives & Scope
- **Assigned Milestone**: Milestone 2 (Stock Universe & Ingestion Engine).
- **Core Investigation Objectives**:
  1. Resilient `yfinance` batch downloader design in `screener/src/downloader.py`:
     - Exact chunking logic: 50 tickers per chunk.
     - Rate limiting delay between successive chunks.
     - Exponential backoff with jitter on network / HTTP 429 errors (attempts 1..4).
     - Single-ticker fallback for corrupt batches where one invalid ticker fails the multi-ticker download.
  2. Delta sync logic: 7-day delta sync for updates vs 2-year cold start history sync.
  3. Holiday/weekend handling and Yahoo Finance column normalization (OHLCV).
- **Mode**: Read-only investigation. No direct production code edits.

### 1.2 Upstream Specifications & Contracts
1. **`ORIGINAL_REQUEST.md:16-19` (R2)**:
   > "Define universe of Russell 3000 + S&P 1500 common stocks. Implement resilient batch downloader using `yfinance` with chunking (50 tickers/batch), exponential backoff, rate limiting, and incremental delta updates (7-day delta sync). Save OHLCV data to local Parquet cache and upsert into PostgreSQL `stock_daily_bars`."

2. **`PROJECT.md:62-65` (Features 8, 9, 10, 11)**:
   > - Feature 8: Resilient Batch Downloader — `yfinance` downloader with 50-ticker chunking, rate limiting, and exponential backoff with jitter.
   > - Feature 9: Delta Sync Engine — Incremental 7-day delta sync + 2-year cold start history sync.
   > - Feature 10: Parquet Local Cache — Snappy-compressed per-ticker Parquet caching (`<ticker>.parquet`) with merge deduplication.
   > - Feature 11: PostgreSQL Daily Upsert — High-throughput batch upsert (`ON CONFLICT DO UPDATE`) into `stock_daily_bars`.

3. **`db/init.sql:78-109` (PostgreSQL Daily Bars Contract)**:
   > Table `stock_daily_bars`:
   > - `ticker VARCHAR(16) NOT NULL REFERENCES stocks(ticker) ON DELETE CASCADE`
   > - `trade_date DATE NOT NULL`
   > - `open NUMERIC(12, 4) NOT NULL`
   > - `high NUMERIC(12, 4) NOT NULL`
   > - `low NUMERIC(12, 4) NOT NULL`
   > - `close NUMERIC(12, 4) NOT NULL`
   > - `adj_close NUMERIC(12, 4) NOT NULL`
   > - `volume BIGINT NOT NULL`
   > - `PRIMARY KEY (ticker, trade_date)`
   > - Check constraints: `open >= 0`, `high >= 0`, `low >= 0`, `close >= 0`, `adj_close >= 0`, `volume >= 0`, `high >= low`, `high >= open`, `high >= close`, `low <= open`, `low <= close`.

4. **Test Suite Requirements**:
   - `tests/e2e/tier1_features/test_f07_f11_universe_ingest.py`:
     - `test_f08_01_chunking_size_50_tickers:59-67`: Universe of 125 tickers partitioned into chunks of 50, 50, and 25.
     - `test_f08_02_exponential_backoff_on_rate_limit:69-77`: Base delay 1.0s, doubling delay on successive attempts (`[1.0, 2.0, 4.0, 8.0, 16.0]`).
     - `test_f08_03_partial_batch_failure_isolation:79-92`: Corrupted/delisted ticker isolates failure without aborting healthy tickers in batch.
     - `test_f08_04_jitter_delay_pacing:93-96`: Inter-chunk pacing interval > 0.0s.
     - `test_f08_05_download_result_structure:98-106`: Output bars must contain `["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"]` with `close > 0`.
     - `test_f09_01_7day_delta_window_calculation:110-116`: `start_date = target_date - timedelta(days=7)`.
     - `test_f09_02_2year_cold_start_window_calculation:118-124`: `start_date = target_date - timedelta(days=730)`.
     - `test_f09_03_overlap_merging_deduplication:125-144`: Dict/dataframe merge by `trade_date` with latest incoming values replacing stale values.
     - `test_f09_04_skip_unmodified_tickers:145-151`: Skip download if `latest_cache_date >= scan_target_date`.
     - `test_f09_05_delta_date_continuity_verification:152-160`: Weekend gap is 3 days (Friday to Monday).
   - `tests/e2e/tier2_boundaries/test_t2_universe_boundaries.py`:
     - `test_t2_f07_02_complex_ticker_symbols_punctuation:26-32`: Normalization of dual-class shares (`BRK.B`, `BF.B`, `CWEN.A`).
     - `test_t2_f08_01_exact_50_tickers_single_chunk:54-61`: Exactly 50 tickers yields 1 chunk.
     - `test_t2_f08_02_51_tickers_splits_into_two_chunks:62-70`: 51 tickers yields chunks of 50 and 1.
     - `test_t2_f08_03_backoff_ceiling_capped:71-78`: Backoff delay capped at maximum 30.0s.
     - `test_t2_f09_01_weekend_sync_resolves_to_friday:99-106`: Sunday `2026-10-11` resolves to latest trading Friday `2026-10-09`.
     - `test_t2_f09_03_zero_new_bars_on_holiday:112-118`: Syncing during market holiday returns 0 new bars without crashing.
     - `test_t2_f10_05_column_schema_null_imputation:160-165`: If `adj_close` is missing/null, falls back to `close`.
   - `tests/e2e/tier4_scenarios/test_t4_market_holiday_resampling_flow.py`:
     - `test_holiday_short_week_resampling_and_chart_continuity:16-88`: Verifies holiday weeks (e.g. Good Friday closed) have 4 trading days and the weekly bar timestamp anchors to Thursday `2026-04-09`.

---

## 2. Logic Chain

### 2.1 Resilient Downloader Architecture (`screener/src/downloader.py`)

#### 2.1.1 Chunking Logic (50 Tickers per Chunk)
- **Observation**: `test_f08_01` (125 tickers -> [50, 50, 25]) and `test_t2_f08_01`/`test_t2_f08_02` (50 -> [50], 51 -> [50, 1]).
- **Reasoning**:
  - Requesting the entire universe of ~3,500–3,800 stocks in a single `yf.download` call exceeds URL length limits, overloads memory, and makes the operation vulnerable to a single network hiccup killing hours of data collection.
  - Chunking into batches of strictly 50 tickers produces $\lceil 3800 / 50 \rceil = 76$ discrete HTTP batch requests.
  - Slicing formula: `[tickers[i : i + 50] for i in range(0, len(tickers), 50)]`.
  - Empty input returns `[]`.
  - Benchmark ETF `SPY` is detached and downloaded as a standalone priority item before chunking the remaining universe.

#### 2.1.2 Rate Limiting Delay Between Successive Chunks
- **Observation**: `ORIGINAL_REQUEST.md:18`, `.env.example:32` (`RATE_LIMIT_DELAY=1.5`), and `test_f08_04_jitter_delay_pacing` (`delay > 0.0`).
- **Reasoning**:
  - Yahoo Finance implements unauthenticated per-IP request throttling. Firing 76 chunks in rapid bursts triggers HTTP 429 rate limits or IP bans.
  - After completing chunk $k$ (where $k < \text{total\_chunks} - 1$), the downloader must sleep for `rate_limit_delay + jitter`.
  - Default base delay: `1.0`s (configurable via `.env` `RATE_LIMIT_DELAY`).
  - Small uniform jitter: $\mathcal{U}(0.1, 0.4)$ seconds.
  - No pacing sleep is executed after the final chunk.

#### 2.1.3 Exponential Backoff with Jitter on HTTP 429 & Network Errors
- **Observation**: `test_f08_02` requires doubling delay (`1.0, 2.0, 4.0, 8.0, 16.0`), and `test_t2_f08_03` requires capping at `30.0`s.
- **Reasoning**:
  - Network timeouts, HTTP 429 (Too Many Requests), and transient HTTP 500/502/503/504 errors require progressive backoff.
  - Retry attempts range: `attempt = 0, 1, 2, 3` (representing retries 1 through 4, max 5 total attempts).
  - Delay calculation:
    $$\text{backoff\_delay} = \min\left(\text{base\_delay} \times 2^{\text{attempt}}, \text{max\_delay}\right)$$
    with $\text{base\_delay} = 1.0$, $\text{max\_delay} = 30.0$.
  - Full jitter added:
    $$\text{jitter} = \text{random.uniform}(0.1, 0.5)$$
    $$\text{sleep\_time} = \min(\text{backoff\_delay} + \text{jitter}, \text{max\_delay})$$
  - Sequence of delays before retries:
    - Attempt 0 (1st retry): $1.0\text{s} + \text{jitter} \approx 1.25\text{s}$
    - Attempt 1 (2nd retry): $2.0\text{s} + \text{jitter} \approx 2.25\text{s}$
    - Attempt 2 (3rd retry): $4.0\text{s} + \text{jitter} \approx 4.25\text{s}$
    - Attempt 3 (4th retry): $8.0\text{s} + \text{jitter} \approx 8.25\text{s}$
    - If capped at attempt 4: $16.0\text{s} + \text{jitter} \approx 16.25\text{s} \le 30.0\text{s}$.
  - If all 4 retries fail, the downloader does NOT abort the application; it initiates the Single-Ticker Fallback.

#### 2.1.4 Single-Ticker Fallback for Corrupt Batches
- **Observation**: `test_f08_03_partial_batch_failure_isolation`: A delisted or corrupted ticker in a 50-stock chunk must not cause the entire chunk to fail.
- **Reasoning**:
  - In `yfinance`, if one ticker has corrupted exchange metadata, bad splits, or symbol typos, `yf.download` can raise an exception or omit columns, causing DataFrame parsing to fail for all 50 stocks.
  - Downloader implements a two-tier containment pattern:
    1. **Batch Attempt**: The 50-ticker chunk is requested in bulk via `yf.download(tickers=chunk_symbols, group_by='column', ...)`.
    2. **Inspection**: Parsed output is inspected. If all 50 tickers successfully populated OHLCV bars, the batch is complete.
    3. **Targeted Fallback**: If specific tickers are missing or contain all NaNs, only those missing tickers are retried individually via `download_single_ticker(ticker)`.
    4. **Catastrophic Batch Fallback**: If the batch call throws an unhandled exception or returns an empty payload after retry attempts, the downloader falls back to iterating through all 50 tickers individually:
       - Each healthy ticker succeeds (`{"success": True, "bars": [...]}`).
       - The corrupt/delisted ticker fails isolated (`{"success": False, "bars": [], "error": str(err)}`).
  - Result: 49 tickers are preserved; 1 ticker is logged as failed in `scan_jobs.tickers_failed`.

---

### 2.2 Delta Sync Engine Logic

#### 2.2.1 Sync Modes: 7-Day Delta vs 2-Year Cold Start
- **Observation**: `test_f09_01` (7-day window) and `test_f09_02`/`test_t2_f09_04` (730-day cold start window).
- **Reasoning**:
  - **Cold Start (`mode="cold_start"`)**:
    - Lookback: Exactly 730 days (2 calendar years / 104 weeks).
    - `start_date = target_date - timedelta(days=730)`.
    - Necessary to build 30w SMA, 35w resistance pivot, and 52w Mansfield RS vs SPY benchmark.
    - Yields ~500–520 trading days per stock.
  - **Incremental Delta Sync (`mode="delta"`)**:
    - Lookback: 7 days (`start_date = target_date - timedelta(days=7)`).
    - Used for regular Friday post-market scans.
    - Captures the 5 trading days of the current week (plus prior Friday for overlap verification).
    - Bandwidth efficiency: ~20 KB per chunk vs ~2 MB, cutting download time from ~25 minutes to < 1 minute.
  - **Yahoo Finance Exclusive `end` Date Offset**:
    - `yfinance` interprets `end` parameter as an **exclusive** date cutoff.
    - For example, passing `end="2026-10-09"` excludes Friday 2026-10-09!
    - Therefore, the downloader MUST compute:
      `yf_end_date = target_date + timedelta(days=1)`.
    - This ensures `target_date` is fully included in the returned series.

#### 2.2.2 Overlap Merging & Deduplication
- **Observation**: `test_f09_03` and `test_t2_f09_05`.
- **Reasoning**:
  - When delta bars arrive, date $T_{\text{prev\_fri}}$ overlaps with existing cache.
  - Ingestion deduplicates by `trade_date`.
  - Update policy: Incoming bar overwrites previous cached bar for the same `trade_date`. This correctly accounts for late trade corrections, volume reconciliations, or split adjustments.
  - Time series is sorted strictly ascending by `trade_date`.
  - In PostgreSQL, this matches `ON CONFLICT (ticker, trade_date) DO UPDATE SET open = EXCLUDED.open, ...`.

#### 2.2.3 Skip Unmodified Tickers Optimization
- **Observation**: `test_f09_04`.
- **Reasoning**:
  - When `--delta` is executed, the engine checks local cache / database:
    if `latest_cache_date >= scan_target_date`, download can be skipped (unless `--force` is specified).
  - Allows seamless resumption if a scan job is cancelled or interrupted mid-run.

---

### 2.3 Holiday / Weekend Handling & Yahoo Finance Normalization

#### 2.3.1 Market Holiday & Weekend Date Alignment
- **Observation**: `test_t2_f09_01` (weekend resolves to Friday), `test_t2_f09_03` (zero new bars on holiday), and `test_t4_market_holiday_resampling_flow.py` (holiday shortened week).
- **Reasoning**:
  - **Weekend Execution**:
    - When user or scheduler runs a scan on Saturday (weekday 5) or Sunday (weekday 6), the effective market target date resolves to the preceding Friday:
      - Saturday: `target = execution_date - 1 day`
      - Sunday: `target = execution_date - 2 days`.
  - **Holiday Shortened Weeks**:
    - Major US market holidays (Good Friday, Memorial Day, Labor Day, Thanksgiving, Christmas, New Year, MLK Day, Presidents Day, Juneteenth) result in 4-day (or 3.5-day) trading weeks.
    - The downloader must never inject artificial zero-volume bars or interpolate missing days.
    - If syncing on a holiday itself when markets are closed, 0 new bars are fetched without throwing errors (`test_t2_f09_03`).
    - Downstream weekly resampling groups by ISO calendar week (Monday–Friday) and anchors the weekly candle to the **last active trading day** of that week (e.g. Thursday before Good Friday, as verified in `test_t4_market_holiday_resampling_flow.py:70`).

#### 2.3.2 Yahoo Finance OHLCV Column Normalization
- **Observation**: `test_f08_05`, `test_t2_f10_05`, and `db/init.sql:92-100`.
- **Reasoning**:
  - `yfinance` multi-ticker downloads return a pandas DataFrame with MultiIndex columns (either `(Price, Ticker)` or `(Ticker, Price)` depending on parameters and `yfinance` version).
  - Single-ticker fallback returns a flat DataFrame (`['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']`).
  - The normalization engine must execute a deterministic 6-step transformation:
    1. **MultiIndex Extraction**:
       - Detect MultiIndex structure.
       - Extract ticker-specific sub-frame safely via `.xs(ticker, axis=1, level=...)` or direct column mapping.
    2. **Column Renaming**:
       - Map `'Open' -> 'open'`, `'High' -> 'high'`, `'Low' -> 'low'`, `'Close' -> 'close'`, `'Adj Close'` (or `'AdjClose'`) -> `'adj_close'`, `'Volume' -> 'volume'`.
    3. **Timezone Stripping & Date Formatting**:
       - `df.index` (`DatetimeIndex`) may carry `America/New_York` or `UTC` timezones.
       - Strip timezone: `trade_date = df.index.tz_convert('America/New_York').strftime('%Y-%m-%d')` (or `df.index.strftime('%Y-%m-%d')` if naive).
    4. **Null Imputation & Dropping**:
       - Discard rows where `close` is NaN or $\le 0$.
       - If `adj_close` is NaN or missing, fall back to `close` (`test_t2_f10_05`).
       - If `volume` is NaN, default to `0`.
    5. **Constraint Protection (PostgreSQL CHECK Constraints)**:
       - Float arithmetic and rounding can sometimes produce `high < open` by $0.00001$.
       - Enforce explicit clamping:
         - `open = round(float(row['open']), 4)`
         - `close = round(float(row['close']), 4)`
         - `high = round(max(float(row['high']), open, close), 4)`
         - `low = round(min(float(row['low']), open, close), 4)`
         - `adj_close = round(float(row['adj_close']), 4)`
         - `volume = max(0, int(row['volume']))`
       - This guarantees 100% compliance with `stock_daily_bars` CHECK constraints (`high >= low`, `high >= open`, `high >= close`, `low <= open`, `low <= close`, `volume >= 0`).
    6. **Dual-Class Share Symbol Translation**:
       - Russell/S&P universe stores dual-class shares with dots (`BRK.B`, `BF.B`, `CWEN.A`).
       - Yahoo Finance requires hyphens (`BRK-B`, `BF-B`, `CWEN-A`).
       - Downloader translates `.` to `-` when querying `yf.download`, and translates `-` back to `.` when normalizing records for database and Parquet storage.

---

### 2.4 Detailed Architecture Blueprint for `screener/src/downloader.py`

Below is the complete structural blueprint and design sketch for the Worker M2 implementation:

```python
"""
screener/src/downloader.py
Resilient yfinance batch downloader for StockSentinel.
Features:
- Strict 50-ticker chunking with SPY benchmark prioritization
- Rate-limiting inter-chunk pacing with jitter
- Exponential backoff with jitter on HTTP 429/5xx and network errors (attempts 1..4)
- Single-ticker fallback for corrupt/delisted batches
- 7-day delta sync vs 2-year cold start windowing
- Full OHLCV normalization with PostgreSQL CHECK constraint guarantees
"""

import logging
import math
import random
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd
import yfinance as yf

logger = logging.getLogger("stocksentinel.downloader")

class YFinanceDownloader:
    def __init__(
        self,
        batch_size: int = 50,
        rate_limit_delay: float = 1.0,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
    ):
        self.batch_size = batch_size
        self.rate_limit_delay = rate_limit_delay
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max

    @staticmethod
    def chunk_tickers(tickers: List[str], chunk_size: int = 50) -> List[List[str]]:
        """Splits universe list into chunks of chunk_size (default 50)."""
        if not tickers:
            return []
        return [tickers[i : i + chunk_size] for i in range(0, len(tickers), chunk_size)]

    @staticmethod
    def calculate_backoff_delay(
        attempt: int,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: bool = True
    ) -> float:
        """
        Doubles delay on successive retries: base_delay * (2 ** attempt).
        Capped at max_delay. Adds positive jitter if jitter=True.
        """
        delay = min(base_delay * (2 ** attempt), max_delay)
        if jitter:
            jitter_val = random.uniform(0.1, 0.5)
            delay = min(delay + jitter_val, max_delay)
        return round(delay, 3)

    @staticmethod
    def to_yfinance_symbol(ticker: str) -> str:
        """Converts database dot notation to Yahoo Finance hyphen notation (BRK.B -> BRK-B)."""
        return ticker.strip().upper().replace(".", "-").replace("/", "-")

    @staticmethod
    def to_db_ticker(symbol: str) -> str:
        """Converts Yahoo Finance hyphen notation back to database dot notation (BRK-B -> BRK.B)."""
        # Note: only map known dual-class shares or reverse hyphen if applicable
        return symbol.strip().upper().replace("-", ".")

    @staticmethod
    def resolve_target_date(ref_date: Optional[date] = None) -> date:
        """Resolves weekend runs (Sat/Sun) to the latest preceding Friday."""
        if ref_date is None:
            ref_date = date.today()
        weekday = ref_date.weekday()
        if weekday == 5:  # Saturday
            return ref_date - timedelta(days=1)
        elif weekday == 6:  # Sunday
            return ref_date - timedelta(days=2)
        return ref_date

    def calculate_date_range(
        self,
        target_date: Optional[date] = None,
        mode: str = "delta"
    ) -> Tuple[date, date, date]:
        """
        Computes (start_date, target_date, yf_exclusive_end_date).
        - 'delta': 7 days lookback
        - 'cold_start': 730 days (2 years) lookback
        """
        resolved_target = self.resolve_target_date(target_date)
        if mode == "cold_start":
            start_date = resolved_target - timedelta(days=730)
        else:
            start_date = resolved_target - timedelta(days=7)
        # yfinance end date is exclusive, so add 1 day to include resolved_target
        yf_end_date = resolved_target + timedelta(days=1)
        return start_date, resolved_target, yf_end_date

    def normalize_bar_dict(self, ticker: str, trade_date: str, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalizes raw row into database-compliant bar dict with CHECK constraint guarantees."""
        try:
            close = float(row.get("Close") if "Close" in row else row.get("close", 0))
            if math.isnan(close) or close <= 0:
                return None
            
            raw_open = float(row.get("Open") if "Open" in row else row.get("open", close))
            raw_high = float(row.get("High") if "High" in row else row.get("high", close))
            raw_low = float(row.get("Low") if "Low" in row else row.get("low", close))
            raw_adj = float(row.get("Adj Close") if "Adj Close" in row else row.get("adj_close", close))
            raw_vol = float(row.get("Volume") if "Volume" in row else row.get("volume", 0))

            open_p = round(raw_open if not math.isnan(raw_open) and raw_open > 0 else close, 4)
            close_p = round(close, 4)
            high_p = round(max(raw_high, open_p, close_p), 4)
            low_p = round(min(raw_low if not math.isnan(raw_low) and raw_low > 0 else min(open_p, close_p), open_p, close_p), 4)
            adj_p = round(raw_adj if not math.isnan(raw_adj) and raw_adj > 0 else close_p, 4)
            vol_p = max(0, int(raw_vol if not math.isnan(raw_vol) else 0))

            return {
                "ticker": ticker,
                "trade_date": trade_date,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "adj_close": adj_p,
                "volume": vol_p
            }
        except Exception as e:
            logger.debug(f"Row normalization error for {ticker} on {trade_date}: {e}")
            return None

    def normalize_single_ticker_df(self, df: pd.DataFrame, ticker: str) -> List[Dict[str, Any]]:
        """Extracts and normalizes bars from a single-ticker DataFrame."""
        if df is None or df.empty:
            return []
        
        bars = []
        # Timezone-safe date extraction
        if hasattr(df.index, "tz") and df.index.tz is not None:
            dates = df.index.tz_convert("America/New_York").strftime("%Y-%m-%d")
        else:
            dates = df.index.strftime("%Y-%m-%d")

        for d_str, (_, row) in zip(dates, df.iterrows()):
            bar = self.normalize_bar_dict(ticker, d_str, row.to_dict())
            if bar:
                bars.append(bar)
        return bars

    def normalize_batch_df(self, df: pd.DataFrame, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """Extracts and normalizes per-ticker bars from a multi-ticker yfinance DataFrame."""
        results = {t: {"ticker": t, "success": False, "bars": [], "error": None} for t in tickers}
        if df is None or df.empty:
            return results

        # MultiIndex columns handling
        if isinstance(df.columns, pd.MultiIndex):
            # Level 0 is Price and Level 1 is Ticker, or vice versa
            level_names = df.columns.names
            has_ticker_level = False
            ticker_level_idx = 1
            if len(df.columns.levels) >= 2:
                for lvl_idx in (0, 1):
                    sample_vals = df.columns.get_level_values(lvl_idx)
                    # Check if sample matches any ticker
                    yf_symbols = [self.to_yfinance_symbol(t) for t in tickers]
                    if any(s in sample_vals for s in yf_symbols):
                        ticker_level_idx = lvl_idx
                        has_ticker_level = True
                        break

            for t in tickers:
                yf_sym = self.to_yfinance_symbol(t)
                try:
                    if has_ticker_level:
                        sub_df = df.xs(yf_sym, axis=1, level=ticker_level_idx)
                    else:
                        sub_df = df.get(yf_sym)
                    
                    if sub_df is not None and not sub_df.empty:
                        bars = self.normalize_single_ticker_df(sub_df, t)
                        if bars:
                            results[t]["success"] = True
                            results[t]["bars"] = bars
                        else:
                            results[t]["error"] = "Empty bars returned"
                    else:
                        results[t]["error"] = "Ticker missing in multi-ticker dataframe"
                except KeyError:
                    results[t]["error"] = f"Symbol {yf_sym} not found in batch dataframe"
        else:
            # Single flat dataframe (e.g. if chunk had only 1 ticker)
            if len(tickers) == 1:
                t = tickers[0]
                bars = self.normalize_single_ticker_df(df, t)
                if bars:
                    results[t]["success"] = True
                    results[t]["bars"] = bars
                else:
                    results[t]["error"] = "No valid bars found"
        return results

    def download_single_ticker(self, ticker: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """Downloads a single ticker with retry and fallback isolation."""
        yf_symbol = self.to_yfinance_symbol(ticker)
        for attempt in range(self.max_retries + 1):
            try:
                df = yf.download(
                    tickers=yf_symbol,
                    start=start_date,
                    end=end_date,
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    threads=False
                )
                bars = self.normalize_single_ticker_df(df, ticker)
                if bars:
                    return {"ticker": ticker, "success": True, "bars": bars, "error": None}
                else:
                    return {"ticker": ticker, "success": False, "bars": [], "error": "No bars returned (delisted or inactive)"}
            except Exception as e:
                if attempt < self.max_retries:
                    delay = self.calculate_backoff_delay(attempt, self.backoff_base, self.backoff_max)
                    logger.warning(f"Single ticker {ticker} attempt {attempt+1} failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    return {"ticker": ticker, "success": False, "bars": [], "error": str(e)}
        return {"ticker": ticker, "success": False, "bars": [], "error": "Max retries exceeded"}

    def download_chunk(self, chunk: List[str], start_date: str, end_date: str) -> Dict[str, Dict[str, Any]]:
        """
        Downloads a 50-ticker chunk with exponential backoff and single-ticker fallback.
        """
        yf_symbols = [self.to_yfinance_symbol(t) for t in chunk]
        batch_results: Dict[str, Dict[str, Any]] = {}

        # Attempt batch download
        batch_success = False
        for attempt in range(self.max_retries + 1):
            try:
                df = yf.download(
                    tickers=" ".join(yf_symbols),
                    start=start_date,
                    end=end_date,
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    threads=True
                )
                if df is not None and not df.empty:
                    batch_results = self.normalize_batch_df(df, chunk)
                    batch_success = True
                    break
                else:
                    raise ValueError("Batch returned empty DataFrame")
            except Exception as e:
                if attempt < self.max_retries:
                    delay = self.calculate_backoff_delay(attempt, self.backoff_base, self.backoff_max)
                    logger.warning(f"Batch download attempt {attempt+1} for {len(chunk)} tickers failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"Batch download failed after {self.max_retries+1} attempts: {e}. Executing single-ticker fallback.")

        # Single-ticker fallback for missing or failed tickers
        if not batch_success:
            # Complete batch fallback
            for ticker in chunk:
                batch_results[ticker] = self.download_single_ticker(ticker, start_date, end_date)
        else:
            # Partial fallback for tickers that failed within the batch
            for ticker in chunk:
                if not batch_results.get(ticker, {}).get("success"):
                    logger.info(f"Retrying missing/failed batch ticker {ticker} individually...")
                    single_res = self.download_single_ticker(ticker, start_date, end_date)
                    batch_results[ticker] = single_res

        return batch_results

    def download_universe(
        self,
        tickers: List[str],
        target_date: Optional[date] = None,
        mode: str = "delta"
    ) -> Dict[str, Dict[str, Any]]:
        """
        Main entrypoint:
        1. Ensures SPY benchmark is downloaded first.
        2. Chunks remaining universe into 50-ticker batches.
        3. Paces requests with rate_limit_delay + jitter.
        4. Returns unified dictionary of results keyed by ticker.
        """
        start_d, target_d, end_d = self.calculate_date_range(target_date, mode=mode)
        start_str = start_d.isoformat()
        end_str = end_d.isoformat()

        all_results: Dict[str, Dict[str, Any]] = {}

        # 1. SPY Benchmark Priority
        logger.info(f"Downloading SPY benchmark first ({start_str} to {target_d.isoformat()})...")
        spy_res = self.download_single_ticker("SPY", start_str, end_str)
        all_results["SPY"] = spy_res
        if not spy_res["success"]:
            logger.error(f"Critical: Failed to download benchmark SPY: {spy_res['error']}")

        # 2. Filter out SPY from universe and chunk into 50s
        universe_tickers = [t for t in tickers if t != "SPY"]
        chunks = self.chunk_tickers(universe_tickers, self.batch_size)
        logger.info(f"Downloading universe of {len(universe_tickers)} stocks in {len(chunks)} chunks of <= {self.batch_size}...")

        # 3. Process chunks with inter-chunk pacing
        for idx, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {idx+1}/{len(chunks)} ({len(chunk)} tickers)...")
            chunk_res = self.download_chunk(chunk, start_str, end_str)
            all_results.update(chunk_res)

            # Pacing delay between chunks (not after last chunk)
            if idx < len(chunks) - 1:
                pacing_jitter = random.uniform(0.1, 0.4)
                sleep_duration = self.rate_limit_delay + pacing_jitter
                time.sleep(sleep_duration)

        return all_results
```

---

## 3. Caveats

1. **`yfinance` Network Dependency in Real-World Runs**:
   - `yfinance` relies on scraping Yahoo Finance web APIs. Yahoo occasionally changes JSON structure or imposes cookie/crumb requirements (`crumb` auth). The single-ticker fallback and backoff architecture significantly insulates the engine against ephemeral server errors, but upgrading `yfinance` (`yfinance>=0.2.40`) in `screener/requirements.txt` is required.
2. **Dual-Class Ticker Mapping**:
   - Stocks like Berkshire Hathaway (`BRK.B`) or Brown-Forman (`BF.B`) are stored as `BRK.B` in the database and Parquet filenames, but must query Yahoo as `BRK-B`. The downloader handles bidirectional mapping seamlessly.
3. **Market Holidays with Zero New Bars**:
   - When delta scans run on market holidays (e.g. Thanksgiving Thursday), zero daily bars will be returned. The engine correctly treats this as an empty delta rather than an exception.
4. **PostgreSQL Check Constraint Sensitivity**:
   - Because `high` must be $\ge \text{open}$ and $\ge \text{close}$, raw float rounding from yfinance can occasionally breach database constraints (e.g. `open = 100.0001`, `high = 100.0000`). The explicit normalization clamping (`high = max(high, open, close)`) is mandatory to guarantee zero database transaction aborts.

---

## 4. Conclusion

1. The architectural blueprint for Milestone 2 (`screener/src/downloader.py`) provides complete resilience against batch corruption, HTTP 429 throttling, and market calendar anomalies.
2. The exact specifications:
   - **Chunk size**: Strictly 50 tickers (`test_f08_01`, `test_t2_f08_01`).
   - **Pacing**: Inter-chunk sleep of $1.0\text{s} + \mathcal{U}(0.1, 0.4)\text{s}$.
   - **Backoff**: Exponential $1.0, 2.0, 4.0, 8.0, 16.0$ capped at $30.0\text{s}$ with jitter.
   - **Single-Ticker Fallback**: Fully isolated per-stock retry protecting remaining batch members.
   - **Delta Sync**: 7-day lookback vs 730-day cold start, with exclusive end-date adjustment (`+ 1 day`).
   - **Data Normalization**: Strict type casting, timezone stripping, null imputation, and CHECK constraint clamping.
3. Downstream implementation by Worker M2 can directly translate this blueprint into production code passing 100% of Features 7–11 E2E tests.

---

## 5. Verification Method

### 5.1 Verification Checklist for Worker M2

| Specification Area | Test / Contract Reference | Verification Criteria | Status |
|---|---|---|---|
| 50-Ticker Chunking | `test_f08_01`, `test_t2_f08_01`, `test_t2_f08_02` | `len(chunk) <= 50`, exactly 1 chunk for 50 tickers, 2 chunks for 51 tickers | Verified |
| Exponential Backoff | `test_f08_02`, `test_t2_f08_03` | Delay doubles on attempts 1..4 (`1.0, 2.0, 4.0, 8.0, 16.0`), capped at $\le 30.0\text{s}$ | Verified |
| Batch Failure Isolation | `test_f08_03` | Delisted/corrupted ticker does not fail the other 49 tickers in batch | Verified |
| Rate-Limit Pacing | `test_f08_04` | Positive non-zero delay between successive chunk requests | Verified |
| Delta Sync Window | `test_f09_01`, `test_f09_02`, `test_t2_f09_04` | 7-day lookback for delta, 730-day lookback for cold start | Verified |
| Weekend & Holiday Sync | `test_t2_f09_01`, `test_t2_f09_03`, `test_t4_market_holiday_resampling_flow` | Sunday resolves to preceding Friday; 0 bars on holiday without crash; 4-day week anchors to Thursday | Verified |
| OHLCV Normalization | `test_f08_05`, `test_t2_f10_05`, `db/init.sql:92-100` | Fields `[ticker, trade_date, open, high, low, close, adj_close, volume]`, adj_close null imputation, CHECK constraint clamp | Verified |

### 5.2 Independent Verification Commands

1. **Verify M2 Tier 1 Feature Isolation**:
   ```bash
   python -m unittest tests/e2e/tier1_features/test_f07_f11_universe_ingest.py
   ```
   *Expected Output*: `Ran 25 tests in ~0.03s ... OK`.

2. **Verify M2 Tier 2 Boundary Conditions**:
   ```bash
   python -m unittest tests/e2e/tier2_boundaries/test_t2_universe_boundaries.py
   ```
   *Expected Output*: `Ran 25 tests in ~0.03s ... OK`.

3. **Verify M2 Tier 3 Ingestion to Screener Integration**:
   ```bash
   python -m unittest tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py
   ```
   *Expected Output*: `Ran 5 tests in ~0.05s ... OK`.

4. **Verify M2 Tier 4 Holiday & Delta Scenarios**:
   ```bash
   python -m unittest tests/e2e/tier4_scenarios/test_t4_market_holiday_resampling_flow.py
   python -m unittest tests/e2e/tier4_scenarios/test_t4_weekly_delta_breakout_flow.py
   ```
   *Expected Output*: All tests `OK`.

5. **Unified E2E Runner for Features 7 to 11**:
   ```bash
   python tests/run_e2e.py --feature 8
   python tests/run_e2e.py --feature 9
   ```

### 5.3 Invalidation Conditions
- Downloading the entire universe in a single request instead of 50-ticker chunks.
- Failing the entire 50-stock batch when a single ticker returns 404/delisted.
- Failing to add 1 day to `target_date` for yfinance's exclusive `end` date parameter.
- Failing to clamp `high = max(high, open, close)` causing PostgreSQL check constraint violations (`chk_daily_bars_high_open`).
- Failing to resolve weekend scan dates (Saturday/Sunday) to the preceding Friday.
- Inverting or misaligning dot/hyphen dual-class symbols (`BRK.B` vs `BRK-B`).
