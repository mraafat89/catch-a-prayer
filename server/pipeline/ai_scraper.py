"""
AI-Powered Prayer Time Scraper (Gemini Vision)
================================================
Uses Gemini to extract prayer times from mosque websites.
Handles cases the regex scraper can't: images, complex layouts, JS widgets.

Strategy:
1. Playwright screenshots the mosque website
2. Gemini Vision analyzes the screenshot and extracts prayer times
3. Validation + save to DB

Cost: FREE (Gemini free tier: 15 RPM, 1M tokens/day)

Usage:
    python -m pipeline.ai_scraper --limit 10       # test on 10 sites
    python -m pipeline.ai_scraper --all             # all remaining sites
    python -m pipeline.ai_scraper --url https://... # specific site
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import re
from datetime import date

import httpx
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"

pg_pass = os.environ.get("POSTGRES_PASSWORD", "cap")
pg_user = os.environ.get("POSTGRES_USER", "cap")
pg_db = os.environ.get("POSTGRES_DB", "catchaprayer")
DB_URL = f"postgresql+psycopg2://{pg_user}:{pg_pass}@db:5432/{pg_db}" if pg_pass != "cap" else None

EXTRACTION_PROMPT = """Look at this mosque website screenshot. Extract ALL prayer time information you can see.

Return ONLY a JSON object with this exact structure (no markdown, no explanation):
{
  "fajr_adhan": "HH:MM AM/PM or null",
  "fajr_iqama": "HH:MM AM/PM or null",
  "sunrise": "HH:MM AM/PM or null",
  "dhuhr_adhan": "HH:MM AM/PM or null",
  "dhuhr_iqama": "HH:MM AM/PM or null",
  "asr_adhan": "HH:MM AM/PM or null",
  "asr_iqama": "HH:MM AM/PM or null",
  "maghrib_adhan": "HH:MM AM/PM or null",
  "maghrib_iqama": "HH:MM AM/PM or null",
  "isha_adhan": "HH:MM AM/PM or null",
  "isha_iqama": "HH:MM AM/PM or null",
  "jumuah_time": "HH:MM AM/PM or null",
  "jumuah_khutba": "HH:MM AM/PM or null",
  "jumuah_imam": "name or null",
  "has_data": true/false
}

If you see prayer times in ANY format (table, list, image, widget), extract them.
Use null for any field you can't find. Set has_data to false if no prayer times are visible at all.
Prayer names may be spelled differently: Zuhr/Dhuhr, Magrib/Maghrib, Fajir/Fajr, etc."""


async def screenshot_and_extract(url: str, browser) -> dict | None:
    """Screenshot a mosque website and extract prayer times via Gemini."""
    page = None
    try:
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(5000)

        # Take screenshot
        screenshot_bytes = await page.screenshot(full_page=False)  # viewport only
        await page.close()
        page = None

        # Send to Gemini
        b64_image = base64.b64encode(screenshot_bytes).decode("utf-8")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(GEMINI_URL, json={
                "contents": [{
                    "parts": [
                        {"text": EXTRACTION_PROMPT},
                        {"inline_data": {"mime_type": "image/png", "data": b64_image}}
                    ]
                }],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500}
            })

            if resp.status_code != 200:
                log.debug(f"Gemini error: {resp.status_code}")
                return None

            result = resp.json()
            text_response = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

            # Parse JSON from response
            json_match = re.search(r'\{[^{}]+\}', text_response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if data.get("has_data"):
                    return data

    except Exception as e:
        log.debug(f"Failed: {e}")
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
    return None


def normalize_time(val: str | None) -> str | None:
    """Convert '5:30 AM' to '05:30'."""
    if not val or val == "null":
        return None
    m = re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)$', val.strip())
    if not m:
        return None
    h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ampm == "pm" and h < 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}"


def save_to_db(engine, mosque_id: str, data: dict, today: date):
    """Save Gemini-extracted prayer times to DB."""
    from pipeline.validation import validate_prayer_schedule

    values = {"mosque_id": mosque_id, "date": today}
    field_map = {
        "fajr_adhan": "fajr_adhan", "fajr_iqama": "fajr_iqama",
        "sunrise": "sunrise",
        "dhuhr_adhan": "dhuhr_adhan", "dhuhr_iqama": "dhuhr_iqama",
        "asr_adhan": "asr_adhan", "asr_iqama": "asr_iqama",
        "maghrib_adhan": "maghrib_adhan", "maghrib_iqama": "maghrib_iqama",
        "isha_adhan": "isha_adhan", "isha_iqama": "isha_iqama",
    }
    source_map = {
        "fajr_adhan": "fajr_adhan_source", "dhuhr_adhan": "dhuhr_adhan_source",
        "asr_adhan": "asr_adhan_source", "maghrib_adhan": "maghrib_adhan_source",
        "isha_adhan": "isha_adhan_source", "sunrise": "sunrise_source",
        "fajr_iqama": "fajr_iqama_source", "dhuhr_iqama": "dhuhr_iqama_source",
        "asr_iqama": "asr_iqama_source", "maghrib_iqama": "maghrib_iqama_source",
        "isha_iqama": "isha_iqama_source",
    }

    for json_key, db_col in field_map.items():
        t = normalize_time(data.get(json_key))
        if t:
            values[db_col] = t
            if db_col in source_map:
                values[source_map[db_col]] = "gemini_vision"

    if len(values) <= 2:
        return False

    # Validate
    flat = {k: v for k, v in values.items() if k not in ("mosque_id", "date") and "_source" not in k}
    vr = validate_prayer_schedule(flat)
    if not vr.valid:
        log.info(f"  Validation failed: {vr.issues[0]['issue'] if vr.issues else 'unknown'}")
        return False

    import uuid
    values["id"] = str(uuid.uuid4())
    with engine.begin() as conn:
        cols = ", ".join(values.keys())
        placeholders = ", ".join(f":{k}" for k in values.keys())
        updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in values.keys() if k not in ("mosque_id", "date", "id"))
        conn.execute(text(f"""
            INSERT INTO prayer_schedules ({cols}) VALUES ({placeholders})
            ON CONFLICT (mosque_id, date) DO UPDATE SET {updates}
        """), values)

        conn.execute(text(
            "UPDATE scraping_jobs SET status = 'success', scraped_at = now(), scrape_method = 'gemini_vision' WHERE mosque_id = :mid"
        ), {"mid": mosque_id})

    # Save jumuah if found
    jumuah_time = normalize_time(data.get("jumuah_time"))
    if jumuah_time:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO jumuah_sessions (id, mosque_id, prayer_start, session_number, source, valid_date)
                VALUES (gen_random_uuid(), CAST(:mid AS uuid), :time, 1, 'gemini_vision', CURRENT_DATE)
                ON CONFLICT DO NOTHING
            """), {"mid": mosque_id, "time": jumuah_time})

    return True


