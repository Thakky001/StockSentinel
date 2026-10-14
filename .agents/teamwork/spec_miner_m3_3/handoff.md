# Milestone 3 Specification Mining Report & Handoff

**Author**: Spec Miner (Milestone 3 Focus)  
**Target Milestone**: M3 — Core Screener Engine & Indicator Math  
**Working Directory**: `d:/git/StockSentinel/.agents/teamwork/spec_miner_m3_3`  
**Timestamp**: 2026-10-14T04:25:00Z  

---

## 1. Executive Summary & Scope

This specification mining report defines the authoritative, mathematically exact, and interface-complete specifications for **Milestone 3 (Core Screener Engine & Indicator Math)** of StockSentinel.

Derived from primary authoritative artifacts (`ORIGINAL_REQUEST.md`, `PROJECT.md`, `db/init.sql`, `TEST_INFRA.md`, and the dual-track E2E test suite in `tests/e2e/`), this report provides implementation-ready specifications across four core domains:
1. **Database Persistence Specification**: Full DDL schema mapping, PostgreSQL 16 UPSERT syntax (`ON CONFLICT (scan_date, ticker) DO UPDATE`), cardinality deduplication guards, and `scan_jobs` execution audit state machine.
2. **Ingestion-to-Screener Pipeline Integration**: Dual-source bar loading (Snappy Parquet primary, PostgreSQL `stock_daily_bars` fallback), Polars vectorized weekly resampling (Friday close / holiday adjustment), indicator algorithms (30w SMA, slope, 10w vol avg, surge ratio, 35w resistance pivot, 52w Mansfield RS vs SPY), Stage 2 breakout filter, and batch runner coordination.
3. **Downstream Interface Contracts**: Signal payload definitions and metadata enrichment for Milestone 4 (Telegram HTML digest cards) and Milestone 5 (Express REST API `/api/screener/latest`, `/api/screener/dates`, `/api/stock/:ticker/summary`, `/api/stock/:ticker/chart`, `/api/screener/trigger`).
4. **Verification Suite Specification**: Comprehensive blueprint for `screener/verify_m3.py` and exact verification commands across Worker, Reviewer, Challenger, and Auditor roles.

---

