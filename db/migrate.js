#!/usr/bin/env node
/**
 * StockSentinel Database Migration Runner (Node.js)
 * Executes versioned SQL migrations in db/migrations/ against PostgreSQL.
 * Supports: direct execution or module export (runMigrations, showStatus, resetDatabase)
 */

const fs = require('fs');
const path = require('path');
const { Client } = require('pg');

function loadEnvFile(projectRoot) {
  for (const filename of ['.env', '.env.example']) {
    const envPath = path.join(projectRoot, filename);
    if (fs.existsSync(envPath)) {
      try {
        const content = fs.readFileSync(envPath, 'utf-8');
        for (const line of content.split('\n')) {
          const trimmed = line.trim();
          if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
            const idx = trimmed.indexOf('=');
            const k = trimmed.slice(0, idx).trim();
            const v = trimmed.slice(idx + 1).trim().replace(/^['"]|['"]$/g, '');
            if (!process.env[k]) {
              process.env[k] = v;
            }
          }
        }
      } catch (err) {
        // Ignore read errors
      }
    }
  }
}

async function getClient(customUrl = null) {
  const connectionString = customUrl || process.env.DATABASE_URL ||
    `postgresql://${process.env.POSTGRES_USER || 'postgres'}:${process.env.POSTGRES_PASSWORD || 'postgres'}@${process.env.DB_HOST || 'localhost'}:${process.env.DB_PORT || 5432}/${process.env.POSTGRES_DB || 'stocksentinel'}`;

  const client = new Client({ connectionString });
  await client.connect();
  return client;
}

async function initMigrationTable(client) {
  await client.query(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      id SERIAL PRIMARY KEY,
      version VARCHAR(64) NOT NULL UNIQUE,
      name VARCHAR(255) NOT NULL,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
  `);
}

async function runMigrations(customUrl = null) {
  const projectRoot = path.resolve(__dirname, '..');
  loadEnvFile(projectRoot);

  const migrationsDir = path.join(__dirname, 'migrations');
  const initSqlPath = path.join(__dirname, 'init.sql');

  // 1. Ensure migrations dir and baseline file exist
  if (!fs.existsSync(migrationsDir)) {
    fs.mkdirSync(migrationsDir, { recursive: true });
  }
  const baselineFile = path.join(migrationsDir, '001_initial_schema.sql');
  if (!fs.existsSync(baselineFile) && fs.existsSync(initSqlPath)) {
    fs.copyFileSync(initSqlPath, baselineFile);
  }

  const client = await getClient(customUrl);
  try {
    // 2. Ensure schema_migrations table exists
    await initMigrationTable(client);

    // 3. Get applied migrations
    const res = await client.query('SELECT version FROM schema_migrations;');
    const appliedVersions = new Set(res.rows.map(r => r.version));

    // 4. Read migration files
    const files = fs.readdirSync(migrationsDir)
      .filter(f => f.endsWith('.sql'))
      .sort();

    console.log(`[*] Found ${files.length} migration file(s) in ${migrationsDir}`);

    let appliedCount = 0;
    for (const file of files) {
      const version = file.split('_')[0];
      const name = path.basename(file, '.sql');

      if (appliedVersions.has(version)) {
        console.log(`[x] Migration ${file} already applied. Skipping.`);
        continue;
      }

      console.log(`[>] Applying migration: ${file}...`);
      const sql = fs.readFileSync(path.join(migrationsDir, file), 'utf-8');

      await client.query('BEGIN');
      try {
        await client.query(sql);
        await client.query(
          'INSERT INTO schema_migrations (version, name) VALUES ($1, $2) ON CONFLICT (version) DO NOTHING;',
          [version, name]
        );
        await client.query('COMMIT');
        console.log(`[✓] Successfully applied: ${file}`);
        appliedCount += 1;
      } catch (err) {
        await client.query('ROLLBACK');
        console.error(`[!] Failed to apply migration ${file}:`, err);
        throw err;
      }
    }
    console.log(`[✓] All migrations up to date. Newly applied: ${appliedCount}`);
  } finally {
    await client.end();
  }
}

async function showStatus(customUrl = null) {
  const projectRoot = path.resolve(__dirname, '..');
  loadEnvFile(projectRoot);

  const migrationsDir = path.join(__dirname, 'migrations');
  const client = await getClient(customUrl);

  try {
    await initMigrationTable(client);
    const res = await client.query('SELECT version FROM schema_migrations;');
    const applied = new Set(res.rows.map(r => r.version));
    const files = fs.readdirSync(migrationsDir).filter(f => f.endsWith('.sql')).sort();

    console.log('\n--- Migration Status ---');
    for (const f of files) {
      const version = f.split('_')[0];
      const status = applied.has(version) ? 'APPLIED' : 'PENDING';
      console.log(`[${status.padEnd(7)}] ${f}`);
    }
    console.log('------------------------\n');
  } finally {
    await client.end();
  }
}

async function resetDatabase(customUrl = null) {
  const projectRoot = path.resolve(__dirname, '..');
  loadEnvFile(projectRoot);

  const client = await getClient(customUrl);
  try {
    console.log('[!] Dropping all application tables...');
    await client.query(`
      DROP TABLE IF EXISTS screener_signals CASCADE;
      DROP TABLE IF EXISTS stock_daily_bars CASCADE;
      DROP TABLE IF EXISTS scan_jobs CASCADE;
      DROP TABLE IF EXISTS stocks CASCADE;
      DROP TABLE IF EXISTS schema_migrations CASCADE;
    `);
    console.log('[✓] All tables dropped.');
  } finally {
    await client.end();
  }
}

if (require.main === module) {
  const args = process.argv.slice(2);
  const isStatus = args.includes('--status');
  const isReset = args.includes('--reset') || args.includes('--force-reset');

  if (isReset) {
    resetDatabase().catch(err => {
      console.error('Database reset failed:', err);
      process.exit(1);
    });
  } else if (isStatus) {
    showStatus().catch(err => {
      console.error('Status check failed:', err);
      process.exit(1);
    });
  } else {
    runMigrations().catch(err => {
      console.error('Migration failed:', err);
      process.exit(1);
    });
  }
}

module.exports = { runMigrations, showStatus, resetDatabase, getClient };
