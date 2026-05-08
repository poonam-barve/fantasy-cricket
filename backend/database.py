"""
Database abstraction layer.
- Uses PostgreSQL if DATABASE_URL env var is set (production)
- Falls back to SQLite (local development)

All other files use `?` parameter style. This module wraps PostgreSQL
connections to translate `?` to `%s` automatically.
"""

import os
import re
import sqlite3
import threading
from backend.config import DATABASE_PATH

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_local = threading.local()


class PgRowDict(dict):
    """Dict that also supports attribute-style access like sqlite3.Row."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class PgCursorWrapper:
    """Wraps psycopg2 cursor to translate ? params to %s."""
    def __init__(self, cursor, conn):
        self._cursor = cursor
        self._conn = conn

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        self._cursor.execute(sql, params)
        return self

    def executescript(self, sql):
        # Split by semicolons and execute each
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._cursor.execute(stmt)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in self._cursor.description]
        return PgRowDict(zip(cols, row))

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows or not self._cursor.description:
            return []
        cols = [desc[0] for desc in self._cursor.description]
        return [PgRowDict(zip(cols, row)) for row in rows]

    @property
    def lastrowid(self):
        return self._cursor.fetchone()[0] if self._cursor.description else None

    @property
    def rowcount(self):
        return self._cursor.rowcount


class PgConnectionWrapper:
    """Wraps psycopg2 connection to behave like sqlite3.Connection."""
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._conn = _connect_postgres(dsn)

    def _is_closed(self) -> bool:
        return self._conn is None or bool(getattr(self._conn, "closed", 0))

    def _ensure_connection(self):
        if self._is_closed():
            self._conn = _connect_postgres(self._dsn)

    def _rollback_safely(self):
        try:
            if not self._is_closed():
                self._conn.rollback()
        except Exception:
            pass

    def execute(self, sql, params=None):
        self._ensure_connection()
        sql = sql.replace("?", "%s")
        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, params)
        except Exception as exc:
            self._rollback_safely()
            if _is_failed_transaction_postgres(exc):
                cursor = self._conn.cursor()
                cursor.execute(sql, params)
            elif _should_reconnect_postgres(exc):
                self._conn = _connect_postgres(self._dsn)
                cursor = self._conn.cursor()
                cursor.execute(sql, params)
            else:
                raise
        return PgCursorWrapper(cursor, self._conn)

    def executescript(self, sql):
        self._ensure_connection()
        try:
            cursor = self._conn.cursor()
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    cursor.execute(stmt)
            self._conn.commit()
        except Exception:
            self._rollback_safely()
            raise

    def commit(self):
        self._ensure_connection()
        try:
            self._conn.commit()
        except Exception:
            self._rollback_safely()
            raise

    def close(self):
        if self._conn is not None and not self._is_closed():
            self._conn.close()

    def cursor(self):
        self._ensure_connection()
        return PgCursorWrapper(self._conn.cursor(), self._conn)


def _is_postgres():
    return DATABASE_URL.startswith("postgres")


def _postgres_dsn() -> str:
    return DATABASE_URL.replace("postgres://", "postgresql://", 1)


def _connect_postgres(dsn: str):
    import psycopg2

    return psycopg2.connect(dsn)


def _should_reconnect_postgres(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "connection already closed" in message
        or "closed the connection unexpectedly" in message
        or "ssl connection has been closed unexpectedly" in message
        or "server closed the connection unexpectedly" in message
    )


def _is_failed_transaction_postgres(exc: Exception) -> bool:
    message = str(exc).lower()
    return "current transaction is aborted" in message or "in failed sql transaction" in message


def _sqlite_column_exists(conn, table_name, column_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def _ensure_user_teams_updated_at_sqlite(conn):
    if not _sqlite_column_exists(conn, "user_teams", "updated_at"):
        conn.execute("ALTER TABLE user_teams ADD COLUMN updated_at TEXT")
        conn.execute(
            "UPDATE user_teams SET updated_at = datetime('now') WHERE updated_at IS NULL OR updated_at = ''"
        )


def _ensure_users_backup_preference_sqlite(conn):
    if not _sqlite_column_exists(conn, "users", "replace_substitutes_with_backups"):
        conn.execute(
            "ALTER TABLE users ADD COLUMN replace_substitutes_with_backups INTEGER NOT NULL DEFAULT 1"
        )
    conn.execute(
        """
        UPDATE users
        SET replace_substitutes_with_backups = 1
        WHERE replace_substitutes_with_backups IS NULL OR replace_substitutes_with_backups = ''
        """
    )


def _ensure_user_teams_updated_at_postgres(cursor):
    # Postgres tables are created with updated_at already present. Avoid ALTERs
    # during startup because they can deadlock with live request traffic.
    return


def _ensure_users_backup_preference_postgres(cursor):
    cursor.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS replace_substitutes_with_backups BOOLEAN NOT NULL DEFAULT TRUE
        """
    )
    cursor.execute(
        """
        UPDATE users
        SET replace_substitutes_with_backups = TRUE
        WHERE replace_substitutes_with_backups IS NULL
        """
    )


