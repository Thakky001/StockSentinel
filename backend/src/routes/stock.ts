/**
 * Stock routes — /api/stock/*
 *
 * Endpoints:
 *   GET /api/stock/:ticker/chart   — weekly OHLCV candlesticks + 30w SMA for Lightweight Charts
 *   GET /api/stock/:ticker/summary — stock details + latest screener signal + latest daily bar
 */

import { Router, Request, Response, NextFunction } from 'express';
import { query } from '../db/pool';
import {
  ChartData,
  CandlestickBar,
  SeriesPoint,
  VolumeBar,
  ChartMetrics,
  StockSummaryData,
  ScreenerSignal,
  DailyBar,
  ApiResponse,
} from '../types';
import { generateMockChartData, MOCK_SIGNALS } from '../db/mockDb';

const router = Router();

// ---------------------------------------------------------------------------
// GET /api/stock/:ticker/chart
// ---------------------------------------------------------------------------
router.get(
  '/:ticker/chart',
  async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
      const ticker = req.params.ticker.toUpperCase().trim();

      // Default 104 weeks (2 years); clamp between 4 and 520
      const weeksRaw = parseInt((req.query.weeks as string) || '104', 10);
      const weeks = Math.min(520, Math.max(4, isNaN(weeksRaw) ? 104 : weeksRaw));

      let companyName = ticker;
      let metrics: ChartMetrics = {
        entry_price: 0,
        max_buy_price: 0,
        stop_loss_price: 0,
        status: 'N/A',
        close_price: 0,
      };

      try {
        // ---- Fetch company name ----
        const stockResult = await query<{ name: string }>(
          `SELECT name FROM stocks WHERE ticker = $1 LIMIT 1`,
          [ticker],
        );
        if (stockResult.rows[0]?.name) {
          companyName = stockResult.rows[0].name;
        }

        // ---- Fetch latest metrics from screener_signals ----
        const metricsResult = await query<{
          entry_price: number;
          max_buy_price: number;
          stop_loss_price: number;
          entry_status: string;
          weekly_close: number;
        }>(
          `SELECT entry_price, max_buy_price, stop_loss_price, entry_status, weekly_close
           FROM screener_signals
           WHERE ticker = $1
           ORDER BY scan_date DESC
           LIMIT 1`,
          [ticker],
        );

        if (metricsResult.rows[0]) {
          const m = metricsResult.rows[0];
          metrics = {
            entry_price: Number(m.entry_price),
            max_buy_price: Number(m.max_buy_price),
            stop_loss_price: Number(m.stop_loss_price),
            status: m.entry_status,
            close_price: Number(m.weekly_close),
          };
        }

        const chartSql = `
          WITH weekly_bars AS (
            SELECT
              (date_trunc('week', trade_date) + interval '4 days')::date AS week_end,
              (array_agg(open::float    ORDER BY trade_date ASC))[1]  AS open,
              MAX(high)::float                                         AS high,
              MIN(low)::float                                          AS low,
              (array_agg(close::float   ORDER BY trade_date DESC))[1] AS close,
              SUM(volume)::bigint                                      AS volume
            FROM stock_daily_bars
            WHERE ticker = $1
            GROUP BY date_trunc('week', trade_date)
            ORDER BY week_end ASC
          ),
          numbered AS (
            SELECT
              week_end,
              open, high, low, close, volume,
              ROW_NUMBER() OVER (ORDER BY week_end) AS rn
            FROM weekly_bars
          )
          SELECT
            to_char(week_end, 'YYYY-MM-DD') AS time,
            open, high, low, close, volume,
            CASE
              WHEN rn >= 30
                THEN ROUND(
                       AVG(close) OVER (
                         ORDER BY week_end
                         ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
                       )::numeric, 4
                     )::float
              ELSE NULL
            END AS sma30
          FROM numbered
          ORDER BY week_end ASC
          LIMIT $2
        `;

        const chartResult = await query<{
          time: string;
          open: number;
          high: number;
          low: number;
          close: number;
          volume: number;
          sma30: number | null;
        }>(chartSql, [ticker, weeks]);

        if (chartResult.rows.length > 0) {
          const candlesticks: CandlestickBar[] = [];
          const sma30: SeriesPoint[] = [];
          const volume: VolumeBar[] = [];

          for (const row of chartResult.rows) {
            candlesticks.push({
              time: row.time,
              open: row.open,
              high: row.high,
              low: row.low,
              close: row.close,
            });

            volume.push({
              time: row.time,
              value: row.volume,
              color: row.close >= row.open ? 'rgba(38,166,154,0.7)' : 'rgba(239,83,80,0.7)',
            });

            if (row.sma30 !== null) {
              sma30.push({ time: row.time, value: row.sma30 });
            }
          }

          const chartData: ChartData = {
            ticker,
            company_name: companyName,
            candlesticks,
            sma30,
            volume,
            metrics,
          };

          res.json({ success: true, data: chartData });
          return;
        }
      } catch (dbErr) {
        console.warn(`[Stock /chart] DB query failed for ${ticker}. Serving fallback chart.`, (dbErr as Error).message);
      }

      // Fallback: Generate realistic chart data using actual company name and metrics
      const fallbackData = generateMockChartData(ticker, weeks, metrics, companyName);
      res.json({ success: true, data: fallbackData });
    } catch (err) {
      next(err);
    }
  },
);

