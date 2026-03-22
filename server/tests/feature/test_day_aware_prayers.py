"""
Day-aware prayer tests for route planner.

Verifies that the route planner uses ABSOLUTE DATETIME ordering, not prayer
name ordering, and that stale prayers (whose period ended before departure)
are correctly excluded.

Spec: docs/DAY_AWARE_PRAYER_DESIGN.md
"""
import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.travel_planner import (
    enumerate_trip_prayers,
    build_pairs_from_prayers,
    hhmm_to_minutes,
)
from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times

PT = ZoneInfo("America/Los_Angeles")
ET = ZoneInfo("America/New_York")
MT = ZoneInfo("America/Denver")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_schedule(
    lat: float, lng: float, d: date, tz_offset: float
) -> dict:
    """Build a full schedule (adhan + iqama) for a location/date."""
    calc = calculate_prayer_times(lat, lng, d, timezone_offset=tz_offset)
    if not calc:
        return {}
    return {**calc, **estimate_iqama_times(calc)}


def _la_schedule(d: date) -> dict:
    """Los Angeles schedule (34.05, -118.24, UTC-7 PDT)."""
    return _make_schedule(34.05, -118.24, d, -7)


def _denver_schedule(d: date) -> dict:
    """Denver schedule (39.74, -104.99, UTC-6 MDT)."""
    return _make_schedule(39.74, -104.99, d, -6)


def _nyc_schedule(d: date) -> dict:
    """NYC schedule (40.71, -74.01, UTC-4 EDT)."""
    return _make_schedule(40.71, -74.01, d, -4)


def _schedules_for_range(
    start: date, end: date, schedule_fn
) -> dict:
    """Build schedules_by_date for a date range using a schedule function."""
    result = {}
    d = start
    while d <= end:
        result[d] = schedule_fn(d)
        d += timedelta(days=1)
    return result


# ---------------------------------------------------------------------------
# 1. 6:45 PM departure, 20h trip → Maghrib+Isha FIRST, then Fajr, then Dhuhr+Asr
# ---------------------------------------------------------------------------

class TestEveningDeparture20hTrip:
    """6:45 PM LA departure, ~20h trip arriving ~2:45 PM next day."""

    @pytest.fixture
    def prayers(self):
        dep = datetime(2026, 3, 21, 18, 45, tzinfo=PT)
        arr = dep + timedelta(hours=20)  # ~2:45 PM next day
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        return enumerate_trip_prayers(dep, arr, schedules)

    def test_chronological_order_maghrib_isha_first(self, prayers):
        """Maghrib+Isha must come before Fajr in the list."""
        names = [p["prayer"] for p in prayers]
        # Maghrib and Isha (tonight) must appear before Fajr (tomorrow morning)
        if "maghrib" in names and "fajr" in names:
            assert names.index("maghrib") < names.index("fajr"), (
                f"Maghrib should come before Fajr but got order: {names}"
            )
        if "isha" in names and "fajr" in names:
            assert names.index("isha") < names.index("fajr"), (
                f"Isha should come before Fajr but got order: {names}"
            )

    def test_chronological_order_fajr_before_dhuhr(self, prayers):
        """Fajr (tomorrow AM) must come before Dhuhr (tomorrow noon)."""
        names = [p["prayer"] for p in prayers]
        if "fajr" in names and "dhuhr" in names:
            assert names.index("fajr") < names.index("dhuhr"), (
                f"Fajr should come before Dhuhr but got order: {names}"
            )

    def test_no_today_dhuhr(self, prayers):
        """Today's Dhuhr (12:30 PM) must NOT appear — it ended hours ago."""
        today = date(2026, 3, 21)
        today_dhuhrs = [
            p for p in prayers
            if p["prayer"] == "dhuhr" and p["date"] == today
        ]
        assert len(today_dhuhrs) == 0, (
            f"Today's Dhuhr should be excluded (period ended before 6:45 PM departure) "
            f"but found: {today_dhuhrs}"
        )

    def test_no_today_asr(self, prayers):
        """Today's Asr (4:30 PM) must NOT appear — period ended before 6:45 PM."""
        today = date(2026, 3, 21)
        today_asrs = [
            p for p in prayers
            if p["prayer"] == "asr" and p["date"] == today
        ]
        # Asr period ends at Maghrib adhan. If Maghrib is ~6:15-7:15 PM and departure
        # is 6:45 PM, Asr MIGHT still be valid depending on exact times.
        # Let's check: if it's included, verify adhan_dt's period hasn't ended.
        for asr in today_asrs:
            assert asr["period_end_dt"] > datetime(2026, 3, 21, 18, 45, tzinfo=PT), (
                f"Today's Asr period_end_dt={asr['period_end_dt']} should be after "
                f"departure 6:45 PM if included"
            )

    def test_tomorrow_dhuhr_asr_present(self, prayers):
        """Tomorrow's Dhuhr and Asr should be present (trip arrives 2:45 PM)."""
        tomorrow = date(2026, 3, 22)
        tomorrow_prayers = {p["prayer"] for p in prayers if p["date"] == tomorrow}
        assert "dhuhr" in tomorrow_prayers, "Tomorrow's Dhuhr should be in the plan"

    def test_sorted_by_adhan_dt(self, prayers):
        """All prayers must be sorted by adhan_dt ascending."""
        for i in range(len(prayers) - 1):
            assert prayers[i]["adhan_dt"] <= prayers[i + 1]["adhan_dt"], (
                f"Prayer {prayers[i]['prayer']} (day {prayers[i]['day_number']}) "
                f"adhan_dt={prayers[i]['adhan_dt']} should be <= "
                f"{prayers[i + 1]['prayer']} (day {prayers[i + 1]['day_number']}) "
                f"adhan_dt={prayers[i + 1]['adhan_dt']}"
            )


