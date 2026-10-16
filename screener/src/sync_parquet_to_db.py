"""
screener/src/sync_parquet_to_db.py - Utility to sync local Parquet historical bars into PostgreSQL stock_daily_bars.
"""
import logging
from pathlib import Path
from screener.src import config, db, parquet_cache, universe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def sync_all_parquet():
    parquet_files = list(config.PARQUET_DIR.glob("*.parquet"))
    if not parquet_files:
        logger.warning(f"No parquet files found in {config.PARQUET_DIR}")
        return

    logger.info(f"Found {len(parquet_files)} parquet files to sync to database.")

    # 1. Ensure all tickers exist in the stocks table (satisfies FK constraint)
    tickers = [f.stem for f in parquet_files]
    seed_map = {item["ticker"]: item for item in universe.load_universe_seed()}
    stock_entries = [seed_map.get(t, {"ticker": t, "name": t, "exchange": "NASDAQ"}) for t in tickers]
    db.upsert_stocks(stock_entries)
    logger.info(f"Ensured {len(stock_entries)} tickers exist in stocks master table.")

    # 2. Upsert daily bars
    total_bars = 0
    for idx, f in enumerate(parquet_files):
        ticker = f.stem
        try:
            bars = parquet_cache.load_from_parquet(ticker)
            if bars:
                upserted = db.upsert_daily_bars(bars)
                total_bars += upserted
        except Exception as e:
            logger.error(f"Failed to upsert bars for {ticker}: {e}")

        if (idx + 1) % 25 == 0 or (idx + 1) == len(parquet_files):
            logger.info(f"Progress: {idx + 1}/{len(parquet_files)} tickers ({total_bars} bars upserted)")

    logger.info(f"Completed! Upserted {total_bars} bars across {len(parquet_files)} tickers.")

if __name__ == "__main__":
    sync_all_parquet()
