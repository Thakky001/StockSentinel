/**
 * StockSentinel Backend — Server Entry Point
 *
 * Starts the Express HTTP server on PORT (default 3001).
 * Implements graceful shutdown on SIGTERM / SIGINT so in-flight requests
 * complete and the database connection pool is drained cleanly.
 */

import dotenv from 'dotenv';

// Load env vars before importing anything that reads them (app, pool, etc.)
dotenv.config({ path: '../.env' });

import http from 'http';
import app from './app';
import { pool, initDatabaseSchemaIfNeeded } from './db/pool';

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
