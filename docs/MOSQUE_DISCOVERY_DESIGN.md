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

### State & Timezone Assignment — IMPLEMENTED

`pipeline/geo_utils.py` handles this automatically on every insert:
1. **Parse from Google formatted_address** (most accurate): extracts state code before ZIP/postal code
2. **Parse from OSM addr:state** tag
3. **Coordinate bounding box fallback** with reference-point tiebreaker for border overlaps
4. **Timezone derived from state** via mapping table

Called via `enrich_mosque_geo(lat, lng, address=...)`.
Backfill runs during full discovery for mosques missing state/timezone.

### Deduplication — IMPLEMENTED

When a discovery source finds a mosque that already exists in our DB:
- **DO NOT skip it** — update the existing record with any new data
- `COALESCE(phone, :phone)` — fills gaps without overwriting
- Increment `verification_count` (more sources = higher confidence)
- Update `last_verified_at` timestamp
- Fill missing address, phone, google_place_id

### Closed Mosque Detection — IMPLEMENTED

During full discovery runs:
1. Mosques with `consecutive_failures >= 3` and dead websites → deactivated
2. Mosques with hijacked/spam websites and no recent prayer data → deactivated
3. Don't auto-delete — set `is_active = false` (can be reactivated)

First run deactivated 34 hijacked/dead mosques.

### Incremental Updates Between Full Runs

Between the 6-month full discovery runs:
1. **Community submissions** — processed daily
2. **New scraping_jobs created** — when a mosque gets a website for the first time
3. **TheMasjidApp check** — monthly, search our mosque locations on TMA for new listings
4. **Mawaqit check** — monthly, search for new US/Canada mosques

---

## Implementation Status

### Phase 1: Fix Current System — DONE
- [x] Auto-assign state + timezone on mosque insert (`geo_utils.py`)
- [x] Add `source` and `discovered_at` columns to mosques table
- [x] Integrate TheMasjidApp as a discovery source in `full_discovery.py`
- [x] Add closed mosque detection (dead websites + hijacked domains)
- [x] Dedup updates existing records instead of skipping
- [x] Geo backfill for existing mosques missing state/timezone
- [x] `is_valid_mosque_data()` rejects records without name/coordinates

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
| Google Places Nearby Search | ~$3-20 | 2x/year | ~$40 |
| Google Place Details enrichment | ~$15 | 2x/year | ~$30 |
| OpenStreetMap | Free | 2x/year | $0 |
| TheMasjidApp | Free | 12x/year | $0 |
| Mawaqit | Free | 12x/year | $0 |
| **Total** | | | **~$70/year** |

Note: Google gives $200/month free credit, so all Google API costs are effectively **$0** as long as we stay under that monthly cap. Our full discovery run uses ~$20-35 total — well within the free tier.
