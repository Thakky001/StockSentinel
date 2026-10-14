# Milestone 3 Independent Review & Adversarial Challenge Report

**Reviewer**: Reviewer M3-1 (`reviewer_m3_1`)  
**Roles**: Reviewer, Adversarial Critic  
**Target Milestone**: Milestone 3 — Core Screener Engine & Indicator Math  
**Timestamp**: 2026-10-14T04:46:00Z  
**Verdict**: **`REQUEST_CHANGES`**  

---

## 1. Review Summary & Formal Verdict

**Verdict**: **`REQUEST_CHANGES`**  
**Overall Risk Assessment**: **HIGH**  

While the mathematical formulas, Python list indicator functions, Stage 2 multi-factor filter logic, target/risk calculations, 4-state entry classifications, and SQL upsert persistence logic are largely sound, the vectorized Polars DataFrame implementation suffers from a critical runtime defect: **nested window expressions (`.over(group_col)`) inside `compute_volume_metrics` and `compute_resistance_pivot`**.

In Polars, nesting window functions on grouped expressions produces an unhandled `ComputeError: nested window functions are not supported`. Because `_resample_daily_df` outputs weekly DataFrames with a `"ticker"` column, invoking the exposed Polars indicator functions `compute_volume_metrics(df)`, `compute_resistance_pivot(df)`, or `compute_all_indicators(df)` on resampled DataFrames will crash. Furthermore, `screener/verify_m3.py` omitted DataFrame unit tests for these two functions, allowing the defect to escape self-verification.

---

## 2. Findings

### [Critical] Finding 1: Nested Polars Window Expressions in `compute_volume_metrics` and `compute_resistance_pivot`
- **What**: Polars raises a runtime `ComputeError` when calling `.over(group_col)` on an expression that already contains `.over(group_col)`.
- **Where**: 
  - `screener/src/indicators.py`, Lines 285–300:
    ```python
    group_col = "ticker" if "ticker" in df.columns else None
    if group_col:
        prior_vol = pl.col("volume").cast(pl.Float64).shift(1).over(group_col)
        avg_vol_expr = (
            prior_vol.rolling_mean(window_size=window, min_periods=window)
            .round(2)
            .over(group_col)
            .alias("avg_volume_10w")
        )
    ```
  - `screener/src/indicators.py`, Lines 343–351:
    ```python
    group_col = "ticker" if "ticker" in df.columns else None
    if group_col:
        prior_high = pl.col("high").shift(1).over(group_col)
        pivot_expr = (
            prior_high.rolling_max(window_size=lookback, min_periods=lookback)
            .round(4)
            .over(group_col)
            .alias("prior_resistance_35w")
        )
    ```
  - `screener/src/indicators.py`, Lines 534–535 (`compute_all_indicators` calling both functions).
- **Why**: 
  Polars explicitly disallows nested window functions. In `compute_volume_metrics`, `prior_vol` already applies `.over(group_col)`. Wrapping `prior_vol` in `.rolling_mean(...)` and applying a second `.over(group_col)` builds an invalid AST with nested `Window` expressions: `Window(RollingMean(Window(Shift(Col("volume")))))`. At runtime, Polars throws `ComputeError: nested window functions are not supported`.
  The exact same issue exists in `compute_resistance_pivot` where `prior_high` has `.over(group_col)` and `pivot_expr` wraps it with another `.over(group_col)`.
- **Suggestion**:
  Remove the inner `.over(group_col)` from `prior_vol` and `prior_high`. In Polars, a single trailing `.over(group_col)` on the aggregated expression chain correctly partitions the entire sequence (both the shift and the rolling calculation) by ticker:
  ```python
  # Correct compute_volume_metrics:
  if group_col:
      avg_vol_expr = (
          pl.col("volume").cast(pl.Float64).shift(1)
          .rolling_mean(window_size=window, min_periods=window)
          .round(2)
          .over(group_col)
          .alias("avg_volume_10w")
      )

  # Correct compute_resistance_pivot:
  if group_col:
      pivot_expr = (
          pl.col("high").shift(1)
          .rolling_max(window_size=lookback, min_periods=lookback)
          .round(4)
          .over(group_col)
          .alias("prior_resistance_35w")
      )
  ```

### [Major] Finding 2: Test Suite Coverage Gap in `screener/verify_m3.py`
- **What**: `screener/verify_m3.py` only tests the Python list variants `compute_volume_surge` and `compute_prior_resistance_pivot`, completely omitting DataFrame tests for `compute_volume_metrics`, `compute_resistance_pivot`, and `compute_all_indicators`.
- **Where**: `screener/verify_m3.py`, Lines 182–247.
- **Why**: 
  While `verify_m3.py` included DataFrame tests for `resample_daily_to_weekly` and `compute_sma_30w`, it skipped testing the DataFrame versions of volume surge and resistance pivot. Because `screener.py` (`run_screener`) converts weekly bars to lists of dictionaries before calling indicators, the Polars DataFrame pipeline was never exercised during verification, allowing the nested window function crash to remain hidden.
