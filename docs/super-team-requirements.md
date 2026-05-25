# Super Team Requirements

This document is the source of truth for the Super Team playoff contest rules and the implementation requirements for the revised substitution model.

## Contest Scope

- Super Team is a playoff-long fantasy contest for matches `71`, `72`, `73`, and `74`.
- Each user selects one Super Team squad.
- The squad size is exactly `12` players.
- Eligible players come from the four playoff teams once those teams are known.
- Players score their normal fantasy points in every playoff match they appear in.
- No regular-match backup, substitute, or Playing XI availability rules apply.

## Initial Team Selection

- Initial selection opens only after the four playoff teams are known.
- Initial selection locks at Match `71` toss, using the same toss cutoff logic already used by the app.
- Users must select exactly `12` players.
- Team distribution rules are removed:
  - No requirement to select exactly `3` players from each team.
  - No maximum of `4` players from a team during substitutions.
- Role rules remain:
  - At least `1` Wicketkeeper.
  - At least `1` Batter.
  - At least `1` AllRounder.
  - At least `4` Bowlers.
- Users must choose one Captain and one Vice-Captain from selected players.
- Captain and Vice-Captain must be different players.

## Multipliers

- Captain fantasy points are multiplied by `1.5`.
- Vice-Captain fantasy points are multiplied by `1.25`.
- Vice-Captain multiplied points are rounded up to the next `0.5`.
- Multipliers apply to the active team snapshot for the relevant scoring phase.

## Substitution Windows

Super Team has two substitution windows after the initial lock.

After the initial Match `71` toss lock, submitted Super Teams become visible to other users. Users should be able to view other users' teams and use comparison features similar to the regular single-match team view.

### Window 1

- Opens after Match `72` is completed.
- Locks before Match `73` toss.
- Uses the same toss cutoff logic already used by the app.
- Users can update players, Captain, and Vice-Captain.
- Only the final saved team in this window matters for penalty calculation.
- If a user does not edit during this window, copy their original team into the edited-team snapshot.
- During Window 1, the Super Team score/compare views must continue to show each user's currently active scoring team from before the window, not the user's unfinalized edits.
- The edit UI and the view/compare UI should both be available during Window 1.

### Window 2

- Opens after Match `73` is completed.
- Locks before Match `74` toss.
- Uses the same toss cutoff logic already used by the app.
- Users can update players, Captain, and Vice-Captain.
- Only the final saved team in this window matters for penalty calculation.
- Window 2 penalties compare against the edited-team snapshot, not the original team.
- During Window 2, the Super Team score/compare views must continue to show each user's active scoring team from before Window 2, not the user's unfinalized final-team edits.
- The edit UI and the view/compare UI should both be available during Window 2.

## Team Snapshots

The system must maintain three snapshots per user.

### Original Team

- The team submitted before Match `71` toss.
- Used as the baseline for Window 1 penalties.
- Used for scoring and team comparison for Matches `71` and `72`.

### Edited Team

- The team after Window 1 closes.
- If the user does not edit in Window 1, this must be a copy of the original team.
- Used as the baseline for Window 2 penalties.
- Used for scoring and team comparison for Match `73` after Match `73` toss lock.

### Final Team

- The team after Window 2 closes.
- If the user does not edit in Window 2, this may be a copy of the edited team.
- Used for the final scoring state after Window 2.
- Used for scoring and team comparison for Match `74` after Match `74` toss lock.

## Team Visibility And Comparison

- Before Match `71` toss, users can edit only their own Super Team and cannot see other users' teams.
- After Match `71` toss, all submitted Super Teams become visible.
- The Super Team page should provide team viewing and comparison options similar to regular single-match score views:
  - View a user's Super Team.
  - Compare my team with another user's team.
  - Highlight common players.
  - Highlight different players.
  - Highlight Captain/Vice-Captain differences.
  - Show point differences where available.
- Visibility remains available during substitution windows.
- During substitution windows, unfinalized edits are private draft/current-edit state for the editing user and must not affect public score/compare views until that substitution window locks.
- After a substitution window locks, the newly finalized snapshot becomes visible and becomes the active comparison team for future matches.