## 2. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 12 | Screener Math | Weekly Resampling Engine | Compresses daily OHLCV bars into weekly bars (Monday–Friday ISO bounds, Friday close, holiday detection, volume summation). | Daily OHLCV bars (`trade_date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`). | Weekly bars (`trade_date` of last trading day, weekly OHLCV, `trading_days` count). | Empty list if no daily bars; preserves 1-day/4-day short weeks without padding missing days. | `ORIGINAL_REQUEST.md` §R3; `PROJECT.md` Feature 12; `formula_oracle.py` |
| 13 | Screener Math | 30-Week SMA & Slope | Computes rolling 30-week simple moving average of weekly close and 1-week percentage slope. | Weekly close series (minimum 30 periods for SMA, 31 for slope). | `sma_30w` (float), `sma_30w_slope` (float % change). | Returns `None` for indices < 29; slope guards against `sma_30w == 0` with division-by-zero protection. | `PROJECT.md` Feature 13; `test_f12_f20_screener_math.py` lines 83-119; `formula_oracle.py` |
| 14 | Screener Math | 10-Week Volume Average & Surge Ratio | Computes prior 10-week average weekly volume (strictly excluding current week) and current volume surge ratio. | Weekly volume series (minimum 11 weeks). | `avg_volume_10w` (int/float), `volume_surge_ratio` (float). | Returns `None` for first 10 weeks; returns 0.0 surge if prior average volume == 0. | `PROJECT.md` Feature 14; `test_f12_f20_screener_math.py` lines 121-155; `formula_oracle.py` |
| 15 | Screener Math | 35-Week Resistance Pivot | Computes the maximum high over the prior 35 weeks (strictly excluding current week's high). | Weekly high series (minimum 36 weeks). | `prior_resistance_35w` (float). | Returns `None` for first 35 weeks; ignores current week's high even if higher. | `PROJECT.md` Feature 15; `test_f12_f20_screener_math.py` lines 157-191; `formula_oracle.py` |
| 16 | Screener Math | Mansfield Relative Strength (MRS) | Computes John Mansfield RS vs SPY benchmark: $RS = \frac{Close_{stock}}{Close_{SPY}}$, 52-week rolling average $RS_{SMA52}$, and $MRS = (\frac{RS}{RS_{SMA52}} - 1) \times 100$. | Aligned stock weekly close & SPY weekly close (minimum 52 weeks). | `mrs_score` (float). | Raises ValueError if lengths mismatch; returns `None` for first 51 weeks; guards against $Close_{SPY} \le 0$ or $RS_{SMA52} \le 0$. | `PROJECT.md` Feature 16; `test_f12_f20_screener_math.py` lines 193-230; `formula_oracle.py` |
| 17 | Screener Math | Stage 2 Breakout Multi-Factor Filter | Evaluates 5 simultaneous Weinstein breakout rules: (1) $Close > SMA_{30w}$, (2) $Slope_{30w} \ge 0.0$, (3) $Close \ge Pivot_{35w}$, (4) $Surge \ge 1.50$, (5) $MRS > 0.0$. | Latest weekly close and all 5 computed indicators. | `is_stage2` (bool), individual condition flags. | Returns `False` if any indicator is `None` or fails threshold; rejection if even one factor fails. | `PROJECT.md` Feature 17; `test_f12_f20_screener_math.py` lines 232-286; `formula_oracle.py` |
| 18 | Target & Risk Math | Entry, Max Buy, Stop Loss, & Distance | Calculates ideal Entry Price ($Pivot_{35w}$), Max Buy Price ($+5\%$), Stop Loss (swing low or $-8\%$), and % distance from entry. | `prior_resistance_35w`, current price, optional `swing_low`. | `entry_price`, `max_buy_price`, `stop_loss_price`, `current_price`, `diff_pct`. | Rejects swing low if $\ge entry\_price$ or $\le 0$ (falls back to 0.92 * entry); rounds all prices to 4 decimal places. | `PROJECT.md` Feature 18; `test_f12_f20_screener_math.py` lines 288-314; `formula_oracle.py` |
| 19 | Target & Risk Math | Entry Status Categorization | Deterministic mapping into 4 mutually exclusive states: `STOPPED_OUT`, `BELOW_ENTRY`, `IN_BUY_ZONE`, `EXTENDED`. | `current_price`, `entry_price`, `max_buy_price`, `stop_loss_price`. | `entry_status` (string enum matching CHECK constraint). | Explicit boundary handling: $price == entry \implies IN\_BUY\_ZONE$; $price == max\_buy \implies IN\_BUY\_ZONE$; $price == stop \implies BELOW\_ENTRY$. | `PROJECT.md` Feature 19; `test_f12_f20_screener_math.py` lines 316-344; `test_t2_indicators_boundaries.py` |
| 20 | DB Persistence | Screener Signals Persistence | Batch upsert of qualified breakout signals into `screener_signals` with `ON CONFLICT (scan_date, ticker) DO UPDATE`. | List of signal dictionaries, `scan_id`, `scan_date`. | Upsert count, updated signal rows. | Prevents Postgres cardinality error 21000 via prior in-batch deduplication; validates CHECK constraints ($entry > 0$, $current > 0$). | `PROJECT.md` Feature 20; `db/init.sql` lines 140-200; `test_f20_01_f20_05` |
| 20b | DB Persistence | Scan Jobs Audit Logging | Execution tracking and state machine transitions: `PENDING` $\to$ `RUNNING` $\to$ `COMPLETED` / `FAILED` with execution metrics and timings. | `job_type`, `tickers_total`, `tickers_processed`, `tickers_failed`, `signals_found`, error string. | `scan_job_id` (BIGINT), audit timestamps. | Enforces CHECK constraint `status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')`; sets `completed_at = CURRENT_TIMESTAMP` on terminal state. | `PROJECT.md` Feature 20; `db/init.sql` lines 114-138; `test_f20_01` & `test_f20_04` |
| 20c | Integration | Pipeline Dual-Source Bar Loader | Resolves historical bar data per ticker, reading Snappy Parquet cache first (`data/parquet/<ticker>.parquet`), falling back to PostgreSQL `stock_daily_bars`. | `ticker`, lookback period / start date. | List of daily bar dicts or Polars DataFrame. | Cleans up corrupt/0-byte Parquet files; returns empty list if ticker has no recorded bars. | `PROJECT.md` §Interface Contracts; `parquet_cache.py`; `db.py` |
| 20d | Integration | Batch Screening Coordinator | Coordinates end-to-end weekly screening over universe (~3,500 tickers): loads SPY benchmark, screens tickers, upserts signals, logs audit job. | `tickers` list (optional), `sample` (optional), `scan_date` (optional). | Execution summary dict (`tickers_total`, `processed`, `failed`, `signals_found`, `scan_id`). | Logs errors per ticker without halting batch; fails `scan_job` if benchmark SPY missing. | `PROJECT.md` Code Layout; `screener/src/screener.py`; `screener/src/main.py` |
| 21-23 | Downstream Interface | Telegram Alert Payload Supplier | Provides formatted stock signal payloads with company metadata for Telegram HTML cards and chunking. | Qualified signals from screener engine. | Telegram stock card dicts with `ticker`, `name`, `sector`, prices, diff %, badges, surge, MRS. | Enforces URL generation `http://localhost:5173/stock/<ticker>` and standard badge emojis. | `PROJECT.md` Interface Contract 2; `test_f21_f23_telegram.py`; `test_t3_screener_to_telegram.py` |
| 24-28 | Downstream Interface | Backend REST API Query Model | Supplies structured relational data for `/api/screener/latest`, `/api/screener/dates`, `/api/stock/:ticker/summary`, and `/api/stock/:ticker/chart`. | HTTP Query parameters (`date`, `sector`, `status`, `search`, `page`, `limit`, `sort_by`, `order`). | Paginated JSON signal envelopes, date arrays, chart candlestick + SMA arrays. | Returns empty arrays on 0 signals; returns 404 on missing stock; verifies ISO date order. | `PROJECT.md` Interface Contract 3; `test_f24_f30_backend_api.py`; `api_validator.py` |

---

## 3. Edge Cases & Boundary Conditions

| # | Feature | Input / Boundary Condition | Observed & Required Behavior |
|---|---------|---------------------------|------------------------------|
| 1 | Resampling | Single-day trading week (emergency closure) | Resamples to 1 weekly bar with `trading_days=1`, `open=close=high=low`, volume=day volume. |
| 2 | Resampling | Good Friday 4-day week (Friday market holiday) | Aggregates Monday–Thursday. Weekly close is Thursday's close; `trade_date` is Thursday's date (`2026-04-09`). |
| 3 | Resampling | Midweek holiday (e.g., Wednesday holiday closure) | Aggregates Mon, Tue, Thu, Fri. `trading_days=4`, open is Mon open, close is Fri close. |
| 4 | Resampling | Mega-cap weekly volume exceeding 32-bit integer | Volume $> 2,147,483,647$ shares (e.g., 3B shares) must use 64-bit integer (`BIGINT` in DB, `Int64` in Polars). |
| 5 | Resampling | Flat price week (halted stock) | `high == low == open == close`, volume = 0; no exception thrown. |
| 6 | 30w SMA | Exactly 29 weekly bars of history | Returns `None` for all 29 weeks. Index 29 (week 30) is the first non-null SMA value. |
| 7 | 30w SMA Slope | Prior SMA value is 0.0 | Division-by-zero guard triggers; returns `None` instead of throwing `ZeroDivisionError`. |
| 8 | 30w SMA Slope | Exact flat slope ($Slope = 0.0000\%$) | Meets qualification ($Slope \ge 0.0$ evaluates to `True`). |
| 9 | 30w SMA Slope | Micro-negative slope ($Slope = -0.0001\%$) | Fails qualification ($Slope \ge 0.0$ evaluates to `False`). |
| 10 | 10w Volume | Exactly 9 weekly bars of volume | Returns `None` for 10-week average volume and surge ratio. |
| 11 | 10w Volume | Prior 10 weeks have zero volume ($avg\_vol = 0$) | Division-by-zero guard triggers; returns `surge_ratio = 0.0` instead of `ZeroDivisionError`. |
| 12 | 10w Volume | Volume surge ratio is exactly 1.4999x | Fails Stage 2 qualification ($1.4999 \ge 1.50$ is `False`). |
| 13 | 10w Volume | Volume surge ratio is exactly 1.5000x | Passes Stage 2 qualification ($1.5000 \ge 1.50$ is `True`). |
| 14 | 10w Volume | Breakout week has massive volume (e.g. 10M vs 1M avg) | Current week's 10M volume is excluded from prior 10w average calculation ($avg = 1M$, surge = 10.0x). |
| 15 | 35w Resistance | Exactly 34 weekly bars of highs | Returns `None` for 35-week resistance pivot. |
| 16 | 35w Resistance | Current weekly close equals pivot ($Close == 100.0000$) | Qualifies breakout ($Close \ge Pivot$ is `True`). |
| 17 | 35w Resistance | Current weekly close is 1 cent below ($Close = 99.99$ vs $100.00$) | Fails breakout ($99.99 \ge 100.00$ is `False`). |
| 18 | 35w Resistance | Resistance peak occurred at oldest lookback week ($t-35$) | Peak is retained throughout the entire 35-week lookback window. |
| 19 | Mansfield RS | Exactly 51 weekly bars of aligned stock & SPY data | Returns `None` for 52-week MRS score. |
| 20 | Mansfield RS | Stock tracks SPY ratio identically for 52 weeks | MRS score is exactly $0.0000$. Fails $MRS > 0.0$ predicate ($0.0000 > 0.0$ is `False`). |
| 21 | Mansfield RS | Micro-positive MRS score ($MRS = +0.0001$) | Passes Stage 2 qualification ($0.0001 > 0.0$ is `True`). |
| 22 | Mansfield RS | Benchmark SPY close is 0.0 or negative | Division-by-zero guard sets RS ratio to 0.0, avoiding fatal exception. |
| 23 | Stage 2 Filter | 4 factors pass, only 1 factor fails | Evaluates to `False` (`is_stage2 = False`). Rejection must occur if even one factor fails. |
| 24 | Target & Risk | Pivot has fractional cents ($12.3456) | All calculated targets round to 4 decimal places ($max\_buy = 12.9629$). |
| 25 | Target & Risk | Provided swing low is higher than entry price ($105 vs $100) | Ignored as invalid; falls back to default 8% stop loss ($entry * 0.92 = 92.00$). |
| 26 | Target & Risk | Provided swing low is negative ($-10.0$) | Ignored as invalid; falls back to default 8% stop loss. |
| 27 | Entry Status | Current price equals stop loss exact ($92.00 == 92.00$) | Categorized as `BELOW_ENTRY` (`STOPPED_OUT` is strictly $price < stop\_loss$). |
| 28 | Entry Status | Current price is 1 cent below stop loss ($91.99$ vs $92.00$) | Categorized as `STOPPED_OUT`. |
| 29 | Entry Status | Current price equals entry price exact ($100.00 == 100.00$) | Categorized as `IN_BUY_ZONE`. |
| 30 | Entry Status | Current price equals max buy price exact ($105.00 == 105.00$) | Categorized as `IN_BUY_ZONE`. |
| 31 | Entry Status | Current price is 1 cent above max buy ($105.01$ vs $105.00$) | Categorized as `EXTENDED`. |
| 32 | Persistence | Re-running scan on same date for same ticker | Database UPSERT updates existing record via `ON CONFLICT (scan_date, ticker)`; zero duplicate rows created. |
| 33 | Persistence | Duplicate records in the same batch list | Internal dictionary deduplication by `(scan_date, ticker)` prevents PostgreSQL 21000 cardinality error. |
| 34 | Persistence | Foreign key check: Ticker not in `stocks` table | Screener must ensure ticker is in `stocks` (`ensure_stocks_exist`) before signal insertion to avoid FK violation. |
| 35 | Audit Jobs | Zero breakouts discovered across universe (bear market) | Audit job logs `status='COMPLETED'`, `signals_found=0`, `error_message=NULL`. |

---

## 4. Deep-Dive Specification 1: Database Persistence (`screener_signals` & `scan_jobs`)

### 4.1. Table Schemas (`db/init.sql` Lines 114–177)

#### Table `scan_jobs`
```sql
CREATE TABLE IF NOT EXISTS scan_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_type VARCHAR(64) NOT NULL DEFAULT 'WEEKLY_SCREEN',
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING'
        CONSTRAINT chk_scan_jobs_status CHECK (
            status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')
        ),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    tickers_total INTEGER NOT NULL DEFAULT 0,
    tickers_processed INTEGER NOT NULL DEFAULT 0,
    tickers_failed INTEGER NOT NULL DEFAULT 0,
    signals_found INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    telegram_alert_sent BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### Table `screener_signals`
```sql
CREATE TABLE IF NOT EXISTS screener_signals (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT REFERENCES scan_jobs(id) ON DELETE SET NULL,
    scan_date DATE NOT NULL,
    ticker VARCHAR(16) NOT NULL REFERENCES stocks(ticker) ON DELETE CASCADE,
    
    -- Price and Pivot Points (USD)
    entry_price NUMERIC(12, 4) NOT NULL,
    max_buy_price NUMERIC(12, 4) NOT NULL,
    current_price NUMERIC(12, 4) NOT NULL,
    stop_loss_price NUMERIC(12, 4) NOT NULL,
    diff_pct NUMERIC(8, 4) NOT NULL,
    
    -- Entry Status Badge
    entry_status VARCHAR(32) NOT NULL
        CONSTRAINT chk_screener_signals_entry_status CHECK (
            entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT')
        ),
    
    -- Weinstein Stage 2 Indicators & Volume Metrics
    volume_surge_ratio NUMERIC(8, 4) NOT NULL,
    mrs_score NUMERIC(10, 4) NOT NULL,
    sma_30w NUMERIC(12, 4) NOT NULL,
    sma_30w_slope NUMERIC(8, 4) NOT NULL,
    prior_resistance_35w NUMERIC(12, 4) NOT NULL,
    weekly_close NUMERIC(12, 4) NOT NULL,
    weekly_volume BIGINT NOT NULL,
    avg_volume_10w BIGINT NOT NULL,
    stage VARCHAR(32) NOT NULL DEFAULT 'Stage 2 Breakout',
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_scan_date_ticker UNIQUE (scan_date, ticker),
    CONSTRAINT chk_screener_signals_positive_entry CHECK (entry_price > 0),
    CONSTRAINT chk_screener_signals_positive_current CHECK (current_price > 0)
);
```

### 4.2. Authoritative PostgreSQL UPSERT Syntax

To satisfy idempotency and ensure repeated runs update signal metrics rather than failing on unique violation:
```sql
INSERT INTO screener_signals (
    scan_id, scan_date, ticker,
    entry_price, max_buy_price, current_price, stop_loss_price, diff_pct,
    entry_status, volume_surge_ratio, mrs_score, sma_30w, sma_30w_slope,
    prior_resistance_35w, weekly_close, weekly_volume, avg_volume_10w, stage
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
```

### 4.3. Cardinality Violation & Foreign Key Safeguards

1. **In-Batch Deduplication Guard**:
   PostgreSQL raises `ERROR 21000: ON CONFLICT DO UPDATE command cannot affect row a second time` if duplicate keys `(scan_date, ticker)` appear in the same multi-row insert batch. In `screener/src/db.py`:
   ```python
   deduped_signals: Dict[Tuple[str, str], Dict[str, Any]] = {}
   for sig in signals_list:
       key = (str(sig["scan_date"]), sig["ticker"])
       deduped_signals[key] = sig
   values = list(deduped_signals.values())
   ```
2. **Foreign Key Integrity**:
   `screener_signals.ticker` references `stocks(ticker) ON DELETE CASCADE`. If a newly added stock is not yet in `stocks`, the insertion fails. Before upserting signals:
   `db.ensure_stocks_exist([s["ticker"] for s in signals_list], cur=cur)` must be called.
3. **Execution Audit State Machine (`scan_jobs`)**:
   - `create_scan_job(job_type='WEEKLY_SCREEN', status='RUNNING', tickers_total=N) -> job_id`
   - `update_scan_job(job_id, status='COMPLETED'|'FAILED', tickers_processed=P, tickers_failed=F, signals_found=S, error_message=E, completed=True)`
   - When entering terminal states (`COMPLETED`, `FAILED`), set `completed_at = CURRENT_TIMESTAMP`.

---

## 5. Deep-Dive Specification 2: Ingestion-to-Screener Pipeline Integration

### 5.1. Dual-Source Historical Bar Loading

```
               ┌────────────────────────────────────────────────────────┐
               │           Screener Pipeline Bar Loader                 │
               └──────────────────────────┬─────────────────────────────┘
                                          │
                     Check local Parquet cache file?
                     screener/data/parquet/<ticker>.parquet
                                   /             \
                       [Exists & Valid]        [Missing or Corrupted]
                                 /                 \
                                ▼                   ▼
                      Read via Polars /       Query PostgreSQL:
                      pyarrow table           SELECT * FROM stock_daily_bars
                                              WHERE ticker = %s ORDER BY date
                                 \                 /
                                  ▼               ▼
                      Validate length >= 260 trading days (52 weeks)
                                          │
                                          ▼
                      Pass to Polars Weekly Resampling Engine
```

### 5.2. Polars Vectorized Weekly Resampling Specifications

Input: Daily OHLCV DataFrame sorted by `trade_date` ascending.
Columns: `ticker`, `trade_date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`.

1. Convert `trade_date` to Polars `Date` type.
2. Extract ISO Year and ISO Week:
   ```python
   df = df.with_columns([
       pl.col("trade_date").dt.iso_year().alias("iso_year"),
       pl.col("trade_date").dt.week().alias("iso_week"),
   ])
   ```
3. Group by `["iso_year", "iso_week"]` and aggregate:
   - `open`: `pl.col("open").first()`
   - `high`: `pl.col("high").max()`
   - `low`: `pl.col("low").min()`
   - `close`: `pl.col("close").last()`
   - `adj_close`: `pl.col("adj_close").last()`
   - `volume`: `pl.col("volume").sum().cast(pl.Int64)`
   - `trade_date`: `pl.col("trade_date").last()` (resolves holiday Thursday or Friday close)
   - `trading_days`: `pl.col("trade_date").count().cast(pl.Int32)`
4. Sort by `trade_date` ascending.

### 5.3. Indicator Calculation Math & Polars Expressions

1. **30-Week Simple Moving Average (SMA)**:
   $$\text{SMA}_{30}(t) = \frac{1}{30} \sum_{i=0}^{29} \text{Close}(t-i)$$
   Polars expression:
   `pl.col("close").rolling_mean(window_size=30, min_periods=30).alias("sma_30w")`
   Indices $0..28$ evaluate to `null`. Index 29 evaluates to the first valid average.

2. **30-Week SMA Slope**:
   $$\text{Slope}_{\text{SMA}}(t) = \frac{\text{SMA}_{30}(t) - \text{SMA}_{30}(t-1)}{\text{SMA}_{30}(t-1)} \times 100\%$$
   Polars expression:
   `pl.when(pl.col("sma_30w").shift(1) > 0).then(((pl.col("sma_30w") - pl.col("sma_30w").shift(1)) / pl.col("sma_30w").shift(1)) * 100.0).otherwise(None).alias("sma_30w_slope")`

3. **10-Week Prior Volume Average & Surge Ratio**:
   $$\overline{\text{Vol}}_{10}(t) = \frac{1}{10} \sum_{i=1}^{10} \text{Volume}(t-i)$$
   $$\text{Surge Ratio}(t) = \frac{\text{Volume}(t)}{\overline{\text{Vol}}_{10}(t)}$$
   Polars expressions:
   `pl.col("volume").shift(1).rolling_mean(window_size=10, min_periods=10).alias("avg_volume_10w")`
   `pl.when(pl.col("avg_volume_10w") > 0).then(pl.col("volume") / pl.col("avg_volume_10w")).otherwise(0.0).alias("volume_surge_ratio")`

4. **35-Week Prior Resistance Pivot**:
   $$\text{Pivot}_{35}(t) = \max_{i=1}^{35} \text{High}(t-i)$$
   Polars expression:
   `pl.col("high").shift(1).rolling_max(window_size=35, min_periods=35).alias("prior_resistance_35w")`

5. **Mansfield Relative Strength (MRS) vs SPY**:
   - Align Stock weekly bars with SPY weekly bars on `trade_date`:
     $$RS(t) = \frac{\text{Stock Close}(t)}{\text{SPY Close}(t)}$$
   - 52-week rolling average:
     $$\overline{RS}_{52}(t) = \frac{1}{52} \sum_{i=0}^{51} RS(t-i)$$
   - Mansfield score:
     $$MRS(t) = \left( \frac{RS(t)}{\overline{RS}_{52}(t)} - 1.0 \right) \times 100$$
   Polars expression:
   `pl.when(pl.col("spy_close") > 0).then(pl.col("close") / pl.col("spy_close")).otherwise(0.0).alias("rs")`
   `pl.col("rs").rolling_mean(window_size=52, min_periods=52).alias("rs_sma52")`
   `pl.when(pl.col("rs_sma52") > 0).then(((pl.col("rs") / pl.col("rs_sma52")) - 1.0) * 100.0).otherwise(0.0).alias("mrs_score")`

### 5.4. Stage 2 Multi-Factor Filter Predicate

A stock qualifies as a Stan Weinstein Stage 2 Breakout if and only if all 5 conditions evaluate to `True` at the latest completed weekly bar:
```python
cond_close_above_sma = (sma_30w is not None) and (close > sma_30w)
cond_sma_rising      = (sma_30w_slope is not None) and (sma_30w_slope >= 0.0)
cond_pivot_breakout  = (prior_resistance_35w is not None) and (close >= prior_resistance_35w)
cond_volume_surge    = (volume_surge_ratio is not None) and (volume_surge_ratio >= 1.50)
cond_mrs_positive    = (mrs_score is not None) and (mrs_score > 0.0)

is_stage2 = (
    cond_close_above_sma and
    cond_sma_rising and
    cond_pivot_breakout and
    cond_volume_surge and
    cond_mrs_positive
)
```

### 5.5. Target & Risk Math and Status Categorization

For each qualified signal:
- $\text{Entry Price} = \text{round}(\text{prior\_resistance\_35w}, 4)$
- $\text{Max Buy Price} = \text{round}(\text{entry\_price} \times 1.05, 4)$
- $\text{Stop Loss Price} = \text{round}(\text{swing\_low}, 4)$ if ($0 < \text{swing\_low} < \text{entry\_price}$) else $\text{round}(\text{entry\_price} \times 0.92, 4)$
- $\text{Current Price} = \text{round}(\text{weekly\_close}, 4)$
- $\text{Diff \%} = \text{round}\left( \frac{\text{current\_price} - \text{entry\_price}}{\text{entry\_price}} \times 100.0, 4 \right)$

Status classification rules:
- $\text{current\_price} < \text{stop\_loss\_price} \implies \text{'STOPPED\_OUT'}$
- $\text{current\_price} < \text{entry\_price} \implies \text{'BELOW\_ENTRY'}$
- $\text{current\_price} \le \text{max\_buy\_price} \implies \text{'IN\_BUY\_ZONE'}$
- $\text{current\_price} > \text{max\_buy\_price} \implies \text{'EXTENDED'}$

---

## 6. Deep-Dive Specification 3: Downstream Interface Contracts

### 6.1. Screener Engine ↔ Milestone 4 (Telegram Alerts)

When the weekly screening job completes, the screener engine dispatches the found signals to the Telegram alerting module (`send_weekly_alert(signals, scan_date, universe_count)`).

#### Payload Dictionary Requirements per Signal
```json
{
  "ticker": "CRWD",
  "name": "CrowdStrike Holdings Inc.",
  "sector": "Technology",
  "entry_price": 320.0000,
  "current_price": 328.5000,
  "max_buy_price": 336.0000,
  "stop_loss_price": 294.4000,
  "diff_pct": 2.6563,
  "entry_status": "IN_BUY_ZONE",
  "volume_surge_ratio": 2.3450,
  "mrs_score": 12.8500,
  "sma_30w": 285.2000,
  "sma_30w_slope": 1.1500
}
```

*Note on Metadata Enrichment*: Because `screener_signals` only stores `ticker`, the screener or query layer must join with `stocks` (or retrieve from universe dictionary) to supply `name` and `sector`.

#### Formatting & HTML Card Rules
- Base URL for chart links: `http://localhost:5173/stock/<ticker>`
- Status Badges:
  - `IN_BUY_ZONE`: `🟢 <b>IN BUY ZONE</b>`
  - `EXTENDED`: `🟠 <b>EXTENDED</b>`
  - `BELOW_ENTRY`: `⚪ <b>BELOW ENTRY</b>`
  - `STOPPED_OUT`: `🔴 <b>STOPPED OUT</b>`
- Chunker rule: Maximum 3,800 characters per message part, split strictly on `\n\n` boundary between stock cards so HTML tags (`<b>`, `<a>`) are never bisected.

### 6.2. Milestone 3 ↔ Milestone 5 (Backend Express REST API)

Milestone 5 Express REST API queries the database persisted by Milestone 3:

#### 1. `GET /api/screener/latest`
- Query parameters: `date` (ISO), `sector`, `status`, `search`, `sort_by`, `order`, `page`, `limit`.
- SQL Join:
  ```sql
  SELECT 
    s.id, s.scan_id, s.scan_date, s.ticker,
    stk.name AS company_name, stk.sector, stk.industry, stk.market_cap,
    s.entry_price, s.max_buy_price, s.current_price, s.stop_loss_price,
    s.diff_pct, s.entry_status, s.volume_surge_ratio, s.mrs_score,
    s.sma_30w, s.sma_30w_slope, s.prior_resistance_35w,
    s.weekly_close, s.weekly_volume, s.avg_volume_10w, s.stage, s.created_at
  FROM screener_signals s
  JOIN stocks stk ON s.ticker = stk.ticker
  WHERE s.scan_date = COALESCE($1, (SELECT MAX(scan_date) FROM screener_signals))
  ```
- Output contract envelope:
  ```json
  {
    "success": true,
    "data": {
      "scan_date": "2026-10-09",
      "total": 45,
      "page": 1,
      "limit": 50,
      "total_pages": 1,
      "signals": [ /* Array of enriched signals */ ]
    }
  }
  ```

#### 2. `GET /api/screener/dates`
- Query: `SELECT DISTINCT scan_date FROM screener_signals ORDER BY scan_date DESC;`
- Output envelope: `{ "success": true, "data": { "dates": ["2026-10-09", "2026-10-02"] } }`

#### 3. `GET /api/stock/:ticker/summary`
- Output includes `latest_signal` from `screener_signals` (latest `scan_date`) and `latest_daily_bar` from `stock_daily_bars`.

#### 4. `GET /api/stock/:ticker/chart`
- Lightweight Charts payload containing candlesticks (time ascending), `sma30` series, volume series, and `metrics`:
  ```json
  {
    "entry_price": 150.0,
    "max_buy_price": 157.5,
    "stop_loss_price": 138.0,
    "status": "IN_BUY_ZONE",
    "close_price": 153.5
  }
  ```

---

## 7. Deep-Dive Specification 4: Verification Suite Specification (`screener/verify_m3.py`)

### 7.1. Verification File Structure (`screener/verify_m3.py`)

Following the architecture of `screener/verify_m2.py`, `screener/verify_m3.py` must be a self-contained, high-speed test suite runnable via standard Python `unittest` without external Postgres/Redis dependencies.

#### Target Test Classes and Cases
1. `TestM3DeliverablesExist`:
   - Checks presence and non-emptiness of:
     - `screener/src/indicators.py`
     - `screener/src/screener.py`
     - `screener/src/db.py` (with M3 methods: `upsert_screener_signals`, `create_scan_job`, `update_scan_job`)
     - `screener/src/main.py` (with `--mode screen` CLI support)
2. `TestWeeklyResamplingEngine`:
   - 5-day standard week aggregation
   - 4-day Good Friday / Thanksgiving short week (Thursday close)
   - 1-day emergency closure short week
   - Volume summation and 64-bit integer overflow protection
   - Extreme high and low selection
3. `TestIndicatorMath30wSMA`:
   - 29 weeks returns None; 30th week computes correct arithmetic mean
   - Slope positive uptrend, flat zero, negative downtrend, division by zero guard
4. `TestIndicatorMath10wVolumeSurge`:
   - 10-week prior rolling average excludes current breakout week
   - Exact boundary checks: 1.4999 fails, 1.5000 passes
   - Zero prior volume division-by-zero guard
5. `TestIndicatorMath35wResistancePivot`:
   - 35-week prior rolling max excludes current breakout week
   - Exact breakout predicate ($Close == Pivot \implies True$, $Close < Pivot \implies False$)
6. `TestIndicatorMathMansfieldRS`:
   - 52-week requirement (51 weeks returns None)
   - Constant RS ratio equals 0.0000; zero crossover predicate ($0.0000 > 0.0 \implies False$, $0.0001 > 0.0 \implies True$)
   - SPY close $\le 0$ division-by-zero guard
7. `TestStage2MultiFactorFilter`:
   - All 5 conditions satisfied $\implies True$
   - 4 conditions satisfied, 1 fails $\implies False$ (isolated failure for each factor)
8. `TestTargetAndRiskMath`:
   - Entry equals pivot, max buy is $+5\%$, default stop is $-8\%$
   - Swing low override ($0 < swing\_low < entry$)
   - Negative swing low or swing low $\ge entry$ defaults back to 8% stop
   - Deterministic 4-state entry status categorization and boundary transitions
9. `TestDatabasePersistenceContracts`:
   - `screener_signals` schema mapping and SQL generator check
   - In-batch signal deduplication preventing Postgres 21000 cardinality error
   - `scan_jobs` state machine transitions (`RUNNING` $\to$ `COMPLETED` / `FAILED`)

### 7.2. Verification Commands by Team Role

| Role | Verification Command | Purpose & Criteria |
|------|----------------------|--------------------|
| **Worker / Developer** | `python screener/verify_m3.py -v` | Unit verification of all M3 deliverables, math formulas, and SQL generators (0 errors). |
| **Worker / Developer** | `python tests/run_e2e.py --feature 12 --feature 13 --feature 14 --feature 15 --feature 16 --feature 17 --feature 18 --feature 19 --feature 20` | Verifies full Tier 1 isolation tests for Features 12 through 20 (45 tests pass). |
| **Reviewer** | `python tests/run_e2e.py --tier 1` | Verifies Features 1–20 pass without regressions in M1/M2 or cross-feature contamination. |
| **Challenger** | `python tests/run_e2e.py --tier 2` | Executes all 180 Boundary & Corner tests, specifically `test_t2_indicators_boundaries.py` (30 tests). |
| **Challenger** | `python tests/run_e2e.py --tier 3` | Executes cross-module interaction tests (`test_t3_ingest_to_screener.py` & `test_t3_screener_to_telegram.py`). |
| **Challenger** | `python tests/run_e2e.py --tier 4` | Executes `test_t4_weekly_delta_breakout_flow.py` and `test_t4_market_holiday_resampling_flow.py`. |
| **Auditor** | `python tests/run_e2e.py` | Full E2E regression run: 100% pass across all 381 tests (Tiers 1–4). |

---

## 8. Handoff Protocol (5 Components)

### 8.1. Observation
1. **Schema DDL**: `db/init.sql` lines 114–177 define `scan_jobs` (id, status CHECK, timestamps, counters) and `screener_signals` (scan_id, scan_date, ticker, prices, indicators, `UNIQUE (scan_date, ticker)`).
2. **Mathematical Oracles**: `tests/e2e/helpers/formula_oracle.py` contains the authoritative reference implementations for `oracle_resample_daily_to_weekly`, `oracle_sma`, `oracle_sma_slope`, `oracle_volume_surge`, `oracle_prior_resistance_pivot`, `oracle_mansfield_relative_strength`, `oracle_stage2_filter`, `oracle_target_and_risk`, and `oracle_entry_status`.
3. **Boundary Specifications**: `tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py` codifies exact edge cases: Good Friday 4-day week, 1-day week, 64-bit volume, slope flat zero, volume surge 1.4999 vs 1.5000, MRS 0.0000 vs 0.0001, swing low invalidation, exact status thresholds ($price == max\_buy \implies IN\_BUY\_ZONE$; $price == stop \implies BELOW\_ENTRY$).
4. **Existing Codebase State**: `screener/src/` currently contains M2 modules (`config.py`, `universe.py`, `downloader.py`, `parquet_cache.py`, `sync.py`, `db.py`, `main.py`). `db.py` contains stock and bar upserts but lacks `screener_signals` and `scan_jobs` persistence helpers. `indicators.py` and `screener.py` need to be implemented for M3.
5. **Existing Verification Precedent**: `screener/verify_m2.py` (466 lines) establishes the pattern for self-contained, dependency-free unit testing for milestone deliverables.

### 8.2. Logic Chain
1. *From schema `uq_scan_date_ticker UNIQUE (scan_date, ticker)`*: Multiple scans on the same Friday will trigger unique constraint violations unless PostgreSQL `ON CONFLICT (scan_date, ticker) DO UPDATE` is used.
2. *From PostgreSQL execute_values behavior*: If duplicate `(scan_date, ticker)` entries exist within a single batch, PostgreSQL throws cardinality error 21000. Therefore, `upsert_screener_signals` must deduplicate signals in-memory by `(scan_date, ticker)` prior to database execution.
3. *From foreign key `REFERENCES stocks(ticker) ON DELETE CASCADE`*: Signal insertions fail if the ticker is missing from `stocks`. Therefore, the batch screener must call `ensure_stocks_exist` or rely on `universe.sync_universe_to_db()`.
4. *From indicator lookback windows*: 30w SMA requires 30 weeks; 35w pivot requires 36 weeks; 52w MRS requires 52 weeks (~260 trading days). Therefore, any stock with fewer than 52 weekly bars must be safely skipped or flagged as having insufficient history without crashing the screening loop.
5. *From downstream M4 and M5 requirements*: `screener_signals` contains quantitative indicators but not `name` or `sector`. Downstream consumers (Telegram alerts and REST API) require joining `screener_signals` with `stocks` on `ticker` to render complete stock cards.

### 8.3. Caveats
1. **Polars vs Pure Python**: Polars is specified in requirements (`requirements.txt`), but in unit test environments without Polars installed, `verify_m3.py` should implement fallback or pure Python verification paths so verification passes seamlessly in any minimal environment.
2. **SPY Benchmark Dependency**: Mansfield RS requires synchronized SPY bars. If the SPY Parquet cache is missing or corrupt, the screener cannot compute MRS. The pipeline must fail gracefully with an explicit message in `scan_jobs.error_message`.
3. **Swing Low Availability**: If granular swing low data is omitted, the default stop loss must deterministically fall back to `entry_price * 0.92`.

### 8.4. Conclusion
The specification for Milestone 3 is completely mined and documented. The engineering worker has explicit schemas, Polars expressions, SQL upsert statements, boundary threshold guards, downstream interface contracts, and verification blueprints to implement `screener/src/indicators.py`, `screener/src/screener.py`, `screener/src/db.py` updates, and `screener/verify_m3.py` with zero ambiguity.

### 8.5. Verification Method
1. Inspect this handoff report: `d:/git/StockSentinel/.agents/teamwork/spec_miner_m3_3/handoff.md`
2. Validate feature coverage: compare section 2 against `PROJECT.md` Features 12–20.
3. Validate formula definitions: compare section 5 against `tests/e2e/helpers/formula_oracle.py`.
4. Validate boundary conditions: compare section 3 against `tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py`.
5. Run the authoritative test suites when ready:
   - `python tests/run_e2e.py --feature 12`
   - `python tests/run_e2e.py --tier 1`
   - `python tests/run_e2e.py --tier 2`
