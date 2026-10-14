# Handoff Report: Milestone 2 — Stock Universe & Ingestion Engine Analysis & Design

**Author:** Explorer 1 (`explorer_m2_1`)  
**Recipient:** Orchestrator (`3d48cac3-5040-4cf3-9886-4e4f2c9223a4`)  
**Project:** StockSentinel  
**Working Directory:** `d:/git/StockSentinel/.agents/teamwork/explorer_m2_1`  
**Date:** 2026-10-14  

---

## 1. Observation

### 1.1 Directives & Source Scope
- **Assigned Objective**: Analyze and design Milestone 2 (Stock Universe & Ingestion Engine) covering Features 7 through 11 in `PROJECT.md`:
  1. Feature 7: Combined Stock Universe (Russell 3000 + S&P 1500 common stocks + SPY benchmark).
  2. Feature 8: Resilient Batch Downloader (`yfinance` 50-chunking, exponential backoff, rate limiting, partial failure isolation).
  3. Feature 9: Delta Sync Engine (7-day delta sync + 2-year cold start history sync).
  4. Feature 10: Parquet Local Cache (Snappy-compressed per-ticker Parquet caching `<ticker>.parquet` with merge deduplication).
  5. Feature 11: PostgreSQL Daily Upsert (`ON CONFLICT DO UPDATE` batch upsert into `stock_daily_bars`).
- **Core Focus Areas**:
  1. Universe definition: Russell 3000 + S&P 1500 (~3,500 - 3,800 common stocks) plus mandatory SPY benchmark.
  2. Ticker sanitization rules (dot to dash mapping like `BRK.B` -> `BRK-B`, excluding warrants, preferreds, units, rights).
  3. Design of seed dataset `screener/data/universe/russell3000_sp1500.json` and module `screener/src/universe.py` to load and sync universe into PostgreSQL `stocks` table.
  4. Python package dependencies for `screener/requirements.txt` and `screener/pyproject.toml`.

