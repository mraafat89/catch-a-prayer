"""
Feature test: Prayer spot lifecycle.
Workflow: submit → pending (invisible) → verify → active → reject → removed.
Rules: PRODUCT_REQUIREMENTS.md FR-5
"""
import pytest


@pytest.mark.asyncio
async def test_full_spot_lifecycle(async_client):
    """Submit → pending → verify x3 → active."""

    # 1. Submit spot
    r1 = await async_client.post("/api/spots", json={
        "name": "Airport Prayer Room",
        "spot_type": "prayer_room",
        "latitude": 40.6413,
        "longitude": -73.7781,
        "session_id": "submitter-lifecycle",
    })
    assert r1.status_code == 201
    spot_id = r1.json()["spot_id"]

    # 2. Spot is pending — only visible to submitter
    r_own = await async_client.post("/api/spots/nearby", json={
        "latitude": 40.6413, "longitude": -73.7781, "radius_km": 5,
        "session_id": "submitter-lifecycle",
    })
    own_ids = [s["id"] for s in r_own.json()["spots"]]
    assert spot_id in own_ids

    # 3. Not visible to others (0 external verifications)
    r_other = await async_client.post("/api/spots/nearby", json={
        "latitude": 40.6413, "longitude": -73.7781, "radius_km": 5,
        "session_id": "stranger-001",
    })
    other_ids = [s["id"] for s in r_other.json()["spots"]]
    assert spot_id not in other_ids

    # 4. First verification → now visible to others (1+ external)
    r_v1 = await async_client.post(
        f"/api/spots/{spot_id}/verify",
        json={"session_id": "voter-lc-1", "is_positive": True, "attributes": {}},
        headers={"X-Forwarded-For": "10.3.0.1"},
    )
    assert r_v1.status_code == 200
    assert r_v1.json()["verification_count"] == 1

    # Now visible to others
    r_visible = await async_client.post("/api/spots/nearby", json={
        "latitude": 40.6413, "longitude": -73.7781, "radius_km": 5,
        "session_id": "stranger-002",
    })
    visible_ids = [s["id"] for s in r_visible.json()["spots"]]
    assert spot_id in visible_ids

    # 5. Two more verifications → active (net >= 3)
    await async_client.post(
        f"/api/spots/{spot_id}/verify",
        json={"session_id": "voter-lc-2", "is_positive": True, "attributes": {}},
        headers={"X-Forwarded-For": "10.3.0.2"},
    )
    r_v3 = await async_client.post(
        f"/api/spots/{spot_id}/verify",
        json={"session_id": "voter-lc-3", "is_positive": True, "attributes": {}},
        headers={"X-Forwarded-For": "10.3.0.3"},
    )
    assert r_v3.json()["status"] == "active"


@pytest.mark.asyncio
async def test_spot_rejected_by_community(async_client):
    """Enough negative votes → spot rejected and hidden."""

    r1 = await async_client.post("/api/spots", json={
        "name": "Fake Spot",
        "spot_type": "other",
        "latitude": 40.7500,
        "longitude": -73.9800,
        "session_id": "submitter-reject",
    })
    spot_id = r1.json()["spot_id"]

    # 3 negative votes → net <= -3 → rejected
    for i in range(3):
        await async_client.post(
            f"/api/spots/{spot_id}/verify",
            json={"session_id": f"neg-voter-{i}", "is_positive": False, "attributes": {}},
            headers={"X-Forwarded-For": f"10.4.0.{i}"},
        )

    # Spot should no longer appear in search
    r_search = await async_client.post("/api/spots/nearby", json={
        "latitude": 40.7500, "longitude": -73.9800, "radius_km": 5,
        "session_id": "stranger-rej",
    })
    ids = [s["id"] for s in r_search.json()["spots"]]
    assert spot_id not in ids


@pytest.mark.asyncio
async def test_self_vote_prevented(async_client):
    """Submitter cannot verify their own spot."""
    r1 = await async_client.post("/api/spots", json={
        "name": "My Spot",
        "spot_type": "prayer_room",
        "latitude": 40.7000,
        "longitude": -74.0000,
        "session_id": "self-voter-spot",
    })
    spot_id = r1.json()["spot_id"]

    r_self = await async_client.post(f"/api/spots/{spot_id}/verify", json={
        "session_id": "self-voter-spot",
        "is_positive": True,
        "attributes": {},
    })
    assert r_self.status_code == 403


@pytest.mark.asyncio
async def test_dedup_within_50m(async_client):
    """Two spots at the same location → second rejected."""
    await async_client.post("/api/spots", json={
        "name": "Spot A",
        "spot_type": "prayer_room",
        "latitude": 40.7300,
        "longitude": -73.9900,
        "session_id": "dedup-author-1",
    })

    r2 = await async_client.post("/api/spots", json={
        "name": "Spot B",
        "spot_type": "prayer_room",
        "latitude": 40.7300,
        "longitude": -73.9900,
        "session_id": "dedup-author-2",
    })
    assert r2.status_code == 409
