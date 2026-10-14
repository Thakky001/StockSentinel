## 2026-10-14T04:37:37Z
You are Challenger 2 for Milestone 3 (Core Screener Engine & Indicator Math) of StockSentinel.
Working directory: d:/git/StockSentinel/.agents/teamwork/challenger_m3_2
Project root: d:/git/StockSentinel
Original request path: d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md
Project plan path: d:/git/StockSentinel/PROJECT.md
Worker handoff path: d:/git/StockSentinel/.agents/teamwork/worker_m3_1/handoff.md
Test suite references:
- tests/e2e/tier2_boundaries/test_t2_indicators_boundaries.py
- tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py
- tests/e2e/tier4_scenarios/test_t4_weekly_delta_breakout_flow.py

You MUST read ORIGINAL_REQUEST.md, PROJECT.md, and the worker handoff report first.

Mission:
Adversarially stress-test Stage 2 breakout filter, target/risk boundaries, and database persistence:
1. Test Stage 2 multi-factor combinations: verify that 4 passing conditions and 1 failing condition (e.g., volume surge = 1.49x, or MRS = -0.01, or slope = -0.0001%, or close = pivot - 0.01) evaluates to `is_stage2 = False`. All 5 must be True simultaneously.
2. Test target and risk edge cases:
   - Fractional cents pivot values round to 4 decimals.
   - Max buy price is strictly +5% of entry price (`entry_price * 1.05`).
   - Stop loss fallback: invalid swing lows (e.g. >= entry price, or <= 0) fall back to -8% default stop (`entry_price * 0.92`).
3. Test entry status boundary transitions:
   - `price == stop_loss` must be `BELOW_ENTRY` (`STOPPED_OUT` is strictly `price < stop_loss`).
   - `price == stop_loss - 0.01` must be `STOPPED_OUT`.
   - `price == entry_price` must be `IN_BUY_ZONE`.
   - `price == max_buy_price` must be `IN_BUY_ZONE`.
   - `price == max_buy_price + 0.01` must be `EXTENDED`.
4. Test database upsert idempotency and cardinality safety:
   - Pass duplicate `(scan_date, ticker)` entries within a single signal batch to `upsert_screener_signals`. Verify in-batch deduplication succeeds without triggering PostgreSQL Error 21000.
   - Verify CHECK constraint compliance (`entry_price > 0`, `current_price > 0`, valid status enum).
5. Run tests:
   `python screener/verify_m3.py`
   `python -m unittest tests/e2e/tier3_interactions/test_t3_ingest_to_screener.py`
   `python -m unittest tests/e2e/tier4_scenarios/test_t4_weekly_delta_breakout_flow.py`

Record your full findings and verdict (`APPROVE` or `REQUEST_CHANGES`) in `d:/git/StockSentinel/.agents/teamwork/challenger_m3_2/handoff.md`.
Maintain progress.md in your working directory. Send a message when finished.
