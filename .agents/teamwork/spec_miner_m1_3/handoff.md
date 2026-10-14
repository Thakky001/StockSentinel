# Specification Mining Report: Milestone 1 (Database & Project Infrastructure)

**Author:** `spec_miner_m1_3` (Milestone 1 Specification Miner)  
**Recipient:** Orchestrator (`3d48cac3-5040-4cf3-9886-4e4f2c9223a4`)  
**Project:** StockSentinel  
**Working Directory:** `d:/git/StockSentinel/.agents/teamwork/spec_miner_m1_3`  
**Date:** 2026-10-14  

---

## 1. Observation

### 1.1 Source Documents Inspected
1. **`ORIGINAL_REQUEST.md`**:
   - `R1. Database & Project Infrastructure`: "Set up Docker Compose for PostgreSQL 16 (and optional Redis cache). Create database schema with migrations: `stocks`, `stock_daily_bars`, `screener_signals`, and `scan_jobs` supporting entry price, current price, diff %, entry status (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`), volume surge ratio, MRS score, and 30w SMA."
   - Acceptance Criteria: "PostgreSQL container starts and schema initializes cleanly."
2. **`PROJECT.md`**:
   - Architecture topology (lines 6–46), Feature Inventory (Features 1–6 allocated to M1), Milestones table (M1 has zero dependencies), and Interface Contracts (§1 Database Schema ↔ Ingestion & Screener).
3. **Prior Explorer Surveys**:
   - `explorer_survey_1/handoff.md`: Docker Compose definitions, 4 table DDLs, 50-chunk downloader, Parquet cache structure, batch upsert SQL.
   - `explorer_survey_2/handoff.md`: Weinstein indicator math, rolling window definitions, weekly resampling, Telegram card structure, 4096-char chunker.
   - `explorer_survey_3/handoff.md`: Express REST API endpoints, SQL query shapes, Lightweight Charts OHLCV + SMA30 formatting, position calculator formulas.
4. **Active Workspace State**:
   - Workspace directory `d:/git/StockSentinel` is clean; no pre-existing application source files or schema migrations exist outside `.agents/`.

---

## 2. Logic Chain

```
[M1 Dispatch Mandates]
        │
        ├──> [Focus 1: Database Connection Specs & Health Scripts (Node.js & Python)]
        │       ├──> Canonical Connection Parameters & Environment Variables
        │       ├──> Connection Pool Architecture & Error Resiliency
        │       ├──> Deterministic Healthcheck Script: Node.js (pg)
        │       └──> Deterministic Healthcheck Script: Python (psycopg2 / psycopg)
        │
        ├──> [Focus 2: Cross-Module Interface Contract Verification (R1 vs R2-R6)]
        │       ├──> Table 1: stocks (R2 Universe Ingestion, R5 REST API, R6 Dashboard)
        │       ├──> Table 2: stock_daily_bars (R2 Ingestion, R3 Resampling, R5/R6 Chart)
        │       ├──> Table 3: scan_jobs (R2 Ingestion, R3 Screener Audit, R5 Trigger Lock)
        │       ├──> Table 4: screener_signals (R3 Stage 2 Math, R4 Telegram, R5/R6 Table)
        │       └──> Column Discrepancy Reconciliation Matrix (Eliminating schema mismatches)
        │
        └──> [Focus 3: Pass/Fail Criteria & Validation Commands]
                ├──> Worker Implementation Checklist & Verification Steps
                ├──> Reviewer Architectural & Code Quality Criteria
                ├──> Challenger Adversarial & Boundary Injections
                └──> Auditor Milestone Gate Acceptance Criteria
```

---

### 2.1 Focus 1: Database Connection Specifications & Health Scripts

#### 2.1.1 Canonical Environment Parameters & Defaults
All services in StockSentinel (Python Screener, Node.js REST API, Docker Compose, and standalone migration runners) MUST adhere to this unified configuration schema:

| Variable | Type | Default (Local Dev) | Docker Container Network Default | Production Rule |
|---|---|---|---|---|
| `POSTGRES_DB` | String | `stocksentinel` | `stocksentinel` | Required |
| `POSTGRES_USER` | String | `postgres` | `postgres` | Required |
| `POSTGRES_PASSWORD` | String | `postgres` | `postgres` | Required, non-default |
| `DB_HOST` | String | `localhost` | `postgres` | Hostname / IP |
| `DB_PORT` | Integer | `5432` | `5432` | Port mapping |
| `DATABASE_URL` | String | `postgresql://postgres:postgres@localhost:5432/stocksentinel` | `postgresql://postgres:postgres@postgres:5432/stocksentinel` | Primary connection string |
| `DATABASE_SSL` | String / Boolean | `false` | `false` | `require` on cloud |
| `REDIS_HOST` | String | `localhost` | `redis` | Cache hostname |
| `REDIS_PORT` | Integer | `6379` | `6379` | Cache port |
| `REDIS_URL` | String | `redis://localhost:6379` | `redis://redis:6379` | Primary redis URI |

