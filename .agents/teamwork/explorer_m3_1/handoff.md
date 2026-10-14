# Milestone 3 Handoff Report: Core Screener Engine & Indicator Math

**Author**: Explorer M3 1 (`explorer_m3_1`)  
**Date**: 2026-10-14  
**Target Milestone**: Milestone 3 — Core Screener Engine & Indicator Math  
**Assigned Focus**:
1. Daily to Weekly Resampling in Polars (Monday-Friday bounds, holiday weeks, Friday/last trading day date anchoring, 64-bit volume).
2. Indicator Mathematics in Polars (`screener/src/indicators.py`): 30-week SMA, SMA slope, 10-week prior volume average, volume surge ratio, 35-week resistance pivot.
3. Vector-Optimized Polars Implementation Blueprints, types, null handling, and 52-week warmup validation.

---

## 1. Observation

### 1.1 Weekly Resampling Engine Contract & Test Oracles
Direct inspection of `PROJECT.md`, `tests/e2e/helpers/formula_oracle.py`, and `tests/e2e/tier1_features/test_f12_f20_screener_math.py` reveals the following exact rules:
- **`PROJECT.md` line 19 & 66**:
  > "Resample Daily to Weekly (Friday close, Monday-Friday bounds)"  
  > "Vectorized Polars aggregation of daily bars to Friday-closed weekly bars"
- **`tests/e2e/helpers/formula_oracle.py` lines 12–66**:
  ```python
  # Group by ISO year and calendar week (Monday of that week)
  # Open is first day's open: bars_in_week[0]["open"]
  # High is max high in week: max(b["high"] for b in bars_in_week)
  # Low is min low in week: min(b["low"] for b in bars_in_week)
  # Close is last trading day's close (Friday or Thursday holiday): bars_in_week[-1]["close"]
  # Adj close is last trading day's adj_close: bars_in_week[-1].get("adj_close", week_close)
  # Volume is sum of daily volume: sum(b["volume"] for b in bars_in_week)
  # Last trading date represents the weekly bar timestamp: week_date = bars_in_week[-1]["trade_date"]
  # trading_days = len(bars_in_week)
  ```
- **`tests/e2e/tier1_features/test_f12_f20_screener_math.py` lines 37–81**:
  - `test_f12_01_resampling_aggregation_counts`: 5 daily bars in a standard week compress to exactly 1 weekly bar with `trading_days = 5`.
  - `test_f12_02_resampling_open_is_monday_open`: Weekly open matches the open of the first trading day of the week (`bars[0]["open"]`).
  - `test_f12_03_resampling_close_is_friday_close`: Weekly close matches the close of the last trading day of the week (`bars[-1]["close"]`).
  - `test_f12_04_resampling_high_and_low_extremes`: Weekly high is the maximum daily high; weekly low is the minimum daily low.
  - `test_f12_05_resampling_volume_summation`: Weekly volume is the sum of all trading days' volumes in that week.

### 1.2 Market Holiday & Boundary Behavior
- **`tests/e2e/tier4_scenarios/test_t4_market_holiday_resampling_flow.py` lines 16–78**:
  - Good Friday short week (Mon 2026-04-06 to Thu 2026-04-09, Friday closed):
    - Produced weekly bar has `trading_days = 4`.
    - `trade_date` is strictly Thursday `2026-04-09` (anchored to the last active trading session, NOT a synthetic holiday Friday date).
    - Close price matches Thursday close `bars[-1]["close"]`.
- **`tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py` lines 30–86**:
  - `test_t2_f12_01_single_day_holiday_week`: Week with only 1 trading day yields 1 weekly bar, `trading_days = 1`, open and close match that day.
  - `test_t2_f12_03_midweek_holiday_wednesday_closure`: 4-day week with Wednesday closed produces `trading_days = 4`, `trade_date` = Friday.
  - `test_t2_f12_04_volume_exceeding_32bit_integer`: Mega-cap volume of 3,000,000,000 shares exceeds $2^{31} - 1$ (2,147,483,647); requires 64-bit integer (`pl.Int64`).
  - `test_t2_f12_05_flat_price_high_equals_low_all_week`: Halted stock with constant price yields `high == low == open == close` and `volume == 0`.

