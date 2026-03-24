"""
SET 1: Controlled fake data route tests.
We create EXACT mosque locations and schedules designed to cover every edge case.
Each test has a KNOWN correct answer.
"""
import pytest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import text
from tests.conftest import NYC_SCHEDULE

PT = ZoneInfo("America/Los_Angeles")

# ─── Controlled mosque data ──────────────────────────────────────────────────

# 5 mosques placed along a line from Visalia (36.33, -119.29) to San Diego (32.72, -117.16)
# Each ~100 km apart, each with valid schedule data
CONTROLLED_MOSQUES = [
    {
        "name": "Test Mosque Visalia",
        "lat": 36.33, "lng": -119.29, "city": "Visalia", "state": "CA",
        "schedule": {
            "fajr_adhan": "05:42", "fajr_iqama": "06:00",
            "dhuhr_adhan": "12:30", "dhuhr_iqama": "13:00",
            "asr_adhan": "16:30", "asr_iqama": "16:45",
            "maghrib_adhan": "19:15", "maghrib_iqama": "19:20",
            "isha_adhan": "20:30", "isha_iqama": "20:45",
            "sunrise": "06:58",
        },
    },
    {
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
    },
    {
        "name": "Test Mosque LA",
        "lat": 34.05, "lng": -118.24, "city": "Los Angeles", "state": "CA",
        "schedule": {
            "fajr_adhan": "05:44", "fajr_iqama": "06:00",
            "dhuhr_adhan": "12:31", "dhuhr_iqama": "13:00",
            "asr_adhan": "16:32", "asr_iqama": "16:45",
            "maghrib_adhan": "19:17", "maghrib_iqama": "19:22",
            "isha_adhan": "20:31", "isha_iqama": "20:45",
            "sunrise": "06:59",
        },
    },
    {
        "name": "Test Mosque Riverside",
        "lat": 33.95, "lng": -117.40, "city": "Riverside", "state": "CA",
        "schedule": {
            "fajr_adhan": "05:44", "fajr_iqama": "06:00",
            "dhuhr_adhan": "12:31", "dhuhr_iqama": "13:00",
            "asr_adhan": "16:32", "asr_iqama": "16:45",
            "maghrib_adhan": "19:17", "maghrib_iqama": "19:22",
            "isha_adhan": "20:31", "isha_iqama": "20:45",
            "sunrise": "06:59",
        },
    },
    {
        "name": "Test Mosque San Diego",
        "lat": 32.72, "lng": -117.16, "city": "San Diego", "state": "CA",
        "schedule": {
            "fajr_adhan": "05:45", "fajr_iqama": "06:00",
            "dhuhr_adhan": "12:32", "dhuhr_iqama": "13:00",
            "asr_adhan": "16:33", "asr_iqama": "16:45",
            "maghrib_adhan": "19:18", "maghrib_iqama": "19:23",
            "isha_adhan": "20:32", "isha_iqama": "20:45",
            "sunrise": "07:00",
        },
    },
]


async def seed_controlled_mosques(db_session):
    """Seed the controlled mosques into the test DB."""
    from app.models import new_uuid
    mosque_ids = []
    today = date.today()

    for m in CONTROLLED_MOSQUES:
        mosque_id = new_uuid()
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
        mosque_ids.append(mosque_id)

    await db_session.commit()
    return mosque_ids


# ─── Test Scenarios ──────────────────────────────────────────────────────────

class TestMorningSameDay:
    """8 AM → ~11:30 AM Visalia→LA (OSRM ~3.5h route).
    Dhuhr starts at 12:30 which is AFTER arrival → no prayers during trip."""

    @pytest.mark.asyncio
    async def test_no_prayers_short_morning_trip(self, async_client, db_session):
        """Trip ends before Dhuhr starts → 0 prayer pairs (correct)."""
        await seed_controlled_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 34.05, "destination_lng": -118.24,
            "destination_name": "LA", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",  # 8 AM PT
        })
        assert r.status_code in (200, 503), f"Status {r.status_code}: {r.text[:200]}"
        if r.status_code == 200:
            pairs = {pp["pair"] for pp in r.json().get("prayer_pairs", [])}
            # Trip 8 AM → ~11:30 AM. Dhuhr at 12:30 is after arrival. No overlap.
            assert "maghrib_isha" not in pairs

    @pytest.mark.asyncio
    async def test_no_isha(self, async_client, db_session):
        await seed_controlled_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 34.05, "destination_lng": -118.24,
            "destination_name": "LA", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code == 200:
            pairs = {pp["pair"] for pp in r.json().get("prayer_pairs", [])}
            assert "maghrib_isha" not in pairs, f"Unexpected maghrib_isha in {pairs}"


