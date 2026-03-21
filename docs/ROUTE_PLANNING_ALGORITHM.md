# Route Planning Algorithm

Detailed specification for the "Pray on Route" travel planner. Covers mosque discovery, scoring, itinerary generation, ranking, and edge cases.

---

## Overview

```
User Input                    Algorithm                         Output
─────────                    ─────────                         ──────
origin + dest + waypoints → 1. Build route checkpoints      → 3-5 ranked itineraries
departure time             → 2. Find mosques along corridor     each with:
travel mode (Muqeem/Musafir) → 3. Score & rank mosques           - mosque stops
prayed prayers             → 4. Generate itinerary templates     - detour cost
                           → 5. Score & rank itineraries         - route geometry
                           → 6. Compute per-itinerary geometry   - feasibility
```

---

## Step 1: Build Route Checkpoints

Input: Mapbox route geometry (polyline coordinates)

1. Walk all geometry points, computing cumulative haversine distance
2. Interpolate time at each point: `estimated_time = departure + (cumulative_dist / total_dist) * total_duration`
3. Deduplicate points within 0.1 km
4. Sample waypoints at **30-minute intervals** along the trip
5. For multi-day trips: checkpoints span the full duration (not just 24 hours)

Output: List of `(lat, lng, estimated_arrival_datetime)` checkpoints

**Fallback**: If Mapbox fails, create minimal checkpoints from origin + user waypoints + destination with straight-line interpolation.

---

## Step 2: Find Mosques Along Corridor

For each 30-minute checkpoint:

1. Query mosques within **25 km radius** (PostGIS spatial query)
2. For each mosque:
   - Compute detour: `haversine(checkpoint, mosque) * 2 * 1.3 / 60` (round trip, road factor, highway speed)
   - Skip if detour > MAX_DETOUR_MINUTES (60 min default)
   - Convert checkpoint arrival time to mosque's local timezone
   - Fetch prayer schedule for that specific LOCAL DATE
3. Deduplicate mosques found from multiple checkpoints (keep earliest arrival)

**Anchor mosques**: Also search near origin and destination (10 km radius). Compute ACTUAL detour for these (not hardcoded 0).

### Progressive Radius Search

If no mosque found for a prayer at 25 km:
1. Expand to **50 km** → retry for that prayer only
2. Expand to **75 km** → retry
3. Still none: return nearest mosque at any distance as fallback, marked with `feasible: false` and detour info

---

## Step 3: Score & Rank Mosques Per Prayer

For each prayer that overlaps the trip window, score all candidate mosques:

```
mosque_score = (
    - detour_minutes * 3.0          # penalize long detours
    + iqama_alignment_bonus         # +10 if arrival is within congregation window
    + data_confidence_bonus         # +5 for scraped data, +2 for IslamicFinder, 0 for calculated
)
```

**iqama_alignment_bonus**:
- Arrive before iqama → `can_catch_with_imam` → +10
- Arrive during congregation (iqama + 15 min) → `can_catch_with_imam_in_progress` → +5
- Arrive after congregation → `can_pray_solo` → 0

Select the **top 2-3 mosques** per prayer (not just the first one found). This allows different itineraries to use different mosques.

---

## Step 4: Generate Itinerary Templates

### Musafir Mode (combining allowed)

Prayer pairs: [Dhuhr+Asr, Maghrib+Isha], Fajr standalone.

