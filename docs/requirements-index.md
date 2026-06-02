# Requirements Index

This folder contains the working requirements and design notes for the Fantasy Cricket app. Use this file as the entry point when planning changes.

## Core Product Areas

| Area | Document |
|------|----------|
| Full app/product map | [product-app-requirements.md](product-app-requirements.md) |
| Auth and profile | [auth-profile-requirements.md](auth-profile-requirements.md) |
| Dashboard, matches, players | [dashboard-matches-players-requirements.md](dashboard-matches-players-requirements.md) |
| Edit team UI | [edit-team-ui-requirements.md](edit-team-ui-requirements.md) |
| View score UI | [view-score-ui-requirements.md](view-score-ui-requirements.md) |
| Leaderboard and points table | [leaderboard-points-table-requirements.md](leaderboard-points-table-requirements.md) |
| Scheduler ticks and caching | [scheduler-caching-requirements.md](scheduler-caching-requirements.md) |
| Database structure | [database-structure-requirements.md](database-structure-requirements.md) |
| Admin panel | [admin-panel-requirements.md](admin-panel-requirements.md) |
| API contract | [api-contract-requirements.md](api-contract-requirements.md) |
| API response schemas | [api-response-schemas.md](api-response-schemas.md) |
| Frontend UI specification | [frontend-ui-spec.md](frontend-ui-spec.md) |
| Seed data requirements | [seed-data-requirements.md](seed-data-requirements.md) |
| Local setup | [local-setup-requirements.md](local-setup-requirements.md) |
| Deployment and runtime | [deployment-runtime-requirements.md](deployment-runtime-requirements.md) |
| Test plan | [test-plan-requirements.md](test-plan-requirements.md) |

## Subcontests And Scoring

| Area | Document |
|------|----------|
| Subcontest requirements overview | [subcontest-requirements.md](subcontest-requirements.md) |
| Compact subcontest rules | [subcontest-rules.md](subcontest-rules.md) |
| Weekend Battle design | [weekend-tournament-design.md](weekend-tournament-design.md) |
| Super Team requirements | [super-team-requirements.md](super-team-requirements.md) |
| Score prediction design | [score-prediction-design.md](score-prediction-design.md) |
| Current scoring and scraper behavior | [current-scoring-scraper-requirements.md](current-scoring-scraper-requirements.md) |
| Scraper and parser requirements | [scraper-parser-requirements.md](scraper-parser-requirements.md) |
| Scoring system | [scoring-system-design.md](scoring-system-design.md) |
| Achievements | [achievements-design.md](achievements-design.md) |

## Maintenance Notes

- Treat the `*-requirements.md` files as the source of truth for rebuilding the current app. Older design/bug documents provide background and examples but may describe historical context.
- Keep rule documents and implementation requirements in sync when changing scoring, locks, bonuses, or admin behavior.
- When a feature adds persistent data, update both [database-structure-requirements.md](database-structure-requirements.md) and the feature-specific document.
- When a feature affects live matches, update [scheduler-caching-requirements.md](scheduler-caching-requirements.md) with invalidation and refresh requirements.
- Prefer requirements phrased as observable behavior and acceptance criteria, not implementation wishes.
