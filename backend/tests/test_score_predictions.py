"""
Tests for the Score Prediction feature.

Tests the core bonus computation logic:
- Exact match ->+500
- Within ±5 ->+200
- Within ±10 ->+100
- Tier evaluation (highest tier wins, lower tiers get remaining users)
- Ties (same diff) ->all tied users get full bonus
- No bonus when diff > 10
- Edge cases: no predictions, no actual points, partial predictions
"""

import os
import sys
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

def setup_test_db():
    """Create a fresh in-memory SQLite DB with required schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    _last_conn = conn

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
            status TEXT DEFAULT 'future'
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
        CREATE TABLE score_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            match_id INTEGER NOT NULL REFERENCES matches(id),
            predicted_points REAL NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, match_id)
        );
    """)
    conn.commit()
    return conn


def seed_users(conn, count=5):
    for i in range(1, count + 1):
        conn.execute(
            "INSERT INTO users (firebase_uid, email, name) VALUES (?, ?, ?)",
            (f"uid_{i}", f"user{i}@test.com", f"User{i}"),
        )
    conn.commit()


def seed_match(conn, match_id=1):
    conn.execute(
        "INSERT INTO matches (id, team1, team2, match_date, match_time, status) VALUES (?, ?, ?, ?, ?, ?)",
        (match_id, "CSK", "MI", "2026-05-01", "19:30", "completed"),
    )
    conn.commit()


def set_contestant_points(conn, match_id, user_points: dict):
    """user_points: {user_id: points}"""
    for uid, pts in user_points.items():
        conn.execute(
            "INSERT INTO contestant_points (user_id, match_id, points, last_updated) VALUES (?, ?, ?, '2026-05-01 23:00')",
            (uid, match_id, pts),
        )
    conn.commit()


def set_predictions(conn, match_id, user_predictions: dict):
    """user_predictions: {user_id: predicted_points}"""
    for uid, pred in user_predictions.items():
        conn.execute(
            "INSERT INTO score_predictions (user_id, match_id, predicted_points, created_at) VALUES (?, ?, ?, '2026-05-01 18:00')",
            (uid, match_id, pred),
        )
    conn.commit()


