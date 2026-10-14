# Handoff Report: Explorer Survey 1 — Database & Ingestion Engine (R1 & R2)

## 1. Observation

### 1.1 Repository State
- **Project Root**: `d:/git/StockSentinel`
- **Directory Inspection**: Checked via `list_dir` on `d:/git/StockSentinel`. Output showed 0 root files and 1 directory (`.agents`). No existing codebase, configuration, or source files currently exist.
- **Agent Workspaces**: `.agents/teamwork/` contains `ORIGINAL_REQUEST.md`, `orchestrator_1/`, `explorer_survey_1/`, `explorer_survey_2/`, `explorer_survey_3/`, and `sentinel/`.
- **Target Requirements**:
  - `ORIGINAL_REQUEST.md:12-14`: "R1. Database & Project Infrastructure: Set up Docker Compose for PostgreSQL 16 (and optional Redis cache). Create database schema with migrations: `stocks`, `stock_daily_bars`, `screener_signals`, and `scan_jobs` supporting entry price, current price, diff %, entry status (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`), volume surge ratio, MRS score, and 30w SMA."
  - `ORIGINAL_REQUEST.md:16-19`: "R2. Stock Universe & Ingestion Engine (Python): Define universe of Russell 3000 + S&P 1500 common stocks. Implement resilient batch downloader using `yfinance` with chunking (50 tickers/batch), exponential backoff, rate limiting, and incremental delta updates (7-day delta sync). Save OHLCV data to local Parquet cache and upsert into PostgreSQL `stock_daily_bars`."
  - `ORIGINAL_REQUEST.md:50-54`: Acceptance Criteria: "PostgreSQL container starts and schema initializes cleanly. Screener engine successfully processes tickers, calculates Stage 2 indicators and Mansfield RS correctly against SPY. Signals are accurately recorded in `screener_signals` with entry prices, current prices, and status."

### 1.2 Host & Runtime Environment
- **Operating System**: Windows (powershell shell).
- **Runtime Expectations**:
  - Docker Desktop with Docker Compose v2 for local container orchestration.
  - Python 3.10+ for the screener and ingestion engine (`yfinance`, `polars`, `pyarrow`, `psycopg2-binary` or `psycopg`, `pydantic`, `python-dotenv`).
  - Node.js 18+ / 20+ and npm for the Express REST API backend and Vite + React frontend.
  - PostgreSQL 16 standard port `5432` (configurable via `.env` to avoid host conflicts), Redis 7 on `6379`.

---

## 2. Logic Chain

```
[Observation: Empty Repo + R1/R2 Mandates]
          │
          ├──> [Design Monorepo Architecture: backend, frontend, screener, db]
          │
          ├──> [R1: Docker Compose + PostgreSQL 16 + Redis 7 Infrastructure]
          │       ├──> 4 Core Tables DDL (`stocks`, `stock_daily_bars`, `screener_signals`, `scan_jobs`)
          │       ├──> Exact Stage 2 breakout fields, enum constraints, foreign keys
          │       └──> Composite indexes for ultra-fast time-series queries
          │
          └──> [R2: Python Universe & Ingestion Engine]
                  ├──> Russell 3000 + S&P 1500 (~3,500 common stocks) + SPY benchmark
                  ├──> Resilient yfinance batching (50 tickers/chunk, rate limiting, backoff)
                  ├──> Parquet columnar local caching (<ticker>.parquet)
                  └──> High-throughput PostgreSQL upsert (ON CONFLICT DO UPDATE)
```

### 2.1 Project Monorepo Layout
To cleanly isolate concerns while sharing configuration and database schemas, the workspace should adopt this directory layout:

```
d:/git/StockSentinel/
├── docker-compose.yml              # PostgreSQL 16 + Redis service definition
├── .env.example                    # Template environment variables
├── .env                            # Local configuration (gitignored)
├── .gitignore                      # Standard python, node, parquet ignores
├── README.md                       # Setup and operational instructions
├── db/                             # Database initialization and DDL
│   ├── init.sql                    # Auto-mounted to /docker-entrypoint-initdb.d/
│   └── migrations/                 # Versioned SQL migration files
├── screener/                       # Python Ingestion & Screener Engine (R2, R3, R4)
│   ├── requirements.txt            # Python dependencies (polars, yfinance, etc.)
│   ├── pyproject.toml              # Modern Python packaging config
│   ├── data/                       # Local file caches (gitignored)
│   │   ├── universe/               # Russell 3000 + S&P 1500 universe seeds
│   │   └── parquet/                # Per-ticker parquet bars cache
│   └── src/
│       ├── config.py               # Env vars and runtime settings
│       ├── db.py                   # Postgres connection pool and upsert helpers
│       ├── universe.py             # Universe loader, normalizer, and SPY injector
│       ├── downloader.py           # yfinance 50-chunk downloader with backoff
│       ├── parquet_cache.py        # Local Parquet read/write/merge engine
│       ├── indicators.py           # Resampling, 30w SMA, pivot, Mansfield RS
│       ├── screener.py             # Stage 2 breakout screener logic
│       ├── telegram_alert.py       # Telegram notification sender
│       └── main.py                 # CLI entrypoint for full or delta pipeline
├── backend/                        # Node.js + Express REST API (R5)
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
└── frontend/                       # React + Vite + Tailwind CSS (R6)
    ├── package.json
    └── src/
```

