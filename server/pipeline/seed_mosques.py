"""
Mosque Database Seeder
======================
Downloads all mosques in the US and Canada from OpenStreetMap via the
Overpass API and inserts them into the PostgreSQL database.

Usage:
    python -m pipeline.seed_mosques
    python -m pipeline.seed_mosques --country US
    python -m pipeline.seed_mosques --country CA
    python -m pipeline.seed_mosques --dry-run
"""

import asyncio
import argparse
import logging
import sys
import os
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from timezonefinder import TimezoneFinder

# Add server root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.models import Mosque, ScrapingJob

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
tf = TimezoneFinder()

# --------------------------------------------------------------------------- #
# Overpass queries
# --------------------------------------------------------------------------- #

OVERPASS_QUERY_TEMPLATE = """
[out:json][timeout:600];
area["ISO3166-1"="{country}"]->.country;
(
  nwr["amenity"="place_of_worship"]["religion"="muslim"](area.country);
  nwr["building"="mosque"](area.country);
);
out center tags;
"""

# Separate query to catch mosques tagged by name only (some US mosques lack religion tag)
OVERPASS_NAME_QUERY_TEMPLATE = """
[out:json][timeout:300];
area["ISO3166-1"="{country}"]->.country;
(
  nwr["amenity"="place_of_worship"]["name"~"mosque|masjid|islamic center|muslim",i](area.country);
);
out center tags;
"""

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


# --------------------------------------------------------------------------- #
# Overpass fetcher
# --------------------------------------------------------------------------- #

async def fetch_overpass(query: str, country: str) -> list[dict]:
    """Fetch elements from Overpass API with fallback endpoints."""
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            logger.info(f"Querying Overpass ({endpoint}) for {country}...")
            async with httpx.AsyncClient(timeout=660) as client:
                response = await client.post(endpoint, data={"data": query})
                response.raise_for_status()
                data = response.json()
                elements = data.get("elements", [])
                logger.info(f"  → {len(elements)} elements returned from {endpoint}")
                return elements
        except Exception as e:
            logger.warning(f"  Endpoint {endpoint} failed: {e}")
            continue

    logger.error(f"All Overpass endpoints failed for {country}")
    return []


# --------------------------------------------------------------------------- #
# Element parsing
# --------------------------------------------------------------------------- #

def extract_coords(element: dict) -> Optional[tuple[float, float]]:
    """Extract (lat, lng) from a node, way, or relation element."""
    etype = element.get("type")
    if etype == "node":
        lat = element.get("lat")
        lng = element.get("lon")
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    elif etype in ("way", "relation"):
        center = element.get("center", {})
        lat = center.get("lat")
        lng = center.get("lon")
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    return None


def parse_address(tags: dict) -> dict:
    """Extract address components from OSM tags."""
    housenumber = tags.get("addr:housenumber", "")
    street = tags.get("addr:street", "")
    address = f"{housenumber} {street}".strip() or None

    return {
        "address": address,
        "city": tags.get("addr:city") or tags.get("addr:suburb"),
        "state": tags.get("addr:state") or tags.get("addr:province"),
        "zip": tags.get("addr:postcode"),
    }


def parse_tags(tags: dict) -> dict:
    """Extract all relevant fields from OSM tags."""
    addr = parse_address(tags)

    # Languages spoken: check for language-tagged names
    languages = []
    if tags.get("name:en"):
        languages.append("English")
    if tags.get("name:ar"):
        languages.append("Arabic")
    if tags.get("name:ur"):
        languages.append("Urdu")
    if tags.get("name:tr"):
        languages.append("Turkish")
    if tags.get("name:fr"):
        languages.append("French")

    # Wheelchair
    wheelchair_raw = tags.get("wheelchair", "")
    has_wheelchair = True if wheelchair_raw in ("yes", "designated") else (
        False if wheelchair_raw == "no" else None
    )

    # Parking
    parking_raw = tags.get("parking", "") or tags.get("amenity:parking", "")
    has_parking = True if parking_raw else None

    return {
        "name": tags.get("name") or tags.get("name:en") or "Unknown Mosque",
        "name_arabic": tags.get("name:ar"),
        **addr,
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "website": tags.get("website") or tags.get("contact:website") or tags.get("url"),
        "email": tags.get("email") or tags.get("contact:email"),
        "denomination": tags.get("denomination"),
        "capacity": int(tags["capacity"]) if tags.get("capacity", "").isdigit() else None,
        "has_womens_section": None,  # Rarely in OSM data
        "has_parking": has_parking,
        "wheelchair_accessible": has_wheelchair,
        "languages_spoken": languages if languages else None,
    }


def is_valid_mosque(element: dict, tags: dict) -> bool:
    """Filter out false positives."""
    name = (tags.get("name") or "").lower()

    # Must have a name
    if not name or name == "unknown mosque":
        # Allow if it has religion=muslim explicitly
        if tags.get("religion") != "muslim":
            return False

    # Exclude obvious non-mosques
    exclude_keywords = ["school", "university", "college", "store", "shop",
                        "restaurant", "hotel", "hospital", "cemetery"]
    if any(kw in name for kw in exclude_keywords):
        return False

    return True


# --------------------------------------------------------------------------- #
# Database helpers (sync, for the seeder script)
# --------------------------------------------------------------------------- #

def get_sync_engine():
    """Create a synchronous SQLAlchemy engine for the seeder."""
    # Convert asyncpg URL to psycopg2 URL for sync operations
    db_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    )
    from sqlalchemy import create_engine
    return create_engine(db_url, echo=False)


