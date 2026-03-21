"""
Tests for itinerary scoring and ranking.
Rules: ROUTE_PLANNING_ALGORITHM.md §5 — Score & Rank Itineraries

Score formula:
  score = (total_detour_minutes * 2) + (stop_count * 10) + (infeasible_count * 100) - (imam_catch_count * 5)
Lower score = better. Sorted ascending.
"""
import pytest
from app.services.travel_planner import score_itinerary, rank_itineraries


class TestScoreItinerary:
    def test_zero_detour_zero_stops(self):
        it = {"total_detour_minutes": 0, "stop_count": 0, "pair_choices": []}
        assert score_itinerary(it) == 0

    def test_detour_costs_2x(self):
        it = {"total_detour_minutes": 10, "stop_count": 0, "pair_choices": []}
        assert score_itinerary(it) == 20  # 10 * 2

    def test_stops_cost_10_each(self):
        it = {"total_detour_minutes": 0, "stop_count": 3, "pair_choices": []}
        assert score_itinerary(it) == 30  # 3 * 10

    def test_infeasible_heavily_penalized(self):
        it = {
            "total_detour_minutes": 0, "stop_count": 0,
            "pair_choices": [{"option": {"feasible": False, "stops": []}}],
        }
        assert score_itinerary(it) == 100  # 1 * 100

    def test_imam_catch_bonus(self):
        it = {
            "total_detour_minutes": 0, "stop_count": 1,
            "pair_choices": [{"option": {"feasible": True, "stops": [
                {"status": "can_catch_with_imam"},
            ]}}],
        }
        assert score_itinerary(it) == 5  # (1*10) - (1*5)

    def test_combined_score(self):
        it = {
            "total_detour_minutes": 15, "stop_count": 2,
            "pair_choices": [
                {"option": {"feasible": True, "stops": [
                    {"status": "can_catch_with_imam"},
                ]}},
                {"option": {"feasible": True, "stops": [
                    {"status": "can_pray_solo_at_mosque"},
                ]}},
            ],
        }
        # (15*2) + (2*10) + (0*100) - (1*5) = 30 + 20 - 5 = 45
        assert score_itinerary(it) == 45

    def test_infeasible_worse_than_high_detour(self):
        """Missing a prayer (infeasible) should score worse than a long detour."""
        long_detour = {"total_detour_minutes": 40, "stop_count": 2, "pair_choices": []}
        infeasible = {
            "total_detour_minutes": 5, "stop_count": 1,
            "pair_choices": [{"option": {"feasible": False, "stops": []}}],
        }
        assert score_itinerary(infeasible) > score_itinerary(long_detour)


class TestRankItineraries:
    def test_sorted_by_score_ascending(self):
        its = [
            {"label": "worst", "total_detour_minutes": 30, "stop_count": 3, "pair_choices": []},
            {"label": "best", "total_detour_minutes": 5, "stop_count": 1, "pair_choices": []},
            {"label": "mid", "total_detour_minutes": 15, "stop_count": 2, "pair_choices": []},
        ]
        ranked = rank_itineraries(its)
        assert ranked[0]["label"] == "best"
        assert ranked[1]["label"] == "mid"
        assert ranked[2]["label"] == "worst"

    def test_infeasible_sorted_last(self):
        its = [
            {"label": "infeasible", "total_detour_minutes": 0, "stop_count": 0,
             "pair_choices": [{"option": {"feasible": False, "stops": []}}]},
            {"label": "feasible", "total_detour_minutes": 20, "stop_count": 2, "pair_choices": []},
        ]
        ranked = rank_itineraries(its)
        assert ranked[0]["label"] == "feasible"
        assert ranked[1]["label"] == "infeasible"

    def test_empty_list(self):
        assert rank_itineraries([]) == []

    def test_single_itinerary(self):
        its = [{"label": "only", "total_detour_minutes": 0, "stop_count": 0, "pair_choices": []}]
        ranked = rank_itineraries(its)
        assert len(ranked) == 1

    def test_imam_catch_tiebreaker(self):
        """Same detour and stops, but one catches with imam → ranked higher."""
        with_imam = {
            "label": "imam", "total_detour_minutes": 10, "stop_count": 1,
            "pair_choices": [{"option": {"feasible": True, "stops": [
                {"status": "can_catch_with_imam"},
            ]}}],
        }
        without_imam = {
            "label": "solo", "total_detour_minutes": 10, "stop_count": 1,
            "pair_choices": [{"option": {"feasible": True, "stops": [
                {"status": "can_pray_solo_at_mosque"},
            ]}}],
        }
        ranked = rank_itineraries([without_imam, with_imam])
        assert ranked[0]["label"] == "imam"
