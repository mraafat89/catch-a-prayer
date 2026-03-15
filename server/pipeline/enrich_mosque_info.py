"""
Mosque Info Enrichment
======================
Scrapes denomination, languages, and facilities from mosque websites.
Updates mosques.denomination, mosques.languages_spoken, mosques.has_womens_section.

Denomination detection uses keyword scoring — never defaults to "sunni".
See docs/SCRAPING_PIPELINE.md — "Mosque Info Enrichment" for full design.

Usage:
    python -m pipeline.enrich_mosque_info               # process all un-enriched mosques
    python -m pipeline.enrich_mosque_info --mosque-id <uuid>
    python -m pipeline.enrich_mosque_info --re-enrich   # refresh already-enriched mosques
    python -m pipeline.enrich_mosque_info --dry-run
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# Denomination keyword lists (from SCRAPING_PIPELINE.md)
# ---------------------------------------------------------------------------

DENOMINATION_KEYWORDS: dict[str, list[str]] = {
    "sunni": [
        "sunni", "ahl al-sunnah", "ahlus sunnah", "ahl us-sunnah",
        "hanafi", "shafi", "shafi'i", "maliki", "hanbali",
        "deobandi", "barelvi", "barelwi", "salafi", "wahhabi",
        "tabligh", "jamaat-e-islami",
    ],
    "shia": [
        "shia", "shi'a", "shi'ite", "shiite", "imami",
        "ithna ashari", "12ver", "twelver", "ja'fari", "jafari",
        "hussainiyya", "hussainia", "husayniyya", "ashura", "imam ali",
        "imam hussain", "imam khomeini",
    ],
    "ismaili": [
        "ismaili", "isma'ili", "ismaeli", "jamatkhana", "imamat",
        "aga khan", "agakhani", "nizari",
    ],
    "ahmadiyya": [
        "ahmadiyya", "ahmadi", "qadiani", "rabwah",
    ],
    "sufi": [
        "sufi", "tasawwuf", "tariqa", "tariqah", "naqshbandi",
        "qadiri", "chishti", "shadhili", "zawiya",
    ],
}

# Languages to detect (keyword: language label)
LANGUAGE_KEYWORDS: dict[str, str] = {
    "english":   "English",
    "arabic":    "Arabic",
    "urdu":      "Urdu",
    "turkish":   "Turkish",
    "french":    "French",
    "somali":    "Somali",
    "bengali":   "Bengali",
    "bangla":    "Bengali",
    "bosnian":   "Bosnian",
    "indonesian": "Indonesian",
    "persian":   "Persian",
    "farsi":     "Persian",
    "pashto":    "Pashto",
    "swahili":   "Swahili",
    "punjabi":   "Punjabi",
    "gujarati":  "Gujarati",
}

# Womens section keywords
WOMENS_KEYWORDS = [
    "sisters", "sisters' section", "women's section", "women section",
    "musalla for sisters", "musallah for sisters", "ladies section",
    "women's prayer area", "sisters prayer", "musalla for women",
    "women's room", "ladies prayer",
]

# Parking keywords
PARKING_KEYWORDS = [
    "parking", "car park", "parking lot", "parking available",
    "parking spaces", "ample parking",
]

# Pages to check for denomination info (in priority order)
INFO_SUBPAGES = ["/about", "/about-us", "/our-mosque", "/who-we-are",
                 "/mission", "/history", "/overview"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_sync_engine():
    db_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    ).split("?")[0]
    return create_engine(db_url, echo=False)


async def fetch_page_text(url: str, client: httpx.AsyncClient) -> Optional[str]:
    """Fetch URL and return lowercased text content, or None on failure."""
    try:
        resp = await client.get(
            url, follow_redirects=True, timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CatchAPrayer/1.0)"},
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            # Remove scripts/styles
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            return soup.get_text(" ").lower()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------

def detect_denomination(text: str) -> tuple[Optional[str], int, str]:
    """
    Score text against denomination keyword lists.
    Returns (denomination | None, hit_count, source_note).

    Rules (from design doc):
    - shia/ismaili/ahmadiyya: ≥1 distinctive keyword → confident
    - sunni: ≥1 keyword AND no shia/ismaili/ahmadiyya signals
    - conflicting signals → None
    - no keywords → None (never assume)
    """
    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}

    for denom, keywords in DENOMINATION_KEYWORDS.items():
        count = 0
        matched = []
        for kw in keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, text):
                count += 1
                matched.append(kw)
        scores[denom] = count
        hits[denom] = matched

    # Ismaili is the most distinctive — check first
    if scores.get("ismaili", 0) >= 1:
        return "ismaili", scores["ismaili"], f"keywords: {hits['ismaili']}"

    # Ahmadiyya
    if scores.get("ahmadiyya", 0) >= 1:
        return "ahmadiyya", scores["ahmadiyya"], f"keywords: {hits['ahmadiyya']}"

    # Shia — check even 1 keyword since terms are distinctive
    if scores.get("shia", 0) >= 1:
        # Conflicting? If also has multiple sunni keywords → unclear
        if scores.get("sunni", 0) >= 3:
            return None, 0, "conflicting sunni+shia signals"
        return "shia", scores["shia"], f"keywords: {hits['shia']}"

    # Sunni — only confident if ≥1 keyword AND no distinctive minority signals
    minority_signals = scores.get("shia", 0) + scores.get("ismaili", 0) + scores.get("ahmadiyya", 0)
    if scores.get("sunni", 0) >= 1 and minority_signals == 0:
        return "sunni", scores["sunni"], f"keywords: {hits['sunni']}"

    # Sufi (soft — often Sunni-background but distinctive)
    if scores.get("sufi", 0) >= 2:
        return "sufi", scores["sufi"], f"keywords: {hits['sufi']}"

    return None, 0, "no keywords found"


def detect_languages(text: str) -> list[str]:
    """Return list of language names detected in text."""
    found = []
    for keyword, language in LANGUAGE_KEYWORDS.items():
        if language not in found:
            if re.search(r"\b" + re.escape(keyword) + r"\b", text):
                found.append(language)
    # Always include English for US/CA mosques with an English website
    if "english" in text and "English" not in found:
        found.append("English")
    return found


def detect_womens_section(text: str) -> Optional[bool]:
    """Return True if womens section mentioned, None if unclear."""
    if any(kw in text for kw in WOMENS_KEYWORDS):
        return True
    return None


def detect_parking(text: str) -> Optional[bool]:
    """Return True if parking mentioned, None if unclear."""
    if any(kw in text for kw in PARKING_KEYWORDS):
        return True
    return None


# ---------------------------------------------------------------------------
# Per-mosque enrichment
# ---------------------------------------------------------------------------

async def enrich_mosque(mosque_id: str, name: str, website: str,
                        dry_run: bool = False) -> dict:
    """
    Scrape homepage + /about page of mosque website.
    Returns dict of detected fields.
    """
    result = {
        "mosque_id": mosque_id,
        "denomination": None,
        "denomination_confidence": 0,
        "denomination_note": "",
        "languages_spoken": [],
        "has_womens_section": None,
        "has_parking": None,
    }

    url = website
    if not url.startswith("http"):
        url = f"https://{url}"

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        combined_text = ""

        # Fetch homepage
        homepage_text = await fetch_page_text(url, client)
        if homepage_text:
            combined_text += homepage_text

        # Fetch about pages
        for subpath in INFO_SUBPAGES:
            about_url = urljoin(url, subpath)
            about_text = await fetch_page_text(about_url, client)
            if about_text:
                combined_text += " " + about_text
                break  # first successful about page is enough

        if not combined_text:
            logger.info(f"  {name}: no page text retrieved")
            return result

    denom, confidence, note = detect_denomination(combined_text)
    languages = detect_languages(combined_text)
    womens = detect_womens_section(combined_text)
    parking = detect_parking(combined_text)

    result.update({
        "denomination": denom,
        "denomination_confidence": confidence,
        "denomination_note": note,
        "languages_spoken": languages,
        "has_womens_section": womens,
        "has_parking": parking,
    })

    logger.info(
        f"  {name}: denom={denom or 'unknown'} ({confidence} hits) "
        f"langs={languages} womens={womens} parking={parking}"
    )
    return result


def save_enrichment(session: Session, result: dict, dry_run: bool):
    if dry_run:
        return

    params: dict = {"mid": result["mosque_id"]}
    set_clauses = ["denomination_enriched_at = NOW()", "updated_at = NOW()"]

    if result["denomination"] is not None:
        set_clauses.append("denomination = :denomination")
        set_clauses.append("denomination_source = 'website_scraped'")
        params["denomination"] = result["denomination"]

    if result["languages_spoken"]:
        set_clauses.append("languages_spoken = :languages")
        params["languages"] = result["languages_spoken"]

    if result["has_womens_section"] is not None:
        set_clauses.append("has_womens_section = :womens")
        params["womens"] = result["has_womens_section"]

    if result["has_parking"] is not None:
        set_clauses.append("has_parking = :parking")
        params["parking"] = result["has_parking"]

    if len(set_clauses) <= 2:
        return  # Nothing to update beyond timestamps

    sql = f"""
        UPDATE mosques SET {', '.join(set_clauses)}
        WHERE id = CAST(:mid AS uuid)
    """
    session.execute(text(sql), params)


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def run_enrichment(batch_size: int = 100, re_enrich: bool = False,
                         dry_run: bool = False) -> dict:
    engine = get_sync_engine()
    stats = {"processed": 0, "denominations_found": 0, "failed": 0}

    # Fetch mosques to enrich
    extra_filter = "" if re_enrich else "AND denomination_enriched_at IS NULL"
    with Session(engine) as session:
        rows = session.execute(text(f"""
            SELECT id::text, name, website
            FROM mosques
            WHERE is_active = true
              AND website IS NOT NULL
              {extra_filter}
            ORDER BY created_at ASC
            LIMIT :limit
        """), {"limit": batch_size}).mappings().all()

    mosques = [dict(r) for r in rows]
    logger.info(f"Enriching {len(mosques)} mosques (dry_run={dry_run})...")

    for m in mosques:
        try:
            result = await enrich_mosque(m["id"], m["name"], m["website"], dry_run)
            stats["processed"] += 1
            if result["denomination"]:
                stats["denominations_found"] += 1

            if not dry_run:
                with Session(engine) as session:
                    save_enrichment(session, result, dry_run)
                    session.commit()

        except Exception as e:
            stats["failed"] += 1
            logger.warning(f"  Failed: {m['name']}: {e}")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Enrich mosque denomination/language data")
    parser.add_argument("--mosque-id", help="Enrich a single mosque by UUID")
    parser.add_argument("--batch", type=int, default=100, help="Batch size (default: 100)")
    parser.add_argument("--re-enrich", action="store_true",
                        help="Re-process already-enriched mosques")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect and log but do not write to database")
    args = parser.parse_args()

    if args.mosque_id:
        engine = get_sync_engine()
        with Session(engine) as session:
            row = session.execute(text("""
                SELECT id::text, name, website FROM mosques
                WHERE id = CAST(:id AS uuid)
            """), {"id": args.mosque_id}).mappings().first()

        if not row:
            logger.error(f"Mosque {args.mosque_id} not found")
            return

        result = await enrich_mosque(row["id"], row["name"], row["website"], args.dry_run)
        logger.info(f"Result: {result}")
    else:
        stats = await run_enrichment(args.batch, args.re_enrich, args.dry_run)
        logger.info("=" * 50)
        logger.info(f"Processed:            {stats['processed']}")
        logger.info(f"Denominations found:  {stats['denominations_found']}")
        logger.info(f"Failed:               {stats['failed']}")
        if args.dry_run:
            logger.info("(dry run — no changes written)")


if __name__ == "__main__":
    asyncio.run(main())
