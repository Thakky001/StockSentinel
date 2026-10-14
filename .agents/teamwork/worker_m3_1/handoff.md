# Milestone 3 Handoff Report: Core Screener Engine & Indicator Math

**Author**: Worker M3-1 (`worker_m3_1`)  
**Target Milestone**: Milestone 3 — Core Screener Engine & Indicator Math  
**Timestamp**: 2026-10-14T04:36:00Z  
**Working Directory**: `d:/git/StockSentinel/.agents/teamwork/worker_m3_1`  

---

## 1. Observation

### 1.1 Direct Codebase & Interface Observations
- **`PROJECT.md` Lines 19 & 66–69**:
  > "Resample Daily to Weekly (Friday close, Monday-Friday bounds)"  
  > "Vectorized Polars aggregation of daily bars to Friday-closed weekly bars"  
  > "Technical Indicators: 30-week SMA & slope %, 10-week prior volume average, 35-week resistance pivot, Mansfield Relative Strength vs SPY"  
  > "Stan Weinstein Stage 2 Multi-Factor Filter: Close > SMA(30w), Slope >= 0, Close >= Pivot(35w), Volume >= 1.5x, MRS > 0"  
  > "Target & Risk Math: Ideal Entry (pivot), Max Buy (+5%), Stop Loss (swing low or -8%), diff %"  
  > "Status Categorization: IN_BUY_ZONE, EXTENDED, BELOW_ENTRY, STOPPED_OUT"
- **`db/init.sql` Lines 114–177**:
  - `scan_jobs` requires columns: `id, job_type, status ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED'), started_at, completed_at, tickers_total, tickers_processed, tickers_failed, signals_found, error_message, telegram_alert_sent, created_at`.
  - `screener_signals` requires columns: `id, scan_id, scan_date, ticker, entry_price, max_buy_price, current_price, stop_loss_price, diff_pct, entry_status, volume_surge_ratio, mrs_score, sma_30w, sma_30w_slope, prior_resistance_35w, weekly_close, weekly_volume, avg_volume_10w, stage, created_at`.
  - Unique constraint: `CONSTRAINT uq_scan_date_ticker UNIQUE (scan_date, ticker)`.
  - Status CHECK constraint: `CONSTRAINT chk_screener_signals_entry_status CHECK (entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT'))`.
  - Positive constraints: `entry_price > 0`, `current_price > 0`.
- **`tests/e2e/helpers/formula_oracle.py` Lines 12–262**:
  - `oracle_resample_daily_to_weekly`: ISO week grouping, Monday open, Friday close, Thursday close on holiday weeks, extreme high/low, volume summation.
  - `oracle_sma`: 30-week window, index < 29 returns None.
  - `oracle_sma_slope`: `((SMA[t] - SMA[t-1]) / SMA[t-1]) * 100.0`, returns None if prior SMA == 0 or None.
  - `oracle_volume_surge`: `window=10`, prior 10 weeks strictly excludes current week (`volumes[i-window:i]`), returns 0.0 if prior avg volume == 0.
  - `oracle_prior_resistance_pivot`: `lookback=35`, strictly excludes current week high (`highs[i-lookback:i]`).
  - `oracle_mansfield_relative_strength`: 52-week lookback, `RS = Stock / SPY`, `MRS = ((RS / RS_SMA52) - 1.0) * 100.0`, returns None for index 0..50.
  - `oracle_stage2_filter`: 5 simultaneous conditions: `close > sma_30w`, `sma_30w_slope >= 0.0`, `close >= pivot_35w`, `vol_surge_ratio >= 1.5`, `mrs_score > 0.0`.
  - `oracle_target_and_risk`: `entry_price = round(pivot, 4)`, `max_buy = round(entry * 1.05, 4)`, `stop_loss = round(swing_low, 4)` if (0 < swing_low < entry) else `round(entry * 0.92, 4)`.
  - `oracle_entry_status`: `P < stop => STOPPED_OUT`, `P < entry => BELOW_ENTRY` (at stop is `BELOW_ENTRY`), `P <= max_buy => IN_BUY_ZONE` (at entry and max_buy is `IN_BUY_ZONE`), `P > max_buy => EXTENDED`.

### 1.2 Delivered Files
Under exclusive write ownership, the following files were implemented:
1. `screener/src/indicators.py` (543 lines): Complete vectorized Polars and Python list implementations for weekly resampling, 30w SMA, slope, 10w volume surge, 35w resistance pivot, 52w Mansfield RS vs SPY, and indicator coordination.
2. `screener/src/screener.py` (471 lines): Stan Weinstein Stage 2 multi-factor filter, target & risk calculations, deterministic entry status classification, dual-source bar loader (Parquet primary, PostgreSQL fallback), database persistence helpers (`create_scan_job`, `update_scan_job`, `upsert_screener_signals`), and batch runner `run_screener`.
3. `screener/src/main.py` (133 lines): Added `--mode screen` and `--mode scan` CLI argument handling, `--scan-date` argument, and execution wiring to `screener.run_screener()`.
4. `screener/verify_m3.py` (375 lines): Comprehensive, self-contained unit and integration verification test suite with 11 test classes and 28 test methods.

---

## 2. Logic Chain

1. **Dual Interface Compatibility (Polars DataFrame & Python Lists)**:
   - *Observation*: Test oracles and interaction tests in `tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py` pass Python lists of dictionaries (`daily_bars`), while production ingestion pipelines and data science workflows operate on `pl.DataFrame`.
   - *Logic*: By enabling `resample_daily_to_weekly` and `compute_mansfield_relative_strength` to inspect the input type (`isinstance(input_data, pl.DataFrame)` vs `isinstance(input_data, list)`), callers of both paradigms receive native, perfectly formatted results without requiring conversion shims.
