"""
Geographic Utilities
=====================
Auto-assign state, timezone, and country from address or coordinates.

Priority:
1. Parse from Google formatted_address (most accurate)
2. Parse from OSM addr:state tag
3. Fall back to lat/lng bounding box lookup (least accurate, border issues)
"""
from __future__ import annotations

import re


# US state boundaries (simplified bounding boxes)
# Format: state_code -> (min_lat, max_lat, min_lng, max_lng)
# For border states, we use the centroid approach below as tiebreaker
US_STATES = {
    "AL": (30.2, 35.0, -88.5, -84.9),
    "AK": (51.2, 71.4, -179.2, -129.9),
    "AZ": (31.3, 37.0, -114.8, -109.0),
    "AR": (33.0, 36.5, -94.6, -89.6),
    "CA": (32.5, 42.0, -124.4, -114.1),
    "CO": (37.0, 41.0, -109.1, -102.0),
    "CT": (41.0, 42.1, -73.7, -71.8),
    "DE": (38.5, 39.8, -75.8, -75.0),
    "FL": (24.4, 31.0, -87.6, -80.0),
    "GA": (30.4, 35.0, -85.6, -80.8),
    "HI": (18.9, 22.2, -160.2, -154.8),
    "ID": (42.0, 49.0, -117.2, -111.0),
    "IL": (37.0, 42.5, -91.5, -87.5),
    "IN": (37.8, 41.8, -88.1, -84.8),
    "IA": (40.4, 43.5, -96.6, -90.1),
    "KS": (37.0, 40.0, -102.1, -94.6),
    "KY": (36.5, 39.1, -89.6, -81.9),
    "LA": (29.0, 33.0, -94.0, -89.0),
    "ME": (43.1, 47.5, -71.1, -66.9),
    "MD": (38.0, 39.7, -79.5, -75.0),
    "MA": (41.2, 42.9, -73.5, -69.9),
    "MI": (41.7, 48.3, -90.4, -82.4),
    "MN": (43.5, 49.4, -97.2, -89.5),
    "MS": (30.2, 35.0, -91.7, -88.1),
    "MO": (36.0, 40.6, -95.8, -89.1),
    "MT": (44.4, 49.0, -116.1, -104.0),
    "NE": (40.0, 43.0, -104.1, -95.3),
    "NV": (35.0, 42.0, -120.0, -114.0),
    "NH": (42.7, 45.3, -72.6, -70.7),
    "NJ": (38.9, 41.4, -75.6, -73.9),
    "NM": (31.3, 37.0, -109.1, -103.0),
    "NY": (40.5, 45.0, -79.8, -71.9),
    "NC": (33.8, 36.6, -84.3, -75.5),
    "ND": (45.9, 49.0, -104.1, -96.6),
    "OH": (38.4, 42.0, -84.8, -80.5),
    "OK": (33.6, 37.0, -103.0, -94.4),
    "OR": (42.0, 46.3, -124.6, -116.5),
    "PA": (39.7, 42.3, -80.5, -74.7),
    "RI": (41.1, 42.0, -71.9, -71.1),
    "SC": (32.0, 35.2, -83.4, -78.5),
    "SD": (42.5, 45.9, -104.1, -96.4),
    "TN": (35.0, 36.7, -90.3, -81.6),
    "TX": (25.8, 36.5, -106.6, -93.5),
    "UT": (37.0, 42.0, -114.1, -109.0),
    "VT": (42.7, 45.0, -73.4, -71.5),
    "VA": (36.5, 39.5, -83.7, -75.2),
    "WA": (45.5, 49.0, -124.8, -116.9),
    "WV": (37.2, 40.6, -82.6, -77.7),
    "WI": (42.5, 47.1, -92.9, -86.8),
    "WY": (41.0, 45.0, -111.1, -104.1),
    "DC": (38.8, 39.0, -77.1, -77.0),
    "PR": (17.9, 18.5, -67.3, -65.6),
}

