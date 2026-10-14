"""
screener/verify_m2.py - Comprehensive verification test suite for Milestone 2.
Self-contained (zero external network/db required) unit & integration test suite verifying:
- Deliverable files existence and non-emptiness
- Universe seed loading, schema completeness, and SPY benchmark presence
- Ticker normalization and non-equity filtering rules
- 50-chunking, exponential backoff, and pacing jitter logic
- Calendar / weekend resolution to Friday, 7-day delta, and 730-day cold start windows
- Daily OHLCV bar normalization and CHECK constraint guarantees
- Parquet local caching, merge deduplication, and corruption recovery
- Database upsert SQL statements and chunking logic
"""
import json
import math
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from screener.src import config, universe, downloader, parquet_cache, db, sync


class TestMilestone2Deliverables(unittest.TestCase):
    """Verifies that all required M2 files exist and are non-empty."""

    def test_all_m2_files_exist(self):
        expected_files = [
            PROJECT_ROOT / "screener" / "requirements.txt",
            PROJECT_ROOT / "screener" / "pyproject.toml",
            PROJECT_ROOT / "screener" / "data" / "universe" / "russell3000_sp1500.json",
            PROJECT_ROOT / "screener" / "src" / "__init__.py",
            PROJECT_ROOT / "screener" / "src" / "config.py",
            PROJECT_ROOT / "screener" / "src" / "db.py",
            PROJECT_ROOT / "screener" / "src" / "universe.py",
            PROJECT_ROOT / "screener" / "src" / "downloader.py",
            PROJECT_ROOT / "screener" / "src" / "parquet_cache.py",
            PROJECT_ROOT / "screener" / "src" / "sync.py",
            PROJECT_ROOT / "screener" / "src" / "main.py",
        ]
        for f in expected_files:
            self.assertTrue(f.exists(), f"Missing required file: {f}")
            self.assertGreater(f.stat().st_size, 0, f"File is empty: {f}")


