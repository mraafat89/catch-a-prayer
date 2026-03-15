"""
Google Places Enricher
======================
One-time enrichment of mosque records with website and phone data
from Google Places API. Only runs for mosques missing this data.
Costs ~$0.017 per mosque — run once, not repeatedly.

Usage:
    python -m pipeline.enrich_places
    python -m pipeline.enrich_places --limit 100
    python -m pipeline.enrich_places --dry-run
"""

import asyncio
import argparse
import logging
import sys
import os
import time
from typing import Optional

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.models import Mosque

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()

PLACES_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
PLACES_TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"


async def search_place(client: httpx.AsyncClient, mosque: Mosque) -> Optional[dict]:
    """Search Google Places for a mosque and return the best match."""
    if not settings.google_places_api_key:
        logger.error("GOOGLE_PLACES_API_KEY not set")
        return None

    # Text search: "{name} {city} {state}"
    query_parts = [mosque.name]
    if mosque.city:
        query_parts.append(mosque.city)
    if mosque.state:
        query_parts.append(mosque.state)
    query = " ".join(query_parts)

    try:
        resp = await client.get(PLACES_TEXTSEARCH_URL, params={
            "query": query,
            "location": f"{mosque.lat},{mosque.lng}",
            "radius": 500,
            "key": settings.google_places_api_key,
        })
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])

        if not results:
            return None

        # Verify the top result is close enough (within ~500m)
        for result in results[:3]:
            place_lat = result["geometry"]["location"]["lat"]
            place_lng = result["geometry"]["location"]["lng"]
            dist = _haversine(mosque.lat, mosque.lng, place_lat, place_lng)
            if dist <= 0.5:  # 500m
                return result

        return None

    except Exception as e:
        logger.error(f"Places search failed for {mosque.name}: {e}")
        return None


async def get_place_details(client: httpx.AsyncClient, place_id: str) -> dict:
    """Get website and phone from Google Place Details."""
    try:
        resp = await client.get(PLACES_DETAILS_URL, params={
            "place_id": place_id,
            "fields": "formatted_phone_number,website,url",
            "key": settings.google_places_api_key,
        })
        resp.raise_for_status()
        result = resp.json().get("result", {})
        return {
            "phone": result.get("formatted_phone_number"),
            "website": result.get("website"),
            "google_place_id": place_id,
        }
    except Exception as e:
        logger.error(f"Place details failed for {place_id}: {e}")
        return {}


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance in km between two coordinates."""
    import math
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def get_sync_engine():
    db_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    )
    from sqlalchemy import create_engine
    return create_engine(db_url)


async def enrich(limit: int, dry_run: bool):
    if not settings.google_places_api_key:
        logger.error("GOOGLE_PLACES_API_KEY is required for enrichment")
        return

    engine = get_sync_engine()

    with Session(engine) as session:
        # Find mosques needing enrichment
        mosques = session.query(Mosque).filter(
            Mosque.is_active == True,
            Mosque.places_enriched == False,
        ).order_by(Mosque.created_at).limit(limit).all()

        logger.info(f"Found {len(mosques)} mosques to enrich")

        enriched = 0
        failed = 0

        async with httpx.AsyncClient(timeout=10) as client:
            for i, mosque in enumerate(mosques):
                logger.info(f"[{i+1}/{len(mosques)}] {mosque.name}, {mosque.city}, {mosque.state}")

                place = await search_place(client, mosque)
                if not place:
                    logger.info(f"  No Places match found")
                    if not dry_run:
                        mosque.places_enriched = True  # Mark as attempted
                    failed += 1
                    continue

                place_id = place.get("place_id")
                details = await get_place_details(client, place_id)

                if not dry_run:
                    if details.get("website") and not mosque.website:
                        mosque.website = details["website"]
                        logger.info(f"  + website: {details['website']}")
                    if details.get("phone") and not mosque.phone:
                        mosque.phone = details["phone"]
                        logger.info(f"  + phone: {details['phone']}")
                    if details.get("google_place_id"):
                        mosque.google_place_id = details["google_place_id"]
                    mosque.places_enriched = True
                else:
                    logger.info(f"  [dry-run] Would update: {details}")

                enriched += 1

                if not dry_run and i % 50 == 0:
                    session.commit()

                # Respect Google Places rate limit (~10 QPS)
                await asyncio.sleep(0.12)

        if not dry_run:
            session.commit()

        logger.info(f"\nEnrichment complete: {enriched} enriched, {failed} no match")


async def main():
    parser = argparse.ArgumentParser(description="Enrich mosque data with Google Places")
    parser.add_argument("--limit", type=int, default=5000, help="Max mosques to process")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to database")
    args = parser.parse_args()

    await enrich(args.limit, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
