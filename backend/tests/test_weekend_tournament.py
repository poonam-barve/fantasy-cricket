"""
End-to-end test for the Weekend Battle feature.

Simulates a realistic scenario:
- Seed users, players, matches for a weekend with 4 matches + a qualifier
- Users submit teams and score points in the qualifier
- Verify detection, seeding, bracket creation, round advancement, and winner
"""

import os
import sys
import sqlite3
import random
from datetime import datetime, timedelta

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

DB_PATH = os.path.join(os.path.dirname(__file__), "test_weekend.db")


def setup_test_db():
    """Create a fresh in-memory-like SQLite DB with full schema."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            mobile TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE players (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            team TEXT NOT NULL,
            role TEXT NOT NULL,
            aliases TEXT DEFAULT ''
        );
        CREATE TABLE matches (
            id INTEGER PRIMARY KEY,
            team1 TEXT NOT NULL,
            team2 TEXT NOT NULL,
            match_date TEXT NOT NULL,
            match_time TEXT NOT NULL,
            status TEXT DEFAULT 'future',
            venue TEXT DEFAULT NULL
        );
        CREATE TABLE user_teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            match_id INTEGER NOT NULL REFERENCES matches(id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            is_captain INTEGER NOT NULL DEFAULT 0,
            is_vice_captain INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT,
            UNIQUE(user_id, match_id, player_id)
        );
        CREATE TABLE contestant_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            match_id INTEGER NOT NULL REFERENCES matches(id),
            points REAL NOT NULL DEFAULT 0,
            last_updated TEXT NOT NULL,
            UNIQUE(user_id, match_id)
        );
        CREATE TABLE player_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL REFERENCES matches(id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            player_name TEXT NOT NULL,
            team TEXT NOT NULL,
            role TEXT NOT NULL,
            points REAL NOT NULL DEFAULT 0,
            last_updated TEXT NOT NULL,
            UNIQUE(match_id, player_id)
        );
        CREATE TABLE weekend_tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qualifying_match_id INTEGER NOT NULL REFERENCES matches(id),
            weekend_match_1_id INTEGER NOT NULL REFERENCES matches(id),
            weekend_match_2_id INTEGER NOT NULL REFERENCES matches(id),
            weekend_match_3_id INTEGER NOT NULL REFERENCES matches(id),
            weekend_match_4_id INTEGER NOT NULL REFERENCES matches(id),
            status TEXT NOT NULL DEFAULT 'pending',
            winner_user_id INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(qualifying_match_id)
        );
        CREATE TABLE weekend_tournament_brackets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL REFERENCES weekend_tournaments(id),
            round INTEGER NOT NULL,
            match_position INTEGER NOT NULL,
            match_id INTEGER NOT NULL REFERENCES matches(id),
            user1_id INTEGER REFERENCES users(id),
            user2_id INTEGER REFERENCES users(id),
            user1_points REAL DEFAULT 0,
            user2_points REAL DEFAULT 0,
            winner_user_id INTEGER REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'pending',
            UNIQUE(tournament_id, round, match_position)
        );
    """)
    conn.commit()
    return conn


