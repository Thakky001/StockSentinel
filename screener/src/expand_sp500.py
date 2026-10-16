"""
screener/src/expand_sp500.py - Expands the active universe to the full S&P 500 (~503 stocks),
downloading 2-year historical daily bars in chunks of 100, saving to Parquet,
and upserting to Neon PostgreSQL.
"""
import io
import json
import logging
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
from screener.src import config, db, downloader, parquet_cache, universe
from screener.src.universe import sanitize_ticker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("expand_sp500")

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_sp500_constituents() -> List[Dict[str, Any]]:
    """Fetches the official list of S&P 500 constituents from Wikipedia."""
    logger.info("Fetching S&P 500 constituent list from Wikipedia...")
    req = urllib.request.Request(
        SP500_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StockSentinel/1.0"}
    )
    html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
    df = pd.read_html(io.StringIO(html))[0]

    stocks: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        raw_sym = str(row.get("Symbol", "")).strip()
        ticker = sanitize_ticker(raw_sym)
        if not ticker:
            continue
        name = str(row.get("Security", ticker)).strip()
        sector = str(row.get("GICS Sector", "Unknown")).strip()
        industry = str(row.get("GICS Sub-Industry", "Unknown")).strip()

        stocks.append({
            "ticker": ticker,
            "name": name,
            "exchange": "NYSE" if ticker in {"BRK.B", "JPM", "V", "XOM", "JNJ", "PG", "HD"} else "NASDAQ",
            "sector": sector,
            "industry": industry,
            "market_cap": None,
            "is_active": True,
            "in_russell3000": True,
            "in_sp1500": True,
        })

    logger.info(f"Retrieved {len(stocks)} S&P 500 constituents.")
    return stocks


def update_universe_seed(new_stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merges new stocks into russell3000_sp1500.json seed file."""
    seed_file = config.UNIVERSE_SEED_FILE
    existing: List[Dict[str, Any]] = []
    if seed_file.exists():
        with open(seed_file, "r", encoding="utf-8") as f:
            existing = json.load(f)

    stock_map = {s["ticker"]: s for s in existing}
    for s in new_stocks:
        if s["ticker"] in stock_map:
            stock_map[s["ticker"]]["in_sp1500"] = True
            if s.get("sector") and stock_map[s["ticker"]].get("sector") == "Unknown":
                stock_map[s["ticker"]]["sector"] = s["sector"]
            if s.get("industry") and stock_map[s["ticker"]].get("industry") == "Unknown":
                stock_map[s["ticker"]]["industry"] = s["industry"]
        else:
            stock_map[s["ticker"]] = s

    # Ensure SPY benchmark is present
    if "SPY" not in stock_map:
        stock_map["SPY"] = {
            "ticker": "SPY",
            "name": "SPDR S&P 500 ETF Trust",
            "exchange": "ARCA",
            "sector": "Benchmark",
            "industry": "Index ETF",
            "is_active": True,
            "in_russell3000": True,
            "in_sp1500": True,
        }

    merged_list = sorted(list(stock_map.values()), key=lambda x: x["ticker"])
    with open(seed_file, "w", encoding="utf-8") as f:
        json.dump(merged_list, f, indent=2)

    logger.info(f"Updated {seed_file} with {len(merged_list)} stocks.")
    return merged_list


def expand_and_sync_sp500(batch_size: int = 100):
    """
    Expands S&P 500 universe, downloads missing tickers in batches of 100,
    and upserts into Neon DB.
    """
    sp500_stocks = fetch_sp500_constituents()
    all_stocks = update_universe_seed(sp500_stocks)

    # 1. Upsert master stock list to PostgreSQL
    logger.info("Synchronizing master stocks list into PostgreSQL...")
    db.upsert_stocks(all_stocks)
    logger.info(f"Master stocks table now contains {len(all_stocks)} records.")

    # 2. Identify missing tickers that need download
    sp500_tickers = [s["ticker"] for s in sp500_stocks if s["ticker"] != "SPY"]
    missing_tickers = [
        t for t in sp500_tickers
        if not (config.PARQUET_DIR / f"{t}.parquet").exists() or (config.PARQUET_DIR / f"{t}.parquet").stat().st_size == 0
    ]

    logger.info(
        f"S&P 500 Total: {len(sp500_tickers)} | "
        f"Already Cached: {len(sp500_tickers) - len(missing_tickers)} | "
        f"To Download: {len(missing_tickers)}"
    )

    if not missing_tickers:
        logger.info("All S&P 500 tickers are already downloaded and cached!")
        return

    # 3. Chunk into batches of batch_size (default 100)
    batches = [missing_tickers[i:i + batch_size] for i in range(0, len(missing_tickers), batch_size)]
    total_downloaded_bars = 0
    total_upserted_bars = 0

    for idx, chunk in enumerate(batches, start=1):
        logger.info(f"=== Processing Batch {idx}/{len(batches)} ({len(chunk)} tickers) ===")
        batch_res = downloader.download_batch_with_retry(chunk, period="2y")

        bars_to_upsert: List[Dict[str, Any]] = []
        for ticker, bars in batch_res.items():
            if bars:
                parquet_cache.save_to_parquet(ticker, bars)
                bars_to_upsert.extend(bars)
                total_downloaded_bars += len(bars)
            else:
                logger.warning(f"No bars returned for {ticker} (may be recently changed or delisted)")

        if bars_to_upsert:
            logger.info(f"Upserting {len(bars_to_upsert)} bars from Batch {idx} into PostgreSQL...")
            upserted = db.upsert_daily_bars(bars_to_upsert)
            total_upserted_bars += upserted
            logger.info(f"Batch {idx} upserted successfully: {upserted} bars.")

        if idx < len(batches):
            logger.info("Waiting 3 seconds before next batch...")
            time.sleep(3)

    logger.info(
        f"=== Phase 2 Expansion Complete! ===\n"
        f"Total downloaded bars: {total_downloaded_bars}\n"
        f"Total upserted bars to DB: {total_upserted_bars}"
    )


if __name__ == "__main__":
    expand_and_sync_sp500(batch_size=100)
