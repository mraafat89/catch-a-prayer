"""
Integration tests verifying mosque detail API returns phone, denomination,
and data source fields correctly.
Rules: CLIENT_TODO.md P0 items 1-3
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import text
from tests.conftest import seed_mosque_direct, NYC_SCHEDULE


async def _seed_mosque_with_extras(
    phone=None, denomination=None, website=None,
):
    """Seed a mosque with optional phone/denomination/website."""
    from app.database import _session_factory
    from app.models import new_uuid
    from datetime import date

    mosque_id = new_uuid()
    async with _session_factory() as session:
        await session.execute(text("""
            INSERT INTO mosques (id, name, lat, lng, geom, timezone, country,
                                is_active, verified, places_enriched,
                                phone, denomination, website)
            VALUES (:id, 'Detail Test Mosque', 40.7128, -74.006,
                    ST_SetSRID(ST_MakePoint(-74.006, 40.7128), 4326),
                    'America/New_York', 'US', true, false, false,
                    :phone, :denom, :website)
        """), {"id": mosque_id, "phone": phone, "denom": denomination, "website": website})

        # Add prayer schedule
        today = date.today()
        params = {"id": new_uuid(), "mosque_id": mosque_id, "date": today}
        for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
            params[f"{prayer}_adhan"] = NYC_SCHEDULE[f"{prayer}_adhan"]
            params[f"{prayer}_iqama"] = NYC_SCHEDULE[f"{prayer}_iqama"]
            params[f"{prayer}_adhan_source"] = "mosque_website_html"
            params[f"{prayer}_iqama_source"] = "mosque_website_html"
            params[f"{prayer}_adhan_confidence"] = "high"
            params[f"{prayer}_iqama_confidence"] = "high"
        params["sunrise"] = "06:30"
        params["sunrise_source"] = "calculated"
        cols = ", ".join(params.keys())
        vals = ", ".join(f":{k}" for k in params.keys())
        await session.execute(text(f"INSERT INTO prayer_schedules ({cols}) VALUES ({vals})"), params)
        await session.commit()
    return mosque_id


@pytest.mark.asyncio
async def test_mosque_returns_phone_when_present(async_client):
    mosque_id = await _seed_mosque_with_extras(phone="+1-555-123-4567")
    r = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128, "longitude": -74.006, "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    assert r.status_code == 200
    mosque = r.json()["mosques"][0]
    assert mosque["phone"] == "+1-555-123-4567"


@pytest.mark.asyncio
async def test_mosque_returns_null_phone_when_missing(async_client):
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    r = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128, "longitude": -74.006, "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    mosque = r.json()["mosques"][0]
    assert mosque["phone"] is None


@pytest.mark.asyncio
async def test_mosque_returns_denomination(async_client):
    mosque_id = await _seed_mosque_with_extras(denomination="sunni")
    r = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128, "longitude": -74.006, "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    mosque = r.json()["mosques"][0]
    assert mosque.get("denomination") == "sunni"


@pytest.mark.asyncio
async def test_mosque_returns_prayer_source(async_client):
    """Each prayer should have source info for data transparency."""
    mosque_id = await _seed_mosque_with_extras()
    r = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128, "longitude": -74.006, "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    mosque = r.json()["mosques"][0]
    for p in mosque["prayers"]:
        assert "adhan_source" in p
        assert "iqama_source" in p


@pytest.mark.asyncio
async def test_mosque_returns_website(async_client):
    mosque_id = await _seed_mosque_with_extras(website="https://testmosque.org")
    r = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128, "longitude": -74.006, "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    mosque = r.json()["mosques"][0]
    assert mosque["website"] == "https://testmosque.org"
