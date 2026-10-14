"""
REST API Contract and Lightweight Charts Schema Validator.
Validates Express REST API responses against PROJECT.md R5/R6 data contracts.
Includes an in-memory REST API controller simulator for deterministic opaque-box testing.
"""

from typing import Any, Dict, List, Optional, Tuple
import math


def validate_api_envelope(response_body: dict) -> Tuple[bool, Optional[str]]:
    """
    Validates top-level API envelope: must have boolean 'success'.
    If success=True, must have 'data' or 'message'.
    If success=False, must have 'error'.
    """
    if not isinstance(response_body, dict):
        return False, "Response body must be a JSON object"
    if "success" not in response_body or not isinstance(response_body["success"], bool):
        return False, "Response must include boolean 'success'"
    if response_body["success"]:
        if "data" not in response_body and "message" not in response_body:
            return False, "Successful response must contain 'data' or 'message'"
    else:
        if "error" not in response_body:
            return False, "Error response must contain 'error' message"
    return True, None


def validate_screener_latest_payload(data: dict) -> Tuple[bool, Optional[str]]:
    """
    Validates GET /api/screener/latest data structure.
    Expected: { scan_date: str, total: int, page: int, limit: int, total_pages: int, signals: list }
    """
    required_keys = ["scan_date", "total", "page", "limit", "total_pages", "signals"]
    for k in required_keys:
        if k not in data:
            return False, f"Missing key '{k}' in screener/latest response"
    
    if not isinstance(data["signals"], list):
        return False, "'signals' must be a list"
    
    for sig in data["signals"]:
        sig_keys = ["ticker", "entry_price", "current_price", "max_buy_price", "stop_loss_price", "diff_pct", "entry_status"]
        for sk in sig_keys:
            if sk not in sig:
                return False, f"Missing field '{sk}' in signal entry"
        if sig["entry_status"] not in {'IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT'}:
            return False, f"Invalid entry_status: {sig['entry_status']}"
            
    return True, None


def validate_chart_payload(data: dict) -> Tuple[bool, Optional[str]]:
    """
    Validates GET /api/stock/:ticker/chart data structure for Lightweight Charts.
    Expected:
    - ticker: str
    - company_name: str
    - candlesticks: list of { time: 'YYYY-MM-DD', open: float, high: float, low: float, close: float }
    - sma30: list of { time: 'YYYY-MM-DD', value: float }
    - volume: list of { time: 'YYYY-MM-DD', value: int, color: str }
    - metrics: { entry_price, max_buy_price, stop_loss_price, status, close_price }
    - Ascending chronological order of timestamps
    """
    required_keys = ["ticker", "company_name", "candlesticks", "sma30", "volume", "metrics"]
    for k in required_keys:
        if k not in data:
            return False, f"Missing key '{k}' in chart response"
    
    candlesticks = data["candlesticks"]
    if not isinstance(candlesticks, list):
        return False, "'candlesticks' must be a list"
    
    # Verify chronological ascending order and format
    prev_time = ""
    for c in candlesticks:
        for ck in ["time", "open", "high", "low", "close"]:
            if ck not in c:
                return False, f"Candlestick missing key '{ck}'"
        t = c["time"]
        if len(t) != 10 or t[4] != '-' or t[7] != '-':
            return False, f"Invalid ISO date format for candlestick time: {t}"
        if prev_time and t <= prev_time:
            return False, f"Candlesticks not strictly sorted in ascending time order: {prev_time} -> {t}"
        prev_time = t
        if c["high"] < c["low"]:
            return False, f"Candlestick high ({c['high']}) < low ({c['low']})"

    # Verify SMA30 series
    prev_time = ""
    for s in data["sma30"]:
        if "time" not in s or "value" not in s:
            return False, "SMA30 point missing 'time' or 'value'"
        t = s["time"]
        if prev_time and t <= prev_time:
            return False, f"SMA30 points not sorted ascending: {prev_time} -> {t}"
        prev_time = t

    # Verify volume series
    for v in data["volume"]:
        if "time" not in v or "value" not in v or "color" not in v:
            return False, "Volume point missing 'time', 'value', or 'color'"

    # Verify metrics
    metrics = data["metrics"]
    for mk in ["entry_price", "max_buy_price", "stop_loss_price", "status"]:
        if mk not in metrics:
            return False, f"Metrics missing key '{mk}'"

    return True, None


