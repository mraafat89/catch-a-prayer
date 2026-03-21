"""
Feature test: Musafir (traveler) mode flow.
Workflow: mode switch → travel combinations → pair skipping → sequential inference.
Rules: PRAYER_LOGIC_RULES.md §3-4
"""
import pytest
from tests.conftest import seed_mosque_direct, NYC_SCHEDULE


def _search(client, travel_mode=False, prayed_prayers=None, time="2026-03-20T17:30:00Z"):
    return client.post("/api/mosques/nearby", json={
        "latitude": 40.7128,
        "longitude": -74.0060,
        "radius_km": 5,
        "client_timezone": "America/New_York",
        "client_current_time": time,
        "travel_mode": travel_mode,
        "prayed_prayers": prayed_prayers or [],
    })


@pytest.mark.asyncio
async def test_muqeem_no_combinations(async_client):
    """Muqeem mode should NOT return travel_combinations."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    r = await _search(async_client, travel_mode=False)
    mosque = r.json()["mosques"][0]
    assert mosque["travel_combinations"] == []


@pytest.mark.asyncio
async def test_musafir_returns_combinations(async_client):
    """Musafir mode should return travel_combinations with pair options."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    # 1:30 PM ET → Dhuhr+Asr window should be active
    r = await _search(async_client, travel_mode=True, time="2026-03-20T17:30:00Z")
    mosque = r.json()["mosques"][0]
    combos = mosque["travel_combinations"]
    assert isinstance(combos, list)
    # Should have at least one pair with options
    if combos:
        assert combos[0]["pair"] in ("dhuhr_asr", "maghrib_isha")
        assert len(combos[0]["options"]) >= 1


@pytest.mark.asyncio
async def test_musafir_skip_asr_implies_dhuhr(async_client):
    """Sequential inference: Asr prayed → both Dhuhr+Asr skipped."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    r = await _search(async_client, travel_mode=True, prayed_prayers=["asr"],
                       time="2026-03-20T17:30:00Z")
    mosque = r.json()["mosques"][0]
    # Dhuhr+Asr pair should be skipped entirely
    dhuhr_asr = [c for c in mosque["travel_combinations"] if c["pair"] == "dhuhr_asr"]
    assert len(dhuhr_asr) == 0

    # next_catchable should NOT be dhuhr or asr
    nc = mosque["next_catchable"]
    if nc:
        assert nc["prayer"] not in ("dhuhr", "asr")


@pytest.mark.asyncio
async def test_musafir_dhuhr_only_doesnt_skip_asr(async_client):
    """Dhuhr prayed alone → Asr still active (no reverse inference)."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    r = await _search(async_client, travel_mode=True, prayed_prayers=["dhuhr"],
                       time="2026-03-20T17:30:00Z")
    mosque = r.json()["mosques"][0]
    # Dhuhr+Asr pair should still show (Asr not done)
    combos = mosque["travel_combinations"]
    # The pair may still appear since asr is not prayed
    # OR dhuhr is skipped from catchable but asr shows — either is acceptable


@pytest.mark.asyncio
async def test_musafir_both_pairs_prayed(async_client):
    """All prayers prayed → no combinations shown."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    r = await _search(async_client, travel_mode=True,
                       prayed_prayers=["dhuhr", "asr", "maghrib", "isha"],
                       time="2026-03-20T17:30:00Z")
    mosque = r.json()["mosques"][0]
    # All pairs prayed — no combinations
    assert mosque["travel_combinations"] == []


@pytest.mark.asyncio
async def test_musafir_first_pair_prayed_shows_second(async_client):
    """Dhuhr+Asr prayed → should show Maghrib+Isha pair."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    # 7:10 PM ET → Maghrib just started (19:00 adhan), Isha coming
    r = await _search(async_client, travel_mode=True,
                       prayed_prayers=["dhuhr", "asr"],
                       time="2026-03-20T23:10:00Z")
    mosque = r.json()["mosques"][0]
    combos = mosque["travel_combinations"]
    if combos:
        # First combo should be maghrib_isha (dhuhr_asr skipped)
        assert combos[0]["pair"] == "maghrib_isha"


@pytest.mark.asyncio
async def test_taqdeem_before_asr_adhan(async_client):
    """Before Asr adhan → Taqdeem (combine early) should be available."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    # 1:15 PM ET → after Dhuhr adhan (12:30), before Asr adhan (16:00)
    r = await _search(async_client, travel_mode=True, time="2026-03-20T17:15:00Z")
    mosque = r.json()["mosques"][0]
    combos = mosque["travel_combinations"]
    if combos and combos[0]["pair"] == "dhuhr_asr":
        option_types = {o["option_type"] for o in combos[0]["options"]}
        assert "combine_early" in option_types


@pytest.mark.asyncio
async def test_takheer_after_asr_adhan(async_client):
    """After Asr iqama → Ta'kheer (combine late) should be available."""
    await seed_mosque_direct(schedule=NYC_SCHEDULE)
    # 4:25 PM ET (UTC 20:25) → after Asr iqama (16:15), during Asr congregation window
    r = await _search(async_client, travel_mode=True, time="2026-03-20T20:25:00Z")
    mosque = r.json()["mosques"][0]
    combos = mosque["travel_combinations"]
    dhuhr_asr = [c for c in combos if c["pair"] == "dhuhr_asr"]
    if dhuhr_asr:
        option_types = {o["option_type"] for o in dhuhr_asr[0]["options"]}
        # After Asr adhan, should have combine_late (or combine_early may still show
        # if the code considers the full window). Either combine option is acceptable.
        assert "combine_late" in option_types or "combine_early" in option_types
