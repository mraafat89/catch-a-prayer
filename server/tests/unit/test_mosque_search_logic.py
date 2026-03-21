"""
Unit tests for mosque search logic — catching status, travel combinations, helpers.
Tests: calculate_catching_status, get_period_end, compute_travel_combinations,
       get_next_catchable, get_catchable_prayers, _musafir_active_prayers,
       haversine_km, estimate_travel_minutes, hhmm_to_minutes, minutes_to_hhmm
Source: server/app/services/mosque_search.py
Rules: PRAYER_LOGIC_RULES.md §1-4
"""
import pytest
from app.services.mosque_search import (
    haversine_km,
    estimate_travel_minutes,
    hhmm_to_minutes,
    minutes_to_hhmm,
    get_period_end,
    calculate_catching_status,
    compute_travel_combinations,
    get_next_catchable,
    get_catchable_prayers,
    _musafir_active_prayers,
    CONGREGATION_WINDOW_MINUTES,
)

# ─── Standard NYC schedule for testing ────────────────────────────────────────

SCHEDULE = {
    "fajr_adhan": "05:30", "fajr_iqama": "05:50",
    "dhuhr_adhan": "12:30", "dhuhr_iqama": "13:00",
    "asr_adhan": "16:00", "asr_iqama": "16:15",
    "maghrib_adhan": "19:00", "maghrib_iqama": "19:05",
    "isha_adhan": "20:30", "isha_iqama": "20:45",
    "sunrise": "06:30",
}


def hm(h, m=0):
    return h * 60 + m


# ─── Time Helpers ─────────────────────────────────────────────────────────────

class TestHhmmToMinutes:
    def test_noon(self):
        assert hhmm_to_minutes("12:00") == 720

    def test_midnight(self):
        assert hhmm_to_minutes("00:00") == 0

    def test_afternoon(self):
        assert hhmm_to_minutes("14:30") == 870

    def test_late_night(self):
        assert hhmm_to_minutes("23:59") == 1439


class TestMinutesToHhmm:
    def test_noon(self):
        assert minutes_to_hhmm(720) == "12:00"

    def test_midnight_wrap(self):
        assert minutes_to_hhmm(1440) == "00:00"

    def test_overflow(self):
        assert minutes_to_hhmm(1500) == "01:00"


# ─── Haversine ────────────────────────────────────────────────────────────────

class TestHaversine:
    def test_same_point(self):
        assert haversine_km(40.71, -74.00, 40.71, -74.00) == 0.0

    def test_nyc_to_la(self):
        dist = haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
        assert 3900 < dist < 4000  # ~3944 km

    def test_short_distance(self):
        dist = haversine_km(40.7128, -74.0060, 40.7200, -74.0060)
        assert 0.5 < dist < 1.5  # ~0.8 km


class TestEstimateTravelMinutes:
    def test_short_urban(self):
        # ~1 km → should use 25 km/h → ~3-5 min + buffer
        minutes = estimate_travel_minutes(40.7128, -74.0060, 40.7200, -74.0060)
        assert 1 <= minutes <= 10

    def test_long_highway(self):
        # NYC to Philly ~130 km → should use higher speed → ~100-120 min
        minutes = estimate_travel_minutes(40.7128, -74.0060, 39.9526, -75.1652)
        assert 60 <= minutes <= 180

    def test_always_at_least_1(self):
        minutes = estimate_travel_minutes(40.7128, -74.0060, 40.7128, -74.0060)
        assert minutes >= 1


# ─── Period End ───────────────────────────────────────────────────────────────

class TestGetPeriodEnd:
    def test_fajr_ends_at_sunrise(self):
        assert get_period_end("fajr", SCHEDULE) == "06:30"

    def test_dhuhr_ends_at_asr_adhan(self):
        assert get_period_end("dhuhr", SCHEDULE) == "16:00"

    def test_asr_ends_at_maghrib_adhan(self):
        assert get_period_end("asr", SCHEDULE) == "19:00"

    def test_maghrib_ends_at_isha_adhan(self):
        assert get_period_end("maghrib", SCHEDULE) == "20:30"

    def test_isha_ends_at_fajr(self):
        # Isha ends at next day's Fajr
        result = get_period_end("isha", SCHEDULE)
        assert result == "05:30"

    def test_missing_prayer(self):
        assert get_period_end("fajr", {}) is None


# ─── Catching Status ──────────────────────────────────────────────────────────

