# 🕌 MOSQUE WEBSITE SCRAPING GUIDE

## Overview
This document outlines our comprehensive approach to extracting prayer times from mosque websites. The goal is to achieve near-zero fallback to default times by handling all common mosque website architectures and designs, with special emphasis on Jumaa (Friday) prayer information.

## 🎯 Scraping Strategy (Implemented)

### 5-Tier Pipeline (`pipeline/scraping_worker.py`)

| Tier | Method | Source tag | Coverage |
|------|--------|-----------|----------|
| 1 | IslamicFinder lookup (no-website mosques only) | `islamicfinder` | ~5% |
| 1b | Aladhan.com mosque API (no-website mosques) | `aladhan_mosque_db` | ~2% |
| 2 | Static HTML — httpx + BeautifulSoup | `mosque_website_html` | ~15% |
| 2 (FB) | Facebook via mbasic.facebook.com | `mosque_website_facebook` | ~1% |
| 3 | Playwright JS rendering + **API interception** | `mosque_website_js` / `masjidbox_api` / `athanplus_api` | ~5% |
| 4 | Claude Haiku Vision AI (images) + pdfplumber (PDFs) | `mosque_website_image` / `mosque_website_pdf` | ~1% |
| 5 | Calculated via praytimes (ISNA 15°/15°, maghrib=0 min) | `calculated` | fallback |

Tier 5 always fills any missing gaps even when a real tier provides primary data.

### Tier Validation
Each tier result is validated **before** accepting it (prayer time range checks, ordering checks). If a later tier corrupts the result, the **last valid tier result** is used as fallback before dropping to Tier 5.

### Primary Approach: Multi-Level Discovery
1. **Home Page Analysis** - Start with the main website URL
2. **Link Discovery** - Find prayer/schedule related pages (`/prayer-times`, `/iqama`, etc.)
3. **Deep Content Extraction** - Table → div → text regex extraction pipeline
4. **API Interception** - Playwright captures MasjidBox/AthanPlus JSON during page load
5. **Fallback Chain** - Graceful degradation to calculated times

### Website Architecture Patterns We Handle

#### 1. **Table-Based Layouts**
- **Monthly Prayer Calendars**: Full month grid with dates and prayer times
- **Daily Prayer Tables**: Today's prayers in tabular format
- **Weekly Schedules**: 7-day prayer timetables
- **Iqama vs Adhan**: Separate columns for call to prayer and congregation times
- **Jumaa Schedules**: Multi-session Friday prayer timetables

#### 2. **Modern Web Apps**
- **JavaScript-Rendered Content**: Dynamic loading of prayer times
- **API Endpoints**: Direct JSON prayer data
- **Single Page Applications**: Client-side rendered schedules
- **Widget Embeds**: Third-party prayer time widgets
- **Interactive Jumaa Booking**: Session selection and imam details

#### 3. **Content Management Systems**
- **WordPress Sites**: Prayer time plugins and custom fields
- **Drupal/Joomla**: Module-based prayer displays
- **Static Site Generators**: Markdown-based schedules
- **Custom CMS**: Bespoke mosque management systems
- **Event Management**: Jumaa sermon scheduling systems

#### 4. **Social Media Integration**
- **Facebook Pages**: Posted prayer schedules and Jumaa announcements
- **Instagram Stories**: Daily prayer time updates and imam highlights
- **WhatsApp Groups**: Shared prayer timetables and sermon topics
- **YouTube Descriptions**: Live stream prayer info and khutba details

## 🔍 Content Discovery Methods

### URL Pattern Recognition
```
Common prayer page URLs:
- /prayer-times, /prayers, /salah
- /schedule, /timetable, /calendar
- /daily-prayers, /monthly-schedule
- /iqama, /jamaat-times
- /jumaa, /jummah, /friday-prayers
- /khutba, /sermon, /imam-schedule
- /ramadan-schedule (seasonal)
```

