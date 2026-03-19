# Data Strategy — Catch a Prayer

## The Problem

2,448 mosques in our database. Prayer time data quality:

| Category | Count | % | Current Source |
|----------|-------|---|----------------|
| Has website with prayer times | ~400 | 16% | Scraper can extract |
| Has website, no prayer times on site | ~300 | 12% | Site exists but no schedule posted |
| Has website, site is dead | ~300 | 12% | Website down/expired |
| No website at all | ~1,400 | 57% | No URL in database |
| **Using calculated fallback** | **~2,400** | **~99%** | praytimes library (estimated) |

## The Solution: 4 Data Sources

```
                    ┌─────────────────────┐
                    │   Prayer Schedules   │
                    │      Database        │
                    └──────────▲──────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    ┌──────┴──────┐    ┌──────┴──────┐    ┌──────┴──────┐
    │  Source 1:   │    │  Source 2:   │    │  Source 3:   │
    │  Smart       │    │  Community   │    │  API         │
    │  Scraper     │    │  Submissions │    │  Partners    │
    └─────────────┘    └─────────────┘    └─────────────┘
           │                   │                   │
    ~400 mosques        User-submitted       IslamicFinder
    (websites)          (in-app form)        Aladhan, etc.
                               │
                        ┌──────┴──────┐
                        │  Source 4:   │
                        │  Calculated  │
                        │  (fallback)  │
                        └─────────────┘
                        ~1,400 mosques
                        (no other source)
```

---

## Source 1: Smart Scraper

**For mosques WITH working websites (~700 mosques)**

### Mosque Classification

Before scraping, classify each mosque website:

| Class | Description | Method | Count (est.) |
|-------|-------------|--------|-------------|
| `widget_masjidal` | Uses Masjidal/AthanPlus iframe widget | Fetch iframe URL directly | ~100 |
| `widget_masjidnow` | Uses MasjidNow widget | Fetch MasjidNow API | ~50 |
| `widget_islamicfinder` | Uses IslamicFinder widget | Fetch IF API | ~30 |
| `html_homepage` | Prayer times in homepage HTML/text | Jina + Claude | ~100 |
| `html_subpage` | Prayer times on /prayer-times or similar | Jina/Playwright + Claude | ~50 |
| `js_rendered` | Prayer times loaded via JavaScript | Playwright + Claude | ~50 |
| `pdf_schedule` | Monthly PDF schedule linked on site | Download PDF + Claude | ~20 |
| `image_schedule` | Prayer times as an image | Screenshot + Claude Vision | ~20 |
| `no_schedule` | Website exists but no prayer info | Skip | ~200 |
| `site_dead` | Website unreachable | Skip | ~300 |

### Scrape Method Storage

Add to `scraping_jobs` table:

```sql
ALTER TABLE scraping_jobs ADD COLUMN website_class VARCHAR(30);
-- widget_masjidal, widget_masjidnow, html_homepage, js_rendered, etc.

ALTER TABLE scraping_jobs ADD COLUMN extraction_url TEXT;
-- The specific URL/API endpoint that worked (e.g., Masjidal iframe URL)

ALTER TABLE scraping_jobs ADD COLUMN website_alive BOOLEAN DEFAULT true;
ALTER TABLE scraping_jobs ADD COLUMN website_last_checked TIMESTAMP;
```

### Periodic Update Strategy

Once a mosque is classified, periodic updates use the known-working method:

```
1. widget_masjidal  → Fetch Masjidal API directly (0.5s, free)
2. widget_masjidnow → Fetch MasjidNow API directly (0.5s, free)
3. html_homepage    → Jina + Claude Haiku (3s, $0.003)
4. js_rendered      → Playwright + Claude (8s, $0.003)
5. no_schedule      → Skip (re-classify monthly in case site added schedule)
6. site_dead        → Skip (re-check monthly)
```

**Cost for periodic updates:**
- Widget mosques (~180): Free (direct API)
- Scraper mosques (~200): ~$0.60 per run
- Total weekly cost: ~$0.60
- Total monthly cost: ~$2.50

---

## Source 2: Community Submissions (NEW — Most Important)

**For mosques WITHOUT websites or with bad data (~1,400+ mosques)**

### In-App Submission Flow

Users at a mosque can submit/update prayer times directly:

```
User opens app → sees mosque card →
  "Help improve this mosque's data" button →
    Simple form:
      ┌─────────────────────────────────┐
      │ Submit Prayer Times             │
      │                                 │
      │ Fajr:    Adhan [__:__] Iqama [__:__] │
      │ Dhuhr:   Adhan [__:__] Iqama [__:__] │
      │ Asr:     Adhan [__:__] Iqama [__:__] │
      │ Maghrib: Adhan [__:__] Iqama [__:__] │
      │ Isha:    Adhan [__:__] Iqama [__:__] │
      │                                 │
      │ Jumuah:                         │
      │   Khutbah [__:__] Prayer [__:__]│
      │   + Add another session         │
      │                                 │
      │ □ Women's section available     │
      │ □ Wheelchair accessible         │
      │ □ Parking available             │
      │                                 │
      │ [Submit]                        │
      └─────────────────────────────────┘
```

### Submission Validation

