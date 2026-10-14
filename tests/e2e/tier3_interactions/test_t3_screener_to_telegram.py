"""
Tier 3 Interaction Tests: M3 (Screener Engine) x M4 (Telegram Alerting)
Verifies that signals computed by the Stage 2 screener flow directly into
Telegram HTML digest cards, chunk safely, and preserve indicator precision.
"""

import unittest
from tests.e2e.tier1_features.test_f21_f23_telegram import (
    format_weekly_digest,
    chunk_telegram_message
)
from tests.e2e.helpers.formula_oracle import (
    oracle_target_and_risk,
    oracle_entry_status
)


class TestTier3ScreenerToTelegram(unittest.TestCase):
    def test_t3_01_screener_signal_to_telegram_card_fidelity(self):
        """Verifies that mathematical targets from screener are accurately reflected in Telegram card."""
        pivot = 150.0
        current = 153.5
        risk = oracle_target_and_risk(pivot_35w=pivot, current_price=current)
        status = oracle_entry_status(current, risk["entry_price"], risk["max_buy_price"], risk["stop_loss_price"])
        
        signal_record = {
            "ticker": "TSLA",
            "name": "Tesla Inc.",
            "sector": "Consumer Cyclical",
            "entry_price": risk["entry_price"],
            "max_buy_price": risk["max_buy_price"],
            "current_price": risk["current_price"],
            "stop_loss_price": risk["stop_loss_price"],
            "diff_pct": risk["diff_pct"],
            "entry_status": status,
            "volume_surge_ratio": 2.15,
            "mrs_score": 14.80
        }
        
        digest = format_weekly_digest([signal_record], scan_date="2026-10-09")
        self.assertIn("TSLA", digest)
        self.assertIn("$150.00", digest)
        self.assertIn("$157.50", digest)  # 150 * 1.05
        self.assertIn("$138.00", digest)  # 150 * 0.92
        self.assertIn("IN BUY ZONE", digest)
        self.assertIn("+2.33%", digest)
        self.assertIn("2.15x", digest)
        self.assertIn("+14.80", digest)

    def test_t3_02_status_badge_mapping_across_all_four_states(self):
        """Verifies all 4 screener status classifications map to their respective icons in Telegram."""
        cases = [
            ("IN_BUY_ZONE", "🟢"),
            ("EXTENDED", "🟠"),
            ("BELOW_ENTRY", "⚪"),
            ("STOPPED_OUT", "🔴"),
        ]
        for status, icon in cases:
            sig = {
                "ticker": "TEST", "name": "Test", "sector": "Tech",
                "entry_price": 100.0, "current_price": 100.0, "max_buy_price": 105.0,
                "stop_loss_price": 92.0, "diff_pct": 0.0, "entry_status": status
            }
            digest = format_weekly_digest([sig], scan_date="2026-10-09")
            self.assertIn(icon, digest)

    def test_t3_03_high_volume_breakout_batch_chunking_integrity(self):
        """Verifies 40 signals from a big market breakout chunk without losing any tickers."""
        signals = []
        for i in range(40):
            t = f"SYM{i:02d}"
            signals.append({
                "ticker": t, "name": f"Company {i}", "sector": "Tech",
                "entry_price": 100.0 + i, "current_price": 102.0 + i, "max_buy_price": (100.0 + i) * 1.05,
                "stop_loss_price": (100.0 + i) * 0.92, "diff_pct": 2.0, "entry_status": "IN_BUY_ZONE",
                "volume_surge_ratio": 2.0, "mrs_score": 10.0
            })
        
        digest = format_weekly_digest(signals, scan_date="2026-10-09")
        chunks = chunk_telegram_message(digest, max_chunk_size=3800)
        
        # Verify all 40 tickers are present across all chunks
        combined = "".join(chunks)
        for i in range(40):
            self.assertIn(f"SYM{i:02d}", combined)
            
        # Verify no chunk exceeds 3800 characters
        for c in chunks:
            self.assertLessEqual(len(c), 3800)

    def test_t3_04_zero_breakout_digest_generation(self):
        """Verifies empty screener output generates polite weekly digest without failing."""
        digest = format_weekly_digest([], scan_date="2026-10-09", universe_count=3800)
        self.assertIn("Breakouts Found: <b>0</b>", digest)
        self.assertIn("No new Stage 2 breakouts", digest)


if __name__ == "__main__":
    unittest.main()
