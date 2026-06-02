# Current Scoring And Scraper Requirements

This document captures the current scoring engine and scorecard parsing behavior from code.

## Scoring Engine

Primary file: `backend/models/player.py`.

### Playing

| Event | Points |
|-------|--------|
| Player appeared/played | `+4` |

### Batting

| Event | Points |
|-------|--------|
| Run | `+1` each |
| Four | `+4` each |
| Six | `+6` each |
| 30+ runs | `+4` |
| 50+ runs | `+8` |
| 75+ runs | `+12` |
| 100+ runs | `+16` |
| Duck for batting roles | `-2` |

Milestone bonuses are exclusive: apply the highest matching milestone only.

Batting roles for duck and strike-rate rules:

- `Batter`
- `Wicketkeeper`
- `AllRounder`

### Strike Rate

Applies only when:

- Player has faced at least `10` balls.
- Player role is a batting role.

| Strike Rate | Points |
|-------------|--------|
| `> 170` | `+6` |
| `> 150` | `+4` |
| `>= 130` | `+2` |
| `<= 50` | `-6` |
| `< 60` | `-4` |
| `<= 70` | `-2` |

### Bowling

| Event | Points |
|-------|--------|
| Wicket | `+30` each |
| Bowled/LBW bonus | `+8` each |
| 3 wickets | `+4` |
| 4 wickets | `+8` |
| 5+ wickets | `+16` |
| Maiden over | `+12` each |
| Dot ball | `+1` each |

Wicket-haul bonuses are exclusive.

### Economy Rate

Applies only when the player bowled at least `2` overs.

| Economy | Points |
|---------|--------|
| `< 5` | `+6` |
| `< 6` | `+4` |
| `<= 7` | `+2` |
| `> 12` | `-6` |
| `> 11` | `-4` |
| `>= 10` | `-2` |

### Fielding

| Event | Points |
|-------|--------|
| Catch | `+8` each |
| 3+ catches bonus | `+4` |
| Stumping | `+12` each |
| Direct run out | `+12` each |
| Indirect run out | `+6` each |

Current code also increments `runout_direct` for stumpings, but points breakdown separately awards stumpings and direct run outs from their counters. Preserve current behavior unless intentionally corrected.

## Regular Match Multipliers

- Captain: `2.0x`.
- Vice-Captain: `1.5x`.
- Regular player: `1.0x`.

These multipliers are used for regular match contestant points.

## Super Team Multipliers

Super Team uses separate multipliers:

- Captain: `1.5x`.
- Vice-Captain: `1.25x`, rounded up to the next `0.5`.

## Dismissal Parsing

The dismissal parser must handle:

- `not out` and `batting` as not out.
- Substitute dismissal text as out without credit.
- `lbw b Bowler`: wicket and LBW bonus to bowler.
- `c Fielder b Bowler`: catch to fielder, wicket to bowler.
- `c & b Bowler`: catch and wicket to bowler.
- `b Bowler`: wicket and bowled bonus to bowler.
- `st Keeper b Bowler`: stumping to keeper and wicket to bowler.
- `run out (Fielder)`: direct run out to one fielder.
- `run out (Fielder1/Fielder2)`: indirect run out to listed fielders.

## Scorecard Sources

The app currently uses multiple cricket data sources and parsers:

- ESPN scorecard scraping.
- Cricbuzz scorecard scraping.
- Legacy scorecard parser support.
- Playing XI cache refresh.
- Toss info cache refresh.
- Venue stats support.

Scraper code must preserve:

- Team-name normalization.
- Player alias matching.
- Unknown player recording for admin review.
- Dot-ball parsing from ESPN bowling sections.
- Cricbuzz JSON/payload extraction where available.
- Fallback behavior when a source is unavailable.

## Player Registry

Primary file: `backend/models/registry.py`.

Requirements:

- Build lookup from player id, name, team, role, aliases.
- Normalize names by lowercasing and simplifying punctuation/spacing.
- Match scorecard names by team-aware lookup first.
- Support aliases for abbreviated or alternate scorecard names.
- Avoid creating duplicate player ids for the same real player.

## Completion And Persistence

When a match is finalized:

- Persist `player_points`.
- Persist `contestant_points`.
- Mark/keep match status completed as appropriate.
- Invalidate score, leaderboard, match, and achievement caches.
- Trigger Weekend Battle progression hooks.

## Acceptance Criteria

- Player points breakdown equals total player points.
- Regular contestant totals equal selected player adjusted points.
- Bowled/LBW, dot balls, 75-run bonus, and non-participant adjustments are represented in docs and UI.
- Scraper failure leaves previous cached data available where possible.
