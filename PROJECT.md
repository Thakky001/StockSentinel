# Project: StockSentinel

## Architecture
StockSentinel is an end-to-end automated weekly stock screener and web application designed for ~3,500–4,000 US equities (Russell 3000 + S&P 1500). It implements Stan Weinstein's Stage 2 Breakout methodology, Mansfield Relative Strength vs SPY, automated Telegram alerts, an Express.js REST API service, and a React + Tailwind + Lightweight Charts dashboard.

### High-Level Topology & Data Flow
```
[External Sources]
  ├── Russell 3000 / S&P 500 / S&P 1500 Universe Constituents + SPY Benchmark
  └── Yahoo Finance (yfinance resilient 50-chunk downloader)
          │
          ▼
[M2: Stock Universe & Ingestion Engine]
  ├── Parquet Local Cache (Snappy compressed, <ticker>.parquet)
  └── PostgreSQL 16 `stock_daily_bars` (ON CONFLICT DO UPDATE batch upsert)
          │
          ▼
[M3: Core Screener Engine V2.1 & Indicator Math] (Python + Polars + NumPy)
  ├── 1. Market Regime Filter (SPY Weekly): BULL_MARKET, CAUTION_MARKET, BEAR_MARKET
  ├── 2. Resample Daily to Weekly (Friday close, Monday-Friday bounds)
  ├── 3. Indicator Pipeline: 30w SMA, 4w slope, 10w SMA, 10w volume avg, 35w pivot,
  │      base tightness (4w <= 18%), ATR(14w), Mansfield RS vs SPY & acceleration
  ├── 4. Dual-Mode Architecture:
  │      ├── Mode 1: Discovery Scanner (8 multi-factor criteria + Min Volatility filter)
  │      └── Mode 2: Active Lifecycle Tracker (`active_breakout_signals` state persistence)
  ├── 5. Adaptive Stop Loss & Breakeven Auto-Lock (🛡️ Breakeven lock when peak gain >= +15%)
  ├── 6. Dynamic Position Sizing (Regime-scaled budget, actual buy price risk, 20% cap)
  ├── 7. 6-Tier Status Classification & Earnings Risk Warning (within 14 days)
  ├── 8. Upsert to `screener_signals`, sync to `active_breakout_signals` & log to `scan_jobs`
          │
          ├───> [M4: Telegram Alerting System] (HTML format, 4096-char chunker)
          │
          ▼
[M1: Database & Project Infrastructure] (PostgreSQL 16, Redis 7, Neon DB)
  ├── Tables: `stocks`, `stock_daily_bars`, `screener_signals`, `active_breakout_signals`, `scan_jobs`
          │
          ▼
[M5: Backend REST API Service] (Node.js / Express / TypeScript)
  ├── GET /api/screener/latest (Sort, filter by sector/status/regime, pagination, V2.1 metrics)
  ├── GET /api/screener/dates, GET /api/screener/status
  ├── GET /api/stock/:ticker/chart (Lightweight Charts ready OHLCV + SMA 30w)
  ├── GET /api/stock/:ticker/summary
  ├── POST /api/screener/trigger (Child process lock & execution)
  └── POST /api/notifications/telegram-test
          │
          ▼
[M6: Frontend Web Application] (React 18 + Vite + Tailwind CSS)
  ├── Market Regime Alert Banners (BEAR_MARKET warning, CAUTION_MARKET, BULL_MARKET)
  ├── Position Sizing Toolbar (Portfolio size $, Risk %, Dollar risk budget)
  ├── Dashboard Table: 6-tier status badges, Base Tightness %, ATR, Shares, Earnings alerts
  ├── TradingView Lightweight Charts Modal (candlesticks, 30w SMA, volume, 3 price lines)
  ├── LocalStorage Watchlist Drawer
  └── Real-Time Risk & Position Sizing Calculator Modal (🧮)
```

---