### 1.3 30-Week SMA & Slope Formula
- **`tests/e2e/helpers/formula_oracle.py` lines 69–96**:
  ```python
  def oracle_sma(series: List[float], window: int) -> List[Optional[float]]:
      # Returns None for indices < window - 1 (indices 0..28 are None; index 29 is first SMA)
  
  def oracle_sma_slope(sma_series: List[Optional[float]], lookback: int = 1) -> List[Optional[float]]:
      # Computes percentage slope of SMA: ((SMA[t] - SMA[t-lookback]) / SMA[t-lookback]) * 100.0
      # Guards against None and division by zero (SMA[t-lookback] == 0) -> None
  ```
- **`tests/e2e/tier1_features/test_f12_f20_screener_math.py` lines 85–119**:
  - `test_f13_01_sma30_window_requires_30_periods`: Returns `None` for the first 29 periods; starts at index 29.
  - `test_f13_03_sma30_slope_positive_uptrend`: `SMA = [100.0, 101.5] -> slope = (101.5 - 100.0) / 100.0 * 100 = 1.5% > 0`.
  - `test_f13_04_sma30_slope_negative_downtrend`: `SMA = [100.0, 98.0] -> slope = -2.0% < 0`.
  - `test_f13_05_sma30_slope_flat_zero`: `SMA = [150.0, 150.0] -> slope = 0.0% >= 0`.
- **`tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py` lines 90–121**:
  - `test_t2_f13_01_exactly_29_weeks_returns_none`: 29 bars is insufficient.
  - `test_t2_f13_03_slope_division_by_zero_guard`: Prior SMA of 0.0 returns `None`.
  - `test_t2_f13_04_slope_exact_zero_meets_qualification`: Slope of `0.0000%` satisfies `slope >= 0.0`.
  - `test_t2_f13_05_slope_micro_negative_fails_qualification`: Slope of `-0.0001%` fails `slope >= 0.0`.

### 1.4 10-Week Prior Volume Average & Surge Ratio
- **`tests/e2e/helpers/formula_oracle.py` lines 99–116**:
  ```python
  def oracle_volume_surge(volumes: List[int], window: int = 10) -> Tuple[List[Optional[float]], List[Optional[float]]]:
      # For i < 10: None
      # For i >= 10: prior_10 = volumes[i - window : i]  <-- CRITICAL: EXCLUDES CURRENT WEEK i
      # avg_vol = sum(prior_10) / 10.0
      # surge = current_volume / avg_vol (if avg_vol > 0 else 0.0)
  ```
- **`tests/e2e/tier1_features/test_f12_f20_screener_math.py` lines 123–155**:
  - `test_f14_01_volume_average_window_10_weeks`: Requires 10 prior weeks (indices 0..9 are `None`; index 10 is the first non-null average).
  - `test_f14_05_volume_average_excludes_current_breakout_week`: Prior 10 weeks of 1,000,000 + Breakout week of 10,000,000 -> 10w avg remains strictly 1,000,000.0; surge ratio = 10.0x.
- **`tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py` lines 125–153**:
  - `test_t2_f14_02_prior_average_volume_zero_guard`: Prior 10 weeks volume = 0 guarded -> `avg_vol = 0.0, surge = 0.0`.
  - `test_t2_f14_03_surge_ratio_1_4999_fails_threshold`: 1.4999 fails `vol_surge >= 1.50`.
  - `test_t2_f14_04_surge_ratio_1_5000_passes_threshold`: 1.5000 passes `vol_surge >= 1.50`.

### 1.5 35-Week Prior Resistance Pivot
- **`tests/e2e/helpers/formula_oracle.py` lines 119–131**:
  ```python
  def oracle_prior_resistance_pivot(highs: List[float], lookback: int = 35) -> List[Optional[float]]:
      # For i < 35: None
      # For i >= 35: prior_highs = highs[i - lookback : i]  <-- CRITICAL: EXCLUDES CURRENT WEEK i
      # pivots.append(round(max(prior_highs), 4))
  ```
- **`tests/e2e/tier1_features/test_f12_f20_screener_math.py` lines 160–191**:
  - `test_f15_01_pivot35_lookback_window`: Requires 35 prior weeks; index 35 is the first valid value.
  - `test_f15_03_pivot35_excludes_current_week_high`: Current week breakout high is NOT included in its own resistance pivot.
  - `test_f15_04_pivot35_breakout_detection`: `close >= pivot_35w` triggers breakout.
