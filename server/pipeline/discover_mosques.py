"""
Google Places Mosque Discovery
================================
Searches for mosques across US and Canada using a grid of circles.

Strategy:
- Focus on urban/suburban areas (where mosques exist)
- Use Census-designated urban area centers + state capitals
- 25km radius per search circle (max 50km, but 25km gives better coverage)
- Each circle returns up to 60 mosques (3 pages of 20)
- Deduplicate against existing DB by place_id and lat/lng proximity

Cost:
- Nearby Search: $0.032 per call (legacy pricing with $200 free credit)
- 3 pages per circle × N circles = 3N API calls
- Estimated: ~500 circles × 3 pages = 1,500 calls = ~$48
- With $200 free monthly credit: effectively free if < 6,250 calls

Usage:
    python -m pipeline.discover_mosques --dry-run          # estimate queries, don't call API
    python -m pipeline.discover_mosques --region northeast  # just NE states
    python -m pipeline.discover_mosques --all               # full US+Canada
    python -m pipeline.discover_mosques --state CA           # just California
"""

import asyncio
import argparse
import json
import logging
import os
import sys
import time
from math import radians, sin, cos, sqrt, atan2
from typing import Optional

import httpx
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()

# Google API key
GOOGLE_KEY = os.environ.get("GOOGLE_PLACES_API_KEY") or settings.google_places_api_key or ""
if not GOOGLE_KEY:
    # Try the client key as fallback
    GOOGLE_KEY = "AIzaSyDRo0q7GrAfAu1hyUCzkhn5lJ1R06IY2u8"

SEARCH_RADIUS = 25000  # 25km per circle
SEARCH_TYPE = "mosque"

# ---------------------------------------------------------------------------
# US + Canada population centers (cities with Muslim communities)
# Each entry: (name, lat, lng, radius_override_km)
# Major metros get 50km radius, smaller cities get 25km
# ---------------------------------------------------------------------------

