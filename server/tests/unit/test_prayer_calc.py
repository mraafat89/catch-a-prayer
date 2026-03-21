"""
Unit tests for prayer time calculation.
Tests: calculate_prayer_times, estimate_iqama_times, _fmt, _add_minutes
Source: server/app/services/prayer_calc.py
Rules: PRAYER_LOGIC_RULES.md §1
"""
from datetime import date

from app.services.prayer_calc import (
    calculate_prayer_times,
    estimate_iqama_times,
    _fmt,
    _add_minutes,
    IQAMA_OFFSETS,
)


# ─── _fmt (time normalization) ────────────────────────────────────────────────

class TestFmt:
    def test_normal_time(self):
        assert _fmt("14:30") == "14:30"

    def test_single_digit_hour(self):
        assert _fmt("5:30") == "05:30"

    def test_invalid_returns_none(self):
        assert _fmt("-----") is None
        assert _fmt("") is None
        assert _fmt(None) is None

    def test_midnight(self):
        assert _fmt("0:00") == "00:00"


# ─── _add_minutes ─────────────────────────────────────────────────────────────

class TestAddMinutes:
    def test_simple_add(self):
        assert _add_minutes("12:00", 30) == "12:30"

    def test_crosses_hour(self):
        assert _add_minutes("12:45", 30) == "13:15"

    def test_midnight_wrap(self):
        assert _add_minutes("23:50", 20) == "00:10"

    def test_zero_add(self):
        assert _add_minutes("08:00", 0) == "08:00"

    def test_negative_add(self):
        result = _add_minutes("01:00", -90)
        assert result == "23:30"


# ─── calculate_prayer_times ───────────────────────────────────────────────────

class TestCalculatePrayerTimes:
    """Test prayer time calculation for known locations."""

    def test_returns_all_five_prayers(self):
        result = calculate_prayer_times(40.7128, -74.0060, date(2026, 3, 20), timezone_offset=-4)
        assert result is not None
        for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
            assert f"{prayer}_adhan" in result, f"Missing {prayer}_adhan"
            assert result[f"{prayer}_adhan"] is not None, f"{prayer}_adhan is None"

    def test_returns_sunrise(self):
        result = calculate_prayer_times(40.7128, -74.0060, date(2026, 3, 20), timezone_offset=-4)
        assert "sunrise" in result
        assert result["sunrise"] is not None

    def test_prayer_order_chronological(self):
        """Fajr < Sunrise < Dhuhr < Asr < Maghrib < Isha."""
        result = calculate_prayer_times(40.7128, -74.0060, date(2026, 6, 21), timezone_offset=-4)
        times = [
            result["fajr_adhan"],
            result["sunrise"],
            result["dhuhr_adhan"],
            result["asr_adhan"],
            result["maghrib_adhan"],
            result["isha_adhan"],
        ]
        for i in range(len(times) - 1):
            assert times[i] < times[i + 1], f"{times[i]} should be before {times[i + 1]}"

    def test_summer_fajr_earlier_than_winter(self):
        summer = calculate_prayer_times(40.7128, -74.0060, date(2026, 6, 21), timezone_offset=-4)
        winter = calculate_prayer_times(40.7128, -74.0060, date(2026, 12, 21), timezone_offset=-5)
        assert summer["fajr_adhan"] < winter["fajr_adhan"]

    def test_summer_isha_later_than_winter(self):
        summer = calculate_prayer_times(40.7128, -74.0060, date(2026, 6, 21), timezone_offset=-4)
        winter = calculate_prayer_times(40.7128, -74.0060, date(2026, 12, 21), timezone_offset=-5)
        assert summer["isha_adhan"] > winter["isha_adhan"]

    def test_source_is_calculated(self):
        result = calculate_prayer_times(40.7128, -74.0060, date(2026, 3, 20), timezone_offset=-4)
        assert result.get("source") == "calculated"

    def test_invalid_coords_returns_empty(self):
        result = calculate_prayer_times(999, 999, date(2026, 3, 20), timezone_offset=0)
        # Should return empty dict or handle gracefully
        assert isinstance(result, dict)


# ─── estimate_iqama_times ─────────────────────────────────────────────────────

class TestEstimateIqamaTimes:
    def test_offsets_match_constants(self):
        adhan = {
            "fajr_adhan": "05:30",
            "dhuhr_adhan": "12:30",
            "asr_adhan": "16:00",
            "maghrib_adhan": "19:00",
            "isha_adhan": "20:30",
        }
        result = estimate_iqama_times(adhan)
        assert result["fajr_iqama"] == "05:50"      # +20
        assert result["dhuhr_iqama"] == "12:45"      # +15
        assert result["asr_iqama"] == "16:10"        # +10
        assert result["maghrib_iqama"] == "19:05"    # +5
        assert result["isha_iqama"] == "20:45"       # +15

    def test_missing_adhan_skipped(self):
        result = estimate_iqama_times({"fajr_adhan": "05:30"})
        assert "fajr_iqama" in result
        assert "dhuhr_iqama" not in result

    def test_source_is_estimated(self):
        result = estimate_iqama_times({"fajr_adhan": "05:30"})
        assert result.get("fajr_iqama_source") == "estimated"
