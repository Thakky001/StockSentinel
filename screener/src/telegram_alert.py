"""
screener/src/telegram_alert.py
──────────────────────────────────────────────────────────────────────────────
Telegram Alerting System for StockSentinel (Milestone M4).

Features implemented
--------------------
F21  Stock-card message formatter  – format_stock_card / format_alert_header
F22  Message chunker               – chunk_telegram_messages
F23  Telegram dispatcher           – send_telegram_message

Public entry point
------------------
  send_weekly_alert(signals, scan_date, universe_count) -> bool

All network I/O is synchronous (requests) and is guarded by retry logic with
exponential back-off and Telegram-specific rate-limit (HTTP 429) handling.
"""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Any, Dict, List, Optional

import requests

from screener.src import config
from screener.src.db import db_cursor

# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Telegram's hard limit is 4096 UTF-16 code units; we stay well under it so
# that formatting markers and emoji do not push us over.
MAX_CHUNK_SIZE: int = 3800

# Visual separator used inside stock cards and headers.
_CARD_SEPARATOR: str = "────────────────────────────"
_HEADER_SEPARATOR: str = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Telegram Bot API base URL (token is interpolated at call time).
_TELEGRAM_API_URL: str = "https://api.telegram.org/bot{token}/sendMessage"

# Delay between consecutive chunk dispatches (milliseconds → seconds).
_INTER_CHUNK_DELAY_S: float = 0.5


# ---------------------------------------------------------------------------
# F21 – Utility: HTML escaping
# ---------------------------------------------------------------------------


def escape_html(text: str) -> str:
    """
    Escape a string for safe embedding inside Telegram HTML parse-mode messages.

    Uses ``html.escape`` with ``quote=False`` so that single/double quotes are
    left unchanged (Telegram does not require them to be escaped in text nodes).

    Args:
        text: Arbitrary string value, including None-safe coercion via str().

    Returns:
        HTML-escaped string safe for use in Telegram ``parse_mode="HTML"`` messages.
    """
    return html.escape(str(text), quote=False)


# ---------------------------------------------------------------------------
# F21 – Stock card formatter
# ---------------------------------------------------------------------------


def format_stock_card(signal: Dict[str, Any], base_url: str = "") -> str:
    """
    Render a single stock breakout signal as a Telegram HTML message card.

    The card covers identification, status badge, key price levels, technical
    indicators, and a deep-link URL back to the StockSentinel web UI.

    Status badge mapping
    --------------------
    +---------------+------------------------------------------------------+
    | entry_status  | Badge text                                           |
    +===============+======================================================+
    | IN_BUY_ZONE   | 🟢 **IN BUY ZONE (+X.X%)**                          |
    | EXTENDED      | 🟡 **EXTENDED (+X.X%)** [Wait for pullback]          |
    | BELOW_ENTRY   | ⚪ **BELOW ENTRY (-X.X%)** [Retesting pivot]         |
    | STOPPED_OUT   | 🔴 **STOPPED OUT (-X.X%)** [Risk trigger]            |
    +---------------+------------------------------------------------------+

    Args:
        signal:   Dictionary containing all screener output fields.
                  Required keys: ticker, entry_price, current_price,
                  max_buy_price, stop_loss_price, diff_pct, entry_status,
                  volume_surge_ratio, mrs_score, sma_30w, sma_30w_slope.
                  Optional keys: name, sector.
        base_url: Root URL of the StockSentinel web application used to
                  build the deep-link chart anchor. Defaults to empty string
                  (link still renders but points to a relative path).

    Returns:
        Fully formatted Telegram HTML string for a single stock card.
    """
    ticker: str = escape_html(signal.get("ticker", "UNKNOWN"))
    name: str = escape_html(signal.get("name") or ticker)
    sector: str = escape_html(signal.get("sector") or "N/A")

    entry_price: float = float(signal.get("entry_price", 0))
    current_price: float = float(signal.get("current_price", 0))
    max_buy_price: float = float(signal.get("max_buy_price", 0))
    stop_loss_price: float = float(signal.get("stop_loss_price", 0))
    diff_pct: float = float(signal.get("diff_pct", 0))
    entry_status: str = str(signal.get("entry_status", ""))
    volume_surge_ratio: float = float(signal.get("volume_surge_ratio", 0))
    mrs_score: float = float(signal.get("mrs_score", 0))
    sma_30w: float = float(signal.get("sma_30w", 0))
    sma_30w_slope: float = float(signal.get("sma_30w_slope", 0))

    # Build status badge based on entry_status enum value
    status_badge: str = _build_status_badge(entry_status, diff_pct)

    # Build chart deep-link (anchor text is always the ticker symbol)
    chart_url: str = f"{base_url}/stock/{ticker}"

    card: str = (
        f"🚀 <b>{ticker}</b> — {name}\n"
        f"📊 <i>{sector}</i>\n"
        f"Status: {status_badge}\n"
        f"• <b>Entry Pivot:</b> ${entry_price:.2f}\n"
        f"• <b>Current Price:</b> ${current_price:.2f}\n"
        f"• <b>Max Buy (+5%):</b> ${max_buy_price:.2f}\n"
        f"• <b>Stop Loss:</b> ${stop_loss_price:.2f}\n"
        f"• <b>Volume Surge:</b> <b>{volume_surge_ratio:.1f}x</b> (10w avg)\n"
        f"• <b>Mansfield RS:</b> <b>{mrs_score:+.1f}</b> vs SPY\n"
        f"• <b>30w SMA:</b> ${sma_30w:.2f} (Slope: {sma_30w_slope:+.1f}%)\n"
        f'🔗 <a href="{chart_url}">View Interactive Chart</a>\n'
        f"{_CARD_SEPARATOR}"
    )
    return card


