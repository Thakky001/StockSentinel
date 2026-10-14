/**
 * Screener runner service for StockSentinel.
 *
 * Manages spawning the Python screener subprocess and persists
 * execution results to the scan_jobs table.
 *
 * Design decisions:
 * - Uses Node.js child_process.spawn (not exec) for streaming stdout/stderr
 *   without buffering the entire output in memory.
 * - The job_id inserted into scan_jobs before spawn is returned immediately
 *   in the 202 response so the frontend can poll /api/screener/status.
 * - stdout / stderr are accumulated (capped at 64 KB) for error_message storage.
 * - The module is stateless: the database is the source of truth for job state.
 */

import { spawn } from 'child_process';
import path from 'path';
import { query } from '../db/pool';
import { ScanJob } from '../types';

import fs from 'fs';

/** In-memory tracking of the latest scan job for offline/zero-DB resilience */
let activeMemoryJob: ScanJob | null = null;

/** Configuration options for running the screener */
export interface RunScreenerOptions {
  /** Python executable (default: process.env.PYTHON_CMD ?? 'python') */
  pythonCmd?: string;
  /** Root directory of the StockSentinel project (default: process.env.SCREENER_ROOT ?? '../') */
  screenerRoot?: string;
}

/** Result returned immediately (before the scan completes) */
export interface RunScreenerResult {
  job_id: number;
  status: 'RUNNING';
  message: string;
  started_at: string;
}

/**
 * Insert a new RUNNING scan_job row and spawn the Python screener subprocess.
 * Stdout/stderr are streamed; the scan_job row is updated on completion.
 *
 * @param options - Optional overrides for python command and screener root path
 * @returns RunScreenerResult with the new job_id and start timestamp
 */
export async function runScreener(options: RunScreenerOptions = {}): Promise<RunScreenerResult> {
  const pythonCmd = options.pythonCmd ?? process.env.PYTHON_CMD ?? 'python';
  const screenerRoot = options.screenerRoot ?? process.env.SCREENER_ROOT ?? path.resolve('../');

  // 1. Insert a RUNNING job row and get back the generated id + timestamp
  let jobId = Math.floor(Date.now() / 1000);
  let startedAt = new Date().toISOString();

  try {
    const insertResult = await query<{ id: number; started_at: string }>(
      `INSERT INTO scan_jobs (job_type, status, started_at)
       VALUES ('WEEKLY_SCREENER', 'RUNNING', NOW())
       RETURNING id, to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at`,
    );

    const row = insertResult.rows[0];
    if (row) {
      jobId = row.id;
      startedAt = row.started_at;
    }
  } catch (err) {
    // DB offline - in memory job will handle tracking
  }

  activeMemoryJob = {
    id: jobId,
    job_type: 'WEEKLY_SCREENER',
    status: 'RUNNING',
    started_at: startedAt,
    completed_at: null,
    tickers_total: 142,
    tickers_processed: 0,
    tickers_failed: 0,
    signals_found: 0,
    error_message: null,
    telegram_alert_sent: false,
    created_at: startedAt,
  };

  // 2. Spawn the Python process asynchronously — do NOT await
  void spawnAndTrack({ pythonCmd, screenerRoot, jobId });

  return {
    job_id: jobId,
    status: 'RUNNING',
    message: `Screener job #${jobId} started successfully.`,
    started_at: startedAt,
  };
}

