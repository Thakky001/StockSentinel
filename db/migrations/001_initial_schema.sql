-- ============================================================================
-- Migration 001: Initial Schema Definition
-- Supporting Weinstein Stage 2 Breakouts, Mansfield Relative Strength vs SPY,
-- Daily Bar Ingestion, Scan Job Auditing, and Real-Time Dashboard Queries.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Extensions
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ----------------------------------------------------------------------------
-- Schema Migration Tracking Table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    version VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- Automatic updated_at Trigger Function
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- 1. Table: stocks
-- Master universe directory of US Equities (Russell 3000 + S&P 1500 + SPY)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stocks (
    ticker VARCHAR(16) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    exchange VARCHAR(32),                          -- NYSE, NASDAQ, AMEX, ARCA, BATS
    sector VARCHAR(128),                           -- GICS Sector (e.g. Technology, Healthcare)
    industry VARCHAR(128),                         -- Industry Group
    market_cap BIGINT,                             -- Market Capitalization in USD
    is_active BOOLEAN NOT NULL DEFAULT TRUE,       -- False if delisted, halted, or inactive
    in_russell3000 BOOLEAN NOT NULL DEFAULT FALSE, -- Constituent of Russell 3000
    in_sp1500 BOOLEAN NOT NULL DEFAULT FALSE,      -- Constituent of S&P 1500
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Trigger for stocks.updated_at
DROP TRIGGER IF EXISTS trg_stocks_updated_at ON stocks;
CREATE TRIGGER trg_stocks_updated_at
    BEFORE UPDATE ON stocks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Indexes for stocks
CREATE INDEX IF NOT EXISTS idx_stocks_active 
    ON stocks (is_active);

CREATE INDEX IF NOT EXISTS idx_stocks_sector 
    ON stocks (sector);

CREATE INDEX IF NOT EXISTS idx_stocks_indices 
    ON stocks (in_russell3000, in_sp1500);

CREATE INDEX IF NOT EXISTS idx_stocks_search_trgm 
    ON stocks USING gin (ticker gin_trgm_ops, name gin_trgm_ops);

-- Seed benchmark SPY to ensure foreign key integrity in ingestion & screener
INSERT INTO stocks (ticker, name, exchange, sector, industry, is_active, in_sp1500, in_russell3000)
VALUES ('SPY', 'SPDR S&P 500 ETF Trust', 'ARCA', 'Benchmark', 'Index ETF', TRUE, TRUE, TRUE)
ON CONFLICT (ticker) DO NOTHING;

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
    PRIMARY KEY (ticker, trade_date),
    CONSTRAINT chk_daily_bars_positive_prices CHECK (
        open >= 0 AND high >= 0 AND low >= 0 AND close >= 0 AND adj_close >= 0
    ),
    CONSTRAINT chk_daily_bars_positive_volume CHECK (volume >= 0),
    CONSTRAINT chk_daily_bars_high_low CHECK (high >= low),
    CONSTRAINT chk_daily_bars_high_open CHECK (high >= open),
    CONSTRAINT chk_daily_bars_high_close CHECK (high >= close),
    CONSTRAINT chk_daily_bars_low_open CHECK (low <= open),
    CONSTRAINT chk_daily_bars_low_close CHECK (low <= close)
);

-- High-throughput composite indexes for stock_daily_bars
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

-- Indexes for scan_jobs
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
    
    -- Price and Pivot Points (USD)
    entry_price NUMERIC(12, 4) NOT NULL,          -- Prior 30w-35w resistance high pivot
    max_buy_price NUMERIC(12, 4) NOT NULL,        -- entry_price * 1.05 (+5% max buy zone)
    current_price NUMERIC(12, 4) NOT NULL,        -- Latest weekly close
    stop_loss_price NUMERIC(12, 4) NOT NULL,      -- Breakout support / 30w SMA level
    diff_pct NUMERIC(8, 4) NOT NULL,              -- ((current_price - entry_price) / entry_price) * 100
    
    -- Entry Status Badge
    entry_status VARCHAR(32) NOT NULL
        CONSTRAINT chk_screener_signals_entry_status CHECK (
            entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT')
        ),
    
    -- Weinstein Stage 2 Indicators & Volume Metrics
    volume_surge_ratio NUMERIC(8, 4) NOT NULL,    -- Current weekly volume / 10w avg volume (>= 1.5)
    mrs_score NUMERIC(10, 4) NOT NULL,             -- Mansfield Relative Strength vs SPY (> 0)
    sma_30w NUMERIC(12, 4) NOT NULL,              -- 30-week Simple Moving Average
    sma_30w_slope NUMERIC(8, 4) NOT NULL,         -- Slope of 30w SMA
    prior_resistance_35w NUMERIC(12, 4) NOT NULL, -- 35-week resistance pivot
    weekly_close NUMERIC(12, 4) NOT NULL,         -- Weekly closing bar price
    weekly_volume BIGINT NOT NULL,                -- Weekly total volume
    avg_volume_10w BIGINT NOT NULL,               -- 10-week average weekly volume
    stage VARCHAR(32) NOT NULL DEFAULT 'Stage 2 Breakout',
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_scan_date_ticker UNIQUE (scan_date, ticker),
    CONSTRAINT chk_screener_signals_positive_entry CHECK (entry_price > 0),
    CONSTRAINT chk_screener_signals_positive_current CHECK (current_price > 0)
);

-- High-performance query indexes for REST API sorting, filtering & chart lookup
CREATE INDEX IF NOT EXISTS idx_screener_signals_date 
    ON screener_signals (scan_date DESC);

CREATE INDEX IF NOT EXISTS idx_screener_signals_date_mrs 
    ON screener_signals (scan_date DESC, mrs_score DESC);

CREATE INDEX IF NOT EXISTS idx_screener_signals_date_status 
    ON screener_signals (scan_date DESC, entry_status);

CREATE INDEX IF NOT EXISTS idx_screener_signals_ticker 
    ON screener_signals (ticker, scan_date DESC);

CREATE INDEX IF NOT EXISTS idx_screener_signals_status 
    ON screener_signals (entry_status);

CREATE INDEX IF NOT EXISTS idx_screener_signals_scan_id 
    ON screener_signals (scan_id);

CREATE INDEX IF NOT EXISTS idx_screener_signals_mrs 
    ON screener_signals (mrs_score DESC);

-- ----------------------------------------------------------------------------
-- Record Initial Migration Baseline
-- ----------------------------------------------------------------------------
INSERT INTO schema_migrations (version, name)
VALUES ('001', 'initial_schema')
ON CONFLICT (version) DO NOTHING;
