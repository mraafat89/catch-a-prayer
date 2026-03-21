# Test Plan

Comprehensive test strategy for Catch a Prayer. Tests run locally during development and automatically on GitHub PRs via GitHub Actions.

---

## Test Layers

```
┌─────────────────────────────────────────────────────────────┐
│  E2E Tests (Playwright)                                      │
│  Full user journeys: browser → API → DB → response → UI     │
│  ~10 tests, slow, run on PR only                            │
├─────────────────────────────────────────────────────────────┤
│  Feature Tests (pytest + httpx, Jest + RTL)                  │
│  Complete feature workflows through real API/components      │
│  ~40 tests, medium speed                                    │
├─────────────────────────────────────────────────────────────┤
│  Integration Tests (pytest + httpx)                          │
│  Single API endpoint with real DB                           │
│  ~30 tests, fast                                            │
├─────────────────────────────────────────────────────────────┤
│  Unit Tests (pytest, Jest)                                   │
│  Pure functions, no DB, no network                          │
│  ~60 tests, very fast                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
server/
  tests/
    conftest.py                          # DB fixtures, async client, seed helpers
    unit/
      test_prayer_calc.py                # Prayer time calculation
      test_mosque_search_logic.py        # Catching status, travel combinations, period ends
      test_travel_planner_logic.py       # Overlap detection, itinerary building, scoring
      test_content_filtering.py          # Spam detection, input validation
    integration/
      test_health_api.py                 # Health check
      test_mosques_api.py                # Mosque search + detail endpoints
      test_spots_api.py                  # Spot CRUD + verification
      test_suggestions_api.py            # Suggestion CRUD + voting
      test_travel_api.py                 # Travel plan endpoint (mocked routing)
    feature/
      test_prayer_catching_flow.py       # Full prayer discovery: search → status → prayed → re-search
      test_musafir_mode_flow.py          # Mode switch → combining → pair skipping → prayed inference
      test_trip_planning_flow.py         # Plan trip → get itineraries → select → navigate
      test_community_correction_flow.py  # Submit suggestion → others vote → auto-apply
      test_spot_lifecycle_flow.py        # Submit spot → pending → verify → active → reject
      test_multi_day_trip_flow.py        # Multi-day trip with per-day prayers + timezone
    nfr/
      test_latency.py                    # Response time benchmarks
      test_rate_limiting.py              # Rate limit enforcement
      test_crash_resistance.py           # Null inputs, malformed data, empty DB

client/
  src/__tests__/
    unit/
      prayer-logic.test.ts              # Prayer period rules, sequential inference
      time-helpers.test.ts              # fmtTime, fmtDuration, distLabel, USE_METRIC
      store.test.ts                     # Zustand store: prayed tracker, mode switching
    feature/
      prayed-banner.test.tsx            # Banner: shows active prayers, mode switching, undo
      mosque-card.test.tsx              # Card: status display, prayed filtering, combinations
      mosque-suggestions.test.tsx       # Suggestion form + voting UI
      trip-planner.test.tsx             # Destination input → plan → results → sort
    e2e/                                # (Playwright, separate from Jest)
      setup.ts                          # Browser launch, base URL config
      mosque-discovery.spec.ts          # Open app → see mosques → tap → details → navigate
      trip-planning.spec.ts             # Search destination → plan → select itinerary → navigate
      prayer-tracking.spec.ts           # Mark prayer → verify filtered → switch mode → verify
      spot-submission.spec.ts           # Submit spot → verify pending → confirm → active
      offline-resilience.spec.ts        # Disconnect → show stale → reconnect → refresh

.github/
  workflows/
    test.yml                            # CI: unit + integration + feature on every PR
    e2e.yml                             # CI: E2E on PRs to main only (slower)
```

---

## Layer 1: Unit Tests

Pure functions, no DB, no network. Run in < 10 seconds.

### Backend Unit Tests