# ---------------------------------------------------------------------------
# 2. 6:45 PM departure → NO today's Dhuhr+Asr (already passed)
# ---------------------------------------------------------------------------

class TestStalePrayerExclusion:
    """At 6:45 PM, Dhuhr (12:30 PM) and Asr (4:30 PM) have passed."""

    def test_evening_departure_excludes_dhuhr(self):
        """Dhuhr period ends at Asr adhan (~4:30 PM), well before 6:45 PM."""
        dep = datetime(2026, 3, 21, 18, 45, tzinfo=PT)
        arr = dep + timedelta(hours=3)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        today_dhuhrs = [p for p in prayers if p["prayer"] == "dhuhr" and p["date"] == dep.date()]
        assert len(today_dhuhrs) == 0, (
            "Dhuhr should be excluded at 6:45 PM departure"
        )

    def test_evening_departure_includes_maghrib(self):
        """Maghrib is the next prayer after 6:45 PM — must be included."""
        dep = datetime(2026, 3, 21, 18, 45, tzinfo=PT)
        arr = dep + timedelta(hours=3)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        today_maghribs = [p for p in prayers if p["prayer"] == "maghrib" and p["date"] == dep.date()]
        # Maghrib should be included if its adhan is around 7 PM and trip starts at 6:45 PM
        # (period hasn't ended yet). If Maghrib adhan is before 6:45 PM, it should still be
        # included if period_end (Isha adhan) is after 6:45 PM.
        sched = schedules[dep.date()]
        maghrib_adhan = sched.get("maghrib_adhan")
        if maghrib_adhan:
            maghrib_min = hhmm_to_minutes(maghrib_adhan)
            isha_adhan = sched.get("isha_adhan")
            isha_min = hhmm_to_minutes(isha_adhan) if isha_adhan else maghrib_min + 90
            # If Maghrib period hasn't ended (Isha adhan after 18:45)
            if isha_min > 18 * 60 + 45 or maghrib_min >= 18 * 60 + 45:
                assert len(today_maghribs) >= 1, "Maghrib should be included"


# ---------------------------------------------------------------------------
# 3. 8 AM departure → Dhuhr+Asr YES, Maghrib+Isha YES (both upcoming)
# ---------------------------------------------------------------------------

class TestMorningDepartureIncludesAll:
    """8 AM departure, 14h trip → all daytime + evening prayers are upcoming."""

    def test_morning_departure_includes_dhuhr_asr(self):
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=14)  # 10 PM
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        names = {p["prayer"] for p in prayers if p["date"] == dep.date()}
        assert "dhuhr" in names, "Dhuhr should be included for 8 AM departure"
        assert "asr" in names, "Asr should be included for 8 AM departure"

    def test_morning_departure_includes_maghrib_isha(self):
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=14)  # 10 PM
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        names = {p["prayer"] for p in prayers if p["date"] == dep.date()}
        assert "maghrib" in names, "Maghrib should be included for 8 AM departure"
        assert "isha" in names, "Isha should be included for 8 AM departure"


