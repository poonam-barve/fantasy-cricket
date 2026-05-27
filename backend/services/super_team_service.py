import copy
import threading
from collections import defaultdict
from datetime import datetime
import math

from fastapi import HTTPException

from backend.config import IST, get_current_datetime
from backend.database import get_db
from backend.services import data_service
from backend.services.match_status import resolve_match_status_from_row

SUPER_MATCH_IDS = [71, 72, 73, 74]
QUALIFIER_MATCH_IDS = [71, 72]
SUPER_TEAM_BONUSES_BY_RANK = {1: 1000, 2: 600, 3: 300}
SUPER_TEAM_SIZE = 12
SUPER_TEAM_MIN_BOWLERS = 4
SUPER_TEAM_CAPTAIN_MULTIPLIER = 1.5
SUPER_TEAM_VICE_CAPTAIN_MULTIPLIER = 1.25
SUPER_TEAM_REQUIRED_ROLES = ["Wicketkeeper", "Batter", "AllRounder"]
SUPER_TEAM_SNAPSHOT_PHASES = ("original", "edited", "final")
SUPER_TEAM_PHASE1_BAT_PENALTY = 80
SUPER_TEAM_PHASE1_BOWL_PENALTY = 60
SUPER_TEAM_PHASE2_BAT_PENALTY = 100
SUPER_TEAM_PHASE2_BOWL_PENALTY = 80

SUPER_TEAM_CACHE_LOCK = threading.Lock()
SUPER_TEAM_CACHE: dict[int, dict] = {}
SUPER_STANDINGS_CACHE: list[dict] = []
SUPER_DETAILS_CACHE: dict = {"user_breakdowns": [], "player_points": []}
SUPER_STANDINGS_META: dict = {}
SUPER_TEAM_CACHE_LOADED = False
SUPER_PLAYER_POOL_CACHE: list[dict] = []
SUPER_PLAYER_POOL_KEY: tuple[str, ...] | None = None


def _now_str() -> str:
    return get_current_datetime().strftime("%Y-%m-%d %H:%M:%S")


def _is_tbd(team: str | None) -> bool:
    value = str(team or "").strip().lower()
    return not value or value in {"tbd", "tba", "to be decided", "qualifier", "winner", "loser"}


def _match_lookup() -> dict[int, dict]:
    return {int(row["MatchID"]): row for row in data_service.get_cached_data("matches")}


def _player_lookup() -> dict[int, dict]:
    return {int(row["PlayerID"]): row for row in data_service.get_cached_data("players")}


def _status_for_match(row: dict | None) -> str:
    if not row:
        return "missing"
    try:
        status, _locked = resolve_match_status_from_row({
            "id": row["MatchID"],
            "team1": row["Team1"],
            "team2": row["Team2"],
            "match_date": row["Date"],
            "match_time": row["Time"],
            "status": row.get("Status"),
            "toss_time": row.get("TossTime"),
        })
        return status
    except Exception:
        return str(row.get("Status") or "").strip().lower()


def _match_cutoff_reached(match_row: dict | None, *, use_toss_time: bool = True) -> bool:
    if not match_row:
        return True
    try:
        cutoff_time = match_row.get("TossTime") if use_toss_time and match_row.get("TossTime") else match_row["Time"]
        match_datetime = datetime.strptime(f"{match_row['Date']} {cutoff_time}", "%Y-%m-%d %H:%M")
        match_datetime = IST.localize(match_datetime)
    except Exception:
        return True
    return get_current_datetime() >= match_datetime


def _is_locked(match71: dict | None) -> bool:
    return _match_cutoff_reached(match71, use_toss_time=True)


def _substitution_window_open(matches: dict[int, dict]) -> bool:
    return (
        _status_for_match(matches.get(72)) == "completed"
        and not _match_cutoff_reached(matches.get(73), use_toss_time=True)
    )


def _second_substitution_window_open(matches: dict[int, dict]) -> bool:
    return (
        _status_for_match(matches.get(73)) == "completed"
        and not _match_cutoff_reached(matches.get(74), use_toss_time=True)
    )


def _first_substitution_finalized(matches: dict[int, dict]) -> bool:
    return _match_cutoff_reached(matches.get(73), use_toss_time=True)


def _second_substitution_finalized(matches: dict[int, dict]) -> bool:
    return _match_cutoff_reached(matches.get(74), use_toss_time=True)


def _active_substitution_phase(matches: dict[int, dict]) -> int:
    if _second_substitution_window_open(matches):
        return 2
    if _substitution_window_open(matches):
        return 1
    return 0


def _substitution_team_list(matches: dict[int, dict]) -> list[str]:
    teams: list[str] = []
    for match_id in (73, 74):
        row = matches.get(match_id)
        if not row:
            continue
        for team in (row.get("Team1"), row.get("Team2")):
            if team and not _is_tbd(team) and team not in teams:
                teams.append(team)
    return teams


