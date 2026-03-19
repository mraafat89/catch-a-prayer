# Database Schema

PostgreSQL 15 + PostGIS. All timestamps are `TIMESTAMPTZ` (UTC stored, converted at display time).

---

## Source Enum

Used in every field that tracks where data came from. Always stored alongside the data itself.

```
mosque_website_html     Scraped from mosque's HTML page (static, httpx + BeautifulSoup)
mosque_website_js       Scraped from mosque's JS-rendered page (Playwright)
mosque_website_image    Extracted from image on mosque website (Vision AI)
mosque_website_pdf      Extracted from PDF on mosque website (pdfplumber)
islamicfinder           Retrieved from IslamicFinder database
aladhan_mosque_db       Retrieved from Aladhan.com mosque database
user_submitted          Submitted or corrected by a community user
calculated              Astronomically calculated from mosque coordinates (adhan-python)
estimated               Estimated from typical adhan+offset (absolute last resort)
```

## Confidence Enum
```
high    5 prayers found, both adhan and iqama, times pass sanity checks
medium  Times found but incomplete (missing some iqama, or only 4 prayers)
low     Partial data, estimated values, or source is unreliable
```

---

## Tables

### `mosques`

```sql
CREATE TABLE mosques (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    name                  TEXT NOT NULL,
    name_arabic           TEXT,

    -- Location
    lat                   DOUBLE PRECISION NOT NULL,
    lng                   DOUBLE PRECISION NOT NULL,
    geom                  GEOMETRY(Point, 4326) GENERATED ALWAYS AS
                              (ST_SetSRID(ST_MakePoint(lng, lat), 4326)) STORED,
    address               TEXT,
    city                  TEXT,
    state                 TEXT,
    zip                   TEXT,
    country               CHAR(2) NOT NULL DEFAULT 'US',  -- ISO 3166-1 alpha-2
    timezone              TEXT NOT NULL,                   -- IANA: "America/New_York"

    -- Contact
    phone                 TEXT,
    website               TEXT,
    email                 TEXT,

    -- External IDs (for re-enrichment and deduplication)
    osm_id                TEXT UNIQUE,
    google_place_id       TEXT UNIQUE,
    islamicfinder_id      TEXT,

    -- Mosque characteristics
    denomination          TEXT,                  -- Sunni / Shia / etc. if determinable
    languages_spoken      TEXT[],                -- e.g. ["English", "Arabic", "Urdu"]
    has_womens_section    BOOLEAN,
    has_parking           BOOLEAN,
    wheelchair_accessible BOOLEAN,
    capacity              INTEGER,

    -- Status
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    verified              BOOLEAN NOT NULL DEFAULT FALSE,  -- manually verified data

    -- Metadata
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX mosques_geom_idx ON mosques USING GIST (geom);
CREATE INDEX mosques_city_state_idx ON mosques (city, state);
CREATE INDEX mosques_active_idx ON mosques (is_active) WHERE is_active = TRUE;
```

---

### `prayer_schedules`

One row per mosque per date. Stores both adhan and iqama times with full source tracking for every individual field.