def _ensure_players_type_postgres(cursor):
    return


def _ensure_players_type_sqlite(conn):
    if not _sqlite_column_exists(conn, "players", "type"):
        conn.execute("ALTER TABLE players ADD COLUMN type CHAR(1) DEFAULT NULL")


def _ensure_weekend_tournaments_flexible_postgres(cursor):
    return


def _ensure_weekend_tournaments_flexible_sqlite(conn):
    if not _sqlite_column_exists(conn, "weekend_tournaments", "weekend_match_ids"):
        conn.execute("ALTER TABLE weekend_tournaments ADD COLUMN weekend_match_ids TEXT DEFAULT '[]'")
    if not _sqlite_column_exists(conn, "weekend_tournaments", "num_rounds"):
        conn.execute("ALTER TABLE weekend_tournaments ADD COLUMN num_rounds INTEGER DEFAULT 0")
    # Backfill from old fixed columns if they exist
    try:
        if _sqlite_column_exists(conn, "weekend_tournaments", "weekend_match_1_id"):
            conn.execute("""
                UPDATE weekend_tournaments
                SET weekend_match_ids = '[' || weekend_match_1_id || ',' || weekend_match_2_id || ',' || weekend_match_3_id || ',' || weekend_match_4_id || ']',
                    num_rounds = 4
                WHERE (weekend_match_ids IS NULL OR weekend_match_ids = '[]') AND weekend_match_1_id IS NOT NULL
            """)
    except Exception:
        pass


def _ensure_matches_venue_sqlite(conn):
    if not _sqlite_column_exists(conn, "matches", "venue"):
        conn.execute("ALTER TABLE matches ADD COLUMN venue TEXT DEFAULT NULL")


