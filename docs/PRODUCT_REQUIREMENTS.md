# Product Requirements

Functional and non-functional requirements for Catch a Prayer. This document + `PRAYER_LOGIC_RULES.md` together define the complete product specification. Tests are written against these two documents.

---

## FR-1: Location & Mosque Discovery

### FR-1.1: Geolocation
- App requests location permission on first open
- On allow: fetch GPS position (high accuracy, 10s timeout, 5 min cache)
- On deny: show error "Please enable location access to find nearby mosques" — app remains usable for trip planning via manual address entry
- On timeout: retry once with `enableHighAccuracy: false` before showing error
- Location updates when user re-opens app or returns from background

### FR-1.2: Nearby Mosque Search
- Search mosques within user's radius (default 10 km, range 1–50 km)
- Results sorted by catching viability first, then distance
- Maximum 20 mosques returned per search
- Results include: name, address, distance, travel time, prayer times, catching status
- Empty results: show "No mosques found within {radius}. Try increasing the search radius in Settings."

### FR-1.3: Auto-Refresh
- Mosque data refreshes every 5 minutes while app is in foreground
- On network error: exponential backoff (5 min → 10 min → 20 min), max 3 retries
- Reset backoff on: successful fetch, user changes radius/mode, user taps a mosque
- Do NOT refresh while trip planner form is open

### FR-1.4: Denomination Filter
- Options: All, Sunni, Shia, Ismaili
- Applied client-side to the fetched mosque list
- Default: All
- Persisted in localStorage

---

## FR-2: Prayer Status Display

### FR-2.1: Catching Status
- Every mosque shows the most actionable prayer status (see `PRAYER_LOGIC_RULES.md` section 2)
- Color-coded: green (catch with imam), amber (in progress), blue (solo), orange (pray nearby), gray (missed/upcoming)
- Message includes specific action: "Leave by {time} to catch with Imam"
- Status refreshes with each 5-minute auto-refresh

### FR-2.2: Prayer Times Table
- Mosque detail shows all 5 prayers with adhan + iqama columns
- Sunrise (Shorooq) row appears after Fajr in amber highlight
- Each time shows its data source on hover/tap
- Missing times show "—" dash

### FR-2.3: Jumu'ah (Friday Prayer)
- Only displayed on Fridays (or when viewing mosque detail any day if data available)
- Supports multiple sessions per mosque
- Shows: session number, khutba start, prayer start, imam name, language, special notes, booking info

### FR-2.4: After All Prayers Pass
- When all 5 prayers have passed and it's after Isha congregation:
  - Show "Next: Fajr tomorrow at {time}" with leave-by time
  - Use tomorrow's Fajr schedule (calculated if not scraped)
- Isha after midnight: show "can pray solo" status with note "Discouraged after midnight"

---

## FR-3: Prayer Tracking (Prayed Banner)

### FR-3.1: Display
- Banner appears at top of mosque list showing active prayers
- Each prayer shows: name, iqama time, "Did you already pray?" prompt
- After marking: shows checkmark with "Undo" button
- Banner disappears when all active prayers are marked

### FR-3.2: Muqeem Mode
- Shows individual prayers: Fajr, Dhuhr, Asr, Maghrib, Isha
- Each toggled independently

### FR-3.3: Musafir Mode
- Shows prayer pairs: Dhuhr+Asr, Maghrib+Isha (Fajr individual)
- Marking a pair marks both prayers in the Set
- Sequential inference: marking Asr → Dhuhr implicitly marked. Marking Dhuhr → Asr NOT implied.

### FR-3.4: Mode Switching
- Muqeem → Musafir: apply sequential inference (Asr marked → add Dhuhr, Isha marked → add Maghrib), persist expanded Set
- Musafir → Muqeem: carry prayed Set as-is, both individual prayers already stored

### FR-3.5: Persistence
- Stored in localStorage keyed by Islamic prayer day (Fajr-to-Fajr, not calendar midnight)
- Before today's Fajr adhan: use yesterday's date key
- After today's Fajr adhan: use today's date key
- Isha prayed at 11 PM and Isha prayed at 1 AM same night → same day key

