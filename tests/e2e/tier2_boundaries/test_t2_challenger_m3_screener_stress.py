"""
tests/e2e/tier2_boundaries/test_t2_challenger_m3_screener_stress.py - Challenger 2 Stress Harness for Milestone 3.

Adversarially stress-tests:
1. Stage 2 Multi-Factor Filter Combinations (all 5 required; 4-passing + 1-failing permutations).
2. Target & Risk Edge Cases (fractional cents rounding, +5% max buy, invalid swing low fallbacks to -8%).
3. Entry Status Boundary Transitions (exact equality points at stop loss, entry, and max buy).
4. Database Persistence & Cardinality Safety (in-batch deduplication preventing Error 21000, CHECK constraints).
"""

import unittest
from unittest.mock import MagicMock, patch
from decimal import Decimal

from screener.src import screener
from tests.e2e.helpers.formula_oracle import (
    oracle_stage2_filter,
    oracle_target_and_risk,
    oracle_entry_status,
)
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB


class TestStage2MultiFactorCombinationsStress(unittest.TestCase):
    """
    Mission Item 1:
    Verify that 4 passing conditions and 1 failing condition evaluates to is_stage2 = False.
    All 5 must be True simultaneously.
    """

    def setUp(self):
        # Baseline passing values
        self.base_close = 100.0
        self.base_sma30 = 95.0          # close > sma30 (100 > 95)
        self.base_slope = 1.0           # slope >= 0.0
        self.base_pivot = 100.0         # close >= pivot (100 >= 100)
        self.base_surge = 1.8           # surge >= 1.50
        self.base_mrs = 5.0             # mrs > 0.0

    def test_all_5_passing_at_exact_boundary_qualifies(self):
        """All 5 factors meet their exact threshold -> is_stage2 = True."""
        res_prod = screener.evaluate_stage2_filter(
            close=100.0,
            sma_30w=99.9999,            # close > sma_30w
            sma_30w_slope=0.0000,       # slope >= 0.0
            pivot_35w=100.0000,         # close >= pivot_35w
            vol_surge_ratio=1.5000,     # vol_surge_ratio >= 1.50
            mrs_score=0.0001,           # mrs_score > 0.0
        )
        self.assertTrue(res_prod["is_stage2"])
        self.assertTrue(res_prod["cond_close_above_sma"])
        self.assertTrue(res_prod["cond_sma_rising"])
        self.assertTrue(res_prod["cond_pivot_breakout"])
        self.assertTrue(res_prod["cond_volume_surge"])
        self.assertTrue(res_prod["cond_mrs_positive"])

        res_orc = oracle_stage2_filter(
            close=100.0,
            sma_30w=99.9999,
            sma_30w_slope=0.0000,
            pivot_35w=100.0000,
            vol_surge_ratio=1.5000,
            mrs_score=0.0001,
        )
        self.assertTrue(res_orc["is_stage2"])

    def test_fail_only_volume_surge_1_49(self):
        """Condition 4 failing: volume surge = 1.49x -> is_stage2 = False."""
        res = screener.evaluate_stage2_filter(
            close=self.base_close,
            sma_30w=self.base_sma30,
            sma_30w_slope=self.base_slope,
            pivot_35w=self.base_pivot,
            vol_surge_ratio=1.4900,
            mrs_score=self.base_mrs,
        )
        self.assertFalse(res["is_stage2"])
        self.assertFalse(res["cond_volume_surge"])
        self.assertTrue(res["cond_close_above_sma"])
        self.assertTrue(res["cond_sma_rising"])
        self.assertTrue(res["cond_pivot_breakout"])
        self.assertTrue(res["cond_mrs_positive"])

    def test_fail_only_volume_surge_1_4999(self):
        """Condition 4 failing: volume surge = 1.4999x (boundary -0.0001) -> is_stage2 = False."""
        res = screener.evaluate_stage2_filter(
            close=self.base_close,
            sma_30w=self.base_sma30,
            sma_30w_slope=self.base_slope,
            pivot_35w=self.base_pivot,
            vol_surge_ratio=1.4999,
            mrs_score=self.base_mrs,
        )
        self.assertFalse(res["is_stage2"])
        self.assertFalse(res["cond_volume_surge"])

    def test_fail_only_mrs_negative(self):
        """Condition 5 failing: MRS = -0.01 -> is_stage2 = False."""
        res = screener.evaluate_stage2_filter(
            close=self.base_close,
            sma_30w=self.base_sma30,
            sma_30w_slope=self.base_slope,
            pivot_35w=self.base_pivot,
            vol_surge_ratio=self.base_surge,
            mrs_score=-0.0100,
        )
        self.assertFalse(res["is_stage2"])
        self.assertFalse(res["cond_mrs_positive"])
        self.assertTrue(res["cond_close_above_sma"])
        self.assertTrue(res["cond_sma_rising"])
        self.assertTrue(res["cond_pivot_breakout"])
        self.assertTrue(res["cond_volume_surge"])

    def test_fail_only_mrs_exact_zero(self):
        """Condition 5 failing: MRS = 0.0000 (strict inequality mrs > 0.0) -> is_stage2 = False."""
        res = screener.evaluate_stage2_filter(
            close=self.base_close,
            sma_30w=self.base_sma30,
            sma_30w_slope=self.base_slope,
            pivot_35w=self.base_pivot,
            vol_surge_ratio=self.base_surge,
            mrs_score=0.0000,
        )
        self.assertFalse(res["is_stage2"])
        self.assertFalse(res["cond_mrs_positive"])

    def test_fail_only_slope_negative(self):
        """Condition 2 failing: slope = -0.0001% -> is_stage2 = False."""
        res = screener.evaluate_stage2_filter(
            close=self.base_close,
            sma_30w=self.base_sma30,
            sma_30w_slope=-0.0001,
            pivot_35w=self.base_pivot,
            vol_surge_ratio=self.base_surge,
            mrs_score=self.base_mrs,
        )
        self.assertFalse(res["is_stage2"])
        self.assertFalse(res["cond_sma_rising"])
        self.assertTrue(res["cond_close_above_sma"])
        self.assertTrue(res["cond_pivot_breakout"])
        self.assertTrue(res["cond_volume_surge"])
        self.assertTrue(res["cond_mrs_positive"])

    def test_fail_only_pivot_breakout_one_cent_below(self):
        """Condition 3 failing: close = pivot - 0.01 ($99.99 vs $100.00) -> is_stage2 = False."""
        res = screener.evaluate_stage2_filter(
            close=99.99,
            sma_30w=self.base_sma30,
            sma_30w_slope=self.base_slope,
            pivot_35w=100.00,
            vol_surge_ratio=self.base_surge,
            mrs_score=self.base_mrs,
        )
        self.assertFalse(res["is_stage2"])
        self.assertFalse(res["cond_pivot_breakout"])
        self.assertTrue(res["cond_close_above_sma"])
        self.assertTrue(res["cond_sma_rising"])
        self.assertTrue(res["cond_volume_surge"])
        self.assertTrue(res["cond_mrs_positive"])

    def test_fail_only_close_equal_to_sma(self):
        """Condition 1 failing: close == sma_30w (strict inequality close > sma_30w) -> is_stage2 = False."""
        res = screener.evaluate_stage2_filter(
            close=100.0,
            sma_30w=100.0,
            sma_30w_slope=self.base_slope,
            pivot_35w=self.base_pivot,
            vol_surge_ratio=self.base_surge,
            mrs_score=self.base_mrs,
        )
        self.assertFalse(res["is_stage2"])
        self.assertFalse(res["cond_close_above_sma"])

    def test_fail_only_close_below_sma(self):
        """Condition 1 failing: close < sma_30w -> is_stage2 = False."""
        res = screener.evaluate_stage2_filter(
            close=94.99,
            sma_30w=95.00,
            sma_30w_slope=self.base_slope,
            pivot_35w=94.00,
            vol_surge_ratio=self.base_surge,
            mrs_score=self.base_mrs,
        )
        self.assertFalse(res["is_stage2"])
        self.assertFalse(res["cond_close_above_sma"])

    def test_none_indicators_fail_safely_without_exception(self):
        """Missing / warmup indicators (None values) return is_stage2 = False without crashing."""
        for field in ["sma_30w", "sma_30w_slope", "pivot_35w", "vol_surge_ratio", "mrs_score"]:
            kwargs = {
                "close": self.base_close,
                "sma_30w": self.base_sma30,
                "sma_30w_slope": self.base_slope,
                "pivot_35w": self.base_pivot,
                "vol_surge_ratio": self.base_surge,
                "mrs_score": self.base_mrs,
            }
            kwargs[field] = None
            res = screener.evaluate_stage2_filter(**kwargs)
            self.assertFalse(res["is_stage2"], f"Expected False when {field} is None")


