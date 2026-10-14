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
    console.warn('[ScreenerRunner] scan_jobs table not ready or DB offline, using memory job id:', (err as Error).message);
  }

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
  const scriptPath = path.join(screenerRoot, 'screener', 'src', 'main.py');

  console.log(`[ScreenerRunner] Spawning job #${jobId}: ${pythonCmd} ${scriptPath} --mode screen`);

  const child = spawn(pythonCmd, [scriptPath, '--mode', 'screen'], {
    cwd: screenerRoot,
    env: { ...process.env },
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
      } else {
        const reason =
          signal != null
            ? `Killed by signal ${signal}`
            : `Exited with code ${code}. Stderr: ${stderrBuffer.slice(-2000)}`;
        console.error(`[ScreenerRunner] Job #${jobId} failed: ${reason}`);
        await markJobFailed(jobId, reason);
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
    console.error(`[ScreenerRunner] Failed to mark job #${jobId} as COMPLETED:`, err);
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
    console.error(`[ScreenerRunner] Failed to mark job #${jobId} as FAILED:`, err);
  }
}

/**
 * Check whether any scan_job is currently in RUNNING state.
 * Used by the trigger endpoint to enforce a single-execution lock.
 *
 * @returns The running job id, or null if none is active
 */
export async function getRunningJobId(): Promise<number | null> {
  try {
    const result = await query<{ id: number }>(
      `SELECT id FROM scan_jobs WHERE status = 'RUNNING' LIMIT 1`,
    );
    return result.rows[0]?.id ?? null;
  } catch (err) {
    console.warn('[ScreenerRunner] getRunningJobId notice (handled gracefully):', (err as Error).message);
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
  try {
    const result = await query<ScanJob>(
      `SELECT * FROM scan_jobs ORDER BY id DESC LIMIT 1`,
    );
    return result.rows[0] ?? null;
  } catch (err) {
    console.warn('[ScreenerRunner] getLatestJob notice (handled gracefully):', (err as Error).message);
    return null;
  }
}
