# Catch a Prayer

Find nearby mosques and never miss a prayer again. Shows whether you can catch a prayer with the Imam, pray solo, or need to find a nearby clean location — with real travel times and full source transparency.

Designed for US and Canada. Mobile-first.

---

## Features

- **Mosque Discovery**: Finds mosques near your location using OpenStreetMap data (pre-indexed, no per-request API cost)
- **Both Adhan and Iqama times**: Scraped from each mosque's own website — not just calculated
- **5-level prayer catching status**: With Imam / Imam in progress / Solo at mosque / Pray nearby / Missed — make up
- **Source transparency**: Every time shown includes where it came from (scraped, calculated, or estimated) and how fresh it is
- **Jumuah details**: Friday prayer times, imam names, khutba topics, languages, multiple sessions
- **Travel Mode**: Route-based prayer combination recommendations (Dhuhr+Asr, Maghrib+Isha) for travelers
- **Push notifications**: Configurable reminders — pre-adhan, pre-iqama, leave-now alerts, Jumuah reminders
- **Real travel times**: Mapbox routing with live traffic (not straight-line estimates)
- **Navigation**: One tap to open directions in Google Maps, Apple Maps, or Waze — no API required
- **Timezone-aware**: Correct calculations when user and mosque are in different timezones
- **Mobile-first PWA**: Works on any phone browser, installable without app store

---

## Architecture Overview

```
User request → FastAPI → PostGIS query (pre-built mosque DB) → prayer calc → response

Background (nightly): OSM mosque sync → website scraping → Vision AI for images → DB
```

No mosque data is fetched live during a user request. Everything is pre-computed and served from the database.

Full architecture details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Documentation

| Document | Description |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, tech stack, data flows |
| [docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md) | Full PostgreSQL schema with all tables |
| [docs/SCRAPING_PIPELINE.md](docs/SCRAPING_PIPELINE.md) | Offline scraping pipeline — all 5 tiers |
| [docs/FRONTEND_DESIGN.md](docs/FRONTEND_DESIGN.md) | Mobile-first UI, Leaflet map, navigation |
| [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md) | Push notification types, scheduling, PWA |
| [docs/TRAVEL_TIME.md](docs/TRAVEL_TIME.md) | Mapbox routing strategy and cost analysis |
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
| Travel time | Mapbox Directions + Matrix API |
| Map display | Leaflet.js + OpenStreetMap tiles (free) |
| Frontend | React 18 + TypeScript + Tailwind CSS |
| Scraping (static) | httpx + BeautifulSoup |
| Scraping (JS sites) | Playwright async |
| Scraping (images) | Claude Vision API |
| Push notifications | Firebase Cloud Messaging (FCM) |
| Containerization | Docker + Docker Compose |

---

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Mapbox API key (for travel times)
- Anthropic API key (for image-based schedule extraction)

### Environment Setup

```bash
# Copy the example env files
cp .env.example .env
cp server/.env.example server/.env
cp client/.env.example client/.env
```

Edit `server/.env`:
```env
DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/catchaprayer
MAPBOX_API_KEY=sk.eyJ1...
ANTHROPIC_API_KEY=sk-ant-...
FCM_SERVER_KEY=...
```

Edit `client/.env`:
```env
VITE_API_URL=http://localhost:8000
VITE_MAPBOX_TOKEN=pk.eyJ1...
VITE_VAPID_PUBLIC_KEY=...
```

### Run

```bash
docker-compose up --build

# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
# API docs: http://localhost:8000/docs
```

### Seed the Mosque Database

```bash
# One-time: download all US/Canada mosques from OpenStreetMap
docker-compose exec api python -m pipeline.seed_mosques

# One-time: enrich with website/phone from Google Places (optional)
docker-compose exec api python -m pipeline.enrich_from_places

# Start the nightly scraping pipeline (for development: run once manually)
docker-compose exec api python -m pipeline.run_scraping
```

---

## API Endpoints

See [docs/API_DESIGN.md](docs/API_DESIGN.md) for full reference.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/api/mosques/nearby` | Find nearby mosques with prayer status |
| GET | `/api/mosques/{id}` | Mosque detail + full schedule |
| GET | `/api/mosques/{id}/schedule` | Monthly prayer schedule |
| POST | `/api/notifications/subscribe` | Register push notifications |
| PUT | `/api/notifications/subscribe/{id}` | Update preferences |
| DELETE | `/api/notifications/subscribe/{id}` | Unsubscribe |
| GET | `/api/settings` | Default settings |

---

## User Settings

- Search radius (1–50 km)
- Travel buffer (minutes added to travel time for parking/walking)
- Travel Mode (enables prayer combination options for travelers)
- Congregation window (how long after iqama a congregation is still joinable, default 15 min)
- Per-prayer notification preferences (timing, enable/disable, quiet hours)

---

## Prayer Data Sources

The app is fully transparent about where every prayer time comes from:

| Source | Label shown to user |
|---|---|
| Scraped from mosque website | "From mosque website" |
| Extracted from schedule image | "From mosque schedule (image)" |
| IslamicFinder database | "From IslamicFinder" |
| Community submitted | "Community-submitted" |
| Astronomically calculated | "Calculated — verify with mosque" |
| Estimated from typical offset | "Estimated — congregation time not confirmed" |

---

Built for the Muslim community.
