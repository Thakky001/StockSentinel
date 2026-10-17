"""
screener/src/indicators.py - Vectorized Polars & List Technical Indicator Calculations:
- Daily to Weekly OHLCV bar resampling with holiday handling and Friday/last-day anchoring.
- 30-week Simple Moving Average (SMA) and SMA slope percentage.
- 10-week prior volume average and volume surge ratio (>= 1.5x).
- 35-week prior resistance pivot.
- Mansfield Relative Strength (MRS) vs SPY benchmark (52-week).
"""
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
import polars as pl

logger = logging.getLogger(__name__)

# Minimum historical bars required for complete indicator warmup
MIN_WEEKLY_BARS = 52
MIN_DAILY_BARS = 260


def _resample_daily_df(daily_df: pl.DataFrame) -> pl.DataFrame:
    """
    Internal vector-optimized Polars resampling of daily bars to weekly bars.
    """
    if daily_df.is_empty():
        return pl.DataFrame(
            schema={
                "ticker": pl.Utf8,
                "trade_date": pl.Date,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "adj_close": pl.Float64,
                "volume": pl.Int64,
                "trading_days": pl.Int32,
            }
        )

    df = daily_df

    # Ensure ticker column exists
    if "ticker" not in df.columns:
        df = df.with_columns(pl.lit("UNKNOWN").alias("ticker"))

    # Ensure trade_date is pl.Date
    string_types = (pl.Utf8, getattr(pl, "String", pl.Utf8))
    if df.schema["trade_date"] in string_types:
        df = df.with_columns(pl.col("trade_date").str.to_date("%Y-%m-%d"))
    elif df.schema["trade_date"] == pl.Object:
        df = df.with_columns(pl.col("trade_date").cast(pl.Utf8).str.to_date("%Y-%m-%d"))
    elif df.schema["trade_date"] != pl.Date:
        df = df.with_columns(pl.col("trade_date").cast(pl.Date))

    # Ensure price columns are Float64
    for price_col in ["open", "high", "low", "close"]:
        if price_col in df.columns and df.schema[price_col] != pl.Float64:
            df = df.with_columns(pl.col(price_col).cast(pl.Float64))

    # Ensure adj_close column exists and is Float64
    if "adj_close" not in df.columns:
        df = df.with_columns(pl.col("close").alias("adj_close"))
    else:
        df = df.with_columns(
            pl.coalesce([pl.col("adj_close"), pl.col("close")]).cast(pl.Float64).alias("adj_close")
        )

    # Ensure volume is Int64
    if df.schema["volume"] != pl.Int64:
        df = df.with_columns(pl.col("volume").cast(pl.Int64))

    # Sort chronologically by ticker and trade_date
    df = df.sort(["ticker", "trade_date"])

    # Truncate to Monday of the calendar week (ISO 8601 week start)
    df = df.with_columns(
        pl.col("trade_date").dt.truncate("1w").alias("week_start")
    )

    # Group by ticker and week_start, aggregating OHLCV
    weekly = (
        df.group_by(["ticker", "week_start"], maintain_order=True)
        .agg([
            pl.col("trade_date").last().alias("trade_date"),
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("adj_close").last().alias("adj_close"),
            pl.col("volume").sum().cast(pl.Int64).alias("volume"),
            pl.col("trade_date").count().cast(pl.Int32).alias("trading_days"),
        ])
        .drop("week_start")
        .sort(["ticker", "trade_date"])
    )

    return weekly


