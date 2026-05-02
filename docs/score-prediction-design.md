# Total Points Prediction — Design Document

## Overview

Users predict their fantasy team's total score when saving their team for a match. After the match completes, bonus points are awarded based on prediction accuracy. The closer the prediction, the bigger the bonus.

### Bonus Tiers

| Tier | Emoji | Condition | Bonus |
|------|-------|-----------|-------|
| Perfect Strike | 🎯 | Exact score | +500 pts |
| Elite Precision | 🔥 | Within ±5 pts | +200 pts |
| Great Call | ⚡ | Within ±10 pts | +100 pts |

### Tiebreaker Rules

- Within each tier, only the **closest** prediction wins the bonus.
- If multiple users are **equally close** (same difference), **all tied users get the full bonus**.
- A user can only win **one tier** (the highest they qualify for). Users who qualify for a higher tier are removed from lower-tier evaluation.

---

## User Flow

### 1. First-Time Team Save (New Prediction)

```
User picks 11 players + C/VC
        │
        ▼
Clicks "Save Team"
        │
        ▼
┌─────────────────────────────┐
│   Prediction Modal appears  │
│                             │
│  🎯 Predict Your Score      │
│                             │
│  Bonus tier breakdown:      │
│  🎯 Perfect Strike +500    │
│  🔥 Elite Precision +200   │
│  ⚡ Great Call +100         │
│                             │
│  [ Enter prediction: ___ ]  │
│                             │
│  [  Skip  ] [Confirm & Save]│
└─────────────────────────────┘
        │
   ┌────┴────┐
   │         │
 Skip    Confirm
   │         │
   ▼         ▼
Team saved  Team saved
No pred.    Prediction stored
   │         │
   ▼         ▼
Team Preview Modal shown
```

### 2. Returning to SelectTeam (Existing Team)

#### Has team + Has prediction:
```
Sticky footer shows:
┌──────────────────────────────────────────┐
│ 🎯 Prediction: 350 pts            [Edit]│
├──────────────────────────────────────────┤
│ 11/11  C / VC              [Save Team]  │
└──────────────────────────────────────────┘

Click "Edit" → Opens prediction modal
  → "Cancel" dismisses (no change)
  → "Update Prediction" calls PATCH /api/teams/prediction
  → No team re-save needed
```

#### Has team + No prediction (skipped earlier or legacy team):
```
Sticky footer shows:
┌───────────────────────────────────────────────────────┐
│ 🎯 Predict your team's total score for bonus pts [Add]│
├───────────────────────────────────────────────────────┤
│ 11/11  C / VC                           [Save Team]  │
└───────────────────────────────────────────────────────┘

Click "Add" → Opens prediction modal
  → "Cancel" dismisses
  → "Update Prediction" calls PATCH /api/teams/prediction
  → No team re-save needed
```

#### No team yet:
```
No prediction bar shown.
Prediction modal appears as part of Save flow (step 1 above).
```

### 3. Match Lock

Once the match starts (match datetime reached):
- Team cannot be changed → Save is disabled
- Prediction **cannot be changed** → PATCH endpoint returns 400
- Existing prediction is locked in for bonus calculation

### 4. During Match (Live)

- Scores page shows each contestant's `predicted_points` next to their name
- No bonuses calculated yet (match not complete)

### 5. After Match (Completed)

```
Match completes
      │
      ▼
Bonus computation runs:
  1. Fetch all predictions for the match
  2. Fetch actual contestant points from contestant_points table
  3. For each user: diff = abs(predicted - actual)
  4. Evaluate tiers top-down (exact → ±5 → ±10)
  5. Per tier: find closest user(s), award bonus
  6. Ties get full bonus; higher-tier winners removed from lower tiers
      │
      ▼
Scores page shows:
  - "Predicted: X pts" under contestant name
  - 🎯+500 / 🔥+200 / ⚡+100 badge next to points (if won)
      │
      ▼
Leaderboard:
  - Prediction bonus is ADDED to cumulative total points
  - Affects overall ranking
```

---

## What Prediction Bonuses Affect vs Don't Affect

| Area | Affected? | Details |
|------|-----------|---------|
| Overall leaderboard total | ✅ Yes | Bonus added to cumulative points |
| Overall leaderboard ranking | ✅ Yes | Rankings reflect bonus in totals |
| Per-match rankings | ✅ Yes | Bonus added to match points, affects rank within a match |
| Gold/Silver/Bronze medals | ✅ Yes | Medals use match points which include prediction bonus |
| Scores page display | ✅ Yes | Bonus badge shown + included in contestant points |
| Balance/prize calculations | ✅ Yes | Uses effective match points which include bonus |
| Weekend Tournament 1v1 results | ❌ No | 1v1 winners use independent query (`_get_match_contestant_points` in `weekend_tournament_service.py`) that computes directly from `user_teams + player_points` — prediction bonus is never included |

---