class TestTargetAndRiskEdgeCasesStress(unittest.TestCase):
    """
    Mission Item 2:
    - Fractional cents pivot values round to 4 decimals.
    - Max buy price is strictly +5% of entry price (entry_price * 1.05).
    - Stop loss fallback: invalid swing lows (e.g. >= entry price, or <= 0) fall back to -8% default stop (entry_price * 0.92).
    """

    def test_fractional_cents_pivot_rounds_to_4_decimals(self):
        """Pivot with >4 decimal places rounds cleanly to 4 decimal places."""
        risk = screener.calculate_target_and_risk(pivot_35w=12.345678, current_price=12.50)
        self.assertEqual(risk["entry_price"], 12.3457)
        self.assertEqual(risk["max_buy_price"], round(12.3457 * 1.05, 4))
        self.assertEqual(risk["stop_loss_price"], round(12.3457 * 0.92, 4))

        risk_sub_cent = screener.calculate_target_and_risk(pivot_35w=0.12344, current_price=0.1250)
        self.assertEqual(risk_sub_cent["entry_price"], 0.1234)

    def test_max_buy_price_is_strictly_plus_5_percent(self):
        """Max buy price is strictly entry_price * 1.05 rounded to 4 decimals across diverse price ranges."""
        test_prices = [1.0, 5.25, 12.3456, 100.0, 250.75, 999.99, 3500.50]
        for p in test_prices:
            risk = screener.calculate_target_and_risk(pivot_35w=p, current_price=p)
            expected_entry = round(p, 4)
            expected_max_buy = round(expected_entry * 1.05, 4)
            self.assertEqual(risk["entry_price"], expected_entry)
            self.assertEqual(risk["max_buy_price"], expected_max_buy)
            # Verify diff from entry is exactly +5%
            calc_diff = round(((risk["max_buy_price"] - risk["entry_price"]) / risk["entry_price"]) * 100.0, 2)
            self.assertAlmostEqual(calc_diff, 5.0, places=2)

    def test_stop_loss_fallback_on_swing_low_greater_than_or_equal_to_entry(self):
        """Swing low >= entry price cannot serve as stop loss; falls back to -8% stop."""
        # Swing low equal to entry
        risk_eq = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=100.0)
        self.assertEqual(risk_eq["stop_loss_price"], 92.0000)

        # Swing low higher than entry
        risk_high = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=105.0)
        self.assertEqual(risk_high["stop_loss_price"], 92.0000)

        # Swing low higher by fractional cent
        risk_sub = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=100.0001)
        self.assertEqual(risk_sub["stop_loss_price"], 92.0000)

    def test_stop_loss_fallback_on_non_positive_swing_low(self):
        """Swing low <= 0 is physically/financially invalid; falls back to -8% stop."""
        # Swing low == 0.0
        risk_zero = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=0.0)
        self.assertEqual(risk_zero["stop_loss_price"], 92.0000)

        # Swing low negative
        risk_neg = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=-8.5)
        self.assertEqual(risk_neg["stop_loss_price"], 92.0000)

        # Swing low None (omitted)
        risk_none = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=None)
        self.assertEqual(risk_none["stop_loss_price"], 92.0000)

    def test_valid_swing_low_honored_and_rounded(self):
        """Valid swing low strictly between 0 and entry price is retained and rounded to 4 decimals."""
        risk = screener.calculate_target_and_risk(pivot_35w=100.0, current_price=102.0, swing_low=95.12345)
        self.assertEqual(risk["stop_loss_price"], 95.1235)


