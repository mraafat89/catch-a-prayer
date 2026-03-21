# Route Planner Redesign

## Why Redesign

The current planner was designed for same-day trips. Every overnight/multi-day/midnight fix has been a patch that introduces new edge cases. The fundamental issue: **all time logic uses minutes-from-midnight (0-1439) which collapses multi-day trips into a single day**.

## Design Principles

1. **Use absolute datetimes everywhere** — never minutes-from-midnight for cross-day logic
2. **Enumerate prayers first, then find mosques** — not the other way around
3. **Reject malformed data silently** — skip bad mosques, don't crash
4. **Each prayer is independent** — find the best mosque for each prayer separately, then combine into itineraries

## Algorithm (3 phases)

### Phase 1: Enumerate Prayers

Input: departure_dt, arrival_dt, origin coords, dest coords, trip_mode, prayed_prayers

```
1. Validate trip duration (max 72h)
2. Walk each calendar day from departure to arrival
3. For each day, calculate prayer times at the midpoint of that day's route segment
4. For each prayer on each day:
   - Compute prayer_start_dt (absolute datetime of adhan)
   - Compute prayer_end_dt (absolute datetime of period end)
   - If prayer_start_dt is between departure and arrival → include it
   - If prayer is in prayed_prayers → skip it
   - Apply sequential inference (Asr prayed → skip Dhuhr too)
5. Return sorted list of TripPrayer objects:
   {prayer_name, day_number, date, adhan_dt, period_end_dt, iqama_dt}
```

This gives us the EXACT list of prayers we need to plan for, in chronological order.

### Phase 2: Find Mosques Per Prayer

For each TripPrayer:

```
1. Find the route checkpoint closest to prayer_start_dt
   (e.g., if Dhuhr adhan is at 12:30 PM and we're at checkpoint X at 12:15 PM,
   search near checkpoint X)
2. Search mosques within 25 km of that checkpoint
3. If none found → expand to 50 km → 75 km
4. For each candidate mosque:
   a. Validate schedule data (reject if adhan/iqama malformed)
   b. Compute arrival time at mosque (checkpoint time + detour)
   c. Check prayer_status_at_arrival:
      - can_catch_with_imam → best
      - can_pray_solo → acceptable
      - missed → skip
   d. Score: -detour*3 + imam_bonus*10 + data_confidence*5
5. Return top 3 mosques per prayer (sorted by score)
```

### Phase 3: Build Itineraries

Group prayers into pairs (Musafir) or individual stops (Muqeem), then generate template combinations:

```
Musafir templates for 2 pairs (Dhuhr+Asr, Maghrib+Isha):
  1. All Taqdeem (combine early)
  2. All Ta'kheer (combine late)
  3. Mixed (Taqdeem first pair, Ta'kheer second)
  4. At destination (if timing allows)
  5. Separate stops (like Muqeem)

Score each itinerary:
  score = detour*2 + stops*10 + infeasible*100 - imam_catches*5
Sort ascending (best first).
```

## Data Validation Rules

**Every time value must pass validation before use:**

```python
def safe_hhmm(t: str | None) -> int | None:
    """Parse HH:MM to minutes. Returns None if malformed."""
    if not t or not isinstance(t, str) or ':' not in t:
        return None
    try:
        parts = t.split(':')
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 60 + m
    except (ValueError, IndexError):
        return None
```

**Mosque schedule validation:**

```python
def is_valid_schedule(schedule: dict) -> bool:
    """A schedule is valid if it has at least adhan times for all 5 prayers."""
    for prayer in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']:
        adhan = safe_hhmm(schedule.get(f'{prayer}_adhan'))
        if adhan is None:
            return False
    # Check chronological order
    times = [safe_hhmm(schedule[f'{p}_adhan']) for p in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']]
    for i in range(len(times) - 1):
        if times[i] >= times[i+1]:
            return False  # Not chronological
    return True
```

**If a mosque has invalid data → skip it silently and try the next one.**

## Key Differences From Current Code

| Current | Redesign |
|---------|----------|
| Uses minutes-from-midnight (0-1439) | Uses absolute datetimes |
| Checks prayer overlap with trip window | Enumerates prayers explicitly per day |
| Stale prayer patches (3h threshold, PM check) | No stale prayers possible — only future prayers included |
| Single-day schedule for entire trip | Per-day schedule at route midpoint |
| `prayer_status_at_arrival` can crash on bad data | `safe_hhmm` validates all inputs |
| Mosque search at waypoint intervals | Mosque search at prayer-time checkpoints |

## Instructions for Server/Scraping Agent

Tell the scraping agent:

> **Data Quality Rules for Prayer Schedules:**
>
> 1. Every adhan and iqama time MUST be in HH:MM 24-hour format (e.g., "13:30", not "1:30 PM" or "1330")
> 2. Validate after scraping: all 5 adhan times present, chronological order (fajr < dhuhr < asr < maghrib < isha)
> 3. Iqama must be after adhan for the same prayer (fajr_iqama > fajr_adhan)
> 4. If validation fails: store NULL for the bad field, don't store malformed strings
> 5. Add a `schedule_valid` boolean column that's TRUE only when all 5 prayers pass validation
> 6. The route planner will skip mosques where `schedule_valid = FALSE`
>
> **Add this validation function to the scraping pipeline:**
> ```python
> def validate_scraped_schedule(times: dict) -> dict:
>     """Validate and clean scraped times. Returns cleaned dict with NULLs for bad values."""
>     import re
>     TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')
>     cleaned = {}
>     for key, val in times.items():
>         if val and TIME_RE.match(str(val)):
>             h, m = val.split(':')
>             if 0 <= int(h) <= 23 and 0 <= int(m) <= 59:
>                 cleaned[key] = f"{int(h):02d}:{int(m):02d}"
>                 continue
>         cleaned[key] = None
>     return cleaned
> ```

## Client-Side Changes Needed

1. **Map route with waypoints**: When waypoints are added, the displayed polyline should show the route through ALL waypoints, not just origin→destination
2. **Arrival time per stop**: Show "Arrive ~2:30 PM" next to each mosque stop
3. **Day indicators**: For multi-day trips, show "Day 1", "Day 2" headers
4. **Next-day arrival**: Show "+1 day" or "Arrives Mar 22" when arrival is next day
5. **Sort selector**: Dropdown above itinerary list (Recommended, Least Detour, Fewest Stops, Most Imam)
