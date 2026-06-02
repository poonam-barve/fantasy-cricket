# Local Setup Requirements

This document defines the required local development setup for running the app with either SQLite or local PostgreSQL.

## Supported Local Database Modes

### SQLite

- Default mode when `DATABASE_URL` is not set.
- Database file: `backend/fantasy.db`.
- Good for quick development and isolated tests.

### Local PostgreSQL

- Used when `DATABASE_URL` points to a local PostgreSQL database.
- Recommended when testing Neon production-like behavior.
- pgAdmin 4 is only a UI; a local PostgreSQL server must also be installed and running.

Example local PostgreSQL URL without password:

```env
DATABASE_URL=postgresql://postgres@127.0.0.1:5432/FantasyCricketProd
```

Example local PostgreSQL URL with password:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/FantasyCricketProd
```

## Environment Files

- `.env.example` and `.env.local.example` document expected variables.
- `.env.local` may contain local secrets and must not be committed.
- Production Neon connection strings must not be committed.

Common variables:

- `DATABASE_URL`
- `FIREBASE_CREDENTIALS_PATH`
- Frontend Firebase variables when using Firebase login.

## Local Auth Modes

### Firebase Auth

- Requires Firebase Admin credentials for backend token verification.
- Requires Firebase client config for frontend login/register.

### Dev Login

- Works without Firebase.
- Login page button: `Dev Login (No Password)`.
- Backend endpoint: `GET /api/auth/dev-login`.
- Protected requests use header `X-Dev-Login: 1`.
- Frontend stores `fantasy_cricket_dev_login=1` in `localStorage`.
- Dev login selects the first active user by id unless changed in code.

Requirement:

- Local database must contain at least one active user.
- Admin testing requires the selected dev-login user to have `role = 'admin'`.

## Copy Neon To Local PostgreSQL

Prerequisites:

- PostgreSQL command-line tools installed.
- Example tools path on Windows: `C:\Program Files\PostgreSQL\18\bin`.
- Local PostgreSQL server running.
- Local database created, for example `FantasyCricketProd`.

Dump Neon:

```cmd
"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" "postgresql://USER:PASSWORD@HOST/DB?sslmode=require" --format=custom --no-owner --no-acl --file="D:\Sushant\fantasy-cricket-poonam\neon_backup.dump"
```

Create local database:

```cmd
"C:\Program Files\PostgreSQL\18\bin\createdb.exe" -h localhost -U postgres "FantasyCricketProd"
```

Restore local database:

```cmd
"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --host=localhost --port=5432 --username=postgres --dbname="FantasyCricketProd" --no-owner --no-acl --clean --if-exists "D:\Sushant\fantasy-cricket-poonam\neon_backup.dump"
```

## Upload Local PostgreSQL Back To Neon

Dump local database:

```cmd
"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -h localhost -p 5432 -U postgres -d "FantasyCricketProd" --format=custom --no-owner --no-acl --file="D:\Sushant\fantasy-cricket-poonam\local_backup.dump"
```

Restore to Neon:

```cmd
"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --dbname="postgresql://USER:PASSWORD@HOST/DB?sslmode=require" --no-owner --no-acl --clean --if-exists "D:\Sushant\fantasy-cricket-poonam\local_backup.dump"
```

Requirement:

- Treat restore-to-Neon as destructive unless restoring into a new branch/database.
- Prefer restoring to a Neon branch first, verifying, then switching production.
- Rotate any database password that has been pasted into chat, terminal history, or docs.

## Running The App Locally

Backend requirements:

- Python virtual environment.
- Dependencies installed from `requirements.txt` or backend requirements file if split.
- Database initialized by app startup.

Frontend requirements:

- Node.js installed.
- Dependencies installed in `frontend`.
- Frontend dev server pointed at the backend through existing proxy/config behavior.

## Verification Checklist

- `psql --version` works.
- Local PostgreSQL service is running when using Postgres.
- `psql -h localhost -U postgres -d FantasyCricketProd` connects.
- Backend starts without database errors.
- Login page dev login succeeds.
- Dashboard loads matches.
- Select Team can load existing local data.
- View Scores can load a match.
- Admin route works for an admin user.

## Acceptance Criteria

- A developer can run the app locally with SQLite and no external DB.
- A developer can run the app locally against a restored Neon PostgreSQL copy.
- Firebase is optional for local development because dev login is available.
- Local setup docs do not contain real production passwords.
