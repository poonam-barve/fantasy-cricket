# Subcontest Requirements

This document consolidates requirements for app features that add points, rankings, or contests beyond the regular single-match fantasy team.

## Subcontest Inventory

| Subcontest | Status | Primary Docs |
|------------|--------|--------------|
| Weekend Battle | Implemented/design documented | [weekend-tournament-design.md](weekend-tournament-design.md), [subcontest-rules.md](subcontest-rules.md) |
| Super Team | Implemented/active requirements | [super-team-requirements.md](super-team-requirements.md), [subcontest-rules.md](subcontest-rules.md) |
| Score Prediction Bonus | Implemented/design documented | [score-prediction-design.md](score-prediction-design.md) |
| Achievements | Implemented/design documented | [achievements-design.md](achievements-design.md) |

## Common Requirements

- Subcontest rules must be deterministic from stored database state.
- Bonus points must be visible wherever they affect leaderboard totals.
- Each subcontest must define whether it affects:
  - Per-match score ranking.
  - Overall leaderboard.
  - Achievements.
  - Weekend Battle head-to-heads.
  - Prize/balance calculations.
- Admin recalculation must be able to recompute derived results without changing user selections.
- Cache invalidation must happen when subcontest source data changes.

## Weekend Battle Requirements

- Detection runs on boot and can be triggered by admin.
- A weekend exists when Saturday and/or Sunday have scheduled matches.
- The qualifier is the latest match before that Saturday.
- Bracket size is `2^n`, where `n` is the number of weekend matches.
- Qualified users are seeded from qualifier match points, then backfilled from overall leaderboard if needed.
- Initial bracket is randomly shuffled once.
- Later rounds follow fixed bracket paths.
- Head-to-head results use raw match fantasy points only.
- Score prediction bonuses do not affect head-to-head results.
- Tie-breaker is higher overall leaderboard rank.
- Champion bonus:
  - Regular Weekend Champion: `+200` leaderboard points.
  - Match `70`-`74` knockout champion: `+400` leaderboard points.

## Super Team Requirements

- Runs across playoff matches `71` through `74`.
- Users select exactly `12` players.
- Role requirements:
  - At least one Wicketkeeper.
  - At least one Batter.
  - At least one AllRounder.
  - At least four Bowlers.
- Captain multiplier is `1.5x`.
- Vice-Captain multiplier is `1.25x`, rounded up to the next `0.5`.
- Match `71` and `72` use original snapshot.
- Match `73` uses edited snapshot.
- Match `74` uses final snapshot.
- Window 1 opens after Match `72` completion and locks before Match `73` toss.
- Window 2 opens after Match `73` completion and locks before Match `74` toss.
- Penalties are phase based and do not compare final team directly to original team.
- Final leaderboard bonuses:
  - Rank 1: `+1000`
  - Rank 2: `+600`
  - Rank 3: `+300`

## Score Prediction Bonus Requirements

- Users may predict their regular match team total before lock.
- One prediction per user per match.
- Tiers:
  - Exact: `+500`
  - Within 5: `+200`
  - Within 10: `+100`
- Tiers are evaluated top-down.
- The first tier with eligible users wins.
- Within the winning tier, closest diff wins.
- Tied closest users all receive the full bonus.
- Prediction bonus affects regular match score ranking and overall leaderboard.
- Prediction bonus does not affect Weekend Battle head-to-heads.

## Achievements Requirements

- Achievements are derived from completed match and subcontest results.
- Stats include medals, total points, highest score, knockout wins, and prediction tier counts.
- Recalculation must be idempotent.
- Achievement cache must be invalidated after match completion, score recalculation, or subcontest result changes.

## Leaderboard Integration

Overall leaderboard total should include:

- Regular match contestant points.
- Score prediction bonuses.
- Weekend Battle champion bonuses.
- Super Team final bonuses when visible/finalized.

Overall leaderboard total should not double count:

- Prediction bonuses already included in effective match points.
- Weekend/Super Team bonus rows when recalculated repeatedly.
- Historical Super Team player points as regular match points unless explicitly intended by leaderboard logic.

## Admin Requirements

- Admin must be able to:
  - Recalculate match scores.
  - Recalculate all completed scores.
  - Trigger Weekend Battle detect/seed/advance.
  - Recalculate Super Team standings.
  - Recalculate achievements.
- Admin actions must not silently change user picks unless the action is specifically an admin team edit/submit.

## Acceptance Criteria

- Each subcontest has a clear rule source in docs.
- Leaderboard shows bonus columns or labels where relevant.
- Recalculation produces the same result when run multiple times against unchanged data.
- Weekend Battle results remain unchanged by prediction bonuses.
- Super Team phase-aware scoring preserves historical player contributions.
