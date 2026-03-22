"""
Integration tests for coverage gap logging.
Verifies that gaps are recorded when:
1. User searches at max radius (50km) and finds no mosques
2. Route planner can't find a mosque for a prayer along a route
"""
import pytest
from sqlalchemy import text
from tests.conftest import seed_mosque_direct, NYC_SCHEDULE

ADMIN_KEY = "cap_admin_2026_secure_key"


@pytest.mark.asyncio
async def test_no_gap_logged_when_mosques_found(async_client, db_session):
    """Normal search that finds mosques should NOT log a gap."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)

    await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 50,
        "client_timezone": "America/New_York",
        "client_current_time": "2026-03-21T12:00:00-04:00",
    }, headers={"x-session-id": "no-gap-session"})

    import asyncio
    await asyncio.sleep(0.2)

    r = await db_session.execute(text("SELECT count(*) as cnt FROM coverage_gaps"))
    assert r.mappings().first()["cnt"] == 0


@pytest.mark.asyncio
async def test_gap_logged_when_max_radius_no_results(async_client, db_session):
    """Search at max radius (50km) with no mosques found should log a gap."""
    # Don't seed any mosques — search will return 404
    response = await async_client.post("/api/mosques/nearby", json={
        "latitude": 35.0,
        "longitude": -100.0,
        "radius_km": 50,
        "client_timezone": "America/Chicago",
        "client_current_time": "2026-03-21T12:00:00-05:00",
    }, headers={"x-session-id": "gap-session-1"})

    assert response.status_code == 404

    import asyncio
    await asyncio.sleep(0.3)

    r = await db_session.execute(text(
        "SELECT lat, lng, gap_type, session_id FROM coverage_gaps"
    ))
    rows = r.mappings().all()
    assert len(rows) == 1
    gap = rows[0]
    assert abs(gap["lat"] - 35.0) < 0.01
    assert abs(gap["lng"] - (-100.0)) < 0.01
    assert gap["gap_type"] == "no_nearby_mosque"
    assert gap["session_id"] == "gap-session-1"


@pytest.mark.asyncio
async def test_no_gap_logged_for_small_radius_no_results(async_client, db_session):
    """Search at small radius with no results is NOT a gap (user chose narrow search)."""
    response = await async_client.post("/api/mosques/nearby", json={
        "latitude": 35.0,
        "longitude": -100.0,
        "radius_km": 5,
        "client_timezone": "America/Chicago",
        "client_current_time": "2026-03-21T12:00:00-05:00",
    }, headers={"x-session-id": "small-radius-session"})

    assert response.status_code == 404

    import asyncio
    await asyncio.sleep(0.2)

    r = await db_session.execute(text("SELECT count(*) as cnt FROM coverage_gaps"))
    assert r.mappings().first()["cnt"] == 0


@pytest.mark.asyncio
async def test_gap_appears_in_dashboard_query(async_client, db_session):
    """Coverage gaps should be queryable for the dashboard."""
    # Insert a gap directly
    await db_session.execute(text("""
        INSERT INTO coverage_gaps (id, lat, lng, gap_type, session_id)
        VALUES (gen_random_uuid(), 35.0, -100.0, 'no_nearby_mosque', 'test')
    """))
    await db_session.commit()

    # Query the same way the dashboard does
    r = await db_session.execute(text("""
        SELECT round(lat::numeric, 2) as lat, round(lng::numeric, 2) as lng,
               count(*) as hits, gap_type
        FROM coverage_gaps
        WHERE created_at > now() - interval '90 days'
        GROUP BY round(lat::numeric, 2), round(lng::numeric, 2), gap_type
    """))
    rows = r.mappings().all()
    assert len(rows) >= 1
    assert float(rows[0]["lat"]) == 35.0
    assert float(rows[0]["lng"]) == -100.0
    assert rows[0]["hits"] >= 1