def get_context() -> dict:
    matches = _match_lookup()
    match71 = matches.get(71)
    match72 = matches.get(72)
    visible = True
    qualifier_rows = [match71, match72]
    teams: list[str] = []
    for row in qualifier_rows:
        if not row:
            continue
        for team in (row.get("Team1"), row.get("Team2")):
            if team and team not in teams:
                teams.append(team)
    enabled = visible and len(teams) == 4 and all(not _is_tbd(team) for team in teams)
    match74_completed = _status_for_match(matches.get(74)) == "completed"
    locked = _is_locked(match71)
    substitution_phase = _active_substitution_phase(matches) if enabled and locked else 0
    substitution_open = substitution_phase > 0
    first_substitution_finalized = enabled and locked and _first_substitution_finalized(matches)
    second_substitution_finalized = enabled and locked and _second_substitution_finalized(matches)
    substitution_teams = _substitution_team_list(matches)
    return {
        "visible": visible,
        "enabled": enabled,
        "locked": locked,
        "can_edit": enabled and ((not locked) or substitution_open),
        "public_visible": enabled and locked,
        "substitution_phase": substitution_phase,
        "substitution_open": substitution_open,
        "substitution_finalized": first_substitution_finalized,
        "first_substitution_finalized": first_substitution_finalized,
        "second_substitution_finalized": second_substitution_finalized,
        "substitution_teams": substitution_teams,
        "bonus_visible": match74_completed,
        "teams": teams if enabled else [],
        "matches": {
            str(mid): copy.deepcopy(matches.get(mid))
            for mid in SUPER_MATCH_IDS
            if matches.get(mid)
        },
        "message": (
            "The playoff gates are shut for now. Once the final four are locked, Super Team turns into war mode."
            if not enabled
            else "Second substitution window is open until Match 74 toss."
            if substitution_phase == 2
            else "Substitution window is open until Match 73 toss."
            if substitution_phase == 1
            else ""
        ),
    }


def _fetch_submissions_from_db() -> dict[int, dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT
            st.user_id,
            u.name AS user_name,
            st.player_id,
            st.is_captain,
            st.is_vice_captain,
            st.updated_at,
            st.updated_by
        FROM super_teams st
        JOIN users u ON u.id = st.user_id
        WHERE u.is_active = 1
        ORDER BY u.name, st.player_id
        """
    ).fetchall()
    grouped: dict[int, dict] = {}
    for row in rows:
        uid = int(row["user_id"])
        entry = grouped.setdefault(
            uid,
            {
                "user_id": uid,
                "name": row["user_name"],
                "player_ids": [],
                "captain": None,
                "vice_captain": None,
                "updated_at": row["updated_at"],
                "updated_by": row["updated_by"],
            },
        )
        player_id = int(row["player_id"])
        entry["player_ids"].append(player_id)
        if row["is_captain"]:
            entry["captain"] = player_id
        if row["is_vice_captain"]:
            entry["vice_captain"] = player_id
        if row["updated_at"]:
            entry["updated_at"] = row["updated_at"]
    return grouped


def _fetch_original_submissions_from_db() -> dict[int, dict]:
    snapshots = _fetch_snapshot_submissions_from_db("original")
    if snapshots:
        return snapshots
    db = get_db()
    rows = db.execute(
        """
        SELECT
            sto.user_id,
            u.name AS user_name,
            sto.player_id,
            sto.is_captain,
            sto.is_vice_captain,
            sto.snapshot_at
        FROM super_team_originals sto
        JOIN users u ON u.id = sto.user_id
        WHERE u.is_active = 1
        ORDER BY u.name, sto.player_id
        """
    ).fetchall()
    grouped: dict[int, dict] = {}
    for row in rows:
        uid = int(row["user_id"])
        entry = grouped.setdefault(
            uid,
            {
                "user_id": uid,
                "name": row["user_name"],
                "player_ids": [],
                "captain": None,
                "vice_captain": None,
                "snapshot_at": row["snapshot_at"],
            },
        )
        player_id = int(row["player_id"])
        entry["player_ids"].append(player_id)
        if row["is_captain"]:
            entry["captain"] = player_id
        if row["is_vice_captain"]:
            entry["vice_captain"] = player_id
        if row["snapshot_at"]:
            entry["snapshot_at"] = row["snapshot_at"]
    return grouped


def _fetch_snapshot_submissions_from_db(phase: str) -> dict[int, dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT
            sts.phase,
            sts.user_id,
            u.name AS user_name,
            sts.player_id,
            sts.is_captain,
            sts.is_vice_captain,
            sts.snapshot_at
        FROM super_team_snapshots sts
        JOIN users u ON u.id = sts.user_id
        WHERE u.is_active = 1 AND sts.phase = ?
        ORDER BY u.name, sts.player_id
        """,
        (phase,),
    ).fetchall()
    grouped: dict[int, dict] = {}
    for row in rows:
        uid = int(row["user_id"])
        entry = grouped.setdefault(
            uid,
            {
                "user_id": uid,
                "name": row["user_name"],
                "phase": row["phase"],
                "player_ids": [],
                "captain": None,
                "vice_captain": None,
                "snapshot_at": row["snapshot_at"],
            },
        )
        player_id = int(row["player_id"])
        entry["player_ids"].append(player_id)
        if row["is_captain"]:
            entry["captain"] = player_id
        if row["is_vice_captain"]:
            entry["vice_captain"] = player_id
        if row["snapshot_at"]:
            entry["snapshot_at"] = row["snapshot_at"]
    return grouped


def _fetch_all_snapshots_from_db() -> dict[str, dict[int, dict]]:
    return {phase: _fetch_snapshot_submissions_from_db(phase) for phase in SUPER_TEAM_SNAPSHOT_PHASES}


