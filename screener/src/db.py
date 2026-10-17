"""
screener/src/db.py - PostgreSQL connection & high-throughput batch upsert operations.
"""
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2.extras import execute_values
from screener.src import config

logger = logging.getLogger(__name__)


def get_db_connection():
    """Establishes and returns a direct PostgreSQL database connection."""
    db_url = config.DATABASE_URL
    if db_url and "localhost" not in db_url and "127.0.0.1" not in db_url:
        if "sslmode" not in db_url and (".render.com" in db_url or "dpg-" in db_url or "neon.tech" in db_url or "supabase.co" in db_url):
            delimiter = "&" if "?" in db_url else "?"
            db_url = f"{db_url}{delimiter}sslmode=require"
        return psycopg2.connect(db_url)
    return psycopg2.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.POSTGRES_DB,
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD,
    )


@contextmanager
def db_cursor(commit: bool = True):
    """
    Context manager managing a database connection and cursor.
    Commits on successful block completion, rolls back on exception, and ensures connection close.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database transaction rolled back due to error: {e}")
        raise
    finally:
        conn.close()


def upsert_stocks(stocks_list: List[Dict[str, Any]], cur=None) -> int:
    """
    Upsert stock master records into the 'stocks' table using ON CONFLICT (ticker) DO UPDATE.
    
    Args:
        stocks_list: List of dicts representing stocks with ticker, name, exchange, etc.
        cur: Optional existing database cursor. If None, a new transaction is created.
        
    Returns:
        Number of records upserted.
    """
    if not stocks_list:
        return 0

    sql = """
    INSERT INTO stocks (ticker, name, exchange, sector, industry, market_cap, is_active, in_russell3000, in_sp1500)
    VALUES %s
    ON CONFLICT (ticker) DO UPDATE SET
        name = EXCLUDED.name,
        exchange = EXCLUDED.exchange,
        sector = EXCLUDED.sector,
        industry = EXCLUDED.industry,
        market_cap = EXCLUDED.market_cap,
        is_active = EXCLUDED.is_active,
        in_russell3000 = EXCLUDED.in_russell3000,
        in_sp1500 = EXCLUDED.in_sp1500,
        updated_at = CURRENT_TIMESTAMP;
    """
    values = [
        (
            s["ticker"],
            s["name"],
            s.get("exchange", "NASDAQ"),
            s.get("sector"),
            s.get("industry"),
            s.get("market_cap"),
            s.get("is_active", True),
            bool(s.get("in_russell3000", False)),
            bool(s.get("in_sp1500", False)),
        )
        for s in stocks_list
    ]

    if cur:
        execute_values(cur, sql, values, page_size=1000)
    else:
        with db_cursor(commit=True) as cursor:
            execute_values(cursor, sql, values, page_size=1000)

    return len(values)


def ensure_stocks_exist(stocks_or_tickers: List[Any], cur=None) -> int:
    """
    Ensures that all given tickers exist in the 'stocks' table with ON CONFLICT (ticker) DO NOTHING.
    Accepts either a list of ticker strings or a list of dicts with 'ticker' (and optional 'name', 'exchange').
    """
    if not stocks_or_tickers:
        return 0

    sql = """
    INSERT INTO stocks (ticker, name, exchange, is_active)
    VALUES %s
    ON CONFLICT (ticker) DO NOTHING;
    """
    values = []
    seen = set()
    for item in stocks_or_tickers:
        if isinstance(item, dict):
            t = item.get("ticker", "")
            name = item.get("name") or t
            exchange = item.get("exchange", "UNKNOWN")
        else:
            t = str(item)
            name = t
            exchange = "UNKNOWN"
        if t and t not in seen:
            seen.add(t)
            values.append((t, name, exchange, True))

    if not values:
        return 0

    if cur:
        execute_values(cur, sql, values, page_size=1000)
    else:
        with db_cursor(commit=True) as cursor:
            execute_values(cursor, sql, values, page_size=1000)

    return len(values)


def upsert_daily_bars(bars_list: List[Dict[str, Any]], cur=None, chunk_size: int = 1000) -> int:
    """
    Batch upserts daily OHLCV bars into 'stock_daily_bars' table in chunks of chunk_size.
    Uses ON CONFLICT (ticker, trade_date) DO UPDATE to update existing bars idempotently.
    Deduplicates incoming bars by (ticker, trade_date) keeping the latest record to prevent
    PostgreSQL cardinality violation errors (error 21000).
    
    Args:
        bars_list: List of dicts containing ticker, trade_date, open, high, low, close, adj_close, volume.
        cur: Optional existing database cursor. If None, a new transaction is opened.
        chunk_size: Size of batches sent to execute_values (default: 1000).
        
    Returns:
        Number of bars upserted.
    """
    if not bars_list:
        return 0

    sql = """
    INSERT INTO stock_daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
    VALUES %s
    ON CONFLICT (ticker, trade_date) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        adj_close = EXCLUDED.adj_close,
        volume = EXCLUDED.volume;
    """

    # Deduplicate bars by (ticker, trade_date) keeping the latest record
    deduped_bars: Dict[tuple, Dict[str, Any]] = {}
    for b in bars_list:
        deduped_bars[(b["ticker"], b["trade_date"])] = b

    values = [
        (
            b["ticker"],
            b["trade_date"],
            b["open"],
            b["high"],
            b["low"],
            b["close"],
            b.get("adj_close", b["close"]),
            b["volume"],
        )
        for b in deduped_bars.values()
    ]

    if cur:
        for i in range(0, len(values), chunk_size):
            execute_values(cur, sql, values[i : i + chunk_size], page_size=chunk_size)
    else:
        with db_cursor(commit=True) as cursor:
            for i in range(0, len(values), chunk_size):
                execute_values(cursor, sql, values[i : i + chunk_size], page_size=chunk_size)

    return len(values)


def get_latest_cached_date(ticker: str, cur=None) -> Optional[str]:
    """
    Retrieves the maximum trade_date recorded for a given ticker in stock_daily_bars.
    """
    sql = "SELECT MAX(trade_date) FROM stock_daily_bars WHERE ticker = %s;"
    if cur:
        cur.execute(sql, (ticker,))
        row = cur.fetchone()
        return str(row[0]) if row and row[0] else None
    else:
        with db_cursor(commit=False) as cursor:
            cursor.execute(sql, (ticker,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else None


def prune_database_records(
    daily_bars_days: int = 730,
    signals_days: int = 365,
    scan_jobs_days: int = 90,
    cur=None,
) -> Dict[str, int]:
    """
    Automated Database Retention / Housekeeping Policy:
    Prunes expired historical records in a rolling window to keep storage capped and fast:
    - stock_daily_bars: Keeps last 730 days (2 years), required for Weinstein 30w/35w/52w indicators.
    - screener_signals: Keeps last 365 days (52 weeks), required for frontend scan date history.
    - scan_jobs: Keeps last 90 days (3 months) of audit run logs.
    """
    deleted_counts = {"daily_bars": 0, "signals": 0, "scan_jobs": 0}

    def _execute_prunes(cursor):
        cursor.execute(
            "DELETE FROM stock_daily_bars WHERE trade_date < CURRENT_DATE - (%s || ' days')::interval;",
            (daily_bars_days,),
        )
        deleted_counts["daily_bars"] = cursor.rowcount

        cursor.execute(
            "DELETE FROM screener_signals WHERE scan_date < CURRENT_DATE - (%s || ' days')::interval;",
            (signals_days,),
        )
        deleted_counts["signals"] = cursor.rowcount

        cursor.execute(
            "DELETE FROM scan_jobs WHERE created_at < CURRENT_DATE - (%s || ' days')::interval;",
            (scan_jobs_days,),
        )
        deleted_counts["scan_jobs"] = cursor.rowcount

    try:
        if cur:
            _execute_prunes(cur)
        else:
            with db_cursor(commit=True) as cursor:
                _execute_prunes(cursor)

        logger.info(
            f"Database housekeeping completed: pruned {deleted_counts['daily_bars']} daily bars (> {daily_bars_days}d), "
            f"{deleted_counts['signals']} signals (> {signals_days}d), "
            f"{deleted_counts['scan_jobs']} scan jobs (> {scan_jobs_days}d)."
        )
    except Exception as e:
        logger.warning(f"Database housekeeping notice (non-fatal): {e}")

    return deleted_counts


def load_active_breakout_signals(cur=None) -> Dict[str, Dict[str, Any]]:
    """
    Loads all active breakout signals from 'active_breakout_signals' keyed by symbol.
    """
    sql = """
    SELECT symbol, breakout_date, entry_price, max_buy_price, initial_stop_loss, active_stop_loss,
           highest_price_since_entry, current_price, peak_gain_pct, current_gain_pct, status,
           recommended_shares, earnings_warning
    FROM active_breakout_signals;
    """
    results: Dict[str, Dict[str, Any]] = {}
    try:
        def _fetch(cursor):
            cursor.execute(sql)
            rows = cursor.fetchall()
            for r in rows:
                results[r[0]] = {
                    "symbol": r[0],
                    "breakout_date": str(r[1]),
                    "entry_price": float(r[2]),
                    "max_buy_price": float(r[3]),
                    "initial_stop_loss": float(r[4]),
                    "active_stop_loss": float(r[5]),
                    "highest_price_since_entry": float(r[6]),
                    "current_price": float(r[7]),
                    "peak_gain_pct": float(r[8]),
                    "current_gain_pct": float(r[9]),
                    "status": r[10],
                    "recommended_shares": int(r[11]),
                    "earnings_warning": r[12],
                }

        if cur:
            _fetch(cur)
        else:
            with db_cursor(commit=False) as cursor:
                _fetch(cursor)
    except Exception as e:
        logger.warning(f"Could not load active_breakout_signals from database: {e}")

    return results


def upsert_active_breakout_signals(signals: List[Dict[str, Any]], cur=None) -> int:
    """
    Upserts tracked breakout lifecycle records into 'active_breakout_signals'.
    """
    if not signals:
        return 0

    sql = """
    INSERT INTO active_breakout_signals (
        symbol, breakout_date, entry_price, max_buy_price, initial_stop_loss, active_stop_loss,
        highest_price_since_entry, current_price, peak_gain_pct, current_gain_pct, status,
        recommended_shares, earnings_warning
    )
    VALUES %s
    ON CONFLICT (symbol) DO UPDATE SET
        entry_price = EXCLUDED.entry_price,
        max_buy_price = EXCLUDED.max_buy_price,
        initial_stop_loss = EXCLUDED.initial_stop_loss,
        active_stop_loss = EXCLUDED.active_stop_loss,
        highest_price_since_entry = EXCLUDED.highest_price_since_entry,
        current_price = EXCLUDED.current_price,
        peak_gain_pct = EXCLUDED.peak_gain_pct,
        current_gain_pct = EXCLUDED.current_gain_pct,
        status = EXCLUDED.status,
        recommended_shares = EXCLUDED.recommended_shares,
        earnings_warning = EXCLUDED.earnings_warning,
        updated_at = CURRENT_TIMESTAMP;
    """
    values = [
        (
            s["symbol"],
            s["breakout_date"],
            s["entry_price"],
            s["max_buy_price"],
            s["initial_stop_loss"],
            s["active_stop_loss"],
            s["highest_price_since_entry"],
            s["current_price"],
            s["peak_gain_pct"],
            s["current_gain_pct"],
            s["status"],
            s.get("recommended_shares", 0),
            s.get("earnings_warning"),
        )
        for s in signals
    ]

    try:
        if cur:
            execute_values(cur, sql, values, page_size=500)
        else:
            with db_cursor(commit=True) as cursor:
                execute_values(cursor, sql, values, page_size=500)
        return len(values)
    except Exception as e:
        logger.error(f"Failed to upsert active_breakout_signals: {e}")
        return 0


def seed_active_breakout_signals_if_empty(cur=None) -> int:
    """
    Seeds active_breakout_signals with previous qualified records from screener_signals
    if active_breakout_signals is currently empty.
    """
    check_sql = "SELECT COUNT(*) FROM active_breakout_signals;"
    seed_sql = """
    INSERT INTO active_breakout_signals (
        symbol, breakout_date, entry_price, max_buy_price, initial_stop_loss, active_stop_loss,
        highest_price_since_entry, current_price, peak_gain_pct, current_gain_pct, status,
        recommended_shares, updated_at
    )
    SELECT 
        s.ticker,
        s.scan_date,
        s.entry_price,
        s.max_buy_price,
        s.stop_loss_price,
        s.stop_loss_price,
        GREATEST(s.current_price, s.entry_price),
        s.current_price,
        GREATEST(0.0, ROUND(((s.current_price - s.entry_price) / NULLIF(s.entry_price, 0) * 100)::numeric, 2)),
        ROUND(((s.current_price - s.entry_price) / NULLIF(s.entry_price, 0) * 100)::numeric, 2),
        s.entry_status,
        COALESCE(s.recommended_shares, 0),
        CURRENT_TIMESTAMP
    FROM screener_signals s
    WHERE s.scan_date = (SELECT MAX(scan_date) FROM screener_signals)
      AND s.entry_status != 'STOPPED_OUT'
    ON CONFLICT (symbol) DO NOTHING;
    """
    count = 0
    try:
        def _seed(cursor):
            nonlocal count
            cursor.execute(check_sql)
            row = cursor.fetchone()
            if row and row[0] == 0:
                logger.info("active_breakout_signals is empty. Seeding from latest screener_signals...")
                cursor.execute(seed_sql)
                count = cursor.rowcount
                logger.info(f"Seeded {count} active breakout records from screener_signals.")

        if cur:
            _seed(cur)
        else:
            with db_cursor(commit=True) as cursor:
                _seed(cursor)
    except Exception as e:
        logger.warning(f"Could not seed active_breakout_signals: {e}")
    return count



