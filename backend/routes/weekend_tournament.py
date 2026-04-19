from fastapi import APIRouter, Depends, HTTPException

from backend.middleware.auth import get_current_user, require_admin
from backend.services import weekend_tournament_service as wt_service

router = APIRouter(prefix="/api", tags=["weekend-tournament"])


@router.get("/weekend-tournament/current")
async def get_current(user: dict = Depends(get_current_user)):
    result = wt_service.get_current_tournament()
    if not result:
        # Try upcoming
        upcoming = wt_service.get_upcoming_tournament()
        if upcoming:
            return upcoming
        return {"id": None, "status": "none", "message": "No weekend competition available"}
    return result


@router.get("/weekend-tournament/history")
async def get_history(user: dict = Depends(get_current_user)):
    return wt_service.get_tournament_history()


@router.get("/weekend-tournament/{tournament_id}")
async def get_by_id(tournament_id: int, user: dict = Depends(get_current_user)):
    result = wt_service.get_tournament_by_id(tournament_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return result


@router.get("/weekend-tournament/match-tags")
async def get_match_tags(user: dict = Depends(get_current_user)):
    return wt_service.get_tournament_match_tags()


# ── Admin endpoints ──

@router.post("/admin/weekend-tournament/detect")
async def admin_detect(user: dict = Depends(require_admin)):
    created = wt_service.detect_and_create_tournaments()
    return {"created_tournament_ids": created}


@router.post("/admin/weekend-tournament/{tournament_id}/seed")
async def admin_seed(tournament_id: int, user: dict = Depends(require_admin)):
    result = wt_service.seed_bracket(tournament_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/admin/weekend-tournament/{tournament_id}/advance")
async def admin_advance(tournament_id: int, match_id: int, user: dict = Depends(require_admin)):
    result = wt_service.advance_round(tournament_id, match_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