def upsert_mosque(session: Session, mosque_data: dict, country: str, dry_run: bool) -> tuple[bool, bool]:
    """
    Insert or update a mosque record.
    Returns (was_inserted, was_updated).
    """
    osm_id = mosque_data["osm_id"]
    existing = session.query(Mosque).filter_by(osm_id=osm_id).first()

    if existing:
        # Update fields that OSM might have improved
        updated = False
        for field in ["name", "name_arabic", "phone", "website", "email",
                      "address", "city", "state", "zip", "wheelchair_accessible",
                      "capacity", "denomination", "languages_spoken"]:
            new_val = mosque_data.get(field)
            if new_val is not None and getattr(existing, field) != new_val:
                setattr(existing, field, new_val)
                updated = True
        if not dry_run and updated:
            session.flush()
        return False, updated

    # New mosque
    if not dry_run:
        mosque = Mosque(
            **{k: v for k, v in mosque_data.items()
               if k not in ("osm_type",)},
            country=country,
            is_active=True,
            verified=False,
            places_enriched=False,
        )
        # Set geometry
        from geoalchemy2.functions import ST_SetSRID, ST_MakePoint
        mosque.geom = f"SRID=4326;POINT({mosque_data['lng']} {mosque_data['lat']})"
        session.add(mosque)
        session.flush()

        # Create scraping job (priority=1 for new mosques)
        job = ScrapingJob(
            mosque_id=mosque.id,
            status="pending",
            priority=1 if mosque_data.get("website") else 9,
            next_attempt_at=datetime.utcnow(),
        )
        session.add(job)

    return True, False


# --------------------------------------------------------------------------- #
# Main seeder
# --------------------------------------------------------------------------- #

async def seed_country(country: str, session: Session, dry_run: bool) -> dict:
    """Seed all mosques for a given country code (US or CA)."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Seeding mosques for: {country}")
    logger.info(f"{'='*60}")

    # Fetch from Overpass — religion-tagged mosques
    query1 = OVERPASS_QUERY_TEMPLATE.format(country=country)
    elements1 = await fetch_overpass(query1, f"{country} (religion=muslim)")

    # Fetch name-tagged mosques (catches some that lack religion tag)
    query2 = OVERPASS_NAME_QUERY_TEMPLATE.format(country=country)
    elements2 = await fetch_overpass(query2, f"{country} (name-based)")

    # Deduplicate by OSM ID
    seen_ids = set()
    all_elements = []
    for el in elements1 + elements2:
        osm_key = f"{el['type']}/{el['id']}"
        if osm_key not in seen_ids:
            seen_ids.add(osm_key)
            all_elements.append(el)

    logger.info(f"Total unique elements: {len(all_elements)}")

    stats = {"total": 0, "inserted": 0, "updated": 0, "skipped": 0, "no_coords": 0}

    for element in all_elements:
        stats["total"] += 1
        tags = element.get("tags", {})

        if not is_valid_mosque(element, tags):
            stats["skipped"] += 1
            continue

        coords = extract_coords(element)
        if not coords:
            stats["no_coords"] += 1
            continue

        lat, lng = coords

        # Assign timezone
        tz = tf.timezone_at(lat=lat, lng=lng) or "UTC"

        parsed = parse_tags(tags)
        mosque_data = {
            **parsed,
            "lat": lat,
            "lng": lng,
            "timezone": tz,
            "osm_id": str(element["id"]),
            "osm_type": element["type"],
        }

        try:
            inserted, updated = upsert_mosque(session, mosque_data, country, dry_run)
            if inserted:
                stats["inserted"] += 1
            elif updated:
                stats["updated"] += 1

            if not dry_run and (stats["inserted"] + stats["updated"]) % 100 == 0:
                session.commit()
                logger.info(f"  Progress: {stats['inserted']} inserted, {stats['updated']} updated...")

        except Exception as e:
            logger.error(f"  Error inserting mosque {tags.get('name')}: {e}")
            session.rollback()

    if not dry_run:
        session.commit()

    logger.info(f"\nResults for {country}:")
    logger.info(f"  Total elements:  {stats['total']}")
    logger.info(f"  Inserted:        {stats['inserted']}")
    logger.info(f"  Updated:         {stats['updated']}")
    logger.info(f"  Skipped:         {stats['skipped']}")
    logger.info(f"  No coordinates:  {stats['no_coords']}")

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Seed mosque database from OpenStreetMap")
    parser.add_argument("--country", choices=["US", "CA", "both"], default="both",
                        help="Which country to seed (default: both)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and log without writing to database")
    args = parser.parse_args()

    countries = []
    if args.country in ("US", "both"):
        countries.append("US")
    if args.country in ("CA", "both"):
        countries.append("CA")

    engine = get_sync_engine()

    # Ensure tables exist
    from app.models import Base as ModelBase
    ModelBase.metadata.create_all(engine)

    with Session(engine) as session:
        total_stats = {"inserted": 0, "updated": 0, "skipped": 0}

        for country in countries:
            stats = await seed_country(country, session, args.dry_run)
            total_stats["inserted"] += stats["inserted"]
            total_stats["updated"] += stats["updated"]
            total_stats["skipped"] += stats["skipped"]

    logger.info(f"\n{'='*60}")
    logger.info("SEEDING COMPLETE")
    logger.info(f"  Total inserted: {total_stats['inserted']}")
    logger.info(f"  Total updated:  {total_stats['updated']}")
    logger.info(f"  Total skipped:  {total_stats['skipped']}")
    logger.info(f"{'='*60}")

    if not args.dry_run:
        logger.info("\nRunning deduplication pass...")
        from pipeline.deduplicate_mosques import run_deduplication
        dedup_stats = run_deduplication(dry_run=False)
        logger.info(f"  Pairs scanned: {dedup_stats['scanned']}")
        logger.info(f"  Duplicates merged: {dedup_stats['merged']}")


if __name__ == "__main__":
    asyncio.run(main())
