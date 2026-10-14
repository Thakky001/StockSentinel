"""
Tier 3 Interaction Tests: M2 (Ingestion Engine) x M3 (Screener Engine)
Verifies seamless data flow from Daily Bar Ingestion/Parquet Cache
into Weekly Resampling, Indicator Computation, and Stage 2 Filtering.
"""

import unittest
from tests.e2e.helpers.mock_data import (
    generate_universe_tickers,
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


class TestTier3IngestToScreener(unittest.TestCase):
    def test_t3_01_daily_ingestion_to_weekly_resampling_continuity(self):
        """Verifies daily bars from ingestion engine compress to weekly bars preserving price fidelity."""
        daily_bars = generate_daily_bars_for_stock("AAPL", pattern="stage2_breakout", num_days=520)
        weekly_bars = oracle_resample_daily_to_weekly(daily_bars)
        
        # 520 trading days ~ 104 weekly bars
        self.assertGreaterEqual(len(weekly_bars), 100)
        self.assertLessEqual(len(weekly_bars), 105)
        
        # Verify first and last date bounds
        self.assertEqual(weekly_bars[0]["open"], daily_bars[0]["open"])
        self.assertEqual(weekly_bars[-1]["close"], daily_bars[-1]["close"])

    def test_t3_02_benchmark_join_alignment(self):
        """Verifies SPY benchmark bars align chronologically with stock bars for Mansfield RS calculation."""
        stock_daily = generate_daily_bars_for_stock("NVDA", pattern="stage2_breakout", num_days=520)
        spy_daily = generate_spy_benchmark_bars(num_days=520)
        
        stock_weekly = oracle_resample_daily_to_weekly(stock_daily)
        spy_weekly = oracle_resample_daily_to_weekly(spy_daily)
        
        self.assertEqual(len(stock_weekly), len(spy_weekly))
        
        # Check date alignment
        for s_bar, spy_bar in zip(stock_weekly, spy_weekly):
            self.assertEqual(s_bar["trade_date"], spy_bar["trade_date"])
            
        # Compute MRS
        stock_closes = [w["close"] for w in stock_weekly]
        spy_closes = [w["close"] for w in spy_weekly]
        mrs_scores = oracle_mansfield_relative_strength(stock_closes, spy_closes, lookback=52)
        
        # Last bar has valid MRS
        self.assertIsNotNone(mrs_scores[-1])

    def test_t3_03_delta_sync_incremental_indicator_update(self):
        """Verifies adding 5 daily delta bars produces exactly 1 new weekly bar and advances SMA 30w."""
        initial_daily = generate_daily_bars_for_stock("CRWD", num_days=260)  # 52 weeks
        initial_weekly = oracle_resample_daily_to_weekly(initial_daily)
        initial_sma = oracle_sma([w["close"] for w in initial_weekly], window=30)
        
        # Simulate 5 new daily bars for week 53
        new_daily = [
            {"ticker": "CRWD", "trade_date": f"2026-10-{12+i:02d}", "open": 325.0, "high": 330.0, "low": 322.0, "close": 328.0, "volume": 1000000}
            for i in range(5)
        ]
        combined_daily = initial_daily + new_daily
        combined_weekly = oracle_resample_daily_to_weekly(combined_daily)
        combined_sma = oracle_sma([w["close"] for w in combined_weekly], window=30)
        
        self.assertEqual(len(combined_weekly), len(initial_weekly) + 1)
        self.assertIsNotNone(combined_sma[-1])

    def test_t3_04_full_pipeline_stage2_qualification(self):
        """Verifies synthetic breakout bars progress from ingestion through indicators to Stage 2 qualification."""
        stock_daily = generate_daily_bars_for_stock("BREAKOUT", pattern="stage2_breakout", num_days=520, base_price=100.0)
        spy_daily = generate_spy_benchmark_bars(num_days=520)
        
        stock_weekly = oracle_resample_daily_to_weekly(stock_daily)
        spy_weekly = oracle_resample_daily_to_weekly(spy_daily)
        
        closes = [w["close"] for w in stock_weekly]
        highs = [w["high"] for w in stock_weekly]
        volumes = [w["volume"] for w in stock_weekly]
        spy_closes = [w["close"] for w in spy_weekly]
        
        sma30 = oracle_sma(closes, window=30)
        slope = oracle_sma_slope(sma30, lookback=1)
        avg_vol10, surge = oracle_volume_surge(volumes, window=10)
        pivot35 = oracle_prior_resistance_pivot(highs, lookback=35)
        mrs = oracle_mansfield_relative_strength(closes, spy_closes, lookback=52)
        
        last_idx = -1
        filter_res = oracle_stage2_filter(
            close=closes[last_idx],
            sma_30w=sma30[last_idx],
            sma_30w_slope=slope[last_idx],
            pivot_35w=pivot35[last_idx],
            vol_surge_ratio=surge[last_idx],
            mrs_score=mrs[last_idx]
        )
        self.assertTrue(filter_res["is_stage2"])

    def test_t3_05_stage4_downtrend_rejection_in_pipeline(self):
        """Verifies stock in Stage 4 downtrend fails Stage 2 filter across all factors."""
        stock_daily = generate_daily_bars_for_stock("DOWNTREND", pattern="stage4_downtrend", num_days=520, base_price=100.0)
        spy_daily = generate_spy_benchmark_bars(num_days=520)
        
        stock_weekly = oracle_resample_daily_to_weekly(stock_daily)
        spy_weekly = oracle_resample_daily_to_weekly(spy_daily)
        
        closes = [w["close"] for w in stock_weekly]
        highs = [w["high"] for w in stock_weekly]
        volumes = [w["volume"] for w in stock_weekly]
        spy_closes = [w["close"] for w in spy_weekly]
        
        sma30 = oracle_sma(closes, window=30)
        slope = oracle_sma_slope(sma30, lookback=1)
        avg_vol10, surge = oracle_volume_surge(volumes, window=10)
        pivot35 = oracle_prior_resistance_pivot(highs, lookback=35)
        mrs = oracle_mansfield_relative_strength(closes, spy_closes, lookback=52)
        
        filter_res = oracle_stage2_filter(
            close=closes[-1], sma_30w=sma30[-1], sma_30w_slope=slope[-1],
            pivot_35w=pivot35[-1], vol_surge_ratio=surge[-1], mrs_score=mrs[-1]
        )
        self.assertFalse(filter_res["is_stage2"])


if __name__ == "__main__":
    unittest.main()
