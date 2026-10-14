"""
screener/src/universe.py - Universe definition, ticker sanitization, filtering, and DB synchronization.
"""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from screener.src import config, db

logger = logging.getLogger(__name__)

# Regular expressions for equity validation and non-equity filtering
RE_COMMON_CLASS = re.compile(r"^[A-Z]{1,5}\.[A-Z]$")
RE_WARRANT = re.compile(r"([.\-/](?:WS|WT|W)(?:\.|$)|-WT|\+|=|^[A-Z]{4}W$)", re.IGNORECASE)
RE_PREFERRED = re.compile(r"([.\-/](?:PR|PF|P[A-Z]?)(?:\.|$)|/PR|-P|\^|^[A-Z]{4}P$)", re.IGNORECASE)
RE_UNIT = re.compile(r"([.\-/](?:UN|U)(?:\.|$)|=U|^[A-Z]{4}U$)", re.IGNORECASE)
RE_RIGHT = re.compile(r"([.\-/](?:RT|R)(?:\.|$)|-RT|\+R|^[A-Z]{4}R$)", re.IGNORECASE)
RE_STANDARD_TICKER = re.compile(r"^[A-Z]{1,5}$")


def sanitize_ticker(raw_ticker: str) -> str:
    """
    Trims unicode whitespace, tabs, and newlines, converts to uppercase,
    and normalizes dual-class share separators (- and /) to dot notation (.):
    e.g. 'BRK-B' -> 'BRK.B', 'JW/A' -> 'JW.A', '  aapl \n' -> 'AAPL'.
    """
    if not raw_ticker or not isinstance(raw_ticker, str):
        return ""
    # Strip common and unicode whitespace (e.g. \u00a0)
    cleaned = raw_ticker.strip().strip("\u00a0\t\r\n ")
    cleaned = cleaned.upper()
    # Normalize dual-class separators: replace hyphen or slash with dot
    cleaned = cleaned.replace("-", ".").replace("/", ".")
    return cleaned


def to_yfinance_symbol(ticker: str) -> str:
    """
    Converts internal canonical ticker (e.g. 'BRK.B') to Yahoo Finance symbol ('BRK-B').
    """
    if not ticker:
        return ""
    cleaned = sanitize_ticker(ticker)
    return cleaned.replace(".", "-")


def from_yfinance_symbol(yf_symbol: str) -> str:
    """
    Converts Yahoo Finance symbol ('BRK-B') back to internal canonical ticker ('BRK.B').
    """
    if not yf_symbol:
        return ""
    return sanitize_ticker(yf_symbol)


def is_common_stock(ticker: str, name: str = "") -> bool:
    """
    Validates whether a ticker and security name represent a standard US common equity
    or the mandatory SPY benchmark ETF. Excludes warrants, preferreds, units, rights, and test tickers.
    """
    sym = sanitize_ticker(ticker)
    if not sym:
        return False

    # Mandatory broad-market benchmark exception
    if sym == "SPY":
        return True

    # Check security name for non-common equity indicators
    if name:
        name_lower = f" {name.lower()} "
        for indicator in [
            "warrant", "wrnt", "preferred", "pfd", " unit", " units",
            " right", " rights", "etf", "etn", "fund", "trust"
        ]:
            # Allow common companies that happen to contain "trust" or "fund" if not an ETF/Unit
            if indicator in ["fund", "trust"] and not any(k in name_lower for k in ["etf", "index", "trust units"]):
                continue
            if indicator in name_lower:
                return False

    # Exclude non-common instruments by ticker pattern first
    if RE_WARRANT.search(sym):
        return False
    if RE_PREFERRED.search(sym):
        return False
    if RE_UNIT.search(sym):
        return False
    if RE_RIGHT.search(sym):
        return False

    # Match valid dual-class common equities: e.g. BRK.B, BF.B, CWEN.A, JW.A
    if RE_COMMON_CLASS.match(sym):
        return True

    # Exclude exchange test and non-tradeable symbols
    if sym in {"ZVZZT", "ZWZZT", "TEST", "NPORT"}:
        return False

    # Standard US common stock ticker (1-5 alphabetical chars, e.g. AAPL, NVDA, CRWD)
    return bool(RE_STANDARD_TICKER.match(sym))


