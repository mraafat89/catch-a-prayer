"""
Enrich mosques with Google Place Details
==========================================
For mosques that have a google_place_id but missing website/phone/address.
Gets: website, phone, formatted_address, wheelchair_accessible_entrance.

Cost: $0.017 per call. 2000 mosques = ~$34 (within $200 free credit).

Usage:
    python -m pipeline.enrich_from_google --batch 100
    python -m pipeline.enrich_from_google --all
    python -m pipeline.enrich_from_google --dry-run
"""

import asyncio
import argparse
import logging
import os
import sys
import time

import httpx
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()

GOOGLE_KEY = os.environ.get("GOOGLE_PLACES_API_KEY") or "AIzaSyDRo0q7GrAfAu1hyUCzkhn5lJ1R06IY2u8"
FIELDS = "name,website,formatted_phone_number,international_phone_number,formatted_address,wheelchair_accessible_entrance"


def get_db():
    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    sync_url = db_url.replace("+asyncpg", "+psycopg2")
    if "psycopg2" not in sync_url:
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(sync_url)


async def fetch_details(place_id: str) -> dict:
    """Fetch Place Details from Google API."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={"place_id": place_id, "fields": FIELDS, "key": GOOGLE_KEY},
        )
        data = resp.json()
        if data.get("status") == "OK":
            return data.get("result", {})
        return {}


async def run(args):
    engine = get_db()

    with engine.connect() as conn:
        limit = args.batch or 2000
        rows = conn.execute(text("""
            SELECT id::text, name, google_place_id, website, phone, address
            FROM mosques
            WHERE is_active AND google_place_id IS NOT NULL
              AND (website IS NULL OR website = '')
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()

    logger.info(f"Enriching {len(rows)} mosques from Google Place Details")
    logger.info(f"Estimated cost: ${len(rows) * 0.017:.2f}")

    if args.dry_run:
        return

    enriched = 0
    websites_found = 0
    phones_found = 0

    for i, row in enumerate(rows):
        mid, name, gpid = row[0], row[1], row[2]
        existing_website = row[3]
        existing_phone = row[4]
        existing_address = row[5]

        try:
            details = await fetch_details(gpid)
            if not details:
                continue

            updates = []
            vals = {"mid": mid}

            website = details.get("website")
            if website and not existing_website:
                updates.append("website = :website")
                vals["website"] = website
                websites_found += 1

            phone = details.get("international_phone_number") or details.get("formatted_phone_number")
            if phone and not existing_phone:
                updates.append("phone = :phone")
                vals["phone"] = phone
                phones_found += 1

            address = details.get("formatted_address")
            if address and not existing_address:
                # Parse city/state from formatted address
                parts = address.split(",")
                if len(parts) >= 3:
                    city = parts[-3].strip()
                    state_zip = parts[-2].strip()
                    state = state_zip.split()[0] if state_zip else None
                    updates.append("address = :addr")
                    vals["addr"] = address
                    if city:
                        updates.append("city = COALESCE(city, :city)")
                        vals["city"] = city
                    if state:
                        updates.append("state = COALESCE(state, :state)")
                        vals["state"] = state

            wheelchair = details.get("wheelchair_accessible_entrance")
            if wheelchair is not None:
                updates.append("wheelchair_accessible = :wheelchair")
                vals["wheelchair"] = wheelchair

            if updates:
                updates.append("updated_at = now()")
                with engine.begin() as conn:
                    conn.execute(text(
                        f"UPDATE mosques SET {', '.join(updates)} WHERE id = :mid"
                    ), vals)
                enriched += 1

            if (i + 1) % 50 == 0:
                logger.info(f"  Progress: {i+1}/{len(rows)} — {websites_found} websites, {phones_found} phones")

        except Exception as e:
            logger.debug(f"  Failed for {name}: {e}")

        await asyncio.sleep(0.1)  # rate limit

    logger.info(f"\nENRICHMENT COMPLETE")
    logger.info(f"  Processed: {len(rows)}")
    logger.info(f"  Updated: {enriched}")
    logger.info(f"  Websites found: {websites_found}")
    logger.info(f"  Phones found: {phones_found}")
    logger.info(f"  Cost: ${len(rows) * 0.017:.2f}")


def main():
    parser = argparse.ArgumentParser(description="Enrich mosques from Google Place Details")
    parser.add_argument("--batch", type=int, metavar="N", help="Process N mosques")
    parser.add_argument("--all", action="store_true", help="Process all missing")
    parser.add_argument("--dry-run", action="store_true", help="Just estimate cost")
    args = parser.parse_args()

    if not any([args.batch, args.all, args.dry_run]):
        parser.print_help()
        sys.exit(1)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
