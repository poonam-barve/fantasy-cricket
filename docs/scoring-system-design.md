# Scoring System - Design Document

## Overview

The scoring system computes fantasy cricket points for users in near-real-time during IPL matches. It ingests live scorecard data from Cricbuzz and ESPN, calculates per-player fantasy points based on cricket performance, applies captain/vice-captain multipliers, and aggregates per-user totals for leaderboard ranking.

---

## Architecture

```
External APIs (Cricbuzz HTML, ESPN HTML)
        │
        ▼
┌─────────────────────────────────┐
│  Scorecard Parsers              │
│  Match.parse_cricbuzz_*()       │  → Player stats (runs, wickets, catches, etc.)
│  Match.parse_espn_*()           │
└─────────────┬───────────────────┘
              ▼
┌─────────────────────────────────┐
│  Player Points Calculator       │
│  Player.calculate_player_points │  → Per-cricketer fantasy points
│  (role-based scoring rules)     │
└─────────────┬───────────────────┘
              ▼
┌─────────────────────────────────┐
│  Team Points Calculator         │
│  Team.calculate_team_points()   │  → Sum of 11 players' points
│  (captain 2x, VC 1.5x)         │    with C/VC multipliers
└─────────────┬───────────────────┘
              ▼
┌─────────────────────────────────┐
│  Persistence Layer              │
│  persist_player_points_to_local │  → player_points table (per-cricketer)
│  persist_to_local               │  → contestant_points table (per-user)
└─────────────┬───────────────────┘
              ▼
┌─────────────────────────────────┐
│  API Layer                      │
│  Scores API (per-match view)    │  → Live scores, player breakdowns
│  Leaderboard API (cumulative)   │  → Rankings, medals, balances
└─────────────────────────────────┘
```

---

## Files

| File | Purpose |
|------|---------|
| `backend/models/tournament.py` | Scoring orchestration — scheduler, scorecard fetching, computation, persistence |
| `backend/models/match.py` | Match data model, scorecard parsing from Cricbuzz/ESPN HTML |
| `backend/models/player.py` | Player data model, fantasy points calculation from stats |
| `backend/models/team.py` | Team/Contestant models, captain/VC multiplier logic |
| `backend/services/data_service.py` | DB persistence — save/load points, team management, backup swaps |
| `backend/routes/scores.py` | Scores API — per-match player breakdown, live scores |
| `backend/routes/leaderboard.py` | Leaderboard API — cumulative rankings, medals, balances |
| `backend/main.py` | App boot, scheduler startup |
| `backend/database.py` | Table schemas |

---

## Data Model

### In-Memory (Tournament Object — Singleton)

```
Tournament
├── matches: {match_id: Match}
│     └── Match
│           ├── team1, team2
│           ├── players: {player_id: Player}  ← populated from scorecard
│           └── scorecard: [{innings data}]
│
├── contestants: {contestant_key: Contestant}
│     └── Contestant
│           ├── user_id, name
│           ├── teams: {match_id: Team}
│           │     └── Team
│           │           ├── player_ids: set of 11 player IDs
│           │           ├── captain: player_id
│           │           └── vice_captain: player_id
│           └── points: {match_id: float}  ← computed total
│
├── match_participants: {match_id: set of contestant_keys}
├── player_points: {match_id: {player_id: float}}
├── player_roles: {player_id: role_string}
└── locked_match_ids_loaded: set of match_ids already loaded
```

### Database Tables

**`player_points`** — Per-cricketer fantasy points (source of truth for individual scoring)

| Column | Type | Description |
|--------|------|-------------|
| match_id | INTEGER | Which match |
| player_id | INTEGER | Which cricketer |
| player_name | TEXT | Cricketer name |
| team | TEXT | IPL team |
| role | TEXT | Batter/Bowler/AllRounder/Wicketkeeper |
| points | REAL | Fantasy points calculated from stats |
| last_updated | TEXT | Timestamp |

**`contestant_points`** — Per-user total points (cache, aggregated from player_points + user_teams)

| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Which user |
| match_id | INTEGER | Which match |
| points | REAL | Total fantasy points (sum of 11 players with C/VC multipliers) |
| last_updated | TEXT | Timestamp |

**`user_teams`** — User's team selection (written before match, immutable during match)

| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Which user |
| match_id | INTEGER | Which match |
| player_id | INTEGER | Selected cricketer |
| is_captain | INTEGER | 1 if captain |
| is_vice_captain | INTEGER | 1 if vice-captain |

**Relationship:** `contestant_points` is a **cache** of `SUM(player_points × multiplier)` for each user's 11 players in `user_teams`. The source of truth is always `player_points` + `user_teams`.

---

## Fantasy Points Scoring Rules

