# API Contract Requirements

This document is the endpoint checklist for recreating the current app.

## Public And Runtime

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/health` | Basic health |
| `GET` | `/api/status` | Boot/scheduler/database counts |
| `GET` | `/api/runtime/current-time` | Backend current time and override status |

## Auth

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `POST` | `/api/auth/register` | Optional Firebase | Register backend user |
| `GET` | `/api/auth/dev-login` | None/local | Return first active user |
| `GET` | `/api/auth/me` | User | Current profile |
| `PATCH` | `/api/auth/me` | User | Update name/settings |

## Matches And Players

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `GET` | `/api/matches` | User | Full match list |
| `GET` | `/api/dashboard/matches` | User | Match list with current user's rank |
| `GET` | `/api/players` | User | All players |
| `GET` | `/api/players?match_id=X` | User | Match players grouped by role with availability |

## Teams

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `GET` | `/api/teams/my?match_id=X` | User | Current user's team and prediction |
| `GET` | `/api/teams/my-backups?match_id=X` | User | Current user's backups |
| `GET` | `/api/teams/my-matches` | User | Match ids where user has a team |
| `GET` | `/api/teams/my-lineup-statuses?match_ids=...` | User | Lineup warnings for user's teams |
| `GET` | `/api/teams/my-backup-counts?match_ids=...` | User | Backup counts |
| `POST` | `/api/teams` | User | Save regular match team/backups/prediction |
| `PATCH` | `/api/teams/prediction` | User | Update prediction only |
| `GET` | `/api/teams/contestants?match_id=X` | User | Users who submitted teams |

## Scores

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `GET` | `/api/scores/{match_id}` | User | Main match score payload |
| `GET` | `/api/scores/{match_id}/my-team` | User | Current user's selected players |
| `GET` | `/api/scores/{match_id}/team-breakdown` | User | User score breakdown |
| `GET` | `/api/scores/{match_id}/team-diff` | User | Compare current user vs another user |
| `GET` | `/api/scores/{match_id}/contestants` | User | Contestants for comparison |

## Leaderboard And Points

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `GET` | `/api/leaderboard` | User | Overall leaderboard |
| `GET` | `/api/points-table` | User | Per-match point matrix |
| `GET` | `/api/points-table/export` | User | Excel export |

## Weekend Battle

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `GET` | `/api/weekend-tournament/current` | User | Current/recent tournament |
| `GET` | `/api/weekend-tournament/history` | User | Past tournaments |
| `GET` | `/api/weekend-tournament/{tournament_id}` | User | Specific tournament |
| `GET` | `/api/weekend-tournament/match-tags` | User | Match labels for dashboard |
| `POST` | `/api/admin/weekend-tournament/detect` | Admin | Detect tournaments |
| `POST` | `/api/admin/weekend-tournament/{id}/seed` | Admin | Seed bracket |
| `POST` | `/api/admin/weekend-tournament/{id}/advance?match_id=X` | Admin | Advance round |

## Super Team

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `GET` | `/api/super-team` | User | Home payload |
| `GET` | `/api/super-team/status` | User | Dashboard status |
| `POST` | `/api/super-team` | User | Save Super Team |
| `POST` | `/api/super-team/penalty-preview` | User | Preview substitution penalty |
| `GET` | `/api/super-team/contestants` | User | Submitted contestants |
| `GET` | `/api/super-team/participants` | User | Playing/missing users |
| `GET` | `/api/super-team/standings` | User | Super Team standings |
| `GET` | `/api/super-team/details` | User | Detailed standings/breakdowns |
| `GET` | `/api/admin/super-team` | Admin | Admin payload |
| `PUT` | `/api/admin/super-team` | Admin | Admin edit Super Team |
| `POST` | `/api/admin/super-team/recalculate` | Admin | Recalculate standings/cache |

## Achievements

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| `GET` | `/api/achievements` | User | Achievement stats |
| `POST` | `/api/admin/achievements/recalculate` | Admin | Recompute achievement stats |

## Admin

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/admin/users` | List users |
| `PUT` | `/api/admin/users/{user_id}` | Update role/active status |
| `GET` | `/api/admin/player-owners` | Player ownership summary |
| `GET` | `/api/admin/pending-users?match_id=X` | Participants and non-participants |
| `GET` | `/api/admin/players` | List players |
| `POST` | `/api/admin/players` | Create player |
| `PUT` | `/api/admin/players/{player_id}` | Update player |
| `DELETE` | `/api/admin/players/{player_id}` | Delete player |
| `GET` | `/api/admin/matches` | List matches |
| `POST` | `/api/admin/matches` | Create match |
| `PUT` | `/api/admin/matches/{match_id}` | Update match |
| `DELETE` | `/api/admin/matches/{match_id}` | Delete match |
| `POST` | `/api/admin/recalculate/{match_id}` | Recompute one match |
| `POST` | `/api/admin/recalculate-all` | Recompute completed matches |
| `POST` | `/api/admin/validate-compute/{match_id}` | Return computed validation payload |
| `GET` | `/api/admin/teams/matches` | Match list with team counts |
| `GET` | `/api/admin/backups` | Backup overview |
| `GET` | `/api/admin/teams?match_id=X` | Submitted teams |
| `PUT` | `/api/admin/teams` | Edit submitted team |
| `POST` | `/api/admin/teams/submit` | Submit team for user |
| `GET` | `/api/admin/missed-players` | Unknown players |
| `DELETE` | `/api/admin/clear/{table_name}` | Clear scoped table data |

## Contract Requirements

- All protected endpoints must return `401` for unauthenticated access.
- Admin endpoints must return `403` for non-admin users.
- Error responses should use FastAPI `detail` where possible.
- Frontend must tolerate empty arrays for caches not ready.
- Endpoint additions must update this file.
