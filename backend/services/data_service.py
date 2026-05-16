"""
SQLite-backed data service.

Replaces the old JSON-based data_service with queries against the SQLite
database defined in backend/database.py.  Every public function keeps the
same signature (or a compatible superset) so that tournament.py and all
route modules continue to work without changes.
"""

from __future__ import annotations

import copy
import time
from datetime import datetime

from backend.database import get_db
from backend.config import get_current_datetime
from backend.services.cache_locks import acquire_cache_locks, get_cache_lock

# ---------------------------------------------------------------------------
# Lightweight in-process cache (mirrors the old JSON cache behaviour)
# ---------------------------------------------------------------------------

CACHE: dict[str, list[dict] | None] = {
    "players": None,
    "users": None,
    "matches": None,
}

STATIC_CACHE_DOMAIN = {
    "players": "static:players",
    "users": "static:users",
    "matches": "static:matches",
}

PLAYER_MATCH_PAYLOAD_LOCK = get_cache_lock("player_match_payloads")
PLAYING_XI_STATUS_LOCK = get_cache_lock("playing_xi_status")
LAST_MATCH_XI_LOCK = get_cache_lock("last_match_xi")
SCORE_PREDICTION_LOCK = get_cache_lock("score_prediction")
TEAM_CONTESTANT_LOCK = get_cache_lock("team_contestants")
USER_TEAM_SUMMARY_LOCK = get_cache_lock("user_team_summary")

PLAYER_MATCH_PAYLOAD_CACHE: dict[int, dict] = {}
PLAYING_XI_STATUS_CACHE: dict[tuple, dict] = {}
LAST_MATCH_XI_CACHE: dict[tuple[int, str], dict] = {}
SCORE_PREDICTION_CACHE: dict[int, dict[int, float]] = {}
TEAM_CONTESTANT_CACHE: dict[int, list[dict]] = {}
USER_TEAM_SUMMARY_CACHE: dict[int, dict[int, dict]] = {}
USER_TEAM_SUMMARY_ALL_LOADED: set[int] = set()


def _is_deadlock_error(exc: Exception) -> bool:
    return "deadlock detected" in str(exc).lower()


def _retry_deadlock(operation, *, attempts: int = 3) -> None:
    for attempt in range(attempts):
        try:
            operation()
            return
        except Exception as exc:
            if not _is_deadlock_error(exc) or attempt == attempts - 1:
                raise
            time.sleep(0.1 * (attempt + 1))


def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row) if row else {}


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def invalidate_cache(*sheet_names: str):
    keys = sheet_names or tuple(CACHE.keys())
    domains = [STATIC_CACHE_DOMAIN[key] for key in keys if key in STATIC_CACHE_DOMAIN]
    with acquire_cache_locks(*domains):
        for key in keys:
            if key in CACHE:
                CACHE[key] = None


def invalidate_match_player_payloads(match_id: int | None = None) -> None:
    with PLAYER_MATCH_PAYLOAD_LOCK:
        if match_id is None:
            PLAYER_MATCH_PAYLOAD_CACHE.clear()
        else:
            PLAYER_MATCH_PAYLOAD_CACHE.pop(int(match_id), None)


def get_cached_match_player_payload(match_id: int) -> dict | None:
    with PLAYER_MATCH_PAYLOAD_LOCK:
        payload = PLAYER_MATCH_PAYLOAD_CACHE.get(int(match_id))
        return copy.deepcopy(payload) if payload is not None else None


def set_cached_match_player_payload(match_id: int, payload: dict) -> None:
    with PLAYER_MATCH_PAYLOAD_LOCK:
        PLAYER_MATCH_PAYLOAD_CACHE[int(match_id)] = copy.deepcopy(payload)


def _is_playing_xi_final(payload: dict | None) -> bool:
    if not payload:
        return False
    if not bool(payload.get("announced")):
        return False
    player_ids = payload.get("player_ids") or []
    substitute_ids = payload.get("substitute_ids") or []
    return len(player_ids) == 22 and len(substitute_ids) == 10


def _is_playing_xi_announced(payload: dict | None) -> bool:
    if not payload:
        return False
    if bool(payload.get("announced")):
        return True
    player_ids = payload.get("player_ids") or []
    return len(player_ids) == 22


def get_cached_match_playing_xi(
    match_id: int,
    team1: str,
    team2: str,
    match_date: str,
    match_time: str,
) -> dict | None:
    cache_key = (int(match_id), team1, team2, match_date, match_time)
    with PLAYING_XI_STATUS_LOCK:
        payload = PLAYING_XI_STATUS_CACHE.get(cache_key)
        return copy.deepcopy(payload) if payload is not None else None


def set_cached_match_playing_xi(
    match_id: int,
    team1: str,
    team2: str,
    match_date: str,
    match_time: str,
    payload: dict,
) -> dict:
    cache_key = (int(match_id), team1, team2, match_date, match_time)
    with PLAYING_XI_STATUS_LOCK:
        existing = PLAYING_XI_STATUS_CACHE.get(cache_key)
        if _is_playing_xi_final(existing) and not _is_playing_xi_final(payload):
            return copy.deepcopy(existing)
        PLAYING_XI_STATUS_CACHE[cache_key] = copy.deepcopy(payload)
        return copy.deepcopy(PLAYING_XI_STATUS_CACHE[cache_key])


def is_cached_playing_xi_final(
    match_id: int,
    team1: str,
    team2: str,
    match_date: str,
    match_time: str,
) -> bool:
    cache_key = (int(match_id), team1, team2, match_date, match_time)
    with PLAYING_XI_STATUS_LOCK:
        return _is_playing_xi_final(PLAYING_XI_STATUS_CACHE.get(cache_key))


def is_cached_playing_xi_announced(
    match_id: int,
    team1: str,
    team2: str,
    match_date: str,
    match_time: str,
) -> bool:
    cache_key = (int(match_id), team1, team2, match_date, match_time)
    with PLAYING_XI_STATUS_LOCK:
        return _is_playing_xi_announced(PLAYING_XI_STATUS_CACHE.get(cache_key))


def get_cached_last_match_xi(match_id: int, team: str) -> dict | None:
    cache_key = (int(match_id), team)
    with LAST_MATCH_XI_LOCK:
        payload = LAST_MATCH_XI_CACHE.get(cache_key)
        return copy.deepcopy(payload) if payload is not None else None


