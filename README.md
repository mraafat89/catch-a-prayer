# Catch a Prayer

Find nearby mosques and never miss a prayer again. Shows whether you can catch a prayer with the Imam, pray solo, or need to find a nearby clean location — with real travel times and full source transparency.

Designed for US and Canada. Mobile-first PWA.

---

## Features

### Prayer Status
- **5 catching statuses**: With Imam / Imam in progress / Solo at mosque / Pray nearby / Missed — make up
- **Both Adhan and Iqama times**: Scraped from each mosque's own website — not just calculated
- **Source transparency**: Every time shown includes provenance (scraped, calculated, estimated) and freshness date
- **Jumuah details**: Friday prayer times, multiple sessions, imam names, khutba languages

### Travel Mode (Musafir / Muqeem)
- **Muqeem mode** (resident): Individual prayer stops, no combining — teal header
- **Musafir mode** (traveler): Prayer combining enabled — indigo header. Dhuhr+Asr and Maghrib+Isha tracked as pairs (Jam' Taqdeem / Ta'kheer)
- **Route-based trip planner**: Set a destination and get a complete prayer itinerary for the entire journey
- **Complete trip itineraries**: 3–5 full plans covering every prayer along the route
- **Pair-aware "have you prayed?" banner**: In Musafir mode asks about pairs, not individual prayers
- **Color-coded mode indicator**: Teal header = Muqeem, Indigo header = Musafir — visible at a glance
- **Segmented flip control**: Switch modes directly from the top bar

### Mosque Discovery
- 2,400+ US/Canada mosques (OpenStreetMap + Hartford Institute + MosqueList)
- No per-request API cost — all pre-indexed in PostGIS
- Real travel times via Mapbox (not straight-line estimates)
- One-tap navigation to Google Maps, Apple Maps, or Waze

---

## Architecture Overview

```
User request → FastAPI → PostGIS query (pre-built mosque DB) → prayer calc → response

Background (continuous): self-improving scraping loop → prayer times + mosque info → DB
One-time seed: OSM + Hartford Institute + MosqueList → 2,400+ mosques
```

No mosque data is fetched live during a user request. Everything is pre-computed and served from the database.

Full architecture details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Self-Improving Scraping Pipeline

Prayer times are scraped from each mosque's website through a 5-tier pipeline that continuously self-improves:

```
Tier 1: IslamicFinder / Aladhan APIs          (zero tokens — fastest)
Tier 2: Static HTML + iframes + custom extractors
Tier 3: Playwright JS rendering + API interception
Tier 4: Claude Vision (images/PDFs with schedule tables)
Tier 5: Astronomical calculation (fallback)
           ↓
Adaptive Extractor (runs after every batch):
  • 7 automated zero-token approaches (JSON-LD, regex, data-attrs, API endpoint detection …)
  • Claude Haiku HTML extractor for sites that defeat automation (batches of 5)
  • New Python functions auto-appended to custom_extractors.py
  • Tier-5-stuck mosques auto-requeued when new extractors are generated
  • Loop exits only when no new extractors can be generated (convergence)
  • Re-run with --fresh to clear cooldowns and retry all stuck domains
```

**Current scrape rate**: ~50% of mosques with websites have real scraped iqama times; 50% fall back to calculated. The self-improving loop continuously raises this floor.

### Run the scraping loop

```bash
cd server

# Start the self-improving loop (batches of 50, runs until convergence)
./run_scraping_loop.sh

# Force-clear stale cooldowns and retry all stuck domains
./run_scraping_loop.sh 50 --fresh

# Monitor in a second terminal
./monitor_scraping.sh watch
./monitor_scraping.sh tail
```

---

## Documentation

| Document | Description |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, tech stack, data flows |
| [docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md) | Full PostgreSQL schema |
| [docs/SCRAPING_PIPELINE.md](docs/SCRAPING_PIPELINE.md) | 5-tier scraping pipeline details |
| [docs/FRONTEND_DESIGN.md](docs/FRONTEND_DESIGN.md) | Mobile-first UI, Leaflet map |
| [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md) | Push notification types and scheduling |
| [docs/TRAVEL_TIME.md](docs/TRAVEL_TIME.md) | Mapbox routing strategy |
| [docs/API_DESIGN.md](docs/API_DESIGN.md) | Full REST API reference |
| [ISLAMIC_PRAYER_RULES.md](ISLAMIC_PRAYER_RULES.md) | Ground truth for all prayer timing logic |
| [MOSQUE_SCRAPING_GUIDE.md](MOSQUE_SCRAPING_GUIDE.md) | Scraping patterns reference |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python FastAPI (async) |
| Database | PostgreSQL 15 + PostGIS |
| Prayer calculation | adhan-python (local, no API) |
| Mosque discovery | Overpass API / OpenStreetMap (pre-indexed) |
| Travel time | Mapbox Directions API |
| Map display | Leaflet.js + OpenStreetMap tiles |
| Frontend | React 18 + TypeScript + Tailwind CSS |
| Scraping (static) | httpx + BeautifulSoup |
| Scraping (JS sites) | Playwright async |
| Scraping (images/PDF) | Claude Vision (Haiku) |
| Push notifications | Firebase Cloud Messaging |
| Containerization | Docker + Docker Compose |

---

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Mapbox API key (travel times and geocoding)
- Anthropic API key (image schedule extraction + adaptive extractor)

### Environment

Copy `.env.example` to `.env` and fill in:

```env
DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/catchaprayer
MAPBOX_API_KEY=sk.eyJ1...
ANTHROPIC_API_KEY=sk-ant-...
FCM_SERVER_KEY=...
```

Edit `client/.env`:
```env
REACT_APP_API_URL=          # leave empty for localhost / ngrok proxy
REACT_APP_GOOGLE_MAPS_API_KEY=...
```

### Run

```bash
docker-compose up --build

# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
# API docs: http://localhost:8000/docs
```

### Seed + Scrape

```bash
# One-time: seed US/Canada mosques
python -m pipeline.seed_mosques
python -m pipeline.seed_from_web_sources

# Run the self-improving scraping loop
./run_scraping_loop.sh
```

---

## API Endpoints

See [docs/API_DESIGN.md](docs/API_DESIGN.md) for full reference.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/api/mosques/nearby` | Find nearby mosques with prayer status |
| GET | `/api/mosques/{id}` | Mosque detail + today's schedule |
| POST | `/api/travel/plan` | Route-based prayer trip plan |
| GET | `/api/mosques/stats` | Database coverage statistics |

---

## Travel Mode — Islamic Rules

The app implements Jam' (prayer combination) rules for travelers per [ISLAMIC_PRAYER_RULES.md](ISLAMIC_PRAYER_RULES.md):

| Mode | Behavior |
|---|---|
| **Muqeem** | Each prayer planned independently in its own time window. No combining. |
| **Musafir** | Dhuhr+Asr and Maghrib+Isha tracked as pairs. Jam' Taqdeem (early) or Ta'kheer (late) combining options shown. |

Key rules: combined window extends to end of second prayer's period (Dhuhr not missed at Asr adhan for Musafir) • Trip planner orders prayers chronologically from departure time • Fajr is always standalone.

---

## Prayer Data Sources

| Source | Label shown to user |
|---|---|
| Scraped from mosque website | "From mosque website" |
| Extracted from schedule image | "From mosque schedule (image)" |
| IslamicFinder database | "From IslamicFinder" |
| Astronomically calculated | "Calculated — verify with mosque" |
| Estimated from typical offset | "Estimated — congregation time not confirmed" |

---

Built for the Muslim community.
