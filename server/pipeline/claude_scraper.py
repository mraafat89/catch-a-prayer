"""
Claude-powered Mosque Scraper
=============================
Uses Jina Reader (free JS rendering) + Claude API for structured extraction.

Flow:
  1. Jina Reader renders the mosque website → clean markdown
  2. Claude extracts structured data (prayer times, jumuah, facilities)
  3. Validates and saves to database

Usage:
    python -m pipeline.claude_scraper --test 5          # test 5 mosques, don't save
    python -m pipeline.claude_scraper --batch 20         # process 20 mosques
    python -m pipeline.claude_scraper --mosque-id <uuid> # scrape one mosque
    python -m pipeline.claude_scraper --all               # process all with websites
"""

import asyncio
import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime
from typing import Optional

import httpx
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

JINA_BASE = "https://r.jina.ai/"
JINA_TIMEOUT = 30
CLAUDE_MODEL = "claude-haiku-4-5-20251001"  # cheap + fast; upgrade to sonnet for retries

PRAYER_SUBPAGES = [
    "/prayer-times", "/prayer-times/", "/prayertimes", "/salah", "/salah-times",
    "/iqama", "/iqama-times", "/schedule", "/prayer-schedule", "/daily-prayer",
    "/prayers", "/namaz", "/times", "/salat",
]

EXTRACTION_PROMPT = """You are extracting mosque information from a website for a prayer times app.
Extract ALL available information and return ONLY a valid JSON object with this exact structure:

{
  "mosque_name": "string or null",
  "address": "full street address or null",
  "phone": "phone number or null",
  "email": "email or null",
  "prayer_times": {
    "fajr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "dhuhr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "asr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "maghrib": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "isha": {"adhan": "HH:MM", "iqama": "HH:MM"}
  },
  "sunrise": "HH:MM or null",
  "jumuah": [
    {"khutbah_time": "HH:MM", "prayer_time": "HH:MM", "language": "string", "imam": "string or null"}
  ],
  "has_womens_section": true/false/null,
  "wheelchair_accessible": true/false/null,
  "denomination": "sunni/shia/null",
  "languages_spoken": ["list of languages"],
  "facilities": ["list of facilities/amenities"],
  "operating_hours": "string or null",
  "notes": "any other relevant info"
}

RULES:
- Use 24-hour format for ALL times (HH:MM)
- Convert 12-hour times: 1:30 PM → 13:30, 6:15 AM → 06:15
- Use null for any field you cannot find — do NOT guess or make up data
- If prayer times are for a specific date, extract them as shown
- Include ALL jumuah/Friday prayer sessions if multiple exist
- For has_womens_section: true if sisters area/section mentioned, false if explicitly none, null if unknown
- Return ONLY the JSON object, no markdown fences, no explanation"""


def get_db():
    """Get a synchronous database connection."""
    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    # Convert async URL to sync
    sync_url = db_url.replace("+asyncpg", "").replace("postgresql://", "postgresql+psycopg2://")
    if "+psycopg2" not in sync_url and "psycopg2" not in sync_url:
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(sync_url)


async def fetch_with_jina(url: str) -> Optional[str]:
    """Fetch a URL through Jina Reader (renders JS, returns markdown)."""
    jina_url = f"{JINA_BASE}{url}"
    try:
        async with httpx.AsyncClient(timeout=JINA_TIMEOUT) as client:
            resp = await client.get(
                jina_url,
                headers={
                    "Accept": "text/markdown",
                    "User-Agent": "CatchAPrayer/1.0",
                },
            )
            if resp.status_code == 200:
                content = resp.text
                # Jina sometimes returns very large pages; truncate to keep Claude costs down
                if len(content) > 15000:
                    content = content[:15000] + "\n\n[CONTENT TRUNCATED]"
                return content
            else:
                logger.warning(f"  Jina returned {resp.status_code} for {url}")
                return None
    except Exception as e:
        logger.warning(f"  Jina fetch failed for {url}: {e}")
        return None


