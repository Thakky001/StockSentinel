/**
 * Screener routes — /api/screener/*
 *
 * Endpoints:
 *   GET  /api/screener/latest   — paginated, filtered list of the latest signals
 *   GET  /api/screener/dates    — list of distinct scan dates (last 52)
 *   GET  /api/screener/status   — latest scan_jobs row
 *   POST /api/screener/trigger  — spawn Python screener with process lock
 */

import fs from 'fs';
import path from 'path';
import { Router, Request, Response, NextFunction } from 'express';
import { query } from '../db/pool';
import { ScreenerSignal, ApiResponse, ScreenerListData } from '../types';
import { getRunningJobId, getLatestJob, runScreener } from '../services/screenerRunner';
import { MOCK_DATES, MOCK_SIGNALS } from '../db/mockDb';

const router = Router();

/**
 * Normalizes any Date object or ISO timestamp string into YYYY-MM-DD format.
 */
function toDateOnlyString(val: any): string {
  if (!val) return '';
  if (val instanceof Date) {
    const year = val.getFullYear();
    const month = String(val.getMonth() + 1).padStart(2, '0');
    const day = String(val.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }
  const str = String(val);
  return str.includes('T') ? str.split('T')[0] : str.slice(0, 10);
}

/**
 * Loads the latest screened signals from the local JSON persistence file.
 * Used when PostgreSQL is offline or when running in standalone mode.
 */
function loadLatestSignalsFromFile(): { scan_date: string; market_regime?: string; signals: ScreenerSignal[] } | null {
  const jsonPaths = [
    path.resolve('/app/screener/data/latest_signals.json'),
    path.resolve(__dirname, '../../../screener/data/latest_signals.json'),
    path.resolve(__dirname, '../../screener/data/latest_signals.json'),
    path.resolve(process.cwd(), 'screener/data/latest_signals.json'),
    path.resolve(process.cwd(), '../screener/data/latest_signals.json'),
  ];

  for (const p of jsonPaths) {
    if (fs.existsSync(p)) {
      try {
        const raw = fs.readFileSync(p, 'utf-8');
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed.signals) && parsed.signals.length > 0) {
          return {
            scan_date: toDateOnlyString(parsed.scan_date ?? '2026-10-16'),
            market_regime: parsed.market_regime ?? 'CAUTION_MARKET',
            signals: parsed.signals,
          };
        }
      } catch (err) {
        console.warn(`[Screener] Failed to parse ${p}:`, err);
      }
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Whitelist of columns that are safe to use in ORDER BY to prevent SQL injection
// ---------------------------------------------------------------------------
const SORT_COLUMN_MAP: Record<string, string> = {
  quality_score: 's.quality_score',
  quality_grade: 's.quality_grade',
  mrs_score: 's.mrs_score',
  diff_pct: 's.diff_pct',
  entry_price: 's.entry_price',
  max_buy_price: 's.max_buy_price',
  stop_loss_price: 's.stop_loss_price',
  volume_surge_ratio: 's.volume_surge_ratio',
  sma_30w: 's.sma_30w',
  sma_30w_slope: 's.sma_30w_slope',
  sma_10w: 's.sma_10w',
  base_tightness_pct: 's.base_tightness_pct',
  atr_14w: 's.atr_14w',
  weekly_close: 's.weekly_close',
  close_price: 's.current_price',
  current_price: 's.current_price',
  status: 's.entry_status',
  entry_status: 's.entry_status',
  scan_date: 's.scan_date',
  ticker: 's.ticker',
  market_cap: 'st.market_cap',
  recommended_shares: 's.recommended_shares',
  peak_gain_pct: 's.peak_gain_pct',
  highest_price_since_entry: 's.highest_price_since_entry',
  earnings_warning: 's.earnings_warning',
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

      // Sort validation — default quality_score DESC
      const sortByRaw = (req.query.sort_by as string) || 'quality_score';
      const sortColumn = Object.prototype.hasOwnProperty.call(SORT_COLUMN_MAP, sortByRaw)
        ? SORT_COLUMN_MAP[sortByRaw]
        : 's.quality_score';

      const orderRaw = ((req.query.order as string) || 'DESC').toUpperCase();
      const order = orderRaw === 'ASC' ? 'ASC' : 'DESC';

      const pageRaw = parseInt((req.query.page as string) || '1', 10);
      const page = Math.max(1, isNaN(pageRaw) ? 1 : pageRaw);
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
            to_char(s.scan_date, 'YYYY-MM-DD') AS scan_date,
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
            COALESCE(s.quality_score, 0.0) AS quality_score,
            COALESCE(s.quality_grade, 'B') AS quality_grade,
            s.sma_30w,
            s.sma_30w_slope,
            s.prior_resistance_35w,
            s.weekly_close,
            s.weekly_volume,
            s.avg_volume_10w,
            s.stage,
            s.sma_10w,
            s.base_tightness_pct,
            s.atr_14w,
            s.market_regime,
            s.recommended_shares,
            s.active_stop_loss,
            s.highest_price_since_entry,
            s.peak_gain_pct,
            s.earnings_warning,
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
          ORDER BY ${sortColumn} ${order} NULLS LAST, s.quality_score DESC NULLS LAST, s.mrs_score DESC
          LIMIT $5 OFFSET $6
        `;

        const result = await query<ScreenerSignal & { total_count: string; market_regime?: string }>(sql, [
          dateParam,
          sector,
          status,
          search,
          limit,
          offset,
        ]);

        if (result.rows.length > 0) {
          total = parseInt(result.rows[0].total_count, 10);
          scanDate = toDateOnlyString(result.rows[0].scan_date ?? scanDate);
          signals = result.rows.map(({ total_count: _, ...row }) => row);
        }
      } catch (dbErr: any) {
        if (!dbErr?.message?.includes('Database offline')) {
          console.warn('[Screener /latest] Database notice:', dbErr?.message);
        }
      }

      let marketRegime: any = signals[0]?.market_regime;

      // If database is offline or empty, use local JSON file signals before falling back to MOCK_SIGNALS
      if (signals.length === 0) {
        const fileData = loadLatestSignalsFromFile();
        const baseSignals = fileData ? fileData.signals : MOCK_SIGNALS;
        if (fileData) {
          scanDate = toDateOnlyString(fileData.scan_date);
          marketRegime = fileData.market_regime ?? marketRegime;
        }

        let filtered = [...baseSignals];
        if (sector) filtered = filtered.filter((s) => s.sector === sector);
        if (status) filtered = filtered.filter((s) => s.entry_status === status);
        if (search) {
          const q = search.toLowerCase();
          filtered = filtered.filter((s) => s.ticker.toLowerCase().includes(q) || (s.name ? s.name.toLowerCase().includes(q) : false));
        }

        // Apply sorting to signals
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
          if (valA === undefined || valA === null) valA = order === 'ASC' ? Infinity : -Infinity;
          if (valB === undefined || valB === null) valB = order === 'ASC' ? Infinity : -Infinity;
          if (typeof valA === 'string' && typeof valB === 'string') {
            return order === 'ASC' ? valA.localeCompare(valB) : valB.localeCompare(valA);
          }
          return order === 'ASC' ? Number(valA) - Number(valB) : Number(valB) - Number(valA);
        });

        total = filtered.length;
        if (!fileData) {
          scanDate = MOCK_DATES[0];
        }
        signals = filtered.slice(offset, offset + limit);
      }

      if (!marketRegime) {
        marketRegime = 'CAUTION_MARKET';
      }

      // Normalize all signals so both close_price & current_price, status & entry_status are always present
      const normalizedSignals = signals.map((s: any) => ({
        ...s,
        scan_date: toDateOnlyString(s.scan_date),
        close_price: Number(s.close_price ?? s.current_price ?? s.weekly_close ?? 0),
        current_price: Number(s.current_price ?? s.weekly_close ?? s.close_price ?? 0),
        status: s.status ?? s.entry_status ?? 'IN_BUY_ZONE',
        entry_status: s.entry_status ?? s.status ?? 'IN_BUY_ZONE',
        sma_10w: s.sma_10w ? Number(s.sma_10w) : null,
        base_tightness_pct: s.base_tightness_pct ? Number(s.base_tightness_pct) : null,
        atr_14w: s.atr_14w ? Number(s.atr_14w) : null,
        quality_score: s.quality_score !== undefined && s.quality_score !== null ? Number(s.quality_score) : 0,
        quality_grade: s.quality_grade ?? 'B',
        initial_breakout_score: s.initial_breakout_score !== undefined && s.initial_breakout_score !== null ? Number(s.initial_breakout_score) : null,
        current_action_score: s.current_action_score !== undefined && s.current_action_score !== null ? Number(s.current_action_score) : null,
        score_badge: s.score_badge ?? null,
        score_breakdown: typeof s.score_breakdown === 'string' ? (() => { try { return JSON.parse(s.score_breakdown); } catch (_) { return null; } })() : (s.score_breakdown ?? null),
        market_regime: s.market_regime ?? marketRegime,
        recommended_shares: s.recommended_shares
          ? Number(s.recommended_shares)
          : (() => {
              const currentP = Number(s.current_price || s.weekly_close || 1);
              const stopP = Number(s.stop_loss_price || currentP * 0.92);
              const riskPerShare = currentP - stopP;
              const maxCapShares = Math.floor(2000 / Math.max(currentP, 0.01));
              if (riskPerShare > 0) {
                return Math.max(1, Math.min(Math.floor(100 / riskPerShare), maxCapShares));
              }
              return Math.max(1, maxCapShares);
            })(),
      }));

      const responseData: ScreenerListData = {
        scan_date: toDateOnlyString(scanDate),
        market_regime: marketRegime,
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
      } catch (dbErr: any) {
        if (!dbErr?.message?.includes('Database offline')) {
          console.warn('[Screener /dates] Database notice:', dbErr?.message);
        }
      }

      if (dates.length === 0) {
        const fileData = loadLatestSignalsFromFile();
        if (fileData?.scan_date) {
          dates = [fileData.scan_date];
        } else {
          dates = MOCK_DATES;
        }
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
        const fileData = loadLatestSignalsFromFile();
        latestJob = {
          id: 101,
          status: 'COMPLETED' as const,
          started_at: '2026-10-09T06:00:00.000Z',
          completed_at: '2026-10-09T06:45:00.000Z',
          signals_found: fileData ? fileData.signals.length : MOCK_SIGNALS.length,
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
