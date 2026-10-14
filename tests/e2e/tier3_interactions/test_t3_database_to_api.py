"""
Tier 3 Interaction Tests: M1 (Database Infrastructure) x M5 (Backend REST API)
Verifies that relational tables (stocks, stock_daily_bars, screener_signals, scan_jobs)
are correctly queried, joined, and served by Express REST API endpoints.
"""

import unittest
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB
from tests.e2e.helpers.api_validator import InMemoryExpressApp, validate_api_envelope


class TestTier3DatabaseToApi(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()
        self.app = InMemoryExpressApp(self.db)
        
        # Populate master stocks
        self.db.upsert_stock({"ticker": "NVDA", "name": "NVIDIA Corp", "sector": "Technology", "industry": "Semiconductors", "market_cap": 2800000000000})
        self.db.upsert_stock({"ticker": "CELH", "name": "Celsius Holdings", "sector": "Consumer Defensive", "industry": "Beverages", "market_cap": 9000000000})
        
        # Populate signals for two dates
        self.db.upsert_screener_signal({
            "scan_date": "2026-10-02", "ticker": "NVDA", "entry_price": 120.0,
            "max_buy_price": 126.0, "current_price": 122.0, "stop_loss_price": 110.4,
            "diff_pct": 1.67, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.2,
            "mrs_score": 22.0, "sma_30w": 105.0, "sma_30w_slope": 1.5,
            "prior_resistance_35w": 120.0, "weekly_close": 122.0, "weekly_volume": 40000000,
            "avg_volume_10w": 18000000
        })
        self.db.upsert_screener_signal({
            "scan_date": "2026-10-09", "ticker": "NVDA", "entry_price": 120.0,
            "max_buy_price": 126.0, "current_price": 128.0, "stop_loss_price": 110.4,
            "diff_pct": 6.67, "entry_status": "EXTENDED", "volume_surge_ratio": 1.8,
            "mrs_score": 25.0, "sma_30w": 107.0, "sma_30w_slope": 1.6,
            "prior_resistance_35w": 120.0, "weekly_close": 128.0, "weekly_volume": 35000000,
            "avg_volume_10w": 19000000
        })
        self.db.upsert_screener_signal({
            "scan_date": "2026-10-09", "ticker": "CELH", "entry_price": 45.0,
            "max_buy_price": 47.25, "current_price": 46.0, "stop_loss_price": 41.4,
            "diff_pct": 2.22, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.5,
            "mrs_score": 15.0, "sma_30w": 38.0, "sma_30w_slope": 1.2,
            "prior_resistance_35w": 45.0, "weekly_close": 46.0, "weekly_volume": 12000000,
            "avg_volume_10w": 4800000
        })

    def test_t3_01_api_screener_latest_joins_company_name_and_sector(self):
        """Verifies GET /api/screener/latest joins screener_signals with stocks table."""
        code, resp = self.app.handle_get_screener_latest({})
        self.assertEqual(code, 200)
        signals = resp["data"]["signals"]
        self.assertEqual(len(signals), 2)
        
        # Verify joined fields from stocks table
        nvda_sig = next(s for s in signals if s["ticker"] == "NVDA")
        self.assertEqual(nvda_sig["company_name"], "NVIDIA Corp")
        self.assertEqual(nvda_sig["sector"], "Technology")

    def test_t3_02_api_screener_dates_extracts_distinct_sorted_dates(self):
        """Verifies GET /api/screener/dates returns sorted unique scan dates."""
        code, resp = self.app.handle_get_screener_dates()
        self.assertEqual(code, 200)
        dates = resp["data"]["dates"]
        self.assertEqual(dates, ["2026-10-09", "2026-10-02"])

    def test_t3_03_api_trigger_state_persisted_in_scan_jobs(self):
        """Verifies POST /api/screener/trigger creates a job record in scan_jobs table."""
        self.app.is_scanner_running = False
        code, resp = self.app.handle_post_screener_trigger()
        self.assertEqual(code, 200)
        job_id = resp["data"]["job_id"]
        
        # Verify persisted in database
        self.assertIn(job_id, self.db.scan_jobs)
        job = self.db.scan_jobs[job_id]
        self.assertEqual(job["status"], "RUNNING")

    def test_t3_04_api_stock_summary_unifies_stock_and_signal_and_bars(self):
        """Verifies GET /api/stock/:ticker/summary consolidates master data and latest signal."""
        code, resp = self.app.handle_get_stock_summary("NVDA")
        self.assertEqual(code, 200)
        data = resp["data"]
        self.assertEqual(data["ticker"], "NVDA")
        self.assertEqual(data["sector"], "Technology")
        self.assertIsNotNone(data["latest_signal"])
        self.assertEqual(data["latest_signal"]["entry_status"], "EXTENDED")


if __name__ == "__main__":
    unittest.main()
