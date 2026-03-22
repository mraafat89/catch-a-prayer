# Mosque Discovery System — Design

## Goal

Know about every mosque in the US and Canada. Detect new mosques opening, old ones closing, and keep basic info current.

---

## Current Implementation

### What exists
- `pipeline/discover_mosques.py` — Google Places grid search with 262 hardcoded city circles
- `pipeline/enrich_from_google.py` — Google Place Details enrichment (website, phone, address, wheelchair)
- `pipeline/full_discovery.py` — Orchestrator that runs Google + OSM + Mawaqit in sequence
- Cron: runs every 6 months (Jan 1 + Jul 1)

### How it works today
1. **Google Places**: 262 search circles across US/Canada metros, 25-50km radius each. Returns name, lat/lng, address, place_id. Cost: ~$50 per run.
2. **Google Place Details**: For mosques with google_place_id but no website/phone. Returns website, phone, formatted address, wheelchair. Cost: ~$15 per run.
3. **OpenStreetMap**: Overpass API query for all `amenity=place_of_worship + religion=muslim` in US/Canada bounding box. Free.
4. **Mawaqit**: Search by city name for 40 major cities. Free but thin US coverage (~130 mosques).

### Deduplication
- By Google Place ID (exact match)
- By lat/lng proximity (< 300m)
- By OSM ID (exact match)

### Problems with current design
1. **Hardcoded city list** — misses smaller cities, rural areas, new suburbs
2. **No closed mosque detection** — we never remove mosques that shut down
3. **No data source tracking** — can't tell where a mosque record came from
4. **Community submissions exist** (suggestions API) but not integrated into discovery
5. **No cross-source validation** — if Google says a mosque exists but OSM doesn't, we don't flag it
6. **Enrichment is separate from discovery** — should be one pipeline
7. **No incremental updates** — full re-run every 6 months, nothing in between

---

## Redesigned System

### Sources (in priority order)

| Source | Data Quality | Cost | Coverage | Frequency |
|--------|-------------|------|----------|-----------|
| **Google Places** | High (verified businesses) | ~$50/run | Best for US/Canada | Every 6 months |
| **OpenStreetMap** | Medium (community-edited) | Free | Good, growing | Every 6 months |
| **Mawaqit API** | High (mosque-managed) | Free | Thin in US (~130) | Monthly check |
| **TheMasjidApp** | High (120k+ mosques) | Free (open API) | Good | Monthly check |
| **Community submissions** | Variable (needs verification) | Free | Fills gaps | Continuous |
| **IslamicFinder directory** | Medium | Free (scrape) | Large but stale | Yearly |

### Discovery Pipeline

```
┌─────────────────────────────────────────────┐
│           DISCOVERY ORCHESTRATOR            │
│  Runs every 6 months (full) + continuous    │
│  (community submissions)                    │
└──────────────────┬──────────────────────────┘
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
┌─────────┐  ┌─────────┐  ┌─────────┐
│ Google  │  │   OSM   │  │  TMA /  │
│ Places  │  │Overpass │  │ Mawaqit │
└────┬────┘  └────┬────┘  └────┬────┘
     │            │            │
     └─────────┬──┘────────────┘
               ▼
┌──────────────────────────────────┐
│        DEDUPLICATION ENGINE      │
│  1. Google Place ID match        │
│  2. OSM ID match                 │
│  3. Lat/lng proximity (< 300m)   │
│  4. Name similarity (> 60%)      │
│     + same city                  │
└──────────────┬───────────────────┘
               ▼
┌──────────────────────────────────┐
│         ENRICHMENT               │
│  Google Place Details:           │
│  - website, phone, address       │
│  - wheelchair, business status   │
│  - opening hours                 │
│  Assigns: state, timezone,       │
│  country from coordinates        │
└──────────────┬───────────────────┘
               ▼
┌──────────────────────────────────┐
│        VALIDATION & SAVE         │
│  - Coordinates within US/Canada  │
│  - Name is not empty/generic     │
│  - Not a duplicate               │
│  - Creates scraping_job entry    │
│  - Runs alive check on website   │
└──────────────────────────────────┘
```

### Closed Mosque Detection

During the 6-month full run:
1. **Google business status**: Check `business_status` field — if "CLOSED_PERMANENTLY", mark `is_active = false`
2. **Website check**: If website returns 404/DNS failure for 2 consecutive runs, flag for review
3. **No data for 6+ months**: If we can't get any prayer data for 6 months and community hasn't verified, flag as potentially closed

Don't auto-delete — flag for admin review. Mosques can temporarily close for renovation.

### Community Submissions

Already implemented via `app/api/suggestions.py`:
- Submit corrections for existing mosques (iqama times, facilities, phone)
- Vote-based acceptance (net +2 for iqama, +3 for facilities)
- Rate limiting per session and IP

**Missing for discovery:**
- "Add new mosque" endpoint (not just corrections to existing)
- Require: name, lat/lng (from map pin), and at least one of: address, website, phone
- Auto-check: is there already a mosque within 300m?
- Trust scoring: users with 3+ approved submissions skip the queue

### Data Source Tracking

Every mosque should track where its data came from:

```sql
-- Already exists
google_place_id     -- from Google Places
osm_id              -- from OpenStreetMap

-- Should add
source              -- 'google_places', 'osm', 'mawaqit', 'themasjidapp', 'community', 'seed'
discovered_at       -- when first added
last_verified_at    -- last time ANY source confirmed it exists
verification_count  -- how many sources agree it exists (higher = more confident)
```

A mosque confirmed by Google Places + OSM + community = high confidence.
A mosque only from one community submission = needs verification.

### State & Timezone Assignment

Currently done ad-hoc with manual SQL. Should be automatic:
- On insert: derive state from lat/lng using a state boundary lookup
- On insert: derive timezone from state (or from lat/lng for border cases)
- On insert: derive country from lat/lng (US vs Canada boundary at ~49°N, with exceptions)

### Incremental Updates Between Full Runs

Between the 6-month full discovery runs:
1. **Community submissions** — processed daily
2. **New scraping_jobs created** — when a mosque gets a website for the first time
3. **TheMasjidApp check** — monthly, search our mosque locations on TMA for new listings
4. **Mawaqit check** — monthly, search for new US/Canada mosques

---

## Implementation Plan

### Phase 1: Fix Current System (quick wins)
- [ ] Auto-assign state + timezone on mosque insert (no more manual SQL)
- [ ] Add `source` and `discovered_at` columns to mosques table
- [ ] Integrate TheMasjidApp as a discovery source in full_discovery.py
- [ ] Add closed mosque detection (Google business status check)

### Phase 2: Community Discovery
- [ ] "Add new mosque" API endpoint
- [ ] Trust scoring for submitters
- [ ] Admin review queue for new mosque submissions (already exists for corrections)

### Phase 3: Smarter Grid Search
- [ ] Replace hardcoded 262 circles with population-density-based grid
- [ ] Focus additional circles on areas where users search but few mosques exist (coverage gaps from request_logs)
- [ ] Skip circles that found 0 new mosques last run

---

## Cost Budget

| Item | Per Run | Frequency | Annual Cost |
|------|---------|-----------|------------|
| Google Places Nearby Search | ~$50 | 2x/year | $100 |
| Google Place Details | ~$15 | 2x/year | $30 |
| OpenStreetMap | Free | 2x/year | $0 |
| TheMasjidApp | Free | 12x/year | $0 |
| Mawaqit | Free | 12x/year | $0 |
| **Total** | | | **~$130/year** |
