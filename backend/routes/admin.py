from collections import defaultdict
import threading
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional

from backend.middleware.auth import require_admin
from backend.database import get_db, get_next_id
from backend.config import ROLES, IST, get_current_datetime
from backend.services import data_service
from backend.services.scraper import compute_toss_time
from backend.services.cache_locks import acquire_cache_locks

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Tournament reference - will be set from main.py
tournament_ref = None
ADMIN_REFRESH_LOCK = threading.Lock()


def _now_str():
    return get_current_datetime().strftime("%Y-%m-%d %H:%M:%S")


def set_tournament(t):
    global tournament_ref
    tournament_ref = t


def _refresh_tournament_static_state(refresh_schedule_map: bool = False):
    if tournament_ref is None:
        return
    tournament_ref.refresh_static_data(
        data_service.get_cached_data("players"),
        data_service.get_cached_data("matches"),
        refresh_schedule_map=refresh_schedule_map,
    )


def _refresh_admin_caches(
    *,
    tables: set[str],
    refresh_schedule_map: bool = False,
    match_id: int | None = None,
):
    tables = {table.lower() for table in tables}

    for table in tables:
        if table in {"players", "matches", "users", "user_teams", "team_backups", "contestant_points", "player_points"}:
            data_service.invalidate_cache(table)

    if tables & {"players", "matches", "user_teams", "team_backups", "contestant_points", "player_points", "users"}:
        data_service.invalidate_match_player_payloads()

    if "matches" in tables:
        _refresh_tournament_static_state(refresh_schedule_map=refresh_schedule_map)
    elif "players" in tables:
        _refresh_tournament_static_state(refresh_schedule_map=refresh_schedule_map)

    if "matches" in tables:
        try:
            from backend.routes.matches import refresh_matches_response_cache_once

            threading.Thread(
                target=refresh_matches_response_cache_once,
                daemon=True,
                name="admin-matches-cache-refresh",
            ).start()
        except Exception as exc:
            print(f"[ADMIN] matches cache refresh failed: {exc}")

    if tables & {"players", "matches", "users", "user_teams", "team_backups", "contestant_points", "player_points"}:
        try:
            from backend.routes.scores import refresh_scores_response_cache_once

            threading.Thread(
                target=refresh_scores_response_cache_once,
                daemon=True,
                name="admin-scores-cache-refresh",
            ).start()
        except Exception as exc:
            print(f"[ADMIN] scores cache refresh failed: {exc}")


def _queue_admin_refresh(
    *,
    tables: set[str],
    refresh_schedule_map: bool = False,
    match_id: int | None = None,
) -> None:
    def _run():
        with ADMIN_REFRESH_LOCK:
            try:
                _refresh_admin_caches(
                    tables=tables,
                    refresh_schedule_map=refresh_schedule_map,
                    match_id=match_id,
                )
            except Exception as exc:
                print(f"[ADMIN] background refresh failed: {exc}")

    threading.Thread(target=_run, daemon=True, name="admin-cache-refresh").start()


def _queue_tournament_match_refresh(
    match_id: int,
    explicit_status: str | None,
) -> None:
    if tournament_ref is None:
        return

    match_id_str = str(match_id)

    def _run():
        with ADMIN_REFRESH_LOCK:
            try:
                with acquire_cache_locks(
                    "scraper_playing_xi",
                    "scores_match_data",
                    "scores_response",
                    "leaderboard_response",
                ):
                    if explicit_status == "completed":
                        tournament_ref.ensure_match_teams_loaded([match_id_str], force=True)
                        tournament_ref.update_match_data(
                            match_id_str,
                            use_playing_xi=True,
                            force_refresh_playing_xi=True,
                        )
                        tournament_ref.compute_player_points_for_match(match_id_str)
                        tournament_ref.compute_points_for_match(match_id_str)
                        tournament_ref.persist_player_points_to_local()
                        tournament_ref.persist_to_local()
                        tournament_ref.warm_today_last_completed_team_xi_previews()
                    elif explicit_status in {"future", "live", "nr"}:
                        tournament_ref.player_points.pop(match_id_str, None)
                        for contestant in tournament_ref.contestants.values():
                            contestant.points.pop(match_id_str, None)

                    _refresh_admin_caches(tables={"matches"}, refresh_schedule_map=True, match_id=match_id)
            except Exception as exc:
                print(f"[ADMIN] background tournament refresh failed for match {match_id}: {exc}")

    threading.Thread(target=_run, daemon=True, name=f"admin-match-refresh-{match_id}").start()


