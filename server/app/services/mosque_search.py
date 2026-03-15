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
    """Rough offline estimate. Only used when Mapbox is unavailable."""
    d_km = haversine_km(lat1, lng1, lat2, lng2)
    road_km = d_km * 1.4
    minutes = (road_km / 35) * 60 + 3
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


def add_minutes(t: str, delta: int) -> str:
    return minutes_to_hhmm(hhmm_to_minutes(t) + delta)


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
        # Isha ends at next Fajr. Approximate as midnight + some hours.
        # We'll just return None to indicate "long period" — client handles
        fajr = schedule.get("fajr_adhan")
        if fajr:
            # Add 24h cycle approximation: Fajr is typically 05:00-06:00
            # Isha period ends when next Fajr starts. We approximate as +6h after Isha iqama.
            isha_iqama = schedule.get("isha_iqama")
            if isha_iqama:
                return add_minutes(isha_iqama, 360)  # +6h rough bound
        return None
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
        minutes_until = adhan_min - current_minutes
        return {
            "prayer": prayer,
            "status": "upcoming",
            "status_label": STATUS_LABELS["upcoming"],
            "message": f"{prayer.title()} in {minutes_until} min",
            "urgency": "low",
            "adhan_time": adhan,
            "iqama_time": iqama,
            "minutes_until_iqama": iqama_min - current_minutes,
            "period_ends_at": period_end,
        }

    # Arrives at or before iqama
    if arrival_min <= iqama_min:
        minutes_until = iqama_min - current_minutes
        urgency = "high" if minutes_until <= 15 else "normal"
        if leave_by_min <= current_minutes:
            # Must leave now or already past leave-by time
            message = f"Leave now for {prayer.title()} — Iqama in {iqama_min - current_minutes} min"
        else:
            leave_by_fmt = minutes_to_hhmm(leave_by_min)
            message = f"Can catch {prayer.title()} with Imam — leave by {leave_by_fmt}"
        return {
            "prayer": prayer,
            "status": "can_catch_with_imam",
            "status_label": STATUS_LABELS["can_catch_with_imam"],
            "message": message,
            "urgency": urgency,
            "adhan_time": adhan,
            "iqama_time": iqama,
            "arrival_time": minutes_to_hhmm(arrival_min),
            "minutes_until_iqama": max(0, iqama_min - current_minutes),
            "leave_by": minutes_to_hhmm(leave_by_min),
            "period_ends_at": period_end,
        }

    # Arrives during congregation window
    congregation_end_min = iqama_min + congregation_window
    if arrival_min <= congregation_end_min:
        minutes_in = current_minutes - iqama_min
        urgency = "high"
        return {
            "prayer": prayer,
            "status": "can_catch_with_imam_in_progress",
            "status_label": STATUS_LABELS["can_catch_with_imam_in_progress"],
            "message": f"Congregation started {minutes_in} min ago — you can still join",
            "urgency": urgency,
            "adhan_time": adhan,
            "iqama_time": iqama,
            "arrival_time": minutes_to_hhmm(arrival_min),
            "minutes_until_iqama": -(current_minutes - iqama_min),
            "period_ends_at": period_end,
        }

    # Congregation over but prayer period still active
    if current_minutes <= period_end_min:
        if arrival_min <= period_end_min:
            return {
                "prayer": prayer,
                "status": "can_pray_solo_at_mosque",
                "status_label": STATUS_LABELS["can_pray_solo_at_mosque"],
                "message": f"Congregation ended — can pray solo, period active until {period_end}",
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
                "message": f"Cannot reach mosque before {prayer.title()} ends — pray where you are",
                "urgency": "normal",
                "adhan_time": adhan,
                "iqama_time": iqama,
                "period_ends_at": period_end,
            }

    return None


def get_next_catchable(
    schedule: dict,
    current_minutes: int,
    travel_minutes: int,
    congregation_window: int = CONGREGATION_WINDOW_MINUTES,
) -> Optional[dict]:
    """Find the most relevant prayer status to show on the mosque card."""
    # Check in-progress or upcoming prayers first
    priority_order = ["fajr", "dhuhr", "asr", "maghrib", "isha"]

    best = None
    for prayer in priority_order:
        status = calculate_catching_status(
            prayer, schedule, current_minutes, travel_minutes, congregation_window
        )
        if status is None:
            continue
        if status["status"] in ("missed_make_up",):
            continue  # Skip missed ones for the "next catchable" display
        best = status
        # Stop at the first non-missed prayer
        if status["status"] != "missed_make_up":
            break

    # If all are missed, return the last one
    if best is None:
        for prayer in reversed(priority_order):
            status = calculate_catching_status(
                prayer, schedule, current_minutes, travel_minutes, congregation_window
            )
            if status:
                best = status
                break

    return best


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
                delta = current_time - sched_row["scraped_at"].replace(tzinfo=None)
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

        # Get next catchable prayer
        next_catchable = get_next_catchable(
            schedule, current_min_mosque, travel_min, congregation_window
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
            "travel_combinations": [],
            "prayers": prayers_out,
            "sunrise": schedule.get("sunrise"),
            "jumuah_sessions": [],  # TODO: fetch from jumuah_sessions table
        }
        mosques.append(mosque_out)

    return mosques