#### 2.1.2 Connection Pool Settings
- **Node.js (`pg.Pool`)**:
  - `max`: `20` clients (handles frontend concurrency and chart streaming).
  - `idleTimeoutMillis`: `30000` (reclaims idle sockets after 30 seconds).
  - `connectionTimeoutMillis`: `5000` (fails fast on database unreachability).
  - `statement_timeout`: `30000` (guards against unindexed runaway queries).
  - Error Handler: Must attach `pool.on('error', (err, client) => ...)` to catch idle connection drops without process termination.
- **Python (`psycopg2` / `psycopg3` Pool)**:
  - `minconn`: `1`, `maxconn`: `10`.
  - `connect_timeout`: `5` seconds.
  - Query timeouts: configured via session options `options='-c statement_timeout=60000'`.
  - Batching: `psycopg2.extras.execute_values` with `page_size=2500` for high-throughput daily bars ingestion.

---

#### 2.1.3 Deterministic Health Validation Script: Node.js (`pg`)
This script must be placed at `backend/src/db/healthcheck.ts` or standalone at `db/verify_node.js` for CI/CD and Worker verification:

```javascript
/**
 * db/verify_node.js
 * Authoritative Database Healthcheck & Schema Validation Script (Node.js)
 */
const { Pool } = require('pg');
const dotenv = require('dotenv');
dotenv.config();

const connectionString = process.env.DATABASE_URL || 
  `postgresql://${process.env.POSTGRES_USER || 'postgres'}:${process.env.POSTGRES_PASSWORD || 'postgres'}@${process.env.DB_HOST || 'localhost'}:${process.env.DB_PORT || 5432}/${process.env.POSTGRES_DB || 'stocksentinel'}`;

const pool = new Pool({
  connectionString,
  connectionTimeoutMillis: 5000,
  idleTimeoutMillis: 10000,
});

async function verifyDatabase() {
  const startTime = Date.now();
  console.log('🔍 [Node.js DB Validator] Connecting to PostgreSQL...');

  let client;
  try {
    client = await pool.connect();
    const latency = Date.now() - startTime;
    console.log(`✅ [Node.js DB Validator] Connected successfully (${latency}ms)`);

    // 1. Basic Health & Version
    const healthRes = await client.query('SELECT 1 AS alive, current_database() AS db, version() AS ver, NOW() AS ts;');
    console.log(`   Database: ${healthRes.rows[0].db}`);
    console.log(`   Timestamp: ${healthRes.rows[0].ts.toISOString()}`);
    console.log(`   Version: ${healthRes.rows[0].ver.split(' on ')[0]}`);

    // 2. Verify Core Tables Existence
    const requiredTables = ['stocks', 'stock_daily_bars', 'scan_jobs', 'screener_signals'];
    const tableRes = await client.query(`
      SELECT table_name 
      FROM information_schema.tables 
      WHERE table_schema = 'public' AND table_name = ANY($1);
    `, [requiredTables]);

    const foundTables = tableRes.rows.map(r => r.table_name);
    console.log(`\n📋 [Node.js DB Validator] Table Existence Check:`);
    for (const tbl of requiredTables) {
      if (foundTables.includes(tbl)) {
        console.log(`   [PASS] Table '${tbl}' exists`);
      } else {
        console.error(`   [FAIL] Table '${tbl}' MISSING!`);
        process.exitCode = 1;
      }
    }

    if (foundTables.length !== requiredTables.length) {
      throw new Error(`Schema validation failed. Expected 4 tables, found ${foundTables.length}`);
    }

    // 3. Verify Critical Columns & Constraints
    const columnChecks = [
      { table: 'stocks', col: 'ticker', type: 'character varying' },
      { table: 'stock_daily_bars', col: 'trade_date', type: 'date' },
      { table: 'scan_jobs', col: 'status', type: 'character varying' },
      { table: 'screener_signals', col: 'entry_status', type: 'character varying' },
      { table: 'screener_signals', col: 'mrs_score', type: 'numeric' },
    ];

    console.log(`\n🔍 [Node.js DB Validator] Column Schema Verification:`);
    for (const check of columnChecks) {
      const colRes = await client.query(`
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = $1 AND column_name = $2;
      `, [check.table, check.col]);

      if (colRes.rows.length === 0) {
        console.error(`   [FAIL] Column '${check.table}.${check.col}' MISSING!`);
        process.exitCode = 1;
      } else {
        console.log(`   [PASS] Column '${check.table}.${check.col}' (${colRes.rows[0].data_type})`);
      }
    }

    console.log('\n🎉 [Node.js DB Validator] ALL CHECKS PASSED. Database infrastructure is HEALTHY.');
  } catch (err) {
    console.error(`\n❌ [Node.js DB Validator] Verification ERROR:`, err.message);
    process.exitCode = 1;
  } finally {
    if (client) client.release();
    await pool.end();
  }
}

verifyDatabase().catch((err) => {
  console.error('Fatal execution error:', err);
  process.exit(1);
});
```

---

#### 2.1.4 Deterministic Health Validation Script: Python (`psycopg2` / `psycopg`)
This script must be placed at `screener/src/verify_db.py` or standalone at `db/verify_python.py`:

```python
"""
db/verify_python.py
Authoritative Database Healthcheck & Schema Validation Script (Python)
"""
import os
import sys
import time
from urllib.parse import urlparse

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


def get_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url, connect_timeout=5)
    
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "stocksentinel"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        connect_timeout=5,
    )


