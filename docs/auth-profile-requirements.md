# Auth And Profile Requirements

This document defines authentication, registration, profile, and local dev-login behavior.

## Auth Modes

### Firebase Mode

- Frontend uses Firebase Auth email/password.
- Backend verifies ID tokens with Firebase Admin SDK.
- Protected requests send `Authorization: Bearer <id-token>`.
- Backend maps Firebase token `uid` to `users.firebase_uid`.

### Dev Login Mode

- Frontend login page provides `Dev Login (No Password)`.
- Dev login calls `GET /api/auth/dev-login`.
- Frontend stores `fantasy_cricket_dev_login=1` in `localStorage`.
- Axios adds `X-Dev-Login: 1` when no Firebase user is present and dev-login storage is enabled.
- Backend `get_current_user` accepts `X-Dev-Login` and returns the first active user by id.

## Registration

Endpoint: `POST /api/auth/register`.

Firebase-token flow:

- Verify Firebase token.
- If `firebase_uid` already exists, return existing user.
- If email already exists, attach Firebase UID to that user and return it.
- Otherwise create a new user.
- First user becomes admin; later users default to user.

Dev fallback flow:

- If no valid token is provided, `email` is required.
- `firebase_uid` is generated as `dev_<email>`.
- Existing user by firebase UID or email is returned.
- Otherwise create a user.

## Current User

Endpoint: `GET /api/auth/me`.

Requirements:

- Requires Firebase token or dev-login header.
- Returns the current database user row.
- Inactive users receive `403`.
- Missing/invalid auth receives `401`.

## Dev Login Endpoint

Endpoint: `GET /api/auth/dev-login`.

Requirements:

- Returns first active user ordered by id.
- Returns `404` when there are no active users.
- Intended for local development only.

## Profile Update

Endpoint: `PATCH /api/auth/me`.

Body:

- `name`
- optional `replace_substitutes_with_backups`

Requirements:

- Name is required after trimming.
- Name max length is 50.
- Backup preference updates when provided.
- User cache must be invalidated after update.

## Logout

Frontend logout must:

- Sign out Firebase user.
- Clear backend profile state.
- Remove `fantasy_cricket_dev_login` from local storage.

## Admin Authorization

- `require_admin` depends on `get_current_user`.
- User role must be `admin`.
- Non-admin receives `403`.

## Acceptance Criteria

- Firebase login loads backend profile.
- Firebase user not registered in app is signed out with a clear error.
- Dev login works with local DB and no Firebase credentials.
- Disabled users cannot access protected APIs.
- Admin pages are inaccessible to non-admins.