def seed_data(conn):
    """Seed 16 users, some players, and 5 matches (1 Fri qualifier + 2 Sat + 2 Sun)."""
    # Create 16 users
    for i in range(1, 17):
        conn.execute(
            "INSERT INTO users (firebase_uid, email, name) VALUES (?, ?, ?)",
            (f"uid_{i}", f"user{i}@test.com", f"Player{i}"),
        )

    # Create some players (we need at least 11 per team for team selection)
    for i in range(1, 23):
        team = "CSK" if i <= 11 else "MI"
        conn.execute(
            "INSERT INTO players (id, name, team, role) VALUES (?, ?, ?, ?)",
            (i, f"Cricketer{i}", team, "Batter"),
        )

    # Find next weekend (Saturday)
    today = datetime.now()
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    saturday = today + timedelta(days=days_until_saturday)
    friday = saturday - timedelta(days=1)
    sunday = saturday + timedelta(days=1)

    fri_str = friday.strftime("%Y-%m-%d")
    sat_str = saturday.strftime("%Y-%m-%d")
    sun_str = sunday.strftime("%Y-%m-%d")

    # Match 1: Friday qualifier
    conn.execute(
        "INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
        (101, "CSK", "MI", fri_str, "19:30", "completed"),
    )
    # Match 2-3: Saturday (2 matches)
    conn.execute(
        "INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
        (102, "RCB", "KKR", sat_str, "15:30", "completed"),
    )
    conn.execute(
        "INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
        (103, "DC", "RR", sat_str, "19:30", "completed"),
    )
    # Match 4-5: Sunday (2 matches)
    conn.execute(
        "INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
        (104, "GT", "LSG", sun_str, "15:30", "completed"),
    )
    conn.execute(
        "INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
        (105, "PBKS", "SRH", sun_str, "19:30", "completed"),
    )

    # Simulate contestant_points for the qualifier (match 101)
    # All 16 users participated with varying points
    for i in range(1, 17):
        pts = 400 - (i * 20) + random.randint(-5, 5)  # ~380, 360, 340, ...
        conn.execute(
            "INSERT INTO contestant_points (user_id, match_id, points, last_updated) VALUES (?, ?, ?, ?)",
            (i, 101, pts, datetime.now().isoformat()),
        )

    conn.commit()
    return {
        "friday": fri_str,
        "saturday": sat_str,
        "sunday": sun_str,
        "qualifier_id": 101,
        "weekend_ids": [102, 103, 104, 105],
    }


def simulate_match_points(conn, match_id, user_ids):
    """Simulate random contestant points for a match for given users."""
    for uid in user_ids:
        pts = round(random.uniform(100, 400), 2)
        conn.execute(
            "INSERT OR REPLACE INTO contestant_points (user_id, match_id, points, last_updated) VALUES (?, ?, ?, ?)",
            (uid, match_id, pts, datetime.now().isoformat()),
        )
    conn.commit()


def patch_get_db(conn):
    """Monkey-patch get_db to return our test connection."""
    import backend.database as db_module
    db_module.get_db = lambda: conn


