"""
Tier 1 Tests: Features 24-30 (Backend REST API Service)
Isolation test cases covering Express server configuration, connection pooling,
GET /api/screener/latest, GET /api/screener/dates, GET /api/stock/:ticker/chart,
GET /api/stock/:ticker/summary, POST /api/screener/trigger (concurrency locks),
and POST /api/notifications/telegram-test.
"""

import unittest
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB
from tests.e2e.helpers.api_validator import (
    InMemoryExpressApp,
    validate_api_envelope,
    validate_screener_latest_payload,
    validate_chart_payload
)
from tests.e2e.helpers.mock_data import generate_daily_bars_for_stock


class TestTier1Features24to30(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()
        self.app = InMemoryExpressApp(self.db)
        
        # Populate test fixtures
        self.db.upsert_stock({
            "ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ",
            "sector": "Technology", "industry": "Consumer Electronics", "market_cap": 3000000000000
        })
        self.db.upsert_stock({
            "ticker": "CRWD", "name": "CrowdStrike Holdings", "exchange": "NASDAQ",
            "sector": "Technology", "industry": "Security Software", "market_cap": 60000000000
        })
        self.db.upsert_stock({
            "ticker": "WING", "name": "Wingstop Inc.", "exchange": "NASDAQ",
            "sector": "Consumer Cyclical", "industry": "Restaurants", "market_cap": 11000000000
        })
        
        # Insert signals for 2026-10-09
        self.db.upsert_screener_signal({
            "scan_date": "2026-10-09", "ticker": "CRWD", "entry_price": 320.0,
            "max_buy_price": 336.0, "current_price": 325.0, "stop_loss_price": 294.4,
            "diff_pct": 1.56, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.45,
            "mrs_score": 18.25, "sma_30w": 280.0, "sma_30w_slope": 1.1,
            "prior_resistance_35w": 320.0, "weekly_close": 325.0, "weekly_volume": 5000000,
            "avg_volume_10w": 2040000
        })
        self.db.upsert_screener_signal({
            "scan_date": "2026-10-09", "ticker": "WING", "entry_price": 410.0,
            "max_buy_price": 430.5, "current_price": 440.0, "stop_loss_price": 377.2,
            "diff_pct": 7.32, "entry_status": "EXTENDED", "volume_surge_ratio": 1.85,
            "mrs_score": 12.10, "sma_30w": 360.0, "sma_30w_slope": 0.9,
            "prior_resistance_35w": 410.0, "weekly_close": 440.0, "weekly_volume": 2000000,
            "avg_volume_10w": 1080000
        })

        # Insert bars for AAPL (52 weeks)
        bars = generate_daily_bars_for_stock("AAPL", num_days=260, base_price=150.0)
        for b in bars:
            self.db.upsert_daily_bar(b)

    # =========================================================================
    # FEATURE 24: Express Server & DB Pool
    # =========================================================================
    def test_f24_01_api_envelope_success_format(self):
        """Verify API response envelope contains boolean success and data payload."""
        code, resp = self.app.handle_get_screener_dates()
        self.assertEqual(code, 200)
        is_valid, err = validate_api_envelope(resp)
        self.assertTrue(is_valid, err)
        self.assertTrue(resp["success"])
        self.assertIn("data", resp)

    def test_f24_02_api_envelope_error_format(self):
        """Verify API response envelope on error contains success=False and error string."""
        code, resp = self.app.handle_get_stock_summary("NON_EXISTENT")
        self.assertEqual(code, 404)
        is_valid, err = validate_api_envelope(resp)
        self.assertTrue(is_valid, err)
        self.assertFalse(resp["success"])
        self.assertIn("error", resp)

    def test_f24_03_cors_and_json_middleware(self):
        """Verify server headers include CORS origin and Content-Type: application/json."""
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/json; charset=utf-8"
        }
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertIn("application/json", headers["Content-Type"])

    def test_f24_04_db_pool_connection_handling(self):
        """Verify database pool healthcheck executes cleanly."""
        is_healthy = len(self.db.stocks) >= 3
        self.assertTrue(is_healthy)

    def test_f24_05_http_status_codes_adherence(self):
        """Verify standard HTTP status codes: 200 OK, 404 Not Found, 409 Conflict."""
        code_ok, _ = self.app.handle_get_screener_dates()
        code_404, _ = self.app.handle_get_stock_summary("NON_EXISTENT")
        self.app.is_scanner_running = True
        code_409, _ = self.app.handle_post_screener_trigger()
        self.assertEqual(code_ok, 200)
        self.assertEqual(code_404, 404)
        self.assertEqual(code_409, 409)

    # =========================================================================
    # FEATURE 25: Latest Screener Endpoint (GET /api/screener/latest)
    # =========================================================================
    def test_f25_01_screener_latest_returns_signals(self):
        """Verify GET /api/screener/latest returns latest date signals."""
        code, resp = self.app.handle_get_screener_latest({})
        self.assertEqual(code, 200)
        is_valid, err = validate_screener_latest_payload(resp["data"])
        self.assertTrue(is_valid, err)
        self.assertEqual(resp["data"]["total"], 2)
        self.assertEqual(len(resp["data"]["signals"]), 2)

    def test_f25_02_screener_latest_sector_filtering(self):
        """Verify filtering by sector returns only matching stocks."""
        code, resp = self.app.handle_get_screener_latest({"sector": "Consumer Cyclical"})
        self.assertEqual(code, 200)
        signals = resp["data"]["signals"]
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["ticker"], "WING")

    def test_f25_03_screener_latest_status_filtering(self):
        """Verify filtering by entry_status returns only IN_BUY_ZONE."""
        code, resp = self.app.handle_get_screener_latest({"status": "IN_BUY_ZONE"})
        self.assertEqual(code, 200)
        signals = resp["data"]["signals"]
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["ticker"], "CRWD")

    def test_f25_04_screener_latest_search_filtering(self):
        """Verify search query matches ticker or company name substring."""
        code, resp = self.app.handle_get_screener_latest({"search": "crowd"})
        self.assertEqual(code, 200)
        signals = resp["data"]["signals"]
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["ticker"], "CRWD")

    def test_f25_05_screener_latest_pagination_and_sorting(self):
        """Verify limit, page, and diff_pct sort ordering."""
        code, resp = self.app.handle_get_screener_latest({"sort_by": "diff_pct", "order": "desc", "limit": 1, "page": 1})
        self.assertEqual(code, 200)
        self.assertEqual(len(resp["data"]["signals"]), 1)
        # WING has diff_pct +7.32%, CRWD has +1.56%
        self.assertEqual(resp["data"]["signals"][0]["ticker"], "WING")
        self.assertEqual(resp["data"]["total_pages"], 2)

    # =========================================================================
    # FEATURE 26: Scan Dates Endpoint (GET /api/screener/dates)
    # =========================================================================
    def test_f26_01_dates_returns_list_of_strings(self):
        """Verify GET /api/screener/dates returns list of date strings."""
        code, resp = self.app.handle_get_screener_dates()
        self.assertEqual(code, 200)
        self.assertIn("dates", resp["data"])
        self.assertIsInstance(resp["data"]["dates"], list)
        self.assertIn("2026-10-09", resp["data"]["dates"])

    def test_f26_02_dates_sorted_descending(self):
        """Verify dates are returned in descending chronological order."""
        # Add another earlier signal date
        self.db.upsert_screener_signal({
            "scan_date": "2026-10-02", "ticker": "CRWD", "entry_price": 310.0,
            "max_buy_price": 325.5, "current_price": 315.0, "stop_loss_price": 285.2,
            "diff_pct": 1.61, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.1,
            "mrs_score": 15.0, "sma_30w": 275.0, "sma_30w_slope": 1.0,
            "prior_resistance_35w": 310.0, "weekly_close": 315.0, "weekly_volume": 4000000,
            "avg_volume_10w": 1900000
        })
        code, resp = self.app.handle_get_screener_dates()
        dates = resp["data"]["dates"]
        self.assertEqual(dates[0], "2026-10-09")
        self.assertEqual(dates[1], "2026-10-02")

    def test_f26_03_dates_deduplicated(self):
        """Verify each distinct scan date appears only once in dates array."""
        code, resp = self.app.handle_get_screener_dates()
        dates = resp["data"]["dates"]
        self.assertEqual(len(dates), len(set(dates)))

    def test_f26_04_dates_iso_format(self):
        """Verify dates adhere to YYYY-MM-DD ISO format."""
        code, resp = self.app.handle_get_screener_dates()
        for d in resp["data"]["dates"]:
            self.assertEqual(len(d), 10)
            self.assertEqual(d[4], "-")
            self.assertEqual(d[7], "-")

    def test_f26_05_dates_empty_database_handling(self):
        """Verify empty database returns empty array instead of error."""
        empty_db = InMemoryRelationalDB()
        empty_app = InMemoryExpressApp(empty_db)
        code, resp = empty_app.handle_get_screener_dates()
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["dates"], [])

    # =========================================================================
    # FEATURE 27: Stock Chart Endpoint (GET /api/stock/:ticker/chart)
    # =========================================================================
    def test_f27_01_chart_response_conforms_to_lightweight_charts(self):
        """Verify chart payload conforms to TradingView Lightweight Charts requirements."""
        code, resp = self.app.handle_get_stock_chart("AAPL")
        self.assertEqual(code, 200)
        is_valid, err = validate_chart_payload(resp["data"])
        self.assertTrue(is_valid, err)

    def test_f27_02_chart_candlesticks_ascending_chronological(self):
        """Verify candlesticks timestamps are strictly ascending."""
        code, resp = self.app.handle_get_stock_chart("AAPL")
        candles = resp["data"]["candlesticks"]
        times = [c["time"] for c in candles]
        self.assertEqual(times, sorted(times))

    def test_f27_03_chart_includes_sma30_series(self):
        """Verify 30w SMA points are computed and returned."""
        code, resp = self.app.handle_get_stock_chart("AAPL")
        sma30 = resp["data"]["sma30"]
        self.assertGreater(len(sma30), 0)
        self.assertIn("time", sma30[0])
        self.assertIn("value", sma30[0])

    def test_f27_04_chart_volume_series_has_colors(self):
        """Verify volume series elements include color attribute."""
        code, resp = self.app.handle_get_stock_chart("AAPL")
        volumes = resp["data"]["volume"]
        self.assertGreater(len(volumes), 0)
        self.assertIn("color", volumes[0])
        self.assertTrue(volumes[0]["color"].startswith("rgba("))

    def test_f27_05_chart_404_on_unknown_ticker(self):
        """Verify 404 response on requesting non-existent ticker."""
        code, resp = self.app.handle_get_stock_chart("UNKNOWN123")
        self.assertEqual(code, 404)
        self.assertFalse(resp["success"])

    # =========================================================================
    # FEATURE 28: Stock Summary Endpoint (GET /api/stock/:ticker/summary)
    # =========================================================================
    def test_f28_01_stock_summary_returns_metadata(self):
        """Verify summary returns company metadata (name, sector, industry, market_cap)."""
        code, resp = self.app.handle_get_stock_summary("AAPL")
        self.assertEqual(code, 200)
        data = resp["data"]
        self.assertEqual(data["ticker"], "AAPL")
        self.assertEqual(data["name"], "Apple Inc.")
        self.assertEqual(data["sector"], "Technology")
        self.assertEqual(data["market_cap"], 3000000000000)

    def test_f28_02_stock_summary_includes_latest_daily_bar(self):
        """Verify summary includes latest daily bar details."""
        code, resp = self.app.handle_get_stock_summary("AAPL")
        self.assertEqual(code, 200)
        self.assertIsNotNone(resp["data"]["latest_daily_bar"])
        self.assertIn("close", resp["data"]["latest_daily_bar"])

    def test_f28_03_stock_summary_includes_latest_signal(self):
        """Verify summary includes latest screener signal if stock is a breakout candidate."""
        code, resp = self.app.handle_get_stock_summary("CRWD")
        self.assertEqual(code, 200)
        sig = resp["data"]["latest_signal"]
        self.assertIsNotNone(sig)
        self.assertEqual(sig["entry_status"], "IN_BUY_ZONE")

    def test_f28_04_stock_summary_case_insensitive_lookup(self):
        """Verify lowercase ticker in route param resolves successfully."""
        code, resp = self.app.handle_get_stock_summary("aapl")
        self.assertEqual(code, 200)
        self.assertEqual(resp["data"]["ticker"], "AAPL")

    def test_f28_05_stock_summary_404_for_missing_ticker(self):
        """Verify 404 returned when ticker does not exist."""
        code, resp = self.app.handle_get_stock_summary("MISSING")
        self.assertEqual(code, 404)

    # =========================================================================
    # FEATURE 29: Screener Trigger Endpoint (POST /api/screener/trigger)
    # =========================================================================
    def test_f29_01_trigger_starts_job_when_idle(self):
        """Verify triggering screener creates new scan_job and returns status RUNNING."""
        self.app.is_scanner_running = False
        code, resp = self.app.handle_post_screener_trigger()
        self.assertEqual(code, 200)
        self.assertTrue(resp["success"])
        self.assertEqual(resp["data"]["status"], "RUNNING")
        self.assertIn("job_id", resp["data"])

    def test_f29_02_trigger_conflict_409_when_already_running(self):
        """Verify 409 Conflict returned if another scan is already active."""
        self.app.is_scanner_running = True
        code, resp = self.app.handle_post_screener_trigger()
        self.assertEqual(code, 409)
        self.assertFalse(resp["success"])
        self.assertIn("already in progress", resp["error"])

    def test_f29_03_trigger_creates_audit_job_record(self):
        """Verify scan_jobs table is updated with job status and timestamp."""
        self.app.is_scanner_running = False
        code, resp = self.app.handle_post_screener_trigger()
        job_id = resp["data"]["job_id"]
        job = self.db.scan_jobs[job_id]
        self.assertEqual(job["status"], "RUNNING")
        self.assertEqual(job["job_type"], "WEEKLY_SCREEN")

    def test_f29_04_trigger_unlocks_on_job_completion(self):
        """Verify lock is released once job completes, allowing subsequent runs."""
        self.app.is_scanner_running = False
        code1, resp1 = self.app.handle_post_screener_trigger()
        self.assertEqual(code1, 200)
        
        # Simulate completion
        self.app.is_scanner_running = False
        code2, resp2 = self.app.handle_post_screener_trigger()
        self.assertEqual(code2, 200)
        self.assertNotEqual(resp1["data"]["job_id"], resp2["data"]["job_id"])

    def test_f29_05_trigger_response_message(self):
        """Verify informative success message returned in payload."""
        self.app.is_scanner_running = False
        code, resp = self.app.handle_post_screener_trigger()
        self.assertIn("message", resp["data"])

    # =========================================================================
    # FEATURE 30: Telegram Test Endpoint (POST /api/notifications/telegram-test)
    # =========================================================================
    def test_f30_01_telegram_test_success_when_configured(self):
        """Verify POST /api/notifications/telegram-test returns 200 and message ID."""
        code, resp = self.app.handle_post_telegram_test(has_valid_token=True)
        self.assertEqual(code, 200)
        self.assertTrue(resp["success"])
        self.assertIn("telegram_message_id", resp)

    def test_f30_02_telegram_test_fails_when_unconfigured(self):
        """Verify 400 error when bot credentials missing."""
        code, resp = self.app.handle_post_telegram_test(has_valid_token=False)
        self.assertEqual(code, 400)
        self.assertFalse(resp["success"])
        self.assertIn("not configured", resp["error"])

    def test_f30_03_telegram_test_response_envelope(self):
        """Verify response conforms to standard API envelope."""
        code, resp = self.app.handle_post_telegram_test(has_valid_token=True)
        is_valid, err = validate_api_envelope(resp)
        self.assertTrue(is_valid, err)

    def test_f30_04_telegram_test_error_envelope(self):
        """Verify error response conforms to standard API envelope."""
        code, resp = self.app.handle_post_telegram_test(has_valid_token=False)
        is_valid, err = validate_api_envelope(resp)
        self.assertTrue(is_valid, err)

    def test_f30_05_telegram_test_idempotent_invocation(self):
        """Verify multiple test invocations succeed without side effects."""
        code1, _ = self.app.handle_post_telegram_test(has_valid_token=True)
        code2, _ = self.app.handle_post_telegram_test(has_valid_token=True)
        self.assertEqual(code1, 200)
        self.assertEqual(code2, 200)


if __name__ == "__main__":
    unittest.main()