async def extract_with_claude(markdown: str, mosque_name: str, model: str = CLAUDE_MODEL) -> Optional[dict]:
    """Send rendered markdown to Claude for structured extraction."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": f"Website content for {mosque_name}:\n\n{markdown}\n\n{EXTRACTION_PROMPT}",
            }],
        )
        raw = response.content[0].text.strip()

        # Clean up: remove markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)

        # Track token usage
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        logger.info(f"  Claude: {input_tokens} in / {output_tokens} out tokens")

        return data
    except json.JSONDecodeError as e:
        logger.warning(f"  Claude returned invalid JSON: {e}")
        logger.debug(f"  Raw response: {raw[:200]}")
        return None
    except Exception as e:
        logger.warning(f"  Claude extraction failed: {e}")
        return None


def validate_prayer_time(time_str: Optional[str]) -> Optional[str]:
    """Validate and normalize a prayer time string."""
    if not time_str or time_str == "null" or time_str == "":
        return None
    # Remove leading/trailing whitespace
    time_str = time_str.strip()
    # Must match HH:MM format
    if len(time_str) >= 4 and ":" in time_str:
        parts = time_str.split(":")
        try:
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
        except ValueError:
            pass
    return None


def validate_extraction(data: dict) -> dict:
    """Validate and clean the extracted data."""
    result = {
        "mosque_name": data.get("mosque_name"),
        "address": data.get("address"),
        "phone": data.get("phone"),
        "email": data.get("email"),
        "prayer_times": {},
        "sunrise": validate_prayer_time(data.get("sunrise")),
        "jumuah": [],
        "has_womens_section": data.get("has_womens_section"),
        "wheelchair_accessible": data.get("wheelchair_accessible"),
        "denomination": data.get("denomination"),
        "languages_spoken": data.get("languages_spoken", []),
        "facilities": data.get("facilities", []),
        "notes": data.get("notes"),
    }

    # Validate prayer times
    pt = data.get("prayer_times", {})
    prayers_found = 0
    for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
        p_data = pt.get(prayer, {}) if isinstance(pt.get(prayer), dict) else {}
        adhan = validate_prayer_time(p_data.get("adhan"))
        iqama = validate_prayer_time(p_data.get("iqama"))
        result["prayer_times"][prayer] = {"adhan": adhan, "iqama": iqama}
        if adhan or iqama:
            prayers_found += 1

    result["prayers_found"] = prayers_found

    # Validate jumuah
    for j in data.get("jumuah", []):
        if isinstance(j, dict):
            entry = {
                "khutbah_time": validate_prayer_time(j.get("khutbah_time")),
                "prayer_time": validate_prayer_time(j.get("prayer_time")),
                "language": j.get("language"),
                "imam": j.get("imam"),
            }
            if entry["khutbah_time"] or entry["prayer_time"]:
                result["jumuah"].append(entry)

    return result


async def scrape_mosque(mosque_id: str, name: str, website: str,
                         model: str = CLAUDE_MODEL, dry_run: bool = False) -> dict:
    """Scrape a single mosque using Jina + Claude. Tries homepage first, then prayer subpages."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Scraping: {name}")
    logger.info(f"  URL: {website}")

    start = time.time()

    # Step 1: Fetch homepage with Jina
    markdown = await fetch_with_jina(website)
    if not markdown:
        return {"mosque_id": mosque_id, "success": False, "error": "Jina fetch failed", "elapsed": time.time() - start}

    jina_time = time.time() - start
    logger.info(f"  Jina (homepage): {len(markdown)} chars in {jina_time:.1f}s")

    # Step 2: Extract from homepage
    data = await extract_with_claude(markdown, name, model=model)
    if not data:
        return {"mosque_id": mosque_id, "success": False, "error": "Claude extraction failed", "elapsed": time.time() - start}

    validated = validate_extraction(data)

    # Step 3: If no prayer times found on homepage, try common subpages
    if validated["prayers_found"] == 0:
        base_url = website.rstrip("/")
        logger.info(f"  No prayer times on homepage, trying subpages...")

        for subpage in PRAYER_SUBPAGES:
            sub_url = f"{base_url}{subpage}"
            sub_md = await fetch_with_jina(sub_url)
            if not sub_md or len(sub_md) < 50:
                continue

            logger.info(f"  Trying {subpage}: {len(sub_md)} chars")
            sub_data = await extract_with_claude(sub_md, name, model=model)
            if sub_data:
                sub_validated = validate_extraction(sub_data)
                if sub_validated["prayers_found"] > validated["prayers_found"]:
                    logger.info(f"  Found {sub_validated['prayers_found']}/5 prayers on {subpage}!")
                    # Merge: keep enrichment from homepage, prayer times from subpage
                    validated["prayer_times"] = sub_validated["prayer_times"]
                    validated["prayers_found"] = sub_validated["prayers_found"]
                    if sub_validated["sunrise"]:
                        validated["sunrise"] = sub_validated["sunrise"]
                    # Also merge any jumuah found on subpage
                    if len(sub_validated["jumuah"]) > len(validated["jumuah"]):
                        validated["jumuah"] = sub_validated["jumuah"]
                    break

            # Rate limit between subpage attempts
            await asyncio.sleep(0.5)

    elapsed = time.time() - start

    logger.info(f"  Result: {validated['prayers_found']}/5 prayers, "
                f"{len(validated['jumuah'])} jumuah sessions, "
                f"women={validated['has_womens_section']}, "
                f"denomination={validated['denomination']}")
    logger.info(f"  Languages: {validated.get('languages_spoken', [])}")
    logger.info(f"  Facilities: {validated.get('facilities', [])}")
    logger.info(f"  Time: {elapsed:.1f}s")

    return {
        "mosque_id": mosque_id,
        "name": name,
        "website": website,
        "success": True,
        "data": validated,
        "elapsed": elapsed,
    }


