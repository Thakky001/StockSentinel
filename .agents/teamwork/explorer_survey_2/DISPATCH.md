## 2026-10-14T02:16:16Z
Sender: 3d48cac3-5040-4cf3-9886-4e4f2c9223a4
Message:
You are Explorer 2 surveying the project scope for StockSentinel.
Working directory: d:/git/StockSentinel/.agents/teamwork/explorer_survey_2
Project root: d:/git/StockSentinel
Original request path: d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md

You MUST read d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md first.

Your primary focus:
1. Requirement 3 (R3 - Core Screener Engine & Indicator Math):
   - Resampling daily bars to weekly bars with Polars (Friday close convention, volume sum, high max, low min).
   - Computing 30-week SMA, SMA slope (% or derivative over N weeks), 10-week volume average, 35-week resistance pivot.
   - Mansfield Relative Strength (MRS) calculation vs SPY: formula definition (RS = (Stock / SPY) / SMA_52w(Stock / SPY) - 1) * 10 or standard Mansfield formula, zero-line crossover / MRS > 0.
   - Stage 2 Breakout filters: Close > SMA 30w, SMA 30w sloping up, Close >= prior 30w-35w high, Volume >= 1.5x average (volume surge), MRS > 0.
   - Entry price computation (pivot high), Max Buy Price (+5%), Current Price comparison, % distance, and Entry Status (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`).
   - Upserting to `screener_signals` table and logging execution to `scan_jobs`.
2. Requirement 4 (R4 - Telegram Alerting System):
   - Formatted weekly alert via Telegram Bot API when scan finishes.
   - Content: ticker, entry pivot, current price, distance %, status badge, stop loss, volume surge, MRS score, web app link.
   - Chunked messaging handling Telegram's 4,096 character limit cleanly without cutting off Markdown/HTML tags or items.
   - Environment variables (BOT_TOKEN, CHAT_ID), error handling when unconfigured or network issues occur.

Enumerate all required features, mathematical formulas, data contracts, edge cases, test strategies, and acceptance verification criteria.
Write your complete findings and handoff report to `d:/git/StockSentinel/.agents/teamwork/explorer_survey_2/handoff.md`.
Maintain `progress.md` in your directory.
Send a message when finished referencing your handoff file.
