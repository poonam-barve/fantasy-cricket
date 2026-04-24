import threading
import time
import copy
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from collections import defaultdict

from backend.config import IST
from backend.middleware.auth import get_current_user
from backend.database import get_db
from backend.services import data_service

ENTRY_FEE = 50
PRIZE_SPLIT = [0.50, 0.30, 0.20]  # 1st, 2nd, 3rd
NON_PARTICIPANT_ADJUSTMENT = {
    "type": "percentage",  # "percentage" or "direct"
    "value": 15.0,
}

router = APIRouter(prefix="/api", tags=["leaderboard"])
LEADERBOARD_CACHE = {
    "leaderboard": None,
    "points_table": None,
    "player_points_version": "",
}
LEADERBOARD_CACHE_LOCK = threading.Lock()
LEADERBOARD_CACHE_SCHEDULER_LOCK = threading.Lock()
LEADERBOARD_CACHE_SCHEDULER_STARTED = False


def invalidate_leaderboard_cache():
    with LEADERBOARD_CACHE_LOCK:
        LEADERBOARD_CACHE["leaderboard"] = None
        LEADERBOARD_CACHE["points_table"] = None
        LEADERBOARD_CACHE["player_points_version"] = ""


def _get_cached_leaderboard_snapshot() -> dict | None:
    with LEADERBOARD_CACHE_LOCK:
        if LEADERBOARD_CACHE["leaderboard"] is None or LEADERBOARD_CACHE["points_table"] is None:
            return None
        return {
            "leaderboard": copy.deepcopy(LEADERBOARD_CACHE["leaderboard"]),
            "points_table": copy.deepcopy(LEADERBOARD_CACHE["points_table"]),
            "player_points_version": LEADERBOARD_CACHE["player_points_version"],
        }


def _compute_non_participant_points(lowest_points: float) -> float:
    adjustment_type = NON_PARTICIPANT_ADJUSTMENT["type"]
    adjustment_value = float(NON_PARTICIPANT_ADJUSTMENT["value"])
    if adjustment_type == "direct":
        adjusted = lowest_points - adjustment_value
    else:
        adjusted = lowest_points - (lowest_points * adjustment_value / 100.0)
    return round(adjusted * 2) / 2


def _compute_match_contestant_points(db, match_id: int) -> list[dict]:
    team_rows = db.execute(
        """
        SELECT
            u.id AS user_id,
            u.name AS user_name,
            ut.player_id,
            ut.is_captain,
            ut.is_vice_captain,
            COALESCE(pp.points, 0) AS player_points
        FROM user_teams ut
        JOIN users u ON u.id = ut.user_id
        LEFT JOIN player_points pp ON pp.match_id = ut.match_id AND pp.player_id = ut.player_id
        WHERE ut.match_id = ?
          AND u.is_active = 1
        ORDER BY u.id
        """,
        (match_id,),
    ).fetchall()

    totals = {}
    for row in team_rows:
        user_id = row["user_id"]
        entry = totals.setdefault(
            user_id,
            {"user_id": user_id, "name": row["user_name"], "points": 0.0},
        )

        base_points = float(row["player_points"] or 0)
        if row["is_captain"]:
            base_points *= 2.0
        elif row["is_vice_captain"]:
            base_points *= 1.5

        entry["points"] += base_points

    result = list(totals.values())
    for row in result:
        row["points"] = round(row["points"], 2)
    result.sort(key=lambda item: (-item["points"], item["name"]))
    return result


def _get_match_participant_ids(db, match_id: int) -> set[int]:
    rows = db.execute(
        """
        SELECT DISTINCT u.id
        FROM user_teams ut
        JOIN users u ON u.id = ut.user_id
        WHERE ut.match_id = ?
          AND u.is_active = 1
        """,
        (match_id,),
    ).fetchall()
    return {int(row["id"]) for row in rows}


def _get_completed_match_ids(db) -> list[int]:
    rows = db.execute(
        "SELECT id, match_date, match_time, status FROM matches ORDER BY match_date, match_time, id"
    ).fetchall()
    now = datetime.now(IST)
    completed_ids: list[int] = []
    for row in rows:
        status = str(row["status"] or "").strip().lower()
        if status == "completed":
            completed_ids.append(int(row["id"]))
            continue
        if status == "nr":
            continue
        try:
            match_datetime = datetime.strptime(
                f"{row['match_date']} {row['match_time']}", "%Y-%m-%d %H:%M"
            )
            match_datetime = IST.localize(match_datetime)
        except Exception:
            continue
        if now >= match_datetime + timedelta(hours=5):
            completed_ids.append(int(row["id"]))
    return completed_ids


