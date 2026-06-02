# Scheduler And Caching Requirements

This document defines requirements for background scheduler ticks, cache priming, cache invalidation, and live refresh behavior.

## Goals

- Keep live match scores, lineups, toss details, leaderboard, and subcontest state fresh.
- Avoid blocking user requests on expensive scraping or recomputation when a cached payload is available.
- Make startup idempotent so multiple imports or reloads do not spawn duplicate scheduler threads.
- Ensure admin changes invalidate and refresh affected caches.

## Primary Files

| File | Responsibility |
|------|----------------|
| `backend/main.py` | Startup priming and scheduler startup |
| `backend/models/tournament.py` | Score scheduler, lineup cache scheduler, toss cache scheduler |
| `backend/routes/scores.py` | Scores response double-buffer cache and scheduler |
| `backend/routes/leaderboard.py` | Leaderboard cache and scheduler |
| `backend/services/data_service.py` | Static, team, prediction, contestant, and selection caches |
| `backend/services/scraper.py` | External scorecard, Playing XI, toss, and live metadata caches |
| `backend/services/double_buffer_cache.py` | Atomic cache publish/read helper |
| `backend/services/cache_locks.py` | Shared named locks |

## Startup Requirements

On app startup, the backend should:

- Initialize database schema.
- Seed static data only when required.
- Initialize Firebase when credentials are available, while allowing dev mode when unavailable.
- Prime static cache domains such as users, players, and matches.
- Prime score prediction cache.
- Prime contestant/team caches.
- Prime Super Team and Weekend Battle caches.
- Prime venue/live metadata caches for active matches where relevant.
- Start score, lineup, toss, scores-response, and leaderboard schedulers once.

## Scheduler Threads

| Scheduler | Owner | Purpose |
|-----------|-------|---------|
| Score scheduler | `Tournament.start_scheduler()` | Refresh scorecards, compute points, persist completed matches |
| Lineup cache scheduler | `Tournament.start_lineup_cache_scheduler()` | Refresh Playing XI and backup replacement opportunities |
| Toss cache scheduler | `Tournament.start_toss_cache_scheduler()` | Refresh toss winner/decision and lock metadata |
| Scores cache scheduler | `scores.start_scores_cache_scheduler()` | Publish full score payload snapshots for live/NR matches |
| Leaderboard cache scheduler | `leaderboard.start_leaderboard_cache_scheduler()` | Keep leaderboard response warm |

Each scheduler must:

- Use a module-level started flag and lock.
- Run in a daemon thread.
- Catch and log exceptions without killing the process.
- Sleep between ticks according to match urgency.
- Avoid duplicate thread creation on repeated startup code paths.

## Score Tick Requirements

The score scheduler must:

- Load matches from cache or database.
- Identify future, live, no-result, and completed matches.
- Refresh live scorecards and compute fantasy points.
- Persist `player_points` and `contestant_points` when a match is complete.
- Apply backup replacements only when Playing XI and substitute data are final enough.
- Trigger Weekend Battle progression when a relevant match completes.
- Invalidate leaderboard, match response, score response, and achievement caches when points change.

## Scores Response Cache

- Use double-buffer publishing so readers either see the old complete snapshot or the new complete snapshot.
- Cache keys should be match ids.
- Live/NR matches should be eligible for scheduled refresh.
- Completed match payloads can be computed from stored data and do not need aggressive polling.
- Cache misses may compute on demand, then publish/update the snapshot.

## Data Service Cache Domains

| Cache | Requirement |
|-------|-------------|
| Static cache | Users, players, matches must be invalidated after admin CRUD or seed changes |
| Score prediction cache | Must update immediately after prediction save |
| Team contestant cache | Must invalidate after team save/admin team edit |
| Match team selection cache | Must invalidate after user/admin team changes or backup application |
| User team summary cache | Must refresh for dashboard and lineup status summaries |
| Player match payload cache | Must invalidate when score or lineup data changes |

## Cache Invalidation Requirements

Invalidate or refresh caches after:

- User team save.
- Backup save or backup application.
- Prediction save.
- Admin player/match/user CRUD.
- Admin team edit or submit.
- Score recalculation.
- Match completion.
- Weekend Battle detect/seed/advance.
- Super Team save, snapshot finalization, or recalculation.
- Unknown player detection that affects admin review.

## Admin Refresh Requirements

Admin operations that change source data must:

- Commit database changes first.
- Invalidate impacted cache domains.
- Prime expensive caches in a background thread where possible.
- Return a clear success response even if a non-critical cache prime fails, while logging the failure.

## Observability Requirements

- Scheduler logs should include channel names such as `SCORE`, `XI`, `TOSS`, `ScoresCache`, or `Leaderboard`.
- Tick logs should include eligible/refreshed/error counts where available.
- Slow auth and API timing logs may remain for operational debugging.
- Errors should include match id where possible.

## Acceptance Criteria

- App startup creates each scheduler once.
- Live score payloads are available from cache after the first successful refresh.
- Admin recalculation updates score page and leaderboard without process restart.
- Team saves update dashboard contestant lists and score comparison data.
- A scraper failure in one tick does not stop future ticks.
- Completed match persistence triggers Weekend Battle progression and achievement invalidation.