- Times must be in valid ranges (Fajr 3:30-7:30, etc.)
- Iqama must be after Adhan
- Compare with calculated times (flag if >30 min off)
- Require at least 3 prayers (partial submissions OK)
- Rate limit: 1 submission per mosque per user per day

### Trust & Verification

Submissions are NOT trusted by default:

| Confidence Level | Rule | Source Label |
|-----------------|------|-------------|
| `high` | 3+ users submitted same times (within 5 min) | `community_verified` |
| `medium` | 1-2 users submitted, times match calculated ±15 min | `community_submitted` |
| `low` | 1 user submitted, times differ significantly from calculated | `community_unverified` |
| `overridden` | Mosque admin confirmed (future feature) | `mosque_admin` |

### Database Schema

```sql
CREATE TABLE community_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mosque_id UUID REFERENCES mosques(id),
    session_id VARCHAR(64) NOT NULL,  -- device session (anonymous)

    -- Prayer times
    fajr_adhan VARCHAR(5),
    fajr_iqama VARCHAR(5),
    dhuhr_adhan VARCHAR(5),
    dhuhr_iqama VARCHAR(5),
    asr_adhan VARCHAR(5),
    asr_iqama VARCHAR(5),
    maghrib_adhan VARCHAR(5),
    maghrib_iqama VARCHAR(5),
    isha_adhan VARCHAR(5),
    isha_iqama VARCHAR(5),

    -- Jumuah
    jumuah_khutbah_1 VARCHAR(5),
    jumuah_prayer_1 VARCHAR(5),
    jumuah_khutbah_2 VARCHAR(5),
    jumuah_prayer_2 VARCHAR(5),

    -- Enrichment
    has_womens_section BOOLEAN,
    wheelchair_accessible BOOLEAN,
    has_parking BOOLEAN,

    -- Meta
    confidence VARCHAR(20) DEFAULT 'unverified',
    submitted_at TIMESTAMP DEFAULT now(),
    ip_hash VARCHAR(64),  -- hashed for rate limiting, not tracking
    user_lat FLOAT,  -- to verify they're near the mosque
    user_lng FLOAT
);
```

### Promotion to Official Data

A cron job runs daily:
1. Group submissions by mosque_id for the current date
2. If 3+ submissions agree (within 5 min per prayer): promote to `prayer_schedules` with `community_verified` source
3. If 1-2 submissions match calculated ±15 min: promote with `community_submitted` source
4. If only 1 submission with large deviation: keep as `community_unverified`, don't promote

---

## Source 3: API Partners

**Bulk data from prayer time services**

| Service | Data Available | Cost | Coverage |
|---------|---------------|------|----------|
| IslamicFinder API | Adhan times (calculated, not mosque-specific) | Free tier | Global |
| Aladhan API | Calculated times by location | Free | Global |
| Masjidal API | Real iqama times for registered mosques | Free (if they allow) | ~500 US mosques |
| MasjidNow API | Real iqama times | Free | ~300 US mosques |

**Strategy**: Use Masjidal/MasjidNow APIs as primary source for mosques registered on those platforms. IslamicFinder/Aladhan as fallback for calculated times (better than our own calculation since they may have regional method preferences).

---

## Source 4: Calculated Fallback

**Last resort — for mosques with no other data source**

- Uses praytimes library (ISNA method for North America)
- Iqama estimated with fixed offsets (Fajr +20, Dhuhr +15, Asr +10, Maghrib +5, Isha +15)
- Clearly labeled as `calculated` in the UI (transparency badge)
- Users see "Estimated times — help improve by submitting real times"

---

## Data Quality Dashboard

Track these metrics:

| Metric | Target | Current |
|--------|--------|---------|
| Mosques with real iqama times | >50% | ~1% |
| Mosques with jumuah info | >30% | ~1% |
| Mosques with women's section info | >20% | ~0% |
| Average data age (days since last update) | <7 | N/A |
| Community submissions per week | >50 | 0 |
| Scraper success rate (on working sites) | >80% | ~70% |

---

## Implementation Priority

### Phase 1: Smart Scraper (Current — Week 1-2)
- [x] Build Jina + Playwright + Claude pipeline
- [x] Iframe widget detection (Masjidal)
- [ ] Save results to DB with correct source labels
- [ ] Classify mosque websites (widget type, alive/dead)
- [ ] Record extraction method per mosque
- [ ] Run on all ~1,000 websites
- [ ] Set up periodic update cron

### Phase 2: Community Submissions (Week 3-4)
- [ ] Create `community_submissions` table + API endpoint
- [ ] Build submission form in the app (MosqueDetailSheet)
- [ ] Validation logic (time ranges, iqama after adhan)
- [ ] Daily promotion cron (submissions → prayer_schedules)
- [ ] "Help improve this data" prompt on calculated-data mosques

### Phase 3: API Partners (Week 5-6)
- [ ] Integrate Masjidal API for bulk iqama times
- [ ] Integrate MasjidNow API
- [ ] Map our mosque IDs to partner mosque IDs (name + location matching)
- [ ] Periodic sync job

### Phase 4: Quality & Monitoring (Ongoing)
- [ ] Data quality dashboard
- [ ] Alert when scraper success rate drops
- [ ] Alert when community submissions spike (possible spam)
- [ ] Monthly re-check of dead websites
- [ ] Monthly re-classify websites that had no schedule (they might add one)
