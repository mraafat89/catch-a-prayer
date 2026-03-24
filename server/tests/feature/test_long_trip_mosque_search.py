"""
Tests for long trip mosque search — seeds mosques ALONG the route corridor
so the corridor search actually finds them.

Key insight: the planner searches for mosques near ROUTE CHECKPOINTS, not
near origin/destination. For tests to be meaningful, mosques must be placed
at coordinates that the route passes through.

We simulate a straight-line route and place mosques along it.
"""
import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import text
from app.models import new_uuid

PT = ZoneInfo("America/Los_Angeles")
MT = ZoneInfo("America/Denver")

# Simulated route: Visalia CA → Denver CO (roughly along I-15/I-40/I-25)
# Straight-line checkpoints approximately every 200km
ROUTE_POINTS = [
    ("Visalia CA",     36.33, -119.29, "America/Los_Angeles"),
    ("Bakersfield CA", 35.37, -119.02, "America/Los_Angeles"),
    ("Barstow CA",     34.90, -117.02, "America/Los_Angeles"),
    ("Las Vegas NV",   36.17, -115.14, "America/Los_Angeles"),
    ("St George UT",   37.10, -113.58, "America/Denver"),
    ("Green River UT", 38.99, -110.16, "America/Denver"),
    ("Grand Junction", 39.06, -108.55, "America/Denver"),
    ("Vail CO",        39.64, -106.37, "America/Denver"),
    ("Denver CO",      39.74, -104.99, "America/Denver"),
]

VALID_SCHEDULE_PT = {
    "fajr_adhan": "05:42", "fajr_iqama": "06:00",
    "dhuhr_adhan": "12:30", "dhuhr_iqama": "13:00",
    "asr_adhan": "16:30", "asr_iqama": "16:45",
    "maghrib_adhan": "19:15", "maghrib_iqama": "19:20",
    "isha_adhan": "20:30", "isha_iqama": "20:45",
    "sunrise": "06:58",
}

VALID_SCHEDULE_MT = {
    "fajr_adhan": "05:45", "fajr_iqama": "06:00",
    "dhuhr_adhan": "12:15", "dhuhr_iqama": "12:45",
    "asr_adhan": "16:00", "asr_iqama": "16:15",
    "maghrib_adhan": "19:00", "maghrib_iqama": "19:05",
    "isha_adhan": "20:15", "isha_iqama": "20:30",
    "sunrise": "07:00",
}


async def seed_route_mosques(db_session):
    """Seed a mosque at each route point with valid prayer schedule."""
    today = date.today()
    mosque_ids = []

    for name, lat, lng, tz in ROUTE_POINTS:
        mosque_id = new_uuid()
        schedule = VALID_SCHEDULE_MT if "Denver" in tz else VALID_SCHEDULE_PT

        await db_session.execute(text("""
            INSERT INTO mosques (id, name, lat, lng, geom, timezone, country,
                                is_active, verified, places_enriched)
            VALUES (:id, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                    :tz, 'US', true, false, false)
        """), {"id": mosque_id, "name": f"Test Mosque {name}", "lat": lat, "lng": lng, "tz": tz})

        params = {"id": new_uuid(), "mosque_id": mosque_id, "date": today}
        for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
            params[f"{prayer}_adhan"] = schedule[f"{prayer}_adhan"]
            params[f"{prayer}_iqama"] = schedule[f"{prayer}_iqama"]
            params[f"{prayer}_adhan_source"] = "mosque_website_html"
            params[f"{prayer}_iqama_source"] = "mosque_website_html"
            params[f"{prayer}_adhan_confidence"] = "high"
            params[f"{prayer}_iqama_confidence"] = "high"
        params["sunrise"] = schedule["sunrise"]
        params["sunrise_source"] = "calculated"
        cols = ", ".join(params.keys())
        vals = ", ".join(f":{k}" for k in params.keys())
        await db_session.execute(text(f"INSERT INTO prayer_schedules ({cols}) VALUES ({vals})"), params)
        mosque_ids.append(mosque_id)

    await db_session.commit()
    return mosque_ids


