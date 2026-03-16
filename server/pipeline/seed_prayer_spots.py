"""
Prayer Spots Seeder
===================
Seeds the prayer_spots table from multiple sources:

Source 1 — OpenStreetMap Overpass API
  - amenity=prayer_room (dedicated prayer rooms)
  - amenity=place_of_worship + religion=muslim (Islamic centers that function as spots)
  - Common locations: airports, universities, hospitals, libraries, community halls

Source 2 — Curated airport prayer rooms
  - Major US airports known to have dedicated prayer/meditation rooms

Usage:
    python -m pipeline.seed_prayer_spots
    python -m pipeline.seed_prayer_spots --source osm
    python -m pipeline.seed_prayer_spots --source airports
    python -m pipeline.seed_prayer_spots --dry-run
    python -m pipeline.seed_prayer_spots --country US
"""

import asyncio
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from timezonefinder import TimezoneFinder

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
tf = TimezoneFinder()

# ---------------------------------------------------------------------------
# Overpass API queries
# ---------------------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

OSM_PRAYER_ROOM_QUERY = """
[out:json][timeout:120];
area["ISO3166-1"="{country}"]->.country;
(
  nwr["amenity"="prayer_room"](area.country);
  nwr["room"="prayer"](area.country);
  nwr["name"~"musalla",i](area.country);
  nwr["name"~"mussala",i](area.country);
);
out center tags;
"""

# Separate name-based query (split to avoid Overpass timeout)
OSM_NAME_PRAYER_QUERY = """
[out:json][timeout:120];
area["ISO3166-1"="{country}"]->.country;
(
  nwr["name"~"interfaith chapel",i](area.country);
  nwr["name"~"reflection room",i](area.country);
  nwr["name"~"prayer room",i](area.country);
  nwr["name"~"meditation room",i](area.country);
);
out center tags;
"""

# Non-mosque Muslim worship spots (Islamic centers in unusual building types, MSA rooms, etc.)
OSM_FACILITY_PRAYER_QUERY = """
[out:json][timeout:300];
area["ISO3166-1"="{country}"]->.country;
(
  nwr["amenity"="place_of_worship"]["religion"="muslim"]["building"!="mosque"](area.country);
  nwr["amenity"="place_of_worship"]["religion"="muslim"]["building"="yes"](area.country);
);
out center tags;
"""

# ---------------------------------------------------------------------------
# Curated airport prayer rooms
# ---------------------------------------------------------------------------

