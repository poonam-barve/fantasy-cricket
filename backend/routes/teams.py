from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List
from datetime import datetime, timedelta
import time

from backend.middleware.auth import get_current_user
from backend.database import get_db
from backend.config import IST, ROLES, get_current_datetime
from backend.services import data_service
router = APIRouter(prefix="/api/teams", tags=["teams"])


class PlayerSelection(BaseModel):
    player_id: int
    is_captain: bool = False
    is_vice_captain: bool = False


class SubmitTeamBody(BaseModel):
    match_id: int
    players: List[PlayerSelection]
    backups: List[int] = []
    predicted_points: float | None = None


def get_now():
    return get_current_datetime()


def get_now_str():
    return get_now().strftime("%Y-%m-%d %H:%M:%S")


def _validate_predicted_points(predicted_points: float) -> float:
    try:
        normalized = float(predicted_points)
    except Exception:
        raise HTTPException(status_code=400, detail="Prediction must be a number")

    if normalized < 0:
        raise HTTPException(status_code=400, detail="Prediction must be 0 or higher")

    doubled = normalized * 2
    if abs(doubled - round(doubled)) > 1e-9:
        raise HTTPException(status_code=400, detail="Prediction must be a whole number or end in .5")

    return round(normalized, 1)


def is_match_locked(match_date: str, match_time: str) -> bool:
    try:
        match_datetime = datetime.strptime(
            f"{match_date} {match_time}", "%Y-%m-%d %H:%M"
        )
        match_datetime = IST.localize(match_datetime)
    except Exception:
        return True
    return get_now() >= match_datetime


def _is_lineup_window_open(match_date: str, match_time: str, toss_time: str | None = None) -> bool:
    try:
        match_datetime = datetime.strptime(f"{match_date} {match_time}", "%Y-%m-%d %H:%M")
        match_datetime = IST.localize(match_datetime)
    except Exception:
        return False

    if toss_time:
        try:
            window_start = IST.localize(datetime.strptime(f"{match_date} {toss_time}", "%Y-%m-%d %H:%M"))
        except Exception:
            window_start = match_datetime - timedelta(minutes=30)
    else:
        window_start = match_datetime - timedelta(minutes=30)

    now = get_current_datetime()
    return window_start <= now < match_datetime


@router.get("/my")
async def my_team(
    match_id: int = Query(...),
    user: dict = Depends(get_current_user),
):
    db = get_db()
    rows = db.execute(
        """
        SELECT ut.player_id, p.name AS player_name, p.team, p.role,
               ut.is_captain, ut.is_vice_captain
        FROM user_teams ut
        JOIN players p ON p.id = ut.player_id
        WHERE ut.user_id = ? AND ut.match_id = ?
        """,
        (user["id"], match_id),
    ).fetchall()

    team = [dict(row) for row in rows]
    predicted = data_service.get_score_prediction(user["id"], match_id)
    return {"team": team, "predicted_points": predicted}


@router.get("/my-backups")
async def my_backups(
    match_id: int = Query(...),
    user: dict = Depends(get_current_user),
):
    return data_service.get_user_backups(user["id"], match_id)


