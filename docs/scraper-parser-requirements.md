# Scraper And Parser Requirements

This document defines the scorecard, Playing XI, toss, and name-matching behavior needed to rebuild the data ingestion layer.

## Responsibilities

The scraper/parser layer must:

- Fetch live and completed scorecard data.
- Parse batting, bowling, fielding, dot balls, and did-not-bat/player appearance data.
- Fetch and cache Playing XI and substitute data.
- Fetch and cache toss data.
- Track unknown players for admin review.
- Preserve previous cached data when a source fails.

## Data Sources

Current code supports:

- ESPN scorecard pages.
- Cricbuzz scorecard pages and embedded payloads.
- Legacy scorecard parsing fallback.
- Venue statistics lookup.

The implementation should be source-tolerant: one failed source should not erase data from another successful source.

## Match Object Parsing

Primary file: `backend/models/match.py`.

The parser must build a match object with:

- Match id.
- Team1/team2.
- Match date.
- Player registry.
- Player stat objects keyed by player id.

Each player stat object must capture:

- Batting: runs, balls, fours, sixes, strike rate, dismissal, out state.
- Bowling: overs, maidens, runs conceded, wickets, dot balls, bowled, lbw, economy.
- Fielding: catches, run outs, stumpings.
- Played state.

## Name Normalization

Requirements:

- Remove redundant whitespace.
- Normalize case.
- Remove or tolerate punctuation differences.
- Support initials and last-name-only scorecard labels.
- Use team context whenever available.
- Use aliases from `players.aliases`.
- Avoid assigning a scorecard row to the wrong team when two players share a surname.

## Team Normalization

Supported full-name to code mappings:

- Chennai Super Kings -> CSK
- Mumbai Indians -> MI
- Royal Challengers Bengaluru -> RCB
- Kolkata Knight Riders -> KKR
- Rajasthan Royals -> RR
- Gujarat Titans -> GT
- Delhi Capitals -> DC
- Lucknow Super Giants -> LSG
- Punjab Kings -> PBKS
- Sunrisers Hyderabad -> SRH

## Batting Parser

Must extract:

- Batter name.
- Runs.
- Balls.
- Fours.
- Sixes.
- Strike rate.
- Dismissal text.

Must mark:

- Batters appearing in batting rows as played.
- Did-not-bat players as played when source indicates they were in XI.

## Bowling Parser

Must extract:

- Bowler name.
- Overs.
- Maidens.
- Runs conceded.
- Wickets.
- Economy.
- Dot balls when source provides them.

Overs are cricket overs, not decimal fractions in base 10. Preserve current code behavior unless intentionally changing calculations.

## Dot Balls

Requirements:

- ESPN dot-ball sections are parsed when available.
- Dot balls add `+1` each.
- If dot balls are unavailable, do not invent them.
- A failed ESPN dot-ball fetch should not discard Cricbuzz batting/bowling points.

## Dismissal Parser Examples

| Dismissal | Required credits |
|-----------|------------------|
| `not out` | Batter not out, no fielding/bowling credit |
| `batting` | Batter not out, no fielding/bowling credit |
| `lbw b Bumrah` | Bumrah wicket and LBW bonus |
| `b Bumrah` | Bumrah wicket and bowled bonus |
| `c Kohli b Siraj` | Kohli catch, Siraj wicket |
| `c & b Narine` | Narine catch and wicket |
| `st Dhoni b Jadeja` | Dhoni stumping, Jadeja wicket |
| `run out (Jadeja)` | Jadeja direct run out |
| `run out (Jadeja/Dhoni)` | Jadeja and Dhoni indirect run outs |
| `(sub)` dismissal text | Batter out, no credit to sub unless safely matchable |

## Playing XI Cache

Playing XI payload:

```json
{
  "announced": true,
  "complete": true,
  "player_ids": [1, 2, 3],
  "substitute_ids": [12, 13],
  "url": "https://..."
}
```

Requirements:

- A complete XI should contain 22 playing ids.
- A complete substitutes list should contain 10 substitute ids when available.
- Cache key must include match id, teams, date, and time.
- XI should refresh during lineup window.
- Once final, repeated refreshes should avoid unnecessary source calls.

## Toss Cache

Toss payload:

```json
{
  "announced": true,
  "team": "RCB",
  "decision": "bowl",
  "text": "RCB won the toss and chose to bowl",
  "url": "https://..."
}
```

Requirements:

- Refresh near toss/lineup window.
- Cache announced toss data.
- Dashboard and player endpoints include cached toss data.

## Unknown Players

When a scorecard player cannot be matched:

- Record name.
- Record team.
- Record match id.
- Record match date.
- Record both match teams.
- Enforce uniqueness to avoid duplicate admin noise.

Admin uses `GET /api/admin/missed-players` to review these.

## Failure Behavior

- Network failure should be logged.
- Parser failure for one match should not stop scheduler loop.
- If live refresh fails, previous cached score payload remains usable.
- Unknown/missing scorecard data should produce empty arrays or partial data, not a server crash.

## Acceptance Criteria

- A completed scorecard can reproduce player fantasy points.
- Dot balls, bowled/LBW, catches, stumpings, and run outs appear in point breakdowns.
- Playing XI availability updates player selection UI.
- Toss information appears on dashboard/player payloads when announced.
- Unknown scorecard names are visible to admin.
