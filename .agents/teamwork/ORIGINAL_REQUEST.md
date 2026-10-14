# Original User Request

## 2026-10-14T02:14:21Z

Build StockSentinel, an end-to-end web application and automated weekly batch screener for ~3,500–4,000 US stocks (Russell 3000 + S&P 1500) based on Stan Weinstein Stage 2 Breakout, Mansfield Relative Strength vs SPY, automated Telegram alerts, entry point tracking vs current price, PostgreSQL database, Express.js REST API, and React + Tailwind + Lightweight Charts dashboard.

Working directory: d:/git/StockSentinel
Integrity mode: development

## Requirements

### R1. Database & Project Infrastructure
- Set up Docker Compose for PostgreSQL 16 (and optional Redis cache).
- Create database schema with migrations: `stocks`, `stock_daily_bars`, `screener_signals`, and `scan_jobs` supporting entry price, current price, diff %, entry status (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`), volume surge ratio, MRS score, and 30w SMA.

### R2. Stock Universe & Ingestion Engine (Python)
- Define universe of Russell 3000 + S&P 1500 common stocks.
- Implement resilient batch downloader using `yfinance` with chunking (50 tickers/batch), exponential backoff, rate limiting, and incremental delta updates (7-day delta sync).
- Save OHLCV data to local Parquet cache and upsert into PostgreSQL `stock_daily_bars`.

### R3. Core Screener Engine & Indicator Math (Python + Polars)
- Resample daily bars to weekly bars.
- Compute 30-week SMA, SMA slope, 10-week volume average, 35-week resistance pivot, and Mansfield Relative Strength (MRS) vs SPY.
- Filter for Stage 2 Breakout: Close > SMA 30w, SMA 30w sloping up, Close >= prior 30w-35w high, Volume >= 1.5x average, and MRS > 0.
- Compute ideal Entry Price, Max Buy Price (+5%), Current Price comparison, % distance, and Entry Status.
- Upsert results to `screener_signals` and log execution to `scan_jobs`.

### R4. Telegram Alerting System
- Dispatch formatted weekly alert via Telegram Bot API when scan completes.
- Include ticker, entry pivot, current price, distance %, status badge, stop loss, volume surge, MRS score, and web app link.
- Support chunked messaging to respect Telegram 4,096 char limits.

### R5. Backend REST API Service (Node.js / Express)
- REST endpoints:
  - `GET /api/screener/latest`: filtered/sorted screener results.
  - `GET /api/screener/dates`: list of scan dates.
  - `GET /api/stock/:ticker/chart`: weekly candle history + SMA 30w for charting.
  - `GET /api/stock/:ticker/summary`: stock details, entry/stop metrics, and technical summary.
  - `POST /api/screener/trigger`: trigger Python screener job.
  - `POST /api/notifications/telegram-test`: test Telegram bot.

### R6. Frontend Web Application (React + Vite + Tailwind CSS)
- Dashboard table with sorting, search, sector filter, and buy status badges.
- LocalStorage-persisted Watchlist drawer.
- Chart Modal using TradingView Lightweight Charts: weekly candlesticks, SMA 30w line, volume histogram, and horizontal lines for Entry Price (green), Max Buy (+5% orange), and Stop Loss (red).
- Risk & Position Sizing calculator.

## Acceptance Criteria

### Data & Screener Verification
- [ ] PostgreSQL container starts and schema initializes cleanly.
- [ ] Screener engine successfully processes tickers, calculates Stage 2 indicators and Mansfield RS correctly against SPY.
- [ ] Signals are accurately recorded in `screener_signals` with entry prices, current prices, and status.
- [ ] Telegram alert module formats and sends messages without errors.

### Backend API Verification
- [ ] All Express API endpoints return valid JSON responses with status 200.
- [ ] `/api/stock/:ticker/chart` returns properly formatted OHLCV and SMA 30w data ready for Lightweight Charts.

### Frontend Verification
- [ ] Frontend builds without TypeScript/Vite errors.
- [ ] Dashboard displays screener results and allows interactive filtering.
- [ ] Opening detail modal renders the candlestick chart with overlays.
