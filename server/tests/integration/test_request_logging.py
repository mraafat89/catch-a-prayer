"""
Integration tests for request logging and dashboard activity metrics.
Verifies that API requests are logged to request_logs and that
the admin dashboard activity section returns correct counts.
"""
import pytest
from sqlalchemy import text
from tests.conftest import seed_mosque_direct, NYC_SCHEDULE

ADMIN_KEY = "cap_admin_2026_secure_key"


@pytest.mark.asyncio
async def test_request_logged_with_session_id(async_client, db_session):
    """Requests with x-session-id header should be logged with session_id."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)

    await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 10,
    }, headers={"x-session-id": "test-session-abc"})

    # Give async task a moment to complete
    import asyncio
    await asyncio.sleep(0.2)

    r = await db_session.execute(text(
        "SELECT endpoint, method, session_id, lat, lng FROM request_logs"
    ))
    rows = r.mappings().all()
    assert len(rows) >= 1
    log = rows[0]
    assert log["session_id"] == "test-session-abc"
    assert log["endpoint"] == "/api/mosques/nearby"
    assert log["method"] == "POST"


@pytest.mark.asyncio
async def test_request_logged_without_session_id(async_client, db_session):
    """Requests without x-session-id should still be logged (session_id=NULL)."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)

    await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 10,
    })

    import asyncio
    await asyncio.sleep(0.2)

    r = await db_session.execute(text(
        "SELECT session_id FROM request_logs WHERE endpoint = '/api/mosques/nearby'"
    ))
    rows = r.mappings().all()
    assert len(rows) >= 1
    assert rows[0]["session_id"] is None


@pytest.mark.asyncio
async def test_nearby_search_logs_lat_lng(async_client, db_session):
    """Nearby searches should log latitude and longitude from request body."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)

    await async_client.post("/api/mosques/nearby", json={
        "latitude": 33.45,
        "longitude": -112.07,
        "radius_km": 15,
    }, headers={"x-session-id": "geo-session"})

    import asyncio
    await asyncio.sleep(0.2)

    r = await db_session.execute(text(
        "SELECT lat, lng, radius_km FROM request_logs WHERE session_id = 'geo-session'"
    ))
    row = r.mappings().first()
    assert row is not None
    assert abs(row["lat"] - 33.45) < 0.01
    assert abs(row["lng"] - (-112.07)) < 0.01
    assert abs(row["radius_km"] - 15) < 0.01


@pytest.mark.asyncio
async def test_admin_stats_excluded_from_logging(async_client, db_session):
    """Admin endpoints should not be logged to request_logs."""
    await async_client.get(f"/api/admin/stats?key={ADMIN_KEY}")

    import asyncio
    await asyncio.sleep(0.2)

    r = await db_session.execute(text(
        "SELECT count(*) as cnt FROM request_logs WHERE endpoint LIKE '%admin%'"
    ))
    assert r.mappings().first()["cnt"] == 0


@pytest.mark.asyncio
async def test_activity_metrics_reflect_logged_requests(async_client, db_session):
    """Dashboard activity metrics should count logged requests correctly."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)

    # Make 3 searches from 2 different sessions
    for sid in ["user-1", "user-1", "user-2"]:
        await async_client.post("/api/mosques/nearby", json={
            "latitude": 40.71,
            "longitude": -74.00,
            "radius_km": 10,
        }, headers={"x-session-id": sid})

    import asyncio
    await asyncio.sleep(0.3)

    r = await async_client.get(f"/api/admin/stats?key={ADMIN_KEY}")
    assert r.status_code == 200
    stats = r.json()
    ua = stats["user_activity"]
    assert ua["users_today"] == 2
    assert ua["searches_today"] == 3


@pytest.mark.asyncio
async def test_latency_is_recorded(async_client, db_session):
    """Logged requests should have a positive latency_ms value."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)

    await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.71,
        "longitude": -74.00,
        "radius_km": 10,
    }, headers={"x-session-id": "latency-test"})

    import asyncio
    await asyncio.sleep(0.2)

    r = await db_session.execute(text(
        "SELECT latency_ms, response_code FROM request_logs WHERE session_id = 'latency-test'"
    ))
    row = r.mappings().first()
    assert row is not None
    assert row["latency_ms"] > 0
    assert row["response_code"] == 200
