# Server Data Validation — Instructions for Scraping Agent

## Goal

Every prayer time stored in the database must be islamically correct and logically valid. The route planner trusts the data — bad data causes wrong prayer suggestions, crashes, and user frustration. The scraper is the PRIMARY defense. Client-side validation is only a lightweight fallback.

## Core Principle

**If scraped data fails ANY validation → fall back to calculated/estimated times and log the incident.**

Never store data you know is wrong. Calculated times from the praytimes library are always available as a safety net.

---

## Islamic Logic Rules for Validation

These are the fundamental rules about prayer times that EVERY scraped result must satisfy. These are not arbitrary — they come from how Islamic prayers work.

### Prayer Time Ranges (US/Canada, all seasons)

| Prayer | Earliest Possible | Latest Possible | What it is |
|--------|------------------|-----------------|------------|
| Fajr adhan | 03:00 | 07:30 | Dawn — always before sunrise |
| Sunrise (Shorooq) | 05:00 | 08:00 | Astronomical sunrise — Fajr period ends here |
| Dhuhr adhan | 11:00 | 13:30 | Solar noon — sun crosses meridian |
| Asr adhan | 13:30 | 18:30 | Afternoon — when shadow equals object height |
| Maghrib adhan | 16:00 | 21:30 | Sunset — Maghrib IS sunset |
| Isha adhan | 17:30 | 23:00 | Twilight disappears — darkest part of evening |

### Mandatory Chronological Order

```
Fajr < Sunrise < Dhuhr < Asr < Maghrib < Isha
```

If this order is violated, the scraper confused the fields (e.g., put Asr time in Dhuhr slot). **Discard the entire scrape**, fall back to calculated times.

### Minimum Gaps Between Prayers

These represent the minimum physical time between consecutive prayers. If the gap is smaller, the data is wrong.

| Gap | Minimum | Maximum | Why |
|-----|---------|---------|-----|
| Fajr → Sunrise | 30 min | 2.5 hours | Dawn to sunrise is never instant |
| Sunrise → Dhuhr | 3 hours | 7 hours | Morning is long |
| Dhuhr → Asr | 1.5 hours | 5 hours | Afternoon shadow takes time |
| Asr → Maghrib | 30 min | 5 hours | Asr to sunset |
| Maghrib → Isha | 30 min | 3 hours | Twilight period |

### Iqama Rules

Iqama (congregation start) is when the imam starts the prayer. It's ALWAYS after the adhan and ALWAYS before the next prayer:

| Prayer | Iqama after adhan | Iqama before next | Typical gap |
|--------|-------------------|-------------------|-------------|
| Fajr | 5 - 45 min | Must be before sunrise | 15-25 min |
| Dhuhr | 5 - 45 min | Must be before Asr adhan | 10-20 min |
| Asr | 3 - 30 min | Must be before Maghrib adhan | 5-15 min |
| Maghrib | 2 - 15 min | Must be before Isha adhan | 3-7 min |
| Isha | 5 - 45 min | Must be before midnight (technically Fajr next day) | 10-20 min |

**If iqama gap is outside these ranges → set iqama to NULL (let route planner use adhan + default offset). Don't store a wrong iqama.**

### Jumuah (Friday Prayer) Rules

- Khutba start: between 11:30 AM and 2:00 PM (always around noon)
- Prayer start: 10-60 min after khutba start
- Prayer start must be after Dhuhr adhan
- Multiple sessions: session 2 is AFTER session 1

### Special Prayer Rules

**Taraweeh:**
- Only during Ramadan
- Time: after Isha iqama (typically 15-45 min after Isha)
- Never before Isha adhan

**Eid prayer:**
- Only on Eid ul-Fitr or Eid ul-Adha dates
- Time: between sunrise and Dhuhr adhan (typically 7:00-10:00 AM)
- Takbeer time: 5-30 min before prayer time
- Never before sunrise, never after Dhuhr

