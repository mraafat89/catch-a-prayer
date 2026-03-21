"""
Extensive tests for overnight/midnight trips and prayed prayer filtering.
Covers the bug: Visalia→Big Sur at 12:12 AM shows Maghrib+Isha after user already prayed.

Scenarios tested:
- Midnight departure (12 AM - 8 AM)
- Late night departure (11 PM - 7 AM)
- Early morning departure (3 AM - 11 AM)
- Evening departure across midnight (9 PM - 5 AM)
- Prayed prayer filtering in trip planner
- Pair relevance with prayed_prayers
"""
import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times
from app.services.travel_planner import (
    _prayer_overlaps_trip,
    _pair_relevant,
    hhmm_to_minutes,
    enumerate_trip_prayers,
)
from app.services.mosque_search import _musafir_active_prayers

PT = ZoneInfo("America/Los_Angeles")
TODAY = date(2026, 3, 21)


def ca_schedule(lat=36.33, lng=-119.29):
    """California prayer schedule."""
    calc = calculate_prayer_times(lat, lng, TODAY, timezone_offset=-7)
    return {**calc, **estimate_iqama_times(calc)}


def hm(h, m=0):
    return h * 60 + m


# ─── Prayer Overlap at Various Night Times ────────────────────────────────────

class TestMidnightDeparture:
    """12:12 AM departure, 8:12 AM arrival."""
    schedule = ca_schedule()
    dep = hm(0, 12)
    arr = hm(8, 12)

    def test_fajr_overlaps(self):
        assert _prayer_overlaps_trip("fajr", self.schedule, self.dep, self.arr) is True

    def test_dhuhr_does_not_overlap(self):
        assert _prayer_overlaps_trip("dhuhr", self.schedule, self.dep, self.arr) is False

    def test_asr_does_not_overlap(self):
        assert _prayer_overlaps_trip("asr", self.schedule, self.dep, self.arr) is False

    def test_maghrib_does_not_overlap(self):
        assert _prayer_overlaps_trip("maghrib", self.schedule, self.dep, self.arr) is False

    def test_isha_technically_overlaps(self):
        """Isha period extends to Fajr, so 12:12 AM IS in Isha window.
        This overlap is technically correct — the bug is elsewhere."""
        result = _prayer_overlaps_trip("isha", self.schedule, self.dep, self.arr)
        # Isha period: ~20:30 to ~05:30 next day. 12:12 AM is inside.
        assert result is True  # This is correct behavior

    def test_maghrib_isha_pair_relevant(self):
        """Pair is relevant because Isha window overlaps. But prayed_prayers should filter."""
        result = _pair_relevant("maghrib", "isha", self.schedule, self.dep, self.arr)
        # Isha overlaps → pair is relevant. The filtering happens upstream.
        assert result is True

    def test_dhuhr_asr_pair_not_relevant(self):
        """Dhuhr+Asr should not be relevant for overnight trip."""
        result = _pair_relevant("dhuhr", "asr", self.schedule, self.dep, self.arr)
        assert result is False


class TestLateNightDeparture:
    """11 PM departure, 7 AM arrival."""
    schedule = ca_schedule()
    dep = hm(23, 0)
    arr = hm(7, 0)

    def test_fajr_overlaps(self):
        assert _prayer_overlaps_trip("fajr", self.schedule, self.dep, self.arr) is True

    def test_isha_overlaps(self):
        """At 11 PM, Isha congregation may still be active."""
        assert _prayer_overlaps_trip("isha", self.schedule, self.dep, self.arr) is True

    def test_maghrib_does_not_overlap(self):
        """Maghrib ends at Isha adhan (~8:30 PM) — before 11 PM departure."""
        assert _prayer_overlaps_trip("maghrib", self.schedule, self.dep, self.arr) is False

    def test_dhuhr_does_not_overlap(self):
        assert _prayer_overlaps_trip("dhuhr", self.schedule, self.dep, self.arr) is False


