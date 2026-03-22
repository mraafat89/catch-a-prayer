"""
Full Mosque Discovery Pipeline
================================
Combines ALL discovery sources to find new mosques and enrich existing ones.
Run every 6 months to catch new mosques as they're built.

Sources:
1. Google Places grid search (US + Canada metros)
2. Google Place Details enrichment (website, phone, address)
3. OpenStreetMap Overpass API (global, free)
4. Mawaqit API (mosque database with prayer times)

Usage:
    python -m pipeline.full_discovery --dry-run       # estimate cost only
    python -m pipeline.full_discovery --all --save     # full run, save to DB
    python -m pipeline.full_discovery --source google  # only Google
    python -m pipeline.full_discovery --source osm     # only OSM
    python -m pipeline.full_discovery --source mawaqit # only Mawaqit
"""

import asyncio
import argparse
import logging
import os
import sys
import time
from datetime import datetime

import httpx
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()


def get_db():
    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    sync_url = db_url.replace("+asyncpg", "+psycopg2")
    if "psycopg2" not in sync_url:
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(sync_url)


async def run(args):
    engine = get_db()
    start = time.time()

    with engine.connect() as conn:
        before_count = conn.execute(text(
            "SELECT count(*) FROM mosques WHERE is_active"
        )).scalar()

    logger.info(f"Current mosque count: {before_count}")
    logger.info(f"Sources: {args.source or 'all'}")

    sources = args.source.split(",") if args.source else ["google", "osm", "mawaqit", "themasjidapp"]
    total_new = 0

    # === Source 1: Google Places ===
    if "google" in sources:
        logger.info("\n" + "="*60)
        logger.info("SOURCE 1: Google Places grid search")
        from pipeline.discover_mosques import run as google_run
        google_args = argparse.Namespace(
            dry_run=args.dry_run, all=True, region=None, state=None,
            save=args.save
        )
        await google_run(google_args)

        if args.save and not args.dry_run:
            # Enrich new mosques with Place Details
            logger.info("\nEnriching new mosques with Google Place Details...")
            from pipeline.enrich_from_google import run as enrich_run
            enrich_args = argparse.Namespace(batch=None, all=True, dry_run=False)
            await enrich_run(enrich_args)

    # === Source 2: OpenStreetMap ===
    if "osm" in sources:
        logger.info("\n" + "="*60)
        logger.info("SOURCE 2: OpenStreetMap Overpass API")
        await _discover_from_osm(engine, args)

    # === Source 3: Mawaqit ===
    if "mawaqit" in sources:
        logger.info("\n" + "="*60)
        logger.info("SOURCE 3: Mawaqit mosque database")
        await _discover_from_mawaqit(engine, args)

    # === Source 4: TheMasjidApp ===
    if "themasjidapp" in sources:
        logger.info("\n" + "=" * 60)
        logger.info("SOURCE 4: TheMasjidApp (120k+ mosques)")
        await _discover_from_themasjidapp(engine, args)

    # === Closed Mosque Detection ===
    if args.save and not args.dry_run:
        logger.info("\n" + "=" * 60)
        logger.info("CLOSED MOSQUE DETECTION")
        await _detect_closed_mosques(engine)

    # === Summary ===
    with engine.connect() as conn:
        after_count = conn.execute(text(
            "SELECT count(*) FROM mosques WHERE is_active"
        )).scalar()

    elapsed = time.time() - start
    total_new = after_count - before_count

    logger.info(f"\n{'='*60}")
    logger.info(f"FULL DISCOVERY COMPLETE")
    logger.info(f"  Before: {before_count} mosques")
    logger.info(f"  After:  {after_count} mosques")
    logger.info(f"  New:    {total_new}")
    logger.info(f"  Time:   {elapsed/60:.1f} minutes")

    # Create scraping jobs for new mosques that have websites
    if args.save and not args.dry_run:
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO scraping_jobs (id, mosque_id, status, priority)
                SELECT gen_random_uuid(), m.id, 'pending', 5
                FROM mosques m
                WHERE m.is_active AND m.website IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM scraping_jobs sj WHERE sj.mosque_id = m.id)
                ON CONFLICT (mosque_id) DO NOTHING
            """))
            logger.info(f"  Created {result.rowcount} new scraping jobs")

    # Backfill geo data for mosques missing state/timezone
    if args.save and not args.dry_run:
        from pipeline.geo_utils import enrich_mosque_geo
        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT id::text, lat, lng FROM mosques WHERE is_active AND (state IS NULL OR timezone IS NULL) AND lat IS NOT NULL"
            )).fetchall()
            for r in rows:
                geo = enrich_mosque_geo(float(r[1]), float(r[2]))
                if geo["state"]:
                    conn.execute(text(
                        "UPDATE mosques SET state = :s, timezone = :tz, country = :c WHERE id = CAST(:id AS uuid)"
                    ), {"id": r[0], "s": geo["state"], "tz": geo["timezone"], "c": geo["country"]})
            if rows:
                logger.info(f"  Backfilled geo data for {len(rows)} mosques")


async def _discover_from_osm(engine, args):
    """Search OpenStreetMap for mosques in US and Canada."""
    overpass_url = os.environ.get("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter")

    # Query for all mosques in US and Canada
    query = """
    [out:json][timeout:120];
    (
      node["amenity"="place_of_worship"]["religion"="muslim"](24.0,-170.0,72.0,-50.0);
      way["amenity"="place_of_worship"]["religion"="muslim"](24.0,-170.0,72.0,-50.0);
      relation["amenity"="place_of_worship"]["religion"="muslim"](24.0,-170.0,72.0,-50.0);
    );
    out center tags;
    """

    logger.info("  Querying Overpass API (US+Canada bounding box)...")

    if args.dry_run:
        logger.info("  DRY RUN — skipping API call")
        return

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(overpass_url, data={"data": query})
            if resp.status_code != 200:
                logger.error(f"  Overpass returned {resp.status_code}")
                return
            data = resp.json()

        elements = data.get("elements", [])
        logger.info(f"  Found {len(elements)} places of worship")

        new_count = 0
        with engine.begin() as conn:
            for el in elements:
                name = el.get("tags", {}).get("name")
                if not name:
                    continue

                lat = el.get("lat") or el.get("center", {}).get("lat")
                lng = el.get("lon") or el.get("center", {}).get("lon")
                if not lat or not lng:
                    continue

                tags = el.get("tags", {})
                osm_id = str(el.get("id", ""))
                osm_type = el.get("type", "node")

                # Check if already exists (by OSM ID or proximity)
                existing = conn.execute(text("""
                    SELECT id FROM mosques
                    WHERE osm_id = :osm_id
                       OR (ABS(lat - :lat) < 0.003 AND ABS(lng - :lng) < 0.003)
                    LIMIT 1
                """), {"osm_id": osm_id, "lat": lat, "lng": lng}).fetchone()

                if existing:
                    continue

                if args.save:
                    try:
                        from pipeline.geo_utils import enrich_mosque_geo
                        geo = enrich_mosque_geo(lat, lng)
                        conn.execute(text("""
                            INSERT INTO mosques (id, name, lat, lng, osm_id, osm_type,
                                address, phone, website, denomination,
                                state, timezone, country, source, discovered_at,
                                is_active, created_at, updated_at)
                            VALUES (gen_random_uuid(), :name, :lat, :lng, :osm_id, :osm_type,
                                :addr, :phone, :website, :denom,
                                :state, :tz, :country, 'osm', now(),
                                true, now(), now())
                            ON CONFLICT DO NOTHING
                        """), {
                            "name": name, "lat": lat, "lng": lng,
                            "osm_id": osm_id, "osm_type": osm_type,
                            "addr": tags.get("addr:street", ""),
                            "phone": tags.get("phone") or tags.get("contact:phone"),
                            "website": tags.get("website") or tags.get("contact:website"),
                            "denom": tags.get("denomination"),
                            "state": geo["state"], "tz": geo["timezone"],
                            "country": geo["country"],
                        })
                        new_count += 1
                    except Exception:
                        pass

        logger.info(f"  New from OSM: {new_count}")

    except Exception as e:
        logger.error(f"  OSM discovery failed: {e}")


async def _discover_from_mawaqit(engine, args):
    """Search Mawaqit for mosques in US and Canada."""
    search_terms = [
        # Major US cities
        "new york", "los angeles", "chicago", "houston", "phoenix",
        "philadelphia", "san antonio", "san diego", "dallas", "san jose",
        "austin", "jacksonville", "san francisco", "columbus", "charlotte",
        "indianapolis", "seattle", "denver", "washington", "boston",
        "detroit", "nashville", "memphis", "portland", "baltimore",
        "milwaukee", "albuquerque", "tucson", "fresno", "sacramento",
        "atlanta", "miami", "tampa", "orlando", "raleigh",
        "minneapolis", "cleveland", "pittsburgh", "st louis", "kansas city",
        # Canada
        "toronto", "montreal", "vancouver", "calgary", "edmonton",
        "ottawa", "winnipeg", "mississauga", "brampton", "hamilton",
    ]

    if args.dry_run:
        logger.info(f"  DRY RUN — would search {len(search_terms)} city names on Mawaqit")
        return

    new_count = 0
    for term in search_terms:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://mawaqit.net/api/2.0/mosque/search",
                    params={"word": term},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    continue
                mosques = resp.json()

            for m in mosques:
                loc = m.get("localisation", "")
                if "United States" not in loc and "Canada" not in loc:
                    continue

                lat = m.get("latitude", 0)
                lng = m.get("longitude", 0)
                name = m.get("name", "")
                if not name or not lat:
                    continue

                # Check duplicate
                with engine.connect() as conn:
                    existing = conn.execute(text("""
                        SELECT id FROM mosques
                        WHERE ABS(lat - :lat) < 0.003 AND ABS(lng - :lng) < 0.003
                        LIMIT 1
                    """), {"lat": lat, "lng": lng}).fetchone()

                if existing:
                    continue

                if args.save:
                    with engine.begin() as conn:
                        try:
                            from pipeline.geo_utils import enrich_mosque_geo
                            geo = enrich_mosque_geo(lat, lng)
                            conn.execute(text("""
                                INSERT INTO mosques (id, name, lat, lng, phone, email,
                                    has_womens_section, wheelchair_accessible,
                                    state, timezone, country, source, discovered_at,
                                    is_active, created_at, updated_at)
                                VALUES (gen_random_uuid(), :name, :lat, :lng, :phone, :email,
                                    :women, :wheelchair,
                                    :state, :tz, :country, 'mawaqit', now(),
                                    true, now(), now())
                            """), {
                                "name": name, "lat": lat, "lng": lng,
                                "phone": m.get("phone"), "email": m.get("email"),
                                "women": m.get("womenSpace"),
                                "wheelchair": m.get("handicapAccessibility"),
                                "state": geo["state"], "tz": geo["timezone"],
                                "country": geo["country"],
                            })
                            new_count += 1
                        except Exception:
                            pass

            await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"  Mawaqit search '{term}' failed: {e}")

    logger.info(f"  New from Mawaqit: {new_count}")


async def _discover_from_themasjidapp(engine, args):
    """Search TheMasjidApp for mosques near our existing mosque locations."""
    TMA_SEARCH = "https://themasjidapp.org/api/v1/search-node"

    if args.dry_run:
        logger.info("  DRY RUN — would search TheMasjidApp by location grid")
        return

    from pipeline.geo_utils import enrich_mosque_geo

    # Get unique location clusters from our DB
    with engine.connect() as conn:
        clusters = conn.execute(text("""
            SELECT DISTINCT round(lat::numeric, 1) as rlat, round(lng::numeric, 1) as rlng
            FROM mosques WHERE is_active AND lat IS NOT NULL
        """)).fetchall()

    logger.info(f"  Searching {len(clusters)} location clusters on TheMasjidApp")

    new_count = 0
    seen_slugs = set()

    async with httpx.AsyncClient(timeout=15) as client:
        for i, (rlat, rlng) in enumerate(clusters):
            try:
                resp = await client.get(TMA_SEARCH, params={
                    "lat": float(rlat), "lng": float(rlng), "radius": 15
                })
                if resp.status_code != 200:
                    continue

                results = resp.json().get("results", [])
                for r in results:
                    m = r.get("masjid", {})
                    slug = m.get("slug")
                    if not slug or slug in seen_slugs:
                        continue
                    seen_slugs.add(slug)

                    lat = float(m.get("lat", 0) or 0)
                    lng = float(m.get("lng", 0) or 0)
                    name = m.get("name", "")
                    if not name or not lat:
                        continue

                    # Check duplicate
                    existing = conn.execute(text("""
                        SELECT id FROM mosques
                        WHERE ABS(lat - :lat) < 0.003 AND ABS(lng - :lng) < 0.003
                        LIMIT 1
                    """), {"lat": lat, "lng": lng}).fetchone()

                    if existing:
                        # Update verification count
                        if args.save:
                            with engine.begin() as wconn:
                                wconn.execute(text("""
                                    UPDATE mosques SET last_verified_at = now(),
                                        verification_count = COALESCE(verification_count, 0) + 1
                                    WHERE id = :id
                                """), {"id": existing[0]})
                        continue

                    if args.save:
                        geo = enrich_mosque_geo(lat, lng)
                        with engine.begin() as wconn:
                            try:
                                wconn.execute(text("""
                                    INSERT INTO mosques (id, name, lat, lng,
                                        state, timezone, country, source, discovered_at,
                                        is_active, created_at, updated_at)
                                    VALUES (gen_random_uuid(), :name, :lat, :lng,
                                        :state, :tz, :country, 'themasjidapp', now(),
                                        true, now(), now())
                                """), {
                                    "name": name, "lat": lat, "lng": lng,
                                    "state": geo["state"], "tz": geo["timezone"],
                                    "country": geo["country"],
                                })
                                new_count += 1
                            except Exception:
                                pass

                await asyncio.sleep(0.3)
            except Exception as e:
                logger.debug(f"  TMA search failed at ({rlat},{rlng}): {e}")

            if (i + 1) % 100 == 0:
                logger.info(f"  Progress: {i + 1}/{len(clusters)} clusters, {new_count} new")

    logger.info(f"  New from TheMasjidApp: {new_count} (searched {len(seen_slugs)} unique)")


async def _detect_closed_mosques(engine):
    """Detect mosques that may have closed permanently."""
    closed_count = 0

    # 1. Check websites that have been dead for 2+ consecutive alive checks
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE mosques SET is_active = false
            WHERE id IN (
                SELECT mosque_id FROM scraping_jobs
                WHERE website_alive = false
                  AND website_checked_at < now() - interval '30 days'
                  AND consecutive_failures >= 3
            )
            AND is_active = true
            RETURNING id
        """))
        dead_website_count = result.rowcount
        if dead_website_count > 0:
            logger.info(f"  Deactivated {dead_website_count} mosques with persistently dead websites")
        closed_count += dead_website_count

    # 2. Flag mosques with gambling/spam on their website (hijacked domains)
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE mosques SET is_active = false
            WHERE id IN (
                SELECT mosque_id FROM scraping_jobs
                WHERE status = 'failed' AND website_alive = false
            )
            AND website IS NOT NULL
            AND is_active = true
            AND id NOT IN (
                SELECT mosque_id FROM prayer_schedules
                WHERE date >= CURRENT_DATE - 30 AND fajr_adhan_source != 'calculated'
            )
            RETURNING id
        """))
        hijacked_count = result.rowcount
        if hijacked_count > 0:
            logger.info(f"  Deactivated {hijacked_count} mosques with hijacked/dead websites and no recent data")
        closed_count += hijacked_count

    logger.info(f"  Total deactivated: {closed_count}")


def main():
    parser = argparse.ArgumentParser(description="Full mosque discovery pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Estimate only")
    parser.add_argument("--all", action="store_true", help="Run all sources")
    parser.add_argument("--source", type=str, help="Specific sources: google,osm,mawaqit")
    parser.add_argument("--save", action="store_true", help="Save to database")
    args = parser.parse_args()

    if not any([args.dry_run, args.all, args.source]):
        parser.print_help()
        sys.exit(1)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
