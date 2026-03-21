"""
END-TO-END route planning tests that call the REAL build_travel_plan function.

These tests seed mosques in the DB, mock the routing API to return synthetic
but realistic routes, then assert that the prayer plan output is CORRECT:
- Which prayer pairs appear (by name)
- Which prayers do NOT appear (stale ones)
- Chronological ordering of pairs
- Multiple itinerary options generated
- No crashes

Each test is a real-world scenario that has historically been broken.
"""
import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta
from unittest.mock import patch, AsyncMock
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import new_uuid
from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times
from app.services.travel_planner import build_travel_plan

ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")
PT = ZoneInfo("America/Los_Angeles")
MT = ZoneInfo("America/Denver")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _schedule_for(lat: float, lng: float, d: date, tz_offset: float) -> dict:
    calc = calculate_prayer_times(lat, lng, d, timezone_offset=tz_offset)
    return {**calc, **estimate_iqama_times(calc)}


def _make_route(origin: tuple, dest: tuple, duration_hours: float, n_points: int = 20) -> dict:
    """Build a synthetic route dict resembling Mapbox Directions API response."""
    olat, olng = origin
    dlat, dlng = dest
    duration_sec = duration_hours * 3600

    # Generate intermediate coordinates along a straight line
    coords = []
    for i in range(n_points + 1):
        frac = i / n_points
        lat = olat + (dlat - olat) * frac
        lng = olng + (dlng - olng) * frac
        coords.append([lng, lat])

    # Approximate distance using haversine
    from app.services.mosque_search import haversine_km
    dist_km = haversine_km(olat, olng, dlat, dlng)

    return {
        "duration": duration_sec,
        "distance": dist_km * 1000,
        "geometry": {"type": "LineString", "coordinates": coords},
        "legs": [{
            "steps": [
                {
                    "maneuver": {"location": coords[i]},
                    "duration": duration_sec / n_points,
                }
                for i in range(n_points + 1)
            ]
        }],
    }


async def _seed_mosque(
    db: AsyncSession,
    name: str,
    lat: float,
    lng: float,
    tz_str: str,
    schedule_date: date,
    schedule: dict,
) -> str:
    """Seed a mosque + prayer schedule directly via SQL."""
    mosque_id = new_uuid()
    await db.execute(text("""
        INSERT INTO mosques (id, name, lat, lng, geom, timezone, country, is_active, verified, places_enriched)
        VALUES (:id, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                :tz, 'US', true, false, false)
    """), {"id": mosque_id, "name": name, "lat": lat, "lng": lng, "tz": tz_str})

    sched_id = new_uuid()
    params = {"id": sched_id, "mosque_id": mosque_id, "date": schedule_date}
    for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
        params[f"{prayer}_adhan"] = schedule.get(f"{prayer}_adhan")
        params[f"{prayer}_iqama"] = schedule.get(f"{prayer}_iqama")
        params[f"{prayer}_adhan_source"] = "calculated"
        params[f"{prayer}_iqama_source"] = "estimated"
        params[f"{prayer}_adhan_confidence"] = "medium"
        params[f"{prayer}_iqama_confidence"] = "low"
    params["sunrise"] = schedule.get("sunrise", "06:30")
    params["sunrise_source"] = "calculated"
    cols = ", ".join(params.keys())
    vals = ", ".join(f":{k}" for k in params.keys())
    await db.execute(text(f"INSERT INTO prayer_schedules ({cols}) VALUES ({vals})"), params)

    await db.commit()
    return mosque_id


async def _seed_route_mosques(db: AsyncSession, route_points: list[dict], schedule_date: date):
    """Seed mosques along a route. Each point: {name, lat, lng, tz, tz_offset}."""
    for pt in route_points:
        sched = _schedule_for(pt["lat"], pt["lng"], schedule_date, pt["tz_offset"])
        await _seed_mosque(db, pt["name"], pt["lat"], pt["lng"], pt["tz"], schedule_date, sched)


