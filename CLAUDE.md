# CLAUDE.md — Project Rules for AI Agents

This file is read by Claude Code and any AI agent working on this project. Follow these rules exactly.

---

## Project Overview

Catch a Prayer — mobile app helping Muslims find nearby mosques with real prayer times. React + Capacitor (iOS/Android) frontend, FastAPI + PostgreSQL/PostGIS backend. US and Canada only.

## Repository Layout

```
client/          React 18 + TypeScript + Tailwind + Capacitor
server/          FastAPI + SQLAlchemy + PostGIS
server/tests/    pytest test suite (unit, integration, feature, NFR)
server/pipeline/ Scraping pipeline (separate domain, don't modify without asking)
docs/            Design docs (source of truth for all logic)
.github/         CI/CD workflows
```

## Key Design Documents (read before making changes)

- `docs/PRAYER_LOGIC_RULES.md` — Islamic prayer rules, catching status, prayed tracker, mode switching
- `docs/PRODUCT_REQUIREMENTS.md` — All functional + non-functional requirements
- `docs/ROUTE_PLANNING_ALGORITHM.md` — Travel planner algorithm
- `docs/FRONTEND_DESIGN.md` — UI/UX design, component behavior
- `docs/DEVELOPMENT_WORKFLOW.md` — Branch strategy, environment config
- `docs/BACKLOG.md` — Deferred items for future versions

---

## Branch Strategy

```
main             production — protected, PR required, tests must pass
 └── dev         integration — open for direct pushes
      └── feature/xyz   your working branch
```

**Rules:**
- NEVER push directly to `main` — always via PR from `dev`
- Create feature branches from `dev`: `git checkout dev && git checkout -b feature/my-feature`
- Merge feature → `dev` (direct push OK)
- Merge `dev` → `main` (PR required, tests must pass)
- Delete feature branches after merge

---

## Development Flow

```
1. Create feature branch from dev
2. Write failing tests first (TDD)
3. Implement the feature
4. Run tests locally: cd server && python -m pytest tests/ -v
5. Run frontend tests: cd client && CI=true npm test -- --watchAll=false
6. Push to feature branch
7. Merge to dev
8. Test on phone (local server): cd client && npm run sync:ios:dev
9. When ready for production: create PR from dev → main
10. Tests run automatically on PR
11. Owner reviews and merges
12. Owner manually triggers Deploy workflow on GitHub Actions
```

---

## Deployment Flow

| Action | How | Who can trigger |
|--------|-----|----------------|
| Deploy to production | GitHub Actions → "Deploy to Production" → type "deploy" | Agent or Owner |
| Create release | GitHub Actions → "Release & Deploy" → fill version + notes | Agent or Owner |
| Submit to Apple/Google | Xcode Archive / Android Studio AAB → upload | Owner only |

**Deploy only when:**
1. All tests pass (automated)
2. PR merged to `main`

**WARNING: DESTRUCTIVE operations (dropping tables, deleting data, destructive migrations) require EXPLICIT human approval before deploying. Always stop and ask the owner first, even in autonomous/skip-permissions mode. No exceptions.**

**Server deploys are independent from app store submissions.** Only submit to Apple/Google when client code changed.

---

## Testing Rules

**396 tests across 8 layers. All must pass before merging to main.**

```bash
# Backend (225 tests)
cd server && python -m pytest tests/ -v --timeout=30

# Frontend (153 tests)
cd client && CI=true npm test -- --watchAll=false

# E2E (12 tests, requires running server + client)
cd client && npm run test:e2e
```

**Test-Driven Development (TDD) is required for all new features and bug fixes:**
1. Write failing test that defines expected behavior
2. Implement the code to make it pass
3. Verify all existing tests still pass

**Test categories:**
- `server/tests/unit/` — pure functions, no DB
- `server/tests/integration/` — API endpoints with real PostGIS DB
- `server/tests/feature/` — multi-step business workflows
- `server/tests/nfr/` — latency, rate limiting, crash resistance
- `client/src/__tests__/unit/` — logic, store, helpers
- `client/src/__tests__/feature/` — component logic
- `client/e2e/` — Playwright browser tests

---

## API Backwards Compatibility

**The server must ALWAYS support the current live app version.**