#### test_prayer_calc.py
| Test | Rule | Input | Expected |
|------|------|-------|----------|
| `test_all_five_prayers_returned` | FR-2.1 | Menlo Park, Mar 20 | Dict with fajr/dhuhr/asr/maghrib/isha adhan keys |
| `test_prayer_order_chronological` | RULES §1 | Any US location | fajr < sunrise < dhuhr < asr < maghrib < isha |
| `test_iqama_offsets` | RULES §2 | Calculated schedule | fajr+20, dhuhr+15, asr+10, maghrib+5, isha+15 |
| `test_maghrib_at_sunset` | RULES §1 | Any location | maghrib_adhan within 2 min of astronomical sunset |
| `test_summer_vs_winter_times` | RULES §1 | NYC Jun 21 vs Dec 21 | Summer Fajr earlier, Isha later |

#### test_mosque_search_logic.py
| Test | Rule | Input | Expected |
|------|------|-------|----------|
| `test_status_can_catch_with_imam` | RULES §2 | Arrive 5 min before iqama | `can_catch_with_imam` |
| `test_status_in_progress` | RULES §2 | Current time >= iqama, arrive within 15 min | `can_catch_with_imam_in_progress` |
| `test_status_solo` | RULES §2 | After congregation, before period end | `can_pray_solo_at_mosque` |
| `test_status_pray_nearby` | RULES §2 | Can't reach before period end | `pray_at_nearby_location` |
| `test_status_missed` | RULES §2 | After period end | `missed_make_up` |
| `test_status_upcoming` | RULES §2 | Before adhan, within 2h | `upcoming` |
| `test_upcoming_window_uses_adhan_not_iqama` | RULES §2 | 2h 5min before iqama, 1h 50min before adhan | `upcoming` (shown) |
| `test_upcoming_beyond_2h_not_shown` | RULES §2 | 2h 10min before adhan | Not in catchable_prayers |
| `test_isha_period_ends_at_next_fajr` | RULES §1 | 1 AM, Isha started 9 PM, Fajr 5:30 AM | `can_pray_solo` (not missed) |
| `test_isha_after_midnight_discouraged` | RULES §1 | 12:30 AM | Status includes discouraged note |
| `test_isha_after_fajr_is_missed` | RULES §1 | 5:45 AM, Fajr at 5:30 | `missed_make_up` |
| `test_all_passed_returns_fajr_tomorrow` | RULES §1 | 11 PM, all passed | Returns info about tomorrow's Fajr |
| `test_no_adhan_uses_iqama_minus_15` | RULES §2 | iqama only, no adhan | Estimated adhan = iqama - 15 |
| `test_no_iqama_uses_standard_offset` | RULES §2 | adhan only, no iqama | Estimated iqama = adhan + offset |
| `test_musafir_sequential_inference` | RULES §3 | prayed={"asr"} | Skip both dhuhr and asr |
| `test_musafir_dhuhr_only_doesnt_skip_asr` | RULES §3 | prayed={"dhuhr"} | Skip dhuhr only, asr still active |
| `test_travel_combinations_first_pair_only` | RULES §4 | Both pairs unresolved | Only dhuhr+asr shown |
| `test_travel_combinations_skip_prayed_pair` | RULES §4 | Dhuhr+Asr prayed | Show maghrib+isha |
| `test_taqdeem_before_asr_adhan` | RULES §4 | Current before Asr adhan | Jam' Taqdeem option |
| `test_takheer_after_asr_adhan` | RULES §4 | Current after Asr adhan | Jam' Ta'kheer option |

#### test_travel_planner_logic.py
| Test | Rule | Input | Expected |
|------|------|-------|----------|
| `test_prayer_overlaps_daytime_trip` | ALGO §2 | Depart 10 AM, arrive 3 PM | Dhuhr and Asr overlap |
| `test_prayer_overlaps_overnight_trip` | ALGO §2 | Depart 10 PM, arrive 6 AM | Isha and Fajr overlap |
| `test_prayer_no_overlap_short_trip` | ALGO §2 | Depart 3:01 PM, arrive 3:30 PM (between prayers) | No overlap |
| `test_pair_relevant_checks_both_prayers` | ALGO §2 | Trip overlaps Asr but not Dhuhr | Pair IS relevant |
| `test_build_itineraries_musafir_templates` | ALGO §4 | 2 pairs, multiple options | 3-5 distinct itineraries |
| `test_build_itineraries_muqeem_no_combining` | ALGO §4 | Muqeem mode | No combine_early/late |
| `test_itinerary_scoring` | ALGO §5 | 3 itineraries with diff detours | Ranked by score ascending |
| `test_checkpoint_time_interpolation` | ALGO §1 | Route with known duration | Checkpoint times spaced correctly |
| `test_trip_over_3_days_rejected` | FR-4.4 | 80-hour trip | Error message about breaking into segments |