### Link Text Patterns
```
Prayer-related link text (case-insensitive):
- "Prayer Times", "Salah Times", "Namaz"
- "Schedule", "Timetable", "Calendar"
- "Iqama Times", "Jamaat", "Congregation"
- "Daily Prayers", "Monthly Schedule"
- "Current Times", "Today's Prayers"
- "Jumaa", "Jummah", "Friday Prayer"
- "Khutba", "Sermon", "Imam Schedule"
- "This Week's Topic", "Friday Sermon"
```

### Meta Tag Analysis
```html
<meta name="description" content="prayer times, iqama, schedule, jumaa, khutba">
<meta property="og:title" content="Friday Prayer Schedule - Imam Details">
<title>Masjid Name - Jumaa Prayer Times & Khutba Topics</title>
```

## 🕌 Jumaa Prayer Information Extraction

### Required Jumaa Data Points
```python
JumaaSession:
- session_time: "12:30 PM"
- imam_name: "Dr. Ahmed Ali"  
- khutba_topic: "The Importance of Prayer in Islam"
- language: "English" | "Arabic" | "Urdu" | "Mixed"
- duration_minutes: 45
- capacity: 500
- booking_required: true
- special_notes: "Sign language interpretation available"
```

### Jumaa-Specific Extraction Patterns

#### 1. **Multi-Session Schedules**
```html
Common patterns:
<div class="jumaa-schedule">
  <h3>Friday Prayer Sessions</h3>
  <div class="session">
    <span class="time">12:30 PM</span>
    <span class="imam">Imam Abdullah</span>
    <span class="topic">Patience in Times of Trial</span>
    <span class="language">English</span>
  </div>
</div>
```

#### 2. **Imam Information Sections**
```html
Imam details:
<div class="imam-profile">
  <h4>Dr. Mohammed Hassan</h4>
  <p>Languages: Arabic, English</p>
  <p>Specialization: Quran & Hadith</p>
  <p>This Friday: "The Virtues of Charity"</p>
</div>
```

#### 3. **Weekly Khutba Topics**
```html
Sermon schedules:
<table class="khutba-schedule">
  <tr>
    <td>Sept 6</td>
    <td>The Importance of Family</td>
    <td>Imam Ali</td>
    <td>Arabic/English</td>
  </tr>
</table>
```

#### 4. **Language-Specific Sessions**
```html
Multi-language support:
<div class="language-sessions">
  <div class="english-session">
    <h4>English Khutba - 12:30 PM</h4>
    <p>Imam: Dr. Sarah Ahmed</p>
  </div>
  <div class="arabic-session">
    <h4>خطبة عربية - 1:30 PM</h4>
    <p>إمام: الشيخ محمد علي</p>
  </div>
</div>
```

### Jumaa Content Recognition Patterns

#### Time Patterns
```python
Jumaa time indicators:
- "Friday Prayer: 12:30 PM"
- "Jummah 1st: 12:00, 2nd: 1:30"  
- "Khutba starts at 12:15"
- "Multiple sessions: 11:30, 12:30, 1:30"
```

#### Imam Name Patterns
```python
Imam identification:
- "Imam: Dr. Ahmed Ali"
- "Led by Sheikh Mohammed"
- "Khatib: Ustaz Abdullah"
- "Guest Speaker: Prof. Sarah"
- "Rotating Imams: See schedule"
```

#### Topic/Khutba Patterns
```python
Sermon topic extraction:
- "This Friday: The Beauty of Islam"
- "Khutba Topic: Patience & Perseverance"  
- "Weekly Theme: Community Unity"
- "Series: Stories of the Prophets (Part 3)"
```

#### Language Detection
```python
Language indicators:
- "English Khutba", "Arabic Sermon"
- "Bilingual: Arabic/Urdu"
- "Translation available"  
- "Sign language interpretation"
- Unicode detection: العربية, اردو
```

## 📊 Data Extraction Techniques

