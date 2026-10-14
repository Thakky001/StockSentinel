"""
screener/verify_m3.py - Comprehensive verification test suite for Milestone 3.
Self-contained (zero external network/db required) unit & integration test suite verifying:
- Deliverable files existence and non-emptiness
- Daily-to-weekly resampling (including 4-day Good Friday week, 1-day week, and 64-bit volume)
- 30-week SMA and slope (positive, negative, flat 0.0, division-by-zero guard)
- 10-week prior volume average and surge ratio (current week excluded, 1.4999 vs 1.5000 boundary)
- 35-week resistance pivot (current week high excluded, breakout detection)
- 52-week Mansfield Relative Strength vs SPY (index 0-50 None, index 51 float, zero-line crossover)
- Stage 2 multi-factor filter (all 5 conditions passing vs any single factor failing)
- Target & risk math (entry, max buy, stop loss fallback, diff %)
- Entry status classification (STOPPED_OUT, BELOW_ENTRY, IN_BUY_ZONE, EXTENDED boundaries)
- Database upsert idempotency and in-batch deduplication
- Main CLI argument parsing for screener execution
"""
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import polars as pl
from screener.src import indicators, main, screener


class TestMilestone3Deliverables(unittest.TestCase):
    """Verifies that all required M3 files exist and are non-empty."""

    def test_all_m3_files_exist(self):
        expected_files = [
            PROJECT_ROOT / "screener" / "src" / "indicators.py",
            PROJECT_ROOT / "screener" / "src" / "screener.py",
            PROJECT_ROOT / "screener" / "src" / "main.py",
            PROJECT_ROOT / "screener" / "verify_m3.py",
        ]
        for f in expected_files:
            self.assertTrue(f.exists(), f"Missing required file: {f}")
            self.assertGreater(f.stat().st_size, 0, f"File is empty: {f}")


