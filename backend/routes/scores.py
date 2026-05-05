import copy
import threading
import time
import traceback
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.config import IST, get_current_datetime
from backend.middleware.auth import get_current_user
from backend.database import get_db
from backend.models.match import Match, clean_team_name
from backend.models.registry import PlayerRegistry
from backend.services import data_service
from backend.services.double_buffer_cache import DoubleBufferCache
from backend.services.cache_locks import acquire_cache_locks, get_cache_lock
from backend.services.match_status import resolve_match_status_from_row
from backend.services.live_scores import append_missing_live_team_players
from backend.services.scraper import (
    fetch_scorecard_html,
    fetch_cricbuzz_scorecard_html,
    get_last_fetched_espn_scorecard_url,
    refresh_playing_xi_cache,
)
from bs4 import BeautifulSoup

router = APIRouter(prefix="/api/scores", tags=["scores"])
LIVE_MATCH_CACHE_TTL_SECONDS = 30
MATCH_DATA_CACHE: dict[tuple[int, bool], dict] = {}
MATCH_DATA_CACHE_LOCK = get_cache_lock("scores_match_data")
MATCH_DATA_REFRESH_INFLIGHT: set[tuple[int, bool]] = set()

SCORES_RESPONSE_CACHE_LOCK = threading.Lock()
SCORES_RESPONSE_CACHE = DoubleBufferCache(lock_name="scores_response")
SCORES_CACHE_SCHEDULER_LOCK = threading.Lock()
SCORES_CACHE_SCHEDULER_STARTED = False
SCORES_PERSIST_LOCK = threading.Lock()
SCORES_REFRESH_INFLIGHT_LOCK = threading.Lock()
SCORES_REFRESH_INFLIGHT: set[int] = set()
SCORES_REFRESH_LOCK = threading.Lock()


def _empty_match_scores_payload(match_status: str = "live") -> dict:
    return {
        "players": [],
        "contestants": [],
        "match_status": match_status,
        "scorecard": [],
    }


def _copy_score_payload(payload: dict | None) -> dict | None:
    return copy.deepcopy(payload) if payload is not None else None


def _log_scores_cache(message: str):
    timestamp = get_current_datetime().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [SCORES] {message}")


def _row_value(row, *keys, default=None):
    if not row:
        return default
    for key in keys:
        if isinstance(row, dict) and key in row:
            value = row.get(key)
            if value not in (None, ""):
                return value
        else:
            try:
                value = row[key]
                if value not in (None, ""):
                    return value
            except Exception:
                continue
    return default


def _match_status_value(match_row) -> str:
    status, _locked = resolve_match_status_from_row(match_row)
    return status


def _is_live_score_target(match_row) -> bool:
    return _match_status_value(match_row) == "live"


def _is_completed_score_target(match_row) -> bool:
    return _match_status_value(match_row) == "completed"


def invalidate_scores_response_cache():
    SCORES_RESPONSE_CACHE.invalidate()
    _log_scores_cache("response cache invalidated")


def _get_cached_score_payload(match_id: int) -> dict | None:
    snapshot = SCORES_RESPONSE_CACHE.read()
    if not snapshot:
        return None
    payload = snapshot.get(int(match_id))
    return _copy_score_payload(payload)


def _get_scores_cache_version() -> int:
    return 0


def _wait_for_cached_score_payload(match_id: int, timeout_seconds: float = 8.0, poll_seconds: float = 0.25) -> dict | None:
    return _get_cached_score_payload(match_id)


def _ensure_score_payload_cached(match_id: int, match_row=None) -> dict | None:
    return _wait_for_cached_score_payload(match_id)


def _get_live_cached_score_payload(match_id: int, match_row, registry, players_data, db) -> dict | None:
    return None


def _queue_scores_refresh(match_id: int) -> None:
    with SCORES_REFRESH_INFLIGHT_LOCK:
        if match_id in SCORES_REFRESH_INFLIGHT:
            return
        SCORES_REFRESH_INFLIGHT.add(match_id)

    def run():
        try:
            refresh_scores_response_cache_once()
        except Exception as exc:
            _log_scores_cache(f"background refresh failed match={match_id}: {exc}")
        finally:
            with SCORES_REFRESH_INFLIGHT_LOCK:
                SCORES_REFRESH_INFLIGHT.discard(match_id)

    threading.Thread(target=run, daemon=True, name=f"scores-refresh-{match_id}").start()


def _store_scores_response_cache(snapshot: dict[int, dict]) -> None:
    SCORES_RESPONSE_CACHE.publish(snapshot)
    _log_scores_cache(f"response cache swapped matches={len(snapshot)}")


def _persist_scores_snapshot_to_db(snapshot: dict[int, dict], match_ids: set[int] | None = None) -> None:
    now_str = get_current_datetime().strftime("%Y-%m-%d %H:%M:%S")

    target_match_ids = set(match_ids) if match_ids is not None else set(snapshot.keys())

    with SCORES_PERSIST_LOCK:
        for match_id, payload in snapshot.items():
            if int(match_id) not in target_match_ids:
                continue
            match_status = str(payload.get("match_status") or "").strip().lower()

            if match_status == "nr":
                data_service.clear_points_for_match(int(match_id))
                continue

            player_rows = []
            for player in payload.get("players", []):
                player_id = player.get("player_id")
                if player_id in (None, ""):
                    _log_scores_cache(
                        f"skipping player row without player id for match={match_id}: {player}"
                    )
                    continue
                player_rows.append({
                    "MatchID": int(match_id),
                    "PlayerID": int(player_id),
                    "PlayerName": player.get("name", ""),
                    "Team": player.get("team", ""),
                    "Role": player.get("role", ""),
                    "Points": float(player.get("points", 0) or 0),
                    "LastUpdated": now_str,
                })

            contestant_rows = []
            for contestant in payload.get("contestants", []):
                contestant_user_id = contestant.get("user_id") or contestant.get("id")
                if contestant_user_id in (None, ""):
                    _log_scores_cache(
                        f"skipping contestant row without user id for match={match_id}: {contestant}"
                    )
                    continue
                # Store raw points WITHOUT prediction bonus so that
                # compute_prediction_bonuses reads the correct base value.
                raw_points = float(contestant.get("points", 0) or 0) - float(contestant.get("prediction_bonus", 0) or 0)
                contestant_rows.append({
                    "UserID": int(contestant_user_id),
                    "User": contestant.get("name", ""),
                    "MatchID": int(match_id),
                    "Points": round(raw_points, 2),
                    "LastUpdated": now_str,
                })

            if player_rows:
                data_service.save_player_points(player_rows)
            if contestant_rows:
                data_service.save_contestant_points(contestant_rows)


