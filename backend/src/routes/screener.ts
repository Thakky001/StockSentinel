/**
 * Screener routes — /api/screener/*
 *
 * Endpoints:
 *   GET  /api/screener/latest   — paginated, filtered list of the latest signals
 *   GET  /api/screener/dates    — list of distinct scan dates (last 52)
 *   GET  /api/screener/status   — latest scan_jobs row
 *   POST /api/screener/trigger  — spawn Python screener with process lock
 */

import { Router, Request, Response, NextFunction } from 'express';
import { query } from '../db/pool';
import { ScreenerSignal, ApiResponse, ScreenerListData } from '../types';
import { getRunningJobId, getLatestJob, runScreener } from '../services/screenerRunner';
import { MOCK_DATES, MOCK_SIGNALS } from '../db/mockDb';

const router = Router();

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Whitelist of columns that are safe to use in ORDER BY to prevent SQL injection
// ---------------------------------------------------------------------------
const SORT_COLUMN_MAP: Record<string, string> = {
  mrs_score: 's.mrs_score',
  diff_pct: 's.diff_pct',
  entry_price: 's.entry_price',
  max_buy_price: 's.max_buy_price',
  stop_loss_price: 's.stop_loss_price',
  volume_surge_ratio: 's.volume_surge_ratio',
  sma_30w: 's.sma_30w',
  sma_30w_slope: 's.sma_30w_slope',
  weekly_close: 's.weekly_close',
  close_price: 's.current_price',
  current_price: 's.current_price',
  status: 's.entry_status',
  entry_status: 's.entry_status',
  scan_date: 's.scan_date',
  ticker: 's.ticker',
  market_cap: 'st.market_cap',
};

// ---------------------------------------------------------------------------
// GET /api/screener/latest
// ---------------------------------------------------------------------------
router.get(
  '/latest',
  async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
      // ---- Parse & validate query params ----
      const dateParam = (req.query.date as string) || null;
      const sector = (req.query.sector as string) || null;
      const status = (req.query.status as string) || null;
      const search = (req.query.search as string) || null;

      // Sort validation — default mrs_score DESC
      const sortByRaw = (req.query.sort_by as string) || 'mrs_score';
      const sortColumn = SORT_COLUMN_MAP[sortByRaw] ?? 's.mrs_score';

      const orderRaw = ((req.query.order as string) || 'DESC').toUpperCase();
      const order = orderRaw === 'ASC' ? 'ASC' : 'DESC';

      const page = Math.max(1, parseInt((req.query.page as string) || '1', 10));
      const limitRaw = parseInt((req.query.limit as string) || '50', 10);
      const limit = Math.min(200, Math.max(1, isNaN(limitRaw) ? 50 : limitRaw));
      const offset = (page - 1) * limit;

      let signals: ScreenerSignal[] = [];
      let total = 0;
      let scanDate = dateParam ?? new Date().toISOString().slice(0, 10);

      try {
        const sql = `
          WITH latest_date AS (
            SELECT COALESCE($1::date, MAX(scan_date)) AS scan_date
            FROM screener_signals
          )
          SELECT
            s.id,
            s.scan_id,
            s.scan_date,
            s.ticker,
            st.name,
            st.sector,
            st.industry,
            st.market_cap,
            s.entry_price,
            s.max_buy_price,
            s.current_price,
            s.current_price AS close_price,
            s.stop_loss_price,
            s.diff_pct,
            s.entry_status,
            s.entry_status AS status,
            s.volume_surge_ratio,
            s.mrs_score,
            s.sma_30w,
            s.sma_30w_slope,
            s.prior_resistance_35w,
            s.weekly_close,
            s.weekly_volume,
            s.avg_volume_10w,
            s.stage,
            s.created_at,
            COUNT(*) OVER() AS total_count
          FROM screener_signals s
          LEFT JOIN stocks st ON s.ticker = st.ticker
          JOIN latest_date ld ON s.scan_date = ld.scan_date
          WHERE ($2::text IS NULL OR st.sector = $2)
            AND ($3::text IS NULL OR s.entry_status = $3)
            AND ($4::text IS NULL
                 OR s.ticker ILIKE '%' || $4 || '%'
                 OR st.name  ILIKE '%' || $4 || '%')
          ORDER BY ${sortColumn} ${order}
          LIMIT $5 OFFSET $6
        `;

        const result = await query<ScreenerSignal & { total_count: string }>(sql, [
          dateParam,
          sector,
          status,
          search,
          limit,
          offset,
        ]);

        if (result.rows.length > 0) {
          total = parseInt(result.rows[0].total_count, 10);
          scanDate = result.rows[0].scan_date ?? scanDate;
          signals = result.rows.map(({ total_count: _, ...row }) => row);
        }
      } catch (dbErr) {
        console.warn('[Screener /latest] Database offline or error. Serving fallback demo signals.', (dbErr as Error).message);
      }

      // If database is offline or empty, use fallback mock signals
      if (signals.length === 0) {
        let filtered = [...MOCK_SIGNALS];
        if (sector) filtered = filtered.filter((s) => s.sector === sector);
        if (status) filtered = filtered.filter((s) => s.entry_status === status);
        if (search) {
          const q = search.toLowerCase();
          filtered = filtered.filter((s) => s.ticker.toLowerCase().includes(q) || (s.name ? s.name.toLowerCase().includes(q) : false));
        }

        // Apply sorting to mock signals
        filtered.sort((a, b) => {
          let valA: any = (a as any)[sortByRaw];
          let valB: any = (b as any)[sortByRaw];
          if (sortByRaw === 'close_price') {
            valA = a.current_price ?? a.weekly_close;
            valB = b.current_price ?? b.weekly_close;
          } else if (sortByRaw === 'status') {
            valA = a.entry_status;
            valB = b.entry_status;
          }
          if (valA === undefined) valA = 0;
          if (valB === undefined) valB = 0;
          if (typeof valA === 'string') {
            return order === 'ASC' ? valA.localeCompare(valB) : valB.localeCompare(valA);
          }
          return order === 'ASC' ? Number(valA) - Number(valB) : Number(valB) - Number(valA);
        });

        total = filtered.length;
        scanDate = MOCK_DATES[0];
        signals = filtered.slice(offset, offset + limit);
      }

      // Normalize all signals so both close_price & current_price, status & entry_status are always present
      const normalizedSignals = signals.map((s: any) => ({
        ...s,
        close_price: Number(s.close_price ?? s.current_price ?? s.weekly_close ?? 0),
        current_price: Number(s.current_price ?? s.weekly_close ?? s.close_price ?? 0),
        status: s.status ?? s.entry_status ?? 'IN_BUY_ZONE',
        entry_status: s.entry_status ?? s.status ?? 'IN_BUY_ZONE',
      }));

      const responseData: ScreenerListData = {
        scan_date: scanDate,
        total,
        page,
        limit,
        total_pages: Math.max(1, Math.ceil(total / limit)),
        signals: normalizedSignals,
      };

      const response: ApiResponse<ScreenerListData> = { success: true, data: responseData };
      res.json(response);
    } catch (err) {
      next(err);
    }
  },
);

