import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from backend.config import IST, get_current_datetime, get_current_date_key
from backend.database import get_db
from backend.middleware.auth import get_current_user
from backend.services import data_service
from backend.services.double_buffer_cache import DoubleBufferCache
from backend.services.match_status import resolve_match_status, resolve_match_status_from_row
from backend.services.scraper import get_cached_toss_info
from backend.services.venue_stats import (
    get_today_cached_venue_stats,
    prime_today_venue_cache,
)

router = APIRouter(prefix="/api", tags=["matches"])
MATCHES_RESPONSE_CACHE = {
    "matches": DoubleBufferCache(lock_name="matches_response"),
    "dashboard": DoubleBufferCache(lock_name="matches_response"),
}


def compute_match_status(match_date: str, match_time: str):
    return compute_runtime_match_status(match_date, match_time, "future")


def compute_runtime_match_status(match_date: str, match_time: str, stored_status: str | None):
    return resolve_match_status(match_date, match_time, stored_status)


@router.get("/matches")
async def list_matches(user: dict = Depends(get_current_user)):
    return _get_matches_payload(cache_key="matches")


@router.get("/dashboard/matches")
async def dashboard_matches(user: dict = Depends(get_current_user)):
    route_started = time.perf_counter()
    payload = _get_matches_payload(cache_key="dashboard")
    if not user:
        return payload
    result = _attach_user_match_ranks(payload, user["id"])
    route_ms = (time.perf_counter() - route_started) * 1000
    if route_ms >= 80:
        print(f"[API timing] GET /api/dashboard/matches total={route_ms:.1f}ms user_id={user['id']}")
    return result


def invalidate_matches_response_cache():
    MATCHES_RESPONSE_CACHE["matches"].invalidate()
    MATCHES_RESPONSE_CACHE["dashboard"].invalidate()


def refresh_matches_response_cache_once() -> dict:
    payload = _build_matches_payload()
    MATCHES_RESPONSE_CACHE["matches"].publish(payload)
    MATCHES_RESPONSE_CACHE["dashboard"].publish(payload)
    return {
        "matches": len(payload),
        "dashboard": len(payload),
    }


def _build_matches_payload() -> list[dict]:
    route_started = time.perf_counter()
    rows = data_service.get_matches_api_rows()
    today_key = get_current_date_key()
    prepared_matches = []
    for row in rows:
        match = dict(row)
        status, locked = compute_runtime_match_status(
            match["match_date"],
            match["match_time"],
            match.get("status"),
        )
        match["status"] = status
        match["locked"] = locked
        prepared_matches.append(match)

    prime_today_venue_cache(prepared_matches)

    result = []
    for match in prepared_matches:
        match["venue"] = get_today_cached_venue_stats(match["id"], match["match_date"], match["status"])
        cached_toss = get_cached_toss_info(int(match["id"]))
        match["toss"] = cached_toss if cached_toss and cached_toss.get("announced") else None
        result.append(match)

    today_matches = [m for m in result if (m["match_date"] == today_key or m["status"] == "live") and m["status"] not in {"completed", "nr"}]
    future_matches = [m for m in result if m["status"] == "future" and m["match_date"] != today_key]
    completed_matches = [m for m in result if m["status"] in {"completed", "nr"}]

    today_matches.sort(key=lambda m: (m["match_date"], m["match_time"]))
    future_matches.sort(key=lambda m: (m["match_date"], m["match_time"]))
    completed_matches.sort(key=lambda m: (m["match_date"], m["match_time"]), reverse=True)

    payload = today_matches + future_matches + completed_matches
    route_ms = (time.perf_counter() - route_started) * 1000
    if route_ms >= 80:
        print(f"[MATCHES timing] build={route_ms:.1f}ms rows={len(payload)}")
    return payload


def _get_matches_payload(cache_key: str) -> list[dict]:
    cached = MATCHES_RESPONSE_CACHE[cache_key].read()
    if cached is not None:
        return cached

    payload = _build_matches_payload()
    MATCHES_RESPONSE_CACHE["matches"].publish(payload)
    MATCHES_RESPONSE_CACHE["dashboard"].publish(payload)
    return payload


def _is_match_completed(db, match_id: int) -> bool:
    row = db.execute(
        "SELECT match_date, match_time, status, toss_time FROM matches WHERE id = ?",
        (match_id,),
    ).fetchone()
    if not row:
        return False
    status, _locked = resolve_match_status_from_row(row)
    return status == "completed"


def _attach_user_match_ranks(payload: list[dict], user_id: int) -> list[dict]:
    db = get_db()
    relevant_match_ids = [
        int(match["id"])
        for match in payload
        if match.get("status") in {"live", "completed"}
    ]
    if not relevant_match_ids:
        return payload

    placeholders = ",".join("?" * len(relevant_match_ids))
    score_rows = db.execute(
        """
        SELECT
            ut.match_id,
            ut.user_id,
            u.name,
            SUM(
                COALESCE(pp.points, 0) *
                CASE
                    WHEN ut.is_captain = 1 THEN 2.0
                    WHEN ut.is_vice_captain = 1 THEN 1.5
                    ELSE 1.0
                END
            ) AS points
        FROM user_teams ut
        JOIN users u ON u.id = ut.user_id
        LEFT JOIN player_points pp
            ON pp.match_id = ut.match_id AND pp.player_id = ut.player_id
        WHERE u.is_active = 1
          AND ut.match_id IN (""" + placeholders + """)
        GROUP BY ut.match_id, ut.user_id, u.name
        """,
        relevant_match_ids,
    ).fetchall()

    match_rank_map: dict[int, dict[int, int]] = {}
    match_points: dict[int, list[dict]] = {}
    for row in score_rows:
        match_points.setdefault(int(row["match_id"]), []).append({
            "user_id": int(row["user_id"]),
            "name": row["name"],
            "points": round(float(row["points"] or 0), 2),
        })

    for match_id, contestants in match_points.items():
        try:
            if _is_match_completed(db, match_id):
                bonuses = data_service.compute_prediction_bonuses(match_id)
                for contestant in contestants:
                    bonus_info = bonuses.get(contestant["user_id"])
                    if bonus_info:
                        contestant["points"] = round(contestant["points"] + bonus_info["bonus"], 2)
        except Exception:
            pass

        sorted_contestants = sorted(
            contestants,
            key=lambda item: (-item["points"], item["name"]),
        )
        rank_lookup: dict[int, int] = {}
        current_rank = 0
        previous_points = None
        for index, contestant in enumerate(sorted_contestants, start=1):
            if previous_points is None or contestant["points"] != previous_points:
                current_rank = index
                previous_points = contestant["points"]
            rank_lookup[contestant["user_id"]] = current_rank
        match_rank_map[match_id] = rank_lookup

    result = []
    for match in payload:
        match_copy = dict(match)
        if match_copy.get("status") in {"live", "completed"}:
            match_copy["current_rank"] = match_rank_map.get(int(match_copy["id"]), {}).get(int(user_id))
        else:
            match_copy["current_rank"] = None
        result.append(match_copy)
    return result