- **Suggestion**:
  Add unit tests in `screener/verify_m3.py` that explicitly pass a Polars DataFrame with multiple tickers to `compute_volume_metrics`, `compute_resistance_pivot`, and `compute_all_indicators`, asserting that no `ComputeError` is raised and that metrics are computed independently per ticker.

---

## 3. Adversarial Stress-Testing & Challenges

### Challenge 1: Nested Window Execution in Polars
- **Assumption challenged**: Polars expressions can chain `.over()` on an intermediate shifted expression.
- **Attack scenario**: Calling `compute_all_indicators(df)` or `compute_volume_metrics(df)` on a DataFrame containing `"ticker"`, which is the standard output of `resample_daily_to_weekly(df)`.
- **Blast radius**: Immediate runtime crash (`ComputeError`) whenever any caller utilizes the vectorized DataFrame indicator pipeline.
- **Result**: **FAIL** (Confirmed architectural defect in `screener/src/indicators.py`).

### Challenge 2: Multi-Ticker Window Data Leakage
- **Assumption challenged**: Calculations for ticker A must never bleed into ticker B when processing multi-ticker DataFrames.
- **Attack scenario**: Passing a DataFrame with 2 tickers ("AAPL", "MSFT") into `compute_sma_30w` and `compute_sma_30w_slope`.
- **Stress test analysis**:
  - `compute_sma_30w` uses `.over(group_col)`.
  - `compute_sma_30w_slope` uses `prior_sma = pl.col("sma_30w").shift(lookback).over(group_col)`.
  Data partitioning across tickers is preserved.
- **Result**: **PASS**.

### Challenge 3: Breakout Bar Feedback Loop (Current Week Leakage)
- **Assumption challenged**: A massive breakout candle (e.g. 10x volume surge or 50% price spike) must not inflate its own baseline.
- **Attack scenario**: 10 weeks of 1M volume followed by week 11 with 10M volume.
- **Stress test analysis**:
  - List implementation uses `volumes[i-window:i]`, strictly excluding index `i`.
  - Polars implementation uses `.shift(1)`, moving current bar out of the rolling window.
  - In both implementations, week 11 prior volume average remains 1,000,000 and surge ratio is 10.0x.
- **Result**: **PASS**.

### Challenge 4: Zero-Division Resilience Under Market Anomalies
- **Assumption challenged**: Division by zero must never raise an unhandled exception for halted stocks (0 volume) or penny/new stocks (0 prior SMA).
- **Stress test analysis**:
  - `compute_sma_slope`: returns `None` when `prior_sma == 0.0`.
  - `compute_volume_surge`: returns `0.0` when `avg_vol == 0`.
  - `_compute_mrs_list`: returns `0.0` when `spy_close <= 0.0` or `rs_sma <= 0.0`.
  - Polars conditional guards use `pl.when(...).then(...).when(... == 0).then(0.0)`.
- **Result**: **PASS**.

### Challenge 5: Holiday-Shortened Week & Thursday Close Anchoring
- **Assumption challenged**: During Good Friday week (Friday market closed), the weekly bar must anchor to Thursday, not Friday.
- **Stress test analysis**:
  - `_resample_daily_df` groups by `pl.col("trade_date").dt.truncate("1w")` and selects `pl.col("trade_date").last()`.
  - On Good Friday 2026-04-10, the last trading day of the week is 2026-04-09 (Thursday).
  - Test scenario in `test_t4_market_holiday_resampling_flow.py` confirms 3 weekly bars are produced and the candle date is `2026-04-09`.
- **Result**: **PASS**.

### Challenge 6: Entry Status Boundary Precision
- **Assumption challenged**: Exactly at `stop_loss_price`, status must be `BELOW_ENTRY`, not `STOPPED_OUT`. Exactly at `entry_price` or `max_buy_price`, status must be `IN_BUY_ZONE`.
- **Stress test analysis**:
  - `classify_entry_status(92.0, 100.0, 105.0, 92.0)` -> `BELOW_ENTRY` (stopped out only when `< 92.0`).
  - `classify_entry_status(100.0, 100.0, 105.0, 92.0)` -> `IN_BUY_ZONE`.
  - `classify_entry_status(105.0, 100.0, 105.0, 92.0)` -> `IN_BUY_ZONE`.
  - `classify_entry_status(105.01, 100.0, 105.0, 92.0)` -> `EXTENDED`.
- **Result**: **PASS**.

---

## 4. Integrity Violation Audit