#### test_content_filtering.py
| Test | Rule | Input | Expected |
|------|------|-------|----------|
| `test_url_in_name_rejected` | NFR-5.2 | "Mosque http://spam.com" | 422 |
| `test_allcaps_spam_rejected` | NFR-5.2 | "VISIT BEST MOSQUE NOW" | 422 |
| `test_normal_name_passes` | NFR-5.2 | "Islamic Center of Durham" | OK |
| `test_geographic_bounds_us` | NFR-5.2 | lat=40, lng=-74 (NYC) | OK |
| `test_geographic_bounds_outside` | NFR-5.2 | lat=10, lng=50 (Africa) | 422 |

### Frontend Unit Tests

#### prayer-logic.test.ts
| Test | Rule | Input | Expected |
|------|------|-------|----------|
| `test_sequential_inference_asr_implies_dhuhr` | RULES §3 | Set has "asr" | effectivePrayed has "dhuhr" and "asr" |
| `test_sequential_inference_dhuhr_alone` | RULES §3 | Set has "dhuhr" | effectivePrayed has "dhuhr" only |
| `test_sequential_inference_isha_implies_maghrib` | RULES §3 | Set has "isha" | effectivePrayed has "maghrib" and "isha" |
| `test_mode_switch_muqeem_to_musafir` | RULES §3 | Muqeem set={"asr"} | After switch: set has {"dhuhr","asr"} |

#### time-helpers.test.ts
| Test | Rule | Input | Expected |
|------|------|-------|----------|
| `test_fmtTime_24h_to_12h` | — | "14:30" | "2:30 PM" |
| `test_fmtTime_null_returns_dash` | — | null | "—" |
| `test_distLabel_metric` | NFR-8.2 | 1500m, USE_METRIC=true | "1.5 km" |
| `test_distLabel_imperial` | NFR-8.2 | 1500m, USE_METRIC=false | "0.9 mi" |
| `test_distLabel_feet_small` | NFR-8.2 | 50m, USE_METRIC=false | "164 ft" |

#### store.test.ts
| Test | Rule | Input | Expected |
|------|------|-------|----------|
| `test_togglePrayed_adds_prayer` | RULES §3 | togglePrayed("dhuhr") | Set contains "dhuhr" |
| `test_togglePrayed_removes_on_second` | RULES §3 | togglePrayed("dhuhr") x2 | Set is empty |
| `test_togglePrayedPair_adds_both` | RULES §3 | togglePrayedPair("dhuhr","asr") | Set has both |
| `test_prayed_persists_to_localStorage` | RULES §3 | togglePrayed("fajr") | localStorage has "fajr" |
| `test_prayed_keyed_by_date` | RULES §3 | Toggle, advance date | New date = empty Set |

---

## Layer 2: Integration Tests

Single API endpoint with real PostgreSQL+PostGIS. Run in < 30 seconds.

### test_mosques_api.py
| Test | Endpoint | Setup | Expected |
|------|----------|-------|----------|
| `test_nearby_returns_seeded_mosque` | POST /api/mosques/nearby | Seed mosque at (40.71, -74.00) | 200, mosque in list |
| `test_nearby_respects_radius` | POST /api/mosques/nearby | Seed mosque 20 km away, radius=5 | 200, empty list |
| `test_nearby_invalid_coords` | POST /api/mosques/nearby | lat=200 | 422 |
| `test_nearby_returns_prayer_times` | POST /api/mosques/nearby | Seed mosque + schedule | prayers array has 5 entries |
| `test_nearby_returns_catching_status` | POST /api/mosques/nearby | Seed mosque + schedule, set client_current_time | next_catchable is not null |