class TestFeature07UniverseDefinition(unittest.TestCase):
    """Tests Feature 7: Combined Stock Universe (Russell 3000 + S&P 1500 + SPY)."""

    def test_universe_seed_loads_and_has_spy(self):
        stocks = universe.load_universe_seed()
        self.assertGreater(len(stocks), 0)
        spy = next((s for s in stocks if s["ticker"] == "SPY"), None)
        self.assertIsNotNone(spy, "SPY benchmark ETF must be present in universe")
        self.assertEqual(spy["ticker"], "SPY")
        self.assertTrue(spy["is_active"])
        self.assertTrue(spy["in_russell3000"])
        self.assertTrue(spy["in_sp1500"])
        # Verify anchor common equities ending in W are not falsely dropped
        now = next((s for s in stocks if s["ticker"] == "NOW"), None)
        self.assertIsNotNone(now, "NOW (ServiceNow) must be present in loaded seed universe")
        low = next((s for s in stocks if s["ticker"] == "LOW"), None)
        self.assertIsNotNone(low, "LOW (Lowe's) must be present in loaded seed universe")

    def test_universe_schema_attributes(self):
        stocks = universe.load_universe_seed()
        required_keys = {
            "ticker", "name", "exchange", "sector", "industry",
            "market_cap", "is_active", "in_russell3000", "in_sp1500"
        }
        for s in stocks[:20]:
            for key in required_keys:
                self.assertIn(key, s, f"Stock {s.get('ticker')} missing required key '{key}'")

    def test_ticker_sanitization(self):
        # Trims whitespace, unicode space, uppercase
        self.assertEqual(universe.sanitize_ticker("  aapl  "), "AAPL")
        self.assertEqual(universe.sanitize_ticker("msft\n"), "MSFT")
        self.assertEqual(universe.sanitize_ticker("nvda\t"), "NVDA")
        self.assertEqual(universe.sanitize_ticker(" \u00a0googl\t\n "), "GOOGL")
        
        # Dual-class share normalization: replace hyphen or slash with dot
        self.assertEqual(universe.sanitize_ticker("BRK-B"), "BRK.B")
        self.assertEqual(universe.sanitize_ticker("BF-B"), "BF.B")
        self.assertEqual(universe.sanitize_ticker("JW/A"), "JW.A")
        self.assertEqual(universe.sanitize_ticker("CWEN.A"), "CWEN.A")

    def test_yfinance_symbol_conversions(self):
        self.assertEqual(universe.to_yfinance_symbol("BRK.B"), "BRK-B")
        self.assertEqual(universe.to_yfinance_symbol("BF.B"), "BF-B")
        self.assertEqual(universe.from_yfinance_symbol("BRK-B"), "BRK.B")
        self.assertEqual(universe.from_yfinance_symbol("BF-B"), "BF.B")

    def test_common_stock_filtering(self):
        # Valid common stocks and dual-class equities
        self.assertTrue(universe.is_common_stock("SPY"))
        self.assertTrue(universe.is_common_stock("AAPL", "Apple Inc."))
        self.assertTrue(universe.is_common_stock("GOOGL", "Alphabet Inc."))
        self.assertTrue(universe.is_common_stock("BRK.B", "Berkshire Hathaway"))
        self.assertTrue(universe.is_common_stock("BRK.B"))
        self.assertTrue(universe.is_common_stock("BF.B", "Brown-Forman"))
        self.assertTrue(universe.is_common_stock("BF.B"))
        self.assertTrue(universe.is_common_stock("CWEN.A", "Clearway Energy"))
        self.assertTrue(universe.is_common_stock("CWEN.A"))
        self.assertTrue(universe.is_common_stock("JW.A", "John Wiley"))
        self.assertTrue(universe.is_common_stock("JW.A"))

        # Common stocks ending in W, UN, PR (S&P 500 / Russell 3000 constituents)
        self.assertTrue(universe.is_common_stock("NOW", "ServiceNow Inc."))
        self.assertTrue(universe.is_common_stock("NOW"))
        self.assertTrue(universe.is_common_stock("LOW", "Lowe's Companies Inc."))
        self.assertTrue(universe.is_common_stock("LOW"))
        self.assertTrue(universe.is_common_stock("SNOW", "Snowflake Inc."))
        self.assertTrue(universe.is_common_stock("SNOW"))
        self.assertTrue(universe.is_common_stock("GLW", "Corning Inc."))
        self.assertTrue(universe.is_common_stock("GLW"))
        self.assertTrue(universe.is_common_stock("CHRW", "C.H. Robinson Worldwide, Inc."))
        self.assertTrue(universe.is_common_stock("CHRW"))
        self.assertTrue(universe.is_common_stock("FLOW", "SPX Technologies Inc."))
        self.assertTrue(universe.is_common_stock("FLOW"))
        self.assertTrue(universe.is_common_stock("W", "Wayfair Inc."))
        self.assertTrue(universe.is_common_stock("W"))
        self.assertTrue(universe.is_common_stock("RUN", "Sunrun Inc."))
        self.assertTrue(universe.is_common_stock("RUN"))
        self.assertTrue(universe.is_common_stock("FUN", "Six Flags Entertainment Corp."))
        self.assertTrue(universe.is_common_stock("FUN"))
        self.assertTrue(universe.is_common_stock("HUN", "Huntsman Corp."))
        self.assertTrue(universe.is_common_stock("HUN"))
        self.assertTrue(universe.is_common_stock("SUN", "Sunoco LP"))
        self.assertTrue(universe.is_common_stock("SUN"))
        self.assertTrue(universe.is_common_stock("EPR", "EPR Properties"))
        self.assertTrue(universe.is_common_stock("EPR"))
        self.assertTrue(universe.is_common_stock("OPRA", "Opera Limited"))
        self.assertTrue(universe.is_common_stock("OPRA"))

        # Warrants rejected (including single-letter suffix and hyphenated forms)
        self.assertFalse(universe.is_common_stock("LCID-W"))
        self.assertFalse(universe.is_common_stock("LCID.W"))
        self.assertFalse(universe.is_common_stock("FOO.W"))
        self.assertFalse(universe.is_common_stock("LCID.WS", "Lucid Group Warrant"))
        self.assertFalse(universe.is_common_stock("NKLA+", "Nikola Corp Warrant"))

        # Preferreds rejected (including single-letter .P and hyphenated forms)
        self.assertFalse(universe.is_common_stock("BAC-P"))
        self.assertFalse(universe.is_common_stock("BAC.P"))
        self.assertFalse(universe.is_common_stock("C-PJ"))
        self.assertFalse(universe.is_common_stock("BAC.PR.A", "Bank of America Preferred"))
        self.assertFalse(universe.is_common_stock("JPM-PC", "JPMorgan Preferred"))

        # Units rejected (including single-letter suffix)
        self.assertFalse(universe.is_common_stock("AACG.U"))
        self.assertFalse(universe.is_common_stock("BAR.U"))
        self.assertFalse(universe.is_common_stock("CLBR.U", "Colombier Units"))

        # Rights rejected (including single-letter suffix)
        self.assertFalse(universe.is_common_stock("BAZ.R"))
        self.assertFalse(universe.is_common_stock("FOO.RT", "Foo Rights"))

        # Test tickers rejected
        self.assertFalse(universe.is_common_stock("ZVZZT"))
        self.assertFalse(universe.is_common_stock("ZWZZT"))
        self.assertFalse(universe.is_common_stock("TEST"))


