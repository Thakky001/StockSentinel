"""
Authoritative Reference Math & Logic Oracle for StockSentinel.
Implements the exact formulas and decision logic defined in PROJECT.md and ORIGINAL_REQUEST.md.
Used as an independent ground-truth oracle for opaque-box testing.
"""

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Union
import math


def oracle_resample_daily_to_weekly(daily_bars: List[Dict[str, any]]) -> List[Dict[str, any]]:
    """
    Resamples daily bars into weekly bars (Monday-Friday convention, Friday close).
    """
    if not daily_bars:
        return []
    
    # Sort by date
    sorted_bars = sorted(daily_bars, key=lambda b: b["trade_date"])
    
    # Group by ISO year and calendar week (or Monday of that week)
    grouped = {}
    for bar in sorted_bars:
        d = date.fromisoformat(bar["trade_date"])
        # Monday of current week
        monday = d - datetime.timedelta(days=d.weekday()) if hasattr(datetime, "timedelta") else d
        # Alternatively using calendar isocalendar
        iso_year, iso_week, _ = d.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(bar)
    
    weekly_bars = []
    for week_key in sorted(grouped.keys()):
        bars_in_week = sorted(grouped[week_key], key=lambda b: b["trade_date"])
        
        # Open is first day's open
        week_open = bars_in_week[0]["open"]
        # High is max high in week
        week_high = max(b["high"] for b in bars_in_week)
        # Low is min low in week
        week_low = min(b["low"] for b in bars_in_week)
        # Close is last trading day's close (Friday or Thursday holiday)
        week_close = bars_in_week[-1]["close"]
        # Adj close is last trading day's adj_close
        week_adj_close = bars_in_week[-1].get("adj_close", week_close)
        # Volume is sum of daily volume
        week_volume = sum(b["volume"] for b in bars_in_week)
        # Last trading date represents the weekly bar timestamp
        week_date = bars_in_week[-1]["trade_date"]
        ticker = bars_in_week[0]["ticker"]
        
        weekly_bars.append({
            "ticker": ticker,
            "trade_date": week_date,
            "open": round(week_open, 4),
            "high": round(week_high, 4),
            "low": round(week_low, 4),
            "close": round(week_close, 4),
            "adj_close": round(week_adj_close, 4),
            "volume": int(week_volume),
            "trading_days": len(bars_in_week)
        })
    return weekly_bars


def oracle_sma(series: List[float], window: int) -> List[Optional[float]]:
    """
    Computes Simple Moving Average of length window.
    Returns None for indices < window - 1.
    """
    result = []
    for i in range(len(series)):
        if i < window - 1:
            result.append(None)
        else:
            avg = sum(series[i - window + 1 : i + 1]) / float(window)
            result.append(round(avg, 4))
    return result


def oracle_sma_slope(sma_series: List[Optional[float]], lookback: int = 1) -> List[Optional[float]]:
    """
    Computes percentage slope of SMA: ((SMA[t] - SMA[t-lookback]) / SMA[t-lookback]) * 100.
    """
    result = []
    for i in range(len(sma_series)):
        if i < lookback or sma_series[i] is None or sma_series[i - lookback] is None or sma_series[i - lookback] == 0:
            result.append(None)
        else:
            diff = sma_series[i] - sma_series[i - lookback]
            pct = (diff / sma_series[i - lookback]) * 100.0
            result.append(round(pct, 4))
    return result