### Playing XI

| Category | Points |
|----------|--------|
| Selected in Playing XI | +4 |

### Batting

| Category | Points |
|----------|--------|
| Runs | +1 per run |
| Fours | +4 per boundary |
| Sixes | +6 per six |
| Century (100+) | +16 |
| 75 runs | +12 |
| Half-century (50+) | +8 |
| 30 runs | +4 |
| Duck (0 runs, out, batting role only) | -2 |

### Strike Rate Bonus (min 10 balls faced, batting roles only)

Batting roles: Batter, Wicketkeeper, AllRounder

| Strike Rate | Points |
|-------------|--------|
| > 170 | +6 |
| 150–170 | +4 |
| 130–149 | +2 |
| 60–70 | -2 |
| 50–59 | -4 |
| ≤ 50 | -6 |

### Bowling

| Category | Points |
|----------|--------|
| Wickets | +30 per wicket |
| Bowled/LBW bonus | +8 per dismissal |
| 5-wicket haul | +16 |
| 4-wicket haul | +8 |
| 3-wicket haul | +4 |
| Maiden over | +12 |
| Dot ball | +1 per dot ball |

### Economy Rate (min 2 overs bowled)

| Economy | Points |
|---------|--------|
| < 5.00 | +6 |
| 5.00–5.99 | +4 |
| 6.00–7.00 | +2 |
| 10.00–11.00 | -2 |
| 11.00–12.00 | -4 |
| > 12.00 | -6 |

### Fielding

| Category | Points |
|----------|--------|
| Catch | +8 |
| 3+ catches bonus | +4 (once per match) |
| Stumping | +12 |
| Direct run-out | +12 |
| Indirect run-out | +6 |

### Captain/Vice-Captain Multipliers

| Role | Multiplier |
|------|-----------|
| Captain | 2.0x |
| Vice-Captain | 1.5x |
| Regular | 1.0x |

**User's match total** = sum of (player_points × multiplier) for all 11 players.

---

## Match Status Lifecycle

```
future ──→ lineups ──→ live ──→ completed
                                    │
                                    └──→ nr (no result)
```

| Status | Trigger | Description |
|--------|---------|-------------|
| `future` | Default | Match hasn't started, before toss time |
| `lineups` | toss_time reached (30 min before match) | Playing XI may be available |
| `live` | match_time reached | Match in progress |
| `completed` | Scorecard shows both innings done, OR 5 hours elapsed | Match finished |
| `nr` | Manual / rain | No result, points cleared |

**Status computation** (`get_match_status`):
- If DB has `completed` or `nr` → return as-is (terminal states)
- If now < toss_time → `future`
- If now < match_time → `lineups`
- If now >= match_time + 5 hours → `completed`
- Otherwise → `live`

---

## Scoring Pipeline — Step by Step

### Phase 1: Server Boot

```
main.py → bootstrap_in_background()
    │
    ├── init_db()                          → create tables if needed
    ├── seed_db_if_needed()                → populate from Excel (matches get status="future")
    │
    ├── tournament.initialize(players, matches, [])
    │     → self.contestants = {}          → empty, no teams loaded
    │     → self.matches = {Match objects} → from schedule
    │     → self.player_roles = {pid: role}
    │     → sync_persistent_match_statuses() → update DB match statuses from time
    │
    ├── tournament.start_scheduler()       → spawn score-scheduler thread (60s loop)
    ├── scores.start_scores_cache_scheduler()     → spawn scores cache thread (15s)
    └── leaderboard.start_leaderboard_cache_scheduler() → spawn leaderboard cache thread (15s)
```

### Phase 2: Score Scheduler Tick (every 60 seconds)