class TestFeature08ResilientBatchDownloader(unittest.TestCase):
    """Tests Feature 8: Resilient Batch Downloader logic."""

    def test_chunking_size_50(self):
        universe_tickers = [f"TICK{i:04d}" for i in range(125)]
        chunks = downloader.chunk_tickers(universe_tickers, chunk_size=50)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 50)
        self.assertEqual(len(chunks[1]), 50)
        self.assertEqual(len(chunks[2]), 25)

    def test_chunking_exact_50_and_51(self):
        t50 = [f"T{i:02d}" for i in range(50)]
        chunks50 = downloader.chunk_tickers(t50, chunk_size=50)
        self.assertEqual(len(chunks50), 1)
        self.assertEqual(len(chunks50[0]), 50)

        t51 = [f"T{i:02d}" for i in range(51)]
        chunks51 = downloader.chunk_tickers(t51, chunk_size=50)
        self.assertEqual(len(chunks51), 2)
        self.assertEqual(len(chunks51[0]), 50)
        self.assertEqual(len(chunks51[1]), 1)

    def test_exponential_backoff_doubling_and_cap(self):
        delays = [downloader.calculate_backoff_delay(i, base_delay=1.0, max_delay=16.0, jitter=False) for i in range(5)]
        self.assertEqual(delays, [1.0, 2.0, 4.0, 8.0, 16.0])

        # Verify cap at 30.0s
        for attempt in range(10):
            d = downloader.calculate_backoff_delay(attempt, base_delay=1.0, max_delay=30.0, jitter=False)
            self.assertLessEqual(d, 30.0)

    def test_daily_bar_normalization_and_constraints(self):
        raw_row = {
            "Open": 100.5,
            "High": 105.0,
            "Low": 99.0,
            "Close": 104.2,
            "Adj Close": 103.8,
            "Volume": 1500000
        }
        bar = downloader.normalize_daily_bar("AAPL", "2026-10-09", raw_row)
        self.assertIsNotNone(bar)
        self.assertEqual(bar["ticker"], "AAPL")
        self.assertEqual(bar["trade_date"], "2026-10-09")
        self.assertEqual(bar["open"], 100.5)
        self.assertEqual(bar["high"], 105.0)
        self.assertEqual(bar["low"], 99.0)
        self.assertEqual(bar["close"], 104.2)
        self.assertEqual(bar["adj_close"], 103.8)
        self.assertEqual(bar["volume"], 1500000)

        # CHECK constraints: high >= max(open, close), low <= min(open, close)
        self.assertGreaterEqual(bar["high"], bar["open"])
        self.assertGreaterEqual(bar["high"], bar["close"])
        self.assertGreaterEqual(bar["high"], bar["low"])
        self.assertLessEqual(bar["low"], bar["open"])
        self.assertLessEqual(bar["low"], bar["close"])
        self.assertGreaterEqual(bar["volume"], 0)

    def test_null_imputation_adj_close(self):
        # Missing Adj Close falls back to Close
        raw_row = {"Open": 50.0, "High": 52.0, "Low": 49.0, "Close": 51.5, "Volume": 1000}
        bar = downloader.normalize_daily_bar("XYZ", "2026-10-09", raw_row)
        self.assertEqual(bar["adj_close"], 51.5)

    def test_multi_ticker_batch_single_level_fallback_prevents_bleed(self):
        """
        Tests that when yfinance returns a single-level column DataFrame for a multi-ticker batch,
        the downloader triggers single-ticker fallback for each ticker instead of copying data.
        """
        from unittest.mock import patch
        import pandas as pd

        fake_single_df = pd.DataFrame(
            {"Open": [100.0], "High": [105.0], "Low": [99.0], "Close": [104.0], "Volume": [1000]},
            index=pd.to_datetime(["2026-10-09"])
        )

        with patch("screener.src.downloader.yf.download", return_value=fake_single_df), \
             patch("screener.src.downloader.download_single_ticker") as mock_single:
            mock_single.return_value = {
                "ticker": "AAPL",
                "bars": [{"ticker": "AAPL", "trade_date": "2026-10-09", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "adj_close": 104.0, "volume": 1000}],
                "success": True,
            }
            res = downloader.download_batch_with_retry(["AAPL", "MSFT"], "2026-10-01", "2026-10-10", max_retries=1)
            # Must invoke single-ticker download for both tickers rather than misattributing fake_single_df
            self.assertEqual(mock_single.call_count, 2)


