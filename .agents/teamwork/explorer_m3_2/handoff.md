# Handoff Report: Milestone 3 Core Screener Engine & Indicator Math

**Summary**: This report delivers an exhaustive, mathematically rigorous, and architecture-complete specification and implementation blueprint for Milestone 3 (Core Screener Engine & Indicator Math). It formalizes Mansfield Relative Strength vs SPY, Stan Weinstein Stage 2 multi-factor breakout criteria, target/risk formulas, deterministic entry status classification, and provides concrete blueprints for `screener/src/indicators.py` and `screener/src/screener.py`.

---

## 1. Observation

Direct observations from the project codebase, database schema, test suites, and reference oracle:

### 1.1 Reference Math Oracle (`tests/e2e/helpers/formula_oracle.py`)
- **Mansfield Relative Strength vs SPY** (Lines 133–167):
  ```python
  def oracle_mansfield_relative_strength(stock_closes: List[float], spy_closes: List[float], lookback: int = 52) -> List[Optional[float]]:
      if len(stock_closes) != len(spy_closes):
          raise ValueError(f"Stock length {len(stock_closes)} != SPY length {len(spy_closes)}")
      rs_series = []
      for s_close, spy_close in zip(stock_closes, spy_closes):
          if spy_close <= 0:
              rs_series.append(0.0)
          else:
              rs_series.append(s_close / spy_close)
      mrs_series = []
      for i in range(len(rs_series)):
          if i < lookback - 1:
              mrs_series.append(None)
          else:
              window_rs = rs_series[i - lookback + 1 : i + 1]
              rs_sma = sum(window_rs) / float(lookback)
              if rs_sma <= 0:
                  mrs_series.append(0.0)
              else:
                  mrs = ((rs_series[i] / rs_sma) - 1.0) * 100.0
                  mrs_series.append(round(mrs, 4))
      return mrs_series
  ```
- **Stan Weinstein Stage 2 Multi-Factor Filter** (Lines 169–208):
  ```python
  def oracle_stage2_filter(close: float, sma_30w: Optional[float], sma_30w_slope: Optional[float], pivot_35w: Optional[float], vol_surge_ratio: Optional[float], mrs_score: Optional[float]) -> Dict[str, any]:
      cond_close_above_sma = (sma_30w is not None) and (close > sma_30w)
      cond_sma_rising = (sma_30w_slope is not None) and (sma_30w_slope >= 0.0)
      cond_pivot_breakout = (pivot_35w is not None) and (close >= pivot_35w)
      cond_volume_surge = (vol_surge_ratio is not None) and (vol_surge_ratio >= 1.5)
      cond_mrs_positive = (mrs_score is not None) and (mrs_score > 0.0)
      is_stage2 = (cond_close_above_sma and cond_sma_rising and cond_pivot_breakout and cond_volume_surge and cond_mrs_positive)
      return {
          "is_stage2": is_stage2,
          "cond_close_above_sma": cond_close_above_sma,
          "cond_sma_rising": cond_sma_rising,
          "cond_pivot_breakout": cond_pivot_breakout,
          "cond_volume_surge": cond_volume_surge,
          "cond_mrs_positive": cond_mrs_positive
      }
  ```
- **Target & Risk Math** (Lines 210–239):
  ```python
  def oracle_target_and_risk(pivot_35w: float, current_price: float, swing_low: Optional[float] = None) -> Dict[str, float]:
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
          "diff_pct": diff_pct
      }
  ```
- **Entry Status Categorization** (Lines 240–262):
  ```python
  def oracle_entry_status(current_price: float, entry_price: float, max_buy_price: float, stop_loss_price: float) -> str:
      if current_price < stop_loss_price:
          return "STOPPED_OUT"
      elif current_price < entry_price:
          return "BELOW_ENTRY"
      elif current_price <= max_buy_price:
          return "IN_BUY_ZONE"
      else:
          return "EXTENDED"
  ```

