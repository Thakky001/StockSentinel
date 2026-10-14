# Handoff Report: Independent Review & Adversarial Stress-Test of Milestone 2

**Author:** Reviewer 1 (`reviewer_m2_1`)  
**Recipient:** Orchestrator (`3d48cac3-5040-4cf3-9886-4e4f2c9223a4`)  
**Project:** StockSentinel  
**Working Directory:** `d:/git/StockSentinel/.agents/teamwork/reviewer_m2_1`  
**Review Target:** Milestone 2 (Stock Universe & Ingestion Engine)  
**Date:** 2026-10-14  

---

## Review Summary

**Verdict: REQUEST_CHANGES**

**Integrity Audit:** **PASS** (Zero integrity violations. No hardcoded test fixtures, facade implementations, or shortcuts detected. Implementation is 100% genuine and built from scratch).

However, rigorous adversarial code analysis and edge-case stress-testing revealed **two critical/major correctness defects** that threaten data integrity:
1. **Critical:** In `screener/src/universe.py`, `RE_COMMON_CLASS` is evaluated *before* warrant, unit, preferred, and right regexes. As a result, any single-letter warrant (`.W`), unit (`.U`), right (`.R`), or preferred share (`.P`) without a descriptive name string bypasses non-equity filtering and is classified as common stock.
2. **Major:** In `screener/src/downloader.py`, if a multi-ticker download returns a single-level column `pd.DataFrame` (when some tickers fail), `sub_df = df` is erroneously assigned to every ticker in the batch, copying one stock's OHLCV bars across unrelated tickers (cross-ticker data bleed).
3. **Major:** In `screener/src/db.py`, `upsert_daily_bars` does not deduplicate input rows by `(ticker, trade_date)`. If duplicate dates occur in a batch, PostgreSQL aborts with `cardinality_violation: ON CONFLICT DO UPDATE command cannot affect row a second time`.
4. **Minor:** In `screener/src/sync.py`, custom tickers passed via `--tickers` are not pre-seeded into `stocks`, risking foreign key constraint failures in PostgreSQL `stock_daily_bars`.

---

## 1. Observation

### 1.1 Deliverables Inspected
Direct source inspection of the 11 Milestone 2 files in `d:/git/StockSentinel/`:
- `screener/requirements.txt` (24 lines)
- `screener/pyproject.toml` (35 lines)
- `screener/data/universe/russell3000_sp1500.json` (1576 lines, 121 representative anchor stocks)
- `screener/data/universe/generate_universe.py` (182 lines, auxiliary generator for up to 3,500 tickers)
- `screener/src/config.py` (53 lines)
- `screener/src/db.py` (164 lines)
- `screener/src/universe.py` (221 lines)
- `screener/src/downloader.py` (365 lines)
- `screener/src/parquet_cache.py` (130 lines)
- `screener/src/sync.py` (167 lines)
- `screener/src/main.py` (115 lines)
- `screener/verify_m2.py` (280 lines)

### 1.2 Specific Code Observations
1. **`screener/src/universe.py:83-96`**:
```python
    # Match valid dual-class common equities: e.g. BRK.B, BF.B, CWEN.A, JW.A
    if RE_COMMON_CLASS.match(sym):
        return True

    # Exclude non-common instruments by ticker pattern
    if RE_WARRANT.search(sym):
        return False
    if RE_PREFERRED.search(sym):
        return False
    if RE_UNIT.search(sym):
        return False
    if RE_RIGHT.search(sym):
        return False
```
`RE_COMMON_CLASS` is defined as `re.compile(r"^[A-Z]{1,5}\.[A-Z]$")`.
`RE_WARRANT` is defined as `re.compile(r"(\.WS|\.W|-WT|\+|=|\.WT|WS$|W$)", re.IGNORECASE)`.
`RE_UNIT` is defined as `re.compile(r"(\.U|\.UN|-U|=U|/U|UN$)", re.IGNORECASE)`.

2. **`screener/src/universe.py:16` & `universe.py:34`**:
`RE_PREFERRED` includes `-P` and `/PR`.
`sanitize_ticker` performs `cleaned = cleaned.replace("-", ".").replace("/", ".")`.
Therefore, `sym` never contains `-` or `/`. For example, `BAC-P` becomes `BAC.P`, which matches `RE_COMMON_CLASS` and never matches `-P`.

