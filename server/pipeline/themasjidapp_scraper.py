"""
TheMasjidApp.org Scraper
=========================
Matches our mosques to themasjidapp.org listings and fetches iqama times.

Their API is open and unauthenticated:
- Search: GET /api/v1/search-node?lat={lat}&lng={lng}&radius=25
- Detail: GET /_next/data/{buildId}/en-us/{slug}.json

Usage:
    python -m pipeline.themasjidapp_scraper --match --limit 100   # match mosques
    python -m pipeline.themasjidapp_scraper --fetch                # fetch iqama for matched
    python -m pipeline.themasjidapp_scraper --all                  # match + fetch all
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from datetime import date, datetime
from difflib import SequenceMatcher

import httpx
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

pg_pass = os.environ.get("POSTGRES_PASSWORD", "cap")
pg_user = os.environ.get("POSTGRES_USER", "cap")
pg_db = os.environ.get("POSTGRES_DB", "catchaprayer")
DB_URL = f"postgresql+psycopg2://{pg_user}:{pg_pass}@db:5432/{pg_db}" if pg_pass != "cap" else None

SEARCH_URL = "https://themasjidapp.org/api/v1/search-node"
BASE_URL = "https://themasjidapp.org"

# How close (in miles) a match must be
MAX_DISTANCE_MILES = 0.5
# Minimum name similarity (0-1)
MIN_NAME_SIMILARITY = 0.4


def name_similarity(a: str, b: str) -> float:
    """Fuzzy name match, ignoring common prefixes."""
    # Normalize
    for prefix in ["masjid ", "mosque ", "islamic center ", "islamic centre ",
                    "the ", "al-", "al ", "masjid al-", "masjid al "]:
        a = a.lower().replace(prefix, "").strip()
        b = b.lower().replace(prefix, "").strip()
    return SequenceMatcher(None, a, b).ratio()


def haversine_miles(lat1, lng1, lat2, lng2):
    """Distance in miles between two points."""
    from math import radians, sin, cos, sqrt, atan2
    R = 3959  # Earth radius in miles
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


async def get_build_id() -> str | None:
    """Extract Next.js buildId from themasjidapp.org homepage."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(BASE_URL)
        match = re.search(r'"buildId":"([^"]+)"', r.text)
        if match:
            return match.group(1)
    return None


async def search_nearby(lat: float, lng: float, radius: int = 25) -> list[dict]:
    """Search themasjidapp for mosques near a point."""
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.get(SEARCH_URL, params={"lat": lat, "lng": lng, "radius": radius})
            if r.status_code == 200:
                data = r.json()
                return data.get("results", [])
        except Exception as e:
            log.debug(f"Search failed: {e}")
    return []


async def fetch_iqama(slug: str, build_id: str) -> dict | None:
    """Fetch iqama schedule for a mosque slug."""
    url = f"{BASE_URL}/_next/data/{build_id}/en-us/{slug}.json"
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.get(url)
            if r.status_code == 200:
                data = r.json()
                props = data.get("pageProps", {})
                return {
                    "iqamas": props.get("iqamas", {}),
                    "azanParams": props.get("azanParams", {}),
                    "events": props.get("events", []),
                }
        except Exception as e:
            log.debug(f"Fetch failed for {slug}: {e}")
    return None


def get_today_iqama(iqamas: dict) -> dict:
    """Extract today's iqama times from the sparse day-of-year map."""
    today = date.today()
    day_of_year = today.timetuple().tm_yday

    # Build up current iqama state by replaying all days up to today
    current = {}
    for day_num in sorted(int(k) for k in iqamas.keys()):
        if day_num > day_of_year:
            break
        day_data = iqamas.get(str(day_num), {})
        current.update(day_data)

    return current


def normalize_12h_to_24h(time_str: str) -> str | None:
    """Convert '6:45 AM' to '06:45'."""
    m = re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)$', time_str.strip())
    if not m:
        return None
    h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ampm == "pm" and h < 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"


