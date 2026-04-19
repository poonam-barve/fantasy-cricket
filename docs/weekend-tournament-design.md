# Player of the Weekend - Design Document

## Overview

A weekly knockout tournament that runs across weekend IPL matches. When a weekend has 4 matches (2 Saturday + 2 Sunday), the **last match before Saturday** (could be Friday, Thursday, or any weekday) becomes the **Qualifying Match**. Top 16 scorers qualify and are drawn into random 1v1 brackets across the 4 weekend matches, culminating in a single **Player of the Weekend**.

---

## How It Works

### Weekend Detection

A weekend tournament is triggered when:
- Saturday has **2 IPL matches** (afternoon + evening)
- Sunday has **2 IPL matches** (afternoon + evening)
- There is **at least 1 match before Saturday** that week (the most recent one becomes the qualifier)

If a weekend has fewer than 4 matches, no tournament runs that week.

Detection runs automatically on app boot and can be triggered manually via admin API.

### Qualifying Match Selection

The qualifying match is the **last match before Saturday** of that weekend:
- If there's a Friday match -> Friday is the qualifier
- If no Friday match but Thursday has one -> Thursday is the qualifier
- Works for any weekday — always picks the **closest match before Saturday**
- If multiple matches on the qualifying day, the **last one by match_time** is picked

### Qualifying Round

- The qualifying match is tagged as **"QUALIFIER"** on the Dashboard
- All users who submitted a team for that match are ranked by fantasy points
- **Top 16** qualify for the weekend knockout
- If fewer than 16 participated, remaining slots are filled from the **overall leaderboard** (highest cumulative points, excluding already-qualified users — tagged as "LB" in the UI)
- If total is odd, the last player is dropped to keep pairings even
- Bracket is seeded once the qualifying match is marked completed

### Random 1v1 Draw — How It Works

The draw uses a **pure random shuffle** approach (not seeded brackets):

**Round 1 (after qualifier completes):**
1. Collect the 16 qualified players (sorted by qualifier points initially)
2. `random.shuffle()` the entire list — fully randomizes the order
3. Pair adjacent entries: players at positions [0,1] form matchup 1, [2,3] form matchup 2, etc.
4. This means the top qualifier could face the 2nd best, or the weakest — it's a lottery

**Rounds 2-4 (after each weekend match completes):**
1. Collect winners from the just-completed round
2. `random.shuffle()` the winners again — fresh random draw
3. Pair adjacent entries for the next round

This means every round is a completely new random draw. There's no bracket path determined upfront — winners are reshuffled and re-paired each round.

### Knockout Rounds (4 Weekend Matches)

| Round | Match | Matchups | Description |
|-------|-------|----------|-------------|
| Round of 16 | Saturday Match 1 | 8 x (1v1) | 16 players, 8 winners advance |
| Quarter Finals | Saturday Match 2 | 4 x (1v1) | 8 players, 4 winners advance |
| Semi Finals | Sunday Match 1 | 2 x (1v1) | 4 players, 2 winners advance |
| Final | Sunday Match 2 | 1 x (1v1) | 2 players, 1 winner crowned |

### 1v1 Rules

- Each pair plays the **same IPL match** (both must have submitted a fantasy team)
- Whoever scores **more fantasy points** in that match wins
- **Tie-break**: user with higher overall leaderboard rank wins (lower rank number = better)
- If a user **didn't submit a team** for a weekend match, they score 0 and lose
- Pairings are **randomized** each round (not seeded)

### Winner

The final winner receives the title **"Player of the Weekend"** displayed on the bracket page and the Weekend Competition hub.

---

## Implementation

### Files Created

| File | Purpose |
|------|---------|
| `backend/services/weekend_tournament_service.py` | Core logic: detection, seeding, bracket advancement, queries |
| `backend/routes/weekend_tournament.py` | REST API endpoints (user + admin) |
| `frontend/src/pages/WeekendTournament.tsx` | Weekend Competition hub with bracket visualization |
| `docs/weekend-tournament-design.md` | This document |

### Files Modified

