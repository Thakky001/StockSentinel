# StockSentinel E2E Test Infrastructure & Feature Coverage Matrix

## 1. Overview & Test Architecture

StockSentinel's end-to-end (E2E) test suite provides an **opaque-box verification system** derived strictly from user requirements in `ORIGINAL_REQUEST.md` and the 36-feature inventory in `PROJECT.md`.

The test architecture is designed with **zero circular dependencies**: it relies on an independent, authoritative mathematical oracle (`tests/e2e/helpers/formula_oracle.py`), an in-memory relational schema emulator (`tests/e2e/helpers/sql_validator.py`), and a REST API contract validator (`tests/e2e/helpers/api_validator.py`). Tests execute out-of-the-box using the Python standard library without requiring external packages or live cloud services.

```
tests/
├── run_e2e.py                          # Unified CLI Test Runner
├── run_e2e.js                          # Node.js Wrapper Runner
└── e2e/
    ├── helpers/
    │   ├── mock_data.py                # Deterministic synthetic OHLCV & universe generator
    │   ├── formula_oracle.py           # Ground-truth math oracle for indicators & risk
    │   ├── sql_validator.py            # DDL parser & in-memory relational engine
    │   └── api_validator.py            # Express REST API & Lightweight Charts validator
    ├── tier1_features/                 # Tier 1: Feature Isolation Coverage (180 tests)
    │   ├── test_f01_f06_database.py        # Features 1-6 (Database & Infra)
    │   ├── test_f07_f11_universe_ingest.py # Features 7-11 (Universe & Ingest)
    │   ├── test_f12_f20_screener_math.py   # Features 12-20 (Screener & Indicators)
    │   ├── test_f21_f23_telegram.py        # Features 21-23 (Telegram Alerting)
    │   ├── test_f24_f30_backend_api.py     # Features 24-30 (Express REST API)
    │   └── test_f31_f36_frontend_calc.py   # Features 31-36 (UI & Calculator)
    ├── tier2_boundaries/               # Tier 2: Boundary & Corner Cases (180 tests)
    │   ├── test_t2_database_boundaries.py
    │   ├── test_t2_universe_boundaries.py
    │   ├── test_t2_indicators_boundaries.py
    │   ├── test_t2_telegram_boundaries.py
    │   ├── test_t2_api_boundaries.py
    │   └── test_t2_frontend_calc_boundaries.py
    ├── tier3_interactions/             # Tier 3: Cross-Feature Combinations (16 tests)
    │   ├── test_t3_ingest_to_screener.py
    │   ├── test_t3_screener_to_telegram.py
    │   ├── test_t3_database_to_api.py
    │   └── test_t3_api_to_frontend_chart.py
    └── tier4_scenarios/                # Tier 4: Real-World Scenarios (5 tests)
        ├── test_t4_cold_start_to_dashboard.py
        ├── test_t4_weekly_delta_breakout_flow.py
        ├── test_t4_market_holiday_resampling_flow.py
        ├── test_t4_telegram_alert_flood_flow.py
        └── test_t4_investor_risk_workflow.py
```

---

## 2. Test Tier Definitions & Methodology

The test suite applies formal test design methodologies across 4 hierarchical tiers:

### Tier 1: Feature Isolation Coverage
- **Methodology**: Category-Partitioning of each feature's specification into discrete behavioral contracts.
- **Requirement**: Minimum 5 tests per feature in complete isolation.
- **Scope**: Features 1–36 (36 features × 5 tests = **180 tests**).

### Tier 2: Boundary & Corner Cases
- **Methodology**: Boundary Value Analysis (BVA) at domain limits (0, 1, max, negative, null, precision thresholds, division-by-zero guards, buffer limits).
- **Requirement**: Minimum 5 boundary tests per feature at limit extremes.
- **Scope**: Features 1–36 (36 features × 5 tests = **180 tests**).

### Tier 3: Cross-Feature Pairwise Interactions
- **Methodology**: Combinatorial Pairwise Testing across module interfaces.
- **Scope**:
  - `M2 x M3`: Daily ingestion bars → Parquet cache → Weekly resampling → Indicators.
  - `M3 x M4`: Stage 2 Screener signals → Telegram HTML card formatting & chunking.
  - `M1 x M5`: PostgreSQL relational tables → Express REST API query endpoints.
  - `M5 x M6`: Express chart endpoint → TradingView Lightweight Charts & Calculator.
- **Volume**: **16 comprehensive interaction tests**.

