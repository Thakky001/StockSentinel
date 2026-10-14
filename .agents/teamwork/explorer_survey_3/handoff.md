# Handoff Report: Survey of Backend REST API (R5), Frontend Web App (R6), and Integration

**Agent**: `explorer_survey_3`  
**Date**: 2026-10-14  
**Target Roles**: `orchestrator_1`, `backend_engineer`, `frontend_engineer`, `test_engineer`  
**Scope**: Requirement 5 (Node.js/Express Backend REST API), Requirement 6 (React + Vite + Tailwind + Lightweight Charts Frontend), Integration, and Acceptance Criteria.

---

## 1. Observation

### 1.1 Direct Repository & Workspace Observations
- **Project Root**: `d:/git/StockSentinel`
- **Existing Files**: Directory listing of `d:/git/StockSentinel` via `list_dir` confirmed only `.agents/` exists. No pre-existing application files, `package.json`, or code exist yet. This is a clean greenfield project.
- **Request Document**: `d:/git/StockSentinel/.agents/teamwork/ORIGINAL_REQUEST.md` lines 33-47 and 56-64:
  > **R5. Backend REST API Service (Node.js / Express)**:
  > - REST endpoints:
  >   - `GET /api/screener/latest`: filtered/sorted screener results.
  >   - `GET /api/screener/dates`: list of scan dates.
  >   - `GET /api/stock/:ticker/chart`: weekly candle history + SMA 30w for charting.
  >   - `GET /api/stock/:ticker/summary`: stock details, entry/stop metrics, and technical summary.
  >   - `POST /api/screener/trigger`: trigger Python screener job.
  >   - `POST /api/notifications/telegram-test`: test Telegram bot.
  > 
  > **R6. Frontend Web Application (React + Vite + Tailwind CSS)**:
  > - Dashboard table with sorting, search, sector filter, and buy status badges.
  > - LocalStorage-persisted Watchlist drawer.
  > - Chart Modal using TradingView Lightweight Charts: weekly candlesticks, SMA 30w line, volume histogram, and horizontal lines for Entry Price (green), Max Buy (+5% orange), and Stop Loss (red).
  > - Risk & Position Sizing calculator.
  > 
  > **Acceptance Criteria**:
  > - All Express API endpoints return valid JSON responses with status 200.
  > - `/api/stock/:ticker/chart` returns properly formatted OHLCV and SMA 30w data ready for Lightweight Charts.
  > - Frontend builds without TypeScript/Vite errors.
  > - Dashboard displays screener results and allows interactive filtering.
  > - Opening detail modal renders the candlestick chart with overlays.

### 1.2 Execution Environment Observation
- Tool execution via `run_command` on Windows PowerShell requires interactive user permission and timed out (`permission check failed for command ...: Permission prompt ... timed out waiting for user response`).
- Consequently, all architecture, schemas, API contracts, component interfaces, and test plans must be fully documented in machine-readable specifications so implementers can build directly without ambiguous environmental assumptions.

---

## 2. Logic Chain

From the observations above, we establish the following chain of technical deduction:

1. **Database Schema Interface Compatibility**:
   - R5 endpoints require querying tables established in R1: `stocks`, `stock_daily_bars`, `screener_signals`, and `scan_jobs`.
   - `GET /api/screener/latest` queries `screener_signals` joined with `stocks` to display company names, sectors, and prices.
   - `GET /api/stock/:ticker/chart` requires aggregated weekly bars with 30-week SMA. This can be pre-computed by the Python screener in R3 or aggregated via PostgreSQL window functions over `stock_daily_bars`. Formatting must strictly match TradingView Lightweight Charts v4 specs (`time: 'YYYY-MM-DD'`, numbers for OHLCV, ascending time order).
   - `POST /api/screener/trigger` must manage process lifecycle and prevent race conditions (duplicate concurrent scans) by tracking state in `scan_jobs`.

