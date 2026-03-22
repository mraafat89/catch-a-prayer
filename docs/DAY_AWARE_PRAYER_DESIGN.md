# Day-Aware Prayer Design

## The Problem

Every feature in the app uses prayer names as strings: "fajr", "dhuhr", "asr", "maghrib", "isha". There is no concept of WHICH DAY a prayer belongs to. This causes:

1. **Route planner**: shows Day 0 Dhuhr before Day 0 Maghrib even when Dhuhr already passed and Maghrib is next
2. **Nearby mosques**: at 11 PM shows "Dhuhr — missed" instead of "Next: Fajr tomorrow"
3. **Prayed tracker**: "isha" means last night AND tonight — ambiguous
4. **Prayer ordering**: hardcoded as Fajr < Dhuhr < Asr < Maghrib < Isha, which is only true WITHIN a single day

## The Solution

**Every prayer is identified by (prayer_name, date, absolute_datetime).**

A prayer is not "Dhuhr" — it is "Dhuhr on March 21 at 12:30 PM PT". This applies everywhere:
- Route planner prayer enumeration
- Nearby mosque catching status
- Prayed tracker
- Prayer ordering/sorting
- Display in UI

## Ordering Rule

Prayers are ordered by their **absolute datetime**, not by name:

```
Day 0 Maghrib (7:15 PM Mar 21) → comes FIRST
Day 0 Isha (8:30 PM Mar 21) → second
Day 1 Fajr (5:42 AM Mar 22) → third
Day 1 Dhuhr (12:30 PM Mar 22) → fourth
Day 1 Asr (4:30 PM Mar 22) → fifth
```

NOT the old way:
```
Fajr → Dhuhr → Asr → Maghrib → Isha (WRONG for multi-day)
```

## Data Model

### TripPrayer (used in route planner)

```python
@dataclass
class TripPrayer:
    prayer_name: str          # "fajr", "dhuhr", etc.
    date: date                # which calendar day
    day_number: int           # 0 = departure day, 1 = next day, etc.
    adhan_dt: datetime        # absolute datetime of adhan (with timezone)
    iqama_dt: datetime | None # absolute datetime of iqama
    period_end_dt: datetime   # absolute datetime when prayer period ends
    schedule: dict            # the full schedule for this day at this location
```

### NearbyPrayer (used in mosque search)

```python
@dataclass
class NearbyPrayer:
    prayer_name: str
    date: date
    adhan_dt: datetime
    iqama_dt: datetime | None
    period_end_dt: datetime
    status: str               # catching status
    is_tomorrow: bool         # True if this is tomorrow's prayer (shown after all today's pass)
```

## Changes Required

### 1. Route Planner — Prayer Enumeration

`enumerate_trip_prayers()` already returns prayers with `date` and `day_number`. This is correct. But the REST of the planner must use these fields:

**Pair grouping**: Only pair prayers ON THE SAME DAY.
- Day 0 Dhuhr + Day 0 Asr = valid pair
- Day 0 Dhuhr + Day 1 Asr = INVALID (different days, different obligations)

**Ordering**: Sort by `adhan_dt` ascending, not by prayer name index.

**Stale check**: A prayer is stale if `adhan_dt < departure_dt - 3 hours`. No minutes-from-midnight needed.

**Relevance**: A prayer is relevant if its window `[adhan_dt, period_end_dt]` overlaps with `[departure_dt, arrival_dt]`. Absolute datetime comparison — no wrapping.

### 2. Route Planner — Itinerary Labels

Instead of "Dhuhr + Asr · Maghrib + Isha · Fajr", show:

For same-day trips:
```
Dhuhr + Asr (Taqdeem) · Maghrib + Isha (Ta'kheer)
```

For multi-day trips:
```
Tonight: Maghrib + Isha (Ta'kheer)
Tomorrow: Fajr · Dhuhr + Asr (Taqdeem)
```

### 3. Nearby Mosques — After All Prayers Pass

Per `PRAYER_LOGIC_RULES.md §1`: "After Isha passes, show Next: Fajr tomorrow."

The `get_next_catchable()` function should:
1. Check all today's prayers
2. If ALL have passed (it's late night), calculate TOMORROW's Fajr
3. Return: `{prayer: "fajr", status: "upcoming", is_tomorrow: True, ...}`

This requires calculating tomorrow's prayer schedule from the mosque's coordinates.

### 4. Prayed Tracker

The prayed set should be **per prayer session** (Fajr-to-Fajr boundary), which we already implemented. No change needed here — the 4 AM boundary handles the day transition correctly.

But the trip planner must sanitize prayed_prayers against departure time:
- If prayer adhan < departure → user prayed it → skip
- If prayer adhan ≥ departure → it's upcoming → include

This is already implemented.

### 5. Prayer Ordering Everywhere

Replace all hardcoded `PRAYER_ORDER = ["fajr", "dhuhr", "asr", "maghrib", "isha"]` orderings with absolute datetime sorting when dealing with multi-day or overnight context.

**Within a single day** (nearby mosques, prayed banner): the name-based order is fine.
**Across days** (route planner, multi-day trips): MUST sort by absolute datetime.

### 6. Client Display

**Route planner itinerary cards**: group stops by day when trip spans midnight.

```
Tonight (Mar 21)
  ● Maghrib + Isha at Islamic Center — 8:30 PM (Ta'kheer)

Tomorrow (Mar 22)
  ● Fajr at Masjid Denver — 5:42 AM
  ● Dhuhr + Asr at Masjid Denver — 12:30 PM (Taqdeem)
```

**Nearby mosques** (after 11 PM): show "Next: Fajr tomorrow at 5:42 AM" instead of "Isha — missed, make it up."

## Implementation Priority

1. **Route planner prayer ordering** — sort by adhan_dt, not prayer name index
2. **Route planner pair grouping** — same-day pairs only
3. **Route planner stale check** — adhan_dt < departure_dt - 3h
4. **Nearby mosques "Next Fajr tomorrow"** — after all today's prayers pass
5. **Client day headers in itinerary** — group stops by day
6. **Itinerary labels** — "Tonight" / "Tomorrow" prefixes for multi-day

## Testing

Tests must verify:

1. 6:45 PM departure 20h trip → Maghrib+Isha FIRST, then Fajr, then Dhuhr+Asr (chronological by datetime, not by name)
2. 6:45 PM departure → NO Dhuhr+Asr for TODAY (already passed)
3. 11 PM nearby search → shows "Next: Fajr tomorrow"
4. 48h trip → Day 1 and Day 2 prayers listed separately, in correct order
5. Prayed ["isha"] at 9 AM → tonight's Isha still included (adhan after departure)
6. Day 0 Dhuhr NOT paired with Day 1 Asr
7. Overnight trip 10 PM → 6 AM → only Fajr (Maghrib+Isha already passed at departure)
