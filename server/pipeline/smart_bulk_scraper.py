"""
Smart Bulk Scraper — Playwright-based prayer time extraction
==============================================================
Three phases:
  1. ALIVE CHECK — fast HTTP HEAD on all websites, mark dead ones
  2. RENDER — Playwright loads live sites, extracts visible text
  3. EXTRACT — regex + heuristics pull prayer times from rendered text

Usage:
    python -m pipeline.smart_bulk_scraper --check-alive          # Phase 1 only
    python -m pipeline.smart_bulk_scraper --scrape --limit 20    # Phase 2+3 on 20 sites
    python -m pipeline.smart_bulk_scraper --scrape --all         # Phase 2+3 on all alive sites
    python -m pipeline.smart_bulk_scraper --analyze              # Show stats only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime

import httpx
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
settings = get_settings()

DB_URL = os.environ.get("DATABASE_URL", settings.database_url).replace("+asyncpg", "+psycopg2")
if "psycopg2" not in DB_URL:
    DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg2://")

# ---------------------------------------------------------------------------
# Prayer time extraction patterns (improved)
# ---------------------------------------------------------------------------

PRAYER_NAMES = {
    "fajr": "fajr", "fajar": "fajr", "subh": "fajr", "dawn": "fajr",
    "sunrise": "sunrise", "shuruq": "sunrise", "ishraq": "sunrise",
    "dhuhr": "dhuhr", "zuhr": "dhuhr", "dhuhur": "dhuhr", "noon": "dhuhr",
    "asr": "asr", "asar": "asr",
    "maghrib": "maghrib", "magrib": "maghrib", "sunset": "maghrib", "iftar": "maghrib",
    "isha": "isha", "ishaa": "isha", "esha": "isha",
}

JUMUAH_NAMES = {"jumuah", "jummah", "jumma", "jumu'ah", "friday", "khutbah", "khutba"}

# Time patterns: 12:30, 12:30 PM, 12:30PM, 1:30pm
TIME_RE = re.compile(r'\b(\d{1,2}):(\d{2})\s*(am|pm|AM|PM|a\.m\.|p\.m\.)?\b')

# Iqama offset pattern: +15, +20 min
OFFSET_RE = re.compile(r'\+\s*(\d{1,3})\s*(?:min|minutes?|mins?)?', re.IGNORECASE)


def extract_times_from_text(text_content: str) -> dict:
    """
    Extract prayer times from rendered page text.
    Returns dict with prayer names as keys and time strings as values.
    """
    lines = text_content.split('\n')
    results = {"adhan": {}, "iqama": {}, "jumuah": []}

    # Strategy 1: Look for tabular data (prayer name followed by times on same/next line)
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        if not line_lower:
            continue

        # Check if this line contains a prayer name
        found_prayer = None
        for pattern, canonical in PRAYER_NAMES.items():
            if pattern in line_lower:
                found_prayer = canonical
                break

        if not found_prayer:
            # Check jumuah
            if any(j in line_lower for j in JUMUAH_NAMES):
                # Look for times on this line and next few lines
                context = " ".join(lines[i:i+3])
                times = TIME_RE.findall(context)
                for h, m, ampm in times:
                    t = _normalize_time(h, m, ampm)
                    if t and 11 <= int(t.split(":")[0]) <= 15:  # Jumuah is around noon
                        results["jumuah"].append(t)
            continue

        # Found a prayer name — look for times on this line and next 2 lines
        context = " ".join(lines[i:i+3])
        times = TIME_RE.findall(context)

        if len(times) >= 2:
            # First time = adhan, second = iqama (common pattern)
            results["adhan"][found_prayer] = _normalize_time(*times[0])
            results["iqama"][found_prayer] = _normalize_time(*times[1])
        elif len(times) == 1:
            results["adhan"][found_prayer] = _normalize_time(*times[0])
            # Check for iqama offset
            offsets = OFFSET_RE.findall(context)
            if offsets:
                results["iqama"][found_prayer] = f"+{offsets[0]}"

    # Strategy 2: Look for a grid/table pattern (all times in a block)
    if len(results["adhan"]) < 3:
        # Try to find a dense block of times
        _extract_from_grid(lines, results)

    return results


def _extract_from_grid(lines: list[str], results: dict):
    """Look for a dense block of 5-6 times that might be a prayer schedule."""
    # Find lines with multiple times
    for i, line in enumerate(lines):
        times = TIME_RE.findall(line)
        if len(times) >= 5:
            # This might be a row of all prayer times
            prayer_order = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
            for j, (h, m, ampm) in enumerate(times[:6]):
                if j < len(prayer_order):
                    t = _normalize_time(h, m, ampm)
                    if t and prayer_order[j] not in results["adhan"]:
                        results["adhan"][prayer_order[j]] = t
            # Check next line for iqama times
            if i + 1 < len(lines):
                iqama_times = TIME_RE.findall(lines[i + 1])
                if len(iqama_times) >= 4:
                    iqama_order = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
                    for j, (h, m, ampm) in enumerate(iqama_times[:5]):
                        if j < len(iqama_order):
                            t = _normalize_time(h, m, ampm)
                            if t:
                                results["iqama"][iqama_order[j]] = t


def _normalize_time(h: str, m: str, ampm: str | None) -> str | None:
    """Normalize to 24h HH:MM format."""
    hour = int(h)
    minute = int(m)
    if minute > 59:
        return None

    if ampm:
        ampm = ampm.lower().replace(".", "")
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    else:
        # No AM/PM — infer from prayer context (handled by caller)
        pass

    if hour > 23:
        return None

    return f"{hour:02d}:{minute:02d}"


def validate_schedule(data: dict) -> bool:
    """Check if extracted data looks like a real prayer schedule."""
    adhan = data.get("adhan", {})
    if len(adhan) < 3:
        return False

    # Basic sanity: fajr should be before sunrise, dhuhr before asr, etc.
    # Just check we have reasonable times
    for prayer, t in adhan.items():
        if not t or ":" not in t:
            continue
        h = int(t.split(":")[0])
        if prayer == "fajr" and not (3 <= h <= 7):
            return False
        if prayer == "dhuhr" and not (11 <= h <= 14):
            return False
        if prayer == "isha" and not (18 <= h <= 23):
            return False

    return True


# ---------------------------------------------------------------------------
# Phase 1: Alive check
# ---------------------------------------------------------------------------

async def check_alive(websites: list[dict], engine) -> dict:
    """Fast concurrent alive check on all websites."""
    results = {"alive": 0, "dead": 0, "redirect": 0, "timeout": 0, "error": 0}

    sem = asyncio.Semaphore(20)  # 20 concurrent checks

    async def check_one(mosque_id: str, url: str):
        async with sem:
            try:
                async with httpx.AsyncClient(
                    timeout=10, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; CatchAPrayer/1.0)"}
                ) as client:
                    resp = await client.head(url)
                    alive = resp.status_code < 400
                    return mosque_id, url, alive, resp.status_code
            except httpx.TimeoutException:
                return mosque_id, url, False, "timeout"
            except Exception as e:
                return mosque_id, url, False, str(type(e).__name__)

    tasks = [check_one(w["id"], w["website"]) for w in websites]

    log.info(f"Checking {len(tasks)} websites (20 concurrent)...")
    completed = 0
    batch_size = 100

    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        batch_results = await asyncio.gather(*batch)
        completed += len(batch_results)

        alive_ids = []
        dead_ids = []

        for mosque_id, url, alive, status in batch_results:
            if alive:
                results["alive"] += 1
                alive_ids.append(mosque_id)
            else:
                results["dead"] += 1
                dead_ids.append(mosque_id)

        # Batch update DB
        with engine.begin() as conn:
            if alive_ids:
                conn.execute(text("""
                    INSERT INTO scraping_jobs (id, mosque_id, status, website_alive, website_checked_at)
                    SELECT gen_random_uuid(), m.id, 'pending', true, now()
                    FROM mosques m WHERE m.id::text = ANY(:ids)
                    ON CONFLICT (mosque_id) DO UPDATE SET website_alive = true, website_checked_at = now()
                """), {"ids": alive_ids})
            if dead_ids:
                conn.execute(text("""
                    INSERT INTO scraping_jobs (id, mosque_id, status, website_alive, website_checked_at)
                    SELECT gen_random_uuid(), m.id, 'failed', false, now()
                    FROM mosques m WHERE m.id::text = ANY(:ids)
                    ON CONFLICT (mosque_id) DO UPDATE SET website_alive = false, website_checked_at = now()
                """), {"ids": dead_ids})

        if completed % 200 == 0 or completed == len(tasks):
            log.info(f"  Progress: {completed}/{len(tasks)} — {results['alive']} alive, {results['dead']} dead")

    return results


# ---------------------------------------------------------------------------
# Phase 2+3: Playwright render + extract
# ---------------------------------------------------------------------------

PRAYER_LINK_KEYWORDS = re.compile(
    r'prayer|salah|salat|iqama|namaz|schedule|times|daily|athan|adhan',
    re.IGNORECASE
)

FALLBACK_PATHS = [
    "/prayer-times", "/prayer-time", "/prayers", "/salah-times",
    "/iqama", "/iqama-times", "/prayer-schedule", "/prayertimes",
    "/salat", "/daily-prayers", "/schedule", "/prayer",
    "/index.php/prayer-schedules", "/index.php/prayer-times",
    "/prayer-times-iqama", "/services/prayer-times",
]


async def _discover_prayer_page(page, base_url: str) -> str | None:
    """
    Find the prayer times page by:
    1. Scanning all <a> links on the page for prayer-related keywords
    2. Falling back to common URL patterns
    """
    from urllib.parse import urljoin

    # Strategy 1: Parse nav/footer links for prayer-related keywords
    try:
        links = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                href: a.href,
                text: (a.textContent || '').trim().substring(0, 100)
            })).filter(l => l.href && l.text);
        }""")

        for link in links:
            if PRAYER_LINK_KEYWORDS.search(link["text"]) or PRAYER_LINK_KEYWORDS.search(link["href"]):
                href = link["href"]
                # Skip anchors, mailto, tel, social media
                if any(x in href for x in ["#", "mailto:", "tel:", "facebook", "instagram", "twitter", "youtube"]):
                    continue
                # Must be same domain or relative
                from urllib.parse import urlparse
                link_domain = urlparse(href).netloc.replace("www.", "")
                base_domain = urlparse(base_url).netloc.replace("www.", "")
                if link_domain and link_domain != base_domain:
                    continue
                log.info(f"  🔗 Found nav link: '{link['text'][:40]}' → {href}")
                return href
    except Exception:
        pass

    # Strategy 2: Try common URL patterns
    base = base_url.rstrip("/")
    for path in FALLBACK_PATHS:
        try:
            full_url = base + path
            resp = await page.context.request.head(full_url, timeout=5000)
            if resp.ok:
                log.info(f"  🔗 Found path: {path}")
                return full_url
        except Exception:
            continue

    return None