Per the strict reviewer identity rules, an exhaustive scan for integrity violations was conducted:
1. **Hardcoded test results**:
   - Grep search for synthetic dates ("2026-"), mock tickers ("TEST", "HOLI", "BREAK"), and static indicator results across `screener/src/indicators.py` and `screener/src/screener.py`.
   - **Result**: No hardcoded values or test shims detected. All calculations derive dynamically from input bar series.
2. **Dummy / facade implementations**:
   - Inspected all mathematical operations: SMA sliding window, slope percentage, volume surge ratio, resistance pivot, Mansfield RS formula.
   - **Result**: Full algorithmic implementations present.
3. **Delegation / shortcuts**:
   - Resampling is natively implemented via Polars expressions and ISO calendar grouping without external library dependencies beyond Polars.
4. **Attestation / verification integrity**:
   - The worker's reported test suite in `verify_m3.py` is authentic, but had a coverage omission (Finding 2).

**Integrity Audit Verdict**: No integrity violation (cheating, facade, hardcoding). The rejection is based on a genuine runtime code defect (Finding 1) and test coverage omission (Finding 2).

---

## 5. Logic Chain

1. **Observation 1**: In `screener/src/indicators.py` lines 287–293:
   `prior_vol = pl.col("volume").cast(pl.Float64).shift(1).over(group_col)` is defined with `.over(group_col)`.
2. **Observation 2**: On lines 288–293:
   `avg_vol_expr` applies `.rolling_mean(...).over(group_col)` to `prior_vol`.
3. **Observation 3**: In Polars, nesting an expression with `.over()` inside another `.over()` triggers `polars.exceptions.ComputeError: nested window functions are not supported`.
4. **Observation 4**: In `screener/src/indicators.py` lines 345–351, the exact same nested structure occurs in `compute_resistance_pivot`.
5. **Observation 5**: In `screener/src/indicators.py` line 534–535, `compute_all_indicators` calls `compute_volume_metrics` and `compute_resistance_pivot`.
6. **Observation 6**: Any DataFrame passed from `resample_daily_to_weekly(df)` contains the `"ticker"` column, activating the `if group_col:` branch and triggering the crash.
7. **Conclusion**: The Polars DataFrame indicators cannot be executed safely on ticker-keyed DataFrames. Changes must be requested to correct the Polars expression AST and add corresponding DataFrame unit tests.

---

## 6. Caveats

1. **List Pipeline Functionality**: The procedural Python list implementation (`compute_volume_surge`, `compute_prior_resistance_pivot`, and `screener.run_screener`) executes without this Polars error because it bypasses DataFrame evaluation.
2. **Non-Titled DataFrames**: If a DataFrame is passed without a `"ticker"` column, `group_col` is `None` and the `else:` branch executes without `.over()`. However, standard StockSentinel data always carries `"ticker"`.

---

## 7. Required Fixes Before Approval

The worker must address the following items:
1. **Fix nested window expressions in `screener/src/indicators.py`**:
   - In `compute_volume_metrics`: simplify `avg_vol_expr` to `pl.col("volume").cast(pl.Float64).shift(1).rolling_mean(window_size=window, min_periods=window).round(2).over(group_col).alias("avg_volume_10w")`.
   - In `compute_resistance_pivot`: simplify `pivot_expr` to `pl.col("high").shift(1).rolling_max(window_size=lookback, min_periods=lookback).round(4).over(group_col).alias("prior_resistance_35w")`.
2. **Expand unit tests in `screener/verify_m3.py`**:
   - Add test methods for `compute_volume_metrics(df)` and `compute_resistance_pivot(df)` on a multi-ticker DataFrame.
   - Add a test method for `compute_all_indicators(df, spy_df)` verifying end-to-end Polars DataFrame indicator pipeline execution.
3. Re-run `python screener/verify_m3.py` and verify all tests pass cleanly.

---

## 8. Verification Method for Upstream

To verify the defect:
```python
import polars as pl
from screener.src.indicators import compute_volume_metrics, compute_resistance_pivot, compute_all_indicators

# Construct a multi-ticker DataFrame
df = pl.DataFrame({
    "ticker": ["AAPL"] * 20 + ["MSFT"] * 20,
    "trade_date": [f"2026-01-{i+1:02d}" for i in range(20)] * 2,
    "open": [100.0] * 40,
    "high": [105.0] * 40,
    "low": [98.0] * 40,
    "close": [102.0] * 40,
    "adj_close": [102.0] * 40,
    "volume": [1000000] * 40,
    "trading_days": [5] * 40,
})

# This call will raise ComputeError due to nested window functions:
compute_volume_metrics(df, window=10)
```

To verify the fix once implemented:
1. Run the script above and assert it completes without error.
2. Run `python screener/verify_m3.py -v`.
3. Run `python tests/run_e2e.py --feature 12`.
4. Run `python tests/run_e2e.py --feature 14`.
5. Run `python tests/run_e2e.py --feature 15`.