### 1. **Table Extraction**
```python
Strategies:
- Header detection (Prayer, Adhan, Iqama, Imam, Topic columns)
- Row parsing (prayer name + times + details)
- Date context (today's row in monthly tables)
- Time format normalization (12h ↔ 24h)
- Jumaa-specific columns (Language, Duration, Capacity)
```

### 2. **Structured Data**
```python
JSON-LD, Microdata, RDFa:
- schema.org/Event for prayer times
- schema.org/Person for imam details
- Custom mosque schemas
- Embedded JSON prayer data
- API response parsing for Jumaa sessions
```

### 3. **Pattern Matching**
```python
Regular expressions for:
- Time formats: 12:30 PM, 0630, 6:30am
- Prayer names: Fajr, Dhuhr, Asr, Maghrib, Isha, Jumaa
- Date contexts: Today, September 4, 2024-09-04, This Friday
- Special cases: Multiple Jumaa sessions, Ramadan Tarawih
- Imam titles: Dr., Sheikh, Imam, Ustaz, Hafiz
- Languages: English, Arabic, Urdu, Turkish, French
```

### 4. **Visual/PDF Processing**
```python
Image/PDF prayer schedules:
- OCR text extraction with Arabic support
- PDF table parsing for Jumaa schedules
- Image-to-text conversion
- Schedule image recognition
- Imam photo recognition (future enhancement)
```

### 5. **Jumaa-Specific Extraction Methods**
```python
def extract_jumaa_sessions(soup):
    """Extract multiple Jumaa prayer sessions"""
    sessions = []
    
    # Method 1: Structured session containers
    session_divs = soup.find_all(['div', 'section'], 
        class_=re.compile(r'jumaa|friday|session'))
    
    # Method 2: Table-based schedules
    jumaa_tables = soup.find_all('table')
    for table in jumaa_tables:
        if any(keyword in table.get_text().lower() 
               for keyword in ['jumaa', 'friday', 'khutba']):
            sessions.extend(parse_jumaa_table(table))
    
    # Method 3: List-based schedules  
    jumaa_lists = soup.find_all(['ul', 'ol'])
    for ul in jumaa_lists:
        if 'jumaa' in ul.get_text().lower():
            sessions.extend(parse_jumaa_list(ul))
    
    return sessions
```

## 🌐 Website Architecture Handling

### Traditional HTML Sites
- **Direct scraping**: BeautifulSoup parsing with Arabic text support
- **Form handling**: POST requests for date selection and Jumaa booking
- **Session management**: Login-required schedules
- **Encoding**: UTF-8, Arabic/Urdu text support

### Modern JavaScript Applications
- **Headless browsers**: Selenium/Playwright for dynamic Jumaa schedules
- **API interception**: Network request monitoring for imam/topic data
- **XHR/Fetch**: AJAX prayer time and Jumaa session requests
- **React/Vue**: Component state extraction for interactive schedules

### Content Management Systems
- **WordPress**: 
  - Plugin detection (Prayer Times Plugin, Islamic Tools, Event Calendar)
  - Custom post types (prayer_schedule, jumaa_session, imam_profile)
  - Widget areas (sidebar prayer times, upcoming khutba)
  - Theme-specific selectors for Jumaa information

- **Drupal**: 
  - Content type analysis (prayer_time, jumaa_event nodes)
  - View exports (calendar displays, imam schedules)
  - Block content (prayer widgets, weekly topics)

### Islamic-Specific Platforms
- **Mosque Management Systems**: 
  - IslamicFinder integration
  - MuslimPro API connections
  - Custom Islamic CMS platforms
  - Masjid booking systems

## 🕐 Time Format Normalization

### Input Formats We Handle
```
12-hour: 6:30 AM, 12:45 PM, 6:30am, 12:45pm
24-hour: 06:30, 18:30, 0630, 1845
Text: six thirty am, quarter to seven
Mixed: 6:30a, 12:45p, 6.30 AM
Arabic: ٦:٣٠ص, ١٢:٤٥م
Islamic: After Maghrib, Before Asr
Jumaa-specific: First session, Second Jumaa
```