### test_spots_api.py
| Test | Endpoint | Setup | Expected |
|------|----------|-------|----------|
| `test_submit_spot_201` | POST /api/spots | Valid spot in NYC | 201 + spot_id |
| `test_submit_spot_outside_bounds` | POST /api/spots | lat=10 | 422 |
| `test_submit_spot_url_in_name` | POST /api/spots | name="http://spam" | 422 |
| `test_submit_spot_dedup_50m` | POST /api/spots | Two spots at same location | 409 on second |
| `test_submit_rate_limit` | POST /api/spots | 4 spots same session | 429 on 4th |
| `test_nearby_hides_unverified` | POST /api/spots/nearby | Pending spot, different session | Spot not in results |
| `test_nearby_shows_own_pending` | POST /api/spots/nearby | Pending spot, same session | Spot in results |
| `test_verify_positive` | POST /api/spots/{id}/verify | Positive vote | verification_count incremented |
| `test_verify_self_rejected` | POST /api/spots/{id}/verify | Same session as submitter | 403 |
| `test_verify_duplicate_rejected` | POST /api/spots/{id}/verify | Same session votes twice | 409 |

### test_suggestions_api.py
| Test | Endpoint | Setup | Expected |
|------|----------|-------|----------|
| `test_submit_iqama_suggestion` | POST /api/mosques/{id}/suggestions | field=dhuhr_iqama, value=13:15 | 201 |
| `test_submit_invalid_time` | POST /api/mosques/{id}/suggestions | field=dhuhr_iqama, value="abc" | 422 |
| `test_submit_same_as_current` | POST /api/mosques/{id}/suggestions | Suggested = current value | 409 |
| `test_duplicate_pending_rejected` | POST /api/mosques/{id}/suggestions | Same field twice | 409 |
| `test_vote_increments_count` | POST /api/suggestions/{id}/vote | Positive vote | upvote_count=1 |
| `test_self_vote_rejected` | POST /api/suggestions/{id}/vote | Submitter votes | 403 |
| `test_list_pending_only` | GET /api/mosques/{id}/suggestions | Mix of pending/accepted | Only pending returned |

---

## Layer 3: Feature Tests

Complete feature workflows through multiple API calls, testing the full business logic.

### test_prayer_catching_flow.py
```
1. Seed mosque with today's schedule (known iqama times)
2. Search nearby at time T (before Dhuhr iqama) → assert can_catch_with_imam for Dhuhr
3. Search again at T+20min (after iqama) → assert can_catch_with_imam_in_progress
4. Search again at T+40min (after congregation) → assert can_pray_solo
5. Search again at T+3h (after Asr adhan) → assert Dhuhr is missed, Asr is catchable
6. Search with prayed_prayers=["dhuhr"] → assert Dhuhr skipped, Asr shown
7. Search at 11 PM (all passed) → assert response includes Fajr tomorrow info
```

### test_musafir_mode_flow.py
```
1. Seed mosque with schedule
2. Search in Muqeem mode → assert no travel_combinations
3. Search in Musafir mode → assert travel_combinations has dhuhr_asr pair
4. Search with prayed=["asr"] in Musafir → both dhuhr+asr skipped, maghrib+isha shown
5. Search with prayed=["dhuhr"] in Musafir → dhuhr skipped, asr still shown (pair incomplete)
6. Search with prayed=["dhuhr","asr"] → pair fully done, show maghrib+isha
7. Search with prayed=["dhuhr","asr","isha"] → all done (isha implies maghrib)
8. Verify taqdeem shown before Asr adhan, takheer shown after
```

### test_trip_planning_flow.py
```
1. Seed mosques along a known route corridor
2. POST /api/travel/plan with origin/dest (mock Mapbox to return fixed route)
3. Assert: prayer_pairs contains relevant pairs for trip window
4. Assert: itineraries has 3-5 options
5. Assert: each itinerary has route_geometry
6. Assert: itineraries are ranked (first has lowest score)
7. Assert: stops have valid mosque_id, iqama_time, detour_minutes
8. Repeat with prayed_prayers=["dhuhr","asr"] → pair skipped in results
9. Repeat in Muqeem mode → no combining options
```

### test_community_correction_flow.py
```
1. Seed mosque with dhuhr_iqama = "13:00"
2. Session A submits suggestion: dhuhr_iqama → "13:15"
3. Assert: suggestion pending, upvote_count=0
4. Session A tries to vote on own → 403
5. Session B votes positive → upvote_count=1
6. Session C votes positive → upvote_count=2, status=accepted (iqama threshold=2)
7. Query mosque prayer schedule → dhuhr_iqama is now "13:15", source="user_submitted"
8. Session D tries to submit same field → 409 (no longer pending, already accepted)
```

