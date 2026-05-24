import copy
import threading
from collections import defaultdict
from datetime import datetime

from fastapi import HTTPException

from backend.config import IST, get_current_datetime
from backend.database import get_db
from backend.services import data_service
from backend.services.match_status import resolve_match_status_from_row

SUPER_MATCH_IDS = [71, 72, 73, 74]
QUALIFIER_MATCH_IDS = [71, 72]
SUPER_TEAM_BONUSES_BY_RANK = {1: 400, 2: 200, 3: 100}
SUPER_TEAM_SIZE = 12
SUPER_TEAM_PLAYERS_PER_TEAM = 3
SUPER_TEAM_MAX_PLAYERS_PER_TEAM_AFTER_SUBS = 4
SUPER_TEAM_MIN_BOWLERS = 4
SUPER_TEAM_CAPTAIN_MULTIPLIER = 1.5
SUPER_TEAM_VICE_CAPTAIN_MULTIPLIER = 1.2
SUPER_TEAM_REQUIRED_ROLES = ["Wicketkeeper", "Batter", "AllRounder"]
SUPER_TEAM_PLAYER_SUB_PENALTY = 100
SUPER_TEAM_CAPTAIN_CHANGE_PENALTY = 50
SUPER_TEAM_VICE_CAPTAIN_CHANGE_PENALTY = 25

SUPER_TEAM_CACHE_LOCK = threading.Lock()
SUPER_TEAM_CACHE: dict[int, dict] = {}
SUPER_STANDINGS_CACHE: list[dict] = []
SUPER_DETAILS_CACHE: dict = {"user_breakdowns": [], "player_points": []}
SUPER_STANDINGS_META: dict = {}
SUPER_TEAM_CACHE_LOADED = False
SUPER_PLAYER_POOL_CACHE: list[dict] = []
SUPER_PLAYER_POOL_KEY: tuple[str, ...] | None = None


def _now_str() -> str:
    return get_current_datetime().strftime("%Y-%m-%d %H:%M:%S")


def _is_tbd(team: str | None) -> bool:
    value = str(team or "").strip().lower()
    return not value or value in {"tbd", "tba", "to be decided", "qualifier", "winner", "loser"}


def _match_lookup() -> dict[int, dict]:
    return {int(row["MatchID"]): row for row in data_service.get_cached_data("matches")}


def _player_lookup() -> dict[int, dict]:
    return {int(row["PlayerID"]): row for row in data_service.get_cached_data("players")}


def _status_for_match(row: dict | None) -> str:
    if not row:
        return "missing"
    try:
        status, _locked = resolve_match_status_from_row({
            "id": row["MatchID"],
            "team1": row["Team1"],
            "team2": row["Team2"],
            "match_date": row["Date"],
            "match_time": row["Time"],
            "status": row.get("Status"),
            "toss_time": row.get("TossTime"),
        })
        return status
    except Exception:
        return str(row.get("Status") or "").strip().lower()


def _match_cutoff_reached(match_row: dict | None, *, use_toss_time: bool = True) -> bool:
    if not match_row:
        return True
    try:
        cutoff_time = match_row.get("TossTime") if use_toss_time and match_row.get("TossTime") else match_row["Time"]
        match_datetime = datetime.strptime(f"{match_row['Date']} {cutoff_time}", "%Y-%m-%d %H:%M")
        match_datetime = IST.localize(match_datetime)
    except Exception:
        return True
    return get_current_datetime() >= match_datetime


def _is_locked(match71: dict | None) -> bool:
    return _match_cutoff_reached(match71, use_toss_time=True)


def _substitution_window_open(matches: dict[int, dict]) -> bool:
    return (
        _status_for_match(matches.get(72)) == "completed"
        and not _match_cutoff_reached(matches.get(73), use_toss_time=True)
    )


def _substitution_finalized(matches: dict[int, dict]) -> bool:
    return _match_cutoff_reached(matches.get(73), use_toss_time=True)


def _substitution_team_list(matches: dict[int, dict]) -> list[str]:
    teams: list[str] = []
    for match_id in (73, 74):
        row = matches.get(match_id)
        if not row:
            continue
        for team in (row.get("Team1"), row.get("Team2")):
            if team and not _is_tbd(team) and team not in teams:
                teams.append(team)
    return teams