- **`tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py` lines 157–186**:
  - `test_t2_f15_02_close_equals_resistance_pivot_exact`: `close == pivot` qualifies breakout.
  - `test_t2_f15_03_close_one_cent_below_pivot_fails`: `close = 99.99` vs `pivot = 100.00` fails.

### 1.6 Database Schema Mapping & Warmup Limits
- **`db/init.sql` lines 143–177**:
  - `screener_signals` schema requirements:
    - `sma_30w NUMERIC(12, 4) NOT NULL`
    - `sma_30w_slope NUMERIC(8, 4) NOT NULL`
    - `prior_resistance_35w NUMERIC(12, 4) NOT NULL`
    - `volume_surge_ratio NUMERIC(8, 4) NOT NULL`
    - `avg_volume_10w BIGINT NOT NULL`
    - `weekly_close NUMERIC(12, 4) NOT NULL`
    - `weekly_volume BIGINT NOT NULL`
    - `mrs_score NUMERIC(10, 4) NOT NULL` (requires 52 weeks of aligned SPY data)
- **Minimum Warmup Barrier**:
  - SMA 30w needs 30 bars; slope needs 31 bars.
  - 10w Volume surge needs 11 bars (10 prior + 1 current).
  - 35w Resistance pivot needs 36 bars (35 prior + 1 current).
  - 52w Mansfield RS needs 52 bars.
  - Therefore, the strict minimum historical warmup is **52 weekly bars** (~260 daily bars). In cold-start ingestion, StockSentinel retrieves 730 days (~104 weekly bars), satisfying this threshold.

---

## 2. Logic Chain

```
[Daily Ingestion Bars (Parquet/DB)]
         │
         ▼
[Step 1: Weekly Resampling via Polars dt.truncate("1w")]
  ├── Group by ["ticker", "week_start"] (where week_start is Monday of the ISO week)
  ├── Open = first(open), High = max(high), Low = min(low), Close = last(close)
  ├── Volume = sum(volume) cast to pl.Int64
  ├── trade_date = last(trade_date) (Thursday on Good Friday, Friday on standard week)
  └── Drop week_start, sort ascending by ["ticker", "trade_date"]
         │
         ▼
[Step 2: Vectorized Window Indicators via Shifted Lookbacks]
  ├── SMA 30w: pl.col("close").rolling_mean(window_size=30, min_periods=30)
  ├── SMA 30w Slope: ((SMA30 - SMA30.shift(1)) / SMA30.shift(1)) * 100.0
  │     └── Guarded: when(SMA30.shift(1) > 0).then(...).otherwise(None)
  ├── 10w Prior Volume Avg: pl.col("volume").shift(1).rolling_mean(10, min_periods=10)
  │     └── Excludes current week via shift(1)
  ├── Volume Surge Ratio: pl.col("volume") / avg_volume_10w
  │     └── Guarded: when(avg_vol > 0).then(volume / avg_vol).when(avg_vol == 0).then(0.0)
  └── 35w Resistance Pivot: pl.col("high").shift(1).rolling_max(35, min_periods=35)
        └── Excludes current week high via shift(1)
         │
         ▼
[Step 3: SPY Benchmark Join & Mansfield RS]
  ├── Left join stock weekly bars with SPY weekly bars on "trade_date"
  ├── RS = Stock_Close / SPY_Close
  ├── RS_SMA52 = RS.rolling_mean(52, min_periods=52)
  └── MRS = ((RS / RS_SMA52) - 1.0) * 100.0
         │
         ▼
[Step 4: Stan Weinstein Stage 2 Multi-Factor Filter]
  ├── Condition 1: close > sma_30w
  ├── Condition 2: sma_30w_slope >= 0.0
  ├── Condition 3: close >= prior_resistance_35w
  ├── Condition 4: volume_surge_ratio >= 1.50
  └── Condition 5: mrs_score > 0.0
  └── All 5 must be non-null and True simultaneously
```