async def scrape_with_playwright(websites: list[dict], engine, save: bool = True) -> dict:
    """Render websites with Playwright and extract prayer times."""
    from playwright.async_api import async_playwright

    stats = {"attempted": 0, "success": 0, "no_data": 0, "error": 0}
    today = date.today()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        for i, w in enumerate(websites):
            stats["attempted"] += 1
            mosque_id = w["id"]
            url = w["website"]
            name = w["name"]

            try:
                page = await context.new_page()
                log.info(f"[{i+1}/{len(websites)}] {name}: {url}")

                # Navigate with timeout
                resp = await page.goto(url, wait_until="networkidle", timeout=20000)

                # --- Hijack/redirect detection ---
                final_url = page.url
                from urllib.parse import urlparse
                orig_domain = urlparse(url).netloc.replace("www.", "")
                final_domain = urlparse(final_url).netloc.replace("www.", "")
                if orig_domain and final_domain and orig_domain != final_domain:
                    # Allow subdomains but reject totally different domains
                    if not final_domain.endswith(orig_domain) and not orig_domain.endswith(final_domain):
                        log.info(f"  ✗ Redirected to unrelated domain: {final_domain}")
                        stats["error"] += 1
                        await page.close()
                        continue

                # Wait for JS frameworks (Wix, React, etc.) to render
                await page.wait_for_timeout(3000)

                # Get all visible text from homepage
                text_content = await page.inner_text("body")

                # Also check for iframes (prayer widgets often in iframes)
                iframes = await page.query_selector_all("iframe")
                for iframe in iframes[:3]:
                    try:
                        frame = await iframe.content_frame()
                        if frame:
                            iframe_text = await frame.inner_text("body")
                            text_content += "\n" + iframe_text
                    except Exception:
                        pass

                # If no prayer data on homepage, discover prayer page from nav links
                quick_check = extract_times_from_text(text_content)
                if len(quick_check.get("adhan", {})) < 3:
                    prayer_url = await _discover_prayer_page(page, url)
                    if prayer_url:
                        try:
                            await page.goto(prayer_url, wait_until="networkidle", timeout=15000)
                            await page.wait_for_timeout(3000)
                            sub_text = await page.inner_text("body")
                            # Check iframes on subpage too
                            sub_iframes = await page.query_selector_all("iframe")
                            for iframe in sub_iframes[:3]:
                                try:
                                    frame = await iframe.content_frame()
                                    if frame:
                                        sub_text += "\n" + await frame.inner_text("body")
                                except Exception:
                                    pass
                            sub_check = extract_times_from_text(sub_text)
                            if len(sub_check.get("adhan", {})) >= 3:
                                text_content = sub_text
                                log.info(f"  → Found data at {prayer_url}")
                        except Exception:
                            pass

                await page.close()

                # Extract prayer times
                data = extract_times_from_text(text_content)

                if validate_schedule(data):
                    stats["success"] += 1
                    log.info(f"  ✓ Found: {len(data['adhan'])} adhan, {len(data['iqama'])} iqama, {len(data['jumuah'])} jumuah")

                    if save:
                        _save_to_db(engine, mosque_id, data, today)
                else:
                    stats["no_data"] += 1
                    adhan_count = len(data.get("adhan", {}))
                    if adhan_count > 0:
                        log.info(f"  ~ Partial: {adhan_count} times found but didn't validate")
                    else:
                        log.info(f"  ✗ No prayer times found")

            except Exception as e:
                stats["error"] += 1
                log.info(f"  ✗ Error: {type(e).__name__}: {str(e)[:80]}")
                try:
                    await page.close()
                except Exception:
                    pass

            # Rate limit
            if i % 10 == 9:
                log.info(f"  --- Stats so far: {stats['success']}/{stats['attempted']} success ({stats['success']*100//max(stats['attempted'],1)}%)")

        await browser.close()

    return stats