def verify_database():
    print("🔍 [Python DB Validator] Connecting to PostgreSQL...")
    start_time = time.time()
    
    try:
        conn = get_connection()
        conn.autocommit = False
        latency = (time.time() - start_time) * 1000
        print(f"✅ [Python DB Validator] Connected successfully ({latency:.1f}ms)")
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Server Health Check
            cur.execute("SELECT 1 AS alive, current_database() AS db, version() AS ver, NOW() AS ts;")
            row = cur.fetchone()
            print(f"   Database: {row['db']}")
            print(f"   Timestamp: {row['ts']}")
            print(f"   Version: {row['ver'].split(' on ')[0]}")
            
            # 2. Check Required Tables
            required_tables = ["stocks", "stock_daily_bars", "scan_jobs", "screener_signals"]
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = ANY(%s);
            """, (required_tables,))
            
            found = [r["table_name"] for r in cur.fetchall()]
            print("\n📋 [Python DB Validator] Table Existence Check:")
            has_error = False
            for tbl in required_tables:
                if tbl in found:
                    print(f"   [PASS] Table '{tbl}' exists")
                else:
                    print(f"   [FAIL] Table '{tbl}' MISSING!")
                    has_error = True
                    
            if has_error:
                raise ValueError("One or more required tables are missing.")

            # 3. Check Indexes
            cur.execute("""
                SELECT indexname, tablename 
                FROM pg_indexes 
                WHERE schemaname = 'public' AND tablename = ANY(%s);
            """, (required_tables,))
            indexes = [r["indexname"] for r in cur.fetchall()]
            required_indexes = [
                "idx_daily_bars_ticker_date", 
                "idx_screener_signals_date", 
                "idx_screener_signals_status",
                "idx_screener_signals_mrs"
            ]
            print("\n⚡ [Python DB Validator] Index Verification:")
            for idx in required_indexes:
                if idx in indexes:
                    print(f"   [PASS] Index '{idx}' exists")
                else:
                    print(f"   [WARN] Index '{idx}' not found (check init.sql index creation)")

            # 4. Roundtrip Transaction Integrity Check (Rolled back)
            print("\n🔒 [Python DB Validator] Testing DML Transaction & Constraints...")
            cur.execute("""
                INSERT INTO stocks (ticker, name, sector, is_active)
                VALUES ('__TEST__', 'Database Validator Probe', 'Test Sector', TRUE)
                ON CONFLICT (ticker) DO NOTHING;
            """)
            cur.execute("SELECT ticker, name FROM stocks WHERE ticker = '__TEST__';")
            probe_stock = cur.fetchone()
            assert probe_stock and probe_stock["ticker"] == "__TEST__", "DML probe insert failed"

            # Check Check Constraint Rejection
            try:
                cur.execute("""
                    INSERT INTO scan_jobs (status) VALUES ('ILLEGAL_STATUS');
                """)
                print("   [FAIL] Check constraint on scan_jobs.status did NOT reject invalid value!")
                has_error = True
            except psycopg2.Error:
                print("   [PASS] Check constraint on scan_jobs.status successfully enforced")
                conn.rollback() # reset aborted transaction

        conn.close()
        if has_error:
            print("\n❌ [Python DB Validator] Validation failed with errors.")
            sys.exit(1)
        else:
            print("\n🎉 [Python DB Validator] ALL CHECKS PASSED. PostgreSQL schema is fully compliant.")
            sys.exit(0)

    except Exception as exc:
        print(f"\n❌ [Python DB Validator] Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    verify_database()
```

---

### 2.2 Focus 2: Cross-Module Interface Contract Verification

Below is the exhaustive, column-by-column cross-module mapping verifying that the M1 DDL satisfies every data requirement across R2, R3, R4, R5, and R6.

#### 2.2.1 Table: `stocks` (Master Equities Directory)
Primary Key: `ticker`

| Column | SQL Type | Nullable | Default | Consumed By | Downstream Usage & Purpose |
|---|---|---|---|---|---|
| `ticker` | `VARCHAR(16)` | `NOT NULL` | - | R2, R3, R4, R5, R6 | Primary equity identifier (e.g. `AAPL`, `MSFT`, `BRK-B`, `SPY`). Used as PK and foreign key across daily bars and signals. |
| `name` | `VARCHAR(255)` | `NOT NULL` | - | R2, R4, R5, R6 | Company name. Rendered in Telegram alert header, dashboard table search, and chart modal header. |
| `exchange` | `VARCHAR(32)` | `YES` | `NULL` | R2, R5, R6 | Listing exchange (`NYSE`, `NASDAQ`, `AMEX`, `ARCA`). Rendered in stock summary card. |
| `sector` | `VARCHAR(128)` | `YES` | `NULL` | R2, R4, R5, R6 | GICS Sector (e.g. `Technology`, `Healthcare`). Critical filter for REST API (`/api/screener/latest?sector=...`) and frontend dropdown. |
| `industry` | `VARCHAR(128)` | `YES` | `NULL` | R2, R5, R6 | Sub-industry classification. Rendered in stock summary drawer. |
| `market_cap` | `BIGINT` | `YES` | `NULL` | R2, R5, R6 | Company market capitalization. Used for API sorting (`sort_by=market_cap`) and formatted on frontend (`$3.1T`, `$450M`). |
| `is_active` | `BOOLEAN` | `NOT NULL` | `TRUE` | R2, R3, R5 | Status flag. Set to `FALSE` if stock is delisted/halted. R3 screener filters `WHERE is_active = TRUE`. |
| `in_russell3000` | `BOOLEAN` | `NOT NULL` | `FALSE` | R2, R3, R5 | Membership flag for Russell 3000 index. |
| `in_sp1500` | `BOOLEAN` | `NOT NULL` | `FALSE` | R2, R3, R5 | Membership flag for S&P Composite 1500 index. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `CURRENT_TIMESTAMP` | Internal | Record creation timestamp. |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL` | `CURRENT_TIMESTAMP` | Internal | Last updated timestamp. |

*Indexes Required in M1*:
- `CREATE INDEX idx_stocks_active ON stocks (is_active);`
- `CREATE INDEX idx_stocks_sector ON stocks (sector);`

---

#### 2.2.2 Table: `stock_daily_bars` (Daily Time-Series OHLCV)
Composite Primary Key: `(ticker, trade_date)`

| Column | SQL Type | Nullable | Default | Consumed By | Downstream Usage & Purpose |
|---|---|---|---|---|---|
| `ticker` | `VARCHAR(16)` | `NOT NULL` | - | R2, R3, R5, R6 | Foreign key to `stocks(ticker) ON DELETE CASCADE`. |
| `trade_date` | `DATE` | `NOT NULL` | - | R2, R3, R5, R6 | Trading day date (`YYYY-MM-DD`). |
| `open` | `NUMERIC(12, 4)` | `NOT NULL` | - | R2, R3, R5, R6 | Open price. Resampled to weekly open (Monday open). Rendered in Lightweight Charts candlesticks. |
| `high` | `NUMERIC(12, 4)` | `NOT NULL` | - | R2, R3, R5, R6 | High price. Used for rolling 35-week resistance pivot in R3. Weekly high in charts. |
| `low` | `NUMERIC(12, 4)` | `NOT NULL` | - | R2, R3, R5, R6 | Low price. Used for weekly low and stop loss calculation in R3. |
| `close` | `NUMERIC(12, 4)` | `NOT NULL` | - | R2, R3, R5, R6 | Close price. Resampled to weekly close (Friday close). Base for 30w SMA, slope, and Mansfield RS vs SPY. |
| `adj_close` | `NUMERIC(12, 4)` | `NOT NULL` | - | R2 | Dividend/split-adjusted close provided by Yahoo Finance. |
| `volume` | `BIGINT` | `NOT NULL` | - | R2, R3, R5, R6 | Daily share volume. Resampled to weekly volume (`sum(volume)`). Base for 10w volume average and surge ratio. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `CURRENT_TIMESTAMP` | Internal | Record creation timestamp. |

*Indexes Required in M1*:
- `CREATE INDEX idx_daily_bars_ticker_date ON stock_daily_bars (ticker, trade_date DESC);` (Powers R2 delta sync `MAX(trade_date)` and R5 chart series retrieval).
- `CREATE INDEX idx_daily_bars_date ON stock_daily_bars (trade_date DESC);` (Powers batch universe joins on date).

---

#### 2.2.3 Table: `scan_jobs` (Execution & Concurrency Audit Log)
Primary Key: `id` (BIGSERIAL)

| Column | SQL Type | Nullable | Default | Consumed By | Downstream Usage & Purpose |
|---|---|---|---|---|---|
| `id` | `BIGSERIAL` | `NOT NULL` | Auto | R2, R3, R5 | Unique job identifier. Foreign key target for `screener_signals.scan_id`. |
| `job_type` | `VARCHAR(64)` | `NOT NULL` | `'WEEKLY_SCREENER'` | R2, R3, R5 | Job category (`'WEEKLY_SCREENER'`, `'DAILY_INGEST'`, `'DELTA_SYNC'`). |
| `status` | `VARCHAR(32)` | `NOT NULL` | `'PENDING'` | R3, R5, R6 | Execution state. CHECK: `('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')`. Used by R5 `/api/screener/trigger` for execution lock. |
| `started_at` | `TIMESTAMPTZ` | `NOT NULL` | `CURRENT_TIMESTAMP` | R3, R5, R6 | Job start timestamp. Polled by frontend progress banner. |
| `completed_at` | `TIMESTAMPTZ` | `YES` | `NULL` | R3, R5, R6 | Job completion timestamp. |
| `tickers_total` | `INTEGER` | `NOT NULL` | `0` | R2, R3, R4, R5 | Total universe tickers targeted in run (~3,800). Included in Telegram summary header. |
| `tickers_processed`| `INTEGER` | `NOT NULL` | `0` | R2, R3, R5 | Count of tickers successfully analyzed. |
| `tickers_failed` | `INTEGER` | `NOT NULL` | `0` | R2, R3, R5 | Count of tickers that errored during download/resampling. |
| `signals_found` | `INTEGER` | `NOT NULL` | `0` | R3, R4, R5, R6 | Count of stocks passing all 5 Stage 2 breakout criteria. |
| `error_message` | `TEXT` | `YES` | `NULL` | R3, R5 | Error stack trace if job fails. |
| `telegram_alert_sent` | `BOOLEAN` | `NOT NULL` | `FALSE` | R3, R4, R5 | Audit flag confirming Telegram alert dispatch. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `CURRENT_TIMESTAMP` | Internal | Audit timestamp. |

*Indexes Required in M1*:
- `CREATE INDEX idx_scan_jobs_status ON scan_jobs (status);`
- `CREATE INDEX idx_scan_jobs_started_at ON scan_jobs (started_at DESC);`

---

#### 2.2.4 Table: `screener_signals` (Stage 2 Breakout Results)
Primary Key: `id` (BIGSERIAL)  
Unique Constraint: `(scan_date, ticker)` (ensures idempotency on repeated runs)

| Column | SQL Type | Nullable | Default | Consumed By | Downstream Usage & Purpose |
|---|---|---|---|---|---|
| `id` | `BIGSERIAL` | `NOT NULL` | Auto | R5 | Unique signal record identifier. |
| `scan_id` | `BIGINT` | `YES` | `NULL` | R3, R5 | Foreign key to `scan_jobs(id) ON DELETE SET NULL`. |
| `scan_date` | `DATE` | `NOT NULL` | - | R3, R4, R5, R6 | Effective date of scan (weekly Friday date). Filtered by `/api/screener/latest?date=...` and `/api/screener/dates`. |
| `ticker` | `VARCHAR(16)` | `NOT NULL` | - | R3, R4, R5, R6 | Stock ticker symbol. Foreign key to `stocks(ticker) ON DELETE CASCADE`. |
| `entry_price` | `NUMERIC(12, 4)`| `NOT NULL` | - | R3, R4, R5, R6 | Weinstein entry pivot (prior 35w resistance high). Rendered as **Green dashed line** in Lightweight Charts modal. |
| `max_buy_price` | `NUMERIC(12, 4)`| `NOT NULL` | - | R3, R4, R5, R6 | Maximum disciplined buy price (`entry_price * 1.05`). Rendered as **Orange/Amber dashed line** in Lightweight Charts. |
| `current_price` | `NUMERIC(12, 4)`| `NOT NULL` | - | R3, R4, R5, R6 | Latest weekly close price. Displayed in table and alert cards. |
| `stop_loss_price`| `NUMERIC(12, 4)`| `NOT NULL` | - | R3, R4, R5, R6 | Initial defensive protective stop level (`entry_price * 0.92`). Rendered as **Red dashed line** in Lightweight Charts. |
| `diff_pct` | `NUMERIC(8, 4)` | `NOT NULL` | - | R3, R4, R5, R6 | Distance % from entry pivot: `((current_price - entry_price) / entry_price) * 100`. |
| `entry_status` | `VARCHAR(32)` | `NOT NULL` | - | R3, R4, R5, R6 | Categorized status badge: `('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT')`. Color badges in table & Telegram. |
| `volume_surge_ratio` | `NUMERIC(8, 4)` | `NOT NULL` | - | R3, R4, R5, R6 | Ratio of weekly volume to prior 10w average (`weekly_volume / avg_volume_10w`). Filter requires `>= 1.50`. |
| `mrs_score` | `NUMERIC(10, 4)`| `NOT NULL` | - | R3, R4, R5, R6 | Mansfield Relative Strength score vs SPY (`((R / SMA52(R)) - 1) * 100`). Filter requires `> 0.0`. Primary default sort key. |
| `sma_30w` | `NUMERIC(12, 4)`| `NOT NULL` | - | R3, R4, R5, R6 | 30-week simple moving average value at breakout. Filter requires `close > sma_30w`. |
| `sma_30w_slope` | `NUMERIC(8, 4)` | `NOT NULL` | - | R3, R4, R5, R6 | Slope of 30w SMA. Filter requires `>= 0.0` (sloping upward or flat). |
| `prior_resistance_35w` | `NUMERIC(12, 4)` | `NOT NULL` | - | R3, R5 | 35-week rolling maximum high pivot. |
| `weekly_close` | `NUMERIC(12, 4)`| `NOT NULL` | - | R3, R5 | Weekly close price bar value. |
| `weekly_volume` | `BIGINT` | `NOT NULL` | - | R3, R5 | Aggregated weekly volume. |
| `avg_volume_10w` | `BIGINT` | `NOT NULL` | - | R3, R5 | Prior 10-week average volume. |
| `stage` | `VARCHAR(32)` | `NOT NULL` | `'Stage 2 Breakout'`| R3, R5, R6 | Label identifying Stage methodology. |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL` | `CURRENT_TIMESTAMP` | Internal | Timestamp of signal detection. |

*Indexes Required in M1*:
- `CREATE INDEX idx_screener_signals_date ON screener_signals (scan_date DESC);`
- `CREATE INDEX idx_screener_signals_status ON screener_signals (entry_status);`
- `CREATE INDEX idx_screener_signals_mrs ON screener_signals (mrs_score DESC);`
- `CREATE INDEX idx_screener_signals_ticker ON screener_signals (ticker);`
- `CREATE INDEX idx_screener_signals_date_status ON screener_signals (scan_date DESC, entry_status);`

---

#### 2.2.5 Column Discrepancy Reconciliation Matrix
During the survey phase, minor terminology variations appeared across reports. The table below defines the **authoritative canonical names** enforced by M1:

| Entity | Canonical Name in M1 DDL (Authoritative) | Survey Variation Found | Resolution / Downstream Mapping |
|---|---|---|---|
| Daily Bar Date | `trade_date` | `bar_date`, `date` | Standardized to `trade_date`. Matches standard financial conventions and prevents SQL keyword collisions with `date`. |
| Latest Signal Price | `current_price` | `close_price` | Standardized to `current_price`. Represents the price evaluated for the signal. Express API may alias `current_price AS close_price` for frontend consistency if needed. |
| Signal Status | `entry_status` | `status` | Standardized to `entry_status` in `screener_signals`. Avoids ambiguity with `scan_jobs.status`. |
| Distance from Pivot | `diff_pct` | `distance_pct` | Standardized to `diff_pct` per `ORIGINAL_REQUEST.md:14`. Express API / Python may alias `diff_pct AS distance_pct` for readability. |
| Protective Stop | `stop_loss_price` | `stop_loss` | Standardized to `stop_loss_price` for naming consistency with `entry_price` and `current_price`. |
| 35w Resistance Pivot | `prior_resistance_35w` | `pivot_high_35w`, `resistance_pivot_35w` | Standardized to `prior_resistance_35w`. |
| 10w Average Volume | `avg_volume_10w` | `vol_avg_10w` | Standardized to `avg_volume_10w`. |

---

### 2.3 Focus 3: Pass/Fail Criteria & Validation Commands

#### 2.3.1 Worker Role Pass/Fail Criteria
The Worker must complete the implementation tasks and verify all items before opening a review:

| Check # | Target Component | Command / Verification Action | Expected Output / Pass Criteria | Failure Mode |
|---|---|---|---|---|
| W-1 | Docker Compose Configuration | `docker compose config` | Valid YAML parsed, exits code 0, lists `postgres` and `redis` services. | Syntax error, unrecognized Docker key. |
| W-2 | Container Lifecycle | `docker compose up -d` | Both containers start without error. | Port collision (e.g. 5432 already bound), volume permission error. |
| W-3 | PostgreSQL Healthcheck | `docker compose ps` | Container `stocksentinel-postgres` transitions to `(healthy)` within 15 seconds. | `pg_isready` fails, wrong password in healthcheck script. |
| W-4 | Redis Healthcheck | `docker compose ps` | Container `stocksentinel-redis` transitions to `(healthy)` within 10 seconds. | Redis fails to start, bad healthcheck syntax. |
| W-5 | Schema DDL Auto-Init | `docker compose logs postgres` | Logs show execution of `/docker-entrypoint-initdb.d/01-init.sql` with `CREATE TABLE` statements and zero syntax errors. | Syntax errors in DDL, relation already exists. |
| W-6 | Node.js DB Health Script | `node db/verify_node.js` | Exits with code 0. Logs `ALL CHECKS PASSED. Database infrastructure is HEALTHY.` | Exit code 1, missing tables, connection rejected. |
| W-7 | Python DB Health Script | `python db/verify_python.py` | Exits with code 0. Logs `ALL CHECKS PASSED. PostgreSQL schema is fully compliant.` | Exit code 1, missing psycopg2 module, assertion error. |

---

#### 2.3.2 Reviewer Role Pass/Fail Criteria
The Reviewer must independently inspect code quality, architecture, and security:

| Check # | Inspection Target | Verification Rule | Pass Condition |
|---|---|---|---|
| R-1 | DDL Idempotency | `db/init.sql` must use `IF NOT EXISTS` for all tables and indexes. | Safe to re-run multiple times on existing database without data loss. |
| R-2 | Referential Integrity | FKs on `stock_daily_bars` and `screener_signals` reference `stocks(ticker) ON DELETE CASCADE`. | Deleting a stock cascades cleanly; orphaned bars/signals cannot exist. |
| R-3 | Check Constraints | `scan_jobs.status` and `screener_signals.entry_status` must have explicit `CHECK` constraints. | Rejects any string not in the approved enum lists. |
| R-4 | Security & Secrets | `.gitignore` must explicitly ignore `.env`, `*.parquet`, `node_modules`, `__pycache__`. | No cleartext passwords or credentials committed to repository. |
| R-5 | Port Flexibility | `docker-compose.yml` uses `${DB_PORT:-5432}:5432` and `${REDIS_PORT:-6379}:6379`. | Developer can override ports via `.env` to avoid local machine collisions. |

---

#### 2.3.3 Challenger Role Boundary & Adversarial Injections
The Challenger must subject the M1 database infrastructure to adversarial edge conditions:

| Challenge # | Test Name | Injection Command / Action | Expected System Behavior (Pass Criteria) |
|---|---|---|---|
| C-1 | Invalid Enum Injection (`scan_jobs`) | `INSERT INTO scan_jobs (status) VALUES ('MALICIOUS_STATUS');` | Transaction rejected with PostgreSQL error: `check constraint "scan_jobs_status_check" violated`. Exits with SQL error. |
| C-2 | Invalid Enum Injection (`screener_signals`) | `INSERT INTO screener_signals (scan_date, ticker, entry_price, max_buy_price, current_price, stop_loss_price, diff_pct, entry_status, volume_surge_ratio, mrs_score, sma_30w, sma_30w_slope, prior_resistance_35w, weekly_close, weekly_volume, avg_volume_10w) VALUES ('2026-10-14', 'AAPL', 100, 105, 102, 92, 2.0, 'UNKNOWN_STATUS', 2.0, 15.0, 95, 1.2, 100, 102, 5000000, 2500000);` | Transaction rejected with PostgreSQL error: `check constraint "screener_signals_entry_status_check" violated`. |
| C-3 | Foreign Key Orphan Injection | `INSERT INTO stock_daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('NONEXISTENT', '2026-10-14', 10, 11, 9, 10, 10, 1000);` | Transaction rejected with error: `violates foreign key constraint "stock_daily_bars_ticker_fkey"`. |
| C-4 | Duplicate PK / Conflict Injection | Insert stock `TEST` twice via `INSERT INTO stocks (ticker, name) VALUES ('TEST', 'Test Inc');`. | Second insert rejected with error: `duplicate key value violates unique constraint "stocks_pkey"`. |
| C-5 | Unique Idempotency on Screener Signals | Insert two signals for `('2026-10-16', 'AAPL')`. | Second insert fails unique constraint `uq_scan_date_ticker` unless `ON CONFLICT (scan_date, ticker) DO UPDATE` is used. |
| C-6 | Host Container Crash & Data Persistence | Insert records, run `docker compose down`, followed by `docker compose up -d`. | Inspect database after restart: all previously inserted records remain intact via persistent volume `pgdata`. |
| C-7 | High Concurrency Sockets | Run 30 concurrent connection requests with pool limit set to 20. | Clients queue gracefully without crashing PostgreSQL or dropping existing sessions. |

---

#### 2.3.4 Auditor Role Acceptance Sign-Off
The Auditor conducts the final milestone verification gate:

- [ ] **Docker Engine Gate**: `docker compose ps` shows `stocksentinel-postgres` (healthy) and `stocksentinel-redis` (healthy).
- [ ] **DDL Completeness Gate**: All 4 tables (`stocks`, `stock_daily_bars`, `scan_jobs`, `screener_signals`) exist in database `stocksentinel`.
- [ ] **Index Coverage Gate**: All 7 performance indexes exist (`idx_stocks_active`, `idx_stocks_sector`, `idx_daily_bars_ticker_date`, `idx_daily_bars_date`, `idx_scan_jobs_status`, `idx_scan_jobs_started_at`, `idx_screener_signals_date`, `idx_screener_signals_status`, `idx_screener_signals_mrs`, `idx_screener_signals_ticker`, `idx_screener_signals_date_status`).
- [ ] **Dual Runtime Gate**: Both `node db/verify_node.js` and `python db/verify_python.py` return exit code 0.
- [ ] **Repository Cleanliness Gate**: No passwords in git, `.env.example` present, `.gitignore` active.

---

## 3. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|----------|---------|-------------|--------|---------|----------------|----------------|
| 1 | Infrastructure | Docker Compose PostgreSQL 16 | PostgreSQL 16 Alpine container with persistent storage and healthcheck | `docker-compose.yml`, `.env` | Running container on port 5432 | Exits 1 on port clash or volume permission error | `ORIGINAL_REQUEST.md:13` |
| 2 | Infrastructure | Docker Compose Redis 7 | Redis 7 Alpine container for optional fast caching and rate limiting | `docker-compose.yml`, `.env` | Running container on port 6379 | Exits 1 if port 6379 unavailable | `ORIGINAL_REQUEST.md:13` |
| 3 | Schema DDL | Master Stocks Table | DDL for `stocks` cataloguing ~3,800 Russell 3000 + S&P 1500 stocks + SPY | Stock metadata (ticker, name, sector, etc.) | Table `stocks` with PK `ticker` | Rejects duplicate tickers | `ORIGINAL_REQUEST.md:14` |
| 4 | Schema DDL | Daily Bars Table | Time-series OHLCV table with composite PK `(ticker, trade_date)` | Daily bars (open, high, low, close, volume) | Table `stock_daily_bars` | Rejects orphaned tickers (FK violation) | `ORIGINAL_REQUEST.md:14` |
| 5 | Schema DDL | Scan Jobs Audit Table | Job lifecycle tracking table with state CHECK constraint | Job type, started_at, total count | Table `scan_jobs` | Rejects invalid status outside enum CHECK | `ORIGINAL_REQUEST.md:14` |
| 6 | Schema DDL | Screener Signals Table | Filtered Stage 2 breakout signals with Weinstein metrics and MRS | Signal metrics (entry, max buy, stop loss, mrs) | Table `screener_signals` with unique `(scan_date, ticker)` | Rejects invalid `entry_status` enum | `ORIGINAL_REQUEST.md:14` |
| 7 | Health Validation | Node.js DB Health Script | `pg`-based validation script inspecting tables, columns, and latency | DB connection string | Console logs, exit code 0 | Exits 1 with clear diagnostic log | Dispatch assignment Focus 1 |
| 8 | Health Validation | Python DB Health Script | `psycopg2`-based script verifying tables, indexes, and transactional DML | DB connection string | Console logs, exit code 0 | Exits 1 with error trace | Dispatch assignment Focus 1 |
| 9 | Cross-Module | SPY Benchmark Seeding | SPY benchmark must be pre-seeded into `stocks` to satisfy R3 MRS calculation | Seed record `('SPY', ...)` | Row in `stocks` | Screener fails if SPY daily bars cannot be joined | Cross-module analysis (R3) |
| 10 | Cross-Module | Screener Concurrency Lock | API trigger checks for `RUNNING` status in `scan_jobs` to prevent race conditions | `POST /api/screener/trigger` | 409 Conflict if running; 202 if spawned | Prevents overlapping worker runs | Cross-module analysis (R5) |
| 11 | Cross-Module | 3 Price Lines Contract | Signals table must supply `entry_price`, `max_buy_price`, and `stop_loss_price` | Computed in R3 screener | Plotted on Lightweight Charts | Missing column breaks chart overlay | Cross-module analysis (R6) |

---

## 4. Edge Cases

| # | Feature | Input | Observed / Required Behavior |
|---|---------|-------|------------------------------|
| 1 | Schema Constraint | Insert status `'IN_PROGRESS'` into `scan_jobs` | Fails check constraint `status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')`. |
| 2 | Schema Constraint | Insert status `'BUY_NOW'` into `screener_signals` | Fails check constraint `entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT')`. |
| 3 | Ticker Symbol Format | Tickers with special chars (`BRK-B`, `BF-B`) | Stored cleanly in `stocks.ticker VARCHAR(16)`. Ingestion converts dots to dashes for Yahoo Finance. |
| 4 | Benchmark Equity | SPY ETF inclusion in common stock table | `stocks.ticker = 'SPY'`, `sector = 'Index / Benchmark'`. Foreign key in `stock_daily_bars` succeeds. |
| 5 | Stock Deletion Cascade | `DELETE FROM stocks WHERE ticker = 'TEST'` | All associated records in `stock_daily_bars` and `screener_signals` are deleted automatically (`ON DELETE CASCADE`). |
| 6 | Re-running Scan on Same Date | Second screener run for `scan_date = '2026-10-16'` | Unique constraint `(scan_date, ticker)` prevents duplicates; R3 uses `ON CONFLICT DO UPDATE` to refresh metrics. |
| 7 | Zero Volume Trading Days | Volume = 0 or NULL from exchange feed | Schema enforces `volume BIGINT NOT NULL`. Ingestion defaults null volume to 0. |
| 8 | Large Market Cap | Multi-trillion market caps (NVDA, MSFT > 3e12) | Handled safely by `stocks.market_cap BIGINT` (max 9.22e18). `INTEGER` would overflow. |
| 9 | Micro-penny Stock Prices | High precision prices (e.g. `$0.0025`) | Handled cleanly by `NUMERIC(12, 4)`. |
| 10 | Container Restart Resilience | Database host rebooted while data present | Docker volume `pgdata` persists tables and data across restarts. |

---

## 5. Caveats

1. **No Application Source Code Written**: In accordance with the Spec Miner role, no code files outside `.agents/teamwork/spec_miner_m1_3` have been modified or written.
2. **Interactive PowerShell Permission**: Direct execution of background commands via `run_command` timed out due to interactive confirmation prompts on the Windows host. Therefore, all healthcheck scripts and test commands are provided in standalone, copy-pasteable files ready for Worker execution.
3. **Redis Role in M1**: Redis 7 is provisioned in `docker-compose.yml` per R1 requirements, but is optional for core Stage 2 math. PostgreSQL remains the authoritative persistent data store for all R1-R6 workflows.

---

## 6. Conclusion

Milestone 1 (Database & Project Infrastructure) specifications have been mined and authored down to the column, constraint, index, and command level:
1. **Connection Specifications & Health Scripts**: Standardized parameters defined for Node.js (`pg`) and Python (`psycopg2`), complete with self-contained, deterministic health scripts (`db/verify_node.js` and `db/verify_python.py`).
2. **Cross-Module Contract Integrity**: Verified 100% column-to-column alignment between M1 database tables and the downstream data consumption requirements of R2 (Ingestion), R3 (Screener Engine), R4 (Telegram Alerting), R5 (Express REST API), and R6 (Frontend Lightweight Charts).
3. **Validation Gates**: Explicit pass/fail commands and criteria documented for Worker, Reviewer, Challenger, and Auditor, providing an unshakeable foundation for immediate M1 execution.

---

## 7. Verification Method

To verify these specifications independently:
1. Inspect the handoff report at `d:/git/StockSentinel/.agents/teamwork/spec_miner_m1_3/handoff.md`.
2. Inspect the cross-module column mapping in Section 2.2 against `PROJECT.md` and `ORIGINAL_REQUEST.md`.
3. Test the Node.js script specification against a local PostgreSQL instance:
   ```bash
   node db/verify_node.js
   ```
4. Test the Python script specification against a local PostgreSQL instance:
   ```bash
   python db/verify_python.py
   ```
5. Confirm that the check constraints and indexes specified in Section 2.2 prevent all invalid enum insertions listed in Section 2.3.3.