# --- User Management ---

class UpdateUserBody(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/users")
async def list_users(user: dict = Depends(require_admin)):
    db = get_db()
    rows = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserBody,
    user: dict = Depends(require_admin),
):
    db = get_db()

    existing = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")

    updates = []
    params = []

    if body.role is not None:
        if body.role not in ("user", "admin"):
            raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'")
        updates.append("role = ?")
        params.append(body.role)

    if body.is_active is not None:
        updates.append("is_active = ?")
        params.append(int(body.is_active))

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(user_id)
    db.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
    db.commit()
    _refresh_admin_caches(tables={"users"})

    updated = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(updated)


# --- Player Management ---

class CreatePlayerBody(BaseModel):
    name: str
    team: str
    role: str
    type: Optional[str] = None
    aliases: Optional[str] = ""


class UpdatePlayerBody(BaseModel):
    name: Optional[str] = None
    team: Optional[str] = None
    role: Optional[str] = None
    type: Optional[str] = None
    aliases: Optional[str] = None


@router.get("/players")
async def list_players(user: dict = Depends(require_admin)):
    db = get_db()
    rows = db.execute("SELECT * FROM players ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@router.post("/players")
async def create_player(
    body: CreatePlayerBody,
    user: dict = Depends(require_admin),
):
    db = get_db()
    next_id = get_next_id("players")
    cursor = db.execute(
        "INSERT INTO players (id, name, team, role, type, aliases) VALUES (?, ?, ?, ?, ?, ?)",
        (next_id, body.name, body.team, body.role, body.type or None, body.aliases or ""),
    )
    db.commit()
    _refresh_admin_caches(tables={"players"}, refresh_schedule_map=True)

    player = db.execute("SELECT * FROM players WHERE id = ?", (next_id,)).fetchone()
    return dict(player)


@router.put("/players/{player_id}")
async def update_player(
    player_id: int,
    body: UpdatePlayerBody,
    user: dict = Depends(require_admin),
):
    db = get_db()

    existing = db.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Player not found")

    updates = []
    params = []

    if body.name is not None:
        updates.append("name = ?")
        params.append(body.name)
    if body.team is not None:
        updates.append("team = ?")
        params.append(body.team)
    if body.role is not None:
        updates.append("role = ?")
        params.append(body.role)
    if body.type is not None:
        updates.append("type = ?")
        params.append(body.type or None)
    if body.aliases is not None:
        updates.append("aliases = ?")
        params.append(body.aliases)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(player_id)
    db.execute(f"UPDATE players SET {', '.join(updates)} WHERE id = ?", params)
    db.commit()
    _refresh_admin_caches(tables={"players"}, refresh_schedule_map=True)

    updated = db.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    return dict(updated)


@router.delete("/players/{player_id}")
async def delete_player(
    player_id: int,
    user: dict = Depends(require_admin),
):
    db = get_db()

    existing = db.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Player not found")

    db.execute("DELETE FROM players WHERE id = ?", (player_id,))
    db.commit()
    _refresh_admin_caches(tables={"players"})

    return {"success": True}


# --- Match Management ---

class CreateMatchBody(BaseModel):
    team1: str
    team2: str
    match_date: str
    match_time: str
    status: Optional[str] = "future"
    toss_time: Optional[str] = None


class UpdateMatchBody(BaseModel):
    team1: Optional[str] = None
    team2: Optional[str] = None
    match_date: Optional[str] = None
    match_time: Optional[str] = None
    status: Optional[str] = None
    toss_time: Optional[str] = None


@router.get("/matches")
async def list_matches(user: dict = Depends(require_admin)):
    db = get_db()
    rows = db.execute("SELECT * FROM matches ORDER BY id").fetchall()
    return [dict(row) for row in rows]


@router.post("/matches")
async def create_match(
    body: CreateMatchBody,
    user: dict = Depends(require_admin),
):
    db = get_db()
    toss_time = body.toss_time if body.toss_time is not None else compute_toss_time(body.match_date, body.match_time)
    next_id = get_next_id("matches")
    cursor = db.execute(
        "INSERT INTO matches (id, team1, team2, match_date, match_time, status, toss_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            next_id,
            body.team1,
            body.team2,
            body.match_date,
            body.match_time,
            (body.status or "future").strip().lower(),
            toss_time,
        ),
    )
    db.commit()
    _refresh_admin_caches(tables={"matches"}, refresh_schedule_map=True)

    match = db.execute("SELECT * FROM matches WHERE id = ?", (next_id,)).fetchone()
    return dict(match)


