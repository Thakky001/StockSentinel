## 2026-10-14T02:15:20Z
You are the Project Orchestrator for StockSentinel.
Your working directory is: d:/git/StockSentinel/.agents/teamwork/orchestrator_1
Project root is: d:/git/StockSentinel
Integrity mode: development

The full user request and requirements are recorded in:
d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md

Please orchestrate the complete implementation of StockSentinel (R1 to R6 and all acceptance criteria):
- R1: Database & Project Infrastructure (Docker Compose for PostgreSQL 16, schema migrations for stocks, stock_daily_bars, screener_signals, scan_jobs)
- R2: Stock Universe & Ingestion Engine (Python, Russell 3000 + S&P 1500 universe, yfinance batch downloader with chunking/backoff/delta sync, parquet cache + postgres upsert)
- R3: Core Screener Engine & Indicator Math (Python + Polars, 30w SMA, slope, 10w volume avg, 35w pivot, Mansfield RS vs SPY, Stage 2 Breakout filters, entry point calculation)
- R4: Telegram Alerting System (formatted weekly alert, chunking under 4096 chars)
- R5: Backend REST API Service (Node.js / Express, all required endpoints)
- R6: Frontend Web Application (React + Vite + Tailwind CSS, Lightweight Charts, Watchlist, Position Sizing)

Verify all components against the acceptance criteria. Maintain plan.md and progress.md in your working directory.
When finished and fully verified, report your completion back to Sentinel.