### Detailed Rationale for Architectural Choices:
1. **Why `dt.truncate("1w")` for Calendar Week Grouping?**
   Using `dt.truncate("1w")` truncates any Date or Datetime to the Monday of its ISO week. This guarantees that whether a week has 5 trading days (Mon–Fri) or 4 days (Mon–Thu, Tue–Fri, or Mon, Tue, Thu, Fri), all trading days belonging to the same calendar week share the exact same `week_start` timestamp. There is no danger of partial weeks getting fragmented across month or year boundaries.
2. **Why `last(trade_date)` for the weekly bar date?**
   In financial charting (Lightweight Charts) and E2E scenario testing (`test_t4_market_holiday_resampling_flow`), a weekly candle cannot bear a trade date for a day the market was closed (e.g. Good Friday). If a holiday closes the market on Friday, the weekly bar must bear Thursday's date. Polars `pl.col("trade_date").last()` dynamically selects Friday during normal weeks and Thursday during Good Friday weeks, maintaining 100% chart continuity.
3. **Why `shift(1)` for Prior Volume and Prior Resistance Pivot?**
   - For Volume Surge: A Stage 2 breakout is defined by massive volume expanding *relative to the prior consolidation base*. If the current breakout bar's heavy volume were included in the 10-week moving average, it would inflate the denominator by 10%, diluting the surge ratio. Shifting by 1 (`volume.shift(1).rolling_mean(10)`) strictly isolates the 10 weeks *prior* to breakout.
   - For Resistance Pivot: If current week high were included, the rolling max would immediately equal the breakout high, making `close >= pivot` impossible unless close was at or above the high of the same candle. Shifting by 1 (`high.shift(1).rolling_max(35)`) ensures the pivot strictly represents the prior 35-week base ceiling.
4. **Why `pl.Int64` for Volume?**
   As demonstrated in `test_t2_f12_04_volume_exceeding_32bit_integer`, mega-cap equities can trade over 2.15 billion shares per week. Standard 32-bit signed integers overflow at 2,147,483,647. Using `pl.Int64` prevents integer overflow and matches PostgreSQL's `BIGINT` column in `screener_signals`.

---

## 3. Caveats

1. **SPY Benchmark Completeness**:
   Mansfield Relative Strength requires SPY benchmark weekly bars to exist for every trade date that target equities trade. In `screener/src/sync.py` and `universe.py`, SPY is guaranteed as the primary ticker (`ticker='SPY'`). If SPY data is missing for a particular date, a left join will yield null for `spy_close`, causing MRS to be null and preventing Stage 2 qualification for that date.
2. **First 51 Weeks Behavior (Warmup Window)**:
   Any stock with fewer than 52 weekly bars will have null MRS scores and cannot qualify for Stage 2 breakouts. This is mathematically correct according to Stan Weinstein's methodology (an unseasoned IPO with only 3 months of history cannot have an established 35-week base or 52-week relative strength trend).
3. **Dual-Class Tickers (`BRK.B`, `BF.B`)**:
   Parquet caches and database queries must preserve the canonical dotted ticker format (`BRK.B`), as standardized in Milestone 2.
4. **Read-Only Scope**:
   As Explorer 1, no source files were written or modified in `screener/src/`. The implementation blueprints provided below are ready for direct inclusion by Worker M3.

---

## 4. Conclusion & Complete Code Blueprints

### Blueprint 1: `screener/src/indicators.py`
The complete, production-ready, vector-optimized Polars blueprint for `indicators.py`:

```python
"""
screener/src/indicators.py - Vectorized Polars technical indicator calculations:
- Daily to Weekly OHLCV bar resampling with holiday handling and Friday/last-day anchoring.
- 30-week Simple Moving Average (SMA) and SMA slope percentage.
- 10-week prior volume average and volume surge ratio (>= 1.5x).
- 35-week prior resistance pivot.
- Mansfield Relative Strength (MRS) vs SPY benchmark (52-week).
"""
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
import polars as pl

logger = logging.getLogger(__name__)

# Minimum historical bars required for complete indicator warmup
MIN_WEEKLY_BARS = 52
MIN_DAILY_BARS = 260


def resample_daily_to_weekly(daily_df: pl.DataFrame) -> pl.DataFrame:
    """
    Resamples daily OHLCV bars into calendar weekly bars (Monday-Friday convention).
    
    Aggregation rules:
    - week_open: first available trading day open
    - week_high: maximum daily high in the week
    - week_low: minimum daily low in the week
    - week_close: last available trading day close
    - week_adj_close: last available trading day adj_close
    - week_volume: sum of daily volume across the week (pl.Int64)
    - trade_date: date of the last active trading session (Friday, or Thursday on holiday weeks)
    - trading_days: count of daily bars compressed into this weekly bar
    """
    if daily_df.is_empty():
        return pl.DataFrame(
            schema={
                "ticker": pl.Utf8,
                "trade_date": pl.Date,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "adj_close": pl.Float64,
                "volume": pl.Int64,
                "trading_days": pl.Int32,
            }
        )

    df = daily_df

    # Ensure trade_date is pl.Date
    if df.schema["trade_date"] != pl.Date:
        df = df.with_columns(pl.col("trade_date").cast(pl.Date))

    # Ensure adj_close column exists
    if "adj_close" not in df.columns:
        df = df.with_columns(pl.col("close").alias("adj_close"))
    else:
        df = df.with_columns(
            pl.coalesce([pl.col("adj_close"), pl.col("close")]).alias("adj_close")
        )

    # Ensure volume is Int64
    if df.schema["volume"] != pl.Int64:
        df = df.with_columns(pl.col("volume").cast(pl.Int64))

    # Sort chronologically by ticker and trade_date
    df = df.sort(["ticker", "trade_date"])

    # Truncate to Monday of the calendar week (ISO 8601 week start)
    df = df.with_columns(
        pl.col("trade_date").dt.truncate("1w").alias("week_start")
    )

    # Group by ticker and week_start, aggregating OHLCV
    weekly = (
        df.group_by(["ticker", "week_start"], maintain_order=True)
        .agg([
            pl.col("trade_date").last().alias("trade_date"),
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("adj_close").last().alias("adj_close"),
            pl.col("volume").sum().cast(pl.Int64).alias("volume"),
            pl.len().cast(pl.Int32).alias("trading_days"),
        ])
        .drop("week_start")
        .sort(["ticker", "trade_date"])
    )

    return weekly


def resample_daily_to_weekly_pylist(daily_bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convenience wrapper converting a list of daily bar dictionaries to a list of weekly bar dictionaries.
    Maintains compatibility with test oracle and non-DataFrame callers.
    """
    if not daily_bars:
        return []
    df = pl.DataFrame(daily_bars)
    weekly_df = resample_daily_to_weekly(df)
    # Format trade_date as ISO string
    formatted = weekly_df.with_columns(
        pl.col("trade_date").dt.to_string("%Y-%m-%d").alias("trade_date"),
        pl.col("open").round(4),
        pl.col("high").round(4),
        pl.col("low").round(4),
        pl.col("close").round(4),
        pl.col("adj_close").round(4),
    )
    return formatted.to_dicts()


def compute_sma_30w(df: pl.DataFrame) -> pl.DataFrame:
    """
    Computes 30-week Simple Moving Average of close.
    Requires at least 30 weekly bars. First 29 bars are null.
    """
    return df.with_columns(
        pl.col("close")
        .rolling_mean(window_size=30, min_periods=30)
        .round(4)
        .over("ticker")
        .alias("sma_30w")
    )


def compute_sma_30w_slope(df: pl.DataFrame, lookback: int = 1) -> pl.DataFrame:
    """
    Computes percentage slope of SMA 30w:
    slope = ((SMA30[t] - SMA30[t-lookback]) / SMA30[t-lookback]) * 100.0
    Guards against division by zero and nulls.
    """
    prior_sma = pl.col("sma_30w").shift(lookback).over("ticker")
    diff = pl.col("sma_30w") - prior_sma
    slope_expr = (
        pl.when(
            pl.col("sma_30w").is_not_null()
            & prior_sma.is_not_null()
            & (prior_sma != 0.0)
        )
        .then(((diff / prior_sma) * 100.0).round(4))
        .otherwise(None)
        .alias("sma_30w_slope")
    )
    return df.with_columns(slope_expr)


def compute_volume_metrics(df: pl.DataFrame, window: int = 10) -> pl.DataFrame:
    """
    Computes 10-week prior average volume (strictly excluding current week) and volume surge ratio:
    surge_ratio = current_week_volume / prior_10w_avg_volume
    Guards against zero-division (surge = 0.0 if avg_volume == 0).
    """
    prior_vol = pl.col("volume").cast(pl.Float64).shift(1).over("ticker")
    avg_vol_expr = (
        prior_vol.rolling_mean(window_size=window, min_periods=window)
        .round(2)
        .over("ticker")
        .alias("avg_volume_10w")
    )

    df_with_avg = df.with_columns(avg_vol_expr)

    surge_expr = (
        pl.when(
            pl.col("avg_volume_10w").is_not_null() & (pl.col("avg_volume_10w") > 0)
        )
        .then((pl.col("volume").cast(pl.Float64) / pl.col("avg_volume_10w")).round(4))
        .when(
            pl.col("avg_volume_10w").is_not_null() & (pl.col("avg_volume_10w") == 0)
        )
        .then(0.0)
        .otherwise(None)
        .alias("volume_surge_ratio")
    )

    return df_with_avg.with_columns(surge_expr)


def compute_resistance_pivot(df: pl.DataFrame, lookback: int = 35) -> pl.DataFrame:
    """
    Computes 35-week prior resistance pivot:
    pivot = maximum weekly high over prior 35 weeks (strictly excluding current week breakout candle).
    """
    prior_high = pl.col("high").shift(1).over("ticker")
    pivot_expr = (
        prior_high.rolling_max(window_size=lookback, min_periods=lookback)
        .round(4)
        .over("ticker")
        .alias("prior_resistance_35w")
    )
    return df.with_columns(pivot_expr)


def compute_mansfield_relative_strength(
    stock_df: pl.DataFrame,
    spy_df: pl.DataFrame,
    lookback: int = 52,
    multiplier: float = 100.0
) -> pl.DataFrame:
    """
    Computes Mansfield Relative Strength vs SPY benchmark:
    RS(t) = Stock_Close(t) / SPY_Close(t)
    RS_SMA52(t) = 52-week SMA of RS
    MRS(t) = ((RS(t) / RS_SMA52(t)) - 1.0) * multiplier (default: 100.0)
    """
    # Select SPY trade_date and close
    spy_clean = spy_df.select([
        pl.col("trade_date").cast(pl.Date),
        pl.col("close").alias("spy_close")
    ])

    stock_clean = stock_df
    if stock_clean.schema["trade_date"] != pl.Date:
        stock_clean = stock_clean.with_columns(pl.col("trade_date").cast(pl.Date))

    joined = stock_clean.join(spy_clean, on="trade_date", how="left")

    rs_expr = (
        pl.when(pl.col("spy_close").is_not_null() & (pl.col("spy_close") > 0))
        .then(pl.col("close") / pl.col("spy_close"))
        .otherwise(None)
        .alias("rs_ratio")
    )

    df_rs = joined.with_columns(rs_expr)

    rs_sma_expr = (
        pl.col("rs_ratio")
        .rolling_mean(window_size=lookback, min_periods=lookback)
        .over("ticker")
        .alias("rs_sma_52w")
    )

    df_rs_sma = df_rs.with_columns(rs_sma_expr)

    mrs_expr = (
        pl.when(
            pl.col("rs_ratio").is_not_null()
            & pl.col("rs_sma_52w").is_not_null()
            & (pl.col("rs_sma_52w") > 0)
        )
        .then(
            (((pl.col("rs_ratio") / pl.col("rs_sma_52w")) - 1.0) * multiplier).round(4)
        )
        .when(
            pl.col("rs_sma_52w").is_not_null() & (pl.col("rs_sma_52w") == 0)
        )
        .then(0.0)
        .otherwise(None)
        .alias("mrs_score")
    )

    return df_rs_sma.with_columns(mrs_expr).drop(["spy_close", "rs_ratio", "rs_sma_52w"])


def compute_all_indicators(
    weekly_df: pl.DataFrame,
    spy_weekly_df: Optional[pl.DataFrame] = None
) -> pl.DataFrame:
    """
    Orchestrates calculation of all Stan Weinstein Stage 2 indicators on a weekly Polars DataFrame:
    1. 30-week SMA
    2. 30-week SMA Slope
    3. 10-week prior Volume Average and Surge Ratio
    4. 35-week prior Resistance Pivot
    5. Mansfield Relative Strength vs SPY (if SPY provided)
    """
    df = weekly_df.sort(["ticker", "trade_date"])
    df = compute_sma_30w(df)
    df = compute_sma_30w_slope(df, lookback=1)
    df = compute_volume_metrics(df, window=10)
    df = compute_resistance_pivot(df, lookback=35)

    if spy_weekly_df is not None and not spy_weekly_df.is_empty():
        df = compute_mansfield_relative_strength(df, spy_weekly_df, lookback=52)
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("mrs_score"))

    return df
```