### test_spot_lifecycle_flow.py
```
1. Session A submits spot at (40.71, -74.00)
2. Assert: status=pending, visible to session A only
3. Session B searches nearby → spot NOT visible (0 external verifications)
4. Session B verifies positive → verification_count=1
5. Session C searches nearby → spot now visible (1+ external verification)
6. Session C verifies positive → verification_count=2
7. Session D verifies positive → verification_count=3, status=active
8. Session E verifies negative → rejection_count=1 (still active, net=2)
9. Three more negative votes → net ≤ -3, status=rejected
10. Session F searches nearby → spot NOT visible
```

### test_multi_day_trip_flow.py
```
1. Seed mosques in 3 cities along a long route
2. POST /api/travel/plan: departure Dec 31 10 PM ET, arrival Jan 2 2 PM CT
3. Assert: trip not rejected (under 3 days)
4. Assert: prayer_pairs include prayers for both Jan 1 and Jan 2
5. Assert: Fajr appears twice (Jan 1 and Jan 2)
6. Assert: mosque stops use correct local timezone
7. Repeat with 4-day trip → assert error message about breaking into segments
```

---

## Layer 4: E2E Tests (Playwright)

Full browser-based user journeys against running local server. Slow but catches real integration issues.

### Setup
- Start local server + DB via docker-compose
- Seed test data via API calls in `globalSetup`
- Use Playwright with Chromium
- Mock geolocation to fixed NYC coordinates
- Mock Mapbox responses via route interception

### mosque-discovery.spec.ts
```
1. Open app → geolocation prompt → allow
2. Wait for mosque list to appear
3. Assert: at least 1 mosque card visible
4. Assert: mosque card shows name, distance, prayer status
5. Tap mosque card → detail sheet opens
6. Assert: prayer times table visible with 5 rows
7. Assert: navigate button visible
8. Tap ✕ → detail closes, list returns
```

### trip-planning.spec.ts
```
1. Tap "Where to?" → search opens
2. Type "Los Angeles" → wait for suggestions
3. Tap first suggestion → destination set
4. Tap "Pray on Route" → spinner appears
5. Wait for itineraries to load
6. Assert: at least 1 itinerary card visible
7. Tap first itinerary → route shown on map
8. Assert: "Bismillah — Navigate" button visible
9. Tap navigate → action sheet with Google Maps option
```

### prayer-tracking.spec.ts
```
1. Open app → mosque list loads
2. Assert: prayed banner visible with active prayers
3. Tap "Yes, I prayed" for Dhuhr
4. Assert: Dhuhr shows checkmark + undo
5. Assert: mosque cards no longer show Dhuhr status
6. Tap mode toggle → switch to Musafir
7. Assert: banner shows pairs (Dhuhr+Asr)
8. Assert: Dhuhr+Asr pair shows as partially done (Dhuhr marked, Asr not)
9. Tap undo on Dhuhr → pair resets
```

### spot-submission.spec.ts
```
1. Open settings → enable "Show prayer spots"
2. Tap "+" FAB → submission form opens
3. Fill name: "Test Prayer Room"
4. Type address → select from suggestions
5. Tap Submit → success message
6. Close form → spot appears on map (pending marker)
```

### offline-resilience.spec.ts
```
1. Open app → mosque list loads
2. Go offline (Playwright context.setOffline(true))
3. Assert: mosque list still visible (cached)
4. Wait for auto-refresh → assert no crash
5. Go online → assert data refreshes
```

---

## Layer 5: NFR Tests

### test_latency.py
| Test | Target | Method |
|------|--------|--------|
| `test_health_under_100ms` | < 100ms | Time GET /health |
| `test_nearby_under_500ms` | < 500ms p95 | Time POST /mosques/nearby × 10 |
| `test_spots_nearby_under_300ms` | < 300ms | Time POST /spots/nearby |
| `test_suggestions_list_under_200ms` | < 200ms | Time GET /mosques/{id}/suggestions |

### test_rate_limiting.py
| Test | Limit | Method |
|------|-------|--------|
| `test_spot_submit_rate_limit_session` | 3/24h | Submit 4, assert 429 on 4th |
| `test_spot_verify_rate_limit_session` | 30/24h | Verify 31, assert 429 on 31st |
| `test_suggestion_submit_rate_limit` | 5/24h | Submit 6, assert 429 on 6th |