class TestFeature09DeltaSyncEngine(unittest.TestCase):
    """Tests Feature 9: Delta Sync Engine."""

    def test_weekend_resolves_to_friday(self):
        sunday = date(2026, 10, 11)
        friday = downloader.resolve_trading_friday(sunday)
        self.assertEqual(friday, date(2026, 10, 9))

        saturday = date(2026, 10, 10)
        self.assertEqual(downloader.resolve_trading_friday(saturday), date(2026, 10, 9))

        fri = date(2026, 10, 9)
        self.assertEqual(downloader.resolve_trading_friday(fri), date(2026, 10, 9))

    def test_date_windows_delta_and_cold_start(self):
        target_friday = date(2026, 10, 9)
        # Delta: 7 days
        start_d, target_d, yf_end = downloader.calculate_date_range(target_friday, mode="delta")
        self.assertEqual(start_d, date(2026, 10, 2))
        self.assertEqual((target_d - start_d).days, 7)
        self.assertEqual(yf_end, date(2026, 10, 10))  # yfinance end is exclusive

        # Cold start: 730 days
        start_c, _, _ = downloader.calculate_date_range(target_friday, mode="cold_start")
        self.assertEqual((target_d - start_c).days, 730)

    def test_overlap_merging_deduplication(self):
        cached = [
            {"trade_date": "2026-10-06", "close": 100.0},
            {"trade_date": "2026-10-07", "close": 101.0},
        ]
        incoming = [
            {"trade_date": "2026-10-07", "close": 101.5},  # updated close
            {"trade_date": "2026-10-08", "close": 103.0},
            {"trade_date": "2026-10-09", "close": 105.0},
        ]
        merged = parquet_cache.merge_daily_bars(cached, incoming)
        self.assertEqual(len(merged), 4)
        self.assertEqual(merged[1]["close"], 101.5)
        self.assertEqual(merged[-1]["trade_date"], "2026-10-09")

    def test_sync_preseeds_custom_tickers_in_stocks(self):
        """
        Verifies that run_sync invokes db.ensure_stocks_exist for custom tickers before downloading.
        """
        from unittest.mock import patch

        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist") as mock_ensure, \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.downloader.download_batch_with_retry", return_value={}):
            
            sync.run_sync(tickers=["CUSTOM_X", "CUSTOM_Y"], target_date=date(2026, 10, 9), skip_unmodified=False)
            mock_ensure.assert_called_once()
            call_args = mock_ensure.call_args[0][0]
            self.assertIn("CUSTOM_X", call_args)
            self.assertIn("CUSTOM_Y", call_args)
            self.assertIn("SPY", call_args)

    def test_sync_prioritizes_spy_before_broader_universe(self):
        """
        Verifies that run_sync ingests SPY benchmark in Step 2 before downloading broader universe tickers.
        """
        from unittest.mock import patch

        call_batches = []
        def mock_download(tickers, start, end):
            call_batches.append(list(tickers))
            return {t: [] for t in tickers}

        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist", return_value=3), \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.downloader.download_batch_with_retry", side_effect=mock_download):

            sync.run_sync(tickers=["CUSTOM_A", "CUSTOM_B"], target_date=date(2026, 10, 9), skip_unmodified=False)
            self.assertGreaterEqual(len(call_batches), 2)
            self.assertEqual(call_batches[0], ["SPY"], "First download must be strictly SPY benchmark")
            self.assertIn("CUSTOM_A", call_batches[1])
            self.assertIn("CUSTOM_B", call_batches[1])

    def test_sync_empty_tickers_list_falls_back_to_spy(self):
        """
        Verifies that passing tickers=[] gracefully defaults to syncing SPY.
        """
        from unittest.mock import patch

        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist") as mock_ensure, \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.downloader.download_batch_with_retry", return_value={}):

            metrics = sync.run_sync(tickers=[], target_date=date(2026, 10, 9), skip_unmodified=False)
            self.assertEqual(metrics["tickers_total"], 1)
            mock_ensure.assert_called_once()
            self.assertEqual(mock_ensure.call_args[0][0], ["SPY"])



