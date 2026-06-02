# Admin Panel Requirements

This document defines requirements for the admin UI and admin API.

## Scope

- Admin pages are available under `/admin`.
- Only authenticated users with `role = 'admin'` may access admin routes.
- Admin actions manage users, players, matches, teams, backups, scores, missed players, and Super Team operations.

## Primary Files

| File | Responsibility |
|------|----------------|
| `frontend/src/pages/admin/AdminLayout.tsx` | Admin navigation and nested layout |
| `frontend/src/pages/admin/AdminDashboard.tsx` | Summary counts and quick actions |
| `frontend/src/pages/admin/ManageUsers.tsx` | User active/role management |
| `frontend/src/pages/admin/ManagePlayers.tsx` | Player CRUD |
| `frontend/src/pages/admin/ManageMatches.tsx` | Match CRUD |
| `frontend/src/pages/admin/ManageTeams.tsx` | View and edit submitted teams |
| `frontend/src/pages/admin/ManageBackups.tsx` | Backup overview |
| `frontend/src/pages/admin/ScoreControl.tsx` | Recalculate, validate, admin submit team |
| `frontend/src/pages/admin/MissedPlayers.tsx` | Unknown player review |
| `frontend/src/pages/admin/AdminSuperTeam.tsx` | Super Team admin controls |
| `backend/routes/admin.py` | Admin API |
| `backend/middleware/auth.py` | Admin authorization |

## Authorization

- Admin frontend routes must be wrapped by `AdminRoute`.
- Backend admin routes must depend on `require_admin`.
- Non-admin users must be redirected away from admin UI and receive `403` from admin APIs.
- Dev login may access admin only if the selected local user has `role = 'admin'`.

## Admin Navigation

Required sections:

- Dashboard
- Players
- Matches
- Teams
- Backups
- Users
- Scores
- Missed Players
- Super Team

Navigation must be usable on mobile and desktop.

## User Management

Admin must be able to:

- List users.
- Toggle `is_active`.
- Change role between `user` and `admin`.
- See identifying fields such as name, email, and mobile where available.

Requirements:

- Disabling a user prevents protected API access.
- Role changes invalidate relevant user/static caches.

## Player Management

Admin must be able to:

- List players.
- Create players.
- Edit name, team, role, type, and aliases.
- Delete players when allowed.

Requirements:

- Player changes invalidate player, score, and match payload caches as needed.
- Deleting a player that is referenced by teams/scores should be prevented or handled safely.

## Match Management

Admin must be able to:

- List matches.
- Create matches.
- Edit teams, date/time, venue, status, external ids, and toss metadata.
- Delete matches when allowed.

Requirements:

- Match changes invalidate match, dashboard, score, lineup, venue, and leaderboard caches as needed.
- Match status changes may affect scheduler eligibility and subcontest progression.

## Team Management

Admin must be able to:

- Select a match.
- View all submitted teams for that match.
- See user details and selected players.
- Edit a user's submitted team.
- Submit a team for a user when needed.
- Preserve validation rules for team size and C/VC.

Requirements:

- Admin team edits must update `user_teams`.
- Backups conflicting with new selected players must be pruned.
- Contestant, user team summary, score, and leaderboard caches must be invalidated/refreshed.

## Backup Management

Admin must be able to:

- View backup order per user/match.
- See replacement status.
- See whether backup is active in cached team data.
- Filter by match when supported.

## Score Control

Admin must be able to:

- Recalculate a single match.
- Recalculate all completed matches.
- Validate score computation against parsed scorecard data.
- Submit a team for a user in emergency/admin mode.

Requirements:

- Recalculation must be idempotent.
- Recalculation must update `player_points` and `contestant_points`.
- Recalculation must invalidate scores, leaderboard, achievements, Weekend Battle, and related caches.
- Validation should return computed player stats clearly enough for manual review.

## Missed Players

Admin must be able to:

- View unknown player names detected by the scraper.
- See team and match context.
- Use the list to update player aliases or create missing players.

## Super Team Admin

Admin must be able to:

- View Super Team context/status.
- View user Super Teams.
- Edit Super Teams where backend rules allow.
- Recalculate standings and bonuses.
- See effective admin phase/snapshot state.

## Destructive Actions

- Clear/delete actions must be explicit and scoped.
- Clearing teams should also clear related backups where applicable.
- Destructive actions must invalidate all affected caches.
- The UI should confirm high-impact operations.

## Acceptance Criteria

- Non-admin users cannot access `/admin` or admin APIs.
- Admin CRUD changes are visible immediately after save.
- Recalculate single match updates View Scores and Leaderboard without restart.
- Admin team edit changes the user's team and all dependent score views.
- Super Team admin recalculation can be run repeatedly without duplicate effects.