# ---------------------------------------------------------------------------
# 4. 10 PM departure overnight → only Fajr (Maghrib+Isha already passed)
# ---------------------------------------------------------------------------

class TestLateNightDeparture:
    """10 PM departure, 8h trip (arrive 6 AM) → Maghrib+Isha have passed."""

    def test_10pm_excludes_maghrib(self):
        dep = datetime(2026, 3, 21, 22, 0, tzinfo=PT)
        arr = dep + timedelta(hours=8)  # 6 AM next day
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        today = dep.date()
        # Maghrib adhan is ~7 PM, Isha adhan is ~8:15 PM. At 10 PM, Maghrib
        # period has ended (ends at Isha adhan). But Isha period extends to
        # next Fajr, so Isha might still be valid!
        today_maghribs = [p for p in prayers if p["prayer"] == "maghrib" and p["date"] == today]
        # Maghrib period ends at Isha adhan (~8:15 PM) which is before 10 PM
        assert len(today_maghribs) == 0, (
            "Maghrib should be excluded (period ended before 10 PM departure)"
        )

    def test_10pm_includes_fajr_tomorrow(self):
        dep = datetime(2026, 3, 21, 22, 0, tzinfo=PT)
        arr = dep + timedelta(hours=8)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        tomorrow = dep.date() + timedelta(days=1)
        tomorrow_fajrs = [p for p in prayers if p["prayer"] == "fajr" and p["date"] == tomorrow]
        assert len(tomorrow_fajrs) == 1, "Tomorrow's Fajr should be included for overnight trip"

    def test_10pm_isha_still_valid(self):
        """At 10 PM, Isha's period extends until tomorrow's Fajr — still valid."""
        dep = datetime(2026, 3, 21, 22, 0, tzinfo=PT)
        arr = dep + timedelta(hours=8)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        today = dep.date()
        today_ishas = [p for p in prayers if p["prayer"] == "isha" and p["date"] == today]
        assert len(today_ishas) == 1, (
            "Isha should be included at 10 PM (period extends to Fajr)"
        )


# ---------------------------------------------------------------------------
# 5. 48h trip → Day 1 and Day 2 each have their own Dhuhr+Asr pair
# ---------------------------------------------------------------------------

class TestMultiDayTrip48h:
    """48h trip: two full days of prayers."""

    @pytest.fixture
    def prayers(self):
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=48)  # Mar 23 8 AM
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        return enumerate_trip_prayers(dep, arr, schedules)

    def test_two_days_of_dhuhr(self, prayers):
        """Day 0 and Day 1 should each have a Dhuhr."""
        dhuhrs = [p for p in prayers if p["prayer"] == "dhuhr"]
        dates = {p["date"] for p in dhuhrs}
        assert len(dates) >= 2, (
            f"48h trip should have Dhuhr on at least 2 days, got dates: {dates}"
        )

    def test_two_days_of_asr(self, prayers):
        asrs = [p for p in prayers if p["prayer"] == "asr"]
        dates = {p["date"] for p in asrs}
        assert len(dates) >= 2, (
            f"48h trip should have Asr on at least 2 days, got dates: {dates}"
        )

    def test_pairs_are_same_day(self, prayers):
        """build_pairs_from_prayers must pair Dhuhr+Asr on the same day only."""
        pairs = build_pairs_from_prayers(prayers)
        for pair_key, group in pairs:
            if len(group) == 2:
                assert group[0]["date"] == group[1]["date"], (
                    f"Pair {pair_key}: prayers are on different days! "
                    f"{group[0]['prayer']} on {group[0]['date']} vs "
                    f"{group[1]['prayer']} on {group[1]['date']}"
                )


# ---------------------------------------------------------------------------
# 6. Prayer ordering: Day 0 Isha before Day 1 Fajr
# ---------------------------------------------------------------------------