def _load_effective_match_points(db) -> dict[int, list[dict]]:
    stored_rows = db.execute(
        """
        SELECT cp.user_id, u.name, cp.match_id, cp.points, cp.last_updated
        FROM contestant_points cp
        JOIN users u ON u.id = cp.user_id
        WHERE u.is_active = 1
        ORDER BY cp.match_id, cp.points DESC
        """
    ).fetchall()

    matches = defaultdict(list)
    for row in stored_rows:
        matches[row["match_id"]].append({
            "user_id": row["user_id"],
            "name": row["name"],
            "points": round(float(row["points"]), 2),
            "last_updated": row["last_updated"],
        })

    match_ids = _get_completed_match_ids(db)
    active_users = db.execute(
        """
        SELECT id, name
        FROM users
        WHERE is_active = 1
        ORDER BY name
        """
    ).fetchall()
    active_user_map = {row["id"]: row["name"] for row in active_users}
    effective = {}

    for match_id in match_ids:
        contestants = matches.get(match_id, [])
        expected_participant_ids = _get_match_participant_ids(db, match_id)
        if contestants:
            stored_participant_ids = {entry["user_id"] for entry in contestants}
            has_nonzero = any(entry["points"] != 0 for entry in contestants)
            player_points_exist = db.execute(
                "SELECT 1 FROM player_points WHERE match_id = ? AND points <> 0 LIMIT 1",
                (match_id,),
            ).fetchone()
            if stored_participant_ids == expected_participant_ids and (has_nonzero or not player_points_exist):
                effective[match_id] = contestants
                continue

        recomputed = _compute_match_contestant_points(db, match_id)
        effective[match_id] = recomputed

    for match_id, contestants in list(effective.items()):
        if not contestants:
            continue

        normalized = []
        for contestant in contestants:
            normalized.append({
                "user_id": contestant["user_id"],
                "name": contestant["name"],
                "points": round(float(contestant["points"]), 2),
                "last_updated": contestant.get("last_updated", ""),
                "adjusted": bool(contestant.get("adjusted", False)),
                "participated": bool(contestant.get("participated", True)),
            })

        participant_ids = {entry["user_id"] for entry in normalized if entry["participated"]}
        lowest_points = min(entry["points"] for entry in normalized if entry["participated"])
        adjusted_points = _compute_non_participant_points(lowest_points)

        for user_id, name in active_user_map.items():
            if user_id in participant_ids:
                continue
            normalized.append({
                "user_id": user_id,
                "name": name,
                "points": adjusted_points,
                "last_updated": "",
                "adjusted": True,
                "participated": False,
            })

        normalized.sort(key=lambda item: (-item["points"], item["name"]))
        effective[match_id] = normalized

    return effective


def _build_rank_map(active_users, totals_by_user: dict[int, float]) -> dict[int, int]:
    sorted_users = sorted(
        active_users,
        key=lambda row: (-round(float(totals_by_user.get(row["id"], 0)), 2), row["name"]),
    )

    rank_map: dict[int, int] = {}
    current_rank = 0
    previous_points = None
    for index, row in enumerate(sorted_users, start=1):
        uid = int(row["id"])
        points = round(float(totals_by_user.get(uid, 0)), 2)
        if previous_points is None or points != previous_points:
            current_rank = index
            previous_points = points
        rank_map[uid] = current_rank
    return rank_map


def _build_rank_movement_context(db, effective_match_points: dict[int, list[dict]] | None = None):
    if effective_match_points is None:
        effective_match_points = _load_effective_match_points(db)

    active_users = db.execute(
        """
        SELECT id, name
        FROM users
        WHERE is_active = 1
        ORDER BY name
        """
    ).fetchall()

    cumulative_points: dict[int, float] = defaultdict(float)
    rank_change_by_match: dict[int, dict[int, int]] = {}
    previous_rank_map: dict[int, int] | None = None
    current_rank_map: dict[int, int] = {}
    completed_match_ids = [
        match_id
        for match_id in _get_completed_match_ids(db)
        if match_id in effective_match_points
    ]

    for match_id in completed_match_ids:
        for contestant in effective_match_points.get(match_id, []):
            cumulative_points[int(contestant["user_id"])] += float(contestant["points"])

        current_rank_map = _build_rank_map(active_users, cumulative_points)
        # Compare the cumulative leaderboard after this match to the cumulative
        # leaderboard immediately before it. This keeps arrows tied to total
        # points progression, not update timing.
        if previous_rank_map is not None:
            delta_map: dict[int, int] = {}
            for user_id, current_rank in current_rank_map.items():
                previous_rank = previous_rank_map.get(user_id)
                if previous_rank is None:
                    continue
                delta = previous_rank - current_rank
                if delta:
                    delta_map[user_id] = delta
            rank_change_by_match[int(match_id)] = delta_map
        previous_rank_map = current_rank_map

    current_rank_change = rank_change_by_match.get(completed_match_ids[-1], {}) if completed_match_ids else {}
    return {
        "effective_match_points": effective_match_points,
        "current_rank_map": current_rank_map,
        "current_rank_change": current_rank_change,
        "rank_change_by_match": rank_change_by_match,
    }