**Safe changes (deploy anytime):**
- Adding new endpoints
- Adding optional fields to responses
- Adding optional fields to requests (with defaults)
- Bug fixes that don't change the API contract

**Breaking changes (NEVER do without coordination):**
- Removing or renaming endpoints
- Removing or renaming response fields
- Changing required request fields
- Changing response field types

If a breaking change is truly needed, use two-phase deploy:
1. Deploy server supporting BOTH old and new behavior
2. Submit new app to App Store
3. Wait 1-2 weeks for users to update
4. Remove old behavior

---

## Versioning

```
0.x.0  — pre-1.0 minor releases (current phase)
1.0.0  — first major release
x.y.0  — minor releases (features, fixes)
x.0.0  — major releases (breaking changes)
```

- Deploys don't need version numbers
- Releases get version tags (v0.10.0)
- App Store version must be higher than previous submission (gaps OK: 0.9.0 → 0.12.0)

---

## Code Style

- **Backend**: Python 3.11, FastAPI, async/await, SQLAlchemy 2 with raw SQL for spatial queries
- **Frontend**: React 18, TypeScript, Tailwind CSS, Zustand for state
- **No emojis in code or UI** unless user explicitly requests
- **No unnecessary abstractions** — keep it simple
- **No over-engineering** — solve the current problem, not hypothetical future ones
- **Read existing code before modifying** — match patterns already in use
- **All text inputs sanitized server-side** — URLs blocked, ALL_CAPS spam blocked, geographic bounds enforced

---

## Database Migrations

Schema changes are managed by **Alembic** (`server/alembic/versions/`). Production deploys run `alembic upgrade head` automatically.

**When to create a migration:**
- Adding a new table
- Adding/removing/renaming columns
- Adding/removing indexes or constraints

**How:**
1. Update or add the model in `server/app/models.py`
2. Create a new migration file in `server/alembic/versions/` following the naming pattern: `00X_description.py` (increment the number from the latest migration)
3. Include both `upgrade()` and `downgrade()` functions
4. Set `revision` and `down_revision` to chain correctly

**Rules:**
- Migrations must be **additive** — never drop columns/tables that live server code uses
- **WARNING: DESTRUCTIVE MIGRATIONS (dropping tables, dropping columns, deleting data, renaming columns) are NEVER allowed without explicit human approval. Always stop and ask the owner first, even in autonomous/skip-permissions mode. No exceptions.**
- For destructive changes, use two-phase: add new → deploy → remove old later
- Never edit the database schema directly in production
- Test migrations locally before merging: `cd server && alembic upgrade head`

---

## Environment

- **Docker**: `docker-compose.yml` for local dev (api + db), `docker-compose.prod.yml` for production
- **Test DB**: `catchaprayer_test` (auto-created by test fixtures)
- **API URL**: set via `REACT_APP_API_URL` environment variable
  - Local: `http://<mac-ip>:8000`
  - Production: `https://catchaprayer.com`
- **Build commands**:
  - `npm run sync:ios:dev` — build + sync for local testing
  - `npm run sync:ios` — build + sync for production / App Store

---

## What NOT to Touch Without Asking

- `server/pipeline/` — scraping pipeline, has its own test files
- `docker-compose.prod.yml` — production infrastructure
- `.env` files — contain secrets, never commit
- Branch protection rules on `main`

---

## CRITICAL: Production Server Rules

**NEVER run `git reset --hard` on the production server.** It breaks Docker bind mounts by recreating files with new inodes. Caddy and other containers lose access to mounted directories (like `client/build/`) and the site goes down.

**NEVER switch branches on the production server.** The server must ALWAYS be on `main`. If you need to test something, test locally or on a staging environment.

**NEVER push directly to `main` from the server.** All changes go through PRs.

**NO manual deploys via SSH.** All production deploys MUST go through GitHub Actions:
- Use the "Deploy to Production" workflow for quick deploys
- Use the "Release & Deploy" workflow for versioned releases
- These workflows handle git pull, builds, Caddy restart correctly

**If something is broken on production**, the ONLY allowed manual SSH action is `docker restart cap-caddy` to fix mount issues. Everything else goes through workflows.

**After ANY client build on the server, Caddy must be restarted** to refresh bind mounts. The workflows handle this automatically.