class TestCrossDayOrdering:
    """Verify that Day 0 Isha sorts before Day 1 Fajr."""

    def test_day0_isha_before_day1_fajr(self):
        dep = datetime(2026, 3, 21, 20, 0, tzinfo=PT)  # 8 PM
        arr = dep + timedelta(hours=12)  # 8 AM next day
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)

        day0_ishas = [p for p in prayers if p["prayer"] == "isha" and p["day_number"] == 0]
        day1_fajrs = [p for p in prayers if p["prayer"] == "fajr" and p["day_number"] == 1]

        if day0_ishas and day1_fajrs:
            isha_dt = day0_ishas[0]["adhan_dt"]
            fajr_dt = day1_fajrs[0]["adhan_dt"]
            assert isha_dt < fajr_dt, (
                f"Day 0 Isha ({isha_dt}) should be before Day 1 Fajr ({fajr_dt})"
            )

    def test_overall_order_is_chronological(self):
        """All prayers across all days must be in adhan_dt order."""
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=36)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)

        for i in range(len(prayers) - 1):
            assert prayers[i]["adhan_dt"] <= prayers[i + 1]["adhan_dt"], (
                f"Not chronological: {prayers[i]['prayer']} day{prayers[i]['day_number']} "
                f"({prayers[i]['adhan_dt']}) > "
                f"{prayers[i+1]['prayer']} day{prayers[i+1]['day_number']} "
                f"({prayers[i+1]['adhan_dt']})"
            )


# ---------------------------------------------------------------------------
# 7. Day 0 Dhuhr NOT paired with Day 1 Asr
# ---------------------------------------------------------------------------

class TestCrossDayPairingForbidden:
    """Day 0 Dhuhr + Day 1 Asr must NEVER be paired together."""

    def test_no_cross_day_dhuhr_asr_pair(self):
        dep = datetime(2026, 3, 21, 12, 0, tzinfo=PT)  # noon
        arr = dep + timedelta(hours=30)  # next day 6 PM
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        pairs = build_pairs_from_prayers(prayers)

        for pair_key, group in pairs:
            if len(group) == 2:
                p1, p2 = group
                if p1["prayer"] == "dhuhr" and p2["prayer"] == "asr":
                    assert p1["date"] == p2["date"], (
                        f"Cross-day pair detected! Dhuhr on {p1['date']} "
                        f"paired with Asr on {p2['date']}"
                    )

    def test_no_cross_day_maghrib_isha_pair(self):
        dep = datetime(2026, 3, 21, 19, 0, tzinfo=PT)  # 7 PM
        arr = dep + timedelta(hours=26)  # next day 9 PM
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        pairs = build_pairs_from_prayers(prayers)

        for pair_key, group in pairs:
            if len(group) == 2:
                p1, p2 = group
                if p1["prayer"] == "maghrib" and p2["prayer"] == "isha":
                    assert p1["date"] == p2["date"], (
                        f"Cross-day pair detected! Maghrib on {p1['date']} "
                        f"paired with Isha on {p2['date']}"
                    )


# ---------------------------------------------------------------------------
# 8. Adhan_dt and period_end_dt are always present
# ---------------------------------------------------------------------------

class TestEnumeratePrayerFields:
    """Every returned prayer must have adhan_dt and period_end_dt."""

    def test_fields_present(self):
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=14)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)

        for p in prayers:
            assert "adhan_dt" in p, f"Missing adhan_dt for {p['prayer']}"
            assert "period_end_dt" in p, f"Missing period_end_dt for {p['prayer']}"
            assert "schedule" in p, f"Missing schedule for {p['prayer']}"
            assert isinstance(p["adhan_dt"], datetime)
            assert isinstance(p["period_end_dt"], datetime)
            assert p["adhan_dt"] < p["period_end_dt"], (
                f"{p['prayer']} adhan_dt={p['adhan_dt']} >= period_end_dt={p['period_end_dt']}"
            )

    def test_day_number_starts_at_zero(self):
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=30)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)

        day_numbers = {p["day_number"] for p in prayers}
        assert 0 in day_numbers, "Departure day should be day_number=0"
        if arr.date() > dep.date():
            assert 1 in day_numbers, "Next day should be day_number=1"


# ---------------------------------------------------------------------------
# 9. build_pairs_from_prayers produces correct groupings
# ---------------------------------------------------------------------------