def get_context() -> dict:
    matches = _match_lookup()
    match71 = matches.get(71)
    match72 = matches.get(72)
    visible = True
    qualifier_rows = [match71, match72]
    teams: list[str] = []
    for row in qualifier_rows:
        if not row:
            continue
        for team in (row.get("Team1"), row.get("Team2")):
            if team and team not in teams:
                teams.append(team)
    enabled = visible and len(teams) == 4 and all(not _is_tbd(team) for team in teams)
    match74_completed = _status_for_match(matches.get(74)) == "completed"
    locked = _is_locked(match71)
    substitution_open = enabled and locked and _substitution_window_open(matches)
    substitution_finalized = enabled and locked and _substitution_finalized(matches)
    substitution_teams = _substitution_team_list(matches)
    return {
        "visible": visible,
        "enabled": enabled,
        "locked": locked,
        "can_edit": enabled and ((not locked) or substitution_open),
        "substitution_open": substitution_open,
        "substitution_finalized": substitution_finalized,
        "substitution_teams": substitution_teams,
        "bonus_visible": match74_completed,
        "teams": teams if enabled else [],
        "matches": {
            str(mid): copy.deepcopy(matches.get(mid))
            for mid in SUPER_MATCH_IDS
            if matches.get(mid)
        },
        "message": (
            "The playoff gates are shut for now. Once the final four are locked, Super Team turns into war mode."
            if not enabled
            else "Substitution window is open until Match 73 toss."
            if substitution_open
            else ""
        ),
    }


def _fetch_submissions_from_db() -> dict[int, dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT
            st.user_id,
            u.name AS user_name,
            st.player_id,
            st.is_captain,
            st.is_vice_captain,
            st.updated_at,
            st.updated_by
        FROM super_teams st
        JOIN users u ON u.id = st.user_id
        WHERE u.is_active = 1
        ORDER BY u.name, st.player_id
        """
    ).fetchall()
    grouped: dict[int, dict] = {}
    for row in rows:
        uid = int(row["user_id"])
        entry = grouped.setdefault(
            uid,
            {
                "user_id": uid,
                "name": row["user_name"],
                "player_ids": [],
                "captain": None,
                "vice_captain": None,
                "updated_at": row["updated_at"],
                "updated_by": row["updated_by"],
            },
        )
        player_id = int(row["player_id"])
        entry["player_ids"].append(player_id)
        if row["is_captain"]:
            entry["captain"] = player_id
        if row["is_vice_captain"]:
            entry["vice_captain"] = player_id
        if row["updated_at"]:
            entry["updated_at"] = row["updated_at"]
    return grouped


def _fetch_original_submissions_from_db() -> dict[int, dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT
            sto.user_id,
            u.name AS user_name,
            sto.player_id,
            sto.is_captain,
            sto.is_vice_captain,
            sto.snapshot_at
        FROM super_team_originals sto
        JOIN users u ON u.id = sto.user_id
        WHERE u.is_active = 1
        ORDER BY u.name, sto.player_id
        """
    ).fetchall()
    grouped: dict[int, dict] = {}
    for row in rows:
        uid = int(row["user_id"])
        entry = grouped.setdefault(
            uid,
            {
                "user_id": uid,
                "name": row["user_name"],
                "player_ids": [],
                "captain": None,
                "vice_captain": None,
                "snapshot_at": row["snapshot_at"],
            },
        )
        player_id = int(row["player_id"])
        entry["player_ids"].append(player_id)
        if row["is_captain"]:
            entry["captain"] = player_id
        if row["is_vice_captain"]:
            entry["vice_captain"] = player_id
        if row["snapshot_at"]:
            entry["snapshot_at"] = row["snapshot_at"]
    return grouped


