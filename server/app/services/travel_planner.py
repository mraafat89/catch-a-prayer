"""
Route-based Travel Prayer Planner
==================================
Given origin + destination, builds a structured prayer plan for the journey.

Algorithm:
1. Get Mapbox Directions route (with steps for time-tagged waypoints)
2. Build time-tagged checkpoints along route from step maneuver locations
3. Sample waypoints every 30 min along the route; find mosques within 25km of each
4. For each mosque, compute: estimated_pass_time + detour_minutes
5. For each prayer pair (Dhuhr+Asr, Maghrib+Isha), build options:
   - combine_early: pray both during first prayer's period (Jam' Taqdeem)
   - combine_late: pray both during second prayer's period (Jam' Ta'kheer)
   - separate: different mosques for each prayer
   - pray_before: both prayers active at departure
   - at_destination: pray near destination
"""
from __future__ import annotations

import asyncio
import math
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.config import get_settings
from app.services.mosque_search import (
    hhmm_to_minutes, minutes_to_hhmm,
    haversine_km, estimate_travel_minutes,
    CONGREGATION_WINDOW_MINUTES
)
from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times

logger = logging.getLogger(__name__)
settings = get_settings()

DETOUR_OVERHEAD_MINUTES = 15      # time to stop, pray, re-enter route
ROUTE_CORRIDOR_KM = 25            # initial search radius around each route waypoint
PROGRESSIVE_RADII = [25, 50, 75]  # progressive expansion when no mosque found
WAYPOINT_INTERVAL_MINUTES = 30    # sample route waypoints every 30 minutes
MAX_DETOUR_MINUTES = 60           # skip mosques requiring > 60 min total detour
HIGHWAY_SPEED_KMH = 60            # speed used for detour estimate (highway avg)
MAX_TRIP_HOURS = 72               # max trip duration (3 days)
PRAYERS = ["fajr", "dhuhr", "asr", "maghrib", "isha"]


def validate_trip_duration(departure_dt: datetime, arrival_dt: datetime) -> tuple[bool, str]:
    """Validate trip duration. Returns (is_valid, error_message)."""
    duration = arrival_dt - departure_dt
    hours = duration.total_seconds() / 3600
    if hours > MAX_TRIP_HOURS:
        return False, (
            f"This trip is longer than 3 days ({hours:.0f} hours). "
            "Please break it into shorter segments for accurate prayer planning."
        )
    if hours <= 0:
        return False, "Arrival must be after departure."
    return True, ""


def enumerate_trip_prayers(
    departure_dt: datetime,
    arrival_dt: datetime,
    schedules_by_date: dict,
) -> list[dict]:
    """
    Enumerate all prayers that fall within a multi-day trip window.
    Returns list of {prayer, date, adhan_time, iqama_time, day_number}.
    Each calendar day uses its own prayer schedule.
    """
    results = []
    current_date = departure_dt.date()
    end_date = arrival_dt.date()
    day_number = 1

    while current_date <= end_date:
        schedule = schedules_by_date.get(current_date, {})
        for prayer in PRAYERS:
            adhan = schedule.get(f"{prayer}_adhan")
            if not adhan:
                continue
            adhan_min = hhmm_to_minutes(adhan)
            prayer_dt = datetime(
                current_date.year, current_date.month, current_date.day,
                adhan_min // 60, adhan_min % 60,
                tzinfo=departure_dt.tzinfo,
            )
            if departure_dt <= prayer_dt <= arrival_dt:
                results.append({
                    "prayer": prayer,
                    "date": current_date,
                    "adhan_time": adhan,
                    "iqama_time": schedule.get(f"{prayer}_iqama"),
                    "day_number": day_number,
                })
        current_date += timedelta(days=1)
        day_number += 1

    return results


def fmt_duration(minutes: int) -> str:
    """Convert minutes to a human-friendly string. e.g. 352 → '5h 52min', 1500 → '1 day 1h'"""
    minutes = max(0, int(minutes))
    days = minutes // (24 * 60)
    remaining = minutes % (24 * 60)
    hours = remaining // 60
    mins = remaining % 60
    if days > 0:
        parts = [f"{days} day{'s' if days > 1 else ''}"]
        if hours:
            parts.append(f"{hours}h")
        if mins:
            parts.append(f"{mins}min")
        return " ".join(parts)
    if hours > 0:
        return f"{hours}h {mins}min" if mins else f"{hours}h"
    return f"{mins}min"


# ---------------------------------------------------------------------------
# Routing helpers (Mapbox primary, OSRM free fallback)
# ---------------------------------------------------------------------------

_OSM_HEADERS = {"User-Agent": "CatchAPrayer/1.0 (contact@catchaprayer.app)"}