def _build_match_scores_payload(match_id: int, match_row, registry, players_data, db) -> dict | None:
    match_status = _match_status_value(match_row)
    if match_status == "nr":
        return _empty_match_scores_payload("nr")
    if _is_completed_score_target(match_row):
        return _build_completed_match_scores_payload(match_id, match_row, registry, players_data, db)
    if not _is_live_score_target(match_row):
        return None

    match_obj = None
    html_content = None
    try:
        from backend.main import tournament

        cached_match = tournament.matches.get(str(match_id))
        if cached_match and getattr(cached_match, "players", None):
            match_obj = copy.deepcopy(cached_match)
            html_content = "tournament-cache"
    except Exception:
        match_obj = None
        html_content = None

    if not match_obj:
        match_obj, html_content, _ = _hydrate_match_for_scores(
            match_id,
            match_row,
            registry,
            players_data,
            include_playing_xi=_is_live_window(match_row),
        )

    if not match_obj or not getattr(match_obj, "players", None):
        return None

    if not html_content:
        return None

    pp_rows = db.execute(
        "SELECT * FROM player_points WHERE match_id = ?",
        (match_id,),
    ).fetchall()
    pp_lookup: dict[str, float] = {}
    role_lookup: dict[str, str] = {}
    for row in pp_rows:
        pp_lookup[str(row["player_id"])] = float(row["points"])
        role_lookup[str(row["player_id"])] = row["role"]

    pp_lookup, role_lookup = _fill_missing_player_points(match_obj, registry, pp_lookup, role_lookup)
    owners_by_player = _load_player_owners(db, match_id)
    team1 = clean_team_name(_row_value(match_row, "team1", "Team1", default=""))
    team2 = clean_team_name(_row_value(match_row, "team2", "Team2", default=""))

    selected_rows = []
    if _is_live_window(match_row):
        selected_rows = db.execute(
            """
            SELECT DISTINCT
                p.id,
                p.name,
                p.team,
                p.role
            FROM user_teams ut
            JOIN players p ON p.id = ut.player_id
            WHERE ut.match_id = ?
              AND p.team IN (?, ?)
            ORDER BY p.team, p.role, p.name
            """,
            (match_id, team1, team2),
        ).fetchall()

    players = []
    # Build a live per-player points lookup from calculated values so
    # contestant totals use the same source as the per-player breakdown.
    live_pp_lookup: dict[str, float] = {}
    for p in match_obj.players.values():
        pid_str = str(p.player_id)
        role = role_lookup.get(pid_str) or registry.players.get(p.player_id, {}).get("Role")
        calculated_points = p.calculate_player_points(role) if role else 0
        live_pp_lookup[pid_str] = float(calculated_points)
        players.append({
            "player_id": int(p.player_id),
            "name": p.name,
            "team": p.team,
            "role": role,
            "played": p.played,
            "is_out": p.is_out,
            "runs": p.runs,
            "balls": p.balls,
            "fours": p.fours,
            "sixes": p.sixes,
            "strike_rate": p.strike_rate,
            "overs": p.overs,
            "maidens": p.maidens,
            "runs_conceded": p.runs_conceded,
            "wickets": p.wickets,
            "bowled": p.bowled,
            "lbw": p.lbw,
            "economy": p.economy,
            "dot_balls": p.dot_balls,
            "catches": p.catches,
            "runout_direct": p.runout_direct,
            "stumpings": p.stumpings,
            "runout_indirect": p.runout_indirect,
            "points": calculated_points if calculated_points or p.played else pp_lookup.get(pid_str, 0),
            "breakdown": p.get_points_breakdown() if role else [],
            "owners": owners_by_player.get(int(p.player_id), []),
        })

    if selected_rows:
        append_missing_live_team_players(
            players,
            registry,
            [dict(row) for row in selected_rows],
            owners_by_player,
        )

    players.sort(key=lambda x: x["points"], reverse=True)
    # Use live-calculated per-player points to compute contestant totals for
    # the main scores response so that these totals stay in sync with the
    # team breakdown (which uses the cached snapshot).
    contestants = _compute_contestants_from_player_points(db, match_id, live_pp_lookup)
    contestants = _enrich_contestants_with_predictions(contestants, match_id, match_row)
    contestants = _rank_contestants(contestants)

    return {
        "players": players,
        "contestants": contestants,
        "match_status": match_status or "live",
        "scorecard": _serialize_scorecard(match_obj),
        "snapshot_version": _get_scores_cache_version(),
    }


