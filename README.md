# 📈 StockSentinel

**ระบบสแกนและวิเคราะห์หุ้นระยะยาวตามทฤษฎี Stan Weinstein Stage 2 Breakout + จุดเข้าซื้อ (Entry Point) & Telegram Alerting**

StockSentinel เป็น Web Application และ Automated Batch Screener สำหรับคัดกรองหุ้นสหรัฐฯ (ดัชนี S&P 500 / S&P 1500 / Russell 3000) โดยคำนวณสัญญาณทางเทคนิคและบริหารความเสี่ยงขั้นสูงตามกลยุทธ์ **Stan Weinstein Stage 2 Breakout (เวอร์ชัน V2.1)**:
- **0. ตรวจสอบสภาวะตลาดรวม (Market Regime Filter - SPY):** เช็กดัชนี S&P 500 (SPY) ใน Timeframe Weekly แยกสถานะ `BULL_MARKET`, `CAUTION_MARKET` และ `BEAR_MARKET` (พร้อมป้ายเตือนหัวเว็บ)
- **1. เส้นค่าเฉลี่ย 30 สัปดาห์ & Smoothed Slope:** `Close > SMA_30w`, ความชันลด Noise 4 สัปดาห์ `>= 0.0%`, และ `Close > SMA_10w` ยืนยันโมเมนตัม
- **2. จุดเบรกเอาต์ 35 สัปดาห์ & กรองฐานบีบตัว (Base Tightness):** ทะลุแนวต้าน `Pivot_35w`, ฐานราคา 4 สัปดาห์บีบตัวแคบ `<= 18%` ป้องกัน V-Shape, และอยู่ใกล้ 52w High ไม่เกิน 15%
- **3. โวลุ่มระเบิดตัวแบบคาดการณ์ (Projected Volume Surge >= 1.5x):** รองรับการสแกนระหว่างสัปดาห์ (จันทร์-ศุกร์) โดยคูณเกลี่ยจำนวนวันทำการ
- **4. ดัชนีความแข็งแกร่ง Mansfield RS ขาขึ้น (Acceleration):** `MRS > 0.0` และเร่งตัวขึ้นเมื่อเทียบกับ 4 สัปดาห์ก่อนหน้า (`MRS[t] > MRS[t-4]`)
- **5. กรองหุ้นเต่า (Minimum Volatility Filter):** อัตราส่วนความผันผวน `(ATR_14w / Close) * 100 >= 2.5%` ตัดหุ้น Defensive เชิงรับที่แกว่งตัวแคบออก
- **6. แยกระบบ Discovery และ Active Lifecycle Tracker:** บันทึกและล็อก State ลงในตาราง `active_breakout_signals` เพื่อติดตามหุ้นที่เบรกเอาต์ไปแล้วอย่างต่อเนื่อง ไม่ให้หลุดหายจากหน้าเว็บเมื่อย่อตัวหรือรันเทรนด์
- **7. จุดตัดขาดทุน Adaptive Stop Loss & Breakeven Auto-Lock (🛡️ บังทุน):** ปรับระยะ Stop Loss ตามความผันผวนจริง `1.5x ATR` และ Low สัปดาห์ก่อนหน้า พร้อมยกบังหน้าทุนอัตโนมัติเมื่อทำกำไรแตะ `+15%`
- **8. คำนวณขนาดไม้ Dynamic Position Sizing:** ปรับขนาดไม้ตามสภาวะตลาด (`regime_multiplier`), ความเสี่ยงจากราคาซื้อจริง, และคุมเพดานเงินลงทุนไม่เกิน 20% ต่อหุ้น
- **9. แจ้งเตือนความเสี่ยงวันประกาศงบ (Earnings Warning):** แสดง Badge เตือนหุ้นที่กำลังจะประกาศผลประกอบการใน 14 วัน (`⚠️ งบออกใน X วัน`)
- **10. จัดหมวดหมู่สถานะ 6 ระดับ (6-Tier Actionable Statuses):** `IN_BUY_ZONE`, `EXTENDED`, `PROFIT_RUN`, `TRAILING_WARNING`, `BELOW_ENTRY`, `STOPPED_OUT`
- **11. ส่งรายงานแจ้งเตือน Telegram Bot & แสดงกราฟ TradingView Lightweight Charts**

---

## 🏗️ สถาปัตยกรรมระบบ (Architecture V2.1)