```sql
CREATE TABLE prayer_schedules (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mosque_id                 UUID NOT NULL REFERENCES mosques(id) ON DELETE CASCADE,
    date                      DATE NOT NULL,

    -- Fajr
    fajr_adhan                TIME,
    fajr_iqama                TIME,
    fajr_adhan_source         TEXT,
    fajr_iqama_source         TEXT,
    fajr_adhan_confidence     TEXT,
    fajr_iqama_confidence     TEXT,

    -- Sunrise (required for Fajr period-end calculation)
    sunrise                   TIME,
    sunrise_source            TEXT,    -- always 'calculated' (astronomical)

    -- Dhuhr
    dhuhr_adhan               TIME,
    dhuhr_iqama               TIME,
    dhuhr_adhan_source        TEXT,
    dhuhr_iqama_source        TEXT,
    dhuhr_adhan_confidence    TEXT,
    dhuhr_iqama_confidence    TEXT,

    -- Asr
    asr_adhan                 TIME,
    asr_iqama                 TIME,
    asr_adhan_source          TEXT,
    asr_iqama_source          TEXT,
    asr_adhan_confidence      TEXT,
    asr_iqama_confidence      TEXT,

    -- Maghrib
    maghrib_adhan             TIME,
    maghrib_iqama             TIME,
    maghrib_adhan_source      TEXT,
    maghrib_iqama_source      TEXT,
    maghrib_adhan_confidence  TEXT,
    maghrib_iqama_confidence  TEXT,

    -- Isha
    isha_adhan                TIME,
    isha_iqama                TIME,
    isha_adhan_source         TEXT,
    isha_iqama_source         TEXT,
    isha_adhan_confidence     TEXT,
    isha_iqama_confidence     TEXT,

    -- Audit
    scraped_at                TIMESTAMPTZ,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT prayer_schedules_mosque_date_unique UNIQUE (mosque_id, date)
);

CREATE INDEX prayer_schedules_mosque_date_idx ON prayer_schedules (mosque_id, date);
CREATE INDEX prayer_schedules_date_idx ON prayer_schedules (date);
```

**Note on date storage**: The pipeline pre-computes schedules for the next 30 days. For mosques where only a single "current" schedule was scraped (no date-specific data), that schedule is duplicated across dates until a new scrape updates it. The `updated_at` field allows the app to show freshness to users.

---

### `jumuah_sessions`

Separate table because a single mosque can have multiple Jumuah sessions per Friday, and details (imam, topic) change weekly.

```sql
CREATE TABLE jumuah_sessions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mosque_id         UUID NOT NULL REFERENCES mosques(id) ON DELETE CASCADE,
    valid_date        DATE NOT NULL,           -- the specific Friday this applies to
    session_number    INTEGER NOT NULL DEFAULT 1,  -- 1st, 2nd, 3rd session

    -- Timing
    khutba_start      TIME,
    prayer_start      TIME,

    -- Imam details
    imam_name         TEXT,
    imam_title        TEXT,                    -- Sheikh / Dr. / Hafiz / Imam / Ustaz
    imam_is_guest     BOOLEAN DEFAULT FALSE,

    -- Sermon details
    language          TEXT,                    -- English / Arabic / Urdu / Mixed
    khutba_topic      TEXT,
    khutba_series     TEXT,                    -- e.g. "Stories of the Prophets – Part 3"

    -- Logistics
    capacity          INTEGER,
    booking_required  BOOLEAN DEFAULT FALSE,
    booking_url       TEXT,
    special_notes     TEXT,

    -- Source tracking
    source            TEXT,
    confidence        TEXT,
    scraped_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT jumuah_sessions_unique UNIQUE (mosque_id, valid_date, session_number)
);

CREATE INDEX jumuah_sessions_mosque_date_idx ON jumuah_sessions (mosque_id, valid_date);
CREATE INDEX jumuah_sessions_date_idx ON jumuah_sessions (valid_date);
```

---

### `scraping_jobs`

The pipeline queue and full audit log. One row per mosque — upserted on each run.

```sql
CREATE TABLE scraping_jobs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mosque_id             UUID NOT NULL REFERENCES mosques(id) ON DELETE CASCADE UNIQUE,

    -- Queue state
    status                TEXT NOT NULL DEFAULT 'pending',
                          -- pending / running / success / failed / no_website / skipped
    priority              INTEGER NOT NULL DEFAULT 5,
                          -- 1=highest (new mosque), 10=lowest (recently scraped success)
    next_attempt_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- History
    last_attempted_at     TIMESTAMPTZ,
    last_success_at       TIMESTAMPTZ,
    attempts_count        INTEGER NOT NULL DEFAULT 0,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,

    -- Result metadata
    tier_reached          INTEGER,             -- 1-5: which tier produced the data
    error_message         TEXT,

    -- Raw evidence (kept for debugging and manual review)
    raw_html_url          TEXT,                -- URL that yielded data
    raw_extracted_json    JSONB,               -- normalized result before DB write
    image_urls_found      TEXT[],              -- images detected as potential schedules

    -- Coverage
    dates_covered_from    DATE,
    dates_covered_until   DATE,
    scraped_at            TIMESTAMPTZ,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX scraping_jobs_next_attempt_idx ON scraping_jobs (next_attempt_at)
    WHERE status IN ('pending', 'failed');
CREATE INDEX scraping_jobs_priority_idx ON scraping_jobs (priority, next_attempt_at);
```