class InMemoryExpressApp:
    """
    In-memory simulator of the Express REST API backend endpoints for opaque-box E2E testing.
    Routes:
    - GET /api/screener/latest
    - GET /api/screener/dates
    - GET /api/stock/:ticker/chart
    - GET /api/stock/:ticker/summary
    - POST /api/screener/trigger
    - POST /api/notifications/telegram-test
    """
    def __init__(self, db):
        self.db = db
        self.is_scanner_running = False
        self.telegram_configured = True

    def handle_get_screener_latest(self, query: dict) -> Tuple[int, dict]:
        date_param = query.get("date")
        sector_param = query.get("sector")
        status_param = query.get("status")
        search_param = query.get("search", "").lower()
        sort_by = query.get("sort_by", "diff_pct")
        order = query.get("order", "asc").lower()
        page = max(1, int(query.get("page", 1)))
        limit = max(1, min(100, int(query.get("limit", 50))))

        # Find latest scan date if not specified
        all_signals = list(self.db.screener_signals.values())
        if not all_signals:
            return 200, {
                "success": True,
                "data": {
                    "scan_date": date_param or "",
                    "total": 0,
                    "page": page,
                    "limit": limit,
                    "total_pages": 0,
                    "signals": []
                }
            }

        dates = sorted(list({s["scan_date"] for s in all_signals}), reverse=True)
        scan_date = date_param if date_param else dates[0]

        filtered = [s for s in all_signals if s["scan_date"] == scan_date]

        # Join with stocks for sector and name
        enriched = []
        for s in filtered:
            stk = self.db.stocks.get(s["ticker"], {})
            item = dict(s)
            item["company_name"] = stk.get("name", s["ticker"])
            item["sector"] = stk.get("sector", "")
            enriched.append(item)

        # Apply filters
        if sector_param:
            enriched = [s for s in enriched if s["sector"].lower() == sector_param.lower()]
        if status_param:
            enriched = [s for s in enriched if s["entry_status"] == status_param]
        if search_param:
            enriched = [s for s in enriched if search_param in s["ticker"].lower() or search_param in s["company_name"].lower()]

        # Apply sorting
        reverse = (order == "desc")
        if sort_by in ["diff_pct", "volume_surge_ratio", "mrs_score", "entry_price", "current_price"]:
            enriched.sort(key=lambda x: float(x.get(sort_by, 0)), reverse=reverse)
        elif sort_by in ["ticker", "company_name", "sector", "entry_status"]:
            enriched.sort(key=lambda x: str(x.get(sort_by, "")), reverse=reverse)

        total = len(enriched)
        total_pages = math.ceil(total / limit) if total > 0 else 0
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_signals = enriched[start_idx:end_idx]

        return 200, {
            "success": True,
            "data": {
                "scan_date": scan_date,
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "signals": paginated_signals
            }
        }

    def handle_get_screener_dates(self) -> Tuple[int, dict]:
        all_signals = list(self.db.screener_signals.values())
        dates = sorted(list({s["scan_date"] for s in all_signals}), reverse=True)
        return 200, {
            "success": True,
            "data": {
                "dates": dates
            }
        }

    def handle_get_stock_chart(self, ticker: str) -> Tuple[int, dict]:
        ticker = ticker.strip().upper()
        if ticker not in self.db.stocks:
            return 404, {"success": False, "error": f"Stock {ticker} not found"}
        
        stk = self.db.stocks[ticker]
        
        # Gather daily bars and build weekly candlesticks
        ticker_bars = [b for k, b in self.db.stock_daily_bars.items() if k[0] == ticker]
        from tests.e2e.helpers.formula_oracle import oracle_resample_daily_to_weekly, oracle_sma
        weekly_bars = oracle_resample_daily_to_weekly(ticker_bars)
        
        closes = [w["close"] for w in weekly_bars]
        sma30_vals = oracle_sma(closes, window=30)
        
        candlesticks = []
        sma30 = []
        volume = []
        for i, w in enumerate(weekly_bars):
            candlesticks.append({
                "time": w["trade_date"],
                "open": w["open"],
                "high": w["high"],
                "low": w["low"],
                "close": w["close"]
            })
            if sma30_vals[i] is not None:
                sma30.append({
                    "time": w["trade_date"],
                    "value": sma30_vals[i]
                })
            color = "rgba(34, 197, 94, 0.5)" if w["close"] >= w["open"] else "rgba(239, 68, 68, 0.5)"
            volume.append({
                "time": w["trade_date"],
                "value": w["volume"],
                "color": color
            })
            
        # Get latest signal metrics if available
        sig = next((s for s in reversed(list(self.db.screener_signals.values())) if s["ticker"] == ticker), None)
        metrics = {
            "entry_price": sig["entry_price"] if sig else (weekly_bars[-1]["high"] if weekly_bars else 0),
            "max_buy_price": sig["max_buy_price"] if sig else (round(weekly_bars[-1]["high"] * 1.05, 4) if weekly_bars else 0),
            "stop_loss_price": sig["stop_loss_price"] if sig else (round(weekly_bars[-1]["low"] * 0.92, 4) if weekly_bars else 0),
            "status": sig["entry_status"] if sig else "NONE",
            "close_price": weekly_bars[-1]["close"] if weekly_bars else 0
        }
        
        return 200, {
            "success": True,
            "data": {
                "ticker": ticker,
                "company_name": stk["name"],
                "candlesticks": candlesticks,
                "sma30": sma30,
                "volume": volume,
                "metrics": metrics
            }
        }

    def handle_get_stock_summary(self, ticker: str) -> Tuple[int, dict]:
        ticker = ticker.strip().upper()
        if ticker not in self.db.stocks:
            return 404, {"success": False, "error": f"Stock {ticker} not found"}
        
        stk = self.db.stocks[ticker]
        latest_sig = next((s for s in reversed(list(self.db.screener_signals.values())) if s["ticker"] == ticker), None)
        
        # Latest daily bar
        ticker_daily = sorted([b for k, b in self.db.stock_daily_bars.items() if k[0] == ticker], key=lambda x: x["trade_date"])
        latest_bar = ticker_daily[-1] if ticker_daily else None
        
        return 200, {
            "success": True,
            "data": {
                "ticker": ticker,
                "name": stk["name"],
                "sector": stk.get("sector"),
                "industry": stk.get("industry"),
                "market_cap": stk.get("market_cap"),
                "exchange": stk.get("exchange"),
                "latest_signal": latest_sig,
                "latest_daily_bar": latest_bar
            }
        }

    def handle_post_screener_trigger(self) -> Tuple[int, dict]:
        if self.is_scanner_running:
            return 409, {
                "success": False,
                "error": "A screener run is already in progress"
            }
        
        self.is_scanner_running = True
        job_id = self.db.create_scan_job({
            "job_type": "WEEKLY_SCREEN",
            "status": "RUNNING",
            "started_at": "2026-10-14T02:30:00Z",
            "tickers_total": len(self.db.stocks)
        })
        return 200, {
            "success": True,
            "data": {
                "job_id": job_id,
                "status": "RUNNING",
                "message": "Screener job triggered successfully"
            }
        }

    def handle_post_telegram_test(self, has_valid_token: bool = True) -> Tuple[int, dict]:
        if not self.telegram_configured or not has_valid_token:
            return 400, {
                "success": False,
                "error": "Telegram Bot Token or Chat ID is not configured"
            }
        return 200, {
            "success": True,
            "message": "Test alert sent successfully",
            "telegram_message_id": 987654321
        }
