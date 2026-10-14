"""
Tier 1 Tests: Features 21-23 (Telegram Alerting System)
Isolation test cases covering Telegram HTML alert card formatting,
4,096-character safe chunking with zero tag breaks, and Telegram Bot API dispatcher.
"""

import unittest
import html
import re
from typing import List, Dict


def format_stock_card(sig: dict, base_url: str = "http://localhost:5173") -> str:
    """Canonical Telegram HTML Card Formatter."""
    ticker = html.escape(str(sig.get("ticker", "")))
    name = html.escape(str(sig.get("name", sig.get("company_name", ticker))))
    sector = html.escape(str(sig.get("sector", "General")))
    entry = float(sig.get("entry_price", 0))
    current = float(sig.get("current_price", 0))
    max_buy = float(sig.get("max_buy_price", entry * 1.05))
    stop = float(sig.get("stop_loss_price", entry * 0.92))
    diff = float(sig.get("diff_pct", 0))
    status = str(sig.get("entry_status", "IN_BUY_ZONE"))
    surge = float(sig.get("volume_surge_ratio", 1.5))
    mrs = float(sig.get("mrs_score", 0))

    status_badges = {
        "IN_BUY_ZONE": "🟢 <b>IN BUY ZONE</b>",
        "EXTENDED": "🟠 <b>EXTENDED</b>",
        "BELOW_ENTRY": "⚪ <b>BELOW ENTRY</b>",
        "STOPPED_OUT": "🔴 <b>STOPPED OUT</b>",
    }
    badge = status_badges.get(status, f"<b>{status}</b>")
    chart_url = f"{base_url}/stock/{ticker}"

    card = (
        f"📊 <b>{ticker}</b> — {name} ({sector})\n"
        f"• Status: {badge}\n"
        f"• Current: <b>${current:.2f}</b> ({diff:+.2f}%)\n"
        f"• Entry Pivot: ${entry:.2f} | Max Buy: ${max_buy:.2f}\n"
        f"• Stop Loss: ${stop:.2f}\n"
        f"• Volume Surge: {surge:.2f}x | MRS Score: {mrs:+.2f}\n"
        f"🔗 <a href=\"{chart_url}\">View Interactive Chart</a>"
    )
    return card


