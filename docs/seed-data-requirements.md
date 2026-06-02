# Seed Data Requirements

This document defines the data needed to recreate a working app instance.

## Seed Files

Current seed files live in `data/`:

- `players.json`
- `matches.json`
- `users.json`
- `teams.json`
- `player_points.json`
- `contestant_points.json`

## Team Codes

The app expects these IPL team codes:

- `CSK`
- `MI`
- `RCB`
- `KKR`
- `RR`
- `GT`
- `DC`
- `LSG`
- `PBKS`
- `SRH`

Full-name aliases are defined in backend config and frontend team themes.

## Player Seed Shape

Each player row must contain:

```json
{
  "PlayerID": 11,
  "Name": "Virat Kohli",
  "Team": "RCB",
  "Role": "Batter",
  "Aliases": "Kohli,VK"
}
```

Optional:

```json
{
  "Type": "p"
}
```

Requirements:

- `PlayerID` must be unique and stable.
- `Team` must be one of the supported team codes.
- `Role` must be one of:
  - `Wicketkeeper`
  - `Batter`
  - `AllRounder`
  - `Bowler`
- `Aliases` is comma-separated and used by scraper matching.
- Bowler `type` may be:
  - `p` for pacer.
  - `s` for spinner.
  - `null`/missing for not classified.

Recommended minimum:

- At least 10-15 players per team for regular match selection.
- Enough Wicketkeepers, Batters, AllRounders, and Bowlers per matchup to satisfy validation.
- Rich aliases for common scorecard names, initials, last names, and abbreviations.

## Match Seed Shape

Each match row must contain:

```json
{
  "MatchID": 1,
  "Team1": "RCB",
  "Team2": "SRH",
  "Date": "2026-03-28",
  "Time": "19:30"
}
```

Optional fields that may be present in database/admin:

- `Status`
- `Venue`
- `CricbuzzMatchID`
- `EspnMatchID`
- `TossTime`

Requirements:

- `MatchID` must be unique and stable.
- `Date` format is `YYYY-MM-DD`.
- `Time` format is `HH:MM` in IST.
- Match ids `71` through `74` are special for Super Team playoff logic.
- Match ids `70` through `74` affect special Weekend Battle bonus detection.

## User Seed Shape

Legacy seed file shape:

```json
{
  "Mobile": "9876543210",
  "Name": "Rahul",
  "Password": "rahul123",
  "Allowed": "true"
}
```

Database user shape:

```json
{
  "firebase_uid": "dev_9876543210",
  "email": "9876543210@example.com",
  "name": "Rahul",
  "mobile": "9876543210",
  "role": "user",
  "is_active": 1
}
```

Requirements:

- Local/dev seed must create at least one active user.
- At least one user should be admin for local testing.
- Production users are normally linked to Firebase UID.
- Local users may use `dev_` firebase UID.

## Team Selection Seed Shape

If seeding submitted teams, each row must identify:

- User.
- Match.
- Player.
- Captain flag.
- Vice-Captain flag.

Requirements:

- Exactly 11 rows per user/match for a valid team.
- One Captain.
- One Vice-Captain.
- Captain and Vice-Captain must be different.
- Player ids must belong to one of the match teams.

## Points Seed Shape

Player points:

```json
{
  "match_id": 1,
  "player_id": 11,
  "player_name": "Virat Kohli",
  "team": "RCB",
  "role": "Batter",
  "points": 134,
  "last_updated": "2026-03-28 23:40:00"
}
```

Contestant points:

```json
{
  "user_id": 1,
  "match_id": 1,
  "points": 542.5,
  "last_updated": "2026-03-28 23:40:00"
}
```

Requirements:

- `player_points` unique key is `match_id`, `player_id`.
- `contestant_points` unique key is `user_id`, `match_id`.
- Completed matches should have enough `player_points` to recompute contestant totals.

## Super Team Seed Requirements

To test Super Team:

- Matches `71`, `72`, `73`, and `74` must exist.
- Playoff team players must exist in `players`.
- Users must exist and be active.
- Optional existing Super Team selections can be seeded into `super_teams`, `super_team_originals`, and `super_team_snapshots`.

## Weekend Battle Seed Requirements

To test Weekend Battle:

- A qualifying match before Saturday must exist.
- At least one Saturday/Sunday match must exist.
- Users should have teams and points for the qualifier.
- Weekend match ids should have teams/points to advance rounds.

## Data Quality Checklist

- No duplicate player ids.
- No duplicate match ids.
- All team codes are supported.
- All roles use exact canonical names.
- Aliases do not accidentally point two players on the same team to the same normalized name.
- Every submitted team references existing users, matches, and players.
- Every completed match has enough player points to explain contestant totals.
