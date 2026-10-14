"""
SQL Schema and Constraint Validator for PostgreSQL 16 DDL.
Validates table structures, column datatypes, primary/foreign keys,
CHECK constraints, and unique indexes against PROJECT.md R1 specifications.
Includes an in-memory SQL relational emulator for contract testing without live Postgres.
"""

from typing import Dict, List, Optional, Set, Tuple
import re


# Canonical R1 Schema Specifications
EXPECTED_TABLES = {
    "stocks": {
        "columns": {
            "ticker": {"type": "VARCHAR", "length": 16, "nullable": False, "pk": True},
            "name": {"type": "VARCHAR", "length": 255, "nullable": False},
            "exchange": {"type": "VARCHAR", "length": 32, "nullable": True},
            "sector": {"type": "VARCHAR", "length": 128, "nullable": True},
            "industry": {"type": "VARCHAR", "length": 128, "nullable": True},
            "market_cap": {"type": "BIGINT", "nullable": True},
            "is_active": {"type": "BOOLEAN", "default": True},
            "in_russell3000": {"type": "BOOLEAN", "default": False},
            "in_sp1500": {"type": "BOOLEAN", "default": False},
            "created_at": {"type": "TIMESTAMPTZ", "nullable": True},
            "updated_at": {"type": "TIMESTAMPTZ", "nullable": True},
        },
        "pk": ["ticker"],
    },
    "stock_daily_bars": {
        "columns": {
            "ticker": {"type": "VARCHAR", "length": 16, "nullable": False, "fk": ("stocks", "ticker")},
            "trade_date": {"type": "DATE", "nullable": False},
            "open": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "high": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "low": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "close": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "adj_close": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "volume": {"type": "BIGINT", "nullable": False},
            "created_at": {"type": "TIMESTAMPTZ", "nullable": True},
        },
        "pk": ["ticker", "trade_date"],
        "checks": [
            "high >= low",
            "high >= open",
            "high >= close",
            "low <= open",
            "low <= close",
            "volume >= 0",
        ],
    },
    "scan_jobs": {
        "columns": {
            "id": {"type": "BIGSERIAL", "nullable": False, "pk": True},
            "job_type": {"type": "VARCHAR", "length": 64, "nullable": False},
            "status": {"type": "VARCHAR", "length": 32, "nullable": False},
            "started_at": {"type": "TIMESTAMPTZ", "nullable": False},
            "completed_at": {"type": "TIMESTAMPTZ", "nullable": True},
            "tickers_total": {"type": "INT", "default": 0},
            "tickers_processed": {"type": "INT", "default": 0},
            "tickers_failed": {"type": "INT", "default": 0},
            "signals_found": {"type": "INT", "default": 0},
            "error_message": {"type": "TEXT", "nullable": True},
            "telegram_alert_sent": {"type": "BOOLEAN", "default": False},
        },
        "pk": ["id"],
        "checks": [
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
        ],
    },
    "screener_signals": {
        "columns": {
            "id": {"type": "BIGSERIAL", "nullable": False, "pk": True},
            "scan_id": {"type": "BIGINT", "fk": ("scan_jobs", "id"), "nullable": True},
            "scan_date": {"type": "DATE", "nullable": False},
            "ticker": {"type": "VARCHAR", "length": 16, "fk": ("stocks", "ticker"), "nullable": False},
            "entry_price": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "max_buy_price": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "current_price": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "stop_loss_price": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "diff_pct": {"type": "NUMERIC", "precision": (8, 4), "nullable": False},
            "entry_status": {"type": "VARCHAR", "length": 32, "nullable": False},
            "volume_surge_ratio": {"type": "NUMERIC", "precision": (8, 4), "nullable": False},
            "mrs_score": {"type": "NUMERIC", "precision": (10, 4), "nullable": False},
            "sma_30w": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "sma_30w_slope": {"type": "NUMERIC", "precision": (8, 4), "nullable": False},
            "prior_resistance_35w": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "weekly_close": {"type": "NUMERIC", "precision": (12, 4), "nullable": False},
            "weekly_volume": {"type": "BIGINT", "nullable": False},
            "avg_volume_10w": {"type": "BIGINT", "nullable": False},
            "stage": {"type": "VARCHAR", "length": 32, "default": "Stage 2"},
            "created_at": {"type": "TIMESTAMPTZ", "nullable": True},
        },
        "pk": ["id"],
        "unique": [["scan_date", "ticker"]],
        "checks": [
            "entry_status IN ('IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT')",
            "entry_price > 0",
            "current_price > 0",
        ],
    },
}