## Feature Inventory
Every feature from the original request and survey is assigned to a milestone:

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Docker Compose Infrastructure | PostgreSQL 16-alpine and Redis 7-alpine configuration, healthchecks, volumes | M1 | ORIGINAL_REQUEST §R1 |
| 2 | Master Stocks Schema | DDL for `stocks` table (ticker, name, sector, industry, market_cap, is_active, indices) | M1 | ORIGINAL_REQUEST §R1 |
| 3 | Daily Bars Schema | DDL for `stock_daily_bars` table with composite primary key (ticker, trade_date) and time-series indexes | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Scan Jobs Audit Schema | DDL for `scan_jobs` table tracking job status, timestamps, metrics, error messages | M1 | ORIGINAL_REQUEST §R1 |
| 5 | Screener Signals Schema | DDL for `screener_signals` with entry/current prices, diff %, entry_status enum CHECK, MRS score, 30w SMA, volume surge | M1 | ORIGINAL_REQUEST §R1 |
| 6 | Migration & Init System | Automated schema execution via `db/init.sql` and standalone migration runners | M1 | ORIGINAL_REQUEST §R1 |
| 7 | Combined Stock Universe | Russell 3000 + S&P 1500 constituent definition (~3,500-3,800 tickers) + SPY benchmark inclusion | M2 | ORIGINAL_REQUEST §R2 |
| 8 | Resilient Batch Downloader | `yfinance` downloader with 50-ticker chunking, rate limiting, and exponential backoff with jitter | M2 | ORIGINAL_REQUEST §R2 |
| 9 | Delta Sync Engine | Incremental 7-day delta sync + 2-year cold start history sync | M2 | ORIGINAL_REQUEST §R2 |
| 10 | Parquet Local Cache | Snappy-compressed per-ticker Parquet caching (`<ticker>.parquet`) with merge deduplication | M2 | ORIGINAL_REQUEST §R2 |
| 11 | PostgreSQL Daily Upsert | High-throughput batch upsert (`ON CONFLICT DO UPDATE`) into `stock_daily_bars` | M2 | ORIGINAL_REQUEST §R2 |
| 12 | Weekly Resampling Engine | Vectorized Polars aggregation of daily bars to Friday-closed weekly bars | M3 | ORIGINAL_REQUEST §R3 |
| 13 | 30-Week SMA & Slope | Rolling 30w SMA and slope calculation (1-week momentum and % slope over 4 weeks) | M3 | ORIGINAL_REQUEST §R3 |
| 14 | 10-Week Volume Average & Surge | Rolling 10w prior average volume and surge ratio calculation (>= 1.5x) | M3 | ORIGINAL_REQUEST §R3 |
| 15 | 35-Week Resistance Pivot | Rolling 35w prior high resistance pivot calculation | M3 | ORIGINAL_REQUEST §R3 |
| 16 | Mansfield Relative Strength | Mathematical calculation of MRS vs SPY benchmark (52w RS SMA zero-line crossover) | M3 | ORIGINAL_REQUEST §R3 |
| 17 | Stage 2 Breakout Filter | Multi-factor filter: Close > SMA30, Slope >= 0, Close >= Pivot35, VolSurge >= 1.5, MRS > 0 | M3 | ORIGINAL_REQUEST §R3 |
| 18 | Target & Risk Math | Entry Price, Max Buy Price (+5%), Current Price comparison, % distance, and Stop Loss | M3 | ORIGINAL_REQUEST §R3 |
| 19 | Entry Status Categorization | Deterministic mapping: `IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT` | M3 | ORIGINAL_REQUEST §R3 |
| 20 | Signals & Job Persistence | Upsert filtered signals to `screener_signals` and update `scan_jobs` status | M3 | ORIGINAL_REQUEST §R3 |
| 21 | Telegram Alert Formatter | Clean HTML card formatting with ticker, entry pivot, current price, diff %, status badge, stop loss, volume surge, MRS score, and web app link | M4 | ORIGINAL_REQUEST §R4 |
| 22 | Message Chunker (4096-char) | Safe chunker splitting message into parts < 3800 chars without breaking HTML tags or stock cards | M4 | ORIGINAL_REQUEST §R4 |
| 23 | Telegram API Dispatcher | HTTP POST with retry/backoff, rate limiting, and graceful fallback on missing credentials | M4 | ORIGINAL_REQUEST §R4 |
| 24 | Express Server & DB Pool | Node.js Express service with TypeScript, `pg.Pool`, CORS, environment config, error handler | M5 | ORIGINAL_REQUEST §R5 |
| 25 | Latest Screener Endpoint | `GET /api/screener/latest` with sorting, filtering (sector, status, search), pagination | M5 | ORIGINAL_REQUEST §R5 |
| 26 | Scan Dates Endpoint | `GET /api/screener/dates` listing historical scan dates | M5 | ORIGINAL_REQUEST §R5 |
| 27 | Stock Chart Endpoint | `GET /api/stock/:ticker/chart` returning Lightweight Charts formatted OHLCV and SMA 30w | M5 | ORIGINAL_REQUEST §R5 |
| 28 | Stock Summary Endpoint | `GET /api/stock/:ticker/summary` returning stock details, technicals, and entry/stop metrics | M5 | ORIGINAL_REQUEST §R5 |
| 29 | Screener Trigger Endpoint | `POST /api/screener/trigger` with process lock, background execution, and status polling | M5 | ORIGINAL_REQUEST §R5 |
| 30 | Telegram Test Endpoint | `POST /api/notifications/telegram-test` testing Telegram bot credentials and alert dispatch | M5 | ORIGINAL_REQUEST §R5 |
| 31 | React + Vite + Tailwind Setup | Modern React 18 SPA with Vite, TypeScript, and responsive Tailwind styling | M6 | ORIGINAL_REQUEST §R6 |
| 32 | Interactive Screener Table | Dashboard table with column sorting, live search, sector dropdown, and buy status badges | M6 | ORIGINAL_REQUEST §R6 |
| 33 | TradingView Lightweight Charts | Modal with weekly candlesticks, 30w SMA line, volume histogram, and 3 price lines (Green Entry, Orange Max Buy, Red Stop Loss) | M6 | ORIGINAL_REQUEST §R6 |
| 34 | LocalStorage Watchlist Drawer | Slide-over drawer persisting favorited tickers with quick chart access | M6 | ORIGINAL_REQUEST §R6 |
| 35 | Position Sizing Calculator | Real-time risk/position calculator based on account size, risk %, entry, and stop loss | M6 | ORIGINAL_REQUEST §R6 |
| 36 | End-to-End System Integration | Full integration of all R1-R6 components passing 100% E2E test suite + adversarial hardening | M7 | ORIGINAL_REQUEST Acceptance Criteria |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Database & Project Infrastructure | Docker Compose for PostgreSQL 16 + Redis, SQL DDL migrations for `stocks`, `stock_daily_bars`, `screener_signals`, `scan_jobs`, connection pool scripts, test connection validation | none | DONE |
| M2 | Stock Universe & Ingestion Engine | Russell 3000 + S&P 1500 universe definition, SPY benchmark, resilient yfinance 50-chunk downloader with backoff, Parquet cache, PostgreSQL upsert | M1 | DONE |
| M3 | Core Screener Engine & Indicator Math | Polars daily-to-weekly resampling, 30w SMA, slope, 10w volume avg, 35w resistance pivot, Mansfield RS vs SPY, Stage 2 Breakout filters, Entry/Stop/Status calculations, signals upsert, job audit logging | M1, M2 | DONE |
| M4 | Telegram Alerting System | Formatted weekly alert in HTML mode, chunker (<4096 chars, zero tag breaks), HTTP dispatcher with rate limiting & retry, test harness | M1, M3 | DONE |
| M5 | Backend REST API Service | Node.js Express TypeScript API service, pg connection pool, endpoints (`/api/screener/latest`, `/api/screener/dates`, `/api/stock/:ticker/chart`, `/api/stock/:ticker/summary`, `/api/screener/trigger`, `/api/screener/status`, `/api/notifications/telegram-test`), tests | M1, M3, M4 | DONE |
| M6 | Frontend Web Application | React 18 + Vite + Tailwind CSS dashboard, Market Regime warning banners, Position Sizing toolbar, ScreenerTable (6-tier badges, Base Tightness, ATR, Shares, Earnings alerts), TradingView Lightweight Charts Modal, WatchlistDrawer, PositionCalculator | M5 | DONE |
| M7 | Final Milestone: E2E Verification & Adversarial Hardening | Phase 1: 100% pass on E2E test suite (Tiers 1-4). Phase 2: Adversarial coverage hardening (Tier 5). | M1-M6, TEST_READY.md | PLANNED |

