import copy

from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timedelta

from backend.middleware.auth import get_current_user
from backend.database import get_db
from backend.config import ROLES, IST, get_current_datetime, get_current_date_key
from backend.models.match import Match, clean_team_name
from backend.models.registry import PlayerRegistry
from backend.services import data_service
from backend.services.scraper import fetch_cricbuzz_scorecard_html, fetch_playing_xi, fetch_scorecard_html, get_cached_toss_info
from bs4 import BeautifulSoup

router = APIRouter(prefix="/api", tags=["players"])


def _build_registry(players_rows: list[dict]) -> PlayerRegistry:
    players_data = []
    for row in players_rows:
        players_data.append({
            "PlayerID": row["id"],
            "Name": row["name"],
            "Team": row["team"],
            "Role": row["role"],
            "Aliases": row.get("aliases") or "",
        })
    return PlayerRegistry(players_data)


def _load_recent_completed_history(db, teams: list[str], player_ids: list[int]) -> dict[int, list[dict]]:
    if not teams or not player_ids:
        return {}

    matches_rows = db.execute(
        f"""
        SELECT id, team1, team2
        FROM matches
        WHERE status = 'completed'
          AND (team1 IN ({",".join("?" * len(teams))}) OR team2 IN ({",".join("?" * len(teams))}))
        ORDER BY id DESC
        """,
        [*teams, *teams],
    ).fetchall()

    matches_by_team: dict[str, list[dict]] = {team: [] for team in teams}
    match_ids: list[int] = []
    for row in matches_rows:
        match_dict = dict(row)
        match_id = int(match_dict["id"])
        match_ids.append(match_id)
        for team in teams:
            if match_dict["team1"] == team or match_dict["team2"] == team:
                matches_by_team.setdefault(team, []).append(match_dict)

    points_lookup: dict[tuple[int, int], float] = {}
    if match_ids:
        point_rows = db.execute(
            f"""
            SELECT match_id, player_id, points
            FROM player_points
            WHERE player_id IN ({",".join("?" * len(player_ids))})
              AND match_id IN ({",".join("?" * len(match_ids))})
            """,
            [*player_ids, *match_ids],
        ).fetchall()
        for row in point_rows:
            points_lookup[(int(row["player_id"]), int(row["match_id"]))] = round(float(row["points"] or 0), 2)

    history_by_player: dict[int, list[dict]] = {}
    player_team_rows = db.execute(
        f"""
        SELECT id, team
        FROM players
        WHERE id IN ({",".join("?" * len(player_ids))})
        """,
        player_ids,
    ).fetchall()
    for row in player_team_rows:
        player_id = int(row["id"])
        team = row["team"]
        recent_matches = matches_by_team.get(team, [])
        history_by_player[player_id] = [
            {
                "match_id": int(match_row["id"]),
                "opponent": match_row["team2"] if match_row["team1"] == team else match_row["team1"],
                "points": points_lookup.get((player_id, int(match_row["id"]))),
                "did_not_play": (player_id, int(match_row["id"])) not in points_lookup,
            }
            for match_row in recent_matches
        ]

    return history_by_player