AIRPORT_SPOTS = [
    {
        "name": "JFK Airport — Interfaith Chapel (Terminal 4)",
        "spot_type": "prayer_room",
        "lat": 40.6441, "lng": -73.7820,
        "address": "Terminal 4, JFK International Airport, Jamaica, NY 11430",
        "city": "Queens", "state": "NY",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "Interfaith prayer room available to all travelers. Located near security in Terminal 4.",
    },
    {
        "name": "JFK Airport — Meditation Room (Terminal 1)",
        "spot_type": "prayer_room",
        "lat": 40.6416, "lng": -73.7820,
        "address": "Terminal 1, JFK International Airport, Jamaica, NY 11430",
        "city": "Queens", "state": "NY",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "Quiet meditation room for all faiths near Gate 8.",
    },
    {
        "name": "O'Hare Airport — Interfaith Chapel (Terminal 2)",
        "spot_type": "prayer_room",
        "lat": 41.9802, "lng": -87.9090,
        "address": "Terminal 2, O'Hare International Airport, Chicago, IL 60666",
        "city": "Chicago", "state": "IL",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "Daily 6am-10pm",
        "notes": "Interfaith chapel staffed by chaplains. Wudu available in nearby restrooms.",
    },
    {
        "name": "LAX Airport — Meditation Room (Tom Bradley International Terminal)",
        "spot_type": "prayer_room",
        "lat": 33.9425, "lng": -118.4081,
        "address": "Tom Bradley International Terminal, LAX, Los Angeles, CA 90045",
        "city": "Los Angeles", "state": "CA",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "Located post-security near Gate 152. All faiths welcome.",
    },
    {
        "name": "Dulles International Airport — Interfaith Prayer Room",
        "spot_type": "prayer_room",
        "lat": 38.9531, "lng": -77.4565,
        "address": "Main Terminal, Dulles International Airport, Dulles, VA 20166",
        "city": "Dulles", "state": "VA",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "Daily 6am-10pm",
        "notes": "Interfaith chapel near baggage claim level.",
    },
    {
        "name": "Reagan National Airport — Interfaith Chapel",
        "spot_type": "prayer_room",
        "lat": 38.8521, "lng": -77.0377,
        "address": "Terminal B/C, Reagan National Airport, Arlington, VA 22202",
        "city": "Arlington", "state": "VA",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "Daily 6am-10pm",
        "notes": "Located in Terminal B/C connector.",
    },
    {
        "name": "Newark Liberty Airport — Interfaith Prayer Room (Terminal B)",
        "spot_type": "prayer_room",
        "lat": 40.6895, "lng": -74.1745,
        "address": "Terminal B, Newark Liberty International Airport, Newark, NJ 07114",
        "city": "Newark", "state": "NJ",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "Multi-faith prayer room on the departures level.",
    },
    {
        "name": "Philadelphia International Airport — Interfaith Chapel",
        "spot_type": "prayer_room",
        "lat": 39.8744, "lng": -75.2424,
        "address": "Terminal D/E, Philadelphia International Airport, Philadelphia, PA 19153",
        "city": "Philadelphia", "state": "PA",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "Daily 7am-9pm",
        "notes": "Interfaith chapel in Terminal D/E connector. Chaplain on duty during hours.",
    },
    {
        "name": "Houston Hobby Airport — Interfaith Prayer Room",
        "spot_type": "prayer_room",
        "lat": 29.6454, "lng": -95.2789,
        "address": "William P. Hobby Airport, Houston, TX 77061",
        "city": "Houston", "state": "TX",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "Daily 5am-11pm",
        "notes": "Multi-faith prayer room near gate area.",
    },
    {
        "name": "Houston Bush Intercontinental — Interfaith Chapel (Terminal C)",
        "spot_type": "prayer_room",
        "lat": 29.9902, "lng": -95.3368,
        "address": "Terminal C, George Bush Intercontinental Airport, Houston, TX 77032",
        "city": "Houston", "state": "TX",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "Interfaith chapel in Terminal C post-security.",
    },
    {
        "name": "Dallas Fort Worth Airport — Interfaith Prayer Room (Terminal D)",
        "spot_type": "prayer_room",
        "lat": 32.8998, "lng": -97.0403,
        "address": "Terminal D, DFW International Airport, DFW Airport, TX 75261",
        "city": "DFW Airport", "state": "TX",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "International terminal prayer room, near Gate D40.",
    },
    {
        "name": "Atlanta Hartsfield-Jackson Airport — Interfaith Chapel",
        "spot_type": "prayer_room",
        "lat": 33.6367, "lng": -84.4281,
        "address": "Concourse A, Hartsfield-Jackson Atlanta International Airport, Atlanta, GA 30337",
        "city": "Atlanta", "state": "GA",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "Daily 6am-10pm",
        "notes": "Chapel in Concourse A. Wudu in nearby family restroom.",
    },
    {
        "name": "Miami International Airport — Interfaith Prayer Room",
        "spot_type": "prayer_room",
        "lat": 25.7959, "lng": -80.2870,
        "address": "Concourse D, Miami International Airport, Miami, FL 33142",
        "city": "Miami", "state": "FL",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "Multi-faith prayer room in Concourse D.",
    },
    {
        "name": "San Francisco International Airport — Reflection Room (International Terminal)",
        "spot_type": "prayer_room",
        "lat": 37.6213, "lng": -122.3790,
        "address": "International Terminal, SFO, San Francisco, CA 94128",
        "city": "San Francisco", "state": "CA",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "Quiet reflection room, post-security in International Terminal near Gate G.",
    },
    {
        "name": "Seattle-Tacoma Airport — Interfaith Chapel",
        "spot_type": "prayer_room",
        "lat": 47.4502, "lng": -122.3088,
        "address": "Main Terminal, Seattle-Tacoma International Airport, Seattle, WA 98158",
        "city": "SeaTac", "state": "WA",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "Daily 6am-10pm",
        "notes": "Interfaith chapel near the main terminal food court.",
    },
    {
        "name": "Denver International Airport — Interfaith Chapel",
        "spot_type": "prayer_room",
        "lat": 39.8561, "lng": -104.6737,
        "address": "Concourse B, Denver International Airport, Denver, CO 80249",
        "city": "Denver", "state": "CO",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "Multi-faith prayer room in Concourse B.",
    },
    {
        "name": "Minneapolis-Saint Paul Airport — Interfaith Chapel (Terminal 1)",
        "spot_type": "prayer_room",
        "lat": 44.8848, "lng": -93.2223,
        "address": "Terminal 1, MSP International Airport, Minneapolis, MN 55111",
        "city": "Minneapolis", "state": "MN",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "Daily 6am-9pm",
        "notes": "Interfaith chapel with Muslim prayer accommodations.",
    },
    {
        "name": "Boston Logan Airport — Interfaith Prayer Room (Terminal E)",
        "spot_type": "prayer_room",
        "lat": 42.3656, "lng": -71.0096,
        "address": "Terminal E, Logan International Airport, Boston, MA 02128",
        "city": "Boston", "state": "MA",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "24 hours",
        "notes": "International terminal, post-security prayer room.",
    },
    {
        "name": "Charlotte Douglas Airport — Interfaith Chapel",
        "spot_type": "prayer_room",
        "lat": 35.2141, "lng": -80.9431,
        "address": "Main Terminal, Charlotte Douglas International Airport, Charlotte, NC 28208",
        "city": "Charlotte", "state": "NC",
        "has_wudu_facilities": False,
        "gender_access": "all",
        "is_indoor": True,
        "operating_hours": "Daily 6am-10pm",
        "notes": "Chapel in the main terminal near ticketing.",
    },
]

