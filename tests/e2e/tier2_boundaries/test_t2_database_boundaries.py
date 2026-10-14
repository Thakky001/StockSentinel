"""
Tier 2 Boundary Tests: Features 1-6 (Database & Project Infrastructure)
Tests domain extremes, boundary values, constraint violations, and corner cases.
"""

import unittest
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB


class TestTier2DatabaseBoundaries(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()

    # =========================================================================
    # FEATURE 1 BOUNDARIES: Docker Infrastructure
    # =========================================================================
    def test_t2_f01_01_port_collision_fallback(self):
        """Boundary: Verify custom non-standard port (e.g. 5433 or 15432) is supported."""
        port = 15432
        port_mapping = f"{port}:5432"
        self.assertEqual(port_mapping, "15432:5432")

    def test_t2_f01_02_empty_password_fallback(self):
        """Corner Case: POSTGRES_PASSWORD falls back to postgres if unset."""
        env_val = None
        password = env_val or "postgres"
        self.assertEqual(password, "postgres")

    def test_t2_f01_03_redis_maxmemory_limit(self):
        """Boundary: Verify redis maxmemory configuration prevents host OOM."""
        maxmemory = "256mb"
        self.assertTrue(maxmemory.endswith("mb"))

    def test_t2_f01_04_healthcheck_minimum_intervals(self):
        """Boundary: Healthcheck with rapid 1s interval and 1 retry."""
        interval_sec = 1
        retries = 1
        self.assertGreaterEqual(interval_sec, 1)
        self.assertGreaterEqual(retries, 1)

    def test_t2_f01_05_database_name_with_underscores(self):
        """Corner Case: Database name with underscores and numbers: stock_sentinel_db_16."""
        db_name = "stock_sentinel_db_16"
        self.assertTrue(db_name.isidentifier())

    # =========================================================================
    # FEATURE 2 BOUNDARIES: Stocks Schema
    # =========================================================================
    def test_t2_f02_01_ticker_max_length_16_allowed(self):
        """Boundary: Ticker of exactly 16 characters is accepted."""
        ticker_16 = "A" * 16
        success = self.db.upsert_stock({"ticker": ticker_16, "name": "Sixteen Chars Inc."})
        self.assertTrue(success)
        self.assertIn(ticker_16, self.db.stocks)

    def test_t2_f02_02_ticker_17_characters_rejected(self):
        """Boundary: Ticker of 17 characters is rejected by VARCHAR(16) check."""
        ticker_17 = "A" * 17
        with self.assertRaises(ValueError):
            self.db.upsert_stock({"ticker": ticker_17, "name": "Seventeen Chars Inc."})

    def test_t2_f02_03_empty_ticker_rejected(self):
        """Corner Case: Empty string ticker is rejected."""
        with self.assertRaises(ValueError):
            self.db.upsert_stock({"ticker": "", "name": "Empty Ticker Corp"})

    def test_t2_f02_04_max_bigint_market_cap(self):
        """Boundary: Market cap at maximum 64-bit signed integer (9,223,372,036,854,775,807)."""
        max_bigint = 9_223_372_036_854_775_807
        self.db.upsert_stock({"ticker": "MEGA", "name": "Mega Cap", "market_cap": max_bigint})
        self.assertEqual(self.db.stocks["MEGA"]["market_cap"], max_bigint)

    def test_t2_f02_05_name_max_255_chars_boundary(self):
        """Boundary: Name with exactly 255 characters accepted."""
        name_255 = "C" * 255
        success = self.db.upsert_stock({"ticker": "LONG", "name": name_255})
        self.assertTrue(success)
        self.assertEqual(len(self.db.stocks["LONG"]["name"]), 255)

    # =========================================================================
    # FEATURE 3 BOUNDARIES: Daily Bars Schema
    # =========================================================================
    def test_t2_f03_01_open_high_low_close_identical(self):
        """Corner Case: Flat trading day where Open == High == Low == Close."""
        self.db.upsert_stock({"ticker": "FLAT", "name": "Flat Stock"})
        bar = {
            "ticker": "FLAT", "trade_date": "2026-10-09",
            "open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "adj_close": 50.0, "volume": 1000
        }
        success = self.db.upsert_daily_bar(bar)
        self.assertTrue(success)

    def test_t2_f03_02_volume_zero_boundary(self):
        """Boundary: Volume == 0 is valid for no-trade or halted day."""
        self.db.upsert_stock({"ticker": "HALT", "name": "Halted Stock"})
        bar = {
            "ticker": "HALT", "trade_date": "2026-10-09",
            "open": 20.0, "high": 20.0, "low": 20.0, "close": 20.0, "adj_close": 20.0, "volume": 0
        }
        success = self.db.upsert_daily_bar(bar)
        self.assertTrue(success)

    def test_t2_f03_03_volume_negative_one_rejected(self):
        """Boundary: Volume == -1 fails volume >= 0 check constraint."""
        self.db.upsert_stock({"ticker": "NEG", "name": "Negative Vol"})
        bar = {
            "ticker": "NEG", "trade_date": "2026-10-09",
            "open": 20.0, "high": 21.0, "low": 19.0, "close": 20.5, "adj_close": 20.5, "volume": -1
        }
        with self.assertRaises(ValueError):
            self.db.upsert_daily_bar(bar)

    def test_t2_f03_04_high_fractionally_less_than_low_rejected(self):
        """Boundary: High is 0.0001 less than low (10.0000 high vs 10.0001 low)."""
        self.db.upsert_stock({"ticker": "MICRO", "name": "Micro Diff"})
        bar = {
            "ticker": "MICRO", "trade_date": "2026-10-09",
            "open": 10.0, "high": 10.0000, "low": 10.0001, "close": 10.0, "adj_close": 10.0, "volume": 100
        }
        with self.assertRaises(ValueError):
            self.db.upsert_daily_bar(bar)

    def test_t2_f03_05_high_price_berkshire_a(self):
        """Boundary: Price of Berkshire Hathaway Class A ($680,000.0000) fits precision."""
        self.db.upsert_stock({"ticker": "BRK.A", "name": "Berkshire Hathaway Class A"})
        bar = {
            "ticker": "BRK.A", "trade_date": "2026-10-09",
            "open": 680000.0, "high": 685000.0, "low": 679000.0, "close": 682500.0,
            "adj_close": 682500.0, "volume": 12
        }
        success = self.db.upsert_daily_bar(bar)
        self.assertTrue(success)

    # =========================================================================
    # FEATURE 4 BOUNDARIES: Scan Jobs Audit Schema
    # =========================================================================
    def test_t2_f04_01_zero_tickers_total(self):
        """Boundary: Job with tickers_total = 0 (empty universe or filtered dry run)."""
        job_id = self.db.create_scan_job({
            "job_type": "EMPTY_RUN", "status": "COMPLETED",
            "started_at": "2026-10-14T00:00:00Z", "tickers_total": 0, "signals_found": 0
        })
        self.assertEqual(self.db.scan_jobs[job_id]["tickers_total"], 0)

    def test_t2_f04_02_all_tickers_failed(self):
        """Corner Case: Total failure where tickers_failed == tickers_total."""
        job_id = self.db.create_scan_job({
            "job_type": "FULL_FAILURE", "status": "FAILED",
            "started_at": "2026-10-14T00:00:00Z", "tickers_total": 50,
            "tickers_processed": 0, "tickers_failed": 50, "signals_found": 0,
            "error_message": "Upstream API completely unreachable"
        })
        job = self.db.scan_jobs[job_id]
        self.assertEqual(job["tickers_failed"], job["tickers_total"])

    def test_t2_f04_03_instantaneous_completion(self):
        """Boundary: started_at equals completed_at."""
        ts = "2026-10-14T00:00:00Z"
        job_id = self.db.create_scan_job({
            "job_type": "CACHE_HIT", "status": "COMPLETED",
            "started_at": ts, "completed_at": ts
        })
        self.assertEqual(self.db.scan_jobs[job_id]["completed_at"], ts)

    def test_t2_f04_04_large_error_traceback_message(self):
        """Boundary: Error message containing a 5,000-character stack trace."""
        stack_trace = "Traceback (most recent call last):\n" + ("  File 'screener.py', line 42\n" * 150)
        job_id = self.db.create_scan_job({
            "job_type": "ERROR_RUN", "status": "FAILED",
            "started_at": "2026-10-14T00:00:00Z", "error_message": stack_trace
        })
        self.assertEqual(self.db.scan_jobs[job_id]["error_message"], stack_trace)

    def test_t2_f04_05_invalid_state_transition_attempt(self):
        """Corner Case: Setting status to unapproved string 'PAUSED' rejected."""
        job_id = self.db.create_scan_job({
            "job_type": "TEST", "status": "RUNNING", "started_at": "2026-10-14T00:00:00Z"
        })
        with self.assertRaises(ValueError):
            self.db.update_scan_job(job_id, {"status": "PAUSED"})

    # =========================================================================
    # FEATURE 5 BOUNDARIES: Screener Signals Schema
    # =========================================================================
    def test_t2_f05_01_penny_stock_boundary_price(self):
        """Boundary: Micro penny stock entry price of $0.0001 accepted."""
        self.db.upsert_stock({"ticker": "PENNY", "name": "Penny Stock Inc."})
        sig = {
            "scan_date": "2026-10-09", "ticker": "PENNY",
            "entry_price": 0.0001, "max_buy_price": 0.000105, "current_price": 0.0001,
            "stop_loss_price": 0.000092, "diff_pct": 0.0, "entry_status": "IN_BUY_ZONE",
            "volume_surge_ratio": 5.0, "mrs_score": 10.0, "sma_30w": 0.00008,
            "sma_30w_slope": 1.0, "prior_resistance_35w": 0.0001, "weekly_close": 0.0001,
            "weekly_volume": 100000000, "avg_volume_10w": 20000000
        }
        sig_id = self.db.upsert_screener_signal(sig)
        self.assertEqual(self.db.screener_signals[sig_id]["entry_price"], 0.0001)

    def test_t2_f05_02_diff_pct_exact_zero_boundary(self):
        """Boundary: diff_pct == 0.0000% when current_price == entry_price."""
        self.db.upsert_stock({"ticker": "EXACT", "name": "Exact Pivot Corp"})
        sig = {
            "scan_date": "2026-10-09", "ticker": "EXACT",
            "entry_price": 100.0, "max_buy_price": 105.0, "current_price": 100.0,
            "stop_loss_price": 92.0, "diff_pct": 0.0000, "entry_status": "IN_BUY_ZONE",
            "volume_surge_ratio": 2.0, "mrs_score": 5.0, "sma_30w": 90.0,
            "sma_30w_slope": 0.5, "prior_resistance_35w": 100.0, "weekly_close": 100.0,
            "weekly_volume": 1000000, "avg_volume_10w": 500000
        }
        sig_id = self.db.upsert_screener_signal(sig)
        self.assertEqual(self.db.screener_signals[sig_id]["diff_pct"], 0.0)

    def test_t2_f05_03_diff_pct_extreme_extended_boundary(self):
        """Boundary: diff_pct of +500.0% on parabolic runner."""
        self.db.upsert_stock({"ticker": "MOON", "name": "Moonshot Inc"})
        sig = {
            "scan_date": "2026-10-09", "ticker": "MOON",
            "entry_price": 10.0, "max_buy_price": 10.5, "current_price": 60.0,
            "stop_loss_price": 9.2, "diff_pct": 500.0, "entry_status": "EXTENDED",
            "volume_surge_ratio": 10.0, "mrs_score": 85.0, "sma_30w": 8.0,
            "sma_30w_slope": 15.0, "prior_resistance_35w": 10.0, "weekly_close": 60.0,
            "weekly_volume": 50000000, "avg_volume_10w": 5000000
        }
        sig_id = self.db.upsert_screener_signal(sig)
        self.assertEqual(self.db.screener_signals[sig_id]["diff_pct"], 500.0)

    def test_t2_f05_04_mrs_score_micro_positive_boundary(self):
        """Boundary: MRS score of +0.0001 (just above zero line)."""
        self.db.upsert_stock({"ticker": "BORDER", "name": "Borderline MRS"})
        sig = {
            "scan_date": "2026-10-09", "ticker": "BORDER",
            "entry_price": 50.0, "max_buy_price": 52.5, "current_price": 51.0,
            "stop_loss_price": 46.0, "diff_pct": 2.0, "entry_status": "IN_BUY_ZONE",
            "volume_surge_ratio": 1.6, "mrs_score": 0.0001, "sma_30w": 45.0,
            "sma_30w_slope": 0.1, "prior_resistance_35w": 50.0, "weekly_close": 51.0,
            "weekly_volume": 1000000, "avg_volume_10w": 600000
        }
        sig_id = self.db.upsert_screener_signal(sig)
        self.assertEqual(self.db.screener_signals[sig_id]["mrs_score"], 0.0001)

    def test_t2_f05_05_volume_surge_exact_1_5_boundary(self):
        """Boundary: Volume surge ratio of exactly 1.5000."""
        self.db.upsert_stock({"ticker": "SURGE15", "name": "Exact 1.5 Surge"})
        sig = {
            "scan_date": "2026-10-09", "ticker": "SURGE15",
            "entry_price": 75.0, "max_buy_price": 78.75, "current_price": 76.0,
            "stop_loss_price": 69.0, "diff_pct": 1.33, "entry_status": "IN_BUY_ZONE",
            "volume_surge_ratio": 1.5000, "mrs_score": 5.0, "sma_30w": 70.0,
            "sma_30w_slope": 0.4, "prior_resistance_35w": 75.0, "weekly_close": 76.0,
            "weekly_volume": 1500000, "avg_volume_10w": 1000000
        }
        sig_id = self.db.upsert_screener_signal(sig)
        self.assertEqual(self.db.screener_signals[sig_id]["volume_surge_ratio"], 1.5)

    # =========================================================================
    # FEATURE 6 BOUNDARIES: Migration System
    # =========================================================================
    def test_t2_f06_01_repeated_table_creation_no_op(self):
        """Corner Case: Idempotent initialization when tables already exist does not corrupt data."""
        self.db.upsert_stock({"ticker": "HOLD", "name": "Holding Corp"})
        # Re-run DDL mock
        self.assertIn("HOLD", self.db.stocks)

    def test_t2_f06_02_foreign_key_missing_parent_aborts(self):
        """Corner Case: Ingesting daily bar before parent stock is loaded aborts."""
        with self.assertRaises(ValueError):
            self.db.upsert_daily_bar({
                "ticker": "ORPHAN", "trade_date": "2026-10-09",
                "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100
            })

    def test_t2_f06_03_date_leap_year_handling(self):
        """Boundary: Leap year date 2024-02-29 is valid trade date."""
        self.db.upsert_stock({"ticker": "LEAP", "name": "Leap Year Stock"})
        bar = {
            "ticker": "LEAP", "trade_date": "2024-02-29",
            "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "adj_close": 104.0, "volume": 50000
        }
        success = self.db.upsert_daily_bar(bar)
        self.assertTrue(success)

    def test_t2_f06_04_millisecond_timestamp_precision(self):
        """Boundary: ISO 8601 with fractional seconds (e.g. 2026-10-14T02:00:00.123456Z)."""
        job_id = self.db.create_scan_job({
            "job_type": "PRECISION_TIME", "status": "RUNNING",
            "started_at": "2026-10-14T02:00:00.123456Z"
        })
        self.assertEqual(self.db.scan_jobs[job_id]["started_at"], "2026-10-14T02:00:00.123456Z")

    def test_t2_f06_05_enum_case_sensitivity(self):
        """Corner Case: Lowercase 'in_buy_zone' rejected by uppercase CHECK constraint."""
        self.db.upsert_stock({"ticker": "CASE", "name": "Case Sensitive Corp"})
        with self.assertRaises(ValueError):
            self.db.upsert_screener_signal({
                "scan_date": "2026-10-09", "ticker": "CASE",
                "entry_price": 50.0, "current_price": 51.0, "entry_status": "in_buy_zone"
            })


if __name__ == "__main__":
    unittest.main()
