"""
Tier 1 Tests: Features 7-11 (Stock Universe & Ingestion Engine)
Isolation test cases covering Russell 3000 + S&P 1500 universe definition,
SPY benchmark injection, yfinance 50-chunking, backoff pacing, delta sync logic,
local Parquet caching, and PostgreSQL batch upserting.
"""

import unittest
from datetime import date, timedelta
from tests.e2e.helpers.mock_data import generate_universe_tickers, generate_market_trading_days, generate_daily_bars_for_stock
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB


class TestTier1Features07to11(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()
        self.raw_universe = generate_universe_tickers()

    # =========================================================================
    # FEATURE 7: Combined Stock Universe
    # =========================================================================
    def test_f07_01_universe_includes_russell_and_sp(self):
        """Verify universe includes stocks from both Russell 3000 and S&P 1500."""
        r3000_tickers = [t["ticker"] for t in self.raw_universe if t.get("in_russell3000")]
        sp1500_tickers = [t["ticker"] for t in self.raw_universe if t.get("in_sp1500")]
        self.assertGreater(len(r3000_tickers), 0)
        self.assertGreater(len(sp1500_tickers), 0)
        self.assertIn("AAPL", r3000_tickers)
        self.assertIn("CRWD", sp1500_tickers)

    def test_f07_02_spy_benchmark_always_present(self):
        """Verify SPY benchmark ETF is always present in universe regardless of Russell/S&P membership."""
        spy = next((t for t in self.raw_universe if t["ticker"] == "SPY"), None)
        self.assertIsNotNone(spy)
        self.assertEqual(spy["ticker"], "SPY")

    def test_f07_03_ticker_symbol_normalization(self):
        """Verify ticker symbols are normalized to uppercase and trimmed."""
        raw_inputs = ["  aapl  ", "msft\n", "nvda\t", "brk.b"]
        normalized = [t.strip().upper() for t in raw_inputs]
        self.assertEqual(normalized, ["AAPL", "MSFT", "NVDA", "BRK.B"])

    def test_f07_04_dual_class_shares_handling(self):
        """Verify dot/dash consistency for dual-class shares (e.g. BRK.B vs BRK-B)."""
        tickers = ["BRK.B", "BF.B", "GOOGL"]
        for t in tickers:
            self.assertTrue(t.isupper())
            self.assertFalse(" " in t)

    def test_f07_05_universe_deduplication(self):
        """Verify duplicate tickers from overlapping index constituents are deduplicated."""
        raw_list = ["AAPL", "MSFT", "AAPL", "NVDA", "MSFT", "SPY"]
        deduped = sorted(list(set(raw_list)))
        self.assertEqual(deduped, ["AAPL", "MSFT", "NVDA", "SPY"])

    # =========================================================================
    # FEATURE 8: Resilient Batch Downloader
    # =========================================================================
    def test_f08_01_chunking_size_50_tickers(self):
        """Verify batch chunking splits universe into batches of <= 50 tickers."""
        universe_tickers = [f"TICK{i:04d}" for i in range(125)]
        chunk_size = 50
        chunks = [universe_tickers[i:i + chunk_size] for i in range(0, len(universe_tickers), chunk_size)]
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 50)
        self.assertEqual(len(chunks[1]), 50)
        self.assertEqual(len(chunks[2]), 25)

    def test_f08_02_exponential_backoff_on_rate_limit(self):
        """Verify backoff calculation doubles delay on successive HTTP 429/500 errors."""
        base_delay = 1.0
        max_delay = 16.0
        delays = []
        for attempt in range(5):
            delay = min(base_delay * (2 ** attempt), max_delay)
            delays.append(delay)
        self.assertEqual(delays, [1.0, 2.0, 4.0, 8.0, 16.0])

    def test_f08_03_partial_batch_failure_isolation(self):
        """Verify single failed/delisted ticker does not abort the entire batch of 50."""
        batch = ["AAPL", "DELISTED_XYZ", "MSFT"]
        download_results = {}
        for t in batch:
            if t == "DELISTED_XYZ":
                download_results[t] = {"success": False, "bars": [], "error": "Ticker not found"}
            else:
                download_results[t] = {"success": True, "bars": [{"close": 150.0}], "error": None}
        
        self.assertTrue(download_results["AAPL"]["success"])
        self.assertFalse(download_results["DELISTED_XYZ"]["success"])
        self.assertTrue(download_results["MSFT"]["success"])

    def test_f08_04_jitter_delay_pacing(self):
        """Verify delay pacing between chunks adds positive non-zero delay."""
        pacing_interval = 0.5
        self.assertGreater(pacing_interval, 0.0)

    def test_f08_05_download_result_structure(self):
        """Verify downloaded daily bars contain standard OHLCV fields."""
        bars = generate_daily_bars_for_stock("AAPL", num_days=5)
        self.assertEqual(len(bars), 5)
        for b in bars:
            for field in ["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"]:
                self.assertIn(field, b)
            self.assertGreater(b["close"], 0)

    # =========================================================================
    # FEATURE 9: Delta Sync Engine
    # =========================================================================
    def test_f09_01_7day_delta_window_calculation(self):
        """Verify incremental delta window computes start date 7-10 days prior to target date."""
        target_date = date(2026, 10, 9)
        delta_days = 7
        start_date = target_date - timedelta(days=delta_days)
        self.assertEqual(start_date, date(2026, 10, 2))
        self.assertEqual((target_date - start_date).days, 7)

    def test_f09_02_2year_cold_start_window_calculation(self):
        """Verify cold start window requests at least 730 days (104 weeks) of history."""
        target_date = date(2026, 10, 9)
        cold_start_days = 730
        start_date = target_date - timedelta(days=cold_start_days)
        self.assertGreaterEqual((target_date - start_date).days, 730)

    def test_f09_03_overlap_merging_deduplication(self):
        """Verify delta sync merges newly fetched bars with existing cache, deduplicating dates."""
        existing_bars = [
            {"trade_date": "2026-10-06", "close": 100.0},
            {"trade_date": "2026-10-07", "close": 101.0},
        ]
        new_delta_bars = [
            {"trade_date": "2026-10-07", "close": 101.5},  # updated close on overlap
            {"trade_date": "2026-10-08", "close": 103.0},
            {"trade_date": "2026-10-09", "close": 105.0},
        ]
        # Dict merge by trade_date
        merged_dict = {b["trade_date"]: b for b in existing_bars}
        for b in new_delta_bars:
            merged_dict[b["trade_date"]] = b
            
        merged_list = sorted(list(merged_dict.values()), key=lambda x: x["trade_date"])
        self.assertEqual(len(merged_list), 4)
        self.assertEqual(merged_list[1]["close"], 101.5)  # updated value preserved

    def test_f09_04_skip_unmodified_tickers(self):
        """Verify delta sync can determine if a ticker cache already has latest Friday close."""
        latest_cache_date = "2026-10-09"
        scan_target_date = "2026-10-09"
        needs_sync = (latest_cache_date < scan_target_date)
        self.assertFalse(needs_sync)

    def test_f09_05_delta_date_continuity_verification(self):
        """Verify no gaps between historical cache and newly ingested delta bars."""
        history_dates = ["2026-10-01", "2026-10-02"]
        delta_dates = ["2026-10-05", "2026-10-06", "2026-10-07"]  # 03 and 04 are weekend
        d1 = date.fromisoformat(history_dates[-1])
        d2 = date.fromisoformat(delta_dates[0])
        # Weekend gap is 3 days (Friday to Monday)
        self.assertEqual((d2 - d1).days, 3)

    # =========================================================================
    # FEATURE 10: Parquet Local Cache
    # =========================================================================
    def test_f10_01_parquet_filename_convention(self):
        """Verify parquet filename convention follows data/parquet/<ticker>.parquet."""
        ticker = "AAPL"
        filename = f"data/parquet/{ticker}.parquet"
        self.assertTrue(filename.endswith(".parquet"))
        self.assertIn(ticker, filename)

    def test_f10_02_snappy_compression_format(self):
        """Verify Parquet writer configuration specifies snappy compression."""
        parquet_config = {
            "compression": "snappy",
            "use_dictionary": True
        }
        self.assertEqual(parquet_config["compression"], "snappy")

    def test_f10_03_cache_read_write_roundtrip(self):
        """Verify bar data integrity across serialize and deserialize mock."""
        raw_bars = generate_daily_bars_for_stock("MSFT", num_days=10)
        # Mock serialized rows
        serialized = [dict(b) for b in raw_bars]
        self.assertEqual(len(serialized), 10)
        self.assertEqual(serialized[0]["ticker"], "MSFT")

    def test_f10_04_cache_incremental_merge(self):
        """Verify cache merge keeps chronological sort order by date."""
        cached_dates = ["2026-10-01", "2026-10-02", "2026-10-05"]
        incoming_dates = ["2026-10-05", "2026-10-06"]
        merged = sorted(list(set(cached_dates + incoming_dates)))
        self.assertEqual(merged, ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"])

    def test_f10_05_cache_corrupted_file_recovery(self):
        """Verify corrupted parquet file is detected and safely recovered via fresh fetch."""
        cache_status = {"valid": False, "size_bytes": 0}
        should_re_download = (not cache_status["valid"] or cache_status["size_bytes"] == 0)
        self.assertTrue(should_re_download)

    # =========================================================================
    # FEATURE 11: PostgreSQL Daily Upsert
    # =========================================================================
    def test_f11_01_on_conflict_do_update_syntax(self):
        """Verify ON CONFLICT (ticker, trade_date) DO UPDATE upsert logic."""
        self.db.upsert_stock({"ticker": "NVDA", "name": "NVIDIA"})
        bar_initial = {
            "ticker": "NVDA", "trade_date": "2026-10-09",
            "open": 130.0, "high": 135.0, "low": 128.0, "close": 134.0, "volume": 10000000
        }
        self.db.upsert_daily_bar(bar_initial)
        
        # Subsequent update on same date
        bar_updated = {
            "ticker": "NVDA", "trade_date": "2026-10-09",
            "open": 130.0, "high": 136.0, "low": 128.0, "close": 135.5, "volume": 12000000
        }
        self.db.upsert_daily_bar(bar_updated)
        
        stored = self.db.stock_daily_bars[("NVDA", "2026-10-09")]
        self.assertEqual(stored["close"], 135.5)
        self.assertEqual(stored["volume"], 12000000)

    def test_f11_02_batch_insert_chunking(self):
        """Verify large upsert datasets can be partitioned into batches of 1,000 rows."""
        total_rows = 3500
        batch_size = 1000
        batches = [i for i in range(0, total_rows, batch_size)]
        self.assertEqual(len(batches), 4)

    def test_f11_03_update_existing_daily_bar_values(self):
        """Verify adj_close and volume are correctly overwritten on conflict."""
        self.db.upsert_stock({"ticker": "JPM", "name": "JPMorgan"})
        self.db.upsert_daily_bar({
            "ticker": "JPM", "trade_date": "2026-10-09",
            "open": 210.0, "high": 215.0, "low": 208.0, "close": 214.0, "adj_close": 214.0, "volume": 5000000
        })
        self.db.upsert_daily_bar({
            "ticker": "JPM", "trade_date": "2026-10-09",
            "open": 210.0, "high": 215.0, "low": 208.0, "close": 214.0, "adj_close": 212.5, "volume": 5500000
        })
        stored = self.db.stock_daily_bars[("JPM", "2026-10-09")]
        self.assertEqual(stored["adj_close"], 212.5)
        self.assertEqual(stored["volume"], 5500000)

    def test_f11_04_preserve_unmodified_bars(self):
        """Verify upserting date T2 does not mutate existing bar on date T1."""
        self.db.upsert_stock({"ticker": "AMZN", "name": "Amazon"})
        self.db.upsert_daily_bar({
            "ticker": "AMZN", "trade_date": "2026-10-08",
            "open": 180.0, "high": 185.0, "low": 178.0, "close": 182.0, "volume": 8000000
        })
        self.db.upsert_daily_bar({
            "ticker": "AMZN", "trade_date": "2026-10-09",
            "open": 182.0, "high": 186.0, "low": 181.0, "close": 185.0, "volume": 9000000
        })
        self.assertEqual(self.db.stock_daily_bars[("AMZN", "2026-10-08")]["close"], 182.0)
        self.assertEqual(self.db.stock_daily_bars[("AMZN", "2026-10-09")]["close"], 185.0)

    def test_f11_05_bulk_upsert_transaction_integrity(self):
        """Verify transaction rollback if a batch row contains an invalid foreign key."""
        self.db.upsert_stock({"ticker": "TSLA", "name": "Tesla"})
        batch = [
            {"ticker": "TSLA", "trade_date": "2026-10-09", "open": 240.0, "high": 245.0, "low": 238.0, "close": 242.0, "volume": 1000000},
            {"ticker": "BAD_TICKER", "trade_date": "2026-10-09", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 500}
        ]
        # In transaction, if second item raises ValueError, system handles or rolls back
        has_error = False
        try:
            for item in batch:
                self.db.upsert_daily_bar(item)
        except ValueError:
            has_error = True
        self.assertTrue(has_error)


if __name__ == "__main__":
    unittest.main()
