"""
Bootstrap a local PostgreSQL database for development.

This script is intended to be called from `start.bat` before the backend
starts. It will:
- create the target database if it does not exist
- create any missing tables via `backend.database.init_db()`

It deliberately avoids seeding data so you can restore a data-only backup
into a clean local schema.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from psycopg2 import sql

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_DATABASE_URL = "postgresql://postgres@localhost:5432/FantasyDBLocal"
DEFAULT_ADMIN_DATABASE_URL = "postgresql://postgres@localhost:5432/postgres"

sys.path.insert(0, str(ROOT_DIR))


def _load_env_file(path: Path, override: bool = False) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


_load_env_file(ROOT_DIR / ".env")
_load_env_file(ROOT_DIR / ".env.local", override=True)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _is_postgres_url(database_url: str) -> bool:
    return database_url.startswith("postgres")


def _ensure_database_exists(database_url: str) -> None:
    parsed = urlparse(database_url)
    if not parsed.path or parsed.path == "/":
        raise ValueError("DATABASE_URL must include a database name")

    database_name = parsed.path.lstrip("/")
    admin_url = os.environ.get("POSTGRES_ADMIN_URL", "").strip() or urlunparse(
        parsed._replace(path="/postgres", query="", fragment="", params="")
    )

    import psycopg2

    try:
        conn = psycopg2.connect(admin_url)
        conn.autocommit = True
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
                exists = cursor.fetchone() is not None
                if exists:
                    print(f"[bootstrap] Database already exists: {database_name}")
                    return

                print(f"[bootstrap] Creating database: {database_name}")
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        finally:
            conn.close()
    except Exception as exc:
        raise RuntimeError(
            "Cannot reach the local PostgreSQL server on localhost:5432. "
            "Start PostgreSQL first in pgAdmin, Windows Services, or Docker, "
            f"then rerun start.bat. Original error: {exc}"
        ) from exc


def _reset_serial_sequence(conn, table_name: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_serial_sequence(%s, 'id')",
            (table_name,),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return

        sequence_name = row[0]
        cursor.execute(sql.SQL("SELECT COALESCE(MAX(id), 0) FROM {}").format(sql.Identifier(table_name)))
        max_id = int(cursor.fetchone()[0] or 0)
        cursor.execute(
            "SELECT setval(%s, %s, %s)",
            (sequence_name, max_id if max_id > 0 else 1, max_id > 0),
        )


def _seed_table_if_empty(source_conn: sqlite3.Connection, target_conn, table_name: str) -> None:
    if not _table_exists_postgres(target_conn, table_name):
        return

    if _table_row_count_postgres(target_conn, table_name) > 0:
        print(f"[bootstrap] {table_name}: already has rows, skipping")
        return

    rows = _fetch_rows_sqlite(source_conn, table_name)
    if not rows:
        print(f"[bootstrap] {table_name}: source has no rows, skipping")
        return

    columns = _table_columns_sqlite(source_conn, table_name)
    column_sql = ", ".join(columns)
    values_template = ", ".join(["%s"] * len(columns))
    query = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
        sql.Identifier(table_name),
        sql.SQL(column_sql),
    )

    with target_conn.cursor() as cursor:
        execute_values(cursor, query.as_string(target_conn), rows, template=f"({values_template})")

    if table_name in {"users", "user_teams"}:
        _reset_serial_sequence(target_conn, table_name)

    print(f"[bootstrap] {table_name}: seeded {len(rows)} rows")


def main() -> int:
    database_url = _database_url() or DEFAULT_LOCAL_DATABASE_URL
    if not database_url:
        print("[bootstrap] DATABASE_URL is not set, skipping local Postgres bootstrap")
        return 0

    if not _is_postgres_url(database_url):
        print("[bootstrap] DATABASE_URL is not Postgres, skipping local Postgres bootstrap")
        return 0

    os.environ.setdefault("POSTGRES_ADMIN_URL", DEFAULT_ADMIN_DATABASE_URL)

    _ensure_database_exists(database_url)

    os.environ["DATABASE_URL"] = database_url

    from backend.database import init_db

    print("[bootstrap] Ensuring schema exists")
    init_db()

    print("[bootstrap] Local Postgres bootstrap complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