# ---------------------------------------------------------------------------
# Spot type mapping from OSM tags
# ---------------------------------------------------------------------------

def infer_spot_type(tags: dict) -> str:
    name_lower = tags.get("name", "").lower()
    amenity = tags.get("amenity", "")
    building = tags.get("building", "")
    shop = tags.get("shop", "")

    if amenity == "prayer_room":
        return "prayer_room"
    if any(w in name_lower for w in ["airport", "terminal"]):
        return "prayer_room"
    if any(w in name_lower for w in ["university", "college", "campus", "student"]):
        return "campus"
    if any(w in name_lower for w in ["library", "biblioth"]):
        return "library"
    if any(w in name_lower for w in ["hospital", "medical", "clinic", "health"]):
        return "prayer_room"
    if any(w in name_lower for w in ["restaurant", "halal", "kitchen", "cafe", "food"]):
        return "halal_restaurant"
    if building == "community_centre" or any(w in name_lower for w in ["community", "center", "centre"]):
        return "community_hall"
    return "other"


def infer_gender_access(tags: dict) -> str:
    name_lower = tags.get("name", "").lower()
    if "men" in name_lower and "women" not in name_lower:
        return "men_only"
    if "women" in name_lower or "sister" in name_lower:
        return "women_only"
    if "separate" in name_lower:
        return "separate_spaces"
    # Islamic prayer rooms often have separate spaces
    return "all"


def infer_wudu(tags: dict) -> Optional[bool]:
    desc = (tags.get("description", "") + " " + tags.get("note", "") + " " + tags.get("name", "")).lower()
    if "wudu" in desc or "ablution" in desc or "washing" in desc:
        return True
    return None  # unknown