---

### `push_subscriptions`

User notification registrations. No PII — location stored at grid cell granularity only.

```sql
CREATE TABLE push_subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Push endpoint (FCM token or Web Push subscription)
    push_token              TEXT NOT NULL UNIQUE,
    push_platform           TEXT NOT NULL,    -- fcm / webpush
    vapid_endpoint          TEXT,             -- for Web Push
    vapid_p256dh            TEXT,
    vapid_auth              TEXT,

    -- User location context (grid cell, not exact GPS)
    location_lat            DOUBLE PRECISION, -- rounded to 0.01 degrees (~1km)
    location_lng            DOUBLE PRECISION,
    timezone                TEXT NOT NULL,    -- IANA timezone

    -- Preferred mosque (optional)
    favorite_mosque_id      UUID REFERENCES mosques(id),

    -- Per-prayer notification preferences (stored as JSONB for flexibility)
    preferences             JSONB NOT NULL DEFAULT '{
        "fajr":    {"enabled": true,  "before_adhan_min": 30, "before_iqama_min": 15},
        "dhuhr":   {"enabled": true,  "before_adhan_min": 15, "before_iqama_min": 10},
        "asr":     {"enabled": true,  "before_adhan_min": 15, "before_iqama_min": 10},
        "maghrib": {"enabled": true,  "before_adhan_min": 15, "before_iqama_min": 5},
        "isha":    {"enabled": true,  "before_adhan_min": 15, "before_iqama_min": 10},
        "jumuah":  {"enabled": true,  "before_khutba_min": 60},
        "quiet_hours_start": "23:00",
        "quiet_hours_end":   "04:30",
        "fajr_override_quiet": true,
        "travel_buffer_min": 5
    }',

    -- Status
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    last_delivered_at       TIMESTAMPTZ,
    failed_count            INTEGER NOT NULL DEFAULT 0,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX push_subscriptions_active_idx ON push_subscriptions (is_active)
    WHERE is_active = TRUE;
CREATE INDEX push_subscriptions_timezone_idx ON push_subscriptions (timezone);
```

---

## Spatial Query Pattern (mosque search)

```sql
-- Find all active mosques within radius_km of user, with today's prayer schedule
SELECT
    m.id,
    m.name,
    m.lat,
    m.lng,
    m.address,
    m.timezone,
    m.website,
    m.phone,
    m.has_womens_section,
    m.wheelchair_accessible,
    ST_Distance(
        m.geom::geography,
        ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography
    ) AS distance_meters,
    ps.fajr_adhan,    ps.fajr_iqama,    ps.fajr_iqama_source,
    ps.dhuhr_adhan,   ps.dhuhr_iqama,   ps.dhuhr_iqama_source,
    ps.asr_adhan,     ps.asr_iqama,     ps.asr_iqama_source,
    ps.maghrib_adhan, ps.maghrib_iqama, ps.maghrib_iqama_source,
    ps.isha_adhan,    ps.isha_iqama,    ps.isha_iqama_source,
    ps.sunrise
FROM mosques m
LEFT JOIN prayer_schedules ps
    ON ps.mosque_id = m.id AND ps.date = :today
WHERE
    m.is_active = TRUE
    AND ST_DWithin(
        m.geom::geography,
        ST_SetSRID(ST_MakePoint(:user_lng, :user_lat), 4326)::geography,
        :radius_meters
    )
ORDER BY distance_meters ASC
LIMIT 20;
```

---

### `prayer_spots`

Community-contributed non-mosque locations where a Muslim can pray — prayer rooms in public buildings, campus prayer rooms, halal restaurants with a prayer area, rest areas, etc.

