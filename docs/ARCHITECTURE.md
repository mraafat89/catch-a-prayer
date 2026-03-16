# Catch a Prayer — System Architecture

## Overview

Catch a Prayer is a mobile-first web application that helps Muslims find nearby mosques and determine whether they can catch an upcoming prayer in congregation. It covers the US and Canada.

The fundamental architecture principle: **no mosque data is fetched live during a user request.** All mosque discovery, prayer times, and iqama data are pre-computed and stored in a database. User requests are fast reads against that database.

---

## System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER-FACING LAYER                        │
│                                                                 │
│  React PWA (mobile-first)                                       │
│  ├── Leaflet.js + OpenStreetMap tiles (map display)            │
│  ├── Mapbox Directions API (precise routing, on demand)         │
│  └── Deep links (Google Maps / Apple Maps / Waze navigation)   │
│                              │                                  │
│                              ▼ HTTPS                            │
│  FastAPI (Python)                                               │
│  ├── Mosque search (PostGIS spatial query)                      │
│  ├── Prayer time calculation + catching status                  │
│  ├── Notification scheduling                                    │
│  └── Push notification delivery (FCM)                          │
│                              │                                  │
│                              ▼                                  │
│  PostgreSQL + PostGIS                                           │
│  ├── mosques                (pre-seeded from OSM + enrichment) │
│  ├── prayer_schedules       (adhan + iqama per mosque/date)    │
│  ├── jumuah_sessions        (Friday prayer details)            │
│  ├── scraping_jobs          (pipeline queue + audit log)       │
│  └── push_subscriptions     (user notification registrations)  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     BACKGROUND PIPELINE                         │
│                    (never runs at request time)                 │
│                                                                 │
│  Mosque DB Seeder (weekly)                                      │
│  ├── Overpass API → bulk US/Canada mosque download              │
│  └── Google Places → one-time enrichment (website, phone)      │
│                                                                 │
│  Iqama Scraping Workers (nightly, pipeline/daily_pipeline.sh,  │
│  schedule: 0 2 * * *)                                          │
│  ├── Tier 1: IslamicFinder / Aladhan structured lookup         │
│  ├── Tier 2: Static HTML (httpx + BeautifulSoup)               │
│  ├── Tier 3: JS-rendered sites (Playwright async pool)         │
│  ├── Tier 4: Images + PDFs (Vision AI + pdfplumber)            │
│  └── Tier 5: Calculated adhan + estimated iqama (fallback)     │
│                                                                 │
│  Jumuah Scraper (Thursday nights)                               │
│  └── Re-scrape Friday-specific details for upcoming week        │
│                                                                 │
│  Notification Scheduler (runs at prayer times)                  │
│  └── FCM push sender for registered users                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

### Backend
| Component | Technology | Reason |
|---|---|---|
| API framework | FastAPI (Python) | Async, fast, typed |
| Database | PostgreSQL 15 + PostGIS | Spatial queries, reliability |
| ORM | SQLAlchemy 2 (async) | Type-safe, async support |
| Migrations | Alembic | Schema version control |
| Task queue | APScheduler (embedded) | No Redis needed for initial scale |
| HTTP client | httpx (async) | Async scraping |
| JS scraping | Playwright (async) | Modern Selenium replacement |
| Vision AI | Anthropic Claude API | Image prayer schedule extraction |
| Prayer calc | praytimes library | Astronomical calculation; explicitly initialized with ISNA settings (maghrib at sunset, fajr 15°, isha 15°) |
| Push notifications | Firebase Cloud Messaging (FCM) | Free, cross-platform |
| Timezone lookup | timezonefinder library | Coordinates → IANA timezone, offline |

### Frontend
| Component | Technology | Reason |
|---|---|---|
| Framework | React 18 + TypeScript | Type safety, component model |
| Map | Leaflet.js + OpenStreetMap | Free, no API key for tiles |
| Routing/travel time | Mapbox Directions API | Accurate, affordable, Leaflet integration |
| Styling | Tailwind CSS | Mobile-first utilities |
| PWA | Vite PWA plugin + Workbox | Service worker, offline support |
| Push (web) | Web Push API + VAPID | Browser push notifications |
| HTTP client | Axios | API communication |
| State | Zustand | Lightweight, simple |

### Infrastructure
| Component | Technology |
|---|---|
| Containerization | Docker + Docker Compose |
| Reverse proxy | Nginx |
| Database host | PostgreSQL (self-hosted or Supabase) |
| Deployment | Any VPS (DigitalOcean, Hetzner, Fly.io) |

---

## Data Flow: User Search Request

