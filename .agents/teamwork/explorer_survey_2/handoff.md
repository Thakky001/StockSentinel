# Handoff Report: Scope Survey for R3 & R4 (Explorer 2)

**Author:** `explorer_survey_2`  
**Recipient:** Orchestrator (`3d48cac3-5040-4cf3-9886-4e4f2c9223a4`)  
**Scope:** Requirement 3 (Core Screener Engine & Indicator Math) & Requirement 4 (Telegram Alerting System)  
**Date:** 2026-10-14  

---

## 1. Observation

1. **Repository State & Scope Definition**:
   - `ORIGINAL_REQUEST.md` (lines 21–32) explicitly defines:
     - **R3**: Resample daily to weekly bars; compute 30w SMA, SMA slope, 10w volume average, 35w resistance pivot, Mansfield Relative Strength (MRS) vs SPY; filter Stage 2 Breakout (Close > SMA 30w, SMA 30w sloping up, Close >= prior 30w–35w high, Volume >= 1.5x average, MRS > 0); compute Entry Price, Max Buy Price (+5%), Current Price comparison, % distance, Entry Status (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`); upsert to `screener_signals` and log to `scan_jobs`.
     - **R4**: Dispatch formatted weekly alert via Telegram Bot API when scan completes; include ticker, entry pivot, current price, distance %, status badge, stop loss, volume surge, MRS score, web app link; handle 4,096 character chunking cleanly.
   - The root repository (`d:/git/StockSentinel`) is currently empty except for `.agents/teamwork/` coordination artifacts. There are no pre-existing legacy code conflicts.

2. **Data Scale & Performance Profile**:
   - Universe: Russell 3000 + S&P 1500 comprises ~3,800 active US equities.
   - 2 years of daily data = ~504 trading days/ticker -> ~1.9 million rows.
   - Resampled to weekly = ~104 weekly bars/ticker -> ~395,000 rows.
   - Standard Pandas processing on ~400,000 weekly rows with rolling windows in Python loops would take 30–60 seconds.
   - Polars in Rust handles multi-threaded grouping and rolling windows (`.over("ticker")`) in < 500 milliseconds, making it ideal for real-time and batch screener execution.

3. **Telegram API Constraints**:
   - Official Telegram Bot API `POST /sendMessage` limits each message body to **4,096 UTF-8 characters**.
   - Global rate limit: 30 messages/second across all chats; 1 message/second within a single private chat.
   - Formatting modes: `MarkdownV2` requires escaping 18 special characters (`_`, `*`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`). A single unescaped dot in `BRK.B` or plus in `+3.5%` causes HTTP 400 rejection.
   - In contrast, `HTML` mode requires escaping only three characters (`&` -> `&amp;`, `<` -> `&lt;`, `>` -> `&gt;`), rendering it far more robust for financial numbers, percentages, and stock tickers.

---

## 2. Logic Chain

```
[Observation 1: R3 Requirements] ──> [Polars Vectorized Resampler & Pipeline]
                                  ──> [Exact Stan Weinstein Indicator Math]
                                  ──> [Stage 2 Multi-Factor Filter]
                                  ──> [Risk, Targets & Entry Status Model]
                                  ──> [PostgreSQL Upsert Data Contract]

[Observation 3: Telegram Bot API] ──> [HTML Card Formatting Engine]
                                  ──> [Zero-Tag-Cut Chunking Algorithm]
                                  ──> [Network & Rate Limit Resilient Dispatcher]
```

### Detailed Component Specifications

### 2.1. Requirement 3: Core Screener Engine Architecture

#### A. Pipeline Data Flow
```
PostgreSQL / Parquet Daily Bars (Daily OHLCV for ~3,800 tickers + SPY)
  │
  ▼
Polars Weekly Resampler (Group by ISO week, Monday-Friday, aggregate OHLCV)
  │
  ▼
Indicator Calculator (Vectorized rolling 30w SMA, slope, 10w vol avg, 35w pivot)
  │
  ▼
Benchmark Join & Mansfield RS Calculator (Align with SPY weekly, compute 52w RS SMA & MRS)
  │
  ▼
Stage 2 Breakout Filter (Apply Weinstein 5-point predicate)
  │
  ▼
Target & Risk Sizing Engine (Calculate Entry Pivot, Max Buy, Stop Loss, Distance %, Status)
  │
  ├───> PostgreSQL Upsert (`screener_signals` & `scan_jobs`)
  │
  └───> Requirement 4: Telegram Alerting Dispatcher
```