### 1.2 Isolation & Boundary Test Suites (`tests/e2e/tier1_features/test_f12_f20_screener_math.py` & `tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py`)
- **Lookback threshold for MRS**: Index 0 to 50 (first 51 periods) must return `None`; index 51 (week 52) returns the first float (`test_f16_01`, `test_t2_f16_01`).
- **Zero-line crossover**: MRS of `0.0000` evaluates to `False` under `mrs_score > 0.0`; `0.0001` evaluates to `True` (`test_t2_f16_02`, `test_t2_f16_03`).
- **Slope zero boundary**: Slope `0.0` evaluates to `True` under `slope >= 0.0`; `-0.0001` evaluates to `False` (`test_t2_f13_04`, `test_t2_f13_05`).
- **Volume surge boundary**: Surge `1.4999` evaluates to `False`; `1.5000` evaluates to `True` under `vol_surge >= 1.50` (`test_t2_f14_03`, `test_t2_f14_04`).
- **Pivot exclusion**: Current week's high must NOT be included in the 35-week pivot window (`test_f15_03`).
- **Prior volume exclusion**: Current week's volume must NOT be included in the 10-week volume average window (`test_f14_05`).
- **Boundary status transitions**:
  - `current_price == stop_loss_price` is `BELOW_ENTRY`, not `STOPPED_OUT` (`test_t2_f19_01`).
  - `current_price == entry_price` is `IN_BUY_ZONE` (`test_f19_05`).
  - `current_price == max_buy_price` is `IN_BUY_ZONE` (`test_t2_f19_03`).
  - `current_price == max_buy_price + 0.01` is `EXTENDED` (`test_t2_f19_04`).
  - `current_price == entry_price - 0.01` is `BELOW_ENTRY` (`test_t2_f19_05`).

### 1.3 Database Schema & Persistence (`db/init.sql`)
- Table `screener_signals`:
  - Primary key: `id BIGSERIAL`
  - Uniqueness constraint: `CONSTRAINT uq_scan_date_ticker UNIQUE (scan_date, ticker)`
  - Status CHECK: `CONSTRAINT chk_screener_signals_entry_status CHECK (entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT'))`
  - Positive bounds: `entry_price > 0`, `current_price > 0`
  - Columns: `scan_id, scan_date, ticker, entry_price, max_buy_price, current_price, stop_loss_price, diff_pct, entry_status, volume_surge_ratio, mrs_score, sma_30w, sma_30w_slope, prior_resistance_35w, weekly_close, weekly_volume, avg_volume_10w, stage, created_at`
- Table `scan_jobs`:
  - Columns: `id, job_type, status ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED'), started_at, completed_at, tickers_total, tickers_processed, tickers_failed, signals_found, error_message, telegram_alert_sent`

### 1.4 Downstream Interaction Formats (`tests/e2e/tier3_interactions/test_t3_screener_to_telegram.py`)
- Telegram card expects:
  `$150.00` entry price, `$157.50` max buy price (+5%), `$138.00` stop loss (-8%), status badge (`🟢 IN BUY ZONE`, `🟠 EXTENDED`, `⚪ BELOW ENTRY`, `🔴 STOPPED OUT`), `+2.33%` diff, `2.15x` volume surge, and `+14.80` MRS score.

---

## 2. Logic Chain

### Step 2.1: Mansfield Relative Strength (MRS) vs SPY Benchmark
1. **Date Alignment**: Daily bars are resampled to weekly bars anchored on the final trading day of the calendar week (Friday, or Thursday on holiday closures like Good Friday). Target stock weekly bars and SPY benchmark weekly bars must be aligned by `trade_date`. If a stock has missing weeks (e.g. trading halt, IPO within the year), simple index zipping would compare misaligned weeks. An exact inner join on `trade_date` ensures strict calendar synchrony.
2. **Relative Strength Ratio**:
   $$\text{RS}[t] = \frac{\text{Stock\_Close}[t]}{\text{SPY\_Close}[t]}$$
   Guard: If $\text{SPY\_Close}[t] \le 0$, impute $0.0$ to prevent `ZeroDivisionError`.