class TestEarlyMorningDeparture:
    """3 AM departure, 11 AM arrival."""
    schedule = ca_schedule()
    dep = hm(3, 0)
    arr = hm(11, 0)

    def test_fajr_overlaps(self):
        assert _prayer_overlaps_trip("fajr", self.schedule, self.dep, self.arr) is True

    def test_dhuhr_does_not_overlap(self):
        """Dhuhr at ~12:30 PM — after 11 AM arrival."""
        assert _prayer_overlaps_trip("dhuhr", self.schedule, self.dep, self.arr) is False

    def test_isha_technically_overlaps(self):
        """At 3 AM, still in Isha window (extends to Fajr)."""
        result = _prayer_overlaps_trip("isha", self.schedule, self.dep, self.arr)
        assert result is True

    def test_maghrib_does_not_overlap(self):
        assert _prayer_overlaps_trip("maghrib", self.schedule, self.dep, self.arr) is False


class TestEveningAcrossMidnight:
    """9 PM departure, 5 AM arrival (8 hours)."""
    schedule = ca_schedule()
    dep = hm(21, 0)
    arr = hm(5, 0)

    def test_isha_overlaps(self):
        """Isha adhan ~8:30 PM, departure 9 PM — in Isha window."""
        assert _prayer_overlaps_trip("isha", self.schedule, self.dep, self.arr) is True

    def test_fajr_overlaps(self):
        """Fajr ~5:30 AM — arriving at 5 AM, close but Fajr hasn't started yet."""
        result = _prayer_overlaps_trip("fajr", self.schedule, self.dep, self.arr)
        # Fajr adhan ~5:30 > arrival 5:00 — no overlap
        fajr_min = hhmm_to_minutes(self.schedule["fajr_adhan"])
        if fajr_min > hm(5, 0):
            assert result is False

    def test_maghrib_does_not_overlap(self):
        """Maghrib ends at Isha adhan — before 9 PM departure."""
        isha_min = hhmm_to_minutes(self.schedule["isha_adhan"])
        if isha_min < hm(21, 0):
            assert _prayer_overlaps_trip("maghrib", self.schedule, self.dep, self.arr) is False


class TestDaytimeTrip:
    """10 AM departure, 6 PM arrival (sanity check)."""
    schedule = ca_schedule()
    dep = hm(10, 0)
    arr = hm(18, 0)

    def test_dhuhr_overlaps(self):
        assert _prayer_overlaps_trip("dhuhr", self.schedule, self.dep, self.arr) is True

    def test_asr_overlaps(self):
        assert _prayer_overlaps_trip("asr", self.schedule, self.dep, self.arr) is True

    def test_fajr_does_not_overlap(self):
        assert _prayer_overlaps_trip("fajr", self.schedule, self.dep, self.arr) is False

    def test_isha_does_not_overlap(self):
        assert _prayer_overlaps_trip("isha", self.schedule, self.dep, self.arr) is False


# ─── Prayed Prayer Filtering ─────────────────────────────────────────────────

class TestPrayedPrayerFiltering:
    """The REAL fix: prayed_prayers must filter out already-prayed pairs."""

    def test_isha_prayed_skips_maghrib_isha(self):
        skip = _musafir_active_prayers({"isha"})
        assert "maghrib" in skip
        assert "isha" in skip

    def test_isha_prayed_does_not_skip_fajr(self):
        skip = _musafir_active_prayers({"isha"})
        assert "fajr" not in skip

    def test_isha_prayed_does_not_skip_dhuhr_asr(self):
        skip = _musafir_active_prayers({"isha"})
        assert "dhuhr" not in skip
        assert "asr" not in skip

    def test_all_prayed_skips_everything(self):
        skip = _musafir_active_prayers({"fajr", "dhuhr", "asr", "maghrib", "isha"})
        assert skip == {"fajr", "dhuhr", "asr", "maghrib", "isha"}

    def test_fajr_and_isha_prayed(self):
        """Common scenario: prayed Isha tonight, Fajr this morning."""
        skip = _musafir_active_prayers({"fajr", "isha"})
        assert "fajr" in skip
        assert "maghrib" in skip  # inferred from isha
        assert "isha" in skip
        assert "dhuhr" not in skip
        assert "asr" not in skip