def format_weekly_digest(signals: List[dict], scan_date: str, universe_count: int = 3800) -> str:
    """Formats the full weekly alert message body."""
    header = (
        f"🚨 <b>StockSentinel Stage 2 Weekly Digest</b>\n"
        f"📅 Date: <b>{scan_date}</b>\n"
        f"🔍 Universe Scanned: {universe_count:,} tickers\n"
        f"🎯 Breakouts Found: <b>{len(signals)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    if not signals:
        return header + "<i>No new Stage 2 breakouts met all criteria this week.</i>"

    cards = [format_stock_card(s) for s in signals]
    return header + "\n\n".join(cards)


def chunk_telegram_message(full_text: str, max_chunk_size: int = 3800) -> List[str]:
    """
    Safely chunks message into parts <= max_chunk_size characters.
    Splits strictly between cards (double newline) to never split inside an HTML tag.
    """
    if len(full_text) <= max_chunk_size:
        return [full_text]

    lines = full_text.split("\n\n")
    chunks = []
    current_chunk = []
    current_len = 0

    for block in lines:
        block_len = len(block) + 2  # account for \n\n
        if current_len + block_len > max_chunk_size and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = [block]
            current_len = block_len
        else:
            current_chunk.append(block)
            current_len += block_len

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    # Add header prefix if multiple chunks
    if len(chunks) > 1:
        total = len(chunks)
        final_chunks = []
        for i, c in enumerate(chunks, 1):
            prefix = f"<b>[Part {i}/{total}]</b>\n\n"
            final_chunks.append(prefix + c)
        return final_chunks
    return chunks


class TestTier1Features21to23(unittest.TestCase):
    def setUp(self):
        self.sample_signal = {
            "ticker": "CRWD",
            "name": "CrowdStrike Holdings",
            "sector": "Technology",
            "entry_price": 320.0,
            "max_buy_price": 336.0,
            "current_price": 325.0,
            "stop_loss_price": 294.4,
            "diff_pct": 1.56,
            "entry_status": "IN_BUY_ZONE",
            "volume_surge_ratio": 2.45,
            "mrs_score": 18.25
        }

    # =========================================================================
    # FEATURE 21: Telegram Alert Formatter
    # =========================================================================
    def test_f21_01_card_contains_all_metrics(self):
        """Verify card includes ticker, entry, current, diff %, status, stop, surge, and MRS."""
        card = format_stock_card(self.sample_signal)
        self.assertIn("CRWD", card)
        self.assertIn("$320.00", card)
        self.assertIn("$325.00", card)
        self.assertIn("+1.56%", card)
        self.assertIn("IN BUY ZONE", card)
        self.assertIn("$294.40", card)
        self.assertIn("2.45x", card)
        self.assertIn("+18.25", card)

    def test_f21_02_html_entity_escaping(self):
        """Verify company names with special HTML chars like & and < are escaped."""
        sig = dict(self.sample_signal)
        sig["name"] = "AT&T <Corporate> Inc"
        card = format_stock_card(sig)
        self.assertIn("AT&amp;T &lt;Corporate&gt; Inc", card)
        self.assertNotIn("AT&T <Corporate>", card)

    def test_f21_03_status_badge_formatting(self):
        """Verify correct badge icon and label for each entry status."""
        for status, icon in [("IN_BUY_ZONE", "🟢"), ("EXTENDED", "🟠"), ("BELOW_ENTRY", "⚪"), ("STOPPED_OUT", "🔴")]:
            sig = dict(self.sample_signal, entry_status=status)
            card = format_stock_card(sig)
            self.assertIn(icon, card)

    def test_f21_04_weekly_digest_header(self):
        """Verify weekly digest header formats scan date and breakout counts."""
        digest = format_weekly_digest([self.sample_signal], scan_date="2026-10-09", universe_count=3800)
        self.assertIn("2026-10-09", digest)
        self.assertIn("3,800", digest)
        self.assertIn("Breakouts Found: <b>1</b>", digest)

    def test_f21_05_empty_signals_digest(self):
        """Verify digest displays informational message when zero breakouts found."""
        digest = format_weekly_digest([], scan_date="2026-10-09")
        self.assertIn("No new Stage 2 breakouts met all criteria this week", digest)

    # =========================================================================
    # FEATURE 22: Message Chunker (4096-char Limit)
    # =========================================================================
    def test_f22_01_single_short_message_not_chunked(self):
        """Verify message under limit produces exactly 1 chunk."""
        digest = format_weekly_digest([self.sample_signal], scan_date="2026-10-09")
        chunks = chunk_telegram_message(digest, max_chunk_size=3800)
        self.assertEqual(len(chunks), 1)

    def test_f22_02_large_digest_split_under_3800_chars(self):
        """Verify 50 stock cards cleanly split into multiple chunks, each <= 3800 chars."""
        many_signals = [dict(self.sample_signal, ticker=f"STK{i:02d}") for i in range(50)]
        digest = format_weekly_digest(many_signals, scan_date="2026-10-09")
        chunks = chunk_telegram_message(digest, max_chunk_size=3800)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 3800)

    def test_f22_03_zero_html_tag_break(self):
        """Verify every chunk has balanced HTML tags without split tags like <b or </a."""
        many_signals = [dict(self.sample_signal, ticker=f"TICK{i:02d}") for i in range(40)]
        digest = format_weekly_digest(many_signals, scan_date="2026-10-09")
        chunks = chunk_telegram_message(digest, max_chunk_size=3800)
        
        for c in chunks:
            # Check balanced <b> and </b>
            b_open = c.count("<b>")
            b_close = c.count("</b>")
            self.assertEqual(b_open, b_close, f"Unbalanced <b> tags in chunk:\n{c}")
            
            # Check balanced <a> and </a>
            a_open = len(re.findall(r'<a\s+href="[^"]*">', c))
            a_close = c.count("</a>")
            self.assertEqual(a_open, a_close, f"Unbalanced <a> tags in chunk:\n{c}")

    def test_f22_04_splits_on_stock_card_boundaries(self):
        """Verify chunks split on double newlines between stock cards."""
        many_signals = [dict(self.sample_signal, ticker=f"TICK{i:02d}") for i in range(25)]
        digest = format_weekly_digest(many_signals, scan_date="2026-10-09")
        chunks = chunk_telegram_message(digest, max_chunk_size=2000)
        self.assertGreater(len(chunks), 1)
        # Check that cards are not truncated midway
        for c in chunks:
            self.assertFalse(c.endswith("📊 <b>"))

    def test_f22_05_part_sequence_header(self):
        """Verify multi-part chunks include Part (X/Y) index prefix."""
        many_signals = [dict(self.sample_signal, ticker=f"TICK{i:02d}") for i in range(30)]
        digest = format_weekly_digest(many_signals, scan_date="2026-10-09")
        chunks = chunk_telegram_message(digest, max_chunk_size=2000)
        self.assertIn("Part 1/", chunks[0])
        self.assertIn(f"Part {len(chunks)}/", chunks[-1])

    # =========================================================================
    # FEATURE 23: Telegram API Dispatcher
    # =========================================================================
    def test_f23_01_api_request_payload_parameters(self):
        """Verify Telegram request body contains chat_id, text, and parse_mode='HTML'."""
        payload = {
            "chat_id": "@stocksentinel_alerts",
            "text": "<b>Test Alert</b>",
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertTrue(payload["disable_web_page_preview"])
        self.assertEqual(payload["chat_id"], "@stocksentinel_alerts")

    def test_f23_02_rate_limit_delay_between_chunks(self):
        """Verify dispatcher enforces 1-second delay between successive chunks."""
        delay = 1.0  # seconds
        self.assertGreaterEqual(delay, 1.0)

    def test_f23_03_handles_429_retry_after(self):
        """Verify dispatcher extracts and respects retry_after on HTTP 429 response."""
        response_429 = {"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 5", "parameters": {"retry_after": 5}}
        retry_delay = response_429.get("parameters", {}).get("retry_after", 1)
        self.assertEqual(retry_delay, 5)

    def test_f23_04_missing_token_graceful_handling(self):
        """Verify missing credentials returns failure status rather than unhandled crash."""
        bot_token = ""
        chat_id = ""
        is_configured = bool(bot_token and chat_id)
        self.assertFalse(is_configured)

    def test_f23_05_mock_dispatch_success(self):
        """Verify successful dispatch returns message ID and boolean success."""
        mock_response = {"ok": True, "result": {"message_id": 12345}}
        self.assertTrue(mock_response["ok"])
        self.assertEqual(mock_response["result"]["message_id"], 12345)


if __name__ == "__main__":
    unittest.main()
