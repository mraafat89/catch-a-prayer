"""
Mosque search and prayer catching status calculation.
"""
from __future__ import annotations

import math
import logging
from datetime import datetime, date, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times

logger = logging.getLogger(__name__)
settings = get_settings()

PRAYERS = ["fajr", "dhuhr", "asr", "maghrib", "isha"]

# Human-readable labels
STATUS_LABELS = {
    "can_catch_with_imam":            "Can catch with Imam",
    "can_catch_with_imam_in_progress": "Congregation in progress",
    "can_pray_solo_at_mosque":        "Can pray solo",
    "pray_at_nearby_location":        "Pray at nearby location",
    "missed_make_up":                 "Missed — make up",
    "upcoming":                       "Upcoming",
}

SOURCE_LABELS = {
    "mosque_website_html":  "From mosque website",
    "mosque_website_js":    "From mosque website",
    "mosque_website_image": "From mosque schedule (image)",
    "mosque_website_pdf":   "From mosque schedule (PDF)",
    "islamicfinder":        "From IslamicFinder",
    "aladhan_mosque_db":    "From Aladhan database",
    "user_submitted":       "Community-submitted",
    "calculated":           "Calculated (astronomical) — verify with mosque",
    "estimated":            "Estimated — congregation time not confirmed",
}

CONGREGATION_WINDOW_MINUTES = 15  # default: how long after iqama you can still join


