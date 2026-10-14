## 2026-10-14T04:47:20Z
You are Worker 2 implementing Milestone 3 Iteration 2 targeted fixes for StockSentinel.
Working directory: d:/git/StockSentinel/.agents/teamwork/worker_m3_2
Project root: d:/git/StockSentinel
Original request path: d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md
Project plan path: d:/git/StockSentinel/PROJECT.md
Review feedback path: d:/git/StockSentinel/.agents/teamwork/reviewer_m3_1/handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

EXCLUSIVE WRITE OWNERSHIP:
You own exclusively:
- `screener/src/indicators.py`
- `screener/verify_m3.py`

MISSION:
You MUST read `d:/git/StockSentinel/.agents/teamwork/reviewer_m3_1/handoff.md` carefully. It specifies the exact line numbers, code snippets, and rationale for 2 targeted fixes:

1. [Critical] Fix Nested Polars Window Functions in `screener/src/indicators.py`:
   - In `compute_volume_metrics` (lines 285–300):
     Polars explicitly disallows nested window functions (`ComputeError: nested window functions are not supported`). Currently, `prior_vol` has `.over(group_col)` and then `avg_vol_expr` applies `.over(group_col)` again.
     Fix: Remove the inner `.over(group_col)` from `prior_vol`:
     ```python
     if group_col:
         avg_vol_expr = (
             pl.col("volume").cast(pl.Float64).shift(1)
             .rolling_mean(window_size=window, min_periods=window)
             .round(2)
             .over(group_col)
             .alias("avg_volume_10w")
         )
     ```
   - In `compute_resistance_pivot` (lines 343–351):
     Currently, `prior_high` has `.over(group_col)` and then `pivot_expr` applies `.over(group_col)` again.
     Fix: Remove the inner `.over(group_col)` from `prior_high`:
     ```python
     if group_col:
         pivot_expr = (
             pl.col("high").shift(1)
             .rolling_max(window_size=lookback, min_periods=lookback)
             .round(4)
             .over(group_col)
             .alias("prior_resistance_35w")
         )
     ```
   - Ensure `compute_all_indicators(weekly_df, spy_weekly_df)` executes without `ComputeError` when `weekly_df` has multiple tickers.

2. [Major] Expand Unit Test Coverage in `screener/verify_m3.py`:
   - Add explicit unit tests for multi-ticker Polars DataFrames (e.g. passing a DataFrame with "AAPL" and "MSFT" to `compute_volume_metrics`, `compute_resistance_pivot`, and `compute_all_indicators`).
   - Verify that no `ComputeError` is raised and that metrics are computed independently per ticker.
   - Run verification tests (`python screener/verify_m3.py`, `python tests/run_e2e.py --feature 12` through `20`).

Document all changes, tests, and verification outputs in `d:/git/StockSentinel/.agents/teamwork/worker_m3_2/handoff.md`.
Maintain progress.md in your working directory. Send a message when finished.
