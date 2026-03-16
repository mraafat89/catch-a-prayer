"""
Route-based Travel Prayer Planner
==================================
Given origin + destination, builds a structured prayer plan for the journey.

Algorithm:
1. Get Mapbox Directions route (with steps for time-tagged waypoints)
2. Build time-tagged checkpoints along route from step maneuver locations
3. Find mosques near the route (within 20km of route bounding box)
4. For each mosque, compute: estimated_pass_time + detour_minutes
5. For each prayer pair (Dhuhr+Asr, Maghrib+Isha), build options:
   - combine_early: pray both during first prayer's period (Jam' Taqdeem)
   - combine_late: pray both during second prayer's period (Jam' Ta'kheer)
   - separate: different mosques for each prayer
   - pray_before: both prayers active at departure
   - at_destination: pray near destination
"""
from __future__ import annotations

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

DETOUR_OVERHEAD_MINUTES = 15   # time to stop, pray, re-enter route
ROUTE_CORRIDOR_KM = 30         # mosques within 30km of route bounding box
MAX_DETOUR_MINUTES = 45        # skip mosques requiring > 45 min total detour
HIGHWAY_SPEED_KMH = 60         # speed used for detour estimate (highway avg)


# ---------------------------------------------------------------------------
# Routing helpers (Mapbox primary, OSRM free fallback)
# ---------------------------------------------------------------------------

_OSM_HEADERS = {"User-Agent": "CatchAPrayer/1.0 (contact@catchaprayer.app)"}


async def get_mapbox_route(
    origin_lat: float, origin_lng: float,
    dest_lat: float, dest_lng: float,
) -> Optional[dict]:
    """Return a route dict with legs/steps. Tries Mapbox first, falls back to OSRM."""
    # --- Mapbox (if key configured) ---
    if settings.mapbox_api_key:
        try:
            url = (
                f"https://api.mapbox.com/directions/v5/mapbox/driving/"
                f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
            )
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
    # Try https (verify=True), https (verify=False), then plain http — the last
    # handles macOS Python 3.9 TLS handshake failures against the OSRM endpoint.
    osrm_attempts = [
        (f"https://router.project-osrm.org/route/v1/driving/{origin_lng},{origin_lat};{dest_lng},{dest_lat}", True),
        (f"https://router.project-osrm.org/route/v1/driving/{origin_lng},{origin_lat};{dest_lng},{dest_lat}", False),
        (f"http://router.project-osrm.org/route/v1/driving/{origin_lng},{origin_lat};{dest_lng},{dest_lat}", True),
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
# DB: find mosques in route bounding box
# ---------------------------------------------------------------------------

async def find_route_mosques(
    db: AsyncSession,
    checkpoints: list[dict],
    departure_dt: datetime,
) -> list[dict]:
    """
    Query mosques within ROUTE_CORRIDOR_KM of the route bounding box.
    For each mosque, compute estimated_pass_time and detour_minutes.
    """
    if not checkpoints:
        return []

    # Bounding box of all checkpoints + buffer
    lats = [c["lat"] for c in checkpoints]
    lngs = [c["lng"] for c in checkpoints]
    # 1 degree lat ≈ 111km, 1 degree lng ≈ 111*cos(lat) km
    lat_buf = ROUTE_CORRIDOR_KM / 111.0
    lng_buf = ROUTE_CORRIDOR_KM / 85.0  # conservative

    bbox = {
        "lat_min": min(lats) - lat_buf,
        "lat_max": max(lats) + lat_buf,
        "lng_min": min(lngs) - lng_buf,
        "lng_max": max(lngs) + lng_buf,
    }
    result = await db.execute(text("""
        SELECT id::text, name, lat, lng, address, city, state, timezone
        FROM mosques
        WHERE is_active = true
          AND lat BETWEEN :lat_min AND :lat_max
          AND lng BETWEEN :lng_min AND :lng_max
        LIMIT 500
    """), bbox)
    rows = result.mappings().all()
    logger.info(f"find_route_mosques: {len(checkpoints)} checkpoints, {len(rows)} mosques in bbox")

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
            "detour_minutes": round(detour_min),
            "estimated_arrival": estimated_arrival,
            "minutes_into_trip": round(minutes_into_trip),
            "local_arrival_minutes": local_pass.hour * 60 + local_pass.minute,
            "local_arrival_time_fmt": f"{local_pass.hour:02d}:{local_pass.minute:02d}",
            "schedule": schedule,
        })

    logger.info(f"find_route_mosques: {len(route_mosques)}/{len(rows)} mosques pass detour filter")
    return route_mosques


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
        period_end_min += 1440  # midnight wrap

    if arrival_minutes < adhan_min:
        return None  # prayer hasn't started
    if arrival_minutes > period_end_min:
        return None  # prayer period has ended

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
        "prayer": prayer,
        "estimated_arrival_time": m["local_arrival_time_fmt"],
        "minutes_into_trip": m["minutes_into_trip"],
        "detour_minutes": m["detour_minutes"],
        "status": status_info["status"],
        "iqama_time": status_info.get("iqama_time"),
        "adhan_time": status_info.get("adhan_time"),
    }


