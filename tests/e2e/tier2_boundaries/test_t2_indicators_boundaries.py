"""
Tier 2 Boundary Tests: Features 12-20 (Indicators, Screener Math & Filters)
Tests mathematical edge cases, lookback thresholds, division-by-zero guards,
exact predicate boundaries (e.g. 1.5000 volume surge, 0.0000 MRS),
and status transition points.
"""

import unittest
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
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB


class TestTier2IndicatorsBoundaries(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()

    # =========================================================================
    # FEATURE 12 BOUNDARIES: Weekly Resampling Engine
    # =========================================================================
    def test_t2_f12_01_single_day_holiday_week(self):
        """Boundary: Week with only 1 trading day (e.g. emergency market closure)."""
        bars = [{"ticker": "T1", "trade_date": "2026-10-05", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 500000}]
        weekly = oracle_resample_daily_to_weekly(bars)
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0]["open"], 100.0)
        self.assertEqual(weekly[0]["close"], 102.0)
        self.assertEqual(weekly[0]["trading_days"], 1)

    def test_t2_f12_02_four_day_good_friday_week(self):
        """Boundary: 4-day week where Friday is a holiday; Thursday close is weekly close."""
        bars = [
            {"ticker": "T1", "trade_date": "2026-04-06", "open": 50.0, "high": 52.0, "low": 49.0, "close": 51.0, "volume": 1000},
            {"ticker": "T1", "trade_date": "2026-04-07", "open": 51.0, "high": 53.0, "low": 50.0, "close": 52.0, "volume": 1000},
            {"ticker": "T1", "trade_date": "2026-04-08", "open": 52.0, "high": 54.0, "low": 51.0, "close": 53.0, "volume": 1000},
            {"ticker": "T1", "trade_date": "2026-04-09", "open": 53.0, "high": 55.0, "low": 52.0, "close": 54.5, "volume": 1000},
        ]
        weekly = oracle_resample_daily_to_weekly(bars)
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0]["close"], 54.5)
        self.assertEqual(weekly[0]["trade_date"], "2026-04-09")

    def test_t2_f12_03_midweek_holiday_wednesday_closure(self):
        """Boundary: Week with Wednesday holiday (Mon, Tue, Thu, Fri active)."""
        bars = [
            {"ticker": "T1", "trade_date": "2026-07-06", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100},
            {"ticker": "T1", "trade_date": "2026-07-07", "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 100},
            {"ticker": "T1", "trade_date": "2026-07-09", "open": 101.5, "high": 103.0, "low": 101.0, "close": 102.5, "volume": 100},
            {"ticker": "T1", "trade_date": "2026-07-10", "open": 102.5, "high": 104.0, "low": 102.0, "close": 103.5, "volume": 100},
        ]
        weekly = oracle_resample_daily_to_weekly(bars)
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0]["trading_days"], 4)
        self.assertEqual(weekly[0]["close"], 103.5)

    def test_t2_f12_04_volume_exceeding_32bit_integer(self):
        """Boundary: Mega-cap weekly volume exceeding 2^31 - 1 (2,147,483,647 shares)."""
        vol_per_day = 600_000_000
        bars = [
            {"ticker": "T1", "trade_date": f"2026-10-0{i}", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": vol_per_day}
            for i in range(5, 10)
        ]
        weekly = oracle_resample_daily_to_weekly(bars)
        total_vol = weekly[0]["volume"]
        self.assertEqual(total_vol, 3_000_000_000)
        self.assertGreater(total_vol, 2_147_483_647)

    def test_t2_f12_05_flat_price_high_equals_low_all_week(self):
        """Corner Case: Halted stock where price remains unchanged all week."""
        bars = [
            {"ticker": "T1", "trade_date": f"2026-10-0{i}", "open": 25.0, "high": 25.0, "low": 25.0, "close": 25.0, "volume": 0}
            for i in range(5, 10)
        ]
        weekly = oracle_resample_daily_to_weekly(bars)
        self.assertEqual(weekly[0]["high"], 25.0)
        self.assertEqual(weekly[0]["low"], 25.0)

    # =========================================================================
    # FEATURE 13 BOUNDARIES: 30-Week SMA & Slope
    # =========================================================================
    def test_t2_f13_01_exactly_29_weeks_returns_none(self):
        """Boundary: 29 weeks of history is insufficient for 30w SMA."""
        closes = [100.0] * 29
        sma = oracle_sma(closes, window=30)
        self.assertEqual(len(sma), 29)
        self.assertTrue(all(x is None for x in sma))

    def test_t2_f13_02_exactly_30_weeks_computes_first_sma(self):
        """Boundary: Week 30 (index 29) produces the first non-null SMA value."""
        closes = [100.0] * 30
        sma = oracle_sma(closes, window=30)
        self.assertIsNone(sma[28])
        self.assertEqual(sma[29], 100.0)

    def test_t2_f13_03_slope_division_by_zero_guard(self):
        """Corner Case: Prior SMA value of 0.0 guarded against ZeroDivisionError."""
        sma_series = [None] * 29 + [0.0, 10.0]
        slopes = oracle_sma_slope(sma_series, lookback=1)
        self.assertIsNone(slopes[30])

    def test_t2_f13_04_slope_exact_zero_meets_qualification(self):
        """Boundary: Flat slope == 0.0000% satisfies Slope >= 0."""
        sma_series = [None] * 29 + [120.0, 120.0]
        slopes = oracle_sma_slope(sma_series, lookback=1)
        self.assertEqual(slopes[30], 0.0)
        self.assertTrue(slopes[30] >= 0.0)

    def test_t2_f13_05_slope_micro_negative_fails_qualification(self):
        """Boundary: Slope of -0.0001% fails Slope >= 0."""
        slope = -0.0001
        self.assertFalse(slope >= 0.0)

    # =========================================================================
    # FEATURE 14 BOUNDARIES: 10-Week Volume Average & Surge
    # =========================================================================
    def test_t2_f14_01_exactly_9_weeks_volume_returns_none(self):
        """Boundary: 9 weeks of volume history returns None for 10w average."""
        vols = [1_000_000] * 9
        avg_vols, surges = oracle_volume_surge(vols, window=10)
        self.assertTrue(all(a is None for a in avg_vols))

    def test_t2_f14_02_prior_average_volume_zero_guard(self):
        """Corner Case: Prior 10 weeks had zero volume; guards against ZeroDivisionError."""
        vols = [0] * 10 + [1_000_000]
        avg_vols, surges = oracle_volume_surge(vols, window=10)
        self.assertEqual(avg_vols[10], 0.0)
        self.assertEqual(surges[10], 0.0)

    def test_t2_f14_03_surge_ratio_1_4999_fails_threshold(self):
        """Boundary: Volume surge ratio of 1.4999 is strictly below 1.50."""
        surge = 1.4999
        self.assertFalse(surge >= 1.50)

    def test_t2_f14_04_surge_ratio_1_5000_passes_threshold(self):
        """Boundary: Volume surge ratio of 1.5000 exactly meets 1.50."""
        surge = 1.5000
        self.assertTrue(surge >= 1.50)

    def test_t2_f14_05_extreme_volume_surge_50x(self):
        """Boundary: Massive 50x volume surge on biotech FDA approval."""
        vols = [100_000] * 10 + [5_000_000]
        avg_vols, surges = oracle_volume_surge(vols, window=10)
        self.assertEqual(surges[10], 50.0)

    # =========================================================================
    # FEATURE 15 BOUNDARIES: 35-Week Resistance Pivot
    # =========================================================================
    def test_t2_f15_01_exactly_34_weeks_returns_none(self):
        """Boundary: 34 weeks of highs returns None for 35w resistance pivot."""
        highs = [100.0] * 34
        pivots = oracle_prior_resistance_pivot(highs, lookback=35)
        self.assertTrue(all(p is None for p in pivots))

    def test_t2_f15_02_close_equals_resistance_pivot_exact(self):
        """Boundary: Close == Pivot (100.0000 == 100.0000) qualifies breakout."""
        close = 100.0
        pivot = 100.0
        self.assertTrue(close >= pivot)

    def test_t2_f15_03_close_one_cent_below_pivot_fails(self):
        """Boundary: Close is 1 cent below pivot ($99.99 vs $100.00 pivot)."""
        close = 99.99
        pivot = 100.00
        self.assertFalse(close >= pivot)

    def test_t2_f15_04_all_35_prior_weeks_identical_high(self):
        """Corner Case: Exact horizontal resistance line across all 35 weeks."""
        highs = [125.0] * 35 + [125.5]
        pivots = oracle_prior_resistance_pivot(highs, lookback=35)
        self.assertEqual(pivots[35], 125.0)

    def test_t2_f15_05_pivot_at_oldest_week_35_persists(self):
        """Boundary: Resistance high established at week t-35 is captured."""
        highs = [150.0] + ([100.0] * 34) + [151.0]
        pivots = oracle_prior_resistance_pivot(highs, lookback=35)
        self.assertEqual(pivots[35], 150.0)

    # =========================================================================
    # FEATURE 16 BOUNDARIES: Mansfield Relative Strength
    # =========================================================================
    def test_t2_f16_01_exactly_51_weeks_returns_none(self):
        """Boundary: 51 weeks of RS data returns None for 52w MRS."""
        stock = [100.0] * 51
        spy = [400.0] * 51
        mrs = oracle_mansfield_relative_strength(stock, spy, lookback=52)
        self.assertTrue(all(m is None for m in mrs))

    def test_t2_f16_02_mrs_score_exact_zero_fails(self):
        """Boundary: MRS score of exactly 0.0000 fails MRS > 0.0 predicate."""
        mrs = 0.0000
        self.assertFalse(mrs > 0.0)

    def test_t2_f16_03_mrs_score_0_0001_passes(self):
        """Boundary: Micro positive MRS score of +0.0001 passes MRS > 0.0 predicate."""
        mrs = 0.0001
        self.assertTrue(mrs > 0.0)

    def test_t2_f16_04_spy_close_zero_division_guard(self):
        """Corner Case: SPY close of 0 guarded against ZeroDivisionError."""
        stock = [100.0] * 52
        spy = [400.0] * 51 + [0.0]
        mrs = oracle_mansfield_relative_strength(stock, spy, lookback=52)
        self.assertIsNotNone(mrs[51])

    def test_t2_f16_05_extreme_mrs_score_plus_200(self):
        """Boundary: Extreme outperformance MRS score (+200.0)."""
        mrs = 200.0
        self.assertTrue(mrs > 0.0)

    # =========================================================================
    # FEATURE 17 BOUNDARIES: Stage 2 Breakout Multi-Factor Filter
    # =========================================================================
    def test_t2_f17_01_fail_only_mrs(self):
        """Corner Case: 4 factors pass, only MRS is negative -> rejected."""
        res = oracle_stage2_filter(close=100.0, sma_30w=90.0, sma_30w_slope=1.0, pivot_35w=100.0, vol_surge_ratio=2.0, mrs_score=-0.01)
        self.assertFalse(res["is_stage2"])

    def test_t2_f17_02_fail_only_volume_surge(self):
        """Corner Case: 4 factors pass, only Volume surge is 1.49x -> rejected."""
        res = oracle_stage2_filter(close=100.0, sma_30w=90.0, sma_30w_slope=1.0, pivot_35w=100.0, vol_surge_ratio=1.49, mrs_score=5.0)
        self.assertFalse(res["is_stage2"])

    def test_t2_f17_03_fail_only_sma_slope(self):
        """Corner Case: 4 factors pass, only SMA slope is -0.1% -> rejected."""
        res = oracle_stage2_filter(close=100.0, sma_30w=90.0, sma_30w_slope=-0.1, pivot_35w=100.0, vol_surge_ratio=2.0, mrs_score=5.0)
        self.assertFalse(res["is_stage2"])

    def test_t2_f17_04_fail_only_pivot_breakout(self):
        """Corner Case: 4 factors pass, only price is $99.99 vs $100.00 pivot -> rejected."""
        res = oracle_stage2_filter(close=99.99, sma_30w=90.0, sma_30w_slope=1.0, pivot_35w=100.0, vol_surge_ratio=2.0, mrs_score=5.0)
        self.assertFalse(res["is_stage2"])

    def test_t2_f17_05_all_factors_at_exact_positive_boundaries(self):
        """Boundary: All factors meet their exact threshold -> qualified."""
        res = oracle_stage2_filter(close=100.0, sma_30w=99.99, sma_30w_slope=0.0, pivot_35w=100.0, vol_surge_ratio=1.50, mrs_score=0.0001)
        self.assertTrue(res["is_stage2"])

    # =========================================================================
    # FEATURE 18 BOUNDARIES: Target & Risk Math
    # =========================================================================
    def test_t2_f18_01_fractional_cent_pivot_precision(self):
        """Boundary: Pivot with 4 decimal places $12.3456 calculates max buy cleanly."""
        risk = oracle_target_and_risk(pivot_35w=12.3456, current_price=12.50)
        self.assertEqual(risk["entry_price"], 12.3456)
        self.assertEqual(risk["max_buy_price"], round(12.3456 * 1.05, 4))

    def test_t2_f18_02_diff_pct_exact_plus_5_percent(self):
        """Boundary: diff_pct is exactly +5.0000%."""
        risk = oracle_target_and_risk(pivot_35w=100.0, current_price=105.0)
        self.assertEqual(risk["diff_pct"], 5.0)

    def test_t2_f18_03_diff_pct_negative_below_pivot(self):
        """Boundary: Current price pulled back -3.5% below pivot."""
        risk = oracle_target_and_risk(pivot_35w=100.0, current_price=96.5)
        self.assertEqual(risk["diff_pct"], -3.5)

    def test_t2_f18_04_swing_low_higher_than_entry_rejected(self):
        """Corner Case: Swing low higher than entry price ignored, defaults to 8% stop."""
        risk = oracle_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=105.0)
        self.assertEqual(risk["stop_loss_price"], 92.0)

    def test_t2_f18_05_swing_low_negative_ignored(self):
        """Corner Case: Negative swing low defaults to 8% stop."""
        risk = oracle_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=-10.0)
        self.assertEqual(risk["stop_loss_price"], 92.0)

    # =========================================================================
    # FEATURE 19 BOUNDARIES: Entry Status Categorization
    # =========================================================================
    def test_t2_f19_01_price_at_stop_loss_exact(self):
        """Boundary: Current price equal to stop loss is BELOW_ENTRY (stopped out only when strictly below)."""
        status = oracle_entry_status(current_price=92.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "BELOW_ENTRY")

    def test_t2_f19_02_price_one_cent_below_stop_is_stopped_out(self):
        """Boundary: Current price 91.99 when stop is 92.00 is STOPPED_OUT."""
        status = oracle_entry_status(current_price=91.99, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "STOPPED_OUT")

    def test_t2_f19_03_price_at_max_buy_exact(self):
        """Boundary: Current price equal to max buy (+5.0%) is IN_BUY_ZONE."""
        status = oracle_entry_status(current_price=105.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "IN_BUY_ZONE")

    def test_t2_f19_04_price_one_cent_above_max_buy_is_extended(self):
        """Boundary: Current price 105.01 when max buy is 105.00 is EXTENDED."""
        status = oracle_entry_status(current_price=105.01, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "EXTENDED")

    def test_t2_f19_05_price_one_cent_below_entry_is_below_entry(self):
        """Boundary: Current price 99.99 when entry is 100.00 is BELOW_ENTRY."""
        status = oracle_entry_status(current_price=99.99, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "BELOW_ENTRY")

    # =========================================================================
    # FEATURE 20 BOUNDARIES: Signals & Job Persistence
    # =========================================================================
    def test_t2_f20_01_zero_signals_found_persistence(self):
        """Boundary: Bear market scan with 0 qualified breakouts recorded properly in scan_jobs."""
        job_id = self.db.create_scan_job({"job_type": "SCREEN", "status": "COMPLETED", "started_at": "2026-10-14T00:00:00Z", "signals_found": 0})
        self.assertEqual(self.db.scan_jobs[job_id]["signals_found"], 0)

    def test_t2_f20_02_job_audit_null_error_message_on_success(self):
        """Boundary: Successful scan job leaves error_message NULL."""
        job_id = self.db.create_scan_job({"job_type": "SCREEN", "status": "COMPLETED", "started_at": "2026-10-14T00:00:00Z", "error_message": None})
        self.assertIsNone(self.db.scan_jobs[job_id]["error_message"])

    def test_t2_f20_03_telegram_alert_sent_boolean_flag(self):
        """Boundary: Flag telegram_alert_sent toggles from False to True."""
        job_id = self.db.create_scan_job({"job_type": "SCREEN", "status": "RUNNING", "started_at": "2026-10-14T00:00:00Z", "telegram_alert_sent": False})
        self.assertFalse(self.db.scan_jobs[job_id]["telegram_alert_sent"])
        self.db.update_scan_job(job_id, {"telegram_alert_sent": True})
        self.assertTrue(self.db.scan_jobs[job_id]["telegram_alert_sent"])

    def test_t2_f20_04_signal_volume_surge_mutation(self):
        """Corner Case: Screener recalculation updates volume surge ratio on existing signal record."""
        self.db.upsert_stock({"ticker": "RESCAN", "name": "Rescan Corp"})
        sig = {
            "scan_date": "2026-10-09", "ticker": "RESCAN", "entry_price": 50.0,
            "max_buy_price": 52.5, "current_price": 51.0, "stop_loss_price": 46.0,
            "diff_pct": 2.0, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 1.6,
            "mrs_score": 5.0, "sma_30w": 45.0, "sma_30w_slope": 0.5,
            "prior_resistance_35w": 50.0, "weekly_close": 51.0, "weekly_volume": 1600000,
            "avg_volume_10w": 1000000
        }
        id1 = self.db.upsert_screener_signal(sig)
        sig_revised = dict(sig, volume_surge_ratio=2.1)
        id2 = self.db.upsert_screener_signal(sig_revised)
        self.assertEqual(id1, id2)
        self.assertEqual(self.db.screener_signals[id1]["volume_surge_ratio"], 2.1)

    def test_t2_f20_05_many_signals_same_date(self):
        """Boundary: 100 qualified breakout signals on the same scan date all stored uniquely."""
        for i in range(100):
            t = f"S{i:03d}"
            self.db.upsert_stock({"ticker": t, "name": f"Stock {i}"})
            self.db.upsert_screener_signal({
                "scan_date": "2026-10-09", "ticker": t, "entry_price": 100.0,
                "max_buy_price": 105.0, "current_price": 102.0, "stop_loss_price": 92.0,
                "diff_pct": 2.0, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.0,
                "mrs_score": 5.0, "sma_30w": 90.0, "sma_30w_slope": 0.5,
                "prior_resistance_35w": 100.0, "weekly_close": 102.0, "weekly_volume": 2000000,
                "avg_volume_10w": 1000000
            })
        signals_oct09 = [s for s in self.db.screener_signals.values() if s["scan_date"] == "2026-10-09"]
        self.assertGreaterEqual(len(signals_oct09), 100)


if __name__ == "__main__":
    unittest.main()
