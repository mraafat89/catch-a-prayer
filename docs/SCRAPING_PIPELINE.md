# Scraping Pipeline Design

The scraping pipeline is a background process that runs independently of user requests. Users always read from the database — scraping never happens at request time.

---

## Core Principle

```
Request time:  read from DB only  (fast, <50ms)
Background:    scrape → normalize → store in DB  (slow, offline, doesn't affect users)
```

---

## Pipeline Schedule

| Job | Schedule | Description |
|---|---|---|
| Full mosque scrape | Nightly 2 AM (staggered by timezone) | Update prayer/iqama times for all mosques |
| Jumuah scrape | Thursday 9 PM local | Re-scrape Friday-specific details for upcoming week |
| Mosque DB seed | Weekly Sunday | Pull new/updated mosques from OSM |
| **Deduplication** | **After every seed run** | **Merge duplicate mosque entries** |
| Places enrichment | On new mosque insert | Get website/phone from Google Places (one-time per mosque) |
| Mosque info enrichment | On new insert + monthly | Scrape denomination, languages, facilities from mosque website |
| Failed retry | Every 6 hours | Retry recently-failed scraping jobs |
| Notification send | At each prayer time | FCM push for registered users |

---

## Mosque Deduplication

### Why Duplicates Occur

OpenStreetMap allows the same physical mosque to be tagged multiple times:
- As a **node** (a single point) AND a **way** (the building outline) — most common
- Once in the `religion=muslim` query and again in the `name~masjid` query (caught by OSM ID deduplication during seeding)
- Rarely: two different contributors adding the same mosque under slightly different names

### Detection Algorithm

Two mosques are considered duplicates if **both** conditions are met:

1. **Spatial proximity** — within 50 meters of each other (PostGIS `ST_DWithin`)
2. **Name match** — one of:
   - Names are identical (exact match)
   - One name is "Unknown Mosque" (always defer to the named entry)
   - pg_trgm similarity score ≥ 0.6 (catches abbreviations, typos, word order differences)

Pairs between 50–200m with high name similarity (≥ 0.85) are also flagged for manual review but not auto-merged.

### Merge Strategy

When a duplicate pair is detected, keep the **winner** and delete the **loser**:

**Winner selection** (first rule that applies):
1. Named mosque beats "Unknown Mosque"
2. Mosque with more non-null fields (name, website, phone, address, city, state)
3. Mosque with a website beats one without
4. Older record (lower `created_at`) wins as tiebreaker

**Field merge before deletion** — before deleting the loser, copy any non-null fields the winner is missing:
```
winner.website   = winner.website   OR loser.website
winner.phone     = winner.phone     OR loser.phone
winner.address   = winner.address   OR loser.address
winner.city      = winner.city      OR loser.city
winner.state     = winner.state     OR loser.state
winner.email     = winner.email     OR loser.email
```

The winner's scraping job is kept. The loser's scraping job is deleted (CASCADE).

### Implementation

Script: `pipeline/deduplicate_mosques.py`

```
Usage:
  python -m pipeline.deduplicate_mosques           # auto-merge confirmed duplicates
  python -m pipeline.deduplicate_mosques --dry-run  # preview only, no changes
  python -m pipeline.deduplicate_mosques --review   # also show borderline pairs
```

Called automatically at the end of `seed_mosques.py`.

### Thresholds (tuned from data)

| Distance | Name match | Action |
|---|---|---|
| ≤ 50m | Identical or one is "Unknown Mosque" | Auto-merge |
| ≤ 50m | pg_trgm similarity ≥ 0.6 | Auto-merge |
| 50–200m | pg_trgm similarity ≥ 0.85 | Log as borderline (manual review) |
| > 200m | Any | Keep both — different mosques |

These thresholds were validated against 45 near-pairs found in the initial US+Canada seed of 1,500 mosques: 36 pairs within 50m, all confirmed duplicates upon inspection.

---

## Mosque Info Enrichment

This section covers scraping mosque metadata (denomination, facilities, languages) from the mosque website — separate from prayer time scraping, runs once after initial seeding and on a monthly refresh.