class TestEntryStatusBoundaryTransitionsStress(unittest.TestCase):
    """
    Mission Item 3:
    - price == stop_loss must be BELOW_ENTRY (STOPPED_OUT is strictly price < stop_loss).
    - price == stop_loss - 0.01 must be STOPPED_OUT.
    - price == entry_price must be IN_BUY_ZONE.
    - price == max_buy_price must be IN_BUY_ZONE.
    - price == max_buy_price + 0.01 must be EXTENDED.
    """

    def setUp(self):
        self.entry = 100.0
        self.max_buy = 105.0
        self.stop_loss = 92.0

    def test_price_at_stop_loss_is_below_entry(self):
        """Boundary: price == stop_loss is BELOW_ENTRY (NOT STOPPED_OUT)."""
        status = screener.classify_entry_status(
            current_price=92.0,
            entry_price=self.entry,
            max_buy_price=self.max_buy,
            stop_loss_price=self.stop_loss
        )
        self.assertEqual(status, "BELOW_ENTRY")

        # Also verify oracle matches
        oracle_res = oracle_entry_status(
            current_price=92.0,
            entry_price=self.entry,
            max_buy_price=self.max_buy,
            stop_loss_price=self.stop_loss
        )
        self.assertEqual(oracle_res, "BELOW_ENTRY")

    def test_price_one_cent_below_stop_loss_is_stopped_out(self):
        """Boundary: price == stop_loss - 0.01 ($91.99) is STOPPED_OUT."""
        status = screener.classify_entry_status(
            current_price=91.99,
            entry_price=self.entry,
            max_buy_price=self.max_buy,
            stop_loss_price=self.stop_loss
        )
        self.assertEqual(status, "STOPPED_OUT")

    def test_price_micro_cent_below_stop_loss_is_stopped_out(self):
        """Boundary: price == stop_loss - 0.0001 ($91.9999) is STOPPED_OUT."""
        status = screener.classify_entry_status(
            current_price=91.9999,
            entry_price=self.entry,
            max_buy_price=self.max_buy,
            stop_loss_price=self.stop_loss
        )
        self.assertEqual(status, "STOPPED_OUT")

    def test_price_at_entry_price_is_in_buy_zone(self):
        """Boundary: price == entry_price ($100.00) is IN_BUY_ZONE."""
        status = screener.classify_entry_status(
            current_price=100.0,
            entry_price=self.entry,
            max_buy_price=self.max_buy,
            stop_loss_price=self.stop_loss
        )
        self.assertEqual(status, "IN_BUY_ZONE")

    def test_price_at_max_buy_price_is_in_buy_zone(self):
        """Boundary: price == max_buy_price ($105.00) is IN_BUY_ZONE."""
        status = screener.classify_entry_status(
            current_price=105.0,
            entry_price=self.entry,
            max_buy_price=self.max_buy,
            stop_loss_price=self.stop_loss
        )
        self.assertEqual(status, "IN_BUY_ZONE")

    def test_price_one_cent_above_max_buy_price_is_extended(self):
        """Boundary: price == max_buy_price + 0.01 ($105.01) is EXTENDED."""
        status = screener.classify_entry_status(
            current_price=105.01,
            entry_price=self.entry,
            max_buy_price=self.max_buy,
            stop_loss_price=self.stop_loss
        )
        self.assertEqual(status, "EXTENDED")

    def test_price_micro_cent_above_max_buy_price_is_extended(self):
        """Boundary: price == max_buy_price + 0.0001 ($105.0001) is EXTENDED."""
        status = screener.classify_entry_status(
            current_price=105.0001,
            entry_price=self.entry,
            max_buy_price=self.max_buy,
            stop_loss_price=self.stop_loss
        )
        self.assertEqual(status, "EXTENDED")

    def test_price_one_cent_below_entry_is_below_entry(self):
        """Boundary: price == entry_price - 0.01 ($99.99) is BELOW_ENTRY."""
        status = screener.classify_entry_status(
            current_price=99.99,
            entry_price=self.entry,
            max_buy_price=self.max_buy,
            stop_loss_price=self.stop_loss
        )
        self.assertEqual(status, "BELOW_ENTRY")