3. **52-Week Rolling Mean of RS**:
   $$\text{SMA\_RS}_{52w}[t] = \frac{1}{52} \sum_{k=0}^{51} \text{RS}[t-k]$$
   Window constraint: Requires 52 bars. For indices $t < 51$, the value is `None`.
4. **Mansfield RS Calculation**:
   $$\text{MRS}[t] = \left( \frac{\text{RS}[t]}{\text{SMA\_RS}_{52w}[t]} - 1.0 \right) \times M$$
   *Multiplier Analysis*: In Stan Weinstein's charting conventions, $M = 10.0$ was originally used on chart scales. In modern quantitative percentage models and the project's reference test oracle (`formula_oracle.py`), $M = 100.0$ is utilized (yielding values like $+14.5$, $+15.5$ matching `screener_signals.mrs_score NUMERIC(10,4)`).
   *Sign Invariance*: Because $M > 0$, the sign is strictly invariant:
   $$\text{MRS}[t] > 0 \iff \frac{\text{RS}[t]}{\text{SMA\_RS}_{52w}[t]} > 1.0 \iff \text{RS}[t] > \text{SMA\_RS}_{52w}[t]$$
   Therefore, zero-line crossover detection is 100% mathematically equivalent regardless of whether $M = 10.0$ or $M = 100.0$. We provide `multiplier: float = 100.0` as the default to ensure exact decimal parity with test suites, with configuration parameter support.
   Guard: If $\text{SMA\_RS}_{52w}[t] \le 0$, return $0.0$.
5. **Weinstein Outperformance Criterion**:
   $\text{mrs\_score} > 0.0$. An exact value of $0.0000$ fails (stock merely tracking the benchmark average); any positive value $> 0.0$ passes.

### Step 2.2: Stan Weinstein Stage 2 Multi-Factor Filter
Stan Weinstein specifies that Stage 2 breakout candidates must meet five criteria simultaneously:
1. `week_close > sma_30w`: Stock price has climbed above its major long-term moving average.
2. `sma_30w_slope >= 0.0`: The 30-week moving average has ceased declining and is flat or turning upward.
   $$\text{slope} = \frac{\text{SMA}_{30w}[t] - \text{SMA}_{30w}[t-1]}{\text{SMA}_{30w}[t-1]} \times 100.0$$
3. `week_close >= prior_resistance_35w`: Breakout above base resistance.
   $$\text{prior\_resistance\_35w}[t] = \max_{k=1}^{35} \left( \text{High}[t-k] \right)$$
   *Crucial boundary rule*: High of current week $[t]$ must be strictly excluded. Including current week would set pivot = current high, preventing breakout detection whenever close $\le$ high!
4. `volume_surge_ratio >= 1.5`: Institutional sponsorship confirmation.
   $$\text{avg\_volume\_10w}[t] = \frac{1}{10} \sum_{k=1}^{10} \text{Volume}[t-k]$$
   $$\text{volume\_surge\_ratio}[t] = \frac{\text{Volume}[t]}{\text{avg\_volume\_10w}[t]}$$
   *Crucial boundary rule*: Current week volume $[t]$ must be strictly excluded from the 10-week average baseline.
5. `mrs_score > 0.0`: Broader market outperformance vs SPY.

Conjunction: `is_stage2 = cond1 and cond2 and cond3 and cond4 and cond5`. If any condition fails, `is_stage2` is `False`.

