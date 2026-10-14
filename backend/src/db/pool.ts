/**
 * PostgreSQL connection pool for StockSentinel backend.
 *
 * Supports both DATABASE_URL (connection string) and individual
 * DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD env vars.
 * Falls back to reasonable defaults for local development.
 */

import { Pool, PoolConfig, QueryResult, QueryResultRow } from 'pg';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';

// Load environment variables from the root .env file (one level up from backend/)
dotenv.config({ path: '../.env' });

/** Normalize short Render internal hostnames to FQDN so DNS resolution never fails */
function fixRenderDatabaseUrl(url: string): string {
  if (!url) return url;
  return url.replace(/@(dpg-[a-z0-9]+-[a-z0-9]+)([:\/])/i, (match, host, suffix) => {
    if (!host.includes('.')) {
      const region = process.env.RENDER_REGION ?? 'singapore';
      return `@${host}.${region}-postgres.render.com${suffix}`;
    }
    return match;
  });
}

/** Clean and prepare database URL for cloud and local environments */
function cleanDatabaseUrl(rawUrl: string): string {
  if (!rawUrl) return rawUrl;
  let url = fixRenderDatabaseUrl(rawUrl);
  // Strip any sslmode parameter so pg-connection-string does NOT wipe out our rejectUnauthorized: false option
  url = url.replace(/([?&])sslmode=[^&]+/gi, '$1').replace(/[?&]$/, '');
  return url;
}

/** Build pool configuration from environment variables */
function buildPoolConfig(): PoolConfig {
  let databaseUrl = process.env.DATABASE_URL;

  if (databaseUrl) {
    const isCloud =
      databaseUrl.includes('.render.com') ||
      databaseUrl.includes('dpg-') ||
      databaseUrl.includes('neon.tech') ||
      databaseUrl.includes('supabase.co');

    databaseUrl = cleanDatabaseUrl(databaseUrl);

    return {
      connectionString: databaseUrl,
      ssl: isCloud || process.env.DATABASE_SSL === 'true' ? { rejectUnauthorized: false } : false,
      max: 5,
      idleTimeoutMillis: 10_000,
      connectionTimeoutMillis: 15_000,
      keepAlive: true,
      keepAliveInitialDelayMillis: 10_000,
    };
  }

  // Individual env vars
  return {
    host: process.env.DB_HOST ?? 'localhost',
    port: parseInt(process.env.DB_PORT ?? '5432', 10),
    database: process.env.POSTGRES_DB ?? process.env.DB_NAME ?? 'stocksentinel',
    user: process.env.POSTGRES_USER ?? process.env.DB_USER ?? 'postgres',
    password: process.env.POSTGRES_PASSWORD ?? process.env.DB_PASSWORD ?? 'postgres',
    ssl: process.env.DATABASE_SSL === 'true' ? { rejectUnauthorized: false } : false,
    max: 10,
    idleTimeoutMillis: 10_000,
    connectionTimeoutMillis: 10_000,
    keepAlive: true,
    keepAliveInitialDelayMillis: 10_000,
  };
}

/** Shared pg.Pool instance — created once and reused across the application lifetime */
export const pool = new Pool(buildPoolConfig());

// Log pool errors to prevent unhandled promise rejections
pool.on('error', (err) => {
  console.warn('[Pool] Idle client notice/error (handled gracefully):', err.message);
});

/**
 * Convenience query helper that acquires a client from the pool,
 * runs the query, then releases the client back automatically.
 * Includes automatic single-retry for transient cloud drops (e.g. Render/Neon).
 *
 * @param text  SQL statement (use $1, $2, … placeholders)
 * @param params  Positional parameter values
 * @returns Promise<QueryResult<R>>
 */
export async function query<R extends QueryResultRow = QueryResultRow>(
  text: string,
  params?: unknown[],
): Promise<QueryResult<R>> {
  const start = Date.now();
  let result: QueryResult<R>;

  try {
    result = await pool.query<R>(text, params);
  } catch (err: any) {
    const msg = String(err?.message || '');
    // Retry once if connection was dropped by cloud proxy timeout or idle reset
    if (
      msg.includes('Connection terminated') ||
      msg.includes('ECONNRESET') ||
      msg.includes('connection closed') ||
      msg.includes('socket has been ended') ||
      err?.code === '57P01' || // admin_shutdown
      err?.code === '08006'    // connection_failure
    ) {
      console.warn('[Pool] Transient connection drop detected, retrying query once...', msg);
      result = await pool.query<R>(text, params);
    } else {
      throw err;
    }
  }

  const duration = Date.now() - start;

  if (process.env.NODE_ENV !== 'production') {
    // Log slow queries (> 500 ms) in development for performance diagnostics
    if (duration > 500) {
      console.warn(`[Pool] Slow query (${duration}ms): ${text.slice(0, 120)}`);
    }
  }

  return result;
}

/**
 * Automatically initializes database tables from db/init.sql if not present.
 * Especially useful on Render where a fresh PostgreSQL instance is provisioned.
 */
export async function initDatabaseSchemaIfNeeded(): Promise<void> {
  try {
    const tableCheck = await query(
      `SELECT to_regclass('public.screener_signals') as exists;`
    );
    if (!tableCheck.rows[0]?.exists) {
      console.log('[Pool] Table screener_signals not found. Initializing schema from db/init.sql...');
      const sqlPaths = [
        path.resolve('/app/db/init.sql'),
        path.resolve(__dirname, '../../../db/init.sql'),
        path.resolve(__dirname, '../../db/init.sql'),
      ];

      for (const p of sqlPaths) {
        if (fs.existsSync(p)) {
          const sql = fs.readFileSync(p, 'utf-8');
          await query(sql);
          console.log('[Pool] Database schema initialized successfully from', p);
          break;
        }
      }
    }
  } catch (err) {
    console.warn('[Pool] Auto-schema initialization skipped or failed:', (err as Error).message);
  }
}