### What to Extract

- `denomination`: sunni / shia / ismaili / ahmadiyya / sufi / other (stored lowercase)
- `languages_spoken`: list of languages mentioned (English, Arabic, Urdu, Turkish, French, Somali, Bengali, etc.)
- `has_womens_section`: boolean — detected from mentions of "sisters", "women's section", "musalla for sisters"
- `has_parking`: boolean — detected from parking mentions

### Where to Look

1. Homepage — About section, footer, mission statement
2. `/about`, `/about-us` page
3. Homepage meta description and page title

### Detection Method — Keyword Scoring

Denomination keywords (check full page text, case-insensitive):

```
sunni:      sunni, ahl al-sunnah, ahlus sunnah, hanafi, shafi, maliki, hanbali,
            deobandi, barelvi, salafi, wahhabi
shia:       shia, shi'a, shi'ite, shite, imami, ithna ashari, 12ver,
            ja'fari, jafari, hussainiyya, hussainia
ismaili:    ismaili, isma'ili, jamatkhana, imamat
ahmadiyya:  ahmadiyya, ahmadi, qadiani
sufi:       sufi, tariqa, naqshbandi, qadiri, chishti, zawiya
```

Rules:
- If ≥1 shia keyword found → denomination = "shia"
- If ≥1 ismaili keyword found → denomination = "ismaili"
- If ≥1 ahmadiyya keyword found → denomination = "ahmadiyya"
- If ≥1 sunni keyword found (AND no shia/ismaili) → denomination = "sunni"
- If no keywords found → denomination = NULL (not "sunni" by default — never assume)
- If conflicting signals → denomination = NULL (don't guess)

**Why not default to "sunni"**: The majority of mosques are Sunni but we never assume — showing wrong denomination is worse than showing none. Users who care will see NULL as "unconfirmed" rather than incorrect.

### Language Detection

Scan About page and homepage for language mentions. Also check if site has language switcher or Arabic/Urdu content sections.

### Storage

- Updates `mosques.denomination`, `mosques.languages_spoken`, `mosques.has_womens_section`
- Recorded in `scraping_jobs.raw_extracted_json` under key `"info_enrichment"`
- `denomination_source`: `"website_scraped"` | `"osm"` | `"user_submitted"` | null
- Only overwrites OSM denomination if website scrape produces a confident result (≥2 keyword hits or Ismaili/Shia/Ahmadiyya with ≥1 hit since those are distinctive)

**Schedule:** Runs once on new mosque insert (after prayer time scraping). Monthly refresh to catch newly-added About pages. Script: `pipeline/enrich_mosque_info.py`

---

## Scraping Tiers

Tiers are attempted in order. The pipeline stops at the first tier that produces valid, complete data. The tier that produced the data is always recorded.

### Tier 1 — Structured Source Lookup

**What**: Query known aggregated databases that already have mosque-specific prayer times.

**Sources**:
- IslamicFinder mosque database (check API/licensing)
- Aladhan.com mosque database
- Salah.com / MasjidAl.com if accessible

**How**:
1. Search by mosque name + city (fuzzy match, score ≥ 0.85 required)
2. Validate coordinates match (within 500m of our mosque record)
3. If match: extract both adhan and iqama times for all 5 prayers
4. Store with `source = 'islamicfinder'` and `confidence = 'high'`

**Expected hit rate**: ~30–40% of major US/Canada mosques

**When to use Tier 1 result**: Only if match confidence is high AND times pass sanity checks (see Validation section).

**Skip condition**: Tier 1 is skipped entirely for mosques that have a website URL. IslamicFinder only provides city-level adhan times without iqama, so for mosques with a known website we go directly to Tier 2 where mosque-specific iqama times can be found.

---

### Tier 2 — Static HTML Scraping

**What**: Fetch the mosque website with httpx, parse with BeautifulSoup.

**How**:

```
1. Fetch homepage
2. Run all extraction methods in parallel:
   a. Table extraction (HTML <table> elements with prayer-related headers)
   b. Structured div extraction (divs/sections with prayer class names)
   c. JSON-LD structured data (schema.org/Event)
   d. Text pattern matching (regex on full page text)
3. If homepage yields <3 prayers: discover sub-pages
   - Check <a> tags for prayer-related link text or URL patterns
   - URL patterns: /prayer-times, /prayers, /salah, /schedule, /timetable,
                   /iqama, /jamaat, /monthly, /daily, /calendar, /jumaa
   - Fetch top 3 candidate pages
4. Detect images that may be prayer schedules → queue for Tier 4
5. Detect PDFs → pass to PDF sub-pipeline
6. Return best result (most prayers found, highest completeness)
```

**Extraction methods in detail**:

*Table extraction*:
- Find all `<table>` elements and div-based table-like structures
- Check if table contains prayer keywords (fajr/dhuhr/asr/maghrib/isha/iqama/adhan)
- Parse header row to identify column positions (Prayer | Adhan | Iqama)
- Handle variable column orders and merged headers
- For monthly tables: identify today's row by date matching

*Text pattern matching (fallback)*:
- Full-page text extraction
- Regex patterns for each prayer name + time
- Extract both adhan and iqama when two times appear near a prayer name
- Time format normalization (12h/24h, with/without AM/PM, Arabic numerals)

#### iframe Widget Detection

The scraper detects embedded prayer widget iframes on both the homepage and any discovered sub-pages. When a matching iframe `src` is found, its URL is fetched directly and parsed with BeautifulSoup for prayer times.

Patterns matched:
- `timing.athanplus.com` (AthanPlus widget)
- `masjidal.com`
- `salahmate.com`
- `salattimes.com`
- `prayer-times.*widget` (generic)
- `muslimpro.com/embed`
- `masjid.us/widget`

#### `extract_times_from_divs()`

A sliding window over leaf DOM elements to find prayer+time pairs in div-based layouts (for sites that don't use `<table>`). This complements the existing table extraction method.

#### `normalize_time()` AM/PM Inference

Times without AM/PM are inferred from prayer context rather than defaulting to AM:
- Dhuhr, Asr, Maghrib, or Isha times with hour 1–9 are assumed PM (+12 hours added)
- Example: `"1:18"` parsed as Dhuhr → `13:18` instead of `01:18`

**Store with**: `source = 'mosque_website_html'`

**Expected hit rate**: ~45% of mosques with websites

---

### Tier 3 — JavaScript-Rendered Scraping

**What**: Use Playwright to render JS-heavy pages before parsing.

**How**:
- Playwright async worker pool (configurable, default 4 workers)
- Persistent browser contexts — NOT new browser per job (too expensive)
- Navigate to URL, wait for network idle + prayer-related element appearance
- Intercept XHR/fetch API responses — if prayer time API response detected, parse it directly (more reliable than parsing rendered HTML)
- After page load: extract using same methods as Tier 2

**Worker pool management**:
```
- Pool size: 4 workers (configurable via env var PLAYWRIGHT_WORKERS)
- Each worker handles one mosque at a time
- Jobs queued; workers pull from queue
- Worker reuses browser context across jobs (faster, less memory)
- Context recycled every 50 jobs to prevent memory leaks
```

**Store with**: `source = 'mosque_website_js'`

**Expected additional hit rate**: ~20% on top of Tier 2

---

### Tier 4 — Image and PDF Extraction (Vision AI)

This tier runs as a **sub-pipeline alongside Tiers 2 and 3**. When those tiers detect a candidate image or PDF, they queue it for Tier 4 processing.

#### Image Detection

Score each `<img>` element found on a mosque page:

```
Filename contains: schedule, prayer, timetable, iqama,
                   salah, times, ramadan, monthly          → +3 points
Alt/title text contains same keywords                      → +3 points
Image is in a section with prayer keyword heading          → +2 points
Image dimensions suggest a table (landscape, wide)         → +2 points
File size > 50KB (not icon/logo/banner)                    → +1 point
Image appears near "prayer times" or "schedule" heading    → +2 points

Score ≥ 4 → send to Vision AI
```

#### Vision AI Prompt (Claude)

```
You are extracting prayer times from a mosque website image.

Analyze this image and return ONLY valid JSON in this exact format:
{
  "is_prayer_schedule": true/false,
  "schedule_type": "daily|weekly|monthly|ramadan|unknown",
  "date_context": "today|YYYY-MM-DD|range:YYYY-MM-DD:YYYY-MM-DD|unknown",
  "prayers": {
    "fajr":    { "adhan": "HH:MM or null", "iqama": "HH:MM or null" },
    "dhuhr":   { "adhan": "HH:MM or null", "iqama": "HH:MM or null" },
    "asr":     { "adhan": "HH:MM or null", "iqama": "HH:MM or null" },
    "maghrib": { "adhan": "HH:MM or null", "iqama": "HH:MM or null" },
    "isha":    { "adhan": "HH:MM or null", "iqama": "HH:MM or null" }
  },
  "jumuah_sessions": [
    {
      "session": 1,
      "khutba_start": "HH:MM or null",
      "prayer_start": "HH:MM or null",
      "imam": "name or null",
      "language": "English/Arabic/Urdu/Mixed or null"
    }
  ],
  "monthly_rows": [
    {
      "date": "YYYY-MM-DD",
      "prayers": { ... same format as above ... }
    }
  ],
  "notes": "any relevant context"
}

Use 24-hour time (HH:MM). If a field is not visible, use null.
If this is not a prayer schedule, return {"is_prayer_schedule": false}.
Handle Arabic numerals and text if present.
For monthly schedules, extract ALL visible date rows into monthly_rows.
```

**Why Claude for this**: Handles varied layouts, Arabic mixed with English, handwritten schedules, poorly-formatted tables, and screenshots of WhatsApp messages — all common in real mosque websites. Cost is ~$0.001 per image (Claude Haiku), ~$3/week for all US/Canada mosques.

#### PDF Extraction

```
1. Download PDF
2. Use pdfplumber to extract text and tables
3. Run same parsing logic as Tier 2 (table extraction + text patterns)
4. If pdfplumber fails to extract structured data: render PDF page as image → Tier 4 Vision AI
```

**Store with**: `source = 'mosque_website_image'` or `source = 'mosque_website_pdf'`

**Expected additional hit rate**: ~15% on top of Tiers 2+3

---

### Tier 2c — Adaptive Custom Extractors

**What**: Between Tier 2 (static HTML) and Tier 3 (Playwright), the pipeline tries any custom extractor functions that were automatically generated by the adaptive extractor (see [Adaptive Extractor Loop](#adaptive-extractor-loop) below). These are Python functions written by Claude based on analysis of previously-failed sites.

**Behaviour**: The page is fetched fresh (same URL as Tier 2), and each registered extractor in `pipeline/custom_extractors.py` is tried in order. On the first one that returns ≥3 valid prayer times, the result is accepted as a Tier 2 (HTML) result.

**Source label**: `mosque_website_html` (treated identically to a successful Tier 2 result).

**Skip condition**: Skipped if Tier 2 already succeeded, if there is no website, or if no custom extractors have been generated yet.

---

### Tier 5 — Calculated Adhan + Estimated Iqama (Last Resort)

**What**: When all scraping fails, fall back to mathematical calculation.

**Adhan times**: Calculate using the `praytimes` Python port library from mosque GPS coordinates.
- Calculation method: ISNA (default for US/Canada) — configurable per mosque if known
- After initialization, explicit overrides are applied to correct inherited Jafari defaults:

```python
pt = PrayTimes('ISNA')
pt.adjust({"maghrib": "0 min", "midnight": "Standard", "fajr": 15, "isha": 15})
```

These overrides are required because initializing with the ISNA method inherits incorrect Jafari defaults (notably `maghrib: 4°`), which would cause Maghrib to be calculated approximately 16 minutes late. With the override, Maghrib is correctly set to sunset (`'0 min'`), Fajr to 15° below the horizon, and Isha to 15° below the horizon.

- Source: `source = 'calculated'`, `confidence = 'medium'`

**Iqama times**: Estimate using typical offset from adhan by prayer:
```
Fajr:    adhan + 20 minutes
Dhuhr:   adhan + 15 minutes
Asr:     adhan + 10 minutes
Maghrib: adhan + 5 minutes  (Maghrib iqama is often very close to adhan)
Isha:    adhan + 15 minutes
```
Source: `source = 'estimated'`, `confidence = 'low'`

**User notification**: Any time estimated iqama is shown, the app displays:
> "Congregation time not confirmed for this mosque — this is an estimate. Tap to help us improve."

---

## Data Validation

All scraped times go through validation before being stored:

```python
def validate_prayer_times(times: dict) -> tuple[bool, str]:
    """
    Returns (is_valid, reason_if_invalid)
    """
    prayers = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']

    # All 5 prayers must be present (at minimum adhan times)
    for p in prayers:
        if not times.get(f'{p}_adhan'):
            return False, f"Missing {p} adhan time"

    # Times must be in correct order
    order_check = [
        ('fajr_adhan',    '04:00', '07:00'),  # Fajr: 4 AM – 7 AM
        ('dhuhr_adhan',   '11:00', '14:00'),  # Dhuhr: 11 AM – 2 PM
        ('asr_adhan',     '13:00', '18:30'),  # Asr: 1 PM – 6:30 PM
        ('maghrib_adhan', '16:00', '21:00'),  # Maghrib: 4 PM – 9 PM
        ('isha_adhan',    '18:00', '24:00'),  # Isha: 6 PM – midnight
    ]
    for field, min_time, max_time in order_check:
        if not (min_time <= times[field] <= max_time):
            return False, f"{field} = {times[field]} is outside expected range"

    # Fajr must be before Dhuhr
    # Dhuhr must be before Asr, etc.
    for i in range(len(prayers) - 1):
        adhan_a = times[f'{prayers[i]}_adhan']
        adhan_b = times[f'{prayers[i+1]}_adhan']
        if adhan_a >= adhan_b:
            return False, f"{prayers[i]} adhan ({adhan_a}) must be before {prayers[i+1]} adhan ({adhan_b})"

    # Iqama gap must be within a reasonable window around adhan
    # Negative gap (iqama before adhan) is valid during Ramadan — e.g. early Fajr iqama
    # Allowed range: -60 min ≤ gap ≤ 90 min
    for p in prayers:
        adhan = times.get(f'{p}_adhan')
        iqama = times.get(f'{p}_iqama')
        if adhan and iqama:
            gap_minutes = time_diff_minutes(adhan, iqama)
            if gap_minutes < -60:
                return False, f"{p} iqama is {abs(gap_minutes)} min before adhan — too early"
            if gap_minutes > 90:
                return False, f"{p} iqama gap of {gap_minutes} min is unreasonably large"

    return True, "ok"
```

### Completeness Check — `is_complete()`

A result is considered complete only when it contains both adhan and iqama times:

```
adhan_count == 5 AND iqama_count >= 4
```

This is stricter than checking adhan count alone. Previously, a result with 5 adhans and 0 iqamas (e.g. an IslamicFinder city-level result) would be marked complete and incorrectly block Tier 2 from running. Now such a result is treated as incomplete and the pipeline continues to the next tier.

---

## Retry and Backoff Logic

```python
def calculate_next_attempt(consecutive_failures: int, tier_reached: int) -> datetime:
    if consecutive_failures == 0:
        # Success: retry in 7 days
        return now() + timedelta(days=7)
    elif consecutive_failures == 1:
        return now() + timedelta(days=1)
    elif consecutive_failures == 2:
        return now() + timedelta(days=3)
    elif consecutive_failures <= 5:
        return now() + timedelta(days=7)
    else:
        # Repeated failure: monthly retry, flag for manual review
        return now() + timedelta(days=30)
```

Priority adjustment:
```
New mosque (never scraped):          priority = 1
Last scraped > 14 days ago:          priority = 2
High-traffic mosque (top 10% views): priority = 3
Standard active mosque:              priority = 5
Recently scraped successfully:       priority = 8
No website, using calculated:        priority = 9 (monthly retry only)
```

---

## Daily Pipeline Script

**File**: `pipeline/daily_pipeline.sh`

**Cron schedule**:
```
0 2 * * * /path/to/daily_pipeline.sh >> /var/log/cap_pipeline.log 2>&1
```

**Steps** (run nightly at 2 AM):

1. **Re-queue stale schedules** — set `status = 'pending'` for all mosques with `status = 'success'` whose schedule is older than 6 days
2. **Reset failed jobs for retry** — set `attempt_count = 0` for failed jobs older than 24 hours
3. **Run scraping worker** — `python -m pipeline.scraping_worker`
4. **Print summary**:
   - Total mosques in DB
   - Mosques with a schedule for today
   - Mosques freshly scraped in the last 24 hours
   - Mosques still pending
   - Mosques in failed state

---

## Mosque Database Seeding

### Phase 1 — Overpass API (OpenStreetMap) bulk download

Runs once initially, then weekly to pick up new/changed mosques.

```
Query:
  area["ISO3166-1"="US"]["admin_level"="2"]->.us;
  area["ISO3166-1"="CA"]["admin_level"="2"]->.ca;
  (
    nwr["amenity"="place_of_worship"]["religion"="muslim"](area.us);
    nwr["amenity"="place_of_worship"]["religion"="muslim"](area.ca);
  );
  out center tags;

Extracts per result:
  - osm_id, name, name:ar (Arabic name if present)
  - lat, lng (or center point for ways/relations)
  - addr:*, phone, website, email
  - capacity, wheelchair, opening_hours
  - denomination (if tagged)

Inserts with ON CONFLICT (osm_id) DO UPDATE
```

### Phase 2 — Google Places enrichment (one-time per mosque)

Only for mosques missing website or phone from OSM.

```
For each mosque WHERE website IS NULL OR phone IS NULL:
  1. Google Places Text Search: "{mosque name} {city} {state}"
  2. Verify coordinates match within 500m
  3. If match: update website, phone, google_place_id
  4. Cost: ~1 API call per mosque × $0.017 = ~$42 for all 2,500 US/CA mosques
  5. Run once — not on every scraping cycle
```

### Phase 3 — Timezone assignment

```python
from timezonefinder import TimezoneFinder
tf = TimezoneFinder()

for mosque in mosques_without_timezone:
    tz = tf.timezone_at(lat=mosque.lat, lng=mosque.lng)
    mosque.timezone = tz  # e.g. "America/New_York"
```

No API call — uses offline polygon data. Runs at insert time for every mosque.

### Prayer Spots Seeding

**File**: `pipeline/seed_prayer_spots.py`

Seeds non-mosque prayer locations (airport prayer rooms, university musallas, etc.) into the database from two sources:

**Source 1 — Curated airport prayer rooms**

Hardcoded list of 19 major US airports known to have dedicated prayer rooms:

```
JFK, LAX, O'Hare (ORD), DFW, ATL, SFO, SEA, DEN, BOS, MIA,
PHX, MSP, DTW, IAD, EWR, SAN, HOU, MDW, PHL
```

**Source 2 — OpenStreetMap Overpass**

Queries `amenity=prayer_room` across the US. The query is split into two requests to avoid the Overpass API 120-second timeout.

**Usage**:
```
python -m pipeline.seed_prayer_spots --source [all|airports|osm] --dry-run
```

- `--source all` (default): runs both sources
- `--source airports`: curated airport list only
- `--source osm`: Overpass query only
- `--dry-run`: preview inserts without writing to the database

---

## Jumuah-Specific Weekly Scrape

Runs every **Thursday 9 PM** (in each mosque's local timezone, batched):

1. Query: all mosques with `jumuah_sessions.valid_date < next_friday` OR no recent Jumuah record
2. Re-scrape mosque website, focusing on:
   - Friday prayer time pages
   - "This week's khutba" or "Imam schedule" sections
   - Any "upcoming events" sections
3. Extract: khutba_start, prayer_start, imam_name, language, khutba_topic
4. Insert new `jumuah_sessions` row for upcoming Friday date
5. If nothing found: carry forward previous session's times (without imam/topic)

---

## Raw Data Retention

Every successful scrape stores:
- `raw_html_url`: the specific URL that yielded prayer times
- `raw_extracted_json`: exactly what the scraper found before normalization

This enables:
- Debugging when times look wrong
- Reprocessing with improved parsers without re-scraping
- Manual review of low-confidence extractions
- Future model training for better extraction

---

## Adaptive Extractor Loop

The adaptive extractor is a lightweight Claude-powered sub-process that runs every 3 scraping iterations and tries to recover mosques permanently stuck on Tier 5 (calculated).

### Design Principles

- **Zero Claude tokens for HTML/JS** — automated heuristics handle all code-based recovery. Claude is NOT used to generate extraction code.
- **Claude Vision only for images/PDFs** — that is already Tier 4's responsibility. The adaptive extractor never calls Claude.
- **Domain cooldown (14 days)** — once a domain is checked, it is not re-fetched for 14 days to avoid wasting HTTP requests.
- **Re-queue on success** — when a new extractor is generated, ALL tier-5 website mosques are reset to `pending` so subsequent scraping iterations retry them.

### Flow

```
Every scraping iteration:

1. Query DB → mosques with (tier_reached=5 AND has_website)
2. Fetch each page (8s timeout, skip domains on cooldown)
3. Regex pre-screen: ≥3 prayer keywords? → skip if no content
4. Try 6 automated approaches in order (zero Claude tokens):
   a. JSON-LD structured data
   b. Inline JS variables (var prayerTimes={...})
   c. JS API endpoint detection (fetch/XHR calls → call API directly)
   d. data-* attribute tables
   e. <dl><dt>/<dd> definition lists
   f. Aggressive regex sweep (30+ pattern variants)
5. If any approach yields ≥3 valid prayer times:
   → generate Python extractor function from result (no Claude)
   → append to pipeline/custom_extractors.py
   → reset ALL tier-5 website mosques to pending
6. If all fail: no Claude call — PDF/image sites are already handled by Tier 4
```

### Files

| File | Purpose |
|------|---------|
| `pipeline/adaptive_extractor.py` | The adaptive script — run as `python -m pipeline.adaptive_extractor` |
| `pipeline/custom_extractors.py` | Auto-generated extractor functions, imported by scraping_worker |
| `pipeline/adaptive_analyzed.json` | Domains already processed (avoids re-sending to Claude) |

### Extractor Format

Each generated extractor is a Python function appended to `custom_extractors.py`:

```python
def _ext_001(html: str) -> dict | None:
    """Return dict with keys: fajr_adhan, fajr_iqama, ... (24h HH:MM) or None if no match."""
    soup = BeautifulSoup(html, "html.parser")
    # Claude-generated extraction logic
    ...

CUSTOM_EXTRACTORS.append(("_ext_001", _ext_001))
```

Multiple extractors accumulate over time. Each one covers a distinct CMS/layout pattern discovered from real failed sites.

---

## Monitoring

### Primary Metric — Real Scrape Rate

```
real_scrape_rate = mosques_with_tier_2_3_4_result / mosques_with_website
```

**Target: 100%** (every mosque that has a website should have real scraped prayer data, not a calculated estimate).

The no-website floor (~790 mosques) is irreducible — those can only be improved by finding their websites. For all other mosques, the scraping pipeline + adaptive extractor should eventually reach full coverage.

Secondary metrics:

```
jobs_done_pct               = success / total_jobs
tier_distribution           = count by tier_reached (shows pipeline health)
stuck_with_website          = tier_5 mosques that have a website (the recovery target)
adaptive_extractor_count    = number of custom extractors generated so far
domains_on_cooldown         = domains recently sent to Claude (14-day cooldown)
```

### Live Monitoring Commands

```bash
# Run scraping loop (logs everything to logs/scraping.log automatically)
./run_scraping_loop.sh

# Check current metrics at any time (one-shot, works while loop is running or stopped)
./monitor_scraping.sh

# Tail the live log
./monitor_scraping.sh tail

# Watch metrics auto-refresh every 30s
./monitor_scraping.sh watch
```
