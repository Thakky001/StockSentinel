## 2026-10-14T03:24:54Z
You are Worker 2 implementing targeted fixes for Milestone 2 (Stock Universe & Ingestion Engine) Iteration 2 for StockSentinel.
Working directory: d:/git/StockSentinel/.agents/teamwork/worker_m2_2
Project root: d:/git/StockSentinel
Original request path: d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md
Project plan path: d:/git/StockSentinel/PROJECT.md
Review feedback path: d:/git/StockSentinel/.agents/teamwork/reviewer_m2_1/handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

You MUST read d:/git/StockSentinel/.agents/teamwork/reviewer_m2_1/handoff.md carefully. It contains the exact line numbers, code snippets, and rationale for 4 specific fixes:

1. [Critical] Fix Order of Operations & Preferred Pattern in `screener/src/universe.py`:
   - Update `RE_PREFERRED = re.compile(r"(\.PR|\.P|\.PF|\^|/PR|PR[A-Z]?$|-P)", re.IGNORECASE)` to include `\.P$` and `\.PR`.
   - Move non-equity pattern checks (`RE_WARRANT`, `RE_PREFERRED`, `RE_UNIT`, `RE_RIGHT`) ABOVE `RE_COMMON_CLASS.match(sym)`.
   - Ensure dual-class equities (`BRK.B`, `BF.B`, `CWEN.A`, `JW.A`) match `RE_COMMON_CLASS`, while warrants (`LCID.W`, `FOO.W`), units (`AACG.U`, `BAR.U`), rights (`BAZ.R`), and preferreds (`BAC.P`, `BAC-P`) return `False`.

2. [Major] Prevent Cross-Ticker Data Bleed in `screener/src/downloader.py`:
   - In `downloader.py:273-275`, when `is_multi_index` is False on multi-ticker batches (`len(chunk_tickers) > 1`), do NOT assign `sub_df = df`. Instead, trigger single-ticker fallback `download_single_ticker(ticker, start_date, end_date, max_retries=1)` for each ticker.

3. [Major] Deduplicate Bars in `screener/src/db.py` to Prevent Cardinality Violations:
   - In `db.py:125-147`, deduplicate `bars_list` by `(b["ticker"], b["trade_date"])` keeping the latest record before creating `values` for `execute_values`.

4. [Minor] Ensure Custom Tickers Exist in `stocks` in `screener/src/sync.py`:
   - In `sync.py`, auto-upsert minimal stock records into `stocks` with `ON CONFLICT (ticker) DO NOTHING` for all tickers in `canonical_tickers` before fetching bars.

5. Update `screener/verify_m2.py`:
   - Add explicit unit tests verifying each of the 4 fixes:
     - `is_common_stock("LCID-W") == False`
     - `is_common_stock("FOO.W") == False`
     - `is_common_stock("BAC-P") == False`
     - `is_common_stock("AACG.U") == False`
     - `is_common_stock("BRK.B") == True`
     - `is_common_stock("BF.B") == True`
     - Batch upserting duplicate `(ticker, trade_date)` rows in `db.upsert_daily_bars` succeeds without throwing `cardinality_violation`.
   - Run `python screener/verify_m2.py` and any affected E2E tests.

Document all changes, tests, and verification outputs in `d:/git/StockSentinel/.agents/teamwork/worker_m2_2/handoff.md`.
Maintain progress.md in your working directory. Send a message when finished.
