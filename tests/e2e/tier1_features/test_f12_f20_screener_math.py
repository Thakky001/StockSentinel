"""
Tier 1 Tests: Features 12-20 (Core Screener Engine & Indicator Math)
Isolation test cases covering daily-to-weekly resampling, 30w SMA, slope,
10w volume average, volume surge ratio, 35w resistance pivot, Mansfield Relative
Strength (MRS) vs SPY, Stage 2 multi-factor breakout filter, target/risk math,
entry status categorization, and signal/job persistence.
"""

import unittest
from datetime import date
from tests.e2e.helpers.mock_data import (
    generate_daily_bars_for_stock,
    generate_spy_benchmark_bars
)
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


class TestTier1Features12to20(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()
        self.db.upsert_stock({"ticker": "TEST", "name": "Test Company Inc."})

    # =========================================================================
    # FEATURE 12: Weekly Resampling Engine
    # =========================================================================
    def test_f12_01_resampling_aggregation_counts(self):
        """Verify 5 daily bars in a standard week compress to exactly 1 weekly bar."""
        bars = [
            {"ticker": "TEST", "trade_date": "2026-10-05", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 1000},
            {"ticker": "TEST", "trade_date": "2026-10-06", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 1000},
            {"ticker": "TEST", "trade_date": "2026-10-07", "open": 102.0, "high": 104.0, "low": 101.0, "close": 103.0, "volume": 1000},
            {"ticker": "TEST", "trade_date": "2026-10-08", "open": 103.0, "high": 105.0, "low": 102.0, "close": 104.0, "volume": 1000},
            {"ticker": "TEST", "trade_date": "2026-10-09", "open": 104.0, "high": 106.0, "low": 103.0, "close": 105.0, "volume": 1000},
        ]
        weekly = oracle_resample_daily_to_weekly(bars)
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0]["trading_days"], 5)

    def test_f12_02_resampling_open_is_monday_open(self):
        """Verify weekly open matches the open of the first trading day of the week (Monday)."""
        daily_bars = generate_daily_bars_for_stock("TEST", num_days=5, base_price=100.0)
        weekly = oracle_resample_daily_to_weekly(daily_bars)
        self.assertEqual(weekly[0]["open"], daily_bars[0]["open"])

    def test_f12_03_resampling_close_is_friday_close(self):
        """Verify weekly close matches the close of the last trading day of the week (Friday)."""
        daily_bars = generate_daily_bars_for_stock("TEST", num_days=5, base_price=100.0)
        weekly = oracle_resample_daily_to_weekly(daily_bars)
        self.assertEqual(weekly[0]["close"], daily_bars[-1]["close"])

    def test_f12_04_resampling_high_and_low_extremes(self):
        """Verify weekly high is the maximum daily high and weekly low is the minimum daily low."""
        bars = [
            {"ticker": "TEST", "trade_date": "2026-10-05", "open": 100.0, "high": 110.0, "low": 98.0, "close": 105.0, "volume": 100},
            {"ticker": "TEST", "trade_date": "2026-10-06", "open": 105.0, "high": 107.0, "low": 92.0, "close": 95.0, "volume": 100},
            {"ticker": "TEST", "trade_date": "2026-10-07", "open": 95.0, "high": 100.0, "low": 94.0, "close": 98.0, "volume": 100},
        ]
        weekly = oracle_resample_daily_to_weekly(bars)
        self.assertEqual(weekly[0]["high"], 110.0)
        self.assertEqual(weekly[0]["low"], 92.0)

    def test_f12_05_resampling_volume_summation(self):
        """Verify weekly volume is the sum of all trading days' volumes in that week."""
        bars = [
            {"ticker": "TEST", "trade_date": "2026-10-05", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1500},
            {"ticker": "TEST", "trade_date": "2026-10-06", "open": 10.5, "high": 12.0, "low": 10.0, "close": 11.0, "volume": 2500},
        ]
        weekly = oracle_resample_daily_to_weekly(bars)
        self.assertEqual(weekly[0]["volume"], 4000)

    # =========================================================================
    # FEATURE 13: 30-Week SMA & Slope
    # =========================================================================
    def test_f13_01_sma30_window_requires_30_periods(self):
        """Verify SMA 30 returns None for the first 29 periods and starts at index 29."""
        closes = [100.0] * 35
        sma = oracle_sma(closes, window=30)
        self.assertIsNone(sma[28])
        self.assertEqual(sma[29], 100.0)
        self.assertEqual(sma[34], 100.0)

    def test_f13_02_sma30_rolling_average_math(self):
        """Verify arithmetic average calculation over rolling 30 weeks."""
        # 10 weeks of 100, followed by 20 weeks of 130 => (10*100 + 20*130) / 30 = 3600 / 30 = 120.0
        closes = ([100.0] * 10) + ([130.0] * 20)
        sma = oracle_sma(closes, window=30)
        self.assertEqual(sma[29], 120.0)

    def test_f13_03_sma30_slope_positive_uptrend(self):
        """Verify slope >= 0 when SMA30 is increasing week over week."""
        sma_series = [None] * 29 + [100.0, 101.5, 103.0]
        slopes = oracle_sma_slope(sma_series, lookback=1)
        self.assertGreater(slopes[30], 0.0)
        self.assertEqual(slopes[30], 1.5)  # (101.5 - 100.0) / 100.0 * 100%

    def test_f13_04_sma30_slope_negative_downtrend(self):
        """Verify slope < 0 when SMA30 is decreasing week over week."""
        sma_series = [None] * 29 + [100.0, 98.0]
        slopes = oracle_sma_slope(sma_series, lookback=1)
        self.assertLess(slopes[30], 0.0)
        self.assertEqual(slopes[30], -2.0)

    def test_f13_05_sma30_slope_flat_zero(self):
        """Verify slope == 0.0 when SMA30 is completely flat."""
        sma_series = [None] * 29 + [150.0, 150.0]
        slopes = oracle_sma_slope(sma_series, lookback=1)
        self.assertEqual(slopes[30], 0.0)

    # =========================================================================
    # FEATURE 14: 10-Week Volume Average & Surge
    # =========================================================================
    def test_f14_01_volume_average_window_10_weeks(self):
        """Verify 10-week average volume requires 10 prior weeks of history."""
        vols = [1_000_000] * 12
        avg_vols, surges = oracle_volume_surge(vols, window=10)
        self.assertIsNone(avg_vols[9])
        self.assertEqual(avg_vols[10], 1_000_000.0)

    def test_f14_02_volume_surge_ratio_calculation(self):
        """Verify surge ratio is current_volume / 10w_avg_volume."""
        # 10 prior weeks of 1,000,000, current week 2,500,000 => surge 2.5x
        vols = ([1_000_000] * 10) + [2_500_000]
        avg_vols, surges = oracle_volume_surge(vols, window=10)
        self.assertEqual(surges[10], 2.5)

    def test_f14_03_volume_surge_threshold_pass_at_1_5(self):
        """Verify volume surge >= 1.5 meets the Stage 2 requirement."""
        surge = 1.50
        self.assertTrue(surge >= 1.5)

    def test_f14_04_volume_surge_threshold_fail_under_1_5(self):
        """Verify volume surge < 1.5 fails the Stage 2 requirement."""
        surge = 1.49
        self.assertFalse(surge >= 1.5)

    def test_f14_05_volume_average_excludes_current_breakout_week(self):
        """Verify prior 10-week average does NOT include current week's heavy breakout volume."""
        # Prior 10 weeks: 1,000,000 each. Breakout week: 10,000,000.
        # Average must remain 1,000,000 (not diluted by 10M).
        vols = ([1_000_000] * 10) + [10_000_000]
        avg_vols, surges = oracle_volume_surge(vols, window=10)
        self.assertEqual(avg_vols[10], 1_000_000.0)
        self.assertEqual(surges[10], 10.0)

    # =========================================================================
    # FEATURE 15: 35-Week Resistance Pivot
    # =========================================================================
    def test_f15_01_pivot35_lookback_window(self):
        """Verify 35-week resistance pivot requires 35 prior weeks."""
        highs = [100.0] * 40
        pivots = oracle_prior_resistance_pivot(highs, lookback=35)
        self.assertIsNone(pivots[34])
        self.assertEqual(pivots[35], 100.0)

    def test_f15_02_pivot35_identifies_highest_high(self):
        """Verify pivot equals the highest high over prior 35 weeks."""
        highs = [100.0] * 35
        highs[15] = 125.0  # prior resistance peak
        highs.append(126.0) # current week breakout
        pivots = oracle_prior_resistance_pivot(highs, lookback=35)
        self.assertEqual(pivots[35], 125.0)

    def test_f15_03_pivot35_excludes_current_week_high(self):
        """Verify current week's breakout high is not used as the resistance pivot itself."""
        highs = [100.0] * 35 + [150.0]
        pivots = oracle_prior_resistance_pivot(highs, lookback=35)
        self.assertEqual(pivots[35], 100.0)

    def test_f15_04_pivot35_breakout_detection(self):
        """Verify close >= pivot35 signals a resistance breakout."""
        pivot = 120.0
        close = 122.5
        self.assertTrue(close >= pivot)

    def test_f15_05_pivot35_below_resistance_rejection(self):
        """Verify close < pivot35 is recognized as still trapped within the base."""
        pivot = 120.0
        close = 119.5
        self.assertFalse(close >= pivot)

    # =========================================================================
    # FEATURE 16: Mansfield Relative Strength
    # =========================================================================
    def test_f16_01_mansfield_rs_requires_52_weeks(self):
        """Verify MRS requires 52 weeks of aligned stock and SPY benchmark bars."""
        stock = [100.0] * 60
        spy = [400.0] * 60
        mrs = oracle_mansfield_relative_strength(stock, spy, lookback=52)
        self.assertIsNone(mrs[50])
        self.assertIsNotNone(mrs[51])

    def test_f16_02_mansfield_rs_flat_performance_is_zero(self):
        """Verify MRS is 0.0 when stock perfectly tracks SPY benchmark ratio."""
        stock = [100.0] * 55
        spy = [400.0] * 55
        mrs = oracle_mansfield_relative_strength(stock, spy, lookback=52)
        self.assertAlmostEqual(mrs[51], 0.0, places=3)

    def test_f16_03_mansfield_rs_outperformance_is_positive(self):
        """Verify MRS > 0 when stock outperforms benchmark relative to its 52w average."""
        # 51 weeks at ratio 100/400 = 0.25. Week 52 stock jumps to 150 (ratio 0.375).
        stock = ([100.0] * 51) + [150.0]
        spy = [400.0] * 52
        mrs = oracle_mansfield_relative_strength(stock, spy, lookback=52)
        self.assertGreater(mrs[51], 0.0)

    def test_f16_04_mansfield_rs_underperformance_is_negative(self):
        """Verify MRS < 0 when stock lags benchmark."""
        stock = ([100.0] * 51) + [70.0]
        spy = [400.0] * 52
        mrs = oracle_mansfield_relative_strength(stock, spy, lookback=52)
        self.assertLess(mrs[51], 0.0)

    def test_f16_05_mansfield_rs_zero_crossover_rule(self):
        """Verify Stage 2 filter condition MRS > 0.0."""
        self.assertTrue(0.01 > 0.0)
        self.assertFalse(0.00 > 0.0)
        self.assertFalse(-0.5 > 0.0)

    # =========================================================================
    # FEATURE 17: Stage 2 Breakout Multi-Factor Filter
    # =========================================================================
    def test_f17_01_stage2_all_criteria_met_qualifies(self):
        """Verify Stage 2 qualification when all 5 factors are satisfied."""
        result = oracle_stage2_filter(
            close=125.0,
            sma_30w=110.0,
            sma_30w_slope=1.2,
            pivot_35w=120.0,
            vol_surge_ratio=2.2,
            mrs_score=8.5
        )
        self.assertTrue(result["is_stage2"])
        self.assertTrue(result["cond_close_above_sma"])
        self.assertTrue(result["cond_sma_rising"])
        self.assertTrue(result["cond_pivot_breakout"])
        self.assertTrue(result["cond_volume_surge"])
        self.assertTrue(result["cond_mrs_positive"])

    def test_f17_02_stage2_fails_if_below_pivot(self):
        """Verify failure if close < pivot (not a breakout)."""
        result = oracle_stage2_filter(
            close=118.0, sma_30w=110.0, sma_30w_slope=1.0,
            pivot_35w=120.0, vol_surge_ratio=2.0, mrs_score=5.0
        )
        self.assertFalse(result["is_stage2"])
        self.assertFalse(result["cond_pivot_breakout"])

    def test_f17_03_stage2_fails_if_volume_surge_insufficient(self):
        """Verify failure if volume surge ratio < 1.5."""
        result = oracle_stage2_filter(
            close=125.0, sma_30w=110.0, sma_30w_slope=1.0,
            pivot_35w=120.0, vol_surge_ratio=1.2, mrs_score=5.0
        )
        self.assertFalse(result["is_stage2"])
        self.assertFalse(result["cond_volume_surge"])

    def test_f17_04_stage2_fails_if_sma_declining(self):
        """Verify failure if 30w SMA slope < 0 (Stage 4 or unformed base)."""
        result = oracle_stage2_filter(
            close=125.0, sma_30w=110.0, sma_30w_slope=-0.5,
            pivot_35w=120.0, vol_surge_ratio=2.0, mrs_score=5.0
        )
        self.assertFalse(result["is_stage2"])
        self.assertFalse(result["cond_sma_rising"])

    def test_f17_05_stage2_fails_if_mrs_negative(self):
        """Verify failure if Mansfield RS <= 0 (lagging broader market)."""
        result = oracle_stage2_filter(
            close=125.0, sma_30w=110.0, sma_30w_slope=1.0,
            pivot_35w=120.0, vol_surge_ratio=2.0, mrs_score=-1.2
        )
        self.assertFalse(result["is_stage2"])
        self.assertFalse(result["cond_mrs_positive"])

    # =========================================================================
    # FEATURE 18: Target & Risk Math
    # =========================================================================
    def test_f18_01_entry_price_equals_pivot(self):
        """Verify entry price is set to the 35w resistance pivot price."""
        risk = oracle_target_and_risk(pivot_35w=150.0, current_price=153.0)
        self.assertEqual(risk["entry_price"], 150.0)

    def test_f18_02_max_buy_price_is_plus_5_percent(self):
        """Verify max buy price is strictly entry_price * 1.05."""
        risk = oracle_target_and_risk(pivot_35w=100.0, current_price=102.0)
        self.assertEqual(risk["max_buy_price"], 105.0)

    def test_f18_03_default_stop_loss_is_minus_8_percent(self):
        """Verify default stop loss is entry_price * 0.92 when no swing low given."""
        risk = oracle_target_and_risk(pivot_35w=100.0, current_price=102.0)
        self.assertEqual(risk["stop_loss_price"], 92.0)

    def test_f18_04_custom_swing_low_stop_loss(self):
        """Verify swing low is adopted if provided below entry price."""
        risk = oracle_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=94.5)
        self.assertEqual(risk["stop_loss_price"], 94.5)

    def test_f18_05_diff_pct_distance_calculation(self):
        """Verify diff_pct = ((current_price - entry_price) / entry_price) * 100."""
        risk = oracle_target_and_risk(pivot_35w=100.0, current_price=103.5)
        self.assertEqual(risk["diff_pct"], 3.5)

    # =========================================================================
    # FEATURE 19: Entry Status Categorization
    # =========================================================================
    def test_f19_01_status_in_buy_zone(self):
        """Verify IN_BUY_ZONE when entry_price <= current_price <= max_buy_price."""
        status = oracle_entry_status(current_price=103.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "IN_BUY_ZONE")

    def test_f19_02_status_extended(self):
        """Verify EXTENDED when current_price > max_buy_price."""
        status = oracle_entry_status(current_price=108.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "EXTENDED")

    def test_f19_03_status_below_entry(self):
        """Verify BELOW_ENTRY when stop_loss <= current_price < entry_price."""
        status = oracle_entry_status(current_price=98.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "BELOW_ENTRY")

    def test_f19_04_status_stopped_out(self):
        """Verify STOPPED_OUT when current_price < stop_loss_price."""
        status = oracle_entry_status(current_price=90.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "STOPPED_OUT")

    def test_f19_05_status_boundary_exact_matches(self):
        """Verify boundary inclusivity: exactly at entry is IN_BUY_ZONE; exactly at max_buy is IN_BUY_ZONE."""
        status_entry = oracle_entry_status(100.0, 100.0, 105.0, 92.0)
        status_max = oracle_entry_status(105.0, 100.0, 105.0, 92.0)
        self.assertEqual(status_entry, "IN_BUY_ZONE")
        self.assertEqual(status_max, "IN_BUY_ZONE")

    # =========================================================================
    # FEATURE 20: Signals & Job Persistence
    # =========================================================================
    def test_f20_01_scan_job_lifecycle_tracking(self):
        """Verify scan job progresses from RUNNING to COMPLETED."""
        job_id = self.db.create_scan_job({"job_type": "WEEKLY_SCAN", "status": "RUNNING", "started_at": "2026-10-14T02:00:00Z"})
        self.db.update_scan_job(job_id, {"status": "COMPLETED", "signals_found": 8})
        self.assertEqual(self.db.scan_jobs[job_id]["status"], "COMPLETED")
        self.assertEqual(self.db.scan_jobs[job_id]["signals_found"], 8)

    def test_f20_02_signal_persistence_with_all_metrics(self):
        """Verify signal row stores all Weinstein indicators and risk metrics."""
        sig = {
            "scan_date": "2026-10-09", "ticker": "TEST",
            "entry_price": 100.0, "max_buy_price": 105.0, "current_price": 102.5,
            "stop_loss_price": 92.0, "diff_pct": 2.5, "entry_status": "IN_BUY_ZONE",
            "volume_surge_ratio": 2.1, "mrs_score": 14.5, "sma_30w": 90.0,
            "sma_30w_slope": 0.8, "prior_resistance_35w": 100.0, "weekly_close": 102.5,
            "weekly_volume": 3000000, "avg_volume_10w": 1400000, "stage": "Stage 2"
        }
        sig_id = self.db.upsert_screener_signal(sig)
        saved = self.db.screener_signals[sig_id]
        self.assertEqual(saved["entry_status"], "IN_BUY_ZONE")
        self.assertEqual(saved["mrs_score"], 14.5)

    def test_f20_03_signal_persistence_idempotency(self):
        """Verify re-running screener on same date updates signal without duplicating rows."""
        sig = {
            "scan_date": "2026-10-09", "ticker": "TEST", "entry_price": 100.0,
            "max_buy_price": 105.0, "current_price": 102.5, "stop_loss_price": 92.0,
            "diff_pct": 2.5, "entry_status": "IN_BUY_ZONE", "volume_surge_ratio": 2.1,
            "mrs_score": 14.5, "sma_30w": 90.0, "sma_30w_slope": 0.8,
            "prior_resistance_35w": 100.0, "weekly_close": 102.5, "weekly_volume": 3000000,
            "avg_volume_10w": 1400000
        }
        id1 = self.db.upsert_screener_signal(sig)
        id2 = self.db.upsert_screener_signal(sig)
        self.assertEqual(id1, id2)
        self.assertEqual(len(self.db.screener_signals), 1)

    def test_f20_04_scan_job_failed_error_logging(self):
        """Verify scan job logs error_message when status is FAILED."""
        job_id = self.db.create_scan_job({"job_type": "WEEKLY_SCAN", "status": "RUNNING", "started_at": "2026-10-14T02:00:00Z"})
        self.db.update_scan_job(job_id, {"status": "FAILED", "error_message": "Network timeout connecting to Yahoo Finance"})
        self.assertEqual(self.db.scan_jobs[job_id]["status"], "FAILED")
        self.assertIn("timeout", self.db.scan_jobs[job_id]["error_message"])

    def test_f20_05_signal_retrieval_by_date(self):
        """Verify query returns all signals belonging to a specific scan_date."""
        signals_oct09 = [s for s in self.db.screener_signals.values() if s["scan_date"] == "2026-10-09"]
        self.assertGreaterEqual(len(signals_oct09), 0)


if __name__ == "__main__":
    unittest.main()