## Implementation Details

### Database

**New table: `score_predictions`**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user_id` | INTEGER FK → users | Who predicted |
| `match_id` | INTEGER FK → matches | Which match |
| `predicted_points` | REAL | The predicted total points |
| `created_at` | TEXT | Timestamp of prediction |

**Constraint:** `UNIQUE(user_id, match_id)` — one prediction per user per match.

**Index:** `idx_score_predictions_match` on `match_id`.

Created in both SQLite and PostgreSQL schema blocks in `backend/database.py`.

### API Endpoints

#### Save team with prediction
```
POST /api/teams
Body: {
  match_id: 25,
  players: [...],
  backups: [...],
  predicted_points: 350.5    ← optional, null = no prediction
}
```

#### Get my team (returns prediction)
```
GET /api/teams/my?match_id=25
Response: {
  team: [{ player_id, player_name, team, role, is_captain, is_vice_captain }, ...],
  predicted_points: 350.5    ← null if not set
}
```

#### Update prediction only (no team re-save)
```
PATCH /api/teams/prediction
Body: { match_id: 25, predicted_points: 360 }
Response: { success: true, predicted_points: 360 }

Errors:
  404 — Match not found
  400 — Match is locked (already started)
```

#### Scores response (enriched with predictions)
```
GET /api/scores/{match_id}
Response: {
  players: [...],
  contestants: [
    {
      id: 1,
      name: "Rupesh",
      points: 342.5,
      rank: 1,
      predicted_points: 350.5,       ← what they predicted
      prediction_bonus: 200,          ← bonus earned (0 if none)
      prediction_label: "Elite Precision"  ← tier name (null if none)
    },
    ...
  ],
  ...
}
```

### Backend Files Modified

| File | Changes |
|------|---------|
| `backend/database.py` | Added `score_predictions` table (SQLite + Postgres), index |
| `backend/routes/teams.py` | `predicted_points` in POST body, PATCH endpoint, prediction in GET /my response |
| `backend/services/data_service.py` | `save_score_prediction`, `get_score_prediction`, `get_match_predictions`, `compute_prediction_bonuses` |
| `backend/routes/scores.py` | `_enrich_contestants_with_predictions()` adds prediction fields to live + completed score responses |
| `backend/routes/leaderboard.py` | `_compute_total_prediction_bonuses()` sums bonuses across matches, added to leaderboard totals only |

### Frontend Files Modified

| File | Changes |
|------|---------|
| `frontend/src/types/index.ts` | Added `predicted_points`, `prediction_bonus`, `prediction_label` to `ContestantScore` |
| `frontend/src/pages/SelectTeam.tsx` | Prediction modal on save, edit/add prediction bar in footer, standalone PATCH update |
| `frontend/src/pages/ViewScores.tsx` | Prediction badge on contestants, predicted vs actual display |

---

## Bonus Computation Algorithm

```python
TIERS = [
    { max_diff: 0,  bonus: 500, label: "Perfect Strike" },
    { max_diff: 5,  bonus: 200, label: "Elite Precision" },
    { max_diff: 10, bonus: 100, label: "Great Call" },
]

for each tier (evaluated top-down):
    eligible = users in remaining pool whose diff <= tier.max_diff
    if no eligible users → skip tier

    min_diff = smallest diff among eligible
    winners = all eligible users with diff == min_diff
    → award full bonus to all winners

    remove ALL eligible users from remaining pool
    (not just winners — prevents double-awarding)
```

**Example:**

| User | Predicted | Actual | Diff |
|------|-----------|--------|------|
| A | 350 | 350 | 0 |
| B | 353 | 350 | 3 |
| C | 354 | 350 | 4 |
| D | 358 | 350 | 8 |
| E | 370 | 350 | 20 |

**Result:**
- Tier 1 (exact, ±0): A wins → **+500** (A removed from pool)
- Tier 2 (±5): B (diff=3) and C (diff=4) eligible. Closest = B → **+200** (B and C removed)
- Tier 3 (±10): D (diff=8) eligible. Closest = D → **+100** (D removed)
- E (diff=20) → no bonus

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| User skips prediction | No prediction stored, no bonus possible |
| User never visits SelectTeam after feature launch | No prediction bar on dashboard; prediction only available from SelectTeam page |
| Match has no predictions at all | `compute_prediction_bonuses` returns empty dict, no bonuses |
| User predicted but didn't submit a team | Not possible — prediction is tied to team save flow |
| User has prediction but 0 actual points (team didn't play) | `diff = abs(prediction - 0)`, evaluated normally |
| Multiple users predict exact same score | If same diff within a tier, all get full bonus |
| All predictions are > 10 pts away | No bonuses awarded for that match |
| Legacy teams saved before feature existed | No prediction stored; footer shows "Add" button on SelectTeam |
| App restart / server reboot | `score_predictions` table persists; bonuses recomputed on-the-fly |
