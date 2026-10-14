"""
screener/src/main.py - CLI entrypoint for StockSentinel screener universe ingestion and daily data sync.
"""
import sys
from pathlib import Path

# Ensure project root is in sys.path so screener.src is always importable
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import argparse
import logging
from typing import List, Optional
from screener.src import config, db, screener, sync, universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("stocksentinel.screener")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="StockSentinel Universe Ingestion & Daily Bar Synchronizer."
    )
    parser.add_argument(
        "--mode",
        choices=["ingest", "sync", "all", "seed", "screen", "scan"],
        default="sync",
        help="Execution mode: 'seed' (universe only), 'sync'/'ingest' (download bars), 'screen'/'scan' (run Stage 2 screener), 'all' (seed + sync + screen).",
    )
    parser.add_argument(
        "--cold-start",
        action="store_true",
        help="Run cold start full historical ingestion (730-day lookback window).",
    )
    parser.add_argument(
        "--delta",
        action="store_true",
        help="Run incremental delta synchronization (7-day lookback window).",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        metavar="N",
        help="Limit execution to a sample of first N tickers.",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated list of specific tickers (e.g. 'AAPL,MSFT,SPY').",
    )
    parser.add_argument(
        "--scan-date",
        type=str,
        default=None,
        help="Target scan date (ISO format YYYY-MM-DD, e.g. '2026-10-09').",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force download and overwrite existing cache even if up-to-date.",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Only populate the PostgreSQL stocks table from universe seed file.",
    )

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    logger.info("=" * 60)
    logger.info("StockSentinel Universe & Ingestion Engine")
    logger.info("=" * 60)

    # Mode 1: Seed only
    if args.seed_only or args.mode == "seed":
        logger.info("Seeding universe to PostgreSQL stocks table...")
        count = universe.sync_universe_to_db()
        logger.info(f"Successfully seeded {count} stocks into database.")
        return 0

    # Determine tickers
    selected_tickers = None
    if args.tickers:
        selected_tickers = [universe.sanitize_ticker(t) for t in args.tickers.split(",") if t.strip()]
    elif args.sample:
        active = universe.get_active_universe()
        selected_tickers = active[: args.sample]
        if "SPY" not in selected_tickers:
            selected_tickers.insert(0, "SPY")

    # Mode 2: Screen / Scan only
    if args.mode in ["screen", "scan"]:
        logger.info(
            f"Starting Stage 2 Breakout Screener (scan_date={args.scan_date or 'LATEST'}, "
            f"tickers={len(selected_tickers) if selected_tickers else 'ALL'})..."
        )
        try:
            results = screener.run_screener(
                scan_date=args.scan_date,
                tickers=selected_tickers,
            )
            logger.info("Screening completed successfully.")
            logger.info(
                f"Summary: {results.get('tickers_processed', 0)} processed, "
                f"{results.get('signals_found', 0)} Stage 2 breakout signals discovered."
            )
            return 0
        except Exception as e:
            if "SPY benchmark data is empty" in str(e):
                logger.warning("SPY benchmark data missing. Automatically synchronizing SPY and initial universe data first...")
                try:
                    sync.run_sync(cold_start=False, tickers=selected_tickers)
                    logger.info("Synchronization complete. Resuming screener...")
                    results = screener.run_screener(
                        scan_date=args.scan_date,
                        tickers=selected_tickers,
                    )
                    logger.info("Screening completed successfully after auto-sync.")
                    return 0
                except Exception as sync_err:
                    logger.error(f"Auto-sync and screening failed: {sync_err}", exc_info=True)
                    return 1
            logger.error(f"Screening failed with error: {e}", exc_info=True)
            return 1

    # Determine sync mode
    is_cold_start = args.cold_start
    if args.delta:
        is_cold_start = False

    logger.info(
        f"Starting data synchronization (mode={'cold_start' if is_cold_start else 'delta'}, "
        f"tickers={len(selected_tickers) if selected_tickers else 'ALL'}, force={args.force})..."
    )

    try:
        metrics = sync.run_sync(
            cold_start=is_cold_start,
            tickers=selected_tickers,
            force=args.force,
        )
        logger.info("Synchronization completed successfully.")
        logger.info(f"Summary Metrics: {metrics}")

        # If mode is 'all', run screener after sync
        if args.mode == "all":
            logger.info("Running Stage 2 Breakout Screener following sync...")
            screener_results = screener.run_screener(
                scan_date=args.scan_date,
                tickers=selected_tickers,
            )
            logger.info(
                f"All-mode screening finished: {screener_results.get('signals_found', 0)} signals found."
            )

        return 0
    except Exception as e:
        logger.error(f"Execution failed with error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