---

## Interface Contracts

### 1. Database Schema ↔ Ingestion & Screener
- `stocks`:
  - `ticker` VARCHAR(16) PRIMARY KEY, `name` VARCHAR(255), `exchange` VARCHAR(32), `sector` VARCHAR(128), `industry` VARCHAR(128), `market_cap` BIGINT, `is_active` BOOLEAN, `in_russell3000` BOOLEAN, `in_sp1500` BOOLEAN
- `stock_daily_bars`:
  - `ticker` VARCHAR(16) REFERENCES stocks(ticker), `trade_date` DATE, `open` NUMERIC(12,4), `high` NUMERIC(12,4), `low` NUMERIC(12,4), `close` NUMERIC(12,4), `adj_close` NUMERIC(12,4), `volume` BIGINT, PRIMARY KEY (ticker, trade_date)
- `scan_jobs`:
  - `id` BIGSERIAL PRIMARY KEY, `job_type` VARCHAR(64), `status` VARCHAR(32) CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')), `started_at` TIMESTAMPTZ, `completed_at` TIMESTAMPTZ, `tickers_total` INT, `tickers_processed` INT, `tickers_failed` INT, `signals_found` INT, `error_message` TEXT, `telegram_alert_sent` BOOLEAN, `market_regime` VARCHAR(32)