### Blueprint 2: `screener/src/screener.py`
Filter and classification logic matching Feature 17–19 requirements:

```python
"""
screener/src/screener.py - Stan Weinstein Stage 2 Breakout Multi-Factor Filter,
Target/Risk calculations, and deterministic Entry Status categorization.
"""
import logging
from typing import Any, Dict, List, Optional
import polars as pl

logger = logging.getLogger(__name__)


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
    1. close > sma_30w
    2. sma_30w_slope >= 0.0
    3. close >= pivot_35w
    4. vol_surge_ratio >= 1.50
    5. mrs_score > 0.0
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
    Calculates entry target, max buy price, stop loss, and distance percentage:
    - entry_price = pivot_35w
    - max_buy_price = entry_price * 1.05 (+5%)
    - stop_loss_price = swing_low if 0 < swing_low < entry_price else entry_price * 0.92 (-8%)
    - diff_pct = ((current_price - entry_price) / entry_price) * 100.0
    """
    entry_price = round(pivot_35w, 4)
    max_buy_price = round(entry_price * 1.05, 4)
    if swing_low is not None and 0 < swing_low < entry_price:
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
    stop_loss_price: float,
) -> str:
    """
    Deterministic entry status categorization:
    - current_price < stop_loss_price => STOPPED_OUT
    - current_price < entry_price => BELOW_ENTRY
    - entry_price <= current_price <= max_buy_price => IN_BUY_ZONE
    - current_price > max_buy_price => EXTENDED
    """
    if current_price < stop_loss_price:
        return "STOPPED_OUT"
    elif current_price < entry_price:
        return "BELOW_ENTRY"
    elif current_price <= max_buy_price:
        return "IN_BUY_ZONE"
    else:
        return "EXTENDED"
```

