# Bug: Weekend Tournament Uses Stale/Incomplete contestant_points

**Date**: 2026-04-25  
**Severity**: High  
**Affected**: Match 35 (Round of 16, Tournament 4)  
**Status**: Open

---

## Summary

The weekend tournament `advance_round()` scored 1v1 matchups using stale/incomplete data from the `contestant_points` cache table. 6 of 16 players got 0 points (missing rows), 4 players got outdated mid-match values, and 3 matchup winners were incorrect — advancing the wrong players to Quarter Finals.

---

## Observed Impact (Match 35, Ro16)

| Player | Correct Points | contestant_points | Bracket Used | Issue |
|---|---|---|---|---|
| SuperQueenNinni | **1452.5** | missing | 0.0 | Should have won pos4 vs Sagar |
| Benzi | **1380.5** | missing | 0.0 | Should have won pos6 vs Ravi |
| EngineerBabu | **1363.5** | 1191.0 | 1191.0 | Stale by 172.5 |
| Rupesh | **1354.5** | 1180.5 | 1180.5 | Stale by 174.0 |
| Omkar | **1317.0** | missing | 0.0 | Got 0, tiebreak happened to pick correct winner |
| AkkiRocker | **1301.5** | 1199.0 | 1199.0 | Stale by 102.5 |
| Boisar Khiladi | **1287.5** | missing | 0.0 | Should have won pos5 vs EngineerBabu |
| Ironman | **1200.5** | 1152.0 | 1152.0 | Stale by 48.5 |
| Sejjol | **948.5** | missing | 0.0 | Got 0 |
| Cancelie | **1026.0** | missing | 0.0 | Got 0 |

**Wrong winners advanced:**

| Position | Bracket Result | Correct Result |
|---|---|---|
| pos3 | AkkiRocker (1199.0) beat Rupesh (1180.5) | **Rupesh** (1354.5) beats AkkiRocker (1301.5) |
| pos4 | Sagar (1089.5) beat SuperQueenNinni (0.0) | **SuperQueenNinni** (1452.5) beats Sagar (1089.5) |
| pos5 | EngineerBabu (1191.0) beat Boisar Khiladi (0.0) | **Boisar Khiladi** (1287.5) beats EngineerBabu (1363.5) — actually EngineerBabu still wins with correct points |
| pos6 | Ravi (1168.5) beat Benzi (0.0) | **Benzi** (1380.5) beats Ravi (1168.5) |

---

## Root Cause

### The Timeline

```
Match 35: live → scores updating periodically
    │
    │  refresh_scores_once() ticks:
    │    1. ensure_match_teams_loaded([35])  ← only loads teams for live/completed matches
    │    2. compute_player_points_for_match(35)
    │    3. compute_points_for_match(35)     ← only for contestants in self.match_participants
    │    4. persist_to_local()               ← writes contestant_points for contestants IN MEMORY
    │       (partial: only users whose teams were loaded into Tournament object)
    │
    │  ... mid-match persist writes intermediate values for SOME users ...
    │
    ▼
Match 35: scorecard completes → _finalize_completed_match(35)
    │
    ├── compute_player_points_for_match(35)  ← updates player-level points
    ├── compute_points_for_match(35)         ← recalculates contestant totals
    │     BUT only for contestants already in self.match_participants["35"]
    │     Users whose teams weren't loaded → NOT recalculated
    │
    ├── persist_player_points_to_local()     ← saves player_points (correct)
    ├── persist_to_local()                   ← saves contestant_points
    │     Iterates self.contestants — only writes rows for users IN MEMORY
    │     6 users never loaded → no row in contestant_points
    │     4 users have stale mid-match values that weren't recalculated
    │
    ├── refresh_leaderboard_cache()          ← leaderboard computes on-the-fly (correct)
    │
    └── weekend_tournament on_match_completed(35)  ← FIRES IMMEDIATELY AFTER
          │
          └── advance_round() → _get_match_contestant_points(35)
                │
                ├── Reads contestant_points → finds 10 rows (incomplete!)
                ├── Returns early (rows exist, never falls through to fallback)
                └── 6 users get 0 points, 4 users get stale values
```

### Three Bugs

**Bug 1 (Root Cause): `ensure_match_teams_loaded` skips late team submissions**

`ensure_match_teams_loaded()` (`tournament.py:143`) only loads teams **once** per match. On subsequent calls it checks `self.locked_match_ids_loaded` and skips:

```python
def ensure_match_teams_loaded(self, match_ids, force=False):
    ids_to_fetch = [mid for mid in normalized_ids if mid not in self.locked_match_ids_loaded]
    if not ids_to_fetch:
        return  # ← Match 35 already loaded, skips even if new teams were submitted since
```

When match 35 first went live, teams were loaded into memory. But 6 users (Cancelie, Boisar Khiladi, Sejjol, SuperQueenNinni, Benzi, Omkar) **submitted their teams after** the initial load. Since the match was already in `locked_match_ids_loaded`, their teams were never picked up by subsequent scoring ticks. They remained invisible to the in-memory `Tournament` object for the rest of the match.

