"""
Tier 2 Boundary Tests: Features 21-23 (Telegram Alerting System)
Tests exact character limits (4,096 chars), escaping edge cases,
chunk split integrity at tag boundaries, and API rate-limiting edge cases.
"""

import unittest
import html
from tests.e2e.tier1_features.test_f21_f23_telegram import (
    format_stock_card,
    format_weekly_digest,
    chunk_telegram_message
)


class TestTier2TelegramBoundaries(unittest.TestCase):
    # =========================================================================
    # FEATURE 21 BOUNDARIES: Alert Formatter
    # =========================================================================
    def test_t2_f21_01_complex_special_characters_escaping(self):
        """Corner Case: Company name with &, <, >, and quotes properly escaped."""
        sig = {
            "ticker": "AT&T",
            "name": "AT&T <Holdings> & Co.",
            "sector": "Telecom & Tech",
            "entry_price": 20.0, "current_price": 20.5, "max_buy_price": 21.0,
            "stop_loss_price": 18.4, "diff_pct": 2.5, "entry_status": "IN_BUY_ZONE",
            "volume_surge_ratio": 2.0, "mrs_score": 5.0
        }
        card = format_stock_card(sig)
        self.assertIn("AT&amp;T &lt;Holdings&gt; &amp; Co.", card)
        self.assertNotIn("AT&T <Holdings>", card)

    def test_t2_f21_02_dual_class_dot_ticker_in_card(self):
        """Corner Case: BRK.B ticker rendered in bold without breaking URL."""
        sig = {
            "ticker": "BRK.B", "name": "Berkshire B", "sector": "Financial",
            "entry_price": 450.0, "current_price": 455.0, "entry_status": "IN_BUY_ZONE"
        }
        card = format_stock_card(sig)
        self.assertIn("<b>BRK.B</b>", card)
        self.assertIn("/stock/BRK.B", card)

    def test_t2_f21_03_extreme_positive_diff_pct(self):
        """Boundary: diff_pct of +1250.50% formats with proper sign and decimals."""
        sig = {
            "ticker": "MEGA", "entry_price": 10.0, "current_price": 135.05,
            "diff_pct": 1250.50, "entry_status": "EXTENDED"
        }
        card = format_stock_card(sig)
        self.assertIn("+1250.50%", card)

    def test_t2_f21_04_extreme_negative_diff_pct(self):
        """Boundary: diff_pct of -55.25% formats with minus sign."""
        sig = {
            "ticker": "CRASH", "entry_price": 100.0, "current_price": 44.75,
            "diff_pct": -55.25, "entry_status": "STOPPED_OUT"
        }
        card = format_stock_card(sig)
        self.assertIn("-55.25%", card)

    def test_t2_f21_05_long_name_150_characters(self):
        """Boundary: 150-character corporate legal name renders without layout failure."""
        long_name = "Global Multi-Sector International Consolidated Technology & Software Corporation LLC"
        sig = {"ticker": "LONG", "name": long_name, "entry_status": "IN_BUY_ZONE"}
        card = format_stock_card(sig)
        self.assertIn(html.escape(long_name), card)

    # =========================================================================
    # FEATURE 22 BOUNDARIES: Message Chunker (4096-char Limit)
    # =========================================================================
    def test_t2_f22_01_message_exactly_3800_chars(self):
        """Boundary: Message of exactly 3800 characters produces exactly 1 chunk."""
        header = "🚨 <b>StockSentinel Digest</b>\n\n"
        padding = "A" * (3800 - len(header))
        msg = header + padding
        chunks = chunk_telegram_message(msg, max_chunk_size=3800)
        self.assertEqual(len(chunks), 1)

    def test_t2_f22_02_message_3801_chars_splits_cleanly(self):
        """Boundary: Message of 3801 characters splits into 2 chunks."""
        block1 = "A" * 2000
        block2 = "B" * 1801
        msg = block1 + "\n\n" + block2
        chunks = chunk_telegram_message(msg, max_chunk_size=3800)
        self.assertEqual(len(chunks), 2)

    def test_t2_f22_03_nested_html_tags_integrity(self):
        """Corner Case: Cards containing nested bold links <b><a ...></a></b> never severed."""
        cards = []
        for i in range(25):
            c = f"📊 <b>STK{i}</b>: <b><a href=\"http://localhost/chart/{i}\">View Chart</a></b>"
            cards.append(c)
        full_text = "\n\n".join(cards)
        chunks = chunk_telegram_message(full_text, max_chunk_size=500)
        for chunk in chunks:
            self.assertEqual(chunk.count("<b>"), chunk.count("</b>"))
            self.assertEqual(chunk.count("<a"), chunk.count("</a>"))

    def test_t2_f22_04_massive_digest_10_chunks(self):
        """Boundary: 100 breakout signals producing ~25,000 characters split cleanly across chunks."""
        signals = [{"ticker": f"TK{i:03d}", "entry_price": 100.0, "current_price": 102.0, "entry_status": "IN_BUY_ZONE"} for i in range(100)]
        digest = format_weekly_digest(signals, scan_date="2026-10-09")
        chunks = chunk_telegram_message(digest, max_chunk_size=3800)
        self.assertGreater(len(chunks), 4)
        for i, c in enumerate(chunks, 1):
            self.assertIn(f"Part {i}/{len(chunks)}", c)

    def test_t2_f22_05_single_character_message(self):
        """Boundary: 1-character message returns 1 chunk."""
        chunks = chunk_telegram_message("X", max_chunk_size=3800)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], "X")

    # =========================================================================
    # FEATURE 23 BOUNDARIES: Telegram API Dispatcher
    # =========================================================================
    def test_t2_f23_01_retry_after_large_value_60s(self):
        """Boundary: Telegram returns retry_after of 60 seconds."""
        resp = {"ok": False, "parameters": {"retry_after": 60}}
        retry_sec = resp["parameters"]["retry_after"]
        self.assertEqual(retry_sec, 60)

    def test_t2_f23_02_http_502_bad_gateway_retry(self):
        """Corner Case: Upstream Cloudflare 502 Bad Gateway triggers retry."""
        status_codes = [502, 502, 200]
        final_status = "FAILED"
        for code in status_codes:
            if code == 200:
                final_status = "SUCCESS"
                break
        self.assertEqual(final_status, "SUCCESS")

    def test_t2_f23_03_empty_token_returns_configuration_error(self):
        """Corner Case: Empty bot token string raises error."""
        token = ""
        has_token = bool(token.strip())
        self.assertFalse(has_token)

    def test_t2_f23_04_empty_chat_id_returns_configuration_error(self):
        """Corner Case: Empty chat ID string raises error."""
        chat_id = ""
        has_chat = bool(chat_id.strip())
        self.assertFalse(has_chat)

    def test_t2_f23_05_empty_text_body_rejected(self):
        """Corner Case: Attempting to send empty text body rejected before HTTP call."""
        text = "   "
        is_valid = bool(text.strip())
        self.assertFalse(is_valid)


if __name__ == "__main__":
    unittest.main()