def resample_daily_to_weekly_pylist(daily_bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convenience wrapper converting a list of daily bar dictionaries to a list of weekly bar dictionaries.
    Maintains compatibility with test oracle and non-DataFrame callers.
    """
    if not daily_bars:
        return []

    # Sort daily bars chronologically ascending
    sorted_bars = sorted(daily_bars, key=lambda b: str(b["trade_date"]))
    df = pl.DataFrame(sorted_bars)
    weekly_df = _resample_daily_df(df)

    # Format trade_date as ISO string and ensure standard numeric types
    formatted = weekly_df.with_columns(
        pl.col("trade_date").dt.to_string("%Y-%m-%d").alias("trade_date"),
        pl.col("open").round(4),
        pl.col("high").round(4),
        pl.col("low").round(4),
        pl.col("close").round(4),
        pl.col("adj_close").round(4),
        pl.col("volume").cast(pl.Int64),
        pl.col("trading_days").cast(pl.Int32),
    )
    dicts = formatted.to_dicts()
    for d in dicts:
        d["volume"] = int(d["volume"])
        d["trading_days"] = int(d["trading_days"])
    return dicts


def resample_daily_to_weekly(
    daily_df_or_bars: Union[pl.DataFrame, List[Dict[str, Any]]]
) -> Union[pl.DataFrame, List[Dict[str, Any]]]:
    """
    Resamples daily OHLCV bars into calendar weekly bars (Monday-Friday convention).
    Accepts either a Polars DataFrame or a list of daily bar dictionaries.
    Returns the same format as input (DataFrame -> DataFrame, list -> list of dicts).
    
    Aggregation rules:
    - open: first available trading day open
    - high: maximum daily high in the week
    - low: minimum daily low in the week
    - close: last available trading day close
    - adj_close: last available trading day adj_close
    - volume: sum of daily volume across the week (64-bit int / pl.Int64)
    - trade_date: date of the last active trading session (Friday, or Thursday on holiday weeks)
    - trading_days: count of daily bars compressed into this weekly bar
    """
    if isinstance(daily_df_or_bars, list):
        return resample_daily_to_weekly_pylist(daily_df_or_bars)
    elif isinstance(daily_df_or_bars, pl.DataFrame):
        return _resample_daily_df(daily_df_or_bars)
    else:
        raise TypeError(f"Expected pl.DataFrame or list of dicts, got {type(daily_df_or_bars)}")


def compute_sma(closes: List[float], window: int = 30) -> List[Optional[float]]:
    """
    Computes rolling Simple Moving Average of length `window` on a list of closes.
    Returns None for indices < window - 1.
    """
    if len(closes) < window:
        return [None] * len(closes)

    result: List[Optional[float]] = []
    running_sum = 0.0
    for i, c in enumerate(closes):
        running_sum += c
        if i < window - 1:
            result.append(None)
        elif i == window - 1:
            result.append(round(running_sum / float(window), 4))
        else:
            running_sum -= closes[i - window]
            result.append(round(running_sum / float(window), 4))
    return result


def compute_sma_30w(df: pl.DataFrame, window: int = 30) -> pl.DataFrame:
    """
    Computes 30-week Simple Moving Average of close on a Polars DataFrame.
    Requires at least 30 weekly bars. First 29 bars are null.
    """
    group_col = "ticker" if "ticker" in df.columns else None
    if group_col:
        return df.with_columns(
            pl.col("close")
            .rolling_mean(window_size=window, min_periods=window)
            .round(4)
            .over(group_col)
            .alias("sma_30w")
        )
    else:
        return df.with_columns(
            pl.col("close")
            .rolling_mean(window_size=window, min_periods=window)
            .round(4)
            .alias("sma_30w")
        )


def compute_sma_slope(
    sma_series: List[Optional[float]],
    lookback: int = 1
) -> List[Optional[float]]:
    """
    Computes percentage slope of SMA on a list of values:
    slope = ((SMA[t] - SMA[t-lookback]) / SMA[t-lookback]) * 100.0
    Guards against None and division by zero (SMA[t-lookback] == 0) -> None.
    """
    result: List[Optional[float]] = []
    for i in range(len(sma_series)):
        if (
            i < lookback
            or sma_series[i] is None
            or sma_series[i - lookback] is None
            or sma_series[i - lookback] == 0.0
        ):
            result.append(None)
        else:
            diff = sma_series[i] - sma_series[i - lookback]
            pct = (diff / sma_series[i - lookback]) * 100.0
            result.append(round(pct, 4))
    return result


def compute_sma_30w_slope(df: pl.DataFrame, lookback: int = 1) -> pl.DataFrame:
    """
    Computes percentage slope of SMA 30w on a Polars DataFrame:
    slope = ((SMA30[t] - SMA30[t-lookback]) / SMA30[t-lookback]) * 100.0
    Guards against division by zero and nulls.
    """
    group_col = "ticker" if "ticker" in df.columns else None
    if group_col:
        prior_sma = pl.col("sma_30w").shift(lookback).over(group_col)
    else:
        prior_sma = pl.col("sma_30w").shift(lookback)

    diff = pl.col("sma_30w") - prior_sma
    slope_expr = (
        pl.when(
            pl.col("sma_30w").is_not_null()
            & prior_sma.is_not_null()
            & (prior_sma != 0.0)
        )
        .then(((diff / prior_sma) * 100.0).round(4))
        .otherwise(None)
        .alias("sma_30w_slope")
    )
    return df.with_columns(slope_expr)


def compute_volume_surge(
    volumes: List[int],
    window: int = 10
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """
    Computes 10-week prior average volume (strictly EXCLUDING current week)
    and volume surge ratio: current_volume / prior_avg_volume.
    Guarded against ZeroDivisionError (returns 0.0 if prior average volume == 0).
    """
    avg_volumes: List[Optional[float]] = []
    surge_ratios: List[Optional[float]] = []

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


def compute_volume_metrics(df: pl.DataFrame, window: int = 10) -> pl.DataFrame:
    """
    Computes 10-week prior average volume (strictly excluding current week) and volume surge ratio:
    surge_ratio = current_week_volume / prior_10w_avg_volume
    Guards against zero-division (surge = 0.0 if avg_volume == 0).
    """
    group_col = "ticker" if "ticker" in df.columns else None
    if group_col:
        avg_vol_expr = (
            pl.col("volume").cast(pl.Float64).shift(1)
            .rolling_mean(window_size=window, min_periods=window)
            .round(2)
            .over(group_col)
            .alias("avg_volume_10w")
        )
    else:
        avg_vol_expr = (
            pl.col("volume").cast(pl.Float64).shift(1)
            .rolling_mean(window_size=window, min_periods=window)
            .round(2)
            .alias("avg_volume_10w")
        )

    df_with_avg = df.with_columns(avg_vol_expr)

    surge_expr = (
        pl.when(
            pl.col("avg_volume_10w").is_not_null() & (pl.col("avg_volume_10w") > 0)
        )
        .then((pl.col("volume").cast(pl.Float64) / pl.col("avg_volume_10w")).round(4))
        .when(
            pl.col("avg_volume_10w").is_not_null() & (pl.col("avg_volume_10w") == 0)
        )
        .then(0.0)
        .otherwise(None)
        .alias("volume_surge_ratio")
    )

    return df_with_avg.with_columns(surge_expr)


def compute_prior_resistance_pivot(
    highs: List[float],
    lookback: int = 35
) -> List[Optional[float]]:
    """
    Computes the maximum high over the prior `lookback` weeks (strictly EXCLUDING current week).
    Returns None for indices < lookback.
    """
    pivots: List[Optional[float]] = []
    for i in range(len(highs)):
        if i < lookback:
            pivots.append(None)
        else:
            prior_highs = highs[i - lookback : i]
            pivots.append(round(max(prior_highs), 4))
    return pivots


def compute_resistance_pivot(df: pl.DataFrame, lookback: int = 35) -> pl.DataFrame:
    """
    Computes 35-week prior resistance pivot on a Polars DataFrame:
    pivot = maximum weekly high over prior 35 weeks (strictly excluding current week breakout candle).
    """
    group_col = "ticker" if "ticker" in df.columns else None
    if group_col:
        pivot_expr = (
            pl.col("high").shift(1)
            .rolling_max(window_size=lookback, min_periods=lookback)
            .round(4)
            .over(group_col)
            .alias("prior_resistance_35w")
        )
    else:
        pivot_expr = (
            pl.col("high").shift(1)
            .rolling_max(window_size=lookback, min_periods=lookback)
            .round(4)
            .alias("prior_resistance_35w")
        )
    return df.with_columns(pivot_expr)


def _compute_mrs_list(
    stock_closes: List[float],
    spy_closes: List[float],
    lookback: int = 52,
    multiplier: float = 100.0,
) -> List[Optional[float]]:
    """
    Mansfield Relative Strength (MRS) vs SPY benchmark ETF on lists of closes:
    1. RS[t] = Stock_Close[t] / SPY_Close[t]
    2. SMA_RS[t] = 52-week rolling mean of RS
    3. MRS[t] = ((RS[t] / SMA_RS[t]) - 1.0) * multiplier
    Returns None for the first lookback - 1 bars (index 0 to 50 for 52w).
    """
    if len(stock_closes) != len(spy_closes):
        raise ValueError(
            f"Stock series length ({len(stock_closes)}) does not match "
            f"SPY benchmark length ({len(spy_closes)})."
        )

    rs_series: List[float] = []
    for s_close, spy_close in zip(stock_closes, spy_closes):
        if spy_close <= 0.0:
            rs_series.append(0.0)
        else:
            rs_series.append(s_close / spy_close)

    mrs_series: List[Optional[float]] = []
    running_rs_sum = 0.0
    for i in range(len(rs_series)):
        running_rs_sum += rs_series[i]
        if i < lookback - 1:
            mrs_series.append(None)
        elif i == lookback - 1:
            rs_sma = running_rs_sum / float(lookback)
            if rs_sma <= 0.0:
                mrs_series.append(0.0)
            else:
                mrs = ((rs_series[i] / rs_sma) - 1.0) * multiplier
                mrs_series.append(round(mrs, 4))
        else:
            running_rs_sum -= rs_series[i - lookback]
            rs_sma = running_rs_sum / float(lookback)
            if rs_sma <= 0.0:
                mrs_series.append(0.0)
            else:
                mrs = ((rs_series[i] / rs_sma) - 1.0) * multiplier
                mrs_series.append(round(mrs, 4))

    return mrs_series


def _compute_mrs_df(
    stock_df: pl.DataFrame,
    spy_df: pl.DataFrame,
    lookback: int = 52,
    multiplier: float = 100.0,
) -> pl.DataFrame:
    """
    Mansfield Relative Strength vs SPY benchmark on Polars DataFrames.
    Aligns by trade_date, computes RS, 52-week rolling average RS, and MRS score.
    """
    stock_clean = stock_df
    if stock_clean.schema["trade_date"] != pl.Date:
        stock_clean = stock_clean.with_columns(pl.col("trade_date").cast(pl.Date))

    spy_clean = spy_df.select([
        pl.col("trade_date").cast(pl.Date),
        pl.col("close").alias("spy_close")
    ])

    joined = stock_clean.join(spy_clean, on="trade_date", how="left")

    rs_expr = (
        pl.when(pl.col("spy_close").is_not_null() & (pl.col("spy_close") > 0))
        .then(pl.col("close") / pl.col("spy_close"))
        .otherwise(0.0)
        .alias("rs_ratio")
    )
    df_rs = joined.with_columns(rs_expr)

    group_col = "ticker" if "ticker" in df_rs.columns else None
    if group_col:
        rs_sma_expr = (
            pl.col("rs_ratio")
            .rolling_mean(window_size=lookback, min_periods=lookback)
            .over(group_col)
            .alias("rs_sma_52w")
        )
    else:
        rs_sma_expr = (
            pl.col("rs_ratio")
            .rolling_mean(window_size=lookback, min_periods=lookback)
            .alias("rs_sma_52w")
        )
    df_rs_sma = df_rs.with_columns(rs_sma_expr)

    mrs_expr = (
        pl.when(
            pl.col("rs_ratio").is_not_null()
            & pl.col("rs_sma_52w").is_not_null()
            & (pl.col("rs_sma_52w") > 0)
        )
        .then(
            (((pl.col("rs_ratio") / pl.col("rs_sma_52w")) - 1.0) * multiplier).round(4)
        )
        .when(
            pl.col("rs_sma_52w").is_not_null() & (pl.col("rs_sma_52w") <= 0)
        )
        .then(0.0)
        .otherwise(None)
        .alias("mrs_score")
    )

    return df_rs_sma.with_columns(mrs_expr).drop(["spy_close", "rs_ratio", "rs_sma_52w"])


def compute_mansfield_relative_strength(
    stock_data: Union[pl.DataFrame, List[float]],
    spy_data: Union[pl.DataFrame, List[float]],
    lookback: int = 52,
    multiplier: float = 100.0,
) -> Union[pl.DataFrame, List[Optional[float]]]:
    """
    Mansfield Relative Strength (MRS) vs SPY benchmark ETF.
    Supports both Polars DataFrame inputs and Python List of float closes.
    """
    if isinstance(stock_data, pl.DataFrame):
        return _compute_mrs_df(stock_data, spy_data, lookback, multiplier)
    else:
        return _compute_mrs_list(stock_data, spy_data, lookback, multiplier)


def align_weekly_bars(
    stock_bars: List[Dict[str, Any]],
    spy_bars: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Aligns target stock weekly bars and SPY benchmark bars on identical `trade_date`.
    Returns matched (aligned_stock, aligned_spy) sorted chronologically ascending.
    """
    spy_dict = {str(b["trade_date"]): b for b in spy_bars}
    aligned_stock: List[Dict[str, Any]] = []
    aligned_spy: List[Dict[str, Any]] = []

    for s in sorted(stock_bars, key=lambda x: str(x["trade_date"])):
        t_date = str(s["trade_date"])
        if t_date in spy_dict:
            aligned_stock.append(s)
            aligned_spy.append(spy_dict[t_date])

    return aligned_stock, aligned_spy


def compute_all_indicators(
    weekly_df: pl.DataFrame,
    spy_weekly_df: Optional[pl.DataFrame] = None
) -> pl.DataFrame:
    """
    Orchestrates calculation of all Stan Weinstein Stage 2 indicators on a weekly Polars DataFrame:
    1. 30-week SMA
    2. 30-week SMA Slope
    3. 10-week prior Volume Average and Surge Ratio
    4. 35-week prior Resistance Pivot
    5. Mansfield Relative Strength vs SPY (if SPY provided)
    """
    df = (
        weekly_df.sort(["ticker", "trade_date"])
        if "ticker" in weekly_df.columns
        else weekly_df.sort("trade_date")
    )
    df = compute_sma_30w(df)
    df = compute_sma_30w_slope(df, lookback=1)
    df = compute_volume_metrics(df, window=10)
    df = compute_resistance_pivot(df, lookback=35)

    if spy_weekly_df is not None and not spy_weekly_df.is_empty():
        df = _compute_mrs_df(df, spy_weekly_df, lookback=52)
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("mrs_score"))

    return df