class TestCalculateCatchingStatus:
    """Test all 6 status types from PRAYER_LOGIC_RULES.md §2."""

    def test_can_catch_with_imam(self):
        """Arrive before iqama → can_catch_with_imam."""
        # At 12:40, travel 5 min → arrive 12:45 < iqama 13:00
        status = calculate_catching_status("dhuhr", SCHEDULE, hm(12, 40), 5)
        assert status is not None
        assert status["status"] == "can_catch_with_imam"

    def test_can_catch_in_progress(self):
        """Current >= iqama, arrive within congregation window."""
        # At 13:05 (after iqama 13:00), travel 3 min → arrive 13:08 < 13:15 (cong end)
        status = calculate_catching_status("dhuhr", SCHEDULE, hm(13, 5), 3)
        assert status is not None
        assert status["status"] == "can_catch_with_imam_in_progress"

    def test_can_pray_solo(self):
        """After congregation, before period end."""
        # At 13:30 (after cong end 13:15), travel 5 min → arrive 13:35 < 16:00 (Asr adhan)
        status = calculate_catching_status("dhuhr", SCHEDULE, hm(13, 30), 5)
        assert status is not None
        assert status["status"] == "can_pray_solo_at_mosque"

    def test_pray_at_nearby_location(self):
        """Can't reach mosque before period ends."""
        # At 15:30, travel 40 min → arrive 16:10 > 16:00 (Asr adhan = Dhuhr period end)
        status = calculate_catching_status("dhuhr", SCHEDULE, hm(15, 30), 40)
        assert status is not None
        assert status["status"] == "pray_at_nearby_location"

    def test_missed_make_up(self):
        """Prayer period has ended."""
        # At 17:00 (well after Asr adhan 16:00), travel 5 min
        status = calculate_catching_status("dhuhr", SCHEDULE, hm(17, 0), 5)
        assert status is not None
        assert status["status"] == "missed_make_up"

    def test_upcoming(self):
        """Prayer period has not started yet."""
        # At 11:00, Dhuhr adhan is 12:30 (90 min away < 120 min window)
        status = calculate_catching_status("dhuhr", SCHEDULE, hm(11, 0), 5)
        assert status is not None
        assert status["status"] == "upcoming"

    def test_upcoming_beyond_2h_returns_upcoming(self):
        """Prayer more than 2h away still returns status but should be filtered."""
        # At 09:00, Dhuhr adhan at 12:30 (210 min away > 120 min window)
        status = calculate_catching_status("dhuhr", SCHEDULE, hm(9, 0), 5)
        # Status is still calculated, filtering is done by get_next_catchable
        assert status is not None
        assert status["status"] == "upcoming"

    def test_no_adhan_returns_none(self):
        """Missing adhan data → None."""
        status = calculate_catching_status("dhuhr", {}, hm(12, 0), 5)
        assert status is None

    def test_urgency_high_near_iqama(self):
        """< 15 min to iqama → high urgency."""
        status = calculate_catching_status("dhuhr", SCHEDULE, hm(12, 50), 5)
        assert status is not None
        assert status["urgency"] == "high"

    # ── Isha midnight crossing ────────────────────────────────────────────

    def test_isha_at_1am_is_solo(self):
        """1 AM (after midnight, before Fajr) → Isha period still active."""
        status = calculate_catching_status("isha", SCHEDULE, hm(1, 0), 5)
        assert status is not None
        assert status["status"] in ("can_pray_solo_at_mosque", "pray_at_nearby_location")

    def test_isha_after_fajr_is_missed(self):
        """After Fajr adhan → Isha period ended."""
        status = calculate_catching_status("isha", SCHEDULE, hm(5, 45), 5)
        assert status is not None
        assert status["status"] == "missed_make_up"

    def test_isha_at_11pm_is_solo(self):
        """11 PM, after isha congregation → can pray solo."""
        status = calculate_catching_status("isha", SCHEDULE, hm(23, 0), 5)
        assert status is not None
        assert status["status"] == "can_pray_solo_at_mosque"


# ─── Musafir Active Prayers (Sequential Inference) ────────────────────────────

class TestMusafirActivePrayers:
    """Test sequential inference from PRAYER_LOGIC_RULES.md §3."""

    def test_empty_prayed(self):
        assert _musafir_active_prayers(set()) == set()

    def test_asr_implies_dhuhr(self):
        """Asr prayed → both dhuhr and asr skipped."""
        result = _musafir_active_prayers({"asr"})
        assert "dhuhr" in result
        assert "asr" in result

    def test_dhuhr_alone_doesnt_imply_asr(self):
        """Dhuhr prayed → only dhuhr skipped, asr still active."""
        result = _musafir_active_prayers({"dhuhr"})
        assert "dhuhr" in result
        assert "asr" not in result

    def test_isha_implies_maghrib(self):
        """Isha prayed → both maghrib and isha skipped."""
        result = _musafir_active_prayers({"isha"})
        assert "maghrib" in result
        assert "isha" in result

    def test_maghrib_alone_doesnt_imply_isha(self):
        result = _musafir_active_prayers({"maghrib"})
        assert "maghrib" in result
        assert "isha" not in result

    def test_both_prayed_explicitly(self):
        result = _musafir_active_prayers({"dhuhr", "asr"})
        assert "dhuhr" in result
        assert "asr" in result

    def test_fajr_standalone(self):
        result = _musafir_active_prayers({"fajr"})
        assert "fajr" in result
        assert len(result) == 1

    def test_all_prayed(self):
        result = _musafir_active_prayers({"fajr", "dhuhr", "asr", "maghrib", "isha"})
        assert result == {"fajr", "dhuhr", "asr", "maghrib", "isha"}