def _save_to_db(engine, mosque_id: str, data: dict, today: date):
    """Save extracted prayer schedule to DB."""
    adhan = data["adhan"]
    iqama = data["iqama"]

    with engine.begin() as conn:
        # Build the prayer schedule row
        values = {
            "mosque_id": mosque_id,
            "date": today,
        }

        # Map prayer names to DB column prefixes
        # sunrise has no adhan/iqama suffix — just "sunrise" and "sunrise_source"
        adhan_col_map = {
            "fajr": "fajr_adhan", "dhuhr": "dhuhr_adhan",
            "asr": "asr_adhan", "maghrib": "maghrib_adhan", "isha": "isha_adhan",
            "sunrise": "sunrise",
        }
        iqama_col_map = {
            "fajr": "fajr_iqama", "dhuhr": "dhuhr_iqama",
            "asr": "asr_iqama", "maghrib": "maghrib_iqama", "isha": "isha_iqama",
        }
        source_col_map = {
            "fajr": "fajr_adhan_source", "dhuhr": "dhuhr_adhan_source",
            "asr": "asr_adhan_source", "maghrib": "maghrib_adhan_source",
            "isha": "isha_adhan_source", "sunrise": "sunrise_source",
        }

        for prayer, t in adhan.items():
            col = adhan_col_map.get(prayer)
            src_col = source_col_map.get(prayer)
            if col and t:
                values[col] = t
                if src_col:
                    values[src_col] = "playwright_scrape"

        for prayer, t in iqama.items():
            col = iqama_col_map.get(prayer)
            if col and t:
                values[col] = t
                values[col + "_source"] = "playwright_scrape"

        if len(values) <= 2:  # only mosque_id and date
            return

        # Upsert — include id for new rows
        values["id"] = str(__import__("uuid").uuid4())
        cols = ", ".join(values.keys())
        placeholders = ", ".join(f":{k}" for k in values.keys())
        updates = ", ".join(
            f"{k} = EXCLUDED.{k}" for k in values.keys()
            if k not in ("mosque_id", "date", "id")
        )

        conn.execute(text(f"""
            INSERT INTO prayer_schedules ({cols})
            VALUES ({placeholders})
            ON CONFLICT (mosque_id, date) DO UPDATE SET {updates}
        """), values)

        # Update scraping job
        conn.execute(text("""
            UPDATE scraping_jobs
            SET status = 'success', scraped_at = now(), scrape_method = 'playwright_scrape'
            WHERE mosque_id = :mid
        """), {"mid": mosque_id})

        # Save jumuah if found
        for i, jtime in enumerate(data.get("jumuah", [])[:3]):
            conn.execute(text("""
                INSERT INTO jumuah_sessions (id, mosque_id, prayer_start, session_number, source)
                VALUES (gen_random_uuid(), CAST(:mid AS uuid), :time, :num, 'playwright_scrape')
                ON CONFLICT DO NOTHING
            """), {"mid": mosque_id, "time": jtime, "num": i + 1})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Smart bulk scraper with Playwright")
    parser.add_argument("--check-alive", action="store_true", help="Phase 1: check which websites are alive")
    parser.add_argument("--scrape", action="store_true", help="Phase 2+3: render and extract")
    parser.add_argument("--analyze", action="store_true", help="Show current stats")
    parser.add_argument("--limit", type=int, default=20, help="Max sites to scrape (default 20)")
    parser.add_argument("--all", action="store_true", help="Scrape all alive sites without real data")
    parser.add_argument("--no-save", action="store_true", help="Don't save to DB (dry run)")
    args = parser.parse_args()

    engine = create_engine(DB_URL)

    if args.analyze:
        with engine.connect() as conn:
            r = conn.execute(text("""
                SELECT
                    count(*) filter (where website is not null) as has_website,
                    count(*) filter (where id in (select mosque_id from scraping_jobs where website_alive = true)) as alive,
                    count(*) filter (where id in (select mosque_id from scraping_jobs where website_alive = false)) as dead,
                    count(*) filter (where id in (
                        select mosque_id from prayer_schedules where date = CURRENT_DATE and fajr_adhan_source != 'calculated'
                    )) as has_real_data
                FROM mosques WHERE is_active
            """)).mappings().first()
            log.info(f"Websites: {r['has_website']} | Alive: {r['alive']} | Dead: {r['dead']} | Real data: {r['has_real_data']}")
        return

    if args.check_alive:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT m.id::text, m.website
                FROM mosques m
                WHERE m.is_active AND m.website IS NOT NULL
                  AND m.website NOT LIKE '%%facebook%%'
                  AND m.website NOT LIKE '%%instagram%%'
                  AND m.website NOT LIKE '%%youtube%%'
                  AND m.website NOT LIKE '%%google.com/maps%%'
                  AND m.website NOT LIKE '%%yelp%%'
                  AND m.id NOT IN (
                      SELECT mosque_id FROM scraping_jobs
                      WHERE website_checked_at > now() - interval '30 days'
                  )
            """)).fetchall()
            websites = [{"id": r[0], "website": r[1]} for r in rows]

        log.info(f"Found {len(websites)} websites to check")
        results = asyncio.run(check_alive(websites, engine))
        log.info(f"\nALIVE CHECK COMPLETE: {results}")
        return

    if args.scrape:
        limit = None if args.all else args.limit

        with engine.connect() as conn:
            # Get alive websites that don't have real data today
            q = """
                SELECT m.id::text, m.name, m.website
                FROM mosques m
                JOIN scraping_jobs sj ON sj.mosque_id = m.id AND sj.website_alive = true
                WHERE m.is_active AND m.website IS NOT NULL
                  AND m.website NOT LIKE '%%facebook%%'
                  AND m.website NOT LIKE '%%instagram%%'
                  AND m.id NOT IN (
                      SELECT mosque_id FROM prayer_schedules
                      WHERE date = CURRENT_DATE AND fajr_adhan_source NOT IN ('calculated')
                  )
                ORDER BY random()
            """
            if limit:
                q += f" LIMIT {limit}"
            rows = conn.execute(text(q)).fetchall()
            websites = [{"id": r[0], "name": r[1], "website": r[2]} for r in rows]

        log.info(f"Scraping {len(websites)} websites with Playwright")
        stats = asyncio.run(scrape_with_playwright(websites, engine, save=not args.no_save))
        log.info(f"\nSCRAPE COMPLETE: {stats}")
        rate = stats['success'] * 100 // max(stats['attempted'], 1)
        log.info(f"Success rate: {rate}%")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