async def run(args):
    engine = get_db()

    with engine.connect() as conn:
        # Get mosques to scrape
        if args.mosque_id:
            rows = conn.execute(text(
                "SELECT id::text, name, website FROM mosques WHERE id = :id AND website IS NOT NULL"
            ), {"id": args.mosque_id}).fetchall()
        else:
            limit = args.batch or (5 if args.test else 1000)
            rows = conn.execute(text("""
                SELECT id::text, name, website FROM mosques
                WHERE is_active = true AND website IS NOT NULL
                  AND website NOT LIKE '%%facebook.com%%'
                ORDER BY updated_at ASC NULLS FIRST
                LIMIT :limit
            """), {"limit": limit}).fetchall()

    logger.info(f"Found {len(rows)} mosques to scrape")

    results = []
    success_count = 0
    prayers_found_total = 0
    jumuah_found_total = 0

    for i, row in enumerate(rows):
        mosque_id, name, website = row[0], row[1], row[2]

        result = await scrape_mosque(
            mosque_id, name, website,
            model=args.model or CLAUDE_MODEL,
            dry_run=args.test or args.dry_run,
        )
        results.append(result)

        if result["success"]:
            success_count += 1
            data = result["data"]
            prayers_found_total += data["prayers_found"]
            jumuah_found_total += len(data["jumuah"])

        # Rate limit: don't hammer Jina
        if i < len(rows) - 1:
            await asyncio.sleep(1)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"SUMMARY")
    logger.info(f"  Total: {len(results)}")
    logger.info(f"  Success: {success_count} ({success_count*100//max(len(results),1)}%)")
    logger.info(f"  Prayer times found: {prayers_found_total} across {success_count} mosques")
    logger.info(f"  Jumuah sessions found: {jumuah_found_total}")
    logger.info(f"  Failed: {len(results) - success_count}")

    # Print detailed results if test mode
    if args.test or args.verbose:
        for r in results:
            if r["success"]:
                d = r["data"]
                print(f"\n--- {r['name']} ({r['website']}) ---")
                print(f"  Prayers: {d['prayers_found']}/5")
                for p in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
                    pt = d["prayer_times"][p]
                    if pt["adhan"] or pt["iqama"]:
                        print(f"    {p}: adhan={pt['adhan']} iqama={pt['iqama']}")
                if d["jumuah"]:
                    print(f"  Jumuah: {d['jumuah']}")
                if d["has_womens_section"] is not None:
                    print(f"  Women's section: {d['has_womens_section']}")
                if d["denomination"]:
                    print(f"  Denomination: {d['denomination']}")
                if d["languages_spoken"]:
                    print(f"  Languages: {d['languages_spoken']}")
                if d["facilities"]:
                    print(f"  Facilities: {d['facilities']}")
            else:
                print(f"\n--- {r.get('name', r['mosque_id'])} — FAILED: {r['error']} ---")

    return results


def main():
    parser = argparse.ArgumentParser(description="Claude-powered mosque scraper")
    parser.add_argument("--test", type=int, metavar="N", help="Test N mosques (don't save)")
    parser.add_argument("--batch", type=int, metavar="N", help="Process N mosques")
    parser.add_argument("--mosque-id", type=str, help="Scrape a specific mosque by UUID")
    parser.add_argument("--all", action="store_true", help="Process all mosques with websites")
    parser.add_argument("--model", type=str, help=f"Claude model (default: {CLAUDE_MODEL})")
    parser.add_argument("--dry-run", action="store_true", help="Don't save to database")
    parser.add_argument("--verbose", action="store_true", help="Print detailed results")
    args = parser.parse_args()

    if not any([args.test, args.batch, args.mosque_id, args.all]):
        parser.print_help()
        sys.exit(1)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