**Evidence — this is a systemic issue, not a one-off:**

| Match | Status | Users in `user_teams` | Users in `contestant_points` | Missing |
|---|---|---|---|---|
| 12 | NR | 17 | **0** | All 17 (NR clears in-memory points, `persist_to_local` writes nothing) |
| 35 | completed | 16 | **10** | 6 late submitters |

**Every single user** has at least 1 match missing from `contestant_points` vs `user_teams`:

```
user  1 (SheWhoMustNotBeNamed): missing = [12]
user  2 (Ironman):              missing = [12]
user  3 (Rupesh):               missing = [12]
user  5 (Sagar):                missing = [12, 37, 38]
user  7 (Cancelie):             missing = [12, 35]
user  8 (Boisar Khiladi):       missing = [12, 35]
user 13 (Sejjol Challengers):   missing = [12, 35]
user 14 (SuperQueenNinni):      missing = [12, 35]
user 16 (Benzi):                missing = [12, 35]
user 17 (Omkar):                missing = [12, 35]
... (all 17 users have gaps)
```

**Bug 2: `persist_to_local` writes only what's in memory**

`persist_to_local()` (`tournament.py:416`) iterates `self.contestants` and writes their points. Users not in memory simply never get a `contestant_points` row. And for users that ARE in memory, if their points were computed from stale player data (mid-match live scoring tick), those intermediate values get persisted and never corrected — because `compute_points_for_match` at finalization only recalculates for contestants in `self.match_participants`, which is the same incomplete set.

For match 35, this means:
- **6 users**: no row at all (teams never loaded → not in `self.contestants`)
- **4 users** (Rupesh, AkkiRocker, EngineerBabu, Ironman): stale mid-match values persisted during live scoring, final scorecard recomputation didn't update them because `compute_points_for_match` ran against the same incomplete participant set

**Bug 3: `_get_match_contestant_points()` trusts partial data**

```python
def _get_match_contestant_points(db, match_id):
    rows = db.execute("SELECT ... FROM contestant_points WHERE match_id = ?", ...)
    if rows:
        return rows  # ← Returns immediately even if only 10 of 16 users have rows
    # Fallback (accurate computation) never reached
```

The function returns early if ANY rows exist in `contestant_points`, even if the data is incomplete. The accurate fallback (computing from `user_teams` + `player_points` with captain/VC multipliers) is never executed.

---

## Why Leaderboard Is Correct But Tournament Is Wrong

The match leaderboard computes points **on-the-fly** from `user_teams` + `player_points` tables every time it's requested. It never reads `contestant_points`.

The weekend tournament reads `contestant_points` (the cache) via `_get_match_contestant_points()`, which short-circuits on partial data.

---

## Fix Options

### Option A: Make tournament always compute on-the-fly (like leaderboard)

Change `_get_match_contestant_points()` to always use the `user_teams` + `player_points` computation, bypassing `contestant_points` entirely. This is the simplest fix and guarantees correctness for the weekend tournament.

**Does NOT fix** the underlying `contestant_points` staleness (Bug 1 + 2), but those bugs don't affect users because the leaderboard already computes on-the-fly.

### Option B: Fix `ensure_match_teams_loaded` to pick up late submissions

Force-reload teams on every scoring tick for live matches (not just on first load):

```python
# In refresh_scores_once(), change:
self.ensure_match_teams_loaded(locked_match_ids_to_load)
# To:
self.ensure_match_teams_loaded(locked_match_ids_to_load, force=True)
```

This fixes the root cause — all users' teams are always in memory. But adds DB load on every tick.

### Option C: Force-reload teams at finalization time

In `_finalize_completed_match()`, force-reload before computing and persisting:

```python
self.ensure_match_teams_loaded([match_id], force=True)  # reload all teams
self.compute_points_for_match(match_id)                  # recalculate all
self.persist_to_local()                                   # now complete
# THEN fire weekend tournament hook
```

This ensures `contestant_points` is complete at match completion, regardless of when teams were loaded during live scoring.

### Recommended: Option A + Option C

- **Option A** makes the weekend tournament immune to `contestant_points` issues (immediate fix)
- **Option C** fixes the root cause so `contestant_points` is reliable for any future consumer
- Together, both the symptom and root cause are addressed

---

## Files Involved

| File | Role |
|---|---|
| `backend/models/tournament.py:188` | `_finalize_completed_match()` — the orchestrator |
| `backend/models/tournament.py:416` | `persist_to_local()` — writes partial contestant_points |
| `backend/services/weekend_tournament_service.py:569` | `_get_match_contestant_points()` — trusts stale cache |
| `backend/services/weekend_tournament_service.py:249` | `advance_round()` — uses wrong points for 1v1 scoring |

---

## Data Repair Needed

Tournament 4, Round 1 (match 35) bracket entries need to be rescored with correct points and winners re-determined. Round 2 pairings (match 36) need to be regenerated from correct Round 1 winners.