class InMemoryRelationalDB:
    """
    Lightweight, deterministic relational database emulator for testing
    PostgreSQL schema contracts, constraints, upserts, foreign keys, and queries.
    """
    def __init__(self):
        self.stocks: Dict[str, dict] = {}
        self.stock_daily_bars: Dict[Tuple[str, str], dict] = {}
        self.scan_jobs: Dict[int, dict] = {}
        self.screener_signals: Dict[int, dict] = {}
        self.unique_signals: Dict[Tuple[str, str], int] = {}
        self._next_scan_job_id = 1
        self._next_signal_id = 1

    def upsert_stock(self, stock_row: dict) -> bool:
        ticker = stock_row.get("ticker")
        if not ticker or not isinstance(ticker, str):
            raise ValueError("ticker must be a non-empty string")
        if len(ticker) > 16:
            raise ValueError("ticker length exceeds 16 chars")
        if "name" not in stock_row or not stock_row["name"]:
            raise ValueError("name is required and cannot be empty")
        
        # Upsert
        self.stocks[ticker] = dict(stock_row)
        return True

    def upsert_daily_bar(self, bar_row: dict) -> bool:
        ticker = bar_row.get("ticker")
        trade_date = bar_row.get("trade_date")
        
        # Foreign key validation
        if ticker not in self.stocks:
            raise ValueError(f"Foreign key violation: ticker {ticker} not found in stocks")
        
        # Check constraints
        open_p = float(bar_row["open"])
        high_p = float(bar_row["high"])
        low_p = float(bar_row["low"])
        close_p = float(bar_row["close"])
        vol = int(bar_row["volume"])
        
        if high_p < low_p:
            raise ValueError(f"Check constraint violation: high ({high_p}) < low ({low_p})")
        if high_p < open_p:
            raise ValueError(f"Check constraint violation: high ({high_p}) < open ({open_p})")
        if high_p < close_p:
            raise ValueError(f"Check constraint violation: high ({high_p}) < close ({close_p})")
        if low_p > open_p:
            raise ValueError(f"Check constraint violation: low ({low_p}) > open ({open_p})")
        if low_p > close_p:
            raise ValueError(f"Check constraint violation: low ({low_p}) > close ({close_p})")
        if vol < 0:
            raise ValueError(f"Check constraint violation: volume ({vol}) < 0")
        
        key = (ticker, str(trade_date))
        self.stock_daily_bars[key] = dict(bar_row)
        return True

    def create_scan_job(self, job_row: dict) -> int:
        status = job_row.get("status", "PENDING")
        valid_statuses = {'PENDING', 'RUNNING', 'COMPLETED', 'FAILED'}
        if status not in valid_statuses:
            raise ValueError(f"Invalid scan_jobs status {status}")
        
        job_id = self._next_scan_job_id
        self._next_scan_job_id += 1
        
        record = dict(job_row)
        record["id"] = job_id
        self.scan_jobs[job_id] = record
        return job_id

    def update_scan_job(self, job_id: int, updates: dict) -> bool:
        if job_id not in self.scan_jobs:
            raise KeyError(f"Job id {job_id} not found")
        if "status" in updates and updates["status"] not in {'PENDING', 'RUNNING', 'COMPLETED', 'FAILED'}:
            raise ValueError(f"Invalid status: {updates['status']}")
        self.scan_jobs[job_id].update(updates)
        return True

    def upsert_screener_signal(self, signal_row: dict) -> int:
        ticker = signal_row.get("ticker")
        scan_date = str(signal_row.get("scan_date"))
        
        if ticker not in self.stocks:
            raise ValueError(f"Foreign key violation: ticker {ticker} not found in stocks")
        
        scan_id = signal_row.get("scan_id")
        if scan_id is not None and scan_id not in self.scan_jobs:
            raise ValueError(f"Foreign key violation: scan_id {scan_id} not found in scan_jobs")
        
        status = signal_row.get("entry_status")
        valid_statuses = {'IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT'}
        if status not in valid_statuses:
            raise ValueError(f"Invalid entry_status {status}")
        
        entry_price = float(signal_row.get("entry_price", 0))
        current_price = float(signal_row.get("current_price", 0))
        if entry_price <= 0:
            raise ValueError(f"entry_price must be > 0, got {entry_price}")
        if current_price <= 0:
            raise ValueError(f"current_price must be > 0, got {current_price}")
        
        unique_key = (scan_date, ticker)
        if unique_key in self.unique_signals:
            # ON CONFLICT (scan_date, ticker) DO UPDATE
            existing_id = self.unique_signals[unique_key]
            updated_record = dict(signal_row)
            updated_record["id"] = existing_id
            self.screener_signals[existing_id] = updated_record
            return existing_id
        else:
            sig_id = self._next_signal_id
            self._next_signal_id += 1
            new_record = dict(signal_row)
            new_record["id"] = sig_id
            self.screener_signals[sig_id] = new_record
            self.unique_signals[unique_key] = sig_id
            return sig_id
