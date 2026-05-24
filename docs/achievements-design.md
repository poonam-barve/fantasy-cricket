# Achievements - Design Document

## Overview

A stats and achievements page that showcases top performers across multiple categories. Data is persisted in a dedicated table and updated incrementally when matches complete, ensuring fast reads without expensive recomputation.

---

## Categories

| Category | Source | Description |
|----------|--------|-------------|
| Most Gold Medals | contestant_points | 1st place finishes per match |
| Most Silver Medals | contestant_points | 2nd place finishes per match |
| Most Bronze Medals | contestant_points | 3rd place finishes per match |
| Most Total Medals | contestant_points | Sum of gold + silver + bronze |
| Knockout Battle Wins | weekend_tournaments | Weekend tournament victories |
| Most Total Points | contestant_points | Cumulative fantasy points across all matches |
| Highest Match Score | contestant_points | Best single-match performance |
| Most Predictions Won | score_predictions | Total prediction bonuses earned |
| Perfect Strike | score_predictions | Predictions within 0.5 points of actual |
| Elite Precision | score_predictions | Predictions within 5 points of actual |
| Great Call | score_predictions | Predictions within 10 points of actual |

---

## Architecture

### Data Flow

```
Match completes
    |
    v
_finalize_completed_match() in tournament.py
    |
    v
invalidate_achievements_cache(match_id)
    |
    v
_incremental_update(match_id)
    - Computes medals for THIS match only
    - Computes prediction bonus for THIS match only
    - Updates knockout_wins (cheap COUNT query)
    - UPSERTs into achievement_stats table
    |
    v
Memory cache cleared (next GET rebuilds from DB)
```

### Caching Strategy

Three layers, fastest to slowest:

1. **In-memory dict** (`_cached_response`) — serves most requests instantly
2. **Database table** (`achievement_stats`) — survives app restarts, no recomputation needed
3. **Full recompute** (`_full_recompute()`) — only on first-ever cold start or admin reset

### Invalidation

- **On match completion**: incremental update (processes 1 match, ~10ms)
- **On app restart**: reads from DB table (simple SELECT, ~5ms)
- **Admin recalculate**: full recompute of all matches (used if data drifts)

---

## Database Schema

### `achievement_stats`

| Column | Type | Description |
|--------|------|-------------|
| `user_id` | INTEGER PK | Foreign key to users |
| `gold` | INTEGER | Gold medal count |
| `silver` | INTEGER | Silver medal count |
| `bronze` | INTEGER | Bronze medal count |
| `total_points` | REAL | Cumulative fantasy points |
| `highest_score` | REAL | Best single-match score |
| `knockout_wins` | INTEGER | Weekend tournament wins |
| `predictions_total` | INTEGER | Total prediction bonuses won |
| `perfect_strike` | INTEGER | Perfect Strike count (diff <= 0.5) |
| `elite_precision` | INTEGER | Elite Precision count (diff <= 5) |
| `great_call` | INTEGER | Great Call count (diff <= 10) |
| `last_computed_match_id` | INTEGER | Last match processed (prevents double-counting) |

---

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/achievements` | Required | Returns all achievement categories with top 5 per category |
| `POST` | `/api/admin/achievements/recalculate` | Admin | Force full recalculation from scratch |

### Response Shape: `GET /api/achievements`

```json
{
  "categories": [
    {
      "title": "Most Gold Medals",
      "icon": "gold",
      "entries": [
        { "user_id": 10, "name": "PSPhoeniXI", "value": 10 },
        { "user_id": 8, "name": "Boisar Khiladi", "value": 8 }
      ]
    }
  ]
}
```

---

## Implementation Files

### Created

| File | Purpose |
|------|---------|
| `backend/routes/achievements.py` | API endpoint, caching, incremental/full compute logic |
| `frontend/src/pages/Achievements.tsx` | Achievements page with category cards |
| `docs/achievements-design.md` | This document |

### Modified

| File | Changes |
|------|---------|
| `backend/database.py` | Added `achievement_stats` table (PostgreSQL + SQLite) |
| `backend/main.py` | Registered achievements router |
| `backend/models/tournament.py` | Hooked `invalidate_achievements_cache(match_id)` into `_finalize_completed_match()` |
| `frontend/src/App.tsx` | Added `/achievements` route |
| `frontend/src/pages/Dashboard.tsx` | Added "Achievements" quick action button (emerald) |

---

## Frontend

### Achievements Page (`/achievements`)

- Grid of category cards (2 columns on desktop, 1 on mobile)
- Each card shows top 5 users with rank, name, and value
- Current user highlighted with "YOU" badge
- Color-coded per category (gold/silver/bronze/emerald/purple/etc.)
- Back navigation to dashboard

### Dashboard Quick Action

- Emerald-colored button with checkmark icon
- Links to `/achievements`

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| App restart (no memory cache) | Reads from `achievement_stats` table |
| First ever deploy (empty table) | Triggers `_full_recompute()` on first request |
| Match points corrected retroactively | Admin calls `POST /api/admin/achievements/recalculate` |
| Tied scores for medals | Both users get same rank (same as leaderboard logic) |
| User didn't participate in match | Gets adjusted points (same as leaderboard) |
| Weekend tournament completes | `knockout_wins` updated via COUNT query |
| Same match processed twice | Guarded by `last_computed_match_id` check |
