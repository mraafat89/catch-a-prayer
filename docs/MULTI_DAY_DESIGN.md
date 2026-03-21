# Multi-Day Design

How every feature should handle trips and prayers spanning multiple days.

## Core Principle

**A prayer obligation is defined by (prayer_name, date).** "Isha on March 20" and "Isha on March 21" are two different obligations. Every feature must track this.

---

## 1. Prayed Tracker

### Current (broken)
- `prayedToday` = Set<string> = `{"isha", "maghrib"}`
- No date context — "isha" could mean last night or tonight
- Client sends flat array to server: `prayed_prayers: ["maghrib", "isha"]`

### Fixed Design
The prayed tracker stays simple (per-day). But the TRIP PLANNER must be smart about interpreting it:

**Rule: prayed_prayers only means "prayers whose adhan has already passed TODAY and I've prayed them."**

The server implements this by checking each prayer against departure time:
- If prayer adhan < departure time → user claims they prayed it → skip
- If prayer adhan ≥ departure time → prayer hasn't happened yet → include regardless of prayed_prayers

This means the client doesn't need to change. The server sanitizes the input.

---

## 2. Trip Planner — Prayer Enumeration

### Current (broken)
- Uses `_pair_relevant()` with minutes-from-midnight
- Single origin_schedule for all prayer times
- Stale check patches for midnight edge cases
- Fajr handled as special case with multiple fallbacks

### Fixed Design

**Step 1: Enumerate all prayers during the trip using absolute datetimes**

```
For each calendar day from departure_date to arrival_date:
    Calculate prayer schedule for that day at the route midpoint
    For each prayer (Fajr, Dhuhr, Asr, Maghrib, Isha):
        prayer_dt = absolute datetime of adhan
        if departure_dt <= prayer_dt <= arrival_dt:
            Add to trip_prayers list
```

This eliminates:
- All midnight wrapping
- All stale prayer detection
- All "is this yesterday's or today's" ambiguity

**Step 2: Find mosques for each prayer at the RIGHT location and time**

For each prayer in trip_prayers:
```
1. Find the route checkpoint closest to prayer_dt (NOT departure time)
2. Search mosques near that checkpoint
3. Check prayer_status_at_arrival using the prayer's actual time
```

This fixes the "Arizona mosque for Texas Fajr" bug — the search happens near where the driver will be AT prayer time.

**Step 3: Group into pairs (Musafir) or individual (Muqeem)**

```
Musafir: group Dhuhr+Asr and Maghrib+Isha ON THE SAME DAY
  - Day 1 Dhuhr+Asr is one pair
  - Day 2 Dhuhr+Asr is a SEPARATE pair
  - Never combine Day 1 Dhuhr with Day 2 Asr

Muqeem: each prayer is standalone
```

**Step 4: Generate itineraries from all options across all pairs**

Use the combinatorial approach (already implemented) but with per-day pairs.

---

## 3. Trip Planner — Schedule Per Day

### Current (broken)
- `origin_schedule` = one schedule for departure day
- `dest_schedule` = one schedule for arrival day
- All mid-trip mosques use origin_schedule for prayer status checks

### Fixed Design

Each mosque along the route should use the schedule for the DAY the driver passes it:

```python
for checkpoint in checkpoints:
    checkpoint_date = checkpoint["time"].date()
    checkpoint_tz = get_timezone_at(checkpoint["lat"], checkpoint["lng"])
    # Use this date for prayer schedule lookup
```

For the prayer enumeration step, calculate schedule at the route midpoint for each day:
```python
for day in range(departure_date, arrival_date + 1):
    midpoint = get_route_midpoint_for_day(checkpoints, day)
    schedule = calculate_prayer_times(midpoint.lat, midpoint.lng, day, tz_offset)
```

---

## 4. Client Display — Day Headers

For multi-day trips, the itinerary should group stops by day:

```
Day 1 — Fri, Mar 21
  ● Dhuhr + Asr at Omar Haikal Academy — 1:03 PM (Taqdeem)
  ● Maghrib + Isha at Two Rivers Mosque — 8:30 PM (Ta'kheer)

Day 2 — Sat, Mar 22
  ● Fajr at Islamic Center of Golden — 5:48 AM
```

The API already returns `minutes_into_trip` per stop. The client can compute which day each stop falls on:
```typescript
const stopDate = new Date(departureTime.getTime() + stop.minutes_into_trip * 60000);
const dayNumber = Math.floor((stopDate - departureTime) / 86400000) + 1;
```

---

## 5. API Contract Changes

### Current
```json
{
  "prayed_prayers": ["maghrib", "isha"],
  "departure_time": "2026-03-21T15:53:00Z"
}
```

### No API change needed

The server sanitizes `prayed_prayers` by checking against departure time. The client continues to send the same flat array. Backward compatible.

---

## 6. What Needs to Change (Code)

### Server — travel_planner.py

1. **DONE**: `enumerate_trip_prayers()` — per-day prayer enumeration ✓
2. **DONE**: `build_pairs_from_prayers()` — per-day pair grouping ✓
3. **DONE**: `validate_trip_duration()` — 72h max ✓
4. **DONE**: Prayed prayers sanitization (adhan before departure) ✓
5. **TODO**: Wire `enumerate_trip_prayers` into `build_travel_plan` to replace `_pair_relevant`
6. **TODO**: Per-day schedule lookup at route midpoint
7. **TODO**: Mosque search at prayer-time checkpoint (not route-pass checkpoint)

### Server — mosque_search.py
- No changes needed for multi-day support

### Client — App.tsx
1. **TODO**: Day headers in itinerary display
2. **DONE**: Arrival time per stop ✓
3. **DONE**: Next-day indicator ✓
4. **DONE**: Sort selector ✓

---

## 7. Testing Strategy

Tests must seed mosques along multi-day routes and verify:
- Day 1 prayers use Day 1 schedule
- Day 2 prayers use Day 2 schedule
- Fajr on Day 2 is found near the Day 2 route position
- Prayed prayers from before departure don't affect trip prayers
- Pairs don't cross day boundaries (Day 1 Dhuhr + Day 2 Asr = wrong)