def build_combination_plan(
    prayer1: str, prayer2: str,
    schedule: dict,
    route_mosques: list[dict],
    departure_dt: datetime,
    arrival_dt: datetime,
    dest_schedule: dict,
    timezone_str: str,
    trip_mode: str = "travel",
) -> dict:
    """
    Build all valid prayer options for a prayer pair (e.g. dhuhr+asr).
    trip_mode='travel' includes combination options (Jam' Taqdeem/Ta'kheer).
    trip_mode='driving' only shows separate-stop options (combining not allowed).
    Returns a dict matching TravelPairPlan schema.
    """
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

    options = []

    # ── Option: Pray before leaving ────────────────────────────────────────
    s1 = prayer_status_at_arrival(prayer1, schedule, dep_min)
    s2 = prayer_status_at_arrival(prayer2, schedule, dep_min)
    if s1 and s2:
        options.append({
            "option_type": "pray_before",
            "label": "Pray Both Before Leaving",
            "description": f"Both {prayer1.title()} and {prayer2.title()} are currently active — pray before you depart.",
            "prayers": [prayer1, prayer2],
            "combination_label": "Jam' Taqdeem or Ta'kheer (both active now)",
            "stops": [],
            "feasible": True,
            "note": "Most convenient — no stop needed on the road.",
        })
    elif s1:
        options.append({
            "option_type": "pray_before",
            "label": f"Pray {prayer1.title()} Before Leaving",
            "description": f"{prayer1.title()} is currently active. Pray before departure; catch {prayer2.title()} along the way.",
            "prayers": [prayer1],
            "combination_label": None,
            "stops": [],
            "feasible": True,
            "note": None,
        })

    # ── Combine Early / Late — only in Travel mode (not Driving) ──────────
    # Return up to 3 diverse mosque options per combination type
    MAX_OPTIONS = 3
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
                "note": f"~{m['minutes_into_trip']} min into your trip",
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
                "note": f"~{m['minutes_into_trip']} min into your trip",
            })

    # ── Separate stops ─────────────────────────────────────────────────────
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
            "note": "Two stops — maximum flexibility.",
        })

    # ── Pray at / near destination ─────────────────────────────────────────
    # Only show this option when there are NO route-stop options covering those
    # prayers — avoids the confusing "third card" for a prayer already covered
    # by combine_early, combine_late, or separate above.
    has_route_stops = any(
        o["option_type"] in ("combine_early", "combine_late", "separate")
        for o in options
    )
    if not has_route_stops:
        s1_dest = prayer_status_at_arrival(prayer1, dest_schedule, arr_min)
        s2_dest = prayer_status_at_arrival(prayer2, dest_schedule, arr_min)
        if s1_dest or s2_dest:
            prayers_at_dest = []
            if s1_dest:
                prayers_at_dest.append(prayer1)
            if s2_dest:
                prayers_at_dest.append(prayer2)
            options.append({
                "option_type": "at_destination",
                "label": "Pray Near Destination",
                "description": (
                    f"{' + '.join(p.title() for p in prayers_at_dest)} "
                    f"{'are' if len(prayers_at_dest) > 1 else 'is'} still active when you arrive."
                ),
                "prayers": prayers_at_dest,
                "combination_label": "Jam' Taqdeem" if len(prayers_at_dest) > 1 and s1_dest else None,
                "stops": [],
                "feasible": True,
                "note": "No stop needed — find a mosque near your destination.",
            })

    if not options:
        options.append({
            "option_type": "no_option",
            "label": "No Mosque Options Found",
            "description": f"No mosques found along the route for {prayer1.title()} or {prayer2.title()}.",
            "prayers": [prayer1, prayer2],
            "combination_label": None,
            "stops": [],
            "feasible": False,
            "note": "You may need to pray at a rest stop or clean roadside area.",
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
        return a1 <= b2 and a2 >= b1

    # Check in the direct frame, and also with trip shifted +1 day (for post-midnight trips
    # that fall within a prayer window that started the previous evening, like Isha at 9 PM
    # and a trip at 12:46 AM).
    return (
        _overlaps(adhan_m, period_end_m, dep_min, arr_min) or
        _overlaps(adhan_m, period_end_m, dep_min + 1440, arr_min + 1440)
    )


def _pair_relevant(p1: str, p2: str, schedule: dict, dep_min: int, arr_min: int) -> bool:
    """True if either prayer in the pair overlaps the trip window."""
    return (
        _prayer_overlaps_trip(p1, schedule, dep_min, arr_min) or
        _prayer_overlaps_trip(p2, schedule, dep_min, arr_min)
    )


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

    # 1. Get Mapbox route
    route = await get_mapbox_route(origin_lat, origin_lng, dest_lat, dest_lng)
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
    try:
        from timezonefinder import TimezoneFinder
        dest_tz_str = TimezoneFinder().timezone_at(lat=dest_lat, lng=dest_lng) or timezone_str
        dest_ptz = pytz.timezone(dest_tz_str)
        dest_offset_h = dest_ptz.utcoffset(departure_dt.replace(tzinfo=None)).total_seconds() / 3600
    except Exception:
        dest_tz_str = timezone_str
        dest_offset_h = offset_h
    dest_calc = calculate_prayer_times(dest_lat, dest_lng, today, timezone_offset=dest_offset_h)
    dest_schedule = {**(dest_calc or {}), **estimate_iqama_times(dest_calc or {})}

    # 4. Find mosques along route
    route_mosques = await find_route_mosques(db, checkpoints, departure_dt)

    # 5. Build prayer pair plans — only for pairs relevant to the trip window
    prayer_pairs = []
    dep_local = departure_dt.astimezone(tz_zone)
    arr_local = arrival_dt.astimezone(tz_zone)
    dep_min = dep_local.hour * 60 + dep_local.minute
    arr_min = arr_local.hour * 60 + arr_local.minute

    for p1, p2 in [("dhuhr", "asr"), ("maghrib", "isha")]:
        if not _pair_relevant(p1, p2, origin_schedule, dep_min, arr_min):
            continue
        plan = build_combination_plan(
            p1, p2, origin_schedule, route_mosques,
            departure_dt, arrival_dt, dest_schedule, timezone_str,
            trip_mode=trip_mode,
        )
        prayer_pairs.append(plan)

    # Fajr (standalone — only if trip overlaps the Fajr prayer window)
    if _prayer_overlaps_trip("fajr", origin_schedule, dep_min, arr_min):
        fajr_adhan = origin_schedule.get("fajr_adhan")
        fajr_options = []
        best_fajr = None
        for m in sorted(route_mosques, key=lambda x: x["minutes_into_trip"]):
            s = prayer_status_at_arrival("fajr", m["schedule"], m["local_arrival_minutes"])
            if s:
                best_fajr = (_make_stop(m, "fajr", s), m)
                break
        if best_fajr:
            stop, m = best_fajr
            fajr_options.append({
                "option_type": "stop_for_fajr",
                "label": "Stop for Fajr",
                "description": f"Stop at {m['name']} ({m['detour_minutes']} min detour) for Fajr.",
                "prayers": ["fajr"],
                "combination_label": None,
                "stops": [stop],
                "feasible": True,
                "note": f"Fajr at {fajr_adhan}. {m['name']} is {m['detour_minutes']} min off route.",
            })
        else:
            fajr_options.append({
                "option_type": "no_option",
                "label": "Fajr — No Mosque Found",
                "description": "No mosque found along the route for Fajr. Find a clean rest stop.",
                "prayers": ["fajr"],
                "combination_label": None,
                "stops": [],
                "feasible": False,
                "note": None,
            })
        prayer_pairs.insert(0, {
            "pair": "fajr",
            "label": "Fajr",
            "emoji": "🌅",
            "options": fajr_options,
        })

    return {
        "route": {
            "distance_meters": route.get("distance", 0),
            "duration_minutes": round(route.get("duration", 0) / 60),
            "origin_name": origin_name,
            "destination_name": destination_name,
        },
        "prayer_pairs": prayer_pairs,
        "departure_time": departure_dt.isoformat(),
        "estimated_arrival_time": arrival_dt.isoformat(),
    }