### Output Standardization
```
Standard format: HH:MM (24-hour)
Examples: 06:30, 12:45, 18:30
Jumaa sessions: Array of session objects
Validation: Range checking, logical ordering
Timezone: Mosque local time zone
```

## 📅 Date Context Recognition

### Today's Prayer Times
- **Date matching**: Current date in various formats
- **Day detection**: Today, current weekday, Friday detection
- **Calendar navigation**: Date picker interaction
- **Dynamic updates**: Real-time schedule changes

### Jumaa-Specific Dating
- **This Friday**: Current week's Friday identification
- **Next Friday**: Following week's Jumaa
- **Weekly series**: "Part 2 of 4" sermon series tracking
- **Special occasions**: Eid prayers, Ramadan schedules
- **Guest speakers**: One-time or visiting imam schedules

### Monthly Schedules
- **Calendar parsing**: Full month prayer grids with Jumaa highlights
- **Date row extraction**: Today's row from calendar
- **Month navigation**: Previous/next month handling
- **Year transitions**: December→January handling
- **Islamic calendar**: Hijri date correlation

## 🚨 Error Handling & Fallbacks

### Network Issues
```python
Retry strategies:
- Exponential backoff (1s, 2s, 4s, 8s)
- User-agent rotation
- Proxy usage for blocked sites
- Timeout handling (30s max)
- Jumaa-specific fallbacks during high traffic
```

### Parsing Failures
```python
Fallback chain:
1. Primary extraction method (structured data)
2. Secondary methods (table/list parsing)
3. Generic text parsing with NLP
4. Pattern matching with fuzzy matching
5. Default prayer times (last resort)
6. Community-sourced Jumaa data (future)
```

### Data Validation
```python
Sanity checks:
- Prayer time ordering (Fajr < Dhuhr < Asr < Maghrib < Isha)
- Reasonable time ranges (Fajr 4-7 AM, Jumaa 11 AM-2 PM)
- Date consistency (not yesterday's times)
- Required prayers present (5 daily + Jumaa on Fridays)
- Imam name validation (not placeholder text)
- Language code validation (ISO 639-1)
```

## 📈 Metrics

### Current Pipeline Stats (as of 2026-03-15)
| Metric | Value |
|--------|-------|
| Total mosques in DB | 2,448 (US + CA) |
| With website | 1,044 (43%) |
| Scraping jobs done | 1,345 / 2,451 (55%) |
| Tier 2 (real HTML) | 76 (5.7%) |
| Tier 3 (JS / API interception) | 14 (1.0%) |
| Tier 4 (Vision/PDF) | 10 (0.7%) |
| Tier 5 (calculated fallback) | 1,245 (92.6%) |

### Improving Hit Rate
The main levers for improving above tier-5:
1. **More mosques with websites** — Hartford + MosqueList enrichment adds website URLs
2. **Better widget detection** — add new widget patterns to `IFRAME_WIDGET_PATTERNS`
3. **API interception** — Playwright captures MasjidBox / AthanPlus / mosqueprayertimes.com
4. **Playwright browsers installed** — required for Tier 3: `python3 -m playwright install chromium`

### Target
- **Real-data coverage**: >30% (from current 8%)
- **Calculated fallback**: <70%

## 🧪 Testing Strategy

### Test Categories
1. **Unit Tests**: Individual extraction methods
2. **Integration Tests**: Full website scraping flows
3. **Regression Tests**: Known mosque websites
4. **Performance Tests**: Speed and reliability benchmarks
5. **Jumaa-Specific Tests**: Friday prayer information accuracy

### Jumaa Test Data
- **Multi-session mosques**: Large mosques with multiple Jumaa times
- **Bilingual content**: Arabic/English mixed content
- **Guest imam schedules**: Special speaker announcements  
- **Series tracking**: Multi-week khutba series
- **Seasonal variations**: Ramadan, Hajj-themed content