### test_crash_resistance.py
| Test | Input | Expected |
|------|-------|----------|
| `test_nearby_empty_db` | No mosques seeded | 200 with empty list (not 500) |
| `test_nearby_null_timezone` | Mosque with timezone=null | Fallback to client TZ, not crash |
| `test_nearby_malformed_schedule` | Prayer times with invalid format | Skip prayer, don't crash |
| `test_suggestion_nonexistent_mosque` | Random UUID | 404 |
| `test_spot_verify_nonexistent_spot` | Random UUID | 404 |

---

## GitHub Actions

### test.yml (every PR)

```yaml
name: Tests
on:
  pull_request:
    branches: [main, dev]
  push:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgis/postgis:15-3.4
        env:
          POSTGRES_DB: catchaprayer_test
          POSTGRES_USER: cap
          POSTGRES_PASSWORD: cap
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U cap"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DATABASE_URL: postgresql+asyncpg://cap:cap@localhost:5432/catchaprayer_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11', cache: 'pip', cache-dependency-path: server/requirements.txt }
      - run: cd server && pip install -r requirements.txt && pip install pytest pytest-asyncio pytest-timeout
      - run: cd server && python -m pytest tests/ -v --timeout=30
        timeout-minutes: 10

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '18', cache: 'npm', cache-dependency-path: client/package-lock.json }
      - run: cd client && npm ci
      - run: cd client && CI=true npm test -- --watchAll=false
        timeout-minutes: 5
```

### e2e.yml (PRs to main only)

```yaml
name: E2E Tests
on:
  pull_request:
    branches: [main]

jobs:
  e2e:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgis/postgis:15-3.4
        env:
          POSTGRES_DB: catchaprayer_test
          POSTGRES_USER: cap
          POSTGRES_PASSWORD: cap
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U cap"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DATABASE_URL: postgresql+asyncpg://cap:cap@localhost:5432/catchaprayer_test
      REACT_APP_API_URL: http://localhost:8000
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - uses: actions/setup-node@v4
        with: { node-version: '18' }
      - run: cd server && pip install -r requirements.txt
      - run: cd server && uvicorn app.main:app --host 0.0.0.0 --port 8000 &
      - run: cd client && npm ci && npm run build
      - run: npx playwright install chromium
      - run: cd client && npx playwright test
        timeout-minutes: 15
```

---

## What NOT to Test

- **Leaflet map rendering** (canvas/WebGL, not available in jsdom or headless)
- **Mapbox/OSRM API calls** (always mocked — never hit real external APIs in tests)
- **Scraping pipeline** (server/pipeline/) — separate domain, has its own ad-hoc tests
- **Capacitor native layer** (iOS/Android build artifacts)
- **Visual regression** (no screenshot comparison)
- **Manual UX** (drag gestures, pinch-zoom, scroll momentum)

---

## Implementation Order

| Phase | What | Priority | Est. Tests |
|-------|------|----------|------------|
| 1 | Test infrastructure: conftest.py, pytest config, CI workflow | Foundation | 0 |
| 2 | Backend unit tests (prayer calc, catching status, travel logic) | Highest value | ~25 |
| 3 | Backend integration tests (all API endpoints) | High value | ~25 |
| 4 | Backend feature tests (full workflows) | High value | ~15 |
| 5 | Frontend unit tests (logic, store, helpers) | Medium | ~15 |
| 6 | Backend NFR tests (latency, rate limits, crash resistance) | Medium | ~15 |
| 7 | Frontend feature tests (components with RTL) | Medium | ~10 |
| 8 | E2E tests (Playwright) | Lower priority, highest confidence | ~10 |

Total: ~115 tests across all layers.

---

## Running Tests Locally

```bash
# Backend (all)
cd server && python -m pytest tests/ -v

# Backend (unit only, fast)
cd server && python -m pytest tests/unit/ -v

# Backend (single file)
cd server && python -m pytest tests/unit/test_prayer_calc.py -v

# Frontend (all)
cd client && npm test -- --watchAll=false

# Frontend (single file)
cd client && npm test -- --testPathPattern=prayer-logic

# E2E (requires running server)
cd client && npx playwright test
```