def _build_completed_match_scores_payload(match_id: int, match_row, registry, players_data, db) -> dict | None:
    match_status = _match_status_value(match_row)
    if match_status == "nr":
        return _empty_match_scores_payload("nr")

    match_obj = _get_completed_match_from_tournament(match_id)
    if not match_obj:
        cached_payload = _get_cached_match_payload(match_id, False)
        if cached_payload:
            match_obj = cached_payload.get("match_obj")
    if not match_obj:
        # Completed matches can lose their in-memory tournament object after restart
        # or a recompute cycle. Fall back to the same scorecard hydration path used
        # for live matches so the team tab still has per-player stat breakdowns.
        match_obj, _, _ = _hydrate_match_for_scores(
            match_id,
            match_row,
            registry,
            players_data,
            include_playing_xi=False,
        )
    team1 = clean_team_name(_row_value(match_row, "team1", "Team1", default=""))
    team2 = clean_team_name(_row_value(match_row, "team2", "Team2", default=""))
    owners_by_player = _load_player_owners(db, match_id)

    pp_rows = db.execute(
        "SELECT * FROM player_points WHERE match_id = ?",
        (match_id,),
    ).fetchall()
    db_pp_lookup: dict[str, float] = {}
    db_role_lookup: dict[str, str] = {}
    for row in pp_rows:
        db_pp_lookup[str(row["player_id"])] = float(row["points"])
        db_role_lookup[str(row["player_id"])] = row["role"]

    # For completed matches, stored player_points are authoritative (they were
    # captured when dot-ball data was still available from the API). Only fall
    # back to re-calculation if no stored points exist.
    has_stored_pp = any(v != 0 for v in db_pp_lookup.values())

    players = []
    if match_obj and getattr(match_obj, "players", None):
        for p in match_obj.players.values():
            pid_str = str(p.player_id)
            role = db_role_lookup.get(pid_str) or registry.players.get(p.player_id, {}).get("Role")
            if role:
                calculated_points = float(p.calculate_player_points(role))
                player_breakdown = p.get_points_breakdown()
            else:
                calculated_points = float(db_pp_lookup.get(pid_str, 0))
                player_breakdown = []
            # Prefer stored points if available — recalculation may lose dot balls
            if has_stored_pp and pid_str in db_pp_lookup:
                points = round(float(db_pp_lookup[pid_str]), 2)
            else:
                points = round(calculated_points, 2)
            players.append({
                "player_id": int(p.player_id),
                "name": p.name,
                "team": p.team or registry.players.get(p.player_id, {}).get("Team", ""),
                "role": role,
                "played": bool(getattr(p, "played", False)),
                "is_out": bool(getattr(p, "is_out", False)),
                "runs": getattr(p, "runs", 0),
                "balls": getattr(p, "balls", 0),
                "fours": getattr(p, "fours", 0),
                "sixes": getattr(p, "sixes", 0),
                "strike_rate": getattr(p, "strike_rate", 0),
                "overs": getattr(p, "overs", 0),
                "maidens": getattr(p, "maidens", 0),
                "runs_conceded": getattr(p, "runs_conceded", 0),
                "wickets": getattr(p, "wickets", 0),
                "bowled": getattr(p, "bowled", 0),
                "lbw": getattr(p, "lbw", 0),
                "economy": getattr(p, "economy", 0),
                "dot_balls": getattr(p, "dot_balls", 0),
                "catches": getattr(p, "catches", 0),
                "runout_direct": getattr(p, "runout_direct", 0),
                "stumpings": getattr(p, "stumpings", 0),
                "runout_indirect": getattr(p, "runout_indirect", 0),
                "points": points,
                "breakdown": player_breakdown,
                "owners": owners_by_player.get(int(p.player_id), []),
            })
    else:
        players_rows = _build_players_rows(players_data, team1, team2)
        for row in players_rows:
            pid = int(row["id"])
            pid_str = str(pid)
            players.append({
                "player_id": pid,
                "name": row["name"],
                "team": row["team"],
                "role": db_role_lookup.get(pid_str) or row["role"],
                "played": pid_str in db_pp_lookup,
                "is_out": False,
                "runs": 0,
                "balls": 0,
                "fours": 0,
                "sixes": 0,
                "strike_rate": 0,
                "overs": 0,
                "maidens": 0,
                "runs_conceded": 0,
                "wickets": 0,
                "bowled": 0,
                "lbw": 0,
                "economy": 0,
                "dot_balls": 0,
                "catches": 0,
                "runout_direct": 0,
                "stumpings": 0,
                "runout_indirect": 0,
                "points": round(float(db_pp_lookup.get(pid_str, 0)), 2),
                "breakdown": [],
                "owners": owners_by_player.get(pid, []),
            })

    players.sort(key=lambda x: x["points"], reverse=True)
    live_points_lookup = {str(player["player_id"]): float(player.get("points", 0)) for player in players}
    contestants = _compute_contestants_from_player_points(db, match_id, live_points_lookup)
    contestants = _enrich_contestants_with_predictions(contestants, match_id, match_row)
    contestants = _rank_contestants(contestants)

    return {
        "players": players,
        "contestants": contestants,
        "match_status": match_status or "completed",
        "scorecard": _serialize_scorecard(match_obj) if match_obj else [],
        "snapshot_version": _get_scores_cache_version(),
    }


def refresh_scores_response_cache_once(match_statuses: set[str] | None = None) -> dict:
    normalized_statuses = {str(status).strip().lower() for status in match_statuses} if match_statuses else None
    if not SCORES_REFRESH_LOCK.acquire(blocking=False):
        _log_scores_cache("refresh already running, skipping")
        snapshot = SCORES_RESPONSE_CACHE.read() or {}
        return {
            "eligible": 0,
            "refreshed": 0,
            "errors": 0,
            "matches": len(snapshot),
        }

    try:
        with acquire_cache_locks("scraper_playing_xi", "scores_match_data", "scores_response", "leaderboard_response"):
            db = get_db()
            registry, players_data = _build_registry(db)
            matches_data = data_service.get_cached_data("matches")
            snapshot: dict[int, dict] = SCORES_RESPONSE_CACHE.read() or {}
            eligible = 0
            refreshed = 0
            errors = 0
            updated_match_ids: set[int] = set()

            _log_scores_cache(
                f"refresh tick start matches={len(matches_data)} "
                f"filter={sorted(normalized_statuses) if normalized_statuses else 'all'}"
            )

            for match_row in matches_data:
                match_id = int(match_row["MatchID"])
                status = _match_status_value(match_row)
                if normalized_statuses and status not in normalized_statuses:
                    continue
                try:
                    if status == "future":
                        continue
                    if status == "nr":
                        if snapshot.get(match_id, {}).get("match_status") == "nr":
                            continue
                        snapshot[match_id] = _empty_match_scores_payload("nr")
                        updated_match_ids.add(match_id)
                        refreshed += 1
                        continue
                    if status == "completed":
                        eligible += 1
                        existing_payload = snapshot.get(match_id)
                        if existing_payload and existing_payload.get("match_status") == "nr":
                            continue
                        # Always rebuild when transitioning from live to completed
                        # so prediction bonuses are computed against final stored
                        # points, not transient live-calculated points.
                        if existing_payload and existing_payload.get("match_status") == "completed" and existing_payload.get("_completed_final"):
                            continue
                        payload = _build_completed_match_scores_payload(match_id, match_row, registry, players_data, db)
                        if payload is not None:
                            payload["_completed_final"] = True
                            snapshot[match_id] = payload
                            updated_match_ids.add(match_id)
                            refreshed += 1
                        continue
                    if status == "live":
                        eligible += 1
                        payload = _build_match_scores_payload(match_id, match_row, registry, players_data, db)
                        if payload is not None:
                            snapshot[match_id] = payload
                            updated_match_ids.add(match_id)
                            refreshed += 1
                        else:
                            _log_scores_cache(f"match {match_id} live -> payload unavailable")
                except Exception as exc:
                    errors += 1
                    _log_scores_cache(f"match {match_id} refresh error: {exc}")
                    traceback.print_exc()

            _store_scores_response_cache(snapshot)
            if updated_match_ids:
                try:
                    _persist_scores_snapshot_to_db(snapshot, updated_match_ids)
                except Exception as exc:
                    _log_scores_cache(f"targeted persistence failed: {exc}")
                    traceback.print_exc()
                try:
                    from backend.routes.leaderboard import refresh_leaderboard_cache_once

                    summary = refresh_leaderboard_cache_once()
                    _log_scores_cache(
                        f"leaderboard cache refreshed leaderboard={summary['leaderboard']} points_table={summary['points_table']}"
                    )
                except Exception as exc:
                    _log_scores_cache(f"leaderboard cache refresh failed: {exc}")
            _log_scores_cache(
                f"refresh tick complete eligible={eligible} refreshed={refreshed} errors={errors} cached={len(snapshot)}"
            )
            return {
                "eligible": eligible,
                "refreshed": refreshed,
                "errors": errors,
                "matches": len(matches_data),
            }
    finally:
        SCORES_REFRESH_LOCK.release()