def set_cached_last_match_xi(match_id: int, team: str, payload: dict) -> dict:
    cache_key = (int(match_id), team)
    with LAST_MATCH_XI_LOCK:
        LAST_MATCH_XI_CACHE[cache_key] = copy.deepcopy(payload)
        return copy.deepcopy(LAST_MATCH_XI_CACHE[cache_key])


def invalidate_score_prediction_cache(match_id: int | None = None) -> None:
    with SCORE_PREDICTION_LOCK:
        if match_id is None:
            SCORE_PREDICTION_CACHE.clear()
        else:
            SCORE_PREDICTION_CACHE.pop(int(match_id), None)


def _copy_score_prediction_map(predictions: dict[int, float] | None) -> dict[int, float]:
    if not predictions:
        return {}
    return {int(user_id): float(points) for user_id, points in predictions.items()}


def get_cached_match_predictions(match_id: int) -> dict[int, float]:
    with SCORE_PREDICTION_LOCK:
        return _copy_score_prediction_map(SCORE_PREDICTION_CACHE.get(int(match_id)))


def set_cached_score_prediction(user_id: int, match_id: int, predicted_points: float) -> None:
    with SCORE_PREDICTION_LOCK:
        match_predictions = SCORE_PREDICTION_CACHE.setdefault(int(match_id), {})
        match_predictions[int(user_id)] = float(predicted_points)


def prime_score_prediction_cache(match_ids: list[int] | None = None) -> dict[int, int]:
    db = get_db()
    params: list[int] = []
    query = "SELECT match_id, user_id, predicted_points FROM score_predictions"
    if match_ids:
        normalized_ids = [int(match_id) for match_id in match_ids]
        placeholders = ",".join("?" * len(normalized_ids))
        query += f" WHERE match_id IN ({placeholders})"
        params.extend(normalized_ids)

    rows = db.execute(query, params).fetchall()
    grouped: dict[int, dict[int, float]] = {}
    for row in rows:
        match_id = int(row["match_id"])
        grouped.setdefault(match_id, {})[int(row["user_id"])] = float(row["predicted_points"])

    with SCORE_PREDICTION_LOCK:
        if match_ids is None:
            SCORE_PREDICTION_CACHE.clear()
        for match_id, predictions in grouped.items():
            SCORE_PREDICTION_CACHE[match_id] = predictions

    return {match_id: len(predictions) for match_id, predictions in grouped.items()}


def _fetch_team_contestants(match_ids: list[int] | None = None) -> dict[int, list[dict]]:
    db = get_db()
    params: list[int] = []
    query = """
        SELECT
            ut.match_id,
            u.id AS user_id,
            u.name AS user_name,
            MAX(COALESCE(ut.updated_at, '')) AS last_team_updated
        FROM user_teams ut
        JOIN users u ON u.id = ut.user_id
        WHERE u.is_active = 1
    """
    if match_ids:
        normalized_ids = [int(match_id) for match_id in match_ids]
        placeholders = ",".join("?" * len(normalized_ids))
        query += f" AND ut.match_id IN ({placeholders})"
        params.extend(normalized_ids)

    query += """
        GROUP BY ut.match_id, u.id, u.name
        ORDER BY ut.match_id, last_team_updated DESC, u.name ASC
    """

    rows = db.execute(query, params).fetchall()
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        mid = int(row["match_id"])
        grouped.setdefault(mid, []).append(
            {
                "user_id": int(row["user_id"]),
                "name": row["user_name"],
                "last_team_updated": row["last_team_updated"] or None,
            }
        )
    return grouped


def get_cached_match_contestants(match_id: int) -> list[dict] | None:
    with TEAM_CONTESTANT_LOCK:
        payload = TEAM_CONTESTANT_CACHE.get(int(match_id))
        return copy.deepcopy(payload) if payload is not None else None


def set_cached_match_contestants(match_id: int, contestants: list[dict]) -> None:
    with TEAM_CONTESTANT_LOCK:
        TEAM_CONTESTANT_CACHE[int(match_id)] = copy.deepcopy(contestants)


def invalidate_match_contestant_cache(match_id: int | None = None) -> None:
    with TEAM_CONTESTANT_LOCK:
        if match_id is None:
            TEAM_CONTESTANT_CACHE.clear()
        else:
            TEAM_CONTESTANT_CACHE.pop(int(match_id), None)


def refresh_match_contestant_cache(match_id: int) -> list[dict]:
    grouped = _fetch_team_contestants([int(match_id)])
    contestants = grouped.get(int(match_id), [])
    set_cached_match_contestants(int(match_id), contestants)
    return copy.deepcopy(contestants)


def prime_contestant_cache(match_ids: list[int] | None = None) -> dict[int, int]:
    db = get_db()
    params: list[int] = []
    query = "SELECT id FROM matches"
    if match_ids:
        normalized_ids = [int(match_id) for match_id in match_ids]
        placeholders = ",".join("?" * len(normalized_ids))
        query += f" WHERE id IN ({placeholders})"
        params.extend(normalized_ids)

    match_rows = db.execute(query, params).fetchall()
    all_match_ids = [int(row["id"]) for row in match_rows]
    if match_ids is None:
        grouped = _fetch_team_contestants()
    else:
        grouped = _fetch_team_contestants(all_match_ids)

    with TEAM_CONTESTANT_LOCK:
        if match_ids is None:
            TEAM_CONTESTANT_CACHE.clear()
        for match_id in all_match_ids:
            TEAM_CONTESTANT_CACHE[int(match_id)] = copy.deepcopy(grouped.get(int(match_id), []))

    return {match_id: len(TEAM_CONTESTANT_CACHE.get(match_id, [])) for match_id in all_match_ids}