async def _seed_multi_day_mosques(db: AsyncSession, route_points: list[dict], dates: list[date]):
    """Seed mosques with schedules for multiple dates."""
    for pt in route_points:
        mosque_id = new_uuid()
        await db.execute(text("""
            INSERT INTO mosques (id, name, lat, lng, geom, timezone, country, is_active, verified, places_enriched)
            VALUES (:id, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                    :tz, 'US', true, false, false)
        """), {"id": mosque_id, "name": pt["name"], "lat": pt["lat"], "lng": pt["lng"], "tz": pt["tz"]})

        for d in dates:
            sched = _schedule_for(pt["lat"], pt["lng"], d, pt["tz_offset"])
            sched_id = new_uuid()
            params = {"id": sched_id, "mosque_id": mosque_id, "date": d}
            for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
                params[f"{prayer}_adhan"] = sched.get(f"{prayer}_adhan")
                params[f"{prayer}_iqama"] = sched.get(f"{prayer}_iqama")
                params[f"{prayer}_adhan_source"] = "calculated"
                params[f"{prayer}_iqama_source"] = "estimated"
                params[f"{prayer}_adhan_confidence"] = "medium"
                params[f"{prayer}_iqama_confidence"] = "low"
            params["sunrise"] = sched.get("sunrise", "06:30")
            params["sunrise_source"] = "calculated"
            cols = ", ".join(params.keys())
            vals = ", ".join(f":{k}" for k in params.keys())
            await db.execute(text(f"INSERT INTO prayer_schedules ({cols}) VALUES ({vals})"), params)

        await db.commit()


# Common route mosque sets
NYC_TO_DC_MOSQUES = [
    {"name": "Masjid Manhattan", "lat": 40.71, "lng": -74.00, "tz": "America/New_York", "tz_offset": -4},
    {"name": "Masjid Newark", "lat": 40.73, "lng": -74.17, "tz": "America/New_York", "tz_offset": -4},
    {"name": "Masjid Edison", "lat": 40.52, "lng": -74.41, "tz": "America/New_York", "tz_offset": -4},
    {"name": "Masjid Trenton", "lat": 40.22, "lng": -74.74, "tz": "America/New_York", "tz_offset": -4},
    {"name": "Masjid Philadelphia", "lat": 39.95, "lng": -75.17, "tz": "America/New_York", "tz_offset": -4},
    {"name": "Masjid Baltimore", "lat": 39.29, "lng": -76.61, "tz": "America/New_York", "tz_offset": -4},
    {"name": "Masjid DC", "lat": 38.90, "lng": -77.04, "tz": "America/New_York", "tz_offset": -4},
]

LA_TO_DENVER_MOSQUES = [
    {"name": "Islamic Center LA", "lat": 34.05, "lng": -118.24, "tz": "America/Los_Angeles", "tz_offset": -7},
    {"name": "Masjid Barstow", "lat": 34.90, "lng": -117.02, "tz": "America/Los_Angeles", "tz_offset": -7},
    {"name": "Masjid Las Vegas", "lat": 36.17, "lng": -115.14, "tz": "America/Los_Angeles", "tz_offset": -7},
    {"name": "Masjid St George", "lat": 37.10, "lng": -113.58, "tz": "America/Denver", "tz_offset": -6},
    {"name": "Masjid Grand Junction", "lat": 39.06, "lng": -108.55, "tz": "America/Denver", "tz_offset": -6},
    {"name": "Masjid Glenwood Springs", "lat": 39.55, "lng": -107.33, "tz": "America/Denver", "tz_offset": -6},
    {"name": "Islamic Center Denver", "lat": 39.74, "lng": -104.99, "tz": "America/Denver", "tz_offset": -6},
]

VISALIA_TO_DALLAS_MOSQUES = [
    {"name": "Masjid Visalia", "lat": 36.33, "lng": -119.29, "tz": "America/Los_Angeles", "tz_offset": -7},
    {"name": "Masjid Barstow", "lat": 34.90, "lng": -117.02, "tz": "America/Los_Angeles", "tz_offset": -7},
    {"name": "Masjid Flagstaff", "lat": 35.20, "lng": -111.65, "tz": "America/Denver", "tz_offset": -7},
    {"name": "Masjid Albuquerque", "lat": 35.08, "lng": -106.65, "tz": "America/Denver", "tz_offset": -6},
    {"name": "Masjid Amarillo", "lat": 35.22, "lng": -101.83, "tz": "America/Chicago", "tz_offset": -5},
    {"name": "Masjid Lubbock", "lat": 33.58, "lng": -101.85, "tz": "America/Chicago", "tz_offset": -5},
    {"name": "Masjid Dallas", "lat": 32.78, "lng": -96.80, "tz": "America/Chicago", "tz_offset": -5},
]