def start_scores_cache_scheduler():
    global SCORES_CACHE_SCHEDULER_STARTED
    with SCORES_CACHE_SCHEDULER_LOCK:
        if SCORES_CACHE_SCHEDULER_STARTED:
            _log_scores_cache("scheduler already started, skipping")
            return
        SCORES_CACHE_SCHEDULER_STARTED = True
        _log_scores_cache("scheduler starting")

    def run():
        while True:
            try:
                summary = refresh_scores_response_cache_once()
                sleep_seconds = 15 if summary["eligible"] else 60
                _log_scores_cache(
                    f"scheduler tick done eligible={summary['eligible']} refreshed={summary['refreshed']} errors={summary['errors']} sleep={sleep_seconds}s"
                )
            except Exception as exc:
                _log_scores_cache(f"scheduler error: {exc}")
                traceback.print_exc()
                sleep_seconds = 30
                _log_scores_cache(f"scheduler retry sleep={sleep_seconds}s")
            time.sleep(sleep_seconds)

    thread = threading.Thread(target=run, daemon=True, name="scores-cache-scheduler")
    thread.start()
    _log_scores_cache("scheduler thread started")


def prewarm_non_live_match_payloads():
    db = get_db()
    registry, players_data = _build_registry(db)
    matches_data = data_service.get_cached_data("matches")

    warmed = 0
    for match_row in matches_data:
        status = _match_status_value(match_row)
        if status not in {"completed", "nr", "future"}:
            continue

        match_id = int(match_row["MatchID"])
        try:
            payload = _hydrate_match_for_scores(
                match_id,
                match_row,
                registry,
                players_data,
                include_playing_xi=False,
            )
            if payload:
                warmed += 1
        except Exception as exc:
            _log_scores_cache(f"prewarm failed match={match_id}: {exc}")
            traceback.print_exc()

    return {"warmed": warmed, "matches": len(matches_data)}


def _compute_contestants_from_player_points(db, match_id: int, pp_lookup: dict[str, float] | None = None) -> list[dict]:
    team_rows = db.execute(
        """
        SELECT
            u.id AS user_id,
            u.name AS user_name,
            ut.player_id,
            ut.is_captain,
            ut.is_vice_captain
        FROM user_teams ut
        JOIN users u ON u.id = ut.user_id
        WHERE ut.match_id = ?
          AND u.is_active = 1
        ORDER BY u.id
        """,
        (match_id,),
    ).fetchall()

    totals: dict[int, dict] = {}
    for row in team_rows:
        user_id = row["user_id"]
        entry = totals.setdefault(
            user_id,
            {"id": user_id, "name": row["user_name"], "points": 0.0},
        )

        base_points = float((pp_lookup or {}).get(str(row["player_id"]), 0))
        if row["is_captain"]:
            base_points *= 2.0
        elif row["is_vice_captain"]:
            base_points *= 1.5

        entry["points"] += base_points

    contestants = list(totals.values())
    for contestant in contestants:
        contestant["points"] = round(contestant["points"], 2)
    contestants.sort(key=lambda item: (-item["points"], item["name"]))
    return contestants


def _enrich_contestants_with_predictions(contestants: list[dict], match_id: int, match_row) -> list[dict]:
    """Add prediction_bonus, predicted_points, and prediction_label to each contestant.

    Bonus points are added to the contestant's total so that rankings and
    medals reflect prediction bonuses once the match is completed.
    """
    try:
        predictions = data_service.get_match_predictions(match_id)
        bonuses = data_service.compute_prediction_bonuses(match_id)
    except Exception:
        return contestants

    apply_bonus = _is_completed_score_target(match_row)

    def _prediction_tier_for_diff(diff: float) -> tuple[str | None, float]:
        for tier in data_service.PREDICTION_BONUS_TIERS:
            if diff <= float(tier["max_diff"]):
                return str(tier["label"]), float(tier["bonus"])
        return None, 0.0

    for contestant in contestants:
        uid = contestant.get("user_id") or contestant.get("id")
        if uid is None:
            continue
        uid = int(uid)
        predicted_points = predictions.get(uid)
        contestant["predicted_points"] = predicted_points
        actual_points = float(contestant.get("points", 0) or 0)
        if predicted_points is not None:
            tier_label, tier_bonus = _prediction_tier_for_diff(abs(float(predicted_points) - actual_points))
            contestant["prediction_tier_label"] = tier_label
            contestant["prediction_tier_bonus"] = tier_bonus if tier_label else 0
        else:
            contestant["prediction_tier_label"] = None
            contestant["prediction_tier_bonus"] = 0

        bonus_info = bonuses.get(uid)
        if apply_bonus and bonus_info:
            contestant["prediction_bonus"] = bonus_info["bonus"]
            contestant["prediction_label"] = bonus_info["label"]
            contestant["points"] = round(float(contestant.get("points", 0)) + bonus_info["bonus"], 2)
        else:
            contestant["prediction_bonus"] = 0
            contestant["prediction_label"] = None

    # Re-sort so that ranking reflects updated totals
    contestants.sort(key=lambda item: (-item["points"], item["name"]))
    return contestants


