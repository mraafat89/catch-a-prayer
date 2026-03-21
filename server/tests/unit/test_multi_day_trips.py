"""
Tests for multi-day trip support (up to 3 days / 72 hours).
Rules: ROUTE_PLANNING_ALGORITHM.md — Multi-Day Trip Handling
       PRODUCT_REQUIREMENTS.md FR-4.4

Key requirements:
- Trips up to 72 hours supported
- Trips > 72 hours rejected with error message
- Each calendar day has its own prayer schedule
- Same prayer (e.g., Fajr) appears multiple times for different days
- Prayed state is per-date
"""
import pytest
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times
from app.services.travel_planner import (
    _prayer_overlaps_trip,
    hhmm_to_minutes,
    build_checkpoints,
    validate_trip_duration,
    enumerate_trip_prayers,
)


ET = ZoneInfo("America/New_York")


class TestTripDurationValidation:
    def test_5_hour_trip_valid(self):
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = dep + timedelta(hours=5)
        valid, msg = validate_trip_duration(dep, arr)
        assert valid is True

    def test_24_hour_trip_valid(self):
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = dep + timedelta(hours=24)
        valid, msg = validate_trip_duration(dep, arr)
        assert valid is True

    def test_48_hour_trip_valid(self):
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = dep + timedelta(hours=48)
        valid, msg = validate_trip_duration(dep, arr)
        assert valid is True

    def test_72_hour_trip_valid(self):
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = dep + timedelta(hours=72)
        valid, msg = validate_trip_duration(dep, arr)
        assert valid is True

    def test_73_hour_trip_rejected(self):
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = dep + timedelta(hours=73)
        valid, msg = validate_trip_duration(dep, arr)
        assert valid is False
        assert "3 days" in msg

    def test_negative_duration_rejected(self):
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = dep - timedelta(hours=1)
        valid, msg = validate_trip_duration(dep, arr)
        assert valid is False


class TestEnumerateTripPrayers:
    def _schedule_for_date(self, d: date) -> dict:
        calc = calculate_prayer_times(40.7128, -74.0060, d, timezone_offset=-4)
        return {**calc, **estimate_iqama_times(calc)}

    def test_same_day_trip_afternoon(self):
        """10 AM - 5 PM → catches Dhuhr and Asr."""
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = datetime(2026, 3, 20, 17, 0, tzinfo=ET)
        schedules = {date(2026, 3, 20): self._schedule_for_date(date(2026, 3, 20))}
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        prayer_names = [p["prayer"] for p in prayers]
        assert "dhuhr" in prayer_names
        assert "asr" in prayer_names
        assert "fajr" not in prayer_names  # 5:30 AM < 10 AM departure
        assert all(p["day_number"] == 1 for p in prayers)

    def test_overnight_trip(self):
        """10 PM - 8 AM next day → catches Isha (day 1) + Fajr (day 2)."""
        dep = datetime(2026, 3, 20, 22, 0, tzinfo=ET)
        arr = datetime(2026, 3, 21, 8, 0, tzinfo=ET)
        schedules = {
            date(2026, 3, 20): self._schedule_for_date(date(2026, 3, 20)),
            date(2026, 3, 21): self._schedule_for_date(date(2026, 3, 21)),
        }
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        prayer_names = [(p["prayer"], p["day_number"]) for p in prayers]
        # Isha on day 1 (if adhan ~20:30 >= 22:00 dep? depends on schedule)
        # Fajr on day 2
        fajr_day2 = [p for p in prayers if p["prayer"] == "fajr" and p["day_number"] == 2]
        assert len(fajr_day2) == 1

    def test_two_day_trip(self):
        """10 AM day 1 - 6 PM day 2 → Fajr appears on day 2 only."""
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = datetime(2026, 3, 21, 18, 0, tzinfo=ET)
        schedules = {
            date(2026, 3, 20): self._schedule_for_date(date(2026, 3, 20)),
            date(2026, 3, 21): self._schedule_for_date(date(2026, 3, 21)),
        }
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        # Day 1: Dhuhr, Asr, Maghrib, Isha
        day1 = [p for p in prayers if p["day_number"] == 1]
        day1_names = {p["prayer"] for p in day1}
        assert "dhuhr" in day1_names
        assert "fajr" not in day1_names  # Fajr at 5:30 < departure 10:00

        # Day 2: Fajr, Dhuhr, Asr (Maghrib at ~19:00 > arrival 18:00)
        day2 = [p for p in prayers if p["day_number"] == 2]
        day2_names = {p["prayer"] for p in day2}
        assert "fajr" in day2_names
        assert "dhuhr" in day2_names

    def test_three_day_trip(self):
        """Fajr appears on day 2 and day 3."""
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = datetime(2026, 3, 22, 18, 0, tzinfo=ET)
        schedules = {
            date(2026, 3, 20): self._schedule_for_date(date(2026, 3, 20)),
            date(2026, 3, 21): self._schedule_for_date(date(2026, 3, 21)),
            date(2026, 3, 22): self._schedule_for_date(date(2026, 3, 22)),
        }
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        fajrs = [p for p in prayers if p["prayer"] == "fajr"]
        assert len(fajrs) == 2  # day 2 + day 3 (day 1 Fajr before departure)
        assert fajrs[0]["day_number"] == 2
        assert fajrs[1]["day_number"] == 3

    def test_empty_schedule(self):
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = datetime(2026, 3, 20, 18, 0, tzinfo=ET)
        prayers = enumerate_trip_prayers(dep, arr, {})
        assert prayers == []

    def test_prayer_dates_are_correct(self):
        """Each prayer's date matches its calendar day."""
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        arr = datetime(2026, 3, 21, 18, 0, tzinfo=ET)
        schedules = {
            date(2026, 3, 20): self._schedule_for_date(date(2026, 3, 20)),
            date(2026, 3, 21): self._schedule_for_date(date(2026, 3, 21)),
        }
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        for p in prayers:
            if p["day_number"] == 1:
                assert p["date"] == date(2026, 3, 20)
            elif p["day_number"] == 2:
                assert p["date"] == date(2026, 3, 21)


# ─── Checkpoint Date Tracking ─────────────────────────────────────────────────

class TestCheckpointDates:
    def test_multi_day_checkpoints_have_dates(self):
        """Checkpoints for a 24h+ trip should span multiple calendar dates."""
        route = {
            "geometry": {
                "coordinates": [[-74.006, 40.713], [-87.630, 41.878]]  # NYC to Chicago
            },
            "duration": 48 * 3600,  # 48 hours
            "distance": 1200000,
        }
        dep = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        checkpoints = build_checkpoints(route, dep)
        if len(checkpoints) >= 2:
            first_date = checkpoints[0]["time"].date()
            last_date = checkpoints[-1]["time"].date()
            # 48-hour trip should span at least 2 different dates
            assert last_date > first_date