3. **`screener/src/downloader.py:263-275`**:
```python
        is_multi_index = isinstance(df.columns, pd.MultiIndex)
        for ticker in chunk_tickers:
            yf_sym = to_yfinance_symbol(ticker)
            try:
                sub_df = None
                if is_multi_index:
                    if yf_sym in df.columns.levels[0]:
                        sub_df = df[yf_sym]
                    elif len(df.columns.levels) > 1 and yf_sym in df.columns.levels[1]:
                        sub_df = df.xs(yf_sym, axis=1, level=1)
                else:
                    sub_df = df
```
When `len(chunk_tickers) > 1` and `is_multi_index` is `False`, `sub_df` is set to `df` for every ticker in `chunk_tickers`.

4. **`screener/src/db.py:125-147`**:
```python
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
        for b in bars_list
    ]

    if cur:
        for i in range(0, len(values), chunk_size):
            execute_values(cur, sql, values[i : i + chunk_size], page_size=chunk_size)
```
`values` is partitioned into chunks of 1000 and passed to `execute_values` with `ON CONFLICT (ticker, trade_date) DO UPDATE` without deduplication by `(ticker, trade_date)`.

5. **`screener/src/sync.py:58-99`**:
`universe.sync_universe_to_db()` syncs `load_universe_seed()`. If a user passes `--tickers TSLA,NVDA,CUSTOM` where `CUSTOM` is not in the seed file, `CUSTOM` is omitted from `stocks`, but its bars are sent to `db.upsert_daily_bars`, triggering `ForeignKeyViolation` in PostgreSQL.

---

## 2. Logic Chain

1. **Integrity Assessment**:
   - Every file was examined for artificial assertions, mock bypasses, or hardcoded return values.
   - All modules (`universe.py`, `downloader.py`, `parquet_cache.py`, `db.py`, `sync.py`) contain real logic, real API calls, genuine database syntax, and authentic file operations.
   - **Conclusion:** No integrity violations.

2. **Analysis of Finding 1 (Warrants & Units Bypassing Filtering)**:
   - Observation 1.2.1 shows `if RE_COMMON_CLASS.match(sym): return True` at line 84.
   - Attack input: `LCID.W` (warrant). `sym = "LCID.W"`.
   - `RE_COMMON_CLASS` matches `^[A-Z]{1,5}\.[A-Z]$` because `"LCID"` is 4 letters and `"W"` is 1 letter.
   - The method immediately returns `True` at line 85, never reaching `RE_WARRANT.search(sym)` at line 88.
   - Attack input: `AACG.U` (unit). `sym = "AACG.U"`. `RE_COMMON_CLASS` matches and returns `True`, never reaching `RE_UNIT.search(sym)` at line 92.
   - Attack input: `BAC-P` (preferred). `sanitize_ticker` turns it into `BAC.P`. `RE_COMMON_CLASS` matches and returns `True`, never reaching `RE_PREFERRED.search(sym)` at line 90.
   - **Conclusion:** Reversing the order of evaluation (checking `RE_WARRANT`, `RE_PREFERRED`, `RE_UNIT`, `RE_RIGHT` *first*, and only falling back to `RE_COMMON_CLASS` if none of them match) is required.

3. **Analysis of Finding 2 (Multi-ticker Fallback Data Bleed)**:
   - Observation 1.2.3 shows that if `df.columns` is not a MultiIndex, line 274 executes `else: sub_df = df`.
   - When yfinance downloads multiple tickers and only 1 ticker is valid or returned, yfinance flattens columns to a single index (`Open, High, Low, Close, Adj Close, Volume`).
   - The loop over `chunk_tickers` will assign the same single-stock DataFrame to every ticker in `chunk_tickers`.
   - Each ticker will then have bars extracted and saved under its name (`_extract_bars_from_single_df(sub_df, ticker)`), polluting the parquet cache and database with invalid price data.
   - **Conclusion:** When `len(chunk_tickers) > 1` and `not is_multi_index`, the downloader must treat the batch as ambiguous and invoke `download_single_ticker` for each ticker.

4. **Analysis of Finding 3 (PostgreSQL Batch Upsert Cardinality Violation)**:
   - PostgreSQL `INSERT ... ON CONFLICT (k1, k2) DO UPDATE` raises error 21000 (`cardinality_violation: ON CONFLICT DO UPDATE command cannot affect row a second time`) if the input data within a single statement contains duplicate `(k1, k2)` keys.
   - If incoming bars for a ticker have duplicate dates, or if a batch contains overlapping slices, `execute_values` will abort and roll back all 1,000 rows.
   - **Conclusion:** Deduplicating `values` by `(ticker, trade_date)` before passing to `execute_values` guarantees idempotency and transaction stability.

5. **Analysis of Finding 4 (Foreign Key Safety for Ad-Hoc Tickers)**:
   - `stock_daily_bars` has a foreign key `REFERENCES stocks(ticker)`.
   - Ad-hoc CLI executions (`--tickers FOO,BAR`) will fail if `FOO` or `BAR` is not already in `stocks`.
   - **Conclusion:** In `sync.py`, auto-upserting missing tickers into `stocks` before downloading bars prevents foreign key rollbacks.