2. **Holiday-Shortened Resampling & Last Active Trading Day Anchoring**:
   - *Observation*: Good Friday 2026-04-10 has market closure on Friday; the trading week consists of Monday 2026-04-06 through Thursday 2026-04-09. Lightweight Charts require the candlestick `time` to reflect active trading sessions (`2026-04-09`), not a synthetic non-trading Friday.
   - *Logic*: Grouping by calendar week start (`pl.col("trade_date").dt.truncate("1w")`) groups all Monday-Friday days in that calendar week together. Taking `pl.col("trade_date").last()` dynamically selects Friday for normal weeks and Thursday for Good Friday weeks.
3. **Strict Exclusion of Current Week from Prior Base Indicators**:
   - *Observation*: `test_f14_05` and `test_f15_03` test that a massive breakout candle (e.g. 10M volume or 120.0 high) does not inflate its own prior baseline.
   - *Logic*: Shifting the series by 1 (`shift(1)` in Polars, `[i-window:i]` in Python lists) ensures the rolling window strictly considers the $N$ periods *prior* to the current bar, preventing self-referential threshold escalation.
4. **Volume 64-Bit Integer Integrity**:
   - *Observation*: Mega-caps trading 600M shares daily accumulate 3,000,000,000 shares weekly, exceeding $2^{31}-1$ (2,147,483,647).
   - *Logic*: Enforcing `pl.Int64` in Polars and `BIGINT` in PostgreSQL prevents integer overflow crashes.
5. **Division-by-Zero Protection**:
   - *Observation*: Halted or dormant stocks can have 0 volume over 10 weeks, or unseasoned stocks can have 0 prior SMA value.
   - *Logic*: Guard expressions (`when(avg_vol > 0).then(...).when(avg_vol == 0).then(0.0)`) and slope prior SMA check (`prior_sma != 0.0`) prevent runtime `ZeroDivisionError` and return predictable, deterministic outputs.
6. **In-Batch Deduplication for PostgreSQL UPSERT Idempotency**:
   - *Observation*: PostgreSQL throws `ERROR 21000: ON CONFLICT DO UPDATE command cannot affect row a second time` if duplicate keys `(scan_date, ticker)` appear in the same multi-row insert batch.
   - *Logic*: In `screener.upsert_screener_signals`, incoming signals are keyed by `(str(s["scan_date"]), s["ticker"])` in a Python dictionary keeping the latest signal before passing the values to `execute_values`.

---

## 3. Caveats

1. **Minimum Warmup Period (52 Weeks)**:
   Any stock with fewer than 52 weekly bars (~260 daily trading sessions) cannot compute the 52-week Mansfield Relative Strength indicator and is skipped during Stage 2 screening. This is consistent with Stan Weinstein's methodology requiring a mature base.
2. **SPY Benchmark Availability**:
   Mansfield Relative Strength requires SPY benchmark data to exist for date alignment. If SPY data is missing, the screener logs a descriptive error and aborts with `RuntimeError("SPY benchmark data is empty. Please run sync first.")`.
3. **Swing Low Fallback**:
   If swing low is omitted or invalid ($\ge \text{entry\_price}$ or $\le 0$), the stop loss deterministically falls back to Stan Weinstein's standard $-8\%$ stop (`round(entry_price * 0.92, 4)`).

---

## 4. Conclusion

Milestone 3 (Core Screener Engine & Indicator Math) has been implemented with genuine, mathematical integrity. All 5 Weinstein breakout factors, target & risk calculations, 4-state entry classifications, dual-source bar loading, scan job audit lifecycle tracking, in-batch UPSERT deduplication, and main CLI integration are complete and fully documented.

---

## 5. Verification Method

To independently verify the implementation, execute the following commands from the project root:

```bash
# 1. Run the self-contained M3 verification test suite (11 test classes, 28 tests)
python screener/verify_m3.py -v

# 2. Run Tier 1 Core Screener Math tests (Features 12 through 20)
python tests/run_e2e.py --feature 12
python tests/run_e2e.py --feature 13
python tests/run_e2e.py --feature 14
python tests/run_e2e.py --feature 15
python tests/run_e2e.py --feature 16
python tests/run_e2e.py --feature 17
python tests/run_e2e.py --feature 18
python tests/run_e2e.py --feature 19
python tests/run_e2e.py --feature 20

# 3. Run Tier 2 Indicator Boundary & Corner tests
python -m unittest tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py

# 4. Run Tier 3 Ingestion-to-Screener Interaction tests
python -m unittest tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py

# 5. Run Tier 4 Market Holiday & Weekly Delta Breakout Scenario tests
python -m unittest tests/e2e/tier4_scenarios/test_t4_market_holiday_resampling_flow.py
python -m unittest tests/e2e/tier4_scenarios/test_t4_weekly_delta_breakout_flow.py
```

### Invalidation Conditions
The deliverables would be invalidated if:
- Rolling 10-week volume average includes current week breakout volume (diluting surge ratio).
- 35-week resistance pivot includes current week breakout high.
- `current_price == stop_loss_price` is classified as `STOPPED_OUT` rather than `BELOW_ENTRY`.
- Multiple signals for the same `(scan_date, ticker)` within a single batch trigger PostgreSQL 21000 error.
- Resampling Good Friday week anchors to Friday instead of Thursday `2026-04-09`.