**Tahajjud/Qiyam:**
- During Ramadan (last 10 nights typically)
- Time: after midnight, before Fajr
- Can be very late (1:00-4:00 AM)

---

## Validation Implementation

### Step 1: Validate Immediately After Scraping

```python
def validate_prayer_schedule(scraped: dict, lat: float, lng: float, date: date) -> tuple[dict, list[str]]:
    """
    Validate scraped prayer times against Islamic logic.
    Returns (cleaned_schedule, list_of_issues).
    If issues found: cleaned_schedule has NULLs for bad fields.
    """
    issues = []
    cleaned = {}

    # 1. Format validation — must be HH:MM
    for key, val in scraped.items():
        if val is None:
            cleaned[key] = None
            continue
        val = str(val).strip()
        # Try to normalize common formats
        val = normalize_time_format(val)  # handles "5:30", "1:30 PM", Arabic numerals
        if val and re.match(r'^\d{2}:\d{2}$', val):
            h, m = int(val[:2]), int(val[3:5])
            if 0 <= h <= 23 and 0 <= m <= 59:
                cleaned[key] = val
                continue
        cleaned[key] = None
        if 'adhan' in key or 'iqama' in key:
            issues.append(f"Malformed {key}: {scraped[key]!r}")

    # 2. Range validation
    RANGES = {
        'fajr_adhan':    (180, 450),   # 03:00 - 07:30
        'sunrise':       (300, 480),   # 05:00 - 08:00
        'dhuhr_adhan':   (660, 810),   # 11:00 - 13:30
        'asr_adhan':     (810, 1110),  # 13:30 - 18:30
        'maghrib_adhan': (960, 1290),  # 16:00 - 21:30
        'isha_adhan':    (1050, 1380), # 17:30 - 23:00
    }
    for field, (min_m, max_m) in RANGES.items():
        val = cleaned.get(field)
        if val:
            minutes = hhmm_to_minutes(val)
            if not (min_m <= minutes <= max_m):
                issues.append(f"{field}={val} outside range [{min_m//60}:{min_m%60:02d}-{max_m//60}:{max_m%60:02d}]")
                cleaned[field] = None

    # 3. Chronological order
    order = ['fajr_adhan', 'sunrise', 'dhuhr_adhan', 'asr_adhan', 'maghrib_adhan', 'isha_adhan']
    times = [hhmm_to_minutes(cleaned.get(f)) for f in order]
    valid_times = [(f, t) for f, t in zip(order, times) if t and cleaned.get(f)]
    for i in range(len(valid_times) - 1):
        if valid_times[i][1] >= valid_times[i+1][1]:
            issues.append(f"Order violation: {valid_times[i][0]}={valid_times[i][1]} >= {valid_times[i+1][0]}={valid_times[i+1][1]}")
            # Don't null individual fields — the whole scrape is suspect
            # Fall back to calculated for everything
            return _fallback_to_calculated(lat, lng, date, issues)

    # 4. Iqama validation
    IQAMA_LIMITS = {
        'fajr':    (5, 45, 'sunrise'),
        'dhuhr':   (5, 45, 'asr_adhan'),
        'asr':     (3, 30, 'maghrib_adhan'),
        'maghrib': (2, 15, 'isha_adhan'),
        'isha':    (5, 45, None),  # no hard upper bound (before midnight)
    }
    for prayer, (min_gap, max_gap, next_prayer) in IQAMA_LIMITS.items():
        adhan = cleaned.get(f'{prayer}_adhan')
        iqama = cleaned.get(f'{prayer}_iqama')
        if adhan and iqama:
            adhan_m = hhmm_to_minutes(adhan)
            iqama_m = hhmm_to_minutes(iqama)
            gap = iqama_m - adhan_m
            if gap < min_gap or gap > max_gap:
                issues.append(f"{prayer} iqama gap={gap}min (expected {min_gap}-{max_gap})")
                cleaned[f'{prayer}_iqama'] = None  # NULL bad iqama, keep adhan
            if next_prayer and cleaned.get(next_prayer):
                next_m = hhmm_to_minutes(cleaned[next_prayer])
                if iqama_m >= next_m:
                    issues.append(f"{prayer} iqama={iqama} >= {next_prayer}={cleaned[next_prayer]}")
                    cleaned[f'{prayer}_iqama'] = None

    # 5. Compare with calculated times (sanity check)
    calc = calculate_prayer_times(lat, lng, date, timezone_offset=get_tz_offset(lat, lng, date))
    if calc:
        for prayer in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']:
            scraped_adhan = cleaned.get(f'{prayer}_adhan')
            calc_adhan = calc.get(f'{prayer}_adhan')
            if scraped_adhan and calc_adhan:
                diff = abs(hhmm_to_minutes(scraped_adhan) - hhmm_to_minutes(calc_adhan))
                if diff > 60:
                    issues.append(f"{prayer} adhan off by {diff}min from calculated (scraped={scraped_adhan}, calc={calc_adhan})")
                    # Don't auto-reject — some mosques use different calc methods
                    # But log it for review

    return cleaned, issues


def _fallback_to_calculated(lat, lng, date, issues):
    """When scraped data is too wrong, use calculated times."""
    calc = calculate_prayer_times(lat, lng, date, timezone_offset=get_tz_offset(lat, lng, date))
    iqama = estimate_iqama_times(calc)
    merged = {**calc, **iqama}
    # Mark source as calculated (not scraped)
    for prayer in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']:
        merged[f'{prayer}_adhan_source'] = 'calculated'
        merged[f'{prayer}_iqama_source'] = 'estimated'
    issues.append("FALLBACK: entire schedule replaced with calculated times")
    return merged, issues
```