## Phase-Aware Scoring

Super Team score views must use the team snapshot that was active for each match.

- Matches `71` and `72` use the original team snapshot.
- Match `73` uses the edited team snapshot.
- Match `74` uses the final team snapshot.
- If a user does not edit in Window 1, the edited snapshot is copied from the original snapshot, so Match `73` still has a valid active team.
- If a user does not edit in Window 2, the final snapshot is copied from the edited snapshot, so Match `74` still has a valid active team.
- Current score and comparison views must not recalculate past match points using a later edited team.
- During Window 1, Match `71` and Match `72` points continue to use the original team even if the user is editing a new team for Match `73`.
- During Window 2, Match `71`, `72`, and `73` points continue to use the snapshots that were active for those matches even if the user is editing a new team for Match `74`.

## Removed Players In Score Views

Score views should preserve removed players when they contributed points in earlier matches.

- If a player was selected in an earlier active snapshot and later removed, the user's team view should still show that player for the matches where they were active.
- Removed players should be visually highlighted or labeled to indicate they are no longer in the latest active/final team.
- Removed players should retain their historical points from matches before the substitution.
- Removed players should not score points for matches after they were removed.
- Newly added players should not show points for matches before they entered the active snapshot.
- Comparison views should account for these phase-aware player histories:
  - A removed player can still explain historical points.
  - A new player can explain future points.
  - A player can be common in one phase and different in another phase.

Example:

- Original team has player `A`.
- Window 1 replaces player `A` with player `B`.
- Player `A` remains visible in the user's score breakdown for Matches `71` and `72`, with a removed-player highlight.
- Player `A` scores `0` for Match `73` onward.
- Player `B` scores `0` for Matches `71` and `72`, then can score from Match `73` onward.

Example:

- Edited team has player `B`.
- Window 2 replaces player `B` with player `C`.
- Player `B` remains visible for Match `73` scoring history, with a removed-player highlight after Window 2 finalizes.
- Player `C` can score only from Match `74` onward.

## Penalty Model

Penalties are phase-based. A later phase does not compare back to the original team unless the original team was copied into the previous phase snapshot.

Simple version: Window 1 swaps cost `80` for batting-side roles or `60` for Bowlers; Window 2 swaps cost `100` for batting-side roles or `80` for Bowlers. Captain changes cost half of that role's swap penalty, and Vice-Captain changes cost one-fourth.

### Window 1 Penalty

Compare `original team` to `edited team`.

New player penalties:

- New Batter: `80` points.
- New Wicketkeeper: `80` points.
- New AllRounder: `80` points.
- New Bowler: `60` points.

Captain/Vice-Captain change penalties:

- If Captain changes to a Batter/Wicketkeeper/AllRounder: `40` points.
- If Captain changes to a Bowler: `30` points.
- If Vice-Captain changes to a Batter/Wicketkeeper/AllRounder: `20` points.
- If Vice-Captain changes to a Bowler: `15` points.
- Captain/Vice-Captain penalty is based on the role of the newly selected Captain/Vice-Captain.

### Window 2 Penalty

Compare `edited team` to `final team`.

New player penalties:

- New Batter: `100` points.
- New Wicketkeeper: `100` points.
- New AllRounder: `100` points.
- New Bowler: `80` points.

Captain/Vice-Captain change penalties:

- If Captain changes to a Batter/Wicketkeeper/AllRounder: `50` points.
- If Captain changes to a Bowler: `40` points.
- If Vice-Captain changes to a Batter/Wicketkeeper/AllRounder: `25` points.
- If Vice-Captain changes to a Bowler: `20` points.
- Captain/Vice-Captain penalty is based on the role of the newly selected Captain/Vice-Captain.

### Penalty Notes

- A player is "new" when present in the later snapshot and absent from the previous snapshot.
- If a user changes from player `A` to player `B` in Window 1, then changes back from `B` to `A` in Window 2, Window 2 treats `A` as a new player relative to the edited snapshot.
- The app should show the current projected penalty while a user edits in each substitution window.
- Total penalty is:
  - Window 1 penalty plus Window 2 penalty.