### Step 2.3: Target & Risk Math
- `entry_price = round(pivot_35w, 4)`: The breakout pivot level.
- `max_buy_price = round(entry_price * 1.05, 4)`: Stan Weinstein's strict rule: never chase a stock more than +5% past its breakout point.
- `current_price = round(week_close, 4)`: The latest closing price.
- `diff_pct = round(((current_price - entry_price) / entry_price) * 100.0, 4)`: Percentage extension or deficit relative to pivot.
- `stop_loss_price`:
  - If a valid swing low is detected where $0 < \text{swing\_low} < \text{entry\_price}$, `stop_loss_price = round(swing_low, 4)`.
  - Default: `round(entry_price * 0.92, 4)` (-8% standard Weinstein protective stop).
  - Invalid swing lows (e.g. $\ge \text{entry\_price}$ or $\le 0$) fall back to the 8% stop.

### Step 2.4: Deterministic Entry Status Classification
The status partition maps every positive real number $P = \text{current\_price}$ into one of four mutually exclusive, collectively exhaustive states:

```
0 ------------ [stop_loss_price] ------------ [entry_price] ------------ [max_buy_price] ------------ +∞
  STOPPED_OUT           |         BELOW_ENTRY       |       IN_BUY_ZONE        |        EXTENDED
  P < stop_loss         |   stop_loss <= P < entry  |   entry <= P <= max_buy  |     P > max_buy
```

Exact Evaluation Order:
1. `if current_price < stop_loss_price:` $\to$ `"STOPPED_OUT"`
2. `elif current_price < entry_price:` $\to$ `"BELOW_ENTRY"` (Note: at $P = \text{stop\_loss\_price}$, this branch triggers, correctly classifying it as `BELOW_ENTRY`).
3. `elif current_price <= max_buy_price:` $\to$ `"IN_BUY_ZONE"` (Note: at $P = \text{entry\_price}$ and $P = \text{max\_buy\_price}$, this branch triggers, making both bounds inclusive).
4. `else:` $\to$ `"EXTENDED"` (Triggered strictly when $P > \text{max\_buy\_price}$).

### Step 2.5: Minimum Warmup Requirement
- 30w SMA requires 30 bars.
- 10w Volume average requires 11 bars (10 prior + 1 current).
- 35w Resistance pivot requires 36 bars (35 prior + 1 current).
- 52w Mansfield RS requires 52 bars.
- **Minimum Warmup Threshold**: Any ticker with $< 52$ weekly bars cannot be evaluated by the Stage 2 screener and must be skipped with an audit log entry.

---

## 3. Caveats

1. **Holiday-Shortened Weeks**: When market is closed on Friday (e.g. Good Friday), the week's final trading date is Thursday. Date matching between target stock and SPY must use the exact last trading date of the calendar week for both tickers.
2. **Dual Multiplier Standard**: While $M = 100.0$ is the standard in the test suite and formula oracle, classical literature references $M = 10.0$. The blueprint defines `multiplier: float = 100.0` as a default parameter, allowing seamless configuration without breaking the zero-line predicate.
3. **Database Availability**: In standalone testing or offline mode, the screener engine must be capable of processing Parquet cache data directly and returning in-memory results when a live PostgreSQL connection is unavailable.
4. **Volume Float / Int**: Weekly volume summation for mega-caps can exceed $2^{31}-1$ (2.14 billion shares). Volume fields must be typed as 64-bit integer (`BIGINT` in PostgreSQL, `pl.Int64` in Polars) to avoid 32-bit overflow (`test_t2_f12_04`).

---

## 4. Conclusion & Implementation Blueprints

Below are complete, production-grade blueprints for `screener/src/indicators.py` and `screener/src/screener.py`.

### 4.1 Blueprint: `screener/src/indicators.py`