- `screener_signals`:
  - `id` BIGSERIAL PRIMARY KEY, `scan_id` BIGINT REFERENCES scan_jobs(id), `scan_date` DATE, `ticker` VARCHAR(16) REFERENCES stocks(ticker), `entry_price` NUMERIC(12,4), `max_buy_price` NUMERIC(12,4), `current_price` NUMERIC(12,4), `stop_loss_price` NUMERIC(12,4), `diff_pct` NUMERIC(8,4), `entry_status` VARCHAR(32) CHECK (entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'PROFIT_RUN', 'TRAILING_WARNING', 'BELOW_ENTRY', 'STOPPED_OUT')), `volume_surge_ratio` NUMERIC(8,4), `mrs_score` NUMERIC(10,4), `sma_30w` NUMERIC(12,4), `sma_30w_slope` NUMERIC(8,4), `prior_resistance_35w` NUMERIC(12,4), `weekly_close` NUMERIC(12,4), `weekly_volume` BIGINT, `avg_volume_10w` BIGINT, `stage` VARCHAR(32), `sma_10w` NUMERIC(12,4), `base_tightness_pct` NUMERIC(8,4), `atr_14w` NUMERIC(12,4), `market_regime` VARCHAR(32), `recommended_shares` INT, `risk_per_share` NUMERIC(12,4), `active_stop_loss` NUMERIC(12,4), `highest_price_since_entry` NUMERIC(12,4), `peak_gain_pct` NUMERIC(8,2), `earnings_warning` VARCHAR(64), UNIQUE (scan_date, ticker)