2. **Backend API Architecture (R5)**:
   - A modular Express application structured as:
     - `src/server.ts` or `src/app.ts`: Express application setup, CORS, JSON parsing, logging, error handling.
     - `src/routes/screener.ts`: routes for `/api/screener/*`.
     - `src/routes/stock.ts`: routes for `/api/stock/*`.
     - `src/routes/notifications.ts`: routes for `/api/notifications/*`.
     - `src/db/pool.ts`: `pg.Pool` connection pool with automatic retry and environment parameterization.
     - `src/services/screenerRunner.ts`: handles triggering the Python screener subprocess, lock management, logging, and status updating.
     - `src/services/telegramService.ts`: handles sending test alerts and interacting with Telegram Bot API.

3. **Frontend Application Architecture (R6)**:
   - Built with React 18+, Vite, TypeScript, and Tailwind CSS.
   - Component hierarchy:
     - `App`: Main layout, global state / TanStack Query client, TopNavbar, WatchlistDrawer, ChartModal, CalculatorModal.
     - `TopNavbar`: App branding, scan date picker, "Trigger Scan" action button with live status badge, Watchlist toggle count badge.
     - `Dashboard`: Filter bar (search ticker/name, sector dropdown, status tabs), ScreenerTable, pagination footer.
     - `ScreenerTable`: Responsive table with columns: Star (watchlist), Ticker/Name, Close Price, Entry Price, Max Buy (+5%), Stop Loss, Distance %, Buy Status Badge, Volume Surge, MRS Score, 30w SMA Slope, and Action buttons.
     - `ChartModal`: Integrates `lightweight-charts` rendering:
       1. Candlestick series (green/red candles).
       2. Volume series (bottom 20% overlay, colored green/red).
       3. Line series for 30w SMA (blue or yellow line).
       4. Price lines: Green dashed line at Entry Price, Orange/Amber dashed line at Max Buy (+5%), Red dashed line at Stop Loss.
       5. ResizeObserver for responsive width/height adjustment.
     - `WatchlistDrawer`: Slide-over drawer stored in `localStorage`, allowing one-click quick chart preview, removal, and portfolio status summary.
     - `PositionCalculator`: Real-time risk and position sizing calculator:
       - Inputs: Account Size ($), Risk Per Trade (%), Entry Price ($), Stop Loss ($).
       - Outputs: Max Dollar Risk ($), Risk Per Share ($), Position Shares, Capital Required ($), Portfolio Allocation (%), Max Loss ($).
       - Safety alerts: Stop loss >= Entry price, Capital > Account Size.

4. **Integration & Network Strategy**:
   - Dev ports: Backend on `3001`, Frontend on `5173`, PostgreSQL on `5432`.
   - In development, Vite proxy forwards `/api` calls to `http://localhost:3001` to eliminate CORS friction, while Express also configures `cors()` for cross-origin flexibility.
   - Unified `.env.example` documents all required environment variables across Python, Node.js, and Frontend.

---

## 3. Detailed Technical Specifications

### 3.1 Backend REST API Specifications (R5)

#### Database Connection & Configuration (`src/db/pool.ts`)
```typescript
import { Pool } from 'pg';
import dotenv from 'dotenv';
dotenv.config();

export const pool = new Pool({
  connectionString: process.env.DATABASE_URL || 'postgresql://postgres:postgres@localhost:5432/stocksentinel',
  max: 20,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

pool.on('error', (err) => {
  console.error('Unexpected error on idle PostgreSQL client', err);
});
```

#### API Route Catalog