```python
"""
screener/src/indicators.py - Polars-based weekly resampling and technical indicator math
for StockSentinel Weinstein Stage 2 Screener.
Features: F12 (Resampling), F13 (30w SMA & Slope), F14 (10w Volume & Surge),
F15 (35w Resistance Pivot), F16 (Mansfield Relative Strength vs SPY).
"""
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import polars as pl

logger = logging.getLogger(__name__)


def resample_daily_to_weekly(daily_bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Resamples daily bars into weekly bars (Monday-Friday convention, Friday close).
    Handles holiday-shortened weeks (e.g. Good Friday Thursday close).
    
    Fields produced per weekly bar:
    - ticker: str
    - trade_date: str (ISO format of the last trading day of the week)
    - open: float (first day's open)
    - high: float (maximum daily high in week)
    - low: float (minimum daily low in week)
    - close: float (last day's close)
    - adj_close: float (last day's adj_close)
    - volume: int (sum of daily volumes, 64-bit safe)
    - trading_days: int (count of trading days in week)
    """
    if not daily_bars:
        return []

    # Sort daily bars chronologically ascending
    sorted_bars = sorted(daily_bars, key=lambda b: b["trade_date"])
    ticker = sorted_bars[0]["ticker"]

    df = pl.DataFrame(sorted_bars)
    
    # Cast trade_date to Date if string
    if df["trade_date"].dtype == pl.Utf8:
        df = df.with_columns(pl.col("trade_date").str.to_date("%Y-%m-%d"))

    # Compute calendar week start (Monday) for grouping
    # Monday = trade_date - weekday (0=Monday, 6=Sunday)
    df = df.with_columns(
        (pl.col("trade_date").dt.truncate("1w")).alias("week_start")
    )

    # Group by week_start and aggregate OHLCV
    weekly_df = (
        df.sort("trade_date")
        .group_by("week_start", maintain_order=True)
        .agg([
            pl.lit(ticker).alias("ticker"),
            pl.col("trade_date").last().dt.to_string("%Y-%m-%d").alias("trade_date"),
            pl.col("open").first().round(4).alias("open"),
            pl.col("high").max().round(4).alias("high"),
            pl.col("low").min().round(4).alias("low"),
            pl.col("close").last().round(4).alias("close"),
            pl.col("adj_close").last().round(4).alias("adj_close"),
            pl.col("volume").cast(pl.Int64).sum().alias("volume"),
            pl.col("trade_date").count().alias("trading_days"),
        ])
        .sort("trade_date")
    )

    return weekly_df.to_dicts()


def compute_sma(closes: List[float], window: int = 30) -> List[Optional[float]]:
    """
    Computes rolling Simple Moving Average of length `window`.
    Returns None for indices < window - 1.
    """
    if len(closes) < window:
        return [None] * len(closes)

    result: List[Optional[float]] = []
    running_sum = 0.0
    for i, c in enumerate(closes):
        running_sum += c
        if i < window - 1:
            result.append(None)
        elif i == window - 1:
            result.append(round(running_sum / float(window), 4))
        else:
            running_sum -= closes[i - window]
            result.append(round(running_sum / float(window), 4))
    return result


def compute_sma_slope(
    sma_series: List[Optional[float]],
    lookback: int = 1
) -> List[Optional[float]]:
    """
    Computes percentage slope of SMA:
    slope = ((SMA[t] - SMA[t-lookback]) / SMA[t-lookback]) * 100.0
    Guarded against None and ZeroDivisionError.
    """
    result: List[Optional[float]] = []
    for i in range(len(sma_series)):
        if (
            i < lookback
            or sma_series[i] is None
            or sma_series[i - lookback] is None
            or sma_series[i - lookback] == 0.0
        ):
            result.append(None)
        else:
            diff = sma_series[i] - sma_series[i - lookback]
            pct = (diff / sma_series[i - lookback]) * 100.0
            result.append(round(pct, 4))
    return result


def compute_volume_surge(
    volumes: List[int],
    window: int = 10
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    Computes 10-week prior average volume (strictly EXCLUDING current week)
    and volume surge ratio: current_volume / prior_avg_volume.
    Guarded against ZeroDivisionError.
    """
    avg_volumes: List[Optional[float]] = []
    surge_ratios: List[Optional[float]] = []

    for i in range(len(volumes)):
        if i < window:
            avg_volumes.append(None)
            surge_ratios.append(None)
        else:
            prior_10 = volumes[i - window : i]
            avg_vol = sum(prior_10) / float(window)
            avg_volumes.append(round(avg_vol, 2))
            surge = (volumes[i] / avg_vol) if avg_vol > 0 else 0.0
            surge_ratios.append(round(surge, 4))

    return avg_volumes, surge_ratios


def compute_prior_resistance_pivot(
    highs: List[float],
    lookback: int = 35
) -> List[Optional[float]]:
    """
    Computes the maximum high over the prior `lookback` weeks (strictly EXCLUDING current week).
    Returns None for indices < lookback.
    """
    pivots: List[Optional[float]] = []
    for i in range(len(highs)):
        if i < lookback:
            pivots.append(None)
        else:
            prior_highs = highs[i - lookback : i]
            pivots.append(round(max(prior_highs), 4))
    return pivots


def compute_mansfield_relative_strength(
    stock_closes: List[float],
    spy_closes: List[float],
    lookback: int = 52,
    multiplier: float = 100.0
) -> List[Optional[float]]:
    """
    Mansfield Relative Strength (MRS) vs SPY benchmark ETF:
    1. RS[t] = Stock_Close[t] / SPY_Close[t]
    2. SMA_RS[t] = 52-week rolling mean of RS
    3. MRS[t] = ((RS[t] / SMA_RS[t]) - 1.0) * multiplier
    
    Returns None for the first lookback - 1 bars (index 0 to 50 for 52w).
    Zero-line crossover: MRS > 0.0 indicates outperformance vs benchmark.
    """
    if len(stock_closes) != len(spy_closes):
        raise ValueError(
            f"Stock series length ({len(stock_closes)}) does not match "
            f"SPY benchmark length ({len(spy_closes)})."
        )

    # 1. Compute RS series with zero-division guard
    rs_series: List[float] = []
    for s_close, spy_close in zip(stock_closes, spy_closes):
        if spy_close <= 0.0:
            rs_series.append(0.0)
        else:
            rs_series.append(s_close / spy_close)

    # 2. Compute 52-week rolling SMA of RS and MRS
    mrs_series: List[Optional[float]] = []
    running_rs_sum = 0.0
    for i in range(len(rs_series)):
        running_rs_sum += rs_series[i]
        if i < lookback - 1:
            mrs_series.append(None)
        elif i == lookback - 1:
            rs_sma = running_rs_sum / float(lookback)
            if rs_sma <= 0.0:
                mrs_series.append(0.0)
            else:
                mrs = ((rs_series[i] / rs_sma) - 1.0) * multiplier
                mrs_series.append(round(mrs, 4))
        else:
            running_rs_sum -= rs_series[i - lookback]
            rs_sma = running_rs_sum / float(lookback)
            if rs_sma <= 0.0:
                mrs_series.append(0.0)
            else:
                mrs = ((rs_series[i] / rs_sma) - 1.0) * multiplier
                mrs_series.append(round(mrs, 4))

    return mrs_series


def align_weekly_bars(
    stock_bars: List[Dict[str, Any]],
    spy_bars: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Aligns target stock weekly bars and SPY benchmark bars on identical `trade_date`.
    Returns matched (aligned_stock, aligned_spy) sorted chronologically ascending.
    """
    spy_dict = {b["trade_date"]: b for b in spy_bars}
    aligned_stock: List[Dict[str, Any]] = []
    aligned_spy: List[Dict[str, Any]] = []

    for s in sorted(stock_bars, key=lambda x: x["trade_date"]):
        t_date = s["trade_date"]
        if t_date in spy_dict:
            aligned_stock.append(s)
            aligned_spy.append(spy_dict[t_date])

    return aligned_stock, aligned_spy
```