```
[External Sources]
  ├── S&P 500 / Russell 3000 Universe + SPY Benchmark
  └── Yahoo Finance API (yfinance resilient downloader & calendar)
          │
          ▼
[Screener Engine V2.1 (Python + Polars + NumPy)]
  ├── Ingestion & Caching: Snappy Parquet Cache (<ticker>.parquet)
  ├── Weekly Bar Resampling (Friday close / Holiday anchoring)
  ├── Market Regime Analysis: SPY SMA 30w / 10w / 4w Slope
  ├── Dual-Mode Screening Architecture:
  │     ├── Mode 1: Discovery Scanner (8 Multi-Factor Filters)
  │     └── Mode 2: Active Lifecycle Tracker (`active_breakout_signals`)
  ├── Adaptive Stop Loss & Breakeven Auto-Lock (🛡️ Peak Gain >= 15%)
  ├── Dynamic Position Sizing (Regime Multiplier + 20% Portfolio Cap)
  ├── 6-Tier Status Classification & Earnings Risk Check (0-14 days)
  └── Database Upsert: `stocks`, `stock_daily_bars`, `screener_signals`, `active_breakout_signals`, `scan_jobs`
          │
          ├───> [Telegram Alert Dispatcher] (HTML card formatting & chunker)
          │
          ▼
[Database Layer (PostgreSQL 16 / Neon DB + Redis 7)]
  ├── Tables: `stocks`, `stock_daily_bars`, `screener_signals`, `active_breakout_signals`, `scan_jobs`
  └── High-throughput indexes for sub-20ms queries
          │
          ▼
[Backend REST API (Node.js / Express / TypeScript)]
  ├── GET /api/screener/latest   (Sort, filter by sector/status, V2.1 metrics, pagination)
  ├── GET /api/screener/dates    (Historical scan dates)
  ├── GET /api/stock/:ticker/chart (Weekly OHLCV + SMA 30w for Lightweight Charts)
  ├── GET /api/stock/:ticker/summary (Company info, latest signal, daily bar)
  ├── POST /api/screener/trigger (Child process runner with execution lock)
  └── POST /api/notifications/telegram-test (Telegram bot test)
          │
          ▼
[Frontend Web App (React 18 + Vite + Tailwind CSS)]
  ├── Market Regime Alert Banners (BEAR_MARKET warning, CAUTION_MARKET, BULL_MARKET)
  ├── Position Sizing & Risk Management Toolbar (Account Size, Risk %, Budget)
  ├── Screener Table with 6 status badges, Base Tightness, ATR, Shares, Earnings alerts
  ├── TradingView Lightweight Charts Modal (Weekly bars, SMA 30w, Volume, Entry & Stop lines)
  ├── LocalStorage Watchlist Drawer
  └── Real-Time Position Sizing & Risk Calculator Modal (🧮)
```

---

## 🚀 เริ่มต้นใช้งาน (Quick Start)

### 1. ติดตั้งและเริ่มฐานข้อมูล (Database)
ตรวจสอบว่าติดตั้ง Docker แล้ว จากนั้นรัน:
```bash
docker compose up -d
```
PostgreSQL จะเปิดทำงานที่พอร์ต `5432` และ Redis ที่พอร์ต `6379` โดยจะรัน DDL schema จาก `db/init.sql` อัตโนมัติ

### 2. ตั้งค่าตัวแปรสภาพแวดล้อม (Environment Variables)
คัดลอกไฟล์ `.env.example` ไปเป็น `.env`:
```bash
cp .env.example .env
```
และระบุค่า `TELEGRAM_BOT_TOKEN` และ `TELEGRAM_CHAT_ID` หากต้องการเปิดใช้งานการแจ้งเตือน

### 3. รัน Screener Worker (Python)
ติดตั้ง dependencies:
```bash
cd screener
pip install -r requirements.txt
```
รันสแกนหุ้น (ทดสอบ 10 ตัวแรก หรือรันทั้งตลาด):
```bash
# ทดสอบสแกน 10 ตัว
python src/main.py --mode screen --sample 10

# สแกนทั้งตลาด
python src/main.py --mode all
```

### 4. รัน Backend API Service (Node.js / Express)
```bash
cd backend
npm.cmd install
npm.cmd run dev
```
Backend API จะทำงานที่: `http://localhost:3001` (ทดสอบ Health check ได้ที่ `http://localhost:3001/health`)

