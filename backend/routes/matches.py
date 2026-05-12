import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from backend.config import IST, get_current_datetime, get_current_date_key
from backend.middleware.auth import get_current_user
from backend.services import data_service
from backend.services.double_buffer_cache import DoubleBufferCache
from backend.services.match_status import resolve_match_status
from backend.services.scraper import get_cached_toss_info
from backend.services.venue_stats import (
    get_venue_stats,
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
        venue_stats = get_today_cached_venue_stats(match["id"], match["match_date"], match["status"])
        if venue_stats is None and match["match_date"] == today_key and match["status"] in {"future", "lineups"}:
            venue_stats = get_venue_stats(
                match.get("team1", ""),
                match.get("team2", ""),
                match.get("venue"),
            )
        match["venue"] = venue_stats
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


def _rank_match_contestants(contestants: list[dict]) -> dict[int, int]:
    rank_lookup: dict[int, int] = {}
    needs_ranking: list[dict] = []

    for contestant in contestants:
        contestant_user_id = contestant.get("user_id", contestant.get("id"))
        if contestant_user_id in (None, ""):
            continue
        rank = contestant.get("rank")
        if rank not in (None, ""):
            rank_lookup[int(contestant_user_id)] = int(rank)
        else:
            needs_ranking.append(
                {
                    "user_id": int(contestant_user_id),
                    "name": contestant.get("name", ""),
                    "points": round(float(contestant.get("points", 0) or 0), 2),
                }
            )

    if not needs_ranking:
        return rank_lookup

    sorted_contestants = sorted(needs_ranking, key=lambda item: (-item["points"], item["name"]))
    current_rank = 0
    previous_points = None
    for index, contestant in enumerate(sorted_contestants, start=1):
        if previous_points is None or contestant["points"] != previous_points:
            current_rank = index
            previous_points = contestant["points"]
        rank_lookup[contestant["user_id"]] = current_rank

    return rank_lookup


def _attach_user_match_ranks(payload: list[dict], user_id: int) -> list[dict]:
    match_rank_map: dict[int, dict[int, int]] = {}
    try:
        from backend.routes.scores import get_cached_scores_snapshot

        scores_snapshot = get_cached_scores_snapshot()
    except Exception:
        scores_snapshot = {}

    for match in payload:
        match_status = str(match.get("status") or "").strip().lower()
        if match_status not in {"live", "completed"}:
            continue

        match_id = int(match["id"])
        scores_payload = scores_snapshot.get(match_id) or {}
        contestants = scores_payload.get("contestants") or []
        if not contestants:
            if match_status == "live":
                print(f"[MATCHES] live rank cache miss match={match_id}")
            continue

        match_rank_map[match_id] = _rank_match_contestants(contestants)

    result = []
    for match in payload:
        match_copy = dict(match)
        if match_copy.get("status") in {"live", "completed"}:
            match_copy["current_rank"] = match_rank_map.get(int(match_copy["id"]), {}).get(int(user_id))
        else:
            match_copy["current_rank"] = None
        result.append(match_copy)
    return result
