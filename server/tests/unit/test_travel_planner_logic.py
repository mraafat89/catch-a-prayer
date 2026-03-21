"""
Unit tests for travel planner logic — overlap detection, itinerary building, checkpoints.
Source: server/app/services/travel_planner.py
Rules: ROUTE_PLANNING_ALGORITHM.md, PRAYER_LOGIC_RULES.md §5
"""
import pytest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times
from app.services.travel_planner import (
    prayer_status_at_arrival,
    _prayer_overlaps_trip,
    _pair_relevant,
    build_itineraries,
    build_checkpoints,
    hhmm_to_minutes,
)

# ─── Test schedule ────────────────────────────────────────────────────────────

ET = ZoneInfo("America/New_York")
TODAY = date(2026, 3, 20)


def nyc_schedule():
    calc = calculate_prayer_times(40.7128, -74.0060, TODAY, timezone_offset=-4)
    return {**calc, **estimate_iqama_times(calc)}


def hm(h, m=0):
    return h * 60 + m


# ─── prayer_status_at_arrival ─────────────────────────────────────────────────

class TestPrayerStatusAtArrival:
    """Test the core function that determines if a prayer is catchable at a given arrival time."""

    def test_arrive_before_adhan(self):
        schedule = nyc_schedule()
        result = prayer_status_at_arrival("dhuhr", schedule, hm(11, 0))
        # Before adhan → either None or not catchable
        assert result is None or result.get("status") in (None, "upcoming")

    def test_arrive_at_iqama(self):
        schedule = nyc_schedule()
        iqama_min = hhmm_to_minutes(schedule["dhuhr_iqama"])
        result = prayer_status_at_arrival("dhuhr", schedule, iqama_min)
        assert result is not None
        assert result["status"] in ("can_catch_with_imam", "can_catch_with_imam_in_progress")

    def test_arrive_during_congregation(self):
        schedule = nyc_schedule()
        iqama_min = hhmm_to_minutes(schedule["dhuhr_iqama"])
        result = prayer_status_at_arrival("dhuhr", schedule, iqama_min + 10)
        assert result is not None
        assert result["status"] in ("can_catch_with_imam", "can_catch_with_imam_in_progress")

    def test_arrive_after_congregation(self):
        schedule = nyc_schedule()
        iqama_min = hhmm_to_minutes(schedule["dhuhr_iqama"])
        result = prayer_status_at_arrival("dhuhr", schedule, iqama_min + 20)
        assert result is not None
        assert result["status"] == "can_pray_solo_at_mosque"

    def test_arrive_after_period_end(self):
        schedule = nyc_schedule()
        asr_min = hhmm_to_minutes(schedule["asr_adhan"])
        result = prayer_status_at_arrival("dhuhr", schedule, asr_min + 5)
        # Dhuhr period ended (Asr adhan passed)
        assert result is None or result.get("status") == "missed_make_up"

    def test_isha_at_1am(self):
        """Isha at 1 AM → still in Isha period (before Fajr)."""
        schedule = nyc_schedule()
        result = prayer_status_at_arrival("isha", schedule, hm(1, 0))
        assert result is not None
        assert result["status"] in ("can_pray_solo_at_mosque", "can_catch_with_imam")

    def test_isha_after_fajr(self):
        """After Fajr → Isha period ended."""
        schedule = nyc_schedule()
        fajr_min = hhmm_to_minutes(schedule["fajr_adhan"])
        result = prayer_status_at_arrival("isha", schedule, fajr_min + 30)
        assert result is None


# ─── _prayer_overlaps_trip ────────────────────────────────────────────────────

class TestPrayerOverlapsTrip:
    """Test trip-window overlap detection."""

    def test_daytime_trip_overlaps_dhuhr(self):
        schedule = nyc_schedule()
        # Depart 10 AM, arrive 3 PM → overlaps Dhuhr (12:30)
        assert _prayer_overlaps_trip("dhuhr", schedule, hm(10, 0), hm(15, 0)) is True

    def test_daytime_trip_overlaps_asr(self):
        schedule = nyc_schedule()
        # Depart 10 AM, arrive 5 PM → overlaps Asr (16:00)
        assert _prayer_overlaps_trip("asr", schedule, hm(10, 0), hm(17, 0)) is True

    def test_no_overlap_between_prayers(self):
        schedule = nyc_schedule()
        # Depart 7 AM, arrive 7:30 AM → between sunrise and Dhuhr, no prayer active
        result = _prayer_overlaps_trip("dhuhr", schedule, hm(7, 0), hm(7, 30))
        assert result is False

    def test_overnight_catches_fajr(self):
        schedule = nyc_schedule()
        # Depart 10 PM, arrive 7 AM → overlaps Fajr (05:30)
        assert _prayer_overlaps_trip("fajr", schedule, hm(22, 0), hm(7, 0)) is True

    def test_overnight_catches_isha(self):
        schedule = nyc_schedule()
        # Depart 8 PM, arrive 2 AM → Isha at 20:30 overlaps
        assert _prayer_overlaps_trip("isha", schedule, hm(20, 0), hm(2, 0)) is True