### 5. รัน Frontend Web Application (React + Vite)
```bash
cd frontend
npm.cmd install
npm.cmd run dev
```
เปิดเบราว์เซอร์ไปที่: `http://localhost:5173`

---

## 🧪 การรันชุดทดสอบ (Test Suites)

โปรเจกต์มีชุดทดสอบครอบคลุมครบทั้ง 4 Tiers:
```bash
# รันชุดทดสอบ E2E ทั้งหมด (424 tests)
python tests/run_e2e.py

# รันชุดทดสอบ Milestone 2 (Universe & Ingestion)
python screener/verify_m2.py

# รันชุดทดสอบ Milestone 3 (Indicators & Screener Engine)
python screener/verify_m3.py

# Build Backend TypeScript
cd backend && npm.cmd run build

# Build Frontend Vite + TypeScript
cd frontend && npm.cmd run build
```

---

## 📐 กลยุทธ์และสูตรคำนวณทางคณิตศาสตร์ (Strategy & Mathematical Models V2.1)

ระบบ StockSentinel V2.1 ใช้การคัดกรองแบบหลายปัจจัย (Multi-Factor Quantitative Model) ร่วมกับระบบบริหารความเสี่ยงระดับสถาบัน:

### 0. สภาวะตลาดรวม (Market Regime Filter - SPY)
วิเคราะห์ดัชนี S&P 500 (SPY) บน Timeframe Weekly ก่อนประมวลผลหุ้นรายตัว เพื่อกำหนด `regime_multiplier`:
- **`BULL_MARKET`**: `Close > SMA_30w` และ `Slope_4w >= 0.0%` ➔ `regime_multiplier = 1.0` (เปิดสถานะเต็มขนาดไม้)
- **`CAUTION_MARKET`**: `Close > SMA_30w` แต่ `Slope_4w < 0.0%` หรือ `Close < SMA_10w` ➔ `regime_multiplier = 0.5` (ลดขนาดไม้ลง 50%)
- **`BEAR_MARKET`**: `Close < SMA_30w` ➔ `regime_multiplier = 0.0` (งดเปิดสถานะซื้อใหม่เด็ดขาด พร้อมขึ้นแบนเนอร์แจ้งเตือนสีแดง)

---

### 1. เกณฑ์คัดกรองรอบเบรกเอาต์ใหม่ (Discovery Mode - 9 เกณฑ์)
สำหรับหุ้นใหม่ที่เพิ่งเบรกเอาต์ ต้องผ่านเกณฑ์ทั้งหมด 9 ข้อพร้อมกัน:
1. **เหนือเส้น 30 สัปดาห์**: `Close > SMA_30w`
2. **ความชันเส้น 30 สัปดาห์เป็นบวก (Smoothed Slope)**:
   ```text
   SMA_30w_Slope = ((SMA_30w[t] - SMA_30w[t-4]) / SMA_30w[t-4]) * 100 >= 0.0%
   ```
3. **เหนือเส้น 10 สัปดาห์ (โมเมนตัมระยะสั้น)**: `Close > SMA_10w`
4. **เบรกเอาต์แนวต้าน 35 สัปดาห์**: `Close >= Pivot_35w` โดย `Pivot_35w = max(High[t-35 : t-1])`
5. **กรอบฐานราคาก่อนเบรกบีบตัวแคบ (Base Tightness <= 18%)**: ป้องกันหุ้นทรง V-Shape
   ```text
   Tightness_Pct = ((max(High[t-4 : t-1]) - min(Low[t-4 : t-1])) / min(Low[t-4 : t-1])) * 100 <= 18.0%
   ```
6. **ใกล้เคียงจุดสูงสุด 52 สัปดาห์**: `Close >= High_52w * 0.85` (อยู่ห่างจาก 52w High ไม่เกิน 15%)
7. **ปริมาณการซื้อขายระเบิดตัวแบบคาดการณ์ (Projected Volume Surge >= 1.5x)**:  
   คำนวณปรับเกลี่ยตามจำนวนวันทำการในสัปดาห์ (1–5 วัน) เพื่อให้สแกนเจอตลอดสัปดาห์โดยไม่ต้องรอแท่งปิดวันศุกร์
8. **ความแข็งแกร่งเชิงเปรียบเทียบเร่งตัว (Mansfield RS Acceleration)**:
   ```text
   MRS[t] = ((Stock[t] / SPY[t]) / SMA_52w(Stock / SPY) - 1) * 10
   เงื่อนไข: MRS[t] > 0.0 และ MRS[t] > MRS[t-4]
   ```