All spots are user-submitted. A spot starts in `pending` status and becomes `active` once it accumulates enough independent verifications.

```sql
CREATE TABLE prayer_spots (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    name                  TEXT NOT NULL,
    spot_type             TEXT NOT NULL,
                          -- 'prayer_room'       dedicated prayer room (mall, convention center, etc.)
                          -- 'multifaith_room'   multi-faith or meditation room
                          -- 'quiet_room'        quiet room or designated quiet area
                          -- 'community_hall'    community center or Islamic cultural center (non-mosque)
                          -- 'halal_restaurant'  restaurant with a verified prayer space
                          -- 'campus'            university / school prayer room
                          -- 'rest_area'         highway rest area or gas station
                          -- 'airport'           airport prayer room or chapel
                          -- 'hospital'          hospital chapel or quiet room
                          -- 'office'            office building prayer room
                          -- 'other'             anything else user-identified

    -- Location
    lat                   DOUBLE PRECISION NOT NULL,
    lng                   DOUBLE PRECISION NOT NULL,
    geom                  GEOMETRY(Point, 4326),
    address               TEXT,
    city                  TEXT,
    state                 TEXT,
    zip                   TEXT,
    country               CHAR(2) NOT NULL DEFAULT 'US',
    timezone              TEXT,
    google_place_id       TEXT,                   -- filled in by enrichment pipeline if matched

    -- Facilities (set initially by submitter, updated by community verifications)
    has_wudu_facilities   BOOLEAN,               -- running water for wudu available
    gender_access         TEXT DEFAULT 'unknown',
                          -- 'all'              mixed or open to everyone
                          -- 'men_only'         only suitable for men
                          -- 'women_only'       only suitable for women
                          -- 'separate_spaces'  separate areas for men and women
                          -- 'unknown'
    is_indoor             BOOLEAN,               -- indoor vs outdoor spot
    operating_hours       TEXT,                  -- free text: "24/7", "Mon-Fri 9am-5pm", etc.
    notes                 TEXT,                  -- submitter description

    -- Submission tracking (anonymous)
    submitted_by_session  TEXT,                  -- anonymous session/device ID
    submitted_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Community verification state
    status                TEXT NOT NULL DEFAULT 'pending',
                          -- 'pending'   submitted, not yet verified
                          -- 'active'    verified by community (≥3 net positive verifications)
                          -- 'rejected'  reported invalid by community (≥3 net negative)
    verification_count    INTEGER NOT NULL DEFAULT 0,  -- total positive verifications
    rejection_count       INTEGER NOT NULL DEFAULT 0,  -- total negative reports
    last_verified_at      TIMESTAMPTZ,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX prayer_spots_geom_idx ON prayer_spots USING GIST (geom);
CREATE INDEX prayer_spots_status_idx ON prayer_spots (status) WHERE status = 'active';
CREATE INDEX prayer_spots_city_state_idx ON prayer_spots (city, state);
```

---

### `prayer_spot_verifications`

One row per user verification event. Records both confirmations ("yes, this spot works") and rejections ("this is wrong / gone").

Aggregate counts are denormalized into `prayer_spots` (verification_count, rejection_count) for fast queries.

```sql
CREATE TABLE prayer_spot_verifications (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spot_id               UUID NOT NULL REFERENCES prayer_spots(id) ON DELETE CASCADE,

    -- Anonymous user identity
    session_id            TEXT NOT NULL,          -- device/session fingerprint (no PII)

    -- Vote
    is_positive           BOOLEAN NOT NULL,       -- true = confirms spot is valid
                                                  -- false = reports spot as gone/invalid

    -- Checklist (what this user confirmed — all fields optional)
    attributes            JSONB NOT NULL DEFAULT '{}',
    -- Example:
    -- {
    --   "has_prayer_space": true,
    --   "has_wudu": true,
    --   "gender_access": "all",
    --   "is_indoor": true,
    --   "operating_hours": "9am-5pm"
    -- }

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One verification per session per spot (prevents ballot stuffing)
    CONSTRAINT uq_spot_verification UNIQUE (spot_id, session_id)
);

CREATE INDEX spot_verifications_spot_idx ON prayer_spot_verifications (spot_id);
```