def ensure_original_snapshots() -> int:
    """Persist the locked Match 71/72 team as the comparison baseline."""
    db = get_db()
    existing_rows = db.execute("SELECT DISTINCT user_id FROM super_team_originals").fetchall()
    existing_user_ids = {int(row["user_id"]) for row in existing_rows}
    rows = db.execute(
        """
        SELECT user_id, player_id, is_captain, is_vice_captain
        FROM super_teams
        ORDER BY user_id, player_id
        """
    ).fetchall()
    snapshot_at = _now_str()
    inserted = 0
    for row in rows:
        if int(row["user_id"]) in existing_user_ids:
            continue
        db.execute(
            """
            INSERT INTO super_team_originals
                (user_id, player_id, is_captain, is_vice_captain, snapshot_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(row["user_id"]),
                int(row["player_id"]),
                int(row["is_captain"] or 0),
                int(row["is_vice_captain"] or 0),
                snapshot_at,
            ),
        )
        inserted += 1
    db.commit()
    return inserted


def _penalty_details(original: dict | None, current: dict | None) -> dict:
    if not original or not current:
        return {
            "total": 0,
            "new_player_count": 0,
            "new_player_penalty": 0,
            "captain_changed": False,
            "captain_penalty": 0,
            "vice_captain_changed": False,
            "vice_captain_penalty": 0,
            "new_player_ids": [],
        }
    original_ids = {int(pid) for pid in original.get("player_ids", [])}
    current_ids = {int(pid) for pid in current.get("player_ids", [])}
    new_player_ids = sorted(current_ids - original_ids)
    captain_changed = int(original.get("captain") or 0) != int(current.get("captain") or 0)
    vice_captain_changed = int(original.get("vice_captain") or 0) != int(current.get("vice_captain") or 0)
    new_player_penalty = len(new_player_ids) * SUPER_TEAM_PLAYER_SUB_PENALTY
    captain_penalty = SUPER_TEAM_CAPTAIN_CHANGE_PENALTY if captain_changed else 0
    vice_captain_penalty = SUPER_TEAM_VICE_CAPTAIN_CHANGE_PENALTY if vice_captain_changed else 0
    total = new_player_penalty + captain_penalty + vice_captain_penalty
    return {
        "total": total,
        "new_player_count": len(new_player_ids),
        "new_player_penalty": new_player_penalty,
        "captain_changed": captain_changed,
        "captain_penalty": captain_penalty,
        "vice_captain_changed": vice_captain_changed,
        "vice_captain_penalty": vice_captain_penalty,
        "new_player_ids": new_player_ids,
    }


def _penalty_lookup(submissions: dict[int, dict] | None = None) -> dict[int, dict]:
    current = submissions or get_submissions()
    originals = _fetch_original_submissions_from_db()
    return {
        int(uid): _penalty_details(originals.get(int(uid)), entry)
        for uid, entry in current.items()
    }


def prime_super_team_cache() -> dict:
    global SUPER_TEAM_CACHE_LOADED
    context = get_context()
    if context.get("substitution_open") or context.get("substitution_finalized"):
        ensure_original_snapshots()
    submissions = _fetch_submissions_from_db()
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_TEAM_CACHE.clear()
        SUPER_TEAM_CACHE.update(copy.deepcopy(submissions))
        SUPER_TEAM_CACHE_LOADED = True
    refresh_super_team_standings_cache()
    return {"teams": len(submissions), "standings": len(SUPER_STANDINGS_CACHE)}


def invalidate_player_pool_cache() -> None:
    global SUPER_PLAYER_POOL_KEY
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_PLAYER_POOL_KEY = None
        SUPER_PLAYER_POOL_CACHE.clear()


def get_submissions() -> dict[int, dict]:
    with SUPER_TEAM_CACHE_LOCK:
        if SUPER_TEAM_CACHE_LOADED:
            return copy.deepcopy(SUPER_TEAM_CACHE)
    return prime_and_get_submissions()


def prime_and_get_submissions() -> dict[int, dict]:
    prime_super_team_cache()
    with SUPER_TEAM_CACHE_LOCK:
        return copy.deepcopy(SUPER_TEAM_CACHE)


def _original_player_ids_for_user(user_id: int | None) -> set[int]:
    if user_id is None:
        return set()
    originals = _fetch_original_submissions_from_db()
    original = originals.get(int(user_id))
    if not original:
        return set()
    return {int(pid) for pid in original.get("player_ids", [])}


def _build_player_pool(user_id: int | None = None) -> list[dict]:
    global SUPER_PLAYER_POOL_KEY
    context = get_context()
    original_ids = _original_player_ids_for_user(user_id) if context.get("substitution_open") else set()
    teams = set(context.get("substitution_teams") or context["teams"]) if context.get("substitution_open") else set(context["teams"])
    if not teams and not original_ids:
        return []
    cache_key = tuple([str(user_id or 0), *sorted(teams), *[str(pid) for pid in sorted(original_ids)]])
    with SUPER_TEAM_CACHE_LOCK:
        if SUPER_PLAYER_POOL_KEY == cache_key:
            return copy.deepcopy(SUPER_PLAYER_POOL_CACHE)
    db = get_db()
    clauses = []
    params: list = []
    if teams:
        clauses.append(f"p.team IN ({','.join('?' * len(teams))})")
        params.extend(list(teams))
    if original_ids:
        clauses.append(f"p.id IN ({','.join('?' * len(original_ids))})")
        params.extend(sorted(original_ids))
    where_clause = " OR ".join(clauses)
    rows = db.execute(
        f"""
        SELECT
            p.id,
            p.name,
            p.team,
            p.role,
            p.type,
            p.aliases,
            COALESCE(SUM(pp.points), 0) AS total_points,
            COUNT(pp.match_id) AS matches_played,
            CASE WHEN COUNT(pp.match_id) > 0
                 THEN ROUND(CAST(COALESCE(SUM(pp.points), 0) * 1.0 / COUNT(pp.match_id) AS numeric), 2)
                 ELSE 0 END AS avg_points
        FROM players p
        LEFT JOIN player_points pp ON pp.player_id = p.id
        WHERE {where_clause}
        GROUP BY p.id, p.name, p.team, p.role, p.type, p.aliases
        ORDER BY p.team, p.role, total_points DESC, p.name
        """,
        params,
    ).fetchall()
    player_ids = [int(row["id"]) for row in rows]
    history_by_player = _load_recent_history(db, list(teams), player_ids)
    last_match_map = _load_last_match_points(db)
    players = []
    for row in rows:
        player = dict(row)
        player["total_points"] = round(float(player.get("total_points") or 0), 2)
        player["matches_played"] = int(player.get("matches_played") or 0)
        player["avg_points"] = round(float(player.get("avg_points") or 0), 2)
        player["last_match_points"] = last_match_map.get(int(player["id"]))
        player["recent_history"] = history_by_player.get(int(player["id"]), [])
        players.append(player)
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_PLAYER_POOL_KEY = cache_key
        SUPER_PLAYER_POOL_CACHE.clear()
        SUPER_PLAYER_POOL_CACHE.extend(copy.deepcopy(players))
    return players


def _load_last_match_points(db) -> dict[int, float]:
    rows = db.execute(
        """
        SELECT pp.player_id, pp.points
        FROM player_points pp
        INNER JOIN (
            SELECT player_id, MAX(match_id) AS max_mid
            FROM player_points
            GROUP BY player_id
        ) latest ON pp.player_id = latest.player_id AND pp.match_id = latest.max_mid
        """
    ).fetchall()
    return {int(row["player_id"]): round(float(row["points"] or 0), 2) for row in rows}


def _load_recent_history(db, teams: list[str], player_ids: list[int]) -> dict[int, list[dict]]:
    if not teams or not player_ids:
        return {}
    team_placeholders = ",".join("?" * len(teams))
    matches_rows = db.execute(
        f"""
        SELECT id, team1, team2
        FROM matches
        WHERE status = 'completed'
          AND (team1 IN ({team_placeholders}) OR team2 IN ({team_placeholders}))
        ORDER BY id DESC
        """,
        [*teams, *teams],
    ).fetchall()
    match_ids = [int(row["id"]) for row in matches_rows]
    if not match_ids:
        return {}
    point_rows = db.execute(
        f"""
        SELECT match_id, player_id, points
        FROM player_points
        WHERE player_id IN ({",".join("?" * len(player_ids))})
          AND match_id IN ({",".join("?" * len(match_ids))})
        """,
        [*player_ids, *match_ids],
    ).fetchall()
    points = {
        (int(row["player_id"]), int(row["match_id"])): round(float(row["points"] or 0), 2)
        for row in point_rows
    }
    player_team = {int(row["PlayerID"]): row["Team"] for row in data_service.get_cached_data("players")}
    history: dict[int, list[dict]] = {pid: [] for pid in player_ids}
    for pid in player_ids:
        team = player_team.get(pid)
        for match in matches_rows:
            if match["team1"] != team and match["team2"] != team:
                continue
            mid = int(match["id"])
            history[pid].append({
                "match_id": mid,
                "opponent": match["team2"] if match["team1"] == team else match["team1"],
                "points": points.get((pid, mid)),
                "did_not_play": (pid, mid) not in points,
            })
    return history


def grouped_player_pool(user_id: int | None = None) -> dict[str, list[dict]]:
    grouped = {"Wicketkeeper": [], "Batter": [], "AllRounder": [], "Bowler": []}
    for player in _build_player_pool(user_id):
        grouped.setdefault(player["role"], []).append(player)
    return grouped


def _eligible_player_ids_for_context(context: dict, user_id: int | None = None) -> set[int]:
    players = _player_lookup()
    original_ids = _original_player_ids_for_user(user_id) if context.get("substitution_open") else set()
    eligible_teams = set(context.get("substitution_teams") or context["teams"]) if context.get("substitution_open") else set(context["teams"])
    return {
        int(pid)
        for pid, player in players.items()
        if player and (player["Team"] in eligible_teams or int(pid) in original_ids)
    }


def validate_selection(player_ids: list[int], user_id: int | None = None) -> list[int]:
    if len(player_ids) != SUPER_TEAM_SIZE:
        raise HTTPException(status_code=400, detail=f"Exactly {SUPER_TEAM_SIZE} players required")
    normalized = [int(pid) for pid in player_ids]
    if len(set(normalized)) != SUPER_TEAM_SIZE:
        raise HTTPException(status_code=400, detail="Duplicate players are not allowed")
    context = get_context()
    if not context["enabled"]:
        raise HTTPException(status_code=400, detail=context["message"] or "Super Team is not open")
    eligible_player_ids = _eligible_player_ids_for_context(context, user_id)
    players = _player_lookup()
    selected = [players.get(pid) for pid in normalized]
    if any(player is None for player in selected):
        raise HTTPException(status_code=400, detail="Some player IDs are invalid")
    if any(pid not in eligible_player_ids for pid in normalized):
        raise HTTPException(status_code=400, detail="Some players are not eligible for Super Team")
    role_counts = {
        role: sum(1 for player in selected if player and player["Role"] == role)
        for role in SUPER_TEAM_REQUIRED_ROLES
    }
    missing_roles = [role for role, count in role_counts.items() if count < 1]
    if missing_roles:
        raise HTTPException(status_code=400, detail="Select at least 1 Wicketkeeper, 1 Batter, and 1 AllRounder")
    bowler_count = sum(1 for player in selected if player and player["Role"] == "Bowler")
    if bowler_count < SUPER_TEAM_MIN_BOWLERS:
        raise HTTPException(status_code=400, detail=f"At least {SUPER_TEAM_MIN_BOWLERS} Bowlers required")
    team_counts: dict[str, int] = {}
    for player in selected:
        if player:
            team_counts[player["Team"]] = team_counts.get(player["Team"], 0) + 1
    if context.get("substitution_open"):
        over_limit_teams = [
            team for team, count in team_counts.items()
            if count > SUPER_TEAM_MAX_PLAYERS_PER_TEAM_AFTER_SUBS
        ]
        if over_limit_teams:
            raise HTTPException(
                status_code=400,
                detail=f"Select at most {SUPER_TEAM_MAX_PLAYERS_PER_TEAM_AFTER_SUBS} players from each team",
            )
        return normalized
    invalid_teams = [
        team for team in context["teams"]
        if team_counts.get(team, 0) != SUPER_TEAM_PLAYERS_PER_TEAM
    ]
    if invalid_teams:
        raise HTTPException(
            status_code=400,
            detail=f"Select exactly {SUPER_TEAM_PLAYERS_PER_TEAM} players from each playoff team",
        )
    return normalized


def validate_substitution_against_original(user_id: int, player_ids: list[int]) -> None:
    originals = _fetch_original_submissions_from_db()
    original = originals.get(int(user_id))
    if not original:
        return
    original_ids = {int(pid) for pid in original.get("player_ids", [])}
    final_ids = {int(pid) for pid in player_ids}
    if len(final_ids - original_ids) > len(original_ids - final_ids):
        raise HTTPException(status_code=400, detail="Every new Super Team player must replace one original player")


def validate_leaders(player_ids: list[int], captain: int, vice_captain: int) -> tuple[int, int]:
    normalized_set = {int(pid) for pid in player_ids}
    captain_id = int(captain)
    vice_captain_id = int(vice_captain)
    if captain_id == vice_captain_id:
        raise HTTPException(status_code=400, detail="Captain and vice-captain must be different")
    if captain_id not in normalized_set:
        raise HTTPException(status_code=400, detail="Captain must be one of the selected players")
    if vice_captain_id not in normalized_set:
        raise HTTPException(status_code=400, detail="Vice-captain must be one of the selected players")
    return captain_id, vice_captain_id


def _super_team_multiplier(player_id: int, captain: int | None, vice_captain: int | None) -> float:
    if captain is not None and int(player_id) == int(captain):
        return SUPER_TEAM_CAPTAIN_MULTIPLIER
    if vice_captain is not None and int(player_id) == int(vice_captain):
        return SUPER_TEAM_VICE_CAPTAIN_MULTIPLIER
    return 1.0


def _super_team_tag(player_id: int, captain: int | None, vice_captain: int | None) -> str:
    if captain is not None and int(player_id) == int(captain):
        return "C"
    if vice_captain is not None and int(player_id) == int(vice_captain):
        return "VC"
    return ""


def save_team(user_id: int, player_ids: list[int], captain: int, vice_captain: int, updated_by: int | None = None, ignore_lock: bool = False) -> dict:
    global SUPER_TEAM_CACHE_LOADED
    context = get_context()
    if context.get("substitution_open"):
        ensure_original_snapshots()
    if not context.get("can_edit") and not ignore_lock:
        raise HTTPException(status_code=400, detail="Super Team is locked")
    normalized = validate_selection(player_ids, int(user_id))
    if context.get("substitution_open") and not ignore_lock:
        validate_substitution_against_original(int(user_id), normalized)
    captain_id, vice_captain_id = validate_leaders(normalized, captain, vice_captain)
    db = get_db()
    user_row = db.execute("SELECT name FROM users WHERE id = ? AND is_active = 1", (int(user_id),)).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    updated_at = _now_str()
    db.execute("DELETE FROM super_teams WHERE user_id = ?", (int(user_id),))
    for pid in normalized:
        db.execute(
            """
            INSERT INTO super_teams (user_id, player_id, is_captain, is_vice_captain, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                int(pid),
                1 if int(pid) == captain_id else 0,
                1 if int(pid) == vice_captain_id else 0,
                updated_at,
                updated_by,
            ),
        )
    db.commit()
    entry = {
        "user_id": int(user_id),
        "name": user_row["name"],
        "player_ids": normalized,
        "captain": captain_id,
        "vice_captain": vice_captain_id,
        "updated_at": updated_at,
        "updated_by": updated_by,
    }
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_TEAM_CACHE[int(user_id)] = copy.deepcopy(entry)
        SUPER_TEAM_CACHE_LOADED = True
    refresh_super_team_standings_cache()
    return copy.deepcopy(entry)