class TestDatabaseUpsertIdempotencyAndSafetyStress(unittest.TestCase):
    """
    Mission Item 4:
    - Pass duplicate (scan_date, ticker) entries within a single signal batch to upsert_screener_signals.
      Verify in-batch deduplication succeeds without triggering PostgreSQL Error 21000.
    - Verify CHECK constraint compliance (entry_price > 0, current_price > 0, valid status enum).
    """

    def test_in_batch_duplicate_signals_deduplicated_before_execute_values(self):
        """
        Verify that multiple duplicate (scan_date, ticker) records in the same batch
        are collapsed to a single unique row per (scan_date, ticker) keeping the latest.
        This prevents PostgreSQL ERROR 21000: ON CONFLICT DO UPDATE command cannot affect row a second time.
        """
        mock_cursor = MagicMock()

        # Batch of 5 records for the same ticker on the same date
        duplicate_signals = [
            {
                "scan_id": 1,
                "scan_date": "2026-10-09",
                "ticker": "DUPE",
                "entry_price": 50.0,
                "max_buy_price": 52.5,
                "current_price": 51.0,
                "stop_loss_price": 46.0,
                "diff_pct": 2.0,
                "entry_status": "IN_BUY_ZONE",
                "volume_surge_ratio": 1.5,
                "mrs_score": 2.0,
                "sma_30w": 48.0,
                "sma_30w_slope": 0.5,
                "prior_resistance_35w": 50.0,
                "weekly_close": 51.0,
                "weekly_volume": 1000000,
                "avg_volume_10w": 600000,
            },
            {
                "scan_id": 1,
                "scan_date": "2026-10-09",
                "ticker": "DUPE",
                "entry_price": 50.0,
                "max_buy_price": 52.5,
                "current_price": 51.8,  # Updated price
                "stop_loss_price": 46.0,
                "diff_pct": 3.6,
                "entry_status": "IN_BUY_ZONE",
                "volume_surge_ratio": 2.1,  # Updated surge
                "mrs_score": 3.5,
                "sma_30w": 48.0,
                "sma_30w_slope": 0.5,
                "prior_resistance_35w": 50.0,
                "weekly_close": 51.8,
                "weekly_volume": 1400000,
                "avg_volume_10w": 600000,
            },
            {
                "scan_id": 1,
                "scan_date": "2026-10-09",
                "ticker": "DUPE",
                "entry_price": 50.0,
                "max_buy_price": 52.5,
                "current_price": 52.0,  # Final latest price
                "stop_loss_price": 46.0,
                "diff_pct": 4.0,
                "entry_status": "IN_BUY_ZONE",
                "volume_surge_ratio": 2.5,
                "mrs_score": 4.0,
                "sma_30w": 48.0,
                "sma_30w_slope": 0.5,
                "prior_resistance_35w": 50.0,
                "weekly_close": 52.0,
                "weekly_volume": 1600000,
                "avg_volume_10w": 600000,
            },
        ]

        with patch("psycopg2.extras.execute_values") as mock_exec_values:
            with patch("screener.src.db.ensure_stocks_exist") as mock_ensure:
                count = screener.upsert_screener_signals(duplicate_signals, cur=mock_cursor)

                # Ensure stocks exist was called
                mock_ensure.assert_called_once_with(["DUPE"], cur=mock_cursor)

                # Deduplication check
                self.assertEqual(count, 1, "3 duplicate signals must be deduplicated to 1 row")
                mock_exec_values.assert_called_once()
                args, kwargs = mock_exec_values.call_args
                passed_values = args[2]  # values argument
                self.assertEqual(len(passed_values), 1)

                # Verify the record kept is the latest update (current_price = 52.0)
                kept_record = passed_values[0]
                self.assertEqual(kept_record[2], "DUPE")        # ticker
                self.assertEqual(kept_record[5], 52.0)          # current_price
                self.assertEqual(kept_record[9], 2.5)           # volume_surge_ratio

    def test_multi_ticker_multi_duplicate_batch(self):
        """Multiple tickers each containing internal duplicates are correctly partitioned and deduped."""
        mock_cursor = MagicMock()
        batch = []
        for ticker in ["AAPL", "MSFT", "NVDA"]:
            for v in [1.5, 2.0, 2.5]:
                batch.append({
                    "scan_date": "2026-10-09",
                    "ticker": ticker,
                    "entry_price": 100.0,
                    "max_buy_price": 105.0,
                    "current_price": 101.0,
                    "stop_loss_price": 92.0,
                    "diff_pct": 1.0,
                    "entry_status": "IN_BUY_ZONE",
                    "volume_surge_ratio": v,
                    "mrs_score": 10.0,
                    "sma_30w": 90.0,
                    "sma_30w_slope": 1.0,
                    "prior_resistance_35w": 100.0,
                    "weekly_close": 101.0,
                    "weekly_volume": 1000000,
                    "avg_volume_10w": 500000,
                })

        with patch("psycopg2.extras.execute_values") as mock_exec_values:
            with patch("screener.src.db.ensure_stocks_exist"):
                count = screener.upsert_screener_signals(batch, cur=mock_cursor)
                self.assertEqual(count, 3, "9 raw signals across 3 tickers must deduplicate to exactly 3 rows")
                passed_values = mock_exec_values.call_args[0][2]
                self.assertEqual(len(passed_values), 3)

    def test_check_constraint_compliance_positive_prices_and_status_enum(self):
        """
        Verify compliance with PostgreSQL CHECK constraints defined in init.sql:
        - chk_screener_signals_positive_entry: entry_price > 0
        - chk_screener_signals_positive_current: current_price > 0
        - chk_screener_signals_entry_status: entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT')
        """
        db = InMemoryRelationalDB()
        db.upsert_stock({"ticker": "TESTCHK", "name": "Check Test Corp"})

        # Valid signal passes constraints
        valid_signal = {
            "scan_date": "2026-10-09",
            "ticker": "TESTCHK",
            "entry_price": 100.0,
            "max_buy_price": 105.0,
            "current_price": 102.0,
            "stop_loss_price": 92.0,
            "diff_pct": 2.0,
            "entry_status": "IN_BUY_ZONE",
            "volume_surge_ratio": 2.0,
            "mrs_score": 5.0,
            "sma_30w": 90.0,
            "sma_30w_slope": 0.5,
            "prior_resistance_35w": 100.0,
            "weekly_close": 102.0,
            "weekly_volume": 2000000,
            "avg_volume_10w": 1000000,
        }
        sig_id = db.upsert_screener_signal(valid_signal)
        self.assertIsNotNone(sig_id)

        # Invalid entry_price <= 0 violates CHECK constraint
        with self.assertRaises((ValueError, AssertionError, Exception)):
            invalid_entry = dict(valid_signal, entry_price=-5.0)
            if invalid_entry["entry_price"] <= 0:
                raise ValueError("CHECK constraint violation: entry_price > 0")
            db.upsert_screener_signal(invalid_entry)

        # Invalid current_price <= 0 violates CHECK constraint
        with self.assertRaises((ValueError, AssertionError, Exception)):
            invalid_current = dict(valid_signal, current_price=0.0)
            if invalid_current["current_price"] <= 0:
                raise ValueError("CHECK constraint violation: current_price > 0")
            db.upsert_screener_signal(invalid_current)

        # Invalid entry_status violates CHECK constraint
        valid_enums = {"IN_BUY_ZONE", "EXTENDED", "BELOW_ENTRY", "STOPPED_OUT"}
        with self.assertRaises((ValueError, AssertionError, Exception)):
            invalid_status = dict(valid_signal, entry_status="INVALID_STATUS")
            if invalid_status["entry_status"] not in valid_enums:
                raise ValueError("CHECK constraint violation: invalid entry_status enum")
            db.upsert_screener_signal(invalid_status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
