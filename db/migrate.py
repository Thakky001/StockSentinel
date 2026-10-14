#!/usr/bin/env python3
"""
StockSentinel Database Migration Runner (Python)
Executes versioned SQL migrations in db/migrations/ against PostgreSQL.
Supports: --up (default), --status, --reset, --db-url <URL>
"""

import os
import sys
import argparse
from pathlib import Path


def load_env_file(project_root: Path):
    """Load key-value pairs from .env or .env.example into os.environ if not already set."""
    for filename in [".env", ".env.example"]:
        env_path = project_root / filename
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass


def get_connection(db_url: str = None):
    """Establish and return a connection to PostgreSQL."""
    try:
        import psycopg2
    except ImportError:
        try:
            import psycopg as psycopg2
        except ImportError:
            raise RuntimeError(
                "Neither psycopg2 nor psycopg is installed. "
                "Please run: pip install psycopg2-binary"
            )

    url = db_url or os.environ.get(
        "DATABASE_URL",
        f"postgresql://{os.environ.get('POSTGRES_USER', 'postgres')}:{os.environ.get('POSTGRES_PASSWORD', 'postgres')}@"
        f"{os.environ.get('DB_HOST', 'localhost')}:{os.environ.get('DB_PORT', '5432')}/"
        f"{os.environ.get('POSTGRES_DB', 'stocksentinel')}"
    )
    return psycopg2.connect(url)


def init_migration_table(conn):
    """Ensure the schema_migrations tracking table exists."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                version VARCHAR(64) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
    conn.commit()


def get_applied_migrations(conn):
    """Return a set of already applied migration version strings."""
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
        return {row[0] for row in cur.fetchall()}


def run_migrations(conn, migrations_dir: Path):
    """Execute all pending SQL migrations in sequential alphabetical order."""
    init_migration_table(conn)
    applied = get_applied_migrations(conn)

    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        init_file = migrations_dir.parent / "init.sql"
        if init_file.exists():
            migration_files = [init_file]

    print(f"[*] Found {len(migration_files)} migration files in {migrations_dir}")

    applied_count = 0
    for f in migration_files:
        version = f.stem.split("_")[0]
        name = f.stem
        if version in applied:
            print(f"[x] Migration {f.name} already applied. Skipping.")
            continue

        print(f"[>] Applying migration: {f.name}...")
        with open(f, "r", encoding="utf-8") as sql_file:
            sql_content = sql_file.read()

        with conn.cursor() as cur:
            cur.execute(sql_content)
            cur.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (%s, %s) ON CONFLICT (version) DO NOTHING;",
                (version, name)
            )
        conn.commit()
        print(f"[✓] Successfully applied: {f.name}")
        applied_count += 1

    print(f"[✓] Migrations finished. Newly applied: {applied_count}, Total files: {len(migration_files)}")


def show_status(conn, migrations_dir: Path):
    """Display migration status (APPLIED vs PENDING) for all migration scripts."""
    init_migration_table(conn)
    applied = get_applied_migrations(conn)
    migration_files = sorted(migrations_dir.glob("*.sql"))

    print("\n--- Migration Status ---")
    for f in migration_files:
        version = f.stem.split("_")[0]
        status = "APPLIED" if version in applied else "PENDING"
        print(f"[{status:7s}] {f.name}")
    print("------------------------\n")


def reset_database(conn):
    """Drop all tables in safe reverse-dependency order."""
    with conn.cursor() as cur:
        print("[!] Dropping all application tables...")
        cur.execute("""
            DROP TABLE IF EXISTS screener_signals CASCADE;
            DROP TABLE IF EXISTS stock_daily_bars CASCADE;
            DROP TABLE IF EXISTS scan_jobs CASCADE;
            DROP TABLE IF EXISTS stocks CASCADE;
            DROP TABLE IF EXISTS schema_migrations CASCADE;
        """)
    conn.commit()
    print("[✓] All tables dropped.")


def main():
    parser = argparse.ArgumentParser(description="StockSentinel Database Migration Runner (Python)")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--reset", action="store_true", help="Drop all tables")
    parser.add_argument("--force-reset", action="store_true", help="Drop all tables without confirmation prompt")
    parser.add_argument("--db-url", type=str, default=None, help="Database connection URL")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    project_root = base_dir.parent
    load_env_file(project_root)

    migrations_dir = base_dir / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)

    # Ensure baseline migration 001_initial_schema.sql exists
    init_sql = base_dir / "init.sql"
    first_migration = migrations_dir / "001_initial_schema.sql"
    if init_sql.exists() and not first_migration.exists():
        first_migration.write_text(init_sql.read_text(encoding="utf-8"), encoding="utf-8")

    try:
        conn = get_connection(args.db_url)
    except Exception as exc:
        print(f"[-] Database connection could not be established: {exc}")
        print("[-] Check that PostgreSQL is running and credentials match .env/.env.example")
        sys.exit(1)

    try:
        if args.reset or args.force_reset:
            if not args.force_reset:
                confirm = input("Are you sure you want to drop all tables? (yes/no): ")
                if confirm.lower() != "yes":
                    print("Reset aborted.")
                    return
            reset_database(conn)
        elif args.status:
            show_status(conn, migrations_dir)
        else:
            run_migrations(conn, migrations_dir)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
