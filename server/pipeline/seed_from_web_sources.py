"""
Web Sources Mosque Seeder
=========================
Fetches mosque data from Hartford Institute and MosqueList.top,
then merges it into the database:
  - Existing mosques: fills in missing website, phone, wheelchair_accessible
  - New mosques: geocodes the address and inserts with a scraping job

Usage:
    python -m pipeline.seed_from_web_sources
    python -m pipeline.seed_from_web_sources --source hartford
    python -m pipeline.seed_from_web_sources --source mosquelist
    python -m pipeline.seed_from_web_sources --dry-run
"""

import asyncio
import argparse
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from timezonefinder import TimezoneFinder

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings
from app.models import Mosque, ScrapingJob
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
tf = TimezoneFinder()

# ---------------------------------------------------------------------------
# Data class for scraped mosque entries
# ---------------------------------------------------------------------------

@dataclass
class WebMosque:
    name: str
    city: str
    state: str
    address: Optional[str] = None
    zip: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    wheelchair_accessible: Optional[bool] = None
    source: str = ""


# ---------------------------------------------------------------------------
# Hartford Institute scraper
# ---------------------------------------------------------------------------

async def fetch_hartford_mosques(client: httpx.AsyncClient) -> list[WebMosque]:
    """Fetch all mosques from Hartford Institute mosque database."""
    logger.info("Fetching Hartford Institute mosque database...")
    mosques = []
    page = 1

    while True:
        r = await client.post(
            f"https://hirr.hartfordinternational.edu/?sfid=199&sf_action=get_data&sf_data=results&sf_paged={page}",
            data={"sfid": "199"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        r.raise_for_status()
        data = r.json()
        soup = BeautifulSoup(data["results"], "lxml")
        rows = soup.find_all("tr")[1:]  # skip header

        if not rows:
            break

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            link = cells[0].find("a")
            name = cells[0].get_text(strip=True)
            if not name:
                continue
            mosques.append(WebMosque(
                name=name,
                address=cells[1].get_text(strip=True) or None,
                city=cells[2].get_text(strip=True),
                state=cells[3].get_text(strip=True),
                zip=cells[4].get_text(strip=True) or None if len(cells) > 4 else None,
                website=link["href"] if link and link.get("href") else None,
                source="hartford",
            ))

        logger.info(f"  Page {page}: {len(rows)} rows (total: {len(mosques)})")
        if len(rows) < 25:
            break
        page += 1
        await asyncio.sleep(0.2)  # be polite

    logger.info(f"Hartford: {len(mosques)} mosques fetched")
    return mosques


# ---------------------------------------------------------------------------
# MosqueList.top scraper
# ---------------------------------------------------------------------------

US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "district-of-columbia", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new-hampshire",
    "new-jersey", "new-mexico", "new-york", "north-carolina", "north-dakota",
    "ohio", "oklahoma", "oregon", "pennsylvania", "rhode-island", "south-carolina",
    "south-dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west-virginia", "wisconsin", "wyoming", "ma",
]


def _parse_mosquelist_mosque_page(soup: BeautifulSoup, url: str) -> Optional[WebMosque]:
    """Parse a single mosquelist.top mosque detail page."""
    h1 = soup.find("h1")
    if not h1:
        return None
    # Title format: "Name in City, State"
    title = h1.get_text(strip=True)
    name_match = re.match(r"^(.+?)\s+in\s+(.+?),\s+(.+)$", title)
    if not name_match:
        return None
    name = name_match.group(1).strip()
    city = name_match.group(2).strip()
    state = name_match.group(3).strip()

    # Address — the text is in a <p> sibling after the <h3>📍 Address</h3>
    address = None
    addr_header = soup.find(string=re.compile(r"📍\s*Address", re.I))
    if addr_header and addr_header.parent:
        addr_p = addr_header.parent.find_next_sibling("p")
        if addr_p:
            address = addr_p.get_text(strip=True) or None

    # Website
    website = None
    web_label = soup.find(string=re.compile(r"🌐\s*Website", re.I))
    if web_label and web_label.parent:
        web_link = web_label.parent.find_next("a", href=True)
        if web_link:
            website = web_link["href"]

    # Phone / email
    phone = None
    email = None
    contact_label = soup.find(string=re.compile(r"Contact Information", re.I))
    if contact_label and contact_label.parent:
        sibling = contact_label.parent.find_next_sibling()
        if sibling:
            contact_text = sibling.get_text(" ", strip=True)
            phone_m = re.search(r"(\+?[\d\s\-\(\)]{7,})", contact_text)
            if phone_m:
                phone = phone_m.group(1).strip()
            email_m = re.search(r"[\w\.\-]+@[\w\.\-]+\.\w+", contact_text)
            if email_m:
                email = email_m.group(0)

    # Wheelchair
    wheelchair = None
    page_text = soup.get_text()
    if "Wheelchair Accessible" in page_text:
        wheelchair = True

    return WebMosque(
        name=name, city=city, state=state,
        address=address, website=website,
        phone=phone, email=email,
        wheelchair_accessible=wheelchair,
        source="mosquelist",
    )


async def fetch_mosquelist_mosques(client: httpx.AsyncClient) -> list[WebMosque]:
    """Crawl mosquelist.top state pages → city pages → mosque detail pages."""
    logger.info("Fetching MosqueList.top mosque data...")
    mosques = []

    for state_slug in US_STATES:
        state_url = f"https://mosquelist.top/state/{state_slug}/"
        try:
            r = await client.get(state_url)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")

            # City links on state page
            city_links = [
                a["href"] for a in soup.find_all("a", href=True)
                if a["href"].startswith("https://mosquelist.top/state/")
                and a["href"] != state_url
                and a["href"] not in ("https://mosquelist.top/state/california/",)
            ]

            for city_url in city_links:
                try:
                    r2 = await client.get(city_url)
                    if r2.status_code != 200:
                        continue
                    soup2 = BeautifulSoup(r2.text, "lxml")

                    # Mosque detail links on city page
                    mosque_links = [
                        a["href"] for a in soup2.find_all("a", href=True)
                        if "/mosques-list/" in a["href"]
                    ]
                    # Deduplicate
                    mosque_links = list(dict.fromkeys(mosque_links))

                    for mosque_url in mosque_links:
                        try:
                            r3 = await client.get(mosque_url)
                            if r3.status_code != 200:
                                continue
                            soup3 = BeautifulSoup(r3.text, "lxml")
                            m = _parse_mosquelist_mosque_page(soup3, mosque_url)
                            if m:
                                mosques.append(m)
                            await asyncio.sleep(0.15)
                        except Exception as e:
                            logger.debug(f"  Mosque page error {mosque_url}: {e}")
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.debug(f"  City page error {city_url}: {e}")

            logger.info(f"  {state_slug}: done (total: {len(mosques)})")
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.warning(f"  State page error {state_slug}: {e}")

    logger.info(f"MosqueList: {len(mosques)} mosques fetched")
    return mosques


# ---------------------------------------------------------------------------
# Geocoding via Nominatim
# ---------------------------------------------------------------------------

async def geocode_address(client: httpx.AsyncClient, address: str,
                          city: str, state: str, zip_code: Optional[str]) -> Optional[tuple[float, float]]:
    """Geocode an address using OSM Nominatim. Returns (lat, lng) or None."""
    # Build query
    q_parts = [p for p in [address, city, state, zip_code, "US"] if p]
    q = ", ".join(q_parts)
    try:
        r = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": "1", "countrycodes": "us,ca"},
            headers={"User-Agent": "CatchAPrayerApp/1.0 (mosque seeder)"},
        )
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        logger.debug(f"  Geocode error for {q}: {e}")
    return None