def oracle_volume_surge(volumes: List[int], window: int = 10) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    Computes 10-week prior average volume (excluding current week) and surge ratio:
    surge_ratio = current_volume / avg_prior_10w.
    """
    avg_volumes = []
    surge_ratios = []
    for i in range(len(volumes)):
        if i < window:
            avg_volumes.append(None)
            surge_ratios.append(None)
        else:
            prior_10 = volumes[i - window : i]
            avg_vol = sum(prior_10) / float(window)
            avg_volumes.append(round(avg_vol, 2))
            surge = (volumes[i] / avg_vol) if avg_vol > 0 else 0.0
            surge_ratios.append(round(surge, 4))
    return avg_volumes, surge_ratios


def oracle_prior_resistance_pivot(highs: List[float], lookback: int = 35) -> List[Optional[float]]:
    """
    Computes the maximum high over the prior `lookback` weeks (excluding current week).
    """
    pivots = []
    for i in range(len(highs)):
        if i < lookback:
            pivots.append(None)
        else:
            prior_highs = highs[i - lookback : i]
            pivots.append(round(max(prior_highs), 4))
    return pivots


def oracle_mansfield_relative_strength(
    stock_closes: List[float],
    spy_closes: List[float],
    lookback: int = 52
) -> List[Optional[float]]:
    """
    Mansfield Relative Strength vs SPY benchmark.
    RS(t) = Stock_Close(t) / SPY_Close(t)
    RS_SMA52(t) = SMA(RS, 52 weeks)
    MRS(t) = ((RS(t) / RS_SMA52(t)) - 1.0) * 100.0
    """
    if len(stock_closes) != len(spy_closes):
        raise ValueError(f"Stock length {len(stock_closes)} != SPY length {len(spy_closes)}")
    
    rs_series = []
    for s_close, spy_close in zip(stock_closes, spy_closes):
        if spy_close <= 0:
            rs_series.append(0.0)
        else:
            rs_series.append(s_close / spy_close)
    
    mrs_series = []
    for i in range(len(rs_series)):
        if i < lookback - 1:
            mrs_series.append(None)
        else:
            window_rs = rs_series[i - lookback + 1 : i + 1]
            rs_sma = sum(window_rs) / float(lookback)
            if rs_sma <= 0:
                mrs_series.append(0.0)
            else:
                mrs = ((rs_series[i] / rs_sma) - 1.0) * 100.0
                mrs_series.append(round(mrs, 4))
    return mrs_series


def oracle_stage2_filter(
    close: float,
    sma_30w: Optional[float],
    sma_30w_slope: Optional[float],
    pivot_35w: Optional[float],
    vol_surge_ratio: Optional[float],
    mrs_score: Optional[float]
) -> Dict[str, any]:
    """
    Evaluates Stan Weinstein Stage 2 Breakout multi-factor filter.
    All 5 conditions must be True simultaneously:
    1. close > sma_30w
    2. sma_30w_slope >= 0.0
    3. close >= pivot_35w
    4. vol_surge_ratio >= 1.5
    5. mrs_score > 0.0
    """
    cond_close_above_sma = (sma_30w is not None) and (close > sma_30w)
    cond_sma_rising = (sma_30w_slope is not None) and (sma_30w_slope >= 0.0)
    cond_pivot_breakout = (pivot_35w is not None) and (close >= pivot_35w)
    cond_volume_surge = (vol_surge_ratio is not None) and (vol_surge_ratio >= 1.5)
    cond_mrs_positive = (mrs_score is not None) and (mrs_score > 0.0)
    
    is_stage2 = (
        cond_close_above_sma and
        cond_sma_rising and
        cond_pivot_breakout and
        cond_volume_surge and
        cond_mrs_positive
    )
    
    return {
        "is_stage2": is_stage2,
        "cond_close_above_sma": cond_close_above_sma,
        "cond_sma_rising": cond_sma_rising,
        "cond_pivot_breakout": cond_pivot_breakout,
        "cond_volume_surge": cond_volume_surge,
        "cond_mrs_positive": cond_mrs_positive
    }


def oracle_target_and_risk(
    pivot_35w: float,
    current_price: float,
    swing_low: Optional[float] = None
) -> Dict[str, float]:
    """
    Calculates entry target, max buy price, stop loss, and distance percentage:
    - entry_price = pivot_35w
    - max_buy_price = entry_price * 1.05 (+5%)
    - stop_loss_price = swing_low if provided else entry_price * 0.92 (-8%)
    - diff_pct = ((current_price - entry_price) / entry_price) * 100.0
    """
    entry_price = round(pivot_35w, 4)
    max_buy_price = round(entry_price * 1.05, 4)
    if swing_low is not None and 0 < swing_low < entry_price:
        stop_loss_price = round(swing_low, 4)
    else:
        stop_loss_price = round(entry_price * 0.92, 4)
    
    diff_pct = round(((current_price - entry_price) / entry_price) * 100.0, 4)
    
    return {
        "entry_price": entry_price,
        "max_buy_price": max_buy_price,
        "stop_loss_price": stop_loss_price,
        "current_price": round(current_price, 4),
        "diff_pct": diff_pct
    }


def oracle_entry_status(
    current_price: float,
    entry_price: float,
    max_buy_price: float,
    stop_loss_price: float
) -> str:
    """
    Deterministic entry status categorization:
    - current_price < stop_loss_price => STOPPED_OUT
    - current_price < entry_price => BELOW_ENTRY
    - entry_price <= current_price <= max_buy_price => IN_BUY_ZONE
    - current_price > max_buy_price => EXTENDED
    """
    if current_price < stop_loss_price:
        return "STOPPED_OUT"
    elif current_price < entry_price:
        return "BELOW_ENTRY"
    elif current_price <= max_buy_price:
        return "IN_BUY_ZONE"
    else:
        return "EXTENDED"


def oracle_position_sizing(
    account_size: float,
    risk_pct: float,
    entry_price: float,
    stop_loss_price: float
) -> Dict[str, any]:
    """
    Calculates exact risk and position sizing.
    Validations:
    - account_size > 0
    - risk_pct > 0
    - entry_price > 0
    - stop_loss_price > 0
    - stop_loss_price < entry_price
    """
    if account_size <= 0:
        return {"valid": False, "error": "Account size must be greater than zero"}
    if risk_pct <= 0 or risk_pct > 100:
        return {"valid": False, "error": "Risk percentage must be between 0 and 100"}
    if entry_price <= 0:
        return {"valid": False, "error": "Entry price must be greater than zero"}
    if stop_loss_price <= 0:
        return {"valid": False, "error": "Stop loss price must be greater than zero"}
    if stop_loss_price >= entry_price:
        return {"valid": False, "error": "Stop loss price must be strictly lower than Entry price"}
    
    max_dollar_risk = account_size * (risk_pct / 100.0)
    risk_per_share = entry_price - stop_loss_price
    shares_to_buy = math.floor(max_dollar_risk / risk_per_share)
    total_capital = shares_to_buy * entry_price
    portfolio_allocation_pct = (total_capital / account_size) * 100.0
    actual_dollar_risk = shares_to_buy * risk_per_share
    
    exceeds_capital = total_capital > account_size
    
    return {
        "valid": True,
        "max_dollar_risk": round(max_dollar_risk, 2),
        "actual_dollar_risk": round(actual_dollar_risk, 2),
        "risk_per_share": round(risk_per_share, 4),
        "shares_to_buy": shares_to_buy,
        "total_capital": round(total_capital, 2),
        "portfolio_allocation_pct": round(portfolio_allocation_pct, 2),
        "exceeds_capital": exceeds_capital
    }