### Test Data Sources
- **Live websites**: Real mosque URLs for testing
- **Mock responses**: Cached HTML for consistent testing  
- **Edge cases**: Broken sites, unusual formats
- **Seasonal tests**: Ramadan, DST transitions, Eid schedules
- **Community mosques**: Different cultural/linguistic backgrounds

## 🔧 Implementation Architecture

### Core Files
```
pipeline/
├── scraping_worker.py      # 5-tier scraper (main)
├── seed_mosques.py         # OSM / OpenStreetMap seeder
├── seed_from_web_sources.py # Hartford + MosqueList seeder
├── deduplicate_mosques.py  # Dedup pass (proximity + name)
└── daily_pipeline.sh       # Cron entry: runs at 2am daily
```

### Mosque Database Sources
1. **OpenStreetMap** (via Overpass API) — primary, 1,400+ mosques US+CA
2. **Hartford Institute** (hirr.hartfordinternational.edu) — 2,108 US mosques; enriches websites on existing records, geocodes+inserts new ones
3. **MosqueList.top** — US mosques with accessibility info (wheelchair, parking)

### Deduplication Strategy
- **Name + city + state** match (≥50% token overlap) for web source enrichment; generic names (`Unknown Mosque`, `Masjid`, `Islamic Center`, etc.) are excluded from name-matching to avoid false merges
- **Proximity + name similarity** before inserting geocoded new mosques:
  - ≤50m → always merge (same building)
  - 50–200m → merge only if name similarity ≥ 0.4 (avoids collapsing distinct orgs at the same address)
- **Periodic DB dedup pass**: deactivate exact-duplicate entries found by `ST_DWithin(100m) AND (same name OR unknown name)`

### Key Extraction Functions
```python
# pipeline/scraping_worker.py

_extract_from_soup(soup)       # Table → div → text regex pipeline
extract_times_from_table(soup) # Header detection + row parsing
extract_times_from_divs(soup)  # Div/span class-based extraction
extract_times_from_text(text)  # Regex fallback on full page text
_extract_from_text(text)       # Plain-text blob parser (Facebook About, PDFs)

normalize_time(raw, prayer)    # Normalizes any time string to HH:MM 24h
validate_prayer_times(result)  # Range + ordering checks
```

### Prayer Time Calculation (Tier 5)
Uses `praytimes` Python library with explicit ISNA settings:
```python
pt = PrayTimes("ISNA")
pt.adjust({"maghrib": "0 min", "midnight": "Standard", "fajr": 15, "isha": 15})
```
`maghrib: "0 min"` ensures sunset time (not 4° angle which is Jafari default).

### Network API Interception (Tier 3)
Playwright response listener captures JSON from known prayer widget APIs:
- `api.masjidbox.com` → `_parse_masjidbox_response()`
- `timing.athanplus.com` → `_parse_athanplus_response()`
- Other APIs → generic fallback parsers

### Data Model
```python
@dataclass
class PrayerTimes:
    fajr_adhan / fajr_iqama
    dhuhr_adhan / dhuhr_iqama
    asr_adhan / asr_iqama
    maghrib_adhan / maghrib_iqama
    isha_adhan / isha_iqama
    sunrise: Optional[str]
    source: str           # e.g. "mosque_website_html", "masjidbox_api", "calculated"
    confidence: str       # "high" | "medium" | "low"
    tier: int             # 1–5
    source_url: str

# Saved to DB table: prayer_schedules (one row per mosque per date)
# ON CONFLICT (mosque_id, date) DO UPDATE — atomic upsert prevents race conditions
```

### Running the Pipeline
```bash
# Full daily pipeline (cron at 2am)
./pipeline/daily_pipeline.sh

# Single scrape
python -m pipeline.scraping_worker --mosque-id <uuid>

# Batch
python -m pipeline.scraping_worker --batch 100

# Seed new mosques from web sources
python -m pipeline.seed_from_web_sources --source hartford
python -m pipeline.seed_from_web_sources --source mosquelist
python -m pipeline.seed_from_web_sources             # both sources
python -m pipeline.seed_from_web_sources --no-geocode # only enrich existing
```