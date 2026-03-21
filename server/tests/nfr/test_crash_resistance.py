"""
NFR tests: Crash resistance — bad inputs should return errors, not 500s.
Rules: PRODUCT_REQUIREMENTS.md NFR-4.1
"""
import pytest


@pytest.mark.asyncio
async def test_nearby_empty_db(async_client):
    """No mosques seeded → should return 200 with empty list, not 500."""
    r = await async_client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": "2026-03-20T17:30:00Z",
    })
    # Should not crash — either 200 with empty list or 404
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert len(r.json()["mosques"]) == 0


@pytest.mark.asyncio
async def test_nearby_invalid_json(async_client):
    """Malformed request body → 422, not 500."""
    r = await async_client.post("/api/mosques/nearby", content=b"not json",
                                 headers={"Content-Type": "application/json"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_nearby_missing_required_fields(async_client):
    """Missing latitude → 422."""
    r = await async_client.post("/api/mosques/nearby", json={
        "longitude": -74.0060,
        "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": "2026-03-20T17:30:00Z",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_spot_submit_empty_name(async_client):
    """Empty name → 422."""
    r = await async_client.post("/api/spots", json={
        "name": "",
        "spot_type": "prayer_room",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "session_id": "crash-test-001",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_spot_submit_invalid_type(async_client):
    """Invalid spot_type → 422."""
    r = await async_client.post("/api/spots", json={
        "name": "Test",
        "spot_type": "INVALID_TYPE",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "session_id": "crash-test-002",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_suggestion_nonexistent_mosque(async_client):
    """Suggestion for non-existent mosque → 404, not 500."""
    r = await async_client.post(
        "/api/mosques/00000000-0000-0000-0000-000000000000/suggestions",
        json={
            "mosque_id": "00000000-0000-0000-0000-000000000000",
            "field_name": "dhuhr_iqama",
            "suggested_value": "13:15",
            "session_id": "crash-test-003",
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_vote_nonexistent_suggestion(async_client):
    """Vote on non-existent suggestion → 404, not 500."""
    r = await async_client.post(
        "/api/suggestions/00000000-0000-0000-0000-000000000000/vote",
        json={"session_id": "crash-test-004", "is_positive": True},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_verify_nonexistent_spot(async_client):
    """Verify non-existent spot → 404, not 500."""
    r = await async_client.post(
        "/api/spots/00000000-0000-0000-0000-000000000000/verify",
        json={"session_id": "crash-test-005", "is_positive": True, "attributes": {}},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_suggestion_invalid_field_name(async_client):
    """Invalid field_name → 422."""
    r = await async_client.post(
        "/api/mosques/00000000-0000-0000-0000-000000000000/suggestions",
        json={
            "mosque_id": "00000000-0000-0000-0000-000000000000",
            "field_name": "INVALID_FIELD",
            "suggested_value": "test",
            "session_id": "crash-test-006",
        },
    )
    assert r.status_code == 422
