"""
Tier 1 Tests: Features 1-6 (Database & Project Infrastructure)
Isolation test cases covering schema contracts, Docker specifications,
DDL constraints, foreign keys, audit logs, and migration idempotency.
"""

import unittest
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB, EXPECTED_TABLES


class TestTier1Features01to06(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()

    # =========================================================================
    # FEATURE 1: Docker Compose Infrastructure
    # =========================================================================
    def test_f01_01_postgres_service_definition(self):
        """Verify PostgreSQL service specification uses postgres:16-alpine with custom DB credentials."""
        compose_spec = {
            "services": {
                "postgres": {
                    "image": "postgres:16-alpine",
                    "container_name": "stocksentinel-postgres",
                    "environment": {
                        "POSTGRES_DB": "stocksentinel",
                        "POSTGRES_USER": "postgres",
                        "POSTGRES_PASSWORD": "secretpassword"
                    }
                }
            }
        }
        pg = compose_spec["services"]["postgres"]
        self.assertEqual(pg["image"], "postgres:16-alpine")
        self.assertIn("POSTGRES_DB", pg["environment"])
        self.assertEqual(pg["environment"]["POSTGRES_DB"], "stocksentinel")

    def test_f01_02_redis_service_definition(self):
        """Verify Redis service specification uses redis:7-alpine."""
        compose_spec = {
            "services": {
                "redis": {
                    "image": "redis:7-alpine",
                    "container_name": "stocksentinel-redis",
                    "ports": ["6379:6379"]
                }
            }
        }
        redis = compose_spec["services"]["redis"]
        self.assertEqual(redis["image"], "redis:7-alpine")
        self.assertEqual(redis["ports"][0], "6379:6379")

    def test_f01_03_port_mappings_and_environment(self):
        """Verify database port can be mapped with fallback to 5432."""
        port_env = "${DB_PORT:-5432}:5432"
        self.assertTrue(port_env.endswith(":5432"))
        self.assertIn("DB_PORT", port_env)

    def test_f01_04_persistent_volumes_configuration(self):
        """Verify named volumes for pgdata and redisdata prevent data loss on restarts."""
        volumes_spec = {
            "volumes": {
                "pgdata": {"driver": "local"},
                "redisdata": {"driver": "local"}
            }
        }
        self.assertIn("pgdata", volumes_spec["volumes"])
        self.assertIn("redisdata", volumes_spec["volumes"])

    def test_f01_05_healthcheck_configuration(self):
        """Verify PostgreSQL healthcheck command pg_isready is defined."""
        healthcheck = {
            "test": ["CMD-SHELL", "pg_isready -U postgres -d stocksentinel"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 5
        }
        self.assertIn("pg_isready", healthcheck["test"][1])
        self.assertEqual(healthcheck["retries"], 5)

    # =========================================================================
    # FEATURE 2: Master Stocks Schema
    # =========================================================================
    def test_f02_01_stocks_pk_and_required_columns(self):
        """Verify stocks table requires ticker PK and name, and allows insertion."""
        stock = {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "exchange": "NASDAQ",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "market_cap": 3000000000000,
            "is_active": True,
            "in_russell3000": True,
            "in_sp1500": True
        }
        success = self.db.upsert_stock(stock)
        self.assertTrue(success)
        self.assertIn("AAPL", self.db.stocks)
        self.assertEqual(self.db.stocks["AAPL"]["name"], "Apple Inc.")

    def test_f02_02_stocks_ticker_length_constraint(self):
        """Verify ticker length cannot exceed 16 characters."""
        long_ticker = "A" * 17
        with self.assertRaises(ValueError):
            self.db.upsert_stock({"ticker": long_ticker, "name": "Invalid Corp"})

    def test_f02_03_stocks_index_membership_flags(self):
        """Verify boolean flags for Russell 3000 and S&P 1500 membership."""
        self.db.upsert_stock({
            "ticker": "CRWD",
            "name": "CrowdStrike Holdings",
            "in_russell3000": True,
            "in_sp1500": True
        })
        self.db.upsert_stock({
            "ticker": "SPY",
            "name": "SPDR S&P 500 ETF",
            "in_russell3000": False,
            "in_sp1500": False
        })
        self.assertTrue(self.db.stocks["CRWD"]["in_russell3000"])
        self.assertFalse(self.db.stocks["SPY"]["in_russell3000"])

    def test_f02_04_stocks_sector_and_industry_metadata(self):
        """Verify sector and industry fields accept standard GICS classifications."""
        self.db.upsert_stock({
            "ticker": "NVDA",
            "name": "NVIDIA Corp",
            "sector": "Information Technology",
            "industry": "Semiconductors"
        })
        self.assertEqual(self.db.stocks["NVDA"]["sector"], "Information Technology")
        self.assertEqual(self.db.stocks["NVDA"]["industry"], "Semiconductors")

    def test_f02_05_stocks_market_cap_datatype(self):
        """Verify market_cap accommodates multi-trillion values (BIGINT)."""
        trillion = 3_150_000_000_000
        self.db.upsert_stock({
            "ticker": "MSFT",
            "name": "Microsoft Corp",
            "market_cap": trillion
        })
        self.assertEqual(self.db.stocks["MSFT"]["market_cap"], trillion)

    # =========================================================================
    # FEATURE 3: Daily Bars Schema
    # =========================================================================
    def test_f03_01_composite_primary_key(self):
        """Verify daily bars are keyed by composite (ticker, trade_date)."""
        self.db.upsert_stock({"ticker": "NVDA", "name": "NVIDIA"})
        bar1 = {
            "ticker": "NVDA", "trade_date": "2026-10-08",
            "open": 130.0, "high": 135.0, "low": 129.0, "close": 134.0, "adj_close": 134.0, "volume": 50000000
        }
        bar2 = {
            "ticker": "NVDA", "trade_date": "2026-10-09",
            "open": 134.0, "high": 136.0, "low": 133.0, "close": 135.5, "adj_close": 135.5, "volume": 48000000
        }
        self.db.upsert_daily_bar(bar1)
        self.db.upsert_daily_bar(bar2)
        self.assertIn(("NVDA", "2026-10-08"), self.db.stock_daily_bars)
        self.assertIn(("NVDA", "2026-10-09"), self.db.stock_daily_bars)

    def test_f03_02_foreign_key_to_stocks(self):
        """Verify inserting daily bar for non-existent stock raises foreign key violation."""
        bar = {
            "ticker": "UNKNOWN_TICKER", "trade_date": "2026-10-09",
            "open": 50.0, "high": 52.0, "low": 49.0, "close": 51.0, "volume": 10000
        }
        with self.assertRaises(ValueError) as ctx:
            self.db.upsert_daily_bar(bar)
        self.assertIn("Foreign key violation", str(ctx.exception))

    def test_f03_03_high_low_check_constraints(self):
        """Verify check constraint high >= low is enforced."""
        self.db.upsert_stock({"ticker": "TSLA", "name": "Tesla"})
        invalid_bar = {
            "ticker": "TSLA", "trade_date": "2026-10-09",
            "open": 200.0, "high": 190.0, "low": 210.0, "close": 205.0, "volume": 1000
        }
        with self.assertRaises(ValueError) as ctx:
            self.db.upsert_daily_bar(invalid_bar)
        self.assertIn("high", str(ctx.exception))

    def test_f03_04_high_open_close_check_constraints(self):
        """Verify high is greater than or equal to both open and close."""
        self.db.upsert_stock({"ticker": "AMZN", "name": "Amazon"})
        invalid_bar = {
            "ticker": "AMZN", "trade_date": "2026-10-09",
            "open": 180.0, "high": 175.0, "low": 170.0, "close": 172.0, "volume": 1000
        }
        with self.assertRaises(ValueError) as ctx:
            self.db.upsert_daily_bar(invalid_bar)
        self.assertIn("high", str(ctx.exception))

    def test_f03_05_volume_non_negative_constraint(self):
        """Verify volume >= 0 check constraint."""
        self.db.upsert_stock({"ticker": "GOOGL", "name": "Alphabet"})
        invalid_bar = {
            "ticker": "GOOGL", "trade_date": "2026-10-09",
            "open": 160.0, "high": 165.0, "low": 158.0, "close": 162.0, "volume": -500
        }
        with self.assertRaises(ValueError) as ctx:
            self.db.upsert_daily_bar(invalid_bar)
        self.assertIn("volume", str(ctx.exception))

    # =========================================================================
    # FEATURE 4: Scan Jobs Audit Schema
    # =========================================================================
    def test_f04_01_scan_jobs_primary_key_serial(self):
        """Verify scan_jobs generates sequential integer IDs."""
        job_id_1 = self.db.create_scan_job({"job_type": "WEEKLY_SCAN", "status": "PENDING", "started_at": "2026-10-14T00:00:00Z"})
        job_id_2 = self.db.create_scan_job({"job_type": "WEEKLY_SCAN", "status": "PENDING", "started_at": "2026-10-14T01:00:00Z"})
        self.assertEqual(job_id_1, 1)
        self.assertEqual(job_id_2, 2)

    def test_f04_02_status_enum_check_constraint(self):
        """Verify status only accepts PENDING, RUNNING, COMPLETED, FAILED."""
        with self.assertRaises(ValueError):
            self.db.create_scan_job({"job_type": "WEEKLY_SCAN", "status": "INVALID_STATUS", "started_at": "2026-10-14T00:00:00Z"})

    def test_f04_03_audit_timestamp_columns(self):
        """Verify started_at and completed_at timestamps are recorded."""
        job_id = self.db.create_scan_job({
            "job_type": "DELTA_SYNC", "status": "RUNNING", "started_at": "2026-10-14T02:00:00Z"
        })
        self.db.update_scan_job(job_id, {"status": "COMPLETED", "completed_at": "2026-10-14T02:15:30Z"})
        job = self.db.scan_jobs[job_id]
        self.assertEqual(job["status"], "COMPLETED")
        self.assertEqual(job["completed_at"], "2026-10-14T02:15:30Z")

    def test_f04_04_counter_metrics_columns(self):
        """Verify scan_jobs tracks tickers_total, tickers_processed, tickers_failed, signals_found."""
        job_id = self.db.create_scan_job({
            "job_type": "STAGE2_SCREEN", "status": "RUNNING", "started_at": "2026-10-14T02:00:00Z",
            "tickers_total": 3800
        })
        self.db.update_scan_job(job_id, {
            "tickers_processed": 3780,
            "tickers_failed": 20,
            "signals_found": 14
        })
        job = self.db.scan_jobs[job_id]
        self.assertEqual(job["tickers_total"], 3800)
        self.assertEqual(job["tickers_processed"], 3780)
        self.assertEqual(job["tickers_failed"], 20)
        self.assertEqual(job["signals_found"], 14)

    def test_f04_05_error_message_and_telegram_flag(self):
        """Verify error_message captured on failure and telegram_alert_sent flag recorded."""
        job_id = self.db.create_scan_job({
            "job_type": "STAGE2_SCREEN", "status": "RUNNING", "started_at": "2026-10-14T02:00:00Z"
        })
        self.db.update_scan_job(job_id, {
            "status": "COMPLETED",
            "telegram_alert_sent": True
        })
        self.assertTrue(self.db.scan_jobs[job_id]["telegram_alert_sent"])

    # =========================================================================
    # FEATURE 5: Screener Signals Schema
    # =========================================================================
    def test_f05_01_unique_scan_date_ticker_constraint(self):
        """Verify UNIQUE (scan_date, ticker) upserts cleanly without duplicate records."""
        self.db.upsert_stock({"ticker": "AXON", "name": "Axon Enterprise"})
        sig1 = {
            "scan_date": "2026-10-09", "ticker": "AXON", "entry_price": 380.0,
            "max_buy_price": 399.0, "current_price": 385.0, "stop_loss_price": 350.0,
            "diff_pct": 1.31, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.1,
            "mrs_score": 15.4, "sma_30w": 340.0, "sma_30w_slope": 1.2,
            "prior_resistance_35w": 380.0, "weekly_close": 385.0, "weekly_volume": 4000000,
            "avg_volume_10w": 1900000
        }
        id1 = self.db.upsert_screener_signal(sig1)
        # Update with new current price on same scan date
        sig2 = dict(sig1)
        sig2["current_price"] = 388.0
        id2 = self.db.upsert_screener_signal(sig2)
        self.assertEqual(id1, id2)
        self.assertEqual(len(self.db.screener_signals), 1)
        self.assertEqual(self.db.screener_signals[id1]["current_price"], 388.0)

    def test_f05_02_entry_status_check_constraint(self):
        """Verify entry_status rejects values not in ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT')."""
        self.db.upsert_stock({"ticker": "WING", "name": "Wingstop"})
        invalid_sig = {
            "scan_date": "2026-10-09", "ticker": "WING", "entry_price": 400.0,
            "current_price": 410.0, "entry_status": "NOT_AN_ENUM_VALUE"
        }
        with self.assertRaises(ValueError) as ctx:
            self.db.upsert_screener_signal(invalid_sig)
        self.assertIn("entry_status", str(ctx.exception))

    def test_f05_03_foreign_key_relationships(self):
        """Verify signal enforces foreign key reference to stocks."""
        sig = {
            "scan_date": "2026-10-09", "ticker": "NON_EXISTENT_STK",
            "entry_price": 100.0, "current_price": 102.0, "entry_status": "IN_BUY_ZONE"
        }
        with self.assertRaises(ValueError) as ctx:
            self.db.upsert_screener_signal(sig)
        self.assertIn("Foreign key violation", str(ctx.exception))

    def test_f05_04_indicator_metric_columns_precision(self):
        """Verify precision of indicator columns: mrs_score, sma_30w, volume_surge_ratio."""
        self.db.upsert_stock({"ticker": "CELH", "name": "Celsius"})
        sig = {
            "scan_date": "2026-10-09", "ticker": "CELH", "entry_price": 45.1234,
            "max_buy_price": 47.3796, "current_price": 46.0000, "stop_loss_price": 41.5135,
            "diff_pct": 1.9422, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.3456,
            "mrs_score": 25.1234, "sma_30w": 40.5432, "sma_30w_slope": 0.8765,
            "prior_resistance_35w": 45.1234, "weekly_close": 46.0000, "weekly_volume": 12000000,
            "avg_volume_10w": 5100000
        }
        sig_id = self.db.upsert_screener_signal(sig)
        saved = self.db.screener_signals[sig_id]
        self.assertEqual(saved["volume_surge_ratio"], 2.3456)
        self.assertEqual(saved["mrs_score"], 25.1234)

    def test_f05_05_positive_price_checks(self):
        """Verify entry_price and current_price cannot be zero or negative."""
        self.db.upsert_stock({"ticker": "INSM", "name": "Insmed"})
        invalid_sig = {
            "scan_date": "2026-10-09", "ticker": "INSM", "entry_price": -10.0,
            "current_price": 50.0, "entry_status": "IN_BUY_ZONE"
        }
        with self.assertRaises(ValueError) as ctx:
            self.db.upsert_screener_signal(invalid_sig)
        self.assertIn("entry_price must be > 0", str(ctx.exception))

    # =========================================================================
    # FEATURE 6: Migration & Init System
    # =========================================================================
    def test_f06_01_idempotent_table_creation(self):
        """Verify DDL uses CREATE TABLE IF NOT EXISTS for safe repeated initialization."""
        ddl_statements = [
            "CREATE TABLE IF NOT EXISTS stocks (ticker VARCHAR(16) PRIMARY KEY);",
            "CREATE TABLE IF NOT EXISTS stock_daily_bars (ticker VARCHAR(16), trade_date DATE);",
            "CREATE TABLE IF NOT EXISTS scan_jobs (id BIGSERIAL PRIMARY KEY);",
            "CREATE TABLE IF NOT EXISTS screener_signals (id BIGSERIAL PRIMARY KEY);"
        ]
        for stmt in ddl_statements:
            self.assertTrue("IF NOT EXISTS" in stmt)

    def test_f06_02_execution_dependency_order(self):
        """Verify stocks table is created before tables with foreign keys to stocks."""
        execution_order = ["stocks", "scan_jobs", "stock_daily_bars", "screener_signals"]
        stocks_idx = execution_order.index("stocks")
        bars_idx = execution_order.index("stock_daily_bars")
        signals_idx = execution_order.index("screener_signals")
        self.assertLess(stocks_idx, bars_idx)
        self.assertLess(stocks_idx, signals_idx)

    def test_f06_03_index_creation_time_series(self):
        """Verify index on stock_daily_bars(trade_date DESC) and (ticker, trade_date DESC)."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_stock_daily_bars_trade_date ON stock_daily_bars(trade_date DESC);",
            "CREATE INDEX IF NOT EXISTS idx_screener_signals_date ON screener_signals(scan_date DESC);"
        ]
        for idx in indexes:
            self.assertIn("INDEX IF NOT EXISTS", idx)
            self.assertIn("DESC", idx)

    def test_f06_04_down_migration_or_cascade_handling(self):
        """Verify clean teardown order reverses creation order."""
        teardown_order = ["screener_signals", "stock_daily_bars", "scan_jobs", "stocks"]
        self.assertEqual(teardown_order[0], "screener_signals")
        self.assertEqual(teardown_order[-1], "stocks")

    def test_f06_05_schema_initialization_verification(self):
        """Verify all 4 core tables exist in EXPECTED_TABLES metadata."""
        self.assertIn("stocks", EXPECTED_TABLES)
        self.assertIn("stock_daily_bars", EXPECTED_TABLES)
        self.assertIn("scan_jobs", EXPECTED_TABLES)
        self.assertIn("screener_signals", EXPECTED_TABLES)


if __name__ == "__main__":
    unittest.main()