def _build_status_badge(entry_status: str, diff_pct: float) -> str:
    """
    Build the coloured status badge line from the entry_status enum string.

    Args:
        entry_status: Screener-defined status string (e.g. "IN_BUY_ZONE").
        diff_pct:     Percentage difference between current price and entry pivot.
                      Positive = above pivot, negative = below.

    Returns:
        Formatted HTML badge string including emoji, bold text, and suffix hint.
    """
    pct_str: str = f"{diff_pct:+.1f}%"

    badges: Dict[str, str] = {
        "IN_BUY_ZONE": f"🟢 <b>IN BUY ZONE ({pct_str})</b>",
        "EXTENDED": f"🟡 <b>EXTENDED ({pct_str})</b> [Wait for pullback]",
        "BELOW_ENTRY": f"⚪ <b>BELOW ENTRY ({pct_str})</b> [Retesting pivot]",
        "STOPPED_OUT": f"🔴 <b>STOPPED OUT ({pct_str})</b> [Risk trigger]",
    }

    return badges.get(entry_status, f"❓ <b>{escape_html(entry_status)} ({pct_str})</b>")


# ---------------------------------------------------------------------------
# F21 – Header formatter
# ---------------------------------------------------------------------------


def format_alert_header(scan_date: str, universe_count: int, signal_count: int) -> str:
    """
    Render the weekly alert header block sent at the top of the first chunk.

    Args:
        scan_date:      ISO-formatted date string of the screening run (YYYY-MM-DD).
        universe_count: Total number of stocks in the screening universe.
        signal_count:   Number of Stage 2 breakout candidates found this run.

    Returns:
        Formatted Telegram HTML header string (does NOT end with a newline so
        callers can append body content seamlessly after a ``\\n``).
    """
    header: str = (
        f"🛡️ <b>StockSentinel Weekly Stage 2 Alert</b>\n"
        f"{_HEADER_SEPARATOR}\n"
        f"📅 <b>Scan Date:</b> {escape_html(scan_date)}\n"
        f"🎯 <b>Universe:</b> Russell 3000 + S&amp;P 1500 ({universe_count:,} stocks)\n"
        f"🚀 <b>New Breakouts:</b> {signal_count} stocks\n"
        f"{_HEADER_SEPARATOR}"
    )
    return header


# ---------------------------------------------------------------------------
# F22 – Message chunker
# ---------------------------------------------------------------------------