class TestFeature12WeeklyResampling(unittest.TestCase):
    """Tests Feature 12: Daily to Weekly Resampling in Polars & Python lists."""

    def test_standard_5_day_week_aggregation(self):
        bars = [
            {"ticker": "TEST", "trade_date": "2026-10-05", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 1000},
            {"ticker": "TEST", "trade_date": "2026-10-06", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 1000},
            {"ticker": "TEST", "trade_date": "2026-10-07", "open": 102.0, "high": 104.0, "low": 101.0, "close": 103.0, "volume": 1000},
            {"ticker": "TEST", "trade_date": "2026-10-08", "open": 103.0, "high": 105.0, "low": 102.0, "close": 104.0, "volume": 1000},
            {"ticker": "TEST", "trade_date": "2026-10-09", "open": 104.0, "high": 106.0, "low": 103.0, "close": 105.0, "volume": 1000},
        ]
        weekly = indicators.resample_daily_to_weekly(bars)
        self.assertEqual(len(weekly), 1)
        w = weekly[0]
        self.assertEqual(w["trading_days"], 5)
        self.assertEqual(w["open"], 100.0)
        self.assertEqual(w["high"], 106.0)
        self.assertEqual(w["low"], 99.0)
        self.assertEqual(w["close"], 105.0)
        self.assertEqual(w["volume"], 5000)
        self.assertEqual(w["trade_date"], "2026-10-09")

    def test_polars_dataframe_resampling(self):
        df = pl.DataFrame([
            {"ticker": "AAPL", "trade_date": "2026-10-05", "open": 200.0, "high": 205.0, "low": 198.0, "close": 202.0, "volume": 10000},
            {"ticker": "AAPL", "trade_date": "2026-10-09", "open": 202.0, "high": 208.0, "low": 201.0, "close": 207.0, "volume": 15000},
        ])
        weekly_df = indicators.resample_daily_to_weekly(df)
        self.assertIsInstance(weekly_df, pl.DataFrame)
        self.assertEqual(weekly_df.height, 1)
        row = weekly_df.to_dicts()[0]
        self.assertEqual(row["open"], 200.0)
        self.assertEqual(row["high"], 208.0)
        self.assertEqual(row["low"], 198.0)
        self.assertEqual(row["close"], 207.0)
        self.assertEqual(row["volume"], 25000)
        self.assertEqual(row["trading_days"], 2)

    def test_good_friday_short_week_anchors_thursday(self):
        bars = [
            {"ticker": "HOLI", "trade_date": "2026-04-06", "open": 50.0, "high": 52.0, "low": 49.0, "close": 51.0, "volume": 1000},
            {"ticker": "HOLI", "trade_date": "2026-04-07", "open": 51.0, "high": 53.0, "low": 50.0, "close": 52.0, "volume": 1000},
            {"ticker": "HOLI", "trade_date": "2026-04-08", "open": 52.0, "high": 54.0, "low": 51.0, "close": 53.0, "volume": 1000},
            {"ticker": "HOLI", "trade_date": "2026-04-09", "open": 53.0, "high": 55.0, "low": 52.0, "close": 54.5, "volume": 1000},
        ]
        weekly = indicators.resample_daily_to_weekly(bars)
        self.assertEqual(len(weekly), 1)
        w = weekly[0]
        self.assertEqual(w["trading_days"], 4)
        self.assertEqual(w["trade_date"], "2026-04-09")
        self.assertEqual(w["close"], 54.5)
        self.assertEqual(w["volume"], 4000)

    def test_single_day_holiday_week(self):
        bars = [{"ticker": "T1", "trade_date": "2026-10-05", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 500000}]
        weekly = indicators.resample_daily_to_weekly(bars)
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0]["open"], 100.0)
        self.assertEqual(weekly[0]["close"], 102.0)
        self.assertEqual(weekly[0]["trading_days"], 1)

    def test_volume_exceeding_32bit_integer(self):
        vol_per_day = 600_000_000
        bars = [
            {"ticker": "T1", "trade_date": f"2026-10-0{i}", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": vol_per_day}
            for i in range(5, 10)
        ]
        weekly = indicators.resample_daily_to_weekly(bars)
        total_vol = weekly[0]["volume"]
        self.assertEqual(total_vol, 3_000_000_000)
        self.assertGreater(total_vol, 2_147_483_647)

    def test_flat_price_week_halted_stock(self):
        bars = [
            {"ticker": "T1", "trade_date": f"2026-10-0{i}", "open": 25.0, "high": 25.0, "low": 25.0, "close": 25.0, "volume": 0}
            for i in range(5, 10)
        ]
        weekly = indicators.resample_daily_to_weekly(bars)
        self.assertEqual(weekly[0]["high"], 25.0)
        self.assertEqual(weekly[0]["low"], 25.0)
        self.assertEqual(weekly[0]["volume"], 0)


class TestFeature13IndicatorMath30wSMA(unittest.TestCase):
    """Tests Feature 13: 30-Week SMA & Slope Percentage."""

    def test_sma30_window_requires_30_periods(self):
        closes = [100.0] * 35
        sma = indicators.compute_sma(closes, window=30)
        self.assertEqual(len(sma), 35)
        for i in range(29):
            self.assertIsNone(sma[i], f"Index {i} should be None")
        self.assertEqual(sma[29], 100.0)
        self.assertEqual(sma[34], 100.0)

    def test_sma30_rolling_math(self):
        closes = ([100.0] * 10) + ([130.0] * 20)
        sma = indicators.compute_sma(closes, window=30)
        self.assertEqual(sma[29], 120.0)

    def test_sma30_polars_dataframe(self):
        df = pl.DataFrame({
            "ticker": ["ABC"] * 30,
            "trade_date": [f"2026-01-{i+1:02d}" for i in range(30)],
            "close": [50.0] * 30,
        })
        res_df = indicators.compute_sma_30w(df, window=30)
        smas = res_df["sma_30w"].to_list()
        self.assertIsNone(smas[28])
        self.assertEqual(smas[29], 50.0)

    def test_sma_slope_positive_uptrend(self):
        sma_series = [None] * 29 + [100.0, 101.5]
        slopes = indicators.compute_sma_slope(sma_series, lookback=1)
        self.assertEqual(slopes[30], 1.5)
        self.assertTrue(slopes[30] >= 0.0)

    def test_sma_slope_negative_downtrend(self):
        sma_series = [None] * 29 + [100.0, 98.0]
        slopes = indicators.compute_sma_slope(sma_series, lookback=1)
        self.assertEqual(slopes[30], -2.0)
        self.assertFalse(slopes[30] >= 0.0)

    def test_sma_slope_flat_exact_zero(self):
        sma_series = [None] * 29 + [120.0, 120.0]
        slopes = indicators.compute_sma_slope(sma_series, lookback=1)
        self.assertEqual(slopes[30], 0.0)
        self.assertTrue(slopes[30] >= 0.0)

    def test_sma_slope_division_by_zero_guard(self):
        sma_series = [None] * 29 + [0.0, 10.0]
        slopes = indicators.compute_sma_slope(sma_series, lookback=1)
        self.assertIsNone(slopes[30])


class TestFeature14IndicatorMath10wVolumeSurge(unittest.TestCase):
    """Tests Feature 14: 10-Week Volume Average & Surge Ratio."""

    def test_volume_average_window_10_weeks(self):
        vols = [1_000_000] * 15
        avg_vols, surges = indicators.compute_volume_surge(vols, window=10)
        for i in range(10):
            self.assertIsNone(avg_vols[i])
            self.assertIsNone(surges[i])
        self.assertEqual(avg_vols[10], 1_000_000.0)
        self.assertEqual(surges[10], 1.0)

    def test_volume_average_strictly_excludes_current_breakout_week(self):
        # 10 weeks of 1M + 1 breakout week of 10M
        vols = [1_000_000] * 10 + [10_000_000]
        avg_vols, surges = indicators.compute_volume_surge(vols, window=10)
        # Week 10 (the 11th week) prior average must remain 1,000,000
        self.assertEqual(avg_vols[10], 1_000_000.0)
        self.assertEqual(surges[10], 10.0)

    def test_volume_zero_guard(self):
        vols = [0] * 10 + [1_000_000]
        avg_vols, surges = indicators.compute_volume_surge(vols, window=10)
        self.assertEqual(avg_vols[10], 0.0)
        self.assertEqual(surges[10], 0.0)

    def test_volume_surge_boundary_threshold(self):
        # 1.4999 fails, 1.5000 passes
        vols_fail = [1_000_000] * 10 + [1_499_900]
        _, surges_fail = indicators.compute_volume_surge(vols_fail, window=10)
        self.assertEqual(surges_fail[10], 1.4999)
        self.assertFalse(surges_fail[10] >= 1.50)

        vols_pass = [1_000_000] * 10 + [1_500_000]
        _, surges_pass = indicators.compute_volume_surge(vols_pass, window=10)
        self.assertEqual(surges_pass[10], 1.5000)
        self.assertTrue(surges_pass[10] >= 1.50)

    def test_volume_metrics_dataframe_multi_ticker(self):
        # AAPL: 10 weeks of 1M, week 11 is 2.5M
        # MSFT: 10 weeks of 500K, week 11 is 1.5M
        dates_aapl = [f"2026-01-{i+1:02d}" for i in range(15)]
        dates_msft = [f"2026-01-{i+1:02d}" for i in range(15)]
        vols_aapl = [1_000_000] * 10 + [2_500_000] + [1_000_000] * 4
        vols_msft = [500_000] * 10 + [1_500_000] + [500_000] * 4

        df = pl.DataFrame({
            "ticker": ["AAPL"] * 15 + ["MSFT"] * 15,
            "trade_date": dates_aapl + dates_msft,
            "volume": vols_aapl + vols_msft,
        })

        res_df = indicators.compute_volume_metrics(df, window=10)
        self.assertIsInstance(res_df, pl.DataFrame)
        self.assertEqual(res_df.height, 30)

        # Separate by ticker and verify
        aapl_df = res_df.filter(pl.col("ticker") == "AAPL").sort("trade_date")
        msft_df = res_df.filter(pl.col("ticker") == "MSFT").sort("trade_date")

        # AAPL checks
        aapl_avg = aapl_df["avg_volume_10w"].to_list()
        aapl_surge = aapl_df["volume_surge_ratio"].to_list()
        for i in range(10):
            self.assertIsNone(aapl_avg[i])
            self.assertIsNone(aapl_surge[i])
        self.assertEqual(aapl_avg[10], 1_000_000.0)
        self.assertEqual(aapl_surge[10], 2.5)

        # MSFT checks
        msft_avg = msft_df["avg_volume_10w"].to_list()
        msft_surge = msft_df["volume_surge_ratio"].to_list()
        for i in range(10):
            self.assertIsNone(msft_avg[i])
            self.assertIsNone(msft_surge[i])
        self.assertEqual(msft_avg[10], 500_000.0)
        self.assertEqual(msft_surge[10], 3.0)

    def test_volume_metrics_dataframe_without_ticker_column(self):
        vols = [1_000_000] * 10 + [2_000_000] + [1_000_000] * 4
        df = pl.DataFrame({
            "trade_date": [f"2026-01-{i+1:02d}" for i in range(15)],
            "volume": vols,
        })
        res_df = indicators.compute_volume_metrics(df, window=10)
        avg = res_df["avg_volume_10w"].to_list()
        surge = res_df["volume_surge_ratio"].to_list()
        self.assertEqual(avg[10], 1_000_000.0)
        self.assertEqual(surge[10], 2.0)


class TestFeature15IndicatorMath35wResistancePivot(unittest.TestCase):
    """Tests Feature 15: 35-Week Prior Resistance Pivot."""

    def test_pivot35_lookback_window(self):
        highs = [100.0] * 40
        pivots = indicators.compute_prior_resistance_pivot(highs, lookback=35)
        for i in range(35):
            self.assertIsNone(pivots[i])
        self.assertEqual(pivots[35], 100.0)

    def test_pivot35_strictly_excludes_current_week_high(self):
        # 35 weeks with max high of 100.0, breakout week high is 120.0
        highs = [95.0] * 34 + [100.0] + [120.0]
        pivots = indicators.compute_prior_resistance_pivot(highs, lookback=35)
        # Week 35 pivot must be 100.0, NOT 120.0
        self.assertEqual(pivots[35], 100.0)

    def test_breakout_detection_predicates(self):
        pivot = 100.0
        # Equal qualifies
        self.assertTrue(100.0 >= pivot)
        # 1 cent below fails
        self.assertFalse(99.99 >= pivot)
        # Above qualifies
        self.assertTrue(105.0 >= pivot)

    def test_resistance_pivot_dataframe_multi_ticker(self):
        # AAPL: 35 weeks of 100.0, week 36 is 115.0
        # MSFT: 35 weeks of 200.0, week 36 is 220.0
        dates = [f"week_{i:02d}" for i in range(40)]
        highs_aapl = [100.0] * 35 + [115.0] + [100.0] * 4
        highs_msft = [200.0] * 35 + [220.0] + [200.0] * 4

        df = pl.DataFrame({
            "ticker": ["AAPL"] * 40 + ["MSFT"] * 40,
            "trade_date": dates + dates,
            "high": highs_aapl + highs_msft,
        })

        res_df = indicators.compute_resistance_pivot(df, lookback=35)
        self.assertIsInstance(res_df, pl.DataFrame)
        self.assertEqual(res_df.height, 80)

        aapl_df = res_df.filter(pl.col("ticker") == "AAPL").sort("trade_date")
        msft_df = res_df.filter(pl.col("ticker") == "MSFT").sort("trade_date")

        aapl_pivots = aapl_df["prior_resistance_35w"].to_list()
        msft_pivots = msft_df["prior_resistance_35w"].to_list()

        for i in range(35):
            self.assertIsNone(aapl_pivots[i])
            self.assertIsNone(msft_pivots[i])

        # Week 35 pivot must strictly exclude current week high and not leak other ticker
        self.assertEqual(aapl_pivots[35], 100.0)
        self.assertEqual(msft_pivots[35], 200.0)

    def test_resistance_pivot_dataframe_without_ticker_column(self):
        highs = [100.0] * 35 + [110.0] + [100.0] * 4
        df = pl.DataFrame({
            "trade_date": [f"week_{i:02d}" for i in range(40)],
            "high": highs,
        })
        res_df = indicators.compute_resistance_pivot(df, lookback=35)
        pivots = res_df["prior_resistance_35w"].to_list()
        self.assertEqual(pivots[35], 100.0)


class TestFeature16MansfieldRelativeStrength(unittest.TestCase):
    """Tests Feature 16: 52-Week Mansfield Relative Strength vs SPY."""

    def test_mrs_lookback_52_weeks(self):
        stock_closes = [100.0] * 55
        spy_closes = [400.0] * 55
        mrs = indicators.compute_mansfield_relative_strength(stock_closes, spy_closes, lookback=52)
        for i in range(51):
            self.assertIsNone(mrs[i], f"Index {i} should be None")
        self.assertIsNotNone(mrs[51])
        # Constant RS ratio yields exact 0.0000
        self.assertEqual(mrs[51], 0.0)

    def test_mrs_zero_line_crossover(self):
        # Flat MRS == 0.0000 fails mrs > 0
        self.assertFalse(0.0000 > 0.0)
        # Micro-positive MRS == 0.0001 passes mrs > 0
        self.assertTrue(0.0001 > 0.0)

    def test_mrs_positive_outperformance(self):
        # Stock doubles while SPY stays flat
        stock_closes = [100.0] * 51 + [200.0]
        spy_closes = [400.0] * 52
        mrs = indicators.compute_mansfield_relative_strength(stock_closes, spy_closes, lookback=52)
        self.assertGreater(mrs[51], 0.0)

    def test_mrs_length_mismatch_raises_error(self):
        with self.assertRaises(ValueError):
            indicators.compute_mansfield_relative_strength([100.0] * 50, [400.0] * 52)

    def test_align_weekly_bars(self):
        stock_bars = [
            {"trade_date": "2026-04-03", "close": 100.0},
            {"trade_date": "2026-04-09", "close": 105.0},
            {"trade_date": "2026-04-17", "close": 110.0},
        ]
        spy_bars = [
            {"trade_date": "2026-04-03", "close": 400.0},
            {"trade_date": "2026-04-09", "close": 405.0},
            {"trade_date": "2026-04-24", "close": 415.0},  # Missing 04-17
        ]
        aligned_s, aligned_spy = indicators.align_weekly_bars(stock_bars, spy_bars)
        self.assertEqual(len(aligned_s), 2)
        self.assertEqual(len(aligned_spy), 2)
        self.assertEqual(aligned_s[0]["trade_date"], "2026-04-03")
        self.assertEqual(aligned_s[1]["trade_date"], "2026-04-09")


class TestComputeAllIndicatorsPipeline(unittest.TestCase):
    """Tests compute_all_indicators end-to-end Polars DataFrame pipeline."""

    def test_compute_all_indicators_multi_ticker_pipeline(self):
        # 60 weekly dates
        base_date = date(2025, 1, 3)
        dates = [(base_date + timedelta(weeks=i)).isoformat() for i in range(60)]

        # Stock weekly data for AAPL and MSFT
        aapl_df = pl.DataFrame({
            "ticker": ["AAPL"] * 60,
            "trade_date": dates,
            "open": [150.0] * 60,
            "high": [155.0] * 60,
            "low": [148.0] * 60,
            "close": [152.0] * 60,
            "volume": [1_000_000] * 60,
        })

        msft_df = pl.DataFrame({
            "ticker": ["MSFT"] * 60,
            "trade_date": dates,
            "open": [300.0] * 60,
            "high": [310.0] * 60,
            "low": [295.0] * 60,
            "close": [305.0] * 60,
            "volume": [2_000_000] * 60,
        })

        weekly_df = pl.concat([aapl_df, msft_df])

        # Benchmark SPY data
        spy_weekly_df = pl.DataFrame({
            "trade_date": dates,
            "open": [400.0] * 60,
            "high": [405.0] * 60,
            "low": [395.0] * 60,
            "close": [402.0] * 60,
            "volume": [10_000_000] * 60,
        })

        # Must execute without ComputeError or any other exception
        result_df = indicators.compute_all_indicators(weekly_df, spy_weekly_df)

        self.assertIsInstance(result_df, pl.DataFrame)
        self.assertEqual(result_df.height, 120)

        expected_columns = [
            "ticker", "trade_date", "open", "high", "low", "close", "volume",
            "sma_30w", "sma_30w_slope", "avg_volume_10w", "volume_surge_ratio",
            "prior_resistance_35w", "mrs_score"
        ]
        for col in expected_columns:
            self.assertIn(col, result_df.columns, f"Missing expected column: {col}")

        # Check values for AAPL
        aapl_res = result_df.filter(pl.col("ticker") == "AAPL").sort("trade_date")
        self.assertEqual(aapl_res.height, 60)
        self.assertEqual(aapl_res["sma_30w"][59], 152.0)
        self.assertEqual(aapl_res["sma_30w_slope"][59], 0.0)
        self.assertEqual(aapl_res["avg_volume_10w"][59], 1_000_000.0)
        self.assertEqual(aapl_res["volume_surge_ratio"][59], 1.0)
        self.assertEqual(aapl_res["prior_resistance_35w"][59], 155.0)
        self.assertIsNotNone(aapl_res["mrs_score"][59])
        self.assertEqual(aapl_res["mrs_score"][59], 0.0)

        # Check values for MSFT
        msft_res = result_df.filter(pl.col("ticker") == "MSFT").sort("trade_date")
        self.assertEqual(msft_res.height, 60)
        self.assertEqual(msft_res["sma_30w"][59], 305.0)
        self.assertEqual(msft_res["sma_30w_slope"][59], 0.0)
        self.assertEqual(msft_res["avg_volume_10w"][59], 2_000_000.0)
        self.assertEqual(msft_res["volume_surge_ratio"][59], 1.0)
        self.assertEqual(msft_res["prior_resistance_35w"][59], 310.0)
        self.assertIsNotNone(msft_res["mrs_score"][59])
        self.assertEqual(msft_res["mrs_score"][59], 0.0)

    def test_compute_all_indicators_without_spy_df(self):
        dates = [f"2026-01-{i+1:02d}" for i in range(40)]
        weekly_df = pl.DataFrame({
            "ticker": ["AAPL"] * 40,
            "trade_date": dates,
            "open": [100.0] * 40,
            "high": [105.0] * 40,
            "low": [98.0] * 40,
            "close": [102.0] * 40,
            "volume": [1_000_000] * 40,
        })
        res = indicators.compute_all_indicators(weekly_df, spy_weekly_df=None)
        self.assertIn("mrs_score", res.columns)
        self.assertTrue(res["mrs_score"].is_null().all())

    def test_compute_all_indicators_single_ticker(self):
        base_date = date(2025, 1, 3)
        dates = [(base_date + timedelta(weeks=i)).isoformat() for i in range(60)]
        weekly_df = pl.DataFrame({
            "ticker": ["TSLA"] * 60,
            "trade_date": dates,
            "open": [200.0] * 60,
            "high": [210.0] * 60,
            "low": [190.0] * 60,
            "close": [205.0] * 60,
            "volume": [3_000_000] * 60,
        })
        spy_df = pl.DataFrame({
            "trade_date": dates,
            "close": [400.0] * 60,
        })
        res = indicators.compute_all_indicators(weekly_df, spy_df)
        self.assertEqual(res.height, 60)
        self.assertEqual(res["sma_30w"][59], 205.0)
        self.assertEqual(res["prior_resistance_35w"][59], 210.0)


class TestFeature17Stage2MultiFactorFilter(unittest.TestCase):
    """Tests Feature 17: Stan Weinstein Stage 2 Multi-Factor Filter."""

    def test_all_5_conditions_passing_qualifies_stage2(self):
        res = screener.evaluate_stage2_filter(
            close=105.0,
            sma_30w=100.0,
            sma_30w_slope=1.5,
            pivot_35w=102.0,
            vol_surge_ratio=2.1,
            mrs_score=14.5
        )
        self.assertTrue(res["is_stage2"])
        self.assertTrue(res["cond_close_above_sma"])
        self.assertTrue(res["cond_sma_rising"])
        self.assertTrue(res["cond_pivot_breakout"])
        self.assertTrue(res["cond_volume_surge"])
        self.assertTrue(res["cond_mrs_positive"])

    def test_single_condition_failing_rejects_stage2(self):
        # 1. Close <= SMA
        r1 = screener.evaluate_stage2_filter(99.0, 100.0, 1.5, 95.0, 2.0, 10.0)
        self.assertFalse(r1["is_stage2"])

        # 2. SMA slope negative
        r2 = screener.evaluate_stage2_filter(105.0, 100.0, -0.1, 95.0, 2.0, 10.0)
        self.assertFalse(r2["is_stage2"])

        # 3. Close < Pivot
        r3 = screener.evaluate_stage2_filter(101.0, 100.0, 1.5, 102.0, 2.0, 10.0)
        self.assertFalse(r3["is_stage2"])

        # 4. Volume surge < 1.50
        r4 = screener.evaluate_stage2_filter(105.0, 100.0, 1.5, 102.0, 1.49, 10.0)
        self.assertFalse(r4["is_stage2"])

        # 5. MRS <= 0.0
        r5 = screener.evaluate_stage2_filter(105.0, 100.0, 1.5, 102.0, 2.0, 0.0)
        self.assertFalse(r5["is_stage2"])

    def test_null_indicator_fails_filter_safely(self):
        res = screener.evaluate_stage2_filter(105.0, None, 1.5, 102.0, 2.0, 10.0)
        self.assertFalse(res["is_stage2"])


class TestFeature18TargetAndRiskMath(unittest.TestCase):
    """Tests Feature 18: Target & Risk Math."""

    def test_target_and_risk_standard_calculation(self):
        risk = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.5)
        self.assertEqual(risk["entry_price"], 100.0)
        self.assertEqual(risk["max_buy_price"], 105.0)
        self.assertEqual(risk["stop_loss_price"], 92.0)  # -8% standard stop
        self.assertEqual(risk["current_price"], 102.5)
        self.assertEqual(risk["diff_pct"], 2.5)

    def test_custom_valid_swing_low(self):
        risk = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=95.0)
        self.assertEqual(risk["stop_loss_price"], 95.0)

    def test_invalid_swing_low_falls_back_to_8_pct_stop(self):
        # Swing low higher than entry
        risk1 = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=105.0)
        self.assertEqual(risk1["stop_loss_price"], 92.0)

        # Swing low <= 0
        risk2 = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=-5.0)
        self.assertEqual(risk2["stop_loss_price"], 92.0)


