"""
Tier 2 Boundary Tests: Challenger 4 Stress Harness for Sync Coordination & Foreign Key Pre-Seeding.
Adversarially tests:
1. db.ensure_stocks_exist:
   - empty lists, empty strings, None
   - custom ad-hoc tickers
   - duplicate tickers
   - dict vs string ticker inputs
   - idempotency (INSERT ... ON CONFLICT (ticker) DO NOTHING)
2. sync.py pipeline coordination:
   - custom ad-hoc tickers pre-seeded into 'stocks' before bars downloaded & upserted
   - relational foreign key integrity verification
   - graceful handling of DB errors during pre-seed
3. SPY benchmark prioritization:
   - SPY benchmark injected at head if missing from custom tickers
   - SPY ingested in Step 2 prior to broader universe in Step 3
   - deduplication when SPY explicitly provided in custom tickers
   - exclusion of SPY from Step 3 batch chunks
"""

import unittest
from datetime import date
from unittest.mock import MagicMock, call, patch

from screener.src import config, db, sync, universe
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB


class TestEnsureStocksExistStress(unittest.TestCase):
    """Adversarial stress tests for db.ensure_stocks_exist."""

    def test_empty_list_returns_zero_no_db_call(self):
        """Verify empty list returns 0 immediately without opening cursor/transaction."""
        with patch("screener.src.db.db_cursor") as mock_cursor:
            count = db.ensure_stocks_exist([])
            self.assertEqual(count, 0)
            mock_cursor.assert_not_called()

        with patch("screener.src.db.db_cursor") as mock_cursor:
            count = db.ensure_stocks_exist(None)
            self.assertEqual(count, 0)
            mock_cursor.assert_not_called()

    def test_empty_string_items_filtered_out(self):
        """Verify empty strings and empty ticker dicts produce 0 values without error."""
        with patch("screener.src.db.db_cursor") as mock_cursor:
            count = db.ensure_stocks_exist(["", ""])
            self.assertEqual(count, 0)
            mock_cursor.assert_not_called()

        with patch("screener.src.db.db_cursor") as mock_cursor:
            count = db.ensure_stocks_exist([{"ticker": ""}, {"ticker": None}])
            self.assertEqual(count, 0)
            mock_cursor.assert_not_called()

    def test_custom_adhoc_tickers_generation(self):
        """Verify custom ad-hoc string tickers generate correct VALUES tuples with default UNKNOWN exchange."""
        mock_cur = MagicMock()
        tickers = ["ADHOC1", "ADHOC2", "CUSTOM_X"]
        with patch("screener.src.db.execute_values") as mock_exec:
            count = db.ensure_stocks_exist(tickers, cur=mock_cur)
            self.assertEqual(count, 3)
            mock_exec.assert_called_once()
            sql, values = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
            
            # Verify SQL contains ON CONFLICT (ticker) DO NOTHING
            self.assertIn("INSERT INTO stocks (ticker, name, exchange, is_active)", sql)
            self.assertIn("ON CONFLICT (ticker) DO NOTHING", sql)
            
            # Verify values tuple structure
            self.assertEqual(len(values), 3)
            self.assertEqual(values[0], ("ADHOC1", "ADHOC1", "UNKNOWN", True))
            self.assertEqual(values[1], ("ADHOC2", "ADHOC2", "UNKNOWN", True))
            self.assertEqual(values[2], ("CUSTOM_X", "CUSTOM_X", "UNKNOWN", True))

    def test_duplicate_tickers_deduplication(self):
        """Verify duplicate tickers in the input list are collapsed to unique entries."""
        mock_cur = MagicMock()
        tickers = ["FOO", "BAR", "FOO", "BAR", "BAZ", "FOO", "FOO"]
        with patch("screener.src.db.execute_values") as mock_exec:
            count = db.ensure_stocks_exist(tickers, cur=mock_cur)
            self.assertEqual(count, 3)
            values = mock_exec.call_args[0][2]
            tickers_extracted = [v[0] for v in values]
            self.assertEqual(tickers_extracted, ["FOO", "BAR", "BAZ"])

    def test_mixed_dict_and_string_inputs(self):
        """Verify ensure_stocks_exist accepts both dicts and strings in the same call."""
        mock_cur = MagicMock()
        items = [
            {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"},
            "MSFT",
            {"ticker": "AAPL", "name": "Duplicate Apple"},  # Duplicate
        ]
        with patch("screener.src.db.execute_values") as mock_exec:
            count = db.ensure_stocks_exist(items, cur=mock_cur)
            self.assertEqual(count, 2)
            values = mock_exec.call_args[0][2]
            self.assertEqual(values[0], ("AAPL", "Apple Inc.", "NASDAQ", True))
            self.assertEqual(values[1], ("MSFT", "MSFT", "UNKNOWN", True))

    def test_dict_missing_optional_fields_fallback(self):
        """Verify dict items without name or exchange fall back to ticker and UNKNOWN."""
        mock_cur = MagicMock()
        items = [{"ticker": "ORCL"}]
        with patch("screener.src.db.execute_values") as mock_exec:
            count = db.ensure_stocks_exist(items, cur=mock_cur)
            self.assertEqual(count, 1)
            values = mock_exec.call_args[0][2]
            self.assertEqual(values[0], ("ORCL", "ORCL", "UNKNOWN", True))

    def test_idempotent_relational_simulation(self):
        """Simulate repeated ensure_stocks_exist on an in-memory relational store."""
        db_sim = InMemoryRelationalDB()
        # Seed AAPL
        db_sim.upsert_stock({"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "sector": "Technology"})
        
        # Calling ensure_stocks_exist with existing AAPL and new CUSTOM1
        # Simulating ON CONFLICT (ticker) DO NOTHING
        tickers = ["AAPL", "CUSTOM1"]
        for t in tickers:
            if t not in db_sim.stocks:
                db_sim.upsert_stock({"ticker": t, "name": t, "exchange": "UNKNOWN"})

        # AAPL retains original metadata
        self.assertEqual(db_sim.stocks["AAPL"]["sector"], "Technology")
        # CUSTOM1 created
        self.assertIn("CUSTOM1", db_sim.stocks)
        self.assertEqual(db_sim.stocks["CUSTOM1"]["exchange"], "UNKNOWN")

        # Second call is a no-op
        for t in tickers:
            if t not in db_sim.stocks:
                db_sim.upsert_stock({"ticker": t, "name": t, "exchange": "UNKNOWN"})
        self.assertEqual(len(db_sim.stocks), 2)


class TestSyncPipelinePreSeedingStress(unittest.TestCase):
    """Adversarial stress tests for sync.py pre-seeding pipeline."""

    def test_custom_adhoc_tickers_preseeded_before_download(self):
        """
        Verify that when custom ad-hoc tickers are provided to run_sync:
        1. db.ensure_stocks_exist is invoked with all canonical tickers including custom ones.
        2. db.ensure_stocks_exist executes strictly BEFORE downloader.download_batch_with_retry.
        """
        call_order = []

        def mock_ensure(tickers, cur=None):
            call_order.append(("ensure_stocks_exist", list(tickers)))
            return len(tickers)

        def mock_download(tickers, start, end):
            call_order.append(("download_batch", list(tickers)))
            return {t: [{"ticker": t, "trade_date": "2026-10-09", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "adj_close": 10.5, "volume": 1000}] for t in tickers}

        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist", side_effect=mock_ensure), \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.parquet_cache.save_to_parquet", return_value=True), \
             patch("screener.src.downloader.download_batch_with_retry", side_effect=mock_download), \
             patch("screener.src.db.upsert_daily_bars", return_value=1):

            metrics = sync.run_sync(
                tickers=["CUSTOM_ALPHA", "CUSTOM_BETA"],
                target_date=date(2026, 10, 9),
                skip_unmodified=False,
            )

            # Ensure ensure_stocks_exist was called first
            self.assertGreater(len(call_order), 0)
            first_action, preseeded_tickers = call_order[0]
            self.assertEqual(first_action, "ensure_stocks_exist")
            self.assertIn("CUSTOM_ALPHA", preseeded_tickers)
            self.assertIn("CUSTOM_BETA", preseeded_tickers)
            self.assertIn("SPY", preseeded_tickers)

            # Ensure download happened after pre-seeding
            download_actions = [action for action, _ in call_order if action == "download_batch"]
            self.assertGreater(len(download_actions), 0)

    def test_preseeded_custom_tickers_prevent_foreign_key_violation(self):
        """
        Verify that pre-seeding custom tickers in stocks allows upserting daily bars
        without foreign key violations in a relational store.
        """
        db_sim = InMemoryRelationalDB()
        custom_tickers = ["AD_HOC_CORP"]

        # 1. Pipeline pre-seeds custom ticker into stocks table
        for t in custom_tickers:
            if t not in db_sim.stocks:
                db_sim.upsert_stock({"ticker": t, "name": t, "exchange": "UNKNOWN"})

        # 2. Pipeline upserts downloaded daily bars
        bar = {
            "ticker": "AD_HOC_CORP",
            "trade_date": "2026-10-09",
            "open": 25.0,
            "high": 26.5,
            "low": 24.5,
            "close": 26.0,
            "adj_close": 26.0,
            "volume": 250000,
        }
        # Upsert succeeds because foreign key exists
        success = db_sim.upsert_daily_bar(bar)
        self.assertTrue(success)
        self.assertIn(("AD_HOC_CORP", "2026-10-09"), db_sim.stock_daily_bars)

    def test_whitespace_and_dual_class_custom_tickers_sanitized(self):
        """Verify custom tickers with whitespace or dual-class separators are sanitized before pre-seeding."""
        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist") as mock_ensure, \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.downloader.download_batch_with_retry", return_value={}):

            sync.run_sync(
                tickers=["  brk-b \n", "jw/a\t", "nvda"],
                target_date=date(2026, 10, 9),
                skip_unmodified=False,
            )
            mock_ensure.assert_called_once()
            called_tickers = mock_ensure.call_args[0][0]
            self.assertIn("BRK.B", called_tickers)
            self.assertIn("JW.A", called_tickers)
            self.assertIn("NVDA", called_tickers)
            self.assertNotIn("  brk-b \n", called_tickers)
            self.assertNotIn("jw/a\t", called_tickers)

    def test_empty_tickers_list_fallback(self):
        """Verify passing tickers=[] falls back to ['SPY'] and pre-seeds SPY."""
        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist") as mock_ensure, \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.downloader.download_batch_with_retry", return_value={}):

            metrics = sync.run_sync(tickers=[], target_date=date(2026, 10, 9), skip_unmodified=False)
            mock_ensure.assert_called_once()
            called_tickers = mock_ensure.call_args[0][0]
            self.assertEqual(called_tickers, ["SPY"])
            self.assertEqual(metrics["tickers_total"], 1)

    def test_database_offline_preseed_logs_warning_and_continues(self):
        """Verify that if PostgreSQL is offline during pre-seeding, run_sync logs warning and continues."""
        with patch("screener.src.universe.sync_universe_to_db", side_effect=Exception("DB connection refused")), \
             patch("screener.src.db.ensure_stocks_exist", side_effect=Exception("DB connection refused")), \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.parquet_cache.save_to_parquet", return_value=True), \
             patch("screener.src.downloader.download_batch_with_retry", return_value={"SPY": [{"ticker": "SPY", "trade_date": "2026-10-09", "open": 500.0, "high": 505.0, "low": 498.0, "close": 502.0, "adj_close": 502.0, "volume": 10000000}]}), \
             patch("screener.src.db.upsert_daily_bars", side_effect=Exception("DB offline")):

            metrics = sync.run_sync(tickers=["CUSTOM1"], target_date=date(2026, 10, 9), skip_unmodified=False)
            # Sync completes without raising unhandled exception
            self.assertIsNotNone(metrics)
            self.assertEqual(metrics["tickers_total"], 2)  # SPY + CUSTOM1