def _rank_contestants(contestants: list[dict]) -> list[dict]:
    ranked: list[dict] = []
    previous_points = None
    current_rank = 0

    for index, contestant in enumerate(contestants, start=1):
        points = round(float(contestant.get("points", 0)), 2)
        if previous_points is None or points != previous_points:
            current_rank = index
            previous_points = points
        ranked.append({**contestant, "rank": current_rank, "points": points})

    return ranked


def _load_player_owners(db, match_id: int) -> dict[int, list[dict]]:
    rows = db.execute(
        """
        SELECT
            ut.player_id,
            u.id AS user_id,
            u.name AS user_name,
            ut.is_captain,
            ut.is_vice_captain
        FROM user_teams ut
        JOIN users u ON u.id = ut.user_id
        WHERE ut.match_id = ?
          AND u.is_active = 1
        ORDER BY ut.player_id, u.name
        """,
        (match_id,),
    ).fetchall()

    owners_by_player: dict[int, list[dict]] = {}
    for row in rows:
        owners_by_player.setdefault(int(row["player_id"]), []).append({
            "id": int(row["user_id"]),
            "name": row["user_name"],
            "tag": "C" if row["is_captain"] else "VC" if row["is_vice_captain"] else "",
        })

    return owners_by_player


def _merge_contestant_points(
    db,
    match_id: int,
    stored_contestants: list[dict],
    pp_lookup: dict[str, float] | None = None,
) -> list[dict]:
    computed_contestants = _compute_contestants_from_player_points(db, match_id, pp_lookup)
    if not computed_contestants:
        return stored_contestants

    merged_by_user = {
        contestant["id"]: {
            "id": contestant["id"],
            "name": contestant["name"],
            "points": round(float(contestant.get("points", 0)), 2),
        }
        for contestant in computed_contestants
    }

    has_nonzero_player_points = any(float(points) != 0 for points in (pp_lookup or {}).values())
    all_stored_zero = bool(stored_contestants) and all(float(contestant.get("points", 0)) == 0 for contestant in stored_contestants)

    for contestant in stored_contestants:
        user_id = contestant["id"]
        stored_points = round(float(contestant.get("points", 0)), 2)

        if user_id not in merged_by_user:
            merged_by_user[user_id] = {
                "id": contestant["id"],
                "name": contestant["name"],
                "points": stored_points,
            }
            continue

        if not has_nonzero_player_points:
            merged_by_user[user_id]["points"] = stored_points
        elif not all_stored_zero and stored_points != 0:
            merged_by_user[user_id]["points"] = stored_points

    merged = list(merged_by_user.values())
    merged.sort(key=lambda item: (-item["points"], item["name"]))
    return merged


def _fill_missing_player_points(match_obj, registry, pp_lookup: dict, role_lookup: dict) -> tuple[dict, dict]:
    if not match_obj:
        return pp_lookup, role_lookup

    for pid, player in match_obj.players.items():
        pid_str = str(pid)
        role = role_lookup.get(pid_str) or registry.players.get(pid, {}).get("Role")
        if role and pid_str not in role_lookup:
            role_lookup[pid_str] = role
        if role and pid_str not in pp_lookup:
            pp_lookup[pid_str] = float(player.calculate_player_points(role))

    return pp_lookup, role_lookup


def _serialize_scorecard(match_obj) -> list[dict]:
    return copy.deepcopy(getattr(match_obj, "scorecard", []) or [])


def _build_registry(db):
    """Build a PlayerRegistry from the players table."""
    players_data = data_service.get_cached_data("players")
    return PlayerRegistry(players_data), players_data


def _backup_map_for_user(match_id: int, user_id: int) -> dict[int, dict]:
    return data_service.get_active_backup_replacements(match_id, user_id)


def _backup_replacements_for_user(match_id: int, user_id: int) -> list[dict]:
    backups = data_service.get_user_backups(user_id, match_id) or []
    replacements: list[dict] = []
    for row in backups:
        replaced_id = row.get("replaced_player_id")
        backup_id = row.get("backup_player_id")
        if replaced_id in (None, ""):
            continue
        replacements.append({
            "backup_player_id": int(backup_id),
            "backup_player_name": row.get("backup_player_name", ""),
            "backup_team": row.get("backup_team", ""),
            "backup_role": row.get("backup_role", ""),
            "replaced_player_id": int(replaced_id),
            "replaced_player_name": row.get("replaced_player_name", ""),
        })
    return replacements


def _build_players_rows(players_data, team1=None, team2=None):
    rows = []
    for row in players_data:
        if team1 and team2 and row["Team"] not in (team1, team2):
            continue
        rows.append({
            "id": row["PlayerID"],
            "name": row["Name"],
            "team": row["Team"],
            "role": row["Role"],
            "aliases": row["Aliases"],
        })
    return rows


def _is_live_window(match_row) -> bool:
    if str(_row_value(match_row, "status", "Status", default="") or "").strip().lower() in {"completed", "nr"}:
        return False

    try:
        match_datetime = datetime.strptime(
            f"{_row_value(match_row, 'match_date', 'Date')} {_row_value(match_row, 'match_time', 'Time')}", "%Y-%m-%d %H:%M"
        )
        match_datetime = IST.localize(match_datetime)
    except Exception:
        return False

    now = get_current_datetime()
    toss_time = str(_row_value(match_row, "toss_time", "TossTime", default="") or "").strip()
    if toss_time:
        try:
            window_start = IST.localize(datetime.strptime(f"{_row_value(match_row, 'match_date', 'Date')} {toss_time}", "%Y-%m-%d %H:%M"))
        except Exception:
            try:
                window_start = IST.localize(datetime.strptime(toss_time, "%Y-%m-%d %H:%M"))
            except Exception:
                window_start = match_datetime - timedelta(minutes=30)
    else:
        window_start = match_datetime - timedelta(minutes=30)
    return window_start <= now < match_datetime + timedelta(hours=5)


def _is_completed_match(match_row) -> bool:
    if str(_row_value(match_row, "status", "Status", default="") or "").strip().lower() in {"completed", "nr"}:
        return True

    try:
        match_datetime = datetime.strptime(
            f"{_row_value(match_row, 'match_date', 'Date')} {_row_value(match_row, 'match_time', 'Time')}", "%Y-%m-%d %H:%M"
        )
        match_datetime = IST.localize(match_datetime)
    except Exception:
        return False

    return get_current_datetime() >= match_datetime + timedelta(hours=5)


