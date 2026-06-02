# Database Structure Requirements

This document describes the required database structure and persistence rules for local SQLite/PostgreSQL and production Neon PostgreSQL.

## Database Modes

- If `DATABASE_URL` starts with `postgres`, the backend uses PostgreSQL via `psycopg2`.
- If `DATABASE_URL` is unset, the backend uses local SQLite at `backend/fantasy.db`.
- SQL in routes/services uses `?` placeholders; the PostgreSQL wrapper translates them to `%s`.
- Runtime schema initialization must support both SQLite and PostgreSQL.

## Core Tables

### `users`

Stores registered contestants and admins.

Required columns:

- `id`
- `firebase_uid`
- `email`
- `name`
- `mobile`
- `role`
- `is_active`
- `replace_substitutes_with_backups`
- `created_at`

Rules:

- `firebase_uid` and `email` are unique.
- `role` is `user` or `admin`.
- In local/dev mode, `firebase_uid` may use a `dev_` prefix.
- Inactive users cannot authenticate through protected endpoints.

### `players`

Stores selectable cricket players.

Required columns:

- `id`
- `name`
- `team`
- `role`
- `type`
- `aliases`

Rules:

- `id` is stable and used in team selections and score mappings.
- `role` powers validation, display, and Super Team penalty logic.
- `aliases` supports scraper name matching.

### `matches`

Stores scheduled matches.

Required columns:

- `id`
- `team1`
- `team2`
- `match_date`
- `match_time`
- `status`
- `venue`
- `cricbuzz_match_id`
- `espn_match_id`
- `toss_time`

Rules:

- `status` is expected to behave as future/live/over/completed/NR style lifecycle data.
- `toss_time` may be derived from match time when not explicitly set.
- External match ids are optional but should be populated when scraping requires them.

## Team And Scoring Tables

### `user_teams`

Stores regular match player selections.

Required columns:

- `id`
- `user_id`
- `match_id`
- `player_id`
- `is_captain`
- `is_vice_captain`
- `updated_at`

Rules:

- Unique by `user_id`, `match_id`, `player_id`.
- A valid submitted team has 11 rows per user/match.
- C/VC flags live on the selected player rows.

### `user_teams_audit`

Stores update audit rows for team changes.

Rules:

- Created by trigger where supported.
- Used for operational review, not primary scoring.

### `team_backups`

Stores ordered backups for regular match teams.

Required columns:

- `id`
- `user_id`
- `match_id`
- `backup_order`
- `backup_player_id`
- `replaced_player_id`

Rules:

- Unique by `user_id`, `match_id`, `backup_order`.
- `replaced_player_id` is set when a backup replaces a selected substitute.

### `player_points`

Stores per-player fantasy points for a match.

Required columns:

- `id`
- `match_id`
- `player_id`
- `player_name`
- `team`
- `role`
- `points`
- `last_updated`

Rules:

- Unique by `match_id`, `player_id`.
- Completed matches should have stable stored points.

### `contestant_points`

Stores per-user match totals.

Required columns:

- `id`
- `user_id`
- `match_id`
- `points`
- `last_updated`

Rules:

- Unique by `user_id`, `match_id`.
- Used for completed-match leaderboard and historical totals.

### `score_predictions`

Stores one prediction per user per match.

Required columns:

- `id`
- `user_id`
- `match_id`
- `predicted_points`
- `created_at`

Rules:

- Unique by `user_id`, `match_id`.
- Prediction bonuses are computed from this table plus actual user points.

## Subcontest Tables

### `weekend_tournaments`

Stores Weekend Battle tournament instances.

Required columns:

- `id`
- `qualifying_match_id`
- `weekend_match_ids`
- `num_rounds`
- `status`
- `winner_user_id`
- `created_at`

Compatibility columns may exist:

- `weekend_match_1_id`
- `weekend_match_2_id`
- `weekend_match_3_id`
- `weekend_match_4_id`

Rules:

- Unique by `qualifying_match_id`.
- `weekend_match_ids` is a JSON array encoded as text.

### `weekend_tournament_brackets`

Stores individual Weekend Battle matchups.

Required columns:

- `id`
- `tournament_id`
- `round`
- `match_position`
- `match_id`
- `user1_id`
- `user2_id`
- `user1_points`
- `user2_points`
- `winner_user_id`
- `status`

Rules:

- Unique by `tournament_id`, `round`, `match_position`.
- Points are raw match fantasy points, excluding score prediction bonus.

### `super_teams`

Stores the current editable Super Team state per user.

Required columns:

- `id`
- `user_id`
- `player_id`
- `is_captain`
- `is_vice_captain`
- `updated_at`
- `updated_by`

Rules:

- Unique by `user_id`, `player_id`.
- Represents current saved/editable team state.

### `super_team_originals`

Stores original Super Team snapshots.

Rules:

- Unique by `user_id`, `player_id`.
- Used for Matches 71 and 72 and Window 1 penalty baseline.

### `super_team_snapshots`

Stores phase snapshots for Super Team.

Required columns:

- `id`
- `phase`
- `user_id`
- `player_id`
- `is_captain`
- `is_vice_captain`
- `snapshot_at`

Rules:

- Unique by `phase`, `user_id`, `player_id`.
- Phases include edited/final-style snapshots used for scoring and penalty calculations.

### `achievement_stats`

Stores derived user achievement totals.

Rules:

- Primary key is `user_id`.
- Recalculation should be idempotent from match and leaderboard data.

### `unknown_players`

Stores scraper player names that could not be matched to known players.

Rules:

- Unique by name, team, match, date, and teams.
- Used by admin missed-player review.

## Index Requirements

The schema must include indexes for frequent lookups:

- `user_teams(user_id, match_id)`
- `user_teams(match_id)`
- `user_teams(match_id, user_id)`
- `user_teams(match_id, updated_at)`
- `contestant_points(match_id)`
- `player_points(match_id)`
- `player_points(last_updated)`
- `users(firebase_uid)`
- `team_backups(user_id, match_id)`
- `team_backups(match_id)`
- `score_predictions(match_id)`
- `super_teams(user_id)`
- `super_teams(player_id)`
- `super_team_originals(user_id)`
- `super_team_snapshots(phase, user_id)`

## Migration Requirements

- `init_db()` must be safe to run repeatedly.
- SQLite helper functions may add missing columns for local/dev databases.
- PostgreSQL startup should avoid expensive `ALTER` operations that can deadlock live traffic.
- New features must add schema to both PostgreSQL and SQLite branches.
- Existing data should be preserved during startup migrations.

## Acceptance Criteria

- A fresh SQLite database can be created by starting the backend.
- A fresh PostgreSQL database can be initialized by starting the backend with `DATABASE_URL`.
- Restored Neon data works locally with the same table names and constraints.
- Team save, score refresh, leaderboard, Weekend Battle, Super Team, and admin pages can all query required tables.
