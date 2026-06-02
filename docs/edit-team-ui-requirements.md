# Edit Team UI Requirements

This document defines the requirements for the regular match team selection UI at `/select-team/:matchId`.

## Scope

- Users select a fantasy team for one scheduled match.
- The UI supports initial selection, editing before lock, captain and vice-captain assignment, backup selection, and score prediction.
- The UI must work for desktop and mobile without layout overlap or hidden actions.

## Primary Files

| File | Responsibility |
|------|----------------|
| `frontend/src/pages/SelectTeam.tsx` | Team selection page, validation, save flow, prediction modal |
| `frontend/src/api/client.ts` | Auth headers and dev-login header injection |
| `backend/routes/teams.py` | Team save, my team, backups, prediction endpoints |
| `backend/services/data_service.py` | Team, backup, contestant, and prediction persistence helpers |

## Entry Points

- Dashboard opens team selection for future or editable matches.
- Route: `/select-team/:matchId`.
- The page must load match details, eligible players, existing team, existing backups, lineup status, and existing score prediction.

## Team Selection Rules

- A valid team has exactly `11` selected players.
- Users must choose one Captain and one Vice-Captain.
- Captain and Vice-Captain must be different players.
- Selected players must be from the two teams in the match.
- The UI must prevent duplicate player selection.
- The UI must clearly show selected count, Captain state, Vice-Captain state, and save eligibility.

## Locking Rules

- Team editing locks when the match starts according to the backend match/toss cutoff logic.
- Once locked:
  - Player selection cannot be changed.
  - Captain and Vice-Captain cannot be changed.
  - Backups cannot be changed.
  - Score prediction cannot be changed.
- The backend remains authoritative. The UI should disable actions, but the API must still reject locked saves.

## Backup Selection

- Users may save up to `3` backup players.
- Backups cannot be players already in the selected 11.
- Backups must be valid players.
- Backup order matters and is persisted as `backup_order`.
- If Playing XI data later marks selected players as substitutes, active backup replacement logic may replace them.
- The UI must communicate backup count and selected backup order.

## Score Prediction Flow

- First team save may include optional `predicted_points`.
- If the user skips prediction, the team still saves.
- If the user already has a team:
  - Existing prediction is shown in the sticky footer.
  - Missing prediction can be added before lock.
  - Existing prediction can be edited before lock without re-saving the team.
- Prediction update endpoint: `PATCH /api/teams/prediction`.

## API Requirements

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/teams/my?match_id=X` | Existing team and prediction |
| `GET` | `/api/teams/my-backups?match_id=X` | Existing backup order |
| `GET` | `/api/teams/my-lineup-statuses` | Per-match user team and lineup status summaries |
| `GET` | `/api/teams/my-backup-counts` | Backup counts for requested matches |
| `POST` | `/api/teams` | Save selected team, backups, and optional prediction |
| `PATCH` | `/api/teams/prediction` | Update only the prediction |

## Save Behavior

- Save must be atomic from the user's perspective:
  - Delete/update previous selected players for that user and match.
  - Insert current selected players with C/VC flags.
  - Save backups.
  - Prune backups that conflict with the selected team.
  - Save prediction if provided.
  - Refresh/invalidate relevant team and contestant caches.
- On success, the UI should show the saved team preview.
- On failure, the UI should preserve the user's current local selections and show the backend error.

## UI Requirements

- The player list must support fast scanning by player name, team, role, and selection state.
- Selected players must be visually distinct from unselected players.
- Captain and Vice-Captain controls must be available only for selected players.
- The sticky footer must remain usable on mobile and must not cover required controls.
- Loading, empty, saving, saved, locked, and error states are required.
- Text must fit in buttons and player rows at mobile widths.

## Acceptance Criteria

- A user can open a future match, select 11 players, assign C/VC, choose backups, optionally predict points, and save.
- Reloading the page shows the same team, backups, C/VC, and prediction.
- Saving with fewer or more than 11 players is blocked.
- Saving without C/VC or with the same C/VC is blocked.
- After match lock, UI actions are disabled and backend save attempts fail.
- Adding or editing only a prediction does not change the saved team.
- Dev login works without Firebase when local mode is enabled.