# Canadian provinces (simplified)
CA_PROVINCES = {
    "ON": (42.0, 56.9, -95.2, -74.3),
    "QC": (45.0, 62.6, -79.8, -57.1),
    "BC": (48.3, 60.0, -139.1, -114.0),
    "AB": (49.0, 60.0, -120.0, -110.0),
    "SK": (49.0, 60.0, -110.0, -101.4),
    "MB": (49.0, 60.0, -102.0, -88.9),
    "NB": (44.6, 48.1, -69.1, -63.8),
    "NS": (43.4, 47.0, -66.4, -59.7),
    "NL": (46.6, 60.4, -67.8, -52.6),
    "PE": (46.0, 47.1, -64.4, -62.0),
    "NT": (60.0, 78.8, -136.5, -102.0),
    "NU": (51.7, 83.1, -120.4, -61.2),
    "YT": (60.0, 69.6, -141.0, -123.8),
}

# State → timezone mapping
STATE_TIMEZONES = {
    # US Eastern
    "CT": "America/New_York", "DE": "America/New_York", "FL": "America/New_York",
    "GA": "America/New_York", "IN": "America/New_York", "KY": "America/New_York",
    "ME": "America/New_York", "MD": "America/New_York", "MA": "America/New_York",
    "MI": "America/New_York", "NH": "America/New_York", "NJ": "America/New_York",
    "NY": "America/New_York", "NC": "America/New_York", "OH": "America/New_York",
    "PA": "America/New_York", "RI": "America/New_York", "SC": "America/New_York",
    "TN": "America/New_York", "VT": "America/New_York", "VA": "America/New_York",
    "WV": "America/New_York", "DC": "America/New_York",
    # US Central
    "AL": "America/Chicago", "AR": "America/Chicago", "IL": "America/Chicago",
    "IA": "America/Chicago", "KS": "America/Chicago", "LA": "America/Chicago",
    "MN": "America/Chicago", "MS": "America/Chicago", "MO": "America/Chicago",
    "NE": "America/Chicago", "ND": "America/Chicago", "OK": "America/Chicago",
    "SD": "America/Chicago", "TX": "America/Chicago", "WI": "America/Chicago",
    # US Mountain
    "AZ": "America/Denver", "CO": "America/Denver", "ID": "America/Boise",
    "MT": "America/Denver", "NM": "America/Denver", "UT": "America/Denver",
    "WY": "America/Denver",
    # US Pacific
    "CA": "America/Los_Angeles", "NV": "America/Los_Angeles",
    "OR": "America/Los_Angeles", "WA": "America/Los_Angeles",
    # US Other
    "AK": "America/Anchorage", "HI": "Pacific/Honolulu", "PR": "America/Puerto_Rico",
    # Canada
    "ON": "America/Toronto", "QC": "America/Toronto",
    "AB": "America/Edmonton", "BC": "America/Vancouver",
    "SK": "America/Regina", "MB": "America/Winnipeg",
    "NB": "America/Halifax", "NS": "America/Halifax", "PE": "America/Halifax",
    "NL": "America/St_Johns",
    "NT": "America/Yellowknife", "NU": "America/Yellowknife",
    "YT": "America/Whitehorse",
}


def get_state_from_coords(lat: float, lng: float) -> str | None:
    """Determine US state or Canadian province from lat/lng."""
    candidates = []

    # Check US states
    for code, (min_lat, max_lat, min_lng, max_lng) in US_STATES.items():
        if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
            # Score by how well the point fits inside the box (smaller box = better match)
            box_area = (max_lat - min_lat) * (max_lng - min_lng)
            center_lat = (min_lat + max_lat) / 2
            center_lng = (min_lng + max_lng) / 2
            dist = (lat - center_lat) ** 2 + (lng - center_lng) ** 2
            candidates.append((code, box_area, dist, "US"))

    # Check Canadian provinces
    for code, (min_lat, max_lat, min_lng, max_lng) in CA_PROVINCES.items():
        if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
            box_area = (max_lat - min_lat) * (max_lng - min_lng)
            center_lat = (min_lat + max_lat) / 2
            center_lng = (min_lng + max_lng) / 2
            dist = (lat - center_lat) ** 2 + (lng - center_lng) ** 2
            candidates.append((code, box_area, dist, "CA"))

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0][0]

    # Multiple candidates (border overlap) — use reference points for tiebreaking
    # These are approximate population centers, not just capitals
    REFERENCE_POINTS = {
        "NY": (42.65, -73.75), "NJ": (40.22, -74.76), "CT": (41.60, -72.70),
        "PA": (40.27, -76.88), "DC": (38.91, -77.04), "MA": (42.36, -71.06),
        "ON": (43.65, -79.38), "QC": (46.81, -71.21), "BC": (49.28, -123.12),
        "MI": (42.73, -84.56), "OH": (39.96, -82.99), "VA": (37.54, -77.44),
        "MD": (39.29, -76.61), "WV": (38.35, -81.63), "VT": (44.26, -72.58),
        "NH": (43.21, -71.54), "ME": (44.31, -69.78), "RI": (41.82, -71.41),
        "DE": (39.16, -75.52), "NC": (35.78, -78.64), "SC": (34.00, -81.03),
        "GA": (33.75, -84.39), "FL": (30.33, -81.66), "AL": (32.38, -86.30),
        "TN": (36.16, -86.78), "KY": (38.19, -84.87), "IN": (39.77, -86.16),
        "IL": (41.88, -87.63), "WI": (43.07, -89.40), "MN": (44.98, -93.27),
        "AB": (53.55, -113.49), "SK": (52.13, -106.67), "MB": (49.90, -97.14),
    }
    best = None
    best_dist = float("inf")
    for code, box_area, center_dist, region in candidates:
        ref = REFERENCE_POINTS.get(code)
        if ref:
            dist = (lat - ref[0]) ** 2 + (lng - ref[1]) ** 2
        else:
            dist = center_dist
        if dist < best_dist:
            best_dist = dist
            best = code
    return best


