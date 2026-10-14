"""
Synthetic Mock Data Generator for StockSentinel E2E Tests.
Provides high-fidelity, deterministic test fixtures for stock universe,
daily OHLCV bars, weekly aggregated bars, SPY benchmark, and screener signals.
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
import math


def generate_universe_tickers() -> List[Dict[str, any]]:
    """
    Returns a representative sample of Russell 3000 and S&P 1500 equities + SPY benchmark.
    Includes large caps, mid caps, small caps, and dual-class shares (e.g. BRK.B, BF.B).
    """
    tickers = [
        {"ticker": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "NYSE", "sector": "ETF", "industry": "Index ETF", "market_cap": 500_000_000_000, "is_active": True, "in_russell3000": False, "in_sp1500": False},
        {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Consumer Electronics", "market_cap": 3_000_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ", "sector": "Technology", "industry": "Software - Infrastructure", "market_cap": 3_100_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "sector": "Technology", "industry": "Semiconductors", "market_cap": 2_800_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "AMZN", "name": "Amazon.com Inc.", "exchange": "NASDAQ", "sector": "Consumer Cyclical", "industry": "Internet Retail", "market_cap": 1_900_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "GOOGL", "name": "Alphabet Inc. Class A", "exchange": "NASDAQ", "sector": "Communication Services", "industry": "Internet Content & Information", "market_cap": 2_000_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "BRK.B", "name": "Berkshire Hathaway Inc. Class B", "exchange": "NYSE", "sector": "Financial", "industry": "Insurance - Diversified", "market_cap": 900_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "JPM", "name": "JPMorgan Chase & Co.", "exchange": "NYSE", "sector": "Financial Services", "industry": "Banks - Diversified", "market_cap": 580_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "LLY", "name": "Eli Lilly and Company", "exchange": "NYSE", "sector": "Healthcare", "industry": "Drug Manufacturers - General", "market_cap": 750_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "TSLA", "name": "Tesla Inc.", "exchange": "NASDAQ", "sector": "Consumer Cyclical", "industry": "Auto Manufacturers", "market_cap": 700_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "CRWD", "name": "CrowdStrike Holdings Inc.", "exchange": "NASDAQ", "sector": "Technology", "industry": "Security Software", "market_cap": 60_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "CELH", "name": "Celsius Holdings Inc.", "exchange": "NASDAQ", "sector": "Consumer Defensive", "industry": "Beverages - Non-Alcoholic", "market_cap": 9_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "AXON", "name": "Axon Enterprise Inc.", "exchange": "NASDAQ", "sector": "Industrials", "industry": "Aerospace & Defense", "market_cap": 25_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "WING", "name": "Wingstop Inc.", "exchange": "NASDAQ", "sector": "Consumer Cyclical", "industry": "Restaurants", "market_cap": 11_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
        {"ticker": "INSM", "name": "Insmed Incorporated", "exchange": "NASDAQ", "sector": "Healthcare", "industry": "Biotechnology", "market_cap": 12_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": False},
        {"ticker": "BF.B", "name": "Brown-Forman Corporation Class B", "exchange": "NYSE", "sector": "Consumer Defensive", "industry": "Beverages - Wineries & Distilleries", "market_cap": 20_000_000_000, "is_active": True, "in_russell3000": True, "in_sp1500": True},
    ]
    return tickers


def generate_market_trading_days(num_days: int = 520, end_date: Optional[date] = None) -> List[date]:
    """
    Generates a list of valid US market trading days (Monday-Friday, excluding weekends),
    ending on end_date (or default 2026-10-09).
    """
    if end_date is None:
        end_date = date(2026, 10, 9)  # Friday
    
    trading_days = []
    curr = end_date
    while len(trading_days) < num_days:
        if curr.weekday() < 5:  # Monday to Friday
            trading_days.append(curr)
        curr -= timedelta(days=1)
    
    trading_days.reverse()
    return trading_days


def generate_daily_bars_for_stock(
    ticker: str,
    pattern: str = "stage2_breakout",
    num_days: int = 520,
    base_price: float = 100.0,
    end_date: Optional[date] = None
) -> List[Dict[str, any]]:
    """
    Generates realistic daily OHLCV bars tailored to specific technical patterns:
    - 'stage2_breakout': 35 weeks consolidating under 120 resistance, then rising SMA 30w, volume surge 2.5x, and breakout close to 123.
    - 'below_entry': Breakout attempt failed, pulled back below entry pivot.
    - 'extended': Surged way past max buy (> +5%, e.g. +15% above entry).
    - 'stopped_out': Dropped below stop loss price.
    - 'stage4_downtrend': Declining price below declining 30w SMA.
    - 'low_volume_breakout': Price broke out above pivot, but volume surge is only 1.1x (< 1.5x threshold).
    - 'weak_mrs': Breakout occurred but relative strength vs benchmark is negative (MRS < 0).
    """
    dates = generate_market_trading_days(num_days=num_days, end_date=end_date)
    bars = []
    
    price = base_price
    for i, d in enumerate(dates):
        # Progress from 0.0 to 1.0 across history
        t = i / float(num_days)
        
        # Base volume: around 1,000,000 shares
        vol = 1_000_000 + int(100_000 * math.sin(i / 10.0))
        
        if pattern == "stage2_breakout":
            if t < 0.6:
                # Stage 1 base: oscillates between 90 and 110
                price = base_price + 10.0 * math.sin(i / 15.0)
            elif t < 0.95:
                # Tight base under resistance pivot 120.0
                price = 115.0 + 4.5 * math.sin(i / 8.0)
            else:
                # Breakout in final weeks: price moves from 118 to 124, volume doubles
                step = (i - (num_days * 0.95))
                price = 118.0 + (step * 0.3)
                vol = int(vol * 2.2)  # High surge
                
        elif pattern == "below_entry":
            if t < 0.95:
                price = 115.0 + 4.5 * math.sin(i / 8.0)
            elif t < 0.98:
                price = 121.0  # brief breakout
            else:
                price = 118.5  # pulls back below 120.0 pivot
                vol = int(vol * 1.6)

        elif pattern == "extended":
            if t < 0.90:
                price = 115.0 + 4.5 * math.sin(i / 8.0)
            else:
                # Surged to 135 (well past max buy 120 * 1.05 = 126.0)
                price = 120.0 + ((i - (num_days * 0.90)) * 0.8)
                vol = int(vol * 2.5)

        elif pattern == "stopped_out":
            if t < 0.90:
                price = 115.0 + 4.5 * math.sin(i / 8.0)
            elif t < 0.95:
                price = 121.0
            else:
                price = 108.0  # dropped below stop loss 111.6
                vol = int(vol * 1.8)

        elif pattern == "stage4_downtrend":
            # Consistent downward trend
            price = base_price * (1.2 - 0.5 * t) + 2.0 * math.sin(i / 5.0)
            vol = int(vol * 0.9)

        elif pattern == "low_volume_breakout":
            if t < 0.95:
                price = 115.0 + 4.5 * math.sin(i / 8.0)
            else:
                price = 123.0  # broke out
                vol = int(vol * 1.1)  # volume did not surge (needs >= 1.5x)

        elif pattern == "weak_mrs":
            # Flat to weak performance
            price = base_price * (1.0 + 0.05 * t)
            if t > 0.95:
                price = base_price * 1.10
                vol = int(vol * 2.0)
        else:
            price = base_price + 5.0 * math.sin(i / 10.0)

        daily_open = round(price * 0.998, 4)
        daily_high = round(price * 1.012, 4)
        daily_low = round(price * 0.992, 4)
        daily_close = round(price, 4)
        adj_close = daily_close
        
        bars.append({
            "ticker": ticker,
            "trade_date": d.isoformat(),
            "open": daily_open,
            "high": max(daily_high, daily_open, daily_close),
            "low": min(daily_low, daily_open, daily_close),
            "close": daily_close,
            "adj_close": adj_close,
            "volume": vol
        })
    return bars


def generate_spy_benchmark_bars(num_days: int = 520, end_date: Optional[date] = None) -> List[Dict[str, any]]:
    """
    Generates realistic daily bars for SPY benchmark (steady bull market trend).
    Starting at 420.0 and rising to ~570.0.
    """
    dates = generate_market_trading_days(num_days=num_days, end_date=end_date)
    bars = []
    
    start_price = 420.0
    end_price = 570.0
    
    for i, d in enumerate(dates):
        t = i / float(num_days)
        base = start_price + (end_price - start_price) * t
        osc = 5.0 * math.sin(i / 12.0)
        close = round(base + osc, 4)
        open_p = round(close * 0.998, 4)
        high_p = round(close * 1.006, 4)
        low_p = round(close * 0.994, 4)
        vol = 50_000_000 + int(5_000_000 * math.sin(i / 7.0))
        
        bars.append({
            "ticker": "SPY",
            "trade_date": d.isoformat(),
            "open": open_p,
            "high": max(high_p, open_p, close),
            "low": min(low_p, open_p, close),
            "close": close,
            "adj_close": close,
            "volume": vol
        })
    return bars