For each pair, generate options:
- **combine_early (Jam' Taqdeem)**: Both prayers at prayer1's mosque/time
- **combine_late (Jam' Ta'kheer)**: Both prayers at prayer2's mosque/time
- **at_destination**: Pray at arrival if timing allows
- **pray_before**: Pray before departure if prayer window is open

Templates (combinations across pairs):
1. All Taqdeem (all early) — minimizes stops
2. Mixed (Taqdeem pair 1, Ta'kheer pair 2)
3. All Ta'kheer (all late) — maximum flexibility
4. All at destination — zero detour if timing works
5. Separate stops — individual stop per prayer (like Muqeem)

### Muqeem Mode (no combining)

Each prayer gets its own stop:
1. En-route stops (best mosque per prayer)
2. Pray before departure + en-route
3. All at destination

### Standalone Fajr

If trip starts late evening or spans overnight:
- Find a mosque near the overnight point for Fajr
- Or find Fajr mosque near destination for early morning arrival

---

## Step 5: Score & Rank Itineraries

Each itinerary is scored:

```
itinerary_score = (
    total_detour_minutes * 2        # main cost factor
    + stop_count * 10               # fewer stops preferred
    + infeasible_count * 100        # missing a prayer is very bad
    - imam_catch_count * 5          # bonus for catching with imam
)
```

Lower score = better. Sort ascending.

**The best-scored itinerary is shown first and auto-selected.**

---

## Step 6: User Sort Options

After initial ranking, user can re-sort:

| Sort Option | Sort Key | Use Case |
|-------------|----------|----------|
| Recommended | itinerary_score (default) | Balanced choice |
| Least detour | total_detour_minutes ASC | "I'm in a hurry" |
| Fewest stops | stop_count ASC, detour tiebreak | "I don't want to stop often" |
| Most prayers with Imam | imam_catch_count DESC | "I want to pray with congregation" |

Sort selector is a small dropdown above the itinerary list.

---

## Step 7: Per-Itinerary Route Geometry

For each itinerary:
1. Collect all mosque stops, sorted by minutes_into_trip
2. Insert mosque stops as waypoints between user waypoints in route order
3. Query Mapbox Directions with full waypoint list
4. Sample every 4th coordinate for performance
5. Convert to [lat, lng] for Leaflet

Computed in parallel (asyncio.gather) for all itineraries.

Fallback: If Mapbox fails, use the base route geometry (direct path without mosque stops).

---

## Multi-Day Trip Handling

### Date Tracking

For trips > 24 hours:
- Each checkpoint carries an absolute datetime (not just minutes-of-day)
- Prayer schedule fetched per DATE per LOCATION
- The same prayer (e.g., Fajr) may appear multiple times for different days

### Display Grouping

Itinerary stops are grouped by day:

```
Day 1 — Thu, Mar 20
  ● Dhuhr + Asr at Islamic Center — 1:15 PM (8 min detour)

Day 2 — Fri, Mar 21
  ● Fajr at Masjid Al-Noor — 5:45 AM (12 min detour)
  ● Jumu'ah at Downtown Mosque — 1:00 PM (5 min detour)
  ● Maghrib + Isha at Mosque of Raleigh — 7:30 PM (3 min detour)
```

### Prayed State Per Day

- Marking Fajr as prayed on Day 1 does NOT affect Day 2's Fajr
- The prayed_prayers parameter should include day info: `["day1:fajr", "day1:dhuhr", "day1:asr"]`
- Or simpler: only track today's prayed prayers, assume previous days are fully prayed

---

## Timezone Crossing

### The Problem

A trip from NYC (ET) to Chicago (CT) crosses a timezone boundary. Prayer times in Chicago are in CT, not ET.

### The Solution

1. Each checkpoint has an absolute UTC datetime
2. When checking a mosque's prayer schedule:
   - Convert checkpoint time to mosque's local timezone: `local_time = checkpoint_utc.astimezone(mosque_tz)`
   - Use `local_time.date()` to fetch the correct day's schedule
   - Use `local_time.hour * 60 + local_time.minute` for time comparisons
3. Destination schedule: use `arrival_dt.astimezone(dest_tz).date()` (NOT departure date)
4. DST: always use `ZoneInfo` (not fixed offsets) — Python handles DST transitions automatically

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| No mosque within 25 km | Progressive search: 50 km → 75 km → show fallback |
| All mosques exceed 60 min detour | Show nearest with "long detour" warning |
| Trip is entirely at night (11 PM → 6 AM) | Plan Isha (if not prayed) + Fajr |
| Trip departs during Isha, arrives next day afternoon | Plan: Isha tonight + Fajr tomorrow + Dhuhr+Asr tomorrow |
| Trip crosses 3 timezones | Each mosque uses its own TZ, each checkpoint converts correctly |
| Destination has no mosque within radius | Use calculated prayer times at destination coordinates |
| Jumu'ah falls during trip (Friday) | Include Jumu'ah as a prayer stop option (khutba + prayer time) |
| User already prayed some prayers | Skip prayed pairs, plan remaining only |
| All prayers already prayed | Show "All prayers completed for today!" — no stops needed |
| Mapbox routing fails | Fallback to straight-line checkpoints with haversine distance |

---

## Known Bugs to Fix

| Bug | Current Behavior | Fix |
|-----|-----------------|-----|
| Destination schedule date | Uses departure date | Use `arrival_dt.astimezone(dest_tz).date()` |
| Anchor mosque detour = 0 | Hardcoded | Compute actual haversine detour |
| Timezone offset from departure_dt | May be wrong for DST | Use arrival_dt for offset |
| Upcoming window uses iqama | Shows prayer too late | Use adhan for 2-hour window |
| Mosque selection: first found | May not be optimal | Score by detour + iqama alignment |
| No ranking of itineraries | Random template order | Score and sort by itinerary_score |
| Multi-day: only 1 day of prayers | Misses intermediate days | Track per-day with absolute datetimes |
| No progressive radius search | Empty "no mosque" message | Expand 25→50→75 km with fallback |