@router.put("/matches/{match_id}")
async def update_match(
    match_id: int,
    body: UpdateMatchBody,
    user: dict = Depends(require_admin),
):
    db = get_db()

    existing = db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Match not found")

    updates = []
    params = []
    schedule_changed = False
    teams_changed = False

    if body.team1 is not None:
        updates.append("team1 = ?")
        params.append(body.team1)
        teams_changed = True
    if body.team2 is not None:
        updates.append("team2 = ?")
        params.append(body.team2)
        teams_changed = True
    if body.match_date is not None:
        updates.append("match_date = ?")
        params.append(body.match_date)
        schedule_changed = True
    if body.match_time is not None:
        updates.append("match_time = ?")
        params.append(body.match_time)
        schedule_changed = True
    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status.strip().lower())
    elif schedule_changed or teams_changed:
        updates.append("status = ?")
        params.append("future")

    if body.toss_time is not None:
        updates.append("toss_time = ?")
        params.append(body.toss_time)
    elif schedule_changed or teams_changed:
        updates.append("toss_time = ?")
        params.append(compute_toss_time(body.match_date or existing["match_date"], body.match_time or existing["match_time"]))

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(match_id)
    db.execute(f"UPDATE matches SET {', '.join(updates)} WHERE id = ?", params)
    explicit_status = (body.status or "").strip().lower() if body.status is not None else None
    if schedule_changed or teams_changed or explicit_status in {"future", "live", "nr"}:
        data_service.clear_points_for_match(match_id)
    db.commit()
    _queue_tournament_match_refresh(match_id, explicit_status)

    updated = db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    return dict(updated)


@router.delete("/matches/{match_id}")
async def delete_match(
    match_id: int,
    user: dict = Depends(require_admin),
):
    db = get_db()

    existing = db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Match not found")

    db.execute("DELETE FROM matches WHERE id = ?", (match_id,))
    db.commit()
    _refresh_admin_caches(tables={"matches"}, refresh_schedule_map=True, match_id=match_id)

    return {"success": True}


# --- Score Recalculation ---

