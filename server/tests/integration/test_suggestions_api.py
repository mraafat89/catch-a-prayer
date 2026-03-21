"""
Integration tests for mosque suggestions endpoints.
Source: server/app/api/suggestions.py
Rules: PRODUCT_REQUIREMENTS.md FR-6
"""
import pytest
from tests.conftest import seed_mosque_direct, NYC_SCHEDULE


@pytest.mark.asyncio
async def test_submit_iqama_suggestion(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)
    response = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "dhuhr_iqama",
        "suggested_value": "13:15",
        "session_id": "suggest-session-001",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["field_name"] == "dhuhr_iqama"
    assert data["suggested_value"] == "13:15"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_submit_invalid_time_format(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)
    response = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "dhuhr_iqama",
        "suggested_value": "abc",
        "session_id": "suggest-session-002",
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_same_as_current_rejected(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)
    response = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "dhuhr_iqama",
        "suggested_value": "13:00",  # same as NYC_SCHEDULE dhuhr_iqama
        "session_id": "suggest-session-003",
    })
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_pending_rejected(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)

    # First suggestion
    r1 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "asr_iqama",
        "suggested_value": "16:30",
        "session_id": "suggest-session-004",
    })
    assert r1.status_code == 201

    # Duplicate for same field
    r2 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "asr_iqama",
        "suggested_value": "16:45",
        "session_id": "suggest-session-005",
    })
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_submit_boolean_suggestion(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)
    response = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "has_womens_section",
        "suggested_value": "true",
        "session_id": "suggest-session-006",
    })
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_submit_nonexistent_mosque(async_client):
    response = await async_client.post("/api/mosques/00000000-0000-0000-0000-000000000000/suggestions", json={
        "mosque_id": "00000000-0000-0000-0000-000000000000",
        "field_name": "dhuhr_iqama",
        "suggested_value": "13:15",
        "session_id": "suggest-session-007",
    })
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_vote_increments_count(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)

    # Submit suggestion
    r1 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "fajr_iqama",
        "suggested_value": "06:00",
        "session_id": "suggest-author-001",
    })
    assert r1.status_code == 201
    suggestion_id = r1.json()["id"]

    # Vote positive
    r2 = await async_client.post(f"/api/suggestions/{suggestion_id}/vote", json={
        "session_id": "voter-session-001",
        "is_positive": True,
    })
    assert r2.status_code == 200
    assert r2.json()["upvote_count"] == 1
    assert r2.json()["downvote_count"] == 0


@pytest.mark.asyncio
async def test_self_vote_rejected(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)

    r1 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "maghrib_iqama",
        "suggested_value": "19:10",
        "session_id": "self-voter-001",
    })
    suggestion_id = r1.json()["id"]

    r2 = await async_client.post(f"/api/suggestions/{suggestion_id}/vote", json={
        "session_id": "self-voter-001",
        "is_positive": True,
    })
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_vote_rejected(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)

    r1 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "isha_iqama",
        "suggested_value": "21:00",
        "session_id": "dup-author-001",
    })
    suggestion_id = r1.json()["id"]

    # First vote
    await async_client.post(f"/api/suggestions/{suggestion_id}/vote", json={
        "session_id": "dup-voter-001",
        "is_positive": True,
    })

    # Duplicate
    r3 = await async_client.post(f"/api/suggestions/{suggestion_id}/vote", json={
        "session_id": "dup-voter-001",
        "is_positive": True,
    })
    assert r3.status_code == 409


@pytest.mark.asyncio
async def test_suggestion_accepted_after_threshold(async_client, db_session):
    """Iqama suggestion accepted at net +2 upvotes."""
    mosque_id = await seed_mosque(db_session, schedule=NYC_SCHEDULE)

    r1 = await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "dhuhr_iqama",
        "suggested_value": "13:30",
        "session_id": "threshold-author",
    })
    suggestion_id = r1.json()["id"]

    # Vote 1
    await async_client.post(f"/api/suggestions/{suggestion_id}/vote", json={
        "session_id": "threshold-voter-1",
        "is_positive": True,
    })

    # Vote 2 — should trigger acceptance (iqama threshold = 2)
    r3 = await async_client.post(f"/api/suggestions/{suggestion_id}/vote", json={
        "session_id": "threshold-voter-2",
        "is_positive": True,
    })
    assert r3.status_code == 200
    assert r3.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_list_shows_pending_only(async_client):
    mosque_id = await seed_mosque_direct(schedule=NYC_SCHEDULE)

    # Submit a suggestion (will be pending)
    await async_client.post(f"/api/mosques/{mosque_id}/suggestions", json={
        "mosque_id": mosque_id,
        "field_name": "asr_iqama",
        "suggested_value": "16:30",
        "session_id": "list-author-001",
    })

    response = await async_client.get(f"/api/mosques/{mosque_id}/suggestions")
    assert response.status_code == 200
    data = response.json()
    assert len(data["suggestions"]) >= 1
    for s in data["suggestions"]:
        assert s["status"] == "pending"
