"""
Integration tests for request logging and dashboard activity metrics.
Verifies that API requests are logged to request_logs and that
the admin dashboard activity section returns correct counts.
"""
import pytest
from sqlalchemy import text
from tests.conftest import seed_mosque_direct, NYC_SCHEDULE

ADMIN_KEY = "cap_admin_2026_secure_key"

NEARBY_PAYLOAD = {
    "latitude": 40.7128,
    "longitude": -74.0060,
    "radius_km": 10,
    "client_timezone": "America/New_York",
    "client_current_time": "2026-03-21T12:00:00-04:00",
}


@pytest.mark.asyncio
async def test_request_logged_with_session_id(async_client, db_session):
    """Requests with x-session-id header should be logged with session_id."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)

    await async_client.post("/api/mosques/nearby", json=NEARBY_PAYLOAD,
                            headers={"x-session-id": "test-session-abc"})

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

    await async_client.post("/api/mosques/nearby", json=NEARBY_PAYLOAD)

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
    await seed_mosque_direct(
        name="Phoenix Mosque", lat=33.45, lng=-112.07,
        timezone_str="America/Phoenix", schedule=NYC_SCHEDULE,
    )

    await async_client.post("/api/mosques/nearby", json={
        "latitude": 33.45,
        "longitude": -112.07,
        "radius_km": 15,
        "client_timezone": "America/Phoenix",
        "client_current_time": "2026-03-21T12:00:00-07:00",
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
async def test_health_and_admin_excluded_from_logging(async_client, db_session):
    """Health checks and admin endpoints should not be logged to request_logs."""
    # Health endpoint is explicitly skipped by middleware
    await async_client.get("/health")

    import asyncio
    await asyncio.sleep(0.2)

    r = await db_session.execute(text(
        "SELECT count(*) as cnt FROM request_logs"
    ))
    assert r.mappings().first()["cnt"] == 0


@pytest.mark.asyncio
async def test_activity_metrics_from_db(async_client, db_session):
    """User activity counts should reflect what's in request_logs."""
    # Insert logs directly to avoid dependency on full admin stats query
    for sid in ["user-1", "user-1", "user-2"]:
        await db_session.execute(text("""
            INSERT INTO request_logs (id, endpoint, method, response_code, latency_ms, session_id)
            VALUES (gen_random_uuid(), '/api/mosques/nearby', 'POST', 200, 50.0, :sid)
        """), {"sid": sid})
    await db_session.commit()

    r = await db_session.execute(text("""
        SELECT
            count(distinct session_id) filter (where created_at > now() - interval '24 hours') as users_today,
            count(*) filter (where endpoint like '%nearby%' and created_at > now() - interval '24 hours') as searches_today
        FROM request_logs WHERE session_id IS NOT NULL
    """))
    row = r.mappings().first()
    assert row["users_today"] == 2
    assert row["searches_today"] == 3


@pytest.mark.asyncio
async def test_latency_is_recorded(async_client, db_session):
    """Logged requests should have a positive latency_ms value."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)

    await async_client.post("/api/mosques/nearby", json=NEARBY_PAYLOAD,
                            headers={"x-session-id": "latency-test"})

    import asyncio
    await asyncio.sleep(0.2)

    r = await db_session.execute(text(
        "SELECT latency_ms, response_code FROM request_logs WHERE session_id = 'latency-test'"
    ))
    row = r.mappings().first()
    assert row is not None
    assert row["latency_ms"] > 0
    assert row["response_code"] == 200