def my_team(user_id: int) -> dict:
    submissions = get_submissions()
    entry = submissions.get(int(user_id))
    if not entry:
        return {"players": [], "updated_at": None, "penalty": _penalty_details(None, None)}
    players = _player_lookup()
    penalty = _penalty_lookup(submissions).get(int(user_id), _penalty_details(None, None))
    return {
        "players": [
            {
                "player_id": pid,
                "player_name": players.get(pid, {}).get("Name", ""),
                "team": players.get(pid, {}).get("Team", ""),
                "role": players.get(pid, {}).get("Role", ""),
                "is_captain": pid == entry.get("captain"),
                "is_vice_captain": pid == entry.get("vice_captain"),
            }
            for pid in entry["player_ids"]
        ],
        "captain": entry.get("captain"),
        "vice_captain": entry.get("vice_captain"),
        "updated_at": entry.get("updated_at"),
        "penalty": penalty,
    }


def contestants() -> list[dict]:
    return [
        {"user_id": entry["user_id"], "name": entry["name"], "last_team_updated": entry.get("updated_at")}
        for entry in sorted(get_submissions().values(), key=lambda item: item["name"])
    ]


def missing_users() -> list[dict]:
    submitted_user_ids = set(get_submissions().keys())
    users = data_service.get_cached_data("users")
    missing = []
    for user in users:
        try:
            user_id = int(user.get("UserID", 0) or 0)
        except Exception:
            continue
        if not user_id or user_id in submitted_user_ids:
            continue
        if str(user.get("Allowed", "")).strip().lower() != "true":
            continue
        missing.append({"id": user_id, "name": user.get("Name", "")})
    missing.sort(key=lambda item: item["name"])
    return missing