### Tier 4: Real-World Application Scenarios
- **Methodology**: Workload testing of end-to-end user journeys and automated operational cron workflows.
- **Scope**:
  - `Scenario 1`: Cold-start 2-year sync from empty database to interactive dashboard.
  - `Scenario 2`: Friday evening automated routine (7-day delta sync → breakout detection → Telegram alert → dashboard view).
  - `Scenario 3`: Market holiday short-week resampling (Good Friday / Thanksgiving Monday-Thursday aggregation).
  - `Scenario 4`: Bull market breakout flood (75 simultaneous alerts chunked under 3,800 chars without tag splits).
  - `Scenario 5`: Investor risk management workflow (trader filters IN_BUY_ZONE, views chart, calculates 1.25% risk sizing, stars to Watchlist).
- **Volume**: **5 end-to-end scenario tests**.

**Total Test Count**: **381 Test Cases**.

---

## 3. Complete Feature Coverage Matrix (Features 1–36)

| Feature # | Feature Name | Requirement | Milestone | Tier 1 Tests | Tier 2 Tests | Tier 3 & 4 Coverage | Total Tests |
|---|---|---|---|---|---|---|---|
| **1** | Docker Compose Infrastructure | R1 | M1 | `test_f01_01` to `test_f01_05` (5) | `test_t2_f01_01` to `05` (5) | `test_t4_cold_start_to_dashboard` | 11 |
| **2** | Master Stocks Schema | R1 | M1 | `test_f02_01` to `test_f02_05` (5) | `test_t2_f02_01` to `05` (5) | `test_t3_database_to_api` | 11 |
| **3** | Daily Bars Schema | R1 | M1 | `test_f03_01` to `test_f03_05` (5) | `test_t2_f03_01` to `05` (5) | `test_t3_database_to_api`, `test_t4_cold_start` | 12 |
| **4** | Scan Jobs Audit Schema | R1 | M1 | `test_f04_01` to `test_f04_05` (5) | `test_t2_f04_01` to `05` (5) | `test_t3_database_to_api` | 11 |
| **5** | Screener Signals Schema | R1 | M1 | `test_f05_01` to `test_f05_05` (5) | `test_t2_f05_01` to `05` (5) | `test_t3_database_to_api` | 11 |
| **6** | Migration & Init System | R1 | M1 | `test_f06_01` to `test_f06_05` (5) | `test_t2_f06_01` to `05` (5) | `test_t4_cold_start` | 11 |
| **7** | Combined Stock Universe | R2 | M2 | `test_f07_01` to `test_f07_05` (5) | `test_t2_f07_01` to `05` (5) | `test_t3_ingest_to_screener` | 11 |
| **8** | Resilient Batch Downloader | R2 | M2 | `test_f08_01` to `test_f08_05` (5) | `test_t2_f08_01` to `05` (5) | `test_t3_ingest_to_screener` | 11 |
| **9** | Delta Sync Engine | R2 | M2 | `test_f09_01` to `test_f09_05` (5) | `test_t2_f09_01` to `05` (5) | `test_t4_weekly_delta` | 11 |
| **10** | Parquet Local Cache | R2 | M2 | `test_f10_01` to `test_f10_05` (5) | `test_t2_f10_01` to `05` (5) | `test_t3_ingest_to_screener` | 11 |
| **11** | PostgreSQL Daily Upsert | R2 | M2 | `test_f11_01` to `test_f11_05` (5) | `test_t2_f11_01` to `05` (5) | `test_t4_cold_start` | 11 |
| **12** | Weekly Resampling Engine | R3 | M3 | `test_f12_01` to `test_f12_05` (5) | `test_t2_f12_01` to `05` (5) | `test_t3_ingest_to_screener`, `test_t4_holiday` | 12 |
| **13** | 30-Week SMA & Slope | R3 | M3 | `test_f13_01` to `test_f13_05` (5) | `test_t2_f13_01` to `05` (5) | `test_t3_ingest_to_screener`, `test_t4_cold_start` | 12 |
| **14** | 10-Week Volume Average & Surge | R3 | M3 | `test_f14_01` to `test_f14_05` (5) | `test_t2_f14_01` to `05` (5) | `test_t3_ingest_to_screener`, `test_t4_delta` | 12 |
| **15** | 35-Week Resistance Pivot | R3 | M3 | `test_f15_01` to `test_f15_05` (5) | `test_t2_f15_01` to `05` (5) | `test_t3_ingest_to_screener`, `test_t4_delta` | 12 |
| **16** | Mansfield Relative Strength | R3 | M3 | `test_f16_01` to `test_f16_05` (5) | `test_t2_f16_01` to `05` (5) | `test_t3_ingest_to_screener` | 11 |
| **17** | Stage 2 Breakout Filter | R3 | M3 | `test_f17_01` to `test_f17_05` (5) | `test_t2_f17_01` to `05` (5) | `test_t3_ingest_to_screener`, `test_t4_delta` | 12 |
| **18** | Target & Risk Math | R3 | M3 | `test_f18_01` to `test_f18_05` (5) | `test_t2_f18_01` to `05` (5) | `test_t3_screener_to_telegram`, `test_t4_investor` | 12 |
| **19** | Entry Status Categorization | R3 | M3 | `test_f19_01` to `test_f19_05` (5) | `test_t2_f19_01` to `05` (5) | `test_t3_screener_to_telegram`, `test_t4_delta` | 12 |
| **20** | Signals & Job Persistence | R3 | M3 | `test_f20_01` to `test_f20_05` (5) | `test_t2_f20_01` to `05` (5) | `test_t4_cold_start` | 11 |
| **21** | Telegram Alert Formatter | R4 | M4 | `test_f21_01` to `test_f21_05` (5) | `test_t2_f21_01` to `05` (5) | `test_t3_screener_to_telegram`, `test_t4_flood` | 12 |
| **22** | Message Chunker (4096-char) | R4 | M4 | `test_f22_01` to `test_f22_05` (5) | `test_t2_f22_01` to `05` (5) | `test_t3_screener_to_telegram`, `test_t4_flood` | 12 |
| **23** | Telegram API Dispatcher | R4 | M4 | `test_f23_01` to `test_f23_05` (5) | `test_t2_f23_01` to `05` (5) | `test_t4_flood` | 11 |
| **24** | Express Server & DB Pool | R5 | M5 | `test_f24_01` to `test_f24_05` (5) | `test_t2_f24_01` to `05` (5) | `test_t3_database_to_api` | 11 |
| **25** | Latest Screener Endpoint | R5 | M5 | `test_f25_01` to `test_f25_05` (5) | `test_t2_f25_01` to `05` (5) | `test_t3_database_to_api`, `test_t4_investor` | 12 |
| **26** | Scan Dates Endpoint | R5 | M5 | `test_f26_01` to `test_f26_05` (5) | `test_t2_f26_01` to `05` (5) | `test_t3_database_to_api` | 11 |
| **27** | Stock Chart Endpoint | R5 | M5 | `test_f27_01` to `test_f27_05` (5) | `test_t2_f27_01` to `05` (5) | `test_t3_api_to_frontend_chart`, `test_t4_holiday` | 12 |
| **28** | Stock Summary Endpoint | R5 | M5 | `test_f28_01` to `test_f28_05` (5) | `test_t2_f28_01` to `05` (5) | `test_t3_database_to_api` | 11 |
| **29** | Screener Trigger Endpoint | R5 | M5 | `test_f29_01` to `test_f29_05` (5) | `test_t2_f29_01` to `05` (5) | `test_t3_database_to_api` | 11 |
| **30** | Telegram Test Endpoint | R5 | M5 | `test_f30_01` to `test_f30_05` (5) | `test_t2_f30_01` to `05` (5) | - | 10 |
| **31** | React + Vite + Tailwind Setup | R6 | M6 | `test_f31_01` to `test_f31_05` (5) | `test_t2_f31_01` to `05` (5) | `test_t4_investor` | 11 |
| **32** | Interactive Screener Table | R6 | M6 | `test_f32_01` to `test_f32_05` (5) | `test_t2_f32_01` to `05` (5) | `test_t4_investor` | 11 |
| **33** | Lightweight Charts Modal | R6 | M6 | `test_f33_01` to `test_f33_05` (5) | `test_t2_f33_01` to `05` (5) | `test_t3_api_to_frontend_chart`, `test_t4_holiday` | 12 |
| **34** | Watchlist Drawer (LocalStorage) | R6 | M6 | `test_f34_01` to `test_f34_05` (5) | `test_t2_f34_01` to `05` (5) | `test_t4_investor` | 11 |
| **35** | Position Sizing Calculator | R6 | M6 | `test_f35_01` to `test_f35_05` (5) | `test_t2_f35_01` to `05` (5) | `test_t3_api_to_frontend_chart`, `test_t4_investor` | 12 |
| **36** | Full System Integration | Acceptance | M7 | `test_f36_01` to `test_f36_05` (5) | `test_t2_f36_01` to `05` (5) | `test_t4_cold_start_to_dashboard` | 11 |
| **TOTAL** | **36 Features** | **R1–R6** | **M1–M7** | **180 Tests** | **180 Tests** | **21 Tests** | **381 Tests** |