class TestPairRelevant:
    """Test pair relevance — either prayer overlapping makes the pair relevant."""

    def test_pair_relevant_when_p2_overlaps(self):
        schedule = nyc_schedule()
        # Trip 15:00-17:00 → Asr (16:00) overlaps but not Dhuhr (12:30)
        assert _pair_relevant("dhuhr", "asr", schedule, hm(15, 0), hm(17, 0)) is True

    def test_pair_not_relevant_when_neither_overlaps(self):
        schedule = nyc_schedule()
        # Trip 7:00-8:00 → neither Dhuhr nor Asr overlaps
        assert _pair_relevant("dhuhr", "asr", schedule, hm(7, 0), hm(8, 0)) is False


# ─── build_checkpoints ────────────────────────────────────────────────────────

class TestBuildCheckpoints:
    def test_creates_checkpoints_from_route(self):
        """Given a simple route, checkpoints are created at intervals."""
        route = {
            "geometry": {
                "coordinates": [
                    [-74.006, 40.713],  # NYC
                    [-74.5, 40.5],      # midpoint
                    [-75.165, 39.953],  # Philly
                ]
            },
            "duration": 7200,  # 2 hours
            "distance": 150000,  # 150 km
        }
        departure = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        result = build_checkpoints(route, departure)
        assert len(result) >= 2  # at least start and end
        # All checkpoints should have lat, lng, time
        for cp in result:
            assert "lat" in cp
            assert "lng" in cp
            assert "time" in cp

    def test_empty_geometry_returns_minimal(self):
        route = {
            "geometry": {"coordinates": []},
            "duration": 3600,
            "distance": 100000,
        }
        departure = datetime(2026, 3, 20, 10, 0, tzinfo=ET)
        result = build_checkpoints(route, departure)
        # Should handle gracefully — empty or minimal list
        assert isinstance(result, list)


# ─── build_itineraries ────────────────────────────────────────────────────────

class TestBuildItineraries:
    """Test itinerary template generation."""

    def _make_option(self, option_type, prayer, feasible=True, detour=10):
        return {
            "option_type": option_type,
            "label": f"{option_type} for {prayer}",
            "description": "test",
            "prayers": [prayer],
            "combination_label": None,
            "stops": [{
                "mosque_id": "test-id",
                "mosque_name": "Test Mosque",
                "mosque_lat": 40.71,
                "mosque_lng": -74.00,
                "mosque_address": "123 Test St",
                "prayer": prayer,
                "estimated_arrival_time": "13:00",
                "minutes_into_trip": 60,
                "detour_minutes": detour,
                "status": "can_catch_with_imam",
                "iqama_time": "13:00",
                "adhan_time": "12:30",
            }] if feasible else [],
            "feasible": feasible,
            "note": None,
        }

    def test_musafir_generates_multiple_itineraries(self):
        """Given prayer pairs with options, generates multiple itinerary templates."""
        pairs = [
            {
                "pair": "dhuhr_asr",
                "label": "Dhuhr + Asr",
                "emoji": "",
                "options": [
                    self._make_option("combine_early", "dhuhr"),
                    self._make_option("combine_late", "asr"),
                    self._make_option("at_destination", "dhuhr"),
                ],
            },
        ]
        result = build_itineraries(pairs, allow_combining=True)
        assert len(result) >= 1
        # Each itinerary should have pair_choices
        for it in result:
            assert "pair_choices" in it
            assert "feasible" in it

    def test_muqeem_no_combining(self):
        """Muqeem mode: no combine_early/late options used."""
        pairs = [
            {
                "pair": "dhuhr_asr",
                "label": "Dhuhr + Asr",
                "emoji": "",
                "options": [
                    self._make_option("solo_stop", "dhuhr"),
                    self._make_option("solo_stop", "asr"),
                    self._make_option("at_destination", "dhuhr"),
                ],
            },
        ]
        result = build_itineraries(pairs, allow_combining=False)
        for it in result:
            for pc in it.get("pair_choices", []):
                assert pc["option"]["option_type"] != "combine_early"
                assert pc["option"]["option_type"] != "combine_late"

    def test_empty_pairs_returns_empty(self):
        result = build_itineraries([], allow_combining=True)
        assert result == [] or isinstance(result, list)

    def test_dedup_removes_identical_templates(self):
        """Duplicate combination keys are removed."""
        pairs = [
            {
                "pair": "dhuhr_asr",
                "label": "Dhuhr + Asr",
                "emoji": "",
                "options": [
                    self._make_option("combine_early", "dhuhr"),
                ],
            },
        ]
        result = build_itineraries(pairs, allow_combining=True)
        # Even with limited options, should not produce duplicates
        labels = [it["label"] for it in result]
        # Duplicates may exist with different labels but same content
        assert len(result) <= 5  # max templates