def compute_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    window: int = 14
) -> List[Optional[float]]:
    """
    Computes Average True Range (ATR) over `window` periods on weekly OHLC lists:
    TR[0] = High[0] - Low[0]
    TR[t] = max(High[t] - Low[t], abs(High[t] - Close[t-1]), abs(Low[t] - Close[t-1]))
    ATR = rolling_mean(TR, window)
    """
    if len(highs) < window:
        return [None] * len(highs)
    tr_list: List[float] = []
    for i in range(len(highs)):
        if i == 0:
            tr = highs[i] - lows[i]
        else:
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            tr = max(hl, hc, lc)
        tr_list.append(tr)

    atr_list: List[Optional[float]] = []
    running_sum = 0.0
    for i in range(len(tr_list)):
        running_sum += tr_list[i]
        if i < window - 1:
            atr_list.append(None)
        elif i == window - 1:
            atr_list.append(round(running_sum / float(window), 4))
        else:
            running_sum -= tr_list[i - window]
            atr_list.append(round(running_sum / float(window), 4))
    return atr_list


def compute_base_tightness(
    highs: List[float],
    lows: List[float],
    lookback: int = 4
) -> List[Optional[float]]:
    """
    Computes Base Tightness percentage over prior `lookback` weeks (strictly excluding current week [t]):
    Max_High_4w = max(High[t-4 : t])
    Min_Low_4w = min(Low[t-4 : t])
    Tightness_Pct = ((Max_High_4w - Min_Low_4w) / Min_Low_4w) * 100.0
    """
    tightness: List[Optional[float]] = []
    for i in range(len(highs)):
        if i < lookback:
            tightness.append(None)
        else:
            prior_highs = highs[i - lookback : i]
            prior_lows = lows[i - lookback : i]
            min_l = min(prior_lows)
            if min_l <= 0:
                tightness.append(0.0)
            else:
                pct = ((max(prior_highs) - min_l) / min_l) * 100.0
                tightness.append(round(pct, 2))
    return tightness


