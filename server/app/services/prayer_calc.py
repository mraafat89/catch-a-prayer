"""
Prayer time calculation using the praytimes library.
Used as fallback when mosque-specific times are not available.
"""
from datetime import date, datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Calculation methods mapping to praytimes method names
CALCULATION_METHODS = {
    "ISNA": "ISNA",       # Islamic Society of North America (standard for US/Canada)
    "MWL": "MWL",         # Muslim World League
    "Egypt": "Egypt",     # Egyptian General Authority
    "Makkah": "Makkah",   # Umm al-Qura University, Makkah
    "Karachi": "Karachi", # University of Islamic Sciences, Karachi
}

# Typical iqama offsets from adhan (minutes) when mosque-specific times unavailable
IQAMA_OFFSETS = {
    "fajr": 20,
    "dhuhr": 15,
    "asr": 10,
    "maghrib": 5,
    "isha": 15,
}


def calculate_prayer_times(
    lat: float,
    lng: float,
    target_date: date,
    method: str = "ISNA",
    timezone_offset: float = 0,
) -> dict:
    """
    Calculate prayer times for a location and date.
    Returns dict with HH:MM strings for each prayer and sunrise.
    Source is always 'calculated'.
    """
    try:
        from praytimes import PrayTimes
        pt = PrayTimes(method)
        times = pt.getTimes(
            (target_date.year, target_date.month, target_date.day),
            (lat, lng),
            timezone_offset,
        )
        return {
            "fajr_adhan":    _fmt(times.get("fajr")),
            "dhuhr_adhan":   _fmt(times.get("dhuhr")),
            "asr_adhan":     _fmt(times.get("asr")),
            "maghrib_adhan": _fmt(times.get("maghrib")),
            "isha_adhan":    _fmt(times.get("isha")),
            "sunrise":       _fmt(times.get("sunrise")),
            "source": "calculated",
            "confidence": "medium",
        }
    except Exception as e:
        logger.error(f"Prayer time calculation failed for ({lat}, {lng}): {e}")
        return {}


def estimate_iqama_times(adhan_times: dict) -> dict:
    """
    Estimate iqama times from adhan times using typical offsets.
    Only used as last resort when no mosque-specific iqama data exists.
    """
    result = {}
    for prayer, offset in IQAMA_OFFSETS.items():
        adhan_key = f"{prayer}_adhan"
        adhan = adhan_times.get(adhan_key)
        if adhan:
            result[f"{prayer}_iqama"] = _add_minutes(adhan, offset)
            result[f"{prayer}_iqama_source"] = "estimated"
            result[f"{prayer}_iqama_confidence"] = "low"
    return result


def _fmt(time_str: Optional[str]) -> Optional[str]:
    """Normalize praytimes output to HH:MM 24-hour format."""
    if not time_str or time_str in ("-----", ""):
        return None
    try:
        parts = time_str.split(":")
        h, m = int(parts[0]), int(parts[1])
        return f"{h:02d}:{m:02d}"
    except Exception:
        return None


def _add_minutes(time_str: str, minutes: int) -> str:
    """Add minutes to HH:MM string."""
    h, m = map(int, time_str.split(":"))
    total = h * 60 + m + minutes
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"