def _save_snapshot_entry(phase: str, entry: dict, *, replace: bool = False) -> int:
    if phase not in SUPER_TEAM_SNAPSHOT_PHASES:
        raise HTTPException(status_code=400, detail="Invalid Super Team snapshot phase")
    db = get_db()
    user_id = int(entry["user_id"])
    if replace:
        db.execute("DELETE FROM super_team_snapshots WHERE phase = ? AND user_id = ?", (phase, user_id))
    else:
        existing = db.execute(
            "SELECT 1 FROM super_team_snapshots WHERE phase = ? AND user_id = ? LIMIT 1",
            (phase, user_id),
        ).fetchone()
        if existing:
            return 0
    snapshot_at = _now_str()
    inserted = 0
    for pid in entry.get("player_ids", []):
        db.execute(
            """
            INSERT INTO super_team_snapshots
                (phase, user_id, player_id, is_captain, is_vice_captain, snapshot_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                phase,
                user_id,
                int(pid),
                1 if int(pid) == int(entry.get("captain") or 0) else 0,
                1 if int(pid) == int(entry.get("vice_captain") or 0) else 0,
                snapshot_at,
            ),
        )
        inserted += 1
    db.commit()
    return inserted


def ensure_original_snapshots() -> int:
    """Persist the locked Match 71/72 team as the comparison baseline."""
    db = get_db()
    existing_rows = db.execute("SELECT DISTINCT user_id FROM super_team_snapshots WHERE phase = 'original'").fetchall()
    existing_user_ids = {int(row["user_id"]) for row in existing_rows}
    inserted = 0
    for uid, entry in _fetch_submissions_from_db().items():
        if int(uid) in existing_user_ids:
            continue
        inserted += _save_snapshot_entry("original", entry)
    return inserted


def ensure_phase_snapshots(context: dict | None = None) -> int:
    context = context or get_context()
    inserted = 0
    submissions = _fetch_submissions_from_db()
    if context.get("locked"):
        inserted += ensure_original_snapshots()
    snapshots = _fetch_all_snapshots_from_db()
    originals = snapshots.get("original", {})
    edited = snapshots.get("edited", {})
    if context.get("first_substitution_finalized"):
        for uid, original in originals.items():
            if uid not in edited:
                inserted += _save_snapshot_entry("edited", submissions.get(uid) or original)
    snapshots = _fetch_all_snapshots_from_db()
    edited = snapshots.get("edited", {})
    final = snapshots.get("final", {})
    if context.get("second_substitution_finalized"):
        for uid, edited_entry in edited.items():
            if uid not in final:
                inserted += _save_snapshot_entry("final", submissions.get(uid) or edited_entry)
    return inserted


def replace_snapshot(phase: str, user_id: int, player_ids: list[int], captain: int, vice_captain: int) -> dict:
    normalized = validate_selection(player_ids, int(user_id), allow_any_playoff_player=True)
    captain_id, vice_captain_id = validate_leaders(normalized, captain, vice_captain)
    user_row = get_db().execute("SELECT name FROM users WHERE id = ? AND is_active = 1", (int(user_id),)).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    entry = {
        "user_id": int(user_id),
        "name": user_row["name"],
        "player_ids": normalized,
        "captain": captain_id,
        "vice_captain": vice_captain_id,
    }
    _save_snapshot_entry(phase, entry, replace=True)
    refresh_super_team_standings_cache()
    return entry


def _batting_sub_penalty_for_phase(phase: int) -> int:
    return SUPER_TEAM_PHASE2_BAT_PENALTY if phase == 2 else SUPER_TEAM_PHASE1_BAT_PENALTY


def _bowling_sub_penalty_for_phase(phase: int) -> int:
    return SUPER_TEAM_PHASE2_BOWL_PENALTY if phase == 2 else SUPER_TEAM_PHASE1_BOWL_PENALTY


def _is_bowling_role(role: str | None) -> bool:
    return str(role or "") == "Bowler"


def _sub_penalty_for_role(role: str | None, phase: int) -> int:
    return _bowling_sub_penalty_for_phase(phase) if _is_bowling_role(role) else _batting_sub_penalty_for_phase(phase)


def _penalty_details(original: dict | None, current: dict | None, *, phase: int = 1) -> dict:
    if not original or not current:
        return {
            "total": 0,
            "new_player_count": 0,
            "new_player_penalty": 0,
            "new_player_penalties": [],
            "substitutions": [],
            "captain_changed": False,
            "captain_penalty": 0,
            "captain_change": None,
            "vice_captain_changed": False,
            "vice_captain_penalty": 0,
            "vice_captain_change": None,
            "new_player_ids": [],
            "phase": phase,
        }
    players = _player_lookup()
    original_ids = {int(pid) for pid in original.get("player_ids", [])}
    current_ids = {int(pid) for pid in current.get("player_ids", [])}
    new_player_ids = sorted(current_ids - original_ids)
    removed_player_ids = sorted(original_ids - current_ids)
    captain_changed = int(original.get("captain") or 0) != int(current.get("captain") or 0)
    vice_captain_changed = int(original.get("vice_captain") or 0) != int(current.get("vice_captain") or 0)
    def player_summary(pid: int | None) -> dict | None:
        if not pid:
            return None
        player = players.get(int(pid), {})
        return {
            "player_id": int(pid),
            "name": player.get("Name", ""),
            "role": player.get("Role", ""),
            "team": player.get("Team", ""),
        }

    new_player_penalties = []
    substitutions = []
    unpaired_removed = list(removed_player_ids)
    for pid in new_player_ids:
        player = players.get(int(pid), {})
        penalty = _sub_penalty_for_role(player.get("Role"), phase)
        removed_id = next((rid for rid in unpaired_removed if players.get(int(rid), {}).get("Role") == player.get("Role")), None)
        if removed_id is None and unpaired_removed:
            removed_id = unpaired_removed[0]
        if removed_id is not None:
            unpaired_removed.remove(removed_id)
        new_player_penalties.append({
            "player_id": int(pid),
            "name": player.get("Name", ""),
            "role": player.get("Role", ""),
            "penalty": penalty,
        })
        substitutions.append({
            "outgoing": player_summary(removed_id),
            "incoming": player_summary(pid),
            "penalty": penalty,
        })
    new_player_penalty = sum(item["penalty"] for item in new_player_penalties)
    captain_role = players.get(int(current.get("captain") or 0), {}).get("Role")
    vice_captain_role = players.get(int(current.get("vice_captain") or 0), {}).get("Role")
    captain_penalty = int(_sub_penalty_for_role(captain_role, phase) * 0.5) if captain_changed else 0
    vice_captain_penalty = int(_sub_penalty_for_role(vice_captain_role, phase) * 0.25) if vice_captain_changed else 0
    total = new_player_penalty + captain_penalty + vice_captain_penalty
    return {
        "total": total,
        "new_player_count": len(new_player_ids),
        "new_player_penalty": new_player_penalty,
        "new_player_penalties": new_player_penalties,
        "substitutions": substitutions,
        "captain_changed": captain_changed,
        "captain_penalty": captain_penalty,
        "captain_change": {
            "from": player_summary(int(original.get("captain") or 0)),
            "to": player_summary(int(current.get("captain") or 0)),
            "penalty": captain_penalty,
        } if captain_changed else None,
        "vice_captain_changed": vice_captain_changed,
        "vice_captain_penalty": vice_captain_penalty,
        "vice_captain_change": {
            "from": player_summary(int(original.get("vice_captain") or 0)),
            "to": player_summary(int(current.get("vice_captain") or 0)),
            "penalty": vice_captain_penalty,
        } if vice_captain_changed else None,
        "new_player_ids": new_player_ids,
        "phase": phase,
    }


def _penalty_lookup(submissions: dict[int, dict] | None = None) -> dict[int, dict]:
    current = submissions or _fetch_submissions_from_db()
    snapshots = _fetch_all_snapshots_from_db()
    originals = snapshots.get("original", {}) or _fetch_original_submissions_from_db()
    edited = snapshots.get("edited", {})
    final = snapshots.get("final", {})
    user_ids = set(current) | set(originals) | set(edited) | set(final)
    penalties: dict[int, dict] = {}
    for uid in user_ids:
        phase1_current = edited.get(uid)
        phase1 = _penalty_details(originals.get(uid), phase1_current, phase=1)
        phase2_base = edited.get(uid)
        phase2_current = final.get(uid)
        phase2 = _penalty_details(phase2_base, phase2_current, phase=2)
        total = int(phase1.get("total", 0) or 0) + int(phase2.get("total", 0) or 0)
        penalties[int(uid)] = {
            "total": total,
            "phase1": phase1,
            "phase2": phase2,
            "new_player_count": int(phase1.get("new_player_count", 0) or 0) + int(phase2.get("new_player_count", 0) or 0),
            "new_player_penalty": int(phase1.get("new_player_penalty", 0) or 0) + int(phase2.get("new_player_penalty", 0) or 0),
            "captain_changed": bool(phase1.get("captain_changed") or phase2.get("captain_changed")),
            "captain_penalty": int(phase1.get("captain_penalty", 0) or 0) + int(phase2.get("captain_penalty", 0) or 0),
            "captain_change": phase2.get("captain_change") or phase1.get("captain_change"),
            "vice_captain_changed": bool(phase1.get("vice_captain_changed") or phase2.get("vice_captain_changed")),
            "vice_captain_penalty": int(phase1.get("vice_captain_penalty", 0) or 0) + int(phase2.get("vice_captain_penalty", 0) or 0),
            "vice_captain_change": phase2.get("vice_captain_change") or phase1.get("vice_captain_change"),
            "new_player_ids": [*phase1.get("new_player_ids", []), *phase2.get("new_player_ids", [])],
            "substitutions": [*phase1.get("substitutions", []), *phase2.get("substitutions", [])],
        }
    return penalties


def prime_super_team_cache() -> dict:
    global SUPER_TEAM_CACHE_LOADED
    context = get_context()
    if context.get("locked"):
        ensure_phase_snapshots(context)
    submissions = _fetch_submissions_from_db()
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_TEAM_CACHE.clear()
        SUPER_TEAM_CACHE.update(copy.deepcopy(submissions))
        SUPER_TEAM_CACHE_LOADED = True
    refresh_super_team_standings_cache()
    return {"teams": len(submissions), "standings": len(SUPER_STANDINGS_CACHE)}


def invalidate_player_pool_cache() -> None:
    global SUPER_PLAYER_POOL_KEY
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_PLAYER_POOL_KEY = None
        SUPER_PLAYER_POOL_CACHE.clear()


def get_submissions() -> dict[int, dict]:
    with SUPER_TEAM_CACHE_LOCK:
        if SUPER_TEAM_CACHE_LOADED:
            return copy.deepcopy(SUPER_TEAM_CACHE)
    return prime_and_get_submissions()


def prime_and_get_submissions() -> dict[int, dict]:
    prime_super_team_cache()
    with SUPER_TEAM_CACHE_LOCK:
        return copy.deepcopy(SUPER_TEAM_CACHE)


def _original_player_ids_for_user(user_id: int | None) -> set[int]:
    if user_id is None:
        return set()
    originals = _fetch_original_submissions_from_db()
    original = originals.get(int(user_id))
    if not original:
        return set()
    return {int(pid) for pid in original.get("player_ids", [])}


def _snapshot_player_ids_for_user_from_cache(user_id: int | None) -> set[int]:
    if user_id is None:
        return set()
    ids: set[int] = set()
    with SUPER_TEAM_CACHE_LOCK:
        details_snapshot = copy.deepcopy(SUPER_DETAILS_CACHE)
    for breakdown in details_snapshot.get("user_breakdowns", []):
        if int(breakdown.get("user_id") or 0) != int(user_id):
            continue
        for match in breakdown.get("matches", []):
            for player in match.get("players", []):
                if player.get("player_id") is not None:
                    ids.add(int(player["player_id"]))
        break
    return ids


def _build_player_pool(user_id: int | None = None) -> list[dict]:
    global SUPER_PLAYER_POOL_KEY
    context = get_context()
    snapshot_ids = _snapshot_player_ids_for_user_from_cache(user_id) if context.get("locked") else set()
    teams = set(context["teams"])
    if not teams and not snapshot_ids:
        return []
    cache_key = tuple([str(user_id or 0), *sorted(teams), *[str(pid) for pid in sorted(snapshot_ids)]])
    with SUPER_TEAM_CACHE_LOCK:
        if SUPER_PLAYER_POOL_KEY == cache_key:
            return copy.deepcopy(SUPER_PLAYER_POOL_CACHE)
    with SUPER_TEAM_CACHE_LOCK:
        details_snapshot = copy.deepcopy(SUPER_DETAILS_CACHE)
    points_by_player = {
        int(row["player_id"]): row
        for row in details_snapshot.get("player_points", [])
        if row.get("player_id") is not None
    }
    players = []
    for row in data_service.get_cached_data("players"):
        pid = int(row["PlayerID"])
        if row["Team"] not in teams and pid not in snapshot_ids:
            continue
        point_row = points_by_player.get(pid, {})
        match_points = point_row.get("match_points", {}) or {}
        nonzero_points = [float(value or 0) for value in match_points.values() if float(value or 0) != 0]
        latest_points = None
        for match_id in sorted(SUPER_MATCH_IDS, reverse=True):
            if str(match_id) in match_points:
                latest_points = round(float(match_points.get(str(match_id)) or 0), 2)
                break
        players.append({
            "id": pid,
            "name": row["Name"],
            "team": row["Team"],
            "role": row["Role"],
            "type": row.get("Type"),
            "aliases": row.get("Aliases", ""),
            "total_points": round(float(point_row.get("points") or 0), 2),
            "matches_played": len(nonzero_points),
            "avg_points": round((sum(nonzero_points) / len(nonzero_points)) if nonzero_points else 0, 2),
            "last_match_points": latest_points,
            "recent_history": [
                {
                    "match_id": int(match_id),
                    "points": round(float(points or 0), 2),
                    "did_not_play": float(points or 0) == 0,
                }
                for match_id, points in sorted(match_points.items(), key=lambda item: int(item[0]), reverse=True)
            ],
        })
    players.sort(key=lambda item: (item["team"], item["role"], -float(item["total_points"]), item["name"]))
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_PLAYER_POOL_KEY = cache_key
        SUPER_PLAYER_POOL_CACHE.clear()
        SUPER_PLAYER_POOL_CACHE.extend(copy.deepcopy(players))
    return players


def _load_last_match_points(db) -> dict[int, float]:
    rows = db.execute(
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
    return {int(row["player_id"]): round(float(row["points"] or 0), 2) for row in rows}


def _load_recent_history(db, teams: list[str], player_ids: list[int]) -> dict[int, list[dict]]:
    if not teams or not player_ids:
        return {}
    team_placeholders = ",".join("?" * len(teams))
    matches_rows = db.execute(
        f"""
        SELECT id, team1, team2
        FROM matches
        WHERE status = 'completed'
          AND (team1 IN ({team_placeholders}) OR team2 IN ({team_placeholders}))
        ORDER BY id DESC
        """,
        [*teams, *teams],
    ).fetchall()
    match_ids = [int(row["id"]) for row in matches_rows]
    if not match_ids:
        return {}
    point_rows = db.execute(
        f"""
        SELECT match_id, player_id, points
        FROM player_points
        WHERE player_id IN ({",".join("?" * len(player_ids))})
          AND match_id IN ({",".join("?" * len(match_ids))})
        """,
        [*player_ids, *match_ids],
    ).fetchall()
    points = {
        (int(row["player_id"]), int(row["match_id"])): round(float(row["points"] or 0), 2)
        for row in point_rows
    }
    player_team = {int(row["PlayerID"]): row["Team"] for row in data_service.get_cached_data("players")}
    history: dict[int, list[dict]] = {pid: [] for pid in player_ids}
    for pid in player_ids:
        team = player_team.get(pid)
        for match in matches_rows:
            if match["team1"] != team and match["team2"] != team:
                continue
            mid = int(match["id"])
            history[pid].append({
                "match_id": mid,
                "opponent": match["team2"] if match["team1"] == team else match["team1"],
                "points": points.get((pid, mid)),
                "did_not_play": (pid, mid) not in points,
            })
    return history


def grouped_player_pool(user_id: int | None = None) -> dict[str, list[dict]]:
    grouped = {"Wicketkeeper": [], "Batter": [], "AllRounder": [], "Bowler": []}
    for player in _build_player_pool(user_id):
        grouped.setdefault(player["role"], []).append(player)
    return grouped


def _eligible_player_ids_for_context(context: dict, user_id: int | None = None) -> set[int]:
    players = _player_lookup()
    snapshot_ids = _snapshot_player_ids_for_user_from_cache(user_id) if context.get("locked") else set()
    eligible_teams = set(context["teams"])
    return {
        int(pid)
        for pid, player in players.items()
        if player and (player["Team"] in eligible_teams or int(pid) in snapshot_ids)
    }


def validate_selection(player_ids: list[int], user_id: int | None = None, *, allow_any_playoff_player: bool = False) -> list[int]:
    if len(player_ids) != SUPER_TEAM_SIZE:
        raise HTTPException(status_code=400, detail=f"Exactly {SUPER_TEAM_SIZE} players required")
    normalized = [int(pid) for pid in player_ids]
    if len(set(normalized)) != SUPER_TEAM_SIZE:
        raise HTTPException(status_code=400, detail="Duplicate players are not allowed")
    context = get_context()
    if not context["enabled"]:
        raise HTTPException(status_code=400, detail=context["message"] or "Super Team is not open")
    eligible_player_ids = _eligible_player_ids_for_context(context, user_id)
    players = _player_lookup()
    selected = [players.get(pid) for pid in normalized]
    if any(player is None for player in selected):
        raise HTTPException(status_code=400, detail="Some player IDs are invalid")
    if not allow_any_playoff_player and any(pid not in eligible_player_ids for pid in normalized):
        raise HTTPException(status_code=400, detail="Some players are not eligible for Super Team")
    role_counts = {
        role: sum(1 for player in selected if player and player["Role"] == role)
        for role in SUPER_TEAM_REQUIRED_ROLES
    }
    missing_roles = [role for role, count in role_counts.items() if count < 1]
    if missing_roles:
        raise HTTPException(status_code=400, detail="Select at least 1 Wicketkeeper, 1 Batter, and 1 AllRounder")
    bowler_count = sum(1 for player in selected if player and player["Role"] == "Bowler")
    if bowler_count < SUPER_TEAM_MIN_BOWLERS:
        raise HTTPException(status_code=400, detail=f"At least {SUPER_TEAM_MIN_BOWLERS} Bowlers required")
    return normalized


def validate_substitution_against_original(user_id: int, player_ids: list[int]) -> None:
    return


def validate_leaders(player_ids: list[int], captain: int, vice_captain: int) -> tuple[int, int]:
    normalized_set = {int(pid) for pid in player_ids}
    captain_id = int(captain)
    vice_captain_id = int(vice_captain)
    if captain_id == vice_captain_id:
        raise HTTPException(status_code=400, detail="Captain and vice-captain must be different")
    if captain_id not in normalized_set:
        raise HTTPException(status_code=400, detail="Captain must be one of the selected players")
    if vice_captain_id not in normalized_set:
        raise HTTPException(status_code=400, detail="Vice-captain must be one of the selected players")
    return captain_id, vice_captain_id


def _super_team_multiplier(player_id: int, captain: int | None, vice_captain: int | None) -> float:
    if captain is not None and int(player_id) == int(captain):
        return SUPER_TEAM_CAPTAIN_MULTIPLIER
    if vice_captain is not None and int(player_id) == int(vice_captain):
        return SUPER_TEAM_VICE_CAPTAIN_MULTIPLIER
    return 1.0


def _super_team_tag(player_id: int, captain: int | None, vice_captain: int | None) -> str:
    if captain is not None and int(player_id) == int(captain):
        return "C"
    if vice_captain is not None and int(player_id) == int(vice_captain):
        return "VC"
    return ""


def _apply_super_team_multiplier(base_points: float, player_id: int, captain: int | None, vice_captain: int | None) -> float:
    multiplier = _super_team_multiplier(player_id, captain, vice_captain)
    points = base_points * multiplier
    if vice_captain is not None and int(player_id) == int(vice_captain):
        return math.ceil(points * 2) / 2
    return points


def save_team(user_id: int, player_ids: list[int], captain: int, vice_captain: int, updated_by: int | None = None, ignore_lock: bool = False) -> dict:
    global SUPER_TEAM_CACHE_LOADED
    context = get_context()
    if context.get("locked"):
        ensure_phase_snapshots(context)
    if not context.get("can_edit") and not ignore_lock:
        raise HTTPException(status_code=400, detail="Super Team is locked")
    normalized = validate_selection(player_ids, int(user_id))
    captain_id, vice_captain_id = validate_leaders(normalized, captain, vice_captain)
    db = get_db()
    user_row = db.execute("SELECT name FROM users WHERE id = ? AND is_active = 1", (int(user_id),)).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    updated_at = _now_str()
    db.execute("DELETE FROM super_teams WHERE user_id = ?", (int(user_id),))
    for pid in normalized:
        db.execute(
            """
            INSERT INTO super_teams (user_id, player_id, is_captain, is_vice_captain, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                int(pid),
                1 if int(pid) == captain_id else 0,
                1 if int(pid) == vice_captain_id else 0,
                updated_at,
                updated_by,
            ),
        )
    db.commit()
    entry = {
        "user_id": int(user_id),
        "name": user_row["name"],
        "player_ids": normalized,
        "captain": captain_id,
        "vice_captain": vice_captain_id,
        "updated_at": updated_at,
        "updated_by": updated_by,
    }
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_TEAM_CACHE[int(user_id)] = copy.deepcopy(entry)
        SUPER_TEAM_CACHE_LOADED = True
    refresh_super_team_standings_cache()
    return copy.deepcopy(entry)