def run_tests():
    print("=" * 60)
    print("WEEKEND BATTLE — END-TO-END TEST")
    print("=" * 60)

    random.seed(42)  # Deterministic for reproducibility
    conn = setup_test_db()
    dates = seed_data(conn)
    patch_get_db(conn)

    from backend.services import weekend_tournament_service as wts

    # ──────────────────────────────────────────
    # TEST 1: Weekend Detection
    # ──────────────────────────────────────────
    print("\n[TEST 1] Weekend Detection")
    created = wts.detect_and_create_tournaments()
    assert len(created) == 1, f"Expected 1 tournament, got {len(created)}"
    tournament_id = created[0]
    print(f"  PASS — Tournament #{tournament_id} created")

    # Verify tournament record
    t = conn.execute("SELECT * FROM weekend_tournaments WHERE id = ?", (tournament_id,)).fetchone()
    assert t["qualifying_match_id"] == 101, f"Qualifier should be M101, got M{t['qualifying_match_id']}"
    assert t["weekend_match_1_id"] == 102
    assert t["weekend_match_2_id"] == 103
    assert t["weekend_match_3_id"] == 104
    assert t["weekend_match_4_id"] == 105
    assert t["status"] == "pending"
    print(f"  PASS — Qualifier=M101, Weekend=M102-105, Status=pending")

    # Idempotent: running again should not create duplicates
    created_again = wts.detect_and_create_tournaments()
    assert len(created_again) == 0, "Detection should be idempotent"
    print(f"  PASS — Idempotent (no duplicates)")

    # ──────────────────────────────────────────
    # TEST 2: Bracket Seeding
    # ──────────────────────────────────────────
    print("\n[TEST 2] Bracket Seeding (after qualifier completes)")
    result = wts.seed_bracket(tournament_id)
    assert "error" not in result, f"Seeding failed: {result}"
    assert result["players"] == 16, f"Expected 16 players, got {result['players']}"
    assert result["matchups"] == 8, f"Expected 8 matchups, got {result['matchups']}"
    print(f"  PASS — 16 players, 8 matchups in Round of 16")

    # Verify brackets in DB
    brackets_r1 = conn.execute(
        "SELECT * FROM weekend_tournament_brackets WHERE tournament_id = ? AND round = 1 ORDER BY match_position",
        (tournament_id,),
    ).fetchall()
    assert len(brackets_r1) == 8, f"Expected 8 R1 brackets, got {len(brackets_r1)}"

    # All 16 users should appear exactly once
    all_users = set()
    for b in brackets_r1:
        all_users.add(b["user1_id"])
        all_users.add(b["user2_id"])
        assert b["match_id"] == 102, f"R1 should use M102, got M{b['match_id']}"
        assert b["status"] == "pending"
    assert len(all_users) == 16, f"Expected 16 unique users, got {len(all_users)}"
    print(f"  PASS — All 16 users in bracket, all using M102")

    # Tournament should now be active
    t = conn.execute("SELECT status FROM weekend_tournaments WHERE id = ?", (tournament_id,)).fetchone()
    assert t["status"] == "active", f"Expected 'active', got '{t['status']}'"
    print(f"  PASS — Tournament status = active")

    # ──────────────────────────────────────────
    # TEST 3: Round 1 (Ro16) — Advance
    # ──────────────────────────────────────────
    print("\n[TEST 3] Round 1 — Round of 16 (M102)")
    r1_user_ids = list(all_users)
    simulate_match_points(conn, 102, r1_user_ids)

    result = wts.advance_round(tournament_id, 102)
    assert result.get("status") == "advanced", f"Expected 'advanced', got {result}"
    assert result["round"] == 2, f"Expected next round 2, got {result['round']}"
    assert result["matchups"] == 4, f"Expected 4 QF matchups, got {result['matchups']}"
    print(f"  PASS — 8 winners advanced to QF, 4 matchups")

    # Verify R1 brackets all completed with winners
    r1_done = conn.execute(
        "SELECT * FROM weekend_tournament_brackets WHERE tournament_id = ? AND round = 1",
        (tournament_id,),
    ).fetchall()
    for b in r1_done:
        assert b["status"] == "completed", f"R1 bracket {b['match_position']} not completed"
        assert b["winner_user_id"] is not None, f"R1 bracket {b['match_position']} has no winner"
    r1_winners = {b["winner_user_id"] for b in r1_done}
    assert len(r1_winners) == 8, f"Expected 8 R1 winners, got {len(r1_winners)}"
    print(f"  PASS — All R1 brackets completed with 8 unique winners")

    # Verify R2 brackets created
    brackets_r2 = conn.execute(
        "SELECT * FROM weekend_tournament_brackets WHERE tournament_id = ? AND round = 2",
        (tournament_id,),
    ).fetchall()
    assert len(brackets_r2) == 4
    r2_users = set()
    for b in brackets_r2:
        r2_users.add(b["user1_id"])
        r2_users.add(b["user2_id"])
        assert b["match_id"] == 103, f"R2 should use M103"
    assert r2_users == r1_winners, "R2 users should be R1 winners"
    print(f"  PASS — QF brackets created with R1 winners, using M103")

    # ──────────────────────────────────────────
    # TEST 4: Round 2 (QF) — Advance
    # ──────────────────────────────────────────
    print("\n[TEST 4] Round 2 — Quarter Finals (M103)")
    simulate_match_points(conn, 103, list(r2_users))
    result = wts.advance_round(tournament_id, 103)
    assert result["status"] == "advanced"
    assert result["round"] == 3
    assert result["matchups"] == 2
    print(f"  PASS — 4 winners advanced to SF, 2 matchups")

    brackets_r3 = conn.execute(
        "SELECT * FROM weekend_tournament_brackets WHERE tournament_id = ? AND round = 3",
        (tournament_id,),
    ).fetchall()
    assert len(brackets_r3) == 2
    r3_users = set()
    for b in brackets_r3:
        r3_users.add(b["user1_id"])
        r3_users.add(b["user2_id"])
        assert b["match_id"] == 104
    assert len(r3_users) == 4
    print(f"  PASS — SF brackets created with 4 players, using M104")

    # ──────────────────────────────────────────
    # TEST 5: Round 3 (SF) — Advance
    # ──────────────────────────────────────────
    print("\n[TEST 5] Round 3 — Semi Finals (M104)")
    simulate_match_points(conn, 104, list(r3_users))
    result = wts.advance_round(tournament_id, 104)
    assert result["status"] == "advanced"
    assert result["round"] == 4
    assert result["matchups"] == 1
    print(f"  PASS — 2 finalists, 1 matchup")

    brackets_r4 = conn.execute(
        "SELECT * FROM weekend_tournament_brackets WHERE tournament_id = ? AND round = 4",
        (tournament_id,),
    ).fetchall()
    assert len(brackets_r4) == 1
    assert brackets_r4[0]["match_id"] == 105
    finalist_1 = brackets_r4[0]["user1_id"]
    finalist_2 = brackets_r4[0]["user2_id"]
    print(f"  PASS — Final: User#{finalist_1} vs User#{finalist_2}, using M105")

    # ──────────────────────────────────────────
    # TEST 6: Round 4 (Final) — Winner
    # ──────────────────────────────────────────
    print("\n[TEST 6] Round 4 — Final (M105)")
    simulate_match_points(conn, 105, [finalist_1, finalist_2])
    result = wts.advance_round(tournament_id, 105)
    assert result["status"] == "completed", f"Expected 'completed', got {result}"
    winner_id = result["winner_user_id"]
    assert winner_id in (finalist_1, finalist_2)
    print(f"  PASS — Tournament completed! Winner: User#{winner_id}")

    # Verify tournament record
    t = conn.execute("SELECT * FROM weekend_tournaments WHERE id = ?", (tournament_id,)).fetchone()
    assert t["status"] == "completed"
    assert t["winner_user_id"] == winner_id
    winner_name = conn.execute("SELECT name FROM users WHERE id = ?", (winner_id,)).fetchone()["name"]
    print(f"  PASS — DB: status=completed, winner={winner_name}")

    # ──────────────────────────────────────────
    # TEST 7: API Queries
    # ──────────────────────────────────────────
    print("\n[TEST 7] Query APIs")

    current = wts.get_current_tournament()
    assert current is not None
    assert current["id"] == tournament_id
    assert current["status"] == "completed"
    assert current["winner"]["user_id"] == winner_id
    assert len(current["brackets"]) == 4  # 4 rounds
    assert len(current["qualifiers"]) == 16
    print(f"  PASS — get_current_tournament() returns full data with 4 rounds, 16 qualifiers")

    by_id = wts.get_tournament_by_id(tournament_id)
    assert by_id is not None
    assert by_id["id"] == tournament_id
    print(f"  PASS — get_tournament_by_id() works")

    history = wts.get_tournament_history()
    assert len(history) == 1
    assert history[0]["winner"]["user_id"] == winner_id
    print(f"  PASS — get_tournament_history() returns 1 completed tournament")

    # Tags only return for pending/qualifying/active tournaments (completed are excluded)
    # Temporarily set back to active to test tags
    conn.execute("UPDATE weekend_tournaments SET status = 'active' WHERE id = ?", (tournament_id,))
    conn.commit()
    tags = wts.get_tournament_match_tags()
    assert 101 in tags
    assert tags[101]["is_qualifier"] is True
    assert tags[102]["round_label"] == "Round of 16"
    assert tags[103]["round_label"] == "Quarter Finals"
    assert tags[104]["round_label"] == "Semi Finals"
    assert tags[105]["round_label"] == "Final"
    conn.execute("UPDATE weekend_tournaments SET status = 'completed' WHERE id = ?", (tournament_id,))
    conn.commit()
    print(f"  PASS — get_tournament_match_tags() correct for all 5 matches")

    # ──────────────────────────────────────────
    # TEST 8: on_match_completed hook
    # ──────────────────────────────────────────
    print("\n[TEST 8] on_match_completed hook (idempotent)")
    # Calling on already-completed tournament should not crash
    wts.on_match_completed(101)  # qualifier already processed
    wts.on_match_completed(105)  # final already processed
    wts.on_match_completed(999)  # non-existent match
    print(f"  PASS — Hook is safe to call on completed/unknown matches")

    # ──────────────────────────────────────────
    # TEST 9: Bracket integrity
    # ──────────────────────────────────────────
    print("\n[TEST 9] Bracket integrity check")
    all_brackets = conn.execute(
        "SELECT * FROM weekend_tournament_brackets WHERE tournament_id = ? ORDER BY round, match_position",
        (tournament_id,),
    ).fetchall()

    # Count: 8 (R1) + 4 (R2) + 2 (R3) + 1 (R4) = 15
    assert len(all_brackets) == 15, f"Expected 15 total brackets, got {len(all_brackets)}"

    # All should be completed
    for b in all_brackets:
        assert b["status"] == "completed"
        assert b["winner_user_id"] is not None

    # Verify winner progressed through all rounds
    winner_appeared = sum(
        1 for b in all_brackets
        if b["winner_user_id"] == winner_id or b["user1_id"] == winner_id or b["user2_id"] == winner_id
    )
    assert winner_appeared >= 4, f"Winner should appear in at least 4 brackets (won all), appeared in {winner_appeared}"
    print(f"  PASS — 15 brackets total, all completed, winner in {winner_appeared} brackets")

    # ──────────────────────────────────────────
    # TEST 10: Less than 16 participants
    # ──────────────────────────────────────────
    print("\n[TEST 10] Backfill test (fewer than 16 qualifier participants)")
    # Create a new weekend
    sat2 = (datetime.strptime(dates["saturday"], "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d")
    fri2 = (datetime.strptime(sat2, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    sun2 = (datetime.strptime(sat2, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    conn.execute("INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
                 (201, "CSK", "RCB", fri2, "19:30", "completed"))
    conn.execute("INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
                 (202, "MI", "KKR", sat2, "15:30", "future"))
    conn.execute("INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
                 (203, "DC", "GT", sat2, "19:30", "future"))
    conn.execute("INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
                 (204, "RR", "LSG", sun2, "15:30", "future"))
    conn.execute("INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
                 (205, "PBKS", "SRH", sun2, "19:30", "future"))

    # Only 8 users participated in qualifier
    for i in range(1, 9):
        conn.execute(
            "INSERT INTO contestant_points (user_id, match_id, points, last_updated) VALUES (?, ?, ?, ?)",
            (i, 201, 300 - i * 10, datetime.now().isoformat()),
        )
    conn.commit()

    created2 = wts.detect_and_create_tournaments()
    assert len(created2) == 1
    t2_id = created2[0]

    result2 = wts.seed_bracket(t2_id)
    assert "error" not in result2
    # Should have 16 players (8 from qualifier + 8 backfilled from leaderboard)
    assert result2["players"] == 16, f"Expected 16 (8+8 backfill), got {result2['players']}"
    assert result2["matchups"] == 8
    print(f"  PASS — 8 qualifier participants + 8 backfilled from leaderboard = 16 players")

    # Verify backfilled users are in brackets
    r1_brackets = conn.execute(
        "SELECT * FROM weekend_tournament_brackets WHERE tournament_id = ? AND round = 1",
        (t2_id,),
    ).fetchall()
    bracket_users = set()
    for b in r1_brackets:
        bracket_users.add(b["user1_id"])
        bracket_users.add(b["user2_id"])
    assert len(bracket_users) == 16
    # Users 9-16 should be backfilled (they didn't participate in M201)
    backfilled = bracket_users - set(range(1, 9))
    assert len(backfilled) == 8, f"Expected 8 backfilled users, got {len(backfilled)}"
    print(f"  PASS — Backfilled users: {sorted(backfilled)}")

    # Cleanup
    conn.close()
    os.remove(DB_PATH)

    print("\n" + "=" * 60)
    print("ALL 10 TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
