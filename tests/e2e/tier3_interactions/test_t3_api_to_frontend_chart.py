"""
Tier 3 Interaction Tests: M5 (Backend REST API) x M6 (Frontend Web Application)
Verifies that chart payloads from Express API conform directly to TradingView
Lightweight Charts specifications and feed the Position Sizing Calculator.
"""

import unittest
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB
from tests.e2e.helpers.api_validator import InMemoryExpressApp, validate_chart_payload
from tests.e2e.helpers.mock_data import generate_daily_bars_for_stock
from tests.e2e.helpers.formula_oracle import oracle_position_sizing


class TestTier3ApiToFrontendChart(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()
        self.app = InMemoryExpressApp(self.db)
        
        self.db.upsert_stock({"ticker": "AXON", "name": "Axon Enterprise Inc.", "sector": "Industrials"})
        
        # Ingest 150 daily bars (~30 weeks)
        bars = generate_daily_bars_for_stock("AXON", pattern="stage2_breakout", num_days=150, base_price=300.0)
        for b in bars:
            self.db.upsert_daily_bar(b)
            
        self.db.upsert_screener_signal({
            "scan_date": "2026-10-09", "ticker": "AXON", "entry_price": 380.0,
            "max_buy_price": 399.0, "current_price": 385.0, "stop_loss_price": 349.6,
            "diff_pct": 1.32, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.2,
            "mrs_score": 16.4, "sma_30w": 340.0, "sma_30w_slope": 1.1,
            "prior_resistance_35w": 380.0, "weekly_close": 385.0, "weekly_volume": 4000000,
            "avg_volume_10w": 1800000
        })

    def test_t3_01_api_payload_matches_tradingview_series_types(self):
        """Verifies API response candlesticks, sma30, volume comply with Lightweight Charts types."""
        code, resp = self.app.handle_get_stock_chart("AXON")
        self.assertEqual(code, 200)
        is_valid, err = validate_chart_payload(resp["data"])
        self.assertTrue(is_valid, err)

    def test_t3_02_metrics_feed_position_calculator_seamlessly(self):
        """Verifies chart metrics entry_price and stop_loss_price directly feed Position Calculator."""
        code, resp = self.app.handle_get_stock_chart("AXON")
        metrics = resp["data"]["metrics"]
        
        entry = metrics["entry_price"]
        stop = metrics["stop_loss_price"]
        self.assertEqual(entry, 380.0)
        self.assertEqual(stop, 349.6)
        
        # Calculate sizing for $100k account risking 1%
        res = oracle_position_sizing(account_size=100000.0, risk_pct=1.0, entry_price=entry, stop_loss_price=stop)
        self.assertTrue(res["valid"])
        # Risk per share = 380 - 349.6 = $30.4. Max risk = $1,000. Shares = floor(1000 / 30.4) = 32 shares.
        self.assertEqual(res["shares_to_buy"], 32)
        self.assertEqual(res["total_capital"], 32 * 380.0)  # $12,160

    def test_t3_03_price_lines_render_exact_levels(self):
        """Verifies 3 price levels exist in metrics for rendering horizontal overlays in ChartModal."""
        code, resp = self.app.handle_get_stock_chart("AXON")
        metrics = resp["data"]["metrics"]
        
        price_lines = [
            {"title": "Entry Price", "price": metrics["entry_price"], "color": "#22c55e"},
            {"title": "Max Buy (+5%)", "price": metrics["max_buy_price"], "color": "#f59e0b"},
            {"title": "Stop Loss", "price": metrics["stop_loss_price"], "color": "#ef4444"},
        ]
        self.assertEqual(price_lines[0]["price"], 380.0)
        self.assertEqual(price_lines[1]["price"], 399.0)
        self.assertEqual(price_lines[2]["price"], 349.6)


if __name__ == "__main__":
    unittest.main()