def projected_penalty(user_id: int, player_ids: list[int], captain: int, vice_captain: int) -> dict:
    context = get_context()
    normalized = validate_selection(player_ids, int(user_id))
    captain_id, vice_captain_id = validate_leaders(normalized, captain, vice_captain)
    draft = {
        "user_id": int(user_id),
        "player_ids": normalized,
        "captain": captain_id,
        "vice_captain": vice_captain_id,
    }
    ensure_phase_snapshots(context)
    snapshots = _fetch_all_snapshots_from_db()
    phase = int(context.get("substitution_phase") or 0)
    if phase == 1:
        return _penalty_details(snapshots.get("original", {}).get(int(user_id)), draft, phase=1)
    if phase == 2:
        baseline = snapshots.get("edited", {}).get(int(user_id)) or snapshots.get("original", {}).get(int(user_id))
        return _penalty_details(baseline, draft, phase=2)
    return _penalty_details(None, None, phase=0)


def my_team(user_id: int) -> dict:
    submissions = get_submissions()
    entry = submissions.get(int(user_id))
    if not entry:
        return {"players": [], "updated_at": None, "penalty": _penalty_details(None, None)}
    players = _player_lookup()
    with SUPER_TEAM_CACHE_LOCK:
        standings_snapshot = copy.deepcopy(SUPER_STANDINGS_CACHE)
    standing = next((row for row in standings_snapshot if int(row.get("user_id") or 0) == int(user_id)), None)
    penalty = (standing or {}).get("penalty") or _penalty_details(None, None)
    return {
        "players": [
            {
                "player_id": pid,
                "player_name": players.get(pid, {}).get("Name", ""),
                "team": players.get(pid, {}).get("Team", ""),
                "role": players.get(pid, {}).get("Role", ""),
                "is_captain": pid == entry.get("captain"),
                "is_vice_captain": pid == entry.get("vice_captain"),
            }
            for pid in entry["player_ids"]
        ],
        "captain": entry.get("captain"),
        "vice_captain": entry.get("vice_captain"),
        "updated_at": entry.get("updated_at"),
        "penalty": penalty,
        "snapshots": {},
    }


