import threading
from collections import defaultdict

from fastapi import APIRouter, Depends

from backend.database import get_db
from backend.middleware.auth import get_current_user, require_admin

router = APIRouter(prefix="/api", tags=["achievements"])

# In-memory cache of the final response
_cache_lock = threading.Lock()
_cached_response: dict | None = None


def invalidate_achievements_cache(match_id: int | None = None):
    """Called when a match completes. Incrementally updates stats for that match."""
    global _cached_response
    with _cache_lock:
        _cached_response = None

    if match_id is not None:
        try:
            _incremental_update(match_id)
        except Exception as e:
            print(f"[ACHIEVEMENTS] incremental update for match {match_id} failed: {e}")


def _incremental_update(match_id: int):
    """Update achievement_stats with just the new match's data."""
    from backend.routes.leaderboard import _load_effective_match_points, _compute_medals
    from backend.services.data_service import compute_prediction_bonuses

    db = get_db()

    # Check if this match was already processed
    row = db.execute("SELECT MAX(last_computed_match_id) AS max_id FROM achievement_stats").fetchone()
    last_id = row["max_id"] if row and row["max_id"] else 0
    if match_id <= last_id:
        return  # Already processed

    # Load effective points for just this match
    effective = _load_effective_match_points(db)
    contestants = effective.get(match_id)
    if not contestants:
        return

    # Compute medals for this match
    sorted_c = sorted(contestants, key=lambda x: (-x["points"], x["name"]))
    ranks: list[tuple[int, dict]] = []
    for i, c in enumerate(sorted_c):
        if i > 0 and c["points"] == sorted_c[i - 1]["points"]:
            rank = ranks[i - 1][0]
        else:
            rank = i + 1
        ranks.append((rank, c))

    medal_deltas: dict[int, dict[str, int]] = defaultdict(lambda: {"gold": 0, "silver": 0, "bronze": 0})
    for rank, c in ranks:
        uid = c["user_id"]
        if rank == 1:
            medal_deltas[uid]["gold"] += 1
        elif rank == 2:
            medal_deltas[uid]["silver"] += 1
        elif rank == 3:
            medal_deltas[uid]["bronze"] += 1

    # Prediction bonuses for this match
    bonuses = compute_prediction_bonuses(match_id)

    # Knockout wins (recount fully since it's cheap)
    kb_rows = db.execute(
        "SELECT winner_user_id, COUNT(*) AS wins FROM weekend_tournaments WHERE status = 'completed' AND winner_user_id IS NOT NULL GROUP BY winner_user_id"
    ).fetchall()
    knockout_wins = {r["winner_user_id"]: r["wins"] for r in kb_rows}

    # Upsert each user who participated in this match
    for c in contestants:
        uid = c["user_id"]
        name = c["name"]
        pts = float(c["points"])
        md = medal_deltas.get(uid, {"gold": 0, "silver": 0, "bronze": 0})
        bonus = bonuses.get(uid)

        # Check if user already has a row
        existing = db.execute("SELECT * FROM achievement_stats WHERE user_id = ?", (uid,)).fetchone()
        if existing:
            new_total_points = round(float(existing["total_points"]) + pts, 1)
            new_highest = max(float(existing["highest_score"]), pts)
            new_gold = existing["gold"] + md["gold"]
            new_silver = existing["silver"] + md["silver"]
            new_bronze = existing["bronze"] + md["bronze"]
            new_knockout = knockout_wins.get(uid, existing["knockout_wins"])
            new_pred_total = existing["predictions_total"] + (1 if bonus else 0)
            new_perfect = existing["perfect_strike"] + (1 if bonus and bonus["label"] == "Perfect Strike" else 0)
            new_elite = existing["elite_precision"] + (1 if bonus and bonus["label"] == "Elite Precision" else 0)
            new_great = existing["great_call"] + (1 if bonus and bonus["label"] == "Great Call" else 0)

            db.execute(
                """
                UPDATE achievement_stats SET
                    gold = ?, silver = ?, bronze = ?,
                    total_points = ?, highest_score = ?,
                    knockout_wins = ?,
                    predictions_total = ?, perfect_strike = ?, elite_precision = ?, great_call = ?,
                    last_computed_match_id = ?
                WHERE user_id = ?
                """,
                (new_gold, new_silver, new_bronze, new_total_points, new_highest,
                 new_knockout, new_pred_total, new_perfect, new_elite, new_great,
                 match_id, uid),
            )
        else:
            db.execute(
                """
                INSERT INTO achievement_stats (user_id, gold, silver, bronze, total_points, highest_score,
                    knockout_wins, predictions_total, perfect_strike, elite_precision, great_call, last_computed_match_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uid, md["gold"], md["silver"], md["bronze"], round(pts, 1), round(pts, 1),
                 knockout_wins.get(uid, 0),
                 1 if bonus else 0,
                 1 if bonus and bonus["label"] == "Perfect Strike" else 0,
                 1 if bonus and bonus["label"] == "Elite Precision" else 0,
                 1 if bonus and bonus["label"] == "Great Call" else 0,
                 match_id),
            )

    # Also update knockout_wins for users not in this match (in case weekend tournament just completed)
    for uid, wins in knockout_wins.items():
        db.execute(
            "UPDATE achievement_stats SET knockout_wins = ? WHERE user_id = ? AND knockout_wins <> ?",
            (wins, uid, wins),
        )

    db.commit()


def _full_recompute():
    """Full recompute of all achievement stats. Used on cold start or admin reset."""
    from backend.routes.leaderboard import _load_effective_match_points, _compute_medals
    from backend.services.data_service import compute_prediction_bonuses

    db = get_db()
    effective_match_points = _load_effective_match_points(db)

    medals_by_user = _compute_medals(effective_match_points)

    name_map: dict[int, str] = {}
    total_points: dict[int, float] = {}
    highest_score: dict[int, float] = {}

    for match_id, contestants in effective_match_points.items():
        if not contestants:
            continue
        for c in contestants:
            uid = c["user_id"]
            name_map[uid] = c["name"]
            total_points[uid] = total_points.get(uid, 0.0) + float(c["points"])
            pts = float(c["points"])
            if pts > highest_score.get(uid, 0.0):
                highest_score[uid] = pts

    prediction_counts: dict[int, dict[str, int]] = defaultdict(lambda: {"Perfect Strike": 0, "Elite Precision": 0, "Great Call": 0, "total": 0})
    for mid in effective_match_points.keys():
        bonuses = compute_prediction_bonuses(mid)
        for uid, info in bonuses.items():
            prediction_counts[uid][info["label"]] = prediction_counts[uid].get(info["label"], 0) + 1
            prediction_counts[uid]["total"] += 1

    kb_rows = db.execute(
        "SELECT winner_user_id, COUNT(*) AS wins FROM weekend_tournaments WHERE status = 'completed' AND winner_user_id IS NOT NULL GROUP BY winner_user_id"
    ).fetchall()
    knockout_wins = {r["winner_user_id"]: r["wins"] for r in kb_rows}

    max_match_id = max(effective_match_points.keys()) if effective_match_points else 0

    db.execute("DELETE FROM achievement_stats")
    for uid in name_map.keys():
        m = medals_by_user.get(uid, {"gold": 0, "silver": 0, "bronze": 0})
        pc = prediction_counts.get(uid, {"Perfect Strike": 0, "Elite Precision": 0, "Great Call": 0, "total": 0})
        db.execute(
            """
            INSERT INTO achievement_stats (user_id, gold, silver, bronze, total_points, highest_score,
                knockout_wins, predictions_total, perfect_strike, elite_precision, great_call, last_computed_match_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uid, m["gold"], m["silver"], m["bronze"],
             round(total_points.get(uid, 0.0), 1), round(highest_score.get(uid, 0.0), 1),
             knockout_wins.get(uid, 0),
             pc["total"], pc["Perfect Strike"], pc["Elite Precision"], pc["Great Call"],
             max_match_id),
        )
    db.commit()

    # Update memory cache
    global _cached_response
    response = _build_response_from_db(db)
    with _cache_lock:
        _cached_response = response


