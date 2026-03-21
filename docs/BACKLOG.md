# Backlog

Items deferred to future versions.

## v1.1 — Nice to Have

### Mosque Facilities Section
Show facility chips in MosqueDetailSheet when data available:
- Wheelchair accessible
- Women's section
- Parking

API fields already returned: `has_womens_section`, `wheelchair_accessible`, `has_parking`.
Design: small tag chips below denomination, collapsible.

### Wire Multi-Day Prayer Enumeration into Trip Planner
`enumerate_trip_prayers()` and `validate_trip_duration()` are implemented and tested.
Need to refactor `build_combination_plan()` to accept per-day schedules instead of
single-day minutes-of-day. This enables proper 2-3 day trip planning with per-day
prayer stops grouped in the itinerary display.

### User Sort Options for Itineraries
Itineraries are now scored and ranked (best first). Add a sort selector UI:
- Recommended (default)
- Least detour
- Fewest stops
- Most prayers with Imam