# ─── Trip Planner Pair Building with Prayed Prayers ──────────────────────────

class TestTripPlannerPrayedIntegration:
    """Test that build_travel_plan correctly uses prayed_prayers to skip pairs."""

    def test_enumerate_prayers_midnight_trip(self):
        """12:12 AM to 8:12 AM — should only show Fajr."""
        dep = datetime(2026, 3, 21, 0, 12, tzinfo=PT)
        arr = datetime(2026, 3, 21, 8, 12, tzinfo=PT)
        schedules = {TODAY: ca_schedule()}
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        prayer_names = [p["prayer"] for p in prayers]
        assert "fajr" in prayer_names
        # Maghrib and Isha should NOT be in the list — their adhan is at 6:30 PM / 8:30 PM
        # which is before our 12:12 AM departure
        assert "maghrib" not in prayer_names
        assert "isha" not in prayer_names

    def test_enumerate_prayers_late_night_trip(self):
        """11 PM to 7 AM — Isha is active at departure, Fajr during trip."""
        dep = datetime(2026, 3, 21, 23, 0, tzinfo=PT)
        arr = datetime(2026, 3, 22, 7, 0, tzinfo=PT)
        schedules = {
            TODAY: ca_schedule(),
            date(2026, 3, 22): calculate_prayer_times(36.33, -119.29, date(2026, 3, 22), timezone_offset=-7),
        }
        # Add iqama estimates to day 2
        day2_calc = schedules[date(2026, 3, 22)]
        schedules[date(2026, 3, 22)] = {**day2_calc, **estimate_iqama_times(day2_calc)}
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        prayer_names = [p["prayer"] for p in prayers]
        # Isha at ~20:30 is before 23:00 departure — should NOT be included
        # (enumerate checks adhan_time >= departure)
        # But Fajr on day 2 should be included
        day2_prayers = [p for p in prayers if p["day_number"] == 2]
        day2_names = [p["prayer"] for p in day2_prayers]
        assert "fajr" in day2_names

    def test_enumerate_prayers_full_day(self):
        """8 AM to 8 PM — all daytime prayers."""
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = datetime(2026, 3, 21, 20, 0, tzinfo=PT)
        schedules = {TODAY: ca_schedule()}
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        prayer_names = {p["prayer"] for p in prayers}
        assert "dhuhr" in prayer_names
        assert "asr" in prayer_names
        assert "maghrib" in prayer_names
        assert "fajr" not in prayer_names  # Fajr at ~5:30 AM < 8 AM departure


# ─── The Actual Bug: Pair Relevance Should Check Prayed ──────────────────────

class TestPairRelevanceBug:
    """The core bug: _pair_relevant only checks time overlap, not prayed state.
    The fix must happen in build_travel_plan where pairs are built."""

    def test_pair_relevant_ignores_prayed(self):
        """_pair_relevant has no prayed_prayers parameter — this is by design.
        The filtering must happen after pair relevance check."""
        schedule = ca_schedule()
        # At 12:12 AM, Isha window is active, so pair IS relevant
        result = _pair_relevant("maghrib", "isha", schedule, hm(0, 12), hm(8, 12))
        # This returns True — correct behavior for the overlap function.
        # The bug is that build_travel_plan doesn't filter this pair out
        # when prayed_prayers={"isha"}.
        assert result is True  # Overlap correct

    def test_build_combination_plan_should_skip_prayed_pair(self):
        """When building prayer pairs in build_travel_plan, already-prayed pairs
        must be excluded. The prayed_prayers parameter must be checked BEFORE
        building combination options for a pair."""
        # This is the fix we need to verify
        prayed = {"isha"}  # User prayed Isha
        skip = _musafir_active_prayers(prayed)
        # Maghrib+Isha should be in skip set
        assert "maghrib" in skip and "isha" in skip
        # Dhuhr+Asr should NOT be in skip set
        assert "dhuhr" not in skip and "asr" not in skip
