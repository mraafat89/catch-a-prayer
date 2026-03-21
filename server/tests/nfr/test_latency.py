"""
NFR tests: Latency benchmarks.
Rules: PRODUCT_REQUIREMENTS.md NFR-1
"""
import time
import pytest
from tests.conftest import seed_mosque_direct, NYC_SCHEDULE


@pytest.mark.asyncio
async def test_health_under_100ms(async_client):
    start = time.monotonic()
    r = await async_client.get("/health")
    elapsed_ms = (time.monotonic() - start) * 1000
    assert r.status_code == 200
    assert elapsed_ms < 100, f"Health took {elapsed_ms:.0f}ms (target < 100ms)"


@pytest.mark.asyncio
async def test_nearby_under_2s(async_client):
    """POST /api/mosques/nearby should respond under 2 seconds."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    start = time.monotonic()
    r = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 10,
        "client_timezone": "America/New_York",
        "client_current_time": "2026-03-20T17:30:00Z",
    })
    elapsed_ms = (time.monotonic() - start) * 1000
    assert r.status_code == 200
    assert elapsed_ms < 2000, f"Nearby took {elapsed_ms:.0f}ms (target < 2000ms)"


@pytest.mark.asyncio
async def test_spots_nearby_under_500ms(async_client):
    start = time.monotonic()
    r = await async_client.post("/api/spots/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 10,
    })
    elapsed_ms = (time.monotonic() - start) * 1000
    assert r.status_code == 200
    assert elapsed_ms < 500, f"Spots nearby took {elapsed_ms:.0f}ms (target < 500ms)"


@pytest.mark.asyncio
async def test_suggestions_list_under_200ms(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)
    start = time.monotonic()
    r = await async_client.get(f"/api/mosques/{mosque_id}/suggestions")
    elapsed_ms = (time.monotonic() - start) * 1000
    assert r.status_code == 200
    assert elapsed_ms < 200, f"Suggestions list took {elapsed_ms:.0f}ms (target < 200ms)"
