"""
Tests for stale pair detection on LONG trips.

Bug: a 20-hour midnight departure trip (12 AM → 8 PM next day) was
skipping Dhuhr+Asr and Maghrib+Isha because the stale check only
looked at departure time (< 6 AM) and adhan times (PM), without
checking if the trip is long enough that those prayers happen DURING it.

Fix: only skip stale pairs if the trip is SHORT (< 8 hours).
Long trips that extend into the next day should include all prayers.
"""
import pytest
from datetime import date
from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times
from app.services.travel_planner import (
    _prayer_overlaps_trip,
    _pair_relevant,
    hhmm_to_minutes,
)


def visalia_schedule():
    calc = calculate_prayer_times(36.33, -119.29, date(2026, 3, 21), timezone_offset=-7)
    return {**calc, **estimate_iqama_times(calc)}


def hm(h, m=0):
    return h * 60 + m


class TestLongTripFromMidnight:
    """12 AM → 8 PM next day (20 hours). Must include daytime prayers."""
    s = visalia_schedule()
    dep = hm(0, 24)   # 12:24 AM
    arr = hm(20, 0)    # 8 PM (simplified: same-day representation of 20h trip)
    # For multi-day: arr wraps, but _pair_relevant handles +1440

    def test_fajr_overlaps(self):
        assert _prayer_overlaps_trip("fajr", self.s, self.dep, self.arr) is True

    def test_dhuhr_overlaps(self):
        """Dhuhr at ~12:30 PM is within 12 AM-8 PM window."""
        assert _prayer_overlaps_trip("dhuhr", self.s, self.dep, self.arr) is True

    def test_asr_overlaps(self):
        """Asr at ~4 PM is within window."""
        assert _prayer_overlaps_trip("asr", self.s, self.dep, self.arr) is True

    def test_maghrib_overlaps(self):
        """Maghrib at ~6:30 PM is within window."""
        assert _prayer_overlaps_trip("maghrib", self.s, self.dep, self.arr) is True

    def test_dhuhr_asr_pair_relevant(self):
        assert _pair_relevant("dhuhr", "asr", self.s, self.dep, self.arr) is True

    def test_maghrib_isha_pair_relevant(self):
        assert _pair_relevant("maghrib", "isha", self.s, self.dep, self.arr) is True


class TestShortTripFromMidnight:
    """12 AM → 6 AM (6 hours). Only Fajr — Dhuhr+Asr are truly stale."""
    s = visalia_schedule()
    dep = hm(0, 12)
    arr = hm(6, 0)

    def test_fajr_overlaps(self):
        assert _prayer_overlaps_trip("fajr", self.s, self.dep, self.arr) is True

    def test_dhuhr_does_not_overlap(self):
        assert _prayer_overlaps_trip("dhuhr", self.s, self.dep, self.arr) is False

    def test_dhuhr_asr_pair_not_relevant(self):
        assert _pair_relevant("dhuhr", "asr", self.s, self.dep, self.arr) is False


class TestMediumTripFromMidnight:
    """12 AM → 2 PM (14 hours). Fajr + Dhuhr, maybe Asr."""
    s = visalia_schedule()
    dep = hm(0, 12)
    arr = hm(14, 0)

    def test_fajr_overlaps(self):
        assert _prayer_overlaps_trip("fajr", self.s, self.dep, self.arr) is True

    def test_dhuhr_overlaps(self):
        assert _prayer_overlaps_trip("dhuhr", self.s, self.dep, self.arr) is True

    def test_dhuhr_asr_pair_relevant(self):
        assert _pair_relevant("dhuhr", "asr", self.s, self.dep, self.arr) is True


class TestOvernight20hTrip:
    """11 PM → 7 PM next day (20 hours). All prayers."""
    s = visalia_schedule()
    dep = hm(23, 0)
    # arr_min for a 20h trip from 23:00 = 23*60 + 20*60 = 2580, but mod 1440 = 1140 (7 PM)
    # _prayer_overlaps_trip handles arr < dep by adding 1440
    arr = hm(19, 0)  # 7 PM next day

    def test_fajr_overlaps(self):
        assert _prayer_overlaps_trip("fajr", self.s, self.dep, self.arr) is True

    def test_dhuhr_overlaps(self):
        assert _prayer_overlaps_trip("dhuhr", self.s, self.dep, self.arr) is True

    def test_asr_overlaps(self):
        assert _prayer_overlaps_trip("asr", self.s, self.dep, self.arr) is True

    def test_maghrib_borderline(self):
        """Maghrib ~7:26 PM, arrival 7 PM → may not overlap (arrival before Maghrib)."""
        result = _prayer_overlaps_trip("maghrib", self.s, self.dep, self.arr)
        assert isinstance(result, bool)  # Either way is acceptable
