# Task Assignment — Explorer M3 1
Explore Polars daily-to-weekly resampling, 30w SMA, slope, 10w volume, and 35w resistance pivot.
## 2026-10-14T04:14:04Z
You are Explorer 1 for Milestone 3 (Core Screener Engine & Indicator Math) of StockSentinel.
Working directory: d:/git/StockSentinel/.agents/teamwork/explorer_m3_1
Project root: d:/git/StockSentinel
Original request path: d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md
Project plan path: d:/git/StockSentinel/PROJECT.md
Test suite references: d:/git/StockSentinel/tests/e2e/tier1_features/test_f12_f16_indicators.py and tests/e2e/tier2_boundaries/test_t2_screener_math_boundaries.py

You MUST read ORIGINAL_REQUEST.md, PROJECT.md, and the test suite references first.

Your primary focus:
1. Resampling Daily to Weekly in Polars:
   - Aggregation from daily OHLCV bars (`trade_date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`).
   - Grouping by calendar week (Monday to Friday bounds, ISO year and week, or Friday-ending week convention).
   - Rules: `week_open` = first trading day open; `week_high` = max of high; `week_low` = min of low; `week_close` = last available trading day close; `week_adj_close` = last available adj_close; `week_volume` = sum of volume; `trade_date` = date of the Friday ending the week.
   - Clean handling of short holiday weeks (e.g. 4-day weeks like Good Friday or Thanksgiving).
2. Indicator Mathematics in Polars (`screener/src/indicators.py`):
   - 30-Week SMA: rolling mean of `week_close` over 30 weeks.
   - 30-Week SMA Slope: formula specification (momentum `SMA30[t] - SMA30[t-1]`, percentage slope `(SMA30[t] - SMA30[t-1]) / SMA30[t-1] * 100`, or 4-week slope). Condition `slope >= 0`.
   - 10-Week Prior Volume Average: rolling mean of volume over the 10 weeks *prior* to the current breakout week (excluding current week to prevent diluting the denominator).
   - Volume Surge Ratio: `current_week_volume / prior_10w_avg_volume`. Condition `>= 1.5x`.
   - 35-Week Prior Resistance Pivot: rolling maximum of `week_high` over the 35 weeks *prior* to the current candle (excluding current breakout high). Condition `current_close >= pivot_35w`.
3. Architecture & Code Blueprints:
   - Provide concrete, vector-optimized Polars implementation blueprints with verified function signatures, types, null handling, and minimum historical bar checks (require at least 52 weekly bars for full indicator warmup).

Do NOT modify or write source code directly. Write your comprehensive analysis and handoff report to `d:/git/StockSentinel/.agents/teamwork/explorer_m3_1/handoff.md`.
Maintain progress.md in your working directory. Send a message when finished.