```
1. User opens app → browser requests location permission

2. User location obtained (GPS or entered address)

3. App sends POST /api/mosques/nearby
   { lat, lng, radius_km, client_timezone, client_current_time }

4. FastAPI handler:
   a. PostGIS query: SELECT mosques within radius, ordered by distance
      (no external API call — pure DB query, <50ms)

   b. For each mosque:
      - Load today's prayer_schedule from DB (adhan + iqama times)
      - If no scraped schedule: calculate adhan via adhan-python from mosque coords
      - Calculate catching status (5 statuses per ISLAMIC_PRAYER_RULES.md)
      - Attach data source label (scraped / calculated / estimated)

   c. Mapbox Matrix API call (ONE batch call for all mosques)
      - Returns travel times to all N mosques in one request
      - Cached by (user grid cell 500m, time-of-day bucket 15min)

   d. Assemble response: mosques sorted by catching viability + distance

5. Frontend renders mosque list + Leaflet map
   - Travel times shown
   - Catching status shown with color + source label

6. User taps mosque → bottom sheet opens
   - Full prayer schedule
   - Jumuah details (if Friday or upcoming)
   - "Navigate" button → deep link to chosen maps app
   - For selected mosque: fire Mapbox Directions for precise live routing
```

---

## Data Flow: Background Scraping Pipeline

```
Nightly 2AM (staggered by timezone batch):

1. Scheduler queries scraping_jobs:
   SELECT * FROM scraping_jobs
   WHERE next_attempt_at <= NOW()
   ORDER BY priority ASC, next_attempt_at ASC
   LIMIT 100  -- process in batches

2. For each job:
   a. Mark status = 'running'
   b. Attempt Tier 1 (structured source lookup via IslamicFinder/Aladhan)
      — Tier 1 is SKIPPED for mosques that have a known website (goes
        directly to Tier 2)
   c. If fails → attempt Tier 2 (static HTML: httpx + BeautifulSoup)
      — Tier 2 includes iframe widget detection (AthanPlus, Masjidal,
        etc.) and div-based extraction for embedded schedule widgets
   d. If fails → attempt Tier 3 (Playwright for JS-rendered sites)
   e. Images found in Tiers 2/3 → Tier 4 (Vision AI)
   f. If all fail → Tier 5 (calculated/estimated)
   g. Write results to prayer_schedules + jumuah_sessions
   h. Update scraping_jobs: status, tier_reached, next_attempt_at

3. Tier 4 runs as a sub-pipeline:
   - Images queued from Tier 2/3 scraping
   - Sent to Claude Vision API with structured prompt
   - JSON response parsed and stored

4. Results stored with:
   - source enum (mosque_website_html, vision_ai, calculated, etc.)
   - confidence (high/medium/low)
   - scraped_at timestamp
   - raw_extracted_json (for debugging/reprocessing)
```

---

## Key Design Decisions

### Why no live scraping at request time
Live scraping would add 5–160 seconds to every user search. Mosque prayer times change at most weekly (iqama) or daily (adhan, but those are calculable). A nightly offline pipeline provides fresh enough data with zero request latency.

### Why both adhan and iqama are scraped (not just iqama)
Some mosques set their own adhan times that differ from astronomical calculations — particularly Fajr, where different communities follow different calculation methods (ISNA 15°, MWL 18°, etc.). Scraped adhan always takes priority over calculated. Calculated is only the final fallback.

### Why PostGIS instead of calculating distance in app code
ST_DWithin + ST_Distance queries in PostGIS with a spatial index return results for 100k+ mosques in <10ms. Application-level distance filtering would require loading all mosques into memory.

### Why Mapbox over Google Maps
Google Maps Distance Matrix costs $10/1000 elements. Mapbox costs $2/1000 with a 100k/month free tier. At 10k DAU with caching, Mapbox costs ~$4/month. Google would cost ~$60,000/month for equivalent usage. Deep links to Google Maps / Apple Maps for navigation require no API at all.

### Why PWA first, Capacitor second
PWA allows instant deployment without app store review. The same React codebase wraps into a native app via Capacitor for iOS/Android when needed. iOS push notification support for PWAs improved significantly in iOS 16.4 (March 2023) and is now viable.

### Why Maghrib is always at sunset
Maghrib marks the end of the day in Islamic timekeeping and begins at astronomical sunset with no delay. The ISNA calculation method correctly specifies `maghrib: '0 min'` (zero minutes after sunset). The `praytimes` Python library has a known issue where it can inherit Jafari method defaults (`maghrib: 4°`, meaning ~16 minutes after sunset) when initialized with ISNA. The scraping worker explicitly overrides this with `pt.adjust({"maghrib": "0 min", ...})` after every initialization to prevent wrong Maghrib times in the database.

---

## Environment Variables

### Backend (server/.env)
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/catchaprayer
MAPBOX_API_KEY=pk.eyJ1...
ANTHROPIC_API_KEY=sk-ant-...
FCM_SERVER_KEY=...
GOOGLE_PLACES_API_KEY=...   # Only for one-time mosque enrichment seeder
ISLAMICFINDER_API_KEY=...   # If/when available
```

### Frontend (client/.env)
```
VITE_API_URL=http://localhost:8000
VITE_MAPBOX_TOKEN=pk.eyJ1...
VITE_VAPID_PUBLIC_KEY=...
```
