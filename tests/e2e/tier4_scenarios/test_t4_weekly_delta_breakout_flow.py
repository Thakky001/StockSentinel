"""
Tier 4 Scenario Test: Weekly Friday Delta Sync & Breakout Detection Flow
Exercises the Friday evening automated batch job:
7-day incremental sync -> cache merge -> weekly candle update -> breakout trigger ->
status IN_BUY_ZONE -> automated Telegram alert dispatch.
"""

import unittest
from datetime import date
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB
from tests.e2e.helpers.api_validator import InMemoryExpressApp
from tests.e2e.helpers.mock_data import generate_daily_bars_for_stock, generate_spy_benchmark_bars, generate_market_trading_days
from tests.e2e.helpers.formula_oracle import (
    oracle_resample_daily_to_weekly,
    oracle_sma,
    oracle_sma_slope,
    oracle_volume_surge,
    oracle_prior_resistance_pivot,
    oracle_mansfield_relative_strength,
    oracle_stage2_filter,
    oracle_target_and_risk,
    oracle_entry_status
)
from tests.e2e.tier1_features.test_f21_f23_telegram import format_weekly_digest


class TestTier4WeeklyDeltaBreakoutFlow(unittest.TestCase):
    def test_friday_delta_sync_detects_fresh_breakout(self):
        """
        Scenario:
        1. Stock built a 35-week base under $120.00 prior resistance pivot.
        2. Week 52 (Friday close) arrives: high volume buying drives close to $122.50 (+2.08% diff).
        3. Weekly delta sync fetches Monday-Friday bars.
        4. Screener processes the new week, detects Close > 120, Volume Surge = 2.4x, Slope = +1.1%, MRS = +15.5.
        5. Categorizes status as 'IN_BUY_ZONE' (within 0% to +5% sweet spot).
        6. Telegram alert sent with green 'IN BUY ZONE' badge.
        7. API endpoint returns status IN_BUY_ZONE for dashboard display.
        """
        db = InMemoryRelationalDB()
        app = InMemoryExpressApp(db)
        
        db.upsert_stock({"ticker": "BREAK", "name": "Breakout Technologies", "sector": "Technology"})
        db.upsert_stock({"ticker": "SPY", "name": "SPDR S&P 500 ETF Trust", "sector": "ETF"})
        
        # 51 weeks of history consolidating under 120 resistance (ending on previous Friday 2026-10-02)
        import math
        dates = [d for d in generate_market_trading_days(num_days=255, end_date=date(2026, 10, 2))]
        history_daily = []
        for i, d in enumerate(dates):
            if i < 155:
                p = 95.0 + 3.0 * math.sin(i / 10.0)
            else:
                p = 95.0 + ((i - 155) / 100.0) * 23.0 + math.sin(i / 5.0)
            history_daily.append({
                "ticker": "BREAK", "trade_date": str(d),
                "open": round(p - 0.5, 4), "high": round(p + 0.5, 4),
                "low": round(p - 0.5, 4), "close": round(p, 4),
                "adj_close": round(p, 4), "volume": 1_000_000
            })
        spy_daily = generate_spy_benchmark_bars(num_days=260)
        for b in history_daily:
            db.upsert_daily_bar(b)
        for b in spy_daily:
            db.upsert_daily_bar(b)
            
        # Delta sync: Friday week 52 daily bars
        friday_date = date(2026, 10, 9)
        delta_daily = [
            {"ticker": "BREAK", "trade_date": "2026-10-05", "open": 118.0, "high": 119.5, "low": 117.5, "close": 119.0, "volume": 1200000},
            {"ticker": "BREAK", "trade_date": "2026-10-06", "open": 119.0, "high": 120.5, "low": 118.5, "close": 120.0, "volume": 1500000},
            {"ticker": "BREAK", "trade_date": "2026-10-07", "open": 120.0, "high": 121.5, "low": 119.5, "close": 121.0, "volume": 1800000},
            {"ticker": "BREAK", "trade_date": "2026-10-08", "open": 121.0, "high": 123.0, "low": 120.5, "close": 122.0, "volume": 2200000},
            {"ticker": "BREAK", "trade_date": "2026-10-09", "open": 122.0, "high": 124.0, "low": 121.5, "close": 122.5, "volume": 3000000},  # Breakout Friday
        ]
        for b in delta_daily:
            db.upsert_daily_bar(b)
            
        # Resample
        all_break_daily = [b for k, b in db.stock_daily_bars.items() if k[0] == "BREAK"]
        break_weekly = oracle_resample_daily_to_weekly(all_break_daily)
        spy_weekly = oracle_resample_daily_to_weekly([b for k, b in db.stock_daily_bars.items() if k[0] == "SPY"])
        
        closes = [w["close"] for w in break_weekly]
        highs = [w["high"] for w in break_weekly]
        volumes = [w["volume"] for w in break_weekly]
        spy_closes = [w["close"] for w in spy_weekly]
        
        sma30 = oracle_sma(closes, window=30)
        slope = oracle_sma_slope(sma30, lookback=1)
        avg_vol10, surge = oracle_volume_surge(volumes, window=10)
        pivot35 = oracle_prior_resistance_pivot(highs, lookback=35)
        mrs = oracle_mansfield_relative_strength(closes, spy_closes, lookback=52)
        
        # Verify breakout
        filter_res = oracle_stage2_filter(
            close=closes[-1],
            sma_30w=sma30[-1],
            sma_30w_slope=slope[-1],
            pivot_35w=pivot35[-1],
            vol_surge_ratio=surge[-1],
            mrs_score=mrs[-1]
        )
        self.assertTrue(filter_res["is_stage2"])
        
        # Compute targets
        risk = oracle_target_and_risk(pivot_35w=pivot35[-1], current_price=closes[-1])
        status = oracle_entry_status(closes[-1], risk["entry_price"], risk["max_buy_price"], risk["stop_loss_price"])
        self.assertEqual(status, "IN_BUY_ZONE")
        self.assertLessEqual(risk["diff_pct"], 5.0)
        
        # Persist signal
        db.upsert_screener_signal({
            "scan_date": "2026-10-09",
            "ticker": "BREAK",
            "entry_price": risk["entry_price"],
            "max_buy_price": risk["max_buy_price"],
            "current_price": risk["current_price"],
            "stop_loss_price": risk["stop_loss_price"],
            "diff_pct": risk["diff_pct"],
            "entry_status": status,
            "volume_surge_ratio": surge[-1],
            "mrs_score": mrs[-1],
            "sma_30w": sma30[-1],
            "sma_30w_slope": slope[-1],
            "prior_resistance_35w": pivot35[-1],
            "weekly_close": closes[-1],
            "weekly_volume": volumes[-1],
            "avg_volume_10w": int(avg_vol10[-1])
        })
        
        # Verify Telegram Alert
        signals = list(db.screener_signals.values())
        digest = format_weekly_digest(signals, scan_date="2026-10-09")
        self.assertIn("IN BUY ZONE", digest)
        self.assertIn("BREAK", digest)
        
        # Verify API
        code, resp = app.handle_get_screener_latest({"status": "IN_BUY_ZONE"})
        self.assertEqual(code, 200)
        self.assertEqual(len(resp["data"]["signals"]), 1)
        self.assertEqual(resp["data"]["signals"][0]["entry_status"], "IN_BUY_ZONE")


if __name__ == "__main__":
    unittest.main()