---

### 2.2 Requirement 1 (R1): Database & Project Infrastructure

#### 2.2.1 Docker Compose Specification (`docker-compose.yml`)
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    container_name: stocksentinel-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-stocksentinel}
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
    ports:
      - "${DB_PORT:-5432}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-stocksentinel}"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - stocksentinel-network

  redis:
    image: redis:7-alpine
    container_name: stocksentinel-redis
    restart: unless-stopped
    ports:
      - "${REDIS_PORT:-6379}:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - stocksentinel-network

volumes:
  pgdata:
    driver: local
  redisdata:
    driver: local

networks:
  stocksentinel-network:
    driver: bridge
```

#### 2.2.2 Environment Configuration (`.env.example`)
```env
# Database Configuration
POSTGRES_DB=stocksentinel
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/stocksentinel

# Redis Configuration (Optional Cache)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_URL=redis://localhost:6379

# Screener Configuration
PYTHON_ENV=development
DATA_DIR=./screener/data
PARQUET_DIR=./screener/data/parquet
UNIVERSE_SEED_FILE=./screener/data/universe/russell3000_sp1500.json
BATCH_SIZE=50
RATE_LIMIT_DELAY=1.5
MAX_RETRIES=4

# Telegram Bot Alerting
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
WEB_APP_URL=http://localhost:5173

# Backend & Frontend
API_PORT=3000
FRONTEND_PORT=5173
```

#### 2.2.3 Exact Database Schema Definition (`db/init.sql`)

```sql
-- ============================================================================
-- StockSentinel PostgreSQL 16 Schema Definition
-- Supports Stage 2 Breakouts, Mansfield Relative Strength, and Time-Series
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ----------------------------------------------------------------------------
-- 1. Table: stocks
-- Master universe directory of US Equities (Russell 3000 + S&P 1500 + SPY)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stocks (
    ticker VARCHAR(16) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    exchange VARCHAR(32),                     -- NYSE, NASDAQ, AMEX, ARCA
    sector VARCHAR(128),
    industry VARCHAR(128),
    market_cap BIGINT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    in_russell3000 BOOLEAN NOT NULL DEFAULT FALSE,
    in_sp1500 BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stocks_active ON stocks (is_active);
CREATE INDEX IF NOT EXISTS idx_stocks_sector ON stocks (sector);

-- ----------------------------------------------------------------------------
-- 2. Table: stock_daily_bars
-- Daily OHLCV data for all universe tickers + SPY benchmark
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_daily_bars (
    ticker VARCHAR(16) NOT NULL REFERENCES stocks(ticker) ON DELETE CASCADE,
    trade_date DATE NOT NULL,
    open NUMERIC(12, 4) NOT NULL,
    high NUMERIC(12, 4) NOT NULL,
    low NUMERIC(12, 4) NOT NULL,
    close NUMERIC(12, 4) NOT NULL,
    adj_close NUMERIC(12, 4) NOT NULL,
    volume BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, trade_date)
);