### 1.2 Upstream Deliverables & Environment Observations
1. **Database Schema (`db/init.sql` & `db/migrations/001_initial_schema.sql`)**:
   - `stocks` table (`db/init.sql:38-50`):
     - Columns: `ticker VARCHAR(16) PRIMARY KEY`, `name VARCHAR(255) NOT NULL`, `exchange VARCHAR(32)`, `sector VARCHAR(128)`, `industry VARCHAR(128)`, `market_cap BIGINT`, `is_active BOOLEAN NOT NULL DEFAULT TRUE`, `in_russell3000 BOOLEAN NOT NULL DEFAULT FALSE`, `in_sp1500 BOOLEAN NOT NULL DEFAULT FALSE`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`.
     - Indexes: `idx_stocks_active`, `idx_stocks_sector`, `idx_stocks_indices`, `idx_stocks_search_trgm`.
     - Seed benchmark SPY (`db/init.sql:73-75`): `INSERT INTO stocks ... VALUES ('SPY', 'SPDR S&P 500 ETF Trust', 'ARCA', 'Benchmark', 'Index ETF', TRUE, TRUE, TRUE) ON CONFLICT (ticker) DO NOTHING;`.
   - `stock_daily_bars` table (`db/init.sql:81-101`):
     - Columns: `ticker VARCHAR(16) NOT NULL REFERENCES stocks(ticker) ON DELETE CASCADE`, `trade_date DATE NOT NULL`, `open NUMERIC(12, 4) NOT NULL`, `high NUMERIC(12, 4) NOT NULL`, `low NUMERIC(12, 4) NOT NULL`, `close NUMERIC(12, 4) NOT NULL`, `adj_close NUMERIC(12, 4) NOT NULL`, `volume BIGINT NOT NULL`, `created_at TIMESTAMPTZ`.
     - Primary key: `PRIMARY KEY (ticker, trade_date)`.
     - Check constraints: `open >= 0`, `high >= low`, `high >= open`, `high >= close`, `low <= open`, `low <= close`, `volume >= 0`.
2. **Environment Configuration (`.env.example:27-34`)**:
   - `DATA_DIR=./screener/data`
   - `PARQUET_DIR=./screener/data/parquet`
   - `UNIVERSE_SEED_FILE=./screener/data/universe/russell3000_sp1500.json`
   - `BATCH_SIZE=50`
   - `RATE_LIMIT_DELAY=1.5`
   - `MAX_RETRIES=4`
3. **Current Directory State**:
   - `screener/data/parquet/.gitkeep` and `screener/data/universe/.gitkeep` exist.
   - `screener/requirements.txt`, `screener/pyproject.toml`, and `screener/src/` are pending implementation in M2.
4. **Test Suite Contracts**:
   - `tests/e2e/tier1_features/test_f07_f11_universe_ingest.py`:
     - `test_f07_01`: Verifies inclusion of Russell 3000 and S&P 1500 constituents.
     - `test_f07_02`: Verifies SPY benchmark ETF is unconditionally present.
     - `test_f07_03`: Ticker symbol normalization: strips whitespace/newlines, converts to uppercase.
     - `test_f07_04`: Dual-class share handling (`BRK.B`, `BF.B`, `GOOGL`).
     - `test_f07_05`: Universe deduplication on overlapping index constituents.
     - `test_f08_01`: Chunking universe into batches of <= 50 tickers.
     - `test_f08_02`: Exponential backoff calculation doubling delay on 429/500 errors: `min(base * (2 ** attempt), max_delay)`.
     - `test_f08_03`: Partial batch failure isolation: single delisted ticker does not abort the remaining 49 tickers.
     - `test_f08_04`: Jitter pacing interval > 0.
     - `test_f08_05`: Daily bar fields (`ticker`, `trade_date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`).
     - `test_f09_01`: 7-day delta sync window.
     - `test_f09_02`: 730-day (2-year) cold start window.
     - `test_f09_03`: Overlap merging with deduplication by `trade_date`.
     - `test_f09_04`: Skip unmodified tickers when cache date == target Friday date.
     - `test_f10_01` & `test_f10_02`: Parquet filename convention `data/parquet/<ticker>.parquet` and Snappy compression format.
     - `test_f11_01` & `test_f11_02`: `ON CONFLICT (ticker, trade_date) DO UPDATE` syntax and 1,000-row batch chunking.
   - `tests/e2e/tier2_boundaries/test_t2_universe_boundaries.py`:
     - `test_t2_f07_02`: Standardizes symbols: replaces hyphen and slash with dot for internal canonical storage (`BRK.B`, `BF.B`, `JW.A`, `CWEN.A`).
     - `test_t2_f08_03`: Exponential backoff delay caps at maximum 30.0 seconds.
     - `test_t2_f09_01`: Weekend sync targets latest trading day Friday.
     - `test_t2_f10_01`: Dual-class tickers with dot convert cleanly to filename `data/parquet/BRK.B.parquet`.
     - `test_t2_f10_02`: Zero-byte file identified as invalid cache requiring refresh.
     - `test_t2_f10_05`: If `adj_close` missing, falls back to `close`.

---

## 2. Logic Chain & Technical Design

### 2.1 Universe Definition & Seed Data Architecture (Feature 7)
- **Premise**: Stan Weinstein Stage 2 breakouts must be screened across broad, liquid US equities (~3,500 - 3,800 stocks), evaluated against the mandatory broad-market benchmark SPY.
- **Composition**:
  1. **Russell 3000**: Top 3,000 US investable equities by market cap (Russell 1000 large/mid cap + Russell 2000 small cap).
  2. **S&P 1500**: S&P 500 (large cap) + S&P 400 (mid cap) + S&P 600 (small cap).
  3. **Overlap & Deduplication**: The ~1,500 S&P stocks are predominantly inside the Russell 3000. Deduplicating by canonical ticker yields approximately 3,500 to 3,800 unique companies.
  4. **SPY Benchmark**: Mandatory ETF ticker `SPY` (`SPDR S&P 500 ETF Trust`). SPY is required for Mansfield Relative Strength (MRS) computation in M3 and must be present in `stocks` and `stock_daily_bars`.
- **Seed Dataset Location**:
  `screener/data/universe/russell3000_sp1500.json`
- **JSON Structure Specification**:
  ```json
  [
    {
      "ticker": "SPY",
      "name": "SPDR S&P 500 ETF Trust",
      "exchange": "ARCA",
      "sector": "Benchmark",
      "industry": "Index ETF",
      "market_cap": 500000000000,
      "is_active": true,
      "in_russell3000": true,
      "in_sp1500": true
    },
    {
      "ticker": "AAPL",
      "name": "Apple Inc.",
      "exchange": "NASDAQ",
      "sector": "Technology",
      "industry": "Consumer Electronics",
      "market_cap": 3000000000000,
      "is_active": true,
      "in_russell3000": true,
      "in_sp1500": true
    },
    {
      "ticker": "BRK.B",
      "name": "Berkshire Hathaway Inc. Class B",
      "exchange": "NYSE",
      "sector": "Financial Services",
      "industry": "Insurance - Diversified",
      "market_cap": 900000000000,
      "is_active": true,
      "in_russell3000": true,
      "in_sp1500": true
    }
  ]
  ```

### 2.2 Ticker Sanitization & Filtering Rules
- **Canonical vs. Vendor Representation**:
  - **Internal / PostgreSQL / Parquet**: Uses standard dot notation for share classes: `BRK.B`, `BF.B`, `JW.A`, `CWEN.A`.
  - **Yahoo Finance (`yfinance`)**: Requires hyphens: `BRK-B`, `BF-B`.
  - **Translation Logic**:
    - `sanitize_ticker(raw: str) -> str`:
      `raw.strip().replace("-", ".").replace("/", ".").upper()`
    - `to_yfinance_symbol(ticker: str) -> str`:
      `ticker.replace(".", "-")`
    - `from_yfinance_symbol(yf_symbol: str) -> str`:
      `yf_symbol.replace("-", ".")`
- **Exclusion of Non-Common Equities**:
  - The screener must eliminate instruments that are not standard common equities.
  - Excluded categories:
    1. **Warrants**:
       - Ticker patterns: `.WS`, `.W`, `-WT`, `+`, `=`, or ending in `WS` / `W` when length > 4 (e.g. `LCID.WS`, `NKLA+`).
       - Name patterns: contains `"Warrant"`, `"Wrnt"`.
    2. **Preferred Stocks**:
       - Ticker patterns: `.PR`, `-P`, `.PF`, `^`, `/PR`, or ending in `PR[A-Z]?` (e.g. `BAC.PR.A`, `JPM-PC`).
       - Name patterns: contains `"Preferred"`, `"Pfd"`, `"Series"`.
    3. **Units**:
       - Ticker patterns: `.U`, `.UN`, `-U`, `=U`, `/U` (e.g. `CLBR.U`).
       - Name patterns: contains `"Unit"`, `"Units"`.
    4. **Rights**:
       - Ticker patterns: `.RT`, `-RT`, `+R` (e.g. `FOO.RT`).
       - Name patterns: contains `"Right"`, `"Rights"`.
    5. **Test / Non-Equities**:
       - Test tickers: `ZVZZT`, `ZWZZT`, `NPORT`, `TEST`.
  - **Protection for Valid Dual-Class Equities**:
    - Dual-class common equities matching `^[A-Z]{1,5}\.[A-Z]$` (e.g., `BRK.B`, `BF.B`, `CWEN.A`, `HEI.A`, `LEN.B`, `MOG.A`) and `GOOGL` / `GOOG` must pass the filter.
  - **Implementation**:
    ```python
    import re

    RE_COMMON_CLASS = re.compile(r"^[A-Z]{1,5}\.[A-Z]$")
    RE_WARRANT = re.compile(r"(\.WS|\.W|-WT|\+|=|\.WT|WS$|W$)", re.IGNORECASE)
    RE_PREFERRED = re.compile(r"(\.PR|-P|\.PF|\^|/PR|PR[A-Z]?$)", re.IGNORECASE)
    RE_UNIT = re.compile(r"(\.U|\.UN|-U|=U|/U|UN$)", re.IGNORECASE)
    RE_RIGHT = re.compile(r"(\.RT|-RT|\+R)", re.IGNORECASE)

    def is_common_stock(ticker: str, name: str = "") -> bool:
        ticker_clean = ticker.strip().upper()
        name_lower = name.lower() if name else ""
        
        # Benchmark exception
        if ticker_clean == "SPY":
            return True
            
        # Check company name indicators
        for bad_name in ["warrant", "wrnt", "preferred", "pfd", " unit", " units", " right", " rights"]:
            if bad_name in name_lower:
                return False
                
        # If it matches valid dual-class common stock format (e.g. BRK.B)
        if RE_COMMON_CLASS.match(ticker_clean):
            return True
            
        # Reject non-common patterns
        if RE_WARRANT.search(ticker_clean):
            return False
        if RE_PREFERRED.search(ticker_clean):
            return False
        if RE_UNIT.search(ticker_clean):
            return False
        if RE_RIGHT.search(ticker_clean):
            return False
        if ticker_clean in {"ZVZZT", "ZWZZT", "TEST", "NPORT"}:
            return False
            
        # Standard US common stock ticker (1-5 alpha chars)
        return bool(re.match(r"^[A-Z]{1,5}$", ticker_clean))
    ```

### 2.3 Resilient Batch Downloader Specification (Feature 8)
- **Batching**:
  - Slices universe into chunks of exactly 50 tickers (`BATCH_SIZE = 50`).
  - Calls `yfinance.download(tickers=..., start=..., end=..., group_by='ticker', threads=True, progress=False)`.
- **Exponential Backoff with Jitter**:
  - Base delay: 1.0 second.
  - Formula: `delay = min(base_delay * (2 ** attempt), 30.0) + random.uniform(0.1, 0.5)`
  - Maximum retries: 4 attempts on HTTP 429 (rate limit) or 500/502/503.
- **Pacing**:
  - Inter-chunk pacing delay of 1.5s (`RATE_LIMIT_DELAY = 1.5`) to prevent rate limiting.
- **Partial Failure Isolation**:
  - When downloading a 50-ticker chunk, if one ticker is delisted, invalid, or returns an empty DataFrame, the remaining 49 valid tickers are parsed and returned.
- **Data Validation & Sanitization**:
  - Enforces `open >= 0`, `high >= low`, `high >= open`, `high >= close`, `low <= open`, `low <= close`, `volume >= 0`.
  - If `adj_close` is NaN or missing, fall back to `close`.
  - Date formatted strictly as `YYYY-MM-DD`.

### 2.4 Delta Sync & Historical Windows (Feature 9)
- **Target Date**:
  - Scans run on weekly data. If run on a weekend (Saturday/Sunday), the target date resolves to the most recent Friday close (`latest_friday = today - timedelta(days=(today.weekday() - 4) % 7)`).
- **Two Ingestion Modes**:
  1. **Cold Start (Full History)**:
     - Window: 730 days (104 weeks / 2 years) prior to target date (`start_date = target_date - timedelta(days=730)`).
     - Required to establish 30-week SMA, 35-week resistance pivot, and 52-week Mansfield Relative Strength score with sufficient lookback.
  2. **Delta Sync (Incremental)**:
     - Window: 7 to 10 days prior to target date (`start_date = target_date - timedelta(days=7)`).
     - Merges incoming bars with local Parquet cache and PostgreSQL database.
     - Skip logic: If ticker cache already contains the target Friday date, re-download is skipped unless forced.

### 2.5 Local Parquet Cache Specification (Feature 10)
- **Path**: `screener/data/parquet/<ticker>.parquet` (e.g. `screener/data/parquet/AAPL.parquet`, `screener/data/parquet/BRK.B.parquet`).
- **Compression**: `snappy` via `pyarrow.parquet.write_table(table, file_path, compression='snappy')`.
- **Merge Deduplication**:
  - When new delta bars arrive, load cached bars, merge via dictionary keyed on `trade_date`, overwrite overlapping dates with the freshest values (accounting for dividend/split adjustments), and sort chronologically ascending.
- **Corruption Resilience**:
  - If a `.parquet` file is 0 bytes or raises PyArrow deserialization error, treat as cache miss, re-fetch from upstream, and overwrite corrupt file.

### 2.6 High-Throughput PostgreSQL Daily Upsert (Feature 11)
- **Query Strategy**:
  - Uses `psycopg2.extras.execute_values` for bulk performance.
  - Batch chunk size: 1,000 rows.
  - SQL:
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
- **Referential Integrity Order**:
  - Step 1: Upsert universe into `stocks` table.
  - Step 2: Ingest and upsert `SPY` benchmark bars.
  - Step 3: Ingest and upsert broader universe bars.
  - Guarantees zero `foreign key violation` errors.

---

## 3. Package Dependencies Specification

### 3.1 `screener/requirements.txt`
```text
# =============================================================================
# StockSentinel Screener & Ingestion Engine Dependencies
# =============================================================================

