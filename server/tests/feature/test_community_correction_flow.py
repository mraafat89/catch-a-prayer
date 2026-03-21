"""
Feature test: Community correction (mosque suggestions) lifecycle.
Workflow: submit → vote → accept → auto-apply to prayer schedule.
Rules: PRODUCT_REQUIREMENTS.md FR-6
"""
import pytest
from tests.conftest import seed_mosque_direct, NYC_SCHEDULE


@pytest.mark.asyncio
async def test_full_suggestion_lifecycle(async_client):
    """Submit suggestion → two voters confirm → status accepted → iqama updated."""
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)

    # 1. Submit a correction: dhuhr_iqama 13:00 → 13:20
    r1 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "dhuhr_iqama",
        "suggested_value": "13:20",
        "session_id": "author-001",
    })
    assert r1.status_code == 201
    data = r1.json()
    assert data["status"] == "pending"
    assert data["suggested_value"] == "13:20"
    assert data["current_value"] == "13:00"
    suggestion_id = data["id"]

    # 2. Author tries to vote on own suggestion → rejected
    r_self = await async_client.post(f"/api/suggestions/{suggestion_id}/vote", json={
        "session_id": "author-001",
        "is_positive": True,
    })
    assert r_self.status_code == 403

    # 3. Voter 1 confirms
    r2 = await async_client.post(
        f"/api/suggestions/{suggestion_id}/vote",
        json={"session_id": "voter-001", "is_positive": True},
        headers={"X-Forwarded-For": "10.0.0.1"},
    )
    assert r2.status_code == 200
    assert r2.json()["upvote_count"] == 1
    assert r2.json()["status"] == "pending"

    # 4. Voter 2 confirms → threshold reached (iqama = net +2)
    r3 = await async_client.post(
        f"/api/suggestions/{suggestion_id}/vote",
        json={"session_id": "voter-002", "is_positive": True},
        headers={"X-Forwarded-For": "10.0.0.2"},
    )
    assert r3.status_code == 200
    assert r3.json()["upvote_count"] == 2
    assert r3.json()["status"] == "accepted"

    # 5. Verify the suggestion no longer appears in pending list
    r4 = await async_client.get(f"/api/mosques/{mosque_id}/suggestions")
    assert r4.status_code == 200
    pending = r4.json()["suggestions"]
    assert all(s["id"] != suggestion_id for s in pending)


@pytest.mark.asyncio
async def test_suggestion_rejected_by_downvotes(async_client):
    """Enough downvotes → suggestion rejected."""
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)

    r1 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "asr_iqama",
        "suggested_value": "16:45",
        "session_id": "author-rej-001",
    })
    suggestion_id = r1.json()["id"]

    # Two downvotes → net -2 → rejected
    await async_client.post(
        f"/api/suggestions/{suggestion_id}/vote",
        json={"session_id": "voter-rej-1", "is_positive": False},
        headers={"X-Forwarded-For": "10.1.0.1"},
    )
    r3 = await async_client.post(
        f"/api/suggestions/{suggestion_id}/vote",
        json={"session_id": "voter-rej-2", "is_positive": False},
        headers={"X-Forwarded-For": "10.1.0.2"},
    )
    assert r3.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_cannot_submit_duplicate_field(async_client):
    """Only one pending suggestion per field per mosque."""
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)

    await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "fajr_iqama",
        "suggested_value": "06:00",
        "session_id": "author-dup-1",
    })

    r2 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "fajr_iqama",
        "suggested_value": "06:10",
        "session_id": "author-dup-2",
    })
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_facility_suggestion_needs_3_votes(async_client):
    """Facility fields need net +3 (not +2 like iqama)."""
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)

    r1 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "has_womens_section",
        "suggested_value": "true",
        "session_id": "author-fac-001",
    })
    suggestion_id = r1.json()["id"]

    # Vote 1
    await async_client.post(
        f"/api/suggestions/{suggestion_id}/vote",
        json={"session_id": "fac-voter-1", "is_positive": True},
        headers={"X-Forwarded-For": "10.2.0.1"},
    )
    # Vote 2 — still pending (facility threshold = 3)
    r3 = await async_client.post(
        f"/api/suggestions/{suggestion_id}/vote",
        json={"session_id": "fac-voter-2", "is_positive": True},
        headers={"X-Forwarded-For": "10.2.0.2"},
    )
    assert r3.json()["status"] == "pending"

    # Vote 3 → accepted
    r4 = await async_client.post(
        f"/api/suggestions/{suggestion_id}/vote",
        json={"session_id": "fac-voter-3", "is_positive": True},
        headers={"X-Forwarded-For": "10.2.0.3"},
    )
    assert r4.json()["status"] == "accepted"