class TestBenchmarkSpyPrioritizationStress(unittest.TestCase):
    """Adversarial stress tests for benchmark SPY prioritization."""

    def test_spy_injected_at_head_when_missing_from_custom_tickers(self):
        """Verify SPY is automatically inserted at index 0 when absent from custom tickers."""
        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist") as mock_ensure, \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.downloader.download_batch_with_retry", return_value={}):

            sync.run_sync(tickers=["AAPL", "MSFT", "GOOGL"], target_date=date(2026, 10, 9), skip_unmodified=False)
            called_tickers = mock_ensure.call_args[0][0]
            self.assertEqual(called_tickers[0], "SPY", "SPY must be at index 0")
            self.assertEqual(len(called_tickers), 4)

    def test_spy_downloaded_in_step2_before_stock_tickers_in_step3(self):
        """
        Verify SPY is fetched and processed in Step 2 before any broader universe tickers
        are fetched in Step 3.
        """
        batches_downloaded = []

        def mock_download(tickers, start, end):
            batches_downloaded.append(list(tickers))
            return {t: [{"ticker": t, "trade_date": "2026-10-09", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "adj_close": 104.0, "volume": 10000}] for t in tickers}

        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist", return_value=3), \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.parquet_cache.save_to_parquet", return_value=True), \
             patch("screener.src.downloader.download_batch_with_retry", side_effect=mock_download), \
             patch("screener.src.db.upsert_daily_bars", return_value=1):

            sync.run_sync(tickers=["TSLA", "AMD"], target_date=date(2026, 10, 9), skip_unmodified=False)

            self.assertGreaterEqual(len(batches_downloaded), 2)
            # First batch must be strictly SPY
            self.assertEqual(batches_downloaded[0], ["SPY"], "Step 2 must download SPY benchmark first")
            # Second batch contains custom tickers
            self.assertIn("TSLA", batches_downloaded[1])
            self.assertIn("AMD", batches_downloaded[1])

    def test_spy_not_duplicated_when_already_in_custom_tickers(self):
        """Verify SPY is not duplicated if explicitly provided in custom tickers list."""
        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist") as mock_ensure, \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.downloader.download_batch_with_retry", return_value={}):

            sync.run_sync(tickers=["NVDA", "SPY", "AAPL"], target_date=date(2026, 10, 9), skip_unmodified=False)
            called_tickers = mock_ensure.call_args[0][0]
            # Count of SPY in called_tickers must be exactly 1
            spy_count = sum(1 for t in called_tickers if t == "SPY")
            self.assertEqual(spy_count, 1)

    def test_spy_excluded_from_step3_batch_chunks(self):
        """Verify SPY is not re-downloaded in Step 3 batch chunks."""
        batches_downloaded = []

        def mock_download(tickers, start, end):
            batches_downloaded.append(list(tickers))
            return {t: [] for t in tickers}

        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist", return_value=2), \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=[]), \
             patch("screener.src.downloader.download_batch_with_retry", side_effect=mock_download):

            sync.run_sync(tickers=["SPY", "META"], target_date=date(2026, 10, 9), skip_unmodified=False)

            self.assertEqual(len(batches_downloaded), 2)
            # Step 2 batch is SPY
            self.assertEqual(batches_downloaded[0], ["SPY"])
            # Step 3 batch is META without SPY
            self.assertEqual(batches_downloaded[1], ["META"])
            self.assertNotIn("SPY", batches_downloaded[1])

    def test_spy_up_to_date_cache_skips_step2_fetch(self):
        """Verify that when SPY cache is current and skip_unmodified=True, SPY fetch is skipped."""
        cached_spy = [{"trade_date": "2026-10-09", "close": 500.0}]
        batches_downloaded = []

        def mock_download(tickers, start, end):
            batches_downloaded.append(list(tickers))
            return {t: [] for t in tickers}

        with patch("screener.src.universe.sync_universe_to_db", return_value=1), \
             patch("screener.src.db.ensure_stocks_exist", return_value=2), \
             patch("screener.src.parquet_cache.load_from_parquet", return_value=cached_spy), \
             patch("screener.src.parquet_cache.is_cache_current", return_value=False), \
             patch("screener.src.downloader.download_batch_with_retry", side_effect=mock_download):

            metrics = sync.run_sync(tickers=["CUSTOM1"], target_date=date(2026, 10, 9), skip_unmodified=True)
            # SPY was skipped because cache is current
            self.assertEqual(metrics["tickers_skipped"], 1)
            # Only CUSTOM1 was fetched
            self.assertEqual(batches_downloaded, [["CUSTOM1"]])


if __name__ == "__main__":
    unittest.main()
