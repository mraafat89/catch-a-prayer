# Prayer Spots in Route Planning

Extends the route planner to include prayer spots (prayer rooms, rest areas, etc.) as stop options alongside mosques.

---

## Problem

The route planner only searches mosques. On long highway drives (e.g., I-10, I-40), mosques may be 50+ km off the route. Prayer spots — rest areas, campus prayer rooms, airport prayer rooms — are often closer to the highway and give the traveler a place to pray even without a congregation.

---

## Design

### What is a prayer spot?

A prayer spot is any non-mosque location where someone can pray. Examples: rest areas, airport prayer rooms, campus rooms, hospital quiet rooms, halal restaurants with prayer space.

Key differences from mosques:

| | Mosque | Prayer Spot |
|---|---|---|
| Iqama time | Yes (scraped or estimated) | No — pray anytime from adhan |
| Imam / congregation | Yes | No |
| Catching status | can_catch_with_imam, in_progress, solo | pray_solo only |
| Adhan source | DB schedule or calculated | Calculated at spot's lat/lng |
| Scoring bonus | +10 imam catch, +5 in-progress | 0 (no imam bonus) |
| Data confidence | high (scraped) or medium (calc) | medium (always calculated) |

### Adhan time for prayer spots

1. **Primary**: Calculate using `calculate_prayer_times(spot.lat, spot.lng, date, tz_offset)` — the praytimes library with ISNA method.
2. **Augmentation** (future): If a mosque with real scraped schedule exists within 5 km of the spot, use that mosque's adhan times instead (more accurate for the local area). Not in v1.

### How prayer spots enter the route planner

**`find_route_mosques`** gains a second query against `prayer_spots` table:

```sql
SELECT DISTINCT ON (id) id::text, name, lat, lng, address, city, state,
       timezone, spot_type, has_wudu_facilities, is_indoor, gender_access
FROM prayer_spots
WHERE status = 'active' AND ({same_bbox_OR_clauses})
LIMIT 500
```

Each prayer spot result is processed identically to a mosque (checkpoint distance, detour calc, timezone conversion) but:
- Schedule is always calculated (no `prayer_schedules` table lookup)
- No iqama times in the schedule — iqama fields are `null`
- `is_prayer_spot = true` flag added to the result dict
- `spot_type` field carried through (e.g., "rest_area", "airport")

**`fetch_anchor_mosques`** gets the same treatment for origin/destination spots.

### Combined result list

Route mosques and route prayer spots are merged into one list, sorted by detour. Downstream functions (`build_combination_plan`, `_build_solo_plan`, `_pick_best_mosque`) already work with the dict format — they just need to handle `null` iqama gracefully.

### Scoring adjustments

In `_score_mosque_for_prayer`:
- Mosque with imam catch: +10 bonus
- Mosque pray solo: +0
- Prayer spot: +0 (no imam), but no penalty either
- Prayer spots with `has_wudu_facilities = true`: +2 bonus
- Prayer spots that are `is_indoor = true`: +1 bonus

This means mosques with congregation naturally rank higher, but prayer spots fill gaps where no mosque exists.

### Catching status for prayer spots

Since there's no iqama, the status is always:
- `can_pray_solo` — if arrival is between adhan and period end
- `prayer_not_started` — if arrival is before adhan (rare, would need to wait)

No `can_catch_with_imam` or `in_progress` variants.

---

## API Response Changes

### TravelStop schema additions (backwards-compatible)

```python
# New optional fields
is_prayer_spot: bool = False        # true for prayer spots, false for mosques
spot_type: Optional[str] = None     # "rest_area", "airport", etc. (null for mosques)
has_wudu: Optional[bool] = None     # wudu facilities available?
is_indoor: Optional[bool] = None    # indoor prayer space?
```

These are additive — existing clients ignore them. The `mosque_name`, `mosque_id`, `mosque_lat`, `mosque_lng` fields are reused (they apply to any stop, not just mosques).

### Client display

Prayer spots show differently from mosques in the itinerary card:
- Icon: location pin instead of mosque icon
- Label: spot type (e.g., "Rest Area", "Airport Prayer Room")
- Time: "Adhan ~HH:MM" instead of "Iqama HH:MM"
- No "catch with imam" badge — just "Pray on your own"
- Optional badges: "Wudu available", "Indoor"

---

## Query performance

Prayer spots table is small (~hundreds of rows in US/Canada) vs mosques (~thousands). The same bbox approach works. The `prayer_spots_geom_idx` gist index exists but the bbox query uses lat/lng columns directly (same pattern as mosques).

---

## What this does NOT change

- Prayer spot submission/verification flow (unchanged)
- Nearby mosque search (already separate — could add spots later)
- Mosque scoring for non-route views
- Multi-day trip logic (prayer spots participate identically to mosques in day enumeration)

---

## Implementation order

1. Add prayer spots query to `find_route_mosques` and `fetch_anchor_mosques`
2. Handle null iqama in `_score_mosque_for_prayer` and `calculate_catching_status`
3. Add `is_prayer_spot`, `spot_type`, `has_wudu`, `is_indoor` to TravelStop schema
4. Update client to display prayer spots differently
5. Tests
