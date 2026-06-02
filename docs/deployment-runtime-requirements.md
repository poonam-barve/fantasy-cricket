# Deployment And Runtime Requirements

This document defines environment, startup, deployment, and runtime behavior.

## Backend Runtime

- FastAPI application lives in `backend/main.py`.
- Uvicorn is the expected ASGI server.
- Backend serves API routes under `/api`.
- In production-style builds, backend can serve the built frontend SPA.
- Unknown frontend paths should fall back to SPA index where static serving is active.

## Startup Sequence

Startup must:

1. Load environment variables.
2. Initialize database schema.
3. Seed database only when required and safe.
4. Normalize player types.
5. Initialize Firebase if credentials exist.
6. Include all routers.
7. Prime caches.
8. Start background schedulers once.
9. Warm live/today match data where applicable.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string; absence means SQLite |
| `SECRET_KEY` | App secret |
| `FIREBASE_CREDENTIALS_PATH` | Firebase service account file path |
| `FIREBASE_CREDENTIALS` | Firebase service account JSON string |
| `APP_CURRENT_DATETIME` | Override app current datetime for testing |
| `APP_CURRENT_DATE` | Override date when paired with time |
| `APP_CURRENT_TIME` | Override time when paired with date |
| `PORT` | Deployment port where used by platform |

Frontend variables:

- Firebase web config variables when not hardcoded.
- Vite dev server proxy must forward `/api` to backend in local dev.

## Health And Status

- `GET /api/health` returns basic OK status.
- `GET /api/status` should expose boot/scheduler/database counts for operational checks.
- `GET /api/runtime/current-time` exposes current app time and whether it is overridden.

## Database Runtime

- PostgreSQL connections must reconnect after common closed/SSL failure errors.
- SQLite must use WAL mode, foreign keys, and busy timeout.
- Schema initialization must be idempotent.

## Static Assets

Required public assets referenced by UI include:

- `mahi.jpg`
- `podium.jpeg`
- `loserclub.jpg`
- any existing hero/team images referenced by frontend components.

Assets must be included in frontend build output or served from public root.

## Local Scripts

Useful scripts and files:

- `start.bat`
- `start.sh`
- `setup.bat`
- `setup.sh`
- `docker-compose.postgres.yml`
- `backend/scripts/seed_db.py`
- `backend/scripts/sync_sqlite_to_postgres.py`
- `backend/scripts/bootstrap_local_postgres.py`

## Deployment Targets

The app should support:

- Local Vite + FastAPI.
- Docker.
- Render/Railway-style Python web service.
- Neon PostgreSQL.

## Security Requirements

- Do not commit real database URLs, Firebase service account files, or local env files.
- Rotate database credentials that were pasted into chats or terminal history.
- Admin routes must never trust frontend-only role checks.
- Dev Login should be considered local-only behavior.

## Acceptance Criteria

- App starts with SQLite and no Firebase credentials.
- App starts with PostgreSQL `DATABASE_URL`.
- App can serve API and frontend routes after build.
- Health/status endpoints work before live score caches are warm.
- Scheduler errors do not crash the server.
