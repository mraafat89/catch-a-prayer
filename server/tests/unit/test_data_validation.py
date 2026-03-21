"""
Tests for prayer schedule data validation.
Every malformed value the scraper might produce must be handled gracefully.
"""
import pytest
from app.services.mosque_search import hhmm_to_minutes


class TestHhmmToMinutes:
    """hhmm_to_minutes must NEVER crash, regardless of input."""

    def test_normal(self):
        assert hhmm_to_minutes("13:30") == 810

    def test_midnight(self):
        assert hhmm_to_minutes("00:00") == 0

    def test_end_of_day(self):
        assert hhmm_to_minutes("23:59") == 1439

    # ── Malformed inputs that previously crashed the server ──

    def test_none(self):
        assert hhmm_to_minutes(None) == 0

    def test_empty_string(self):
        assert hhmm_to_minutes("") == 0

    def test_no_colon(self):
        assert hhmm_to_minutes("1330") == 0

    def test_string_none(self):
        assert hhmm_to_minutes("None") == 0

    def test_am_pm_format(self):
        assert hhmm_to_minutes("1:30 PM") == 0

    def test_single_number(self):
        assert hhmm_to_minutes("5") == 0

    def test_three_parts(self):
        # "HH:MM:SS" — should handle gracefully
        result = hhmm_to_minutes("13:30:00")
        assert result == 810  # takes first two parts

    def test_float_string(self):
        assert hhmm_to_minutes("13.5") == 0

    def test_negative(self):
        assert hhmm_to_minutes("-1:30") == 0

    def test_hour_25(self):
        # Out of range but has colon
        result = hhmm_to_minutes("25:00")
        # Should either return 0 or 1500 — must not crash
        assert isinstance(result, int)

    def test_integer_input(self):
        assert hhmm_to_minutes(123) == 0

    def test_boolean_input(self):
        assert hhmm_to_minutes(True) == 0


class TestScheduleValidation:
    """Mosque schedules from the DB can have various data quality issues."""

    def _make_schedule(self, **overrides):
        base = {
            "fajr_adhan": "05:30", "fajr_iqama": "05:50",
            "dhuhr_adhan": "12:30", "dhuhr_iqama": "13:00",
            "asr_adhan": "16:00", "asr_iqama": "16:15",
            "maghrib_adhan": "19:00", "maghrib_iqama": "19:05",
            "isha_adhan": "20:30", "isha_iqama": "20:45",
            "sunrise": "06:30",
        }
        base.update(overrides)
        return base

    def test_valid_schedule_all_parse(self):
        s = self._make_schedule()
        for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
            assert hhmm_to_minutes(s[f"{prayer}_adhan"]) > 0

    def test_missing_iqama_doesnt_crash(self):
        s = self._make_schedule(dhuhr_iqama=None)
        assert hhmm_to_minutes(s["dhuhr_iqama"]) == 0
        assert hhmm_to_minutes(s["dhuhr_adhan"]) == 750  # adhan still works

    def test_corrupt_iqama_doesnt_crash(self):
        s = self._make_schedule(fajr_iqama="invalid")
        assert hhmm_to_minutes(s["fajr_iqama"]) == 0

    def test_all_none_schedule(self):
        s = {f"{p}_{t}": None for p in ["fajr","dhuhr","asr","maghrib","isha"]
             for t in ["adhan", "iqama"]}
        for key in s:
            assert hhmm_to_minutes(s[key]) == 0  # no crash

    def test_mixed_valid_invalid(self):
        """Real scenario: scraper got some times, missed others."""
        s = self._make_schedule(
            asr_iqama="",       # empty
            maghrib_iqama=None, # null
            isha_adhan="2030",  # no colon
        )
        assert hhmm_to_minutes(s["asr_iqama"]) == 0
        assert hhmm_to_minutes(s["maghrib_iqama"]) == 0
        assert hhmm_to_minutes(s["isha_adhan"]) == 0
        # Valid ones still work
        assert hhmm_to_minutes(s["fajr_adhan"]) == 330
        assert hhmm_to_minutes(s["dhuhr_adhan"]) == 750