@router.get("/my-matches")
async def my_team_matches(user: dict = Depends(get_current_user)):
    """Returns list of match IDs where user has picked a team."""
    started = time.perf_counter()
    summaries = data_service.get_cached_user_team_summaries(user["id"])
    result = sorted(
        match_id
        for match_id, summary in summaries.items()
        if summary.get("selected_ids")
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms >= 80:
        print(f"[API timing] GET /api/teams/my-matches total={elapsed_ms:.1f}ms user_id={user['id']}")
    return result


@router.get("/my-lineup-statuses")
async def my_lineup_statuses(
    match_ids: str = Query(...),
    user: dict = Depends(get_current_user),
):
    started = time.perf_counter()
    requested_ids = [int(match_id.strip()) for match_id in match_ids.split(",") if match_id.strip()]
    if not requested_ids:
        return {}

    match_lookup = {
        int(row["MatchID"]): row
        for row in data_service.get_cached_data("matches")
        if int(row.get("MatchID", 0) or 0) in requested_ids
    }
    team_summaries = data_service.get_cached_user_team_summaries(user["id"], requested_ids)

    result = {}
    for match_id in requested_ids:
        match = match_lookup.get(match_id)
        lineup_window_open = False
        if match:
            lineup_window_open = _is_lineup_window_open(
                match["Date"],
                match["Time"],
                match.get("TossTime"),
            )
        team_summary = team_summaries.get(match_id) or {"selected_ids": [], "backup_count": 0}
        selected_ids = set(team_summary.get("selected_ids") or [])
        if not match or not selected_ids:
            result[str(match_id)] = {
                "announced": False,
                "complete": False,
                "unannouncedSelected": 0,
                "substituteSelected": 0,
                "backupCount": int(team_summary.get("backup_count") or 0),
                "lineupWindowOpen": lineup_window_open,
            }
            continue

        cached_playing_xi = data_service.get_cached_match_playing_xi(
            match_id,
            match["Team1"],
            match["Team2"],
            match["Date"],
            match["Time"],
        )
        if cached_playing_xi and cached_playing_xi.get("announced"):
            playing_xi = cached_playing_xi
        else:
            playing_xi = {"announced": False, "url": "", "player_ids": [], "substitute_ids": []}

        playing_ids = set(playing_xi.get("player_ids", []))
        substitute_ids = set(playing_xi.get("substitute_ids", []))
        announced = bool(playing_xi.get("announced"))
        playing_ids_complete = len(playing_ids) == 22 and len(substitute_ids) == 10

        unavailable_selected = 0
        substitute_selected = 0
        if announced and playing_ids:
            unavailable_selected = len([player_id for player_id in selected_ids if player_id not in playing_ids and player_id not in substitute_ids])
            substitute_selected = len([player_id for player_id in selected_ids if player_id in substitute_ids])

        result[str(match_id)] = {
            "announced": announced,
            "complete": playing_ids_complete,
            "unannouncedSelected": unavailable_selected,
            "substituteSelected": substitute_selected,
            "backupCount": int(team_summary.get("backup_count") or 0),
            "lineupWindowOpen": lineup_window_open,
        }

    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms >= 80:
        print(
            f"[API timing] GET /api/teams/my-lineup-statuses total={elapsed_ms:.1f}ms "
            f"user_id={user['id']} matches={len(requested_ids)}"
        )
    return result


@router.get("/my-backup-counts")
async def my_backup_counts(
    match_ids: str = Query(...),
    user: dict = Depends(get_current_user),
):
    started = time.perf_counter()
    requested_ids = [int(match_id.strip()) for match_id in match_ids.split(",") if match_id.strip()]
    if not requested_ids:
        return {}
    counts = data_service.get_backup_counts_for_user(user["id"], requested_ids)
    result = {str(match_id): counts.get(match_id, 0) for match_id in requested_ids}
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms >= 80:
        print(
            f"[API timing] GET /api/teams/my-backup-counts total={elapsed_ms:.1f}ms "
            f"user_id={user['id']} matches={len(requested_ids)}"
        )
    return result


@router.post("")
async def submit_team(
    body: SubmitTeamBody,
    user: dict = Depends(get_current_user),
):
    db = get_db()

    # Get match
    match = db.execute(
        "SELECT * FROM matches WHERE id = ?", (body.match_id,)
    ).fetchone()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Check lock
    if is_match_locked(match["match_date"], match["match_time"]):
        raise HTTPException(status_code=400, detail="Match is locked, team submission closed")

    # Validate 11 players
    if len(body.players) != 11:
        raise HTTPException(status_code=400, detail="Exactly 11 players required")

    normalized_backups: list[int] = []
    seen_backups = set()
    selected_player_ids = {int(player.player_id) for player in body.players}
    for backup_player_id in body.backups[:3]:
        normalized_id = int(backup_player_id)
        if normalized_id in selected_player_ids or normalized_id in seen_backups:
            continue
        seen_backups.add(normalized_id)
        normalized_backups.append(normalized_id)

    # Validate captain and vice captain
    captains = [p for p in body.players if p.is_captain]
    vice_captains = [p for p in body.players if p.is_vice_captain]

    if len(captains) != 1:
        raise HTTPException(status_code=400, detail="Exactly 1 captain required")
    if len(vice_captains) != 1:
        raise HTTPException(status_code=400, detail="Exactly 1 vice captain required")
    if captains[0].player_id == vice_captains[0].player_id:
        raise HTTPException(status_code=400, detail="Captain and Vice Captain cannot be the same player")

    # Validate at least 1 player per role
    player_ids = [p.player_id for p in body.players]
    players_db = db.execute(
        f"SELECT * FROM players WHERE id IN ({','.join('?' * len(player_ids))})",
        player_ids,
    ).fetchall()

    if len(players_db) != 11:
        raise HTTPException(status_code=400, detail="Some player IDs are invalid")

    if normalized_backups:
        backup_players = db.execute(
            f"SELECT id FROM players WHERE id IN ({','.join('?' * len(normalized_backups))})",
            normalized_backups,
        ).fetchall()
        if len(backup_players) != len(normalized_backups):
            raise HTTPException(status_code=400, detail="Some backup player IDs are invalid")

    role_counts = {role: 0 for role in ROLES}
    for p in players_db:
        if p["role"] in role_counts:
            role_counts[p["role"]] += 1

    for role in ROLES:
        if role_counts[role] < 1:
            raise HTTPException(status_code=400, detail=f"At least 1 {role} required")

    # Delete old team for this user + match
    db.execute(
        "DELETE FROM user_teams WHERE user_id = ? AND match_id = ?",
        (user["id"], body.match_id),
    )

    # Insert new team
    updated_at = get_now_str()
    for p in body.players:
        db.execute(
            "INSERT INTO user_teams (user_id, match_id, player_id, is_captain, is_vice_captain, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], body.match_id, p.player_id, int(p.is_captain), int(p.is_vice_captain), updated_at),
        )

    db.commit()
    data_service.save_user_backups(user["id"], body.match_id, normalized_backups)
    data_service.prune_user_backups(user["id"], body.match_id, player_ids)
    data_service.refresh_match_contestant_cache(body.match_id)
    data_service.refresh_user_team_summary_cache(user["id"], body.match_id)

    if body.predicted_points is not None:
        predicted_points = _validate_predicted_points(body.predicted_points)
        data_service.save_score_prediction(user["id"], body.match_id, predicted_points)

    return {"success": True}


class UpdatePredictionBody(BaseModel):
    match_id: int
    predicted_points: float


@router.patch("/prediction")
async def update_prediction(
    body: UpdatePredictionBody,
    user: dict = Depends(get_current_user),
):
    db = get_db()

    match = db.execute(
        "SELECT * FROM matches WHERE id = ?", (body.match_id,)
    ).fetchone()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if is_match_locked(match["match_date"], match["match_time"]):
        raise HTTPException(status_code=400, detail="Match is locked, prediction cannot be changed")

    predicted_points = _validate_predicted_points(body.predicted_points)
    data_service.save_score_prediction(user["id"], body.match_id, predicted_points)
    return {"success": True, "predicted_points": predicted_points}


@router.get("/contestants")
async def match_contestants_with_updates(
    match_id: int = Query(...),
    user: dict = Depends(get_current_user),
):
    contestants = data_service.get_cached_match_contestants(match_id)
    return contestants or []