def _load_last_completed_team_xi(
    db,
    current_match_id: int,
    team: str,
) -> dict | None:
    cached = data_service.get_cached_last_match_xi(current_match_id, team)
    if cached is not None:
        return cached

    last_match = db.execute(
        """
        SELECT id, team1, team2, match_date, match_time, toss_time
        FROM matches
        WHERE status = 'completed'
          AND (team1 = ? OR team2 = ?)
        ORDER BY match_date DESC, match_time DESC, id DESC
        LIMIT 1
        """,
        (team, team),
    ).fetchone()
    if not last_match:
        return None

    last_match_row = dict(last_match)
    last_match_id = int(last_match_row["id"])
    last_team1 = last_match_row["team1"]
    last_team2 = last_match_row["team2"]
    last_match_date = last_match_row["match_date"]
    last_match_time = last_match_row["match_time"]
    last_toss_time = last_match_row.get("toss_time") or last_match_row.get("TossTime")

    player_rows = db.execute(
        """
        SELECT id, name, team, role, type, aliases
        FROM players
        WHERE team IN (?, ?)
        """,
        (last_team1, last_team2),
    ).fetchall()
    last_players = [dict(row) for row in player_rows]
    registry = _build_registry(last_players)
    match_obj = Match(
        last_match_id,
        last_team1,
        last_team2,
        registry,
        last_match_date,
    )

    cached_playing_xi = data_service.get_cached_match_playing_xi(
        last_match_id,
        last_team1,
        last_team2,
        last_match_date,
        last_match_time,
    )
    if cached_playing_xi and cached_playing_xi.get("announced"):
        playing_xi = cached_playing_xi
    else:
        playing_xi = fetch_playing_xi(
            last_match_id,
            last_team1,
            last_team2,
            last_players,
            last_match_date,
            last_match_time,
            last_toss_time,
            force_refresh=True,
        )

    if not playing_xi or not playing_xi.get("announced"):
        return None

    playing_ids = [int(pid) for pid in playing_xi.get("player_ids", [])]
    if len(playing_ids) != 22:
        return None

    match_obj.apply_playing_xi(playing_ids)
    cricbuzz_html = fetch_cricbuzz_scorecard_html(last_match_id, last_team1, last_team2)
    if cricbuzz_html:
        match_obj.parse_cricbuzz_scorecard_html(cricbuzz_html, reset_players=False)
    espn_html = fetch_scorecard_html(last_match_id, last_team1, last_team2)
    if espn_html:
        soup = BeautifulSoup(espn_html, "html.parser")
        match_obj.parse_espn_bowling_dot_balls(soup)

    player_team_lookup = {int(row["id"]): row["team"] for row in last_players}
    team_order = [pid for pid in playing_ids if player_team_lookup.get(pid) == team]
    if len(team_order) != 11:
        return None

    impact_sub_player_ids = [
        int(pid)
        for pid, player in match_obj.players.items()
        if player_team_lookup.get(int(pid)) == team and int(pid) not in team_order and getattr(player, "played", False)
    ]
    impact_sub_player_ids = [
        pid for pid in impact_sub_player_ids
        if pid not in team_order
    ]
    impact_sub_player_ids.sort(
        key=lambda pid: (
            0 if player_team_lookup.get(pid) == team else 1,
            -getattr(match_obj.players.get(pid), "points", 0),
            pid,
        )
    )

    payload = {
        "match_id": last_match_id,
        "team": team,
        "player_ids": team_order,
        "impact_sub_player_ids": impact_sub_player_ids[:1],
    }
    return data_service.set_cached_last_match_xi(current_match_id, team, payload)


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


def _is_match_today(match_date: str | None) -> bool:
    if not match_date:
        return False
    try:
        return match_date == get_current_date_key()
    except Exception:
        return False