def deduplicate_universe(raw_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicates a list of stock entries by uppercase canonical ticker.
    Merges index membership flags (in_russell3000, in_sp1500) if a duplicate is found.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    for item in raw_list:
        ticker = sanitize_ticker(item.get("ticker", ""))
        if not ticker:
            continue
        if ticker not in seen:
            entry = dict(item)
            entry["ticker"] = ticker
            entry["in_russell3000"] = bool(entry.get("in_russell3000", False))
            entry["in_sp1500"] = bool(entry.get("in_sp1500", False))
            seen[ticker] = entry
        else:
            # Merge membership flags
            seen[ticker]["in_russell3000"] = seen[ticker]["in_russell3000"] or bool(item.get("in_russell3000", False))
            seen[ticker]["in_sp1500"] = seen[ticker]["in_sp1500"] or bool(item.get("in_sp1500", False))
            # Prefer richer metadata if present
            if not seen[ticker].get("name") and item.get("name"):
                seen[ticker]["name"] = item["name"]

    return sorted(list(seen.values()), key=lambda x: x["ticker"])


def load_universe_seed(json_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Loads, sanitizes, filters, and deduplicates the universe constituents from the JSON seed file.
    Always guarantees inclusion of the SPY benchmark ETF.
    """
    path = json_path or config.UNIVERSE_SEED_FILE
    if not path.exists():
        logger.warning(f"Universe seed file {path} not found. Returning minimal benchmark universe.")
        return [{
            "ticker": "SPY",
            "name": "SPDR S&P 500 ETF Trust",
            "exchange": "ARCA",
            "sector": "Benchmark",
            "industry": "Index ETF",
            "market_cap": 500_000_000_000,
            "is_active": True,
            "in_russell3000": True,
            "in_sp1500": True,
        }]

    with open(path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)

    cleaned_items: List[Dict[str, Any]] = []
    for item in raw_items:
        ticker = sanitize_ticker(item.get("ticker", ""))
        name = item.get("name", "").strip()
        if not ticker or not name:
            continue
        if not is_common_stock(ticker, name):
            continue

        cleaned_items.append({
            "ticker": ticker,
            "name": name,
            "exchange": item.get("exchange", "NASDAQ"),
            "sector": item.get("sector", "Unknown"),
            "industry": item.get("industry", "Unknown"),
            "market_cap": item.get("market_cap"),
            "is_active": item.get("is_active", True),
            "in_russell3000": bool(item.get("in_russell3000", False)),
            "in_sp1500": bool(item.get("in_sp1500", False)),
        })

    deduped = deduplicate_universe(cleaned_items)

    # Ensure SPY benchmark is unconditionally present
    spy_entry = next((item for item in deduped if item["ticker"] == "SPY"), None)
    if not spy_entry:
        deduped.insert(0, {
            "ticker": "SPY",
            "name": "SPDR S&P 500 ETF Trust",
            "exchange": "ARCA",
            "sector": "Benchmark",
            "industry": "Index ETF",
            "market_cap": 500_000_000_000,
            "is_active": True,
            "in_russell3000": True,
            "in_sp1500": True,
        })

    return deduped


def sync_universe_to_db(universe: Optional[List[Dict[str, Any]]] = None) -> int:
    """
    Synchronizes the universe seed dataset into the PostgreSQL 'stocks' table.
    """
    stocks = universe if universe is not None else load_universe_seed()
    if not stocks:
        return 0
    return db.upsert_stocks(stocks)


def get_active_universe() -> List[str]:
    """
    Retrieves the list of active stock tickers from PostgreSQL or falls back to the seed dataset.
    """
    try:
        with db.db_cursor(commit=False) as cur:
            cur.execute("SELECT ticker FROM stocks WHERE is_active = TRUE ORDER BY ticker ASC;")
            rows = cur.fetchall()
            # If database has a populated stock universe (more than just SPY benchmark)
            if rows and any(r[0] != "SPY" for r in rows):
                return [r[0] for r in rows]
    except Exception as e:
        logger.warning(f"Could not load active universe from database ({e}). Falling back to seed file.")

    seed = load_universe_seed()
    return [s["ticker"] for s in seed if s.get("is_active", True)]