async def run(args):
    if not GEMINI_KEY:
        log.error("No GEMINI_API_KEY or GOOGLE_API_KEY set")
        return

    engine = create_engine(DB_URL) if DB_URL else None
    if not engine:
        log.error("No DB connection")
        return

    today = date.today()

    # Get sites to scrape
    if args.url:
        websites = [{"id": "test", "name": "Test", "website": args.url}]
    else:
        limit = args.limit or 400
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT m.id::text, m.name, m.website
                FROM mosques m
                JOIN scraping_jobs sj ON sj.mosque_id = m.id AND sj.website_alive = true
                WHERE m.is_active AND m.website IS NOT NULL
                  AND m.website NOT LIKE '%facebook%' AND m.website NOT LIKE '%instagram%'
                  AND m.website NOT LIKE '%youtube%' AND m.website NOT LIKE '%yelp%'
                  AND m.website NOT LIKE '%x.com%'
                  AND m.id NOT IN (SELECT mosque_id FROM prayer_schedules
                      WHERE date = CURRENT_DATE AND fajr_adhan_source NOT IN ('calculated'))
                ORDER BY CASE WHEN m.state IN ('NY','CA','TX','IL','NJ','FL','MI','PA') THEN 0 ELSE 1 END, random()
                LIMIT :lim
            """), {"lim": limit}).fetchall()
            websites = [{"id": r[0], "name": r[1], "website": r[2]} for r in rows]

    log.info(f"AI scraping {len(websites)} sites with Gemini Vision")

    from playwright.async_api import async_playwright
    stats = {"attempted": 0, "success": 0, "no_data": 0, "error": 0}
    sem = asyncio.Semaphore(3)  # 3 concurrent (Gemini rate limit: 15 RPM)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])

        async def process_one(w):
            async with sem:
                stats["attempted"] += 1
                log.info(f"  {w['name']}: {w['website']}")
                data = await screenshot_and_extract(w["website"], browser)
                if data:
                    stats["success"] += 1
                    adhan_count = sum(1 for k in ["fajr_adhan", "dhuhr_adhan", "asr_adhan", "maghrib_adhan", "isha_adhan"] if data.get(k) and data[k] != "null")
                    iqama_count = sum(1 for k in ["fajr_iqama", "dhuhr_iqama", "asr_iqama", "maghrib_iqama", "isha_iqama"] if data.get(k) and data[k] != "null")
                    log.info(f"  ✓ {adhan_count} adhan, {iqama_count} iqama")
                    if engine and w["id"] != "test":
                        save_to_db(engine, w["id"], data, today)
                else:
                    stats["no_data"] += 1
                    log.info(f"  ✗ No data")
                await asyncio.sleep(4)  # Stay under 15 RPM

        tasks = [process_one(w) for w in websites]
        await asyncio.gather(*tasks, return_exceptions=True)
        await browser.close()

    log.info(f"\n=== AI SCRAPE COMPLETE ===")
    log.info(f"Attempted: {stats['attempted']} | Success: {stats['success']} | No data: {stats['no_data']}")
    rate = stats['success'] * 100 // max(stats['attempted'], 1)
    log.info(f"Success rate: {rate}%")


def main():
    parser = argparse.ArgumentParser(description="AI-powered prayer time scraper (Gemini Vision)")
    parser.add_argument("--limit", type=int, help="Max sites to scrape")
    parser.add_argument("--all", action="store_true", help="All remaining sites")
    parser.add_argument("--url", type=str, help="Test specific URL")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
