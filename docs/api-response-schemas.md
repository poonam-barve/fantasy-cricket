# API Response Schemas

This document defines the response shapes needed by the current frontend. Field names should remain stable unless the frontend types and all consumers are updated.

## Common Error Shape

FastAPI errors should use:

```json
{
  "detail": "Human readable error"
}
```

Some legacy endpoints may return:

```json
{
  "error": "Human readable error"
}
```

Frontend code must tolerate both.

## User

```json
{
  "id": 1,
  "firebase_uid": "firebase-or-dev-id",
  "email": "user@example.com",
  "name": "User Name",
  "mobile": "9876543210",
  "role": "user",
  "is_active": 1,
  "replace_substitutes_with_backups": true
}
```

Notes:

- `role` is `user` or `admin`.
- SQLite may return booleans as `0`/`1`; frontend treats truthy values as active.

## Runtime Current Time

Endpoint: `GET /api/runtime/current-time`.

```json
{
  "datetime": "2026-06-02T19:30:00+05:30",
  "date": "2026-06-02",
  "time": "19:30",
  "timezone": "Asia/Kolkata",
  "overridden": false
}
```

## Match

Used by `GET /api/matches` and `GET /api/dashboard/matches`.

```json
{
  "id": 1,
  "team1": "RCB",
  "team2": "SRH",
  "match_date": "2026-03-28",
  "match_time": "19:30",
  "toss_time": "19:00",
  "status": "future",
  "locked": false,
  "venue": {
    "venue": "M. Chinnaswamy Stadium",
    "city": "Bengaluru",
    "matches": 94,
    "avg_first_innings": 183,
    "bat_first_win_pct": 46.8,
    "chase_win_pct": 53.2,
    "pitch_type": "Batting friendly"
  },
  "toss": {
    "announced": true,
    "team": "RCB",
    "decision": "bowl",
    "text": "RCB won the toss and chose to bowl",
    "url": "https://..."
  },
  "current_rank": 4
}
```

Notes:

- `venue`, `toss`, and `current_rank` may be `null`.
- Valid statuses: `future`, `lineups`, `live`, `completed`, `nr`.

## Players For Match

Endpoint: `GET /api/players?match_id=1`.

```json
{
  "players": {
    "Wicketkeeper": [
      {
        "id": 14,
        "name": "Dinesh Karthik",
        "team": "RCB",
        "role": "Wicketkeeper",
        "type": null,
        "aliases": "Karthik,DK",
        "total_points": 312.5,
        "matches_played": 8,
        "avg_points": 39.06,
        "last_match_points": 44.5,
        "recent_history": [
          {
            "match_id": 12,
            "opponent": "MI",
            "points": 44.5,
            "did_not_play": false
          }
        ],
        "is_playing_xi": true,
        "is_substitute": false,
        "availability_status": "available",
        "availability_order": 3
      }
    ],
    "Batter": [],
    "AllRounder": [],
    "Bowler": []
  },
  "match_teams": ["RCB", "SRH"],
  "playing_xi": {
    "announced": true,
    "url": "https://...",
    "playing_count": 22,
    "substitute_count": 10
  },
  "lineup_window_open": true,
  "is_today_match": true,
  "last_match_xi": {
    "RCB": {
      "match_id": 10,
      "team": "RCB",
      "player_ids": [11, 12, 14],
      "impact_sub_player_ids": [19]
    }
  },
  "toss": {
    "announced": true,
    "team": "RCB",
    "decision": "bowl",
    "text": "RCB won the toss and chose to bowl",
    "url": "https://..."
  }
}
```

## My Team

Endpoint: `GET /api/teams/my?match_id=1`.

```json
{
  "team": [
    {
      "player_id": 11,
      "player_name": "Virat Kohli",
      "team": "RCB",
      "role": "Batter",
      "is_captain": true,
      "is_vice_captain": false
    }
  ],
  "predicted_points": 350.5
}
```

## Team Backups

Endpoint: `GET /api/teams/my-backups?match_id=1`.

```json
[
  {
    "backup_order": 1,
    "backup_player_id": 19,
    "backup_player_name": "Rajat Patidar",
    "backup_team": "RCB",
    "backup_role": "Batter",
    "replaced_player_id": null,
    "replaced_player_name": null
  }
]
```

## Team Save Request And Response

Endpoint: `POST /api/teams`.

Request:

```json
{
  "match_id": 1,
  "players": [
    { "player_id": 11, "is_captain": true, "is_vice_captain": false },
    { "player_id": 14, "is_captain": false, "is_vice_captain": true }
  ],
  "backups": [19, 20, 18],
  "predicted_points": 350.5
}
```

Response:

```json
{
  "success": true,
  "message": "Team saved successfully"
}
```

## Main Scores Payload