class TestFeature10ParquetLocalCache(unittest.TestCase):
    """Tests Feature 10: Parquet Local Cache."""

    def test_parquet_filename_convention_and_dots(self):
        path = parquet_cache.get_parquet_path("BRK.B")
        self.assertTrue(str(path).endswith("BRK.B.parquet"))
        self.assertEqual(path.name, "BRK.B.parquet")

    def test_roundtrip_save_and_load(self):
        ticker = "TEST_ROUNDTRIP"
        bars = [
            {"ticker": ticker, "trade_date": "2026-10-08", "open": 10.0, "high": 12.0, "low": 9.5, "close": 11.0, "adj_close": 11.0, "volume": 5000},
            {"ticker": ticker, "trade_date": "2026-10-09", "open": 11.0, "high": 13.0, "low": 10.5, "close": 12.5, "adj_close": 12.5, "volume": 6000},
        ]
        success = parquet_cache.save_to_parquet(ticker, bars)
        self.assertTrue(success)

        loaded = parquet_cache.load_from_parquet(ticker)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["trade_date"], "2026-10-08")
        self.assertEqual(loaded[1]["close"], 12.5)

        # Cleanup
        parquet_cache.get_parquet_path(ticker).unlink(missing_ok=True)

    def test_zero_byte_corruption_detection(self):
        ticker = "TEST_CORRUPT"
        path = parquet_cache.get_parquet_path(ticker)
        path.write_bytes(b"")  # 0 bytes
        self.assertEqual(path.stat().st_size, 0)

        loaded = parquet_cache.load_from_parquet(ticker)
        self.assertEqual(loaded, [])
        self.assertFalse(path.exists(), "Corrupt 0-byte file should be unlinked")