9. **กรองหุ้นเต่า (Minimum Volatility Filter)**:
   ```text
   (ATR_14w / Close) * 100 >= 2.5%
   ```
   *(คัดหุ้น Defensive เชิงรับที่ราคาแกว่งตัวแคบเกินไปออก)*

---

### 2. สถาปัตยกรรม 2 โหมด: Discovery vs Active Lifecycle Tracker
แก้ปัญหาหุ้นหายจากตารางเมื่อราคาย่อตัวหรือวิ่งไปไกล:
- **Mode 1 (Discovery Scanner)**: สแกนหาหุ้นที่เพิ่งผ่านเกณฑ์ทั้ง 9 ข้อในรอบสัปดาห์ และล็อก State ลงตาราง `active_breakout_signals`:
  - `entry_price` = `Pivot_35w` ณ วันที่เบรก
  - `max_buy_price` = `entry_price * 1.05`
  - `initial_stop_loss` = Stop Loss ที่คำนวณได้ ณ สัปดาห์แรก
  - `highest_price_since_entry` = `max(High, Close)`
- **Mode 2 (Active Lifecycle Tracker)**: นำหุ้นที่เคยผ่านเบรกเอาต์ใน Watchlist/Database มาอัปเดตสถานะและราคาล่าสุดโดยตรง **ไม่นำกลับไปเข้าตัวกรอง 9 ข้อซ้ำ** ทำให้หุ้นที่ย่อตัวลงมาเทสฐานหรือกำลังรันเทรนด์ยังคงอยู่ในระบบต่อเนื่อง

---

### 3. จุดตัดขาดทุน Adaptive Stop Loss & Breakeven Auto-Lock (🛡️ บังทุน)
- **สูตรคำนวณ Stop Loss เริ่มต้น (ณ จุดเบรกเอาต์)**:
  ```text
  raw_stop  = max(entry_price * 0.90, entry_price - (1.5 * ATR_14w), Low_prev_week * 0.99)
  stop_loss = min(entry_price * 0.98, raw_stop)
  ```
  *(จำกัดความเสี่ยงไม่เกิน -10% และไม่ตื้นกว่า -2%)*
- **🛡️ Breakeven Auto-Lock (ยกบังหน้าทุน)**:  
  เมื่อหุ้นทำผลตอบแทนสูงสุดแตะ +15% (`peak_gain_pct >= 15.0%`) ระบบจะขยับ Stop Loss ขึ้นมาที่ระดับหน้าทุนทันที:
  ```text
  active_stop_loss = max(initial_stop_loss, entry_price)
  ```
  ป้องกันไม่ให้กำไรก้อนใหญ่พลิกกลับมาขาดทุนเด็ดขาด!

---

### 4. คำนวณขนาดไม้ลงทุน Dynamic Position Sizing
คำนวณจำนวนหุ้นที่แนะนำให้ซื้อตามหลักการจำกัดความเสี่ยง:
```text
effective_buy      = max(current_price, entry_price)
risk_per_share     = effective_buy - stop_loss
shares_risk        = floor((portfolio_size * risk_pct * regime_multiplier) / risk_per_share)
shares_cap         = floor((portfolio_size * 0.20 * regime_multiplier) / effective_buy)
recommended_shares = min(shares_risk, shares_cap)
```
*(ควบคุมสัดส่วนไม่ให้หุ้นตัวใดตัวหนึ่งกินเงินเกิน 20% ของพอร์ต และปรับลดตาม `regime_multiplier`)*

---