def chunk_telegram_messages(header: str, stock_cards: List[str]) -> List[str]:
    """
    Split a header and a list of stock cards into Telegram-deliverable chunks.

    Each chunk is kept at or below ``MAX_CHUNK_SIZE`` characters.  Individual
    stock cards are treated as *atomic* units and will never be split across
    chunks.  If adding a card would exceed the limit, a new chunk is started.

    Chunk rules
    -----------
    * The first chunk always begins with ``header``.
    * Subsequent chunks begin with a continuation header.
    * If there are multiple chunks each chunk ends with a ``(Part N of M)`` footer.
    * If ``stock_cards`` is empty, returns a single message with the header and
      a "no candidates" notice.

    Args:
        header:      Pre-formatted alert header string (HTML).
        stock_cards: List of pre-formatted stock card strings (HTML), one per signal.

    Returns:
        List of complete Telegram message strings ready for dispatch.
    """
    if not stock_cards:
        return [header + "\nNo Stage 2 breakout candidates found this week."]

    continuation_header: str = (
        f"🛡️ <b>StockSentinel Alerts (Continued)</b>\n{_HEADER_SEPARATOR}\n"
    )

    # ── Pass 1: bin cards into raw chunks (without part footers) ──────────
    chunks: List[str] = []
    current_parts: List[str] = [header]
    current_len: int = len(header)

    for card in stock_cards:
        # Each card is separated from the previous content by a newline
        separator: str = "\n"
        candidate_addition: str = separator + card
        candidate_len: int = len(candidate_addition)

        if current_len + candidate_len > MAX_CHUNK_SIZE:
            # Flush current chunk and start a new one
            chunks.append("\n".join(p for p in current_parts))
            current_parts = [continuation_header, card]
            current_len = len(continuation_header) + len(card) + 1  # +1 for join \n
        else:
            current_parts.append(card)
            current_len += candidate_len

    # Flush the last in-progress chunk
    if current_parts:
        chunks.append("\n".join(p for p in current_parts))

    # ── Pass 2: append "(Part N of M)" footers when there are multiple chunks ──
    total: int = len(chunks)
    if total > 1:
        chunks = [f"{chunk}\n<i>(Part {idx + 1} of {total})</i>" for idx, chunk in enumerate(chunks)]

    logger.debug(
        "chunk_telegram_messages: %d card(s) → %d chunk(s) "
        "(max chunk size: %d chars)",
        len(stock_cards),
        total,
        MAX_CHUNK_SIZE,
    )
    return chunks


# ---------------------------------------------------------------------------
# F23 – Telegram dispatcher
# ---------------------------------------------------------------------------


def send_telegram_message(
    message: str,
    bot_token: str,
    chat_id: str,
    retries: int = 3,
) -> bool:
    """
    Dispatch a single HTML-formatted message to a Telegram chat via Bot API.

    Retry strategy
    --------------
    * Network / connection errors   → exponential back-off: 1 s, 2 s, 4 s …
    * HTTP 429 Too Many Requests    → sleep ``retry_after + 1`` seconds (from
                                      Telegram response JSON), then retry.
    * HTTP 400 Bad Request          → strip all HTML tags and retry **once** as
                                      plain text (guards against malformed HTML
                                      caused by unexpected characters in ticker
                                      names or company names).
    * Other HTTP errors             → logged and counted as a failed attempt.

    Args:
        message:   Telegram HTML message string (parse_mode="HTML").
        bot_token: Telegram Bot API token string (without "bot" prefix).
        chat_id:   Telegram chat / channel ID to deliver the message to.
        retries:   Maximum number of send attempts before giving up (default 3).

    Returns:
        ``True`` if the message was accepted by Telegram, ``False`` otherwise.
    """
    api_url: str = _TELEGRAM_API_URL.format(token=bot_token)
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    attempt: int = 0
    html_stripped: bool = False  # track whether we already fell back to plain text

    while attempt < retries:
        backoff_s: float = 2 ** attempt  # 1 s, 2 s, 4 s …

        try:
            logger.debug(
                "Telegram dispatch attempt %d/%d (chat_id=%s, len=%d)",
                attempt + 1,
                retries,
                chat_id,
                len(payload["text"]),
            )
            response = requests.post(api_url, json=payload, timeout=15)

        except requests.exceptions.RequestException as exc:
            logger.warning(
                "Telegram network error on attempt %d/%d: %s – retrying in %.0fs",
                attempt + 1,
                retries,
                exc,
                backoff_s,
            )
            time.sleep(backoff_s)
            attempt += 1
            continue

        # ── HTTP-level handling ────────────────────────────────────────────
        if response.status_code == 200:
            logger.info(
                "Telegram message delivered successfully (chat_id=%s, attempt=%d)",
                chat_id,
                attempt + 1,
            )
            return True

        if response.status_code == 429:
            # Telegram rate-limit: honour the retry_after field if present
            try:
                retry_after: int = int(
                    response.json().get("parameters", {}).get("retry_after", 30)
                )
            except (ValueError, AttributeError):
                retry_after = 30

            sleep_s: float = retry_after + 1
            logger.warning(
                "Telegram HTTP 429 – rate limited. Sleeping %.0f s before retry.",
                sleep_s,
            )
            time.sleep(sleep_s)
            attempt += 1
            continue

        if response.status_code == 400 and not html_stripped:
            # Bad Request often means malformed HTML. Strip tags and retry once.
            logger.warning(
                "Telegram HTTP 400 – likely malformed HTML. Stripping tags and "
                "retrying as plain text. Response: %s",
                response.text[:200],
            )
            plain_text: str = _strip_html_tags(payload["text"])
            payload = {
                "chat_id": chat_id,
                "text": plain_text,
                # No parse_mode → plain text
                "disable_web_page_preview": True,
            }
            html_stripped = True
            # Do NOT increment attempt – this retry does not count as a failure
            continue

        # Any other HTTP error
        logger.error(
            "Telegram HTTP %d on attempt %d/%d. Body: %s",
            response.status_code,
            attempt + 1,
            retries,
            response.text[:300],
        )
        time.sleep(backoff_s)
        attempt += 1

    logger.error(
        "Failed to deliver Telegram message after %d attempt(s) to chat_id=%s.",
        retries,
        chat_id,
    )
    return False