---

## 4. Ground-Truth Formula Oracles & Contracts

All test assertions compare against explicit mathematical specifications defined in `tests/e2e/helpers/formula_oracle.py`:

### 1. Weekly Resampling
- Aggregation: Monday-Friday ISO week bounds.
- Close: Last trading day close (Friday, or Thursday on holiday).
- High / Low: Extreme max and min across trading days in the week.
- Volume: $\sum \text{Daily Volume}$.

### 2. 30-Week Simple Moving Average (SMA) & Slope
$$\text{SMA}_{30}(t) = \frac{1}{30} \sum_{i=0}^{29} \text{Close}(t-i)$$
$$\text{Slope}_{\text{SMA}}(t) = \frac{\text{SMA}_{30}(t) - \text{SMA}_{30}(t-1)}{\text{SMA}_{30}(t-1)} \times 100\%$$
*Predicate*: $\text{Slope}_{\text{SMA}} \ge 0.0$ (flat or upward sloping).

### 3. 10-Week Volume Average & Surge Ratio
$$\overline{\text{Vol}}_{10}(t) = \frac{1}{10} \sum_{i=1}^{10} \text{Volume}(t-i)$$
$$\text{Surge Ratio}(t) = \frac{\text{Volume}(t)}{\overline{\text{Vol}}_{10}(t)}$$
*Predicate*: $\text{Surge Ratio} \ge 1.50$ (50% surge above 10w prior average).