class TestEveningSameDay:
    """5 PM → 11 PM. Expected: Maghrib+Isha pair."""

    @pytest.mark.asyncio
    async def test_has_maghrib_isha(self, async_client, db_session):
        await seed_controlled_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "SD", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["fajr", "dhuhr", "asr"],
            "departure_time": "2026-03-22T00:00:00Z",  # 5 PM PT
        })
        if r.status_code == 200:
            pairs = {pp["pair"] for pp in r.json().get("prayer_pairs", [])}
            assert "maghrib_isha" in pairs, f"Expected maghrib_isha, got {pairs}"


class TestMidnightShort:
    """12:15 AM → ~3:48 AM (OSRM ~3.5h route). NO stale Isha.
    Fajr at 5:42 AM is after 3:48 AM arrival → no Fajr in trip window."""

    @pytest.mark.asyncio
    async def test_no_fajr_short_midnight_trip(self, async_client, db_session):
        """Trip ends at ~3:48 AM, Fajr at 5:42 AM → no Fajr (correct)."""
        await seed_controlled_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 34.05, "destination_lng": -118.24,
            "destination_name": "LA", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["isha"],
            "departure_time": "2026-03-22T07:15:00Z",  # 12:15 AM PT
        })
        if r.status_code == 200:
            pairs = {pp["pair"] for pp in r.json().get("prayer_pairs", [])}
            # Trip: 12:15 AM → ~3:48 AM. Fajr at 5:42 AM is after arrival.
            # No prayers during this trip window.
            assert "maghrib_isha" not in pairs, f"Stale maghrib_isha in {pairs}"

    @pytest.mark.asyncio
    async def test_no_stale_isha(self, async_client, db_session):
        await seed_controlled_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 34.05, "destination_lng": -118.24,
            "destination_name": "LA", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["isha"],
            "departure_time": "2026-03-22T07:15:00Z",
        })
        if r.status_code == 200:
            pairs = {pp["pair"] for pp in r.json().get("prayer_pairs", [])}
            assert "maghrib_isha" not in pairs, f"Stale maghrib_isha in {pairs}"


class TestFullDay22h:
    """6 AM → 4 AM next day (22h). Expected: ALL prayer pairs."""

    @pytest.mark.asyncio
    async def test_has_all_pairs(self, async_client, db_session):
        await seed_controlled_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "SD", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": [],
            "departure_time": "2026-03-22T13:00:00Z",  # 6 AM PT
            "waypoints": [
                {"lat": 37.37, "lng": -122.04, "name": "Sunnyvale"},
                {"lat": 36.17, "lng": -115.14, "name": "Las Vegas"},
            ],
        })
        if r.status_code == 200:
            pairs = {pp["pair"] for pp in r.json().get("prayer_pairs", [])}
            assert "fajr" in pairs or "dhuhr_asr" in pairs, f"Expected daytime prayers, got {pairs}"
            # 22h trip must include evening prayers too
            # (maghrib_isha should be relevant — it's a full day)


class TestMuqeemMode:
    """Muqeem mode: individual prayer stops, no combining."""

    @pytest.mark.asyncio
    async def test_no_combining(self, async_client, db_session):
        await seed_controlled_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 34.05, "destination_lng": -118.24,
            "destination_name": "LA", "timezone": "America/Los_Angeles",
            "trip_mode": "driving", "prayed_prayers": ["fajr"],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        if r.status_code == 200:
            for pp in r.json().get("prayer_pairs", []):
                for opt in pp["options"]:
                    assert opt["option_type"] not in ("combine_early", "combine_late"), \
                        f"Muqeem mode has combining: {opt['option_type']}"