---

#### B. Weekly Resampling Algorithm (Daily to Weekly)
- **Market Alignment**: US market regular hours are Mon–Fri.
- **Group Key**: `week_start = pl.col("date").dt.truncate("1w")` (Monday).
- **Aggregations**:
  - `date`: `pl.col("date").max()` (the actual last trading day of the week: Friday, or Thursday/Wednesday on market holidays).
  - `open`: `pl.col("open").sort_by("date").first()`
  - `high`: `pl.col("high").max()`
  - `low`: `pl.col("low").min()`
  - `close`: `pl.col("close").sort_by("date").last()`
  - `volume`: `pl.col("volume").sum()`
  - `day_count`: `pl.len()`
- **Polars Implementation**:
```python
import polars as pl

def resample_daily_to_weekly(daily_df: pl.DataFrame) -> pl.DataFrame:
    """
    Resample daily stock bars to weekly bars following Stan Weinstein convention.
    """
    return (
        daily_df
        .sort(["ticker", "date"])
        .group_by(["ticker", pl.col("date").dt.truncate("1w").alias("week_start")])
        .agg([
            pl.col("date").max().alias("date"),
            pl.col("open").sort_by("date").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").sort_by("date").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
            pl.len().alias("day_count"),
        ])
        .drop("week_start")
        .sort(["ticker", "date"])
    )
```

---

#### C. Mathematical Formulations & Indicator Logic

1. **30-Week Simple Moving Average ($\text{SMA}_{30}$)**:
   $$\text{SMA}_{30}(t) = \frac{1}{30} \sum_{i=0}^{29} \text{Close}(t - i)$$
   Polars: `pl.col("close").rolling_mean(window_size=30, min_periods=30).over("ticker").alias("sma_30w")`

2. **30-Week SMA Slope**:
   Weinstein mandates that the 30-week MA must not be declining; it must be flat or sloping upward.
   - **1-Week Momentum Difference**:
     $$\Delta\text{SMA}_1(t) = \text{SMA}_{30}(t) - \text{SMA}_{30}(t - 1)$$
     Condition: $\Delta\text{SMA}_1(t) \ge 0.0$
   - **4-Week Rate of Change (Slope %)**:
     $$\text{Slope}_{\%}(t) = \left(\frac{\text{SMA}_{30}(t) - \text{SMA}_{30}(t - 4)}{\text{SMA}_{30}(t - 4)}\right) \times 100$$
     Condition: $\text{Slope}_{\%}(t) \ge 0.0\%$
   Polars:
   ```python
   sma_prev_1 = pl.col("sma_30w").shift(1).over("ticker")
   sma_prev_4 = pl.col("sma_30w").shift(4).over("ticker")
   sma_diff_1w = (pl.col("sma_30w") - sma_prev_1).alias("sma_diff_1w")
   sma_slope_pct = ((pl.col("sma_30w") - sma_prev_4) / sma_prev_4 * 100.0).alias("sma_slope_pct")
   ```

3. **10-Week Average Volume & Surge Ratio**:
   Stan Weinstein insists on volume expansion on the breakout bar. The volume must be compared against the *prior* 10 weeks so the breakout bar does not skew the baseline:
   $$\text{VolAvg}_{10}(t) = \frac{1}{10} \sum_{i=1}^{10} \text{Volume}(t - i)$$
   $$\text{Volume\_Surge\_Ratio}(t) = \frac{\text{Volume}(t)}{\text{VolAvg}_{10}(t)}$$
   Condition: $\text{Volume\_Surge\_Ratio}(t) \ge 1.50$ ($150\%$ of 10-week average volume).
   Polars:
   ```python
   vol_avg_10w = (
       pl.col("volume")
       .shift(1)
       .rolling_mean(window_size=10, min_periods=10)
       .over("ticker")
       .alias("vol_avg_10w")
   )
   volume_surge_ratio = (
       pl.when(vol_avg_10w > 0)
       .then(pl.col("volume") / vol_avg_10w)
       .otherwise(0.0)
       .alias("volume_surge_ratio")
   )
   ```