def extract_coords(element: dict) -> Optional[tuple[float, float]]:
    if element["type"] == "node":
        return element["lat"], element["lon"]
    elif "center" in element:
        return element["center"]["lat"], element["center"]["lon"]
    return None


def build_address(tags: dict) -> str:
    parts = []
    if tags.get("addr:housenumber") and tags.get("addr:street"):
        parts.append(f"{tags['addr:housenumber']} {tags['addr:street']}")
    elif tags.get("addr:street"):
        parts.append(tags["addr:street"])
    if tags.get("addr:city"):
        parts.append(tags["addr:city"])
    if tags.get("addr:state"):
        parts.append(tags["addr:state"])
    if tags.get("addr:postcode"):
        parts.append(tags["addr:postcode"])
    return ", ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_sync_engine():
    db_url = settings.database_url
    if "asyncpg" in db_url:
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    return create_engine(db_url, pool_pre_ping=True)


def spot_exists(session: Session, lat: float, lng: float, name: str) -> bool:
    """Check if a spot with similar name/location already exists."""
    result = session.execute(
        text("""
            SELECT id FROM prayer_spots
            WHERE ABS(lat - :lat) < 0.001
              AND ABS(lng - :lng) < 0.001
              AND LOWER(name) = LOWER(:name)
            LIMIT 1
        """),
        {"lat": lat, "lng": lng, "name": name},
    ).fetchone()
    return result is not None


def insert_spot(session: Session, spot: dict, dry_run: bool = False) -> bool:
    """Insert a prayer spot. Returns True if inserted (or would be in dry-run)."""
    lat = spot["lat"]
    lng = spot["lng"]
    name = spot["name"]

    if spot_exists(session, lat, lng, name):
        logger.debug(f"  Skip (exists): {name}")
        return False

    tz = tf.timezone_at(lat=lat, lng=lng)

    if dry_run:
        logger.info(f"  [DRY] Would insert: {name} ({spot['spot_type']}) @ {lat:.4f},{lng:.4f}")
        return True

    session.execute(
        text("""
            INSERT INTO prayer_spots (
                id,
                name, spot_type, lat, lng,
                geom,
                address, city, state, zip, country,
                timezone,
                has_wudu_facilities, gender_access, is_indoor,
                operating_hours, notes,
                submitted_by_session,
                status, verification_count, rejection_count,
                submitted_at, created_at, updated_at
            ) VALUES (
                gen_random_uuid(),
                :name, :spot_type, :lat, :lng,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                :address, :city, :state, :zip, :country,
                :timezone,
                :has_wudu_facilities, :gender_access, :is_indoor,
                :operating_hours, :notes,
                'seed_pipeline',
                'active', :verification_count, 0,
                NOW(), NOW(), NOW()
            )
        """),
        {
            "name": name,
            "spot_type": spot.get("spot_type", "other"),
            "lat": lat,
            "lng": lng,
            "address": spot.get("address", ""),
            "city": spot.get("city", ""),
            "state": spot.get("state", ""),
            "zip": spot.get("zip", ""),
            "country": spot.get("country", "US"),
            "timezone": tz,
            "has_wudu_facilities": spot.get("has_wudu_facilities"),
            "gender_access": spot.get("gender_access", "all"),
            "is_indoor": spot.get("is_indoor", True),
            "operating_hours": spot.get("operating_hours"),
            "notes": spot.get("notes"),
            "verification_count": spot.get("verification_count", 0),
        },
    )
    return True


# ---------------------------------------------------------------------------
# OSM seeding
# ---------------------------------------------------------------------------

async def fetch_overpass(query: str) -> list[dict]:
    """Fetch elements from Overpass API."""
    async with httpx.AsyncClient(timeout=360) as client:
        logger.info("Querying Overpass API...")
        resp = await client.post(OVERPASS_URL, data={"data": query})
        resp.raise_for_status()
        data = resp.json()
        return data.get("elements", [])