def _calculate_balances(db, effective_match_points: dict[int, list[dict]] | None = None):
    """Calculate running balance for each user across all completed matches."""
    if effective_match_points is None:
        effective_match_points = _load_effective_match_points(db)

    matches = defaultdict(list)
    for match_id, contestants in effective_match_points.items():
        for contestant in contestants:
            if not contestant.get("participated", True):
                continue
            matches[match_id].append({
                "user_id": contestant["user_id"],
                "points": float(contestant["points"]),
            })

    # Calculate balance per user
    balances = defaultdict(float)  # user_id -> running balance
    match_results = defaultdict(dict)  # user_id -> {match_id -> net}

    for match_id, participants in matches.items():
        # Sort by points descending
        participants.sort(key=lambda x: x["points"], reverse=True)
        num = len(participants)
        pool = num * ENTRY_FEE

        for i, p in enumerate(participants):
            uid = p["user_id"]

            # Prize for top 3
            if i < len(PRIZE_SPLIT):
                prize = pool * PRIZE_SPLIT[i]
            else:
                prize = 0

            net = prize - ENTRY_FEE
            balances[uid] += net
            match_results[uid][match_id] = round(net, 2)

    return balances, match_results

def _compute_medals(effective_match_points: dict) -> dict[int, dict[str, int]]:
    """Compute gold/silver/bronze medal counts per user across all matches."""
    medals: dict[int, dict[str, int]] = defaultdict(lambda: {"gold": 0, "silver": 0, "bronze": 0})

    for match_id, contestants in effective_match_points.items():
        if not contestants:
            continue
        sorted_c = sorted(contestants, key=lambda x: (-x["points"], x["name"]))
        # Assign ranks handling ties
        ranks: list[tuple[int, dict]] = []
        for i, c in enumerate(sorted_c):
            if i > 0 and c["points"] == sorted_c[i - 1]["points"]:
                rank = ranks[i - 1][0]
            else:
                rank = i + 1
            ranks.append((rank, c))

        for rank, c in ranks:
            uid = c["user_id"]
            if rank == 1:
                medals[uid]["gold"] += 1
            elif rank == 2:
                medals[uid]["silver"] += 1
            elif rank == 3:
                medals[uid]["bronze"] += 1

    return dict(medals)


def _build_leaderboard(db, effective_match_points: dict[int, list[dict]] | None = None, current_rank_change: dict[int, int] | None = None):
    if effective_match_points is None:
        effective_match_points = _load_effective_match_points(db)
    balances, _ = _calculate_balances(db, effective_match_points)
    totals_by_user = defaultdict(float)
    for contestants in effective_match_points.values():
        for contestant in contestants:
            totals_by_user[contestant["user_id"]] += float(contestant["points"])

    medals_by_user = _compute_medals(effective_match_points)

    # Weekend battle wins
    weekend_wins: dict[int, int] = {}
    try:
        wt_rows = db.execute(
            "SELECT winner_user_id, COUNT(*) AS wins FROM weekend_tournaments WHERE status = 'completed' AND winner_user_id IS NOT NULL GROUP BY winner_user_id"
        ).fetchall()
        for r in wt_rows:
            weekend_wins[r["winner_user_id"]] = r["wins"]
    except Exception:
        pass

    users = db.execute(
        """
        SELECT u.id, u.name
        FROM users u
        WHERE u.is_active = 1
        ORDER BY u.name
        """
    ).fetchall()

    sorted_users = sorted(
        users,
        key=lambda row: (-round(float(totals_by_user.get(row["id"], 0)), 2), row["name"]),
    )

    result = []
    rank = 1
    for i, row in enumerate(sorted_users):
        uid = row["id"]
        pts = round(float(totals_by_user.get(uid, 0)), 2)
        user_medals = medals_by_user.get(uid, {"gold": 0, "silver": 0, "bronze": 0})

        if i > 0 and pts == result[i - 1]["points"]:
            rank = result[i - 1]["rank"]
        else:
            rank = i + 1

        result.append({
            "rank": rank,
            "name": row["name"],
            "user_id": uid,
            "points": pts,
            "rank_change": current_rank_change.get(uid) if current_rank_change else None,
            "gold": user_medals["gold"],
            "silver": user_medals["silver"],
            "bronze": user_medals["bronze"],
            "weekend_wins": weekend_wins.get(uid, 0),
            "balance": round(balances.get(uid, 0), 2),
        })

    return result