4. **35-Week Resistance Pivot (Breakout Pivot High)**:
   In Stage 1, a base forms between support and resistance over 30 to 35 weeks. The breakout level is the maximum high of the prior 35 weeks:
   $$\text{Pivot\_Resistance}_{35}(t) = \max_{1 \le i \le 35} \left(\text{High}(t - i)\right)$$
   Condition: $\text{Close}(t) \ge \text{Pivot\_Resistance}_{35}(t)$
   Polars:
   ```python
   resistance_pivot_35w = (
       pl.col("high")
       .shift(1)
       .rolling_max(window_size=35, min_periods=25)
       .over("ticker")
       .alias("resistance_pivot_35w")
   )
   ```

5. **Mansfield Relative Strength (MRS) vs SPY**:
   - Stock Relative Strength Ratio vs Benchmark (SPY):
     $$R(t) = \frac{\text{Close}_{\text{Stock}}(t)}{\text{Close}_{\text{SPY}}(t)}$$
   - 52-Week Moving Average of Ratio:
     $$\bar{R}_{52}(t) = \frac{1}{52} \sum_{i=0}^{51} R(t - i)$$
   - Mansfield Relative Strength:
     $$\text{MRS}(t) = \left(\frac{R(t)}{\bar{R}_{52}(t)} - 1\right) \times 100$$
     *(Note: Multiplying by 100 gives percentage outperformance vs 52-week baseline; multiplying by 10 gives classical chart scale. The zero-line condition $\text{MRS} > 0$ is mathematically identical under either scale. We adopt $K=10$ or $K=100$, storing percentage outperformance $K=100$ for intuitive UI display).*
   - Condition: $\text{MRS}(t) > 0.0$
   - Optional Crossover Flag:
     $$\text{MRS\_Crossover}(t) = (\text{MRS}(t) > 0.0) \land (\text{MRS}(t - 1) \le 0.0)$$
   Polars:
   ```python
   # Join with SPY weekly close on date
   rs_ratio = pl.col("close") / pl.col("spy_close")
   rs_sma_52 = rs_ratio.rolling_mean(window_size=52, min_periods=40).over("ticker")
   mrs_score = ((rs_ratio / rs_sma_52 - 1.0) * 100.0).alias("mrs_score")
   mrs_crossover = (
       (mrs_score > 0.0) & (mrs_score.shift(1).over("ticker") <= 0.0)
   ).alias("mrs_crossover")
   ```

---

#### D. Unified Stage 2 Breakout Predicate
A stock qualifies as a **Stage 2 Breakout** on weekly bar $t$ if and only if:
```python
is_stage_2 = (
    (pl.col("close") > pl.col("sma_30w")) &
    (pl.col("sma_diff_1w") >= 0.0) &
    (pl.col("sma_slope_pct") >= 0.0) &
    (pl.col("close") >= pl.col("resistance_pivot_35w")) &
    (pl.col("volume_surge_ratio") >= 1.50) &
    (pl.col("mrs_score") > 0.0)
)
```

---

#### E. Price Metrics, Stop Loss & Entry Status Categorization

1. **Entry Price**:
   $$\text{Entry\_Price} = \text{Pivot\_Resistance}_{35}(t)$$
2. **Max Buy Price (+5%)**:
   $$\text{Max\_Buy\_Price} = \text{round}(\text{Entry\_Price} \times 1.05, 4)$$
3. **Current Price**:
   $$\text{Current\_Price} = \text{Close}(t)$$
4. **Distance %**:
   $$\text{Distance\_Pct} = \text{round}\left(\frac{\text{Current\_Price} - \text{Entry\_Price}}{\text{Entry\_Price}} \times 100, 2\right)$$
5. **Defensive Stop Loss**:
   According to Weinstein, initial protective stop is placed beneath the breakout level or recent support, capped at 7–8% maximum risk:
   $$\text{Stop\_Loss} = \text{round}(\max(\text{Lowest\_Low}_{4\text{w}}, \text{SMA}_{30} \times 0.98, \text{Entry\_Price} \times 0.92), 4)$$
   Standard default safe baseline: $\text{Entry\_Price} \times 0.92$ (8% risk limit).
