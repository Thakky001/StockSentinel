# 📈 StockSentinel

**ระบบสแกนและวิเคราะห์หุ้นระยะยาวตามทฤษฎี Stan Weinstein Stage 2 Breakout + จุดเข้าซื้อ (Entry Point) & Telegram Alerting**

StockSentinel เป็น Web Application และ Automated Batch Screener สำหรับคัดกรองหุ้นสหรัฐฯ กว่า 3,500–4,000 ตัว (Russell 3000 + S&P 1500) โดยคำนวณสัญญาณทางเทคนิคตามกลยุทธ์ **Stan Weinstein Stage 2 Breakout**:
- เส้นค่าเฉลี่ย 30 สัปดาห์ (SMA 30w) และความชัน (Slope)
- ปริมาณการซื้อขายระเบิดตัว (Volume Surge $\ge 1.5\times$ เทียบค่าเฉลี่ย 10 สัปดาห์)
- ทะลุแนวต้าน 35 สัปดาห์ (35-Week Resistance Pivot Breakout)
- ดัชนีความแข็งแกร่งเปรียบเทียบ Mansfield Relative Strength (MRS) เทียบกับ $SPY > 0
- คำนวณจุดเข้าซื้อที่เหมาะสม (Entry Pivot), เพดานราคาซื้อสูงสุด (Max Buy Price +5%), ราคาปัจจุบัน, และจัดกลุ่มสถานะโซนราคา (`IN_BUY_ZONE`, `EXTENDED`, `BELOW_ENTRY`, `STOPPED_OUT`)
- ส่งรายงานสรุปแจ้งเตือนอัตโนมัติเข้า Telegram Bot
- แสดงผลบน Dashboard ตารางคัดกรอง และกราฟแท่งเทียนสัปดาห์ด้วย TradingView Lightweight Charts

---

## 🏗️ สถาปัตยกรรมระบบ (Architecture)

```
[External Sources]
  ├── Russell 3000 / S&P 1500 Universe + SPY Benchmark
  └── Yahoo Finance API (yfinance batch downloader with chunking & backoff)
          │
          ▼
[Screener Engine (Python + Polars)]
  ├── Ingestion & Caching: Snappy Parquet Cache (<ticker>.parquet)
  ├── Weekly Bar Resampling (Friday close / Holiday anchoring)
  ├── Indicator Math: SMA 30w, Volume Surge, Pivot 35w, Mansfield RS vs SPY
  ├── Weinstein Stage 2 Breakout Filtering & Entry/Stop Risk Math
  └── Database Batch Upsert: `stocks`, `stock_daily_bars`, `screener_signals`, `scan_jobs`
          │
          ├───> [Telegram Alert Dispatcher] (HTML card formatting & chunker)
          │
          ▼
[Database Layer (PostgreSQL 16 + Redis 7)]
  ├── DDL Schema: db/init.sql
  └── High-throughput indexes for sub-20ms queries
          │
          ▼
[Backend REST API (Node.js / Express / TypeScript)]
  ├── GET /api/screener/latest   (Sort, filter by sector/status, pagination)
  ├── GET /api/screener/dates    (Historical scan dates)
  ├── GET /api/stock/:ticker/chart (Weekly OHLCV + SMA 30w for Lightweight Charts)
  ├── GET /api/stock/:ticker/summary (Company info, latest signal, daily bar)
  ├── POST /api/screener/trigger (Child process runner with execution lock)
  └── POST /api/notifications/telegram-test (Telegram bot test)
          │
          ▼
[Frontend Web App (React 18 + Vite + Tailwind CSS)]
  ├── Screener Table with interactive sorting, search, and status badges
  ├── TradingView Lightweight Charts Modal (Weekly bars, SMA 30w, Volume, Entry & Stop lines)
  ├── LocalStorage Watchlist Drawer
  └── Real-Time Position Sizing & Risk Calculator
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

## 📊 สถานะโซนราคา (Entry Status)
- 🟢 **`IN_BUY_ZONE`**: ราคาอยู่ระหว่างจุดเข้าซื้อ (Entry Pivot) ถึง $+5\%$ (เข้าซื้อได้ ไม่เสียเปรียบ)
- ⚠️ **`EXTENDED`**: ราคาพุ่งเกิน $+5\%$ จากจุดเข้าแล้ว (เตือนห้ามไล่ราคา ให้รอจังหวะย่อตัว)
- 🟡 **`BELOW_ENTRY`**: ราคาย่อตัวลงมาต่ำกว่าจุดเบรก แต่ยังยืนเหนือ Stop Loss (โซนรับของ)
- 🔴 **`STOPPED_OUT`**: ราคาหลุดจุดตัดขาดทุน (Stop Loss)

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