- Super Team standings should show gross points, penalty details, and net points where relevant.

## Examples

### Vice-Captain Scoring

Vice-Captain score uses `1.25x`, then rounds up to the next `0.5`.

- If a Vice-Captain scores `20` base points: `20 * 1.25 = 25`, so credited points are `25`.
- If a Vice-Captain scores `21` base points: `21 * 1.25 = 26.25`, rounded up to the next `0.5`, so credited points are `26.5`.
- If a Vice-Captain scores `21.5` base points: `21.5 * 1.25 = 26.875`, rounded up to the next `0.5`, so credited points are `27`.

### Window 1 Player And Captain Penalty

Original team has Batter `A` as Captain and Bowler `B` as Vice-Captain.

In Window 1, the user replaces Batter `C` with Batter `D`, replaces Bowler `E` with Bowler `F`, changes Captain to Bowler `F`, and changes Vice-Captain to Batter `D`.

- New Batter `D`: `80`.
- New Bowler `F`: `60`.
- Captain changed to Bowler: `30`, because Captain penalty is `50%` of Window 1 bowler substitute penalty.
- Vice-Captain changed to Batter: `20`, because Vice-Captain penalty is `25%` of Window 1 batter substitute penalty.
- Total Window 1 penalty: `80 + 60 + 30 + 20 = 190`.

### Window 2 Fresh Penalty

Edited team has Batter `D` and Bowler `F`.

In Window 2, the user replaces Batter `D` with AllRounder `G`, changes Captain to AllRounder `G`, and changes Vice-Captain to Bowler `H`.

- New AllRounder `G`: `100`.
- Captain changed to AllRounder: `50`, because Captain penalty is `50%` of Window 2 batter/WK/AR substitute penalty.
- Vice-Captain changed to Bowler: `20`, because Vice-Captain penalty is `25%` of Window 2 bowler substitute penalty.
- Total Window 2 penalty: `100 + 50 + 20 = 170`.
- If Window 1 penalty was `190`, total Super Team penalty is `190 + 170 = 360`.

### Returning To An Original Player

Original team has Batter `A`.

Window 1 changes Batter `A` to Batter `D`, so Batter `D` is penalized in Window 1.

Window 2 changes Batter `D` back to Batter `A`.

- Window 2 compares edited team to final team.
- Batter `A` is new relative to the edited team.
- Batter `A` gets the Window 2 batter substitute penalty of `100`.
- The system does not compare final team directly against original team.

## Scoring And Ranking

- Player fantasy points are accumulated across playoff matches `71` to `74`.
- Captain and Vice-Captain multipliers apply according to the saved team state for the applicable scoring phase.
- Vice-Captain multiplied points are rounded up to the next `0.5`.
- Net Super Team points are gross Super Team points minus total penalties.
- Ranking is based on net Super Team points.

## Leaderboard Bonus

After Match `74` is completed:

- Rank `1` gets `+1000` leaderboard bonus points.
- Rank `2` gets `+600` leaderboard bonus points.
- Rank `3` gets `+300` leaderboard bonus points.
- If multiple users tie at a bonus rank, all tied users receive that rank's bonus.

## UI Requirements

- The selection UI must not enforce team-count limits.
- The validation UI must show only:
  - Total selected players.
  - Role requirements.
  - Captain/Vice-Captain requirements.
  - Current projected substitution penalties when a substitution window is open.
- During substitution windows, users should see penalty impact before saving.
- The `My Team` tab should display selected players sorted by average points.
- When `My Team` is selected, the secondary role tab row should be hidden.

## Implementation Notes

- Existing toss cutoff logic should be reused for Match `71`, Match `73`, and Match `74` locks.
- The backend should expose the active substitution phase in the Super Team context.
- Snapshot creation should be idempotent so cache refreshes and repeated jobs do not duplicate rows.
- Penalty calculation should be deterministic from stored snapshots and player roles.
- Existing admin recalculation should recompute snapshots and standings safely without changing user selections.