@router.get("/players")
async def list_players(
    match_id: Optional[int] = Query(None),
    user: dict = Depends(get_current_user),
):
    db = get_db()

    if match_id:
        cached_payload = data_service.get_cached_match_player_payload(match_id)
        if cached_payload is not None:
            players = [copy.deepcopy(player) for player in cached_payload["players"]]
            team1, team2 = cached_payload["match_teams"]
            match_date = cached_payload["match_date"]
            match_time = cached_payload["match_time"]
        else:
            # Get the match to find teams
            match = db.execute(
                "SELECT * FROM matches WHERE id = ?", (match_id,)
            ).fetchone()

            if not match:
                return {"error": "Match not found"}

            team1 = match["team1"]
            team2 = match["team2"]
            match_date = match["match_date"]
            match_time = match["match_time"]

            rows = db.execute(
                """
                SELECT
                    p.id,
                    p.name,
                    p.team,
                    p.role,
                    p.type,
                    p.aliases,
                    COALESCE(SUM(pp.points), 0) AS total_points,
                    COUNT(pp.match_id) AS matches_played,
                    CASE WHEN COUNT(pp.match_id) > 0
                         THEN ROUND(CAST(COALESCE(SUM(pp.points), 0) * 1.0 / COUNT(pp.match_id) AS numeric), 2)
                         ELSE 0 END AS avg_points
                FROM players p
                LEFT JOIN player_points pp ON pp.player_id = p.id
                WHERE p.team IN (?, ?)
                GROUP BY p.id, p.name, p.team, p.role, p.type, p.aliases
                ORDER BY
                    CASE p.role
                        WHEN 'Wicketkeeper' THEN 1
                        WHEN 'Batter' THEN 2
                        WHEN 'AllRounder' THEN 3
                        WHEN 'Bowler' THEN 4
                        ELSE 5
                    END,
                    total_points DESC,
                    p.name ASC
                """,
                (team1, team2),
            ).fetchall()

            # Fetch last match points per player in one query
            last_match_rows = db.execute(
                """
                SELECT pp.player_id, pp.points
                FROM player_points pp
                INNER JOIN (
                    SELECT player_id, MAX(match_id) AS max_mid
                    FROM player_points
                    GROUP BY player_id
                ) latest ON pp.player_id = latest.player_id AND pp.match_id = latest.max_mid
                """
            ).fetchall()
            last_match_map = {r["player_id"]: round(float(r["points"]), 2) for r in last_match_rows}
            player_ids = [int(row["id"]) for row in rows]
            history_by_player = _load_recent_completed_history(db, [team1, team2], player_ids)

            players = []
            for row in rows:
                player = dict(row)
                player["total_points"] = round(float(player.get("total_points") or 0), 2)
                player["matches_played"] = int(player.get("matches_played") or 0)
                player["avg_points"] = round(float(player.get("avg_points") or 0), 2)
                player["last_match_points"] = last_match_map.get(player["id"])
                player["recent_history"] = history_by_player.get(player["id"], [])
                players.append(player)

            data_service.set_cached_match_player_payload(match_id, {
                "players": players,
                "match_teams": [team1, team2],
                "match_date": match_date,
                "match_time": match_time,
            })

            players = [copy.deepcopy(player) for player in players]

        playing_xi_data = {
            "announced": False,
            "url": "",
            "player_ids": [],
            "substitute_ids": [],
        }
        cached_playing_xi = data_service.get_cached_match_playing_xi(
            match_id,
            team1,
            team2,
            match_date,
            match_time,
        )
        if cached_playing_xi and cached_playing_xi.get("announced"):
            playing_xi_data = cached_playing_xi

        toss_info = get_cached_toss_info(match_id) or {"announced": False, "team": None, "decision": None, "text": "", "url": ""}
        lineup_window_open = _is_lineup_window_open(match_date, match_time)

        playing_ids = set(playing_xi_data["player_ids"])
        substitute_ids = set(playing_xi_data.get("substitute_ids", []))
        playing_order = {player_id: index for index, player_id in enumerate(playing_xi_data["player_ids"])}
        substitute_order = {
            player_id: index for index, player_id in enumerate(playing_xi_data.get("substitute_ids", []))
        }
        playing_xi_known = len(playing_ids) == 22
        substitutes_known = len(substitute_ids) == 10
        is_today_match = _is_match_today(match_date)
        lineup_preview: dict[str, dict] = {}
        if is_today_match and not playing_xi_data["announced"]:
            for team in (team1, team2):
                preview = _load_last_completed_team_xi(db, match_id, team)
                if preview:
                    lineup_preview[team] = preview

        # Group by role
        grouped = {role: [] for role in ROLES}
        for player in players:
            if not playing_xi_data["announced"]:
                player["is_playing_xi"] = None
                player["is_substitute"] = None
                player["availability_status"] = None
                player["availability_order"] = None
            elif player["id"] in playing_ids:
                player["is_playing_xi"] = True
                player["is_substitute"] = False
                player["availability_status"] = "available"
                player["availability_order"] = playing_order.get(player["id"])
            elif substitutes_known and player["id"] in substitute_ids:
                player["is_playing_xi"] = False
                player["is_substitute"] = True
                player["availability_status"] = "substitute"
                player["availability_order"] = substitute_order.get(player["id"])
            elif playing_xi_known:
                player["is_playing_xi"] = False
                player["is_substitute"] = False
                player["availability_status"] = "unavailable"
                player["availability_order"] = None
            else:
                player["is_playing_xi"] = None
                player["is_substitute"] = None
                player["availability_status"] = None
                player["availability_order"] = None
            if player["role"] in grouped:
                grouped[player["role"]].append(player)

        return {
            "players": grouped,
            "match_teams": [team1, team2],
            "playing_xi": {
                "announced": playing_xi_data["announced"],
                "url": playing_xi_data["url"],
                "playing_count": len(playing_ids),
                "substitute_count": len(substitute_ids),
            },
            "lineup_window_open": lineup_window_open,
            "is_today_match": is_today_match,
            "last_match_xi": lineup_preview,
            "toss": toss_info,
        }

    # Return all players
    rows = db.execute(
        """
        SELECT
            p.id,
            p.name,
            p.team,
            p.role,
            p.type,
            p.aliases,
            COALESCE(SUM(pp.points), 0) AS total_points
        FROM players p
        LEFT JOIN player_points pp ON pp.player_id = p.id
        GROUP BY p.id, p.name, p.team, p.role, p.type, p.aliases
        ORDER BY p.team, p.role, total_points DESC, p.name
        """
    ).fetchall()
    result = []
    for row in rows:
        player = dict(row)
        player["total_points"] = round(float(player.get("total_points") or 0), 2)
        result.append(player)
    return result