---

### Verification Confidence Logic

Status transitions driven by net score (verification_count − rejection_count):

| Net score | Status | Display label |
|---|---|---|
| 0–2 | `pending` | "Reported by community — not yet verified" |
| ≥ 3 | `active` | "Verified by N users" |
| ≥ 10 | `active` | "Highly verified" |
| net ≤ −3 | `rejected` | Hidden from results |

A spot with `pending` status is shown in results with a clear "unverified" disclaimer. Users are never shown rejected spots.

---

### `mosque_suggestions`

Community-submitted corrections for mosque data — iqama times, contact info, and facility details. Uses the same anonymous identity model as prayer spots (session_id + IP hash).

```sql
CREATE TABLE mosque_suggestions (
    id                      UUID PRIMARY KEY,
    mosque_id               UUID NOT NULL REFERENCES mosques(id) ON DELETE CASCADE,

    -- What is being suggested
    field_name              TEXT NOT NULL,
                            -- Iqama: fajr_iqama / dhuhr_iqama / asr_iqama / maghrib_iqama / isha_iqama
                            -- Facility: phone / website / has_womens_section / has_parking / wheelchair_accessible
    suggested_value         TEXT NOT NULL,
    current_value           TEXT,               -- snapshot at submission time (for diff display)

    -- Submission tracking (anonymous)
    submitted_by_session    TEXT NOT NULL,
    submitted_ip_hash       TEXT,               -- sha256(IP)

    -- Community consensus
    status                  TEXT NOT NULL DEFAULT 'pending',
                            -- pending / accepted / rejected / expired
    upvote_count            INTEGER NOT NULL DEFAULT 0,
    downvote_count          INTEGER NOT NULL DEFAULT 0,

    -- Auto-expiry
    expires_at              TIMESTAMPTZ,        -- iqama: 7 days, facility: 90 days

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX mosque_suggestions_mosque_idx ON mosque_suggestions (mosque_id);
CREATE INDEX mosque_suggestions_status_idx ON mosque_suggestions (status);
CREATE INDEX mosque_suggestions_expires_idx ON mosque_suggestions (expires_at) WHERE status = 'pending';
```

---

### `mosque_suggestion_votes`

One row per user vote on a suggestion. Same anti-abuse pattern as spot verifications.

```sql
CREATE TABLE mosque_suggestion_votes (
    id                      UUID PRIMARY KEY,
    suggestion_id           UUID NOT NULL REFERENCES mosque_suggestions(id) ON DELETE CASCADE,

    session_id              TEXT NOT NULL,
    ip_hash                 TEXT,               -- sha256(IP)
    is_positive             BOOLEAN NOT NULL,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_suggestion_vote_session UNIQUE (suggestion_id, session_id)
);

CREATE INDEX suggestion_votes_suggestion_idx ON mosque_suggestion_votes (suggestion_id);
CREATE INDEX suggestion_votes_ip_idx ON mosque_suggestion_votes (suggestion_id, ip_hash);
```

---

### Mosque Suggestion Consensus Logic

Different thresholds by field type (iqama times are urgent, need faster consensus):

| Field type | Accept threshold | Reject threshold | Expiry |
|-----------|-----------------|-----------------|--------|
| Iqama times | net ≥ 2 | net ≤ -2 | 7 days |
| Facility / contact | net ≥ 3 | net ≤ -2 | 90 days |

When a suggestion is accepted:
- Iqama fields → update `prayer_schedules` for today, source set to `user_submitted`
- Contact fields (phone, website) → update `mosques` table directly
- Boolean fields (has_womens_section, etc.) → update `mosques` table directly

Nightly scraper auto-closes pending suggestions when it finds fresh data for those fields.

---

## Migrations

Managed by Alembic. All schema changes go through versioned migration files. Never edit the schema directly in production.

```
server/
  alembic/
    versions/
      001_initial_schema.py
      002_add_push_subscriptions.py
      ...
    env.py
  alembic.ini
```