SEARCH_GRID = [
    # === US NORTHEAST ===
    ("New York City", 40.7128, -74.0060, 40000),
    ("Newark NJ", 40.7357, -74.1724, 25000),
    ("Jersey City", 40.7178, -74.0431, 20000),
    ("Long Island", 40.7891, -73.1350, 30000),
    ("Philadelphia", 39.9526, -75.1652, 35000),
    ("Boston", 42.3601, -71.0589, 30000),
    ("Hartford CT", 41.7658, -72.6734, 25000),
    ("Providence RI", 41.8240, -71.4128, 25000),
    ("New Haven CT", 41.3083, -72.9279, 20000),
    ("Albany NY", 42.6526, -73.7562, 25000),
    ("Buffalo NY", 42.8864, -78.8784, 25000),
    ("Rochester NY", 43.1566, -77.6088, 25000),
    ("Syracuse NY", 43.0481, -76.1474, 25000),
    ("Pittsburgh", 40.4406, -79.9959, 30000),

    # === US SOUTHEAST ===
    ("Washington DC", 38.9072, -77.0369, 40000),
    ("Baltimore", 39.2904, -76.6122, 30000),
    ("Richmond VA", 37.5407, -77.4360, 25000),
    ("Virginia Beach", 36.8529, -75.9780, 25000),
    ("Charlotte NC", 35.2271, -80.8431, 30000),
    ("Raleigh NC", 35.7796, -78.6382, 25000),
    ("Atlanta", 33.7490, -84.3880, 40000),
    ("Miami", 25.7617, -80.1918, 35000),
    ("Tampa", 27.9506, -82.4572, 30000),
    ("Orlando", 28.5383, -81.3792, 30000),
    ("Jacksonville FL", 30.3322, -81.6557, 25000),
    ("Nashville", 36.1627, -86.7816, 25000),
    ("Memphis", 35.1495, -90.0490, 25000),
    ("Birmingham AL", 33.5207, -86.8025, 25000),
    ("New Orleans", 29.9511, -90.0715, 25000),
    ("Columbia SC", 34.0007, -81.0348, 25000),
    ("Charleston SC", 32.7765, -79.9311, 25000),

    # === US MIDWEST ===
    ("Chicago", 41.8781, -87.6298, 45000),
    ("Detroit", 42.3314, -83.0458, 35000),
    ("Dearborn MI", 42.3223, -83.1763, 15000),
    ("Minneapolis", 44.9778, -93.2650, 30000),
    ("Milwaukee", 43.0389, -87.9065, 25000),
    ("Columbus OH", 39.9612, -82.9988, 30000),
    ("Cleveland", 41.4993, -81.6944, 25000),
    ("Cincinnati", 39.1031, -84.5120, 25000),
    ("Indianapolis", 39.7684, -86.1581, 30000),
    ("St Louis", 38.6270, -90.1994, 30000),
    ("Kansas City", 39.0997, -94.5786, 25000),
    ("Omaha", 41.2565, -95.9345, 25000),
    ("Des Moines", 41.5868, -93.6250, 25000),
    ("Madison WI", 43.0731, -89.4012, 25000),
    ("Ann Arbor MI", 42.2808, -83.7430, 20000),

    # === US SOUTH ===
    ("Houston", 29.7604, -95.3698, 50000),
    ("Dallas", 32.7767, -96.7970, 40000),
    ("Austin", 30.2672, -97.7431, 30000),
    ("San Antonio", 29.4241, -98.4936, 30000),
    ("Fort Worth", 32.7555, -97.3308, 25000),
    ("El Paso", 31.7619, -106.4850, 25000),
    ("McAllen TX", 26.2034, -98.2300, 25000),
    ("Oklahoma City", 35.4676, -97.5164, 25000),
    ("Tulsa", 36.1540, -95.9928, 25000),
    ("Little Rock", 34.7465, -92.2896, 25000),
    ("Baton Rouge", 30.4515, -91.1871, 25000),

    # === US WEST ===
    ("Los Angeles", 34.0522, -118.2437, 50000),
    ("San Diego", 32.7157, -117.1611, 30000),
    ("San Francisco", 37.7749, -122.4194, 30000),
    ("San Jose", 37.3382, -121.8863, 25000),
    ("Sacramento", 38.5816, -121.4944, 25000),
    ("Fresno", 36.7378, -119.7871, 25000),
    ("Bakersfield", 35.3733, -119.0187, 25000),
    ("Orange County CA", 33.7175, -117.8311, 30000),
    ("Riverside CA", 33.9806, -117.3755, 25000),
    ("Seattle", 47.6062, -122.3321, 35000),
    ("Portland OR", 45.5152, -122.6784, 30000),
    ("Phoenix", 33.4484, -112.0740, 40000),
    ("Tucson", 32.2226, -110.9747, 25000),
    ("Las Vegas", 36.1699, -115.1398, 30000),
    ("Denver", 39.7392, -104.9903, 30000),
    ("Salt Lake City", 40.7608, -111.8910, 25000),
    ("Boise", 43.6150, -116.2023, 25000),
    ("Albuquerque", 35.0844, -106.6504, 25000),
    ("Honolulu", 21.3069, -157.8583, 25000),

    # === CANADA ===
    ("Toronto", 43.6532, -79.3832, 45000),
    ("Mississauga ON", 43.5890, -79.6441, 25000),
    ("Montreal", 45.5017, -73.5673, 40000),
    ("Vancouver", 49.2827, -123.1207, 35000),
    ("Calgary", 51.0447, -114.0719, 30000),
    ("Edmonton", 53.5461, -113.4938, 30000),
    ("Ottawa", 45.4215, -75.6972, 30000),
    ("Winnipeg", 49.8951, -97.1384, 25000),
    ("Hamilton ON", 43.2557, -79.8711, 20000),
    ("London ON", 42.9849, -81.2453, 20000),
    ("Kitchener ON", 43.4516, -80.4925, 20000),
    ("Halifax", 44.6488, -63.5752, 25000),
    ("Regina", 50.4452, -104.6189, 25000),
    ("Saskatoon", 52.1332, -106.6700, 25000),
    ("Quebec City", 46.8139, -71.2080, 25000),
    ("Surrey BC", 49.1913, -122.8490, 20000),
    ("Brampton ON", 43.7315, -79.7624, 20000),
]


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    dlat, dlng = radians(lat2-lat1), radians(lng2-lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def get_db():
    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    sync_url = db_url.replace("+asyncpg", "+psycopg2")
    if "psycopg2" not in sync_url:
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(sync_url)


async def search_circle(lat: float, lng: float, radius: int, api_key: str) -> list[dict]:
    """Search one circle for mosques. Returns up to 60 results (3 pages)."""
    results = []
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "type": SEARCH_TYPE,
        "key": api_key,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        for page in range(3):  # max 3 pages
            resp = await client.get(url, params=params)
            data = resp.json()

            if data.get("status") not in ("OK", "ZERO_RESULTS"):
                logger.warning(f"  API error: {data.get('status')} — {data.get('error_message', '')}")
                break

            for place in data.get("results", []):
                loc = place.get("geometry", {}).get("location", {})
                results.append({
                    "google_place_id": place.get("place_id"),
                    "name": place.get("name"),
                    "lat": loc.get("lat"),
                    "lng": loc.get("lng"),
                    "address": place.get("vicinity"),
                    "phone": place.get("international_phone_number"),
                    "rating": place.get("rating"),
                    "user_ratings_total": place.get("user_ratings_total"),
                    "business_status": place.get("business_status"),
                    "types": place.get("types", []),
                })

            next_token = data.get("next_page_token")
            if not next_token:
                break

            # Google requires a short delay before using next_page_token
            await asyncio.sleep(2)
            params = {"pagetoken": next_token, "key": api_key}

    return results


def is_duplicate(place: dict, existing_mosques: list[dict], threshold_km: float = 0.3) -> Optional[str]:
    """Check if this place already exists in our DB. Returns existing mosque_id if duplicate."""
    # Check by google_place_id first (exact match)
    for m in existing_mosques:
        if m.get("google_place_id") == place["google_place_id"]:
            return m["id"]

    # Check by proximity (within 300m)
    for m in existing_mosques:
        dist = haversine_km(place["lat"], place["lng"], m["lat"], m["lng"])
        if dist < threshold_km:
            return m["id"]

    return None


async def run(args):
    if not GOOGLE_KEY:
        logger.error("No Google API key found. Set GOOGLE_PLACES_API_KEY in .env")
        return

    engine = get_db()

    # Load existing mosques for deduplication
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id::text, name, lat, lng, google_place_id FROM mosques WHERE is_active"
        )).fetchall()
        existing = [{"id": r[0], "name": r[1], "lat": float(r[2]) if r[2] else 0,
                     "lng": float(r[3]) if r[3] else 0,
                     "google_place_id": r[4]} for r in rows]

    logger.info(f"Existing mosques: {len(existing)}")

    # Filter grid by region/state if specified
    grid = SEARCH_GRID
    if args.state:
        grid = [(n,la,ln,r) for n,la,ln,r in grid if args.state.upper() in n.upper()]
    if args.region:
        region_map = {
            "northeast": ["New York", "Newark", "Jersey", "Long Island", "Philadelphia", "Boston",
                           "Hartford", "Providence", "New Haven", "Albany", "Buffalo", "Rochester",
                           "Syracuse", "Pittsburgh"],
            "southeast": ["Washington", "Baltimore", "Richmond", "Virginia", "Charlotte", "Raleigh",
                           "Atlanta", "Miami", "Tampa", "Orlando", "Jacksonville", "Nashville",
                           "Memphis", "Birmingham", "New Orleans", "Columbia", "Charleston"],
            "midwest": ["Chicago", "Detroit", "Dearborn", "Minneapolis", "Milwaukee", "Columbus",
                         "Cleveland", "Cincinnati", "Indianapolis", "St Louis", "Kansas", "Omaha",
                         "Des Moines", "Madison", "Ann Arbor"],
            "south": ["Houston", "Dallas", "Austin", "San Antonio", "Fort Worth", "El Paso",
                       "McAllen", "Oklahoma", "Tulsa", "Little Rock", "Baton Rouge"],
            "west": ["Los Angeles", "San Diego", "San Francisco", "San Jose", "Sacramento",
                      "Fresno", "Bakersfield", "Orange County", "Riverside", "Seattle", "Portland",
                      "Phoenix", "Tucson", "Las Vegas", "Denver", "Salt Lake", "Boise",
                      "Albuquerque", "Honolulu"],
            "canada": ["Toronto", "Mississauga", "Montreal", "Vancouver", "Calgary", "Edmonton",
                        "Ottawa", "Winnipeg", "Hamilton", "London ON", "Kitchener", "Halifax",
                        "Regina", "Saskatoon", "Quebec", "Surrey", "Brampton"],
        }
        region_cities = region_map.get(args.region.lower(), [])
        grid = [(n,la,ln,r) for n,la,ln,r in grid if any(c in n for c in region_cities)]

    if args.dry_run:
        total_calls = len(grid) * 3  # 3 pages per circle
        cost = total_calls * 0.032
        logger.info(f"DRY RUN — {len(grid)} circles × 3 pages = {total_calls} API calls")
        logger.info(f"Estimated cost: ${cost:.2f}")
        logger.info(f"With $200 free credit: {'FREE' if cost < 200 else f'${cost-200:.2f}'}")
        for name, lat, lng, radius in grid:
            logger.info(f"  {name}: ({lat:.2f}, {lng:.2f}) r={radius/1000:.0f}km")
        return

    # Run searches
    all_places = []
    seen_place_ids = set()
    api_calls = 0

    for i, (name, lat, lng, radius) in enumerate(grid):
        logger.info(f"\n[{i+1}/{len(grid)}] Searching: {name} (r={radius/1000:.0f}km)")
        places = await search_circle(lat, lng, radius, GOOGLE_KEY)
        api_calls += min(3, (len(places) // 20) + 1)

        new_in_circle = 0
        for p in places:
            if p["google_place_id"] in seen_place_ids:
                continue
            seen_place_ids.add(p["google_place_id"])
            all_places.append(p)
            new_in_circle += 1

        logger.info(f"  Found {len(places)} results, {new_in_circle} new unique")
        await asyncio.sleep(1)  # rate limit

    # Deduplicate against existing DB
    new_mosques = []
    updated_mosques = []

    for place in all_places:
        existing_id = is_duplicate(place, existing)
        if existing_id:
            # Update existing mosque with Google data (phone, place_id, etc.)
            updated_mosques.append({**place, "existing_id": existing_id})
        else:
            new_mosques.append(place)

    logger.info(f"\n{'='*60}")
    logger.info(f"DISCOVERY RESULTS")
    logger.info(f"  API calls: {api_calls} (est. cost: ${api_calls * 0.032:.2f})")
    logger.info(f"  Total places found: {len(all_places)}")
    logger.info(f"  Already in DB: {len(updated_mosques)}")
    logger.info(f"  NEW mosques: {len(new_mosques)}")

    if args.save:
        # Save new mosques to DB
        with engine.begin() as conn:
            for m in new_mosques:
                try:
                    conn.execute(text("""
                        INSERT INTO mosques (id, name, lat, lng, address, phone,
                            google_place_id, is_active, created_at, updated_at)
                        VALUES (gen_random_uuid(), :name, :lat, :lng, :addr, :phone,
                            :gpid, true, now(), now())
                        ON CONFLICT (google_place_id) DO NOTHING
                    """), {
                        "name": m["name"], "lat": m["lat"], "lng": m["lng"],
                        "addr": m["address"], "phone": m["phone"],
                        "gpid": m["google_place_id"],
                    })
                except Exception as e:
                    logger.debug(f"  Insert failed for {m['name']}: {e}")

            # Update existing mosques with Google data
            for m in updated_mosques:
                updates = []
                vals = {"mid": m["existing_id"]}
                if m.get("phone") and m["phone"]:
                    updates.append("phone = COALESCE(phone, :phone)")
                    vals["phone"] = m["phone"]
                if m.get("google_place_id"):
                    updates.append("google_place_id = COALESCE(google_place_id, :gpid)")
                    vals["gpid"] = m["google_place_id"]
                if updates:
                    conn.execute(text(
                        f"UPDATE mosques SET {', '.join(updates)}, updated_at = now() WHERE id = :mid"
                    ), vals)

        logger.info(f"  Saved {len(new_mosques)} new + updated {len(updated_mosques)} existing")

        # Also create scraping_jobs for new mosques that have websites
        # (we don't have websites from Google — would need Place Details API for that)

    else:
        logger.info(f"\n  Run with --save to write to database")
        logger.info(f"  Sample new mosques:")
        for m in new_mosques[:10]:
            logger.info(f"    {m['name']} — {m['address']} ({m['lat']:.4f}, {m['lng']:.4f})")


def main():
    parser = argparse.ArgumentParser(description="Discover mosques via Google Places API")
    parser.add_argument("--dry-run", action="store_true", help="Just estimate cost, don't call API")
    parser.add_argument("--all", action="store_true", help="Search all US+Canada")
    parser.add_argument("--region", type=str, help="Region: northeast, southeast, midwest, south, west, canada")
    parser.add_argument("--state", type=str, help="Filter by state/province name")
    parser.add_argument("--save", action="store_true", help="Save results to database")
    args = parser.parse_args()

    if not any([args.dry_run, args.all, args.region, args.state]):
        parser.print_help()
        sys.exit(1)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