def compute_market_regime(
    spy_closes: List[float],
    min_weeks: int = 35
) -> Dict[str, Any]:
    """
    Evaluates Market Regime Filter (SPY Weekly):
    - BULL_MARKET: SPY_Close >= SPY_SMA_30w and SPY_SMA_30w_Slope_4w >= 0 and SPY_Close >= SPY_SMA_10w
    - CAUTION_MARKET: SPY_Close >= SPY_SMA_30w but (SPY_SMA_30w_Slope_4w < 0 or SPY_Close < SPY_SMA_10w)
    - BEAR_MARKET: SPY_Close < SPY_SMA_30w
    """
    if len(spy_closes) < min_weeks:
        return {
            "market_regime": "BULL_MARKET",
            "spy_close": round(spy_closes[-1], 2) if spy_closes else 0.0,
            "spy_sma_30w": 0.0,
            "spy_sma_10w": 0.0,
            "spy_slope_4w": 0.0,
        }
    sma10 = compute_sma(spy_closes, window=10)
    sma30 = compute_sma(spy_closes, window=30)
    slope4 = compute_sma_slope(sma30, lookback=4)

    c = spy_closes[-1]
    s10 = sma10[-1] or c
    s30 = sma30[-1] or c
    sl4 = slope4[-1] if slope4[-1] is not None else 0.0

    if c >= s30 and sl4 >= 0.0 and c >= s10:
        regime = "BULL_MARKET"
        multiplier = 1.0
    elif c >= s30:
        regime = "CAUTION_MARKET"
        multiplier = 0.5
    else:
        regime = "BEAR_MARKET"
        multiplier = 0.0

    return {
        "market_regime": regime,
        "regime_multiplier": multiplier,
        "spy_close": round(c, 2),
        "spy_sma_30w": round(s30, 2),
        "spy_sma_10w": round(s10, 2),
        "spy_slope_4w": round(sl4, 2),
    }