```
refresh_scores_once()
    │
    ├── 1. CLASSIFY MATCHES
    │     computed_matches = set of match_ids in player_points table
    │     for each match:
    │       if "live"                          → add to load list
    │       if "completed" + NOT in computed   → add to load list
    │       if "completed" + in computed       → SKIP (already scored)
    │       if "future"                        → SKIP
    │
    ├── 2. LOAD TEAMS
    │     ensure_match_teams_loaded(matches_to_load)
    │       → queries user_teams from DB
    │       → _apply_team_row() for each row:
    │           adds user to self.contestants
    │           adds their Team to contestant.teams[match_id]
    │           adds user to match_participants[match_id]
    │       → skips matches already in locked_match_ids_loaded
    │
    ├── 3. PROCESS EACH MATCH
    │     for each match:
    │       │
    │       ├── "lineups":
    │       │     update_match_data(use_playing_xi=True, include_scorecards=False)
    │       │       → fetch Playing XI from Cricbuzz
    │       │       → apply_playing_xi() → mark 22 players in match.players
    │       │
    │       ├── "live":
    │       │     update_match_data(use_playing_xi=True, include_scorecards=True, apply_backups=True)
    │       │       → match.players = {} (RESET every tick)
    │       │       → fetch Playing XI → apply_playing_xi()
    │       │       → apply_backups (swap non-playing players in user_teams)
    │       │       → parse Cricbuzz scorecard → fill player stats
    │       │       → parse ESPN scorecard → fill dot balls
    │       │       → check completion_state
    │       │           if completed → _finalize_completed_match() (see Phase 3)
    │       │           if not      → continue to compute below
    │       │     
    │       │     compute_player_points_for_match(match_id)
    │       │       → for each cricketer in match.players:
    │       │           player.calculate_player_points(role) → fantasy points
    │       │       → self.player_points[match_id] = {pid: points}
    │       │     
    │       │     compute_points_for_match(match_id)
    │       │       → for each user in match_participants[match_id]:
    │       │           team.calculate_team_points(match, player_roles)
    │       │             → sum(player_points × captain/vc multiplier) for 11 players
    │       │           contestant.points[match_id] = total
    │       │
    │       └── "completed" (not yet computed):
    │             Same as "live" — fetches scorecard, computes points
    │
    └── 4. PERSIST (if any match was processed)
          persist_player_points_to_local()
            → writes self.player_points to player_points table (ALL matches in memory)
          persist_to_local()
            → writes contestant.points to contestant_points table (ALL users, ALL matches)
          refresh_leaderboard_cache()
```

### Phase 3: Match Finalization

Triggered when `get_scorecard_completion_state()` detects both innings are done.

```
_finalize_completed_match(match_id)
    │
    ├── _set_persistent_match_status(match_id, "completed")
    │     → UPDATE matches SET status = 'completed'
    │     → if already "completed" → return False (no-op)
    │
    ├── compute_player_points_for_match(match_id)
    │     → recalculate all cricketer points from final scorecard
    │
    ├── compute_points_for_match(match_id)
    │     → recalculate all user totals for this match
    │     → ONLY for users in match_participants[match_id]
    │
    ├── persist_player_points_to_local()  → write player_points to DB
    ├── persist_to_local()                → write contestant_points to DB
    │
    ├── refresh_leaderboard_cache()
    │
    └── on_match_completed(match_id)      → weekend tournament hook
```

---

## Scorecard Parsing Pipeline

Two external sources are parsed in sequence for each match:

### 1. Cricbuzz (Primary Source)

```
fetch_cricbuzz_scorecard_html(match_id, team1, team2)
    → HTTP GET cricbuzz match page
    → returns HTML

match.parse_cricbuzz_scorecard_html(html)
    → extract JSON from HTML (ApiData marker)
    → for each innings in scoreCard[]:
        → for each batsman:
            player = match.get_or_create_player(name, team)
            player.runs = batsman.runs
            player.balls = batsman.balls
            player.fours = batsman.fours
            player.sixes = batsman.sixes
            player.strike_rate = batsman.strkRate
            player.apply_dismissal(dismissal_text)
              → classifies as caught/bowled/lbw/stumped/run-out
              → credits fielder (catches, stumpings, run-outs)
              → credits bowler (wickets, bowled count, lbw count)
        → for each bowler:
            player = match.get_or_create_player(name, team)
            player.overs = bowler.overs
            player.maidens = bowler.maidens
            player.runs_conceded = bowler.runs
            player.wickets = bowler.wickets
            player.economy = bowler.economy
```

### 2. ESPN (Supplementary — Dot Balls)

```
fetch_scorecard_html(match_id, team1, team2)
    → HTTP GET ESPN match page
    → returns HTML

match.parse_espn_bowling_dot_balls(soup)
    → parse bowling table from HTML
    → extract dot_balls column (ESPN-specific data)
    → for each bowler:
        player = match.get_player(name, team)
        player.dot_balls = parsed_dot_balls
```

**Why two sources:** Cricbuzz provides comprehensive batting/bowling/fielding data. ESPN provides **dot balls** which Cricbuzz doesn't include. Dot balls = +1 point each, which can significantly impact bowler scores.

### 3. Completion Detection

```
match.get_scorecard_completion_state()
    → if < 2 innings parsed: return None (not complete)
    → check 2nd innings:
        if overs >= 20: complete (full innings played)
        if wickets >= 10: complete (all out)
        if 2nd innings runs > 1st innings runs: complete (target chased)
    → return {"status": "completed", "reason": "..."}
```

---

## Backup Player Swap System

When Playing XI is announced, some users may have selected players not in the XI. The backup system auto-swaps them.

