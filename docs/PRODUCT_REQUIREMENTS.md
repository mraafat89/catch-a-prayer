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

### FR-4.5: Plan Results
- Return 3-5 itinerary options with different prayer strategies
- Each itinerary shows: label, summary, detour minutes, mosque stops, route geometry
- First itinerary auto-selected
- Tap itinerary → select it, show route on map
- Tap mosque stop → focus on map, show details

### FR-4.6: Plan Caching
- Cache by: mode + origin + destination + waypoints + departure time
- Cache invalidated on: clearAll(), prayed state change (replan with new prayed set)
- Cache does NOT persist across app reloads

### FR-4.7: Navigation
- "Bismillah — Navigate" button when itinerary selected
- Opens action sheet: Google Maps, Apple Maps (iOS only), Share Route
- Waypoints from selected itinerary included in navigation URL
- Uses Google Place ID when available for more accurate pin placement

### FR-4.8: Error Handling
- Plan loading: show spinner "Planning your prayer route..."
- Plan failure: show error message "Failed to plan route. Please check your connection and try again." — do NOT leave spinner hanging
- No mosques along route: show "No prayer stops found along this route"

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

## NFR-1: Performance

### NFR-1.1: Load Time
- Initial mosque list: < 2 seconds on 4G network
- Prayer times table render: < 100ms
- Map tile load: dependent on network, Leaflet handles caching

### NFR-1.2: Memory
- Plan cache: clear on clearAll() and limit to 10 entries (LRU eviction)
- Mosque list: max 20 items (server-limited)
- Map markers: max ~70 (20 mosques + 20 spots + route stops + user)

### NFR-1.3: Battery
- Auto-refresh capped at 5-minute intervals with backoff
- No continuous GPS polling (one-shot with 5 min cache)
- No background processing (Capacitor app suspends in background)

---

## NFR-2: Reliability

### NFR-2.1: Crash Prevention
- All API responses must be null-checked before property access
- `next_catchable` can be null — mosque still renders without status badge
- `catchable_prayers` can be empty array — no crash
- `adhan_time` / `iqama_time` can be null — show "—" dash
- `travel_combinations` can be empty — section hidden
- Array index access (itinerary selection) must bounds-check

### NFR-2.2: Error Recovery
- Network failure: show user-facing error message (never silent for primary actions)
- Stale data: show cached data with "Last updated X minutes ago" indicator
- Invalid state: reset to safe defaults (e.g., selectedItineraryIndex reset when plan changes)

### NFR-2.3: Data Integrity
- Prayed state: never lose data — persist immediately on toggle
- Session ID: never regenerate — same ID for lifetime of app install
- Spot confirmations: persist even on API failure (optimistic update)

---

## NFR-3: Security

### NFR-3.1: No PII
- No user accounts, emails, or names collected
- Session ID is random, not derived from device info
- IP addresses hashed (SHA-256) on server, never stored raw

### NFR-3.2: Input Sanitization
- All text inputs checked for URLs, excessive caps (server-side)
- Geographic bounds enforced (US/Canada only)
- Rate limiting on all submission/voting endpoints

### NFR-3.3: Transport
- All API calls over HTTPS
- No sensitive data in URL parameters

---

## NFR-4: Usability

### NFR-4.1: Glanceability
- Most important info (can I catch this prayer?) readable in 2 seconds
- Color + text + icon for status (not color alone)
- Distance and time always visible on mosque card

### NFR-4.2: One-Handed Use
- All primary actions reachable from bottom half of screen
- Bottom sheet covers primary interactions
- Top bar only for trip destination input

### NFR-4.3: Accessibility
- All icon buttons have aria-label
- Prayer times table uses semantic HTML (thead, th, td)
- Touch targets minimum 44x44px
- Text minimum 12px (0.75rem)

### NFR-4.4: Offline Graceful Degradation
- Show cached mosque list when offline
- Show "You're offline" indicator (not silent failure)
- Prayed tracking works fully offline
- Spot/suggestion submissions queued for retry (or show clear error)

---

## NFR-5: Compatibility

### NFR-5.1: Platforms
- iOS 15+ (via Capacitor)
- Android 10+ (via Capacitor)
- Mobile Safari, Chrome (PWA fallback)

### NFR-5.2: Regions
- United States and Canada only
- Metric (Canada) / Imperial (US) auto-detected from timezone
- English language only (v1)

### NFR-5.3: Calculation Method
- ISNA (Islamic Society of North America) — default for US/Canada
- Fajr 15°, Isha 15°, Maghrib at sunset (0 min)