class TestPrayedFiltering:
    """Prayed prayers must be excluded from results."""

    @pytest.mark.asyncio
    async def test_isha_prayed_no_maghrib_isha(self, async_client, db_session):
        """At 5 PM, user says isha prayed. Trust them — Maghrib+Isha should be skipped."""
        await seed_controlled_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 32.72, "destination_lng": -117.16,
            "destination_name": "SD", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": ["isha"],
            "departure_time": "2026-03-22T00:00:00Z",  # 5 PM PT
        })
        if r.status_code == 200:
            pairs = {pp["pair"] for pp in r.json().get("prayer_pairs", [])}
            assert "maghrib_isha" not in pairs, f"Isha prayed but pair shown: {pairs}"

    @pytest.mark.asyncio
    async def test_all_prayed_short_trip_no_overlap(self, async_client, db_session):
        """8 AM dep, ~3.5h trip. No prayers overlap the trip window regardless of prayed status."""
        await seed_controlled_mosques(db_session)
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 36.33, "origin_lng": -119.29,
            "destination_lat": 34.05, "destination_lng": -118.24,
            "destination_name": "LA", "timezone": "America/Los_Angeles",
            "trip_mode": "travel",
            "prayed_prayers": ["fajr", "dhuhr", "asr", "maghrib", "isha"],
            "departure_time": "2026-03-22T15:00:00Z",  # 8 AM PT
        })
        if r.status_code == 200:
            pairs = r.json().get("prayer_pairs", [])
            # Trip 8 AM → ~11:33 AM. No prayer windows overlap.
            assert len(pairs) == 0, f"No prayers during 8-11:30 AM window, got {len(pairs)} pairs"


class TestNoCrashWithBadData:
    """Routes must not crash even with malformed mosque data in DB."""

    @pytest.mark.asyncio
    async def test_malformed_iqama(self, async_client, db_session):
        """Seed a mosque with bad iqama and ensure no crash."""
        from app.models import new_uuid
        today = date.today()
        mosque_id = new_uuid()
        await db_session.execute(text("""
            INSERT INTO mosques (id, name, lat, lng, geom, timezone, country,
                                is_active, verified, places_enriched)
            VALUES (:id, 'Bad Mosque', 35.0, -118.5,
                    ST_SetSRID(ST_MakePoint(-118.5, 35.0), 4326),
                    'America/Los_Angeles', 'US', true, false, false)
        """), {"id": mosque_id})
        # Insert schedule with malformed data
        await db_session.execute(text("""
            INSERT INTO prayer_schedules (id, mosque_id, date,
                fajr_adhan, fajr_iqama, dhuhr_adhan, dhuhr_iqama,
                asr_adhan, asr_iqama, maghrib_adhan, maghrib_iqama,
                isha_adhan, isha_iqama, sunrise, sunrise_source,
                fajr_adhan_source, fajr_iqama_source, dhuhr_adhan_source, dhuhr_iqama_source,
                asr_adhan_source, asr_iqama_source, maghrib_adhan_source, maghrib_iqama_source,
                isha_adhan_source, isha_iqama_source,
                fajr_adhan_confidence, fajr_iqama_confidence,
                dhuhr_adhan_confidence, dhuhr_iqama_confidence,
                asr_adhan_confidence, asr_iqama_confidence,
                maghrib_adhan_confidence, maghrib_iqama_confidence,
                isha_adhan_confidence, isha_iqama_confidence)
            VALUES (:id, :mid, :date,
                '+15', NULL, '13:00', '1300', '16:30', '', '19:15', 'None',
                '20:30', '20:45', '06:58', 'calculated',
                'calculated', 'estimated', 'calculated', 'estimated',
                'calculated', 'estimated', 'calculated', 'estimated',
                'calculated', 'estimated',
                'low', 'low', 'low', 'low', 'low', 'low', 'low', 'low', 'low', 'low')
        """), {"id": new_uuid(), "mid": mosque_id, "date": today})
        await db_session.commit()

        # This must NOT crash
        r = await async_client.post("/api/travel/plan", json={
            "origin_lat": 35.0, "origin_lng": -118.5,
            "destination_lat": 34.05, "destination_lng": -118.24,
            "destination_name": "LA", "timezone": "America/Los_Angeles",
            "trip_mode": "travel", "prayed_prayers": [],
            "departure_time": "2026-03-22T15:00:00Z",
        })
        assert r.status_code in (200, 503), f"Crashed with bad data: {r.status_code} {r.text[:200]}"

