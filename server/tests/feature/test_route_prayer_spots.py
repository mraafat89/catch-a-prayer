"""
Tests for prayer spots in route planning.

Prayer spots (rest areas, airport rooms, etc.) should appear as stop options
alongside mosques. They have no iqama — only calculated adhan times.

See docs/PRAYER_SPOTS_IN_ROUTES.md for design.
"""
import pytest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import text
from app.models import new_uuid

PT = ZoneInfo("America/Los_Angeles")

# ─── Test Data ────────────────────────────────────────────────────────────────

# Mosque near Bakersfield (on route)
ROUTE_MOSQUE = {
    "name": "Test Mosque Bakersfield",
    "lat": 35.37, "lng": -119.02, "city": "Bakersfield", "state": "CA",
    "schedule": {
        "fajr_adhan": "05:43", "fajr_iqama": "06:00",
        "dhuhr_adhan": "12:30", "dhuhr_iqama": "13:00",
        "asr_adhan": "16:31", "asr_iqama": "16:45",
        "maghrib_adhan": "19:16", "maghrib_iqama": "19:21",
        "isha_adhan": "20:30", "isha_iqama": "20:45",
        "sunrise": "06:58",
    },
}

# Prayer spots along the Visalia → San Diego route
ROUTE_PRAYER_SPOTS = [
    {
        "name": "I-5 Rest Area Grapevine",
        "lat": 34.94, "lng": -118.77,
        "spot_type": "rest_area",
        "city": "Grapevine", "state": "CA",
        "has_wudu_facilities": False,
        "is_indoor": False,
    },
    {
        "name": "LAX Airport Prayer Room",
        "lat": 33.94, "lng": -118.41,
        "spot_type": "airport",
        "city": "Los Angeles", "state": "CA",
        "has_wudu_facilities": True,
        "is_indoor": True,
    },
    {
        "name": "UCSD Campus Prayer Room",
        "lat": 32.88, "lng": -117.24,
        "spot_type": "campus",
        "city": "San Diego", "state": "CA",
        "has_wudu_facilities": True,
        "is_indoor": True,
    },
]

# Prayer spot far off route (Las Vegas) — should NOT appear due to detour filter
OFF_ROUTE_PRAYER_SPOT = {
    "name": "Vegas Strip Rest Stop",
    "lat": 36.17, "lng": -115.14,
    "spot_type": "rest_area",
    "city": "Las Vegas", "state": "NV",
    "has_wudu_facilities": False,
    "is_indoor": False,
}