def _get_completed_match_from_tournament(match_id: int):
    try:
        from backend.main import tournament
    except Exception:
        return None

    match_obj = tournament.matches.get(str(match_id))
    if not match_obj or not getattr(match_obj, "players", None):
        return None

    return copy.deepcopy(match_obj)


def _get_cached_match_payload(match_id: int, include_playing_xi: bool = False) -> dict | None:
    cache_key = (int(match_id), include_playing_xi)
    with MATCH_DATA_CACHE_LOCK:
        cached = MATCH_DATA_CACHE.get(cache_key)
        return copy.deepcopy(cached) if cached is not None else None


def _log_active_player_count(match_id: int, match_obj):
    active_players = [player for player in match_obj.players.values() if getattr(player, "played", False)]
    active_count = len(active_players)
    if active_count < 22 or active_count > 24:
        print(f"[ALERT] Match {match_id}: active scoring player count is {active_count} (expected 22 to 24)")


def _count_dot_ball_players(match_obj) -> tuple[int, int]:
    players = getattr(match_obj, "players", {}) or {}
    dot_ball_players = 0
    dot_ball_total = 0
    for player in players.values():
        dot_balls = int(getattr(player, "dot_balls", 0) or 0)
        if dot_balls > 0:
            dot_ball_players += 1
            dot_ball_total += dot_balls
    return dot_ball_players, dot_ball_total


def _build_live_match_payload(match_id: int, match_row, registry, players_data, include_playing_xi=False, force_refresh_scorecard: bool = False):
    cache_key = (match_id, include_playing_xi)

    team1 = clean_team_name(_row_value(match_row, "team1", "Team1", default=""))
    team2 = clean_team_name(_row_value(match_row, "team2", "Team2", default=""))
    match_date = _row_value(match_row, "match_date", "Date", default="")
    match_time = _row_value(match_row, "match_time", "Time", default="")
    toss_time = _row_value(match_row, "toss_time", "TossTime", default=None)

    match_obj = Match(
        str(match_id),
        team1,
        team2,
        registry,
        match_date,
    )

    players_rows = _build_players_rows(players_data, team1, team2)
    playing_xi = {"announced": False, "url": "", "player_ids": []}
    # Always fetch and apply playing XI so that all 22 players are marked as "played"
    # This ensures bowlers who haven't bowled yet still get 4 base points
    playing_xi = refresh_playing_xi_cache(
        match_id,
        team1,
        team2,
        players_rows,
        match_date,
        match_time,
        toss_time,
    )
    playing_ids = playing_xi.get("player_ids", [])
    if playing_ids:
        match_obj.apply_playing_xi(playing_ids)

    html_content = fetch_cricbuzz_scorecard_html(match_id, team1, team2)
    if html_content:
        match_obj.parse_cricbuzz_scorecard_html(html_content, reset_players=False)

    espn_html = fetch_scorecard_html(match_id, team1, team2, force_refresh=force_refresh_scorecard)
    if espn_html:
        soup = BeautifulSoup(espn_html, "html.parser")
        match_obj.parse_espn_bowling_dot_balls(soup, get_last_fetched_espn_scorecard_url(match_id))
        if include_playing_xi:
            _log_active_player_count(match_id, match_obj)
        dot_ball_players, dot_ball_total = _count_dot_ball_players(match_obj)
        print(
            f"[scores-cache] ESPN dot-ball parse match={match_id} "
            f"url={get_last_fetched_espn_scorecard_url(match_id) or '<unknown>'} "
            f"force_refresh={force_refresh_scorecard} "
            f"dot_ball_players={dot_ball_players} dot_balls_total={dot_ball_total}"
        )

    payload = {
        "match_obj": match_obj,
        "html_content": html_content,
        "playing_xi": playing_xi,
        "fetched_at": time.time(),
        "match_status": _match_status_value(match_row),
    }
    with MATCH_DATA_CACHE_LOCK:
        MATCH_DATA_CACHE[cache_key] = payload
        MATCH_DATA_REFRESH_INFLIGHT.discard(cache_key)
    return payload


def _refresh_live_match_payload_async(match_id: int, match_row, registry, players_data, include_playing_xi=False, force_refresh_scorecard: bool = False):
    cache_key = (match_id, include_playing_xi)

    with MATCH_DATA_CACHE_LOCK:
        if cache_key in MATCH_DATA_REFRESH_INFLIGHT:
            return
        MATCH_DATA_REFRESH_INFLIGHT.add(cache_key)

    def _run():
        try:
            _build_live_match_payload(
                match_id,
                match_row,
                registry,
                players_data,
                include_playing_xi=include_playing_xi,
                force_refresh_scorecard=force_refresh_scorecard,
            )
        except Exception as exc:
            print(f"[scores-cache] async refresh failed for match {match_id}: {exc}")
            with MATCH_DATA_CACHE_LOCK:
                MATCH_DATA_REFRESH_INFLIGHT.discard(cache_key)

    threading.Thread(target=_run, daemon=True).start()


def _hydrate_match_from_live_data(match_id: int, match_row, registry, players_data, include_playing_xi=False):
    cache_key = (match_id, include_playing_xi)
    now_ts = time.time()
    current_status = _match_status_value(match_row)

    with MATCH_DATA_CACHE_LOCK:
        cached = MATCH_DATA_CACHE.get(cache_key)

    if cached:
        cached_status = cached.get("match_status")
        status_changed = cached_status != current_status
        if (not include_playing_xi) and not status_changed:
            return cached["match_obj"], cached["html_content"], cached["playing_xi"]
        if (not status_changed) and (now_ts - cached["fetched_at"] < LIVE_MATCH_CACHE_TTL_SECONDS):
            return cached["match_obj"], cached["html_content"], cached["playing_xi"]

        if status_changed:
            print(
                f"[scores-cache] live transition match={match_id} "
                f"stored_status={cached_status or 'unknown'} resolved_status={current_status} "
                f"force_refresh_scorecard=True"
            )
            payload = _build_live_match_payload(
                match_id,
                match_row,
                registry,
                players_data,
                include_playing_xi=include_playing_xi,
                force_refresh_scorecard=True,
            )
            return payload["match_obj"], payload["html_content"], payload["playing_xi"]

        # Stale-while-refresh: keep serving previous snapshot while refresh runs in background.
        _refresh_live_match_payload_async(
            match_id,
            match_row,
            registry,
            players_data,
            include_playing_xi=include_playing_xi,
            force_refresh_scorecard=False,
        )
        return cached["match_obj"], cached["html_content"], cached["playing_xi"]

    payload = _build_live_match_payload(
        match_id,
        match_row,
        registry,
        players_data,
        include_playing_xi=include_playing_xi,
        force_refresh_scorecard=True,
    )
    dot_ball_players, dot_ball_total = _count_dot_ball_players(payload["match_obj"])
    print(
        f"[scores-cache] initial live hydrate match={match_id} "
        f"status={current_status} espn_url={get_last_fetched_espn_scorecard_url(match_id) or '<unknown>'} "
        f"dot_ball_players={dot_ball_players} dot_balls_total={dot_ball_total}"
    )
    return payload["match_obj"], payload["html_content"], payload["playing_xi"]


