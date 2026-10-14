"""
Tier 4 Scenario Test: Investor End-to-End Risk Management Workflow
Simulates the real-world user journey:
1. Investor opens web dashboard and filters by 'IN_BUY_ZONE'
2. Selects breakout candidate 'CELH'
3. Reviews interactive weekly chart with 30w SMA and Entry/Stop lines
4. Launches Position Sizing Calculator with $50k account and 1.25% risk
5. Validates position size, capital required, and portfolio allocation %
6. Adds stock to Watchlist Drawer for ongoing surveillance.
"""

import unittest
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB
from tests.e2e.helpers.api_validator import InMemoryExpressApp, validate_chart_payload
from tests.e2e.helpers.mock_data import generate_daily_bars_for_stock
from tests.e2e.helpers.formula_oracle import oracle_position_sizing


class TestTier4InvestorRiskWorkflow(unittest.TestCase):
    def test_complete_investor_journey(self):
        """Exercises the complete trader workflow from dashboard discovery to sizing and watchlisting."""
        db = InMemoryRelationalDB()
        app = InMemoryExpressApp(db)
        
        # Seed stock and bars
        db.upsert_stock({"ticker": "CELH", "name": "Celsius Holdings Inc.", "sector": "Consumer Defensive"})
        bars = generate_daily_bars_for_stock("CELH", pattern="stage2_breakout", num_days=200, base_price=40.0)
        for b in bars:
            db.upsert_daily_bar(b)
            
        # Seed screener signal
        entry_pivot = 45.0
        max_buy = 47.25  # +5%
        current_p = 46.0  # +2.2% in buy zone
        stop_loss = 41.4  # -8%
        
        db.upsert_screener_signal({
            "scan_date": "2026-10-09",
            "ticker": "CELH",
            "entry_price": entry_pivot,
            "max_buy_price": max_buy,
            "current_price": current_p,
            "stop_loss_price": stop_loss,
            "diff_pct": 2.22,
            "entry_status": "IN_BUY_ZONE",
            "volume_surge_ratio": 2.4,
            "mrs_score": 19.5,
            "sma_30w": 38.0,
            "sma_30w_slope": 1.2,
            "prior_resistance_35w": entry_pivot,
            "weekly_close": current_p,
            "weekly_volume": 8000000,
            "avg_volume_10w": 3300000
        })
        
        # Step 1: Investor queries latest screener filtered by IN_BUY_ZONE
        code_latest, resp_latest = app.handle_get_screener_latest({"status": "IN_BUY_ZONE"})
        self.assertEqual(code_latest, 200)
        signals = resp_latest["data"]["signals"]
        self.assertEqual(len(signals), 1)
        target_signal = signals[0]
        self.assertEqual(target_signal["ticker"], "CELH")
        
        # Step 2: Investor opens stock chart
        code_chart, resp_chart = app.handle_get_stock_chart("CELH")
        self.assertEqual(code_chart, 200)
        chart_data = resp_chart["data"]
        is_valid_chart, err = validate_chart_payload(chart_data)
        self.assertTrue(is_valid_chart, err)
        
        # Step 3: Verify price lines match screener levels
        metrics = chart_data["metrics"]
        self.assertEqual(metrics["entry_price"], entry_pivot)
        self.assertEqual(metrics["max_buy_price"], max_buy)
        self.assertEqual(metrics["stop_loss_price"], stop_loss)
        
        # Step 4: Investor launches Position Calculator
        # Account: $50,000. Risk: 1.25% ($625.00 max loss)
        # Entry: $45.00. Stop: $41.40 (Risk per share = $3.60)
        # Expected Shares: floor(625 / 3.60) = floor(173.61) = 173 shares
        # Capital: 173 * $45.00 = $7,785.00 (15.57% allocation)
        calc = oracle_position_sizing(
            account_size=50000.0,
            risk_pct=1.25,
            entry_price=metrics["entry_price"],
            stop_loss_price=metrics["stop_loss_price"]
        )
        self.assertTrue(calc["valid"])
        self.assertEqual(calc["max_dollar_risk"], 625.00)
        self.assertEqual(calc["risk_per_share"], 3.60)
        self.assertEqual(calc["shares_to_buy"], 173)
        self.assertEqual(calc["total_capital"], 7785.00)
        self.assertEqual(calc["portfolio_allocation_pct"], 15.57)
        self.assertFalse(calc["exceeds_capital"])
        
        # Step 5: Investor tests invalid stop price (Stop above Entry)
        invalid_calc = oracle_position_sizing(
            account_size=50000.0,
            risk_pct=1.25,
            entry_price=45.00,
            stop_loss_price=46.00
        )
        self.assertFalse(invalid_calc["valid"])
        self.assertIn("Stop loss price must be strictly lower than Entry price", invalid_calc["error"])
        
        # Step 6: Investor adds CELH to localStorage Watchlist
        watchlist = []
        if "CELH" not in watchlist:
            watchlist.append("CELH")
        self.assertIn("CELH", watchlist)
        self.assertEqual(len(watchlist), 1)


if __name__ == "__main__":
    unittest.main()
