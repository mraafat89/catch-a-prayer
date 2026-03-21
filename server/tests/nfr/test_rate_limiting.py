"""
NFR tests: Rate limiting enforcement.
Rules: PRODUCT_REQUIREMENTS.md NFR-2.5
"""
import pytest
from tests.conftest import seed_mosque_direct, NYC_SCHEDULE


@pytest.mark.asyncio
async def test_spot_submit_rate_limit_ip(async_client):
    """Max 2 spot submissions per IP per 24h (stricter than 3/session)."""
    for i in range(2):
        r = await async_client.post("/api/spots", json={
            "name": f"Rate Test Spot {i}",
            "spot_type": "prayer_room",
            "latitude": 40.7128 + i * 0.01,
            "longitude": -74.0060,
            "session_id": f"rate-session-{i}",  # different sessions
        }, headers={"X-Forwarded-For": "10.99.0.1"})  # same IP
        assert r.status_code == 201, f"Submission {i+1} should succeed"

    # 3rd from same IP → rate limited
    r3 = await async_client.post("/api/spots", json={
        "name": "Rate Test Spot 3",
        "spot_type": "prayer_room",
        "latitude": 40.7328,
        "longitude": -74.0060,
        "session_id": "rate-session-2",
    }, headers={"X-Forwarded-For": "10.99.0.1"})
    assert r3.status_code == 429


@pytest.mark.asyncio
async def test_suggestion_submit_rate_limit_ip(async_client):
    """Max 3 mosque suggestions per IP per 24h (stricter than 5/session)."""
    fields = ["fajr_iqama", "dhuhr_iqama", "asr_iqama"]
    for i, field in enumerate(fields):
        mosque_id = await seed_mosque_direct(
            name=f"Rate Mosque {i}", lat=40.7 + i * 0.01, schedule=NYC_SCHEDULE,
        )
        r = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
            "mosque_id": mosque_id,
            "field_name": field,
            "suggested_value": "13:30",
            "session_id": f"suggest-session-{i}",  # different sessions
        }, headers={"X-Forwarded-For": "10.98.0.1"})  # same IP
        assert r.status_code == 201, f"Suggestion {i+1} should succeed"

    # 4th from same IP → rate limited
    mosque_id = await seed_mosque_direct(
        name="Rate Mosque Extra", lat=40.76, schedule=NYC_SCHEDULE,
    )
    r4 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "maghrib_iqama",
        "suggested_value": "19:15",
        "session_id": "suggest-session-3",
    }, headers={"X-Forwarded-For": "10.98.0.1"})
    assert r4.status_code == 429
