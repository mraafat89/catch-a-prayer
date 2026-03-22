"""
Test extraction against specific sites.
Fetches via Jina, runs extraction, shows what was found/missed.

Usage:
    python -m pipeline.test_extraction                    # test 10 random failed sites
    python -m pipeline.test_extraction --url https://...  # test specific URL
    python -m pipeline.test_extraction --limit 20         # test 20 sites
"""
import argparse
import asyncio
import os
import httpx
from datetime import date
from sqlalchemy import create_engine, text

from pipeline.smart_bulk_scraper import (
    extract_times_from_text, sanitize_schedule, validate_schedule,
    PRAYER_NAMES, TIME_RE,
)

pg_pass = os.environ.get("POSTGRES_PASSWORD", "cap")
pg_user = os.environ.get("POSTGRES_USER", "cap")
pg_db = os.environ.get("POSTGRES_DB", "catchaprayer")
DB_URL = f"postgresql+psycopg2://{pg_user}:{pg_pass}@db:5432/{pg_db}" if pg_pass != "cap" else None

JINA_PATHS = [
    "", "/prayer-times", "/prayer-time", "/prayers", "/prayer-timings",
    "/prayer-timing", "/prayer-schedule", "/iqama", "/salah-times",
    "/horaires-de-priere",
]


async def test_url(url: str) -> dict:
    """Test extraction on a single URL."""
    result = {"url": url, "category": "unknown", "adhan": {}, "iqama": {}, "lines": []}
    base = url.rstrip("/")

    async with httpx.AsyncClient(timeout=20) as c:
        for path in JINA_PATHS:
            target = base + path if path else url
            try:
                r = await c.get(f"https://r.jina.ai/{target}", headers={"Accept": "text/plain"})
                if r.status_code != 200:
                    continue

                text_content = r.text
                if len(text_content) < 100:
                    continue

                # Find prayer-related lines
                prayer_lines = []
                for line in text_content.split("\n"):
                    ll = line.lower().strip()
                    if not ll:
                        continue
                    has_prayer = any(p in ll for p in PRAYER_NAMES)
                    has_time = bool(TIME_RE.search(line))
                    if has_prayer or (has_time and any(w in ll for w in ["iqama", "athan", "adhan", "prayer", "salah"])):
                        prayer_lines.append(line.strip()[:150])

                if prayer_lines:
                    result["lines"] = prayer_lines[:15]
                    result["found_on"] = path or "/"

                    # Run extraction
                    data = extract_times_from_text(text_content)
                    data = sanitize_schedule(data)
                    result["adhan"] = data.get("adhan", {})
                    result["iqama"] = data.get("iqama", {})
                    result["jumuah"] = data.get("jumuah", [])
                    result["valid"] = validate_schedule(data)

                    if len(result["adhan"]) >= 3:
                        result["category"] = "A_EXTRACTED"
                    elif len(result["adhan"]) >= 1:
                        result["category"] = "A_PARTIAL"
                    else:
                        result["category"] = "A_MISSED"  # has prayer lines but extraction failed
                    return result

            except Exception:
                continue
            await asyncio.sleep(1)

    result["category"] = "E_NO_DATA"
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", type=str, help="Test specific URL")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    if args.url:
        urls = [args.url]
    elif DB_URL:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT m.website FROM mosques m
                JOIN scraping_jobs sj ON sj.mosque_id = m.id AND sj.website_alive = true
                WHERE m.is_active AND m.website IS NOT NULL
                  AND m.website NOT LIKE '%facebook%' AND m.website NOT LIKE '%instagram%'
                  AND m.website NOT LIKE '%youtube%' AND m.website NOT LIKE '%yelp%'
                  AND m.website NOT LIKE '%x.com%' AND m.website NOT LIKE '%ahmadiyya%'
                  AND m.website NOT LIKE '%alislam%'
                  AND m.id NOT IN (SELECT mosque_id FROM prayer_schedules
                      WHERE date = CURRENT_DATE AND fajr_adhan_source NOT IN ('calculated'))
                ORDER BY random() LIMIT :lim
            """), {"lim": args.limit}).fetchall()
        urls = [r[0] for r in rows]
    else:
        print("No DB connection and no --url provided")
        return

    categories = {"A_EXTRACTED": 0, "A_PARTIAL": 0, "A_MISSED": 0, "E_NO_DATA": 0}

    for url in urls:
        result = await test_url(url)
        cat = result["category"]
        categories[cat] = categories.get(cat, 0) + 1

        if cat == "A_MISSED":
            print(f"\nMISSED: {url}")
            print(f"  Found on: {result.get('found_on', '?')}")
            print(f"  Prayer lines ({len(result['lines'])}):")
            for pl in result["lines"][:8]:
                print(f"    {pl}")
            print(f"  Extracted: adhan={result['adhan']}, iqama={result['iqama']}")

        elif cat == "A_PARTIAL":
            print(f"\nPARTIAL: {url} — {len(result['adhan'])} adhan")
            for pl in result["lines"][:5]:
                print(f"    {pl}")
            print(f"  Extracted: adhan={result['adhan']}")

        elif cat == "A_EXTRACTED":
            print(f"\nEXTRACTED: {url} — {len(result['adhan'])} adhan, {len(result['iqama'])} iqama (valid={result['valid']})")

        elif cat == "E_NO_DATA":
            print(f"\nNO_DATA: {url}")

        await asyncio.sleep(2)

    print(f"\n=== SUMMARY ===")
    total = len(urls)
    for cat, cnt in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {cnt} ({cnt*100//max(total,1)}%)")
    print(f"  Fixable (MISSED+PARTIAL): {categories.get('A_MISSED',0) + categories.get('A_PARTIAL',0)}")


if __name__ == "__main__":
    asyncio.run(main())