| File | Changes |
|------|---------|
| `backend/database.py` | Added `weekend_tournaments` and `weekend_tournament_brackets` tables (SQLite + Postgres) |
| `backend/main.py` | Registered weekend_tournament router, added detection on boot |
| `backend/models/tournament.py` | Hooked `on_match_completed()` into `_finalize_completed_match()` for auto-progression |
| `frontend/src/types/index.ts` | Added WeekendTournament, WeekendTournamentRound, WeekendTournamentMatchup, etc. types |
| `frontend/src/App.tsx` | Added `/weekend` route with lazy-loaded WeekendTournament page |
| `frontend/src/pages/Dashboard.tsx` | Added "Weekend" quick action button (purple) in 4-column grid |

---

## Database Schema

### `weekend_tournaments`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `qualifying_match_id` | INTEGER FK -> matches | Last match before Saturday (qualifier) |
| `weekend_match_1_id` | INTEGER FK -> matches | Sat match 1 (Ro16) |
| `weekend_match_2_id` | INTEGER FK -> matches | Sat match 2 (QF) |
| `weekend_match_3_id` | INTEGER FK -> matches | Sun match 1 (SF) |
| `weekend_match_4_id` | INTEGER FK -> matches | Sun match 2 (Final) |
| `status` | TEXT | `pending` / `qualifying` / `active` / `completed` |
| `winner_user_id` | INTEGER FK -> users | Winner (set when completed) |
| `created_at` | TEXT | Timestamp |

**Constraint**: `UNIQUE(qualifying_match_id)`

### `weekend_tournament_brackets`

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `tournament_id` | INTEGER FK -> weekend_tournaments | Which tournament |
| `round` | INTEGER | 1=Ro16, 2=QF, 3=SF, 4=Final |
| `match_position` | INTEGER | Position within round (1-8 for Ro16, 1-4 for QF, etc.) |
| `match_id` | INTEGER FK -> matches | Which IPL match this round uses |
| `user1_id` | INTEGER FK -> users | First player in matchup |
| `user2_id` | INTEGER FK -> users | Second player in matchup |
| `user1_points` | REAL | Fantasy points scored by user1 |
| `user2_points` | REAL | Fantasy points scored by user2 |
| `winner_user_id` | INTEGER FK -> users | Winner of this matchup |
| `status` | TEXT | `pending` / `live` / `completed` |

**Constraint**: `UNIQUE(tournament_id, round, match_position)`

### Entity Relationship

```
weekend_tournaments (1) ──── (many) weekend_tournament_brackets
       |                                    |
       |                                    |-- user1_id -> users
       |                                    |-- user2_id -> users
       |                                    +-- match_id -> matches
       |
       |-- qualifying_match_id -> matches
       |-- weekend_match_1_id  -> matches
       |-- weekend_match_2_id  -> matches
       |-- weekend_match_3_id  -> matches
       |-- weekend_match_4_id  -> matches
       +-- winner_user_id      -> users
```

---

## Tournament Lifecycle

```
               Weekend with 4 matches             Qualifier match           Bracket seeded
               detected in schedule                completes                 with top 16
                                                                            (random draw)
  [pending] ──────────────────────> [qualifying] ─────────────────────> [active]
                                                                          |
                                              Each weekend match completes:
                                              score 1v1s, advance winners
                                                                          |
                                                          Final match completes, winner set
                                                                          |
                                                                          v
                                                                     [completed]
```

### Auto-progression (in `tournament.py`)

After each IPL match completes via `_finalize_completed_match()`:

1. Calls `weekend_tournament_service.on_match_completed(match_id)`
2. **Is this a qualifying match for a pending tournament?** -> `seed_bracket()`: get top 16 from qualifier points, backfill from leaderboard if needed, random shuffle, create matchup pairs, set status to `active`
3. **Is this a weekend match in an active tournament?** -> `advance_round()`: look up each user's points for this match, determine 1v1 winners (tie-break by leaderboard rank), shuffle winners, create next round pairs
4. **Is this the final (4th weekend) match?** -> Set `winner_user_id`, mark tournament `completed`