async def get_mapbox_route(
    origin_lat: float, origin_lng: float,
    dest_lat: float, dest_lng: float,
    waypoints: Optional[list[dict]] = None,
) -> Optional[dict]:
    """Return a route dict with legs/steps. Supports intermediate waypoints.
    Tries Mapbox first, falls back to OSRM."""
    # Build coordinate string: origin;wp1;wp2;...;destination
    coords = [(origin_lng, origin_lat)]
    for wp in (waypoints or []):
        coords.append((wp["lng"], wp["lat"]))
    coords.append((dest_lng, dest_lat))
    coord_str = ";".join(f"{lng},{lat}" for lng, lat in coords)

    # --- Mapbox (if key configured) ---
    if settings.mapbox_api_key:
        try:
            url = f"https://api.mapbox.com/directions/v5/mapbox/driving/{coord_str}"
            params = {
                "access_token": settings.mapbox_api_key,
                "geometries": "geojson",
                "overview": "full",
                "steps": "true",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            routes = data.get("routes")
            if routes:
                return routes[0]
        except Exception as e:
            logger.warning(f"Mapbox Directions failed, falling back to OSRM: {e}")

    # --- OSRM public router (free, no key needed, same response format) ---
    osrm_base = f"https://router.project-osrm.org/route/v1/driving/{coord_str}"
    osrm_attempts = [
        (osrm_base, True),
        (osrm_base, False),
        (osrm_base.replace("https://", "http://"), True),
    ]
    for url, verify_ssl in osrm_attempts:
        try:
            params = {"overview": "full", "steps": "true", "geometries": "geojson"}
            async with httpx.AsyncClient(timeout=20, verify=verify_ssl) as client:
                resp = await client.get(url, params=params, headers=_OSM_HEADERS)
                resp.raise_for_status()
                data = resp.json()
            routes = data.get("routes")
            if routes:
                logger.info(f"OSRM routing succeeded via {url[:8]}... verify={verify_ssl}")
                return routes[0]
        except Exception as e:
            logger.warning(f"OSRM attempt failed ({url[:8]}... verify={verify_ssl}): {e}")

    return None


# ---------------------------------------------------------------------------
# Geocoding helpers (Photon primary, Mapbox optional enhancement)
# ---------------------------------------------------------------------------

async def geocode_query(query: str) -> list[dict]:
    """Return up to 5 geocoded suggestions using Photon (free OSM) or Mapbox."""
    # --- Mapbox (if key configured — more precise for POIs) ---
    if settings.mapbox_api_key:
        try:
            import urllib.parse
            encoded = urllib.parse.quote(query)
            url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{encoded}.json"
            params = {
                "access_token": settings.mapbox_api_key,
                "country": "us,ca",
                "limit": 5,
                "types": "place,address,poi",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            results = []
            for feat in data.get("features", []):
                coords = feat.get("center", [])
                if len(coords) == 2:
                    results.append({
                        "place_name": feat.get("place_name", ""),
                        "lat": coords[1],
                        "lng": coords[0],
                    })
            if results:
                return results
        except Exception as e:
            logger.warning(f"Mapbox geocoding failed, falling back to Photon: {e}")

    # --- Photon (free, no key, OpenStreetMap data, designed for autocomplete) ---
    try:
        params = {
            "q": query,
            "limit": 5,
            "lang": "en",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://photon.komoot.io/api/",
                params=params,
                headers=_OSM_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()

        def in_north_america(lat: float, lng: float) -> bool:
            return 24 <= lat <= 73 and -168 <= lng <= -52

        results = []
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            coords = feat.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            lng, lat = coords[0], coords[1]
            if not in_north_america(lat, lng):
                continue

            # Build a readable display name
            name = props.get("name", "")
            city = props.get("city", "") or props.get("county", "")
            state = props.get("state", "")
            parts = [p for p in [name, city if city != name else "", state] if p]
            place_name = ", ".join(parts)
            if not place_name:
                continue
            results.append({"place_name": place_name, "lat": lat, "lng": lng})
            if len(results) >= 5:
                break

        return results
    except Exception as e:
        logger.warning(f"Photon geocoding failed: {e}")
        return []


async def reverse_geocode(lat: float, lng: float) -> Optional[str]:
    """Reverse-geocode coordinates to a short human-readable address via Nominatim."""
    try:
        params = {
            "lat": lat,
            "lon": lng,
            "format": "jsonv2",
            "zoom": 16,
            "addressdetails": 1,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params=params,
                headers=_OSM_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()

        addr = data.get("address", {})
        # Build a short label: "Road, City, State" or fallback to display_name
        parts = []
        road = addr.get("road") or addr.get("pedestrian") or addr.get("footway")
        city = (addr.get("city") or addr.get("town") or addr.get("village")
                or addr.get("suburb") or addr.get("county"))
        state = addr.get("state")
        if road:
            parts.append(road)
        if city:
            parts.append(city)
        if state:
            parts.append(state)
        if parts:
            return ", ".join(parts)
        return data.get("display_name", "").split(",")[0]
    except Exception as e:
        logger.warning(f"Reverse geocoding failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Route checkpoint builder
# ---------------------------------------------------------------------------

def build_checkpoints(route: dict, departure_dt: datetime) -> list[dict]:
    """
    Build a list of {lat, lng, time, cumulative_minutes} checkpoints along the route.

    Uses the full route geometry (overview=full) with time interpolated by cumulative
    distance, giving dense coverage of the entire route — not just turn/maneuver locations.
    This ensures mosques along long straight highway stretches are found and timed correctly.

    Points within 0.1 km of the previous kept point are skipped (deduplication).
    """
    total_duration = route.get("duration", 0)
    coords = route.get("geometry", {}).get("coordinates", [])

    if coords and len(coords) >= 2:
        # Compute cumulative haversine distance at each geometry point
        cum_dist: list[float] = [0.0]
        for i in range(1, len(coords)):
            lng1, lat1 = coords[i - 1]
            lng2, lat2 = coords[i]
            cum_dist.append(cum_dist[-1] + haversine_km(lat1, lng1, lat2, lng2))
        total_dist = cum_dist[-1] or 1.0

        checkpoints: list[dict] = []
        last_kept_dist = -1.0
        for i, (lng, lat) in enumerate(coords):
            d = cum_dist[i]
            if d - last_kept_dist < 0.1 and i != len(coords) - 1:
                continue  # skip points within 100 m of the last kept one
            last_kept_dist = d
            t_frac = d / total_dist
            t = departure_dt + timedelta(seconds=t_frac * total_duration)
            checkpoints.append({
                "lat": lat,
                "lng": lng,
                "time": t,
                "cumulative_minutes": t_frac * total_duration / 60,
            })
        return checkpoints

    # Fallback: step maneuver locations (used when geometry is absent)
    checkpoints = []
    cumulative_seconds = 0.0
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            loc = step.get("maneuver", {}).get("location", [])
            if len(loc) == 2:
                t = departure_dt + timedelta(seconds=cumulative_seconds)
                checkpoints.append({
                    "lat": loc[1],
                    "lng": loc[0],
                    "time": t,
                    "cumulative_minutes": cumulative_seconds / 60,
                })
            cumulative_seconds += step.get("duration", 0)
    return checkpoints


def nearest_checkpoint(mosque_lat: float, mosque_lng: float, checkpoints: list[dict]) -> tuple:
    """Find the route checkpoint nearest to a mosque."""
    best = None
    best_dist = float("inf")
    for cp in checkpoints:
        d = haversine_km(mosque_lat, mosque_lng, cp["lat"], cp["lng"])
        if d < best_dist:
            best_dist = d
            best = cp
    return best, best_dist


# ---------------------------------------------------------------------------
# DB: find mosques along route corridor (per-waypoint radius search)
# ---------------------------------------------------------------------------

def sample_route_waypoints(checkpoints: list[dict], interval_minutes: float = 30.0) -> list[dict]:
    """
    Sample checkpoints at regular time intervals along the route.
    Always includes the first and last checkpoint.
    A 6-hour trip → ~13 waypoints; a 15-hour trip → ~31 waypoints.
    """
    if not checkpoints:
        return []
    waypoints = [checkpoints[0]]
    next_target = checkpoints[0]["cumulative_minutes"] + interval_minutes
    for cp in checkpoints[1:]:
        if cp["cumulative_minutes"] >= next_target:
            waypoints.append(cp)
            next_target = cp["cumulative_minutes"] + interval_minutes
    if waypoints[-1] is not checkpoints[-1]:
        waypoints.append(checkpoints[-1])
    return waypoints


async def find_route_mosques(
    db: AsyncSession,
    checkpoints: list[dict],
    departure_dt: datetime,
    corridor_km: float = ROUTE_CORRIDOR_KM,
) -> list[dict]:
    """
    Find mosques within corridor_km of the route.
    Samples search centres every WAYPOINT_INTERVAL_MINUTES along the route,
    then searches a radius around each centre — giving uniform corridor coverage
    without the false positives of a single bounding box on diagonal routes.
    """
    if not checkpoints:
        return []

    search_wps = sample_route_waypoints(checkpoints, WAYPOINT_INTERVAL_MINUTES)
    lat_buf = corridor_km / 111.0
    lng_buf = corridor_km / 85.0  # conservative

    # Build per-waypoint bbox OR clauses.
    # Values are computed floats from route geometry (not user input) — safe to inline.
    or_clauses = " OR ".join(
        f"(lat BETWEEN {w['lat'] - lat_buf:.6f} AND {w['lat'] + lat_buf:.6f} "
        f"AND lng BETWEEN {w['lng'] - lng_buf:.6f} AND {w['lng'] + lng_buf:.6f})"
        for w in search_wps
    )
    result = await db.execute(text(f"""
        SELECT DISTINCT ON (id) id::text, name, lat, lng, address, city, state, timezone, google_place_id
        FROM mosques
        WHERE is_active = true AND ({or_clauses})
        LIMIT 2000
    """))
    rows = result.mappings().all()
    logger.info(
        f"find_route_mosques: {len(checkpoints)} checkpoints → "
        f"{len(search_wps)} search waypoints → {len(rows)} mosques in corridor"
    )

    route_mosques = []

    for row in rows:
        cp, dist_km = nearest_checkpoint(row["lat"], row["lng"], checkpoints)
        # Detour: drive to mosque + prayer overhead + drive back
        # Use highway speed (faster than the offline estimate_travel_minutes default)
        dist_km = haversine_km(cp["lat"], cp["lng"], row["lat"], row["lng"])
        road_km = dist_km * 1.3  # road factor
        drive_one_way = max(1, round((road_km / HIGHWAY_SPEED_KMH) * 60 + 2))
        detour_min = drive_one_way * 2 + DETOUR_OVERHEAD_MINUTES

        if detour_min > MAX_DETOUR_MINUTES:
            continue

        estimated_pass_time = cp["time"]
        estimated_arrival = estimated_pass_time + timedelta(minutes=drive_one_way)
        minutes_into_trip = cp["cumulative_minutes"] + drive_one_way

        # Convert arrival to mosque's local timezone — critical for timezone crossings
        # (e.g. driving Pacific → Mountain adds 1 hour; overnight trips cross a date boundary)
        tz_str = row["timezone"] or "UTC"
        try:
            tz = ZoneInfo(tz_str)
            local_pass = estimated_arrival.astimezone(tz)
        except Exception:
            local_pass = estimated_arrival

        # Use the mosque-local DATE at time-of-arrival, not departure date
        local_date = local_pass.date()

        sched_result = await db.execute(text("""
            SELECT * FROM prayer_schedules
            WHERE mosque_id = CAST(:mid AS uuid) AND date = :date LIMIT 1
        """), {"mid": row["id"], "date": local_date})
        sched_row = sched_result.mappings().first()

        schedule = {}
        if sched_row:
            schedule = dict(sched_row)
        else:
            try:
                import pytz
                ptz = pytz.timezone(tz_str)
                offset = ptz.utcoffset(estimated_arrival.replace(tzinfo=None)).total_seconds() / 3600
            except Exception:
                offset = -5
            calc = calculate_prayer_times(row["lat"], row["lng"], local_date, timezone_offset=offset)
            if calc:
                schedule = {**calc, **estimate_iqama_times(calc)}

        route_mosques.append({
            "id": row["id"],
            "name": row["name"],
            "lat": row["lat"],
            "lng": row["lng"],
            "address": row["address"],
            "city": row["city"],
            "state": row["state"],
            "google_place_id": row.get("google_place_id"),
            "detour_minutes": round(detour_min),
            "estimated_arrival": estimated_arrival,
            "minutes_into_trip": round(minutes_into_trip),
            "local_arrival_minutes": local_pass.hour * 60 + local_pass.minute,
            "local_arrival_time_fmt": f"{local_pass.hour:02d}:{local_pass.minute:02d}",
            "schedule": schedule,
        })

    logger.info(f"find_route_mosques: {len(route_mosques)}/{len(rows)} mosques pass detour filter")
    return route_mosques


async def fetch_anchor_mosques(
    db: AsyncSession,
    lat: float, lng: float,
    tz_str: str,
    anchor_dt: datetime,
    radius_km: float = 10.0,
) -> list[dict]:
    """
    Find mosques within radius_km of an anchor point (origin or destination).
    Returns mosque dicts in the same format as route_mosques entries, with
    local_arrival_minutes set to anchor_dt converted to each mosque's timezone.
    Used by pray_before (origin anchor) and at_destination (dest anchor).
    """
    lat_buf = radius_km / 111.0
    lng_buf = radius_km / 85.0
    result = await db.execute(text("""
        SELECT id::text, name, lat, lng, address, city, state, timezone, google_place_id
        FROM mosques
        WHERE is_active = true
          AND lat BETWEEN :lat_min AND :lat_max
          AND lng BETWEEN :lng_min AND :lng_max
        LIMIT 50
    """), {
        "lat_min": lat - lat_buf, "lat_max": lat + lat_buf,
        "lng_min": lng - lng_buf, "lng_max": lng + lng_buf,
    })
    rows = result.mappings().all()

    mosques = []
    for row in rows:
        dist = haversine_km(lat, lng, row["lat"], row["lng"])
        if dist > radius_km:
            continue

        tz_str_m = row["timezone"] or tz_str
        try:
            tz = ZoneInfo(tz_str_m)
            local_pass = anchor_dt.astimezone(tz)
        except Exception:
            local_pass = anchor_dt

        local_date = local_pass.date()
        sched_result = await db.execute(text("""
            SELECT * FROM prayer_schedules
            WHERE mosque_id = CAST(:mid AS uuid) AND date = :date LIMIT 1
        """), {"mid": row["id"], "date": local_date})
        sched_row = sched_result.mappings().first()

        schedule: dict = {}
        if sched_row:
            schedule = dict(sched_row)
        else:
            try:
                import pytz
                ptz = pytz.timezone(tz_str_m)
                offset = ptz.utcoffset(anchor_dt.replace(tzinfo=None)).total_seconds() / 3600
            except Exception:
                offset = -5
            calc = calculate_prayer_times(row["lat"], row["lng"], local_date, timezone_offset=offset)
            if calc:
                schedule = {**calc, **estimate_iqama_times(calc)}

        # Compute actual detour from anchor point to this mosque (round trip)
        dist_km = haversine_km(lat, lng, row["lat"], row["lng"])
        detour_est = max(1, round(dist_km * 2 * 1.3 / 60 * 60))  # round trip, road factor 1.3, 60 km/h

        mosques.append({
            "id": row["id"],
            "name": row["name"],
            "lat": row["lat"],
            "lng": row["lng"],
            "address": row["address"],
            "city": row["city"],
            "state": row["state"],
            "google_place_id": row.get("google_place_id"),
            "detour_minutes": detour_est,
            "minutes_into_trip": 0,
            "local_arrival_minutes": local_pass.hour * 60 + local_pass.minute,
            "local_arrival_time_fmt": f"{local_pass.hour:02d}:{local_pass.minute:02d}",
            "schedule": schedule,
        })

    return mosques


# ---------------------------------------------------------------------------
# Prayer status at a mosque given arrival time
# ---------------------------------------------------------------------------

def prayer_status_at_arrival(prayer: str, schedule: dict, arrival_minutes: int) -> Optional[dict]:
    """
    Returns status dict if the prayer is catchable at this arrival time, else None.
    Status: 'can_catch_with_imam' or 'can_pray_solo_at_mosque'
    """
    adhan = schedule.get(f"{prayer}_adhan")
    iqama = schedule.get(f"{prayer}_iqama")
    if not adhan:
        return None

    adhan_min = hhmm_to_minutes(adhan)
    iqama_min = hhmm_to_minutes(iqama) if iqama else adhan_min + 15
    cong_end = iqama_min + CONGREGATION_WINDOW_MINUTES

    # Period end
    PERIOD_END_MAP = {
        "fajr": "sunrise",
        "dhuhr": "asr_adhan",
        "asr": "maghrib_adhan",
        "maghrib": "isha_adhan",
        "isha": "fajr_adhan",
    }
    period_end_key = PERIOD_END_MAP.get(prayer)
    period_end_raw = schedule.get(period_end_key) if period_end_key else None
    period_end_min = hhmm_to_minutes(period_end_raw) if period_end_raw else iqama_min + 360
    if period_end_min < iqama_min:
        period_end_min += 1440  # midnight wrap (e.g. Isha → next Fajr)

    # Midnight-wrap for arrival: if arrival is after midnight (small minutes value)
    # and the prayer window spans midnight, shift arrival by +1440 so the comparison works.
    # e.g. arrival at 00:30 (=30 min) is within Isha window 20:30–05:30 (=1230–1770).
    if arrival_minutes < adhan_min and (arrival_minutes + 1440) <= period_end_min:
        arrival_minutes += 1440

    if arrival_minutes < adhan_min:
        return None  # prayer hasn't started
    if arrival_minutes >= period_end_min:
        return None  # prayer period has ended (>= because period ends exactly at the next prayer's adhan)

    if arrival_minutes <= cong_end:
        return {
            "status": "can_catch_with_imam",
            "adhan_time": adhan,
            "iqama_time": iqama,
        }
    if arrival_minutes <= period_end_min:
        return {
            "status": "can_pray_solo_at_mosque",
            "adhan_time": adhan,
            "iqama_time": iqama,
        }
    return None


# ---------------------------------------------------------------------------
# Build options for a prayer pair
# ---------------------------------------------------------------------------

def _make_stop(m: dict, prayer: str, status_info: dict) -> dict:
    return {
        "mosque_id": m["id"],
        "mosque_name": m["name"],
        "mosque_lat": m["lat"],
        "mosque_lng": m["lng"],
        "mosque_address": f"{m.get('city') or ''}, {m.get('state') or ''}".strip(", ") or m.get("address"),
        "google_place_id": m.get("google_place_id"),
        "prayer": prayer,
        "estimated_arrival_time": m["local_arrival_time_fmt"],
        "minutes_into_trip": m["minutes_into_trip"],
        "detour_minutes": m["detour_minutes"],
        "status": status_info["status"],
        "iqama_time": status_info.get("iqama_time"),
        "adhan_time": status_info.get("adhan_time"),
    }


def _find_nearby_mosque(
    lat: float, lng: float,
    route_mosques: list[dict],
    prayer: str,
    time_min: int,
    anchor_mosques: Optional[list[dict]] = None,
) -> Optional[dict]:
    """
    Find the nearest mosque to (lat, lng) that supports `prayer` at arrival time.
    Uses each mosque's own local_arrival_minutes (timezone-correct) rather than
    the caller-supplied time_min, which may be in a different timezone.
    Falls back to time_min only if local_arrival_minutes is absent.
    Searches anchor_mosques (e.g. pre-fetched near origin/destination) first,
    merged with route_mosques, deduplicated by id, sorted by distance.
    """
    pool = list(anchor_mosques or []) + list(route_mosques)
    seen: set[str] = set()
    deduped = []
    for m in sorted(pool, key=lambda m: haversine_km(lat, lng, m["lat"], m["lng"])):
        if m["id"] not in seen:
            seen.add(m["id"])
            deduped.append(m)
    for m in deduped[:15]:
        arrival = m.get("local_arrival_minutes", time_min)
        s = prayer_status_at_arrival(prayer, m["schedule"], arrival)
        if s:
            return m
    return None


def _build_solo_plan(
    prayer: str,
    schedule: dict,
    route_mosques: list[dict],
    departure_dt: datetime,
    arrival_dt: datetime,
    dest_schedule: dict,
    timezone_str: str,
    origin_lat: float = 0.0,
    origin_lng: float = 0.0,
    dest_lat: float = 0.0,
    dest_lng: float = 0.0,
    origin_mosques: Optional[list[dict]] = None,
    dest_mosques: Optional[list[dict]] = None,
    dest_tz_str: Optional[str] = None,
) -> dict:
    """Build a single-prayer plan (no combining) for Muqeem mode or a solo remaining prayer."""
    pair_labels_solo = {
        "fajr":    ("fajr",    "Fajr",    "🌅"),
        "dhuhr":   ("dhuhr",   "Dhuhr",   "🕌"),
        "asr":     ("asr",     "Asr",     "🕌"),
        "maghrib": ("maghrib", "Maghrib", "🌙"),
        "isha":    ("isha",    "Isha",    "🌙"),
    }
    pair_key, label, emoji = pair_labels_solo.get(prayer, (prayer, prayer.title(), "🕌"))

    try:
        tz = ZoneInfo(timezone_str)
        dep_local = departure_dt.astimezone(tz)
        arr_local = arrival_dt.astimezone(tz)
    except Exception:
        dep_local = departure_dt
        arr_local = arrival_dt

    dep_min = dep_local.hour * 60 + dep_local.minute
    arr_min = arr_local.hour * 60 + arr_local.minute
    dep_fmt = f"{dep_local.hour:02d}:{dep_local.minute:02d}"

    # Arrival time in the DESTINATION's timezone — used for dest_schedule checks.
    # dest_schedule times are in destination local time, so comparing against origin
    # arr_min would be wrong for cross-timezone trips (e.g. LA→NY 3hr offset).
    try:
        _dest_tz = ZoneInfo(dest_tz_str or timezone_str)
        _arr_dest = arrival_dt.astimezone(_dest_tz)
        arr_min_dest = _arr_dest.hour * 60 + _arr_dest.minute
    except Exception:
        arr_min_dest = arr_min

    # Deadline for no_option fallback
    _DEADLINE_KEYS = {"fajr": "sunrise", "dhuhr": "asr_adhan", "asr": "maghrib_adhan",
                      "maghrib": "isha_adhan", "isha": "fajr_adhan"}
    _deadline_key = _DEADLINE_KEYS.get(prayer)
    _deadline_time = (schedule.get(_deadline_key) or dest_schedule.get(_deadline_key)) if _deadline_key else None

    options = []

    # Pray before leaving — use anchor mosques near origin for best results
    s = prayer_status_at_arrival(prayer, schedule, dep_min)
    if s:
        origin_mosque = _find_nearby_mosque(origin_lat, origin_lng, route_mosques, prayer, dep_min,
                                            anchor_mosques=origin_mosques)
        if origin_mosque:
            om_status = prayer_status_at_arrival(prayer, origin_mosque["schedule"], dep_min) or s
            pre_stop = dict(_make_stop(origin_mosque, prayer, om_status))
            pre_stop["minutes_into_trip"] = 0
            pre_stop["detour_minutes"] = 0
            pre_stop["estimated_arrival_time"] = dep_fmt
            origin_stops = [pre_stop]
            origin_note = f"{origin_mosque['name']} is near your departure point."
        else:
            origin_stops = []
            origin_note = "No mosque found near origin — pray at a clean spot before departing."
        options.append({
            "option_type": "pray_before",
            "label": f"Pray {label} Before Leaving",
            "description": f"{label} is currently active — pray before you depart.",
            "prayers": [prayer],
            "combination_label": None,
            "stops": origin_stops,
            "feasible": True,
            "note": origin_note,
        })

    # Best mosque en route
    for m in sorted(route_mosques, key=lambda x: x["minutes_into_trip"]):
        si = prayer_status_at_arrival(prayer, m["schedule"], m["local_arrival_minutes"])
        if si:
            options.append({
                "option_type": "solo_stop",
                "label": f"Stop for {label}",
                "description": f"Stop at {m['name']} ({m['detour_minutes']} min detour) to pray {label}.",
                "prayers": [prayer],
                "combination_label": None,
                "stops": [_make_stop(m, prayer, si)],
                "feasible": True,
                "note": f"~{fmt_duration(m['minutes_into_trip'])} into your trip",
            })
            break

    # At destination — use anchor mosques near destination for best results
    s_dest = prayer_status_at_arrival(prayer, dest_schedule, arr_min_dest)
    if s_dest:
        dest_mosque = _find_nearby_mosque(dest_lat, dest_lng, route_mosques, prayer, arr_min_dest,
                                          anchor_mosques=dest_mosques)
        if dest_mosque:
            dm_status = prayer_status_at_arrival(prayer, dest_mosque["schedule"], dest_mosque["local_arrival_minutes"]) or s_dest
            dest_stops = [_make_stop(dest_mosque, prayer, dm_status)]
            dest_note = f"{dest_mosque['name']} is near your destination."
        else:
            dest_stops = []
            dest_note = "No mosque confirmed near destination — find a mosque on arrival."
        options.append({
            "option_type": "at_destination",
            "label": f"Pray {label} Near Destination",
            "description": f"{label} is still active when you arrive.",
            "prayers": [prayer],
            "combination_label": None,
            "stops": dest_stops,
            "feasible": True,
            "note": dest_note,
        })

    if not options:
        deadline_str = f" before {_deadline_time}" if _deadline_time else ""
        options.append({
            "option_type": "no_option",
            "label": f"{label} — No Mosque Found",
            "description": f"No mosque found. Pray {label} at a clean rest stop{deadline_str}.",
            "prayers": [prayer],
            "combination_label": None,
            "stops": [],
            "feasible": False,
            "note": f"Pray at a clean rest stop{deadline_str}.",
        })

    return {"pair": pair_key, "label": label, "emoji": emoji, "options": options}


def build_combination_plan(
    prayer1: str, prayer2: str,
    schedule: dict,
    route_mosques: list[dict],
    departure_dt: datetime,
    arrival_dt: datetime,
    dest_schedule: dict,
    timezone_str: str,
    trip_mode: str = "travel",
    prayed_prayers: Optional[set] = None,
    origin_lat: float = 0.0,
    origin_lng: float = 0.0,
    dest_lat: float = 0.0,
    dest_lng: float = 0.0,
    origin_mosques: Optional[list[dict]] = None,
    dest_mosques: Optional[list[dict]] = None,
    dest_tz_str: Optional[str] = None,
) -> Optional[dict]:
    """
    Build all valid prayer options for a prayer pair (e.g. dhuhr+asr).
    trip_mode='travel' includes combination options (Jam' Taqdeem/Ta'kheer).
    trip_mode='driving' only shows separate-stop options (combining not allowed).
    prayed_prayers: set of prayer names already performed today.
    origin_mosques/dest_mosques: pre-fetched anchor mosques for pray_before/at_destination.
    dest_tz_str: destination timezone string — used to correctly check dest_schedule times.
    Returns a dict matching TravelPairPlan schema, or None if both prayers are done.
    """
    prayed = prayed_prayers or set()

    # Both already prayed → skip pair entirely
    if prayer1 in prayed and prayer2 in prayed:
        return None

    # One already prayed → solo plan for the other
    if prayer1 in prayed:
        return _build_solo_plan(
            prayer2, schedule, route_mosques, departure_dt, arrival_dt, dest_schedule,
            timezone_str, origin_lat, origin_lng, dest_lat, dest_lng,
            origin_mosques=origin_mosques, dest_mosques=dest_mosques,
            dest_tz_str=dest_tz_str,
        )
    # Sequential inference: if prayer2 (e.g. Asr) is already prayed, prayer1 (e.g. Dhuhr)
    # must have been addressed before it. Skip the entire pair — both are done.
    if prayer2 in prayed:
        return None

    allow_combining = (trip_mode == "travel")
    pair_labels = {
        ("dhuhr", "asr"): ("dhuhr_asr", "Dhuhr + Asr", "🕌"),
        ("maghrib", "isha"): ("maghrib_isha", "Maghrib + Isha", "🌙"),
    }
    pair_key, label, emoji = pair_labels.get(
        (prayer1, prayer2),
        (f"{prayer1}_{prayer2}", f"{prayer1.title()} + {prayer2.title()}", "🕌"),
    )

    try:
        tz = ZoneInfo(timezone_str)
        dep_local = departure_dt.astimezone(tz)
        arr_local = arrival_dt.astimezone(tz)
    except Exception:
        dep_local = departure_dt
        arr_local = arrival_dt

    dep_min = dep_local.hour * 60 + dep_local.minute
    arr_min = arr_local.hour * 60 + arr_local.minute
    dep_fmt = f"{dep_local.hour:02d}:{dep_local.minute:02d}"

    # Arrival time in DESTINATION timezone — dest_schedule times are in dest local time.
    try:
        _dest_tz = ZoneInfo(dest_tz_str or timezone_str)
        _arr_dest = arrival_dt.astimezone(_dest_tz)
        arr_min_dest = _arr_dest.hour * 60 + _arr_dest.minute
    except Exception:
        arr_min_dest = arr_min

    # Deadline for no_option fallback — end of prayer2's window
    _DEADLINE_KEYS = {"asr": "maghrib_adhan", "isha": "fajr_adhan"}
    _deadline_key = _DEADLINE_KEYS.get(prayer2)
    _deadline_time = (schedule.get(_deadline_key) or dest_schedule.get(_deadline_key)) if _deadline_key else None

    _p1_dep = prayer_status_at_arrival(prayer1, schedule, dep_min)
    _p2_dep = prayer_status_at_arrival(prayer2, schedule, dep_min)

    # ── Period-closed check (Muqeem mode only) ─────────────────────────────
    # In Muqeem mode (no combining), if prayer1's window has already closed at departure
    # AND prayer2 is now active, redirect to a solo plan for prayer2 only.
    # In Musafir mode this check is SKIPPED — the combined window (Jam' Ta'kheer) stays
    # open until the end of prayer2's period regardless of prayer1's standard period.
    if not allow_combining and _p1_dep is None and _p2_dep is not None:
        return _build_solo_plan(
            prayer2, schedule, route_mosques, departure_dt, arrival_dt, dest_schedule,
            timezone_str, origin_lat, origin_lng, dest_lat, dest_lng,
            origin_mosques=origin_mosques, dest_mosques=dest_mosques,
            dest_tz_str=dest_tz_str,
        )

    options = []

    # ── Option: Pray before leaving — anchor mosque search near origin ──────
    s1 = _p1_dep
    s2 = _p2_dep
    if s1 or s2:
        # Which prayer to use for mosque search (first active, or prayer2 if only prayer2 active)
        search_prayer = prayer1 if s1 else prayer2
        origin_mosque = _find_nearby_mosque(origin_lat, origin_lng, route_mosques, search_prayer, dep_min,
                                            anchor_mosques=origin_mosques)
        if origin_mosque:
            om_status = prayer_status_at_arrival(search_prayer, origin_mosque["schedule"], dep_min) or s1 or s2
            pre_stop = dict(_make_stop(origin_mosque, search_prayer, om_status))
            pre_stop["minutes_into_trip"] = 0
            pre_stop["detour_minutes"] = 0
            pre_stop["estimated_arrival_time"] = dep_fmt
            origin_stops = [pre_stop]
            origin_note = f"{origin_mosque['name']} is near your departure point."
        else:
            origin_stops = []
            origin_note = "No mosque found near origin — pray at a clean spot before departing."

        if s1 and s2:
            # Both prayers active at departure
            options.append({
                "option_type": "pray_before",
                "label": "Pray Both Before Leaving",
                "description": f"Both {prayer1.title()} and {prayer2.title()} are currently active — pray before you depart.",
                "prayers": [prayer1, prayer2],
                "combination_label": "Jam' Taqdeem or Ta'kheer (both active now)" if allow_combining else None,
                "stops": origin_stops,
                "feasible": True,
                "note": origin_note,
            })
        elif allow_combining and not s1 and s2:
            # Musafir: prayer1 standard period closed but Ta'kheer window still open —
            # user should pray BOTH together (Jam' Ta'kheer) before leaving
            options.append({
                "option_type": "pray_before",
                "label": "Pray Both Before Leaving",
                "description": (
                    f"As a Musafir, pray both {prayer1.title()} + {prayer2.title()} together "
                    f"(Jam' Ta'kheer) before departing — the combined window is still open."
                ),
                "prayers": [prayer1, prayer2],
                "combination_label": "Jam' Ta'kheer",
                "stops": origin_stops,
                "feasible": True,
                "note": origin_note,
            })
        else:
            # One prayer active: show it (catch the other en route / at destination)
            active_p = prayer1 if s1 else prayer2
            options.append({
                "option_type": "pray_before",
                "label": f"Pray {active_p.title()} Before Leaving",
                "description": f"{active_p.title()} is currently active — pray before you depart.",
                "prayers": [active_p],
                "combination_label": None,
                "stops": origin_stops,
                "feasible": True,
                "note": origin_note,
            })

    # ── Combine Early / Late — only in Travel mode (not Driving) ──────────
    # In Musafir mode (more option types) limit to 2 per type; in Muqeem mode allow up to 3.
    MAX_OPTIONS = 2 if allow_combining else 3
    if allow_combining:
        early_candidates = []
        for m in sorted(route_mosques, key=lambda x: x["minutes_into_trip"]):
            s = prayer_status_at_arrival(prayer1, m["schedule"], m["local_arrival_minutes"])
            if s:
                early_candidates.append((_make_stop(m, prayer1, s), m))
                if len(early_candidates) >= MAX_OPTIONS:
                    break

        for stop, m in early_candidates:
            options.append({
                "option_type": "combine_early",
                "label": f"Jam' Taqdeem — {m['name']}",
                "description": (
                    f"Stop at {m['name']} ({m['detour_minutes']} min detour) and pray "
                    f"both {prayer1.title()} + {prayer2.title()} together during {prayer1.title()} time."
                ),
                "prayers": [prayer1, prayer2],
                "combination_label": "Jam' Taqdeem",
                "stops": [stop],
                "feasible": True,
                "note": f"~{fmt_duration(m['minutes_into_trip'])} into your trip",
            })

        late_candidates = []
        for m in sorted(route_mosques, key=lambda x: x["minutes_into_trip"]):
            s = prayer_status_at_arrival(prayer2, m["schedule"], m["local_arrival_minutes"])
            if s:
                late_candidates.append((_make_stop(m, prayer2, s), m))
                if len(late_candidates) >= MAX_OPTIONS:
                    break

        for stop, m in late_candidates:
            options.append({
                "option_type": "combine_late",
                "label": f"Jam' Ta'kheer — {m['name']}",
                "description": (
                    f"Stop at {m['name']} ({m['detour_minutes']} min detour) and pray "
                    f"both {prayer1.title()} + {prayer2.title()} together during {prayer2.title()} time."
                ),
                "prayers": [prayer1, prayer2],
                "combination_label": "Jam' Ta'kheer",
                "stops": [stop],
                "feasible": True,
                "note": f"~{fmt_duration(m['minutes_into_trip'])} into your trip",
            })

    # ── Separate stops — Muqeem mode only (hidden in Musafir/travel mode) ─
    if not allow_combining:
        best_p1 = None
        best_p2 = None
        for m in sorted(route_mosques, key=lambda x: x["minutes_into_trip"]):
            arr_min_m = m["local_arrival_minutes"]
            if not best_p1:
                s = prayer_status_at_arrival(prayer1, m["schedule"], arr_min_m)
                if s:
                    best_p1 = (_make_stop(m, prayer1, s), m)
            if not best_p2:
                s = prayer_status_at_arrival(prayer2, m["schedule"], arr_min_m)
                if s:
                    best_p2 = (_make_stop(m, prayer2, s), m)
            if best_p1 and best_p2:
                break

        if best_p1 and best_p2:
            stops = [best_p1[0]]
            if best_p2[1]["id"] != best_p1[1]["id"]:
                stops.append(best_p2[0])
            options.append({
                "option_type": "separate",
                "label": "Separate Stops",
                "description": (
                    f"Pray {prayer1.title()} at {best_p1[1]['name']} "
                    f"and {prayer2.title()} at {best_p2[1]['name']}."
                ),
                "prayers": [prayer1, prayer2],
                "combination_label": None,
                "stops": stops,
                "feasible": True,
                "note": "Two stops — one per prayer.",
            })

    # ── Pray at / near destination — anchor mosque search near destination ───
    # Use arr_min_dest (arrival in destination timezone) to correctly check dest_schedule times.
    s1_dest = prayer_status_at_arrival(prayer1, dest_schedule, arr_min_dest)
    s2_dest = prayer_status_at_arrival(prayer2, dest_schedule, arr_min_dest)
    prayers_at_dest: list[str] = [p for p, s in [(prayer1, s1_dest), (prayer2, s2_dest)] if s]
    dest_combination_label: Optional[str] = None

    if allow_combining:
        if not s1_dest and s2_dest:
            # Musafir: prayer1 standard period closed at arrival, but Ta'kheer window still open —
            # show BOTH as Jam' Ta'kheer (combined window extends to end of prayer2's period)
            prayers_at_dest = [prayer1, prayer2]
            dest_combination_label = "Jam' Ta'kheer"
        elif s1_dest and not s2_dest:
            # Musafir near-arrival Ta'kheer: prayer1 active, prayer2 starting within 45 min
            p2_adhan_raw = dest_schedule.get(f"{prayer2}_adhan")
            if p2_adhan_raw:
                p2_adhan_min = hhmm_to_minutes(p2_adhan_raw)
                if p2_adhan_min < arr_min_dest:
                    p2_adhan_min += 1440
                if 0 <= p2_adhan_min - arr_min_dest <= 45:
                    prayers_at_dest = [prayer1, prayer2]
                    dest_combination_label = "Jam' Ta'kheer"
        elif s1_dest and s2_dest:
            dest_combination_label = "Jam' Taqdeem"

    if prayers_at_dest:
        # For Jam' Ta'kheer the active window is prayer2 (e.g. Asr), not prayer1 (Dhuhr which ended).
        # Search using the last prayer in the list so the mosque check uses the correct active window.
        search_prayer_dest = prayers_at_dest[-1] if dest_combination_label == "Jam' Ta'kheer" else prayers_at_dest[0]
        dest_mosque = _find_nearby_mosque(dest_lat, dest_lng, route_mosques, search_prayer_dest, arr_min_dest,
                                          anchor_mosques=dest_mosques)
        if dest_mosque:
            dm_status = (prayer_status_at_arrival(search_prayer_dest, dest_mosque["schedule"], dest_mosque["local_arrival_minutes"])
                         or s1_dest or s2_dest)
            dest_stops = [_make_stop(dest_mosque, prayers_at_dest[0], dm_status)]
            dest_note = f"{dest_mosque['name']} is near your destination."
        else:
            dest_stops = []
            dest_note = "No mosque confirmed near destination — find a mosque on arrival."

        if dest_combination_label == "Jam' Ta'kheer":
            desc = (
                f"Pray both {prayer1.title()} + {prayer2.title()} together "
                f"(Jam' Ta'kheer) near your destination."
            )
        else:
            desc = (
                f"{' + '.join(p.title() for p in prayers_at_dest)} "
                f"{'are' if len(prayers_at_dest) > 1 else 'is'} still active when you arrive."
            )
        options.append({
            "option_type": "at_destination",
            "label": "Pray Near Destination",
            "description": desc,
            "prayers": prayers_at_dest,
            "combination_label": dest_combination_label,
            "stops": dest_stops,
            "feasible": True,
            "note": dest_note,
        })

    if not options:
        deadline_str = f" before {_deadline_time}" if _deadline_time else ""
        comb_label = "Jam' Ta'kheer" if allow_combining else None
        options.append({
            "option_type": "no_option",
            "label": "No Mosque Found",
            "description": (
                f"No mosque found. Pray {prayer1.title()} + {prayer2.title()} "
                f"at a clean rest stop{deadline_str}."
            ),
            "prayers": [prayer1, prayer2],
            "combination_label": comb_label,
            "stops": [],
            "feasible": False,
            "note": f"Pray at a clean rest stop{deadline_str}.",
        })

    return {"pair": pair_key, "label": label, "emoji": emoji, "options": options}


# ---------------------------------------------------------------------------
# Trip-window relevance check
# ---------------------------------------------------------------------------

_PERIOD_END_KEYS = {
    "fajr": "sunrise",
    "dhuhr": "asr_adhan",
    "asr": "maghrib_adhan",
    "maghrib": "isha_adhan",
    "isha": "fajr_adhan",
}

def _prayer_overlaps_trip(prayer: str, schedule: dict, dep_min: int, arr_min: int) -> bool:
    """
    Returns True if the prayer's active window overlaps the trip window [dep_min, arr_min].
    Handles midnight wrap (e.g. Isha period extends past midnight into next day's Fajr).
    All times are minutes-from-midnight (0–1439). Trip may also cross midnight.

    Strategy: check overlap in the original frame and again with trip shifted +1440 (next-day
    context), so that e.g. a 12:46 AM trip is correctly matched against an Isha window that
    started at 9 PM today and extends past midnight.
    """
    adhan = schedule.get(f"{prayer}_adhan")
    if not adhan:
        return False

    adhan_m = hhmm_to_minutes(adhan)
    period_end_key = _PERIOD_END_KEYS.get(prayer)
    period_end_raw = schedule.get(period_end_key) if period_end_key else None
    if period_end_raw:
        period_end_m = hhmm_to_minutes(period_end_raw)
        if period_end_m <= adhan_m:          # midnight wrap (e.g. Isha → Fajr)
            period_end_m += 1440
    else:
        period_end_m = adhan_m + 360

    # Handle trip crossing midnight (e.g. dep=1380, arr=60 → arr becomes 1500)
    if arr_min < dep_min:
        arr_min += 1440

    def _overlaps(a1: int, a2: int, b1: int, b2: int) -> bool:
        # Strict on period end: a prayer ends exactly at the next adhan, so
        # a trip starting exactly at period_end has no prayer window remaining.
        return a1 <= b2 and a2 > b1

    # Three frames to cover:
    # 1. Normal: today's prayer vs today's trip window
    # 2. Post-midnight trip: today's prayer vs trip shifted to yesterday's frame
    #    (e.g. Isha at 9 PM and a 12:46 AM trip)
    # 3. Next-day prayer: tomorrow's prayer (adhan+1440) vs today's trip window
    #    (e.g. 10 PM departure arriving 2 PM next day — catches tomorrow's Dhuhr)
    return (
        _overlaps(adhan_m, period_end_m, dep_min, arr_min) or
        _overlaps(adhan_m, period_end_m, dep_min + 1440, arr_min + 1440) or
        _overlaps(adhan_m + 1440, period_end_m + 1440, dep_min, arr_min)
    )


def _pair_relevant(p1: str, p2: str, schedule: dict, dep_min: int, arr_min: int) -> bool:
    """True if either prayer in the pair overlaps the trip window."""
    return (
        _prayer_overlaps_trip(p1, schedule, dep_min, arr_min) or
        _prayer_overlaps_trip(p2, schedule, dep_min, arr_min)
    )


# First prayer and period-end key for each pair (used for sort ordering)
_PAIR_FIRST_PRAYER = {
    "fajr": "fajr", "dhuhr": "dhuhr", "asr": "asr",
    "maghrib": "maghrib", "isha": "isha",
    "dhuhr_asr": "dhuhr", "maghrib_isha": "maghrib",
}
_PAIR_END_KEY_FOR_SORT = {
    "fajr": "sunrise",
    "dhuhr": "asr_adhan", "dhuhr_asr": "maghrib_adhan",
    "asr": "maghrib_adhan",
    "maghrib": "isha_adhan", "maghrib_isha": "fajr_adhan",
    "isha": "fajr_adhan",
}


def _pair_sort_key(pair_plan: dict, schedule: dict, dep_min: int) -> int:
    """
    Sort prayer pairs chronologically relative to departure time.

    - Pair already active at departure (adhan <= dep_min AND period not yet ended): sort by adhan_m.
    - Pair whose period ended before departure (next-day occurrence): sort by adhan_m + 1440.
    - Pair starting after departure: sort by adhan_m as-is.

    Example (departure 10 PM = 1320 min):
      Maghrib+Isha: adhan=1143, end=fajr+1440=1755 → active at dep → sort key 1143 (first)
      Fajr: adhan=315, end=sunrise=375 → period ended before dep → sort key 315+1440=1755 (second)
    """
    pair = pair_plan.get("pair", "")
    first_prayer = _PAIR_FIRST_PRAYER.get(pair, pair.split("_")[0] if "_" in pair else pair)

    adhan_raw = schedule.get(f"{first_prayer}_adhan") or "00:00"
    adhan_m = hhmm_to_minutes(adhan_raw)

    end_key = _PAIR_END_KEY_FOR_SORT.get(pair)
    end_raw = schedule.get(end_key) if end_key else None
    end_m = hhmm_to_minutes(end_raw) if end_raw else adhan_m + 360
    if end_m <= adhan_m:          # midnight wrap (Isha/Maghrib+Isha → Fajr)
        end_m += 1440

    # Active at departure: adhan already passed but period still running
    if adhan_m <= dep_min < end_m:
        return adhan_m            # sort by actual adhan (earlier = highest priority)
    # Period ended before departure → next-day occurrence
    if adhan_m <= dep_min and dep_min >= end_m:
        return adhan_m + 1440
    # Starts after departure
    return adhan_m


# ---------------------------------------------------------------------------
# Complete trip itinerary builder
# ---------------------------------------------------------------------------

def _itinerary_label(pair_choices: list[dict]) -> str:
    """Short label describing each pair's strategy, e.g. '🕌 Dhuhr+Asr early · 🌙 Maghrib+Isha late'"""
    type_words = {
        "pray_before":    "before leaving",
        "combine_early":  "early (Taqdeem)",
        "combine_late":   "late (Ta'kheer)",
        "at_destination": "at destination",
        "separate":       "separate stops",
        "solo_stop":      "en route stop",
        "stop_for_fajr":  "Fajr stop",
        "no_option":      "no mosque",
    }
    parts = []
    for pc in pair_choices:
        ot = pc["option"]["option_type"]
        parts.append(f"{pc['emoji']} {pc['label']} {type_words.get(ot, ot)}")
    return " · ".join(parts)


def _itinerary_summary(pair_choices: list[dict]) -> str:
    """One-sentence description of the full plan."""
    parts = []
    for pc in pair_choices:
        opt = pc["option"]
        ot = opt["option_type"]
        label = pc["label"]
        stops = opt.get("stops", [])
        if ot == "pray_before":
            parts.append(f"Pray {label} before leaving")
        elif ot in ("combine_early", "combine_late"):
            combo = "Jam' Taqdeem" if ot == "combine_early" else "Jam' Ta'kheer"
            mosque = stops[0]["mosque_name"] if stops else "a mosque en route"
            t = stops[0]["minutes_into_trip"] if stops else 0
            parts.append(f"Combine {label} at {mosque} ({combo}, ~{fmt_duration(t)} into trip)")
        elif ot == "at_destination":
            parts.append(f"Pray {label} near your destination")
        elif ot == "solo_stop":
            mosque = stops[0]["mosque_name"] if stops else "a mosque en route"
            t = stops[0]["minutes_into_trip"] if stops else 0
            parts.append(f"Stop for {label} at {mosque} (~{fmt_duration(t)} into trip)")
        elif ot == "separate":
            if len(stops) >= 2:
                parts.append(f"{label}: {stops[0]['mosque_name']} then {stops[1]['mosque_name']}")
            elif stops:
                parts.append(f"{label} at {stops[0]['mosque_name']}")
            else:
                parts.append(f"{label} separately")
        elif ot == "stop_for_fajr":
            mosque = stops[0]["mosque_name"] if stops else "a mosque"
            parts.append(f"Fajr at {mosque}")
        else:
            parts.append(f"{label}: no option found")
    return " → ".join(parts)


def build_itineraries(prayer_pairs: list[dict], allow_combining: bool = True) -> list[dict]:
    """
    Build 3-5 complete trip itineraries from the per-pair option sets.
    Each itinerary is one cohesive plan covering ALL prayers for the whole trip.

    Musafir (allow_combining=True) templates:
      1. All early  — pray before leaving or Taqdeem for every pair
      2. Early then late — Taqdeem for first pair, Ta'kheer/destination for last
      3. All late   — Ta'kheer or at-destination for every pair
      4. All at destination
      5. Separate stops (no combining)

    Muqeem (allow_combining=False) templates:
      1. Separate stops for every pair (primary)
      2. Pray before leaving where possible, separate otherwise
      3. All at destination
    Duplicate combos are skipped.
    """
    if not prayer_pairs:
        return []

    # Per-pair map: option_type -> first feasible option of that type
    pair_maps: list[dict] = []
    for pair in prayer_pairs:
        omap: dict[str, dict] = {}
        for opt in pair["options"]:
            t = opt["option_type"]
            if t not in omap:
                omap[t] = opt
        pair_maps.append({"pair": pair["pair"], "label": pair["label"], "emoji": pair["emoji"], "omap": omap})

    def pick(pm: dict, *types: str):
        for t in types:
            if t in pm["omap"]:
                return (pm, pm["omap"][t])
        return None

    n = len(pair_maps)

    if not allow_combining:
        # Muqeem mode: each prayer is planned individually (no pairs, no combining).
        # Options available: solo_stop, pray_before, at_destination, stop_for_fajr, no_option.
        MUQEEM_FALLBACK = ["solo_stop", "pray_before", "at_destination", "stop_for_fajr", "no_option"]
        templates: list[list[list[str]]] = [
            # 1. Best en-route stop for each prayer (primary plan)
            [["solo_stop", "pray_before"] + MUQEEM_FALLBACK] * n,
            # 2. Pray before leaving where possible, else en-route stop
            [["pray_before", "solo_stop"] + MUQEEM_FALLBACK] * n,
            # 3. All at destination (fallback when no en-route mosques)
            [["at_destination", "solo_stop"] + MUQEEM_FALLBACK] * n,
        ]
    else:
        # Musafir mode: no `separate` — only combining options, pray_before, at_destination, solo_stop
        FALLBACK = ["at_destination", "solo_stop", "combine_late", "combine_early", "stop_for_fajr", "no_option"]
        templates = [
            # 1. All early (pray before or Taqdeem)
            [["pray_before", "combine_early", "solo_stop"] + FALLBACK] * n,
            # 2. Early first pair, late rest (only meaningful if ≥2 pairs)
            (
                [["pray_before", "combine_early", "solo_stop"] + FALLBACK] +
                [["combine_late", "at_destination", "solo_stop"] + FALLBACK] * (n - 1)
            ) if n >= 2 else [],
            # 3. All late (Ta'kheer or at destination)
            [["combine_late", "at_destination", "solo_stop"] + FALLBACK] * n,
            # 4. All at destination
            [["at_destination", "combine_late", "solo_stop"] + FALLBACK] * n,
            # 5. Mix: combine_late first pair, at_destination rest (only if ≥2 pairs)
            (
                [["combine_late", "at_destination", "solo_stop"] + FALLBACK] +
                [["at_destination", "combine_late", "solo_stop"] + FALLBACK] * (n - 1)
            ) if n >= 2 else [],
        ]

    seen: set[tuple] = set()
    itineraries: list[dict] = []

    for template in templates:
        if not template:
            continue
        choices = [pick(pair_maps[i], *template[i]) for i in range(n)]
        if any(c is None for c in choices):
            continue

        combo_key = tuple(opt["option_type"] for _, opt in choices)  # type: ignore[index]
        if combo_key in seen:
            continue
        seen.add(combo_key)

        pair_choices_out = []
        total_detour = 0
        all_feasible = True
        for pm, opt in choices:  # type: ignore[misc]
            pair_choices_out.append({
                "pair": pm["pair"],
                "label": pm["label"],
                "emoji": pm["emoji"],
                "option": opt,
            })
            total_detour += sum(s["detour_minutes"] for s in opt.get("stops", []))
            if not opt.get("feasible", True):
                all_feasible = False

        itineraries.append({
            "label": _itinerary_label(pair_choices_out),
            "summary": _itinerary_summary(pair_choices_out),
            "pair_choices": pair_choices_out,
            "total_detour_minutes": total_detour,
            "stop_count": sum(len(opt.get("stops", [])) for _, opt in choices),  # type: ignore[misc]
            "feasible": all_feasible,
        })

    return itineraries


# ---------------------------------------------------------------------------
# Itinerary scoring & ranking (ROUTE_PLANNING_ALGORITHM.md §5)
# ---------------------------------------------------------------------------

def score_itinerary(itinerary: dict) -> float:
    """Score an itinerary. Lower is better.

    Formula: (detour * 2) + (stops * 10) + (infeasible * 100) - (imam_catches * 5)
    """
    total_detour = itinerary.get("total_detour_minutes", 0)
    stop_count = itinerary.get("stop_count", 0)

    infeasible = 0
    imam_catches = 0
    for pc in itinerary.get("pair_choices", []):
        opt = pc.get("option", {})
        if not opt.get("feasible", True):
            infeasible += 1
        for stop in opt.get("stops", []):
            if stop.get("status") == "can_catch_with_imam":
                imam_catches += 1

    return (total_detour * 2) + (stop_count * 10) + (infeasible * 100) - (imam_catches * 5)


def rank_itineraries(itineraries: list[dict]) -> list[dict]:
    """Sort itineraries by score ascending (best first)."""
    scored = [(score_itinerary(it), i, it) for i, it in enumerate(itineraries)]
    scored.sort(key=lambda x: (x[0], x[1]))
    return [it for _, _, it in scored]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def build_travel_plan(
    db: AsyncSession,
    origin_lat: float, origin_lng: float,
    dest_lat: float, dest_lng: float,
    destination_name: str,
    timezone_str: str,
    origin_name: str = "Current location",
    departure_dt: Optional[datetime] = None,
    trip_mode: str = "travel",
    waypoints: Optional[list[dict]] = None,
    prayed_prayers: Optional[set] = None,
) -> Optional[dict]:
    """
    Build a full travel prayer plan.
    Returns a dict matching TravelPlanResponse schema, or None on failure.
    """
    try:
        tz_zone = ZoneInfo(timezone_str)
    except Exception:
        tz_zone = ZoneInfo("UTC")
    if departure_dt is None:
        departure_dt = datetime.now(tz_zone)
    elif departure_dt.tzinfo is None:
        departure_dt = departure_dt.replace(tzinfo=tz_zone)

    prayed = prayed_prayers or set()

    # 1. Get Mapbox route (through waypoints if any)
    route = await get_mapbox_route(origin_lat, origin_lng, dest_lat, dest_lng, waypoints=waypoints)
    if not route:
        # Fallback: straight-line estimate with intermediate checkpoints every ~50 km
        # so that mosques along the route (not just near origin/destination) can be found.
        dist_km = haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
        duration_min = estimate_travel_minutes(origin_lat, origin_lng, dest_lat, dest_lng)
        n_segments = max(4, int(dist_km / 50))
        fallback_coords = [
            [origin_lng + (dest_lng - origin_lng) * i / n_segments,
             origin_lat + (dest_lat - origin_lat) * i / n_segments]
            for i in range(n_segments + 1)
        ]
        logger.warning(
            f"Routing unavailable — using straight-line fallback with {len(fallback_coords)} checkpoints "
            f"over {dist_km:.0f} km"
        )
        route = {
            "duration": duration_min * 60,
            "distance": dist_km * 1000,
            "geometry": {"type": "LineString", "coordinates": fallback_coords},
            "legs": [],
        }

    arrival_dt = departure_dt + timedelta(seconds=route["duration"])

    # Validate trip duration (max 3 days)
    valid, error_msg = validate_trip_duration(departure_dt, arrival_dt)
    if not valid:
        raise ValueError(error_msg)

    # 2. Build checkpoints
    checkpoints = build_checkpoints(route, departure_dt)
    if len(checkpoints) < 2:
        # Fallback minimal checkpoints
        checkpoints = [
            {"lat": origin_lat, "lng": origin_lng, "time": departure_dt, "cumulative_minutes": 0},
            {"lat": dest_lat, "lng": dest_lng, "time": arrival_dt, "cumulative_minutes": route["duration"] / 60},
        ]

    # 3. Get prayer schedule at origin (for departure time)
    today = departure_dt.date()
    try:
        import pytz
        ptz = pytz.timezone(timezone_str)
        offset_h = ptz.utcoffset(departure_dt.replace(tzinfo=None)).total_seconds() / 3600
    except Exception:
        offset_h = -5
    origin_calc = calculate_prayer_times(origin_lat, origin_lng, today, timezone_offset=offset_h)
    origin_schedule = {**(origin_calc or {}), **estimate_iqama_times(origin_calc or {})}

    # Get destination schedule (for arrival time prayers)
    # Use ARRIVAL date and arrival-time offset (not departure) for correct
    # date and DST handling (ROUTE_PLANNING_ALGORITHM.md — Timezone Crossing)
    arrival_date = arrival_dt.date()
    try:
        from timezonefinder import TimezoneFinder
        dest_tz_str = TimezoneFinder().timezone_at(lat=dest_lat, lng=dest_lng) or timezone_str
        dest_ptz = pytz.timezone(dest_tz_str)
        dest_offset_h = dest_ptz.utcoffset(arrival_dt.replace(tzinfo=None)).total_seconds() / 3600
    except Exception:
        dest_tz_str = timezone_str
        dest_offset_h = offset_h
    dest_calc = calculate_prayer_times(dest_lat, dest_lng, arrival_date, timezone_offset=dest_offset_h)
    dest_schedule = {**(dest_calc or {}), **estimate_iqama_times(dest_calc or {})}

    # 4. Find mosques along route with progressive radius search
    # Start at 25 km, expand to 50/75 km if too few mosques found
    route_mosques = []
    for radius in PROGRESSIVE_RADII:
        route_mosques = await find_route_mosques(db, checkpoints, departure_dt, corridor_km=radius)
        if len(route_mosques) >= 3:  # enough candidates to build viable plans
            break
        logger.info(f"Progressive search: {len(route_mosques)} mosques at {radius}km, expanding...")

    origin_mosques = await fetch_anchor_mosques(db, origin_lat, origin_lng, timezone_str, departure_dt)
    dest_mosques = await fetch_anchor_mosques(db, dest_lat, dest_lng, dest_tz_str, arrival_dt)

    # 5. Build prayer plans for the trip window
    prayer_pairs = []
    dep_local = departure_dt.astimezone(tz_zone)
    arr_local = arrival_dt.astimezone(tz_zone)
    dep_min = dep_local.hour * 60 + dep_local.minute
    arr_min = arr_local.hour * 60 + arr_local.minute

    if trip_mode != "travel":
        # ── Muqeem mode: plan each prayer INDEPENDENTLY — no pairs, no combining ──
        # Sequential inference: if prayer2 is prayed → prayer1 also done
        muqeem_prayed = set(prayed)
        if "asr" in muqeem_prayed:
            muqeem_prayed.add("dhuhr")
        if "isha" in muqeem_prayed:
            muqeem_prayed.add("maghrib")

        for prayer in ["dhuhr", "asr", "maghrib", "isha"]:
            if prayer in muqeem_prayed:
                continue
            if not (
                _prayer_overlaps_trip(prayer, origin_schedule, dep_min, arr_min) or
                _prayer_overlaps_trip(prayer, dest_schedule, dep_min, arr_min)
            ):
                continue
            plan = _build_solo_plan(
                prayer, origin_schedule, route_mosques,
                departure_dt, arrival_dt, dest_schedule, timezone_str,
                origin_lat, origin_lng, dest_lat, dest_lng,
                origin_mosques=origin_mosques, dest_mosques=dest_mosques,
                dest_tz_str=dest_tz_str,
            )
            prayer_pairs.append(plan)
    else:
        # ── Musafir mode: pair-based planning with combining options ──
        for p1, p2 in [("dhuhr", "asr"), ("maghrib", "isha")]:
            # Skip if pair is prayed (sequential inference: p2 prayed → both done)
            if p2 in prayed or (p1 in prayed and p2 in prayed):
                continue

            # A pair is relevant if it overlaps the trip window using EITHER origin OR destination
            # prayer times. This matters for north-south routes where sunset/prayer times differ.
            if not (
                _pair_relevant(p1, p2, origin_schedule, dep_min, arr_min) or
                _pair_relevant(p1, p2, dest_schedule, dep_min, arr_min)
            ):
                continue

            # Skip stale pairs: if departure is after midnight (before 6 AM)
            # and both prayers have evening adhans (after noon), the pair is
            # from yesterday — skip it. Example: Maghrib 6:30 PM + Isha 8:30 PM,
            # departure 12:12 AM → both adhans happened yesterday evening.
            p1_adhan = origin_schedule.get(f"{p1}_adhan")
            p2_adhan = origin_schedule.get(f"{p2}_adhan")
            if p1_adhan and p2_adhan and dep_min < 360:  # departure before 6 AM
                p1_min = hhmm_to_minutes(p1_adhan)
                p2_min = hhmm_to_minutes(p2_adhan)
                if p1_min > 720 and p2_min > 720:  # both adhans are PM (after noon)
                    continue
            plan = build_combination_plan(
                p1, p2, origin_schedule, route_mosques,
                departure_dt, arrival_dt, dest_schedule, timezone_str,
                trip_mode=trip_mode,
                prayed_prayers=prayed,
                origin_lat=origin_lat,
                origin_lng=origin_lng,
                dest_lat=dest_lat,
                dest_lng=dest_lng,
                origin_mosques=origin_mosques,
                dest_mosques=dest_mosques,
                dest_tz_str=dest_tz_str,
            )
            if plan is not None:
                prayer_pairs.append(plan)

    # Fajr (standalone — only if trip overlaps the Fajr prayer window and not already prayed)
    if "fajr" not in prayed and (
        _prayer_overlaps_trip("fajr", origin_schedule, dep_min, arr_min) or
        _prayer_overlaps_trip("fajr", dest_schedule, dep_min, arr_min)
    ):
        fajr_adhan = origin_schedule.get("fajr_adhan")
        fajr_sunrise = origin_schedule.get("sunrise", "sunrise unknown")
        fajr_options = []
        best_fajr_m = None
        # Search route mosques first (each has its own estimated arrival time)
        for m in sorted(route_mosques, key=lambda x: x["minutes_into_trip"]):
            s = prayer_status_at_arrival("fajr", m["schedule"], m["local_arrival_minutes"])
            if s:
                best_fajr_m = m
                break
        # Fall back to anchor mosques near the destination
        if not best_fajr_m and dest_mosques:
            for m in sorted(dest_mosques, key=lambda m: haversine_km(dest_lat, dest_lng, m["lat"], m["lng"])):
                s = prayer_status_at_arrival("fajr", m["schedule"], m["local_arrival_minutes"])
                if s:
                    best_fajr_m = m
                    break
        if best_fajr_m:
            m = best_fajr_m
            stop = _make_stop(m, "fajr", prayer_status_at_arrival("fajr", m["schedule"], m["local_arrival_minutes"]))
            fajr_options.append({
                "option_type": "stop_for_fajr",
                "label": "Stop for Fajr",
                "description": f"Stop at {m['name']} ({m['detour_minutes']} min detour) for Fajr.",
                "prayers": ["fajr"],
                "combination_label": None,
                "stops": [stop],
                "feasible": True,
                "note": f"Fajr at {fajr_adhan}, ends at sunrise ({fajr_sunrise}). {m['name']} is {m['detour_minutes']} min off route.",
            })
        else:
            fajr_options.append({
                "option_type": "no_option",
                "label": "Fajr — No Mosque Found",
                "description": f"No mosque found for Fajr. Find a clean rest stop before sunrise ({fajr_sunrise}).",
                "prayers": ["fajr"],
                "combination_label": None,
                "stops": [],
                "feasible": False,
                "note": None,
            })
        prayer_pairs.append({
            "pair": "fajr",
            "label": "Fajr",
            "emoji": "🌅",
            "options": fajr_options,
        })

    # Sort pairs chronologically relative to departure: active prayers first,
    # then prayers starting during the trip, then next-day occurrences (e.g. Fajr after evening departure).
    prayer_pairs.sort(key=lambda pp: _pair_sort_key(pp, origin_schedule, dep_min))

    itineraries = build_itineraries(prayer_pairs, allow_combining=(trip_mode == "travel"))

    # Build simplified polyline for the main route (origin → destination, no stops)
    raw_coords = route.get("geometry", {}).get("coordinates", [])
    if raw_coords:
        sampled = raw_coords[::4]
        if raw_coords[-1] not in sampled:
            sampled = list(sampled) + [raw_coords[-1]]
        base_geometry = [[c[1], c[0]] for c in sampled]  # lng,lat → lat,lng for Leaflet
    else:
        base_geometry = []

    async def _geometry_for_itinerary(itin: dict) -> list:
        """Return route geometry through this itinerary's prayer stops."""
        seen: set = set()
        stops: list[dict] = []
        for pc in itin["pair_choices"]:
            for s in pc["option"].get("stops", []):
                if s["mosque_id"] not in seen:
                    seen.add(s["mosque_id"])
                    stops.append(s)
        stops.sort(key=lambda s: s["minutes_into_trip"])

        if not stops:
            return base_geometry  # no detour — same as direct route

        stop_wps = [{"lat": s["mosque_lat"], "lng": s["mosque_lng"]} for s in stops]
        # Insert user-provided trip waypoints in their original positions
        all_wps = list(waypoints or []) + stop_wps  # user wps first, mosque stops after
        # Re-sort by proximity to the route isn't trivial; just pass mosque stops as additional
        # waypoints appended after any user waypoints — Mapbox/OSRM will order them optimally
        r = await get_mapbox_route(origin_lat, origin_lng, dest_lat, dest_lng, waypoints=all_wps)
        if not r:
            return base_geometry
        rc = r.get("geometry", {}).get("coordinates", [])
        if not rc:
            return base_geometry
        samp = rc[::4]
        if rc[-1] not in samp:
            samp = list(samp) + [rc[-1]]
        return [[c[1], c[0]] for c in samp]

    # Compute per-itinerary routes in parallel
    itinerary_geometries = await asyncio.gather(
        *[_geometry_for_itinerary(it) for it in itineraries],
        return_exceptions=True,
    )
    for it, geom in zip(itineraries, itinerary_geometries):
        it["route_geometry"] = geom if isinstance(geom, list) else base_geometry

    return {
        "route": {
            "distance_meters": route.get("distance", 0),
            "duration_minutes": round(route.get("duration", 0) / 60),
            "origin_name": origin_name,
            "destination_name": destination_name,
            "route_geometry": base_geometry,
        },
        "prayer_pairs": prayer_pairs,
        "itineraries": rank_itineraries(itineraries),
        "departure_time": departure_dt.isoformat(),
        "estimated_arrival_time": arrival_dt.isoformat(),
    }
