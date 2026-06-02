# Dashboard, Matches, And Players Requirements

This document defines Dashboard behavior and the match/player APIs that power team selection.

## Dashboard Requirements

Route: `/dashboard`.

The dashboard must:

- Load match cards from `GET /api/dashboard/matches`.
- Load user's submitted match ids from `GET /api/teams/my-matches`.
- Load Super Team status from `GET /api/super-team/status`.
- For future/lineup matches where the user has a team, load:
  - `GET /api/teams/my-lineup-statuses`
  - `GET /api/teams/my-backup-counts`
- Refresh dashboard data every 30 seconds.
- Prefetch player payloads for today's future/lineup matches after initial load.
- Split matches into tabs:
  - Today: today's matches plus live matches, excluding completed/NR.
  - Upcoming: future matches not today.
  - Completed: completed or NR matches.
- Auto-select Today if available, otherwise Upcoming, otherwise Completed.

## Dashboard Match Cards

Each match card must show:

- Team names/codes.
- Match date and time.
- Status badge.
- Countdown for future matches.
- User team status.
- Backup count when applicable.
- Lineup warnings for unannounced or substitute-selected players.
- Current rank for live/completed matches when available.
- Venue/toss details when available.
- Actions to pick/edit team, view scores, view contestants, and open subcontest pages.

## Contestants Modal

- `GET /api/teams/contestants?match_id=X` lists users who submitted teams.
- Admin users can also view missing users via `GET /api/admin/pending-users?match_id=X`.
- Modal has Playing and Missing tabs where available.

## Match API

Endpoints:

- `GET /api/matches`
- `GET /api/dashboard/matches`

Response requirements:

- Return matches ordered as today/live, future, completed.
- Each match includes computed `status` and `locked`.
- Dashboard payload includes `current_rank` for the current user on live/completed matches when cached score data is available.
- Include venue stats for today's/future matches when available.
- Include cached toss info when announced.

## Match Status Requirements

Status is resolved from match date/time, toss time, stored status, and app current time.

Required statuses used by UI/code:

- `future`
- `lineups`
- `live`
- `completed`
- `nr`

Locking must be backend-authoritative and consistent across matches, players, teams, and Super Team logic.

## Runtime Clock

- Backend uses `get_current_datetime()` in IST.
- Overrides are supported:
  - `APP_CURRENT_DATETIME`
  - `APP_CURRENT_DATE` plus `APP_CURRENT_TIME`
- Frontend uses `/api/runtime/current-time` through `useAppClock` so local/test time matches backend.

## Player API

Endpoint: `GET /api/players`.

Without `match_id`:

- Return all players ordered by team, role, total points, and name.

With `match_id`:

- Return players for the match teams grouped by role.
- Include player metadata:
  - `id`
  - `name`
  - `team`
  - `role`
  - `type`
  - `aliases`
  - `total_points`
  - `matches_played`
  - `avg_points`
  - `last_match_points`
  - `recent_history`
- Include match teams.
- Include Playing XI summary.
- Include lineup window state.
- Include whether match is today.
- Include last completed XI preview for today matches when current XI is unknown.
- Include toss info.

## Player Availability

When Playing XI is announced:

- Players in the XI get `is_playing_xi = true`, `availability_status = available`.
- Substitute players get `is_substitute = true`, `availability_status = substitute`.
- If full XI is known and a player is not in XI/substitutes, mark unavailable.
- If XI is not announced, availability fields are null.

## Recent History

- Recent history uses completed matches involving the player's team.
- For each player, include recent match id, opponent, points, and did-not-play flag.
- Used by selection UI and Super Team player pool for decision support.

## Acceptance Criteria

- Dashboard updates match status without page reload.
- Today's match cards show lineup and backup warnings.
- Player list for a match shows role groups and availability once lineups are available.
- Current user rank appears for live/completed matches when score cache has contestants.