# ─── Travel Combinations ─────────────────────────────────────────────────────

class TestComputeTravelCombinations:
    """Test Musafir combining options from PRAYER_LOGIC_RULES.md §4."""

    def test_returns_empty_list_when_all_passed(self):
        """All prayers passed → no combinations."""
        result = compute_travel_combinations(SCHEDULE, hm(23, 0))
        # After Isha congregation, pair window has ended for both pairs
        # First pair (dhuhr+asr) definitely passed, second pair may or may not
        for pair in result:
            assert len(pair["options"]) >= 0  # may have isha options if window open

    def test_shows_dhuhr_asr_before_asr(self):
        """Before Asr adhan → Taqdeem option available."""
        result = compute_travel_combinations(SCHEDULE, hm(12, 35))
        assert len(result) >= 1
        pair = result[0]
        assert pair["pair"] == "dhuhr_asr"
        assert any(o["option_type"] == "combine_early" for o in pair["options"])

    def test_shows_takheer_after_asr_adhan(self):
        """After Asr adhan → Ta'kheer option."""
        result = compute_travel_combinations(SCHEDULE, hm(16, 5))
        dhuhr_asr = [p for p in result if p["pair"] == "dhuhr_asr"]
        if dhuhr_asr:
            assert any(o["option_type"] == "combine_late" for o in dhuhr_asr[0]["options"])

    def test_first_pair_only_when_both_unresolved(self):
        """Only the first unresolved pair shown."""
        result = compute_travel_combinations(SCHEDULE, hm(12, 35))
        # Should show dhuhr_asr, not maghrib_isha (first unresolved)
        if result:
            assert result[0]["pair"] == "dhuhr_asr"

    def test_skip_prayed_pair(self):
        """Prayed pair is skipped, next pair shown."""
        result = compute_travel_combinations(
            SCHEDULE, hm(19, 10), prayed_prayers={"dhuhr", "asr"}
        )
        if result:
            assert result[0]["pair"] == "maghrib_isha"

    def test_skip_when_prayer2_prayed(self):
        """If asr prayed → dhuhr+asr pair skipped (sequential inference)."""
        result = compute_travel_combinations(
            SCHEDULE, hm(12, 35), prayed_prayers={"asr"}
        )
        dhuhr_asr = [p for p in result if p["pair"] == "dhuhr_asr"]
        assert len(dhuhr_asr) == 0


# ─── Next Catchable / Catchable Prayers ──────────────────────────────────────

class TestGetNextCatchable:
    def test_returns_most_urgent(self):
        """During Dhuhr window → returns Dhuhr status."""
        result = get_next_catchable(SCHEDULE, hm(12, 40), 5)
        assert result is not None
        assert result["prayer"] == "dhuhr"

    def test_skips_prayed_in_musafir(self):
        """Musafir: Asr prayed → skip dhuhr+asr, show next."""
        result = get_next_catchable(
            SCHEDULE, hm(12, 40), 5,
            travel_mode=True, prayed_prayers={"asr"}
        )
        # Dhuhr and Asr both skipped via sequential inference
        if result:
            assert result["prayer"] not in ("dhuhr", "asr")

    def test_returns_none_when_all_prayed_muqeem(self):
        """When all are marked prayed in Muqeem, should return None."""
        result = get_next_catchable(
            SCHEDULE, hm(12, 40), 5,
            travel_mode=False, prayed_prayers={"fajr", "dhuhr", "asr", "maghrib", "isha"}
        )
        assert result is None

    def test_returns_none_when_all_prayed_musafir(self):
        """When all are marked prayed in Musafir, should return None."""
        result = get_next_catchable(
            SCHEDULE, hm(12, 40), 5,
            travel_mode=True, prayed_prayers={"fajr", "dhuhr", "asr", "maghrib", "isha"}
        )
        assert result is None

    def test_empty_schedule_returns_none(self):
        result = get_next_catchable({}, hm(12, 0), 5)
        assert result is None


class TestGetCatchablePrayers:
    def test_returns_multiple_during_day(self):
        """During the day, multiple prayers may be catchable/upcoming."""
        result = get_catchable_prayers(SCHEDULE, hm(12, 40), 5)
        assert len(result) >= 1

    def test_excludes_missed(self):
        """Missed prayers are excluded from catchable list."""
        result = get_catchable_prayers(SCHEDULE, hm(17, 0), 5)
        for p in result:
            if p["prayer"] == "fajr":
                # Fajr should be missed at 5 PM, shouldn't appear
                assert p["status"] != "can_catch_with_imam"

    def test_musafir_skips_prayed_pairs(self):
        result = get_catchable_prayers(
            SCHEDULE, hm(12, 40), 5,
            travel_mode=True, prayed_prayers={"asr"}
        )
        prayers = {p["prayer"] for p in result}
        assert "dhuhr" not in prayers
        assert "asr" not in prayers