# ---------------------------------------------------------------------------
# Name normalization for deduplication
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Normalize mosque name for fuzzy matching."""
    name = name.lower().strip()
    # Remove common suffixes/prefixes
    for word in ["masjid", "mosque", "islamic center", "islamic centre",
                 "islami", "center", "centre", "the ", "al-", "al ", "of ",
                 "association", "assoc", "society", "foundation",
                 "inc", "inc.", "llc"]:
        name = name.replace(word, " ")
    # Remove punctuation and extra spaces
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def name_similarity(a: str, b: str) -> float:
    """Simple token overlap similarity between two mosque names."""
    ta = set(normalize_name(a).split())
    tb = set(normalize_name(b).split())
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb)
    return overlap / max(len(ta), len(tb))


# ---------------------------------------------------------------------------
# Database matching and upsert
# ---------------------------------------------------------------------------

_GENERIC_NAMES = {"unknown mosque", "mosque", "masjid", "islamic center", "islamic centre", "musallah"}


def _is_generic_name(name: str) -> bool:
    return name.lower().strip() in _GENERIC_NAMES


def find_existing_mosque(session: Session, mosque: WebMosque) -> Optional[dict]:
    """Find an existing mosque in the DB matching by name + city + state."""
    # Don't match against generic placeholder names
    if _is_generic_name(mosque.name):
        return None

    # Exact city+state match first, then name similarity
    rows = session.execute(text("""
        SELECT id::text, name, website, phone, email, wheelchair_accessible
        FROM mosques
        WHERE LOWER(COALESCE(city, '')) = LOWER(:city)
          AND LOWER(COALESCE(state, '')) = LOWER(:state)
          AND is_active = true
          AND LOWER(name) NOT IN ('unknown mosque', 'mosque', 'masjid',
                                  'islamic center', 'islamic centre', 'musallah')
    """), {"city": mosque.city or "", "state": mosque.state or ""}).mappings().all()

    if not rows:
        return None

    # Find best name match
    best = None
    best_sim = 0.0
    for row in rows:
        sim = name_similarity(mosque.name, row["name"])
        if sim > best_sim:
            best_sim = sim
            best = dict(row)

    return best if best_sim >= 0.5 else None


def enrich_mosque(session: Session, mosque_id: str, mosque: WebMosque, dry_run: bool) -> bool:
    """Update missing fields on an existing mosque. Returns True if any change was made."""
    updates = {}
    row = session.execute(text("""
        SELECT website, phone, email, wheelchair_accessible
        FROM mosques WHERE id = CAST(:id AS uuid)
    """), {"id": mosque_id}).mappings().first()

    if not row:
        return False

    if mosque.website and not row["website"]:
        updates["website"] = mosque.website
    if mosque.phone and not row["phone"]:
        updates["phone"] = mosque.phone
    if mosque.email and not row["email"]:
        updates["email"] = mosque.email
    if mosque.wheelchair_accessible is not None and row["wheelchair_accessible"] is None:
        updates["wheelchair_accessible"] = mosque.wheelchair_accessible

    if not updates:
        return False

    if not dry_run:
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        session.execute(text(f"""
            UPDATE mosques SET {set_clause}, updated_at = NOW()
            WHERE id = CAST(:mosque_id AS uuid)
        """), {**updates, "mosque_id": mosque_id})

        # If we just got a website, upgrade scraping priority
        if "website" in updates:
            session.execute(text("""
                UPDATE scraping_jobs SET priority = 1, next_attempt_at = NOW()
                WHERE mosque_id = CAST(:mosque_id AS uuid)
                  AND status IN ('pending', 'failed')
            """), {"mosque_id": mosque_id})

    return True


async def insert_new_mosque(session: Session, mosque: WebMosque,
                            client: httpx.AsyncClient, dry_run: bool) -> bool:
    """Geocode and insert a new mosque. Returns True if inserted."""
    # Skip generically-named entries — they add noise without helping users
    if _is_generic_name(mosque.name):
        return False

    if not mosque.city and not mosque.address:
        return False

    coords = await geocode_address(client, mosque.address or "", mosque.city or "",
                                   mosque.state or "", mosque.zip)
    if not coords:
        logger.debug(f"  Could not geocode: {mosque.name}, {mosque.city}, {mosque.state}")
        return False

    lat, lng = coords

    # Check for nearby duplicates — same building (≤50m) always merges;
    # 50–200m only merges if names are similar (avoids collapsing distinct orgs at same address)
    nearby_rows = session.execute(text("""
        SELECT id::text, name,
               ROUND(ST_Distance(
                   geom::geography,
                   ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
               )::numeric, 1) as dist_m
        FROM mosques
        WHERE is_active = true
          AND ST_DWithin(
              geom::geography,
              ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
              200
          )
        ORDER BY dist_m
        LIMIT 5
    """), {"lat": lat, "lng": lng}).mappings().all()

    for nearby in nearby_rows:
        dist = float(nearby["dist_m"])
        sim = name_similarity(mosque.name, nearby["name"])
        is_same_building = dist <= 50
        is_similar_name = sim >= 0.4
        if is_same_building or is_similar_name:
            logger.debug(f"  Nearby duplicate ({dist}m, sim={sim:.2f}): "
                         f"{mosque.name} → {nearby['name']}")
            return enrich_mosque(session, nearby["id"], mosque, dry_run)

    tz = tf.timezone_at(lat=lat, lng=lng) or "UTC"

    if dry_run:
        logger.info(f"  [dry-run] Would insert: {mosque.name} ({mosque.city}, {mosque.state}) "
                    f"at {lat:.4f},{lng:.4f}")
        return True

    from app.models import Mosque as MosqueModel
    m = MosqueModel(
        name=mosque.name,
        lat=lat,
        lng=lng,
        geom=f"SRID=4326;POINT({lng} {lat})",
        address=mosque.address,
        city=mosque.city,
        state=mosque.state,
        zip=mosque.zip,
        country="US",
        timezone=tz,
        phone=mosque.phone,
        website=mosque.website,
        email=mosque.email,
        wheelchair_accessible=mosque.wheelchair_accessible,
        is_active=True,
        verified=False,
        places_enriched=False,
    )
    session.add(m)
    session.flush()

    job = ScrapingJob(
        mosque_id=m.id,
        status="pending",
        priority=1 if mosque.website else 9,
        next_attempt_at=datetime.utcnow(),
    )
    session.add(job)
    return True


# ---------------------------------------------------------------------------
# Main merge logic
# ---------------------------------------------------------------------------

async def merge_web_mosques(mosques: list[WebMosque], session: Session,
                            dry_run: bool, geocode_new: bool = True) -> dict:
    """Match web-scraped mosques against DB and update/insert."""
    stats = {"enriched": 0, "inserted": 0, "skipped": 0}

    geocode_client = httpx.AsyncClient(timeout=10, follow_redirects=True)

    try:
        for i, mosque in enumerate(mosques):
            existing = find_existing_mosque(session, mosque)

            if existing:
                enriched = enrich_mosque(session, existing["id"], mosque, dry_run)
                if enriched:
                    stats["enriched"] += 1
                    logger.debug(f"  Enriched: {mosque.name} ({mosque.city})")
                else:
                    stats["skipped"] += 1
            elif geocode_new:
                inserted = await insert_new_mosque(session, mosque, geocode_client, dry_run)
                if inserted:
                    stats["inserted"] += 1
                    logger.info(f"  Inserted new: {mosque.name} ({mosque.city}, {mosque.state})")
                else:
                    stats["skipped"] += 1
                await asyncio.sleep(1.1)  # Nominatim rate limit: 1 req/sec
            else:
                stats["skipped"] += 1

            if not dry_run and (i + 1) % 100 == 0:
                session.commit()
                logger.info(f"  Progress {i+1}/{len(mosques)}: "
                            f"enriched={stats['enriched']}, inserted={stats['inserted']}")

        if not dry_run:
            session.commit()
    finally:
        await geocode_client.aclose()

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Seed mosques from Hartford and MosqueList")
    parser.add_argument("--source", choices=["hartford", "mosquelist", "both"], default="both",
                        help="Which source to fetch (default: both)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and log without writing to database")
    parser.add_argument("--no-geocode", action="store_true",
                        help="Skip geocoding+inserting new mosques (only enrich existing)")
    args = parser.parse_args()

    db_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    ).split("?")[0]
    engine = create_engine(db_url, echo=False)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        all_mosques: list[WebMosque] = []

        if args.source in ("hartford", "both"):
            hartford = await fetch_hartford_mosques(client)
            all_mosques.extend(hartford)

        if args.source in ("mosquelist", "both"):
            ml = await fetch_mosquelist_mosques(client)
            all_mosques.extend(ml)

    logger.info(f"\nTotal web mosques: {len(all_mosques)}")

    with Session(engine) as session:
        stats = await merge_web_mosques(
            all_mosques, session, args.dry_run,
            geocode_new=not args.no_geocode,
        )

    logger.info("=" * 60)
    logger.info(f"DONE — enriched: {stats['enriched']}, "
                f"inserted: {stats['inserted']}, skipped: {stats['skipped']}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
