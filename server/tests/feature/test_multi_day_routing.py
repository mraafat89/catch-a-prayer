"""
Tests for multi-day trip routing — the build_travel_plan must handle
trips spanning 2-3 calendar days, fetching per-day prayer schedules
and generating prayer pairs for each day.

TDD: these tests define the expected behavior BEFORE implementation.
"""
import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times
from app.services.travel_planner import (
    enumerate_trip_prayers,
    validate_trip_duration,
    build_pairs_from_prayers,
    hhmm_to_minutes,
)

PT = ZoneInfo("America/Los_Angeles")


def schedule_for_date(d: date) -> dict:
    calc = calculate_prayer_times(36.33, -119.29, d, timezone_offset=-7)
    return {**calc, **estimate_iqama_times(calc)}


def schedules_for_range(start: date, end: date) -> dict:
    """Build schedules dict for a date range."""
    result = {}
    current = start
    while current <= end:
        result[current] = schedule_for_date(current)
        current += timedelta(days=1)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-DAY PRAYER ENUMERATION — prayers per day
# ═══════════════════════════════════════════════════════════════════════════════

class TestTwoDayPrayerList:
    """8 AM day 1 → 6 PM day 2: full set of prayers across both days."""

    dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
    arr = datetime(2026, 3, 22, 18, 0, tzinfo=PT)
    scheds = schedules_for_range(date(2026, 3, 21), date(2026, 3, 22))

    def test_day0_has_dhuhr_asr_maghrib_isha(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        day0 = {p["prayer"] for p in prayers if p["day_number"] == 0}
        assert "dhuhr" in day0
        assert "asr" in day0
        assert "maghrib" in day0
        assert "isha" in day0

    def test_day0_no_fajr(self):
        """Fajr at ~5:30 AM is before 8 AM departure."""
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        day0 = {p["prayer"] for p in prayers if p["day_number"] == 0}
        assert "fajr" not in day0

    def test_day1_has_fajr_dhuhr_asr(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        day1 = {p["prayer"] for p in prayers if p["day_number"] == 1}
        assert "fajr" in day1
        assert "dhuhr" in day1
        assert "asr" in day1

    def test_day1_no_isha(self):
        """Isha at ~8:30 PM is after 6 PM arrival."""
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        day1 = {p["prayer"] for p in prayers if p["day_number"] == 1}
        assert "isha" not in day1

    def test_total_prayer_count(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        # Day 0: Dhuhr, Asr, Maghrib, Isha (4)
        # Day 1: Fajr, Dhuhr, Asr (3), maybe Maghrib
        assert len(prayers) >= 7

    def test_each_prayer_has_date(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        for p in prayers:
            assert "date" in p
            assert isinstance(p["date"], date)

    def test_each_prayer_has_day_number(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        for p in prayers:
            assert p["day_number"] in (0, 1)


class TestThreeDayPrayerList:
    """8 AM day 1 → 6 PM day 3."""

    dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
    arr = datetime(2026, 3, 23, 18, 0, tzinfo=PT)
    scheds = schedules_for_range(date(2026, 3, 21), date(2026, 3, 23))

    def test_fajr_on_day1_and_day2(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        fajrs = [p for p in prayers if p["prayer"] == "fajr"]
        assert len(fajrs) == 2
        days = {f["day_number"] for f in fajrs}
        assert days == {1, 2}

    def test_dhuhr_on_all_three_days(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        dhuhrs = [p for p in prayers if p["prayer"] == "dhuhr"]
        # Day 0: yes (after 8 AM). Day 1: yes. Day 2: yes (before 6 PM)
        assert len(dhuhrs) == 3

    def test_isha_on_day0_and_day1_not_day2(self):
        """Isha at ~8:30 PM, arrival day 2 at 6 PM → no Isha on day 2."""
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        ishas = [p for p in prayers if p["prayer"] == "isha"]
        # Day 0: yes, Day 1: yes, Day 2: no (arrival 6 PM < Isha 8:30 PM)
        assert len(ishas) == 2
        days = {i["day_number"] for i in ishas}
        assert 2 not in days

    def test_total_prayers(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        # Day 1: 4 (Dhuhr, Asr, Maghrib, Isha)
        # Day 2: 5 (Fajr, Dhuhr, Asr, Maghrib, Isha)
        # Day 3: 3-4 (Fajr, Dhuhr, Asr, maybe Maghrib)
        assert len(prayers) >= 12


class TestOvernightPrayerList:
    """10 PM → 8 AM next day."""

    dep = datetime(2026, 3, 21, 22, 0, tzinfo=PT)
    arr = datetime(2026, 3, 22, 8, 0, tzinfo=PT)
    scheds = schedules_for_range(date(2026, 3, 21), date(2026, 3, 22))

    def test_only_fajr_on_day1(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        # Day 0: Isha might still be valid (period extends to Fajr)
        # Day 1: Fajr only (before 8 AM arrival)
        day1_names = {p["prayer"] for p in prayers if p["day_number"] == 1}
        assert "fajr" in day1_names
        assert "dhuhr" not in day1_names  # Dhuhr ~12:30 > 8 AM arrival


class TestMidnightStartPrayerList:
    """12:15 AM → 10 AM same day."""

    dep = datetime(2026, 3, 21, 0, 15, tzinfo=PT)
    arr = datetime(2026, 3, 21, 10, 0, tzinfo=PT)
    scheds = schedules_for_range(date(2026, 3, 21), date(2026, 3, 21))

    def test_only_fajr(self):
        prayers = enumerate_trip_prayers(self.dep, self.arr, self.scheds)
        names = {p["prayer"] for p in prayers}
        assert "fajr" in names
        assert "dhuhr" not in names  # Dhuhr ~12:30 > 10 AM
        assert "isha" not in names   # Isha adhan ~20:30 way before 12:15 AM


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-DAY PAIR BUILDING — which Musafir pairs per day
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiDayPairBuilding:

    def test_two_day_musafir(self):
        """2-day trip: Day 0 has Dhuhr+Asr + Maghrib+Isha, Day 1 has Fajr + Dhuhr+Asr."""
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = datetime(2026, 3, 22, 18, 0, tzinfo=PT)
        scheds = schedules_for_range(date(2026, 3, 21), date(2026, 3, 22))
        prayers = enumerate_trip_prayers(dep, arr, scheds)
        pairs = build_pairs_from_prayers(prayers, travel_mode=True)

        # pairs is list of (pair_key, prayer_list) tuples
        # Extract pair types per day from pair_key (e.g. "dhuhr_asr_day0")
        day0_types = set()
        day1_types = set()
        for pair_key, group in pairs:
            # pair_key format: "dhuhr_asr_day0", "fajr_day1", etc.
            if "_day0" in pair_key:
                day0_types.add(pair_key.replace("_day0", ""))
            elif "_day1" in pair_key:
                day1_types.add(pair_key.replace("_day1", ""))

        assert "dhuhr_asr" in day0_types
        assert "maghrib_isha" in day0_types
        assert "fajr" in day1_types
        assert "dhuhr_asr" in day1_types

    def test_two_day_muqeem(self):
        """Muqeem: each prayer is standalone, no pairs."""
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = datetime(2026, 3, 22, 18, 0, tzinfo=PT)
        scheds = schedules_for_range(date(2026, 3, 21), date(2026, 3, 22))
        prayers = enumerate_trip_prayers(dep, arr, scheds)
        pairs = build_pairs_from_prayers(prayers, travel_mode=False)

        # Each prayer is its own entry — no combined pair keys
        pair_keys = [k for k, _ in pairs]
        has_dhuhr_solo = any("dhuhr_day" in k and "asr" not in k for k in pair_keys)
        has_asr_solo = any("asr_day" in k for k in pair_keys)
        has_dhuhr_asr = any("dhuhr_asr" in k for k in pair_keys)
        assert has_dhuhr_solo, f"Muqeem should have standalone dhuhr, got keys: {pair_keys}"
        assert has_asr_solo, f"Muqeem should have standalone asr, got keys: {pair_keys}"
        assert not has_dhuhr_asr, f"Muqeem should NOT have dhuhr_asr pair, got keys: {pair_keys}"

    def test_overnight_musafir(self):
        """10 PM - 8 AM: Isha (still active) + Fajr."""
        dep = datetime(2026, 3, 21, 22, 0, tzinfo=PT)
        arr = datetime(2026, 3, 22, 8, 0, tzinfo=PT)
        scheds = schedules_for_range(date(2026, 3, 21), date(2026, 3, 22))
        prayers = enumerate_trip_prayers(dep, arr, scheds)
        pairs = build_pairs_from_prayers(prayers, travel_mode=True)

        pair_keys = {k for k, _ in pairs}
        has_fajr = any("fajr" in k for k in pair_keys)
        assert has_fajr, f"Overnight trip should include Fajr, got: {pair_keys}"

    def test_three_day_has_fajr_each_morning(self):
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = datetime(2026, 3, 23, 18, 0, tzinfo=PT)
        scheds = schedules_for_range(date(2026, 3, 21), date(2026, 3, 23))
        prayers = enumerate_trip_prayers(dep, arr, scheds)
        pairs = build_pairs_from_prayers(prayers, travel_mode=True)

        fajr_day_nums = []
        for pair_key, group in pairs:
            if "fajr" in pair_key:
                fajr_day_nums.append(group[0]["day_number"])
        assert 1 in fajr_day_nums, f"Day 1 Fajr missing, got day_nums: {fajr_day_nums}"
        assert 2 in fajr_day_nums, f"Day 2 Fajr missing, got day_nums: {fajr_day_nums}"

    def test_pair_keys_include_day_number(self):
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = datetime(2026, 3, 22, 18, 0, tzinfo=PT)
        scheds = schedules_for_range(date(2026, 3, 21), date(2026, 3, 22))
        prayers = enumerate_trip_prayers(dep, arr, scheds)
        pairs = build_pairs_from_prayers(prayers, travel_mode=True)

        for pair_key, group in pairs:
            assert "day" in pair_key, f"Pair key {pair_key} should include day number"
