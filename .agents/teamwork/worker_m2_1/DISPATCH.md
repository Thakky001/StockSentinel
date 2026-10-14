## 2026-10-14T03:02:49Z
You are Worker 1 for Milestone 2 (Stock Universe & Ingestion Engine) of StockSentinel.
Working directory: d:/git/StockSentinel/.agents/teamwork/worker_m2_1
Project root: d:/git/StockSentinel
Original request path: d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md
Project plan path: d:/git/StockSentinel/PROJECT.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

You MUST read the following technical design blueprints before starting:
- d:/git/StockSentinel/.agents/teamwork/explorer_m2_1/handoff.md (Complete code blueprints for config, db, universe, downloader, parquet_cache, sync, requirements.txt, pyproject.toml)
- d:/git/StockSentinel/.agents/teamwork/explorer_m2_2/handoff.md (Downloader architecture, 50-chunking, exponential backoff, single-ticker fallback, delta sync, calendar normalization)
- d:/git/StockSentinel/TEST_READY.md
- d:/git/StockSentinel/tests/e2e/tier1_features/test_f07_f11_universe_ingest.py
- d:/git/StockSentinel/tests/e2e/tier2_boundaries/test_t2_universe_boundaries.py

Your exclusive write ownership:
- `screener/requirements.txt`
- `screener/pyproject.toml`
- `screener/data/universe/russell3000_sp1500.json`
- `screener/src/config.py`
- `screener/src/db.py`
- `screener/src/universe.py`
- `screener/src/downloader.py`
- `screener/src/parquet_cache.py`
- `screener/src/sync.py`
- `screener/src/main.py`
- Any auxiliary generation scripts in `screener/data/universe/`

Deliverables:
1. `screener/requirements.txt` and `screener/pyproject.toml` specifying all Python dependencies.
2. `screener/data/universe/russell3000_sp1500.json`: Comprehensive seed dataset containing Russell 3000 + S&P 1500 equities plus mandatory `SPY` benchmark ETF with all required metadata fields.
3. `screener/src/config.py`: Environment settings with transparent `.env` and `.env.example` loading.
4. `screener/src/db.py`: Database connection and batch upsert into `stocks` and `stock_daily_bars` via psycopg2 `execute_values` (`ON CONFLICT (ticker, trade_date) DO UPDATE`).
5. `screener/src/universe.py`: Seed loading, ticker normalization (dot notation `BRK.B`), Yahoo symbol mapping (`BRK-B`), non-equity exclusion (warrants, preferreds, units, rights), and database sync.
6. `screener/src/downloader.py`: Resilient yfinance batch downloader:
   - Chunking into batches of 50 tickers.
   - Pacing delay (`RATE_LIMIT_DELAY=1.5s` + jitter) between chunks.
   - Exponential backoff with jitter on HTTP 429/500/timeouts (`min(base * 2^attempt, 30.0)`).
   - Single-ticker fallback isolating delisted/corrupted tickers.
   - OHLCV column normalization, timezone stripping to `YYYY-MM-DD`, null imputation (`adj_close` -> `close`), price sanity checks.
7. `screener/src/parquet_cache.py`: Local Parquet caching:
   - Per-ticker Snappy-compressed Parquet cache (`screener/data/parquet/<ticker>.parquet`).
   - Merge deduplication by `trade_date`.
   - Corruption resilience (re-fetch if 0 bytes or corrupt).
8. `screener/src/sync.py`: Synchronizer supporting `--mode delta` (7-day window) and `--mode cold_start` (730-day window), skipping unmodified tickers, coordinating Parquet cache and PostgreSQL upsert.
9. `screener/src/main.py`: CLI entrypoint supporting `--mode ingest|sync|all`, `--sample N`, `--delta`, `--cold-start`.
10. Execute validation and test suite (`python -m unittest tests/e2e/tier1_features/test_f07_f11_universe_ingest.py`, etc.). Document all verification commands and outputs in `d:/git/StockSentinel/.agents/teamwork/worker_m2_1/handoff.md`.