def _strip_html_tags(text: str) -> str:
    """
    Remove all HTML tags from *text* using a simple regex substitution.

    Also converts common HTML entities (``&amp;``, ``&lt;``, ``&gt;``) back
    to their plain-text equivalents so the fallback message is human-readable.

    Args:
        text: String potentially containing HTML markup.

    Returns:
        Plain-text string with all tags removed and entities decoded.
    """
    # Remove tags
    plain: str = re.sub(r"<[^>]+>", "", text)
    # Decode basic entities
    plain = plain.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return plain


# ---------------------------------------------------------------------------
# Enrichment helper – F21 support
# ---------------------------------------------------------------------------


def enrich_signals_from_db(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Populate missing ``name`` and ``sector`` fields on signal dicts by querying
    the ``stocks`` master table.

    Uses a **single** batch query with ``= ANY(%s)`` to avoid N+1 problems.
    Only signals that are missing at least one of ``name`` / ``sector`` are
    included in the query.

    Args:
        signals: List of screener signal dictionaries.  Each dict must have a
                 ``ticker`` key.  Other keys are optional and will be added if
                 absent.

    Returns:
        The same list of dicts, mutated in-place with ``name`` and ``sector``
        populated from the database where they were previously absent.
        Unknown tickers (not found in ``stocks`` table) retain ``None`` values.
    """
    # Identify which tickers need enrichment
    tickers_needing_enrichment: List[str] = [
        s["ticker"]
        for s in signals
        if not s.get("name") or not s.get("sector")
    ]

    if not tickers_needing_enrichment:
        logger.debug("enrich_signals_from_db: all signals already have name/sector.")
        return signals

    logger.debug(
        "enrich_signals_from_db: fetching name/sector for %d ticker(s) from DB.",
        len(tickers_needing_enrichment),
    )

    # Deduplicate the ticker list for the query
    unique_tickers: List[str] = list(set(tickers_needing_enrichment))

    try:
        with db_cursor(commit=False) as cur:
            cur.execute(
                "SELECT ticker, name, sector FROM stocks WHERE ticker = ANY(%s)",
                (unique_tickers,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error(
            "enrich_signals_from_db: DB query failed – signals will not be enriched. "
            "Error: %s",
            exc,
        )
        return signals

    # Build lookup map: ticker → {name, sector}
    db_data: Dict[str, Dict[str, Optional[str]]] = {
        row[0]: {"name": row[1], "sector": row[2]} for row in rows
    }

    # Apply enrichment in-place
    for signal in signals:
        ticker: str = signal["ticker"]
        if ticker in db_data:
            if not signal.get("name"):
                signal["name"] = db_data[ticker]["name"]
            if not signal.get("sector"):
                signal["sector"] = db_data[ticker]["sector"]

    logger.debug(
        "enrich_signals_from_db: enriched signals for %d ticker(s).", len(db_data)
    )
    return signals


# ---------------------------------------------------------------------------
# F21 + F22 + F23 – Main alert orchestrator
# ---------------------------------------------------------------------------


def send_weekly_alert(
    signals: List[Dict[str, Any]],
    scan_date: str,
    universe_count: int,
) -> bool:
    """
    Orchestrate the full weekly alert pipeline: enrich → format → chunk → dispatch.

    Pipeline steps
    --------------
    1. Read ``TELEGRAM_ENABLED``, ``TELEGRAM_BOT_TOKEN``, and
       ``TELEGRAM_CHAT_ID`` from :mod:`screener.src.config`.
    2. If alerting is disabled or credentials are missing, log a warning and
       return ``True`` (graceful no-op – does not count as a failure).
    3. Enrich each signal dict with company ``name`` and ``sector`` from the
       ``stocks`` table if those fields are absent.
    4. Render the weekly header (``format_alert_header``).
    5. Render a stock card per signal (``format_stock_card``).
    6. Chunk header + cards into Telegram-safe message strings
       (``chunk_telegram_messages``).
    7. Dispatch all chunks via ``send_telegram_message`` with a
       ``_INTER_CHUNK_DELAY_S`` pause between each chunk.

    Args:
        signals:         List of screener signal dicts, one per breakout candidate.
                         Each dict must contain at minimum: ``ticker``,
                         ``entry_price``, ``current_price``, ``max_buy_price``,
                         ``stop_loss_price``, ``diff_pct``, ``entry_status``,
                         ``volume_surge_ratio``, ``mrs_score``, ``sma_30w``,
                         ``sma_30w_slope``.
        scan_date:       ISO date string (YYYY-MM-DD) of the screening run.
        universe_count:  Total stocks in the screening universe.

    Returns:
        ``True`` if all chunks were dispatched successfully (or alerting was
        intentionally disabled); ``False`` if any chunk failed to send.
    """
    # ── Guard: check configuration ─────────────────────────────────────────
    if not config.TELEGRAM_ENABLED:
        logger.warning(
            "send_weekly_alert: TELEGRAM_ENABLED is False – skipping alert dispatch."
        )
        return True

    bot_token: str = config.TELEGRAM_BOT_TOKEN
    chat_id: str = config.TELEGRAM_CHAT_ID
    base_url: str = config.WEB_APP_BASE_URL

    if not bot_token or not chat_id:
        logger.warning(
            "send_weekly_alert: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set – "
            "skipping alert dispatch."
        )
        return True

    logger.info(
        "send_weekly_alert: preparing alert for %d signal(s) on %s.",
        len(signals),
        scan_date,
    )

    # ── Step 1: DB enrichment ──────────────────────────────────────────────
    enriched_signals: List[Dict[str, Any]] = enrich_signals_from_db(signals)

    # ── Step 2: Format header ──────────────────────────────────────────────
    header: str = format_alert_header(
        scan_date=scan_date,
        universe_count=universe_count,
        signal_count=len(enriched_signals),
    )

    # ── Step 3: Format stock cards ─────────────────────────────────────────
    stock_cards: List[str] = [
        format_stock_card(signal, base_url=base_url) for signal in enriched_signals
    ]

    # ── Step 4: Chunk into deliverable messages ────────────────────────────
    chunks: List[str] = chunk_telegram_messages(header, stock_cards)
    total_chunks: int = len(chunks)

    logger.info(
        "send_weekly_alert: dispatching %d message chunk(s) to chat_id=%s.",
        total_chunks,
        chat_id,
    )

    # ── Step 5: Dispatch ───────────────────────────────────────────────────
    all_ok: bool = True
    for idx, chunk in enumerate(chunks, start=1):
        ok: bool = send_telegram_message(
            message=chunk,
            bot_token=bot_token,
            chat_id=chat_id,
        )
        if not ok:
            logger.error(
                "send_weekly_alert: chunk %d/%d FAILED for chat_id=%s.",
                idx,
                total_chunks,
                chat_id,
            )
            all_ok = False
        else:
            logger.info(
                "send_weekly_alert: chunk %d/%d delivered successfully.",
                idx,
                total_chunks,
            )

        # Rate-limit courtesy delay between consecutive chunks
        if idx < total_chunks:
            time.sleep(_INTER_CHUNK_DELAY_S)

    return all_ok