---

### 4.2 Blueprint: `screener/src/screener.py`

```python
"""
screener/src/screener.py - Core Screener Engine, Stage 2 Breakout Filters,
Target & Risk Calculations, Entry Status Classification, and Signal Persistence.
Features: F17 (Breakout Filter), F18 (Target/Risk Math), F19 (Entry Status), F20 (Persistence).
"""
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from screener.src import config, db, parquet_cache, universe
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
    mrs_score: Optional[float]
) -> Dict[str, Any]:
    """
    Evaluates Stan Weinstein Stage 2 Breakout multi-factor filter.
    All 5 conditions must be True simultaneously:
    1. close > sma_30w (Price above rising 30w moving average)
    2. sma_30w_slope >= 0.0 (30w SMA is flat or rising)
    3. close >= pivot_35w (Price broke out above 35-week base resistance)
    4. vol_surge_ratio >= 1.5 (Institutional volume surge >= 1.5x 10w avg)
    5. mrs_score > 0.0 (Mansfield Relative Strength > 0 indicating outperformance vs SPY)
    """
    cond_close_above_sma = (sma_30w is not None) and (close > sma_30w)
    cond_sma_rising = (sma_30w_slope is not None) and (sma_30w_slope >= 0.0)
    cond_pivot_breakout = (pivot_35w is not None) and (close >= pivot_35w)
    cond_volume_surge = (vol_surge_ratio is not None) and (vol_surge_ratio >= 1.5)
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
    - entry_price: prior 35w resistance pivot level
    - max_buy_price: entry_price * 1.05 (+5% do-not-chase upper boundary)
    - stop_loss_price: swing_low if (0 < swing_low < entry_price) else entry_price * 0.92 (-8%)
    - diff_pct: ((current_price - entry_price) / entry_price) * 100.0
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
    - stop_loss_price <= current_price < entry => 'BELOW_ENTRY'
    - entry_price <= current_price <= max_buy  => 'IN_BUY_ZONE'
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
    VALUES ('WEEKLY_SCREENER', 'RUNNING', CURRENT_TIMESTAMP, %s, 0, 0, 0)
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
    """
    if not signals:
        return 0

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
        for s in signals
    ]

    from psycopg2.extras import execute_values
    if cur:
        execute_values(cur, sql, values, page_size=1000)
    else:
        with db.db_cursor(commit=True) as cursor:
            execute_values(cursor, sql, values, page_size=1000)

    return len(values)


# =============================================================================
# Core Pipeline Runner
# =============================================================================

def run_screener(
    scan_date: Optional[Union[date, str]] = None,
    tickers: Optional[List[str]] = None,
    min_weeks: int = MINIMUM_REQUIRED_WEEKS
) -> Dict[str, Any]:
    """
    Executes the end-to-end weekly Stage 2 screener job:
    1. Loads SPY benchmark daily bars from Parquet cache and resamples to weekly.
    2. Initializes scan_jobs audit record.
    3. Loops through universe tickers, resamples daily bars, computes indicators.
    4. Evaluates Stage 2 filter, computes targets/risk, classifies entry status.
    5. Upserts qualified signals to 'screener_signals'.
    6. Updates scan_jobs audit status and metrics.
    """
    # 1. Load SPY benchmark
    spy_daily = parquet_cache.load_from_parquet("SPY")
    if not spy_daily:
        raise RuntimeError("SPY benchmark cache is empty. Please run sync first.")
    spy_weekly = resample_daily_to_weekly(spy_daily)
    if len(spy_weekly) < min_weeks:
        raise RuntimeError(f"SPY has {len(spy_weekly)} weekly bars, but {min_weeks} required.")

    # Determine tickers to scan
    target_tickers = tickers if tickers is not None else universe.get_active_universe()
    target_tickers = [t for t in target_tickers if t != "SPY"]

    # 2. Audit job initiation
    job_id = None
    try:
        job_id = create_scan_job(tickers_total=len(target_tickers))
    except Exception as e:
        logger.warning(f"Could not initialize scan_jobs table: {e}")

    qualified_signals: List[Dict[str, Any]] = []
    processed_count = 0
    failed_count = 0

    for ticker in target_tickers:
        try:
            daily_bars = parquet_cache.load_from_parquet(ticker)
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
            effective_scan_date = stock_w[last_idx]["trade_date"]
            if scan_date:
                effective_scan_date = str(scan_date)

            filter_res = evaluate_stage2_filter(
                close=closes[last_idx],
                sma_30w=sma30[last_idx],
                sma_30w_slope=slope[last_idx],
                pivot_35w=pivot35[last_idx],
                vol_surge_ratio=surge[last_idx],
                mrs_score=mrs[last_idx],
            )

            if filter_res["is_stage2"]:
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

                signal_record = {
                    "scan_id": job_id,
                    "scan_date": effective_scan_date,
                    "ticker": ticker,
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
                    "avg_volume_10w": int(avg_vol10[last_idx]) if avg_vol10[last_idx] else 0,
                    "stage": "Stage 2 Breakout",
                }
                qualified_signals.append(signal_record)

            processed_count += 1
        except Exception as e:
            logger.error(f"Error evaluating ticker {ticker}: {e}")
            failed_count += 1

    # 5. Persist signals to PostgreSQL
    if qualified_signals:
        try:
            upsert_screener_signals(qualified_signals)
            logger.info(f"Successfully persisted {len(qualified_signals)} Stage 2 signals.")
        except Exception as e:
            logger.error(f"Failed to persist signals to PostgreSQL: {e}")

    # 6. Audit job completion
    if job_id:
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

    return {
        "job_id": job_id,
        "tickers_total": len(target_tickers),
        "tickers_processed": processed_count,
        "tickers_failed": failed_count,
        "signals_found": len(qualified_signals),
        "signals": qualified_signals,
    }
```

