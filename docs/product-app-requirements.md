# Product App Requirements

This document describes the full application shape needed to recreate the Fantasy Cricket app from scratch.

## Product Summary

Fantasy Cricket is a private IPL fantasy league for a fixed group of users. For each match, users submit an 11-player fantasy team before lock, choose Captain and Vice-Captain, optionally choose backups and a score prediction, then compete on live match standings and an overall leaderboard.

## Main User Journeys

1. User logs in with Firebase or local dev login.
2. User lands on Dashboard.
3. User reviews today's, upcoming, and completed matches.
4. User opens a future match and selects a team.
5. User optionally adds backups and a score prediction.
6. Once the match starts, the team locks.
7. User views live score, player fantasy points, contestant rankings, and team comparison.
8. User checks overall Leaderboard and Points Table.
9. User participates in subcontests such as Weekend Battle, Super Team, predictions, and achievements.
10. Admin users manage data and recalculate scores from the admin panel.

## Frontend Routes

| Route | Auth | Purpose |
|-------|------|---------|
| `/login` | Public | Firebase login and Dev Login |
| `/register` | Public | Firebase registration and backend profile creation |
| `/dashboard` | Required | Match list, quick actions, team status |
| `/select-team/:matchId` | Required | Regular match team selection |
| `/view-scores/:matchId` | Required | Match scores, scorecard, team breakdown, comparison |
| `/leaderboard` | Required | Overall standings and prize/balance columns |
| `/points-table` | Required | Per-match point matrix and Excel export |
| `/weekend` | Required | Weekend Battle bracket hub |
| `/super-team` | Required | Super Team contest page |
| `/achievements` | Required | User achievement stats and top lists |
| `/rules` | Required | Scoring/rules summary |
| `/settings` | Required | User settings/profile preferences |
| `/admin` | Admin | Admin dashboard |
| `/admin/players` | Admin | Player CRUD |
| `/admin/matches` | Admin | Match CRUD |
| `/admin/teams` | Admin | Submitted team review/edit |
| `/admin/backups` | Admin | Backup overview |
| `/admin/users` | Admin | User role and active status |
| `/admin/scores` | Admin | Score recalculation and validation |
| `/admin/missed-players` | Admin | Unknown scraper player review |
| `/admin/super-team` | Admin | Super Team admin tools |

## App Shell

- The app uses React, TypeScript, Vite, React Router, Axios, and Tailwind CSS.
- Protected routes render inside `AppLayout`.
- Admin routes render inside `AdminLayout`.
- The navbar must show normal app links and an Admin link only for admin users.
- Route-level lazy loading is used for pages.
- A global auth provider stores Firebase user, backend profile, loading state, and login/register/logout/dev-login actions.

## Visual And Interaction Requirements

- Mobile-first dark UI.
- Match cards use team themes from `frontend/src/utils/teamTheme.ts`.
- Dashboard, leaderboard, score pages, and Super Team pages use dense app UI, not marketing pages.
- Loading states use skeletons/spinners.
- Rank movement uses `RankShiftBadge`.
- Toasts are used for save/recalculate-style actions where applicable.
- Primary visual assets include `/mahi.jpg`, `/podium.jpeg`, and `/loserclub.jpg` where referenced by pages.

## Core Domain Objects

- User: active contestant or admin.
- Player: selectable cricketer with team, role, type, and aliases.
- Match: IPL match with teams, date/time, status, venue, toss, and external ids.
- Team selection: 11 regular match players plus C/VC flags.
- Backup: ordered backup player for a user's match team.
- Player points: player fantasy score for one match.
- Contestant points: user fantasy score for one match.
- Prediction: user's predicted team score for one match.
- Weekend Battle: bracket contest across weekend matches.
- Super Team: playoff squad contest across Matches 71-74.
- Achievement stats: derived awards and records.

## Non-Functional Requirements

- Local development must work without Firebase through Dev Login.
- Production auth must verify Firebase ID tokens.
- App time must be overrideable through environment variables for testing match locks.
- PostgreSQL and SQLite must both be supported by the backend abstraction.
- Cache misses must degrade gracefully instead of breaking the UI.
- Background schedulers must be idempotent and resilient to scraper failures.