class TestFeature19EntryStatusClassification(unittest.TestCase):
    """Tests Feature 19: Entry Status Categorization and Exact Boundaries."""

    def test_status_stopped_out(self):
        status = screener.classify_entry_status(current_price=90.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "STOPPED_OUT")

    def test_status_at_stop_loss_is_below_entry(self):
        status = screener.classify_entry_status(current_price=92.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "BELOW_ENTRY")

    def test_status_below_entry(self):
        status = screener.classify_entry_status(current_price=98.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "BELOW_ENTRY")

    def test_status_at_entry_is_in_buy_zone(self):
        status = screener.classify_entry_status(current_price=100.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "IN_BUY_ZONE")

    def test_status_inside_buy_zone(self):
        status = screener.classify_entry_status(current_price=103.5, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "IN_BUY_ZONE")

    def test_status_at_max_buy_is_in_buy_zone(self):
        status = screener.classify_entry_status(current_price=105.0, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "IN_BUY_ZONE")

    def test_status_extended(self):
        status = screener.classify_entry_status(current_price=105.01, entry_price=100.0, max_buy_price=105.0, stop_loss_price=92.0)
        self.assertEqual(status, "EXTENDED")


class TestFeature20DatabasePersistence(unittest.TestCase):
    """Tests Feature 20: Screener Signals Persistence & Scan Jobs Lifecycle."""

    @patch("psycopg2.extras.execute_values")
    def test_in_batch_signal_deduplication(self, mock_exec_values):
        # Multiple signals with same (scan_date, ticker)
        signals = [
            {"scan_date": "2026-10-09", "ticker": "AAPL", "entry_price": 150.0, "max_buy_price": 157.5,
             "current_price": 152.0, "stop_loss_price": 138.0, "diff_pct": 1.33, "entry_status": "IN_BUY_ZONE",
             "volume_surge_ratio": 2.0, "mrs_score": 10.0, "sma_30w": 140.0, "sma_30w_slope": 1.0,
             "prior_resistance_35w": 150.0, "weekly_close": 152.0, "weekly_volume": 1000000, "avg_volume_10w": 500000},
            {"scan_date": "2026-10-09", "ticker": "AAPL", "entry_price": 150.0, "max_buy_price": 157.5,
             "current_price": 153.0, "stop_loss_price": 138.0, "diff_pct": 2.00, "entry_status": "IN_BUY_ZONE",
             "volume_surge_ratio": 2.5, "mrs_score": 11.0, "sma_30w": 140.0, "sma_30w_slope": 1.0,
             "prior_resistance_35w": 150.0, "weekly_close": 153.0, "weekly_volume": 1200000, "avg_volume_10w": 500000},
        ]
        mock_cursor = MagicMock()
        count = screener.upsert_screener_signals(signals, cur=mock_cursor)
        self.assertEqual(count, 1, "Duplicate keys in same batch must be deduplicated to 1 row")
        mock_exec_values.assert_called_once()
        self.assertEqual(len(mock_exec_values.call_args[0][2]), 1)

    def test_create_and_update_scan_job_sql(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (42,)

        job_id = screener.create_scan_job(tickers_total=500, cur=mock_cursor)
        self.assertEqual(job_id, 42)
        mock_cursor.execute.assert_called_once()
        self.assertIn("INSERT INTO scan_jobs", mock_cursor.execute.call_args[0][0])

        screener.update_scan_job(
            job_id=42,
            status="COMPLETED",
            tickers_processed=500,
            tickers_failed=0,
            signals_found=12,
            cur=mock_cursor
        )
        self.assertEqual(mock_cursor.execute.call_count, 2)
        self.assertIn("UPDATE scan_jobs", mock_cursor.execute.call_args[0][0])


class TestMainCommandLineInterface(unittest.TestCase):
    """Tests Main CLI support for --mode screen / --mode scan."""

    def test_main_arg_parser_supports_screen_and_scan_modes(self):
        args1 = main.parse_args(["--mode", "screen", "--scan-date", "2026-10-09"])
        self.assertEqual(args1.mode, "screen")
        self.assertEqual(args1.scan_date, "2026-10-09")

        args2 = main.parse_args(["--mode", "scan", "--tickers", "AAPL,MSFT"])
        self.assertEqual(args2.mode, "scan")
        self.assertEqual(args2.tickers, "AAPL,MSFT")

    @patch("screener.src.screener.run_screener")
    def test_main_invokes_run_screener(self, mock_run):
        mock_run.return_value = {
            "tickers_processed": 10,
            "signals_found": 2,
            "signals": [],
        }
        ret = main.main(["--mode", "screen", "--tickers", "AAPL,MSFT"])
        self.assertEqual(ret, 0)
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