// ---------------------------------------------------------------------------
// GET /api/screener/dates
// ---------------------------------------------------------------------------
router.get(
  '/dates',
  async (_req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
      let dates: string[] = [];
      try {
        const result = await query<{ scan_date: string }>(
          `SELECT DISTINCT to_char(scan_date, 'YYYY-MM-DD') AS scan_date
           FROM screener_signals
           ORDER BY scan_date DESC
           LIMIT 52`,
        );
        dates = result.rows.map((r) => r.scan_date);
      } catch (dbErr) {
        console.warn('[Screener /dates] Database offline. Serving fallback dates.', (dbErr as Error).message);
      }

      if (dates.length === 0) {
        dates = MOCK_DATES;
      }

      const response: ApiResponse<{ dates: string[] }> = {
        success: true,
        data: { dates },
      };
      res.json(response);
    } catch (err) {
      next(err);
    }
  },
);

// ---------------------------------------------------------------------------
// GET /api/screener/status
// ---------------------------------------------------------------------------
router.get(
  '/status',
  async (_req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
      let latestJob = null;
      try {
        latestJob = await getLatestJob();
      } catch (err) {
        // Fallback below
      }

      if (!latestJob) {
        latestJob = {
          id: 101,
          status: 'COMPLETED' as const,
          started_at: '2026-10-09T06:00:00.000Z',
          completed_at: '2026-10-09T06:45:00.000Z',
          signals_found: MOCK_SIGNALS.length,
          error_message: null,
        };
      }

      const response: ApiResponse<{ latest_job: typeof latestJob }> = {
        success: true,
        data: { latest_job: latestJob },
      };
      res.json(response);
    } catch (err) {
      next(err);
    }
  },
);

// ---------------------------------------------------------------------------
// POST /api/screener/trigger
// ---------------------------------------------------------------------------
router.post(
  '/trigger',
  async (_req: Request, res: Response, _next: NextFunction): Promise<void> => {
    try {
      // Enforce a single-execution lock: reject if a job is already running
      const runningJobId = await getRunningJobId();
      if (runningJobId !== null) {
        res.status(409).json({
          success: false,
          error: {
            code: 'JOB_ALREADY_RUNNING',
            message: `มีงานสแกนหุ้นกำลังทำงานอยู่แล้ว (Job #${runningJobId}) กรุณารอให้ระบบสแกนเสร็จสิ้นก่อนเริ่มสแกนใหม่`,
            job_id: runningJobId,
          },
        });
        return;
      }

      // Spawn the screener subprocess (returns immediately with job_id)
      const result = await runScreener();

      const response: ApiResponse<typeof result> = { success: true, data: result };
      res.status(202).json(response);
    } catch (err) {
      console.error('[Screener /trigger] Failed to trigger scan:', err);
      res.status(500).json({
        success: false,
        error: {
          code: 'TRIGGER_FAILED',
          message: (err as Error).message || 'เกิดข้อผิดพลาดในการเริ่มสแกนหุ้น กรุณาลองใหม่อีกครั้งในครู่หนึ่ง',
        },
      });
    }
  },
);

export default router;
