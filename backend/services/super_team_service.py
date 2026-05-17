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
SUPER_TEAM_BONUS = 400
SUPER_TEAM_SIZE = 12
SUPER_TEAM_PLAYERS_PER_TEAM = 3
SUPER_TEAM_MIN_BOWLERS = 3
SUPER_TEAM_ROLES = ["Wicketkeeper", "Batter", "AllRounder", "Bowler"]

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


def _is_locked(match71: dict | None) -> bool:
    if not match71:
        return True
    try:
        match_datetime = datetime.strptime(f"{match71['Date']} {match71['Time']}", "%Y-%m-%d %H:%M")
        match_datetime = IST.localize(match_datetime)
    except Exception:
        return True
    return get_current_datetime() >= match_datetime


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
    return {
        "visible": visible,
        "enabled": enabled,
        "locked": _is_locked(match71),
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
            else ""
        ),
    }


def _fetch_submissions_from_db() -> dict[int, dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT st.user_id, u.name AS user_name, st.player_id, st.updated_at, st.updated_by
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
                "updated_at": row["updated_at"],
                "updated_by": row["updated_by"],
            },
        )
        entry["player_ids"].append(int(row["player_id"]))
        if row["updated_at"]:
            entry["updated_at"] = row["updated_at"]
    return grouped


def prime_super_team_cache() -> dict:
    global SUPER_TEAM_CACHE_LOADED
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


def _build_player_pool() -> list[dict]:
    global SUPER_PLAYER_POOL_KEY
    context = get_context()
    teams = set(context["teams"])
    if not teams:
        return []
    cache_key = tuple(sorted(teams))
    with SUPER_TEAM_CACHE_LOCK:
        if SUPER_PLAYER_POOL_KEY == cache_key:
            return copy.deepcopy(SUPER_PLAYER_POOL_CACHE)
    db = get_db()
    placeholders = ",".join("?" * len(teams))
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
        WHERE p.team IN ({placeholders})
        GROUP BY p.id, p.name, p.team, p.role, p.type, p.aliases
        ORDER BY p.team, p.role, total_points DESC, p.name
        """,
        list(teams),
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


def grouped_player_pool() -> dict[str, list[dict]]:
    grouped = {"Wicketkeeper": [], "Batter": [], "AllRounder": [], "Bowler": []}
    for player in _build_player_pool():
        grouped.setdefault(player["role"], []).append(player)
    return grouped


def validate_selection(player_ids: list[int]) -> list[int]:
    if len(player_ids) != SUPER_TEAM_SIZE:
        raise HTTPException(status_code=400, detail=f"Exactly {SUPER_TEAM_SIZE} players required")
    normalized = [int(pid) for pid in player_ids]
    if len(set(normalized)) != SUPER_TEAM_SIZE:
        raise HTTPException(status_code=400, detail="Duplicate players are not allowed")
    context = get_context()
    if not context["enabled"]:
        raise HTTPException(status_code=400, detail=context["message"] or "Super Team is not open")
    eligible_teams = set(context["teams"])
    players = _player_lookup()
    selected = [players.get(pid) for pid in normalized]
    if any(player is None for player in selected):
        raise HTTPException(status_code=400, detail="Some player IDs are invalid")
    if any(player["Team"] not in eligible_teams for player in selected if player):
        raise HTTPException(status_code=400, detail="Some players are not eligible for Super Team")
    role_counts = {
        role: sum(1 for player in selected if player and player["Role"] == role)
        for role in SUPER_TEAM_ROLES
    }
    missing_roles = [role for role, count in role_counts.items() if count < 1]
    if missing_roles:
        raise HTTPException(status_code=400, detail="Select at least 1 player from each role")
    bowler_count = sum(1 for player in selected if player and player["Role"] == "Bowler")
    if bowler_count < SUPER_TEAM_MIN_BOWLERS:
        raise HTTPException(status_code=400, detail=f"At least {SUPER_TEAM_MIN_BOWLERS} Bowlers required")
    team_counts = {
        team: sum(1 for player in selected if player and player["Team"] == team)
        for team in eligible_teams
    }
    invalid_teams = [team for team, count in team_counts.items() if count != SUPER_TEAM_PLAYERS_PER_TEAM]
    if invalid_teams:
        raise HTTPException(
            status_code=400,
            detail=f"Select exactly {SUPER_TEAM_PLAYERS_PER_TEAM} players from each playoff team",
        )
    return normalized


def save_team(user_id: int, player_ids: list[int], updated_by: int | None = None, ignore_lock: bool = False) -> dict:
    global SUPER_TEAM_CACHE_LOADED
    context = get_context()
    if context["locked"] and not ignore_lock:
        raise HTTPException(status_code=400, detail="Super Team is locked")
    normalized = validate_selection(player_ids)
    db = get_db()
    user_row = db.execute("SELECT name FROM users WHERE id = ? AND is_active = 1", (int(user_id),)).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    updated_at = _now_str()
    db.execute("DELETE FROM super_teams WHERE user_id = ?", (int(user_id),))
    for pid in normalized:
        db.execute(
            """
            INSERT INTO super_teams (user_id, player_id, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            """,
            (int(user_id), int(pid), updated_at, updated_by),
        )
    db.commit()
    entry = {
        "user_id": int(user_id),
        "name": user_row["name"],
        "player_ids": normalized,
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
        return {"players": [], "updated_at": None}
    players = _player_lookup()
    return {
        "players": [
            {
                "player_id": pid,
                "player_name": players.get(pid, {}).get("Name", ""),
                "team": players.get(pid, {}).get("Team", ""),
                "role": players.get(pid, {}).get("Role", ""),
            }
            for pid in entry["player_ids"]
        ],
        "updated_at": entry.get("updated_at"),
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
        for pid in entry["player_ids"]:
            player = players.get(int(pid), {})
            for match_id in SUPER_MATCH_IDS:
                pts = float(point_lookup.get((match_id, int(pid)), 0))
                match_points[match_id] += pts
                total += pts
                match_players[match_id].append({
                    "player_id": int(pid),
                    "name": player.get("Name", ""),
                    "team": player.get("Team", ""),
                    "role": player.get("Role", ""),
                    "points": round(pts, 2),
                })
        total = round(total, 2)
        if max_points is None or total > max_points:
            max_points = total
        row = {
            "user_id": entry["user_id"],
            "name": entry["name"],
            "points": total,
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
        for entry in submissions.values()
        for pid in entry["player_ids"]
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

    context = get_context()
    bonus_winners = [
        int(row["user_id"])
        for row in rows
        if context["bonus_visible"] and max_points is not None and row["points"] == max_points
    ]
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
            "bonus_winners": bonus_winners,
        })
    return {"standings": len(rows), "bonus_winners": len(bonus_winners)}


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
            return {int(uid): SUPER_TEAM_BONUS for uid in SUPER_STANDINGS_META.get("bonus_winners", [])}
    refresh_super_team_standings_cache()
    with SUPER_TEAM_CACHE_LOCK:
        return {int(uid): SUPER_TEAM_BONUS for uid in SUPER_STANDINGS_META.get("bonus_winners", [])}