def _build_points_table(db, effective_match_points: dict[int, list[dict]] | None = None, rank_change_by_match: dict[int, dict[int, int]] | None = None):
    if effective_match_points is None:
        effective_match_points = _load_effective_match_points(db)
    _, match_results = _calculate_balances(db, effective_match_points)
    result = []
    for match_id, contestants in effective_match_points.items():
        sorted_contestants = sorted(contestants, key=lambda item: (-item["points"], item["name"]))
        for contestant in sorted_contestants:
            uid = contestant["user_id"]
            result.append({
                "user_id": uid,
                "name": contestant["name"],
                "match_id": match_id,
                "points": contestant["points"],
                "last_updated": contestant.get("last_updated", ""),
                "net": match_results.get(uid, {}).get(match_id, 0),
                "adjusted": contestant.get("adjusted", False),
                "participated": contestant.get("participated", True),
                "rank_change": (rank_change_by_match or {}).get(match_id, {}).get(uid),
            })
    return result


def _wait_for_leaderboard_cache(timeout_seconds: float = 8.0, poll_seconds: float = 0.25) -> dict | None:
    deadline = time.time() + timeout_seconds
    first_wait_log = True

    while time.time() < deadline:
        cached_snapshot = _get_cached_leaderboard_snapshot()
        if cached_snapshot is not None:
            return cached_snapshot

        if first_wait_log:
            print(f"[LEADERBOARD] waiting for cache timeout={timeout_seconds:.1f}s")
            first_wait_log = False

        time.sleep(poll_seconds)

    return _get_cached_leaderboard_snapshot()


def refresh_leaderboard_cache_once() -> dict:
    db = get_db()
    effective_match_points = _load_effective_match_points(db)
    rank_context = _build_rank_movement_context(db, effective_match_points)
    leaderboard = _build_leaderboard(db, effective_match_points, rank_context["current_rank_change"])
    points_table = _build_points_table(db, effective_match_points, rank_context["rank_change_by_match"])
    player_points_version = data_service.get_latest_player_points_update()
    with LEADERBOARD_CACHE_LOCK:
        LEADERBOARD_CACHE["leaderboard"] = leaderboard
        LEADERBOARD_CACHE["points_table"] = points_table
        LEADERBOARD_CACHE["player_points_version"] = player_points_version
    return {
        "leaderboard": len(leaderboard),
        "points_table": len(points_table),
        "player_points_version": player_points_version,
    }


def start_leaderboard_cache_scheduler():
    global LEADERBOARD_CACHE_SCHEDULER_STARTED
    with LEADERBOARD_CACHE_SCHEDULER_LOCK:
        if LEADERBOARD_CACHE_SCHEDULER_STARTED:
            return
        LEADERBOARD_CACHE_SCHEDULER_STARTED = True

    def run():
        while True:
            try:
                summary = refresh_leaderboard_cache_once()
                sleep_seconds = 15 if summary["leaderboard"] or summary["points_table"] else 45
            except Exception as exc:
                print(f"[LEADERBOARD] scheduler error: {exc}")
                sleep_seconds = 30
            time.sleep(sleep_seconds)

    thread = threading.Thread(target=run, daemon=True, name="leaderboard-cache-scheduler")
    thread.start()


@router.get("/leaderboard")
async def leaderboard(user: dict = Depends(get_current_user)):
    cached_snapshot = _wait_for_leaderboard_cache()
    if cached_snapshot is None:
        return []
    return cached_snapshot["leaderboard"]


@router.get("/points-table")
async def points_table(user: dict = Depends(get_current_user)):
    cached_snapshot = _wait_for_leaderboard_cache()
    if cached_snapshot is None:
        return []
    return cached_snapshot["points_table"]