def _point_lookup_from_score_cache() -> dict[tuple[int, int], float]:
    lookup: dict[tuple[int, int], float] = {}
    try:
        from backend.routes.scores import get_cached_scores_snapshot
        snapshot = get_cached_scores_snapshot()
    except Exception:
        snapshot = {}
    for match_id in SUPER_MATCH_IDS:
        payload = snapshot.get(match_id) or snapshot.get(str(match_id)) or {}
        for player in payload.get("players", []):
            if player.get("player_id") is None:
                continue
            lookup[(int(match_id), int(player["player_id"]))] = float(player.get("points", 0) or 0)
    return lookup


def _point_lookup_from_db() -> dict[tuple[int, int], float]:
    db = get_db()
    rows = db.execute(
        f"""
        SELECT match_id, player_id, points
        FROM player_points
        WHERE match_id IN ({",".join("?" * len(SUPER_MATCH_IDS))})
        """,
        SUPER_MATCH_IDS,
    ).fetchall()
    return {(int(row["match_id"]), int(row["player_id"])): float(row["points"] or 0) for row in rows}


def refresh_super_team_standings_cache() -> dict:
    submissions = get_submissions()
    originals = _fetch_original_submissions_from_db()
    penalties = _penalty_lookup(submissions)
    context = get_context()
    penalty_applies = bool(context.get("substitution_finalized"))
    point_lookup = _point_lookup_from_db()
    point_lookup.update(_point_lookup_from_score_cache())
    players = _player_lookup()
    rows = []
    user_breakdowns = []
    max_points = None
    for entry in submissions.values():
        match_points: dict[int, float] = defaultdict(float)
        match_players: dict[int, list[dict]] = {match_id: [] for match_id in SUPER_MATCH_IDS}
        total = 0.0
        original_entry = originals.get(int(entry["user_id"]))
        score_entries_by_match = {
            71: original_entry or entry,
            72: original_entry or entry,
            73: entry,
            74: entry,
        }
        for match_id in SUPER_MATCH_IDS:
            score_entry = score_entries_by_match[match_id]
            match_captain = score_entry.get("captain")
            match_vice_captain = score_entry.get("vice_captain")
            for pid in score_entry["player_ids"]:
                player = players.get(int(pid), {})
                multiplier = _super_team_multiplier(int(pid), match_captain, match_vice_captain)
                tag = _super_team_tag(int(pid), match_captain, match_vice_captain)
                base_pts = float(point_lookup.get((match_id, int(pid)), 0))
                pts = base_pts * multiplier
                match_points[match_id] += pts
                total += pts
                match_players[match_id].append({
                    "player_id": int(pid),
                    "name": player.get("Name", ""),
                    "team": player.get("Team", ""),
                    "role": player.get("Role", ""),
                    "base_points": round(base_pts, 2),
                    "multiplier": multiplier,
                    "tag": tag,
                    "points": round(pts, 2),
                })
        gross_points = round(total, 2)
        penalty = penalties.get(int(entry["user_id"]), _penalty_details(None, None))
        total = round(gross_points - float(penalty.get("total", 0) or 0), 2) if penalty_applies else gross_points
        if max_points is None or total > max_points:
            max_points = total
        row = {
            "user_id": entry["user_id"],
            "name": entry["name"],
            "points": total,
            "gross_points": gross_points,
            "penalty": penalty,
            "penalty_applied": penalty_applies,
            "match_points": {str(k): round(v, 2) for k, v in match_points.items()},
            "updated_at": entry.get("updated_at"),
        }
        rows.append(row)
        user_breakdowns.append({
            **row,
            "matches": [
                {
                    "match_id": match_id,
                    "points": round(match_points.get(match_id, 0), 2),
                    "players": sorted(
                        match_players[match_id],
                        key=lambda item: (-float(item["points"]), item["name"]),
                    ),
                }
                for match_id in SUPER_MATCH_IDS
            ],
        })
    rows.sort(key=lambda item: (-item["points"], item["name"]))
    rank = 1
    for index, row in enumerate(rows):
        if index > 0 and row["points"] == rows[index - 1]["points"]:
            row["rank"] = rows[index - 1]["rank"]
        else:
            row["rank"] = rank = index + 1
    rank_by_user = {int(row["user_id"]): int(row["rank"]) for row in rows}
    for breakdown in user_breakdowns:
        breakdown["rank"] = rank_by_user.get(int(breakdown["user_id"]), 0)
    user_breakdowns.sort(key=lambda item: (int(item.get("rank") or 9999), item["name"]))

    player_ids = sorted({
        int(pid)
        for entry in [*submissions.values(), *originals.values()]
        for pid in entry.get("player_ids", [])
    })
    player_points = []
    for pid in player_ids:
        player = players.get(pid, {})
        match_point_map = {
            str(match_id): round(float(point_lookup.get((match_id, pid), 0)), 2)
            for match_id in SUPER_MATCH_IDS
        }
        total_points = round(sum(match_point_map.values()), 2)
        player_points.append({
            "player_id": pid,
            "name": player.get("Name", ""),
            "team": player.get("Team", ""),
            "role": player.get("Role", ""),
            "points": total_points,
            "match_points": match_point_map,
        })
    player_points.sort(key=lambda item: (-float(item["points"]), item["team"], item["name"]))

    bonus_by_user = {
        int(row["user_id"]): int(SUPER_TEAM_BONUSES_BY_RANK[int(row["rank"])])
        for row in rows
        if context["bonus_visible"] and int(row["rank"]) in SUPER_TEAM_BONUSES_BY_RANK
    }
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_STANDINGS_CACHE.clear()
        SUPER_STANDINGS_CACHE.extend(copy.deepcopy(rows))
        SUPER_DETAILS_CACHE.clear()
        SUPER_DETAILS_CACHE.update({
            "user_breakdowns": copy.deepcopy(user_breakdowns),
            "player_points": copy.deepcopy(player_points),
        })
        SUPER_STANDINGS_META.clear()
        SUPER_STANDINGS_META.update({
            "bonus_visible": context["bonus_visible"],
            "bonus_by_user": bonus_by_user,
        })
    return {"standings": len(rows), "bonus_users": len(bonus_by_user)}


def standings() -> list[dict]:
    with SUPER_TEAM_CACHE_LOCK:
        return copy.deepcopy(SUPER_STANDINGS_CACHE)


def details() -> dict:
    with SUPER_TEAM_CACHE_LOCK:
        return copy.deepcopy(SUPER_DETAILS_CACHE)


def bonus_map() -> dict[int, int]:
    context = get_context()
    if not context["bonus_visible"]:
        return {}
    with SUPER_TEAM_CACHE_LOCK:
        if not SUPER_STANDINGS_CACHE:
            pass
        else:
            return {int(uid): int(bonus) for uid, bonus in SUPER_STANDINGS_META.get("bonus_by_user", {}).items()}
    refresh_super_team_standings_cache()
    with SUPER_TEAM_CACHE_LOCK:
        return {int(uid): int(bonus) for uid, bonus in SUPER_STANDINGS_META.get("bonus_by_user", {}).items()}