---

## 5. Verification Method

### 5.1 Test Commands & Execution Plan
Once implemented in `screener/src/indicators.py` and `screener/src/screener.py`, verify with the following standalone commands:

```bash
# 1. Run Tier 1 Core Screener Math tests (Features 12-20)
python -m unittest tests/e2e/tier1_features/test_f12_f20_screener_math.py

# 2. Run Tier 2 Indicator Boundary & Edge Case tests
python -m unittest tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py

# 3. Run Tier 3 Ingestion-to-Screener Interaction tests
python -m unittest tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py

# 4. Run Tier 4 Market Holiday Resampling Flow scenario
python -m unittest tests/e2e/tier4_scenarios/test_t4_market_holiday_resampling_flow.py

# 5. Run unified E2E test runner for feature 12-16
python tests/run_e2e.py --feature 12
python tests/run_e2e.py --feature 13
python tests/run_e2e.py --feature 14
python tests/run_e2e.py --feature 15
python tests/run_e2e.py --feature 16
```

### 5.2 Inspection Checklist
1. **Resampling**: Verify that passing a 4-day Good Friday week returns a bar with `trading_days == 4` and `trade_date == '2026-04-09'`.
2. **Prior Volume Shift**: Verify that week 10 has `avg_volume_10w` computed strictly from weeks 0–9.
3. **Prior Resistance Shift**: Verify that week 35 has `prior_resistance_35w` computed strictly from highs of weeks 0–34.
4. **Volume Type**: Verify that weekly volume is typed as `pl.Int64` (BIGINT), surviving values $> 2^{31}-1$.
5. **Warmup Gate**: Verify that `compute_all_indicators` returns null for indicators when history $< 52$ weeks and handles division-by-zero safely without throwing runtime exceptions.

### 5.3 Invalidation Conditions
- If weekly resampling anchors `trade_date` to an artificial Friday date when Friday is a market holiday, this invalidates chart continuity tests in Tier 4.
- If rolling 10-week volume average includes current week volume, this dilutes breakout surge ratios and fails `test_f14_05`.
- If rolling 35-week resistance pivot includes current week high, breakout detection will fail `test_f15_03`.