def get_country_from_coords(lat: float, lng: float) -> str:
    """Determine country (US or CA) from lat/lng."""
    # Simple boundary: Canada is mostly above 49°N (with exceptions)
    state = get_state_from_coords(lat, lng)
    if state and state in CA_PROVINCES:
        return "CA"
    if state and state in US_STATES:
        return "US"
    # Fallback: above 49°N in western NA is likely Canada
    if lat > 49 and lng < -50:
        return "CA"
    return "US"


def get_timezone_from_state(state: str | None) -> str | None:
    """Get IANA timezone from state/province code."""
    if state:
        return STATE_TIMEZONES.get(state)
    return None


def parse_state_from_address(address: str | None) -> tuple[str | None, str | None]:
    """
    Extract state/province and country from a formatted address string.
    Returns (state_code, country_code) or (None, None).

    Handles formats like:
    - "123 Main St, Brooklyn, NY 11201, USA"
    - "456 Elm Ave, Toronto, ON M5V 1A1, Canada"
    """
    if not address:
        return None, None

    # US: look for 2-letter state code before ZIP
    us_match = re.search(r',\s*([A-Z]{2})\s+\d{5}', address)
    if us_match:
        state = us_match.group(1)
        if state in STATE_TIMEZONES:
            country = "CA" if state in CA_PROVINCES else "US"
            return state, country

    # Canada: look for 2-letter province before postal code (A1A 1A1)
    ca_match = re.search(r',\s*([A-Z]{2})\s+[A-Z]\d[A-Z]', address)
    if ca_match:
        state = ca_match.group(1)
        if state in CA_PROVINCES:
            return state, "CA"

    # Check for country at end
    if "Canada" in address:
        return None, "CA"
    if "USA" in address or "United States" in address:
        return None, "US"

    return None, None


def enrich_mosque_geo(lat: float, lng: float, address: str | None = None) -> dict:
    """
    Get state, timezone, and country for a mosque.
    Uses address first (most accurate), falls back to lat/lng bounding boxes.
    Returns dict with keys: state, timezone, country.
    """
    # Try address parsing first (most accurate)
    state, country = parse_state_from_address(address)

    # Fall back to coordinate lookup only if address parsing failed
    if not state:
        state = get_state_from_coords(lat, lng)

    if not country:
        country = get_country_from_coords(lat, lng)

    return {
        "state": state,
        "timezone": get_timezone_from_state(state),
        "country": country,
    }


def is_valid_mosque_data(name: str | None, lat: float | None, lng: float | None,
                          address: str | None = None) -> bool:
    """
    Check if a mosque record has enough data to be useful.
    A mosque without a name or coordinates is useless.
    """
    if not name or not name.strip():
        return False
    if lat is None or lng is None:
        return False
    if lat == 0 and lng == 0:
        return False
    # Must be within US/Canada bounds
    if not (18.0 <= lat <= 83.0 and -180.0 <= lng <= -50.0):
        return False
    return True
