"""
Weekend Tournament Service — "Player of the Weekend"

Detects weekends with IPL matches (1-4 on Sat+Sun), picks the last match
before Saturday as the qualifier, seeds a 2^n player knockout bracket
(where n = number of weekend matches), and advances rounds as weekend
matches complete.
"""

import json
import random
from datetime import datetime, timedelta
from collections import defaultdict

from backend.config import IST
from backend.database import get_db


def _get_round_labels(num_rounds: int) -> dict[int, str]:
    """Generate round labels based on total number of rounds."""
    if num_rounds == 1:
        return {1: "Final"}
    if num_rounds == 2:
        return {1: "Semi Finals", 2: "Final"}
    if num_rounds == 3:
        return {1: "Quarter Finals", 2: "Semi Finals", 3: "Final"}
    return {1: "Round of 16", 2: "Quarter Finals", 3: "Semi Finals", 4: "Final"}


def _get_weekend_match_ids(tournament) -> list[int]:
    """Extract weekend match IDs from tournament row."""
    if "weekend_match_ids" in tournament.keys():
        raw = tournament["weekend_match_ids"]
        if raw and isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [int(mid) for mid in parsed if mid is not None]
            except Exception:
                pass
        if isinstance(raw, list):
            return [int(mid) for mid in raw if mid is not None]

    legacy_ids = []
    for suffix in range(1, 5):
        key = f"weekend_match_{suffix}_id"
        if key in tournament.keys():
            mid = tournament[key]
            if mid is not None:
                legacy_ids.append(int(mid))
    return legacy_ids


def _get_tournament_num_rounds(tournament) -> int:
    """Get the number of rounds, falling back to the number of weekend matches."""
    if "num_rounds" in tournament.keys():
        raw = tournament["num_rounds"]
        if raw not in (None, ""):
            try:
                value = int(raw)
                if value > 0:
                    return value
            except Exception:
                pass
    return len(_get_weekend_match_ids(tournament))


# ──────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────

def detect_and_create_tournaments() -> list[int]:
    """Scan match schedule for weekends with matches. Create tournaments for any new ones found.
    Returns list of newly created tournament IDs."""
    db = get_db()
    matches = db.execute(
        "SELECT id, match_date, match_time FROM matches ORDER BY match_date, match_time"
    ).fetchall()

    # Group matches by date
    by_date: dict[str, list[dict]] = defaultdict(list)
    for m in matches:
        by_date[m["match_date"]].append({"id": m["id"], "date": m["match_date"], "time": m["match_time"]})

    # Find Saturdays with at least 1 weekend match (Sat or Sun)
    all_dates = sorted(by_date.keys())
    created_ids = []

    for date_str in all_dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.weekday() != 5:  # Not Saturday
            continue

        sat = date_str
        sun = (dt + timedelta(days=1)).strftime("%Y-%m-%d")

        sat_matches = by_date.get(sat, [])
        sun_matches = by_date.get(sun, [])

        # Collect all weekend matches sorted by date+time
        sat_matches.sort(key=lambda x: x["time"])
        sun_matches.sort(key=lambda x: x["time"])
        weekend_matches = sat_matches + sun_matches

        if len(weekend_matches) < 1:
            continue

        weekend_match_ids = [m["id"] for m in weekend_matches]
        num_rounds = len(weekend_match_ids)

        # Find qualifying match: last match before Saturday
        qualifier = _find_qualifier_match(all_dates, by_date, sat)
        if qualifier is None:
            continue

        # Check if tournament already exists
        existing = db.execute(
            "SELECT id FROM weekend_tournaments WHERE qualifying_match_id = ?",
            (qualifier["id"],),
        ).fetchone()
        if existing:
            continue

        db.execute(
            """
            INSERT INTO weekend_tournaments
                (qualifying_match_id, weekend_match_ids, num_rounds, status)
            VALUES (?, ?, ?, 'pending')
            """,
            (qualifier["id"], json.dumps(weekend_match_ids), num_rounds),
        )
        db.commit()

        row = db.execute(
            "SELECT id FROM weekend_tournaments WHERE qualifying_match_id = ?",
            (qualifier["id"],),
        ).fetchone()
        if row:
            created_ids.append(row["id"])
            print(f"[WEEKEND] Created tournament #{row['id']} qualifier=M{qualifier['id']} "
                  f"weekend=M{weekend_match_ids} rounds={num_rounds}")

    return created_ids


