"""
Copy the current local SQLite data into a local PostgreSQL database.

Usage:
    python -m backend.scripts.sync_sqlite_to_postgres

By default this expects a local Postgres instance at:
    postgresql://fantasy:fantasy@localhost:5432/fantasy_cricket

The script preserves the existing rows from backend/fantasy.db and copies
them into a separate local Postgres instance so you can test scenarios
without touching any live database.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Iterable

from psycopg2.extras import execute_values

# Allow running as ``python backend/scripts/sync_sqlite_to_postgres.py``.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

DEFAULT_POSTGRES_URL = "postgresql://fantasy:fantasy@localhost:5432/fantasy_cricket"
TABLE_ORDER = [
    "users",
    "players",
    "matches",
    "user_teams",
    "user_teams_audit",
    "contestant_points",
    "player_points",
    "team_backups",
    "unknown_players",
    "weekend_tournaments",
    "weekend_tournament_brackets",
]


def _table_names(source_conn: sqlite3.Connection) -> list[str]:
    rows = source_conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    names = [row[0] for row in rows]
    order_index = {name: index for index, name in enumerate(TABLE_ORDER)}
    return sorted(names, key=lambda name: (order_index.get(name, len(TABLE_ORDER)), name))


def _table_columns(source_conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = source_conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1] for row in rows]


def _fetch_rows(source_conn: sqlite3.Connection, table_name: str) -> list[tuple]:
    columns = _table_columns(source_conn, table_name)
    if not columns:
        return []
    placeholders = ", ".join(columns)
    rows = source_conn.execute(f"SELECT {placeholders} FROM {table_name}").fetchall()
    return [tuple(row) for row in rows]


def _truncate_target_tables(target_conn, table_names: Iterable[str]) -> None:
    names = list(table_names)
    if not names:
        return
    joined = ", ".join(names)
    target_conn.cursor().execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE")


def _reset_sequence(target_conn, table_name: str) -> None:
    cursor = target_conn.cursor()
    cursor.execute(
        "SELECT pg_get_serial_sequence(%s, 'id')",
        (table_name,),
    )
    row = cursor.fetchone()
    if not row:
        return
    sequence_name = row[0]
    if not sequence_name:
        return

    cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table_name}")
    max_id = cursor.fetchone()[0] or 0
    cursor.execute(
        "SELECT setval(%s, %s, %s)",
        (sequence_name, max_id if max_id > 0 else 1, max_id > 0),
    )


def _copy_table(source_conn: sqlite3.Connection, target_conn, table_name: str) -> int:
    columns = _table_columns(source_conn, table_name)
    if not columns:
        return 0

    rows = _fetch_rows(source_conn, table_name)
    if not rows:
        return 0

    column_sql = ", ".join(columns)
    values_template = ", ".join(["%s"] * len(columns))
    query = f"INSERT INTO {table_name} ({column_sql}) VALUES %s"
    execute_values(target_conn.cursor(), query, rows, template=f"({values_template})")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy local SQLite data into local Postgres.")
    parser.add_argument(
        "--source",
        default=None,
        help="Path to the SQLite database file. Defaults to backend/fantasy.db.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL") or DEFAULT_POSTGRES_URL,
        help="Postgres connection string for the target database.",
    )
    args = parser.parse_args()

    source_db = args.source or os.path.join(os.path.dirname(os.path.dirname(__file__)), "fantasy.db")
    if not os.path.exists(source_db):
        raise FileNotFoundError(f"SQLite source database not found: {source_db}")

    os.environ["DATABASE_URL"] = args.database_url

    from backend.database import init_db
    import psycopg2

    print(f"Using source SQLite: {source_db}")
    print(f"Using target Postgres: {args.database_url}")

    source_conn = sqlite3.connect(source_db)
    source_conn.row_factory = sqlite3.Row
    target_conn = psycopg2.connect(args.database_url)

    try:
        print("Initializing target schema ...")
        init_db()

        table_names = _table_names(source_conn)
        print(f"Found tables: {', '.join(table_names)}")

        print("Clearing target tables ...")
        _truncate_target_tables(target_conn, table_names)
        target_conn.commit()

        total_rows = 0
        for table_name in table_names:
            copied = _copy_table(source_conn, target_conn, table_name)
            if copied:
                print(f"  copied {copied} rows from {table_name}")
                total_rows += copied
            else:
                print(f"  skipped {table_name} (no rows)")

        target_conn.commit()

        for table_name in table_names:
            try:
                _reset_sequence(target_conn, table_name)
            except Exception:
                pass
        target_conn.commit()

        print(f"Done. Copied {total_rows} rows into Postgres.")
    finally:
        source_conn.close()
        target_conn.close()


if __name__ == "__main__":
    main()
