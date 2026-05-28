from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.middleware.auth import get_current_user
from backend.middleware.auth import require_admin
from backend.services import super_team_service

router = APIRouter(prefix="/api/super-team", tags=["super-team"])
admin_router = APIRouter(prefix="/api/admin/super-team", tags=["admin-super-team"])


class SuperTeamBody(BaseModel):
    players: list[int]
    captain: int
    vice_captain: int


class AdminSuperTeamBody(BaseModel):
    user_id: int
    players: list[int]
    captain: int
    vice_captain: int
    phase: str = "current"


@router.get("")
async def super_team_home(user: dict = Depends(get_current_user)):
    return super_team_service.home_payload(user["id"])


@router.get("/status")
async def super_team_status(user: dict = Depends(get_current_user)):
    return {
        "context": super_team_service.get_context(),
        "has_team": super_team_service.has_submission(user["id"]),
    }


@router.post("")
async def submit_super_team(body: SuperTeamBody, user: dict = Depends(get_current_user)):
    entry = super_team_service.save_team(user["id"], body.players, body.captain, body.vice_captain)
    return {"success": True, "team": entry}


@router.post("/penalty-preview")
async def preview_super_team_penalty(body: SuperTeamBody, user: dict = Depends(get_current_user)):
    return super_team_service.projected_penalty(user["id"], body.players, body.captain, body.vice_captain)


@router.get("/contestants")
async def super_team_contestants(user: dict = Depends(get_current_user)):
    return super_team_service.contestants()


@router.get("/participants")
async def super_team_participants(user: dict = Depends(get_current_user)):
    return {
        "participants": super_team_service.contestants(),
        "non_participants": super_team_service.missing_users(),
    }


@router.get("/standings")
async def super_team_standings(user: dict = Depends(get_current_user)):
    return super_team_service.standings()


@router.get("/details")
async def super_team_details(user: dict = Depends(get_current_user)):
    return super_team_service.details()


@admin_router.get("")
async def admin_super_team(user: dict = Depends(require_admin)):
    super_team_service.refresh_super_team_standings_cache()
    return {
        "context": super_team_service.get_context(),
        "players": super_team_service.grouped_player_pool(),
        "teams": list(super_team_service.get_submissions().values()),
        "snapshots": super_team_service.admin_snapshot_payload(),
        "standings": super_team_service.standings(),
    }


@admin_router.put("")
async def admin_update_super_team(body: AdminSuperTeamBody, user: dict = Depends(require_admin)):
    if body.phase == "current":
        entry = super_team_service.save_team(
            body.user_id,
            body.players,
            body.captain,
            body.vice_captain,
            updated_by=user["id"],
            ignore_lock=True,
        )
    else:
        entry = super_team_service.replace_snapshot(
            body.phase,
            body.user_id,
            body.players,
            body.captain,
            body.vice_captain,
        )
    try:
        from backend.routes.leaderboard import invalidate_leaderboard_cache, refresh_leaderboard_cache_once

        invalidate_leaderboard_cache()
        refresh_leaderboard_cache_once()
    except Exception:
        pass
    return {"success": True, "team": entry}


@admin_router.post("/recalculate")
async def admin_recalculate_super_team(user: dict = Depends(require_admin)):
    super_team_service.ensure_phase_snapshots()
    summary = super_team_service.refresh_super_team_standings_cache()
    try:
        from backend.routes.leaderboard import invalidate_leaderboard_cache, refresh_leaderboard_cache_once

        invalidate_leaderboard_cache()
        summary["leaderboard"] = refresh_leaderboard_cache_once()
    except Exception as exc:
        summary["leaderboard_error"] = str(exc)
    return summary
