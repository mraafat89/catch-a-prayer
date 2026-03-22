# Data System Design — Catch a Prayer

## North Star

Our database has 100% accurate mosque information for every mosque in the US and Canada. Users trust us because our data is always correct and always fresh.

---

## System Architecture

Three independent subsystems, each with its own schedule and concerns:

```
┌─────────────────────────────────────────────────────┐
│                 1. MOSQUE DISCOVERY                  │
│  "Find every mosque in US/Canada"                   │
│  Sources: Google Places, OSM, community submissions │
│  Frequency: Every 6 months                          │
│  Concerns: Dedup, closed mosques, new mosques       │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              2. STATIC INFO ENRICHMENT              │
│  "Get mosque details that rarely change"            │
│  Data: denomination, women section, wheelchair,     │
│        parking, phone, address, languages           │
│  Sources: Google Places, website scraping, community│
│  Frequency: Every 6 months                          │
│  Concerns: Accuracy, verification                   │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│            3. DYNAMIC PRAYER DATA SCRAPER           │
│  "Get prayer/iqama times that change regularly"     │
│  Data: adhan, iqama, jumuah, taraweeh, eid          │
│  Sources: mosque websites, Mawaqit API              │
│  Frequency: Varies per mosque (see classification)  │
│  Concerns: Speed, accuracy, parallelism, freshness  │
└─────────────────────────────────────────────────────┘
```

---

## 1. Mosque Discovery System

### Goal
Know about every mosque in the US and Canada. Detect new mosques opening and old ones closing.

### Sources (priority order)
1. **Google Places API** — most comprehensive, has business status (open/closed)
2. **OpenStreetMap Overpass** — free, community-maintained
3. **Community submissions** — users report new mosques via the app
4. **Mawaqit directory** — European-focused but growing in NA

### Schedule
- **Full discovery run**: Every 6 months (January 1 + July 1)
- **Community submissions**: Processed daily
- **Closed mosque detection**: Part of the 6-month run (check Google business status)

### Deduplication
- Match by Google Place ID (exact)
- Match by lat/lng proximity (< 300m)
- Match by name similarity (> 60%) + same city

### Community Submission Rules
- Require location (lat/lng) + mosque name
- Rate limit: 5 submissions per user per day
- IP-based rate limit: 3 per IP per day
- Auto-flag if coordinates are outside US/Canada
- Admin review queue for all submissions
- Trust scoring: users with 3+ approved submissions get auto-approved

---

## 2. Static Info Enrichment

### Goal
Every mosque has accurate metadata: denomination, facilities, contact info.

### Data Fields
| Field | Source | Volatility |
|-------|--------|-----------|
| Denomination (Sunni/Shia) | Website scrape, community | Very rare change |
| Women's section | Google Places, community | Rare change |
| Wheelchair accessible | Google Places | Rare change |
| Parking | Google Places | Rare change |
| Phone number | Google Places, website | Occasional change |
| Website URL | Google Places | Occasional change |
| Languages spoken | Website scrape, community | Rare change |
| Capacity | Community | Rare change |

### Schedule
- **Google Places enrichment**: Every 6 months (with discovery)
- **Website scrape for denomination/languages**: Every 6 months
- **Community corrections**: Processed daily via suggestion queue

---

## 3. Dynamic Prayer Data Scraper

### This is the hard problem. Design it carefully.

### Data Fields
| Field | Changes | Scrape Frequency |
|-------|---------|-----------------|
| Adhan times (5 prayers) | Daily (astronomical) | Scrape when available, calculate as fallback |
| Iqama times (5 prayers) | Weekly to seasonal | Based on mosque classification |
| Jumuah khutba time | Rarely | Monthly |
| Jumuah prayer time | Rarely | Monthly |
| Jumuah imam name | Per week | Weekly (if available) |
| Jumuah khutba topic | Per week | Weekly (if available) |
| Jumuah language | Rarely | Monthly |
| Jumuah sessions (1st, 2nd, 3rd) | Rarely | Monthly |
| Taraweeh time | During Ramadan only | Daily during Ramadan |
| Eid prayer sessions + takbeer | 2x per year | Before each Eid |
| Calculation method (ISNA/MWL/etc) | Rarely | Detect once, store |

