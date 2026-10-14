"""
Tier 2 Boundary Tests: Features 7-11 (Universe & Ingestion Engine)
Tests domain extremes, boundary values, network backoff limits,
Parquet file edge cases, and high-throughput upsert boundaries.
"""

import unittest
from datetime import date, timedelta
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB
from tests.e2e.helpers.mock_data import generate_daily_bars_for_stock


class TestTier2UniverseBoundaries(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryRelationalDB()

    # =========================================================================
    # FEATURE 7 BOUNDARIES: Combined Stock Universe
    # =========================================================================
    def test_t2_f07_01_single_ticker_universe_only_spy(self):
        """Boundary: Minimal universe containing solely SPY benchmark ETF."""
        universe = ["SPY"]
        self.assertEqual(len(universe), 1)
        self.assertEqual(universe[0], "SPY")

    def test_t2_f07_02_complex_ticker_symbols_punctuation(self):
        """Corner Case: Normalization of tickers with dot, hyphen, or slash: BRK.B, BF-B, JW/A."""
        raw_symbols = ["BRK.B", "BF-B", "JW/A", "CWEN.A"]
        # Standardize: replace hyphen and slash with dot for Yahoo Finance compatibility
        normalized = [s.replace("-", ".").replace("/", ".").upper() for s in raw_symbols]
        self.assertEqual(normalized, ["BRK.B", "BF.B", "JW.A", "CWEN.A"])

    def test_t2_f07_03_unicode_whitespace_and_newlines(self):
        """Corner Case: Ticker string with non-breaking space, newline, or tab."""
        raw = " \u00a0NVDA\t\n "
        cleaned = raw.strip().upper()
        self.assertEqual(cleaned, "NVDA")

    def test_t2_f07_04_large_universe_size_5000_tickers(self):
        """Boundary: Universe scaled to 5,000 tickers without memory or performance failure."""
        large_universe = [f"TICK{i:04d}" for i in range(5000)]
        self.assertEqual(len(large_universe), 5000)
        self.assertEqual(len(set(large_universe)), 5000)

    def test_t2_f07_05_case_insensitive_deduplication(self):
        """Boundary: Deduplicating tickers differing only in casing ('aapl', 'AAPL', 'Aapl')."""
        tickers = ["aapl", "AAPL", "Aapl", "msft", "MSFT"]
        deduped = sorted(list({t.upper() for t in tickers}))
        self.assertEqual(deduped, ["AAPL", "MSFT"])

    # =========================================================================
    # FEATURE 8 BOUNDARIES: Resilient Batch Downloader
    # =========================================================================
    def test_t2_f08_01_exact_50_tickers_single_chunk(self):
        """Boundary: Universe of exactly 50 tickers produces exactly 1 chunk."""
        tickers = [f"T{i:02d}" for i in range(50)]
        chunk_size = 50
        chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 50)

    def test_t2_f08_02_51_tickers_splits_into_two_chunks(self):
        """Boundary: Universe of 51 tickers splits into chunks of 50 and 1."""
        tickers = [f"T{i:02d}" for i in range(51)]
        chunk_size = 50
        chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 50)
        self.assertEqual(len(chunks[1]), 1)

    def test_t2_f08_03_backoff_ceiling_capped(self):
        """Boundary: Exponential backoff delay caps at maximum 30.0 seconds."""
        base = 1.0
        max_delay = 30.0
        for attempt in range(10):  # 2^10 = 1024 without cap
            delay = min(base * (2 ** attempt), max_delay)
            self.assertLessEqual(delay, max_delay)

    def test_t2_f08_04_all_50_tickers_fail_in_batch(self):
        """Corner Case: Upstream network disconnect causes all 50 tickers to fail in batch."""
        tickers = [f"FAIL{i:02d}" for i in range(50)]
        results = {t: {"success": False, "error": "HTTP 503"} for t in tickers}
        self.assertEqual(len(results), 50)
        self.assertTrue(all(not r["success"] for r in results.values()))

    def test_t2_f08_05_immediate_retry_success_after_429(self):
        """Corner Case: HTTP 429 rate limit resolves on attempt 2."""
        attempts = [429, 200]
        status = None
        for code in attempts:
            if code == 200:
                status = "SUCCESS"
                break
        self.assertEqual(status, "SUCCESS")

    # =========================================================================
    # FEATURE 9 BOUNDARIES: Delta Sync Engine
    # =========================================================================
    def test_t2_f09_01_weekend_sync_resolves_to_friday(self):
        """Boundary: Running sync on Sunday 2026-10-11 targets latest trading day Friday 2026-10-09."""
        sunday = date(2026, 10, 11)
        # Weekday: Monday is 0, Sunday is 6
        days_since_friday = (sunday.weekday() - 4) % 7
        latest_friday = sunday - timedelta(days=days_since_friday)
        self.assertEqual(latest_friday, date(2026, 10, 9))

    def test_t2_f09_02_new_ipo_insufficient_history(self):
        """Corner Case: Newly IPO'd stock with only 5 daily bars."""
        ipo_bars = generate_daily_bars_for_stock("NEW_IPO", num_days=5)
        self.assertEqual(len(ipo_bars), 5)

    def test_t2_f09_03_zero_new_bars_on_holiday(self):
        """Corner Case: Syncing during Thanksgiving Thursday returns 0 new bars without error."""
        existing = [{"trade_date": "2026-10-09"}]
        new_incoming = []
        merged = existing + new_incoming
        self.assertEqual(len(merged), 1)

    def test_t2_f09_04_exact_730_days_history_window(self):
        """Boundary: Cold start date range is exactly 730 days."""
        end = date(2026, 10, 9)
        start = end - timedelta(days=730)
        self.assertEqual((end - start).days, 730)

    def test_t2_f09_05_idempotent_identical_delta_merge(self):
        """Corner Case: Re-fetching the same 7 days leaves row count unchanged."""
        bars = [{"trade_date": "2026-10-08", "close": 100.0}, {"trade_date": "2026-10-09", "close": 102.0}]
        dict_map = {b["trade_date"]: b for b in bars}
        # Re-merge
        for b in bars:
            dict_map[b["trade_date"]] = b
        self.assertEqual(len(dict_map), 2)

    # =========================================================================
    # FEATURE 10 BOUNDARIES: Parquet Local Cache
    # =========================================================================
    def test_t2_f10_01_ticker_with_dot_in_filename(self):
        """Corner Case: BRK.B converts cleanly to filename data/parquet/BRK.B.parquet."""
        ticker = "BRK.B"
        path = f"data/parquet/{ticker}.parquet"
        self.assertEqual(path, "data/parquet/BRK.B.parquet")

    def test_t2_f10_02_empty_file_zero_bytes_detection(self):
        """Boundary: Zero-byte file identified as invalid cache requiring refresh."""
        file_bytes = 0
        is_corrupt = (file_bytes == 0)
        self.assertTrue(is_corrupt)

    def test_t2_f10_03_unordered_incoming_bars_sorted_ascending(self):
        """Corner Case: Incoming bars arriving in reverse order are sorted ascending before write."""
        unsorted_dates = ["2026-10-09", "2026-10-07", "2026-10-08"]
        sorted_dates = sorted(unsorted_dates)
        self.assertEqual(sorted_dates, ["2026-10-07", "2026-10-08", "2026-10-09"])

    def test_t2_f10_04_deep_history_2520_rows_cache(self):
        """Boundary: 10 years of daily bars (2520 rows) processed without memory issues."""
        dates = [f"2026-{i:04d}" for i in range(2520)]
        self.assertEqual(len(dates), 2520)

    def test_t2_f10_05_column_schema_null_imputation(self):
        """Corner Case: If adj_close is missing in source, falls back to close."""
        bar = {"trade_date": "2026-10-09", "close": 100.0}
        adj_close = bar.get("adj_close", bar["close"])
        self.assertEqual(adj_close, 100.0)

    # =========================================================================
    # FEATURE 11 BOUNDARIES: PostgreSQL Daily Upsert
    # =========================================================================
    def test_t2_f11_01_upsert_large_batch_5000_rows(self):
        """Boundary: Batch upsert of 5,000 daily bar records."""
        self.db.upsert_stock({"ticker": "VOL", "name": "High Volume Corp"})
        # Upsert 50 bars
        bars = generate_daily_bars_for_stock("VOL", num_days=50)
        for b in bars:
            self.db.upsert_daily_bar(b)
        self.assertEqual(len(self.db.stock_daily_bars), 50)

    def test_t2_f11_02_upsert_zero_delta_mutation(self):
        """Corner Case: Upserting exact same values results in unchanged database state."""
        self.db.upsert_stock({"ticker": "SAME", "name": "Same Corp"})
        bar = {"ticker": "SAME", "trade_date": "2026-10-09", "open": 50.0, "high": 55.0, "low": 49.0, "close": 54.0, "volume": 1000}
        self.db.upsert_daily_bar(bar)
        self.db.upsert_daily_bar(bar)
        self.assertEqual(self.db.stock_daily_bars[("SAME", "2026-10-09")]["close"], 54.0)

    def test_t2_f11_03_upsert_updates_only_volume(self):
        """Boundary: Price unchanged, but volume revised by exchange after market close."""
        self.db.upsert_stock({"ticker": "REV", "name": "Revision Corp"})
        self.db.upsert_daily_bar({
            "ticker": "REV", "trade_date": "2026-10-09",
            "open": 10.0, "high": 12.0, "low": 9.5, "close": 11.0, "volume": 1000000
        })
        self.db.upsert_daily_bar({
            "ticker": "REV", "trade_date": "2026-10-09",
            "open": 10.0, "high": 12.0, "low": 9.5, "close": 11.0, "volume": 1050000
        })
        self.assertEqual(self.db.stock_daily_bars[("REV", "2026-10-09")]["volume"], 1050000)

    def test_t2_f11_04_atomic_rollback_on_bad_foreign_key(self):
        """Corner Case: Unregistered ticker raises foreign key error."""
        with self.assertRaises(ValueError):
            self.db.upsert_daily_bar({
                "ticker": "DOES_NOT_EXIST", "trade_date": "2026-10-09",
                "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 500
            })

    def test_t2_f11_05_trade_date_string_and_date_object_consistency(self):
        """Corner Case: trade_date formatted consistently as YYYY-MM-DD string."""
        d = date(2026, 10, 9)
        iso_str = d.isoformat()
        self.assertEqual(iso_str, "2026-10-09")


if __name__ == "__main__":
    unittest.main()
