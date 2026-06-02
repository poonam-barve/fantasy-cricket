# Test Plan Requirements

This document defines the test coverage needed to recreate the app confidently.

## Test Levels

Required coverage should include:

- Unit tests for scoring, parsing, penalties, and bonus calculations.
- API tests for protected/user/admin endpoints.
- Integration tests for database writes and cache invalidation.
- Frontend interaction tests for core user journeys.
- Manual smoke tests for local PostgreSQL restore and dev login.

## Auth Tests

- Firebase token success maps to existing user.
- Missing token returns `401`.
- Invalid token returns `401`.
- Inactive user returns `403`.
- Dev login returns first active user.
- Dev login returns `404` when no active users exist.
- Non-admin accessing admin endpoint returns `403`.

## Team Selection Tests

- Save exactly 11 players succeeds.
- Fewer than 11 players fails.
- More than 11 players fails.
- Missing Captain fails.
- Missing Vice-Captain fails.
- Same Captain and Vice-Captain fails.
- Invalid player id fails.
- Player outside match teams fails.
- Locked match save fails.
- Backups exclude selected players.
- Backup order persists.
- Prediction save persists.
- Prediction-only update does not change team rows.

## Scoring Tests

Use deterministic player stat fixtures for:

- Playing XI points.
- Runs, fours, sixes.
- 30/50/75/100 milestone exclusivity.
- Duck penalty for batting roles only.
- Strike-rate bonuses and penalties at boundary values.
- Wickets.
- Bowled/LBW bonus.
- 3/4/5 wicket haul exclusivity.
- Maidens.
- Dot balls.
- Economy bonuses and penalties at boundary values.
- Catches and 3-catch bonus.
- Stumping.
- Direct and indirect run outs.
- Captain `2x`.
- Vice-Captain `1.5x`.

## Score Prediction Tests

- No prediction means no bonus.
- Exact prediction awards `+500`.
- If exact exists, within-5 users get no bonus.
- No exact but within 5 awards `+200` to closest.
- No within 5 but within 10 awards `+100` to closest.
- Tied closest users all receive full bonus.
- Prediction bonus applies only after match completion.
- Weekend Battle raw points exclude prediction bonus.

## Leaderboard Tests

- Active users appear.
- Inactive users are excluded.
- Completed match totals sum correctly.
- Non-participants receive adjusted points.
- Adjusted points are 15% below lowest participant and rounded to nearest 0.5.
- Adjusted users do not affect prize pool.
- Balance uses entry fee 50 and 50/30/20 prize split.
- Medals handle ties.
- Rank movement compares cumulative rank after each completed match.
- Weekend and Super Team bonuses are added once.
- Points table export includes match rows, bonus rows, and total row.

## Weekend Battle Tests

- Detect weekend with 1, 2, 3, and 4 matches.
- Choose latest match before Saturday as qualifier.
- Seed top `2^n` users.
- Backfill from leaderboard when qualifier participants are fewer than bracket size.
- Drop odd last participant.
- Shuffle once at seeding.
- Advance fixed bracket path.
- Missing team scores 0.
- Tie uses overall leaderboard rank.
- Champion bonus is `+200`.
- Match 70-74 knockout bonus is `+400`.
- Re-running detect/seed/advance is idempotent.

## Super Team Tests

- Selection opens only when context is enabled.
- Exactly 12 players required.
- Role requirements enforced.
- C/VC required and distinct.
- Initial lock prevents edits.
- Window 1 compares original to edited.
- Window 2 compares edited to final.
- No edit copies previous snapshot.
- Match 71/72 use original.
- Match 73 uses edited.
- Match 74 uses final.
- VC `1.25x` rounds up to next 0.5.
- Penalty values match role and phase.
- Returning to an original player in Window 2 counts as new relative to edited.
- Final bonuses rank 1/2/3 as 1000/600/300.

## Scheduler And Cache Tests

- Startup creates schedulers once.
- Score scheduler survives one match refresh error.
- Score completion persists player and contestant points.
- Cache invalidates after team save.
- Cache invalidates after admin team edit.
- Cache invalidates after score recalculation.
- Scores response cache uses previous payload during refresh failure.
- Leaderboard cache refresh updates points table.

## Frontend Smoke Tests

- Login page renders and dev login works.
- Dashboard loads and tabs switch.
- Select Team can save a valid team.
- Locked match disables save.
- View Scores shows contestants and team breakdown.
- Team comparison works.
- Leaderboard sorting works.
- Points table export button downloads a file.
- Admin users can access admin layout.
- Non-admin users cannot.
- Mobile viewport has no overlapping sticky footer or table controls.

## Local Setup Tests

- App starts with no `DATABASE_URL` using SQLite.
- App starts with local PostgreSQL `DATABASE_URL`.
- Restored Neon dump connects locally.
- Dev login works without Firebase credentials.
- Admin user can access `/admin`.

## Regression Fixtures

Keep fixtures for known bug classes:

- Weekend tournament stale/incomplete `contestant_points`.
- ESPN dot-ball parsing.
- Backup substitutions after Playing XI announcement.
- Super Team phase snapshot scoring.
- Prediction bonus tier tie handling.
