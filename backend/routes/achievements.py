import threading

from fastapi import APIRouter, Depends

from backend.database import get_db
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api", tags=["achievements"])

# In-memory cache: invalidated when a match completes
_cache_lock = threading.Lock()
_cached_response: dict | None = None


def invalidate_achievements_cache():
    global _cached_response
    with _cache_lock:
        _cached_response = None


def _compute_achievements() -> dict:
    from backend.routes.leaderboard import _load_effective_match_points, _compute_medals

    db = get_db()
    effective_match_points = _load_effective_match_points(db)

    # --- Medals (same logic as leaderboard) ---
    medals_by_user = _compute_medals(effective_match_points)

    # Build name map from effective data
    name_map: dict[int, str] = {}
    total_points: dict[int, float] = {}
    highest_score: list[dict] = []

    for match_id, contestants in effective_match_points.items():
        if not contestants:
            continue
        for c in contestants:
            uid = c["user_id"]
            name_map[uid] = c["name"]
            total_points[uid] = total_points.get(uid, 0.0) + float(c["points"])

        # Highest single match score (top scorer of this match)
        top = max(contestants, key=lambda x: x["points"])
        highest_score.append(
            {"user_id": top["user_id"], "name": top["name"], "value": round(float(top["points"]), 1), "match_id": match_id}
        )

    # --- Prediction Bonuses ---
    from backend.services.data_service import compute_prediction_bonuses
    from collections import defaultdict

    prediction_counts: dict[int, dict[str, int]] = defaultdict(lambda: {"Perfect Strike": 0, "Elite Precision": 0, "Great Call": 0, "total": 0})
    completed_match_ids = list(effective_match_points.keys())
    for mid in completed_match_ids:
        bonuses = compute_prediction_bonuses(mid)
        for uid, info in bonuses.items():
            label = info["label"]
            prediction_counts[uid][label] = prediction_counts[uid].get(label, 0) + 1
            prediction_counts[uid]["total"] += 1

    # --- Knockout Battle Wins ---
    kb_rows = db.execute(
        """
        SELECT wt.winner_user_id AS user_id, u.name, COUNT(*) AS wins
        FROM weekend_tournaments wt
        JOIN users u ON u.id = wt.winner_user_id
        WHERE wt.status = 'completed' AND wt.winner_user_id IS NOT NULL
        GROUP BY wt.winner_user_id, u.name
        ORDER BY wins DESC
        """
    ).fetchall()

    # --- Build categories ---
    medal_list = [
        {"user_id": uid, "name": name_map.get(uid, ""), "gold": d["gold"], "silver": d["silver"], "bronze": d["bronze"],
         "total": d["gold"] + d["silver"] + d["bronze"]}
        for uid, d in medals_by_user.items()
    ]

    gold_top = sorted(medal_list, key=lambda x: (-x["gold"], -x["silver"], -x["bronze"]))[:5]
    silver_top = sorted(medal_list, key=lambda x: (-x["silver"], -x["gold"], -x["bronze"]))[:5]
    bronze_top = sorted(medal_list, key=lambda x: (-x["bronze"], -x["gold"], -x["silver"]))[:5]
    total_medals_top = sorted(medal_list, key=lambda x: (-x["total"], -x["gold"], -x["silver"]))[:5]

    # Points leaderboard
    points_list = [
        {"user_id": uid, "name": name_map.get(uid, ""), "value": round(pts, 1)}
        for uid, pts in total_points.items()
    ]
    points_top = sorted(points_list, key=lambda x: -x["value"])[:5]

    # Highest single match score
    highest_score_top = sorted(highest_score, key=lambda x: -x["value"])[:5]

    # Knockout wins
    knockout_top = [{"user_id": r["user_id"], "name": r["name"], "value": r["wins"]} for r in kb_rows][:5]

    # Prediction leaderboards
    pred_list = [
        {"user_id": uid, "name": name_map.get(uid, ""), **counts}
        for uid, counts in prediction_counts.items()
        if uid in name_map
    ]
    perfect_top = sorted(pred_list, key=lambda x: -x["Perfect Strike"])[:5]
    elite_top = sorted(pred_list, key=lambda x: -x["Elite Precision"])[:5]
    great_top = sorted(pred_list, key=lambda x: -x["Great Call"])[:5]
    predictions_total_top = sorted(pred_list, key=lambda x: -x["total"])[:5]

    return {
        "categories": [
            {
                "title": "Most Gold Medals",
                "icon": "gold",
                "entries": [{"user_id": e["user_id"], "name": e["name"], "value": e["gold"]} for e in gold_top],
            },
            {
                "title": "Most Silver Medals",
                "icon": "silver",
                "entries": [{"user_id": e["user_id"], "name": e["name"], "value": e["silver"]} for e in silver_top],
            },
            {
                "title": "Most Bronze Medals",
                "icon": "bronze",
                "entries": [{"user_id": e["user_id"], "name": e["name"], "value": e["bronze"]} for e in bronze_top],
            },
            {
                "title": "Most Total Medals",
                "icon": "medals",
                "entries": [{"user_id": e["user_id"], "name": e["name"], "value": e["total"]} for e in total_medals_top],
            },
            {
                "title": "Knockout Battle Wins",
                "icon": "trophy",
                "entries": knockout_top,
            },
            {
                "title": "Most Total Points",
                "icon": "points",
                "entries": points_top,
            },
            {
                "title": "Highest Match Score",
                "icon": "fire",
                "entries": [{"user_id": e["user_id"], "name": e["name"], "value": e["value"]} for e in highest_score_top],
            },
            {
                "title": "Most Predictions Won",
                "icon": "predictions",
                "entries": [{"user_id": e["user_id"], "name": e["name"], "value": e["total"]} for e in predictions_total_top if e["total"] > 0],
            },
            {
                "title": "Perfect Strike",
                "icon": "perfect",
                "entries": [{"user_id": e["user_id"], "name": e["name"], "value": e["Perfect Strike"]} for e in perfect_top if e["Perfect Strike"] > 0],
            },
            {
                "title": "Elite Precision",
                "icon": "elite",
                "entries": [{"user_id": e["user_id"], "name": e["name"], "value": e["Elite Precision"]} for e in elite_top if e["Elite Precision"] > 0],
            },
            {
                "title": "Great Call",
                "icon": "great",
                "entries": [{"user_id": e["user_id"], "name": e["name"], "value": e["Great Call"]} for e in great_top if e["Great Call"] > 0],
            },
        ]
    }


@router.get("/achievements")
async def get_achievements(user: dict = Depends(get_current_user)):
    global _cached_response
    with _cache_lock:
        if _cached_response is not None:
            return _cached_response

    result = _compute_achievements()

    with _cache_lock:
        _cached_response = result

    return result