@router.post("/recalculate/{match_id}")
async def recalculate_match(
    match_id: int,
    user: dict = Depends(require_admin),
):
    if tournament_ref is None:
        raise HTTPException(status_code=500, detail="Tournament not initialized")

    db = get_db()
    match_row = db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match_row:
        raise HTTPException(status_code=404, detail="Match not found")

    current_status = tournament_ref.get_match_status(match_row)
    if current_status == "future":
        raise HTTPException(status_code=400, detail="Future matches cannot be recalculated")

    match_id_str = str(match_id)

    refreshed_status = current_status

    def _run_recalculate():
        nonlocal refreshed_status
        with ADMIN_REFRESH_LOCK:
            try:
                _refresh_tournament_static_state()
                tournament_ref.ensure_match_teams_loaded([match_id_str], force=True)

                # Fetch scorecard first so final match status can be refreshed from Cricbuzz.
                tournament_ref.update_match_data(match_id_str, use_playing_xi=True, force_refresh_playing_xi=True)
                updated_match_row = tournament_ref.match_rows.get(match_id_str, {})
                refreshed_status = tournament_ref.get_match_status(updated_match_row)

                if refreshed_status == "completed":
                    tournament_ref.compute_player_points_for_match(match_id_str)
                    tournament_ref.compute_points_for_match(match_id_str)
                    tournament_ref.persist_player_points_to_local()
                    tournament_ref.persist_to_local()
                    data_service.invalidate_match_player_payloads()
                    tournament_ref.warm_today_last_completed_team_xi_previews()

                _refresh_admin_caches(tables={"matches"}, refresh_schedule_map=True, match_id=match_id)
            except Exception as exc:
                print(f"[ADMIN] background recalculate failed for match {match_id}: {exc}")

    threading.Thread(target=_run_recalculate, daemon=True, name=f"admin-recalculate-{match_id}").start()

    return {
        "success": True,
        "message": f"Recalculated scores for match {match_id}",
        "status": refreshed_status,
    }


# --- View Submitted Teams ---

class AdminPlayerSelection(BaseModel):
    player_id: int
    is_captain: bool = False
    is_vice_captain: bool = False


class AdminUpdateTeamBody(BaseModel):
    user_id: int
    match_id: int
    players: List[AdminPlayerSelection]


def _validate_team_selection(db, match_id: int, selections: List[AdminPlayerSelection]):
    if len(selections) != 11:
        raise HTTPException(status_code=400, detail="Exactly 11 players required")

    captains = [p for p in selections if p.is_captain]
    vice_captains = [p for p in selections if p.is_vice_captain]

    if len(captains) != 1:
        raise HTTPException(status_code=400, detail="Exactly 1 captain required")
    if len(vice_captains) != 1:
        raise HTTPException(status_code=400, detail="Exactly 1 vice captain required")
    if captains[0].player_id == vice_captains[0].player_id:
        raise HTTPException(status_code=400, detail="Captain and Vice Captain cannot be the same player")

    player_ids = [p.player_id for p in selections]
    placeholders = ",".join("?" * len(player_ids))
    players = db.execute(
        f"""
        SELECT *
        FROM players
        WHERE id IN ({placeholders})
          AND team IN (
            SELECT team1 FROM matches WHERE id = ?
            UNION
            SELECT team2 FROM matches WHERE id = ?
          )
        """,
        [*player_ids, match_id, match_id],
    ).fetchall()

    if len(players) != 11:
        raise HTTPException(status_code=400, detail="Some selected players are invalid for this match")

    role_counts = {role: 0 for role in ROLES}
    for player in players:
        if player["role"] in role_counts:
            role_counts[player["role"]] += 1

    for role in ROLES:
        if role_counts[role] < 1:
            raise HTTPException(status_code=400, detail=f"At least 1 {role} required")


