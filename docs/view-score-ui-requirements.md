# View Score UI Requirements

This document defines the requirements for the regular match score view at `/view-scores/:matchId`.

## Scope

- Show match scorecard, fantasy player points, contestant rankings, prediction bonus status, user team breakdowns, and team comparison.
- Support future, live, completed, no-result, and partially cached states.
- Keep live updates responsive without forcing users to refresh manually.

## Primary Files

| File | Responsibility |
|------|----------------|
| `frontend/src/pages/ViewScores.tsx` | Score page UI, polling, tabs, contestant comparison |
| `backend/routes/scores.py` | Score payloads, live/completed calculations, team breakdowns, cache reads |
| `backend/services/data_service.py` | Team selection, backups, predictions, cache helpers |
| `backend/models/tournament.py` | Match score refresh and persistence |

## Data Sources

- Match metadata from `matches`.
- Player fantasy points from live scraper output or stored `player_points`.
- Contestant points from computed `user_teams` plus `player_points`, with persisted `contestant_points` for completed matches.
- Prediction data from `score_predictions`.
- Backup replacement data from `team_backups`.

## Main Score Payload

Endpoint: `GET /api/scores/{match_id}`.

The response must include:

- Match metadata and status.
- Player score rows with fantasy point fields.
- Contestant rows with:
  - `id`
  - `name`
  - `points`
  - `rank`
  - `predicted_points` when present
  - `prediction_bonus` when awarded
  - `prediction_label` or tier label when available
- Scorecard rows if available.
- Safe fallback payloads for cache miss, no scorecard, or not-started states.

## Contestant Ranking

- Contestants are sorted by descending effective points.
- Ties must be stable and deterministic.
- Prediction bonuses affect per-match displayed points after the match is complete.
- Rank changes may be shown by comparing the latest poll with the previous poll.

## Prediction Bonus Display

- Before match completion, show predictions as informational only.
- After match completion, show awarded bonus badges only for winners.
- Non-winning tier labels may be shown softly, but must not imply a bonus was awarded.
- Bonus points must be included in displayed contestant points wherever effective match points are intended.

## Team Breakdown

Endpoint: `GET /api/scores/{match_id}/team-breakdown`.

Requirements:

- Show selected players for the target user.
- Show base points, C/VC multiplier, adjusted points, role, and team.
- Mark Captain and Vice-Captain.
- Mark backup replacements and the player they replaced.
- Include total adjusted points.
- Support viewing self and other users when allowed.

## Team Comparison

Endpoint: `GET /api/scores/{match_id}/team-diff`.

Requirements:

- Compare current user against another contestant.
- Show players only in my team, only in their team, and common players.
- Show adjusted point differences.
- Highlight C/VC differences.
- Return a helpful error when either side has no team.

## Contestant Picker

Endpoint: `GET /api/scores/{match_id}/contestants`.

Requirements:

- List users who submitted teams for the match.
- Use cached live contestants when available.
- Exclude inactive users where backend selection logic does so.
- Support the comparison dropdown without requiring the full score payload to reload.

## Live Update Behavior

- Live match score views should poll or refresh at a reasonable interval.
- The page should avoid flicker when a refresh fails; keep the previous usable payload.
- Loading indicators should distinguish initial load from background refresh.
- Completed matches may use cached/stored points and should not refresh aggressively.

## Empty And Error States

- Future match: show that scores are not available yet.
- No contestants: show a clear empty state.
- Scorecard unavailable: show match/contestant data if available, with a non-blocking warning.
- Backend error: show a retry path and preserve the current route.

## Acceptance Criteria

- A live match page updates player and contestant points without a full page reload.
- A completed match page shows stable stored results and prediction bonus badges.
- Team breakdown totals match the contestant row for the same user and match.
- Team comparison correctly separates common and different players.
- Backup replacements are visible in breakdowns when applied.
- Score page remains usable during cache miss or scraper failure.