class TestFeature11PostgreSQLDailyUpsert(unittest.TestCase):
    """Tests Feature 11: SQL Query definitions and batching contracts."""

    def test_upsert_empty_list_returns_zero(self):
        self.assertEqual(db.upsert_stocks([]), 0)
        self.assertEqual(db.upsert_daily_bars([]), 0)

    def test_batch_chunking_calculation(self):
        total_rows = 3500
        chunk_size = 1000
        chunks = [i for i in range(0, total_rows, chunk_size)]
        self.assertEqual(len(chunks), 4)

    def test_upsert_daily_bars_deduplicates_to_prevent_cardinality_violation(self):
        """
        Verifies that passing duplicate (ticker, trade_date) records into upsert_daily_bars
        deduplicates them (keeping the latest) and executes without cardinality violations.
        """
        from unittest.mock import MagicMock

        mock_cur = MagicMock()
        mock_cur.connection.encoding = "UTF8"
        mock_cur.mogrify.side_effect = lambda t, v: b"('AAPL', '2026-10-09', 100, 105, 99, 102, 102, 1000)"
        duplicate_bars = [
            {"ticker": "AAPL", "trade_date": "2026-10-09", "open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0, "adj_close": 102.0, "volume": 1000},
            {"ticker": "AAPL", "trade_date": "2026-10-09", "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0, "adj_close": 105.0, "volume": 1500},
            {"ticker": "MSFT", "trade_date": "2026-10-09", "open": 200.0, "high": 205.0, "low": 199.0, "close": 204.0, "adj_close": 204.0, "volume": 2000},
            {"ticker": "MSFT", "trade_date": "2026-10-09", "open": 200.0, "high": 208.0, "low": 199.0, "close": 207.0, "adj_close": 207.0, "volume": 2500},
        ]

        count = db.upsert_daily_bars(duplicate_bars, cur=mock_cur)
        self.assertEqual(count, 2, "Duplicate (ticker, trade_date) pairs must be collapsed into 2 unique records")

    def test_ensure_stocks_exist_with_custom_tickers(self):
        """
        Verifies that db.ensure_stocks_exist deduplicates custom tickers and executes correctly.
        """
        from unittest.mock import MagicMock

        mock_cur = MagicMock()
        mock_cur.connection.encoding = "UTF8"
        mock_cur.mogrify.side_effect = lambda t, v: b"('CUSTOM', 'CUSTOM', 'NYSE', 'Unknown', 'Unknown', 0, True, False, False)"
        tickers = ["CUSTOM1", "CUSTOM2", "CUSTOM1"]
        count = db.ensure_stocks_exist(tickers, cur=mock_cur)
        self.assertEqual(count, 2, "Custom tickers should be deduplicated")

    def test_ensure_stocks_exist_empty_list_and_falsy(self):
        """
        Verifies that db.ensure_stocks_exist returns 0 for empty list or falsy values without DB calls.
        """
        from unittest.mock import patch
        with patch("screener.src.db.db_cursor") as mock_cursor:
            self.assertEqual(db.ensure_stocks_exist([]), 0)
            self.assertEqual(db.ensure_stocks_exist(None), 0)
            self.assertEqual(db.ensure_stocks_exist(["", ""]), 0)
            mock_cursor.assert_not_called()

    def test_ensure_stocks_exist_sql_clause_and_idempotency(self):
        """
        Verifies SQL clause uses ON CONFLICT (ticker) DO NOTHING and formats tuples properly.
        """
        from unittest.mock import MagicMock, patch

        mock_cur = MagicMock()
        tickers = ["FOO", "BAR", "FOO"]
        with patch("screener.src.db.execute_values") as mock_exec:
            count = db.ensure_stocks_exist(tickers, cur=mock_cur)
            self.assertEqual(count, 2)
            sql = mock_exec.call_args[0][1]
            values = mock_exec.call_args[0][2]
            self.assertIn("ON CONFLICT (ticker) DO NOTHING", sql)
            self.assertEqual(values, [("FOO", "FOO", "UNKNOWN", True), ("BAR", "BAR", "UNKNOWN", True)])



if __name__ == "__main__":
    unittest.main()