async def match_and_fetch(engine, limit: int = None):
    """Match our mosques to themasjidapp and fetch iqama data."""
    build_id = await get_build_id()
    if not build_id:
        log.error("Could not get buildId from themasjidapp.org")
        return

    log.info(f"BuildId: {build_id}")

    # Get our mosques that need data
    with engine.connect() as conn:
        q = """
            SELECT m.id::text, m.name, m.lat, m.lng
            FROM mosques m
            WHERE m.is_active AND m.lat IS NOT NULL
            ORDER BY
                CASE WHEN m.state IN ('NY','CA','TX','IL','NJ','FL','MI','PA','MD','VA','GA','OH','DC','ON','QC','BC','AB') THEN 0 ELSE 1 END,
                random()
        """
        if limit:
            q += f" LIMIT {limit}"
        rows = conn.execute(text(q)).fetchall()
        our_mosques = [{"id": r[0], "name": r[1], "lat": float(r[2]), "lng": float(r[3])} for r in rows]

    log.info(f"Matching {len(our_mosques)} mosques against themasjidapp.org")

    # Group mosques by proximity to avoid redundant API calls
    # Search in batches by unique lat/lng clusters
    searched_points = set()
    tma_mosques = {}  # slug -> {data}
    matched = 0
    fetched = 0
    saved = 0
    today = date.today()

    sem = asyncio.Semaphore(3)  # Rate limit

    for i, mosque in enumerate(our_mosques):
        # Round to 0.1 degree (~7 mile grid) to avoid duplicate searches
        grid_key = (round(mosque["lat"], 1), round(mosque["lng"], 1))
        if grid_key not in searched_points:
            searched_points.add(grid_key)
            async with sem:
                results = await search_nearby(mosque["lat"], mosque["lng"], radius=15)
                for r in results:
                    m = r.get("masjid", {})
                    slug = m.get("slug")
                    if slug and slug not in tma_mosques:
                        tma_mosques[slug] = {
                            "name": m.get("name", ""),
                            "lat": m.get("lat", 0),
                            "lng": m.get("lng", 0),
                            "slug": slug,
                            "id": m.get("id"),
                        }
                await asyncio.sleep(0.5)

        # Try to match this mosque to a themasjidapp listing
        best_match = None
        best_score = 0
        for slug, tma in tma_mosques.items():
            dist = haversine_miles(mosque["lat"], mosque["lng"], tma["lat"], tma["lng"])
            if dist > MAX_DISTANCE_MILES:
                continue
            sim = name_similarity(mosque["name"], tma["name"])
            # Score: weighted combo of name similarity and proximity
            score = sim * 0.7 + (1 - min(dist, 1)) * 0.3
            if score > best_score and sim >= MIN_NAME_SIMILARITY:
                best_score = score
                best_match = tma

        if best_match:
            matched += 1
            # Fetch iqama data
            async with sem:
                detail = await fetch_iqama(best_match["slug"], build_id)
                await asyncio.sleep(0.3)

            if detail and detail.get("iqamas"):
                fetched += 1
                iqama_today = get_today_iqama(detail["iqamas"])
                if iqama_today:
                    # Save to DB
                    _save_iqama(engine, mosque["id"], iqama_today, today)
                    saved += 1

        if (i + 1) % 100 == 0:
            log.info(f"Progress: {i + 1}/{len(our_mosques)} | Matched: {matched} | Fetched: {fetched} | Saved: {saved}")

    log.info(f"\n=== COMPLETE ===")
    log.info(f"Searched: {len(our_mosques)} | TMA mosques found: {len(tma_mosques)}")
    log.info(f"Matched: {matched} | With iqama: {fetched} | Saved: {saved}")


def _save_iqama(engine, mosque_id: str, iqama: dict, today: date):
    """Save iqama times from themasjidapp to our DB."""
    from pipeline.validation import validate_prayer_schedule

    prayer_map = {
        "fajr": "fajr_iqama", "dhuhr": "dhuhr_iqama", "asr": "asr_iqama",
        "maghrib": "maghrib_iqama", "isha": "isha_iqama",
    }

    values = {"mosque_id": mosque_id, "date": today}
    for tma_key, db_col in prayer_map.items():
        time_str = iqama.get(tma_key)
        if time_str:
            normalized = normalize_12h_to_24h(time_str)
            if normalized:
                values[db_col] = normalized
                values[db_col + "_source"] = "themasjidapp"

    if len(values) <= 2:
        return

    # Validate
    flat = {k: v for k, v in values.items() if k not in ("mosque_id", "date") and "_source" not in k}
    vr = validate_prayer_schedule(flat)
    if not vr.valid:
        return

    with engine.begin() as conn:
        # Only update iqama columns (don't overwrite adhan)
        updates = []
        params = {"mid": mosque_id, "dt": today}
        for col, val in values.items():
            if col in ("mosque_id", "date"):
                continue
            updates.append(f"{col} = :{col}")
            params[col] = val

        if updates:
            conn.execute(text(f"""
                UPDATE prayer_schedules SET {', '.join(updates)}
                WHERE mosque_id = CAST(:mid AS uuid) AND date = :dt
            """), params)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Limit mosques to process")
    parser.add_argument("--all", action="store_true", help="Match + fetch all")
    args = parser.parse_args()

    if not DB_URL:
        log.error("No DB connection")
        return

    engine = create_engine(DB_URL)
    asyncio.run(match_and_fetch(engine, limit=args.limit))


if __name__ == "__main__":
    main()