def _get_pair_names(result: dict) -> set:
    """Extract prayer pair keys from a build_travel_plan result."""
    return {pp["pair"] for pp in result["prayer_pairs"]}


def _get_pair_order(result: dict) -> list:
    """Extract ordered list of prayer pair keys."""
    return [pp["pair"] for pp in result["prayer_pairs"]]


def _get_option_types(result: dict) -> dict:
    """Map pair name -> set of option types available."""
    out = {}
    for pp in result["prayer_pairs"]:
        out[pp["pair"]] = {opt["option_type"] for opt in pp["options"]}
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 1: Stale Isha shows as "pray before leaving" at 1 AM
# ═══════════════════════════════════════════════════════════════════════════════

class TestBug1StaleIshaAtMidnight:
    """
    At 1 AM departure, Isha (adhan ~8:30 PM) is 4.5 hours old.
    The planner should NOT show "Pray Maghrib+Isha before leaving".
    Even if _prayer_overlaps_trip returns True (technically the Isha window
    extends to Fajr), the stale check must suppress it.
    """

    @pytest.mark.asyncio
    async def test_1am_departure_no_stale_isha_pair(self, db_session):
        """1 AM departure, 6-hour trip (arrives 7 AM): Maghrib+Isha should NOT appear (stale).
        Fajr SHOULD appear since arrival is after Fajr adhan (~5:37 AM)."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=6.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 1, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        pairs = _get_pair_names(result)
        # Isha adhan was ~20:30, departure at 01:00 — 4.5 hours stale
        # Stale check should suppress both prayers in the pair
        assert "maghrib_isha" not in pairs, (
            f"Stale Maghrib+Isha should not appear at 1 AM. Got pairs: {pairs}"
        )
        # Fajr should be present — trip arrives 7 AM, past Fajr adhan (~5:37)
        assert "fajr" in pairs, f"Fajr should appear for 1 AM-7 AM trip. Got pairs: {pairs}"

    @pytest.mark.asyncio
    async def test_1am_departure_with_prayed_isha(self, db_session):
        """1 AM departure, Isha marked as prayed: definitely no Maghrib+Isha."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=4.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 1, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
                prayed_prayers={"isha"},
            )

        assert result is not None
        pairs = _get_pair_names(result)
        assert "maghrib_isha" not in pairs


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 2: Fajr "no mosque" on major routes
# ═══════════════════════════════════════════════════════════════════════════════

