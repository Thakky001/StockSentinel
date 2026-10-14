## 2026-10-14T03:48:43Z

You are Worker 3 implementing Milestone 2 Iteration 3 targeted regex refinements for StockSentinel.
Working directory: d:/git/StockSentinel/.agents/teamwork/worker_m2_3
Project root: d:/git/StockSentinel
Original request path: d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md
Project plan path: d:/git/StockSentinel/PROJECT.md
Challenger handoff report: d:/git/StockSentinel/.agents/teamwork/challenger_m2_3/handoff.md

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

You MUST read d:/git/StockSentinel/.agents/teamwork/challenger_m2_3/handoff.md carefully.

Issue:
In `screener/src/universe.py:15-18`, the non-equity regexes:
```python
RE_WARRANT = re.compile(r"(\.WS|\.W|-WT|\+|=|\.WT|WS$|W$)", re.IGNORECASE)
RE_PREFERRED = re.compile(r"(\.PR|\.P|\.PF|\^|/PR|PR[A-Z]?$|-P)", re.IGNORECASE)
RE_UNIT = re.compile(r"(\.U|\.UN|-U|=U|/U|UN$)", re.IGNORECASE)
RE_RIGHT = re.compile(r"(\.RT|\.R|-RT|\+R)", re.IGNORECASE)
```
contain un-delimited suffix patterns `W$`, `UN$`, `PR[A-Z]?$` that match common stock tickers ending in W, UN, PR. This falsely rejects major S&P 500 / Russell 3000 common equities:
- `NOW` (ServiceNow), `LOW` (Lowe's), `SNOW` (Snowflake), `GLW` (Corning), `CHRW` (C.H. Robinson), `FLOW`, `W` (Wayfair)
- `RUN` (Sunrun), `FUN` (Six Flags), `HUN`, `SUN`
- `EPR` (EPR Properties), `OPRA`

Task:
1. Update `screener/src/universe.py` regex definitions so that:
   - Suffixes like `.W`, `.WS`, `.U`, `.UN`, `.P`, `.PR`, `.RT`, `.R` REQUIRE a dot delimiter (or hyphen/plus delimiter on pre-sanitized symbols), OR follow the legacy NASDAQ 5-letter ticker convention where the 5th character indicates the instrument type (`^[A-Z]{4}[WUPR]$`).
   - Bare 1- to 4-letter common stock tickers like `NOW`, `LOW`, `SNOW`, `GLW`, `CHRW`, `FLOW`, `RUN`, `FUN`, `HUN`, `SUN`, `EPR`, `OPRA`, `W` MUST return `True` for `is_common_stock()`.
   - Dual-class common equities (`BRK.B`, `BF.B`, `CWEN.A`, `JW.A`, `GOOGL`, `AAPL`) MUST return `True`.
   - Non-equities (`LCID-W`, `LCID.W`, `FOO.W`, `BAC-P`, `BAC.P`, `C-PJ`, `AACG.U`, `BAR.U`, `BAZ.R`, `TEST`, `ZVZZT`) MUST return `False`.
   - For single-letter ticker `W`, ensure it returns `True` as standard ticker `^[A-Z]{1,5}$`.
2. Update `screener/verify_m2.py`:
   - In `test_common_stock_filtering`, add assertions verifying that `NOW`, `LOW`, `SNOW`, `GLW`, `CHRW`, `RUN`, `FUN`, `EPR`, `W` all return `True`.
   - Keep all non-equity assertions returning `False`.
   - Keep all dual-class assertions returning `True`.
3. Run verification tests and document all changes in `d:/git/StockSentinel/.agents/teamwork/worker_m2_3/handoff.md`.
Maintain progress.md in your working directory. Send a message when finished.