def _find_qualifier_match(all_dates, by_date, saturday_str):
    """Find the last match before the given Saturday date."""
    sat_dt = datetime.strptime(saturday_str, "%Y-%m-%d")

    # Look backwards from Friday up to 5 days
    for days_back in range(1, 6):
        check_date = (sat_dt - timedelta(days=days_back)).strftime("%Y-%m-%d")
        matches_on_day = by_date.get(check_date, [])
        if matches_on_day:
            # Pick last match of the day (by time)
            matches_on_day.sort(key=lambda x: x["time"])
            return matches_on_day[-1]

    return None


# ──────────────────────────────────────────────
# Seeding
# ──────────────────────────────────────────────

def seed_bracket(tournament_id: int) -> dict:
    """After qualifying match completes, seed the bracket with 2^n players."""
    db = get_db()

    tournament = db.execute(
        "SELECT * FROM weekend_tournaments WHERE id = ?", (tournament_id,)
    ).fetchone()
    if not tournament:
        return {"error": "Tournament not found"}

    match_ids = _get_weekend_match_ids(tournament)
    num_rounds = _get_tournament_num_rounds(tournament) or len(match_ids)
    num_players_needed = 2 ** num_rounds

    # Get qualifier results
    qualifier_match_id = tournament["qualifying_match_id"]
    qualifier_results = _get_match_contestant_points(db, qualifier_match_id)

    # Get qualified user IDs (top N from qualifier)
    qualified = []
    for entry in qualifier_results[:num_players_needed]:
        qualified.append({
            "user_id": entry["user_id"],
            "name": entry["name"],
            "qualifying_points": entry["points"],
        })

    # If less than needed, backfill from overall leaderboard
    if len(qualified) < num_players_needed:
        qualified_ids = {q["user_id"] for q in qualified}
        leaderboard_fill = _get_leaderboard_backfill(db, qualified_ids, num_players_needed - len(qualified))
        qualified.extend(leaderboard_fill)

    # Ensure we have an even number (at least 2)
    if len(qualified) < 2:
        return {"error": "Not enough participants"}

    # If odd, trim to even
    if len(qualified) % 2 != 0:
        qualified = qualified[:-1]

    # Determine bracket size
    num_players = len(qualified)
    num_matchups = num_players // 2

    # Randomize pairings (one-time shuffle — bracket is fixed from here)
    random.shuffle(qualified)

    # Create round 1 brackets
    match_id_for_round_1 = match_ids[0]

    for i in range(num_matchups):
        user1 = qualified[i * 2]
        user2 = qualified[i * 2 + 1]
        db.execute(
            """
            INSERT INTO weekend_tournament_brackets
                (tournament_id, round, match_position, match_id, user1_id, user2_id, status)
            VALUES (?, 1, ?, ?, ?, ?, 'pending')
            """,
            (tournament_id, i + 1, match_id_for_round_1, user1["user_id"], user2["user_id"]),
        )

    # Update tournament status
    db.execute(
        "UPDATE weekend_tournaments SET status = 'active' WHERE id = ?",
        (tournament_id,),
    )
    db.commit()

    print(f"[WEEKEND] Seeded tournament #{tournament_id} with {num_players} players, "
          f"{num_matchups} matchups, {num_rounds} rounds")
    return {"tournament_id": tournament_id, "players": num_players, "matchups": num_matchups}


