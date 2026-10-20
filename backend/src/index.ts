/**
 * StockSentinel Backend — Server Entry Point
 *
 * Starts the Express HTTP server on PORT (default 3001).
 * Implements graceful shutdown on SIGTERM / SIGINT so in-flight requests
 * complete and the database connection pool is drained cleanly.
 */

import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';

// Load env vars robustly before importing anything that reads them (app, pool, etc.)
const envCandidates = [
  path.resolve(__dirname, '../../.env'),
  path.resolve(process.cwd(), '.env'),
  path.resolve(process.cwd(), '../.env'),
];
for (const envP of envCandidates) {
  if (fs.existsSync(envP)) {
    dotenv.config({ path: envP });
    break;
  }
}

import http from 'http';
import app from './app';
import { pool, initDatabaseSchemaIfNeeded } from './db/pool';
import cron from 'node-cron';
import { runScreener, getRunningJobId } from './services/screenerRunner';

const PORT = parseInt(process.env.PORT ?? '3001', 10);

// Create the HTTP server (wrapping Express)
const server = http.createServer(app);

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------
server.listen(PORT, '0.0.0.0', () => {
  console.log(`[StockSentinel] Server running on http://0.0.0.0:${PORT}`);
  console.log(`[StockSentinel] NODE_ENV = ${process.env.NODE_ENV ?? 'development'}`);
  console.log(`[StockSentinel] CORS origins: ${process.env.CORS_ORIGIN ?? 'http://localhost:5173'}`);

  // Auto-initialize PostgreSQL tables if database is connected
  initDatabaseSchemaIfNeeded().catch((err) => {
    console.warn('[StockSentinel] DB auto-init skipped:', err.message);
  });

  // Automated Weekly Screener Scheduler (Runs inside Render container)
  // Since server is kept awake 24/7 via Uptime monitor, this triggers every Saturday at 08:00 AM Bangkok time.
  cron.schedule('0 8 * * 6', async () => {
    console.log('[Scheduler] Triggering automated weekly Stage 2 stock screener (Asia/Bangkok 08:00 AM)...');
    const running = getRunningJobId();
    if (running !== null) {
      console.warn(`[Scheduler] Job #${running} is already running. Skipping this trigger.`);
      return;
    }
    try {
      const result = await runScreener();
      console.log(`[Scheduler] Weekly screener job #${result.job_id} initiated successfully.`);
    } catch (err: any) {
      console.error('[Scheduler] Failed to trigger weekly screener:', err?.message || err);
    }
  }, {
    timezone: 'Asia/Bangkok'
  });
  console.log('[StockSentinel] Internal Weekly Screener Scheduler active (Every Saturday at 08:00 AM Asia/Bangkok)');
});

// ---------------------------------------------------------------------------
// Graceful Shutdown
// ---------------------------------------------------------------------------
/**
 * Gracefully shut down the server:
 *   1. Stop accepting new connections.
 *   2. Wait for in-flight requests to finish (30-second timeout).
 *   3. Drain the pg connection pool.
 *   4. Exit.
 */
async function gracefulShutdown(signal: string): Promise<void> {
  console.log(`\n[StockSentinel] ${signal} received — starting graceful shutdown…`);

  await new Promise<void>((resolve, reject) => {
    server.close((err) => {
      if (err) {
        console.error('[StockSentinel] Error closing HTTP server:', err.message);
        return reject(err);
      }
      console.log('[StockSentinel] HTTP server closed.');
      resolve();
    });

    // Force-close after 30 seconds if requests are still in-flight
    setTimeout(() => {
      console.warn('[StockSentinel] Forced shutdown after 30s timeout.');
      resolve();
    }, 30_000);
  });

  try {
    await pool.end();
    console.log('[StockSentinel] Database pool drained.');
  } catch (err) {
    console.error('[StockSentinel] Error draining pool:', err);
  }

  console.log('[StockSentinel] Shutdown complete. Goodbye.');
  process.exit(0);
}

process.on('SIGTERM', () => void gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => void gracefulShutdown('SIGINT'));

// Catch unhandled promise rejections — log and exit with code 1 so the process
// manager (Docker, PM2, etc.) can restart the service automatically.
process.on('unhandledRejection', (reason) => {
  console.error('[StockSentinel] Unhandled rejection:', reason);
  process.exit(1);
});