### Step 2: Validate Jumuah Data

```python
def validate_jumuah(session: dict, dhuhr_adhan: str) -> tuple[dict, list[str]]:
    issues = []
    cleaned = dict(session)

    khutba = cleaned.get('khutba_start')
    prayer = cleaned.get('prayer_start')
    dhuhr_m = hhmm_to_minutes(dhuhr_adhan) if dhuhr_adhan else 750  # ~12:30 default

    if khutba:
        k_m = hhmm_to_minutes(khutba)
        if not (690 <= k_m <= 840):  # 11:30 AM - 2:00 PM
            issues.append(f"Jumuah khutba={khutba} outside 11:30-14:00 range")
            cleaned['khutba_start'] = None

    if prayer:
        p_m = hhmm_to_minutes(prayer)
        if p_m < dhuhr_m:
            issues.append(f"Jumuah prayer={prayer} before dhuhr adhan={dhuhr_adhan}")
            cleaned['prayer_start'] = None
        if khutba and cleaned.get('khutba_start'):
            k_m = hhmm_to_minutes(cleaned['khutba_start'])
            if p_m < k_m:
                issues.append(f"Jumuah prayer={prayer} before khutba={khutba}")
                cleaned['prayer_start'] = None
            elif p_m - k_m > 60:
                issues.append(f"Jumuah prayer {p_m - k_m}min after khutba (too long)")

    return cleaned, issues
```

### Step 3: Validate Special Prayers

