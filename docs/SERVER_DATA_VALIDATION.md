# Server Data Validation — Instructions for Scraping Agent

## Goal

The prayer schedule database must NEVER contain malformed data. The route planner trusts that every `prayer_schedules` row has valid, correct times. Bad data causes crashes, wrong prayer suggestions, and user frustration.

## Validation Layers

### Layer 1: Post-Scrape Validation (before saving to DB)

After scraping a mosque's website, validate BEFORE inserting into `prayer_schedules`:

**Format check:**
- Every time field must match `^\d{2}:\d{2}$` (24-hour, zero-padded)
- Convert non-standard formats: "5:30" → "05:30", "1:30 PM" → "13:30"
- Strip whitespace, remove AM/PM, handle Arabic numerals

**Chronological order check:**
```
fajr_adhan < sunrise < dhuhr_adhan < asr_adhan < maghrib_adhan < isha_adhan
```
If this order is violated, the scraped data is wrong — discard the entire scrape for that mosque and fall back to calculated times.

**Iqama sanity checks:**
- `fajr_iqama > fajr_adhan` (iqama after adhan, always)
- `iqama - adhan` must be between 2 and 60 minutes (an iqama 3 hours after adhan is wrong)
- If iqama fails: set to NULL (let the route planner use `adhan + default_offset`)

**Prayer-specific range checks (for US/Canada):**
```
Fajr adhan:    03:00 - 07:30 (varies by season/latitude)
Sunrise:       05:00 - 08:00
Dhuhr adhan:   11:30 - 13:30
Asr adhan:     13:30 - 18:30
Maghrib adhan: 16:00 - 21:30
Isha adhan:    17:30 - 23:00
```
If a time is outside its range, it's wrong — either the scraper confused the field, or the source was garbage.

**Cross-prayer gap checks:**
- Dhuhr to Asr: at least 1.5 hours, at most 6 hours
- Asr to Maghrib: at least 30 minutes, at most 5 hours
- Maghrib to Isha: at least 30 minutes, at most 3 hours
- Fajr to sunrise: at least 30 minutes, at most 2.5 hours

If gaps are wrong, the data is likely shifted (e.g., Asr time was put in Dhuhr field).

### Layer 2: Comparison with Calculated Times

After scraping, compare scraped times with astronomically calculated times (from `praytimes` library):

```python
calc = calculate_prayer_times(lat, lng, date, timezone_offset)

for prayer in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']:
    scraped_min = hhmm_to_minutes(scraped[f'{prayer}_adhan'])
    calc_min = hhmm_to_minutes(calc[f'{prayer}_adhan'])
    diff = abs(scraped_min - calc_min)

    if diff > 60:  # More than 1 hour off from calculated
        # The scraped time is probably WRONG
        # Flag for review, don't save the scraped time
        # Use calculated as fallback
        log.warning(f"Mosque {mosque_id}: {prayer} scraped={scraped_min} calc={calc_min} diff={diff}min")
```

**Iqama should be close to adhan:**
- Fajr: 10-30 min after adhan (typical)
- Dhuhr: 10-30 min after adhan
- Asr: 5-20 min after adhan
- Maghrib: 3-10 min after adhan (shortest gap)
- Isha: 10-30 min after adhan

If scraped iqama is outside these ranges, set it to NULL.

### Layer 3: Historical Consistency

When a new scrape comes in, compare with the last known good scrape:

```python
prev = get_last_valid_schedule(mosque_id)
if prev:
    for prayer in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']:
        old_adhan = hhmm_to_minutes(prev[f'{prayer}_adhan'])
        new_adhan = hhmm_to_minutes(new[f'{prayer}_adhan'])
        diff = abs(new_adhan - old_adhan)

        if diff > 30:  # Adhan changed by more than 30 min
            # Possible scraping error — flag for review
            # Iqama can change more (mosques adjust seasonally)
            # But adhan changes gradually (1-2 min per week)
            log.warning(f"Mosque {mosque_id}: {prayer} adhan jumped {diff}min")
```

### Layer 4: One-Time Database Cleanup

Run this SQL to find and fix existing bad data:

```sql
-- Find all malformed adhan/iqama times
SELECT ps.id, m.name, ps.date,
    ps.fajr_adhan, ps.fajr_iqama,
    ps.dhuhr_adhan, ps.dhuhr_iqama,
    ps.asr_adhan, ps.asr_iqama,
    ps.maghrib_adhan, ps.maghrib_iqama,
    ps.isha_adhan, ps.isha_iqama
FROM prayer_schedules ps
JOIN mosques m ON m.id = ps.mosque_id
WHERE ps.date >= CURRENT_DATE
AND (
    -- Check for non-HH:MM format
    ps.fajr_adhan !~ '^\d{2}:\d{2}$'
    OR ps.dhuhr_adhan !~ '^\d{2}:\d{2}$'
    OR ps.asr_adhan !~ '^\d{2}:\d{2}$'
    OR ps.maghrib_adhan !~ '^\d{2}:\d{2}$'
    OR ps.isha_adhan !~ '^\d{2}:\d{2}$'
    -- Check for NULL adhans (missing data)
    OR ps.fajr_adhan IS NULL
    OR ps.dhuhr_adhan IS NULL
    OR ps.asr_adhan IS NULL
    OR ps.maghrib_adhan IS NULL
    OR ps.isha_adhan IS NULL
    -- Check for wrong chronological order
    OR ps.fajr_adhan >= ps.dhuhr_adhan
    OR ps.dhuhr_adhan >= ps.asr_adhan
    OR ps.asr_adhan >= ps.maghrib_adhan
    OR ps.maghrib_adhan >= ps.isha_adhan
    -- Check for obviously wrong times
    OR ps.fajr_adhan < '03:00' OR ps.fajr_adhan > '07:30'
    OR ps.dhuhr_adhan < '11:30' OR ps.dhuhr_adhan > '13:30'
    OR ps.maghrib_adhan < '16:00' OR ps.maghrib_adhan > '21:30'
);

-- For bad rows: replace with calculated times
-- The scraping agent should re-calculate and update these
```

### Layer 5: Continuous Monitoring

Add a daily check (cron job) that:
1. Counts mosques with valid vs invalid schedules
2. Alerts if invalid count increases
3. Re-calculates schedules for mosques that failed validation
4. Logs the `schedule_valid` flag per mosque

## Summary

| Layer | When | What | Action on failure |
|-------|------|------|-------------------|
| Format | After scrape | Regex + range check | Clean or NULL the field |
| Chronological | After scrape | Order check | Discard entire scrape |
| Calculated comparison | After scrape | Diff > 60 min | Flag for review, use calculated |
| Historical | After scrape | Diff > 30 min from last good | Flag for review |
| DB cleanup | One-time + daily | SQL query for bad data | Re-calculate |