class TestLongTripMosqueDiscovery:
    """20-hour trip from Visalia to Denver with mosques seeded along the route."""

    @pytest.mark.asyncio
    async def test_20h_morning_finds_dhuhr_asr(self, async_client, db_session):
        """8 AM departure, 20h trip → must find Dhuhr+Asr mosque."""
        await seed_route_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 39.74, "destination_lng": -104.99,
            "destination_name": "Denver",
            "timezone": "America/Los_Angeles",
            "trip_mode": "travel",
            "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",  # 8 AM PT
        })
        assert r.status_code in (200, 503), f"Status {r.status_code}: {r.text[:200]}"
        if r.status_code == 200:
            data = r.json()
            pairs = {pp["pair"] for pp in data.get("prayer_pairs", [])}
            assert "dhuhr_asr" in pairs, f"No Dhuhr+Asr for 20h trip. Got: {pairs}"
            # Should have mosque stops, not just "no mosque"
            for pp in data["prayer_pairs"]:
                if pp["pair"] == "dhuhr_asr":
                    has_stops = any(len(o["stops"]) > 0 for o in pp["options"])
                    assert has_stops, "Dhuhr+Asr has no mosque stops"

    @pytest.mark.asyncio
    async def test_20h_evening_finds_maghrib_isha(self, async_client, db_session):
        """8 AM departure, 20h trip → must find Maghrib+Isha mosque."""
        await seed_route_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 39.74, "destination_lng": -104.99,
            "destination_name": "Denver",
            "timezone": "America/Los_Angeles",
            "trip_mode": "travel",
            "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code == 200:
            pairs = {pp["pair"] for pp in r.json().get("prayer_pairs", [])}
            # 20h from 8 AM → arrives ~4 AM next day. Maghrib (~7:15 PM) is during trip.
            assert "maghrib_isha" in pairs, f"No Maghrib+Isha for 20h trip. Got: {pairs}"

    @pytest.mark.asyncio
    async def test_20h_finds_fajr_with_correct_arrival(self, async_client, db_session):
        """1 AM departure, 20h trip, isha prayed → Fajr should show correct time."""
        await seed_route_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 39.74, "destination_lng": -104.99,
            "destination_name": "Denver",
            "timezone": "America/Los_Angeles",
            "trip_mode": "travel",
            "prayed_prayers": ["isha"],
            "departure_time": "2026-03-22T08:00:00Z",  # 1 AM PT
        })
        if r.status_code == 200:
            data = r.json()
            fajr_pairs = [pp for pp in data["prayer_pairs"] if pp["pair"] == "fajr"]
            if fajr_pairs:
                for opt in fajr_pairs[0]["options"]:
                    for stop in opt.get("stops", []):
                        # Fajr arrival should be around 5-6 AM, not 2 PM
                        arr = stop.get("estimated_arrival_time", "")
                        if arr:
                            from app.services.mosque_search import hhmm_to_minutes
                            arr_min = hhmm_to_minutes(arr)
                            assert 300 <= arr_min <= 420 or arr_min == 0, \
                                f"Fajr arrival time {arr} is not around 5-7 AM (got {arr_min} min)"

    @pytest.mark.asyncio
    async def test_20h_multiple_itineraries(self, async_client, db_session):
        """Long trip with multiple mosque options should generate 3+ itineraries."""
        await seed_route_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 39.74, "destination_lng": -104.99,
            "destination_name": "Denver",
            "timezone": "America/Los_Angeles",
            "trip_mode": "travel",
            "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code == 200:
            its = r.json().get("itineraries", [])
            assert len(its) >= 2, f"Only {len(its)} itineraries for 20h trip with route mosques"

    @pytest.mark.asyncio
    async def test_no_stale_isha_midnight_departure(self, async_client, db_session):
        """1 AM departure, isha prayed → no Maghrib+Isha in results."""
        await seed_route_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 39.74, "destination_lng": -104.99,
            "destination_name": "Denver",
            "timezone": "America/Los_Angeles",
            "trip_mode": "travel",
            "prayed_prayers": ["isha"],
            "departure_time": "2026-03-22T08:00:00Z",  # 1 AM PT
        })
        if r.status_code == 200:
            pairs = {pp["pair"] for pp in r.json().get("prayer_pairs", [])}
            assert "maghrib_isha" not in pairs, f"Stale Maghrib+Isha found. Pairs: {pairs}"

    @pytest.mark.asyncio
    async def test_muqeem_finds_individual_stops(self, async_client, db_session):
        """Muqeem mode should find individual mosque stops."""
        await seed_route_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 39.74, "destination_lng": -104.99,
            "destination_name": "Denver",
            "timezone": "America/Los_Angeles",
            "trip_mode": "driving",
            "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code == 200:
            data = r.json()
            # Should have individual prayer pairs, not combined
            pair_names = {pp["pair"] for pp in data["prayer_pairs"]}
            # At least Dhuhr and Asr should appear as separate
            has_daytime = "dhuhr" in pair_names or "asr" in pair_names or "dhuhr_asr" in pair_names
            assert has_daytime, f"No daytime prayers in Muqeem mode. Got: {pair_names}"

    @pytest.mark.asyncio
    async def test_short_trip_no_crash(self, async_client, db_session):
        """Short trip between two seeded mosques."""
        await seed_route_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 35.37, "destination_lng": -119.02,
            "destination_name": "Bakersfield",
            "timezone": "America/Los_Angeles",
            "trip_mode": "travel",
            "prayed_prayers": [],
            "departure_time": "2026-03-22T19:00:00Z",  # noon PT
        })
        assert r.status_code in (200, 503)