### FR-3.6: Effect on Mosque List
- Prayed prayers excluded from catching status calculation
- Mosque cards show next unprayed prayer instead
- Travel combinations skip prayed pairs

---

## FR-4: Travel Planning (Pray on Route)

### FR-4.1: Destination Input
- "Where to?" pill at top of screen
- Geocoding autocomplete (debounced 400ms, min 3 chars)
- Supports: US and Canada addresses/places
- Tap suggestion → confirms destination, shows preview

### FR-4.2: Trip Configuration
- Origin: defaults to current GPS location, can be changed manually
- Waypoints: up to 4 intermediate stops, reorderable
- Departure time: defaults to now, user can set future time
- Departure time must be in the future (validate on submit)

### FR-4.3: Long Trip Detection
- Trips > 80 km in Muqeem mode → show Musafir suggestion modal
- User chooses: "Switch to Musafir" or "Continue as Muqeem"
- Distance shown in km (Canada) or miles (US)

### FR-4.4: Trip Duration Limits
- Maximum supported: 3 days (72 hours)
- Trips exceeding 3 days: show message "This trip is longer than 3 days. Please break it into shorter segments for accurate prayer planning."
- Multi-day trips track prayers per calendar day with correct timezone-aware schedules

### FR-4.5: Route Planning Algorithm

#### 4.5.1: Mosque Discovery (Corridor Search)
- Sample waypoints every 30 minutes along the route
- Search within 25 km radius of each waypoint (default corridor)
- Skip mosques requiring > 60 min total detour
- Compute detour time using haversine + 1.3x road factor at 60 km/h
- Origin/destination anchor mosques: compute ACTUAL detour (not hardcoded 0)

#### 4.5.2: Mosque Selection (Scoring)
- For each prayer, score candidate mosques by:
  - **Detour cost** (lower is better): time added to trip in minutes
  - **Iqama alignment** (higher is better): how close arrival is to iqama (catching with imam preferred over solo)
  - **Data confidence** (higher is better): scraped mosque > calculated times
- Select the top-scoring mosque per prayer, not just the first one found
- This is the key optimization: we don't pick the first mosque along the route — we pick the BEST one