```
apply_backups_for_match(match_id, playing_ids, substitute_ids)
    │
    │ Preconditions: 22 playing XI + 10 substitutes
    │
    for each user who has backups defined:
        for each backup (in priority order):
            │
            ├── Is backup player in Playing XI? (not benched)
            ├── Is backup player NOT already in user's team?
            ├── Find a player in user's team who is NOT in Playing XI
            ├── Would the swap break role constraints?
            │     (must keep ≥1 each of Batter, Bowler, WK, AllRounder)
            │
            └── If all checks pass:
                  UPDATE user_teams SET player_id = backup
                  Record the swap in team_backups table
```

This runs BEFORE scoring on each tick (line 277-281 in `update_match_data`), and triggers a force-reload of teams for that match.

---

## Leaderboard Computation

The leaderboard computes cumulative points across all completed matches.

### Data Source

The leaderboard reads from `contestant_points` but **validates and falls back to on-the-fly computation**:

```python
# For each completed match:
stored_users = users in contestant_points for this match
expected_users = users in user_teams for this match

if stored_users == expected_users:
    use cached contestant_points  # fast path
else:
    recompute from user_teams + player_points  # correct path
```

This is why the leaderboard was always correct even when `contestant_points` was stale/incomplete.

### Non-Participant Adjustment

Users who didn't submit a team for a match get a penalty score:
- `adjusted_points = lowest_participant_points - (lowest_participant_points × 15%)`
- This prevents non-participants from gaining an advantage by skipping bad matches.

### Prize Calculation

| Place | Prize Share |
|-------|------------|
| 1st | 50% of pool |
| 2nd | 30% of pool |
| 3rd | 20% of pool |

Pool = number_of_participants × entry_fee (₹50)

---

## Caching Layers

### Scores Response Cache

| Setting | Value |
|---------|-------|
| Refresh interval | 15 seconds (if live matches), 60 seconds (idle) |
| Invalidated by | `persist_player_points_to_local()` |
| Contains | Per-match player breakdowns, contestant rankings |

### Leaderboard Response Cache

| Setting | Value |
|---------|-------|
| Refresh interval | 15 seconds (if data changed), 45 seconds (idle) |
| Invalidated by | `persist_to_local()`, match status changes |
| Contains | Cumulative rankings, medals, balances, rank movements |

### In-Memory Match Data

| Data | Lifetime | Refreshed |
|------|----------|-----------|
| `match.players` | Reset every tick (`match.players = {}`) | Every 60s from scorecard |
| `contestant.points` | Set once per `compute_points_for_match` call | Every 60s for live matches |
| `self.player_points` | Overwritten per `compute_player_points_for_match` | Every 60s for live matches |
| `match_participants` | Set once by `ensure_match_teams_loaded` | Only on first load (or force) |

---

## Threading Model

Single mutation thread after the race condition fix:

| Thread | Interval | Purpose |
|--------|----------|---------|
| `score-scheduler` | 60s | Score live matches, finalize completed, persist |
| `lineup-cache-scheduler` | 15-60s | Refresh Playing XI cache (read-only on Tournament) |
| `toss-cache-scheduler` | 15-60s | Refresh toss data cache (read-only on Tournament) |
| `scores-cache-scheduler` | 15-60s | Build scores API response cache (reads DB) |
| `leaderboard-cache-scheduler` | 15-45s | Build leaderboard API response cache (reads DB) |

Only `score-scheduler` mutates the Tournament object. All other threads either read from it or operate on the DB directly.

**Previous issue (now fixed):** A `recompute-scheduler` thread also mutated the Tournament object concurrently with no locking. Its `force=True` team reload (remove-then-re-add) created a window where `persist_to_local()` could capture incomplete state. This was removed.

---

## Known Limitations

1. **`contestant_points` can be stale** — It's a cache written from in-memory state. If the server restarts after a match completes, and `player_points` already exists, that match's teams are never loaded and `contestant_points` is never written. The leaderboard handles this with its validation fallback. The weekend tournament now computes on-the-fly.

2. **Scorecard parsing depends on external APIs** — If Cricbuzz/ESPN return incomplete HTML, player stats may be partial. The 60s retry loop eventually catches up, but intermediate persists may have stale values.

3. **`match.players` is reset every tick** — Line 258: `match.players = {}`. This means player stats are recomputed from scratch each tick rather than updated incrementally. If one source (Cricbuzz) succeeds but the other (ESPN) fails, dot balls may be missing.

4. **`persist_to_local` writes ALL matches** — A persist triggered by match 36 (live) also writes stale match 35 data if it's still in memory. There's no per-match staleness tracking.

5. **No atomicity guarantee on `contestant_points`** — Nothing verifies that all expected users got their points computed before writing. The leaderboard compensates with its validation check; other consumers must do the same.