def _fetch_match_team_snapshots(db, match_id: int):
    rows = db.execute(
        """
        SELECT
            ut.user_id,
            u.name AS user_name,
            u.email AS user_email,
            u.mobile AS user_mobile,
            ut.player_id,
            p.name AS player_name,
            p.team,
            p.role,
            ut.is_captain,
            ut.is_vice_captain
        FROM user_teams ut
        JOIN users u ON u.id = ut.user_id
        JOIN players p ON p.id = ut.player_id
        WHERE ut.match_id = ?
        ORDER BY u.name, p.team, p.role, p.name
        """,
        (match_id,),
    ).fetchall()

    teams_by_user = {}
    for row in rows:
        uid = row["user_id"]
        if uid not in teams_by_user:
            teams_by_user[uid] = {
                "user_id": uid,
                "user_name": row["user_name"],
                "user_email": row["user_email"],
                "user_mobile": row["user_mobile"],
                "players": [],
                "team_counts": defaultdict(int),
            }
        teams_by_user[uid]["players"].append({
            "player_id": row["player_id"],
            "player_name": row["player_name"],
            "team": row["team"],
            "role": row["role"],
            "is_captain": bool(row["is_captain"]),
            "is_vice_captain": bool(row["is_vice_captain"]),
        })
        teams_by_user[uid]["team_counts"][row["team"]] += 1

    result = []
    for team in teams_by_user.values():
        team["team_counts"] = dict(team["team_counts"])
        team["captain_name"] = next((p["player_name"] for p in team["players"] if p["is_captain"]), None)
        team["vice_captain_name"] = next((p["player_name"] for p in team["players"] if p["is_vice_captain"]), None)
        result.append(team)

    return result


@router.get("/teams/matches")
async def team_matches(user: dict = Depends(require_admin)):
    db = get_db()
    rows = db.execute(
        """
        SELECT
            m.id,
            m.team1,
            m.team2,
            m.match_date,
            m.match_time,
            COUNT(DISTINCT ut.user_id) AS team_count
        FROM matches m
        LEFT JOIN user_teams ut ON ut.match_id = m.id
        GROUP BY m.id, m.team1, m.team2, m.match_date, m.match_time
        ORDER BY m.id
        """
    ).fetchall()
    return [dict(row) for row in rows]

@router.get("/teams")
async def view_teams(
    match_id: int = Query(...),
    user: dict = Depends(require_admin),
):
    db = get_db()
    match = db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    return {
        "match": dict(match),
        "teams": _fetch_match_team_snapshots(db, match_id),
    }