#### 4.5.3: Itinerary Generation
- Generate 3-5 itinerary templates per trip:
  - **All early (Jam' Taqdeem)**: combine both pairs at first prayer's time — minimizes stops
  - **All late (Jam' Ta'kheer)**: combine at second prayer's time — maximizes flexibility
  - **Mixed**: Taqdeem for first pair, Ta'kheer for second
  - **Separate stops**: individual mosque stop for each prayer (Muqeem mode)
  - **At destination**: pray all at arrival if timing allows
- Each itinerary scored and ranked (see 4.5.4)

#### 4.5.4: Itinerary Ranking (Default Sort)
- Score each itinerary: `score = (total_detour_minutes * 2) + (stop_count * 10) + (infeasible_prayers * 100)`
- Lower score = better. Rank ascending.
- Best-ranked itinerary is auto-selected and shown first
- Infeasible prayers heavily penalized (missing a prayer is worse than a long detour)

#### 4.5.5: User Sort Options
- After results load, user can re-sort itineraries by:
  - **Recommended** (default ranking from 4.5.4)
  - **Least detour** (sort by total_detour_minutes ascending)
  - **Fewest stops** (sort by stop_count ascending, detour as tiebreak)
  - **Most prayers with Imam** (sort by count of `can_catch_with_imam` stops descending)
- Sort selector appears above itinerary list as a small dropdown or segmented control

#### 4.5.6: Progressive Radius Search (No Mosque Found)
- If no mosque found for a prayer within 25 km corridor:
  1. Expand search to 50 km radius and retry
  2. If still none at 50 km: expand to 75 km and retry
  3. If still none at 75 km: show "No mosque found for {prayer}. Consider praying at a rest stop. Nearest mosque is {distance} away ({detour} min detour)."
- Each expansion only runs for the missing prayer, not all prayers
- The nearest mosque (even if over the limit) is always returned as a fallback option with a warning label

#### 4.5.7: Multi-Day Trip Planning
- For trips spanning multiple calendar days (up to 3 days):
  - Track which DATE each prayer belongs to
  - Fetch prayer schedule for each specific date at each location along the route
  - Group prayer stops by day in the itinerary display:
    ```
    Day 1 (Mar 20)
      Dhuhr + Asr at Islamic Center of Durham — 1:15 PM (8 min detour)
    Day 2 (Mar 21)
      Fajr at Masjid Al-Noor — 5:45 AM (12 min detour)
      Dhuhr + Asr at Mosque of Raleigh — 1:30 PM (5 min detour)
    ```
  - Each day's Fajr is a separate prayer (not carried from previous day)
  - Prayed state is per-date: marking Fajr as prayed on Day 1 doesn't skip Day 2's Fajr

#### 4.5.8: Timezone Crossing
- All prayer time comparisons use the MOSQUE's local timezone
- Destination schedule uses ARRIVAL date in destination timezone (not departure date)
- Timezone offset computed from arrival_dt (not departure_dt) to handle DST correctly
- Each checkpoint's local time is computed in the timezone at that geographic point

### FR-4.6: Plan Results Display
- Itinerary list with sort selector at top
- Each itinerary shows: label, summary, total detour, stop count, route geometry
- Best-ranked itinerary auto-selected
- Tap itinerary → select it, show route on map
- Tap mosque stop → focus on map, show details
- Multi-day trips: day headers between stops

### FR-4.7: Plan Caching
- Cache by: mode + origin + destination + waypoints + departure time + sort preference
- Cache invalidated on: clearAll(), prayed state change (replan with new prayed set)
- Cache does NOT persist across app reloads
- Limit cache to 10 entries (LRU eviction)

### FR-4.8: Navigation
- "Bismillah — Navigate" button when itinerary selected
- Opens action sheet: Google Maps, Apple Maps (iOS only), Share Route
- Waypoints from selected itinerary included in navigation URL
- Uses Google Place ID when available for more accurate pin placement

### FR-4.9: Error Handling
- Plan loading: show spinner "Planning your prayer route..."
- Plan failure: show error message "Failed to plan route. Please check your connection and try again." — do NOT leave spinner hanging
- No mosques along route after progressive search: show nearest mosque as fallback with detour warning
- Trip > 3 days: show message before planning starts

---

## FR-5: Prayer Spots (Community Locations)

### FR-5.1: Display
- Toggle via Settings → "Show prayer spots"
- Shown as dashed circle markers on map
- Listed below mosques in bottom sheet
- Each shows: name, type, distance, verification status, facilities

### FR-5.2: Spot Types
- Prayer room, Multifaith room, Quiet room, Community hall, Halal restaurant, Campus prayer room, Rest area / gas station, Airport prayer room, Hospital chapel, Office prayer room, Other

### FR-5.3: Submission
- "+" FAB button opens submission form
- Required: name, location (GPS or address search)
- Optional: type (default prayer room), facilities, hours, website, notes
- On submit: spot starts as "pending", visible only to submitter until 1+ external verification
- Becomes "active" at 3+ net positive verifications
- Removed at 3+ net negative verifications

### FR-5.4: Verification
- Other users see: "Confirm" / "No longer valid" buttons
- One vote per session per spot (enforced by session_id + IP hash)
- Cannot verify own submission
- Rate limit: 30 verifications per session per 24h

### FR-5.5: Spot Navigation
- Navigate button on spot detail → action sheet (Google/Apple Maps, Share)

---

## FR-6: Mosque Suggestions (Community Corrections)

### FR-6.1: Submitting Corrections
- "Times look wrong? Suggest a correction" link in mosque detail
- Correctable fields: 5 iqama times, phone, website, women's section, parking, wheelchair
- One pending suggestion per field per mosque
- Rate limit: 5 per session per 24h, 3 per IP per 24h

### FR-6.2: Voting
- Other users see pending corrections with current→suggested diff
- "Confirm" / "That's wrong" buttons
- Self-vote prevention, session+IP dedup

### FR-6.3: Acceptance
- Iqama corrections: accepted at net +2 votes, expire after 7 days
- Facility corrections: accepted at net +3 votes, expire after 90 days
- On acceptance: correction applied to database automatically

---

## FR-7: Settings

### FR-7.1: Search Radius
- Slider: 1–50 km (or equivalent in miles for US)
- Changes trigger immediate mosque re-fetch
- Label shows current value in user's unit system

### FR-7.2: Denomination Filter
- Segmented control: All / Sunni / Shia / Ismaili
- Changes filter mosque list immediately

### FR-7.3: Show Prayer Spots
- Toggle switch
- Off: hides spot markers on map and spot cards in list
- Also hides/shows FAB button

---

## FR-8: Map Interactions

### FR-8.1: Mosque Pins
- Color-coded by catching status
- Tap pin → select mosque (same as tapping card)
- Selected pin is larger

### FR-8.2: Route Display
- Trip route polyline shown when destination set
- Single-mosque route (OSRM) shown when mosque selected
- Route stop pins with permanent tooltip (mosque name)

### FR-8.3: Recenter Button
- Visible when user has panned away from their location
- Hidden during: full sheet, modal open, nav action sheet, trip planner loading/editing
- Tap → fly to current location with sheet-aware offset

---

## FR-9: Deep Links / Sharing

### FR-9.1: Incoming Deep Links
- Format: `?dest_lat=X&dest_lng=Y&dest_name=Z`
- Sets destination ONLY — does NOT change travel mode
- Long-trip modal appears if >80 km and user is in Muqeem mode

### FR-9.2: Web Share Target
- Accepts shared URLs from Google Maps / Apple Maps
- Parses coordinates and place name
- Pre-fills destination search if URL can't be parsed
- Does NOT change travel mode

### FR-9.3: Outgoing Sharing
- Share mosque directions (Google Maps URL)
- Share trip route (Google Maps with waypoints)
- Uses Web Share API → clipboard fallback → open in new tab

---

## NFR-1: Latency

### NFR-1.1: API Response Times (p95 targets)
| Endpoint | Target | Notes |
|----------|--------|-------|
| `POST /api/mosques/nearby` | < 500ms | PostGIS spatial query + Mapbox matrix (1 batch call). This is the hot path — every user hits it on app open and every 5 min. |
| `POST /api/travel/plan` | < 5s | Corridor search + Mapbox routing + itinerary generation. Heavier computation is acceptable because user explicitly triggers it and sees a spinner. |
| `GET /api/mosques/{id}/suggestions` | < 200ms | Simple DB read. |
| `POST /api/spots/nearby` | < 300ms | PostGIS spatial query, similar to mosque search. |
| `POST /api/spots` | < 500ms | Insert + dedup check + rate limit checks. |
| `POST /api/spots/{id}/verify` | < 300ms | Insert + count update. |
| `POST /api/mosques/{id}/suggestions` | < 500ms | Insert + dedup + rate limits. |
| `POST /api/suggestions/{id}/vote` | < 300ms | Insert + count update + possible auto-apply. |
| `GET /health` | < 50ms | No DB access. |

### NFR-1.2: Client-Side Render Times
| Operation | Target | Notes |
|-----------|--------|-------|
| Initial mosque list render | < 200ms | 20 MosqueCards with status badges |
| Prayer times table | < 100ms | 5 rows + Shorooq |
| Map tile load (cached) | < 500ms | Leaflet tile layer from CARTO |
| Bottom sheet snap animation | < 16ms per frame (60 FPS) | CSS transform, no layout thrash |
| Mode toggle → UI repaint | < 100ms | Theme color swap, no API call needed |

### NFR-1.3: Third-Party Dependency Latency
| Service | Expected | Timeout | Fallback |
|---------|----------|---------|----------|
| Mapbox Directions API | 200-800ms | 10s | Straight-line distance + haversine time estimate |
| Mapbox Matrix API | 100-500ms | 10s | Haversine distance / 40 km/h estimate |
| OSRM (single mosque route) | 100-400ms | 5s | Straight line between user and mosque |
| Nominatim geocoding | 200-600ms | 10s | Show "search failed" message |
| OpenStreetMap tiles | 50-200ms (cached) | 10s | Blank tiles (map still functional) |

### NFR-1.4: Cold Start
- Server cold start (Docker container): < 10s
- Client first paint: < 1.5s on 4G (HTML + JS bundle)
- Client interactive (mosque list visible): < 3s on 4G (geolocation + API call)
- Subsequent app opens (warm): < 1s (cached JS + cached tiles)

---

## NFR-2: Scalability

### NFR-2.1: Data Scale
| Entity | Current | Target (1 year) | Growth Strategy |
|--------|---------|-----------------|-----------------|
| Mosques | ~2,500 | ~5,000 | Weekly OSM seed + community additions |
| Prayer schedules | ~2,500/day | ~5,000/day | Nightly scraper, 30-day pre-compute |
| Prayer spots | ~100 | ~10,000 | Community submissions |
| Mosque suggestions | ~0 | ~5,000/month | Community corrections |
| Spot verifications | ~0 | ~50,000/month | Community voting |

### NFR-2.2: User Scale
| Metric | Current | Target (1 year) | Bottleneck |
|--------|---------|-----------------|------------|
| DAU | <100 | 10,000 | Mapbox API limits (100k free/month) |
| Peak concurrent | <10 | 500 | PostgreSQL connection pool (default 20) |
| Requests/min (peak) | <50 | 5,000 | Single FastAPI instance with uvicorn workers |
| Travel plans/min | <5 | 200 | Mapbox rate limits + computation |

### NFR-2.3: Scaling Strategy (When Needed)
**Phase 1 — Current (single VPS, <1,000 DAU):**
- 1x FastAPI + uvicorn (4 workers)
- 1x PostgreSQL + PostGIS
- Caddy reverse proxy
- All on one Hetzner/DigitalOcean VPS

**Phase 2 — Growth (1,000-10,000 DAU):**
- Add Redis for: rate limiting (shared state across workers), Mapbox response cache (matrix results, 15 min TTL), session-based rate limit counters
- Increase uvicorn workers to 8
- Add connection pooler (PgBouncer) for PostgreSQL
- Move scraping pipeline to separate worker (not on the API server)
- CDN for static assets (Cloudflare or similar)

**Phase 3 — Scale (10,000+ DAU):**
- Horizontal API scaling (2-3 instances behind load balancer)
- Read replicas for PostgreSQL (nearby search is read-heavy)
- Mapbox cache at CDN edge
- Consider Mapbox alternatives if costs scale (OSRM self-hosted for matrix)
- Background job queue (Celery + Redis) for travel plan computation

### NFR-2.4: Database Performance
- All spatial queries use PostGIS GIST indexes (already in place)
- `ST_DWithin` for radius search (uses index, not full table scan)
- Mosque search: max 20 results per query (LIMIT enforced)
- Travel corridor search: max 2,000 mosque candidates (LIMIT enforced)
- Prayer schedule: unique index on (mosque_id, date) for fast lookups
- Connection pool: 5 min connections, 20 max (configurable via `DATABASE_URL` pool params)

### NFR-2.5: Rate Limiting
| Endpoint Group | Limit | Window | Scope |
|----------------|-------|--------|-------|
| `/api/mosques/nearby` | 30 req | 1 min | Per IP |
| `/api/travel/plan` | 10 req | 1 min | Per IP |
| All other endpoints | 60 req | 1 min | Per IP |
| Spot submissions | 3 | 24h | Per session + per IP |
| Spot verifications | 30 | 24h | Per session |
| Mosque suggestions | 5 | 24h | Per session |
| Suggestion votes | 30 | 24h | Per session |

---

## NFR-3: Availability

### NFR-3.1: Uptime Target
- **99.5% monthly uptime** (allows ~3.6 hours downtime/month)
- Planned maintenance: during low-traffic hours (2-5 AM ET, when scraper runs anyway)
- Unplanned downtime: target < 30 min recovery time

### NFR-3.2: Health Monitoring
- `GET /health` endpoint returns server status
- Health check: database connectivity test (simple query)
- Docker HEALTHCHECK: curl /health every 30s, 3 retries before marking unhealthy
- External uptime monitoring (e.g., UptimeRobot or similar — ping /health every 5 min)

### NFR-3.3: Failure Modes & Recovery

| Failure | User Impact | Detection | Recovery |
|---------|-------------|-----------|----------|
| API server crash | App shows stale data + error on refresh | Docker HEALTHCHECK → auto-restart | Automatic (Docker restart policy: unless-stopped) |
| Database crash | All API calls fail (500) | Health check fails | Docker auto-restart; WAL recovery for data integrity |
| Mapbox API down | No travel times on mosque cards; travel plan fails | HTTP timeout (10s) | Fallback to haversine distance estimates; show "Travel time unavailable" |
| OSRM down | No single-mosque route on map | HTTP timeout (5s) | Straight-line polyline fallback |
| Nominatim down | Geocoding fails | HTTP timeout (10s) | Backend Mapbox geocoder fallback; then show "Search unavailable" |
| Disk full | DB writes fail, scraper fails | Monitor disk usage | Alert + clean old scraping logs/raw HTML |
| SSL cert expired | HTTPS fails, app can't connect | Caddy auto-renewal (should not happen) | Manual cert renewal |

### NFR-3.4: Data Durability
- PostgreSQL with WAL (Write-Ahead Logging) — survives crashes without data loss
- Daily database backups (pg_dump) stored off-server
- Prayer schedules pre-computed 30 days ahead — if scraper fails, data stays valid for weeks
- Mosque data from OSM is stable — only changes on weekly seed runs

### NFR-3.5: Graceful Degradation Tiers

| Tier | What's Down | What Still Works |
|------|-------------|-----------------|
| Tier 1 (full service) | Nothing | Everything |
| Tier 2 (no Mapbox) | Mapbox API | Mosque search (haversine fallback), prayer times, spots, suggestions. No travel times or route planning. |
| Tier 3 (no external APIs) | Mapbox + OSRM + Nominatim | Mosque search, prayer times (from DB), spots, suggestions. No routing, no geocoding. |
| Tier 4 (DB read-only) | DB writes fail | Mosque search + prayer times (reads work). No submissions, votes, or suggestions. |
| Tier 5 (API down) | FastAPI server | Client shows cached mosque list. Prayed tracking works (localStorage). Map tiles load (CDN). |
| Tier 6 (fully offline) | Network | Prayed tracking. Cached map tiles. Previously loaded mosque list (stale). |

---

## NFR-4: Reliability

### NFR-4.1: Crash Prevention
- All API responses must be null-checked before property access
- `next_catchable` can be null — mosque still renders without status badge
- `catchable_prayers` can be empty array — no crash
- `adhan_time` / `iqama_time` can be null — show "—" dash
- `travel_combinations` can be empty — section hidden
- Array index access (itinerary selection) must bounds-check
- Travel plan response can be null — show error message, not spinner forever

### NFR-4.2: Error Recovery
- Network failure: show user-facing error message (never silent for primary actions)
- Stale data: show cached data with "Last updated X minutes ago" indicator
- Invalid state: reset to safe defaults (e.g., selectedItineraryIndex reset when plan changes)
- API 5xx: show "Something went wrong. Please try again." with retry button

### NFR-4.3: Data Integrity
- Prayed state: never lose data — persist immediately on toggle
- Session ID: never regenerate — same ID for lifetime of app install
- Spot confirmations: persist even on API failure (optimistic update)
- Database transactions: all multi-step writes use transactions (vote + count update atomic)

### NFR-4.4: Idempotency
- Spot verification: unique constraint on (spot_id, session_id) — double-submit returns 409, not duplicate entry
- Suggestion vote: unique constraint on (suggestion_id, session_id) — same protection
- Spot submission: dedup by 50m radius — submitting same location twice returns 409

---

## NFR-5: Security

### NFR-5.1: No PII
- No user accounts, emails, or names collected
- Session ID is random, not derived from device info
- IP addresses hashed (SHA-256) on server, never stored raw

### NFR-5.2: Input Sanitization
- All text inputs checked for URLs, excessive caps (server-side)
- Geographic bounds enforced (US/Canada only: lat 24-72, lng -168 to -52)
- SQL injection: all queries use parameterized statements (SQLAlchemy `text()` with `:param` bindings)
- XSS: React auto-escapes all rendered text; no `dangerouslySetInnerHTML`
- Rate limiting on all submission/voting endpoints (see NFR-2.5)

### NFR-5.3: Transport
- All API calls over HTTPS (Caddy auto-TLS with Let's Encrypt)
- No sensitive data in URL parameters
- CORS: allow all origins (public API, no auth)
- Security headers: X-Frame-Options, X-Content-Type-Options, X-XSS-Protection (via Nginx/Caddy)

### NFR-5.4: Abuse Prevention
- Rate limiting per IP and per session (see NFR-2.5)
- Content filtering: reject URLs in name/notes fields, reject excessive ALL_CAPS
- Self-vote prevention on spots and suggestions
- IP hash dedup prevents multi-device ballot stuffing from same network
- Geographic bounds reject submissions outside US/Canada

---

## NFR-6: Usability

### NFR-6.1: Glanceability
- Most important info (can I catch this prayer?) readable in 2 seconds
- Color + text + icon for status (not color alone — accessible to colorblind users)
- Distance and time always visible on mosque card

### NFR-6.2: One-Handed Use
- All primary actions reachable from bottom half of screen
- Bottom sheet covers primary interactions
- Top bar only for trip destination input

### NFR-6.3: Accessibility
- All icon buttons have aria-label
- Prayer times table uses semantic HTML (thead, th, td)
- Touch targets minimum 44x44px
- Text minimum 12px (0.75rem)
- Status communicated by color AND text (not color alone)

### NFR-6.4: Offline Graceful Degradation
- Show cached mosque list when offline
- Show "You're offline" indicator (not silent failure)
- Prayed tracking works fully offline
- Spot/suggestion submissions: show clear error with "Try again when connected"

---

## NFR-7: Performance

### NFR-7.1: Client Memory
- Plan cache: clear on clearAll() and limit to 10 entries (LRU eviction)
- Mosque list: max 20 items (server-limited)
- Map markers: max ~70 (20 mosques + 20 spots + route stops + user)
- No memory leaks from event listeners or intervals (cleanup in useEffect returns)

### NFR-7.2: Battery
- Auto-refresh capped at 5-minute intervals with exponential backoff on failure
- No continuous GPS polling (one-shot with 5 min cache)
- No background processing (Capacitor app suspends in background)
- Map tile requests only on pan/zoom (Leaflet handles this)

### NFR-7.3: Bundle Size
- Target: < 500 KB gzipped for initial JS bundle
- Leaflet lazy-loaded (not in critical path)
- No unnecessary dependencies

### NFR-7.4: Database Query Performance
- All spatial queries: < 50ms (PostGIS GIST index)
- Prayer schedule lookup: < 10ms (unique index on mosque_id + date)
- Travel corridor query: < 200ms for 13+ waypoint OR clauses (to be optimized with single bbox)

---

## NFR-8: Compatibility

### NFR-8.1: Platforms
- iOS 15+ (via Capacitor)
- Android 10+ (via Capacitor)
- Mobile Safari 15+, Chrome 90+ (PWA fallback)

### NFR-8.2: Regions
- United States and Canada only
- Metric (Canada) / Imperial (US) auto-detected from timezone
- English language only (v1)

### NFR-8.3: Calculation Method
- ISNA (Islamic Society of North America) — default for US/Canada
- Fajr 15°, Isha 15°, Maghrib at sunset (0 min)

---

## NFR-9: Observability

### NFR-9.1: Logging
- Structured logging: timestamp, level, module, message
- Log all API errors with request path, status code, and error detail
- Log scraper results: mosques scraped, tier reached, success/failure counts
- No PII in logs (no IPs, no session IDs in production logs)

### NFR-9.2: Metrics (when Prometheus is enabled)
- Request count by endpoint and status code
- Response time histogram by endpoint
- Active database connections
- Scraper success rate (by tier)
- Mosque coverage: % with scraped data vs calculated

### NFR-9.3: Alerting (Phase 2)
- Health check failure for > 5 min → alert
- Error rate > 10% for > 5 min → alert
- Disk usage > 80% → alert
- Scraper success rate < 50% → alert
- SSL certificate expiry < 14 days → alert
