from collections import defaultdict

from fastapi import APIRouter, Depends

from backend.database import get_db
from backend.middleware.auth import get_current_user

router = APIRouter(prefix="/api", tags=["achievements"])


@router.get("/achievements")
async def get_achievements(user: dict = Depends(get_current_user)):
    db = get_db()

    # --- Medals: compute from contestant_points ---
    rows = db.execute(
        """
        SELECT cp.user_id, u.name, cp.match_id, cp.points
        FROM contestant_points cp
        JOIN users u ON u.id = cp.user_id
        JOIN matches m ON m.id = cp.match_id
        WHERE m.status = 'completed'
        ORDER BY cp.match_id, cp.points DESC
        """
    ).fetchall()

    # Group by match and rank
    matches_data: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        matches_data[r["match_id"]].append(
            {"user_id": r["user_id"], "name": r["name"], "points": r["points"]}
        )

    medals: dict[int, dict] = defaultdict(lambda: {"gold": 0, "silver": 0, "bronze": 0, "name": ""})
    total_points: dict[int, dict] = defaultdict(lambda: {"total": 0.0, "name": ""})
    highest_score: list[dict] = []

    for match_id, contestants in matches_data.items():
        # Already sorted by points DESC from SQL
        for i, c in enumerate(contestants):
            uid = c["user_id"]
            medals[uid]["name"] = c["name"]
            total_points[uid]["name"] = c["name"]
            total_points[uid]["total"] += c["points"]

            # Rank with ties
            if i == 0:
                rank = 1
            elif c["points"] == contestants[i - 1]["points"]:
                rank = prev_rank
            else:
                rank = i + 1
            prev_rank = rank

            if rank == 1:
                medals[uid]["gold"] += 1
            elif rank == 2:
                medals[uid]["silver"] += 1
            elif rank == 3:
                medals[uid]["bronze"] += 1

        # Track highest single score
        if contestants:
            top = contestants[0]
            highest_score.append(
                {"user_id": top["user_id"], "name": top["name"], "value": top["points"], "match_id": match_id}
            )

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
    def top_n(data, key, n=5):
        sorted_list = sorted(data, key=lambda x: -x[key])
        return sorted_list[:n]

    # Medal leaderboards
    medal_list = [
        {"user_id": uid, "name": d["name"], "gold": d["gold"], "silver": d["silver"], "bronze": d["bronze"],
         "total": d["gold"] + d["silver"] + d["bronze"]}
        for uid, d in medals.items()
    ]

    gold_top = sorted(medal_list, key=lambda x: (-x["gold"], -x["silver"], -x["bronze"]))[:5]
    silver_top = sorted(medal_list, key=lambda x: (-x["silver"], -x["gold"], -x["bronze"]))[:5]
    bronze_top = sorted(medal_list, key=lambda x: (-x["bronze"], -x["gold"], -x["silver"]))[:5]
    total_medals_top = sorted(medal_list, key=lambda x: (-x["total"], -x["gold"], -x["silver"]))[:5]

    # Points leaderboard
    points_list = [
        {"user_id": uid, "name": d["name"], "value": round(d["total"], 1)}
        for uid, d in total_points.items()
    ]
    points_top = sorted(points_list, key=lambda x: -x["value"])[:5]

    # Highest single match score
    highest_score_top = sorted(highest_score, key=lambda x: -x["value"])[:5]

    # Knockout wins
    knockout_top = [{"user_id": r["user_id"], "name": r["name"], "value": r["wins"]} for r in kb_rows][:5]

    categories = [
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
    ]

    return {"categories": categories}
