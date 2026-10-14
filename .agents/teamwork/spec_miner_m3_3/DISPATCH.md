## 2026-10-14T04:14:04Z
You are Spec Miner for Milestone 3 (Core Screener Engine & Indicator Math) of StockSentinel.
Working directory: d:/git/StockSentinel/.agents/teamwork/spec_miner_m3_3
Project root: d:/git/StockSentinel
Original request path: d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md
Project plan path: d:/git/StockSentinel/PROJECT.md
Database schema path: d:/git/StockSentinel/db/init.sql
Test suite references: d:/git/StockSentinel/tests/e2e/tier1_features/test_f17_f20_filter_signals.py, tests/e2e/tier2_boundaries/test_t2_screener_math_boundaries.py, and tests/e2e/tier3_interactions/test_t3_screener_to_telegram.py

You MUST read ORIGINAL_REQUEST.md, PROJECT.md, and db/init.sql first.

Your primary focus:
1. Database Persistence Specification (`screener_signals` and `scan_jobs`):
   - Schema mapping in `db/init.sql` lines 122-167 for `screener_signals`:
     `scan_id`, `scan_date`, `ticker`, `entry_price`, `max_buy_price`, `current_price`, `stop_loss_price`, `diff_pct`, `entry_status`, `volume_surge_ratio`, `mrs_score`, `sma_30w`, `sma_30w_slope`, `prior_resistance_35w`, `weekly_close`, `weekly_volume`, `avg_volume_10w`, `stage`.
   - Unique constraint: `UNIQUE (scan_date, ticker)` -> UPSERT syntax: `ON CONFLICT (scan_date, ticker) DO UPDATE SET ...`
   - Job audit logging in `scan_jobs`: `job_type='WEEKLY_SCREEN'`, status transitions (`PENDING` -> `RUNNING` -> `COMPLETED` / `FAILED`), counts (`tickers_total`, `tickers_processed`, `tickers_failed`, `signals_found`), timings (`started_at`, `completed_at`), error messages.
2. Ingestion-to-Screener Pipeline Integration:
   - Read from local Snappy Parquet cache (`screener/data/parquet/<ticker>.parquet`) or PostgreSQL `stock_daily_bars`.
   - Batch screening coordination: iterate through universe, filter active common stocks, compute weekly indicators, apply Stage 2 filter, classify status, upsert signals, and log audit job.
3. Downstream Interface Contracts:
   - Data payload for Milestone 4 (Telegram Alerts): signal fields required for weekly alert cards.
   - Data payload for Milestone 5 (Backend Express REST API): `/api/screener/latest`, `/api/screener/dates`, `/api/stock/:ticker/summary`.
4. Verification Suite Specification:
   - Provide concrete specifications for `screener/verify_m3.py` and test commands for Worker, Reviewers, Challengers, and Auditor.

Do NOT modify or write source code directly. Write your comprehensive analysis and handoff report to `d:/git/StockSentinel/.agents/teamwork/spec_miner_m3_3/handoff.md`.
Maintain progress.md in your working directory. Send a message when finished.