##### 1. `GET /api/screener/latest`
- **Query Parameters**:
  | Parameter | Type | Required | Default | Description |
  |---|---|---|---|---|
  | `date` | string (`YYYY-MM-DD`) | No | Latest date in DB | Target scan date |
  | `sector` | string | No | All | Sector name filter (e.g., 'Technology') |
  | `status` | string | No | All | Filter by status (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`) |
  | `search` | string | No | None | Partial match on ticker or company name |
  | `sort_by` | string | No | `mrs_score` | Sort field (`mrs_score`, `volume_surge_ratio`, `distance_pct`, `close_price`, `ticker`, `market_cap`) |
  | `order` | string | No | `DESC` | Sort direction (`ASC` or `DESC`) |
  | `page` | integer | No | `1` | Page number (1-indexed) |
  | `limit` | integer | No | `50` | Items per page (max: 200) |

- **SQL Implementation Pattern**:
  ```sql
  WITH latest_date AS (
    SELECT COALESCE($1::date, MAX(scan_date)) AS scan_date FROM screener_signals
  )
  SELECT 
    s.ticker,
    st.name,
    st.sector,
    st.industry,
    st.market_cap,
    s.scan_date,
    s.stage,
    s.close_price,
    s.entry_price,
    s.max_buy_price,
    s.stop_loss_price,
    s.distance_pct,
    s.status,
    s.volume_surge_ratio,
    s.mrs_score,
    s.sma_30w,
    s.sma_30w_slope,
    s.pivot_high_35w,
    COUNT(*) OVER() AS total_count
  FROM screener_signals s
  JOIN stocks st ON s.ticker = st.ticker
  JOIN latest_date ld ON s.scan_date = ld.scan_date
  WHERE ($2::text IS NULL OR st.sector = $2)
    AND ($3::text IS NULL OR s.status = $3)
    AND ($4::text IS NULL OR s.ticker ILIKE '%' || $4 || '%' OR st.name ILIKE '%' || $4 || '%')
  ORDER BY 
    CASE WHEN $5 = 'mrs_score' AND $6 = 'DESC' THEN s.mrs_score END DESC,
    CASE WHEN $5 = 'mrs_score' AND $6 = 'ASC' THEN s.mrs_score END ASC,
    CASE WHEN $5 = 'volume_surge_ratio' AND $6 = 'DESC' THEN s.volume_surge_ratio END DESC,
    CASE WHEN $5 = 'volume_surge_ratio' AND $6 = 'ASC' THEN s.volume_surge_ratio END ASC,
    CASE WHEN $5 = 'distance_pct' AND $6 = 'DESC' THEN s.distance_pct END DESC,
    CASE WHEN $5 = 'distance_pct' AND $6 = 'ASC' THEN s.distance_pct END ASC,
    s.mrs_score DESC
  LIMIT $7 OFFSET $8;
  ```
- **Response Format (200 OK)**:
  ```json
  {
    "success": true,
    "data": {
      "scan_date": "2026-10-09",
      "total": 38,
      "page": 1,
      "limit": 50,
      "total_pages": 1,
      "signals": [
        {
          "ticker": "NVDA",
          "name": "NVIDIA Corporation",
          "sector": "Technology",
          "industry": "Semiconductors",
          "market_cap": 3100000000000,
          "close_price": 138.25,
          "entry_price": 135.00,
          "max_buy_price": 141.75,
          "stop_loss_price": 125.55,
          "distance_pct": 2.41,
          "status": "IN_BUY_ZONE",
          "volume_surge_ratio": 2.15,
          "mrs_score": 24.50,
          "sma_30w": 118.40,
          "sma_30w_slope": 1.85,
          "pivot_high_35w": 135.00
        }
      ]
    }
  }
  ```

##### 2. `GET /api/screener/dates`
- **Response Format (200 OK)**:
  ```json
  {
    "success": true,
    "data": {
      "dates": ["2026-10-09", "2026-10-02", "2026-09-25", "2026-09-18"]
    }
  }
  ```
- **SQL**:
  `SELECT DISTINCT scan_date FROM screener_signals ORDER BY scan_date DESC LIMIT 52;`

##### 3. `GET /api/stock/:ticker/chart`
- **Route Param**: `:ticker` (e.g., `AAPL`, `NVDA`, uppercase).
- **Query Param**: `weeks` (default: 104, minimum: 52).
- **Weekly Resampling & SMA30 SQL**:
  ```sql
  WITH daily_data AS (
    SELECT 
      ticker,
      bar_date,
      open,
      high,
      low,
      close,
      volume,
      date_trunc('week', bar_date)::date AS week_date
    FROM stock_daily_bars
    WHERE ticker = $1
    ORDER BY bar_date ASC
  ),
  weekly_bars AS (
    SELECT
      week_date AS time,
      (array_agg(open ORDER BY bar_date ASC))[1] AS open,
      MAX(high) AS high,
      MIN(low) AS low,
      (array_agg(close ORDER BY bar_date DESC))[1] AS close,
      SUM(volume) AS volume
    FROM daily_data
    GROUP BY week_date
    ORDER BY week_date ASC
  ),
  weekly_with_sma AS (
    SELECT
      time,
      open,
      high,
      low,
      close,
      volume,
      CASE 
        WHEN ROW_NUMBER() OVER (ORDER BY time ASC) >= 30 
        THEN ROUND(AVG(close) OVER (ORDER BY time ASC ROWS BETWEEN 29 PRECEDING AND CURRENT ROW), 4)
        ELSE NULL 
      END AS sma30
    FROM weekly_bars
  )
  SELECT 
    to_char(time, 'YYYY-MM-DD') AS time,
    open::numeric::float AS open,
    high::numeric::float AS high,
    low::numeric::float AS low,
    close::numeric::float AS close,
    volume::bigint AS volume,
    sma30::numeric::float AS sma30
  FROM weekly_with_sma
  ORDER BY time ASC;
  ```
- **Response Format (200 OK)**:
  ```json
  {
    "success": true,
    "data": {
      "ticker": "NVDA",
      "company_name": "NVIDIA Corporation",
      "candlesticks": [
        { "time": "2024-10-18", "open": 132.5, "high": 139.0, "low": 131.2, "close": 138.0 },
        { "time": "2024-10-25", "open": 138.0, "high": 144.2, "low": 137.5, "close": 141.5 }
      ],
      "sma30": [
        { "time": "2024-10-18", "value": 116.8 },
        { "time": "2024-10-25", "value": 118.4 }
      ],
      "volume": [
        { "time": "2024-10-18", "value": 312000000, "color": "rgba(34, 197, 94, 0.6)" },
        { "time": "2024-10-25", "value": 298000000, "color": "rgba(34, 197, 94, 0.6)" }
      ],
      "metrics": {
        "entry_price": 135.00,
        "max_buy_price": 141.75,
        "stop_loss_price": 125.55,
        "status": "IN_BUY_ZONE",
        "close_price": 141.50
      }
    }
  }
  ```
- **Error Response**:
  - `404 Not Found`: `{ "success": false, "error": { "code": "NOT_FOUND", "message": "Ticker 'XYZ' not found" } }`

##### 4. `GET /api/stock/:ticker/summary`
- **Response Format (200 OK)**:
  ```json
  {
    "success": true,
    "data": {
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "sector": "Technology",
      "industry": "Semiconductors",
      "market_cap": 3100000000000,
      "exchange": "NASDAQ",
      "latest_signal": {
        "scan_date": "2026-10-09",
        "stage": 2,
        "close_price": 138.25,
        "entry_price": 135.00,
        "max_buy_price": 141.75,
        "stop_loss_price": 125.55,
        "distance_pct": 2.41,
        "status": "IN_BUY_ZONE",
        "volume_surge_ratio": 2.15,
        "mrs_score": 24.50,
        "sma_30w": 118.40,
        "sma_30w_slope": 1.85,
        "pivot_high_35w": 135.00
      },
      "latest_daily_bar": {
        "bar_date": "2026-10-13",
        "open": 137.5,
        "high": 139.8,
        "low": 136.2,
        "close": 138.5,
        "volume": 48200000
      }
    }
  }
  ```

##### 5. `POST /api/screener/trigger`
- **Request Body** (optional):
  ```json
  {
    "universe": "russell_sp",
    "send_telegram": true
  }
  ```
- **Execution & Lock Mechanism (`src/services/screenerRunner.ts`)**:
  1. Check if a job is already in `RUNNING` or `QUEUED` status in `scan_jobs`.
  2. If running, return `409 Conflict`:
     `{ "success": false, "error": { "code": "JOB_ALREADY_RUNNING", "message": "Screener scan is already running", "job_id": 14 } }`
  3. If no job is active, insert a new record into `scan_jobs` (`status = 'RUNNING'`, `started_at = NOW()`).
  4. Spawn Python process:
     ```typescript
     import { spawn } from 'child_process';
     const pythonPath = process.env.PYTHON_CMD || 'python';
     const scriptPath = process.env.SCREENER_SCRIPT_PATH || 'screener/main.py';
     const child = spawn(pythonPath, [scriptPath, '--job-id', jobId.toString()], {
       detached: true,
       stdio: ['ignore', 'pipe', 'pipe']
     });
     ```
  5. Asynchronously accumulate stdout/stderr and on process `exit`, update `scan_jobs` status (`COMPLETED` or `FAILED`), update `completed_at`, `signals_count`, and `error_message`.
- **Response Format (202 Accepted)**:
  ```json
  {
    "success": true,
    "data": {
      "job_id": 15,
      "status": "RUNNING",
      "message": "Screener job triggered successfully in the background",
      "started_at": "2026-10-14T02:25:00.000Z"
    }
  }
  ```

##### 6. `GET /api/screener/status`
- **Purpose**: Polling endpoint for frontend scan status banner.
- **Response Format (200 OK)**:
  ```json
  {
    "success": true,
    "data": {
      "latest_job": {
        "id": 15,
        "status": "RUNNING",
        "started_at": "2026-10-14T02:25:00.000Z",
        "completed_at": null,
        "signals_count": 0,
        "error_message": null
      }
    }
  }
  ```

##### 7. `POST /api/notifications/telegram-test`
- **Request Body** (optional overrides):
  ```json
  {
    "bot_token": "optional_override",
    "chat_id": "optional_override",
    "message": "StockSentinel Test: Telegram notifications configured properly!"
  }
  ```
- **Backend Service Logic**:
  - Resolves token and chat ID from request body or `process.env.TELEGRAM_BOT_TOKEN` and `process.env.TELEGRAM_CHAT_ID`.
  - Dispatches `POST https://api.telegram.org/bot<TOKEN>/sendMessage`.
  - If successful (200), returns:
    ```json
    {
      "success": true,
      "message": "Test Telegram message sent successfully",
      "telegram_message_id": 1042
    }
    ```
  - If credentials missing: `400 Bad Request` with helpful message.
  - If Telegram returns error: `502 Bad Gateway` returning the exact Telegram error description.

---

### 3.2 Frontend Web Application Specifications (R6)

#### Project Structure (`frontend/`)
```
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── index.css
│   ├── api/
│   │   ├── client.ts         # Axios / fetch wrapper with error handling
│   │   └── screenerApi.ts    # Typed API calls for screener, stock, jobs, telegram
│   ├── types/
│   │   └── index.ts          # ScreenerSignal, ChartData, StockSummary, CalculatorInputs
│   ├── hooks/
│   │   ├── useScreener.ts    # React Query / SWR hook for screener list & dates
│   │   ├── useStockChart.ts  # Hook for fetching chart OHLCV & SMA
│   │   ├── useWatchlist.ts   # LocalStorage sync hook
│   │   └── useScanStatus.ts  # Polling hook for trigger scan progress
│   ├── components/
│   │   ├── Navbar.tsx        # Logo, scan date dropdown, Trigger button, Watchlist button
│   │   ├── FilterBar.tsx     # Search input, Sector dropdown, Status badges tabs
│   │   ├── ScreenerTable.tsx # Main data table with sortable columns & badges
│   │   ├── StatusBadge.tsx   # Color-coded badge for buy statuses
│   │   ├── Pagination.tsx    # Page navigation controls
│   │   ├── ChartModal.tsx    # TradingView Lightweight Charts modal dialog
│   │   ├── TradingViewChart.tsx # Core Lightweight Charts canvas & series manager
│   │   ├── WatchlistDrawer.tsx  # Slide-over watchlist manager
│   │   ├── PositionCalculator.tsx # Risk & position sizing modal/drawer
│   │   └── TelegramTestModal.tsx  # Telegram configuration & test dialog
```

#### TradingView Lightweight Charts Integration Specification
- **Library**: `lightweight-charts` (v4.2+)
- **Candlestick Series**:
  ```typescript
  const candlestickSeries = chart.addCandlestickSeries({
    upColor: '#22c55e',
    downColor: '#ef4444',
    borderVisible: false,
    wickUpColor: '#22c55e',
    wickDownColor: '#ef4444',
  });
  candlestickSeries.setData(chartData.candlesticks);
  ```
- **30-Week SMA Line Series**:
  ```typescript
  const smaSeries = chart.addLineSeries({
    color: '#3b82f6',
    lineWidth: 2,
    title: '30w SMA',
    priceLineVisible: false,
  });
  smaSeries.setData(chartData.sma30);
  ```
- **Volume Histogram Series**:
  ```typescript
  const volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: '', // Overlay series on price
  });
  volumeSeries.priceScale().applyOptions({
    scaleMargins: { top: 0.8, bottom: 0 }, // Confine volume to bottom 20%
  });
  volumeSeries.setData(chartData.volume);
  ```
- **Horizontal Indicator Price Lines**:
  ```typescript
  // 1. Entry Price Line (Green)
  candlestickSeries.createPriceLine({
    price: metrics.entry_price,
    color: '#22c55e',
    lineWidth: 2,
    lineStyle: 2, // Dashed
    axisLabelVisible: true,
    title: `Entry: $${metrics.entry_price.toFixed(2)}`,
  });

  // 2. Max Buy (+5%) Price Line (Amber/Orange)
  candlestickSeries.createPriceLine({
    price: metrics.max_buy_price,
    color: '#f59e0b',
    lineWidth: 2,
    lineStyle: 2, // Dashed
    axisLabelVisible: true,
    title: `Max Buy (+5%): $${metrics.max_buy_price.toFixed(2)}`,
  });

  // 3. Stop Loss Price Line (Red)
  candlestickSeries.createPriceLine({
    price: metrics.stop_loss_price,
    color: '#ef4444',
    lineWidth: 2,
    lineStyle: 2, // Dashed
    axisLabelVisible: true,
    title: `Stop Loss: $${metrics.stop_loss_price.toFixed(2)}`,
  });
  ```
- **Responsive Sizing & Lifecycle**:
  ```typescript
  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight || 450,
        });
      }
    };
    const resizeObserver = new ResizeObserver(handleResize);
    if (containerRef.current) resizeObserver.observe(containerRef.current);
    return () => {
      resizeObserver.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, []);
  ```

#### Risk & Position Sizing Calculator Formula & Logic
- **User Inputs**:
  - `accountSize`: Total trading portfolio value ($), e.g., $100,000.
  - `riskPct`: Percentage of account willing to risk on trade, e.g., 1.0% (default 1.0%, range 0.25% - 5.0%).
  - `entryPrice`: Planned entry purchase price ($), auto-populated from stock entry pivot.
  - `stopLossPrice`: Planned stop loss exit price ($), auto-populated from stock stop loss.
- **Mathematical Formulations**:
  1. `Dollar Risk Amount` = `accountSize * (riskPct / 100)`
  2. `Risk Per Share` = `entryPrice - stopLossPrice`
  3. `Risk Percentage Per Share` = `((entryPrice - stopLossPrice) / entryPrice) * 100`
  4. `Position Size (Shares)` = `Math.floor(Dollar Risk Amount / Risk Per Share)`
  5. `Total Capital Required ($)` = `Position Size * entryPrice`
  6. `Portfolio Allocation (%)` = `(Total Capital Required / accountSize) * 100`
  7. `Actual Max Dollar Loss ($)` = `Position Size * Risk Per Share`
  8. `Gain at 2R Target ($)` = `Position Size * (Risk Per Share * 2)`
  9. `Target Price at 2R ($)` = `entryPrice + (Risk Per Share * 2)`
- **Safety Validations**:
  - If `stopLossPrice >= entryPrice`: error banner "Stop loss price must be below entry price."
  - If `Total Capital Required > accountSize`: warning alert "Position size exceeds total account size! Requires leverage or smaller risk %."
  - If `Position Size <= 0`: warning "Risk amount is too small to buy at least 1 share."

#### Status Badges & Color Semantics
| Status | Semantic Meaning | Tailwind Styling |
|---|---|---|
| `IN_BUY_ZONE` | Price is between `entry_price` and `max_buy_price` (+0% to +5% above pivot) | `bg-emerald-500/15 text-emerald-400 border border-emerald-500/30` |
| `EXTENDED` | Price has climbed > +5% past entry pivot (chasing risk is high) | `bg-amber-500/15 text-amber-400 border border-amber-500/30` |
| `BELOW_ENTRY` | Price has pulled back below the pivot level or hasn't breached yet | `bg-blue-500/15 text-blue-400 border border-blue-500/30` |
| `STOPPED_OUT` | Price fell below the stop loss threshold | `bg-rose-500/15 text-rose-400 border border-rose-500/30` |

#### LocalStorage Watchlist Drawer Specification
- Key in localStorage: `'stocksentinel_watchlist_v1'`
- Schema:
  ```typescript
  interface WatchlistItem {
    ticker: string;
    name: string;
    sector: string;
    addedAt: string; // ISO date
    entryPrice: number;
    currentPrice: number;
    status: 'IN_BUY_ZONE' | 'EXTENDED' | 'BELOW_ENTRY' | 'STOPPED_OUT';
  }
  ```
- React Hook `useWatchlist`: Provides `watchlist`, `addToWatchlist(stock)`, `removeFromWatchlist(ticker)`, `isWatchlisted(ticker)`, and `clearWatchlist()`. Syncs across tabs via the `storage` window event.

---

### 3.3 Integration, Network, and Port Topology
- **Topology**:
  - `PostgreSQL 16`: `localhost:5432`
  - `Node.js / Express Backend`: `localhost:3001`
  - `Vite Dev Server (Frontend)`: `localhost:5173`
- **Vite Proxy Config (`frontend/vite.config.ts`)**:
  ```typescript
  import { defineConfig } from 'vite';
  import react from '@vitejs/plugin-react';

  export default defineConfig({
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:3001',
          changeOrigin: true,
          secure: false,
        },
      },
    },
  });
  ```
- **Backend CORS Config (`backend/src/app.ts`)**:
  ```typescript
  import cors from 'cors';
  app.use(cors({
    origin: process.env.CORS_ORIGIN 
      ? process.env.CORS_ORIGIN.split(',') 
      : ['http://localhost:5173', 'http://127.0.0.1:5173'],
    credentials: true,
  }));
  ```

---

## 4. Edge Cases and Resilience Measures

1. **Strictly Ascending Dates in TradingView Lightweight Charts**:
   - TradingView Lightweight Charts throws a fatal JavaScript exception (`Assertion failed: data must be asc ordered by time`) if dates are duplicate or out of order.
   - *Mitigation*: The backend SQL query orders by `time ASC` and groups strictly by `week_date`. The frontend chart adapter passes the data through an idempotency deduplication and sorting validator:
     ```typescript
     const validCandles = data.candlesticks
       .filter((c, idx, arr) => idx === 0 || c.time > arr[idx - 1].time)
       .sort((a, b) => a.time.localeCompare(b.time));
     ```

2. **SMA30 Insufficient History (< 30 weeks)**:
   - For newly listed stocks or IPOs with under 30 weeks of weekly bars, a 30-week SMA cannot be calculated.
   - *Mitigation*: Backend returns `sma30: []` or starts the SMA series only at the 30th week candle. Lightweight Charts handles lines that begin later than the candlestick series gracefully as long as every point in `sma30` has a valid `time` and numeric `value`.

3. **Subprocess Concurrency & Orphaned Screener Jobs**:
   - If a user clicks "Run Scan Now" multiple times, multiple heavy Python scans could exhaust CPU/memory or corrupt database writes.
   - *Mitigation*: Database-backed status check on `scan_jobs` (`status = 'RUNNING'`). Returns HTTP `409 Conflict` if active. The backend service tracks process PID and listens for `SIGINT` / `SIGTERM` to mark interrupted jobs as `FAILED`.

4. **Database Connection Pool Exhaustion**:
   - If large numbers of requests hit `/api/screener/latest` or `/api/stock/:ticker/chart`, connections could be depleted.
   - *Mitigation*: Use `pg.Pool` with connection pooling, parameterized queries, and proper client release (`client.release()` or `pool.query()`). Set statements timeouts (`statement_timeout = 5000ms`).

5. **Telegram Bot Rate Limits & Markdown Injection**:
   - Special characters in stock names or ticker symbols (e.g. `BRK.B`, `_`, `*`, `[`, `]`) can cause Telegram MarkdownV2 parse errors (HTTP 400).
   - *Mitigation*: Backend Telegram service sanitizes special characters with regex escape `([_*\[\]()~`>#+-=|{}.!])` or uses HTML formatting (`<b>`, `<code>`), and chunks messages at 4,000 characters.

6. **Empty Screener Results**:
   - On rare occasions (e.g., bear market corrections), 0 stocks qualify for Stage 2 breakouts.
   - *Mitigation*: Frontend displays an empty-state illustration: "No Stage 2 Breakouts found for this scan date. Market conditions may be in Stage 4 downtrend or Stage 1 consolidation."

---

## 5. Caveats

- **Runtime Execution**: Live shell execution via `run_command` requires user approval and timed out in this environment. The findings in this report are based on deep architectural analysis, official library specifications (`lightweight-charts`, `express`, `pg`, `vite`), and strict adherence to `ORIGINAL_REQUEST.md`.
- **Database Schema Upstream Dependency**: R5 assumes R1 implements tables `stocks`, `stock_daily_bars`, `screener_signals`, and `scan_jobs`. The SQL queries documented here use those exact table and column names.
- **Python Subprocess Path**: The backend screener trigger assumes the Python virtual environment or binary is available via `PYTHON_CMD` (defaults to `python`).

---

## 6. Conclusion

Requirements 5 and 6 form the complete user-facing and application-serving core of StockSentinel:
- **Backend (R5)**: A clean, decoupled Express.js service providing 6 core REST endpoints + 1 polling endpoint, PostgreSQL connection pool via `pg`, secure CORS, child_process screener triggering with concurrency locks, and Telegram integration testing.
- **Frontend (R6)**: A high-performance React 18 + Vite + Tailwind CSS dashboard featuring interactive sorting/filtering, status badges, an interactive TradingView Lightweight Charts modal with 3 color-coded price lines (Entry, Max Buy +5%, Stop Loss), a localStorage-persisted Watchlist drawer, and a mathematically rigorous Risk & Position Sizing Calculator.
- **Integration**: Zero-friction setup via Vite reverse proxy and Express CORS, with standard dev ports (`3001` backend, `5173` frontend).

---

## 7. Verification Method

To independently verify the implementation once built:

### 7.1 Backend API Verification
1. **Server Startup**:
   ```bash
   cd backend && npm test
   # Or starting development server:
   npm run dev
   ```
2. **Endpoint Health Checks**:
   - `curl -i http://localhost:3001/api/screener/dates` -> Verify HTTP 200 and JSON with array of date strings.
   - `curl -i "http://localhost:3001/api/screener/latest?limit=10"` -> Verify HTTP 200, pagination metadata, and array of signals with status, MRS score, and volume surge ratio.
   - `curl -i "http://localhost:3001/api/stock/AAPL/chart"` -> Verify HTTP 200, candlesticks array, sma30 array, volume array, and metrics object.
   - `curl -i -X POST http://localhost:3001/api/screener/trigger` -> Verify HTTP 202 Accepted with `job_id`. Subsequent immediate call must return HTTP 409 Conflict.
   - `curl -i -X POST http://localhost:3001/api/notifications/telegram-test` -> Verify HTTP 200 or clean HTTP 400/502 JSON error.

### 7.2 Frontend Application Verification
1. **Type Checking & Build**:
   ```bash
   cd frontend
   npx tsc --noEmit
   npm run build
   ```
   *Expected*: Zero TypeScript compilation errors, Vite bundling successfully produces assets in `dist/`.
2. **Interactive UI Verification**:
   - Open `http://localhost:5173`.
   - Verify Screener Table loads and displays tickers, prices, and status badges (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`).
   - Test search filter by typing a ticker (e.g. `NVDA`) and sector filter.
   - Click "View Chart" -> Modal opens and renders TradingView Lightweight Charts with weekly candlesticks, 30w SMA line, volume histogram, and 3 horizontal lines (Green Entry, Orange Max Buy, Red Stop Loss).
   - Test Watchlist -> Click star icon; open Watchlist drawer -> item appears; reload page -> item persists.
   - Test Position Calculator -> Enter Account Size `$50,000`, Risk `1%`, Entry `$100`, Stop `$90` -> Verify output displays 50 shares, $5,000 capital, 10% portfolio allocation, $500 max loss.