```python
def validate_special_prayer(sp: dict, schedule: dict, is_ramadan: bool) -> tuple[dict, list[str]]:
    issues = []
    cleaned = dict(sp)
    prayer_type = sp.get('prayer_type', '')

    if prayer_type == 'taraweeh':
        if not is_ramadan:
            issues.append("Taraweeh outside Ramadan — likely wrong data")
            return {}, issues
        isha_m = hhmm_to_minutes(schedule.get('isha_adhan', '20:30'))
        taraweeh_m = hhmm_to_minutes(sp.get('prayer_time'))
        if taraweeh_m and taraweeh_m < isha_m:
            issues.append(f"Taraweeh at {sp['prayer_time']} before Isha at {schedule.get('isha_adhan')}")
            cleaned['prayer_time'] = None

    elif prayer_type in ('eid_fitr', 'eid_adha'):
        sunrise_m = hhmm_to_minutes(schedule.get('sunrise', '06:30'))
        dhuhr_m = hhmm_to_minutes(schedule.get('dhuhr_adhan', '12:30'))
        eid_m = hhmm_to_minutes(sp.get('prayer_time'))
        if eid_m:
            if eid_m < sunrise_m:
                issues.append(f"Eid prayer at {sp['prayer_time']} before sunrise")
                cleaned['prayer_time'] = None
            elif eid_m > dhuhr_m:
                issues.append(f"Eid prayer at {sp['prayer_time']} after Dhuhr")
                cleaned['prayer_time'] = None
        takbeer_m = hhmm_to_minutes(sp.get('takbeer_time'))
        if takbeer_m and eid_m and takbeer_m >= eid_m:
            issues.append("Takbeer after prayer time")
            cleaned['takbeer_time'] = None

    elif prayer_type in ('tahajjud', 'qiyam'):
        # Must be after midnight, before Fajr
        fajr_m = hhmm_to_minutes(schedule.get('fajr_adhan', '05:30'))
        prayer_m = hhmm_to_minutes(sp.get('prayer_time'))
        if prayer_m and not (0 <= prayer_m <= fajr_m or prayer_m >= 1380):  # after 11 PM or before Fajr
            issues.append(f"Tahajjud at {sp['prayer_time']} not in late night window")

    return cleaned, issues
```

### Step 4: Log All Validation Incidents

Every validation issue must be logged to a table for the admin dashboard:

```sql
CREATE TABLE IF NOT EXISTS scraping_validation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mosque_id UUID REFERENCES mosques(id),
    scrape_date DATE NOT NULL,
    field_name TEXT NOT NULL,
    scraped_value TEXT,
    expected_range TEXT,
    issue_description TEXT NOT NULL,
    action_taken TEXT NOT NULL,  -- 'nulled', 'fallback_to_calculated', 'kept_with_warning'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_validation_log_date ON scraping_validation_log (scrape_date);
CREATE INDEX idx_validation_log_mosque ON scraping_validation_log (mosque_id);
```

The admin dashboard should show:
- Total validation issues per day (trending up = scraper degrading)
- Top mosques with issues (need manual review or re-scraping)
- Top issue types (helps prioritize scraper fixes)
- Percentage of mosques using calculated fallback vs real scraped data

### Step 5: One-Time Cleanup of Existing Data

Run this to find and fix current bad data:

```sql
-- Count bad schedules
SELECT COUNT(*) as bad_count,
    COUNT(*) FILTER (WHERE fajr_adhan IS NULL) as missing_fajr,
    COUNT(*) FILTER (WHERE dhuhr_adhan IS NULL) as missing_dhuhr,
    COUNT(*) FILTER (WHERE fajr_adhan >= dhuhr_adhan) as order_violation,
    COUNT(*) FILTER (WHERE fajr_adhan !~ '^\d{2}:\d{2}$') as malformed_fajr
FROM prayer_schedules
WHERE date >= CURRENT_DATE;
```

For each bad row: re-calculate using `calculate_prayer_times()` from the mosque's coordinates and save with `source = 'calculated'`.

---

## Summary

| What | When | Fail action | Log to |
|------|------|-------------|--------|
| Format check (HH:MM) | After scrape | NULL the field | validation_log |
| Range check (time of day) | After scrape | NULL the field | validation_log |
| Chronological order | After scrape | Fallback entire schedule | validation_log |
| Iqama gap check | After scrape | NULL iqama only | validation_log |
| Comparison with calculated | After scrape | Keep but flag | validation_log |
| Jumuah time check | After scrape | NULL bad fields | validation_log |
| Special prayer check | After scrape | NULL or discard | validation_log |
| Historical jump check | After scrape | Flag for review | validation_log |
| DB cleanup | Daily cron | Re-calculate | validation_log |