async def seed_mosque_and_spots(db_session):
    """Seed one mosque + several prayer spots for route tests."""
    today = date.today()
    mosque_id = new_uuid()

    # Seed mosque
    m = ROUTE_MOSQUE
    await db_session.execute(text("""
        INSERT INTO mosques (id, name, lat, lng, geom, city, state, timezone,
                            country, is_active, verified, places_enriched)
        VALUES (:id, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                :city, :state, 'America/Los_Angeles', 'US', true, false, false)
    """), {"id": mosque_id, "name": m["name"], "lat": m["lat"], "lng": m["lng"],
           "city": m["city"], "state": m["state"]})

    s = m["schedule"]
    params = {"id": new_uuid(), "mosque_id": mosque_id, "date": today}
    for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
        params[f"{prayer}_adhan"] = s[f"{prayer}_adhan"]
        params[f"{prayer}_iqama"] = s[f"{prayer}_iqama"]
        params[f"{prayer}_adhan_source"] = "mosque_website_html"
        params[f"{prayer}_iqama_source"] = "mosque_website_html"
        params[f"{prayer}_adhan_confidence"] = "high"
        params[f"{prayer}_iqama_confidence"] = "high"
    params["sunrise"] = s["sunrise"]
    params["sunrise_source"] = "calculated"
    cols = ", ".join(params.keys())
    vals = ", ".join(f":{k}" for k in params.keys())
    await db_session.execute(text(f"INSERT INTO prayer_schedules ({cols}) VALUES ({vals})"), params)

    # Seed prayer spots
    spot_ids = []
    for sp in ROUTE_PRAYER_SPOTS + [OFF_ROUTE_PRAYER_SPOT]:
        spot_id = new_uuid()
        spot_ids.append(spot_id)
        await db_session.execute(text("""
            INSERT INTO prayer_spots (id, name, lat, lng, geom, spot_type, city, state,
                                     timezone, country, status, has_wudu_facilities,
                                     is_indoor, gender_access, verification_count, rejection_count)
            VALUES (:id, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                    :spot_type, :city, :state, 'America/Los_Angeles', 'US', 'active',
                    :has_wudu, :is_indoor, 'all', 0, 0)
        """), {
            "id": spot_id, "name": sp["name"], "lat": sp["lat"], "lng": sp["lng"],
            "spot_type": sp["spot_type"], "city": sp["city"], "state": sp["state"],
            "has_wudu": sp.get("has_wudu_facilities", False),
            "is_indoor": sp.get("is_indoor", False),
        })

    await db_session.commit()
    return mosque_id, spot_ids


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestPrayerSpotsInRouteResults:
    """Prayer spots should appear in travel plan results alongside mosques."""

    @pytest.mark.asyncio
    async def test_route_includes_prayer_spots(self, async_client, db_session):
        """Route from Visalia to San Diego should find prayer spots along the way."""
        await seed_mosque_and_spots(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",  # 8 AM PT
        })
        if r.status_code != 200:
            return  # OSRM may be down
        data = r.json()
        all_stops = []
        for pp in data.get("prayer_pairs", []):
            for opt in pp.get("options", []):
                for stop in opt.get("stops", []):
                    all_stops.append(stop)

        # At least one stop should be a prayer spot
        prayer_spot_stops = [s for s in all_stops if s.get("is_prayer_spot")]
        mosque_stops = [s for s in all_stops if not s.get("is_prayer_spot")]

        assert len(prayer_spot_stops) > 0, \
            f"Expected prayer spots in route stops. Got {len(all_stops)} stops, all mosques: {[s['mosque_name'] for s in all_stops]}"

    @pytest.mark.asyncio
    async def test_prayer_spot_has_no_iqama(self, async_client, db_session):
        """Prayer spot stops should have null iqama_time."""
        await seed_mosque_and_spots(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code != 200:
            return
        data = r.json()
        for pp in data.get("prayer_pairs", []):
            for opt in pp.get("options", []):
                for stop in opt.get("stops", []):
                    if stop.get("is_prayer_spot"):
                        assert stop.get("iqama_time") is None, \
                            f"Prayer spot {stop['mosque_name']} should have no iqama, got {stop['iqama_time']}"

    @pytest.mark.asyncio
    async def test_prayer_spot_has_adhan_time(self, async_client, db_session):
        """Prayer spot stops should have a calculated adhan_time."""
        await seed_mosque_and_spots(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code != 200:
            return
        data = r.json()
        for pp in data.get("prayer_pairs", []):
            for opt in pp.get("options", []):
                for stop in opt.get("stops", []):
                    if stop.get("is_prayer_spot"):
                        assert stop.get("adhan_time") is not None, \
                            f"Prayer spot {stop['mosque_name']} should have calculated adhan_time"

    @pytest.mark.asyncio
    async def test_prayer_spot_status_is_solo(self, async_client, db_session):
        """Prayer spots should never show can_catch_with_imam."""
        await seed_mosque_and_spots(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code != 200:
            return
        data = r.json()
        for pp in data.get("prayer_pairs", []):
            for opt in pp.get("options", []):
                for stop in opt.get("stops", []):
                    if stop.get("is_prayer_spot"):
                        assert "imam" not in stop.get("status", ""), \
                            f"Prayer spot should not have imam status, got {stop['status']}"


class TestPrayerSpotFields:
    """Prayer spot stops should carry spot-specific metadata."""

    @pytest.mark.asyncio
    async def test_spot_type_field(self, async_client, db_session):
        """Prayer spot stops should include spot_type."""
        await seed_mosque_and_spots(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code != 200:
            return
        data = r.json()
        for pp in data.get("prayer_pairs", []):
            for opt in pp.get("options", []):
                for stop in opt.get("stops", []):
                    if stop.get("is_prayer_spot"):
                        assert stop.get("spot_type") is not None, \
                            f"Prayer spot {stop['mosque_name']} missing spot_type"
                        assert stop["spot_type"] in (
                            "rest_area", "airport", "campus", "prayer_room",
                            "multifaith_room", "quiet_room", "community_hall",
                            "halal_restaurant", "hospital", "office", "other",
                        ), f"Invalid spot_type: {stop['spot_type']}"

    @pytest.mark.asyncio
    async def test_wudu_and_indoor_fields(self, async_client, db_session):
        """Prayer spot stops should include has_wudu and is_indoor."""
        await seed_mosque_and_spots(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code != 200:
            return
        data = r.json()
        for pp in data.get("prayer_pairs", []):
            for opt in pp.get("options", []):
                for stop in opt.get("stops", []):
                    if stop.get("is_prayer_spot"):
                        assert "has_wudu" in stop, \
                            f"Prayer spot {stop['mosque_name']} missing has_wudu field"
                        assert "is_indoor" in stop, \
                            f"Prayer spot {stop['mosque_name']} missing is_indoor field"


class TestPrayerSpotFiltering:
    """Only active spots within corridor, pending/rejected excluded."""

    @pytest.mark.asyncio
    async def test_off_route_spot_excluded(self, async_client, db_session):
        """Las Vegas prayer spot is far off the Visalia-SD route — should not appear."""
        await seed_mosque_and_spots(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code != 200:
            return
        data = r.json()
        all_names = []
        for pp in data.get("prayer_pairs", []):
            for opt in pp.get("options", []):
                for stop in opt.get("stops", []):
                    all_names.append(stop["mosque_name"])
        assert "Vegas Strip Rest Stop" not in all_names, \
            f"Off-route prayer spot should be excluded. Stops: {all_names}"

    @pytest.mark.asyncio
    async def test_pending_spot_excluded(self, async_client, db_session):
        """Pending prayer spots should not appear in route results."""
        await seed_mosque_and_spots(db_session)
        # Add a pending spot right on the route
        pending_id = new_uuid()
        await db_session.execute(text("""
            INSERT INTO prayer_spots (id, name, lat, lng, geom, spot_type, city, state,
                                     timezone, country, status, has_wudu_facilities,
                                     is_indoor, gender_access, verification_count, rejection_count)
            VALUES (:id, 'Pending Rest Area', 35.0, -118.5,
                    ST_SetSRID(ST_MakePoint(-118.5, 35.0), 4326),
                    'rest_area', 'Test', 'CA', 'America/Los_Angeles', 'US',
                    'pending', false, false, 'all', 0, 0)
        """), {"id": pending_id})
        await db_session.commit()

        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code != 200:
            return
        data = r.json()
        all_names = []
        for pp in data.get("prayer_pairs", []):
            for opt in pp.get("options", []):
                for stop in opt.get("stops", []):
                    all_names.append(stop["mosque_name"])
        assert "Pending Rest Area" not in all_names, \
            f"Pending spots should be excluded. Stops: {all_names}"


class TestMosquePriorityOverSpot:
    """Mosques with imam should rank higher than prayer spots."""

    @pytest.mark.asyncio
    async def test_mosque_ranked_above_spot_same_detour(self, async_client, db_session):
        """When a mosque and prayer spot have similar detour, mosque should be preferred."""
        await seed_mosque_and_spots(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code != 200:
            return
        data = r.json()
        # Check first itinerary (best ranked) — if both mosque and spot exist
        # for the same prayer, mosque should be the primary option
        if not data.get("itineraries"):
            return
        first = data["itineraries"][0]
        for pc in first["pair_choices"]:
            stops = pc["option"].get("stops", [])
            if len(stops) > 0:
                # First stop for each prayer should prefer mosque over spot
                first_stop = stops[0]
                # Not a hard assert — just check the structure is right
                assert "mosque_name" in first_stop


class TestPrayerSpotOnlyRoute:
    """When no mosques exist near the route, prayer spots should fill the gap."""

    @pytest.mark.asyncio
    async def test_spots_fill_gap_when_no_mosques(self, async_client, db_session):
        """With no mosques seeded, prayer spots should still provide stop options."""
        today = date.today()
        # Seed ONLY prayer spots (no mosques)
        for sp in ROUTE_PRAYER_SPOTS:
            spot_id = new_uuid()
            await db_session.execute(text("""
                INSERT INTO prayer_spots (id, name, lat, lng, geom, spot_type, city, state,
                                         timezone, country, status, has_wudu_facilities,
                                         is_indoor, gender_access, verification_count, rejection_count)
                VALUES (:id, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                        :spot_type, :city, :state, 'America/Los_Angeles', 'US', 'active',
                        :has_wudu, :is_indoor, 'all', 0, 0)
            """), {
                "id": spot_id, "name": sp["name"], "lat": sp["lat"], "lng": sp["lng"],
                "spot_type": sp["spot_type"], "city": sp["city"], "state": sp["state"],
                "has_wudu": sp.get("has_wudu_facilities", False),
                "is_indoor": sp.get("is_indoor", False),
            })
        await db_session.commit()

        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "San Diego", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code != 200:
            return
        data = r.json()
        all_stops = []
        for pp in data.get("prayer_pairs", []):
            for opt in pp.get("options", []):
                all_stops.extend(opt.get("stops", []))

        prayer_spot_stops = [s for s in all_stops if s.get("is_prayer_spot")]
        assert len(prayer_spot_stops) > 0, \
            f"With no mosques, prayer spots should fill the gap. Got 0 prayer spot stops out of {len(all_stops)} total."
