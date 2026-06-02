# Frontend UI Specification

This document defines the visual and interaction requirements needed to recreate the current frontend.

## Technology And Structure

- React 19 with TypeScript.
- Vite build tool.
- Tailwind CSS utility styling.
- React Router for navigation.
- Axios client with auth interceptor.
- Lazy-loaded route components.
- Dark app shell with sticky top navbar.

## Global Styling

- Body background: black.
- Default text: white.
- Antialiasing enabled.
- Main content should be constrained to a readable app width where appropriate.
- Use translucent panels with `bg-white/5`, `bg-white/10`, and `border-white/10`.
- Common corners are rounded-xl or rounded-2xl in current UI.
- Mobile touch devices disable expensive blur/shadow effects through utility classes.
- Reduced motion disables ping animations.

## Navbar

File: `frontend/src/components/Navbar.tsx`.

Requirements:

- Sticky top nav, black background, bottom white translucent border.
- Brand link goes to `/dashboard`.
- Brand includes a cricket-style icon and text `Fantasy Cricket`.
- When logged in:
  - Show user name on larger screens.
  - Show Admin link only for admin users.
  - Show Settings link.
  - Show Rules link.
  - Show Logout button.
- Logout clears auth and routes to `/login`.

## Team Themes

File: `frontend/src/utils/teamTheme.ts`.

Supported team codes and aliases:

- CSK: Chennai Super Kings
- MI: Mumbai Indians
- RCB: Royal Challengers Bengaluru
- KKR: Kolkata Knight Riders
- RR: Rajasthan Royals
- GT: Gujarat Titans
- DC: Delhi Capitals
- LSG: Lucknow Super Giants
- PBKS: Punjab Kings
- SRH: Sunrisers Hyderabad

Requirements:

- Each team has a short `label`.
- Each team has a badge class.
- Each team has a tint gradient class.
- Unknown teams fall back to white translucent styling.

## Login Page

Route: `/login`.

Requirements:

- Full-screen black page.
- Hero image `/mahi.jpg`.
- Brand title `Fantasy Cricket`.
- Subtitle `Hippies Mahasangram`.
- Email and password fields.
- Primary `Sign In` button.
- Secondary `Dev Login (No Password)` button.
- Link to Register.
- Error banner for login failures.
- Loading state while signing in.

## Register Page

Route: `/register`.

Requirements:

- Register Firebase user and backend profile.
- Collect name, email, and password.
- Navigate to dashboard after success.
- Link back to login.
- Show validation/auth errors.

## Dashboard Page

Route: `/dashboard`.

Requirements:

- Shows greeting or personalized player context.
- Shows quick action buttons for Leaderboard, Points Table, Weekend, Super Team, Achievements where enabled.
- Tabs: Today, Upcoming, Completed.
- Match cards show team badges, date/time, status, countdown, user team state, backup count, lineup warnings, current rank.
- Skeleton loading state.
- Empty states per tab.
- Contestants modal with Playing and Missing tabs.
- Prefetch player data for today matches.

## Select Team Page

Route: `/select-team/:matchId`.

Required layout:

- Header with match teams/status.
- Role filter tabs.
- Player list grouped by role.
- My Team view.
- Backup selection controls.
- Sticky footer with selected count, C/VC status, prediction state, and save button.
- Prediction modal.
- Saved team preview modal.

Player cards must show:

- Name.
- Team badge.
- Role.
- Total/average/last match points.
- Recent history when available.
- Playing XI/substitute/unavailable state.
- Selected state highlight.
- Captain/Vice-Captain controls for selected players.

## View Scores Page

Route: `/view-scores/:matchId`.

Tabs:

- Scores.
- Scorecard.
- My Team.
- Diff/Compare.

Requirements:

- Contestant ranking list with points and rank movement.
- Prediction badges for predictions and awarded bonuses.
- Player fantasy point table.
- Team breakdown modal/section.
- Comparison selector and diff display.
- Polling for live matches.
- Preserve stale usable data if refresh fails.

## Leaderboard Page

Route: `/leaderboard`.

Requirements:

- Header with back and refresh actions.
- Top 3 podium when at least 3 entries exist.
- Podium background uses `/podium.jpeg` for descending sort and `/loserclub.jpg` for ascending sort.
- Sortable columns:
  - Points
  - Prediction Bonus
  - Super Team Bonus when present
  - Gold
  - Silver
  - Bronze
  - Total medals
  - Weekend wins
  - Balance
- Current user row highlighted and marked `YOU`.
- Entry/prize note displayed.

## Points Table Page

Route: `/points-table`.

Requirements:

- Sticky Player and Total columns.
- One column per match.
- Match column header shows teams and match id.
- Per-cell points, medal rank, net balance, or adjusted marker.
- Export button downloads `.xlsx`.
- Current user highlighted.

## Weekend Battle Page

Route: `/weekend`.

Requirements:

- Status banner.
- Winner display when completed.
- Progress tracker.
- Qualifier list with seeds, points, LB/backfilled tag, YOU tag.
- Horizontal bracket diagram.
- Matchup cards with pending/live/completed states.
- Past winners list.
- Rules section.

## Super Team Page

Route: `/super-team`.

Requirements:

- Context/status banner.
- Tabs: Live, My Team, Compare.
- Player pool grouped by role and squad.
- Role requirements and selected count.
- Captain/Vice-Captain controls.
- Projected penalty preview during substitution windows.
- Contestants and Missing tabs.
- Standings with gross, penalty, net points.
- Player ownership/compare details where available.

## Admin UI

Admin layout:

- Sidebar or mobile-friendly admin navigation.
- Admin identity summary.
- Nested content area.

Admin pages:

- Dashboard: counts and recalculation shortcut.
- Players: list, create, edit, delete, role/type/aliases.
- Matches: list, create, edit, delete, status/external ids.
- Teams: match selector, submitted teams, edit modal.
- Backups: replacement overview.
- Users: active toggle and role select.
- Scores: recalculate, validate, admin submit team.
- Missed Players: unknown scraper names.
- Super Team: snapshot and recalculation controls.

## Loading And Empty States

- Initial page loads use spinners or skeletons.
- Background refresh should not blank the page.
- Empty states should be short and direct.
- Failed admin actions should show an error toast/message.

## Accessibility And Responsiveness

- All buttons must remain tappable on mobile.
- Sticky footers must not cover essential controls.
- Tables may scroll horizontally.
- Text should truncate rather than overlap.
- Icon-only buttons need `title` or accessible text.