### 4. 35-Week Resistance Pivot
$$\text{Pivot}_{35}(t) = \max_{i=1}^{35} \text{High}(t-i)$$
*Predicate*: $\text{Close}(t) \ge \text{Pivot}_{35}(t)$.

### 5. Mansfield Relative Strength (MRS) vs SPY Benchmark
$$\text{RS}(t) = \frac{\text{Stock Close}(t)}{\text{SPY Close}(t)}$$
$$\overline{\text{RS}}_{52}(t) = \frac{1}{52} \sum_{i=0}^{51} \text{RS}(t-i)$$
$$\text{MRS}(t) = \left( \frac{\text{RS}(t)}{\overline{\text{RS}}_{52}(t)} - 1.0 \right) \times 100$$
*Predicate*: $\text{MRS}(t) > 0.0$ (outperforming S&P 500 benchmark on 52-week relative basis).

### 6. Target, Risk & Status Classification
- $\text{Entry Price} = \text{Pivot}_{35}$
- $\text{Max Buy Price} = \text{Entry Price} \times 1.05$ (+5% chase boundary)
- $\text{Stop Loss Price} = \text{Swing Low}$ (or $\text{Entry Price} \times 0.92$)
- $\text{Diff \%} = \frac{\text{Current Price} - \text{Entry Price}}{\text{Entry Price}} \times 100\%$
- Status:
  - $\text{Current Price} < \text{Stop Loss} \implies \text{STOPPED\_OUT}$
  - $\text{Stop Loss} \le \text{Current Price} < \text{Entry Price} \implies \text{BELOW\_ENTRY}$
  - $\text{Entry Price} \le \text{Current Price} \le \text{Max Buy Price} \implies \text{IN\_BUY\_ZONE}$
  - $\text{Current Price} > \text{Max Buy Price} \implies \text{EXTENDED}$

### 7. Position Sizing Calculator
$$\text{Max Dollar Risk} = \text{Account Size} \times \frac{\text{Risk \%}}{100}$$
$$\text{Risk Per Share} = \text{Entry Price} - \text{Stop Loss Price}$$
$$\text{Shares to Buy} = \left\lfloor \frac{\text{Max Dollar Risk}}{\text{Risk Per Share}} \right\rfloor$$
$$\text{Total Capital} = \text{Shares to Buy} \times \text{Entry Price}$$
$$\text{Portfolio Allocation \%} = \frac{\text{Total Capital}}{\text{Account Size}} \times 100\%$$

---

## 5. Test Runner Execution & CI/CD Integration

The test suite is driven by `tests/run_e2e.py`.

### Runner Commands
```bash
# 1. Run all 381 tests across all 4 tiers
python tests/run_e2e.py

# 2. Run Tier 1 Isolation tests only (180 tests)
python tests/run_e2e.py --tier 1

# 3. Run Tier 2 Boundary tests only (180 tests)
python tests/run_e2e.py --tier 2

# 4. Run Tier 3 Cross-feature Interaction tests only (16 tests)
python tests/run_e2e.py --tier 3

# 5. Run Tier 4 Real-world Scenario tests only (5 tests)
python tests/run_e2e.py --tier 4

# 6. Filter by specific Feature ID (e.g. Feature 16: Mansfield RS)
python tests/run_e2e.py --feature 16

# 7. Verbose execution
python tests/run_e2e.py -v

# 8. Machine-readable JSON output for CI pipelines
python tests/run_e2e.py --json

# 9. Stop immediately on first failure
python tests/run_e2e.py --failfast
```

### Exit Codes
- `0`: All tests passed.
- `1`: One or more tests failed or encountered errors.
