# Route Planning Bugs — Active

Known bugs in the travel planner discovered by real-world testing. These need to be fixed BEFORE productization.

## Critical Bugs

### 1. Stale Isha still shows when client doesn't send prayed_prayers
**Scenario**: 1 AM departure, user prayed Isha but didn't mark it in the app.
**Result**: "Isha before leaving" shown
**Root cause**: Client doesn't auto-detect that Isha was already prayed. User must manually tap "Yes I prayed" — but there's no prompt in the trip planner.
**Fix needed**:
- Option A: Trip planner UI asks "Have you prayed Isha tonight?" before planning
- Option B: Auto-detect from time of day (if it's past midnight + before Fajr, assume Isha was prayed)
- Option C: Always send current prayer status based on time (if after Isha congregation ended, auto-mark)

### 2. Fajr "no mosque" on major routes
**Scenario**: Visalia→Denver (20h), Visalia→Dallas (27h)
**Result**: "Fajr — No Mosque Found"
**Root cause**: Progressive search (25→50→75 km) isn't finding mosques along the I-15/I-40 corridor. Route goes through Las Vegas, Flagstaff, Albuquerque — all have mosques.
**Investigation needed**: Is `find_route_mosques` sampling waypoints at the right times? Is the Fajr-specific mosque search looking at the right part of the route?

### 3. NYC→DC route crashes with ValueError
**Scenario**: NYC→DC at 10 AM, 4-hour trip
**Result**: `ValueError: not enough values to unpack (expected 2, got 1)`
**Root cause**: Unknown — need to trace the exact error in the server logs.

### 4. Missing daytime prayers on overnight trips
**Scenario**: 1 AM → 9 PM (20h), should show Fajr + Dhuhr+Asr + Maghrib+Isha for the daytime portion
**Result**: Only shows Fajr + Dhuhr+Asr (Maghrib+Isha missing for the evening of the trip)
**Root cause**: The planner uses single-day schedules. A trip from 1 AM to 9 PM spans into next evening but only checks origin schedule.

### 5. User sorting not implemented
**Scenario**: User wants to sort itineraries by "least detour" or "fewest stops"
**Status**: `score_itinerary` and `rank_itineraries` functions exist in travel_planner.py but no frontend sort UI.
**Fix needed**: Add sort dropdown above itinerary list in TravelPlanView.

## How to write PROPER tests for these

Tests should call the real `build_travel_plan` function (not just helpers), seed real mosque data, and assert on the PRAYER PAIR NAMES and OPTION TYPES in the result — not just "does it return something".

Example of a GOOD test:
```python
async def test_midnight_trip_no_stale_isha():
    """1 AM departure, isha prayed → result should NOT contain maghrib_isha pair."""
    result = await build_travel_plan(...)
    pair_names = {pp["pair"] for pp in result["prayer_pairs"]}
    assert "maghrib_isha" not in pair_names
    assert "fajr" in pair_names
    assert "dhuhr_asr" in pair_names
```

Example of a BAD test (what we have now):
```python
def test_isha_overlaps_trip():
    """Just checks a boolean from a helper function."""
    assert _prayer_overlaps_trip("isha", schedule, dep, arr) is True
    # This passes but tells us NOTHING about the actual route result
```
