"""
Tests for progressive radius search when no mosque found.
Rules: ROUTE_PLANNING_ALGORITHM.md §2 — Progressive Radius Search

When no mosque found at 25 km:
1. Expand to 50 km
2. Expand to 75 km
3. Still none: return nearest mosque at any distance as fallback with warning
"""
import pytest


SEARCH_RADII = [25, 50, 75]  # km


def progressive_search(candidates_by_radius: dict[int, list]) -> tuple[list, int, bool]:
    """
    Simulate progressive radius search.

    Args:
        candidates_by_radius: {radius_km: [mosque_list]} — what each radius returns

    Returns:
        (mosques_found, radius_used, is_fallback)
    """
    for radius in SEARCH_RADII:
        results = candidates_by_radius.get(radius, [])
        if results:
            return results, radius, False

    # Fallback: return nearest at any distance
    all_mosques = []
    for r in sorted(candidates_by_radius.keys()):
        all_mosques.extend(candidates_by_radius[r])
    if all_mosques:
        return [all_mosques[0]], -1, True  # -1 = fallback radius

    return [], -1, True  # truly none


class TestProgressiveSearch:
    def test_found_at_25km(self):
        candidates = {25: [{"name": "Mosque A"}], 50: [], 75: []}
        results, radius, fallback = progressive_search(candidates)
        assert len(results) == 1
        assert radius == 25
        assert fallback is False

    def test_not_at_25_found_at_50(self):
        candidates = {25: [], 50: [{"name": "Mosque B"}], 75: []}
        results, radius, fallback = progressive_search(candidates)
        assert len(results) == 1
        assert radius == 50
        assert fallback is False

    def test_not_at_50_found_at_75(self):
        candidates = {25: [], 50: [], 75: [{"name": "Mosque C"}]}
        results, radius, fallback = progressive_search(candidates)
        assert len(results) == 1
        assert radius == 75
        assert fallback is False

    def test_none_at_any_radius_returns_fallback(self):
        candidates = {25: [], 50: [], 75: [], 100: [{"name": "Far Mosque"}]}
        results, radius, fallback = progressive_search(candidates)
        assert len(results) == 1
        assert fallback is True
        assert results[0]["name"] == "Far Mosque"

    def test_truly_no_mosques(self):
        candidates = {25: [], 50: [], 75: []}
        results, radius, fallback = progressive_search(candidates)
        assert len(results) == 0
        assert fallback is True

    def test_prefers_first_available_radius(self):
        """If found at 25 AND 50, should use 25 (don't search further)."""
        candidates = {25: [{"name": "Near"}], 50: [{"name": "Far"}], 75: []}
        results, radius, fallback = progressive_search(candidates)
        assert results[0]["name"] == "Near"
        assert radius == 25

    def test_multiple_at_same_radius(self):
        candidates = {25: [], 50: [{"name": "A"}, {"name": "B"}], 75: []}
        results, radius, fallback = progressive_search(candidates)
        assert len(results) == 2
        assert radius == 50