# ──────────────────────────────────────────────
# Round Advancement
# ──────────────────────────────────────────────

def advance_round(tournament_id: int, completed_match_id: int) -> dict:
    """After a weekend match completes, score the 1v1s and create next round."""
    db = get_db()

    tournament = db.execute(
        "SELECT * FROM weekend_tournaments WHERE id = ?", (tournament_id,)
    ).fetchone()
    if not tournament or tournament["status"] != "active":
        return {"error": "Tournament not active"}

    match_ids = _get_weekend_match_ids(tournament)
    num_rounds = len(match_ids)

    # Find which round this match belongs to
    current_round = _get_round_for_match(tournament, completed_match_id)
    if current_round is None:
        return {"error": "Match not part of this tournament's weekend matches"}

    # Get brackets for this round
    brackets = db.execute(
        """
        SELECT * FROM weekend_tournament_brackets
        WHERE tournament_id = ? AND round = ?
        ORDER BY match_position
        """,
        (tournament_id, current_round),
    ).fetchall()

    if not brackets:
        return {"error": "No brackets for this round"}

    # Get contestant points for this match
    match_points = _get_match_contestant_points(db, completed_match_id)
    points_map = {entry["user_id"]: entry["points"] for entry in match_points}

    # Also get leaderboard ranks for tie-breaking
    leaderboard_ranks = _get_leaderboard_ranks(db)

    winners = []
    for bracket in brackets:
        u1 = bracket["user1_id"]
        u2 = bracket["user2_id"]
        u1_pts = points_map.get(u1, 0.0)
        u2_pts = points_map.get(u2, 0.0)

        # Determine winner
        if u1_pts > u2_pts:
            winner = u1
        elif u2_pts > u1_pts:
            winner = u2
        else:
            # Tie-break: better leaderboard rank wins
            r1 = leaderboard_ranks.get(u1, 9999)
            r2 = leaderboard_ranks.get(u2, 9999)
            winner = u1 if r1 <= r2 else u2

        db.execute(
            """
            UPDATE weekend_tournament_brackets
            SET user1_points = ?, user2_points = ?, winner_user_id = ?, status = 'completed'
            WHERE id = ?
            """,
            (u1_pts, u2_pts, winner, bracket["id"]),
        )
        winners.append(winner)

    # Check if this was the final round
    if current_round == num_rounds or len(winners) == 1:
        db.execute(
            "UPDATE weekend_tournaments SET status = 'completed', winner_user_id = ? WHERE id = ?",
            (winners[0], tournament_id),
        )
        db.commit()
        print(f"[WEEKEND] Tournament #{tournament_id} completed! Winner: user #{winners[0]}")
        return {"status": "completed", "winner_user_id": winners[0]}

    # Create next round pairings — adjacent winners play each other (no reshuffle)
    next_round = current_round + 1
    next_match_id = match_ids[next_round - 1]

    num_matchups = len(winners) // 2
    round_labels = _get_round_labels(num_rounds)

    for i in range(num_matchups):
        db.execute(
            """
            INSERT INTO weekend_tournament_brackets
                (tournament_id, round, match_position, match_id, user1_id, user2_id, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (tournament_id, next_round, i + 1, next_match_id, winners[i * 2], winners[i * 2 + 1]),
        )

    db.commit()
    print(f"[WEEKEND] Advanced tournament #{tournament_id} to round {next_round} "
          f"({round_labels.get(next_round, '')}), {num_matchups} matchups")
    return {"status": "advanced", "round": next_round, "matchups": num_matchups}


# ──────────────────────────────────────────────
# Match Completion Hook
# ──────────────────────────────────────────────

def on_match_completed(match_id: int):
    """Called when any match is finalized. Checks if it triggers tournament actions."""
    db = get_db()

    # Always try to detect new tournaments (picks up new weekends automatically)
    try:
        detect_and_create_tournaments()
    except Exception as exc:
        print(f"[WEEKEND] Auto-detection failed: {exc}")

    # Check if this match is a qualifier for a pending tournament
    tournament = db.execute(
        "SELECT * FROM weekend_tournaments WHERE qualifying_match_id = ? AND status IN ('pending', 'qualifying')",
        (match_id,),
    ).fetchone()
    if tournament:
        print(f"[WEEKEND] Qualifier match M{match_id} completed, seeding tournament #{tournament['id']}")
        seed_bracket(tournament["id"])
        return

    # Check if this match is a weekend match in an active tournament
    active = db.execute(
        "SELECT * FROM weekend_tournaments WHERE status = 'active'"
    ).fetchall()
    for t in active:
        if match_id in _get_weekend_match_ids(t):
            print(f"[WEEKEND] Weekend match M{match_id} completed, advancing tournament #{t['id']}")
            advance_round(t["id"], match_id)
            return


# ──────────────────────────────────────────────
# Query helpers
# ──────────────────────────────────────────────

def get_current_tournament() -> dict | None:
    """Get the active or most recent tournament with full bracket data."""
    db = get_db()

    tournament = db.execute(
        """
        SELECT * FROM weekend_tournaments
        WHERE status IN ('active', 'qualifying')
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()

    if not tournament:
        # Fall back to next upcoming pending tournament (by qualifier date)
        tournament = db.execute(
            """
            SELECT wt.* FROM weekend_tournaments wt
            JOIN matches m ON m.id = wt.qualifying_match_id
            WHERE wt.status = 'pending'
            ORDER BY m.match_date ASC LIMIT 1
            """
        ).fetchone()

    if not tournament:
        # Fall back to most recent completed
        tournament = db.execute(
            "SELECT * FROM weekend_tournaments WHERE status = 'completed' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if not tournament:
        return None

    return _build_tournament_response(db, tournament)


def get_tournament_by_id(tournament_id: int) -> dict | None:
    db = get_db()
    tournament = db.execute(
        "SELECT * FROM weekend_tournaments WHERE id = ?", (tournament_id,)
    ).fetchone()
    if not tournament:
        return None
    return _build_tournament_response(db, tournament)


def get_tournament_history() -> list[dict]:
    db = get_db()
    rows = db.execute(
        """
        SELECT wt.id, wt.status, wt.qualifying_match_id,
               wt.winner_user_id, u.name AS winner_name,
               m.match_date AS qualifier_date
        FROM weekend_tournaments wt
        LEFT JOIN users u ON u.id = wt.winner_user_id
        LEFT JOIN matches m ON m.id = wt.qualifying_match_id
        ORDER BY wt.id DESC
        """
    ).fetchall()

    return [
        {
            "id": r["id"],
            "status": r["status"],
            "qualifier_date": r["qualifier_date"],
            "winner": {"user_id": r["winner_user_id"], "name": r["winner_name"]}
            if r["winner_user_id"]
            else None,
        }
        for r in rows
    ]


def get_upcoming_tournament() -> dict | None:
    """Get the next pending tournament that hasn't started yet."""
    db = get_db()
    tournament = db.execute(
        """
        SELECT wt.*
        FROM weekend_tournaments wt
        LEFT JOIN matches m ON m.id = wt.qualifying_match_id
        WHERE wt.status = 'pending'
        ORDER BY m.match_date ASC, m.match_time ASC, wt.id ASC
        LIMIT 1
        """
    ).fetchone()
    if not tournament:
        return None
    return _build_tournament_response(db, tournament)


def get_tournament_match_tags() -> dict[int, dict]:
    """Returns a map of match_id -> tournament tag info for all active/pending tournaments."""
    db = get_db()
    tournaments = db.execute(
        "SELECT * FROM weekend_tournaments WHERE status IN ('pending', 'qualifying', 'active')"
    ).fetchall()

    tags = {}
    for t in tournaments:
        tags[t["qualifying_match_id"]] = {
            "tournament_id": t["id"],
            "is_qualifier": True,
            "round_label": "Qualifier",
        }
        match_ids = _get_weekend_match_ids(t)
        labels = _get_round_labels(len(match_ids))
        for i, mid in enumerate(match_ids):
            tags[mid] = {
                "tournament_id": t["id"],
                "is_qualifier": False,
                "round_label": labels.get(i + 1, f"Round {i + 1}"),
            }
    return tags


# ──────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────

def _build_tournament_response(db, tournament) -> dict:
    """Build full tournament response with brackets and match info."""
    t = tournament
    weekend_match_ids = _get_weekend_match_ids(t)
    num_rounds = _get_tournament_num_rounds(t) or len(weekend_match_ids)
    all_match_ids = [t["qualifying_match_id"]] + weekend_match_ids

    # Fetch match info
    placeholders = ",".join("?" * len(all_match_ids))
    match_rows = db.execute(
        f"SELECT id, team1, team2, match_date, match_time, status FROM matches WHERE id IN ({placeholders})",
        all_match_ids,
    ).fetchall()
    matches_info = {
        str(m["id"]): {
            "team1": m["team1"], "team2": m["team2"],
            "match_date": m["match_date"], "match_time": m["match_time"],
            "status": m["status"] or "future",
        }
        for m in match_rows
    }

    # Fetch brackets
    brackets = db.execute(
        """
        SELECT wtb.*, u1.name AS user1_name, u2.name AS user2_name, uw.name AS winner_name
        FROM weekend_tournament_brackets wtb
        LEFT JOIN users u1 ON u1.id = wtb.user1_id
        LEFT JOIN users u2 ON u2.id = wtb.user2_id
        LEFT JOIN users uw ON uw.id = wtb.winner_user_id
        WHERE wtb.tournament_id = ?
        ORDER BY wtb.round, wtb.match_position
        """,
        (t["id"],),
    ).fetchall()

    # Group brackets by round
    round_labels = _get_round_labels(num_rounds)
    rounds_data = {}
    for b in brackets:
        r = b["round"]
        if r not in rounds_data:
            rounds_data[r] = {
                "round": r,
                "round_label": round_labels.get(r, f"Round {r}"),
                "match_id": b["match_id"],
                "matchups": [],
            }
        rounds_data[r]["matchups"].append({
            "position": b["match_position"],
            "user1": {"id": b["user1_id"], "name": b["user1_name"]} if b["user1_id"] else None,
            "user2": {"id": b["user2_id"], "name": b["user2_name"]} if b["user2_id"] else None,
            "user1_points": b["user1_points"] or 0,
            "user2_points": b["user2_points"] or 0,
            "winner_user_id": b["winner_user_id"],
            "status": b["status"],
        })

    # Get qualifiers list (from qualifier match points)
    qualifiers = []
    if t["status"] in ("active", "completed"):
        qualifier_results = _get_match_contestant_points(db, t["qualifying_match_id"])
        # Get all user IDs that are in round 1 brackets
        bracket_user_ids = set()
        for b in brackets:
            if b["round"] == 1:
                if b["user1_id"]:
                    bracket_user_ids.add(b["user1_id"])
                if b["user2_id"]:
                    bracket_user_ids.add(b["user2_id"])

        seed = 1
        for entry in qualifier_results:
            if entry["user_id"] in bracket_user_ids:
                qualifiers.append({
                    "user_id": entry["user_id"],
                    "name": entry["name"],
                    "qualifying_points": entry["points"],
                    "seed": seed,
                })
                seed += 1
        # Add backfilled users not in qualifier results
        for uid in bracket_user_ids:
            if not any(q["user_id"] == uid for q in qualifiers):
                user_row = db.execute("SELECT name FROM users WHERE id = ?", (uid,)).fetchone()
                qualifiers.append({
                    "user_id": uid,
                    "name": user_row["name"] if user_row else "Unknown",
                    "qualifying_points": 0,
                    "seed": seed,
                    "backfilled": True,
                })
                seed += 1

    # Winner info
    winner = None
    if t["winner_user_id"]:
        w_row = db.execute("SELECT name FROM users WHERE id = ?", (t["winner_user_id"],)).fetchone()
        winner = {"user_id": t["winner_user_id"], "name": w_row["name"] if w_row else "Unknown"}

    return {
        "id": t["id"],
        "status": t["status"],
        "qualifying_match_id": t["qualifying_match_id"],
        "weekend_match_ids": weekend_match_ids,
        "num_rounds": num_rounds,
        "winner": winner,
        "matches": matches_info,
        "qualifiers": qualifiers,
        "brackets": [rounds_data[r] for r in sorted(rounds_data.keys())],
    }


def _get_match_contestant_points(db, match_id: int) -> list[dict]:
    """Get contestant fantasy points for a match, sorted descending.

    Always computes on-the-fly from user_teams + player_points to avoid
    stale/incomplete data in the contestant_points cache table.
    """
    team_rows = db.execute(
        """
        SELECT u.id AS user_id, u.name, ut.player_id,
               ut.is_captain, ut.is_vice_captain,
               COALESCE(pp.points, 0) AS player_points
        FROM user_teams ut
        JOIN users u ON u.id = ut.user_id
        LEFT JOIN player_points pp ON pp.match_id = ut.match_id AND pp.player_id = ut.player_id
        WHERE ut.match_id = ? AND u.is_active = 1
        """,
        (match_id,),
    ).fetchall()

    totals: dict[int, dict] = {}
    for row in team_rows:
        uid = row["user_id"]
        entry = totals.setdefault(uid, {"user_id": uid, "name": row["name"], "points": 0.0})
        pts = float(row["player_points"] or 0)
        if row["is_captain"]:
            pts *= 2.0
        elif row["is_vice_captain"]:
            pts *= 1.5
        entry["points"] += pts

    result = list(totals.values())
    for r in result:
        r["points"] = round(r["points"], 2)
    result.sort(key=lambda x: (-x["points"], x["name"]))
    return result


def _get_leaderboard_backfill(db, exclude_ids: set[int], needed: int) -> list[dict]:
    """Get users from overall leaderboard to fill remaining bracket slots."""
    rows = db.execute(
        """
        SELECT u.id AS user_id, u.name, COALESCE(SUM(cp.points), 0) AS total_points
        FROM users u
        LEFT JOIN contestant_points cp ON cp.user_id = u.id
        WHERE u.is_active = 1
        GROUP BY u.id, u.name
        ORDER BY total_points DESC
        """
    ).fetchall()

    result = []
    for r in rows:
        if r["user_id"] in exclude_ids:
            continue
        result.append({
            "user_id": r["user_id"],
            "name": r["name"],
            "qualifying_points": 0,
            "backfilled": True,
        })
        if len(result) >= needed:
            break
    return result


def _get_leaderboard_ranks(db) -> dict[int, int]:
    """Get user_id -> overall leaderboard rank mapping."""
    rows = db.execute(
        """
        SELECT u.id, COALESCE(SUM(cp.points), 0) AS total
        FROM users u
        LEFT JOIN contestant_points cp ON cp.user_id = u.id
        WHERE u.is_active = 1
        GROUP BY u.id
        ORDER BY total DESC
        """
    ).fetchall()
    ranks = {}
    for i, r in enumerate(rows):
        ranks[r["id"]] = i + 1
    return ranks


def _get_round_for_match(tournament, match_id: int) -> int | None:
    """Determine which round number a match_id corresponds to."""
    match_ids = _get_weekend_match_ids(tournament)
    for i, mid in enumerate(match_ids):
        if mid == match_id:
            return i + 1
    return None