## 📊 สถานะโซนราคา 6 ระดับ (6-Tier Actionable Statuses)
- 🟢 **`IN_BUY_ZONE`**: ราคาปัจจุบันอยู่ระหว่างจุดเบรกเอาต์ (`Entry`) ถึง `+5%` (`Entry * 1.05`) เป็นโซนเข้าซื้อที่ได้เปรียบต้นทุน
- ⚠️ **`EXTENDED`**: ราคาพุ่งเกิน `+5%` จากจุดเบรกเอาต์ (`> Entry * 1.05`) เตือนห้ามไล่ราคาเด็ดขาด ให้รอจังหวะย่อตัวเข้าโซน
- 🚀 **`PROFIT_RUN`**: ราคาทำกำไรเกิน `+5%` จากจุดเบรก และยังคงรักษาโมเมนตัมขาขึ้น ไม่หลุดเกณฑ์ Trailing Stop (ปล่อยให้กำไรวิ่งต่อ)
- 🔔 **`TRAILING_WARNING`**: หุ้นที่เคยทำกำไรขึ้นไปสูง (`peak_gain_pct >= 8%`) แล้วย่อตัวลงมาเกิน 8% จากจุดสูงสุดเดิม (`Close <= Peak * 0.92`) เตือนให้พิจารณาทยอยแบ่งขายล็อคกำไร
- 🟡 **`BELOW_ENTRY`**: ราคาย่อตัวลงมาต่ำกว่าจุดเบรกเอาต์ (`Close < Entry`) แต่ราคายังยืนเหนือ Stop Loss (`Close > Stop_Loss`) ยังไม่เสียทรงหลัก เป็นจุดรอซื้อดักจังหวะย่อเทสฐาน
- 🔴 **`STOPPED_OUT`**: ราคาหลุดจุด Stop Loss (`Close <= Stop_Loss`) ต้องตัดขาดทุนทันทีตามวินัยบริหารความเสี่ยง

---

## ⚠️ การแจ้งเตือนวันประกาศงบการเงิน (Earnings Risk Warning)
ระบบดึงปฏิทินวันรายงานผลประกอบการจาก Yahoo Finance Calendar แบบคู่ขนาน:
- หากบริษัทมีกำหนดการประกาศงบภายใน 14 วัน ระบบจะแสดง Badge เตือน:  
  `⚠️ งบออกใน X วัน`
- ป้องกันความเสี่ยงจากการเปิดสถานะก่อนงบการเงินออก (Earnings Gap Risk)

---

## ☁️ การนำขึ้นคลาวด์ Render (Deploy to Render.com)

ระบบนี้รองรับการ Deploy ขึ้น **Render** ด้วย Dockerfile แบบ Multi-stage ที่รวมทั้ง React Frontend, Express Backend และ Python Polars Screener ไว้ใน Web Service ตัวเดียวได้อย่างประหยัดทรัพยากร:

### วิธีที่ 1: Deploy อัตโนมัติด้วย Render Blueprint (แนะนำ - ง่ายที่สุดใน 1 คลิก)
1. Push โค้ดทั้งหมดขึ้น GitHub Repository ของคุณ
2. เข้าสู่เว็บ [dashboard.render.com](https://dashboard.render.com)
3. คลิกปุ่ม **New +** ➔ เลือก **Blueprint**
4. เชื่อมต่อกับ GitHub Repo ของคุณ Render จะอ่านไฟล์ `render.yaml` อัตโนมัติและสร้าง:
   - **PostgreSQL Database** (`stocksentinel-db`) ฟรี
   - **Full-Stack Web Service** (`stocksentinel-web`) จาก Dockerfile
   - **Weekly Screener Cron Job** (`stocksentinel-screener-cron`) สแกนหุ้นอัตโนมัติทุกเช้าวันเสาร์เวลา 06:00 น.
5. คลิก **Apply** เพื่อเริ่มการ Build และ Deploy ทันที!

### วิธีที่ 2: Deploy แบบกำหนดเองผ่าน Render Dashboard
1. สร้าง **PostgreSQL** ใหม่บน Render:
   - ไปที่ **New +** ➔ **PostgreSQL** ตั้งชื่อ `stocksentinel-db`
   - คัดลอกค่า **Internal Database URL** มาไว้
2. สร้าง **Web Service**:
   - ไปที่ **New +** ➔ **Web Service** ➔ เลือก GitHub Repository ของคุณ
   - เลือก Environment เป็น **Docker** (ระบบจะตรวจพบ `Dockerfile` ที่ root อัตโนมัติ)
   - ที่เมนู **Environment Variables** ให้เพิ่ม:
     - `DATABASE_URL`: ใส่ Internal Database URL จากข้อ 1
     - `NODE_ENV`: `production`
     - `TELEGRAM_BOT_TOKEN`: (ตัวเลือก) สำหรับแจ้งเตือน Telegram
     - `TELEGRAM_CHAT_ID`: (ตัวเลือก) สำหรับแจ้งเตือน Telegram
3. คลิก **Create Web Service** ระบบจะทำการ Build Docker และเปิดใช้งานเว็บแอปให้คุณทันที!