### Key Insight: Calculated as Fallback, Scraped as Ground Truth

**Calculated adhan times** (from praytimes library) are a good estimate but mosques use different calculation methods (ISNA, MWL, Egyptian, Umm al-Qura) and different Asr calculations (Hanafi vs Shafi'i). The scraped adhan times from a mosque's own website reflect THEIR chosen method — this is the ground truth.

**Strategy:**
- **Scrape BOTH adhan and iqama** when available
- **Fall back to calculated** only when we can't scrape
- **Label the source** so users know: "From mosque website" vs "Estimated"
- When we detect a mosque's calculation method from their website, store it and use it for the calculated fallback

**Iqama times** are set by the mosque imam — the core value we provide that no other app has.

**Jumuah details** go beyond just prayer time:
- Khutba start time
- Prayer start time
- Imam name (if available)
- Khutba topic/series (if available)
- Language (English, Arabic, Urdu, etc.)
- Multiple sessions (1st Jumuah, 2nd Jumuah)

These details make our app uniquely useful for Friday prayers.

### Mosque Classification by Update Frequency

After first successful scrape, classify each mosque:

| Class | Description | Scrape Frequency | Est. Count |
|-------|------------|-----------------|-----------|
| **MONTHLY** | Posts full month schedule (Islamic or Gregorian) | 1st of each month | ~300 |
| **WEEKLY** | Changes iqama weekly (seasonal adjustment) | Every Monday | ~200 |
| **SEASONAL** | Same iqama for months, changes 2-4x/year | Every 2 weeks | ~400 |
| **STATIC** | Never changes iqama (or no iqama posted) | Monthly check | ~600 |
| **MAWAQIT** | Uses Mawaqit platform (API available) | Daily via API (free) | ~130 |
| **UNSCRAPEABLE** | Image/PDF only, JS widget, no website | Never (use calculated) | ~800 |
| **NEW** | Not yet classified | First scrape ASAP | Variable |

Classification happens automatically:
- First scrape: classify as NEW
- After 3+ successful scrapes across different weeks: analyze change pattern
- If iqama times changed between scrapes → WEEKLY
- If same for 4+ weeks → SEASONAL or STATIC
- If site has monthly table → MONTHLY
- If Mawaqit API returns data → MAWAQIT

### Scraper Architecture

```
┌──────────────────────────────────────────────┐
│             SCRAPER ORCHESTRATOR              │
│  Decides WHICH mosques to scrape today       │
│  Based on classification + last scrape date  │
└──────────────────┬───────────────────────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
   ┌─────────────┐  ┌─────────────┐
   │ PLAYWRIGHT  │  │    JINA     │
   │  WORKERS    │  │   WORKERS   │
   │ (5 tabs)    │  │ (10 conc.)  │
   │ JS-heavy    │  │ Static HTML │
   └──────┬──────┘  └──────┬──────┘
          │                │
          ▼                ▼
   ┌─────────────────────────────┐
   │     EXTRACTION ENGINE       │
   │  Regex + prayer context     │
   │  AM/PM inference            │
   │  Monthly table detection    │
   │  AJAX response parsing      │
   └──────────────┬──────────────┘
                  │
                  ▼
   ┌─────────────────────────────┐
   │     VALIDATION ENGINE       │
   │  Islamic logic rules        │
   │  Latitude-aware ranges      │
   │  Iqama gap checks           │
   │  Comparison with calculated │
   └──────────────┬──────────────┘
                  │
                  ▼
   ┌─────────────────────────────┐
   │      DATABASE WRITER        │
   │  Only saves validated data  │
   │  Logs all rejections        │
   │  Updates classification     │
   └─────────────────────────────┘
```

### Parallelism

The scraper MUST be concurrent:

```python
# Playwright: 5 concurrent browser tabs
# Each tab handles one mosque site
async with async_playwright() as pw:
    browser = await pw.chromium.launch()
    sem = asyncio.Semaphore(5)
    tasks = [scrape_one(browser, sem, mosque) for mosque in batch]
    results = await asyncio.gather(*tasks)

# Jina: 10 concurrent HTTP requests
# Rate-limited to avoid 429s
jina_sem = asyncio.Semaphore(10)
```

Target: **500 sites in 15 minutes** (vs current 1.5 hours)

### Separation from API Server

The scraper should NOT run inside the API container:
- Option A: Separate Docker container with its own Chromium
- Option B: Cron runs `docker exec` but with resource limits (`--memory 1g --cpus 1`)
- Option C: Separate lightweight VPS for scraping only

For now, Option B is simplest — run in the API container but with concurrency and resource awareness.

### Daily Schedule

```
12:30 AM  Calculate adhan times for all mosques (praytimes library)
 1:00 AM  Scrape MAWAQIT class mosques (API, fast, ~2 min)
 1:05 AM  Scrape MONTHLY class if 1st of Islamic month (~5 min)
 1:15 AM  Scrape WEEKLY class if Monday (~10 min)
 1:30 AM  Scrape DAILY class mosques (~10 min)
 2:00 AM  Scrape NEW/unclassified mosques (~15 min)
 2:30 AM  Re-scrape any failed from above (~10 min)
 3:00 AM  Validation audit + cleanup
 4:00 AM  Database backup
```

Total scraping window: ~2.5 hours, all concurrent.

### Accuracy Guarantee

Every piece of data goes through:

1. **Extraction validation** — does the extracted text look like a prayer time?
2. **Islamic logic validation** — is the time within the valid range for this prayer?
3. **Chronological validation** — fajr < sunrise < dhuhr < asr < maghrib < isha?
4. **Iqama validation** — is iqama after adhan and before next prayer?
5. **Comparison validation** — does it deviate > 60min from calculated?
6. **Historical validation** — did iqama suddenly jump by > 30min from yesterday?

If ANY check fails:
- Adhan: use calculated (always available)
- Iqama: use last known good value, or null
- **Never store data you know is wrong**

### Handling Unscrapeable Mosques (~800)

For mosques we can't scrape (image schedules, no website, JS-only):
- Show calculated adhan times (always accurate)
- Show "Iqama times not available — help us by submitting times"
- Community submission button in the app
- These mosques get classified as UNSCRAPEABLE and are never re-scraped

---

## Database Schema Changes Needed

```sql
-- Add classification to scraping_jobs
ALTER TABLE scraping_jobs ADD COLUMN IF NOT EXISTS
    scrape_class TEXT DEFAULT 'new';
    -- Values: monthly, weekly, seasonal, static, mawaqit, unscrapeable, new

ALTER TABLE scraping_jobs ADD COLUMN IF NOT EXISTS
    next_scrape_date DATE;

ALTER TABLE scraping_jobs ADD COLUMN IF NOT EXISTS
    consecutive_failures INT DEFAULT 0;

ALTER TABLE scraping_jobs ADD COLUMN IF NOT EXISTS
    last_iqama_change DATE;  -- When iqama times last changed
```

---

## Migration Plan

1. Add classification column to scraping_jobs
2. Classify all mosques based on existing scrape history
3. Implement concurrent Playwright (5 tabs)
4. Implement orchestrator (decides what to scrape today)
5. Replace current sequential scraper with new concurrent one
6. Set up daily cron with the new schedule
7. Monitor for 1 week, adjust classification thresholds
8. Remove old sequential scraper code

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Real prayer data % | 39% | 50%+ within 1 month |
| Data freshness (avg age) | 3-7 days | < 1 day for daily, < 7 for weekly |
| Scrape time (full daily run) | 1.5 hours | < 30 minutes |
| Validation pass rate | 100% | 100% (non-negotiable) |
| Iqama accuracy | Unknown | Verified by community |
| Scraper uptime | Manual | Automated daily, monitored |
