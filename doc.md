---
name: Fantasy Cricket Project Overview
description: Complete project context - architecture, tech stack, deployment, data flow, current state
type: project
---

## Fantasy Cricket - Hippies Mahasangram

IPL fantasy league app for a friend group (~15 users). Users pick 11-player teams per match, scores computed from live ESPN data.

### Repo & Deployment
- **Repo:** `sushant-shelte/fantasy-cricket` branch `build`
- **Live URL:** https://fantasy-cricket-gnu6.onrender.com
- **Render:** Free tier web service + free PostgreSQL
- **Firebase project:** cricket-fantasy-7d3ac
- **GitHub Actions:** keep-alive cron every 4 min on `main` branch

### Tech Stack
- **Backend:** FastAPI (Python) at `backend/`
- **Frontend:** React 19 + TypeScript + Vite 5 + Tailwind CSS 3 at `frontend/`
- **DB:** PostgreSQL (Render prod), SQLite (local dev) — auto-detected via `DATABASE_URL` env var
- **Auth:** Firebase email/password
- **Scraper:** ESPN Cricinfo scorecard parser (`backend/models/match.py`)

### Key Config
- `backend/config.py`: `ESPN_SERIES_ID = 8048`, `ESPN_MATCH_ID_OFFSET = 1527673`
- Match ID 1 + offset = ESPN scorecard ID 1527674
- `TEST_MODE = False` (using real time, no frozen dates)
- Live window = 4 hours from match start

### Database (6 tables)
- `users` — id, firebase_uid, email, name, mobile, role (user/admin), is_active
- `players` — id, name, team (CSK/RCB/MI etc), role (Wicketkeeper/Batter/AllRounder/Bowler), aliases
- `matches` — id, team1, team2, match_date, match_time, status
- `user_teams` — user_id, match_id, player_id, is_captain, is_vice_captain (11 rows per team)
- `contestant_points` — user_id, match_id, points (total team score with C/VC multipliers)
- `player_points` — match_id, player_id, points (individual fantasy points)

### Data
- 250 players, 74 matches (IPL 2026) from `FantasyCricket.xlsx`
- 15 users with Firebase accounts (<name>@gmail.com)
- Match 1 (RCB vs SRH, Mar 28) has contestant_points for 10 users
- Admins: rupesh@gmail.com, sushant@gmail.com, poonam@gmail.com (password: admin@123)
- Others: password hippies123

### Scoring Engine (`backend/models/player.py`)
- Playing: +4
- Runs: +1/run, +4/four, +6/six
- Milestones: +4 (30), +8 (50), +12 (75), +16 (100)
- Duck: -2 (batting roles only)
- SR bonus/penalty: min 10 balls, +6/>170, +4/>150, +2/>=130, -2/<=70, -4/<60, -6/<=50
- Wickets: +30/wicket, haul bonus +4/3W, +8/4W, +16/5W
- Maidens: +12, Dot balls: +1 each
- Economy: min 2 overs, +6/<5, +4/<6, +2/<=7, -2/>=10, -4/>11, -6/>12
- Fielding: catches +8 (3+ bonus +4), stumpings +12, direct runout +12, indirect +6
- Captain: 2x, Vice Captain: 1.5x

### Prize Pool
- ₹50 entry per match per participant
- Pool = participants × 50
- 1st: 50%, 2nd: 30%, 3rd: 20%
- Balance shown on leaderboard + points table
- Calculated on-the-fly from contestant_points (not stored separately)

### Backend Architecture
- `backend/main.py` — FastAPI app, CORS, startup, static file serving
- `backend/database.py` — dual SQLite/PostgreSQL with auto `?` to `%s` translation
- `backend/middleware/auth.py` — Firebase token verification, dev mode fallback
- `backend/models/tournament.py` — scheduler (60s loop), fetches ESPN, computes points
- `backend/routes/` — auth, matches, players, teams, scores, leaderboard, admin
- `backend/services/scraper.py` — ESPN scorecard fetcher
- `backend/services/data_service.py` — DB CRUD operations

### Frontend Architecture
- `frontend/src/App.tsx` — routing (AppLayout wraps protected pages with Navbar)
- `frontend/src/auth/` — Firebase client, AuthContext, ProtectedRoute/AdminRoute
- `frontend/src/pages/` — Login, Register, Dashboard, SelectTeam, ViewScores, Leaderboard, PointsTable
- `frontend/src/pages/admin/` — AdminLayout, AdminDashboard, ManagePlayers, ManageMatches, ManageUsers, ManageTeams, ScoreControl

### Key Features
- Dashboard: Sachin Tendulkar hero bg, Today/Upcoming/Completed tabs
- Select Team: role-grouped players, C/VC selection, cricket ground preview after save
- View Scores: player stats table + contestant rankings + team comparison (Compare tab)
- Leaderboard: podium top 3, tied ranks, balance column, manual refresh
- Points Table: contestants as rows, matches as columns, shows points + net amount
- Admin: CRUD all entities, score recalculation, submit team for users, clear table data

### Scheduler Flow
```
Every 60s:
  future matches → skip
  live matches → scrape ESPN → compute player points → compute contestant totals → save to DB
  over matches → compute once, then skip (checks player_points table)
  per-match error handling (one failure doesn't stop others)
```

### Production DB Access
```
(credentials removed — use Render dashboard)
```

### Build & Deploy
- `build.sh` — installs deps, builds React, seeds DB from Excel
- `render.yaml` — Render blueprint config
- Start: `python -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Static files: FastAPI serves `frontend/dist/` in production