def patch_db(conn):
    """Monkey-patch data_service.get_db to return our test connection."""
    import backend.services.data_service as ds
    ds.get_db = lambda: conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_exact_prediction():
    """User predicts the exact score ->+500."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})
    set_predictions(conn, 1, {1: 350.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert 1 in bonuses, "User 1 should get a bonus"
    assert bonuses[1]["bonus"] == 500, f"Expected 500, got {bonuses[1]['bonus']}"
    assert bonuses[1]["label"] == "Perfect Strike"
    assert bonuses[1]["diff"] == 0
    print("  PASS: exact prediction ->+500")


def test_near_exact_half_point():
    """Predicted 500, actual 499.5 (diff=0.5) -> Perfect Strike +500."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 499.5})
    set_predictions(conn, 1, {1: 500.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert 1 in bonuses, "User 1 should get Perfect Strike (diff=0.5)"
    assert bonuses[1]["bonus"] == 500, f"Expected 500, got {bonuses[1]['bonus']}"
    assert bonuses[1]["label"] == "Perfect Strike"
    print("  PASS: diff=0.5 -> Perfect Strike +500")


def test_just_over_half_point():
    """Predicted 500, actual 499 (diff=1) -> NOT Perfect Strike, falls to tier 2."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 499.0})
    set_predictions(conn, 1, {1: 500.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert 1 in bonuses, "User 1 should get Elite Precision (diff=1)"
    assert bonuses[1]["bonus"] == 200, f"Expected 200, got {bonuses[1]['bonus']}"
    assert bonuses[1]["label"] == "Elite Precision"
    print("  PASS: diff=1 -> Elite Precision +200 (not Perfect Strike)")


def test_within_5():
    """User predicts within ±5 ->+200."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})
    set_predictions(conn, 1, {1: 353.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert 1 in bonuses
    assert bonuses[1]["bonus"] == 200, f"Expected 200, got {bonuses[1]['bonus']}"
    assert bonuses[1]["label"] == "Elite Precision"
    print("  PASS: within ±5 ->+200")


def test_within_10():
    """User predicts within ±10 ->+100."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})
    set_predictions(conn, 1, {1: 358.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert 1 in bonuses
    assert bonuses[1]["bonus"] == 100, f"Expected 100, got {bonuses[1]['bonus']}"
    assert bonuses[1]["label"] == "Great Call"
    print("  PASS: within ±10 ->+100")


def test_no_bonus_outside_range():
    """Prediction > 10 away ->no bonus."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})
    set_predictions(conn, 1, {1: 400.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert 1 not in bonuses, "User 1 should NOT get a bonus (diff=50)"
    print("  PASS: diff > 10 ->no bonus")


def test_tier_priority():
    """First tier with eligible users wins - no lower tiers evaluated.

    User A: exact (diff=0) -> +500 (tier 1 wins, stop)
    User B: diff=3 -> no bonus (tier 2 not evaluated)
    User C: diff=8 -> no bonus (tier 3 not evaluated)
    """
    conn = setup_test_db()
    seed_users(conn, 3)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0, 2: 350.0, 3: 350.0})
    set_predictions(conn, 1, {1: 350.0, 2: 353.0, 3: 358.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert bonuses[1]["bonus"] == 500, f"User1: expected 500, got {bonuses[1]['bonus']}"
    assert 2 not in bonuses, "User2 should NOT get bonus (tier 1 already awarded)"
    assert 3 not in bonuses, "User3 should NOT get bonus (tier 1 already awarded)"
    print("  PASS: tier priority - first tier wins, rest skipped")


def test_tie_same_diff_get_full_bonus():
    """Two users with same diff within a tier both get full bonus."""
    conn = setup_test_db()
    seed_users(conn, 2)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0, 2: 350.0})
    set_predictions(conn, 1, {1: 353.0, 2: 347.0})  # both diff=3
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert bonuses[1]["bonus"] == 200, f"User1: expected 200, got {bonuses[1]['bonus']}"
    assert bonuses[2]["bonus"] == 200, f"User2: expected 200, got {bonuses[2]['bonus']}"
    print("  PASS: tied users both get full bonus")


def test_closest_in_tier_wins():
    """Within a tier, only the closest user wins (not all in range).

    User A: diff=2 ->wins +200
    User B: diff=4 ->in range but not closest ->removed, no bonus
    """
    conn = setup_test_db()
    seed_users(conn, 2)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0, 2: 350.0})
    set_predictions(conn, 1, {1: 352.0, 2: 354.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert bonuses[1]["bonus"] == 200, f"User1: expected 200 (closest), got {bonuses[1]['bonus']}"
    assert 2 not in bonuses, "User2 should NOT get a bonus (not closest in tier)"
    print("  PASS: closest in tier wins, others removed")


def test_no_predictions():
    """No predictions for a match ->empty result."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert len(bonuses) == 0, "No predictions ->no bonuses"
    print("  PASS: no predictions ->empty")


def test_no_actual_points():
    """Predictions exist but no contestant_points yet ->empty result."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_predictions(conn, 1, {1: 350.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert len(bonuses) == 0, "No actual points ->no bonuses"
    print("  PASS: no actual points ->empty")


def test_user_predicted_but_didnt_play():
    """User has prediction but no contestant_points entry ->skipped."""
    conn = setup_test_db()
    seed_users(conn, 2)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})  # only user 1 played
    set_predictions(conn, 1, {1: 350.0, 2: 350.0})  # both predicted
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert 1 in bonuses, "User1 (played + predicted) should get bonus"
    assert 2 not in bonuses, "User2 (predicted but didn't play) should NOT get bonus"
    print("  PASS: predicted but didn't play ->skipped")


def test_negative_diff():
    """Prediction below actual (negative direction) still uses abs diff."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})
    set_predictions(conn, 1, {1: 345.0})  # diff = 5
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert bonuses[1]["bonus"] == 200, f"Expected 200 (diff=5), got {bonuses[1]['bonus']}"
    print("  PASS: negative diff uses abs ->±5 = +200")


def test_boundary_exactly_5():
    """Prediction exactly 5 away ->Elite Precision (+200)."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})
    set_predictions(conn, 1, {1: 355.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert bonuses[1]["bonus"] == 200, f"Expected 200 (diff=5 boundary), got {bonuses[1]['bonus']}"
    print("  PASS: exactly 5 away ->+200")


def test_boundary_exactly_10():
    """Prediction exactly 10 away ->Great Call (+100)."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})
    set_predictions(conn, 1, {1: 360.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert bonuses[1]["bonus"] == 100, f"Expected 100 (diff=10 boundary), got {bonuses[1]['bonus']}"
    print("  PASS: exactly 10 away ->+100")


def test_boundary_just_over_10():
    """Prediction 10.5 away ->no bonus."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0})
    set_predictions(conn, 1, {1: 360.5})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert 1 not in bonuses, "diff=10.5 should NOT get a bonus"
    print("  PASS: diff=10.5 ->no bonus")


def test_full_scenario():
    """Full 5-user scenario. Tier 1 (exact) has a winner -> only that user gets bonus.

    User A: predicted=350, actual=350, diff=0 -> +500 (exact, tier 1 wins, STOP)
    User B: predicted=353, actual=350, diff=3 -> no bonus (tier 2 not evaluated)
    User C: predicted=354, actual=350, diff=4 -> no bonus
    User D: predicted=358, actual=350, diff=8 -> no bonus
    User E: predicted=370, actual=350, diff=20 -> no bonus
    """
    conn = setup_test_db()
    seed_users(conn, 5)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0, 2: 350.0, 3: 350.0, 4: 350.0, 5: 350.0})
    set_predictions(conn, 1, {1: 350.0, 2: 353.0, 3: 354.0, 4: 358.0, 5: 370.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert bonuses[1]["bonus"] == 500, f"User A: expected 500, got {bonuses[1]['bonus']}"
    assert 2 not in bonuses, "User B: should NOT get bonus (tier 1 already awarded)"
    assert 3 not in bonuses, "User C: should NOT get bonus"
    assert 4 not in bonuses, "User D: should NOT get bonus"
    assert 5 not in bonuses, "User E: should NOT get bonus (diff=20)"
    print("  PASS: full scenario - exact match wins, all others skipped")


def test_tier2_wins_when_no_exact():
    """No exact match -> tier 2 (+-5) evaluated. Closest wins, rest get nothing.

    User A: diff=3 -> +200 (closest in +-5, tier 2 wins, STOP)
    User B: diff=4 -> no bonus (not closest)
    User C: diff=8 -> no bonus (tier 3 not evaluated)
    """
    conn = setup_test_db()
    seed_users(conn, 3)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0, 2: 350.0, 3: 350.0})
    set_predictions(conn, 1, {1: 353.0, 2: 354.0, 3: 358.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert bonuses[1]["bonus"] == 200, f"User A: expected 200, got {bonuses[1]['bonus']}"
    assert 2 not in bonuses, "User B: should NOT get bonus (not closest in tier 2)"
    assert 3 not in bonuses, "User C: should NOT get bonus (tier 3 not evaluated)"
    print("  PASS: tier 2 wins when no exact, lower tiers skipped")


def test_tier3_wins_when_no_higher():
    """No one within +-5 -> tier 3 (+-10) evaluated.

    User A: diff=8 -> +100 (tier 3 wins)
    User B: diff=20 -> no bonus
    """
    conn = setup_test_db()
    seed_users(conn, 2)
    seed_match(conn)
    set_contestant_points(conn, 1, {1: 350.0, 2: 350.0})
    set_predictions(conn, 1, {1: 358.0, 2: 370.0})
    patch_db(conn)

    from backend.services.data_service import compute_prediction_bonuses
    bonuses = compute_prediction_bonuses(1)

    assert bonuses[1]["bonus"] == 100, f"User A: expected 100, got {bonuses[1]['bonus']}"
    assert 2 not in bonuses, "User B: should NOT get bonus (diff=20)"
    print("  PASS: tier 3 wins when no higher tier matches")


def test_save_and_read_prediction():
    """Test save_score_prediction and get_score_prediction round-trip."""
    conn = setup_test_db()
    seed_users(conn, 1)
    seed_match(conn)
    patch_db(conn)

    from backend.services.data_service import save_score_prediction, get_score_prediction

    # Initially no prediction
    assert get_score_prediction(1, 1) is None

    # Save prediction
    save_score_prediction(1, 1, 350.5)
    result = get_score_prediction(1, 1)
    assert result == 350.5, f"Expected 350.5, got {result}"

    # Update prediction (UPSERT)
    save_score_prediction(1, 1, 400.0)
    result = get_score_prediction(1, 1)
    assert result == 400.0, f"Expected 400.0 after update, got {result}"

    print("  PASS: save/read/update prediction round-trip")


def test_get_match_predictions():
    """Test get_match_predictions returns all predictions for a match."""
    conn = setup_test_db()
    seed_users(conn, 3)
    seed_match(conn)
    set_predictions(conn, 1, {1: 300.0, 2: 350.0, 3: 400.0})
    patch_db(conn)

    from backend.services.data_service import get_match_predictions
    preds = get_match_predictions(1)

    assert len(preds) == 3
    assert preds[1] == 300.0
    assert preds[2] == 350.0
    assert preds[3] == 400.0
    print("  PASS: get_match_predictions returns all")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_save_and_read_prediction,
        test_get_match_predictions,
        test_exact_prediction,
        test_near_exact_half_point,
        test_just_over_half_point,
        test_within_5,
        test_within_10,
        test_no_bonus_outside_range,
        test_tier_priority,
        test_tie_same_diff_get_full_bonus,
        test_closest_in_tier_wins,
        test_no_predictions,
        test_no_actual_points,
        test_user_predicted_but_didnt_play,
        test_negative_diff,
        test_boundary_exactly_5,
        test_boundary_exactly_10,
        test_boundary_just_over_10,
        test_full_scenario,
        test_tier2_wins_when_no_exact,
        test_tier3_wins_when_no_higher,
    ]

    print(f"\nRunning {len(tests)} prediction tests...\n")
    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed:
        sys.exit(1)
    else:
        print("All tests passed!")
