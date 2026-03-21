"""
Integration tests for mosque search and detail endpoints.
Source: server/app/api/mosques.py
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import text

from tests.conftest import seed_mosque_direct, NYC_SCHEDULE


@pytest.mark.asyncio
async def test_nearby_returns_seeded_mosque(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)
    response = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 200
    data = response.json()
    assert "mosques" in data
    ids = [m["id"] for m in data["mosques"]]
    assert mosque_id in ids


@pytest.mark.asyncio
async def test_nearby_respects_radius(async_client):
    await seed_mosque_direct(lat=40.90, lng=-74.00, schedule=NYC_SCHEDULE)
    response = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 1,  # 1 km — too small to reach mosque 20 km away
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        data = response.json()
        assert len(data["mosques"]) == 0


@pytest.mark.asyncio
async def test_nearby_invalid_coords(async_client):
    response = await async_client.post("/api/mosques/nearby", json={
        "latitude": 200,
        "longitude": -74.0060,
        "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_nearby_returns_prayer_times(async_client):
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    response = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 200
    data = response.json()
    if data["mosques"]:
        mosque = data["mosques"][0]
        assert "prayers" in mosque
        assert len(mosque["prayers"]) == 5
        prayer_names = {p["prayer"] for p in mosque["prayers"]}
        assert prayer_names == {"fajr", "dhuhr", "asr", "maghrib", "isha"}


@pytest.mark.asyncio
async def test_nearby_returns_catching_status(async_client):
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    response = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 200
    data = response.json()
    if data["mosques"]:
        mosque = data["mosques"][0]
        # next_catchable may be null (all passed) but should exist as key
        assert "next_catchable" in mosque
        assert "catchable_prayers" in mosque


@pytest.mark.asyncio
async def test_nearby_musafir_returns_combinations(async_client):
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    response = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": "2026-03-20T17:30:00Z",  # during Dhuhr+Asr window in ET
        "travel_mode": True,
    })
    assert response.status_code == 200
    data = response.json()
    if data["mosques"]:
        mosque = data["mosques"][0]
        assert "travel_combinations" in mosque
        # In musafir mode, should have combination options (or empty if all passed)
        assert isinstance(mosque["travel_combinations"], list)


@pytest.mark.asyncio
async def test_nearby_returns_user_location(async_client):
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    response = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 200
    data = response.json()
    assert "user_location" in data
    assert data["user_location"]["latitude"] == 40.7128