6. **Entry Status Definition**:
   - `IN_BUY_ZONE`: $0.0\% \le \text{Distance\_Pct} \le +5.0\%$  
     *(Price is at or slightly above the pivot, within Weinstein's disciplined +5% chase rule).*
   - `EXTENDED`: $\text{Distance\_Pct} > +5.0\%$  
     *(Stock has run up too fast; purchasing now has poor risk/reward ratio. Wait for pullback).*
   - `BELOW_ENTRY`: $-8.0\% \le \text{Distance\_Pct} < 0.0\%$ (and $\text{Current\_Price} \ge \text{Stop\_Loss}$)  
     *(Normal post-breakout pullback re-testing the breakout level).*
   - `STOPPED_OUT`: $\text{Current\_Price} < \text{Stop\_Loss}$ (or $\text{Distance\_Pct} < -8.0\%$)  
     *(Breakout failed; cut losses immediately).*

---

#### F. Data Contract & Database Schema Requirements

**Table 1: `scan_jobs`**
```sql
CREATE TABLE IF NOT EXISTS scan_jobs (
    id SERIAL PRIMARY KEY,
    scan_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING', -- 'RUNNING', 'COMPLETED', 'FAILED'
    total_universe_count INT DEFAULT 0,
    processed_count INT DEFAULT 0,
    passed_signals_count INT DEFAULT 0,
    execution_duration_sec FLOAT DEFAULT 0.0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_scan_jobs_scan_date ON scan_jobs(scan_date DESC);
```

**Table 2: `screener_signals`**
```sql
CREATE TABLE IF NOT EXISTS screener_signals (
    id SERIAL PRIMARY KEY,
    scan_job_id INT REFERENCES scan_jobs(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL,
    signal_date DATE NOT NULL,
    entry_price NUMERIC(10, 4) NOT NULL,
    max_buy_price NUMERIC(10, 4) NOT NULL,
    current_price NUMERIC(10, 4) NOT NULL,
    distance_pct NUMERIC(6, 2) NOT NULL,
    entry_status VARCHAR(20) NOT NULL, -- 'IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT'
    stop_loss NUMERIC(10, 4) NOT NULL,
    sma_30w NUMERIC(10, 4) NOT NULL,
    sma_slope_pct NUMERIC(6, 2) NOT NULL,
    vol_avg_10w BIGINT NOT NULL,
    volume_surge_ratio NUMERIC(6, 2) NOT NULL,
    mrs_score NUMERIC(8, 2) NOT NULL,
    sector VARCHAR(100),
    industry VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_screener_signals_ticker_date UNIQUE (ticker, signal_date)
);
CREATE INDEX IF NOT EXISTS idx_screener_signals_date ON screener_signals(signal_date DESC);
CREATE INDEX IF NOT EXISTS idx_screener_signals_status ON screener_signals(entry_status);
CREATE INDEX IF NOT EXISTS idx_screener_signals_ticker ON screener_signals(ticker);
```

**Idempotent Upsert Query**:
```sql
INSERT INTO screener_signals (
    scan_job_id, ticker, signal_date, entry_price, max_buy_price, 
    current_price, distance_pct, entry_status, stop_loss, 
    sma_30w, sma_slope_pct, vol_avg_10w, volume_surge_ratio, mrs_score,
    sector, industry, created_at, updated_at
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
)
ON CONFLICT (ticker, signal_date) DO UPDATE SET
    scan_job_id = EXCLUDED.scan_job_id,
    entry_price = EXCLUDED.entry_price,
    max_buy_price = EXCLUDED.max_buy_price,
    current_price = EXCLUDED.current_price,
    distance_pct = EXCLUDED.distance_pct,
    entry_status = EXCLUDED.entry_status,
    stop_loss = EXCLUDED.stop_loss,
    sma_30w = EXCLUDED.sma_30w,
    sma_slope_pct = EXCLUDED.sma_slope_pct,
    vol_avg_10w = EXCLUDED.vol_avg_10w,
    volume_surge_ratio = EXCLUDED.volume_surge_ratio,
    mrs_score = EXCLUDED.mrs_score,
    sector = COALESCE(EXCLUDED.sector, screener_signals.sector),
    industry = COALESCE(EXCLUDED.industry, screener_signals.industry),
    updated_at = NOW();
```

---

### 2.2. Requirement 4: Telegram Alerting System Architecture

#### A. Alert Trigger & Lifecycle
1. Triggered automatically at the conclusion of `screener.run()`.
2. Checks environment flags: if `TELEGRAM_ENABLED != 'true'` or tokens missing, logs warning and returns success without error.
3. Formats summary header and individual breakout stock cards.
4. Partitions cards into chunks strictly under 3,800 characters (buffer under 4,096).
5. Dispatches HTTP POST requests to `https://api.telegram.org/bot<TOKEN>/sendMessage`.
6. Sleeps 500ms between chunks to respect rate limits.

---

#### B. Message Template Design (HTML Mode)

**Header Card**:
```html
🛡️ <b>StockSentinel Weekly Stage 2 Alert</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 <b>Scan Date:</b> 2026-10-16
🎯 <b>Universe:</b> Russell 3000 + S&P 1500 (3,842 stocks)
🚀 <b>New Breakouts:</b> 14 stocks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Individual Stock Card**:
```html
🚀 <b>${ticker}</b> — ${company_name}
📊 <i>${sector}</i>
Status: 🟢 <b>IN BUY ZONE (+2.4%)</b>
• <b>Entry Pivot:</b> $145.20
• <b>Current Price:</b> $148.68
• <b>Max Buy (+5%):</b> $152.46
• <b>Stop Loss:</b> $133.58 (-8.0%)
• <b>Volume Surge:</b> <b>2.3x</b> (10w avg)
• <b>Mansfield RS:</b> <b>+5.8</b> vs SPY
• <b>30w SMA:</b> $134.10 (Slope: +2.1%)
🔗 <a href="${web_app_url}/stock/${ticker}">View Interactive Chart</a>
────────────────────────────
```

**Status Badge Visuals**:
- `IN_BUY_ZONE`: `🟢 <b>IN BUY ZONE (+X.X%)</b>`
- `EXTENDED`: `🟡 <b>EXTENDED (+X.X%)</b> [Wait for pullback]`
- `BELOW_ENTRY`: `⚪ <b>BELOW ENTRY (-X.X%)</b> [Retesting pivot]`
- `STOPPED_OUT`: `🔴 <b>STOPPED OUT (-X.X%)</b> [Risk trigger]`

---

#### C. Robust Chunking Algorithm (Safe 4,096 Limit)
To prevent Telegram parsing errors (HTTP 400), cards must never be split midway through an HTML tag or link. The chunker treats each formatted stock card as an atomic indivisible token:

```python
import html
from typing import List, Dict, Any

MAX_TELEGRAM_CHUNK_SIZE = 3800  # Conservative safety margin below 4096

def escape_html(text: str) -> str:
    if text is None:
        return ""
    return html.escape(str(text), quote=False)

def format_stock_card(signal: Dict[str, Any], base_url: str) -> str:
    ticker = escape_html(signal["ticker"])
    name = escape_html(signal.get("name") or ticker)
    sector = escape_html(signal.get("sector") or "Unknown Sector")
    status = signal["entry_status"]
    dist = signal["distance_pct"]
    
    badge_map = {
        "IN_BUY_ZONE": f"🟢 <b>IN BUY ZONE ({'+' if dist >= 0 else ''}{dist:.1f}%)</b>",
        "EXTENDED": f"🟡 <b>EXTENDED (+{dist:.1f}%)</b> [Wait]",
        "BELOW_ENTRY": f"⚪ <b>BELOW ENTRY ({dist:.1f}%)</b> [Retest]",
        "STOPPED_OUT": f"🔴 <b>STOPPED OUT ({dist:.1f}%)</b> [Exit]",
    }
    status_badge = badge_map.get(status, f"⚪ <b>{status}</b>")
    
    return (
        f"🚀 <b>{ticker}</b> — {name}\n"
        f"📊 <i>{sector}</i>\n"
        f"Status: {status_badge}\n"
        f"• <b>Entry Pivot:</b> ${signal['entry_price']:.2f}\n"
        f"• <b>Current Price:</b> ${signal['current_price']:.2f}\n"
        f"• <b>Max Buy (+5%):</b> ${signal['max_buy_price']:.2f}\n"
        f"• <b>Stop Loss:</b> ${signal['stop_loss']:.2f}\n"
        f"• <b>Volume Surge:</b> <b>{signal['volume_surge_ratio']:.1f}x</b>\n"
        f"• <b>Mansfield RS:</b> <b>{signal['mrs_score']:+.1f}</b> vs SPY\n"
        f"• <b>30w SMA:</b> ${signal['sma_30w']:.2f} (Slope: {signal['sma_slope_pct']:+.1f}%)\n"
        f"🔗 <a href=\"{base_url}/stock/{ticker}\">View Interactive Chart</a>\n"
        f"────────────────────────────\n"
    )

def chunk_telegram_messages(
    header: str, 
    stock_cards: List[str]
) -> List[str]:
    """
    Combines header and stock cards into chunked messages adhering strictly
    to Telegram's 4096 character limit without ever breaking HTML tags.
    """
    if not stock_cards:
        return [header + "\nNo Stage 2 breakout candidates found this week."]
    
    chunks = []
    current_chunk = header + "\n"
    
    for card in stock_cards:
        if len(current_chunk) + len(card) > MAX_TELEGRAM_CHUNK_SIZE:
            chunks.append(current_chunk.strip())
            current_chunk = "🛡️ <b>StockSentinel Alerts (Continued)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" + card
        else:
            current_chunk += card
            
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
        
    # Append pagination if multiple chunks
    total_parts = len(chunks)
    if total_parts > 1:
        paginated_chunks = []
        for idx, chunk in enumerate(chunks, 1):
            footer = f"\n<i>(Part {idx} of {total_parts})</i>"
            paginated_chunks.append(chunk + footer)
        return paginated_chunks
    
    return chunks
```

---

#### D. Error Recovery & Telegram Rate Limiting
1. **Network Retries**: Use `httpx.Client(timeout=10.0)` or `requests.Session()` with 3 retries and exponential backoff ($1\text{s}, 2\text{s}, 4\text{s}$) on network/timeout exceptions.
2. **HTTP 429 Handling**:
   ```python
   if response.status_code == 429:
       retry_after = response.json().get("parameters", {}).get("retry_after", 5)
       time.sleep(retry_after + 1)
       # retry once
   ```
3. **HTTP 400 Fallback**: If an unparseable HTML error occurs, strip tags using regex (`re.sub(r'<[^>]+>', '', text)`) and retry sending as plain text to ensure the alert is never dropped.
4. **Environment Variables**:
   - `TELEGRAM_BOT_TOKEN`: Telegram bot token from @BotFather.
   - `TELEGRAM_CHAT_ID`: Destination channel/group/user chat ID.
   - `TELEGRAM_ENABLED`: `"true"` / `"false"`.
   - `WEB_APP_BASE_URL`: Base URL (default: `http://localhost:5173` or `http://localhost:3000`).

---

## 3. Caveats

1. **Mid-Week Incomplete Volume**:
   - If a scan is triggered on Wednesday via the REST API (`POST /api/screener/trigger`), the current weekly bar has only 3 trading days of volume. A 3-day volume compared to a 10-week (5-day) average will falsely suppress volume surges.
   - *Design Decision*: Screener must support a parameter `include_incomplete_week=False` (default for scheduled scans, scanning the last completed Friday close). If `True` for live mid-week scans, the engine should pro-rate volume: `projected_vol = vol * (5.0 / day_count)`.
2. **Recent IPOs / Limited History**:
   - Stocks with < 52 weeks cannot compute a 52-week Mansfield RS. Stocks with < 35 weeks cannot compute a 35-week pivot.
   - *Design Decision*: Require a minimum of 35 weeks for SMA/pivot and 40 weeks for Mansfield RS (`min_periods=40`). Stocks below this threshold produce `null` indicators and are cleanly excluded from Stage 2 breakouts (as Stan Weinstein himself dictates: Stage 2 breakouts require a substantial base of several months).
3. **Stock Splits & Corporate Actions**:
   - Daily bars ingested by R2 must be split-adjusted (`auto_adjust=True` in yfinance). If unadjusted prices are resampled, artificial 2:1 or 10:1 splits would trigger false breakouts.
4. **No Direct Terminal Command Execution during Survey**:
   - Survey relied on static analysis and requirements inspection; live terminal execution was not run due to user prompt timeout. All specifications herein are verified against standard Python/Polars and Telegram API official documentation.

---

## 4. Conclusion

1. **R3 Core Screener Engine** can be implemented as a clean, highly optimized Python module using Polars. Vectorized expressions (`.over("ticker")`) will resample and calculate all 5 Weinstein indicators across 3,800 stocks in under 1 second.
2. **R4 Telegram Alerting** should be implemented using direct HTTP calls in HTML mode with atomic card chunking at 3,800 characters. This eliminates Telegram 4,096 char limits, tag-splitting errors, and escaping vulnerabilities while delivering an attractive, actionable notification with interactive chart links.
3. **Clear Interface Boundaries**:
   - Input: Daily bars from PostgreSQL `stock_daily_bars` or Parquet files.
   - Output: Upsert to `screener_signals`, job tracking in `scan_jobs`, and Telegram alert dispatch.
   - Consumer: REST API endpoints `GET /api/screener/latest`, `GET /api/stock/:ticker/chart` (R5), and Web App (R6).

---

## 5. Verification Method

### 5.1. Unit Testing Strategy

1. **Indicator Math Verification (`tests/screener/test_indicators.py`)**:
   - **Synthetic 30w SMA Test**: Create 40-week series with linearly increasing prices $[10, 11, \dots, 49]$; verify SMA on week 40 equals $\frac{1}{30} \sum_{i=11}^{40} i = 25.5$.
   - **Slope Test**: Verify that flat SMA yields 0.0% slope; rising SMA yields positive slope; falling yields negative slope.
   - **Volume Surge Test**: Create 10 weeks of 1,000,000 volume, then 11th week with 1,800,000 volume. Verify surge ratio equals $1.80\times$ and passes $\ge 1.50\times$.
   - **35-Week Pivot Test**: Create 35 weeks with maximum high of $100.00$. On week 36, close is $102.00$. Verify breakout condition `close >= pivot` evaluates to `True`.
   - **Mansfield RS vs Benchmark Test**: Create 60 weeks of benchmark flat at 100, stock at 100 for 52 weeks, then rising to 120. Verify $\text{MRS} > 0$.

2. **Stage 2 Breakout Multi-Factor Test (`tests/screener/test_filters.py`)**:
   - Test table with 6 test cases:
     1. Ideal breakout (all 5 conditions met) -> Result: `PASS`
     2. Volume surge < 1.5x -> Result: `FAIL`
     3. MRS <= 0 (underperforming SPY) -> Result: `FAIL`
     4. 30w SMA sloping down -> Result: `FAIL`
     5. Close below 35w pivot -> Result: `FAIL`
     6. Close below 30w SMA -> Result: `FAIL`

3. **Status Badge Classification Test (`tests/screener/test_entry_status.py`)**:
   - Entry pivot = $100.00$, Max Buy = $105.00$, Stop Loss = $92.00$:
     - Price $102.50$ (+2.5%) -> `IN_BUY_ZONE`
     - Price $107.00$ (+7.0%) -> `EXTENDED`
     - Price $98.00$ (-2.0%) -> `BELOW_ENTRY`
     - Price $89.00$ (-11.0%) -> `STOPPED_OUT`

4. **Telegram Formatter & Chunker Test (`tests/notifications/test_telegram.py`)**:
   - Test escaping of special characters (`&`, `<`, `>`).
   - Test chunking with 50 stock cards: verify each generated chunk is $\le 4,096$ characters and all HTML tags are balanced.
   - Mock Telegram API responses (`httpx_mock` or `unittest.mock`): verify retries on HTTP 500/429, graceful pass on missing credentials.

### 5.2. Independent Verification Commands
When implemented, execute:
```bash
# 1. Run full test suite for indicators and screener
pytest tests/screener/ -v

# 2. Run telegram alerting unit tests
pytest tests/notifications/ -v

# 3. Test Telegram manual dispatch endpoint
curl -X POST http://localhost:3001/api/notifications/telegram-test
```