def _fetch_user_team_summaries(user_id: int, match_ids: list[int] | None = None) -> dict[int, dict]:
    db = get_db()
    params: list[int] = [int(user_id)]
    match_filter = ""
    normalized_ids: list[int] | None = None
    if match_ids is not None:
        normalized_ids = [int(match_id) for match_id in match_ids]
        if not normalized_ids:
            return {}
        placeholders = ",".join("?" * len(normalized_ids))
        match_filter = f" AND match_id IN ({placeholders})"
        params.extend(normalized_ids)

    summaries: dict[int, dict] = {}
    if normalized_ids is not None:
        summaries = {
            int(match_id): {"selected_ids": [], "backup_count": 0}
            for match_id in normalized_ids
        }

    team_rows = db.execute(
        f"""
        SELECT match_id, player_id
        FROM user_teams
        WHERE user_id = ?{match_filter}
        ORDER BY match_id, player_id
        """,
        params,
    ).fetchall()
    for row in team_rows:
        match_id = int(row["match_id"])
        summaries.setdefault(match_id, {"selected_ids": [], "backup_count": 0})
        summaries[match_id]["selected_ids"].append(int(row["player_id"]))

    backup_rows = db.execute(
        f"""
        SELECT match_id, COUNT(*) AS backup_count
        FROM team_backups
        WHERE user_id = ?{match_filter} AND replaced_player_id IS NULL
        GROUP BY match_id
        """,
        params,
    ).fetchall()
    for row in backup_rows:
        match_id = int(row["match_id"])
        summaries.setdefault(match_id, {"selected_ids": [], "backup_count": 0})
        summaries[match_id]["backup_count"] = int(row["backup_count"])

    return summaries


def get_cached_user_team_summaries(user_id: int, match_ids: list[int | str] | None = None) -> dict[int, dict]:
    normalized_ids = [int(match_id) for match_id in match_ids] if match_ids is not None else None
    user_id = int(user_id)

    with USER_TEAM_SUMMARY_LOCK:
        cached_for_user = USER_TEAM_SUMMARY_CACHE.get(user_id)
        if cached_for_user is not None and (normalized_ids is not None or user_id in USER_TEAM_SUMMARY_ALL_LOADED):
            if normalized_ids is None:
                return copy.deepcopy(cached_for_user)
            missing_ids = [match_id for match_id in normalized_ids if match_id not in cached_for_user]
            if not missing_ids:
                return {
                    match_id: copy.deepcopy(cached_for_user.get(match_id, {"selected_ids": [], "backup_count": 0}))
                    for match_id in normalized_ids
                }
        else:
            missing_ids = normalized_ids

    fetched = _fetch_user_team_summaries(user_id, missing_ids)
    with USER_TEAM_SUMMARY_LOCK:
        cached_for_user = USER_TEAM_SUMMARY_CACHE.setdefault(user_id, {})
        if normalized_ids is None:
            cached_for_user.clear()
            cached_for_user.update(copy.deepcopy(fetched))
            USER_TEAM_SUMMARY_ALL_LOADED.add(user_id)
            return copy.deepcopy(cached_for_user)
        for match_id in missing_ids or []:
            cached_for_user[match_id] = copy.deepcopy(fetched.get(match_id, {"selected_ids": [], "backup_count": 0}))
        return {
            match_id: copy.deepcopy(cached_for_user.get(match_id, {"selected_ids": [], "backup_count": 0}))
            for match_id in normalized_ids
        }


def refresh_user_team_summary_cache(user_id: int, match_id: int | None = None) -> dict[int, dict]:
    match_ids = [int(match_id)] if match_id is not None else None
    fetched = _fetch_user_team_summaries(int(user_id), match_ids)
    with USER_TEAM_SUMMARY_LOCK:
        cached_for_user = USER_TEAM_SUMMARY_CACHE.setdefault(int(user_id), {})
        if match_id is None:
            cached_for_user.clear()
            cached_for_user.update(copy.deepcopy(fetched))
            USER_TEAM_SUMMARY_ALL_LOADED.add(int(user_id))
        else:
            cached_for_user[int(match_id)] = copy.deepcopy(
                fetched.get(int(match_id), {"selected_ids": [], "backup_count": 0})
            )
            USER_TEAM_SUMMARY_ALL_LOADED.discard(int(user_id))
        return copy.deepcopy(cached_for_user)


def prime_user_team_summary_cache() -> dict[int, int]:
    users = get_cached_data("users")
    counts: dict[int, int] = {}
    with USER_TEAM_SUMMARY_LOCK:
        USER_TEAM_SUMMARY_CACHE.clear()
        USER_TEAM_SUMMARY_ALL_LOADED.clear()

    for user in users:
        user_id = int(user.get("UserID", 0) or 0)
        if not user_id:
            continue
        summaries = refresh_user_team_summary_cache(user_id)
        counts[user_id] = len([summary for summary in summaries.values() if summary.get("selected_ids")])
    return counts


def invalidate_user_team_summary_cache(user_id: int | None = None, match_id: int | None = None) -> None:
    with USER_TEAM_SUMMARY_LOCK:
        if user_id is None:
            USER_TEAM_SUMMARY_CACHE.clear()
            USER_TEAM_SUMMARY_ALL_LOADED.clear()
            return
        cached_for_user = USER_TEAM_SUMMARY_CACHE.get(int(user_id))
        if cached_for_user is None:
            return
        if match_id is None:
            USER_TEAM_SUMMARY_CACHE.pop(int(user_id), None)
            USER_TEAM_SUMMARY_ALL_LOADED.discard(int(user_id))
        else:
            cached_for_user.pop(int(match_id), None)
            USER_TEAM_SUMMARY_ALL_LOADED.discard(int(user_id))


def prime_static_cache():
    """Warm static caches at startup so hot paths avoid repeated reloads."""
    get_cached_data("players")
    get_cached_data("users")
    get_cached_data("matches")


# ---------------------------------------------------------------------------
# Cached reads  – keys returned match what tournament.py / routes expect
# ---------------------------------------------------------------------------

def get_cached_data(sheet_name: str) -> list[dict]:
    """Return cached list-of-dicts for *players*, *users*, or *matches*.

    The dict keys deliberately match the old JSON field names so that every
    consumer (tournament.py, routes, templates) keeps working.
    """
    if sheet_name not in CACHE:
        return []

    cache_lock_name = STATIC_CACHE_DOMAIN.get(sheet_name)
    if cache_lock_name:
        with acquire_cache_locks(cache_lock_name):
            cached = CACHE[sheet_name]
            if cached is not None:
                return copy.deepcopy(cached)

    if sheet_name == "players":
        payload = _cached_players()
    elif sheet_name == "users":
        payload = _cached_users()
    elif sheet_name == "matches":
        payload = _cached_matches()
    else:
        payload = []

    if cache_lock_name:
        with acquire_cache_locks(cache_lock_name):
            CACHE[sheet_name] = copy.deepcopy(payload)
    return payload