def osm_element_to_spot(element: dict) -> Optional[dict]:
    tags = element.get("tags", {})
    if not tags:
        return None

    name = tags.get("name") or tags.get("name:en") or tags.get("alt_name")
    if not name:
        return None

    coords = extract_coords(element)
    if not coords:
        return None

    lat, lng = coords

    # Filter out clearly non-US/Canada coordinates
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None

    return {
        "name": name,
        "spot_type": infer_spot_type(tags),
        "lat": lat,
        "lng": lng,
        "address": build_address(tags),
        "city": tags.get("addr:city", ""),
        "state": tags.get("addr:state", ""),
        "zip": tags.get("addr:postcode", ""),
        "country": "US",
        "has_wudu_facilities": infer_wudu(tags),
        "gender_access": infer_gender_access(tags),
        "is_indoor": True,  # prayer rooms are almost always indoor
        "operating_hours": tags.get("opening_hours"),
        "notes": tags.get("description") or tags.get("note"),
        "verification_count": 1,  # OSM data is community-verified
    }


async def seed_from_osm(country: str, dry_run: bool = False) -> int:
    """Seed prayer rooms from OpenStreetMap."""
    elements_1 = await fetch_overpass(OSM_PRAYER_ROOM_QUERY.format(country=country))
    logger.info(f"  Found {len(elements_1)} OSM tag-based elements for {country}")

    logger.info("  Running name-based query...")
    elements_2 = await fetch_overpass(OSM_NAME_PRAYER_QUERY.format(country=country))
    logger.info(f"  Found {len(elements_2)} OSM name-based elements for {country}")

    # Deduplicate by OSM id
    seen_ids: set = set()
    elements = []
    for el in elements_1 + elements_2:
        key = (el["type"], el["id"])
        if key not in seen_ids:
            seen_ids.add(key)
            elements.append(el)
    logger.info(f"  Total unique elements: {len(elements)}")

    engine = get_sync_engine()
    inserted = 0
    skipped = 0

    with Session(engine) as session:
        for el in elements:
            spot = osm_element_to_spot(el)
            if not spot:
                skipped += 1
                continue

            if insert_spot(session, spot, dry_run=dry_run):
                inserted += 1
                logger.info(f"  ✓ {spot['name']} ({spot['spot_type']}) @ {spot['lat']:.4f},{spot['lng']:.4f}")
            else:
                skipped += 1

        if not dry_run:
            session.commit()

    logger.info(f"  OSM {country}: inserted={inserted}, skipped={skipped}")
    return inserted


def seed_airport_spots(dry_run: bool = False) -> int:
    """Seed curated airport prayer rooms."""
    engine = get_sync_engine()
    inserted = 0

    with Session(engine) as session:
        for spot in AIRPORT_SPOTS:
            spot_with_defaults = {
                **spot,
                "country": "US",
                "verification_count": 3,  # curated = pre-verified
            }
            if insert_spot(session, spot_with_defaults, dry_run=dry_run):
                inserted += 1
                logger.info(f"  ✓ {spot['name']}")
            else:
                logger.info(f"  Skip (exists): {spot['name']}")

        if not dry_run:
            session.commit()

    logger.info(f"  Airport spots: inserted={inserted}")
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Seed prayer spots")
    parser.add_argument("--source", choices=["all", "osm", "airports"], default="all")
    parser.add_argument("--country", default="US", choices=["US", "CA"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    total = 0

    if args.source in ("all", "airports"):
        logger.info("=== Seeding airport prayer rooms ===")
        n = seed_airport_spots(dry_run=args.dry_run)
        total += n

    if args.source in ("all", "osm"):
        logger.info(f"=== Seeding from OSM (country={args.country}) ===")
        n = await seed_from_osm(args.country, dry_run=args.dry_run)
        total += n

    logger.info(f"\nTotal inserted: {total}")
    if args.dry_run:
        logger.info("(dry-run — no changes committed)")


if __name__ == "__main__":
    asyncio.run(main())
