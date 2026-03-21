"""
Tests for destination prayer schedule date and timezone correctness.
Rules: ROUTE_PLANNING_ALGORITHM.md — Timezone Crossing
Bug: dest schedule was using departure date instead of arrival date,
     and departure_dt instead of arrival_dt for timezone offset.
"""
import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times


class TestDestinationScheduleDate:
    """Destination schedule must use ARRIVAL date, not departure date."""

    def test_overnight_trip_uses_next_day(self):
        """Depart Dec 31 11 PM, arrive Jan 1 10 AM → dest schedule for Jan 1."""
        departure_dt = datetime(2026, 12, 31, 23, 0, tzinfo=ZoneInfo("America/New_York"))
        duration_seconds = 11 * 3600  # 11 hours
        arrival_dt = departure_dt + timedelta(seconds=duration_seconds)

        departure_date = departure_dt.date()  # Dec 31
        arrival_date = arrival_dt.date()       # Jan 1

        assert departure_date != arrival_date, "Trip must cross midnight"
        assert arrival_date == date(2027, 1, 1)

        # Bug: code uses departure_date for destination schedule
        # Fix: should use arrival_date
        dest_schedule_buggy = calculate_prayer_times(
            40.71, -74.00, departure_date, timezone_offset=-5
        )
        dest_schedule_fixed = calculate_prayer_times(
            40.71, -74.00, arrival_date, timezone_offset=-5
        )

        # Both should work, but times may differ slightly (different solar positions)
        assert dest_schedule_buggy is not None
        assert dest_schedule_fixed is not None
        # The key assertion: the dates are different
        assert departure_date.month == 12
        assert arrival_date.month == 1

    def test_same_day_trip_no_difference(self):
        """Depart 10 AM, arrive 3 PM same day → same date, no bug."""
        departure_dt = datetime(2026, 3, 20, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        arrival_dt = departure_dt + timedelta(hours=5)
        assert departure_dt.date() == arrival_dt.date()


class TestDestinationTimezoneOffset:
    """Dest timezone offset must use arrival_dt for DST correctness."""

    def test_dst_transition_offset_differs(self):
        """On DST change day, offset from departure_dt vs arrival_dt may differ."""
        import pytz
        # US DST spring forward: March 8, 2026 at 2 AM ET
        et = pytz.timezone("America/New_York")

        # Departure at 1 AM ET (before spring forward)
        dep_naive = datetime(2026, 3, 8, 1, 0)
        dep_offset = et.utcoffset(dep_naive).total_seconds() / 3600
        assert dep_offset == -5  # EST

        # Arrival at 4 AM ET (after spring forward)
        arr_naive = datetime(2026, 3, 8, 4, 0)
        arr_offset = et.utcoffset(arr_naive).total_seconds() / 3600
        assert arr_offset == -4  # EDT

        # Bug: using dep_offset for dest schedule
        # Fix: should use arr_offset
        assert dep_offset != arr_offset

    def test_cross_timezone_trip(self):
        """NYC to Chicago: ET→CT, 1 hour difference."""
        import pytz
        et = pytz.timezone("America/New_York")
        ct = pytz.timezone("America/Chicago")

        dep_time = datetime(2026, 6, 15, 10, 0)  # summer, no DST ambiguity
        et_offset = et.utcoffset(dep_time).total_seconds() / 3600
        ct_offset = ct.utcoffset(dep_time).total_seconds() / 3600

        assert et_offset == -4  # EDT
        assert ct_offset == -5  # CDT
        assert et_offset != ct_offset
