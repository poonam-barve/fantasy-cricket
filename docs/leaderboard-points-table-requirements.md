# Leaderboard And Points Table Requirements

This document defines overall standings, match point matrix, rank movement, balance, medals, and export behavior.

## Primary Files

| File | Responsibility |
|------|----------------|
| `backend/routes/leaderboard.py` | Leaderboard, points table, export, cache scheduler |
| `frontend/src/pages/Leaderboard.tsx` | Overall standings UI |
| `frontend/src/pages/PointsTable.tsx` | Match-by-match matrix UI and export |
| `frontend/src/components/RankShiftBadge.tsx` | Rank movement display |

## Leaderboard Endpoint

Endpoint: `GET /api/leaderboard`.

Returns a cached array of users with:

- `rank`
- `name`
- `user_id`
- `points`
- `prediction_bonus`
- `rank_change`
- `gold`
- `silver`
- `bronze`
- `weekend_wins`
- `weekend_bonus`
- `super_team_bonus`
- `balance`

## Points Table Endpoint

Endpoint: `GET /api/points-table`.

Returns rows with:

- `user_id`
- `name`
- `match_id`
- `points`
- `last_updated`
- `net`
- `adjusted`
- `participated`
- `rank_change`

## Export Endpoint

Endpoint: `GET /api/points-table/export`.

Requirements:

- Requires `openpyxl`.
- Returns `.xlsx`.
- Includes one row per match.
- Includes Weekend Battle Winner Bonus row.
- Includes Super Team Rank Bonus row when any Super Team bonus exists.
- Includes Total row.
- Freezes header row and sets practical column widths.

## Effective Match Points

For completed matches, effective points come from stored `contestant_points` when complete and trustworthy. Otherwise they are recomputed from `user_teams` and `player_points`.

Prediction bonus is added only after the match is completed.

No-result (`nr`) matches are excluded from completed match ids.

## Non-Participant Adjustment

For each completed match:

- Active users who did not participate are added to the standings with adjusted points.
- Current adjustment config is `15%` below the lowest participant score.
- Adjusted points are rounded to the nearest `0.5`.
- Adjusted users are marked:
  - `adjusted = true`
  - `participated = false`
- Adjusted points affect standings but do not create prize/balance participation.

## Prize Balance

Constants:

- Entry fee: `50`
- Prize split: `50%`, `30%`, `20%` for top 3 participants.

Rules:

- Pool is `number_of_participants * 50`.
- Only participants are included in prize calculation.
- Top 3 by points receive pool percentages.
- Net per match is `prize - entry fee`.
- Balance is cumulative net across matches.

## Medals

- Gold, silver, and bronze are computed from effective match points.
- Match ranks handle ties.
- Rank 1 gets gold, rank 2 silver, rank 3 bronze.
- Tied users at a medal rank each receive that medal.

## Rank Movement

- Rank movement compares cumulative leaderboard rank after each completed match to the immediately previous completed match.
- `rank_change` is positive when a user moves up.
- Current leaderboard rank change uses the most recent completed match.
- Points table rows include per-match rank movement.

## Bonus Integration

Leaderboard total includes:

- Effective regular match points.
- Prediction bonuses when awarded.
- Weekend Battle champion bonuses.
- Super Team final rank bonuses when available.

Weekend bonus rules:

- Regular Weekend Battle champion: `+200`.
- Knockout involving Match 70-74 set: `+400`.

Super Team bonus comes from `super_team_service.bonus_map()`.

## Frontend Leaderboard UI

- Shows F1-style top 3 podium when at least 3 entries exist.
- Supports sorting by points, prediction bonus, Super Team bonus, medals, total medals, weekend wins, and balance.
- Ties in selected sort show same displayed rank.
- Current user gets a `YOU` badge.
- Shows entry fee and prize split note.
- Shows PB and ST bonus columns.

## Frontend Points Table UI

- Loads points table and matches.
- Displays sticky player and total columns.
- Displays one column per match.
- Shows match teams and match id in column header.
- Shows rank medal per match.
- Shows net amount for participants.
- Shows `Adj.` for non-participant adjustment points.
- Supports Excel export.

## Acceptance Criteria

- Leaderboard totals match the sum of points table rows plus visible subcontest bonuses.
- Non-participants are visible as adjusted in Points Table but excluded from prize pool.
- Rank movement badges are stable after reload.
- Export matches the visible leaderboard totals.
