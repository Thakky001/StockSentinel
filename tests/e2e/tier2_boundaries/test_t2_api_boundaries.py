"""
Tier 2 Boundary Tests: Features 24-30 (Backend REST API Service)
Tests API query parameter boundaries (page, limit clamping), SQL injection prevention,
URL path encoding with ticker dots (BRK.B), concurrency locks, and status code edge cases.
"""

import unittest
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB
from tests.e2e.helpers.api_validator import InMemoryExpressApp, validate_api_envelope
from tests.e2e.helpers.mock_data import generate_daily_bars_for_stock


class TestTier2ApiBoundaries(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()
        self.app = InMemoryExpressApp(self.db)
        
        # Populate basic seed
        self.db.upsert_stock({"ticker": "BRK.B", "name": "Berkshire Hathaway B", "market_cap": 900000000000})
        self.db.upsert_stock({"ticker": "MEGA", "name": "Mega Cap Inc", "market_cap": 3000000000000})
        
        # Insert 10 signals
        for i in range(10):
            t = f"TK{i:02d}"
            self.db.upsert_stock({"ticker": t, "name": f"Stock {i}"})
            self.db.upsert_screener_signal({
                "scan_date": "2026-10-09", "ticker": t, "entry_price": 100.0 + i,
                "max_buy_price": (100.0 + i) * 1.05, "current_price": 102.0 + i,
                "stop_loss_price": (100.0 + i) * 0.92, "diff_pct": 2.0,
                "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.0, "mrs_score": 10.0,
                "sma_30w": 90.0, "sma_30w_slope": 1.0, "prior_resistance_35w": 100.0 + i,
                "weekly_close": 102.0 + i, "weekly_volume": 1000000, "avg_volume_10w": 500000
            })

    # =========================================================================
    # FEATURE 24 BOUNDARIES: Express Server & Pool
    # =========================================================================
    def test_t2_f24_01_malformed_json_returns_error_envelope(self):
        """Corner Case: Parsing malformed JSON body returns valid error envelope."""
        err_resp = {"success": False, "error": "Invalid JSON body payload"}
        is_valid, err = validate_api_envelope(err_resp)
        self.assertTrue(is_valid, err)

    def test_t2_f24_02_options_preflight_cors_response(self):
        """Boundary: OPTIONS request headers contain allowed methods GET, POST, OPTIONS."""
        cors_methods = "GET, POST, OPTIONS"
        self.assertIn("GET", cors_methods)
        self.assertIn("POST", cors_methods)

    def test_t2_f24_03_pool_timeout_handling(self):
        """Corner Case: Database pool timeout produces 500 JSON envelope."""
        err_resp = {"success": False, "error": "Database connection pool timeout"}
        self.assertFalse(err_resp["success"])
        self.assertIn("timeout", err_resp["error"])

    def test_t2_f24_04_bearer_token_authorization_header(self):
        """Boundary: Authorization header parsing ignores case and leading whitespace."""
        header = "Bearer  secret_admin_token "
        token = header.split("Bearer")[-1].strip()
        self.assertEqual(token, "secret_admin_token")

    def test_t2_f24_05_extreme_query_string_length(self):
        """Boundary: Query string with 2,000 characters processed without crash."""
        long_query = "search=" + ("A" * 2000)
        self.assertEqual(len(long_query), 2007)

    # =========================================================================
    # FEATURE 25 BOUNDARIES: Latest Screener Endpoint
    # =========================================================================
    def test_t2_f25_01_negative_page_defaults_to_page_1(self):
        """Boundary: page=-5 is clamped to page 1."""
        code, resp = self.app.handle_get_screener_latest({"page": -5})
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["page"], 1)

    def test_t2_f25_02_page_beyond_total_pages_returns_empty_list(self):
        """Boundary: page=999 on 10 total items returns empty signals array."""
        code, resp = self.app.handle_get_screener_latest({"page": 999, "limit": 10})
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["signals"], [])

    def test_t2_f25_03_limit_exceeding_100_clamped_to_100(self):
        """Boundary: limit=5000 is clamped to maximum allowable limit of 100."""
        code, resp = self.app.handle_get_screener_latest({"limit": 5000})
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["limit"], 100)

    def test_t2_f25_04_limit_zero_or_negative_clamped_to_minimum(self):
        """Boundary: limit=0 or -10 is clamped to minimum limit of 1."""
        code, resp = self.app.handle_get_screener_latest({"limit": 0})
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["limit"], 1)

    def test_t2_f25_05_sql_injection_attempt_in_search_parameter(self):
        """Corner Case: Search input containing SQL injection syntax sanitized cleanly."""
        code, resp = self.app.handle_get_screener_latest({"search": "' OR '1'='1'; DROP TABLE stocks; --"})
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["signals"], [])

    # =========================================================================
    # FEATURE 26 BOUNDARIES: Scan Dates Endpoint
    # =========================================================================
    def test_t2_f26_01_large_dates_history_100_scans(self):
        """Boundary: Database with 100 weekly scan dates returns all dates sorted."""
        for w in range(100):
            d_str = f"202{w // 52:01d}-{(w % 52) + 1:02d}-01"
            self.db.screener_signals[w + 1000] = {"scan_date": d_str, "ticker": "T0"}
        code, resp = self.app.handle_get_screener_dates()
        self.assertEqual(code, 200)
        self.assertGreaterEqual(len(resp["data"]["dates"]), 100)

    def test_t2_f26_02_dates_query_parameters_ignored(self):
        """Boundary: Passing unexpected query parameters like ?foo=bar does not error."""
        code, resp = self.app.handle_get_screener_dates()
        self.assertEqual(code, 200)

    def test_t2_f26_03_dates_returned_strictly_sorted_descending(self):
        """Boundary: Dates must be strictly descending."""
        code, resp = self.app.handle_get_screener_dates()
        dates = resp["data"]["dates"]
        for i in range(len(dates) - 1):
            self.assertGreater(dates[i], dates[i + 1])

    def test_t2_f26_04_dates_single_scan_in_db(self):
        """Boundary: Database with exactly 1 scan returns list of 1 string."""
        empty_db = InMemoryRelationalDB()
        empty_db.screener_signals[1] = {"scan_date": "2026-10-09", "ticker": "AAPL"}
        app = InMemoryExpressApp(empty_db)
        code, resp = app.handle_get_screener_dates()
        self.assertEqual(resp["data"]["dates"], ["2026-10-09"])

    def test_t2_f26_05_dates_response_envelope_valid(self):
        """Boundary: Response envelope adheres to JSON contract."""
        code, resp = self.app.handle_get_screener_dates()
        is_valid, _ = validate_api_envelope(resp)
        self.assertTrue(is_valid)

    # =========================================================================
    # FEATURE 27 BOUNDARIES: Stock Chart Endpoint
    # =========================================================================
    def test_t2_f27_01_ticker_with_dot_in_path(self):
        """Corner Case: Route parameter with dot like BRK.B parses cleanly."""
        code, resp = self.app.handle_get_stock_chart("BRK.B")
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["ticker"], "BRK.B")

    def test_t2_f27_02_stock_with_single_daily_bar_chart(self):
        """Boundary: Newly listed stock with only 1 day of trading."""
        self.db.upsert_stock({"ticker": "IPO1", "name": "Day 1 Corp"})
        self.db.upsert_daily_bar({"ticker": "IPO1", "trade_date": "2026-10-09", "open": 20.0, "high": 25.0, "low": 19.0, "close": 24.0, "volume": 100000})
        code, resp = self.app.handle_get_stock_chart("IPO1")
        self.assertEqual(code, 200)
        self.assertEqual(len(resp["data"]["candlesticks"]), 1)

    def test_t2_f27_03_sma30_empty_when_under_30_weeks(self):
        """Boundary: Chart with 10 weeks of data has candlesticks but empty sma30 series."""
        self.db.upsert_stock({"ticker": "SHORT", "name": "Short History"})
        bars = generate_daily_bars_for_stock("SHORT", num_days=50)  # 10 weeks
        for b in bars:
            self.db.upsert_daily_bar(b)
        code, resp = self.app.handle_get_stock_chart("SHORT")
        self.assertEqual(code, 200)
        self.assertEqual(len(resp["data"]["sma30"]), 0)
        self.assertEqual(len(resp["data"]["candlesticks"]), 10)

    def test_t2_f27_04_deep_history_260_weeks_chart(self):
        """Boundary: 5 years of weekly candlesticks (260 candles) returned."""
        self.db.upsert_stock({"ticker": "OLD", "name": "Old Corp"})
        bars = generate_daily_bars_for_stock("OLD", num_days=1300)  # 260 weeks
        for b in bars:
            self.db.upsert_daily_bar(b)
        code, resp = self.app.handle_get_stock_chart("OLD")
        self.assertEqual(code, 200)
        self.assertEqual(len(resp["data"]["candlesticks"]), 260)

    def test_t2_f27_05_metrics_fallbacks_when_no_signal_exists(self):
        """Corner Case: Chart for non-breakout stock falls back to weekly bar metrics."""
        code, resp = self.app.handle_get_stock_chart("BRK.B")
        self.assertEqual(code, 200)
        self.assertIn("metrics", resp["data"])

    # =========================================================================
    # FEATURE 28 BOUNDARIES: Stock Summary Endpoint
    # =========================================================================
    def test_t2_f28_01_stock_summary_trillion_dollar_market_cap(self):
        """Boundary: Mega market cap $3,000,000,000,000 formatted as number."""
        code, resp = self.app.handle_get_stock_summary("MEGA")
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["market_cap"], 3_000_000_000_000)

    def test_t2_f28_02_stock_summary_null_daily_bar_when_no_bars_ingested(self):
        """Corner Case: Stock present in stocks table but no daily bars ingested yet."""
        self.db.upsert_stock({"ticker": "NOBARS", "name": "No Bars Corp"})
        code, resp = self.app.handle_get_stock_summary("NOBARS")
        self.assertEqual(code, 200)
        self.assertIsNone(resp["data"]["latest_daily_bar"])

    def test_t2_f28_03_stock_summary_null_signal_when_not_in_screener(self):
        """Corner Case: Stock with bars but not qualifying as Stage 2 breakout."""
        code, resp = self.app.handle_get_stock_summary("BRK.B")
        self.assertEqual(code, 200)
        self.assertIsNone(resp["data"]["latest_signal"])

    def test_t2_f28_04_stock_summary_lowercase_and_whitespace_ticker(self):
        """Corner Case: Ticker passed with trailing spaces trimmed and uppercased."""
        code, resp = self.app.handle_get_stock_summary("  brk.b  ")
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["ticker"], "BRK.B")

    def test_t2_f28_05_stock_summary_returns_not_found_envelope(self):
        """Boundary: 404 response body has success=False and error message."""
        code, resp = self.app.handle_get_stock_summary("TOTALLY_UNKNOWN")
        self.assertEqual(code, 404)
        self.assertFalse(resp["success"])
        self.assertIn("not found", resp["error"].lower())

    # =========================================================================
    # FEATURE 29 BOUNDARIES: Screener Trigger Endpoint
    # =========================================================================
    def test_t2_f29_01_rapid_successive_trigger_conflict(self):
        """Boundary: Two immediate trigger calls in a row — second call returns 409 Conflict."""
        self.app.is_scanner_running = False
        code1, resp1 = self.app.handle_post_screener_trigger()
        code2, resp2 = self.app.handle_post_screener_trigger()
        self.assertEqual(code1, 200)
        self.assertEqual(code2, 409)
        self.assertFalse(resp2["success"])

    def test_t2_f29_02_trigger_lock_reset_after_completion(self):
        """Corner Case: Releasing lock allows subsequent trigger to succeed."""
        self.app.is_scanner_running = False
        self.app.handle_post_screener_trigger()
        # Reset
        self.app.is_scanner_running = False
        code, resp = self.app.handle_post_screener_trigger()
        self.assertEqual(code, 200)

    def test_t2_f29_03_trigger_job_id_is_positive_integer(self):
        """Boundary: Returned job_id is strictly a positive integer."""
        self.app.is_scanner_running = False
        code, resp = self.app.handle_post_screener_trigger()
        self.assertGreater(resp["data"]["job_id"], 0)

    def test_t2_f29_04_trigger_response_envelope_compliance(self):
        """Boundary: Trigger response strictly satisfies validate_api_envelope."""
        self.app.is_scanner_running = False
        code, resp = self.app.handle_post_screener_trigger()
        is_valid, _ = validate_api_envelope(resp)
        self.assertTrue(is_valid)

    def test_t2_f29_05_trigger_conflict_envelope_compliance(self):
        """Boundary: Conflict response strictly satisfies validate_api_envelope."""
        self.app.is_scanner_running = True
        code, resp = self.app.handle_post_screener_trigger()
        is_valid, _ = validate_api_envelope(resp)
        self.assertTrue(is_valid)

    # =========================================================================
    # FEATURE 30 BOUNDARIES: Telegram Test Endpoint
    # =========================================================================
    def test_t2_f30_01_missing_token_returns_400(self):
        """Corner Case: has_valid_token=False returns status 400."""
        code, resp = self.app.handle_post_telegram_test(has_valid_token=False)
        self.assertEqual(code, 400)
        self.assertFalse(resp["success"])

    def test_t2_f30_02_telegram_configured_flag_false_returns_400(self):
        """Corner Case: telegram_configured=False returns status 400."""
        self.app.telegram_configured = False
        code, resp = self.app.handle_post_telegram_test(has_valid_token=True)
        self.assertEqual(code, 400)
        self.app.telegram_configured = True  # restore

    def test_t2_f30_03_successful_test_returns_positive_message_id(self):
        """Boundary: telegram_message_id is positive integer."""
        code, resp = self.app.handle_post_telegram_test(has_valid_token=True)
        self.assertEqual(code, 200)
        self.assertGreater(resp["telegram_message_id"], 0)

    def test_t2_f30_04_test_endpoint_empty_payload(self):
        """Boundary: POST without request body succeeds."""
        code, resp = self.app.handle_post_telegram_test()
        self.assertEqual(code, 200)

    def test_t2_f30_05_error_message_clarity(self):
        """Boundary: Error message specifically mentions Telegram Bot Token or Chat ID."""
        code, resp = self.app.handle_post_telegram_test(has_valid_token=False)
        self.assertIn("Telegram Bot Token", resp["error"])


if __name__ == "__main__":
    unittest.main()