/** @internal Spawn the Python subprocess and update scan_jobs on completion */
async function spawnAndTrack(params: {
  pythonCmd: string;
  screenerRoot: string;
  jobId: number;
}): Promise<void> {
  const { pythonCmd, screenerRoot, jobId } = params;

  console.log(`[ScreenerRunner] Spawning job #${jobId}: ${pythonCmd} -m screener.src.main --mode screen (cwd: ${screenerRoot})`);

  const child = spawn(pythonCmd, ['-m', 'screener.src.main', '--mode', 'screen'], {
    cwd: screenerRoot,
    env: {
      ...process.env,
      PYTHONPATH: screenerRoot,
      PYTHONUNBUFFERED: '1',
    },
    // Do not detach — we want to track exit
  });

  /** Buffer stderr for error_message storage (capped at 64 KB) */
  const MAX_BUFFER = 64 * 1024;
  let stderrBuffer = '';
  let stdoutBuffer = '';

  child.stdout.on('data', (chunk: Buffer) => {
    const text = chunk.toString();
    process.stdout.write(`[Screener #${jobId}] ${text}`);
    if (stdoutBuffer.length < MAX_BUFFER) {
      stdoutBuffer += text;
    }
  });

  child.stderr.on('data', (chunk: Buffer) => {
    const text = chunk.toString();
    process.stderr.write(`[Screener #${jobId} ERR] ${text}`);
    if (stderrBuffer.length < MAX_BUFFER) {
      stderrBuffer += text;
    }
  });

  // Wait for the process to exit
  await new Promise<void>((resolve) => {
    child.on('error', async (err) => {
      console.error(`[ScreenerRunner] Job #${jobId} spawn error:`, err.message);
      await markJobFailed(jobId, err.message);
      resolve();
    });

    child.on('close', async (code, signal) => {
      if (code === 0) {
        console.log(`[ScreenerRunner] Job #${jobId} completed successfully (exit 0).`);
        await markJobCompleted(jobId);
        let signalsFound = 0;
        try {
          const candidates = [
            path.resolve('/app/screener/data/latest_signals.json'),
            path.resolve(__dirname, '../../../screener/data/latest_signals.json'),
            path.resolve(__dirname, '../../screener/data/latest_signals.json'),
            path.resolve(process.cwd(), 'screener/data/latest_signals.json'),
          ];
          for (const cp of candidates) {
            if (fs.existsSync(cp)) {
              const parsed = JSON.parse(fs.readFileSync(cp, 'utf-8'));
              signalsFound = parsed.signals?.length || parsed.signals_found || 0;
              break;
            }
          }
        } catch (_) {}
        if (activeMemoryJob && activeMemoryJob.id === jobId) {
          activeMemoryJob.status = 'COMPLETED';
          activeMemoryJob.completed_at = new Date().toISOString();
          activeMemoryJob.signals_found = signalsFound;
        }
      } else {
        const reason =
          signal != null
            ? `Killed by signal ${signal}`
            : `Exited with code ${code}. Stderr: ${stderrBuffer.slice(-2000)}`;
        console.error(`[ScreenerRunner] Job #${jobId} failed: ${reason}`);
        await markJobFailed(jobId, reason);
        if (activeMemoryJob && activeMemoryJob.id === jobId) {
          activeMemoryJob.status = 'FAILED';
          activeMemoryJob.completed_at = new Date().toISOString();
          activeMemoryJob.error_message = reason;
        }
      }
      resolve();
    });
  });
}

/** Update the scan_job row to COMPLETED status */
async function markJobCompleted(jobId: number): Promise<void> {
  try {
    await query(
      `UPDATE scan_jobs
       SET status = 'COMPLETED', completed_at = NOW()
       WHERE id = $1`,
      [jobId],
    );
  } catch (err) {
    // Handled in memory fallback
  }
}

/** Update the scan_job row to FAILED status with error message */
async function markJobFailed(jobId: number, errorMessage: string): Promise<void> {
  try {
    await query(
      `UPDATE scan_jobs
       SET status = 'FAILED', completed_at = NOW(), error_message = $2
       WHERE id = $1`,
      [jobId, errorMessage.slice(0, 4096)],
    );
  } catch (err) {
    // Handled in memory fallback
  }
}

/**
 * Check whether any scan_job is currently in RUNNING state.
 * Used by the trigger endpoint to enforce a single-execution lock.
 *
 * @returns The running job id, or null if none is active
 */
export async function getRunningJobId(): Promise<number | null> {
  if (activeMemoryJob && activeMemoryJob.status === 'RUNNING') {
    return activeMemoryJob.id;
  }
  try {
    const result = await query<{ id: number }>(
      `SELECT id FROM scan_jobs WHERE status = 'RUNNING' LIMIT 1`,
    );
    return result.rows[0]?.id ?? null;
  } catch (_err) {
    return null;
  }
}

/**
 * Fetch the latest scan_job row regardless of status.
 * Used by GET /api/screener/status.
 *
 * @returns The latest ScanJob row or null if the table is empty
 */
export async function getLatestJob(): Promise<ScanJob | null> {
  if (activeMemoryJob && activeMemoryJob.status === 'RUNNING') {
    return activeMemoryJob;
  }
  try {
    const result = await query<ScanJob>(
      `SELECT * FROM scan_jobs ORDER BY id DESC LIMIT 1`,
    );
    if (result.rows[0]) {
      return result.rows[0];
    }
  } catch (_err) {
    // Handled via memory fallback
  }
  return activeMemoryJob;
}