Endpoint: `GET /api/scores/{match_id}`.

```json
{
  "match": {
    "id": 1,
    "team1": "RCB",
    "team2": "SRH",
    "status": "live"
  },
  "players": [
    {
      "name": "Virat Kohli",
      "team": "RCB",
      "role": "Batter",
      "played": true,
      "is_out": true,
      "runs": 72,
      "balls": 48,
      "fours": 8,
      "sixes": 2,
      "strike_rate": 150.0,
      "overs": 0,
      "maidens": 0,
      "runs_conceded": 0,
      "wickets": 0,
      "dot_balls": 0,
      "bowled": 0,
      "lbw": 0,
      "economy": 0,
      "catches": 1,
      "runout_direct": 0,
      "runout_indirect": 0,
      "stumpings": 0,
      "points": 134,
      "owners": [
        { "id": 1, "name": "Rahul", "tag": "C" }
      ]
    }
  ],
  "contestants": [
    {
      "id": 1,
      "name": "Rahul",
      "points": 542.5,
      "rank": 1,
      "predicted_points": 540,
      "prediction_bonus": 200,
      "prediction_label": "Elite Precision",
      "prediction_tier_bonus": 200,
      "prediction_tier_label": "Elite Precision"
    }
  ],
  "scorecard": [],
  "status": "live"
}
```

Notes:

- Future/cache-miss payloads may contain empty arrays.
- Prediction bonus fields may be `null` or `0`.

## Team Breakdown

Endpoint: `GET /api/scores/{match_id}/team-breakdown?user_id=2`.

```json
{
  "user_id": 2,
  "user_name": "Priya",
  "total": 421.5,
  "players": [
    {
      "player_id": 11,
      "player_name": "Virat Kohli",
      "team": "RCB",
      "role": "Batter",
      "base_points": 134,
      "multiplier": 2,
      "adjusted_points": 268,
      "is_captain": true,
      "is_vice_captain": false,
      "is_backup": false,
      "replaced_player_id": null
    }
  ],
  "backup_replacements": []
}
```

## Team Diff

Endpoint: `GET /api/scores/{match_id}/team-diff?other_user_id=2`.

```json
{
  "current_user": "Rahul",
  "other_user": "Priya",
  "my_total": 421.5,
  "other_total": 398,
  "total_diff": 23.5,
  "my_only": [],
  "other_only": [],
  "common": [],
  "rows": []
}
```

## Leaderboard Entry

Endpoint: `GET /api/leaderboard`.

```json
{
  "rank": 1,
  "name": "Rahul",
  "user_id": 1,
  "points": 4250.5,
  "prediction_bonus": 700,
  "rank_change": 2,
  "gold": 4,
  "silver": 3,
  "bronze": 1,
  "weekend_wins": 1,
  "weekend_bonus": 200,
  "super_team_bonus": 1000,
  "balance": 450
}
```

## Points Table Entry

Endpoint: `GET /api/points-table`.

```json
{
  "user_id": 1,
  "name": "Rahul",
  "match_id": 1,
  "points": 542.5,
  "last_updated": "2026-03-28 23:40:00",
  "net": 125,
  "adjusted": false,
  "participated": true,
  "rank_change": 1
}
```

## Weekend Tournament

Endpoint: `GET /api/weekend-tournament/current`.

See [weekend-tournament-design.md](weekend-tournament-design.md) for the complete response. The frontend requires:

- `id`
- `status`
- `qualifying_match_id`
- `weekend_match_ids`
- `num_rounds`
- `winner`
- `matches`
- `qualifiers`
- `brackets`

## Super Team Home

Endpoint: `GET /api/super-team`.

Required top-level fields:

```json
{
  "context": {
    "visible": true,
    "enabled": true,
    "locked": false,
    "message": "Selection open",
    "phase": 0,
    "bonus_visible": false
  },
  "player_pool": {
    "Wicketkeeper": [],
    "Batter": [],
    "AllRounder": [],
    "Bowler": []
  },
  "my_team": {
    "player_ids": [11, 14],
    "captain": 11,
    "vice_captain": 14
  },
  "standings": [],
  "details": {}
}
```

## Admin Team

Endpoint: `GET /api/admin/teams?match_id=1`.

```json
[
  {
    "user_id": 1,
    "user_name": "Rahul",
    "user_email": "rahul@example.com",
    "user_mobile": "9876543210",
    "players": [
      {
        "player_id": 11,
        "player_name": "Virat Kohli",
        "team": "RCB",
        "role": "Batter",
        "is_captain": true,
        "is_vice_captain": false
      }
    ],
    "team_counts": {
      "RCB": 6,
      "SRH": 5
    },
    "captain_name": "Virat Kohli",
    "vice_captain_name": "Dinesh Karthik"
  }
]
```