---

## 3. Caveats

1. **Offline Test Execution**: In environments where live internet or PostgreSQL Docker containers are offline, `verify_m2.py` and local Parquet caching verify logic without network dependencies.
2. **Yahoo Finance Upstream Flakiness**: The two-tier retry architecture (batch retry + single-ticker fallback) is well designed; addressing Finding 2 will make it completely bulletproof.
3. No other caveats.

---

## 4. Conclusion & Actionable Findings

### Verdict: REQUEST_CHANGES

### Required Changes for Worker 1:

#### 1. [Critical] Fix Order of Operations & Preferred Suffix in `screener/src/universe.py`
- **Location:** `screener/src/universe.py:16, 83-96`
- **Action:**
  - Update `RE_PREFERRED` to also catch `\.P$` and `\.PR`:
    ```python
    RE_PREFERRED = re.compile(r"(\.PR|\.P|\.PF|\^|/PR|PR[A-Z]?$|-P)", re.IGNORECASE)
    ```
  - Move the non-equity pattern checks (`RE_WARRANT`, `RE_PREFERRED`, `RE_UNIT`, `RE_RIGHT`) **above** `RE_COMMON_CLASS.match(sym)`:
    ```python
    # Exclude non-common instruments by ticker pattern first
    if RE_WARRANT.search(sym):
        return False
    if RE_PREFERRED.search(sym):
        return False
    if RE_UNIT.search(sym):
        return False
    if RE_RIGHT.search(sym):
        return False

    # Match valid dual-class common equities: e.g. BRK.B, BF.B, CWEN.A, JW.A
    if RE_COMMON_CLASS.match(sym):
        return True
    ```

#### 2. [Major] Prevent Cross-Ticker Data Bleed in `screener/src/downloader.py`
- **Location:** `screener/src/downloader.py:273-275`
- **Action:**
  - When `is_multi_index` is False in a multi-ticker batch (`len(chunk_tickers) > 1`), do NOT assign `sub_df = df`. Instead, trigger single-ticker fallback for each ticker:
    ```python
    if is_multi_index:
        if yf_sym in df.columns.levels[0]:
            sub_df = df[yf_sym]
        elif len(df.columns.levels) > 1 and yf_sym in df.columns.levels[1]:
            sub_df = df.xs(yf_sym, axis=1, level=1)
    else:
        # Multi-ticker batch returned single-level DataFrame: ambiguous attribution
        logger.debug(f"Batch returned single-level DataFrame; isolating {ticker} via single download.")
        res = download_single_ticker(ticker, start_date, end_date, max_retries=1)
        results[ticker] = res["bars"]
        continue
    ```

#### 3. [Major] Deduplicate Bars in `screener/src/db.py` to Prevent Cardinality Violations
- **Location:** `screener/src/db.py:125-138`
- **Action:**
  - Deduplicate `bars_list` by `(b["ticker"], b["trade_date"])` keeping the latest record before creating `values`:
    ```python
    deduped_bars: Dict[tuple, Dict[str, Any]] = {}
    for b in bars_list:
        deduped_bars[(b["ticker"], b["trade_date"])] = b
    ```

#### 4. [Minor] Ensure Custom Tickers Exist in `stocks` in `screener/src/sync.py`
- **Location:** `screener/src/sync.py:70-76`
- **Action:**
  - Deduplicate `canonical_tickers = list(dict.fromkeys(canonical_tickers))`
  - Auto-upsert minimal stock records into `stocks` table for all `canonical_tickers` with `ON CONFLICT (ticker) DO NOTHING`.

---

## 5. Verification Method

Once Worker 1 applies these targeted fixes:
1. Run `python screener/verify_m2.py`
2. Add explicit unit tests in `screener/verify_m2.py` verifying:
   - `is_common_stock("LCID-W") == False`
   - `is_common_stock("FOO.W") == False`
   - `is_common_stock("BAC-P") == False`
   - `is_common_stock("AACG.U") == False`
   - `is_common_stock("BRK.B") == True`
   - `is_common_stock("BF.B") == True`
   - Batch upserting duplicate `(ticker, trade_date)` rows in `db.upsert_daily_bars` succeeds without throwing `cardinality_violation`.
3. Run Tier 1 and Tier 2 E2E suites:
   - `python tests/run_e2e.py --feature 7`
   - `python tests/run_e2e.py --feature 8`
   - `python tests/run_e2e.py --feature 11`
   - `python tests/run_e2e.py --tier 2`