- `active_breakout_signals`:
  - `symbol` VARCHAR(16) PRIMARY KEY, `breakout_date` DATE NOT NULL, `entry_price` NUMERIC(12,4) NOT NULL, `max_buy_price` NUMERIC(12,4) NOT NULL, `initial_stop_loss` NUMERIC(12,4) NOT NULL, `active_stop_loss` NUMERIC(12,4) NOT NULL, `highest_price_since_entry` NUMERIC(12,4) NOT NULL, `current_price` NUMERIC(12,4) NOT NULL, `peak_gain_pct` NUMERIC(8,2) NOT NULL, `current_gain_pct` NUMERIC(8,2) NOT NULL, `status` VARCHAR(32) NOT NULL, `recommended_shares` INT NOT NULL, `earnings_warning` VARCHAR(64), `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP

### 2. Screener Engine ↔ Telegram Alerting System
- `send_weekly_alert(signals: List[Dict], scan_date: str, universe_count: int) -> bool`
- Stock card payload fields:
  - `ticker`: string
  - `name`: string
  - `sector`: string
  - `entry_price`: float
  - `current_price`: float
  - `max_buy_price`: float
  - `stop_loss_price`: float
  - `diff_pct`: float
  - `entry_status`: 'IN_BUY_ZONE' | 'EXTENDED' | 'PROFIT_RUN' | 'TRAILING_WARNING' | 'BELOW_ENTRY' | 'STOPPED_OUT'
  - `volume_surge_ratio`: float
  - `mrs_score`: float
  - `sma_30w`: float
  - `sma_30w_slope`: float
  - `earnings_warning`: Optional[str]

### 3. Backend REST API ↔ Frontend Web Application
- `GET /api/screener/latest`:
  - Query: `date`, `sector`, `status`, `search`, `sort_by`, `order`, `page`, `limit`
  - Response: `{ success: true, data: { scan_date: string, market_regime: string, total: number, page: number, limit: number, total_pages: number, signals: ScreenerSignal[] } }`
- `GET /api/screener/dates`:
  - Response: `{ success: true, data: { dates: string[] } }`
- `GET /api/stock/:ticker/chart`:
  - Response: `{ success: true, data: { ticker: string, company_name: string, candlesticks: { time: string, open: number, high: number, low: number, close: number }[], sma30: { time: string, value: number }[], volume: { time: string, value: number, color: string }[], metrics: { entry_price: number, max_buy_price: number, stop_loss_price: number, status: string, close_price: number } } }`
- `GET /api/stock/:ticker/summary`:
  - Response: `{ success: true, data: { ticker: string, name: string, sector: string, industry: string, market_cap: number, exchange: string, latest_signal: ScreenerSignal, latest_daily_bar: DailyBar } }`
- `POST /api/screener/trigger`:
  - Response: `{ success: true, data: { job_id: number, status: "RUNNING", message: string } }` (or 409 Conflict if already running)
- `POST /api/notifications/telegram-test`:
  - Response: `{ success: true, message: string, telegram_message_id?: number }`

---

## Code Layout
```
d:/git/StockSentinel/
├── docker-compose.yml              # PostgreSQL 16 + Redis 7 Docker services
├── .env.example                    # Template environment variables
├── .gitignore                      # Git ignore patterns
├── README.md                       # Architecture & setup instructions
├── db/                             # Database initialization and DDL
│   ├── init.sql                    # Main DDL schema initialization
│   └── migrate.js / migrate.py     # Migration runner
├── screener/                       # Python Universe Ingestion & Screener Engine
│   ├── requirements.txt            # Python dependencies (polars, yfinance, psycopg2-binary, etc.)
│   ├── pyproject.toml
│   ├── data/
│   │   ├── universe/               # Russell 3000 + S&P 1500 seed data
│   │   └── parquet/                # Per-ticker parquet cache (<ticker>.parquet)
│   └── src/
│       ├── config.py               # Settings & environment variables
│       ├── db.py                   # PostgreSQL connection & upsert helpers
│       ├── universe.py             # Universe definition, normalization, SPY benchmark
│       ├── downloader.py           # yfinance 50-chunk downloader with backoff & rate limits
│       ├── parquet_cache.py        # Local Parquet read/write/merge
│       ├── indicators.py           # Polars weekly resampling, 30w SMA, slope, 10w vol, 35w pivot, Mansfield RS
│       ├── screener.py             # Weinstein Stage 2 filters, targets, and status classification
│       ├── telegram_alert.py       # Telegram HTML formatter, 4096-char chunker, dispatcher
│       └── main.py                 # CLI entrypoint (--mode ingest|screen|all, --sample N)
├── backend/                        # Node.js Express REST API
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts                # Server startup
│       ├── app.ts                  # Express application setup, CORS, error middleware
│       ├── db/
│       │   └── pool.ts             # pg.Pool connection pool
│       ├── routes/
│       │   ├── screener.ts         # /api/screener/*
│       │   ├── stock.ts            # /api/stock/*
│       │   └── notifications.ts    # /api/notifications/*
│       └── services/
│           ├── screenerRunner.ts   # Child process manager & execution lock
│           └── telegramService.ts  # Telegram test & dispatch service
├── frontend/                       # React 18 + Vite + Tailwind CSS Application
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/                    # API client & route bindings
│       ├── types/                  # TypeScript interface definitions
│       ├── hooks/                  # React Query / SWR / Watchlist hooks
│       └── components/             # Dashboard, ScreenerTable, ChartModal, Watchlist, PositionCalculator
└── tests/                          # E2E and Integration Test Suite (Dual Track)
    ├── e2e/                        # Comprehensive Tiers 1-4 test runner & cases
    │   ├── tier1_features/
    │   ├── tier2_boundaries/
    │   ├── tier3_interactions/
    │   └── tier4_scenarios/
    └── run_e2e.py / run_e2e.js     # Unified E2E test runner
```