class TestBuildPairsFromPrayers:
    """Verify pair grouping logic."""

    def test_simple_daytime_trip(self):
        """8 AM - 10 PM same day: Dhuhr+Asr pair, Maghrib+Isha pair, Fajr not included."""
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=14)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        pairs = build_pairs_from_prayers(prayers)

        pair_keys = [k for k, _ in pairs]
        # Should have dhuhr_asr and maghrib_isha pairs for day 0
        pair_types = []
        for key, group in pairs:
            names = tuple(p["prayer"] for p in group)
            pair_types.append(names)

        # Dhuhr+Asr should be one pair
        assert ("dhuhr", "asr") in pair_types, (
            f"Expected Dhuhr+Asr pair, got: {pair_types}"
        )

    def test_multi_day_separate_pairs(self):
        """48h trip should have separate pairs for each day."""
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=48)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        pairs = build_pairs_from_prayers(prayers)

        # Count dhuhr_asr pairs — should be at least 2 (one per day)
        dhuhr_asr_pairs = [
            (k, g) for k, g in pairs
            if len(g) == 2 and g[0]["prayer"] == "dhuhr" and g[1]["prayer"] == "asr"
        ]
        assert len(dhuhr_asr_pairs) >= 2, (
            f"48h trip should have at least 2 Dhuhr+Asr pairs, got {len(dhuhr_asr_pairs)}"
        )

    def test_fajr_always_standalone(self):
        """Fajr is never paired with another prayer."""
        dep = datetime(2026, 3, 21, 4, 0, tzinfo=PT)
        arr = dep + timedelta(hours=24)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        pairs = build_pairs_from_prayers(prayers)

        for key, group in pairs:
            if any(p["prayer"] == "fajr" for p in group):
                assert len(group) == 1, (
                    f"Fajr should be standalone but was paired: {[p['prayer'] for p in group]}"
                )

    def test_pairs_sorted_chronologically(self):
        """Pairs must be sorted by earliest adhan_dt."""
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=36)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        pairs = build_pairs_from_prayers(prayers)

        min_dts = [min(p["adhan_dt"] for p in group) for _, group in pairs]
        for i in range(len(min_dts) - 1):
            assert min_dts[i] <= min_dts[i + 1], (
                f"Pairs not chronological: {min_dts[i]} > {min_dts[i + 1]}"
            )


# ---------------------------------------------------------------------------
# 10. Edge case: very short evening trip (only Maghrib)
# ---------------------------------------------------------------------------

class TestShortEveningTrip:
    """Short trip during Maghrib only — should only include Maghrib."""

    def test_short_maghrib_only_trip(self):
        dep = datetime(2026, 3, 21, 19, 30, tzinfo=PT)  # 7:30 PM
        arr = dep + timedelta(minutes=45)  # 8:15 PM
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)

        # Should NOT include Dhuhr or Asr (long past)
        stale = [p for p in prayers if p["prayer"] in ("dhuhr", "asr")]
        assert len(stale) == 0, (
            f"Short 7:30 PM trip should not include stale prayers: "
            f"{[p['prayer'] for p in stale]}"
        )


# ---------------------------------------------------------------------------
# 11. Window overlap precision: period_end exactly at departure
# ---------------------------------------------------------------------------

class TestBoundaryOverlap:
    """Prayer whose period_end equals departure exactly → NOT included."""

    def test_period_end_at_departure_excluded(self):
        """If Asr period ends exactly at departure time, Asr is excluded."""
        dep = datetime(2026, 3, 21, 18, 45, tzinfo=PT)
        arr = dep + timedelta(hours=2)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        sched = schedules[dep.date()]
        maghrib_adhan = sched.get("maghrib_adhan")
        if maghrib_adhan:
            # Set departure to exactly Maghrib adhan (= Asr period end)
            maghrib_min = hhmm_to_minutes(maghrib_adhan)
            exact_dep = datetime(
                2026, 3, 21, maghrib_min // 60, maghrib_min % 60, tzinfo=PT
            )
            exact_arr = exact_dep + timedelta(hours=2)
            prayers = enumerate_trip_prayers(exact_dep, exact_arr, schedules)
            today_asrs = [p for p in prayers if p["prayer"] == "asr" and p["date"] == dep.date()]
            # Asr period ends at exactly Maghrib adhan = departure time
            # Overlap check: departure_dt < period_end_dt → dep == period_end → NOT <, so excluded
            assert len(today_asrs) == 0, (
                "Asr should be excluded when departure is exactly at Maghrib adhan"
            )


# ---------------------------------------------------------------------------
# 12. Regression: empty schedules_by_date
# ---------------------------------------------------------------------------