def _get_cached_match_field(match_id: int, field_name: str):
    rows = get_cached_data("matches")
    if not rows:
        return None
    for row in rows:
        if int(row.get("MatchID", 0) or 0) != int(match_id):
            continue
        value = row.get(field_name)
        if value not in (None, ""):
            return value
    return None


def _cached_players() -> list[dict]:
    db = get_db()
    rows = db.execute("SELECT id, name, team, role, type, aliases FROM players").fetchall()
    return [
        {
            "PlayerID": r["id"],
            "Name": r["name"],
            "Team": r["team"],
            "Role": r["role"],
            "Type": r["type"],
            "Aliases": r["aliases"] or "",
        }
        for r in rows
    ]


def _cached_users() -> list[dict]:
    """Legacy-compatible user dicts (Mobile, Name, Password, Allowed)."""
    db = get_db()
    rows = db.execute(
        "SELECT id, firebase_uid, email, name, mobile, role, is_active FROM users"
    ).fetchall()
    return [
        {
            "Mobile": r["mobile"] or "",
            "Name": r["name"],
            "Password": "",          # Firebase handles auth – dummy value
            "Allowed": "true" if r["is_active"] else "false",
        }
        for r in rows
    ]


def _cached_users() -> list[dict]:
    """Legacy-compatible user dicts (Mobile, Name, Password, Allowed)."""
    db = get_db()
    rows = db.execute(
        "SELECT id, firebase_uid, email, name, mobile, role, is_active, replace_substitutes_with_backups FROM users"
    ).fetchall()
    return [
        {
            "UserID": r["id"],
            "Mobile": r["mobile"] or "",
            "Name": r["name"],
            "Password": "",          # Firebase handles auth - dummy value
            "Allowed": "true" if r["is_active"] else "false",
            "ReplaceSubstitutesWithBackups": bool(r["replace_substitutes_with_backups"]),
        }
        for r in rows
    ]