def contestants() -> list[dict]:
    return [
        {"user_id": entry["user_id"], "name": entry["name"], "last_team_updated": entry.get("updated_at")}
        for entry in sorted(
            get_submissions().values(),
            key=lambda item: (str(item.get("updated_at") or ""), item["name"]),
            reverse=True,
        )
    ]


def admin_snapshot_payload() -> dict:
    snapshots = _fetch_all_snapshots_from_db()
    current = get_submissions()
    return {
        "current": list(current.values()),
        "original": list(snapshots.get("original", {}).values()),
        "edited": list(snapshots.get("edited", {}).values()),
        "final": list(snapshots.get("final", {}).values()),
    }


def missing_users() -> list[dict]:
    submitted_user_ids = set(get_submissions().keys())
    users = data_service.get_cached_data("users")
    missing = []
    for user in users:
        try:
            user_id = int(user.get("UserID", 0) or 0)
        except Exception:
            continue
        if not user_id or user_id in submitted_user_ids:
            continue
        if str(user.get("Allowed", "")).strip().lower() != "true":
            continue
        missing.append({"id": user_id, "name": user.get("Name", "")})
    missing.sort(key=lambda item: item["name"])
    return missing


def _point_lookup_from_score_cache() -> dict[tuple[int, int], float]:
    lookup: dict[tuple[int, int], float] = {}
    try:
        from backend.routes.scores import get_cached_scores_snapshot
        snapshot = get_cached_scores_snapshot()
    except Exception:
        snapshot = {}
    for match_id in SUPER_MATCH_IDS:
        payload = snapshot.get(match_id) or snapshot.get(str(match_id)) or {}
        for player in payload.get("players", []):
            if player.get("player_id") is None:
                continue
            lookup[(int(match_id), int(player["player_id"]))] = float(player.get("points", 0) or 0)
    return lookup


