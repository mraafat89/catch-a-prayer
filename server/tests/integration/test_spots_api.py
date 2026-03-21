"""
Integration tests for prayer spots endpoints.
Source: server/app/api/spots.py
Rules: PRODUCT_REQUIREMENTS.md FR-5
"""
import pytest
from tests.conftest import seed_spot_direct


@pytest.mark.asyncio
async def test_submit_spot_success(async_client, db_session):
    response = await async_client.post("/api/spots", json={
        "name": "Airport Prayer Room",
        "spot_type": "prayer_room",
        "latitude": 40.6413,
        "longitude": -73.7781,
        "session_id": "test-session-submit-001",
    })
    assert response.status_code == 201
    data = response.json()
    assert "spot_id" in data
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_submit_spot_outside_bounds(async_client):
    response = await async_client.post("/api/spots", json={
        "name": "London Spot",
        "spot_type": "prayer_room",
        "latitude": 51.5074,
        "longitude": -0.1278,
        "session_id": "test-session-bounds-001",
    })
    assert response.status_code == 422
    assert "United States or Canada" in response.json()["detail"]


@pytest.mark.asyncio
async def test_submit_spot_url_in_name(async_client):
    response = await async_client.post("/api/spots", json={
        "name": "Visit http://spam.com",
        "spot_type": "prayer_room",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "session_id": "test-session-url-001",
    })
    assert response.status_code == 422
    assert "URL" in response.json()["detail"]


@pytest.mark.asyncio
async def test_submit_spot_dedup_50m(async_client, db_session):
    # First submission
    r1 = await async_client.post("/api/spots", json={
        "name": "Spot A",
        "spot_type": "prayer_room",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "session_id": "test-session-dedup-001",
    })
    assert r1.status_code == 201

    # Second at same location
    r2 = await async_client.post("/api/spots", json={
        "name": "Spot B",
        "spot_type": "prayer_room",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "session_id": "test-session-dedup-002",
    })
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_nearby_returns_active_spots(async_client):
    await seed_spot_direct(status="active", verification_count=5)
    response = await async_client.post("/api/spots/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
    })
    assert response.status_code == 200
    data = response.json()
    assert len(data["spots"]) >= 1


@pytest.mark.asyncio
async def test_nearby_hides_unverified_from_others(async_client):
    await seed_spot_direct(
        session_id="submitter-session",
        status="pending", verification_count=0,
    )
    response = await async_client.post("/api/spots/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
        "session_id": "different-session",
    })
    assert response.status_code == 200
    data = response.json()
    assert len(data["spots"]) == 0


@pytest.mark.asyncio
async def test_nearby_shows_own_pending(async_client):
    await seed_spot_direct(
        session_id="my-session",
        status="pending", verification_count=0,
    )
    response = await async_client.post("/api/spots/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
        "session_id": "my-session",
    })
    assert response.status_code == 200
    data = response.json()
    assert len(data["spots"]) >= 1


@pytest.mark.asyncio
async def test_verify_spot_positive(async_client):
    spot_id = await seed_spot_direct(
        session_id="submitter",
        status="pending", verification_count=0,
    )
    response = await async_client.post(f"/api/spots/{spot_id}/verify", json={
        "session_id": "voter-session-001",
        "is_positive": True,
        "attributes": {},
    })
    assert response.status_code == 200
    data = response.json()
    assert data["verification_count"] == 1


@pytest.mark.asyncio
async def test_verify_self_rejected(async_client):
    spot_id = await seed_spot_direct(session_id="submitter-self")
    response = await async_client.post(f"/api/spots/{spot_id}/verify", json={
        "session_id": "submitter-self",
        "is_positive": True,
        "attributes": {},
    })
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_verify_duplicate_rejected(async_client):
    spot_id = await seed_spot_direct(session_id="submitter-dup")

    # First vote
    r1 = await async_client.post(f"/api/spots/{spot_id}/verify", json={
        "session_id": "voter-dup-001",
        "is_positive": True,
        "attributes": {},
    })
    assert r1.status_code == 200

    # Duplicate vote
    r2 = await async_client.post(f"/api/spots/{spot_id}/verify", json={
        "session_id": "voter-dup-001",
        "is_positive": True,
        "attributes": {},
    })
    assert r2.status_code == 409