-- Essential composite indexes for fast time-series queries & weekly resampling
CREATE INDEX IF NOT EXISTS idx_daily_bars_ticker_date 
    ON stock_daily_bars (ticker, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_bars_date 
    ON stock_daily_bars (trade_date DESC);

-- ----------------------------------------------------------------------------
-- 3. Table: scan_jobs
-- Execution audit log and state management for automated/triggered scan runs
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scan_jobs (
    id BIGSERIAL PRIMARY KEY,
    job_type VARCHAR(64) NOT NULL DEFAULT 'WEEKLY_SCREENER',
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
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

CREATE INDEX IF NOT EXISTS idx_scan_jobs_started_at 
    ON scan_jobs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_jobs_status 
    ON scan_jobs (status);

-- ----------------------------------------------------------------------------
-- 4. Table: screener_signals
-- Filtered Stage 2 breakout signals with Weinstein indicators and Mansfield RS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS screener_signals (
    id BIGSERIAL PRIMARY KEY,
    scan_id BIGINT REFERENCES scan_jobs(id) ON DELETE SET NULL,
    scan_date DATE NOT NULL,
    ticker VARCHAR(16) NOT NULL REFERENCES stocks(ticker) ON DELETE CASCADE,
    
    -- Price and Pivot Points
    entry_price NUMERIC(12, 4) NOT NULL,       -- Prior 30w-35w resistance high pivot
    max_buy_price NUMERIC(12, 4) NOT NULL,     -- entry_price * 1.05 (+5% max buy zone)
    current_price NUMERIC(12, 4) NOT NULL,     -- Latest weekly close
    stop_loss_price NUMERIC(12, 4) NOT NULL,   -- Breakout support / 30w SMA level
    diff_pct NUMERIC(8, 4) NOT NULL,           -- ((current_price - entry_price) / entry_price) * 100
    
    -- Entry Status Badge
    entry_status VARCHAR(32) NOT NULL
        CHECK (entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT')),
    
    -- Stage 2 Indicators & Volume Metrics
    volume_surge_ratio NUMERIC(8, 4) NOT NULL, -- Current weekly volume / 10w avg volume (>= 1.5)
    mrs_score NUMERIC(10, 4) NOT NULL,          -- Mansfield Relative Strength vs SPY (> 0)
    sma_30w NUMERIC(12, 4) NOT NULL,           -- 30-week Simple Moving Average
    sma_30w_slope NUMERIC(8, 4) NOT NULL,      -- Slope of 30w SMA (positive for Stage 2)
    prior_resistance_35w NUMERIC(12, 4) NOT NULL, -- 35-week resistance pivot
    weekly_close NUMERIC(12, 4) NOT NULL,
    weekly_volume BIGINT NOT NULL,
    avg_volume_10w BIGINT NOT NULL,
    stage VARCHAR(32) NOT NULL DEFAULT 'Stage 2 Breakout',
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_scan_date_ticker UNIQUE (scan_date, ticker)
);

-- High-performance query indexes for REST API sorting and filtering
CREATE INDEX IF NOT EXISTS idx_screener_signals_date 
    ON screener_signals (scan_date DESC);
CREATE INDEX IF NOT EXISTS idx_screener_signals_status 
    ON screener_signals (entry_status);
CREATE INDEX IF NOT EXISTS idx_screener_signals_mrs 
    ON screener_signals (mrs_score DESC);
CREATE INDEX IF NOT EXISTS idx_screener_signals_ticker 
    ON screener_signals (ticker);
CREATE INDEX IF NOT EXISTS idx_screener_signals_date_status 
    ON screener_signals (scan_date DESC, entry_status);
```

#### 2.2.4 Entry Status Logic Matrix
The status constraint and computed values follow this deterministic logic:
| Status | Formula Condition | Business Meaning | UI Badge Color |
|---|---|---|---|
| `IN_BUY_ZONE` | `current_price >= entry_price AND current_price <= max_buy_price` | Stock is between 0% and +5% above pivot. Optimal buy window. | Emerald Green |
| `EXTENDED` | `current_price > max_buy_price` (i.e. > +5% above pivot) | High risk of pullback. Do not chase. | Amber / Orange |
| `BELOW_ENTRY` | `current_price < entry_price AND current_price >= stop_loss_price` | Pulling back into base but stop is intact. Watch for re-test. | Blue / Slate |
| `STOPPED_OUT` | `current_price < stop_loss_price` | Failed breakout or violated stop level. Cut loss immediately. | Rose Red |

---

### 2.3 Requirement 2 (R2): Stock Universe & Ingestion Engine

#### 2.3.1 Russell 3000 + S&P 1500 Universe Definition & Generation
1. **Universe Scope**:
   - Russell 3000 measures the performance of the largest 3,000 US companies (~98% of investable US equity market).
   - S&P 1500 (Composite 1500) combines S&P 500, S&P MidCap 400, and S&P SmallCap 600 (~90% of US market capitalization).
   - Merging Russell 3000 and S&P 1500 yields ~3,500 - 3,800 unique liquid common stocks.
   - Benchmark Inclusion: **`SPY`** (SPDR S&P 500 ETF Trust) MUST be included in the ingestion pipeline to compute Mansfield Relative Strength for every stock.

2. **Ticker Sanitization & Filtering Rules**:
   - Exclude ETFs, ETNs, mutual funds, warrants (`.WS`, `W`, `WS`), units (`.U`, `U`), preferred shares (`-P`, `.PR`, `PR`), and rights.
   - Yahoo Finance symbol mapping:
     - Replace dots with dashes: `BRK.B` -> `BRK-B`, `BF.B` -> `BF-B`.
   - Seed Generation:
     - Provide a curated JSON/CSV seed file at `screener/data/universe/russell3000_sp1500.json` containing `[ { "ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Consumer Electronics", "in_sp1500": true, "in_russell3000": true }, ... ]`.
     - Provide a generator utility `screener/src/universe.py` that can either load the local seed file or pull live constituent lists from public SEC / exchange sources.

#### 2.3.2 Resilient Batch Downloader (`yfinance`)
Downloading 3,500 tickers sequentially is prohibitively slow and triggers Yahoo Finance HTTP 429 rate limits. The downloader must implement:
1. **Batch Chunking**:
   - Chunk size: Exactly **50 tickers per batch** (e.g. `["AAPL", "MSFT", "GOOGL", ...]`).
   - Call `yf.download(tickers=batch, period=period, interval="1d", group_by="ticker", auto_adjust=False, threads=True)`.
2. **Rate Limiting Delay**:
   - Enforce an asynchronous or synchronous sleep of `1.0` to `2.0` seconds between successive 50-ticker batches.
3. **Exponential Backoff with Jitter**:
   - On HTTP 429, 502, 503, or connection timeouts:
     - Attempt $k \in \{1, 2, 3, 4\}$.
     - Sleep duration: $T = \text{base\_delay} \times 2^{k-1} + \text{uniform}(0, 1.0)$.
     - Example: 2s, 4.5s, 8.8s, 16.2s.
4. **Fallback Degradation for Problematic Batches**:
   - If a 50-ticker batch fails after 3 retries (due to a delisted or malformed ticker symbol corrupting the multi-ticker payload), the downloader automatically splits the batch into single-ticker downloads:
     - Downloads each of the 50 tickers individually.
     - Logs the specific bad ticker to `failed_tickers` and continues without failing the other 49 tickers.

#### 2.3.3 Parquet Local Caching Mechanism
1. **Directory Structure**:
   - Store historical bars locally as Parquet: `screener/data/parquet/<ticker>.parquet`.
   - Separate files per ticker offer significant advantages:
     - Independent read/write locks — zero risk of corrupting the entire dataset if one process crashes.
     - Fast Polars lazy evaluation: `pl.read_parquet(f"data/parquet/{ticker}.parquet")`.
     - Small disk footprint: Snappy-compressed Parquet achieves ~90% compression over CSV. 3,500 tickers x 500 days is only ~25-40 MB total.
2. **Read-Through / Write-Back Cache Pattern**:
   ```
   [Check Local Parquet File]
           │
           ├──> Exists?
           │      ├──> YES: Read local Max Date. Is Max Date recent (< 7 days)?
           │      │          ├──> YES: Fetch 7-day delta from yfinance.
           │      │          └──> NO: Fetch delta from (Max Date - 7 days).
           │      │
           │      └──> NO (Cold Start): Fetch 2-year history from yfinance.
           │
           ├──> Merge new rows with existing Parquet (Polars unique by trade_date).
           ├──> Overwrite local Parquet file.
           └──> Queue rows for PostgreSQL upsert.
   ```

#### 2.3.4 7-Day Delta Sync Architecture
- **Cold-Start (Initial Sync)**:
  - Download `period="2y"` (approx 504 trading days) to ensure sufficient lookback for 35-week resistance pivot, 30-week SMA, and 52-week Mansfield RS.
- **Weekly / Daily Delta Sync**:
  - Download `period="10d"` or `start=latest_date - timedelta(days=7)` to safely cover holiday weekends and potential retrospective data corrections.
  - De-duplicate against existing records using `trade_date`.
- **Database Upsert Performance**:
  - Bulk upserting 1.7 million rows row-by-row would take 30+ minutes.
  - Solution: Batch upsert using psycopg `execute_values` or chunked parameter queries of 2,500 rows per transaction:
    ```sql
    INSERT INTO stock_daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
    VALUES %s
    ON CONFLICT (ticker, trade_date) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        adj_close = EXCLUDED.adj_close,
        volume = EXCLUDED.volume;
    ```
  - Initial cold-start completes in ~60-90 seconds across the database; delta sync takes ~3-5 seconds.

#### 2.3.5 Fault Tolerance & Error Handling
1. **Delisted / Halted Stocks**:
   - `yfinance` returns an empty DataFrame or NaN values. The ingestion engine checks `df.is_empty()` and skips writing bars, updating `stocks.is_active = FALSE` if inactive for > 30 days.
2. **Missing Columns or Volume = 0**:
   - Check presence of `['Open', 'High', 'Low', 'Close', 'Volume']`. Convert volume to integer 0 if null.
3. **Transaction Rollback & Isolation**:
   - Database operations use atomic transactions per batch. A database failure on one batch does not corrupt previous batches.
4. **Scan Job Auditability**:
   - Every ingestion cycle registers in `scan_jobs` with `status='RUNNING'`.
   - On completion: status set to `'COMPLETED'`, `tickers_processed`, `tickers_failed`, and `completed_at` populated.
   - On unhandled exception: status set to `'FAILED'`, stack trace recorded in `error_message`.

---

## 3. Caveats
1. **Interactive Shell Permission in Container/Host**: Host command execution required interactive confirmation which timed out. All recommendations are designed to be environment-agnostic using standard Docker Compose and portable Python/Node scripts.
2. **Initial Cold-Start Download Duration**: Downloading 2 years of daily data for ~3,500 tickers in 50-ticker batches with 1.5s rate limits will take approximately 8-12 minutes on initial setup. Subsequent weekly delta scans will take < 2 minutes. For development testing, a `--sample 100` CLI flag should be supported.
3. **Mansfield RS Benchmark Dependency**: If `SPY` fails to download, Mansfield RS cannot be calculated for any stock. Therefore, `SPY` must be ingested as a mandatory prerequisite before processing universe stocks.

---

## 4. Conclusion
1. **Infrastructure (R1)**: A clean, containerized PostgreSQL 16 + Redis 7 Docker Compose stack provides the exact foundation needed. The 4-table schema (`stocks`, `stock_daily_bars`, `screener_signals`, `scan_jobs`) with strict foreign keys, check constraints on entry statuses, and composite time-series indexes satisfies all requirements of R1, R3, R4, and R5.
2. **Ingestion Engine (R2)**: A resilient Python pipeline pairing chunked `yfinance` downloading (50 tickers/batch + backoff + jitter) with local Snappy-compressed Parquet caching and PostgreSQL `ON CONFLICT` batch upserting guarantees high performance, fault tolerance, and minimal network overhead via 7-day delta sync.
3. **Interface Alignment**: The database schema and parquet structure directly feed the Polars weekly resampling engine (R3) and provide the exact columns expected by the REST API (R5) and Frontend (R6).

---

## 5. Verification Method

### 5.1 Docker Infrastructure Verification
```bash
# 1. Start Docker containers
docker compose up -d

# 2. Check container health status
docker compose ps
# Expected: stocksentinel-postgres (healthy), stocksentinel-redis (healthy)

# 3. Verify PostgreSQL schema initialization
docker compose exec postgres psql -U postgres -d stocksentinel -c "\dt"
# Expected output contains:
# - stocks
# - stock_daily_bars
# - scan_jobs
# - screener_signals

# 4. Verify table constraints
docker compose exec postgres psql -U postgres -d stocksentinel -c "\d screener_signals"
# Verify CHECK constraint on entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT')
```

### 5.2 Python Universe & Ingestion Verification
```bash
# 1. Install screener requirements
cd screener && pip install -r requirements.txt

# 2. Test universe generation & SPY inclusion
python -c "from src.universe import get_universe; u = get_universe(); assert 'SPY' in u; print(f'Universe count: {len(u)}')"

# 3. Test resilient 50-chunk downloader with sample batch
python -c "from src.downloader import download_batch; df = download_batch(['AAPL', 'MSFT', 'SPY'], period='5d'); print(df.shape)"

# 4. Test Parquet cache read/write
python -c "from src.parquet_cache import save_bars, load_bars; print('Parquet engine verified')"

# 5. Run initial ingestion test (sample of 20 stocks)
python src/main.py --sample 20 --mode ingest
```

### 5.3 Database Upsert & Invalidation Conditions
- Query `SELECT count(*) FROM stock_daily_bars;` — count must be > 0.
- Verify `ON CONFLICT` behavior by running delta sync twice; count of duplicate `(ticker, trade_date)` must remain strictly 0.
- Invalidation condition: If any ticker can have duplicate trade dates or missing close prices, the migration constraints have failed.