def _ensure_user_teams_audit_sqlite(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_teams_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_team_id INTEGER,
            user_id INTEGER NOT NULL,
            match_id INTEGER NOT NULL,
            old_player_id INTEGER,
            new_player_id INTEGER,
            old_is_captain INTEGER,
            new_is_captain INTEGER,
            old_is_vice_captain INTEGER,
            new_is_vice_captain INTEGER,
            old_updated_at TEXT,
            new_updated_at TEXT,
            action TEXT NOT NULL DEFAULT 'UPDATE',
            changed_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.executescript("""
        DROP TRIGGER IF EXISTS trg_user_teams_audit_update;
        CREATE TRIGGER trg_user_teams_audit_update
        AFTER UPDATE ON user_teams
        FOR EACH ROW
        BEGIN
            INSERT INTO user_teams_audit (
                user_team_id,
                user_id,
                match_id,
                old_player_id,
                new_player_id,
                old_is_captain,
                new_is_captain,
                old_is_vice_captain,
                new_is_vice_captain,
                old_updated_at,
                new_updated_at,
                action,
                changed_at
            ) VALUES (
                OLD.id,
                OLD.user_id,
                OLD.match_id,
                OLD.player_id,
                NEW.player_id,
                OLD.is_captain,
                NEW.is_captain,
                OLD.is_vice_captain,
                NEW.is_vice_captain,
                OLD.updated_at,
                NEW.updated_at,
                'UPDATE',
                datetime('now')
            );
        END;
    """)


def _ensure_user_teams_audit_postgres(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_teams_audit (
            id BIGSERIAL PRIMARY KEY,
            user_team_id INTEGER,
            user_id INTEGER NOT NULL,
            match_id INTEGER NOT NULL,
            old_player_id INTEGER,
            new_player_id INTEGER,
            old_is_captain INTEGER,
            new_is_captain INTEGER,
            old_is_vice_captain INTEGER,
            new_is_vice_captain INTEGER,
            old_updated_at TEXT,
            new_updated_at TEXT,
            action TEXT NOT NULL DEFAULT 'UPDATE',
            changed_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    cursor.execute("""
        CREATE OR REPLACE FUNCTION log_user_teams_update_audit()
        RETURNS TRIGGER AS $$
        BEGIN
            INSERT INTO user_teams_audit (
                user_team_id,
                user_id,
                match_id,
                old_player_id,
                new_player_id,
                old_is_captain,
                new_is_captain,
                old_is_vice_captain,
                new_is_vice_captain,
                old_updated_at,
                new_updated_at,
                action,
                changed_at
            ) VALUES (
                OLD.id,
                OLD.user_id,
                OLD.match_id,
                OLD.player_id,
                NEW.player_id,
                OLD.is_captain,
                NEW.is_captain,
                OLD.is_vice_captain,
                NEW.is_vice_captain,
                OLD.updated_at,
                NEW.updated_at,
                'UPDATE',
                NOW()
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    cursor.execute("DROP TRIGGER IF EXISTS trg_user_teams_audit_update ON user_teams")
    cursor.execute("""
        CREATE TRIGGER trg_user_teams_audit_update
        AFTER UPDATE ON user_teams
        FOR EACH ROW
        EXECUTE FUNCTION log_user_teams_update_audit()
    """)


def _ensure_team_backups_postgres(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_backups (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            match_id INTEGER NOT NULL REFERENCES matches(id),
            backup_order INTEGER NOT NULL,
            backup_player_id INTEGER NOT NULL REFERENCES players(id),
            replaced_player_id INTEGER REFERENCES players(id),
            UNIQUE(user_id, match_id, backup_order)
        )
    """)


def _ensure_unknown_players_postgres(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS unknown_players (
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            match_id INTEGER NOT NULL,
            match_date TEXT NOT NULL,
            team1 TEXT NOT NULL,
            team2 TEXT NOT NULL,
            UNIQUE(name, team, match_id, match_date, team1, team2)
        )
    """)


def _ensure_team_backups_sqlite(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            match_id INTEGER NOT NULL REFERENCES matches(id),
            backup_order INTEGER NOT NULL,
            backup_player_id INTEGER NOT NULL REFERENCES players(id),
            replaced_player_id INTEGER REFERENCES players(id),
            UNIQUE(user_id, match_id, backup_order)
        )
    """)


def _ensure_unknown_players_sqlite(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unknown_players (
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            match_id INTEGER NOT NULL,
            match_date TEXT NOT NULL,
            team1 TEXT NOT NULL,
            team2 TEXT NOT NULL,
            UNIQUE(name, team, match_id, match_date, team1, team2)
        )
    """)


def _ensure_matches_metadata_sqlite(conn):
    if not _sqlite_column_exists(conn, "matches", "cricbuzz_match_id"):
        conn.execute("ALTER TABLE matches ADD COLUMN cricbuzz_match_id INTEGER DEFAULT NULL")
    if not _sqlite_column_exists(conn, "matches", "espn_match_id"):
        conn.execute("ALTER TABLE matches ADD COLUMN espn_match_id INTEGER DEFAULT NULL")
    if not _sqlite_column_exists(conn, "matches", "toss_time"):
        conn.execute("ALTER TABLE matches ADD COLUMN toss_time TEXT DEFAULT NULL")
    conn.execute(
        """
        UPDATE matches
        SET toss_time = COALESCE(
            toss_time,
            strftime('%H:%M', datetime(match_date || ' ' || match_time, '-30 minutes'))
        )
        WHERE toss_time IS NULL OR toss_time = ''
        """
    )


def _ensure_indexes_sqlite(conn):
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_user_match ON user_teams(user_id, match_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_match ON user_teams(match_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_match_user ON user_teams(match_id, user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_match_updated_at ON user_teams(match_id, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_contestant_points_match ON contestant_points(match_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_points_match ON player_points(match_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_player_points_last_updated ON player_points(last_updated)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_backups_user_match ON team_backups(user_id, match_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_backups_match ON team_backups(match_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_score_predictions_match ON score_predictions(match_id)")


def _ensure_matches_metadata_postgres(cursor):
    # Postgres tables are created with these columns already. Avoid runtime ALTERs
    # here because they can deadlock with concurrent read traffic during startup.
    return


def _ensure_autoincrement_postgres(cursor, table_name: str):
    # Keep startup schema initialization lightweight and non-blocking.
    # ID generation for these tables is handled explicitly in the insert paths
    # so we do not need to ALTER live tables at boot time.
    return


def get_db():
    if not hasattr(_local, "conn") or _local.conn is None:
        if _is_postgres():
            _local.conn = PgConnectionWrapper(_postgres_dsn())
        else:
            conn = sqlite3.connect(DATABASE_PATH, timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            _local.conn = conn
    elif _is_postgres() and getattr(_local.conn, "_is_closed", lambda: False)():
        _local.conn = PgConnectionWrapper(_postgres_dsn())
    return _local.conn


def get_next_id(table_name: str) -> int:
    db = get_db()
    row = db.execute(f"SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM {table_name}").fetchone()
    return int(row["next_id"] if row and "next_id" in row else row[0])


def init_db():
    if _is_postgres():
        conn = _connect_postgres(_postgres_dsn())
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                firebase_uid TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                mobile TEXT,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                replace_substitutes_with_backups BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                team TEXT NOT NULL,
                role TEXT NOT NULL,
                type CHAR(1) DEFAULT NULL,
                aliases TEXT DEFAULT ''
            )
        """)
        _ensure_autoincrement_postgres(cursor, "players")
        _ensure_players_type_postgres(cursor)
        _ensure_users_backup_preference_postgres(cursor)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY,
                team1 TEXT NOT NULL,
                team2 TEXT NOT NULL,
                match_date TEXT NOT NULL,
                match_time TEXT NOT NULL,
                status TEXT DEFAULT 'future',
                venue TEXT DEFAULT NULL,
                cricbuzz_match_id INTEGER DEFAULT NULL,
                espn_match_id INTEGER DEFAULT NULL,
                toss_time TEXT DEFAULT NULL
            )
        """)
        _ensure_autoincrement_postgres(cursor, "matches")
        _ensure_matches_metadata_postgres(cursor)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_teams (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                match_id INTEGER NOT NULL REFERENCES matches(id),
                player_id INTEGER NOT NULL REFERENCES players(id),
                is_captain INTEGER NOT NULL DEFAULT 0,
                is_vice_captain INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT,
                UNIQUE(user_id, match_id, player_id)
            )
        """)
        _ensure_user_teams_updated_at_postgres(cursor)
        _ensure_user_teams_audit_postgres(cursor)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contestant_points (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                match_id INTEGER NOT NULL REFERENCES matches(id),
                points REAL NOT NULL DEFAULT 0,
                last_updated TEXT NOT NULL,
                UNIQUE(user_id, match_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_points (
                id SERIAL PRIMARY KEY,
                match_id INTEGER NOT NULL REFERENCES matches(id),
                player_id INTEGER NOT NULL REFERENCES players(id),
                player_name TEXT NOT NULL,
                team TEXT NOT NULL,
                role TEXT NOT NULL,
                points REAL NOT NULL DEFAULT 0,
                last_updated TEXT NOT NULL,
                UNIQUE(match_id, player_id)
            )
        """)
        _ensure_team_backups_postgres(cursor)
        _ensure_unknown_players_postgres(cursor)

        # Weekend tournament tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weekend_tournaments (
                id SERIAL PRIMARY KEY,
                qualifying_match_id INTEGER NOT NULL REFERENCES matches(id),
                weekend_match_1_id INTEGER REFERENCES matches(id),
                weekend_match_2_id INTEGER REFERENCES matches(id),
                weekend_match_3_id INTEGER REFERENCES matches(id),
                weekend_match_4_id INTEGER REFERENCES matches(id),
                status TEXT NOT NULL DEFAULT 'pending',
                winner_user_id INTEGER REFERENCES users(id),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(qualifying_match_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS weekend_tournament_brackets (
                id SERIAL PRIMARY KEY,
                tournament_id INTEGER NOT NULL REFERENCES weekend_tournaments(id),
                round INTEGER NOT NULL,
                match_position INTEGER NOT NULL,
                match_id INTEGER NOT NULL REFERENCES matches(id),
                user1_id INTEGER REFERENCES users(id),
                user2_id INTEGER REFERENCES users(id),
                user1_points REAL DEFAULT 0,
                user2_points REAL DEFAULT 0,
                winner_user_id INTEGER REFERENCES users(id),
                status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(tournament_id, round, match_position)
            )
        """)
        _ensure_weekend_tournaments_flexible_postgres(cursor)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS score_predictions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                match_id INTEGER NOT NULL REFERENCES matches(id),
                predicted_points REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, match_id)
            )
        """)

        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_user_match ON user_teams(user_id, match_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_match ON user_teams(match_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_match_user ON user_teams(match_id, user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_teams_match_updated_at ON user_teams(match_id, updated_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contestant_points_match ON contestant_points(match_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_points_match ON player_points(match_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_points_last_updated ON player_points(last_updated)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_backups_user_match ON team_backups(user_id, match_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_backups_match ON team_backups(match_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_score_predictions_match ON score_predictions(match_id)")

        conn.commit()
        conn.close()
    else:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                firebase_uid TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                mobile TEXT,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                replace_substitutes_with_backups INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                team TEXT NOT NULL,
                role TEXT NOT NULL,
                type CHAR(1) DEFAULT NULL,
                aliases TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY,
                team1 TEXT NOT NULL,
                team2 TEXT NOT NULL,
                match_date TEXT NOT NULL,
                match_time TEXT NOT NULL,
                status TEXT DEFAULT 'future',
                venue TEXT DEFAULT NULL,
                cricbuzz_match_id INTEGER DEFAULT NULL,
                espn_match_id INTEGER DEFAULT NULL,
                toss_time TEXT DEFAULT NULL
            );
            CREATE TABLE IF NOT EXISTS user_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                match_id INTEGER NOT NULL REFERENCES matches(id),
                player_id INTEGER NOT NULL REFERENCES players(id),
                is_captain INTEGER NOT NULL DEFAULT 0,
                is_vice_captain INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT,
                UNIQUE(user_id, match_id, player_id)
            );
            CREATE TABLE IF NOT EXISTS user_teams_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_team_id INTEGER,
                user_id INTEGER NOT NULL,
                match_id INTEGER NOT NULL,
                old_player_id INTEGER,
                new_player_id INTEGER,
                old_is_captain INTEGER,
                new_is_captain INTEGER,
                old_is_vice_captain INTEGER,
                new_is_vice_captain INTEGER,
                old_updated_at TEXT,
                new_updated_at TEXT,
                action TEXT NOT NULL DEFAULT 'UPDATE',
                changed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS contestant_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                match_id INTEGER NOT NULL REFERENCES matches(id),
                points REAL NOT NULL DEFAULT 0,
                last_updated TEXT NOT NULL,
                UNIQUE(user_id, match_id)
            );
            CREATE TABLE IF NOT EXISTS player_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL REFERENCES matches(id),
                player_id INTEGER NOT NULL REFERENCES players(id),
                player_name TEXT NOT NULL,
                team TEXT NOT NULL,
                role TEXT NOT NULL,
                points REAL NOT NULL DEFAULT 0,
                last_updated TEXT NOT NULL,
                UNIQUE(match_id, player_id)
            );
            CREATE TABLE IF NOT EXISTS team_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                match_id INTEGER NOT NULL REFERENCES matches(id),
                backup_order INTEGER NOT NULL,
                backup_player_id INTEGER NOT NULL REFERENCES players(id),
                replaced_player_id INTEGER REFERENCES players(id),
                UNIQUE(user_id, match_id, backup_order)
            );
            CREATE TABLE IF NOT EXISTS unknown_players (
                name TEXT NOT NULL,
                team TEXT NOT NULL,
                match_id INTEGER NOT NULL,
                match_date TEXT NOT NULL,
                team1 TEXT NOT NULL,
                team2 TEXT NOT NULL,
                UNIQUE(name, team, match_id, match_date, team1, team2)
            );
            CREATE TABLE IF NOT EXISTS weekend_tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qualifying_match_id INTEGER NOT NULL REFERENCES matches(id),
                weekend_match_1_id INTEGER NOT NULL REFERENCES matches(id),
                weekend_match_2_id INTEGER NOT NULL REFERENCES matches(id),
                weekend_match_3_id INTEGER NOT NULL REFERENCES matches(id),
                weekend_match_4_id INTEGER NOT NULL REFERENCES matches(id),
                status TEXT NOT NULL DEFAULT 'pending',
                winner_user_id INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(qualifying_match_id)
            );
            CREATE TABLE IF NOT EXISTS weekend_tournament_brackets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER NOT NULL REFERENCES weekend_tournaments(id),
                round INTEGER NOT NULL,
                match_position INTEGER NOT NULL,
                match_id INTEGER NOT NULL REFERENCES matches(id),
                user1_id INTEGER REFERENCES users(id),
                user2_id INTEGER REFERENCES users(id),
                user1_points REAL DEFAULT 0,
                user2_points REAL DEFAULT 0,
                winner_user_id INTEGER REFERENCES users(id),
                status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(tournament_id, round, match_position)
            );
            CREATE TABLE IF NOT EXISTS score_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                match_id INTEGER NOT NULL REFERENCES matches(id),
                predicted_points REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, match_id)
            );
        """)
        _ensure_user_teams_updated_at_sqlite(conn)
        _ensure_users_backup_preference_sqlite(conn)
        _ensure_matches_venue_sqlite(conn)
        _ensure_matches_metadata_sqlite(conn)
        _ensure_user_teams_audit_sqlite(conn)
        _ensure_team_backups_sqlite(conn)
        _ensure_unknown_players_sqlite(conn)
        _ensure_players_type_sqlite(conn)
        _ensure_weekend_tournaments_flexible_sqlite(conn)
        _ensure_indexes_sqlite(conn)
        conn.commit()
        conn.close()
