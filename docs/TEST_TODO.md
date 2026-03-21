# Test TODO

Remaining test phases to implement after bug fixes.

## Phase 7: Frontend Component Tests (React Testing Library)

Tests that render actual React components and verify UI behavior.

| File | Tests | What it covers |
|------|-------|---------------|
| `prayed-banner.test.tsx` | ~8 | Banner shows active prayers, mode-specific display (individual vs pairs), undo button, hide when all prayed |
| `mosque-card.test.tsx` | ~6 | Status badge colors, prayed filtering, travel combinations section, tap interaction |
| `mosque-suggestions.test.tsx` | ~6 | Suggestion form toggle, field selector, time input, submit, pending card display, vote buttons |
| `trip-planner.test.tsx` | ~5 | Destination input, long-trip modal, itinerary sort selector, plan loading state |

Prerequisites:
- Mock `leaflet` and `react-leaflet` in jest config (canvas not available in jsdom)
- Mock `apiService` per test
- Mock `navigator.geolocation`

## Phase 8: E2E Tests (Playwright)

Full browser tests against a running local server.

| File | Tests | What it covers |
|------|-------|---------------|
| `mosque-discovery.spec.ts` | 3 | Open app → mosque list → tap → details → navigate |
| `trip-planning.spec.ts` | 3 | Search destination → plan → select itinerary → navigate button |
| `prayer-tracking.spec.ts` | 3 | Mark prayer → verify filtered → switch mode → verify pairs |
| `spot-submission.spec.ts` | 2 | Submit spot → verify pending → confirm |
| `offline-resilience.spec.ts` | 2 | Disconnect → stale data → reconnect → refresh |

Prerequisites:
- Install Playwright: `npx playwright install chromium`
- E2E workflow in `.github/workflows/e2e.yml` (already created)
- Seed test data via API in `globalSetup.ts`
- Mock geolocation to fixed coordinates

## Pre-existing Test Failure

`client/src/__tests__/waypoint-advanced.test.ts` — 1 failing test, pre-existing. Needs investigation.