def _cached_matches() -> list[dict]:
    db = get_db()
    rows = db.execute(
        "SELECT id, team1, team2, match_date, match_time, status, venue, cricbuzz_match_id, espn_match_id, toss_time FROM matches"
    ).fetchall()
    return [
        {
            "MatchID": r["id"],
            "Team1": r["team1"],
            "Team2": r["team2"],
            "Date": r["match_date"],
            "Time": r["match_time"],
            "Status": r["status"],
            "Venue": r["venue"],
            "CricbuzzMatchID": r["cricbuzz_match_id"],
            "ESPNMatchID": r["espn_match_id"],
            "TossTime": r["toss_time"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_users() -> list[dict]:
    db = get_db()
    rows = db.execute("SELECT * FROM users").fetchall()
    return _rows_to_dicts(rows)


def get_user_by_firebase_uid(uid: str) -> dict | None:
    db = get_db()
    row = db.execute(
        "SELECT * FROM users WHERE firebase_uid = ?", (uid,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_user_backup_preference(user_id: int) -> bool:
    try:
        users = get_cached_data("users")
        for user in users:
            if int(user.get("UserID", 0) or 0) != int(user_id):
                continue
            value = user.get("ReplaceSubstitutesWithBackups")
            if value is not None:
                return bool(value)
    except Exception:
        pass
    return True


def create_user(
    firebase_uid: str,
    email: str,
    name: str,
    mobile: str | None = None,
    role: str = "user",
) -> dict:
    db = get_db()
    cur = db.execute(
        """INSERT INTO users (firebase_uid, email, name, mobile, role)
           VALUES (?, ?, ?, ?, ?) RETURNING id""",
        (firebase_uid, email, name, mobile, role),
    )
    inserted = cur.fetchone()
    db.commit()
    invalidate_cache("users")
    user_id = inserted["id"] if inserted and "id" in inserted else cur.lastrowid
    return get_user_by_id(user_id)


def update_user(user_id: int, **fields) -> None:
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [user_id]
    db = get_db()
    db.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
    db.commit()
    invalidate_cache("users")


def update_user_password(mobile: str, new_password: str) -> None:
    """Legacy compatibility stub.

    With Firebase auth the password is not stored locally.  This is kept so
    the old change-password route does not crash; it is effectively a no-op
    against the DB but invalidates the cache for consistency.
    """
    invalidate_cache("users")


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

def get_players() -> list[dict]:
    db = get_db()
    rows = db.execute("SELECT * FROM players").fetchall()
    return _rows_to_dicts(rows)


def get_players_for_match(match_id) -> list[dict]:
    """Return players whose team participates in the given match."""
    db = get_db()
    match = db.execute(
        "SELECT team1, team2 FROM matches WHERE id = ?", (int(match_id),)
    ).fetchone()
    if not match:
        return []
    rows = db.execute(
        "SELECT * FROM players WHERE team IN (?, ?)",
        (match["team1"], match["team2"]),
    ).fetchall()
    return _rows_to_dicts(rows)


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------

def get_matches() -> list[dict]:
    db = get_db()
    rows = db.execute("SELECT * FROM matches").fetchall()
    return _rows_to_dicts(rows)


def get_matches_api_rows() -> list[dict]:
    rows = get_cached_data("matches")
    return [
        {
            "id": int(row["MatchID"]),
            "team1": row["Team1"],
            "team2": row["Team2"],
            "match_date": row["Date"],
            "match_time": row["Time"],
            "status": row.get("Status", "future"),
            "venue": row.get("Venue"),
            "cricbuzz_match_id": row.get("CricbuzzMatchID"),
            "espn_match_id": row.get("ESPNMatchID"),
            "toss_time": row.get("TossTime"),
        }
        for row in rows
    ]


def get_match_by_id(match_id: int) -> dict | None:
    db = get_db()
    row = db.execute("SELECT * FROM matches WHERE id = ?", (int(match_id),)).fetchone()
    return _row_to_dict(row) if row else None


def get_stored_cricbuzz_match_id(match_id: int) -> int | None:
    value = _get_cached_match_field(int(match_id), "CricbuzzMatchID")
    if value in (None, ""):
        db = get_db()
        row = db.execute(
            "SELECT cricbuzz_match_id FROM matches WHERE id = ?",
            (int(match_id),),
        ).fetchone()
        if not row:
            return None
        value = row["cricbuzz_match_id"]
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def get_stored_espn_match_id(match_id: int) -> int | None:
    value = _get_cached_match_field(int(match_id), "ESPNMatchID")
    if value in (None, ""):
        db = get_db()
        row = db.execute(
            "SELECT espn_match_id FROM matches WHERE id = ?",
            (int(match_id),),
        ).fetchone()
        if not row:
            return None
        value = row["espn_match_id"]
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def update_match_fields(match_id: int, **fields) -> bool:
    allowed_fields = {"team1", "team2", "match_date", "match_time", "status", "venue", "cricbuzz_match_id", "espn_match_id", "toss_time"}
    updates = []
    values = []
    for key, value in fields.items():
        if key not in allowed_fields:
            continue
        updates.append(f"{key} = ?")
        values.append(value)

    if not updates:
        return False

    db = get_db()
    values.append(int(match_id))
    db.execute(f"UPDATE matches SET {', '.join(updates)} WHERE id = ?", values)
    db.commit()
    invalidate_cache("matches")
    return True


def update_match_status(match_id: int, status: str) -> bool:
    db = get_db()
    normalized_status = (status or "").strip().lower()
    if normalized_status not in {"future", "live", "completed", "nr"}:
        return False

    existing = db.execute("SELECT status FROM matches WHERE id = ?", (int(match_id),)).fetchone()
    if not existing:
        return False

    current_status = (existing["status"] or "").strip().lower()
    if current_status == normalized_status:
        return False

    db.execute("UPDATE matches SET status = ? WHERE id = ?", (normalized_status, int(match_id)))
    db.commit()
    invalidate_cache("matches")
    return True


def clear_points_for_match(match_id: int) -> None:
    db = get_db()
    normalized_match_id = int(match_id)
    db.execute("DELETE FROM contestant_points WHERE match_id = ?", (normalized_match_id,))
    db.execute("DELETE FROM player_points WHERE match_id = ?", (normalized_match_id,))
    db.commit()


# ---------------------------------------------------------------------------
# Teams (user_teams)
# ---------------------------------------------------------------------------

def get_teams() -> list[dict]:
    """Return all user-team selections in the legacy format expected by
    ``tournament.initialize()`` and the routes.

    Keys: User, Mobile, MatchID, PlayerID, Name, Captain, ViceCaptain
    """
    return get_teams_for_matches()


def get_teams_for_matches(match_ids: list[int | str] | None = None) -> list[dict]:
    db = get_db()
    query = """
        SELECT
            u.id     AS user_id,
            u.name   AS user_name,
            u.mobile AS mobile,
            u.is_active AS user_is_active,
            ut.match_id,
            ut.player_id,
            p.name   AS player_name,
            ut.is_captain,
            ut.is_vice_captain
        FROM user_teams ut
        JOIN users   u ON u.id  = ut.user_id
        JOIN players p ON p.id  = ut.player_id
    """
    params: list[int] = []
    if match_ids:
        normalized_ids = [int(match_id) for match_id in match_ids]
        placeholders = ",".join("?" * len(normalized_ids))
        query += f" WHERE ut.match_id IN ({placeholders})"
        params.extend(normalized_ids)

    rows = db.execute(query, params).fetchall()

    return [
        {
            "UserID": r["user_id"],
            "User": r["user_name"],
            "Mobile": r["mobile"] or "",
            "IsActive": bool(r["user_is_active"]),
            "MatchID": str(r["match_id"]),
            "PlayerID": r["player_id"],
            "Name": r["player_name"],
            "Captain": "TRUE" if r["is_captain"] else "FALSE",
            "ViceCaptain": "TRUE" if r["is_vice_captain"] else "FALSE",
        }
        for r in rows
    ]


def get_user_team(user_id, match_id) -> list[dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT ut.*, p.name AS player_name, p.team, p.role
        FROM user_teams ut
        JOIN players p ON p.id = ut.player_id
        WHERE ut.user_id = ? AND ut.match_id = ?
        """,
        (int(user_id), int(match_id)),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_user_backups(user_id: int, match_id: int) -> list[dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT
            tb.backup_order,
            tb.backup_player_id,
            tb.replaced_player_id,
            bp.name AS backup_player_name,
            bp.team AS backup_team,
            bp.role AS backup_role,
            rp.name AS replaced_player_name
        FROM team_backups tb
        JOIN players bp ON bp.id = tb.backup_player_id
        LEFT JOIN players rp ON rp.id = tb.replaced_player_id
        WHERE tb.user_id = ? AND tb.match_id = ?
        ORDER BY tb.backup_order
        """,
        (int(user_id), int(match_id)),
    ).fetchall()
    return _rows_to_dicts(rows)


def save_user_backups(user_id: int, match_id: int, backup_player_ids: list[int]) -> None:
    db = get_db()
    db.execute(
        "DELETE FROM team_backups WHERE user_id = ? AND match_id = ?",
        (int(user_id), int(match_id)),
    )
    for index, player_id in enumerate(backup_player_ids[:3], start=1):
        db.execute(
            """
            INSERT INTO team_backups (user_id, match_id, backup_order, backup_player_id, replaced_player_id)
            VALUES (?, ?, ?, ?, NULL)
            """,
            (int(user_id), int(match_id), index, int(player_id)),
        )
    db.commit()
    invalidate_user_team_summary_cache(int(user_id), int(match_id))


def prune_user_backups(user_id: int, match_id: int, selected_player_ids: list[int]) -> None:
    db = get_db()
    selected_ids = [int(player_id) for player_id in selected_player_ids]
    if selected_ids:
        placeholders = ",".join("?" * len(selected_ids))
        db.execute(
            f"""
            DELETE FROM team_backups
            WHERE user_id = ? AND match_id = ? AND backup_player_id IN ({placeholders})
            """,
            [int(user_id), int(match_id), *selected_ids],
        )
    rows = db.execute(
        """
        SELECT id, backup_player_id
        FROM team_backups
        WHERE user_id = ? AND match_id = ?
        ORDER BY backup_order
        """,
        (int(user_id), int(match_id)),
    ).fetchall()
    for order_index, row in enumerate(rows, start=1):
        db.execute(
            "UPDATE team_backups SET backup_order = ? WHERE id = ?",
            (order_index, row["id"]),
        )
    db.commit()
    invalidate_user_team_summary_cache(int(user_id), int(match_id))


def log_unknown_player(name: str, team: str, match_id: int, match_date: str, team1: str, team2: str) -> None:
    """Record an unresolved player mapping for later review."""
    cleaned_name = " ".join(str(name or "").split()).strip()
    cleaned_team = " ".join(str(team or "").split()).strip()
    if not cleaned_name or not cleaned_team:
        return

    db = get_db()
    db.execute(
        """
        INSERT INTO unknown_players (name, team, match_id, match_date, team1, team2)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name, team, match_id, match_date, team1, team2) DO NOTHING
        """,
        (
            cleaned_name,
            cleaned_team,
            int(match_id),
            str(match_date or ""),
            str(team1 or ""),
            str(team2 or ""),
        ),
    )
    db.commit()


def get_backup_counts_for_user(user_id: int, match_ids: list[int | str]) -> dict[int, int]:
    if not match_ids:
        return {}
    normalized_ids = [int(match_id) for match_id in match_ids]
    summaries = get_cached_user_team_summaries(int(user_id), normalized_ids)
    return {
        match_id: int((summaries.get(match_id) or {}).get("backup_count") or 0)
        for match_id in normalized_ids
    }


def get_active_backup_replacements(match_id: int, user_id: int | None = None) -> dict[int, dict]:
    db = get_db()
    params: list[int] = [int(match_id)]
    query = """
        SELECT
            tb.user_id,
            tb.backup_player_id,
            tb.replaced_player_id
        FROM team_backups tb
        WHERE tb.match_id = ?
          AND tb.replaced_player_id IS NOT NULL
    """
    if user_id is not None:
        query += " AND tb.user_id = ?"
        params.append(int(user_id))
    rows = db.execute(query, params).fetchall()
    return {
        int(row["backup_player_id"]): {
            "user_id": int(row["user_id"]),
            "replaced_player_id": int(row["replaced_player_id"]),
        }
        for row in rows
    }


def apply_backups_for_match(match_id: int | str, playing_ids: list[int], substitute_ids: list[int]) -> int:
    if len(playing_ids) != 22 or len(substitute_ids) != 10:
        return 0

    db = get_db()
    mid = int(match_id)
    playing_set = {int(pid) for pid in playing_ids}
    substitute_set = {int(pid) for pid in substitute_ids}

    team_rows = db.execute(
        """
        SELECT
            ut.id,
            ut.user_id,
            ut.player_id,
            ut.is_captain,
            ut.is_vice_captain
        FROM user_teams ut
        JOIN users u ON u.id = ut.user_id
        WHERE ut.match_id = ?
          AND u.is_active = 1
        ORDER BY ut.user_id, ut.is_captain DESC, ut.is_vice_captain DESC, ut.id
        """,
        (mid,),
    ).fetchall()

    backups = db.execute(
        """
        SELECT id, user_id, backup_order, backup_player_id, replaced_player_id
        FROM team_backups
        WHERE match_id = ?
        ORDER BY user_id, backup_order
        """,
        (mid,),
    ).fetchall()

    team_rows_by_user: dict[int, list[dict]] = {}
    for row in team_rows:
        team_rows_by_user.setdefault(int(row["user_id"]), []).append(dict(row))

    backups_by_user: dict[int, list[dict]] = {}
    for row in backups:
        backups_by_user.setdefault(int(row["user_id"]), []).append(dict(row))

    all_player_ids = {
        int(row["player_id"]) for rows in team_rows_by_user.values() for row in rows
    } | {
        int(row["backup_player_id"]) for rows in backups_by_user.values() for row in rows
    }
    player_roles: dict[int, str] = {}
    if all_player_ids:
        placeholders = ",".join("?" * len(all_player_ids))
        role_rows = db.execute(
            f"SELECT id, role FROM players WHERE id IN ({placeholders})",
            list(all_player_ids),
        ).fetchall()
        player_roles = {int(row["id"]): row["role"] for row in role_rows}

    required_roles = {"Batter", "Bowler", "Wicketkeeper", "AllRounder"}

    def role_counts_for_team(team_rows_for_user: list[dict]) -> dict[str, int]:
        counts = {role: 0 for role in required_roles}
        for team_row in team_rows_for_user:
            role = player_roles.get(int(team_row["player_id"]))
            if role in counts:
                counts[role] += 1
        return counts

    def can_swap_without_breaking_roles(
        counts: dict[str, int],
        old_player_id: int,
        new_player_id: int,
    ) -> bool:
        next_counts = counts.copy()
        old_role = player_roles.get(old_player_id)
        new_role = player_roles.get(new_player_id)
        if old_role in next_counts:
            next_counts[old_role] -= 1
        if new_role in next_counts:
            next_counts[new_role] += 1
        return all(next_counts[role] >= 1 for role in required_roles)

    swap_count = 0
    changed_user_ids: set[int] = set()
    for user_id, user_team_rows in team_rows_by_user.items():
        selected_ids = {int(row["player_id"]) for row in user_team_rows}
        role_counts = role_counts_for_team(user_team_rows)
        replace_substitutes_with_backups = get_user_backup_preference(user_id)

        for backup_row in backups_by_user.get(user_id, []):
            if backup_row["replaced_player_id"] is not None:
                continue

            new_player_id = int(backup_row["backup_player_id"])
            replacement_eligible_set = (
                playing_set
                if replace_substitutes_with_backups
                else playing_set | substitute_set
            )
            if new_player_id not in replacement_eligible_set or new_player_id in selected_ids:
                continue

            invalid_rows = [
                row for row in user_team_rows
                if int(row["player_id"]) not in playing_set
            ]
            if not invalid_rows:
                break

            preferred_invalid_rows = [
                row for row in invalid_rows
                if int(row["player_id"]) not in substitute_set
            ]
            candidate_rows = invalid_rows if replace_substitutes_with_backups else preferred_invalid_rows

            chosen_invalid_row = None
            for invalid_row in candidate_rows:
                old_player_id = int(invalid_row["player_id"])
                if can_swap_without_breaking_roles(role_counts, old_player_id, new_player_id):
                    chosen_invalid_row = invalid_row
                    break

            if not chosen_invalid_row:
                continue

            old_player_id = int(chosen_invalid_row["player_id"])
            db.execute(
                "UPDATE user_teams SET player_id = ? WHERE id = ?",
                (new_player_id, int(chosen_invalid_row["id"])),
            )
            db.execute(
                "UPDATE team_backups SET replaced_player_id = ? WHERE id = ?",
                (old_player_id, int(backup_row["id"])),
            )
            chosen_invalid_row["player_id"] = new_player_id
            selected_ids.discard(old_player_id)
            selected_ids.add(new_player_id)
            old_role = player_roles.get(old_player_id)
            new_role = player_roles.get(new_player_id)
            if old_role in role_counts:
                role_counts[old_role] -= 1
            if new_role in role_counts:
                role_counts[new_role] += 1
            swap_count += 1
            changed_user_ids.add(int(user_id))

    if swap_count:
        db.commit()
        for changed_user_id in changed_user_ids:
            refresh_user_team_summary_cache(changed_user_id, mid)
    return swap_count


def save_team(mobile, name, match_id, selected_players, captain, vice_captain, players_data=None):
    """Persist a user's team selection for a match.

    Signature kept compatible with the old JSON version called from
    ``routes/team.py``:
        save_team(mobile, name, match_id, selected_ids, captain, vice_captain, players_data)
    """
    db = get_db()

    # Resolve user_id from mobile
    user = db.execute(
        "SELECT id FROM users WHERE mobile = ?", (str(mobile),)
    ).fetchone()
    if not user:
        raise ValueError(f"No user found with mobile {mobile}")
    user_id = user["id"]

    mid = int(match_id)

    # Remove previous selections for this user + match
    db.execute(
        "DELETE FROM user_teams WHERE user_id = ? AND match_id = ?",
        (user_id, mid),
    )

    # Insert new selections
    updated_at = get_current_datetime().strftime("%Y-%m-%d %H:%M:%S")
    for pid in selected_players:
        is_cap = 1 if str(pid) == str(captain) else 0
        is_vc = 1 if str(pid) == str(vice_captain) else 0
        db.execute(
            """INSERT INTO user_teams (user_id, match_id, player_id, is_captain, is_vice_captain, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, mid, int(pid), is_cap, is_vc, updated_at),
          )

    db.commit()
    prune_user_backups(user_id, mid, [int(pid) for pid in selected_players])
    refresh_match_contestant_cache(mid)
    refresh_user_team_summary_cache(user_id, mid)


# ---------------------------------------------------------------------------
# Contestant Points
# ---------------------------------------------------------------------------

def get_contestant_points() -> list[dict]:
    """Return contestant points in the legacy format used by routes and
    tournament.py: User, Mobile, MatchID, Points, LastUpdated.
    """
    db = get_db()
    rows = db.execute(
        """
        SELECT
            u.id     AS user_id,
            u.name   AS user_name,
            u.mobile AS mobile,
            cp.match_id,
            cp.points,
            cp.last_updated
        FROM contestant_points cp
        JOIN users u ON u.id = cp.user_id
        """
    ).fetchall()
    return [
        {
            "UserID": r["user_id"],
            "User": r["user_name"],
            "Mobile": r["mobile"] or "",
            "MatchID": str(r["match_id"]),
            "Points": r["points"],
            "LastUpdated": r["last_updated"],
        }
        for r in rows
    ]


def save_contestant_points(rows: list[dict]) -> None:
    """Persist contestant points.

    Each dict in *rows* is expected to have:
        User, Mobile, MatchID, Points, LastUpdated
    (produced by ``Tournament.persist_to_local``).
    """
    def _save():
        db = get_db()
        upsert_rows = {}

        for row in rows:
            user_id = row.get("UserID")
            mobile = str(row.get("Mobile", ""))
            match_id = int(row["MatchID"])
            points = float(row["Points"])
            last_updated = row.get("LastUpdated", get_current_datetime().strftime("%Y-%m-%d %H:%M:%S"))

            user = None
            if user_id is not None:
                user = db.execute("SELECT id FROM users WHERE id = ?", (int(user_id),)).fetchone()
            if not user and mobile:
                user = db.execute(
                    "SELECT id FROM users WHERE mobile = ?", (mobile,)
                ).fetchone()
            if not user:
                continue

            resolved_user_id = int(user["id"])
            upsert_rows[(resolved_user_id, match_id)] = (
                resolved_user_id,
                match_id,
                points,
                last_updated,
            )

        for user_id, match_id in sorted(upsert_rows):
            _, _, points, last_updated = upsert_rows[(user_id, match_id)]
            db.execute(
                """
                INSERT INTO contestant_points (user_id, match_id, points, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, match_id) DO UPDATE SET
                    points = excluded.points,
                    last_updated = excluded.last_updated
                """,
                (user_id, match_id, points, last_updated),
            )

        db.commit()

    _retry_deadlock(_save)


def get_computed_match_ids() -> set[str]:
    db = get_db()
    rows = db.execute(
        """
        SELECT DISTINCT match_id
        FROM player_points
        UNION
        SELECT DISTINCT match_id
        FROM contestant_points
        """
    ).fetchall()
    return {str(row["match_id"]) for row in rows}


def has_persisted_match_points(match_id: int) -> bool:
    db = get_db()
    row = db.execute(
        """
        SELECT 1
        FROM player_points
        WHERE match_id = ?
        LIMIT 1
        """,
        (int(match_id),),
    ).fetchone()
    if row:
        return True
    row = db.execute(
        """
        SELECT 1
        FROM contestant_points
        WHERE match_id = ?
        LIMIT 1
        """,
        (int(match_id),),
    ).fetchone()
    return bool(row)


def get_latest_player_points_update(match_id: int | None = None) -> str:
    db = get_db()
    if match_id is None:
        row = db.execute("SELECT COALESCE(MAX(last_updated), '') AS latest FROM player_points").fetchone()
    else:
        row = db.execute(
            "SELECT COALESCE(MAX(last_updated), '') AS latest FROM player_points WHERE match_id = ?",
            (int(match_id),),
        ).fetchone()
    return (row["latest"] if row else "") or ""


def delete_inactive_contestant_points() -> None:
    db = get_db()
    db.execute(
        """
        DELETE FROM contestant_points
        WHERE user_id IN (
            SELECT id FROM users WHERE is_active = 0
        )
        """
    )
    db.commit()


# ---------------------------------------------------------------------------
# Player Points
# ---------------------------------------------------------------------------

def get_player_points() -> list[dict]:
    """Return player points in the legacy format: MatchID, PlayerID,
    PlayerName, Team, Role, Points, LastUpdated.
    """
    db = get_db()
    rows = db.execute("SELECT * FROM player_points").fetchall()
    return [
        {
            "MatchID": str(r["match_id"]),
            "PlayerID": r["player_id"],
            "PlayerName": r["player_name"],
            "Team": r["team"],
            "Role": r["role"],
            "Points": r["points"],
            "LastUpdated": r["last_updated"],
        }
        for r in rows
    ]


def save_player_points(rows: list[dict]) -> None:
    """Persist player points.

    Each dict in *rows* is expected to have:
        MatchID, PlayerID, PlayerName, Team, Role, Points, LastUpdated
    (produced by ``Tournament.persist_player_points_to_local``).
    """
    def _save():
        db = get_db()
        upsert_rows = {}

        for row in rows:
            match_id = int(row["MatchID"])
            player_id = int(row["PlayerID"])
            player_name = row.get("PlayerName", "")
            team = row.get("Team", "")
            role = row.get("Role", "")
            points = float(row["Points"])
            last_updated = row.get("LastUpdated", get_current_datetime().strftime("%Y-%m-%d %H:%M:%S"))
            upsert_rows[(match_id, player_id)] = (
                match_id,
                player_id,
                player_name,
                team,
                role,
                points,
                last_updated,
            )

        for match_id, player_id in sorted(upsert_rows):
            _, _, player_name, team, role, points, last_updated = upsert_rows[(match_id, player_id)]
            db.execute(
                """
                INSERT INTO player_points
                    (match_id, player_id, player_name, team, role, points, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id, player_id) DO UPDATE SET
                    player_name = excluded.player_name,
                    team = excluded.team,
                    role = excluded.role,
                    points = excluded.points,
                    last_updated = excluded.last_updated
                """,
                (match_id, player_id, player_name, team, role, points, last_updated),
            )

        db.commit()
        if any(int(match_id) in {71, 72, 73, 74} for match_id, _player_id in upsert_rows):
            try:
                from backend.services import super_team_service

                super_team_service.invalidate_player_pool_cache()
                super_team_service.refresh_super_team_standings_cache()
            except Exception:
                pass

    _retry_deadlock(_save)


# ---------------------------------------------------------------------------
# Score Predictions
# ---------------------------------------------------------------------------

PREDICTION_BONUS_TIERS = [
    {"label": "Perfect Strike", "max_diff": 0.5, "bonus": 500},
    {"label": "Elite Precision", "max_diff": 5, "bonus": 200},
    {"label": "Great Call", "max_diff": 10, "bonus": 100},
]


def save_score_prediction(user_id: int, match_id: int, predicted_points: float) -> None:
    db = get_db()
    created_at = get_current_datetime().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """
        INSERT INTO score_predictions (user_id, match_id, predicted_points, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, match_id) DO UPDATE SET
            predicted_points = excluded.predicted_points,
            created_at = excluded.created_at
        """,
        (user_id, match_id, predicted_points, created_at),
    )
    db.commit()
    set_cached_score_prediction(user_id, match_id, predicted_points)


def get_score_prediction(user_id: int, match_id: int) -> float | None:
    cached = get_cached_match_predictions(match_id)
    if user_id in cached:
        return float(cached[int(user_id)])

    db = get_db()
    row = db.execute(
        "SELECT predicted_points FROM score_predictions WHERE user_id = ? AND match_id = ?",
        (user_id, match_id),
    ).fetchone()
    if row:
        predicted_points = float(row["predicted_points"])
        set_cached_score_prediction(user_id, match_id, predicted_points)
        return predicted_points
    return None


def get_match_predictions(match_id: int) -> dict[int, float]:
    """Return {user_id: predicted_points} for all predictions on a match."""
    cached = get_cached_match_predictions(match_id)
    if cached:
        return cached

    db = get_db()
    rows = db.execute(
        "SELECT user_id, predicted_points FROM score_predictions WHERE match_id = ?",
        (match_id,),
    ).fetchall()
    predictions = {int(r["user_id"]): float(r["predicted_points"]) for r in rows}
    if predictions:
        with SCORE_PREDICTION_LOCK:
            SCORE_PREDICTION_CACHE[int(match_id)] = dict(predictions)
    return predictions


def compute_prediction_bonuses(match_id: int) -> dict[int, dict]:
    """Compute prediction bonuses for a completed match.

    Returns {user_id: {"bonus": float, "label": str, "diff": float, "predicted": float}}
    """
    predictions = get_match_predictions(match_id)
    if not predictions:
        return {}

    db = get_db()
    rows = db.execute(
        "SELECT user_id, points FROM contestant_points WHERE match_id = ?",
        (match_id,),
    ).fetchall()
    actual_points = {int(r["user_id"]): float(r["points"]) for r in rows}

    if not actual_points:
        return {}

    # Build list of (user_id, diff, predicted) for users who both predicted and participated
    user_diffs = []
    for user_id, predicted in predictions.items():
        actual = actual_points.get(user_id)
        if actual is None:
            continue
        diff = abs(predicted - actual)
        user_diffs.append({"user_id": user_id, "diff": diff, "predicted": predicted})

    if not user_diffs:
        return {}

    # Sort by diff ascending (closest first)
    user_diffs.sort(key=lambda x: x["diff"])

    # Evaluate tiers top-down. The FIRST tier that has eligible users wins
    # — no lower tiers are evaluated. Within that tier, only the closest
    # user(s) get the bonus. If multiple users share the same closest diff,
    # all of them receive the full bonus.
    for tier in PREDICTION_BONUS_TIERS:
        eligible = [u for u in user_diffs if u["diff"] <= tier["max_diff"]]
        if not eligible:
            continue

        min_diff = min(u["diff"] for u in eligible)
        winners = [u for u in eligible if u["diff"] == min_diff]

        return {
            winner["user_id"]: {
                "bonus": tier["bonus"],
                "label": tier["label"],
                "diff": winner["diff"],
                "predicted": winner["predicted"],
            }
            for winner in winners
        }

    return {}