def _player_breakdown_lookup_from_score_cache() -> dict[tuple[int, int], list[dict]]:
    lookup: dict[tuple[int, int], list[dict]] = {}
    try:
        from backend.routes.scores import get_cached_scores_snapshot
        snapshot = get_cached_scores_snapshot()
    except Exception:
        snapshot = {}
    for match_id in SUPER_MATCH_IDS:
        payload = snapshot.get(match_id) or snapshot.get(str(match_id)) or {}
        for player in payload.get("players", []):
            if player.get("player_id") is None:
                continue
            lookup[(int(match_id), int(player["player_id"]))] = list(player.get("breakdown") or [])
    return lookup


def _point_lookup_from_db() -> dict[tuple[int, int], float]:
    db = get_db()
    rows = db.execute(
        f"""
        SELECT match_id, player_id, points
        FROM player_points
        WHERE match_id IN ({",".join("?" * len(SUPER_MATCH_IDS))})
        """,
        SUPER_MATCH_IDS,
    ).fetchall()
    return {(int(row["match_id"]), int(row["player_id"])): float(row["points"] or 0) for row in rows}


def refresh_super_team_standings_cache() -> dict:
    context = get_context()
    if context.get("locked"):
        ensure_phase_snapshots(context)
    submissions = _fetch_submissions_from_db()
    snapshots = _fetch_all_snapshots_from_db()
    originals = snapshots.get("original", {}) or _fetch_original_submissions_from_db()
    edited = snapshots.get("edited", {})
    final = snapshots.get("final", {})
    penalties = _penalty_lookup(submissions)
    penalty_applies = bool(context.get("first_substitution_finalized") or context.get("second_substitution_finalized"))
    point_lookup = _point_lookup_from_score_cache()
    if not point_lookup:
        point_lookup = _point_lookup_from_db()
    breakdown_lookup = _player_breakdown_lookup_from_score_cache()
    players = _player_lookup()
    rows = []
    user_breakdowns = []
    owners_by_player_match: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    max_points = None
    for entry in submissions.values():
        match_points: dict[int, float] = defaultdict(float)
        match_players: dict[int, list[dict]] = {match_id: [] for match_id in SUPER_MATCH_IDS}
        total = 0.0
        original_entry = originals.get(int(entry["user_id"])) or entry
        edited_entry = edited.get(int(entry["user_id"])) or original_entry
        final_entry = final.get(int(entry["user_id"])) or edited_entry
        score_entries_by_match = {
            71: original_entry,
            72: original_entry,
            73: edited_entry,
            74: final_entry,
        }
        latest_ids = {int(pid) for pid in final_entry.get("player_ids", [])}
        for match_id in SUPER_MATCH_IDS:
            score_entry = score_entries_by_match[match_id]
            match_captain = score_entry.get("captain")
            match_vice_captain = score_entry.get("vice_captain")
            for pid in score_entry["player_ids"]:
                player = players.get(int(pid), {})
                multiplier = _super_team_multiplier(int(pid), match_captain, match_vice_captain)
                tag = _super_team_tag(int(pid), match_captain, match_vice_captain)
                base_pts = float(point_lookup.get((match_id, int(pid)), 0))
                pts = _apply_super_team_multiplier(base_pts, int(pid), match_captain, match_vice_captain)
                match_points[match_id] += pts
                total += pts
                owners_by_player_match[int(pid)][str(match_id)].append({
                    "user_id": int(entry["user_id"]),
                    "name": entry["name"],
                    "tag": tag,
                })
                match_players[match_id].append({
                    "player_id": int(pid),
                    "name": player.get("Name", ""),
                    "team": player.get("Team", ""),
                    "role": player.get("Role", ""),
                    "base_points": round(base_pts, 2),
                    "multiplier": multiplier,
                    "tag": tag,
                    "points": round(pts, 2),
                    "removed": int(pid) not in latest_ids,
                })
        gross_points = round(total, 2)
        penalty = penalties.get(int(entry["user_id"]), _penalty_details(None, None))
        total = round(gross_points - float(penalty.get("total", 0) or 0), 2) if penalty_applies else gross_points
        if max_points is None or total > max_points:
            max_points = total
        row = {
            "user_id": entry["user_id"],
            "name": entry["name"],
            "points": total,
            "gross_points": gross_points,
            "penalty": penalty,
            "penalty_applied": penalty_applies,
            "match_points": {str(k): round(v, 2) for k, v in match_points.items()},
            "updated_at": entry.get("updated_at"),
        }
        rows.append(row)
        user_breakdowns.append({
            **row,
            "matches": [
                {
                    "match_id": match_id,
                    "points": round(match_points.get(match_id, 0), 2),
                    "players": sorted(
                        match_players[match_id],
                        key=lambda item: (-float(item["points"]), item["name"]),
                    ),
                }
                for match_id in SUPER_MATCH_IDS
            ],
        })
    rows.sort(key=lambda item: (-item["points"], item["name"]))
    rank = 1
    for index, row in enumerate(rows):
        if index > 0 and row["points"] == rows[index - 1]["points"]:
            row["rank"] = rows[index - 1]["rank"]
        else:
            row["rank"] = rank = index + 1
    rank_by_user = {int(row["user_id"]): int(row["rank"]) for row in rows}
    for breakdown in user_breakdowns:
        breakdown["rank"] = rank_by_user.get(int(breakdown["user_id"]), 0)
    user_breakdowns.sort(key=lambda item: (int(item.get("rank") or 9999), item["name"]))
    for match_owners in owners_by_player_match.values():
        for owners in match_owners.values():
            for owner in owners:
                owner["rank"] = rank_by_user.get(int(owner["user_id"]), 0)
            owners.sort(key=lambda item: (int(item.get("rank") or 9999), item["name"]))

    player_ids = sorted({
        int(pid)
        for entry in [*submissions.values(), *originals.values(), *edited.values(), *final.values()]
        for pid in entry.get("player_ids", [])
    })
    player_points = []
    for pid in player_ids:
        player = players.get(pid, {})
        match_point_map = {
            str(match_id): round(float(point_lookup.get((match_id, pid), 0)), 2)
            for match_id in SUPER_MATCH_IDS
        }
        match_breakdown_map = {
            str(match_id): copy.deepcopy(breakdown_lookup.get((match_id, pid), []))
            for match_id in SUPER_MATCH_IDS
        }
        total_points = round(sum(match_point_map.values()), 2)
        player_points.append({
            "player_id": pid,
            "name": player.get("Name", ""),
            "team": player.get("Team", ""),
            "role": player.get("Role", ""),
            "points": total_points,
            "match_points": match_point_map,
            "match_breakdowns": match_breakdown_map,
            "owners": {
                str(match_id): copy.deepcopy(owners_by_player_match.get(pid, {}).get(str(match_id), []))
                for match_id in SUPER_MATCH_IDS
            },
        })
    player_points.sort(key=lambda item: (-float(item["points"]), item["team"], item["name"]))

    bonus_by_user = {
        int(row["user_id"]): int(SUPER_TEAM_BONUSES_BY_RANK[int(row["rank"])])
        for row in rows
        if context["bonus_visible"] and int(row["rank"]) in SUPER_TEAM_BONUSES_BY_RANK
    }
    with SUPER_TEAM_CACHE_LOCK:
        SUPER_STANDINGS_CACHE.clear()
        SUPER_STANDINGS_CACHE.extend(copy.deepcopy(rows))
        SUPER_DETAILS_CACHE.clear()
        SUPER_DETAILS_CACHE.update({
            "user_breakdowns": copy.deepcopy(user_breakdowns),
            "player_points": copy.deepcopy(player_points),
        })
        SUPER_STANDINGS_META.clear()
        SUPER_STANDINGS_META.update({
            "bonus_visible": context["bonus_visible"],
            "bonus_by_user": bonus_by_user,
        })
    return {"standings": len(rows), "bonus_users": len(bonus_by_user)}


def standings() -> list[dict]:
    with SUPER_TEAM_CACHE_LOCK:
        return copy.deepcopy(SUPER_STANDINGS_CACHE)


def details() -> dict:
    with SUPER_TEAM_CACHE_LOCK:
        return copy.deepcopy(SUPER_DETAILS_CACHE)


def bonus_map() -> dict[int, int]:
    context = get_context()
    if not context["bonus_visible"]:
        return {}
    with SUPER_TEAM_CACHE_LOCK:
        if not SUPER_STANDINGS_CACHE:
            pass
        else:
            return {int(uid): int(bonus) for uid, bonus in SUPER_STANDINGS_META.get("bonus_by_user", {}).items()}
    refresh_super_team_standings_cache()
    with SUPER_TEAM_CACHE_LOCK:
        return {int(uid): int(bonus) for uid, bonus in SUPER_STANDINGS_META.get("bonus_by_user", {}).items()}