---

## 5. Verification Method

To independently verify the mathematical accuracy, boundary handling, and downstream interface compatibility:

1. **Isolation Test Suite**:
   Inspect `tests/e2e/tier1_features/test_f12_f20_screener_math.py`.
   - Feature 12: Weekly Resampling (Monday open, Friday close, extreme high/low, volume sum).
   - Feature 13: 30-week SMA (null for first 29) and slope.
   - Feature 14: 10-week volume average (excludes current week) and $\ge 1.5$ surge.
   - Feature 15: 35-week resistance pivot (excludes current week) and breakout condition.
   - Feature 16: Mansfield Relative Strength (52-week lookback, zero-line crossover).
   - Feature 17: Multi-factor filter conjunction (all 5 factors must pass).
   - Feature 18: Target and risk math (entry pivot, +5% max buy, -8% stop loss, diff pct).
   - Feature 19: Entry status mapping (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`).
   - Feature 20: Persistence idempotency and scan audit lifecycle.

2. **Boundary & Corner Cases Suite**:
   Inspect `tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py`.
   - Single day holiday weeks, Good Friday 4-day weeks, volume exceeding 32-bit int.
   - SMA prior value zero-division guard.
   - Slope exact 0.0000% passes; -0.0001% fails.
   - Volume surge 1.4999 fails; 1.5000 passes.
   - MRS exact 0.0000 fails; 0.0001 passes.
   - Exact boundary price inclusivity: at stop loss is `BELOW_ENTRY`; at entry and max buy is `IN_BUY_ZONE`.

3. **System Interaction & Scenarios**:
   Inspect `tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py`, `test_t3_screener_to_telegram.py`, `tests/e2e/tier4_scenarios/test_t4_weekly_delta_breakout_flow.py`.

4. **Invalidation Conditions**:
   The logic in this report would be invalidated if:
   - Mansfield RS formula uses a denominator that includes the target stock price rather than SPY benchmark.
   - Breakout resistance pivot includes the current week's bar (which would cause self-referential pivot escalation).
   - Status categorization classifies `current_price == stop_loss_price` as `STOPPED_OUT` rather than `BELOW_ENTRY`.
   - Multi-factor filter permits qualification when fewer than all 5 criteria are met.