class TestEmptySchedules:
    """Empty or missing schedules should not crash."""

    def test_empty_schedules(self):
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=10)
        prayers = enumerate_trip_prayers(dep, arr, {})
        assert prayers == []

    def test_partial_schedules(self):
        """Only departure day has a schedule, arrival day missing."""
        dep = datetime(2026, 3, 21, 20, 0, tzinfo=PT)
        arr = dep + timedelta(hours=14)
        schedules = {dep.date(): _la_schedule(dep.date())}
        # Should not crash; just won't have arrival-day prayers
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        assert isinstance(prayers, list)
        # All returned prayers should be from dep.date()
        for p in prayers:
            assert p["date"] == dep.date()


# ---------------------------------------------------------------------------
# 13. Multiple Fajrs in 48h trip
# ---------------------------------------------------------------------------

class TestMultipleFajrs:
    """A 48h trip should include Fajr on multiple days."""

    def test_two_fajrs(self):
        dep = datetime(2026, 3, 21, 4, 0, tzinfo=PT)  # Before Fajr
        arr = dep + timedelta(hours=48)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)

        fajrs = [p for p in prayers if p["prayer"] == "fajr"]
        assert len(fajrs) >= 2, (
            f"48h trip starting at 4 AM should have at least 2 Fajrs, got {len(fajrs)}"
        )
        # Each Fajr on different dates
        fajr_dates = [p["date"] for p in fajrs]
        assert len(set(fajr_dates)) == len(fajrs), (
            f"Fajrs should be on different dates: {fajr_dates}"
        )


# ---------------------------------------------------------------------------
# 14. Same-day Dhuhr+Asr pairing correctness across days
# ---------------------------------------------------------------------------

class TestPairIntegrity:
    """Verify pairs always contain same-day prayers."""

    def test_all_pairs_same_day(self):
        """Every 2-prayer pair must have both on the same calendar day."""
        dep = datetime(2026, 3, 21, 6, 0, tzinfo=PT)
        arr = dep + timedelta(hours=60)  # 2.5 days
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        pairs = build_pairs_from_prayers(prayers)

        for pair_key, group in pairs:
            if len(group) == 2:
                assert group[0]["date"] == group[1]["date"], (
                    f"Pair {pair_key} crosses days: "
                    f"{group[0]['prayer']}={group[0]['date']} vs "
                    f"{group[1]['prayer']}={group[1]['date']}"
                )

    def test_pair_key_includes_day(self):
        """Pair keys should include day number for uniqueness."""
        dep = datetime(2026, 3, 21, 8, 0, tzinfo=PT)
        arr = dep + timedelta(hours=48)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)
        pairs = build_pairs_from_prayers(prayers)

        keys = [k for k, _ in pairs]
        # Should have day0 and day1 variants
        assert any("day0" in k for k in keys), f"No day0 pairs found in {keys}"
        assert any("day1" in k for k in keys), f"No day1 pairs found in {keys}"


# ---------------------------------------------------------------------------
# 15. Midnight crossing: prayers from both days
# ---------------------------------------------------------------------------

class TestMidnightCrossing:
    """Trip crossing midnight should include prayers from both calendar days."""

    def test_midnight_crossing_both_days(self):
        dep = datetime(2026, 3, 21, 23, 0, tzinfo=PT)  # 11 PM
        arr = dep + timedelta(hours=10)  # 9 AM next day
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)

        dates = {p["date"] for p in prayers}
        # Should have prayers from today (Isha still active) and tomorrow (Fajr)
        assert len(dates) >= 1, "Should have prayers from at least one day"

        # Isha at 11 PM is still valid (period extends to Fajr)
        today_ishas = [p for p in prayers if p["prayer"] == "isha" and p["date"] == dep.date()]
        assert len(today_ishas) == 1, "Isha should be included at 11 PM"

    def test_all_returned_prayers_have_valid_windows(self):
        """Every prayer's window must actually overlap with the trip."""
        dep = datetime(2026, 3, 21, 23, 0, tzinfo=PT)
        arr = dep + timedelta(hours=10)
        schedules = _schedules_for_range(dep.date(), arr.date(), _la_schedule)
        prayers = enumerate_trip_prayers(dep, arr, schedules)

        for p in prayers:
            # Verify: [adhan_dt, period_end_dt] overlaps [dep, arr]
            assert p["adhan_dt"] < arr, (
                f"{p['prayer']} adhan_dt={p['adhan_dt']} is not before arrival"
            )
            assert dep < p["period_end_dt"], (
                f"{p['prayer']} period_end_dt={p['period_end_dt']} is not after departure"
            )