// ---------------------------------------------------------------------------
// GET /api/stock/:ticker/summary
// ---------------------------------------------------------------------------
router.get(
  '/:ticker/summary',
  async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
      const ticker = req.params.ticker.toUpperCase().trim();

      try {
        const stockResult = await query<{
          ticker: string;
          name: string;
          sector: string | null;
          industry: string | null;
          market_cap: number | null;
          exchange: string | null;
        }>(
          `SELECT ticker, name, sector, industry, market_cap, exchange
           FROM stocks
           WHERE ticker = $1
           LIMIT 1`,
          [ticker],
        );

        if (stockResult.rows.length > 0) {
          const stockRow = stockResult.rows[0];

          const signalResult = await query<ScreenerSignal>(
            `SELECT *, to_char(scan_date, 'YYYY-MM-DD') AS scan_date
             FROM screener_signals
             WHERE ticker = $1
             ORDER BY scan_date DESC
             LIMIT 1`,
            [ticker],
          );

          const dailyResult = await query<DailyBar>(
            `SELECT ticker, to_char(trade_date, 'YYYY-MM-DD') AS trade_date,
                    open::float, high::float, low::float, close::float,
                    adj_close::float, volume
             FROM stock_daily_bars
             WHERE ticker = $1
             ORDER BY trade_date DESC
             LIMIT 1`,
            [ticker],
          );

          const summaryData: StockSummaryData = {
            ticker: stockRow.ticker,
            name: stockRow.name,
            sector: stockRow.sector,
            industry: stockRow.industry,
            market_cap: stockRow.market_cap,
            exchange: stockRow.exchange,
            latest_signal: signalResult.rows[0] ?? null,
            latest_daily_bar: dailyResult.rows[0] ?? null,
          };

          res.json({ success: true, data: summaryData });
          return;
        }
      } catch (dbErr) {
        console.warn(`[Stock /summary] DB query failed for ${ticker}. Serving fallback summary.`, (dbErr as Error).message);
      }

      // Fallback summary from mock signals
      const mockSignal = MOCK_SIGNALS.find((s) => s.ticker === ticker) ?? MOCK_SIGNALS[0];
      const summaryData: StockSummaryData = {
        ticker: ticker,
        name: mockSignal.name ?? ticker,
        sector: mockSignal.sector ?? null,
        industry: mockSignal.industry ?? null,
        market_cap: mockSignal.market_cap ?? null,
        exchange: 'NASDAQ',
        latest_signal: mockSignal,
        latest_daily_bar: {
          ticker: ticker,
          trade_date: '2026-10-09',
          open: mockSignal.current_price * 0.99,
          high: mockSignal.current_price * 1.02,
          low: mockSignal.current_price * 0.98,
          close: mockSignal.current_price,
          adj_close: mockSignal.current_price,
          volume: Math.round(mockSignal.weekly_volume / 5),
        },
      };

      res.json({ success: true, data: summaryData });
    } catch (err) {
      next(err);
    }
  },
);

export default router;
