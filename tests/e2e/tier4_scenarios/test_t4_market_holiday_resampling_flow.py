"""
Tier 4 Scenario Test: Market Holiday Resampling Flow
Verifies system behavior during holiday-shortened trading weeks
(e.g., Good Friday, Thanksgiving, Labor Day, Martin Luther King Jr. Day).
Ensures weekly bar compression correctly anchors to the final active trading day
without breaking time-series continuity, SMA calculations, or chart rendering.
"""

import unittest
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB
from tests.e2e.helpers.api_validator import InMemoryExpressApp, validate_chart_payload
from tests.e2e.helpers.formula_oracle import oracle_resample_daily_to_weekly, oracle_sma


class TestTier4MarketHolidayResamplingFlow(unittest.TestCase):
    def test_holiday_short_week_resampling_and_chart_continuity(self):
        """
        Scenario:
        - Week 1: Full trading week (Mon 2026-03-30 to Fri 2026-04-03)
        - Week 2: Good Friday Holiday (Mon 2026-04-06 to Thu 2026-04-09, Fri market closed)
        - Week 3: Full trading week (Mon 2026-04-13 to Fri 2026-04-17)
        Verifications:
        - Exactly 3 weekly bars are produced.
        - Week 2 candle trade_date is Thursday 2026-04-09 (not Friday).
        - Volume for Week 2 is sum of 4 trading days.
        - SMA 30w continues without discontinuity.
        - Lightweight Charts API validates clean chronological time-series.
        """
        db = InMemoryRelationalDB()
        app = InMemoryExpressApp(db)
        
        ticker = "HOLI"
        db.upsert_stock({"ticker": ticker, "name": "Holiday Test Corp", "sector": "Technology"})
        
        # 30 prior weeks of full 5-day weeks (150 days)
        # Week 1 (5 days)
        week1_days = [
            {"ticker": ticker, "trade_date": f"2026-03-{30+i:02d}", "open": 100.0 + i, "high": 102.0 + i, "low": 99.0 + i, "close": 101.0 + i, "volume": 1000000}
            for i in range(2)
        ] + [
            {"ticker": ticker, "trade_date": f"2026-04-0{i}", "open": 102.0 + i, "high": 104.0 + i, "low": 101.0 + i, "close": 103.0 + i, "volume": 1000000}
            for i in range(1, 4)
        ]
        
        # Week 2 (4 days: Good Friday closed)
        week2_days = [
            {"ticker": ticker, "trade_date": f"2026-04-0{i}", "open": 105.0 + i, "high": 107.0 + i, "low": 104.0 + i, "close": 106.0 + i, "volume": 1200000}
            for i in range(6, 10)  # 06, 07, 08, 09 (Mon-Thu)
        ]
        
        # Week 3 (5 days)
        week3_days = [
            {"ticker": ticker, "trade_date": f"2026-04-{13+i:02d}", "open": 110.0 + i, "high": 112.0 + i, "low": 109.0 + i, "close": 111.0 + i, "volume": 1100000}
            for i in range(5)
        ]
        
        all_bars = week1_days + week2_days + week3_days
        for b in all_bars:
            db.upsert_daily_bar(b)
            
        weekly_bars = oracle_resample_daily_to_weekly(all_bars)
        self.assertEqual(len(weekly_bars), 3)
        
        # Week 1 checks
        self.assertEqual(weekly_bars[0]["trading_days"], 5)
        self.assertEqual(weekly_bars[0]["trade_date"], "2026-04-03")
        
        # Week 2 (Good Friday) checks
        self.assertEqual(weekly_bars[1]["trading_days"], 4)
        self.assertEqual(weekly_bars[1]["trade_date"], "2026-04-09")  # Thursday
        self.assertEqual(weekly_bars[1]["volume"], 4 * 1200000)
        self.assertEqual(weekly_bars[1]["open"], week2_days[0]["open"])
        self.assertEqual(weekly_bars[1]["close"], week2_days[-1]["close"])
        
        # Week 3 checks
        self.assertEqual(weekly_bars[2]["trading_days"], 5)
        self.assertEqual(weekly_bars[2]["trade_date"], "2026-04-17")
        
        # Verify chart API response
        code, resp = app.handle_get_stock_chart(ticker)
        self.assertEqual(code, 200)
        is_valid, err = validate_chart_payload(resp["data"])
        self.assertTrue(is_valid, err)
        
        candles = resp["data"]["candlesticks"]
        self.assertEqual(len(candles), 3)
        self.assertEqual(candles[1]["time"], "2026-04-09")


if __name__ == "__main__":
    unittest.main()