def _hydrate_match_for_scores(match_id: int, match_row, registry, players_data, include_playing_xi=False):
    if _is_completed_match(match_row):
        cached_match = _get_completed_match_from_tournament(match_id)
        if cached_match:
            return cached_match, "tournament-cache", {"announced": False, "url": "", "player_ids": []}

    return _hydrate_match_from_live_data(
        match_id,
        match_row,
        registry,
        players_data,
        include_playing_xi=include_playing_xi,
    )


@router.get("/{match_id}")
async def match_scores(
    match_id: int,
    user: dict = Depends(get_current_user),
):
    db = get_db()
    registry, players_data = _build_registry(db)

    # Get match info
    match_row = db.execute(
        "SELECT * FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    if not match_row:
        raise HTTPException(status_code=404, detail="Match not found")

    match_status = _match_status_value(match_row)

    if match_status == "nr":
        return _empty_match_scores_payload("nr")

    cached_payload = _ensure_score_payload_cached(match_id, match_row)
    if cached_payload is None:
        _log_scores_cache(
            f"cache miss match={match_id} status={match_status or 'unknown'} live={SCORES_RESPONSE_CACHE.has_live()}"
        )
        return _empty_match_scores_payload(match_status)

    return cached_payload


@router.get("/{match_id}/my-team")
async def my_team_for_match(
    match_id: int,
    user: dict = Depends(get_current_user),
):
    db = get_db()

    rows = db.execute(
        """
        SELECT p.name
        FROM user_teams ut
        JOIN players p ON p.id = ut.player_id
        WHERE ut.user_id = ? AND ut.match_id = ?
        """,
        (user["id"], match_id),
    ).fetchall()

    return [row["name"] for row in rows]


@router.get("/{match_id}/team-breakdown")
async def team_breakdown(
    match_id: int,
    user_id: int = None,
    snapshot_version: int | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Get detailed breakdown of a user's team points for a match."""
    db = get_db()
    target_user_id = user_id or user["id"]

    # Get user's team
    team_rows = db.execute(
        """
        SELECT ut.player_id, ut.is_captain, ut.is_vice_captain,
               p.name, p.team, p.role
        FROM user_teams ut
        JOIN players p ON p.id = ut.player_id
        WHERE ut.user_id = ? AND ut.match_id = ?
        """,
        (target_user_id, match_id),
    ).fetchall()

    if not team_rows:
        return {"error": "No team found for this match"}

    match_row, cached_payload, pp_lookup, role_lookup = _load_match_and_points(db, match_id)
    if not match_row:
        return {"error": "Match not found"}
    if not cached_payload and str(match_row.get("status") or "").strip().lower() != "nr":
        _log_scores_cache(f"team-breakdown cache miss match={match_id}")
        raise HTTPException(status_code=503, detail="Score cache not ready")

    player_lookup = {
        int(player["player_id"]): player
        for player in (cached_payload.get("players", []) if cached_payload else [])
        if player.get("player_id") is not None
    }

    target_user = db.execute("SELECT name FROM users WHERE id = ?", (target_user_id,)).fetchone()

    breakdown = []
    total = 0.0
    backup_map = _backup_map_for_user(match_id, target_user_id)
    backup_replacements = _backup_replacements_for_user(match_id, target_user_id)

    for row in team_rows:
        pid = row["player_id"]
        player_payload = player_lookup.get(int(pid), {})
        base_pts = pp_lookup.get(str(pid), 0)
        is_captain = bool(row["is_captain"])
        is_vc = bool(row["is_vice_captain"])

        if is_captain:
            multiplier = 2.0
            tag = "C"
        elif is_vc:
            multiplier = 1.5
            tag = "VC"
        else:
            multiplier = 1.0
            tag = ""

        adjusted = round(base_pts * multiplier, 2)
        total += adjusted

        # Get per-category breakdown
        player_breakdown = list(player_payload.get("breakdown", []))

        breakdown.append({
            "name": row["name"],
            "team": row["team"],
            "role": row["role"],
            "base_points": base_pts,
            "multiplier": multiplier,
            "tag": tag,
            "adjusted_points": adjusted,
            "is_backup": pid in backup_map,
            "replaced_player_id": backup_map.get(pid, {}).get("replaced_player_id"),
            "breakdown": player_breakdown,
        })

    breakdown.sort(key=lambda x: x["adjusted_points"], reverse=True)

    return {
        "user_name": target_user["name"] if target_user else "Unknown",
        "total": round(total, 2),
        "players": breakdown,
        "backup_replacements": backup_replacements,
    }


def _load_match_and_points(db, match_id):
    """Shared helper: read the cached score snapshot and derive point lookups."""
    match_row = db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match_row:
        return None, None, {}, {}

    cached_payload = _ensure_score_payload_cached(match_id, match_row)
    if not cached_payload:
        return match_row, None, {}, {}

    pp_rows = db.execute(
        "SELECT player_id, points, role FROM player_points WHERE match_id = ?",
        (match_id,),
    ).fetchall()
    db_pp_lookup = {
        str(row["player_id"]): float(row["points"])
        for row in pp_rows
    }
    db_role_lookup = {
        str(row["player_id"]): row["role"]
        for row in pp_rows
        if row["role"]
    }
    cached_pp_lookup = {
        str(player["player_id"]): float(player.get("points", 0))
        for player in cached_payload.get("players", [])
        if player.get("player_id") is not None
    }
    cached_role_lookup = {
        str(player["player_id"]): player.get("role")
        for player in cached_payload.get("players", [])
        if player.get("player_id") is not None and player.get("role")
    }

    match_status = _match_status_value(match_row)
    if match_status == "completed":
        pp_lookup = cached_pp_lookup or db_pp_lookup
        role_lookup = cached_role_lookup or db_role_lookup
    elif match_status == "live":
        pp_lookup = cached_pp_lookup
        role_lookup = cached_role_lookup or db_role_lookup
        if not pp_lookup:
            # Live views should never fall back to stale DB points. If the live
            # snapshot is not populated yet, let the caller treat it as not ready.
            return match_row, cached_payload, {}, {}
    else:
        pp_lookup = db_pp_lookup or cached_pp_lookup
        role_lookup = db_role_lookup or cached_role_lookup

    return match_row, cached_payload, pp_lookup, role_lookup


def _build_team_snapshot(db, user_id, match_id, match_obj, pp_lookup, role_lookup):
    """Build a snapshot of a user's team with points and multipliers."""
    rows = db.execute(
        """
        SELECT ut.player_id, ut.is_captain, ut.is_vice_captain, p.name, p.team, p.role
        FROM user_teams ut
        JOIN players p ON p.id = ut.player_id
        WHERE ut.user_id = ? AND ut.match_id = ?
        """,
        (user_id, match_id),
    ).fetchall()

    entries = {}
    total = 0.0
    backup_map = _backup_map_for_user(match_id, user_id)

    for row in rows:
        pid = row["player_id"]
        pid_str = str(pid)
        base_points = pp_lookup.get(pid_str, 0)

        is_captain = bool(row["is_captain"])
        is_vice_captain = bool(row["is_vice_captain"])

        if is_captain:
            multiplier = 2.0
            tag = "C"
        elif is_vice_captain:
            multiplier = 1.5
            tag = "VC"
        else:
            multiplier = 1.0
            tag = ""

        adjusted = round(base_points * multiplier, 2)
        total += adjusted

        entries[pid] = {
            "player_id": pid,
            "name": row["name"],
            "team": row["team"],
            "role": role_lookup.get(pid_str, row["role"]),
            "base_points": base_points,
            "multiplier": multiplier,
            "tag": tag,
            "adjusted_points": adjusted,
            "is_backup": pid in backup_map,
            "replaced_player_id": backup_map.get(pid, {}).get("replaced_player_id"),
        }

    return entries, round(total, 2)


@router.get("/{match_id}/team-diff")
async def team_diff(
    match_id: int,
    other_user_id: int,
    snapshot_version: int | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    db = get_db()

    if user["id"] == other_user_id:
        return {"error": "Select another contestant to compare"}

    match_row, cached_payload, pp_lookup, role_lookup = _load_match_and_points(db, match_id)
    if not match_row:
        return {"error": "Match not found"}
    if not cached_payload and str(match_row.get("status") or "").strip().lower() != "nr":
        _log_scores_cache(f"team-diff cache miss match={match_id}")
        raise HTTPException(status_code=503, detail="Score cache not ready")

    # Get other user's name
    other_user = db.execute("SELECT * FROM users WHERE id = ?", (other_user_id,)).fetchone()
    if not other_user:
        return {"error": "Contestant not found"}
    if not other_user["is_active"]:
        return {"error": "Contestant is inactive"}

    my_entries, my_total = _build_team_snapshot(db, user["id"], match_id, cached_payload, pp_lookup, role_lookup)
    other_entries, other_total = _build_team_snapshot(db, other_user_id, match_id, cached_payload, pp_lookup, role_lookup)

    if not my_entries:
        return {"error": "You haven't picked a team for this match"}
    if not other_entries:
        return {"error": f"{other_user['name']} hasn't picked a team for this match"}

    my_ids = set(my_entries.keys())
    other_ids = set(other_entries.keys())

    # Players only in my team vs only in their team
    my_only = sorted(
        [my_entries[pid] for pid in my_ids - other_ids],
        key=lambda x: x["adjusted_points"], reverse=True,
    )
    other_only = sorted(
        [other_entries[pid] for pid in other_ids - my_ids],
        key=lambda x: x["adjusted_points"], reverse=True,
    )

    different_players_diff = round(
        sum(e["adjusted_points"] for e in my_only) - sum(e["adjusted_points"] for e in other_only), 2
    )

    # Common players with different roles (C/VC difference)
    common_role_diff = []
    common_same = []
    role_diff_total = 0.0

    for pid in sorted(my_ids & other_ids, key=lambda p: my_entries[p]["adjusted_points"], reverse=True):
        left = my_entries[pid]
        right = other_entries[pid]
        row = {"left": left, "right": right}

        if left["tag"] != right["tag"] or left["multiplier"] != right["multiplier"]:
            diff_points = round(left["adjusted_points"] - right["adjusted_points"], 2)
            row["diff_points"] = diff_points
            role_diff_total += diff_points
            common_role_diff.append(row)
        else:
            common_same.append(row)

    # Pair different players side by side
    max_len = max(len(my_only), len(other_only), 1)
    different_players = [
        {
            "left": my_only[i] if i < len(my_only) else None,
            "right": other_only[i] if i < len(other_only) else None,
        }
        for i in range(max_len)
    ]

    return {
        "current_user": user["name"],
        "other_user": other_user["name"],
        "my_total": my_total,
        "other_total": other_total,
        "total_diff": round(my_total - other_total, 2),
        "different_players_diff": different_players_diff,
        "different_players": different_players,
        "common_role_diff_total": round(role_diff_total, 2),
        "common_role_diff": common_role_diff,
        "common_players": common_same,
    }


@router.get("/{match_id}/contestants")
async def match_contestants(
    match_id: int,
    snapshot_version: int | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """List contestants who picked teams for this match (for the diff dropdown)."""
    db = get_db()
    match_row, cached_payload, pp_lookup, role_lookup = _load_match_and_points(db, match_id)
    if not match_row:
        return []
    if not cached_payload and str(match_row.get("status") or "").strip().lower() != "nr":
        _log_scores_cache(f"contestants cache miss match={match_id}")
        raise HTTPException(status_code=503, detail="Score cache not ready")

    contestants = _rank_contestants(_compute_contestants_from_player_points(db, match_id, pp_lookup))
    return [
        {
            "id": contestant["id"],
            "name": contestant["name"],
            "points": contestant["points"],
            "rank": contestant["rank"],
        }
        for contestant in contestants
    ]