# ---------------------------------------------------------------------------
# Haversine (offline fallback for travel time)
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def estimate_travel_minutes(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Rough offline estimate. Only used when routing APIs are unavailable.
    Uses tiered speeds based on trip distance (longer = more highway driving)."""
    d_km = haversine_km(lat1, lng1, lat2, lng2)
    road_km = d_km * 1.4  # road factor
    if d_km > 100:
        speed_kmh = 100  # mostly highway
    elif d_km > 30:
        speed_kmh = 70   # mix of highway and suburban
    elif d_km > 10:
        speed_kmh = 50   # suburban / regional
    else:
        speed_kmh = 25   # urban / local
    minutes = (road_km / speed_kmh) * 60 + 3
    return max(1, round(minutes))


# ---------------------------------------------------------------------------
# Mapbox Matrix API (batch travel times)
# ---------------------------------------------------------------------------

async def get_mapbox_travel_times(
    user_lat: float, user_lng: float, mosque_coords: list[tuple[float, float]]
) -> Optional[list[Optional[int]]]:
    """
    Batch travel time from user to all mosques via Mapbox Matrix API.
    Returns list of travel times in minutes (None if unavailable).
    """
    if not settings.mapbox_api_key:
        return None

    try:
        # Mapbox: first coordinate is source
        coords = f"{user_lng},{user_lat};" + ";".join(f"{lng},{lat}" for lat, lng in mosque_coords)
        url = f"https://api.mapbox.com/directions-matrix/v1/mapbox/driving-traffic/{coords}"
        params = {
            "access_token": settings.mapbox_api_key,
            "sources": "0",
            "destinations": "all",
            "annotations": "duration",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        durations = data.get("durations", [[]])[0]  # row 0 = from user
        # durations[0] is user→user (0), durations[1..] are user→mosque[0..]
        return [
            round(d / 60) if d is not None else None
            for d in durations[1:]  # skip self
        ]
    except Exception as e:
        logger.warning(f"Mapbox Matrix API failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def hhmm_to_minutes(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def minutes_to_hhmm(total: int) -> str:
    total = total % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def fmt_dur(m: int) -> str:
    """Format a duration in minutes as '1h 5m' or '45 min'."""
    if m >= 60:
        return f"{m // 60}h {m % 60}m"
    return f"{m} min"


def add_minutes(t: str, delta: int) -> str:
    return minutes_to_hhmm(hhmm_to_minutes(t) + delta)


# ---------------------------------------------------------------------------
# Musafir (traveler, no route) combination options
# ---------------------------------------------------------------------------

_PAIR_PERIOD_END_KEYS = {
    "dhuhr": "asr_adhan",     # Dhuhr ends when Asr begins
    "maghrib": "isha_adhan",   # Maghrib ends when Isha begins
    "asr": "maghrib_adhan",
    "isha": "fajr_adhan",
}

def compute_travel_combinations(
    schedule: dict,
    current_min: int,
    prayed_prayers: Optional[set] = None,
) -> list:
    """
    Compute Jam' (prayer combining) options for a Musafir at a given mosque.
    Called when travel_mode=True and no destination (mode 1: Musafir no route).

    prayed_prayers: set of prayer names already performed (pair-level tracking in Musafir
    mode means both prayers of a pair are passed together, e.g. {"dhuhr", "asr"}).
    Pairs where both prayers are prayed (or prayer2 is prayed → sequential inference) are skipped.

    Returns a list of TravelPairPlan-compatible dicts — same shape as used
    by the route-based travel planner so the frontend can reuse the same renderer.
    """
    prayed = prayed_prayers or set()
    PAIRS = [
        ("dhuhr",   "asr",  "dhuhr_asr",   "Dhuhr + Asr",   "🕌"),
        ("maghrib", "isha", "maghrib_isha", "Maghrib + Isha", "🌙"),
    ]
    result = []

    found_active_pair = False  # only show the first unresolved pair

    for p1, p2, pair_key, label, emoji in PAIRS:
        # Sequential inference: prayer2 prayed → prayer1 was also done → skip pair
        if p2 in prayed or (p1 in prayed and p2 in prayed):
            continue

        p1_adhan = schedule.get(f"{p1}_adhan")
        p1_iqama = schedule.get(f"{p1}_iqama")
        p2_adhan = schedule.get(f"{p2}_adhan")
        p2_iqama = schedule.get(f"{p2}_iqama")

        if not p1_adhan or not p2_adhan:
            continue

        p1_adhan_m = hhmm_to_minutes(p1_adhan)
        p2_adhan_m = hhmm_to_minutes(p2_adhan)

        # Period end for p2
        p2_end_key = _PAIR_PERIOD_END_KEYS.get(p2)
        p2_end_raw = schedule.get(p2_end_key) if p2_end_key else None
        if p2_end_raw:
            p2_end_m = hhmm_to_minutes(p2_end_raw)
            if p2_end_m < p2_adhan_m:
                p2_end_m += 1440  # midnight wrap (Isha → Fajr next day)
        else:
            p2_end_m = p2_adhan_m + 90

        cur = current_min

        # Skip if the entire pair window has passed
        if cur > p2_end_m and p2_end_m > p1_adhan_m:
            continue

        # Don't show a later pair (Maghrib+Isha) while an earlier pair (Dhuhr+Asr) is
        # still unresolved — the user should deal with one pair at a time.
        if found_active_pair:
            continue
        found_active_pair = True

        p1_iqama_fmt = p1_iqama or p1_adhan
        p2_iqama_fmt = p2_iqama or p2_adhan
        options = []

        if cur < p2_adhan_m:
            # ── Taqdeem window: p2 (Asr/Isha) hasn't started yet ──────────────
            # Show Taqdeem only. Takheer becomes relevant once p2 has started.
            if cur < p1_adhan_m:
                # Before p1 adhan — describe the plan, not "now"
                taqdeem_desc = (
                    f"Combine {p1.title()} + {p2.title()} at {p1.title()} time "
                    f"(iqama {p1_iqama_fmt}) — pray both when you reach the mosque."
                )
            else:
                # p1 congregation is active
                taqdeem_desc = (
                    f"Pray {p1.title()} + {p2.title()} together now — "
                    f"{p1.title()} iqama {p1_iqama_fmt}."
                )
            options.append({
                "option_type": "combine_early",
                "label": "Jam' Taqdeem — Combine Early",
                "description": taqdeem_desc,
                "prayers": [p1, p2],
                "combination_label": "Jam' Taqdeem",
                "stops": [],
                "feasible": True,
                "note": f"Pray {p2.title()} early, during {p1.title()} time.",
            })
        else:
            # ── Takheer window: p2 adhan has started, period hasn't ended ─────
            # Taqdeem is no longer possible; show Takheer until p2 period ends.
            p2_iqama_m = hhmm_to_minutes(p2_iqama) if p2_iqama else p2_adhan_m + 15
            congregation_ended = cur >= p2_iqama_m + CONGREGATION_WINDOW_MINUTES
            p2_end_display = schedule.get(_PAIR_PERIOD_END_KEYS.get(p2, ""), p2_iqama_fmt)
            if congregation_ended:
                takheer_desc = (
                    f"Pray {p1.title()} + {p2.title()} together now (solo) — "
                    f"{p2.title()} period ends at {p2_end_display}."
                )
            else:
                takheer_desc = (
                    f"Pray {p1.title()} + {p2.title()} together now — "
                    f"{p2.title()} iqama {p2_iqama_fmt}."
                )
            options.append({
                "option_type": "combine_late",
                "label": "Jam' Ta'kheer — Combine Late",
                "description": takheer_desc,
                "prayers": [p1, p2],
                "combination_label": "Jam' Ta'kheer",
                "stops": [],
                "feasible": True,
                "note": f"Pray {p1.title()} late, during {p2.title()} time.",
            })

        if options:
            result.append({
                "pair": pair_key,
                "label": label,
                "emoji": emoji,
                "options": options,
            })

    return result


# ---------------------------------------------------------------------------
# Prayer period end time
# ---------------------------------------------------------------------------

def get_period_end(prayer: str, schedule: dict) -> Optional[str]:
    """
    Returns the time at which the prayer period ends.
    - Fajr ends at sunrise
    - Dhuhr ends at Asr adhan
    - Asr ends at Maghrib adhan
    - Maghrib ends at Isha adhan
    - Isha ends at Fajr adhan next day (approximated as 01:00 + offset)
    """
    if prayer == "fajr":
        return schedule.get("sunrise")
    elif prayer == "dhuhr":
        return schedule.get("asr_adhan")
    elif prayer == "asr":
        return schedule.get("maghrib_adhan")
    elif prayer == "maghrib":
        return schedule.get("isha_adhan")
    elif prayer == "isha":
        # Isha ends at next day's Fajr adhan — use today's Fajr as the proxy.
        # The midnight wraparound is handled in calculate_catching_status via +24h adjustment.
        return schedule.get("fajr_adhan")
    return None


# ---------------------------------------------------------------------------
# Catching status calculation
# ---------------------------------------------------------------------------

def calculate_catching_status(
    prayer: str,
    schedule: dict,
    current_minutes: int,  # minutes since midnight in mosque's timezone
    travel_minutes: int,
    congregation_window: int = CONGREGATION_WINDOW_MINUTES,
) -> Optional[dict]:
    """
    Determine the catching status for a single prayer.
    Returns None if no data available.
    """
    adhan = schedule.get(f"{prayer}_adhan")
    iqama = schedule.get(f"{prayer}_iqama")
    period_end = get_period_end(prayer, schedule)

    if not adhan:
        return None  # No data at all for this prayer

    adhan_min = hhmm_to_minutes(adhan)
    iqama_min = hhmm_to_minutes(iqama) if iqama else adhan_min + 15
    period_end_min = hhmm_to_minutes(period_end) if period_end else iqama_min + 120

    # Midnight wraparound: isha period end (fajr next day) is numerically less than
    # isha iqama time. Adjust period_end by +24h so comparisons work across midnight.
    if period_end_min < iqama_min:
        period_end_min += 24 * 60  # e.g. fajr=315 → 1755 ("next day 05:15")

    # Isha straddles midnight — three sub-cases based on current time:
    #
    #  A) After Isha adhan (e.g. 8:30 PM+): normal flow, no adjustment needed.
    #
    #  B) After midnight, before Fajr (e.g. 1:30 AM):
    #     We're still in yesterday's Isha window. Bump current by +24h so the
    #     comparison current_minutes < period_end_min (1755) works correctly.
    #     → Isha period ends at today's Fajr (same calendar day since it's after midnight).
    #
    #  C) After Fajr but before tonight's Isha (e.g. 9 AM – 8 PM):
    #     Yesterday's Isha has ended; today's Isha hasn't started.
    #     Return missed immediately — do not fall through to "upcoming".
    if prayer == "isha" and current_minutes < adhan_min:
        fajr_adhan = schedule.get("fajr_adhan")
        fajr_min = hhmm_to_minutes(fajr_adhan) if fajr_adhan else 300
        if current_minutes < fajr_min:
            # Case B: post-midnight carry-over window — still valid Isha time
            current_minutes = current_minutes + 24 * 60
        else:
            # Case C: past Fajr, yesterday's Isha has ended
            return {
                "prayer": prayer,
                "status": "missed_make_up",
                "status_label": STATUS_LABELS["missed_make_up"],
                "message": "Isha has ended — make it up",
                "urgency": "low",
                "adhan_time": adhan,
                "iqama_time": iqama,
                "period_ends_at": period_end,
            }

    arrival_min = current_minutes + travel_minutes
    leave_by_min = iqama_min - travel_minutes

    # Check if prayer period has ended
    if current_minutes > period_end_min:
        return {
            "prayer": prayer,
            "status": "missed_make_up",
            "status_label": STATUS_LABELS["missed_make_up"],
            "message": f"{prayer.title()} has ended — make it up",
            "urgency": "low",
            "adhan_time": adhan,
            "iqama_time": iqama,
            "period_ends_at": period_end,
        }

    # Prayer period hasn't started yet
    if current_minutes < adhan_min:
        minutes_until_adhan = adhan_min - current_minutes
        minutes_until_iqama = iqama_min - current_minutes
        # Determine what the user can still achieve when they arrive
        if arrival_min <= iqama_min:
            leave_by_fmt = minutes_to_hhmm(leave_by_min)
            action_msg = f"leave by {leave_by_fmt} to catch with Imam"
        elif arrival_min <= period_end_min:
            leave_by_solo = period_end_min - travel_minutes
            action_msg = f"leave by {minutes_to_hhmm(leave_by_solo)} to pray solo at mosque"
        else:
            action_msg = "too far to reach before prayer ends"
        return {
            "prayer": prayer,
            "status": "upcoming",
            "status_label": STATUS_LABELS["upcoming"],
            "message": f"{prayer.title()} in {fmt_dur(minutes_until_adhan)} — {action_msg}",
            "urgency": "high" if minutes_until_adhan <= 15 else "normal" if minutes_until_adhan <= 45 else "low",
            "adhan_time": adhan,
            "iqama_time": iqama,
            "minutes_until_iqama": minutes_until_iqama,
            "leave_by": minutes_to_hhmm(leave_by_min),
            "period_ends_at": period_end,
        }

    congregation_end_min = iqama_min + congregation_window

    # Congregation already started — check if user can still arrive in time
    if current_minutes >= iqama_min:
        if arrival_min <= congregation_end_min:
            minutes_in = current_minutes - iqama_min
            return {
                "prayer": prayer,
                "status": "can_catch_with_imam_in_progress",
                "status_label": STATUS_LABELS["can_catch_with_imam_in_progress"],
                "message": f"Congregation started {fmt_dur(minutes_in)} ago — leave now to join",
                "urgency": "high",
                "adhan_time": adhan,
                "iqama_time": iqama,
                "arrival_time": minutes_to_hhmm(arrival_min),
                "minutes_until_iqama": -minutes_in,
                "period_ends_at": period_end,
            }
        # Congregation ended — fall through to solo/missed checks below
    else:
        # Congregation hasn't started yet (current_minutes < iqama_min)
        minutes_until_iqama = iqama_min - current_minutes
        urgency = "high" if minutes_until_iqama <= 15 else "normal"

        if arrival_min <= iqama_min:
            # Can arrive before iqama
            if leave_by_min <= current_minutes:
                message = f"Leave now for {prayer.title()} — Iqama in {fmt_dur(minutes_until_iqama)}"
            else:
                message = f"Can catch {prayer.title()} with Imam — leave by {minutes_to_hhmm(leave_by_min)}"
            return {
                "prayer": prayer,
                "status": "can_catch_with_imam",
                "status_label": STATUS_LABELS["can_catch_with_imam"],
                "message": message,
                "urgency": urgency,
                "adhan_time": adhan,
                "iqama_time": iqama,
                "arrival_time": minutes_to_hhmm(arrival_min),
                "minutes_until_iqama": minutes_until_iqama,
                "leave_by": minutes_to_hhmm(leave_by_min),
                "period_ends_at": period_end,
            }

        if arrival_min <= congregation_end_min:
            # Would arrive after iqama but congregation still active — leave NOW
            mins_late = arrival_min - iqama_min
            return {
                "prayer": prayer,
                "status": "can_catch_with_imam",
                "status_label": STATUS_LABELS["can_catch_with_imam"],
                "message": f"Leave now for {prayer.title()} — arrive {mins_late} min after iqama, congregation still active",
                "urgency": "high",
                "adhan_time": adhan,
                "iqama_time": iqama,
                "arrival_time": minutes_to_hhmm(arrival_min),
                "minutes_until_iqama": minutes_until_iqama,
                "leave_by": minutes_to_hhmm(leave_by_min),
                "period_ends_at": period_end,
            }
        # Would arrive after congregation ends — fall through to solo/missed

    # Asr near Maghrib: praying within 15 min of Maghrib is discouraged (makruh)
    _asr_discouraged_suffix = ""
    if prayer == "asr":
        maghrib = schedule.get("maghrib_adhan")
        if maghrib:
            maghrib_min = hhmm_to_minutes(maghrib)
            if maghrib_min - current_minutes <= 15:
                _asr_discouraged_suffix = " · Note: delaying Asr this close to Maghrib is discouraged — pray as soon as possible"

    # Congregation over (or will be over by the time user arrives) but prayer period still active
    if current_minutes <= period_end_min:
        if arrival_min <= period_end_min:
            # Distinguish: did congregation actually already end, or will it end before user arrives?
            congregation_actually_ended = current_minutes >= congregation_end_min
            # For Isha after midnight: valid but discouraged — note it
            _after_midnight = (
                prayer == "isha"
                and current_minutes >= 24 * 60  # current was bumped by +24h in Case B
            )
            if _after_midnight:
                _solo_msg = (
                    f"Congregation ended for Isha — can pray solo until Fajr ({period_end})"
                    f" · Note: praying after midnight is discouraged"
                )
            elif congregation_actually_ended:
                _solo_msg = f"Congregation ended for {prayer.title()} — can pray solo until {period_end}"
            else:
                # Congregation hasn't ended yet but travel time means user will miss it
                _solo_msg = f"Congregation will be over by the time you arrive — can still pray solo until {period_end}"
            _solo_msg += _asr_discouraged_suffix
            return {
                "prayer": prayer,
                "status": "can_pray_solo_at_mosque",
                "status_label": STATUS_LABELS["can_pray_solo_at_mosque"],
                "message": _solo_msg,
                "urgency": "low",
                "adhan_time": adhan,
                "iqama_time": iqama,
                "period_ends_at": period_end,
            }
        else:
            return {
                "prayer": prayer,
                "status": "pray_at_nearby_location",
                "status_label": STATUS_LABELS["pray_at_nearby_location"],
                "message": f"Cannot reach mosque before {prayer.title()} ends — pray where you are{_asr_discouraged_suffix}",
                "urgency": "normal",
                "adhan_time": adhan,
                "iqama_time": iqama,
                "period_ends_at": period_end,
            }

    return None


def _musafir_active_prayers(prayed: set) -> set:
    """
    In Musafir mode, return the set of prayer names that should be SKIPPED
    in individual catchable_prayers because they're part of a prayed pair.
    Also handles sequential inference (prayer2 prayed → prayer1 also done).
    Fajr is handled individually (not part of a pair).
    """
    skip = set()
    # Dhuhr+Asr pair
    if "asr" in prayed or ("dhuhr" in prayed and "asr" in prayed):
        skip.update({"dhuhr", "asr"})
    elif "dhuhr" in prayed:
        skip.add("dhuhr")  # solo Dhuhr prayed, Asr still pending — show Asr
    # Maghrib+Isha pair
    if "isha" in prayed or ("maghrib" in prayed and "isha" in prayed):
        skip.update({"maghrib", "isha"})
    elif "maghrib" in prayed:
        skip.add("maghrib")  # solo Maghrib prayed, Isha still pending — show Isha
    # Fajr
    if "fajr" in prayed:
        skip.add("fajr")
    return skip


def get_next_catchable(
    schedule: dict,
    current_minutes: int,
    travel_minutes: int,
    congregation_window: int = CONGREGATION_WINDOW_MINUTES,
    travel_mode: bool = False,
    prayed_prayers: Optional[set] = None,
) -> Optional[dict]:
    """Find the most relevant prayer status to show on the mosque card.

    Priority (per design doc):
    1. can_catch_with_imam / can_catch_with_imam_in_progress
    2. upcoming within 2 hours (beats a prior prayer's solo period)
    3. can_pray_solo_at_mosque
    4. pray_at_nearby_location
    5. missed_make_up (only if nothing else)

    In Musafir mode (travel_mode=True), prayers belonging to a prayed pair are skipped
    (the pair is handled by travel_combinations instead).
    """
    priority_order = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
    # In Musafir: sequential inference (Asr prayed → skip Dhuhr+Asr)
    # In Muqeem: skip individually prayed prayers
    if travel_mode:
        skip = _musafir_active_prayers(prayed_prayers or set())
    else:
        skip = set(prayed_prayers) if prayed_prayers else set()
    UPCOMING_WINDOW_MINUTES = 120  # show upcoming if adhan within 2 hours

    STATUS_RANK = {
        "can_catch_with_imam": 0,
        "can_catch_with_imam_in_progress": 0,
        "upcoming": 1,
        "can_pray_solo_at_mosque": 2,
        "pray_at_nearby_location": 3,
        "missed_make_up": 4,
    }

    candidates = []
    for prayer in priority_order:
        if prayer in skip:
            continue
        status = calculate_catching_status(
            prayer, schedule, current_minutes, travel_minutes, congregation_window
        )
        if status is None:
            continue
        # missed_make_up is never a "winner" — only shown when nothing else exists
        if status["status"] == "missed_make_up":
            continue
        # Filter out upcoming prayers that are more than 2 hours away when
        # there are other active options to show — but keep them in the fallback.
        if status["status"] == "upcoming":
            # Use adhan time for the 2-hour window, not iqama (PRAYER_LOGIC_RULES §2)
            adhan_t = status.get("adhan_time")
            minutes_until = (hhmm_to_minutes(adhan_t) - current_minutes) if adhan_t else 9999
            if minutes_until > UPCOMING_WINDOW_MINUTES:
                continue
        candidates.append(status)

    if not candidates:
        # Nothing active or imminent: show the soonest upcoming prayer regardless
        # of how far away it is (dead time — user needs to plan for Dhuhr etc.)
        for prayer in priority_order:
            if prayer in skip:
                continue
            status = calculate_catching_status(
                prayer, schedule, current_minutes, travel_minutes, congregation_window
            )
            if status and status["status"] == "upcoming":
                return status
        # Truly nothing upcoming — return most recent missed prayer
        for prayer in reversed(priority_order):
            if prayer in skip:
                continue
            status = calculate_catching_status(
                prayer, schedule, current_minutes, travel_minutes, congregation_window
            )
            if status and status["status"] == "missed_make_up":
                return status
        return None

    # Return highest-priority candidate; among ties keep the chronologically first
    candidates.sort(key=lambda s: STATUS_RANK.get(s["status"], 99))
    return candidates[0]


def get_catchable_prayers(
    schedule: dict,
    current_minutes: int,
    travel_minutes: int,
    congregation_window: int = CONGREGATION_WINDOW_MINUTES,
    travel_mode: bool = False,
    prayed_prayers: Optional[set] = None,
) -> list[dict]:
    """Return all prayers with an actionable status (for the multi-prayer card UI).

    In Musafir mode (travel_mode=True), prayers belonging to a prayed pair are skipped —
    the pair is shown via travel_combinations instead of individual prayer statuses.
    """
    priority_order = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
    UPCOMING_WINDOW_MINUTES = 120
    if travel_mode:
        skip = _musafir_active_prayers(prayed_prayers or set())
    else:
        skip = set(prayed_prayers) if prayed_prayers else set()

    results = []
    for prayer in priority_order:
        if prayer in skip:
            continue
        status = calculate_catching_status(
            prayer, schedule, current_minutes, travel_minutes, congregation_window
        )
        if status is None:
            continue
        if status["status"] == "missed_make_up":
            continue
        if status["status"] == "upcoming":
            # Use adhan time for the 2-hour window, not iqama (PRAYER_LOGIC_RULES §2)
            adhan_t = status.get("adhan_time")
            minutes_until = (hhmm_to_minutes(adhan_t) - current_minutes) if adhan_t else 9999
            if minutes_until > UPCOMING_WINDOW_MINUTES:
                continue
        results.append(status)

    # If nothing actionable, prefer the soonest upcoming prayer over missed
    if not results:
        for prayer in priority_order:
            if prayer in skip:
                continue
            status = calculate_catching_status(
                prayer, schedule, current_minutes, travel_minutes, congregation_window
            )
            if status and status["status"] == "upcoming":
                return [status]
        for prayer in reversed(priority_order):
            if prayer in skip:
                continue
            status = calculate_catching_status(
                prayer, schedule, current_minutes, travel_minutes, congregation_window
            )
            if status and status["status"] == "missed_make_up":
                return [status]
        return []

    return results


# ---------------------------------------------------------------------------
# Jumu'ah sessions helper
# ---------------------------------------------------------------------------

async def _fetch_jumuah_sessions(db: AsyncSession, mosque_id: str, today) -> list[dict]:
    """
    Return Jumu'ah (Friday prayer) sessions for today.
    Only queries on Fridays (weekday == 4) to avoid unnecessary DB calls.
    """
    from datetime import date as _date
    if isinstance(today, _date) and today.weekday() != 4:
        return []
    result = await db.execute(text("""
        SELECT session_number, khutba_start, prayer_start,
               imam_name, language, special_notes, booking_required, booking_url
        FROM jumuah_sessions
        WHERE mosque_id = CAST(:mosque_id AS uuid) AND valid_date = :date
        ORDER BY session_number ASC
    """), {"mosque_id": mosque_id, "date": today})
    rows = result.mappings().all()
    return [dict(r) for r in rows]


async def _fetch_special_prayers(db: AsyncSession, mosque_id: str, today) -> list[dict]:
    """Return active special prayers (Eid, Taraweeh, etc.) for today or upcoming."""
    result = await db.execute(text("""
        SELECT prayer_type, prayer_time, takbeer_time, doors_open_time,
               session_number, imam_name, language, location_notes, special_notes,
               valid_date::text
        FROM special_prayers
        WHERE mosque_id = CAST(:mosque_id AS uuid)
          AND (valid_date = :date
               OR (valid_from IS NOT NULL AND valid_from <= :date AND valid_until >= :date)
               OR (valid_date >= :date AND valid_date <= :date + 7))
        ORDER BY prayer_type, session_number
    """), {"mosque_id": mosque_id, "date": today})
    rows = result.mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

async def find_nearby_mosques(
    db: AsyncSession,
    lat: float,
    lng: float,
    radius_km: float,
    client_timezone: str,
    current_time: datetime,
    travel_mode: bool = False,
    congregation_window: int = CONGREGATION_WINDOW_MINUTES,
    prayed_prayers: Optional[set] = None,
) -> list[dict]:
    """
    Find mosques within radius_km and calculate prayer catching status for each.
    """
    # PostGIS spatial query
    radius_meters = radius_km * 1000
    query = text("""
        SELECT
            id::text, name, lat, lng, address, city, state, country, timezone,
            phone, website, has_womens_section, wheelchair_accessible,
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            ) as distance_meters
        FROM mosques
        WHERE
            is_active = true
            AND ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius_meters
            )
        ORDER BY distance_meters ASC
        LIMIT 30
    """)

    result = await db.execute(query, {"lat": lat, "lng": lng, "radius_meters": radius_meters})
    rows = result.mappings().all()

    if not rows:
        return []

    # Batch travel times via Mapbox
    mosque_coords = [(row["lat"], row["lng"]) for row in rows]
    mapbox_times = await get_mapbox_travel_times(lat, lng, mosque_coords)

    # Today's date in client timezone (for prayer schedule lookup)
    try:
        client_tz = ZoneInfo(client_timezone)
        local_now = current_time.astimezone(client_tz)
    except Exception:
        local_now = current_time

    today = local_now.date()
    current_minutes_client = local_now.hour * 60 + local_now.minute

    mosques = []
    for i, row in enumerate(rows):
        # Travel time
        if mapbox_times and mapbox_times[i] is not None:
            travel_min = mapbox_times[i]
            travel_source = "mapbox_matrix"
        else:
            travel_min = estimate_travel_minutes(lat, lng, row["lat"], row["lng"])
            travel_source = "estimated"

        # Prayer times in mosque's timezone
        mosque_tz_str = row["timezone"] or client_timezone
        try:
            mosque_tz = ZoneInfo(mosque_tz_str)
            mosque_now = current_time.astimezone(mosque_tz)
        except Exception:
            mosque_now = local_now

        mosque_today = mosque_now.date()
        current_min_mosque = mosque_now.hour * 60 + mosque_now.minute

        # Fetch today's prayer schedule from DB
        sched_result = await db.execute(text("""
            SELECT * FROM prayer_schedules
            WHERE mosque_id = CAST(:mosque_id AS uuid) AND date = :date
            LIMIT 1
        """), {"mosque_id": row["id"], "date": mosque_today})
        sched_row = sched_result.mappings().first()

        schedule = {}
        data_freshness = None

        if sched_row:
            schedule = dict(sched_row)
            if sched_row.get("scraped_at"):
                delta = current_time.replace(tzinfo=None) - sched_row["scraped_at"].replace(tzinfo=None)
                days = delta.days
                data_freshness = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
        else:
            # Fallback: calculate from coordinates
            from pytz import timezone as pytz_tz
            import pytz
            try:
                ptz = pytz.timezone(mosque_tz_str)
                offset_hours = ptz.utcoffset(current_time.replace(tzinfo=None)).total_seconds() / 3600
            except Exception:
                offset_hours = -5  # ET fallback

            calc = calculate_prayer_times(row["lat"], row["lng"], mosque_today, timezone_offset=offset_hours)
            if calc:
                iqama_est = estimate_iqama_times(calc)
                schedule = {**calc, **iqama_est}
            data_freshness = None

        # Build prayer times list for response
        prayers_out = []
        for prayer in PRAYERS:
            prayers_out.append({
                "prayer": prayer,
                "adhan_time": schedule.get(f"{prayer}_adhan"),
                "iqama_time": schedule.get(f"{prayer}_iqama"),
                "adhan_source": SOURCE_LABELS.get(
                    schedule.get(f"{prayer}_adhan_source", ""), schedule.get(f"{prayer}_adhan_source")
                ),
                "iqama_source": SOURCE_LABELS.get(
                    schedule.get(f"{prayer}_iqama_source", ""), schedule.get(f"{prayer}_iqama_source")
                ),
                "adhan_confidence": schedule.get(f"{prayer}_adhan_confidence"),
                "iqama_confidence": schedule.get(f"{prayer}_iqama_confidence"),
                "data_freshness": data_freshness,
            })

        prayed = prayed_prayers or set()

        # Get next catchable prayer (single) and all catchable prayers (list)
        next_catchable = get_next_catchable(
            schedule, current_min_mosque, travel_min, congregation_window,
            travel_mode=travel_mode, prayed_prayers=prayed,
        )
        catchable_prayers = get_catchable_prayers(
            schedule, current_min_mosque, travel_min, congregation_window,
            travel_mode=travel_mode, prayed_prayers=prayed,
        )

        mosque_out = {
            "id": row["id"],
            "name": row["name"],
            "location": {
                "latitude": row["lat"],
                "longitude": row["lng"],
                "address": row["address"],
                "city": row["city"],
                "state": row["state"],
            },
            "timezone": row["timezone"],
            "distance_meters": round(row["distance_meters"]),
            "travel_time_minutes": travel_min,
            "travel_time_source": travel_source,
            "phone": row["phone"],
            "website": row["website"],
            "has_womens_section": row["has_womens_section"],
            "wheelchair_accessible": row["wheelchair_accessible"],
            "next_catchable": next_catchable,
            "catchable_prayers": catchable_prayers,
            "travel_combinations": (
                compute_travel_combinations(schedule, current_min_mosque, prayed_prayers=prayed)
                if travel_mode else []
            ),
            "prayers": prayers_out,
            "sunrise": schedule.get("sunrise"),
            "jumuah_sessions": await _fetch_jumuah_sessions(db, row["id"], mosque_today),
            "denomination": row.get("denomination"),
            "special_prayers": await _fetch_special_prayers(db, row["id"], mosque_today),
        }
        mosques.append(mosque_out)

    return mosques