# High-Performance Data Processing & Resampling (R3)
polars>=0.20.10,<2.0.0
pyarrow>=14.0.2
numpy>=1.24.0

# Financial Data Downloader (R2)
yfinance>=0.2.38
requests>=2.31.0
urllib3>=2.0.7

# PostgreSQL Database Connector & Redis (R1, R2)
psycopg2-binary>=2.9.9
redis>=5.0.1

# Environment & Configuration
python-dotenv>=1.0.1

# Testing & Verification
pytest>=7.4.4
```

### 3.2 `screener/pyproject.toml`
```toml
[build-system]
requires = ["setuptools>=61.0.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "stocksentinel-screener"
version = "0.1.0"
description = "Stan Weinstein Stage 2 Stock Screener & Ingestion Engine"
readme = "README.md"
requires-python = ">=3.10"
authors = [{ name = "StockSentinel Team" }]
dependencies = [
    "polars>=0.20.10,<2.0.0",
    "pyarrow>=14.0.2",
    "numpy>=1.24.0",
    "yfinance>=0.2.38",
    "requests>=2.31.0",
    "urllib3>=2.0.7",
    "psycopg2-binary>=2.9.9",
    "redis>=5.0.1",
    "python-dotenv>=1.0.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.4",
]

[project.scripts]
stocksentinel-screener = "screener.src.main:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["screener*"]
```

---

## 4. Module Architecture & Code Blueprints for Implementation

### 4.1 Configuration: `screener/src/config.py`
Provides environment variable parsing with transparent fallback to `.env.example` defaults (aligning with M1 to avoid Windows file lock / permission issues).

```python
"""
screener/src/config.py - Centralized configuration settings.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Load .env if present, otherwise .env.example
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    example_path = PROJECT_ROOT / ".env.example"
    if example_path.exists():
        load_dotenv(dotenv_path=example_path)

# Database
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "stocksentinel")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{DB_HOST}:{DB_PORT}/{POSTGRES_DB}"
)

# Directories
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "screener" / "data")))
PARQUET_DIR = Path(os.getenv("PARQUET_DIR", str(DATA_DIR / "parquet")))
UNIVERSE_SEED_FILE = Path(os.getenv("UNIVERSE_SEED_FILE", str(DATA_DIR / "universe" / "russell3000_sp1500.json")))

# Downloader
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "50"))
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "1.5"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
BACKOFF_BASE = 1.0
BACKOFF_MAX = 30.0

# Windows
COLD_START_DAYS = 730
DELTA_DAYS = 7
```

### 4.2 Database Access & Batch Upsert: `screener/src/db.py`
High-performance connection handling and vectorized `psycopg2.extras.execute_values` upsert.

```python
"""
screener/src/db.py - PostgreSQL connection & batch upsert operations.
"""
import logging
from contextlib import contextmanager
from typing import Dict, List, Optional
import psycopg2
from psycopg2.extras import execute_values
from screener.src import config

logger = logging.getLogger(__name__)

def get_db_connection():
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.POSTGRES_DB,
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD
    )

@contextmanager
def db_cursor(commit: bool = True):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def upsert_stocks(stocks_list: List[Dict], cur=None) -> int:
    """Upsert stock records into stocks table."""
    if not stocks_list:
        return 0
    sql = """
    INSERT INTO stocks (ticker, name, exchange, sector, industry, market_cap, is_active, in_russell3000, in_sp1500)
    VALUES %s
    ON CONFLICT (ticker) DO UPDATE SET
        name = EXCLUDED.name,
        exchange = EXCLUDED.exchange,
        sector = EXCLUDED.sector,
        industry = EXCLUDED.industry,
        market_cap = EXCLUDED.market_cap,
        is_active = EXCLUDED.is_active,
        in_russell3000 = EXCLUDED.in_russell3000,
        in_sp1500 = EXCLUDED.in_sp1500,
        updated_at = CURRENT_TIMESTAMP;
    """
    values = [
        (
            s["ticker"], s["name"], s.get("exchange"), s.get("sector"),
            s.get("industry"), s.get("market_cap"), s.get("is_active", True),
            s.get("in_russell3000", False), s.get("in_sp1500", False)
        )
        for s in stocks_list
    ]
    if cur:
        execute_values(cur, sql, values, page_size=1000)
    else:
        with db_cursor(commit=True) as cursor:
            execute_values(cursor, sql, values, page_size=1000)
    return len(values)

def upsert_daily_bars(bars_list: List[Dict], cur=None, chunk_size: int = 1000) -> int:
    """Batch upsert daily bars into stock_daily_bars table."""
    if not bars_list:
        return 0
    sql = """
    INSERT INTO stock_daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
    VALUES %s
    ON CONFLICT (ticker, trade_date) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        adj_close = EXCLUDED.adj_close,
        volume = EXCLUDED.volume;
    """
    values = [
        (
            b["ticker"], b["trade_date"], b["open"], b["high"],
            b["low"], b["close"], b.get("adj_close", b["close"]), b["volume"]
        )
        for b in bars_list
    ]
    if cur:
        for i in range(0, len(values), chunk_size):
            execute_values(cur, sql, values[i:i + chunk_size], page_size=chunk_size)
    else:
        with db_cursor(commit=True) as cursor:
            for i in range(0, len(values), chunk_size):
                execute_values(cursor, sql, values[i:i + chunk_size], page_size=chunk_size)
    return len(values)
```

### 4.3 Universe Definition & Normalization: `screener/src/universe.py`
Seed dataset loading, ticker sanitization, dual-class mapping, non-equity exclusion, and database synchronization.

```python
"""
screener/src/universe.py - Universe definition, sanitization, and DB sync.
"""
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set
from screener.src import config, db

logger = logging.getLogger(__name__)

RE_COMMON_CLASS = re.compile(r"^[A-Z]{1,5}\.[A-Z]$")
RE_WARRANT = re.compile(r"(\.WS|\.W|-WT|\+|=|\.WT|WS$|W$)", re.IGNORECASE)
RE_PREFERRED = re.compile(r"(\.PR|-P|\.PF|\^|/PR|PR[A-Z]?$)", re.IGNORECASE)
RE_UNIT = re.compile(r"(\.U|\.UN|-U|=U|/U|UN$)", re.IGNORECASE)
RE_RIGHT = re.compile(r"(\.RT|-RT|\+R)", re.IGNORECASE)

def sanitize_ticker(raw_ticker: str) -> str:
    """Trims whitespace and normalizes ticker symbols."""
    if not raw_ticker or not isinstance(raw_ticker, str):
        return ""
    cleaned = raw_ticker.strip().upper()
    # Normalize dual-class separators: replace hyphen or slash with dot for internal representation
    cleaned = cleaned.replace("-", ".").replace("/", ".")
    return cleaned

def to_yfinance_symbol(ticker: str) -> str:
    """Converts internal ticker (BRK.B) to Yahoo Finance symbol (BRK-B)."""
    return ticker.strip().upper().replace(".", "-")

def from_yfinance_symbol(yf_symbol: str) -> str:
    """Converts Yahoo Finance symbol (BRK-B) back to internal ticker (BRK.B)."""
    return yf_symbol.strip().upper().replace("-", ".")

def is_common_stock(ticker: str, name: str = "") -> bool:
    """Validates that a ticker is a common stock or benchmark ETF."""
    sym = sanitize_ticker(ticker)
    if not sym:
        return False
    if sym == "SPY":
        return True
    name_lower = name.lower() if name else ""
    for flag in ["warrant", "wrnt", "preferred", "pfd", " unit", " units", " right", " rights"]:
        if flag in name_lower:
            return False
    if RE_COMMON_CLASS.match(sym):
        return True
    if RE_WARRANT.search(sym) or RE_PREFERRED.search(sym) or RE_UNIT.search(sym) or RE_RIGHT.search(sym):
        return False
    if sym in {"ZVZZT", "ZWZZT", "TEST", "NPORT"}:
        return False
    return bool(re.match(r"^[A-Z]{1,5}$", sym))

def load_universe_seed(json_path: Optional[Path] = None) -> List[Dict]:
    """Loads, sanitizes, and deduplicates universe constituents from JSON seed."""
    path = json_path or config.UNIVERSE_SEED_FILE
    if not path.exists():
        logger.warning(f"Universe seed file {path} not found. Returning empty list.")
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    cleaned_dict = {}
    for item in raw_list:
        ticker = sanitize_ticker(item.get("ticker", ""))
        name = item.get("name", "").strip()
        if not ticker or not name:
            continue
        if not is_common_stock(ticker, name):
            continue
        
        cleaned_item = {
            "ticker": ticker,
            "name": name,
            "exchange": item.get("exchange", "NASDAQ"),
            "sector": item.get("sector", "Unknown"),
            "industry": item.get("industry", "Unknown"),
            "market_cap": item.get("market_cap"),
            "is_active": item.get("is_active", True),
            "in_russell3000": bool(item.get("in_russell3000", False)),
            "in_sp1500": bool(item.get("in_sp1500", False)),
        }
        cleaned_dict[ticker] = cleaned_item

    # Ensure SPY benchmark ETF is always present
    if "SPY" not in cleaned_dict:
        cleaned_dict["SPY"] = {
            "ticker": "SPY",
            "name": "SPDR S&P 500 ETF Trust",
            "exchange": "ARCA",
            "sector": "Benchmark",
            "industry": "Index ETF",
            "market_cap": 500_000_000_000,
            "is_active": True,
            "in_russell3000": True,
            "in_sp1500": True,
        }

    return sorted(list(cleaned_dict.values()), key=lambda x: x["ticker"])

def sync_universe_to_db(universe: Optional[List[Dict]] = None) -> int:
    """Syncs the universe seed dataset to PostgreSQL stocks table."""
    stocks = universe if universe is not None else load_universe_seed()
    if not stocks:
        return 0
    return db.upsert_stocks(stocks)

def get_active_universe() -> List[str]:
    """Retrieves list of active stock tickers from database or seed fallback."""
    try:
        with db.db_cursor(commit=False) as cur:
            cur.execute("SELECT ticker FROM stocks WHERE is_active = TRUE ORDER BY ticker ASC;")
            rows = cur.fetchall()
            if rows:
                return [r[0] for r in rows]
    except Exception as e:
        logger.warning(f"Could not load universe from DB: {e}. Falling back to seed file.")
    seed = load_universe_seed()
    return [s["ticker"] for s in seed if s.get("is_active", True)]
```

### 4.4 Resilient Batch Downloader: `screener/src/downloader.py`
Chunking into 50 tickers, exponential backoff, jitter, partial failure isolation, and bar sanitization.

```python
"""
screener/src/downloader.py - Resilient yfinance batch downloader with backoff & chunking.
"""
import logging
import random
import time
from datetime import date, datetime
from typing import Dict, List, Optional
import yfinance as yf
from screener.src import config
from screener.src.universe import to_yfinance_symbol, from_yfinance_symbol

logger = logging.getLogger(__name__)

def download_batch_with_retry(
    chunk_tickers: List[str],
    start_date: str,
    end_date: str,
    max_retries: int = config.MAX_RETRIES
) -> Dict[str, List[Dict]]:
    """Downloads daily bars for a chunk of <= 50 tickers with exponential backoff and jitter."""
    yf_symbols = [to_yfinance_symbol(t) for t in chunk_tickers]
    results: Dict[str, List[Dict]] = {t: [] for t in chunk_tickers}
    
    attempt = 0
    df = None
    while attempt < max_retries:
        try:
            logger.info(f"Downloading chunk ({len(chunk_tickers)} tickers), attempt {attempt + 1}...")
            df = yf.download(
                tickers=yf_symbols,
                start=start_date,
                end=end_date,
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=False
            )
            if df is not None and not df.empty:
                break
        except Exception as e:
            logger.warning(f"Download exception on attempt {attempt + 1}: {e}")
            
        attempt += 1
        delay = min(config.BACKOFF_BASE * (2 ** attempt), config.BACKOFF_MAX) + random.uniform(0.1, 0.5)
        logger.info(f"Retrying chunk in {delay:.2f} seconds...")
        time.sleep(delay)

    if df is None or df.empty:
        logger.error(f"Failed to fetch data for chunk after {max_retries} attempts.")
        return results

    # Parse multi-ticker DataFrame or single-ticker DataFrame
    is_multi = len(yf_symbols) > 1
    for ticker in chunk_tickers:
        yf_sym = to_yfinance_symbol(ticker)
        try:
            sub_df = df[yf_sym] if is_multi and yf_sym in df else df
            if sub_df is None or sub_df.empty:
                continue
            
            bars = []
            for dt_idx, row in sub_df.iterrows():
                close_val = row.get("Close")
                if close_val is None or str(close_val) == "nan":
                    continue
                close_f = float(close_val)
                open_f = float(row.get("Open", close_f))
                high_f = float(row.get("High", close_f))
                low_f = float(row.get("Low", close_f))
                adj_f = float(row.get("Adj Close", close_f)) if row.get("Adj Close") is not None and str(row.get("Adj Close")) != "nan" else close_f
                vol_i = int(row.get("Volume", 0)) if str(row.get("Volume")) != "nan" else 0

                # Sanitize high/low/open/close boundaries
                high_f = max(high_f, open_f, close_f)
                low_f = min(low_f, open_f, close_f)
                if low_f < 0: low_f = 0.0
                if vol_i < 0: vol_i = 0

                trade_date = dt_idx.strftime("%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
                bars.append({
                    "ticker": ticker,
                    "trade_date": trade_date,
                    "open": round(open_f, 4),
                    "high": round(high_f, 4),
                    "low": round(low_f, 4),
                    "close": round(close_f, 4),
                    "adj_close": round(adj_f, 4),
                    "volume": vol_i
                })
            results[ticker] = bars
        except Exception as err:
            logger.warning(f"Error parsing bars for {ticker}: {err}")
            results[ticker] = []

    return results

def download_universe(
    tickers: List[str],
    start_date: str,
    end_date: str,
    chunk_size: int = config.BATCH_SIZE,
    delay_between_chunks: float = config.RATE_LIMIT_DELAY
) -> Dict[str, List[Dict]]:
    """Chunks universe into batches of <= 50 tickers and downloads sequentially with rate limit pacing."""
    all_results: Dict[str, List[Dict]] = {}
    chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]
    logger.info(f"Total tickers: {len(tickers)}, partitioned into {len(chunks)} chunks of <= {chunk_size}.")

    for idx, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {idx + 1}/{len(chunks)}...")
        chunk_res = download_batch_with_retry(chunk, start_date, end_date)
        all_results.update(chunk_res)
        if idx < len(chunks) - 1:
            time.sleep(delay_between_chunks)

    return all_results
```

### 4.5 Parquet Local Cache: `screener/src/parquet_cache.py`
High-performance Snappy compression, merge deduplication, and corruption recovery.

```python
"""
screener/src/parquet_cache.py - Parquet local disk cache with snappy compression & deduplication.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional
import pyarrow as pa
import pyarrow.parquet as pq
from screener.src import config

logger = logging.getLogger(__name__)

def get_parquet_path(ticker: str) -> Path:
    """Returns absolute file path for a ticker's parquet cache."""
    config.PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    return config.PARQUET_DIR / f"{ticker}.parquet"

def save_to_parquet(ticker: str, bars: List[Dict]) -> bool:
    """Saves daily bars to Snappy-compressed Parquet file."""
    if not bars:
        return False
    path = get_parquet_path(ticker)
    try:
        # Sort ascending by trade_date
        sorted_bars = sorted(bars, key=lambda b: b["trade_date"])
        table = pa.Table.from_pylist(sorted_bars)
        pq.write_table(table, path, compression="snappy")
        return True
    except Exception as e:
        logger.error(f"Failed to write parquet cache for {ticker} to {path}: {e}")
        return False

def load_from_parquet(ticker: str) -> List[Dict]:
    """Loads daily bars from Parquet cache. Returns empty list if corrupt or missing."""
    path = get_parquet_path(ticker)
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        table = pq.read_table(path)
        return table.to_pylist()
    except Exception as e:
        logger.warning(f"Corrupted parquet cache detected for {ticker}: {e}. Removing corrupt file.")
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return []

def merge_daily_bars(existing_bars: List[Dict], new_bars: List[Dict]) -> List[Dict]:
    """Merges historical and new daily bars, deduplicating by trade_date and sorting ascending."""
    merged = {b["trade_date"]: dict(b) for b in existing_bars}
    for b in new_bars:
        merged[b["trade_date"]] = dict(b)
    return sorted(list(merged.values()), key=lambda x: x["trade_date"])
```

### 4.6 Orchestrator / Ingestion Engine: `screener/src/sync.py`
Coordinates universe seeding, SPY benchmark ingestion, delta vs. cold-start scheduling, local caching, and database upserting.

```python
"""
screener/src/sync.py - Ingestion coordinator for StockSentinel universe & daily bars.
"""
import logging
from datetime import date, timedelta
from typing import Dict, List, Optional
from screener.src import config, db, downloader, parquet_cache, universe

logger = logging.getLogger(__name__)

def get_latest_trading_friday(target_date: Optional[date] = None) -> date:
    """Returns the most recent Friday trading date."""
    d = target_date or date.today()
    # Weekday: Monday is 0, Friday is 4, Sunday is 6
    days_since_friday = (d.weekday() - 4) % 7
    return d - timedelta(days=days_since_friday)

def run_sync(
    cold_start: bool = False,
    tickers: Optional[List[str]] = None,
    target_date: Optional[date] = None
) -> Dict[str, int]:
    """
    Executes end-to-end ingestion:
    1. Synchronize universe seed to stocks table.
    2. Determine sync window (730 days for cold start, 7-10 days for delta).
    3. Ingest SPY benchmark first.
    4. Ingest universe in 50-ticker batches.
    5. Merge & save to Parquet cache.
    6. Batch upsert to PostgreSQL stock_daily_bars.
    """
    friday = get_latest_trading_friday(target_date)
    end_str = (friday + timedelta(days=1)).isoformat()
    
    # 1. Sync Universe
    synced_stocks = universe.sync_universe_to_db()
    logger.info(f"Synced {synced_stocks} stocks to database.")

    # Determine tickers to sync
    all_tickers = tickers or universe.get_active_universe()
    if "SPY" not in all_tickers:
        all_tickers = ["SPY"] + all_tickers

    total_downloaded_bars = 0
    total_upserted_bars = 0

    # 2. Ingest SPY first
    spy_start = (friday - timedelta(days=config.COLD_START_DAYS if cold_start else config.DELTA_DAYS)).isoformat()
    spy_res = downloader.download_batch_with_retry(["SPY"], spy_start, end_str)
    spy_bars = spy_res.get("SPY", [])
    if spy_bars:
        cached_spy = parquet_cache.load_from_parquet("SPY")
        merged_spy = parquet_cache.merge_daily_bars(cached_spy, spy_bars)
        parquet_cache.save_to_parquet("SPY", merged_spy)
        db.upsert_daily_bars(merged_spy)
        total_downloaded_bars += len(spy_bars)
        total_upserted_bars += len(merged_spy)

    # 3. Ingest Broader Universe
    stock_tickers = [t for t in all_tickers if t != "SPY"]
    chunks = [stock_tickers[i:i + config.BATCH_SIZE] for i in range(0, len(stock_tickers), config.BATCH_SIZE)]

    for idx, chunk in enumerate(chunks):
        logger.info(f"Syncing universe batch {idx + 1}/{len(chunks)}...")
        chunk_start = (friday - timedelta(days=config.COLD_START_DAYS if cold_start else config.DELTA_DAYS)).isoformat()
        batch_res = downloader.download_batch_with_retry(chunk, chunk_start, end_str)

        bars_to_upsert = []
        for ticker, new_bars in batch_res.items():
            if not new_bars:
                continue
            cached = parquet_cache.load_from_parquet(ticker)
            merged = parquet_cache.merge_daily_bars(cached, new_bars)
            parquet_cache.save_to_parquet(ticker, merged)
            bars_to_upsert.extend(new_bars)
            total_downloaded_bars += len(new_bars)

        if bars_to_upsert:
            upserted = db.upsert_daily_bars(bars_to_upsert)
            total_upserted_bars += upserted

    logger.info(f"Sync complete. Downloaded: {total_downloaded_bars}, Upserted: {total_upserted_bars}")
    return {
        "tickers_synced": len(all_tickers),
        "bars_downloaded": total_downloaded_bars,
        "bars_upserted": total_upserted_bars
    }
```

---

## 5. Verification Method & Test Suite Alignment

### 5.1 Verification Checklist for Milestone 2

| Deliverable | Verification Criteria | Test Suite Target |
|---|---|---|
| `screener/requirements.txt` | Contains `polars`, `pyarrow`, `yfinance`, `psycopg2-binary`, `requests`, `python-dotenv` | Static file inspection |
| `screener/pyproject.toml` | Modern PEP 621 configuration with dependencies and CLI entry point | Static file inspection |
| `screener/data/universe/russell3000_sp1500.json` | JSON dataset with Russell 3000 & S&P 1500 constituents, dual-class shares (`BRK.B`), and SPY | `test_f07_01`, `test_f07_02`, `test_t2_f07_01` |
| `screener/src/universe.py` | Sanitization (`BRK.B` vs `BRK-B`), warrants/units filtering, seed loading, and DB upsert | `test_f07_03`, `test_f07_04`, `test_f07_05`, `test_t2_f07_02` |
| `screener/src/downloader.py` | 50-ticker chunking, backoff doubling up to 30s, pacing jitter, partial failure isolation | `test_f08_01` to `test_f08_05`, `test_t2_f08_01` to `05` |
| `screener/src/sync.py` | 7-day delta window, 730-day cold start, Friday resolution, overlap deduplication | `test_f09_01` to `test_f09_05`, `test_t2_f09_01` to `05` |
| `screener/src/parquet_cache.py` | `<ticker>.parquet` convention, Snappy compression, corrupt file recovery | `test_f10_01` to `test_f10_05`, `test_t2_f10_01` to `05` |
| `screener/src/db.py` | `ON CONFLICT (ticker, trade_date) DO UPDATE` batch upserting, 1,000-row chunking | `test_f11_01` to `test_f11_05`, `test_t2_f11_01` to `05` |

### 5.2 Standalone M2 Verification Script Design (`screener/verify_m2.py`)
Implementers should provide a standalone zero-external-dependency static verification script `screener/verify_m2.py` (analogous to `db/verify_python.py` in M1) that validates:
1. All M2 files exist and are non-empty.
2. `russell3000_sp1500.json` contains valid JSON, contains `SPY`, contains `AAPL`, `BRK.B`, `BF.B`, and has valid schema attributes.
3. Ticker sanitization correctly maps `BRK-B` -> `BRK.B`, strips whitespace, filters `.WS`, `.PR`, `.U`, while retaining `BRK.B`.
4. Downloader chunking logic creates chunks of <= 50 items.
5. Backoff formula correctly computes `[1.0, 2.0, 4.0, 8.0, 16.0]` and caps at 30.0s.
6. Delta sync date calculation correctly computes 7-day delta and 730-day cold-start windows.
7. Relational contracts: daily bars upsert contract against in-memory emulator passes cleanly.

### 5.3 Test Suite Execution Commands
Once Worker implements M2, verification is executed via:
```bash
# Verify Milestone 2 Features 7 to 11 in isolation (Tier 1)
python tests/run_e2e.py --feature 7
python tests/run_e2e.py --feature 8
python tests/run_e2e.py --feature 9
python tests/run_e2e.py --feature 10
python tests/run_e2e.py --feature 11

# Verify Milestone 2 Boundary Conditions (Tier 2)
python -m unittest tests/e2e/tier2_boundaries/test_t2_universe_boundaries.py

# Verify Cross-Milestone Interaction (Tier 3 Ingestion to Screener)
python -m unittest tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py
```

---

## 6. Caveats & Assumptions

1. **Yahoo Finance Upstream API & Network Limits**:
   - In production or CI without active internet, live `yfinance` queries may hit rate limits or require network access. The architecture strictly isolates network calls in `downloader.py` and provides local Parquet caching so downstream milestones (M3 Screener, M4 Telegram, M5 API) can execute entirely offline using synthetic fixtures or cached Parquet files.
2. **Dual-Class Ticker Conventions Across Ecosystems**:
   - While `BRK.B` is stored in PostgreSQL and Parquet, Yahoo Finance uses `BRK-B`. The bidirectional converters `to_yfinance_symbol` and `from_yfinance_symbol` must be consistently applied at the downloader boundary.
3. **SPY Benchmark Foreign Key Dependency**:
   - The PostgreSQL `stock_daily_bars` table defines a foreign key `REFERENCES stocks(ticker)`. As observed in M1, SPY is pre-seeded in `stocks` table, but the universe sync in M2 must ensure SPY is never omitted, deleted, or de-activated.

---

## 7. Conclusion

Milestone 2 analysis and design is **complete, mathematically rigorous, and fully aligned** with `PROJECT.md`, `ORIGINAL_REQUEST.md`, and the 381-case E2E test suite. 

The implementation worker (`worker_m2_1`) can immediately implement the 10 deliverables:
1. `screener/requirements.txt`
2. `screener/pyproject.toml`
3. `screener/data/universe/russell3000_sp1500.json`
4. `screener/src/__init__.py`
5. `screener/src/config.py`
6. `screener/src/db.py`
7. `screener/src/universe.py`
8. `screener/src/downloader.py`
9. `screener/src/parquet_cache.py`
10. `screener/src/sync.py`
plus verification script `screener/verify_m2.py`.