---

## API Endpoints

### User Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/weekend-tournament/current` | Required | Active or most recent tournament with full bracket |
| `GET` | `/api/weekend-tournament/{id}` | Required | Specific tournament bracket |
| `GET` | `/api/weekend-tournament/history` | Required | List of all past tournaments with winners |
| `GET` | `/api/weekend-tournament/match-tags` | Required | Map of match_id -> tournament tag (qualifier/round label) |

### Admin Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/admin/weekend-tournament/detect` | Admin | Manually trigger weekend detection |
| `POST` | `/api/admin/weekend-tournament/{id}/seed` | Admin | Manually seed bracket |
| `POST` | `/api/admin/weekend-tournament/{id}/advance?match_id=X` | Admin | Manually advance a round |

### Response Shape: `GET /api/weekend-tournament/current`

```json
{
  "id": 1,
  "status": "active",
  "qualifying_match_id": 25,
  "weekend_match_ids": [26, 27, 28, 29],
  "winner": null,
  "matches": {
    "25": { "team1": "CSK", "team2": "MI", "match_date": "2026-04-16", "match_time": "19:30", "status": "completed" },
    "26": { "team1": "RCB", "team2": "KKR", "match_date": "2026-04-18", "match_time": "15:30", "status": "live" }
  },
  "qualifiers": [
    { "user_id": 1, "name": "Rupesh", "qualifying_points": 342.5, "seed": 1 },
    { "user_id": 8, "name": "Sagar", "qualifying_points": 0, "seed": 16, "backfilled": true }
  ],
  "brackets": [
    {
      "round": 1,
      "round_label": "Round of 16",
      "match_id": 26,
      "matchups": [
        {
          "position": 1,
          "user1": { "id": 1, "name": "Rupesh" },
          "user2": { "id": 5, "name": "Sagar" },
          "user1_points": 285.0,
          "user2_points": 210.5,
          "winner_user_id": 1,
          "status": "completed"
        }
      ]
    }
  ]
}
```

When no tournament exists: `{ "id": null, "status": "none", "message": "No weekend competition available" }`

---

## Frontend

### Weekend Competition Page (`/weekend`)

Accessible from Dashboard quick actions (purple "Weekend" button).

**Sections:**
1. **Status Banner** — Tournament name, status badge (Upcoming/Qualifying/Live/Completed)
2. **Winner Display** — Trophy + winner name (when completed)
3. **Progress Tracker** — 5-segment bar (Qualifier, Ro16, QF, SF, Final) with green fill for completed, pulse for live
4. **Qualifiers List** — Grid of 16 qualified players with seed number, points, "LB" tag for backfilled, "YOU" badge
5. **Bracket Diagram** — Horizontally scrollable bracket with matchup cards per round:
   - Green background + text for winners
   - Dimmed/red for losers
   - "LIVE" badge on active matchups
   - "TBD" for undrawn future matchups
   - Trophy + "Player of the Weekend" at the end for the winner
6. **Past Winners** — Hall of fame list with trophy emoji and date

### Dashboard Changes

- Quick actions grid changed from 3 to 4 columns
- Added purple "Weekend" button with lightning bolt icon linking to `/weekend`

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Fewer than 16 qualifier participants | Fill from overall leaderboard (tagged "LB") |
| Fewer than 16 total active users | Run with available count, trim to even |
| Odd number of qualified players | Drop last player to make even pairs |
| User didn't submit team for weekend match | They score 0, opponent wins |
| Tie in 1v1 points | Higher overall leaderboard rank wins |
| Match marked "NR" (no result) | Not yet handled (TODO) |
| Weekend has only 3 matches | No tournament that week |
| No match before Saturday that week | No tournament that week |
| Qualifier is on Wednesday/Thursday | Works — picks last match before Saturday |
| Tournament already exists for a weekend | Skipped (UNIQUE constraint on qualifying_match_id) |
| Multiple matches on qualifier day | Last one by match_time is picked |
| App restart | Detection runs on boot, idempotent (skips existing tournaments) |