def calculate_projected_volume_surge(
    current_volume: int,
    avg_vol_10w: float,
    days_elapsed: Optional[float] = None
) -> Tuple[float, float]:
    """
    Computes Projected Volume Surge (>= 1.5x of prior 10w avg volume).
    If scanning mid-week, scales up current volume to project full 5-day week:
    Scale_Factor = 5.0 / max(days_elapsed, 0.5)
    Projected_Volume = current_volume * Scale_Factor
    Returns (projected_volume, volume_surge_ratio).
    """
    if days_elapsed is None:
        # Determine based on current UTC day and time
        now = datetime.utcnow()
        weekday = now.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
        if weekday >= 5 or (weekday == 4 and now.hour >= 21):
            days_elapsed = 5.0
        else:
            days_elapsed = float(weekday + 1)

    scale_factor = 5.0 / max(days_elapsed, 0.5)
    projected_vol = float(current_volume) * scale_factor
    ratio = (projected_vol / avg_vol_10w) if avg_vol_10w > 0 else 0.0
    return round(projected_vol, 2), round(ratio, 4)


def compute_quality_score(
    mrs_score: float,
    volume_surge_ratio: float,
    diff_pct: float,
    base_tightness_pct: Optional[float] = None,
) -> Tuple[float, str]:
    """
    Computes the composite Breakout Quality Score (0-100) & Grade (A+, A, B, C).

    Base Weight Distribution (100 pts):
    1. Mansfield RS vs SPY: max 35 pts (Relative strength outperformance)
    2. Volume Surge Ratio: max 25 pts (Institutional accumulation power)
    3. Entry Distance (diff_pct): max 25 pts (Sweet spot close to breakout pivot)
    4. Base Tightness (4w): max 15 pts (Volatility contraction before breakout)

    Strict Penalty Rules:
    - Dry Volume (< 1.0x): -25 pts penalty (prevents low-volume pullbacks from earning Grade A/A+)
    - Late Entry (> +3.5%): -20 pts penalty (prevents stretched setups with wide stop loss)
    - Loose Base (> 20.0%): -10 pts penalty

    Grades:
    - 90 - 100: A+ (💎 Prime Leader)
    - 80 - 89.9: A (🟢 Strong Breakout)
    - 65 - 79.9: B (🟡 Moderate / Watch)
    - < 65:      C (⚪ Weak / Late Stage / Low Volume)

    Returns:
        (score: float, grade: str)
    """
    score: float = 0.0

    # 1. Mansfield RS (max 35 pts)
    mrs = float(mrs_score or 0.0)
    if mrs >= 30.0:
        score += 35.0
    elif mrs >= 20.0:
        score += 30.0
    elif mrs >= 10.0:
        score += 24.0
    elif mrs >= 0.0:
        score += 15.0
    else:
        score += 5.0

    # 2. Volume Surge (max 25 pts)
    vol = float(volume_surge_ratio or 0.0)
    if vol >= 2.5:
        score += 25.0
    elif vol >= 2.0:
        score += 22.0
    elif vol >= 1.5:
        score += 18.0
    elif vol >= 1.0:
        score += 10.0
    else:
        score += 0.0  # Dry volume

    # 3. Entry Price Sweet Spot (max 25 pts)
    diff = float(diff_pct or 0.0)
    if 0.0 <= diff <= 1.5:
        score += 25.0  # Perfect entry pivot sweet spot
    elif 1.5 < diff <= 2.5:
        score += 20.0
    elif 2.5 < diff <= 3.5:
        score += 12.0
    elif 3.5 < diff <= 5.0:
        score += 5.0   # Late entry
    elif -2.0 <= diff < 0.0:
        score += 15.0  # Healthy retest right below pivot
    else:
        score += 0.0   # Extended or deep drawdown

    # 4. Base Tightness (max 15 pts)
    tightness = float(base_tightness_pct) if base_tightness_pct is not None else 18.0
    if tightness <= 12.0:
        score += 15.0
    elif tightness <= 15.0:
        score += 12.0
    elif tightness <= 18.0:
        score += 9.0
    elif tightness <= 22.0:
        score += 4.0
    else:
        score += 0.0

    # Apply Strict Penalties
    if vol < 1.0:
        score -= 25.0  # Volume is dry
    if diff > 3.5:
        score -= 20.0  # Late edge of buy zone
    if tightness > 20.0:
        score -= 10.0  # Base is loose and volatile

    score = max(0.0, min(100.0, score))
    score = round(score, 1)

    if score >= 90.0:
        grade = "A+"
    elif score >= 80.0:
        grade = "A"
    elif score >= 65.0:
        grade = "B"
    else:
        grade = "C"

    return score, grade

