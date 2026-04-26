# Fantasy Cricket — Hippies Mahasangram

A full-stack fantasy cricket web application for IPL where users pick 11-player teams, designate a Captain (2x points) and Vice Captain (1.5x points), and compete on a live leaderboard.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [Backend API Reference](#backend-api-reference)
- [Scoring Engine](#scoring-engine)
- [How It Works (User Flow)](#how-it-works-user-flow)
- [Admin Dashboard](#admin-dashboard)
- [Live Score System](#live-score-system)
- [Authentication](#authentication)
- [Setup & Installation](#setup--installation)
- [Running Locally](#running-locally)
- [Environment Variables](#environment-variables)
- [Deployment](#deployment)

---

## Overview

Fantasy Cricket is a private fantasy league app built for a group of friends ("Hippies Mahasangram"). Each IPL match, every user selects a team of 11 players before the match starts. Once the match begins, the app automatically scrapes live scorecards from [howstat.com](https://www.howstat.com), calculates fantasy points for each player, and ranks all contestants on a leaderboard.

### Key Features

- **User Registration & Login** via Firebase Authentication (email/password)
- **Team Selection** — pick 11 players grouped by role (WK, BAT, AR, BWL) with Captain & Vice Captain
- **Match Locking** — teams can't be changed after match start time
- **Live Score Scraping** — background scheduler fetches scorecards every 60 seconds
- **Fantasy Points Engine** — comprehensive scoring system (runs, wickets, fielding, milestones, strike rate, economy)
- **Leaderboard** — real-time rankings across all matches
- **Points Table** — match-by-match breakdown per contestant
- **Admin Dashboard** — manage players, matches, users, and trigger score recalculation
- **Mobile-First UI** — responsive React + Tailwind CSS design

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | React 19 + TypeScript | User interface |
| **Styling** | Tailwind CSS 3 | Mobile-first responsive design |
| **Build Tool** | Vite 5 | Fast development server & bundler |
| **Routing** | React Router DOM 7 | Client-side navigation |
| **HTTP Client** | Axios | API calls with auth token interceptor |
| **Backend** | FastAPI (Python) | REST API server |
| **Database** | SQLite | Local file-based relational database |
| **Authentication** | Firebase Auth | Email/password login, token verification |
| **Scraping** | BeautifulSoup4 + Requests | Parse IPL scorecards from howstat.com |
| **Timezone** | pytz | IST timezone handling |

---

## Project Structure

```
fantasy-cricket/
│
├── backend/                          # FastAPI Backend
│   ├── main.py                       # App entry point, CORS, startup, routes
│   ├── config.py                     # Configuration constants
│   ├── database.py                   # SQLite connection & schema initialization
│   ├── firebase_setup.py             # Firebase Admin SDK initialization
│   ├── firebase-credentials.json     # Firebase service account key (gitignored)
│   ├── fantasy.db                    # SQLite database file (gitignored)
│   │
│   ├── middleware/
│   │   └── auth.py                   # Firebase token verification & role guards
│   │
│   ├── models/                       # Domain Models (Business Logic)
│   │   ├── player.py                 # Player stats + fantasy points calculator
│   │   ├── match.py                  # HTML scorecard parser
│   │   ├── registry.py               # Player name/alias lookup system
│   │   ├── team.py                   # Team & Contestant classes
│   │   └── tournament.py             # Tournament orchestrator & background scheduler
│   │
│   ├── routes/                       # API Route Handlers
│   │   ├── auth.py                   # POST /api/auth/register, GET /api/auth/me
│   │   ├── matches.py                # GET /api/matches
│   │   ├── players.py                # GET /api/players
│   │   ├── teams.py                  # GET/POST /api/teams
│   │   ├── scores.py                 # GET /api/scores/:id
│   │   ├── leaderboard.py            # GET /api/leaderboard, /api/points-table
│   │   └── admin.py                  # Admin CRUD + score recalculation
│   │
│   ├── services/
│   │   ├── data_service.py           # SQLite read/write operations
│   │   └── scraper.py                # Fetches scorecard HTML from howstat.com
│   │
│   ├── scripts/
│   │   └── seed_db.py                # Seed database from JSON files
│   │
│   └── requirements.txt              # Python dependencies
│
├── frontend/                         # React Frontend
│   ├── index.html                    # HTML entry point
│   ├── package.json                  # Node dependencies
│   ├── vite.config.ts                # Vite config with API proxy
│   ├── tailwind.config.js            # Tailwind CSS config
│   ├── postcss.config.js             # PostCSS config
│   │
│   └── src/
│       ├── main.tsx                  # React entry point
│       ├── App.tsx                   # Router & layout
│       ├── index.css                 # Tailwind base styles
│       │
│       ├── api/
│       │   └── client.ts             # Axios instance with Firebase token interceptor
│       │
│       ├── auth/
│       │   ├── firebase.ts           # Firebase client SDK config
│       │   ├── AuthContext.tsx        # Auth state provider (login/register/logout)
│       │   └── ProtectedRoute.tsx    # Route guards (user & admin)
│       │
│       ├── types/
│       │   └── index.ts              # TypeScript type definitions
│       │
│       ├── components/
│       │   ├── Navbar.tsx             # Top navigation bar
│       │   └── LoadingSpinner.tsx     # Loading indicator
│       │
│       └── pages/
│           ├── Login.tsx              # Login page
│           ├── Register.tsx           # Registration page
│           ├── Dashboard.tsx          # Match list & quick actions
│           ├── SelectTeam.tsx         # 11-player team picker
│           ├── ViewScores.tsx         # Live match scores & stats
│           ├── Leaderboard.tsx        # Overall rankings
│           ├── PointsTable.tsx        # Match-by-match breakdown
│           │
│           └── admin/                 # Admin Dashboard
│               ├── AdminLayout.tsx    # Sidebar layout
│               ├── AdminDashboard.tsx # Summary stats
│               ├── ManagePlayers.tsx  # Player CRUD
│               ├── ManageMatches.tsx  # Match CRUD
│               ├── ManageUsers.tsx    # User management
│               └── ScoreControl.tsx   # Recalculate scores & clear data
│
└── data/                             # Seed data (JSON files)
    ├── players.json                  # 100 IPL players
    ├── matches.json                  # Sample matches
    └── users.json                    # Demo users
```

---

## Database Schema

SQLite database with 6 tables stored in `backend/fantasy.db`.

### `users` — Registered app users

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment unique ID |
| `firebase_uid` | TEXT UNIQUE | Firebase Authentication UID |
| `email` | TEXT UNIQUE | User email address |
| `name` | TEXT | Display name |
| `mobile` | TEXT | Optional phone number |
| `role` | TEXT | `'user'` or `'admin'` (controls dashboard access) |
| `is_active` | INTEGER | 1 = active, 0 = disabled by admin |
| `created_at` | TEXT | ISO timestamp of registration |

### `players` — IPL cricketers

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Unique player ID |
| `name` | TEXT | Full name (e.g. "Virat Kohli") |
| `team` | TEXT | IPL team code: CSK, RCB, MI, KKR, RR, GT, DC, LSG, PBKS, SRH |
| `role` | TEXT | One of: `Wicketkeeper`, `Batter`, `AllRounder`, `Bowler` |
| `aliases` | TEXT | Comma-separated alternative names for scorecard matching (e.g. "Kohli,VK") |

### `matches` — IPL match schedule

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Unique match ID |
| `team1` | TEXT | First team code |
| `team2` | TEXT | Second team code |
| `match_date` | TEXT | Date in `YYYY-MM-DD` format |
| `match_time` | TEXT | Time in `HH:MM` format (IST) |
| `status` | TEXT | `future`, `live`, or `over` (computed by scheduler) |

### `user_teams` — Fantasy team selections

Each user picks 11 players per match. This creates 11 rows per user per match.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user_id` | INTEGER FK → users | Who selected this team |
| `match_id` | INTEGER FK → matches | For which match |
| `player_id` | INTEGER FK → players | Which player was picked |
| `is_captain` | INTEGER | 1 = Captain (points multiplied by 2x) |
| `is_vice_captain` | INTEGER | 1 = Vice Captain (points multiplied by 1.5x) |

**Constraint:** `UNIQUE(user_id, match_id, player_id)` — no duplicate picks.

### `contestant_points` — User scores per match

Computed by the background scheduler after parsing scorecards.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user_id` | INTEGER FK → users | Which user |
| `match_id` | INTEGER FK → matches | Which match |
| `points` | REAL | Total fantasy points (sum of 11 players with C/VC multipliers) |
| `last_updated` | TEXT | When this was last computed |

**Constraint:** `UNIQUE(user_id, match_id)` — one score per user per match.

### `player_points` — Individual player fantasy points per match

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `match_id` | INTEGER FK → matches | Which match |
| `player_id` | INTEGER FK → players | Which player |
| `player_name` | TEXT | Player name (denormalized for display) |
| `team` | TEXT | Team code |
| `role` | TEXT | Player role |
| `points` | REAL | Fantasy points earned in this match |
| `last_updated` | TEXT | When this was last computed |

**Constraint:** `UNIQUE(match_id, player_id)` — one score per player per match.

### Entity Relationship

```
users (1) ──── (many) user_teams (many) ──── (1) players
  │                       │
  │                       │
  │                    matches (1) ──── (many) player_points (many) ──── (1) players
  │                       │
  └──── contestant_points ┘
```

---

## Backend API Reference

All endpoints are prefixed with `/api`. Protected routes require a Firebase Bearer token in the `Authorization` header.

### Authentication

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/auth/register` | Firebase token | Create user record after Firebase signup. Body: `{name, email?, mobile?}` |
| `GET` | `/api/auth/me` | Required | Get current user profile |

### Matches

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/matches` | Required | List all matches with computed `status` and `locked` fields |

### Players

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/players?match_id=X` | Required | Players for a match grouped by role. Without `match_id`, returns all. |

### Teams

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/teams/my?match_id=X` | Required | Current user's team for a match |
| `POST` | `/api/teams` | Required | Submit team. Body: `{match_id, players: [{player_id, is_captain, is_vice_captain}]}`. Validates 11 players, 1+ per role, match not locked. |

### Scores

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/scores/{match_id}` | Required | Player stats + contestant rankings for a match |
| `GET` | `/api/scores/{match_id}/my-team` | Required | Player names in user's team (for highlighting) |

### Leaderboard

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/leaderboard` | Required | Total points per user across all matches, sorted descending |
| `GET` | `/api/points-table` | Required | Per-match points breakdown for all users |

### Admin (requires `role: 'admin'`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/admin/users` | List all users |
| `PUT` | `/api/admin/users/{id}` | Update user role/active status |
| `GET` | `/api/admin/players` | List all players |
| `POST` | `/api/admin/players` | Create player |
| `PUT` | `/api/admin/players/{id}` | Update player |
| `DELETE` | `/api/admin/players/{id}` | Delete player |
| `GET` | `/api/admin/matches` | List all matches |
| `POST` | `/api/admin/matches` | Create match |
| `PUT` | `/api/admin/matches/{id}` | Update match |
| `DELETE` | `/api/admin/matches/{id}` | Delete match |
| `POST` | `/api/admin/recalculate/{match_id}` | Force re-scrape and recompute scores |
| `GET` | `/api/admin/teams?match_id=X` | View all submitted teams |
| `DELETE` | `/api/admin/clear/{table_name}` | Clear all data from a table |

### Health Check

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Returns `{"status": "ok"}` |

---

## Scoring Engine

The scoring engine lives in `backend/models/player.py`. Points are calculated based on real IPL performance.

### Batting Points

| Category | Points | Condition |
|----------|--------|-----------|
| Playing in match | +4 | Player appeared in scorecard |
| Runs scored | +1 per run | Direct accumulation |
| Fours | +4 per four | Boundary bonus (on top of runs) |
| Sixes | +6 per six | Boundary bonus (on top of runs) |
| Century (100+ runs) | +16 | Milestone bonus |
| Half-century (50+ runs) | +8 | Milestone bonus |
| 30+ runs | +4 | Milestone bonus |
| Duck | -2 | Out for 0 (batting roles only: WK, BAT, AR) |

### Strike Rate Bonus/Penalty (min 10 balls faced, batting roles only)

| Strike Rate | Points |
|-------------|--------|
| > 170 | +6 |
| > 150 | +4 |
| >= 130 | +2 |
| <= 70 | -2 |
| < 60 | -4 |
| <= 50 | -6 |

### Bowling Points

| Category | Points | Condition |
|----------|--------|-----------|
| Wickets | +30 per wicket | Each wicket taken |
| 5-wicket haul | +16 | 5 or more wickets |
| 4-wicket haul | +8 | Exactly 4 wickets |
| 3-wicket haul | +4 | Exactly 3 wickets |
| Maiden overs | +12 per maiden | Each maiden over |

### Economy Rate Bonus/Penalty (min 2 overs bowled)

| Economy Rate | Points |
|-------------|--------|
| < 5 | +6 |
| < 6 | +4 |
| <= 7 | +2 |
| >= 10 | -2 |
| > 11 | -4 |
| > 12 | -6 |

### Fielding Points

| Category | Points |
|----------|--------|
| Catch | +8 per catch |
| 3+ catches bonus | +4 |
| Stumping | +12 per stumping |
| Direct run-out | +12 (single fielder) |
| Indirect run-out | +6 (shared between fielders) |

### Captain & Vice Captain Multipliers

| Role | Multiplier |
|------|-----------|
| Captain (C) | 2x all points |
| Vice Captain (VC) | 1.5x all points |
| Regular player | 1x (no multiplier) |

---

## How It Works (User Flow)

### 1. Registration
- User goes to `/register`, enters name + email + password
- Firebase creates auth account
- Backend creates user record in SQLite linked by `firebase_uid`

### 2. Login
- User enters email + password on `/login`
- Firebase verifies credentials, returns ID token
- Frontend stores token, sends it with every API request
- Backend verifies token and identifies user

### 3. Dashboard
- Shows all matches with status badges:
  - **Upcoming** (blue) — team selection open
  - **Live** (green, pulsing) — match in progress, scores updating
  - **Over** (gray) — match completed
- Quick links to Leaderboard and Points Table

### 4. Team Selection (before match starts)
- User clicks "Pick Team" on an upcoming match
- Sees all players from both teams grouped by role
- Must select exactly 11 players with:
  - At least 1 Wicketkeeper
  - At least 1 Batter
  - At least 1 AllRounder
  - At least 1 Bowler
- Designates 1 Captain (2x) and 1 Vice Captain (1.5x)
- Submits team — saved to `user_teams` table
- Can re-submit until match locks

### 5. Match Lock
- When current time >= match start time, the match is **locked**
- No more team changes allowed
- "Pick Team" button changes to "View Scores"

### 6. Live Scoring
- Background scheduler runs every 60 seconds
- For live matches: fetches scorecard from howstat.com, parses HTML, calculates points
- Player points saved to `player_points`
- Contestant totals (with C/VC multipliers) saved to `contestant_points`
- Frontend auto-refreshes scores every 30 seconds

### 7. Leaderboard
- Aggregates `contestant_points` across all matches
- Sorted by total points descending
- Current user highlighted with "YOU" badge
- Auto-refreshes every 15 seconds

---

## Admin Dashboard

Accessible at `/admin` for users with `role: 'admin'`.

### Features

| Section | Capabilities |
|---------|-------------|
| **Dashboard** | Total users, players, matches, live match count |
| **Players** | Search, filter by team, add/edit/delete players |
| **Matches** | Add/edit/delete matches, see status |
| **Users** | Toggle active/inactive, change role (user/admin) |
| **Score Control** | Recalculate scores per match or all, clear table data |

### Making Someone Admin

```sql
-- Using SQLite directly
UPDATE users SET role = 'admin' WHERE email = 'someone@example.com';
```

Or use the Admin → Users page to change any user's role via the dropdown.

---

## Live Score System

### How Scorecard Scraping Works

1. **Scheduler** (`backend/models/tournament.py`) runs a background thread every 60 seconds
2. For each match, determines status:
   - `future` (before start time) → skip
   - `live` (within 5 hours of start) → fetch & compute
   - `over` (5+ hours after start) → fetch once, then cache
3. Fetches HTML from `https://www.howstat.com/Cricket/Statistics/IPL/MatchScorecard.asp?MatchCode=XXXX`
4. **BeautifulSoup** parses:
   - Batting tables → runs, balls, fours, sixes, dismissals
   - Bowling tables → overs, maidens, runs conceded, wickets
   - Did Not Bat lists → marks players as "played"
5. **Dismissal parser** extracts fielding credits:
   - "c Kohli b Bumrah" → catch to Kohli, wicket to Bumrah
   - "run out (Jadeja/Dhoni)" → indirect run-out to both
   - "st Dhoni b Chahal" → stumping to Dhoni, wicket to Chahal
6. Points calculated for each player and saved to database
7. Contestant totals computed with Captain/VC multipliers

### Player Registry (Name Matching)

The scraper encounters names like "VK" or "Kohli" on scorecards. The **PlayerRegistry** (`backend/models/registry.py`) matches these to player IDs:

1. Each player has a name + comma-separated aliases
2. Registry builds lookup: `(team, normalized_name) → player_id`
3. Matching order: full name → last name → first name
4. Names normalized: lowercase, dots removed, spaces collapsed

---

## Authentication

### Firebase Auth (Frontend)
- **SDK:** Firebase Client SDK in `frontend/src/auth/firebase.ts`
- **Methods:** Email/password sign-in and registration
- **State:** Managed via React Context in `AuthContext.tsx`
- **Token:** `getIdToken()` called on each API request via Axios interceptor

### Firebase Admin (Backend)
- **SDK:** Firebase Admin SDK in `backend/firebase_setup.py`
- **Verification:** `verify_id_token(token)` on each protected request
- **Credentials:** Service account JSON file at `backend/firebase-credentials.json`

### Dev Mode
- If no Firebase token is provided, backend falls back to first user in database
- Frontend has a "Dev Login" button that skips Firebase entirely
- Useful for local development without Firebase setup

---

## Setup & Installation

### Prerequisites
- Python 3.10+
- Node.js 20+
- Firebase project with Email/Password authentication enabled

### 1. Clone & Install

```bash
# Backend
cd fantasy-cricket
pip install -r backend/requirements.txt

# Frontend
cd frontend
npm install
```

### 2. Firebase Setup

1. Create a project at [console.firebase.google.com](https://console.firebase.google.com)
2. Enable **Authentication → Email/Password**
3. Go to **Project Settings → Service Accounts → Generate new private key**
4. Save as `backend/firebase-credentials.json`
5. Copy your Firebase web config to `frontend/src/auth/firebase.ts`

### 2b. Local Environment

Create a separate local env file for your machine:

```bash
# From project root
copy .env.local.example .env.local
```

Then edit `.env.local` with your local values. This file is loaded automatically
when the app starts locally.

### 3. Initialize Database

```bash
# From project root
python -m backend.scripts.seed_db
```

This creates `backend/fantasy.db` with sample players, matches, and a demo admin user.

### Optional: Separate Local PostgreSQL DB

If you want to test against PostgreSQL locally, start a separate local database and
copy the current local SQLite snapshot into it:

```bash
# Start Postgres
docker compose -f docker-compose.postgres.yml up -d

# Point the app at local Postgres (PowerShell)
$env:DATABASE_URL="postgresql://postgres@localhost:5432/FantasyDBLocal"

# Copy the current local SQLite data into the local Postgres DB
python -m backend.scripts.sync_sqlite_to_postgres
```

This keeps the app code unchanged while letting you exercise the same data model
against a separate local PostgreSQL database. Live and local databases stay
independent.

---

## Running Locally

### One-Click Start
```bash
start.bat
```

This will:
- create the local Postgres database if it does not already exist
- create any missing tables
- skip automatic workbook seeding during local startup
- start the backend and frontend

After the schema is created, you can restore a data-only backup into the empty
database and then rerun the app if needed.

### Start Backend (Terminal 1)
```bash
cd fantasy-cricket
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Start Frontend (Terminal 2)
```bash
cd fantasy-cricket/frontend
npx vite --host 0.0.0.0 --port 5173
```

### Access
- **App:** http://localhost:5173
- **API:** http://localhost:8000/api
- **API Docs:** http://localhost:8000/docs (Swagger UI)

The Vite dev server proxies `/api` requests to the backend automatically.

---

## Environment Variables

### Backend
| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `fantasy-cricket-dev-secret-key` | Session encryption key |
| `FIREBASE_CREDENTIALS_PATH` | `backend/firebase-credentials.json` | Path to Firebase service account |
| `FIREBASE_CREDENTIALS` | — | JSON string of Firebase credentials (alternative to file) |

### Frontend
| Variable | Description |
|----------|-------------|
| `VITE_FIREBASE_API_KEY` | Firebase API key (or hardcode in firebase.ts) |
| `VITE_FIREBASE_AUTH_DOMAIN` | Firebase auth domain |
| `VITE_FIREBASE_PROJECT_ID` | Firebase project ID |

---

## Deployment

### Option 1: Render.com (Recommended)

1. Push to GitHub
2. Create a **Web Service** on Render
3. Build command: `cd frontend && npm install && npm run build && cd .. && pip install -r backend/requirements.txt`
4. Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables: `FIREBASE_CREDENTIALS`, `SECRET_KEY`
6. Configure FastAPI to serve `frontend/dist/` as static files

### Option 2: Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -r backend/requirements.txt
RUN apt-get update && apt-get install -y nodejs npm
RUN cd frontend && npm install && npm run build
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Option 3: Separate Deploys
- **Backend** → Render / Railway / Fly.io
- **Frontend** → Vercel / Netlify (set API URL via env var)

---

## Credits

Built with FastAPI, React, Firebase, SQLite, Tailwind CSS, and BeautifulSoup.

Scorecard data sourced from [howstat.com](https://www.howstat.com).