def _build_response_from_db(db=None) -> dict:
    """Build the API response from the achievement_stats table."""
    if db is None:
        db = get_db()

    rows = db.execute(
        """
        SELECT a.user_id, u.name, a.gold, a.silver, a.bronze,
               a.total_points, a.highest_score, a.knockout_wins,
               a.predictions_total, a.perfect_strike, a.elite_precision, a.great_call
        FROM achievement_stats a
        JOIN users u ON u.id = a.user_id
        """
    ).fetchall()

    if not rows:
        return {"categories": []}

    entries = [dict(r) for r in rows]

    def top5(key, secondary_keys=None):
        if secondary_keys:
            sort_key = lambda x: tuple(-x[k] for k in [key] + secondary_keys)
        else:
            sort_key = lambda x: -x[key]
        sorted_list = sorted(entries, key=sort_key)
        return [{"user_id": e["user_id"], "name": e["name"], "value": e[key]} for e in sorted_list[:5] if e[key] > 0]

    return {
        "categories": [
            {"title": "Most Gold Medals", "icon": "gold", "entries": top5("gold", ["silver", "bronze"])},
            {"title": "Most Silver Medals", "icon": "silver", "entries": top5("silver", ["gold", "bronze"])},
            {"title": "Most Bronze Medals", "icon": "bronze", "entries": top5("bronze", ["gold", "silver"])},
            {"title": "Most Total Medals", "icon": "medals",
             "entries": (lambda: sorted(
                 [{"user_id": e["user_id"], "name": e["name"], "value": e["gold"] + e["silver"] + e["bronze"]} for e in entries],
                 key=lambda x: -x["value"]
             )[:5])()},
            {"title": "Knockout Battle Wins", "icon": "trophy", "entries": top5("knockout_wins")},
            {"title": "Most Total Points", "icon": "points", "entries": top5("total_points")},
            {"title": "Highest Match Score", "icon": "fire", "entries": top5("highest_score")},
            {"title": "Most Predictions Won", "icon": "predictions", "entries": top5("predictions_total")},
            {"title": "Perfect Strike", "icon": "perfect", "entries": top5("perfect_strike")},
            {"title": "Elite Precision", "icon": "elite", "entries": top5("elite_precision")},
            {"title": "Great Call", "icon": "great", "entries": top5("great_call")},
        ]
    }


@router.get("/achievements")
async def get_achievements(user: dict = Depends(get_current_user)):
    global _cached_response

    with _cache_lock:
        if _cached_response is not None:
            return _cached_response

    # Try loading from DB (fast path after restart)
    db = get_db()
    has_data = db.execute("SELECT 1 FROM achievement_stats LIMIT 1").fetchone()
    if has_data:
        response = _build_response_from_db(db)
        with _cache_lock:
            _cached_response = response
        return response

    # Cold start: full recompute
    _full_recompute()
    with _cache_lock:
        return _cached_response or {"categories": []}


@router.post("/admin/achievements/recalculate")
async def admin_recalculate(user: dict = Depends(require_admin)):
    """Admin endpoint to force full recalculation of all achievement stats."""
    _full_recompute()
    return {"success": True, "message": "Achievement stats fully recalculated"}