class TestBug2FajrNoMosque:
    """
    Long trips (15-27 hours) should find Fajr mosques along the corridor.
    The progressive search should expand to 50/75 km to find mosques.
    """

    @pytest.mark.asyncio
    async def test_la_to_denver_fajr_found(self, db_session):
        """LA to Denver (15h), 6 PM departure. Fajr should find a mosque."""
        d = date(2026, 3, 21)
        d2 = date(2026, 3, 22)
        route = _make_route((34.05, -118.24), (39.74, -104.99), duration_hours=15.0)

        # Seed mosques with schedules for both dates
        await _seed_multi_day_mosques(db_session, LA_TO_DENVER_MOSQUES, [d, d2])

        dep = datetime(2026, 3, 21, 18, 0, tzinfo=PT)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=34.05, origin_lng=-118.24,
                dest_lat=39.74, dest_lng=-104.99,
                destination_name="Denver, CO",
                timezone_str="America/Los_Angeles",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        pairs = _get_pair_names(result)
        assert "fajr" in pairs, f"Fajr should appear on overnight LA->Denver trip. Got: {pairs}"

        # Check that Fajr has an actual mosque option (not just "no mosque found")
        fajr_pair = next(pp for pp in result["prayer_pairs"] if pp["pair"] == "fajr")
        option_types = {opt["option_type"] for opt in fajr_pair["options"]}
        has_mosque_option = "stop_for_fajr" in option_types or "at_destination" in option_types
        assert has_mosque_option, (
            f"Fajr should have a mosque option. Got option types: {option_types}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 3: NYC->DC crashes with ValueError
# ═══════════════════════════════════════════════════════════════════════════════

class TestBug3NYCToDCCrash:
    """
    NYC to DC at 10 AM should not crash with ValueError.
    """

    @pytest.mark.asyncio
    async def test_nyc_to_dc_10am_no_crash(self, db_session):
        """Standard 10 AM NYC->DC trip should complete without errors."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=4.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 10, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        assert "prayer_pairs" in result
        assert "itineraries" in result
        assert "route" in result

    @pytest.mark.asyncio
    async def test_nyc_to_dc_has_dhuhr_asr(self, db_session):
        """10 AM - 2 PM trip should show Dhuhr+Asr pair."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=4.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 10, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        pairs = _get_pair_names(result)
        assert "dhuhr_asr" in pairs, f"Dhuhr+Asr should appear on 10AM-2PM trip. Got: {pairs}"

    @pytest.mark.asyncio
    async def test_nyc_to_dc_itinerary_count(self, db_session):
        """Should generate at least 2 itineraries."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=4.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 10, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        assert len(result["itineraries"]) >= 2, (
            f"Should have >=2 itineraries. Got {len(result['itineraries'])}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 4: Missing daytime prayers on overnight trips
# ═══════════════════════════════════════════════════════════════════════════════

class TestBug4MissingPrayersOvernightTrip:
    """
    A 1 AM to 9 PM trip (20 hours) should show:
    - Fajr (morning)
    - Dhuhr+Asr (afternoon)
    - Maghrib+Isha (evening)

    Bug: planner uses single-day schedules and misses evening prayers.
    """

    @pytest.mark.asyncio
    async def test_1am_to_9pm_all_prayers_present(self, db_session):
        """1 AM - 9 PM same day: Fajr + Dhuhr+Asr + Maghrib+Isha."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=20.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 1, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        pairs = _get_pair_names(result)
        assert "fajr" in pairs, f"Fajr should appear on 1AM-9PM trip. Got: {pairs}"
        assert "dhuhr_asr" in pairs, f"Dhuhr+Asr should appear on 1AM-9PM trip. Got: {pairs}"
        assert "maghrib_isha" in pairs, (
            f"Maghrib+Isha should appear on 1AM-9PM trip (arrives 9PM). Got: {pairs}"
        )

    @pytest.mark.asyncio
    async def test_10pm_to_6pm_next_day(self, db_session):
        """10 PM - 6 PM next day (20h): should show Fajr + Dhuhr+Asr."""
        d = date(2026, 3, 21)
        d2 = date(2026, 3, 22)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=20.0)
        await _seed_multi_day_mosques(db_session, NYC_TO_DC_MOSQUES, [d, d2])

        dep = datetime(2026, 3, 21, 22, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        pairs = _get_pair_names(result)
        # Overnight into next day: should have Fajr + Dhuhr+Asr at minimum
        assert "fajr" in pairs, f"Fajr missing on overnight trip. Got: {pairs}"
        assert "dhuhr_asr" in pairs, f"Dhuhr+Asr missing on overnight trip. Got: {pairs}"


# ═══════════════════════════════════════════════════════════════════════════════
# BUG 5: Only 1-2 itineraries for long trips
# ═══════════════════════════════════════════════════════════════════════════════

class TestBug5InsufficientItineraries:
    """
    Long trips with multiple prayer pairs should generate 3-5 itineraries
    (different strategies: all early, all late, mixed, etc.)
    """

    @pytest.mark.asyncio
    async def test_full_day_trip_multiple_itineraries(self, db_session):
        """8 AM - 10 PM trip (14h) with Dhuhr+Asr + Maghrib+Isha."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=14.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 8, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        n_pairs = len(result["prayer_pairs"])
        n_itin = len(result["itineraries"])
        assert n_pairs >= 2, f"Full day trip should have >=2 pairs. Got {n_pairs}"
        assert n_itin >= 3, (
            f"Full day trip with {n_pairs} pairs should have >=3 itineraries. Got {n_itin}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CHRONOLOGICAL ORDERING
# ═══════════════════════════════════════════════════════════════════════════════

class TestChronologicalOrdering:
    """Prayer pairs must appear in chronological order within each day."""

    @pytest.mark.asyncio
    async def test_full_day_order(self, db_session):
        """8 AM - 11 PM: Dhuhr+Asr before Maghrib+Isha, Fajr (if present) first."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=15.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 8, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        order = _get_pair_order(result)
        # Dhuhr+Asr must come before Maghrib+Isha
        if "dhuhr_asr" in order and "maghrib_isha" in order:
            assert order.index("dhuhr_asr") < order.index("maghrib_isha"), (
                f"Dhuhr+Asr should come before Maghrib+Isha. Got order: {order}"
            )

    @pytest.mark.asyncio
    async def test_evening_departure_order(self, db_session):
        """6 PM departure: Maghrib+Isha should be first, Fajr second."""
        d = date(2026, 3, 21)
        d2 = date(2026, 3, 22)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=12.0)
        await _seed_multi_day_mosques(db_session, NYC_TO_DC_MOSQUES, [d, d2])

        dep = datetime(2026, 3, 21, 18, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        order = _get_pair_order(result)
        if "maghrib_isha" in order and "fajr" in order:
            assert order.index("maghrib_isha") < order.index("fajr"), (
                f"Maghrib+Isha should come before Fajr for evening departure. Got: {order}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# MUQEEM MODE (no combining)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMuqeemMode:
    """In driving/Muqeem mode, each prayer is standalone — no Jam' Taqdeem/Ta'kheer."""

    @pytest.mark.asyncio
    async def test_muqeem_no_combining_options(self, db_session):
        """Muqeem mode should not have combine_early or combine_late option types."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=4.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 10, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="driving",
            )

        assert result is not None
        for pp in result["prayer_pairs"]:
            option_types = {opt["option_type"] for opt in pp["options"]}
            assert "combine_early" not in option_types, (
                f"Muqeem mode should not have combine_early. Pair {pp['pair']} has: {option_types}"
            )
            assert "combine_late" not in option_types, (
                f"Muqeem mode should not have combine_late. Pair {pp['pair']} has: {option_types}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-DAY TRIPS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiDayTrips:
    """Multi-day trips must show prayers for EACH calendar day."""

    @pytest.mark.asyncio
    async def test_2_day_trip_all_day_prayers(self, db_session):
        """8 AM day 1 - 6 PM day 2: full prayers both days."""
        d1 = date(2026, 3, 21)
        d2 = date(2026, 3, 22)
        route = _make_route((34.05, -118.24), (39.74, -104.99), duration_hours=34.0)
        await _seed_multi_day_mosques(db_session, LA_TO_DENVER_MOSQUES, [d1, d2])

        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=34.05, origin_lng=-118.24,
                dest_lat=39.74, dest_lng=-104.99,
                destination_name="Denver, CO",
                timezone_str="America/Los_Angeles",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        pairs = _get_pair_names(result)
        # Day 1: Dhuhr+Asr, Maghrib+Isha
        # Day 2: Fajr, Dhuhr+Asr
        assert "dhuhr_asr" in pairs, f"Missing Dhuhr+Asr. Got: {pairs}"
        assert "fajr" in pairs, f"Missing Fajr. Got: {pairs}"


# ═══════════════════════════════════════════════════════════════════════════════
# ITINERARY CONTENT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestItineraryContent:
    """Each itinerary should be a complete plan covering all prayer pairs."""

    @pytest.mark.asyncio
    async def test_each_itinerary_covers_all_pairs(self, db_session):
        """Each itinerary should have one choice per prayer pair."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=14.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 8, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        n_pairs = len(result["prayer_pairs"])
        for itin in result["itineraries"]:
            assert len(itin["pair_choices"]) == n_pairs, (
                f"Itinerary should cover all {n_pairs} pairs. "
                f"Got {len(itin['pair_choices'])} choices."
            )
            # Each choice should have an option with stops or a note
            for pc in itin["pair_choices"]:
                assert "option" in pc
                assert "option_type" in pc["option"]


# ═══════════════════════════════════════════════════════════════════════════════
# TIMEZONE CROSSING
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimezoneCrossing:
    """Routes crossing timezone boundaries should handle prayer times correctly."""

    @pytest.mark.asyncio
    async def test_la_to_denver_timezone_crossing(self, db_session):
        """LA (PT) to Denver (MT) should not crash or produce wrong times."""
        d = date(2026, 3, 21)
        route = _make_route((34.05, -118.24), (39.74, -104.99), duration_hours=15.0)
        await _seed_multi_day_mosques(db_session, LA_TO_DENVER_MOSQUES, [d, date(2026, 3, 22)])

        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=34.05, origin_lng=-118.24,
                dest_lat=39.74, dest_lng=-104.99,
                destination_name="Denver, CO",
                timezone_str="America/Los_Angeles",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        # Should have at least Dhuhr+Asr and Maghrib+Isha
        pairs = _get_pair_names(result)
        assert "dhuhr_asr" in pairs


# ═══════════════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_no_mosques_in_db(self, db_session):
        """Trip with no mosques seeded should not crash, just show no_option."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=4.0)

        dep = datetime(2026, 3, 21, 10, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        # Should still have pairs (with no_option type)
        assert len(result["prayer_pairs"]) >= 1

    @pytest.mark.asyncio
    async def test_short_30min_trip(self, db_session):
        """30 min trip at 3 PM should only show Dhuhr+Asr (if Asr is active)."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (40.50, -74.20), duration_hours=0.5)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES[:3], d)

        dep = datetime(2026, 3, 21, 15, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=40.50, dest_lng=-74.20,
                destination_name="Nearby",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
            )

        assert result is not None
        pairs = _get_pair_names(result)
        # At 3 PM, Dhuhr+Asr should overlap (Asr active)
        assert "maghrib_isha" not in pairs, "Maghrib+Isha should not appear for 3-3:30 PM trip"
        assert "fajr" not in pairs, "Fajr should not appear for 3-3:30 PM trip"

    @pytest.mark.asyncio
    async def test_all_prayed_returns_empty_pairs(self, db_session):
        """If all prayers are marked as prayed, no prayer pairs should appear."""
        d = date(2026, 3, 21)
        route = _make_route((40.71, -74.00), (38.90, -77.04), duration_hours=4.0)
        await _seed_route_mosques(db_session, NYC_TO_DC_MOSQUES, d)

        dep = datetime(2026, 3, 21, 14, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            result = await build_travel_plan(
                db_session,
                origin_lat=40.71, origin_lng=-74.00,
                dest_lat=38.90, dest_lng=-77.04,
                destination_name="Washington DC",
                timezone_str="America/New_York",
                departure_dt=dep,
                trip_mode="travel",
                prayed_prayers={"fajr", "dhuhr", "asr", "maghrib", "isha"},
            )

        assert result is not None
        assert len(result["prayer_pairs"]) == 0, (
            f"All prayed: should have 0 pairs. Got {len(result['prayer_pairs'])}"
        )

    @pytest.mark.asyncio
    async def test_trip_over_72h_raises(self, db_session):
        """Trips over 72 hours should raise ValueError."""
        route = _make_route((40.71, -74.00), (34.05, -118.24), duration_hours=73.0)

        dep = datetime(2026, 3, 21, 10, 0, tzinfo=ET)

        with patch("app.services.travel_planner.get_mapbox_route", new_callable=AsyncMock, return_value=route):
            with pytest.raises(ValueError, match="3 days"):
                await build_travel_plan(
                    db_session,
                    origin_lat=40.71, origin_lng=-74.00,
                    dest_lat=34.05, dest_lng=-118.24,
                    destination_name="Los Angeles",
                    timezone_str="America/New_York",
                    departure_dt=dep,
                    trip_mode="travel",
                )