@router.get("/missed-players")
async def missed_players(
    match_id: int | None = Query(default=None),
    user: dict = Depends(require_admin),
):
    db = get_db()

    if match_id is None:
        row = db.execute(
            """
            SELECT match_id
            FROM unknown_players
            GROUP BY match_id
            ORDER BY match_id DESC
            LIMIT 1
            """
        ).fetchone()
        if row:
            match_id = int(row["match_id"])
        else:
            row = db.execute("SELECT id FROM matches ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return {"match": None, "players": [], "missed_count": 0, "total_missed_points": 0}
            match_id = int(row["id"])

    match = db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    rows = db.execute(
        """
        SELECT
            name,
            team,
            match_id,
            match_date,
            team1,
            team2
        FROM unknown_players
        WHERE match_id = ?
        ORDER BY team ASC, name ASC
        """,
        (match_id,),
    ).fetchall()

    return {
        "match": dict(match),
        "players": [
            {
                "match_id": int(row["match_id"]),
                "name": row["name"],
                "team": row["team"],
                "match_date": row["match_date"],
                "team1": row["team1"],
                "team2": row["team2"],
            }
            for row in rows
        ],
        "missed_count": len(rows),
        "total_missed_points": 0,
    }


@router.put("/teams")
async def update_team(
    body: AdminUpdateTeamBody,
    user: dict = Depends(require_admin),
):
    db = get_db()

    existing_user = db.execute("SELECT id FROM users WHERE id = ?", (body.user_id,)).fetchone()
    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing_match = db.execute("SELECT id FROM matches WHERE id = ?", (body.match_id,)).fetchone()
    if not existing_match:
        raise HTTPException(status_code=404, detail="Match not found")

    _validate_team_selection(db, body.match_id, body.players)

    updated_at = _now_str()
    existing_rows = db.execute(
        """
        SELECT id, player_id
        FROM user_teams
        WHERE user_id = ? AND match_id = ?
        """,
        (body.user_id, body.match_id),
    ).fetchall()
    existing_by_player = {int(row["player_id"]): dict(row) for row in existing_rows}
    incoming_player_ids = set()

    for player in body.players:
        incoming_player_ids.add(int(player.player_id))
        existing_row = existing_by_player.get(int(player.player_id))
        if existing_row:
            db.execute(
                """
                UPDATE user_teams
                SET is_captain = ?, is_vice_captain = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(player.is_captain), int(player.is_vice_captain), updated_at, int(existing_row["id"])),
            )
        else:
            db.execute(
                """
                INSERT INTO user_teams (user_id, match_id, player_id, is_captain, is_vice_captain, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (body.user_id, body.match_id, player.player_id, int(player.is_captain), int(player.is_vice_captain), updated_at),
            )

    for player_id, existing_row in existing_by_player.items():
        if player_id not in incoming_player_ids:
            db.execute("DELETE FROM user_teams WHERE id = ?", (int(existing_row["id"]),))

    db.commit()
    data_service.prune_user_backups(body.user_id, body.match_id, [player.player_id for player in body.players])
    _refresh_admin_caches(tables={"user_teams"})

    return {
        "success": True,
        "teams": _fetch_match_team_snapshots(db, body.match_id),
    }


# --- Clear Table Data ---

CLEARABLE_TABLES = {
    "players": "DELETE FROM players",
    "matches": "DELETE FROM matches",
    "user_teams": "DELETE FROM user_teams",
    "team_backups": "DELETE FROM team_backups",
    "contestant_points": "DELETE FROM contestant_points",
    "player_points": "DELETE FROM player_points",
    "unknown_players": "DELETE FROM unknown_players",
}


@router.delete("/clear/{table_name}")
async def clear_table(
    table_name: str,
    user: dict = Depends(require_admin),
):
    if table_name not in CLEARABLE_TABLES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot clear '{table_name}'. Allowed: {', '.join(CLEARABLE_TABLES.keys())}",
        )

    db = get_db()

    # If clearing matches, also clear dependent data
    if table_name == "matches":
        db.execute("DELETE FROM user_teams")
        db.execute("DELETE FROM team_backups")
        db.execute("DELETE FROM contestant_points")
        db.execute("DELETE FROM player_points")
        db.execute("DELETE FROM unknown_players")

    # If clearing players, also clear dependent data
    if table_name == "players":
        db.execute("DELETE FROM user_teams")
        db.execute("DELETE FROM team_backups")
        db.execute("DELETE FROM contestant_points")
        db.execute("DELETE FROM player_points")
        db.execute("DELETE FROM unknown_players")

    db.execute(CLEARABLE_TABLES[table_name])
    db.commit()
    _refresh_admin_caches(
        tables={table_name},
        refresh_schedule_map=(table_name == "matches"),
    )

    return {"success": True, "message": f"Cleared all data from {table_name}"}


# --- Admin Submit Team on Behalf of User ---

class AdminTeamPlayer(BaseModel):
    player_id: int
    is_captain: bool = False
    is_vice_captain: bool = False


class AdminSubmitTeamBody(BaseModel):
    user_id: int
    match_id: int
    players: List[AdminTeamPlayer]


@router.post("/teams/submit")
async def admin_submit_team(body: AdminSubmitTeamBody, user: dict = Depends(require_admin)):
    db = get_db()
    # Delete old team
    db.execute("DELETE FROM user_teams WHERE user_id = ? AND match_id = ?", (body.user_id, body.match_id))
    # Insert new
    updated_at = _now_str()
    for p in body.players:
        db.execute(
            "INSERT INTO user_teams (user_id, match_id, player_id, is_captain, is_vice_captain, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (body.user_id, body.match_id, p.player_id, int(p.is_captain), int(p.is_vice_captain), updated_at),
        )
    db.commit()
    data_service.prune_user_backups(body.user_id, body.match_id, [player.player_id for player in body.players])
    _refresh_admin_caches(tables={"user_teams"})
    return {"success": True}
