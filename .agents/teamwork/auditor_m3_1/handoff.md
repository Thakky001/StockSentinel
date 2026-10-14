# Milestone 3 Forensic Integrity Audit Report

**Auditor**: Forensic Auditor (`auditor_m3_1`)  
**Target Milestone**: Milestone 3 — Core Screener Engine & Indicator Math  
**Timestamp**: 2026-10-14T04:45:00Z  
**Integrity Mode**: Development (from `ORIGINAL_REQUEST.md` line 8)  
**Binary Verdict**: **`CLEAN`**

---

## 1. Observation

### 1.1 Integrity Mode & Deliverable Files
- **`ORIGINAL_REQUEST.md` Line 8**:
  > `Integrity mode: development`
- **Deliverable Files Inspected**:
  1. `screener/src/indicators.py` (543 lines): Complete vectorized Polars and Python list implementations for weekly resampling, 30w SMA, slope %, 10w prior volume average & surge ratio, 35w prior resistance pivot, 52w Mansfield RS vs SPY benchmark, date alignment, and indicator coordination.
  2. `screener/src/screener.py` (471 lines): Stan Weinstein Stage 2 multi-factor filter (5 AND conditions), target & risk math (entry, +5% max buy, -8% stop loss fallback, diff %), deterministic 4-state entry status classification (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`), dual-source historical bar loader (Parquet primary, PostgreSQL fallback), database batch upsert with in-batch deduplication, `scan_jobs` execution state machine, and batch runner `run_screener`.
  3. `screener/src/main.py` (154 lines): CLI entrypoint supporting `--mode screen` / `--mode scan`, `--scan-date`, and `--tickers`, wiring directly to `screener.run_screener()`.
  4. `screener/verify_m3.py` (464 lines): Self-contained unit & integration test suite (11 test classes, 28 tests) covering deliverables existence, resampling with holiday anchoring, 64-bit volume, SMA & slope zero-division guards, volume surge exclusion, resistance pivot exclusion, Mansfield RS 52w lookback, Stage 2 filter, target/risk math, entry status boundaries, and in-batch deduplication.

### 1.2 Prohibited Patterns Check
- **Pattern 1: Hardcoded test results / Canned responses**:
  - Direct grep search for test tickers (`AAPL`, `HOLI`, `TEST`) in `screener/src/` returned zero conditional branches or hardcoded outputs. Only CLI help strings and ticker sanitizer regex comments mention ticker names.
  - All indicator and screener calculations process dynamic inputs mathematically.
- **Pattern 2: Facade implementations**:
  - Direct grep search for `NotImplementedError`, `TODO`, `FIXME`, or hollow stub routines in `screener/src/` returned 0 occurrences.
  - Every function has genuine, complete logic.
- **Pattern 3: Fabricated verification outputs**:
  - File search across repository for pre-populated `*.log` or `*result*` files returned 0 results. No pre-recorded artifacts exist.
- **Pattern 4: Self-certifying tests**:
  - `screener/verify_m3.py` contains independent mathematical assertions based on first principles (e.g. `(10 * 100 + 20 * 130) / 30 = 120.0`).
  - Dual test tracks exist in `tests/e2e/tier1_features/test_f12_f20_screener_math.py`, `tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py`, `tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py`, and `tests/e2e/tier4_scenarios/test_t4_weekly_delta_breakout_flow.py`.
- **Pattern 5: Execution delegation**:
  - No external TA libraries (`ta-lib`, `pandas-ta`, etc.) are imported. Indicator math is implemented from scratch using native Polars expressions and Python numerical logic.

### 1.3 Feature Specifications & Algorithmic Observations
- **Feature 12 (Weekly Resampling Engine)**:
  - `screener/src/indicators.py` lines 76–95:
    ```python
    df = df.with_columns(pl.col("trade_date").dt.truncate("1w").alias("week_start"))
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
            pl.col("trade_date").count().cast(pl.Int32).alias("trading_days"),
        ])
        .drop("week_start")
        .sort(["ticker", "trade_date"])
    )
    ```
    `trade_date.last()` dynamically resolves to Friday for regular weeks and Thursday for Good Friday weeks (`2026-04-09`). Volume is cast to `pl.Int64` to prevent 32-bit overflow.
- **Feature 13 (30-Week SMA & Slope %)**:
  - `screener/src/indicators.py` lines 184–200 & 227–250:
    Rolling window size 30 with `min_periods=30`. Slope calculates `((SMA[t] - SMA[t-1]) / SMA[t-1]) * 100.0` guarded by `prior_sma != 0.0` and not null.
- **Feature 14 (10-Week Volume Average & Surge Ratio)**:
  - `screener/src/indicators.py` lines 287–315:
    `prior_vol = pl.col("volume").cast(pl.Float64).shift(1).over(group_col)`
    `prior_vol.rolling_mean(window_size=10, min_periods=10)`
    `shift(1)` strictly excludes the current week breakout candle from the 10-week average baseline. Zero division guarded (`avg_volume_10w == 0` returns `0.0`).
- **Feature 15 (35-Week Prior Resistance Pivot)**:
  - `screener/src/indicators.py` lines 343–358:
    `prior_high = pl.col("high").shift(1).over(group_col)`
    `prior_high.rolling_max(window_size=35, min_periods=35)`
    `shift(1)` strictly excludes the current week breakout candle high from the resistance pivot.
- **Feature 16 (Mansfield Relative Strength vs SPY)**:
  - `screener/src/indicators.py` lines 362–475:
    $RS = \text{Stock} / \text{SPY}$, $SMA_{52}(RS)$, $MRS = ((RS / SMA_{52}(RS)) - 1.0) * 100.0$.
    Aligned on `trade_date` via join.
- **Feature 17 (Stan Weinstein Stage 2 Multi-Factor Filter)**:
  - `screener/src/screener.py` lines 43–64:
    Evaluates 5 simultaneous AND conditions: `close > sma_30w`, `sma_30w_slope >= 0.0`, `close >= pivot_35w`, `vol_surge_ratio >= 1.50`, `mrs_score > 0.0`.
- **Feature 18 (Target & Risk Math)**:
  - `screener/src/screener.py` lines 80–96:
    `entry_price = round(pivot_35w, 4)`, `max_buy_price = round(entry_price * 1.05, 4)`, `stop_loss_price = round(swing_low, 4)` if valid else `round(entry_price * 0.92, 4)`, `diff_pct = round(((current_price - entry_price) / entry_price) * 100.0, 4)`.
- **Feature 19 (Entry Status Classification)**:
  - `screener/src/screener.py` lines 112–119:
    - $P < \text{stop} \Rightarrow \text{'STOPPED\_OUT'}$
    - $P < \text{entry} \Rightarrow \text{'BELOW\_ENTRY'}$ (exact stop is `BELOW_ENTRY`)
    - $P \le \text{max\_buy} \Rightarrow \text{'IN\_BUY\_ZONE'}$ (exact entry and max buy are `IN_BUY_ZONE`)
    - $P > \text{max\_buy} \Rightarrow \text{'EXTENDED'}$
- **Feature 20 (Persistence & Scan Jobs Lifecycle)**:
  - `screener/src/screener.py` lines 182–221:
    In-batch deduplication `(str(s["scan_date"]), s["ticker"])` prevents PostgreSQL Error 21000.
    Upsert query: `INSERT INTO screener_signals (...) VALUES %s ON CONFLICT (scan_date, ticker) DO UPDATE SET ...` matches `db/init.sql` schema and constraints exactly.
    `scan_jobs` creates `RUNNING` record on start and updates to `COMPLETED` or `FAILED` on finish.

---

## 2. Logic Chain

1. **Development Mode Compliance**:
   Under `ORIGINAL_REQUEST.md` line 8, Development Mode prohibits hardcoding, dummy facades, and fabricated outputs, while permitting standard libraries and utility helpers. The code contains zero hardcoded shortcuts or stub implementations.
2. **Mathematical Correctness & Zero-Division Safety**:
   - Trace of `compute_sma_slope`: when prior SMA is 0.0 or None, the code returns None rather than throwing `ZeroDivisionError`.
   - Trace of `compute_volume_surge`: when prior average volume is 0.0, the surge ratio returns 0.0.
   - Trace of `_compute_mrs_df`: when SPY close is null/0 or RS SMA is <= 0, the MRS score returns 0.0.
3. **No Self-Referential Dilution of Breakout Signals**:
   - `shift(1)` on volume ensures that an enormous breakout volume (e.g. 10x normal) does not enter the 10-week denominator.
   - `shift(1)` on high ensures that a breakout price jump above prior resistance does not raise the resistance pivot to itself.
4. **Boundary Inclusivity Alignment**:
   - Status categorization covers the full domain $(-\infty, +\infty)$ deterministically without gaps.
   - Exact boundary checks: price at stop loss is `BELOW_ENTRY`; price at entry is `IN_BUY_ZONE`; price at max buy is `IN_BUY_ZONE`; price above max buy is `EXTENDED`.
5. **Database Integrity & Interface Contract**:
   - All 18 columns in `screener_signals` match `db/init.sql` DDL definitions and data types.
   - In-batch deduplication guarantees that duplicate entries for `(scan_date, ticker)` within a single batch will not trigger PostgreSQL error 21000.
   - Output payload meets the downstream requirements for M4 (`send_weekly_alert`) and M5 (`/api/screener/latest`).

---

## 3. Caveats

- **Warmup Data Requirement**:
  Stocks with fewer than 52 weeks of historical daily data cannot compute the 52-week Mansfield Relative Strength indicator and are skipped. This is an intentional Weinstein methodology constraint.
- **SPY Benchmark Requirement**:
  Screener execution requires SPY daily bars to exist for benchmark alignment; if SPY data is absent, the pipeline halts with a descriptive error.
- "No other caveats."

---

## 4. Conclusion

**Binary Verdict**: **`CLEAN`**

The Milestone 3 deliverables (`screener/src/indicators.py`, `screener/src/screener.py`, `screener/src/main.py`, `screener/verify_m3.py`) represent a genuine, fully implemented, mathematically accurate core screener engine.
No integrity violations, dummy facades, canned responses, or prohibited shortcuts were identified.

---

## 5. Verification Method

To independently verify the implementation:

1. **Self-Contained Verification Test Suite**:
   ```bash
   python screener/verify_m3.py -v
   ```
   Inspect all 28 passing tests across 11 test classes.
2. **Tier 1 Feature Tests (Features 12 through 20)**:
   ```bash
   python -m unittest tests/e2e/tier1_features/test_f12_f20_screener_math.py
   ```
3. **Tier 2 Indicator Boundary Tests**:
   ```bash
   python -m unittest tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py
   ```
4. **Tier 3 Ingestion to Screener Interaction Tests**:
   ```bash
   python -m unittest tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py
   ```
5. **Tier 4 Scenario Tests**:
   ```bash
   python -m unittest tests/e2e/tier4_scenarios/test_t4_market_holiday_resampling_flow.py
   python -m unittest tests/e2e/tier4_scenarios/test_t4_weekly_delta_breakout_flow.py
   ```

### Invalidation Conditions
The verdict would be invalidated if:
- Current week breakout volume is included in the prior 10-week average volume.
- Current week breakout high is included in the prior 35-week resistance pivot.
- Zero-division in SMA slope or volume surge causes unhandled exceptions.
- PostgreSQL throws Error 21000 on batch upserts with duplicate keys.
- Thursday close is not used for Good Friday holiday shortened trading weeks.
