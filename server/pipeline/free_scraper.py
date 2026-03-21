"""
Free Mosque Scraper — Zero API Cost
=====================================
Extracts prayer times without any paid API calls.

Step 0: Mawaqit API (free, best quality)
Step 1: Iframe widget extraction (Masjidal/AthanPlus/MasjidNow — free)
Step 2: HTML table/pattern extraction (BeautifulSoup regex — free)
Step 3: Playwright render + HTML extraction (free, for JS-heavy sites)
Step 4: [OPTIONAL] Claude AI extraction (paid, only for hard cases)

Usage:
    python -m pipeline.free_scraper --batch 100
    python -m pipeline.free_scraper --all
    python -m pipeline.free_scraper --test 10  # dry run
"""

import asyncio
import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Prayer time patterns for regex extraction
# ---------------------------------------------------------------------------

PRAYER_NAMES = {
    "fajr": r"fajr|fajir|fajar|subh|dawn",
    "sunrise": r"sunrise|shurooq|shorooq|ishraq",
    "dhuhr": r"dhuhr|zuhr|zohr|duhr|thuhr|noon",
    "asr": r"asr|asar|afternoon",
    "maghrib": r"maghrib|magrib|maghreb|sunset",
    "isha": r"isha|esha|ishaa|night",
}

TIME_PATTERN = re.compile(
    r'(\d{1,2})\s*[:\.]\s*(\d{2})\s*(am|pm|AM|PM)?'
)

IQAMA_LABELS = re.compile(
    r'iqama|iqamah|jamaat|jamaah|congregation|start\s*time|prayer\s*start',
    re.IGNORECASE
)

ADHAN_LABELS = re.compile(
    r'adhan|athan|azan|azaan|begin|start|time',
    re.IGNORECASE
)

JUMUAH_PATTERN = re.compile(
    r'jumu.?ah|jummah|juma|friday\s+prayer|friday\s+salah|friday\s+congregat',
    re.IGNORECASE
)

KHUTBAH_PATTERN = re.compile(
    r'khutba|khutbah|sermon|talk',
    re.IGNORECASE
)

# Special prayer patterns
EID_PATTERN = re.compile(
    r'eid\s*(ul|al)?\s*-?\s*(fitr|adha|al-fitr|al-adha)|eid\s+prayer|eid\s+salah',
    re.IGNORECASE
)

TARAWEEH_PATTERN = re.compile(
    r'taraweeh|tarawih|taravih|taraveeh|qiyam\s*(ul|al)?\s*-?\s*layl',
    re.IGNORECASE
)

TAHAJJUD_PATTERN = re.compile(
    r'tahajjud|tahajud|night\s+prayer|qiyam',
    re.IGNORECASE
)

PHONE_PATTERN = re.compile(
    r'(?:\+?1[-.\s]?)?\(?(\d{3})\)?[-.\s]?(\d{3})[-.\s]?(\d{4})'
)

TAKBEER_PATTERN = re.compile(
    r'takbeer|takbir|takbirat|starts?\s+at',
    re.IGNORECASE
)


def parse_time_12h(h, m, ampm=None):
    """Convert 12h time to HH:MM 24h format."""
    h, m = int(h), int(m)
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    return None


def extract_times_from_text(text: str) -> list[tuple[str, str]]:
    """Extract all (context, time) pairs from text."""
    results = []
    for match in TIME_PATTERN.finditer(text):
        h, m, ampm = match.group(1), match.group(2), match.group(3)
        t = parse_time_12h(h, m, ampm)
        if t:
            # Get surrounding context (50 chars before)
            start = max(0, match.start() - 50)
            context = text[start:match.end()].lower()
            results.append((context, t))
    return results


# ---------------------------------------------------------------------------
# Step 0: Mawaqit API
# ---------------------------------------------------------------------------

async def step0_mawaqit(name: str, lat: float, lng: float) -> Optional[dict]:
    """Search Mawaqit for this mosque. Free API."""
    if not lat or not lng:
        return None
    try:
        search_name = name.split("(")[0].strip()[:40]
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://mawaqit.net/api/2.0/mosque/search",
                params={"word": search_name},
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                return None
            mosques = resp.json()
            if not mosques:
                return None

            from math import radians, sin, cos, sqrt, atan2
            def haversine(lat1, lng1, lat2, lng2):
                R = 6371
                dlat, dlng = radians(lat2-lat1), radians(lng2-lng1)
                a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlng/2)**2
                return R * 2 * atan2(sqrt(a), sqrt(1-a))

            best = min(mosques, key=lambda m: haversine(lat, lng, m.get("latitude",0), m.get("longitude",0)))
            if haversine(lat, lng, best.get("latitude",0), best.get("longitude",0)) > 50:
                return None

            times = best.get("times", [])
            iqamas = best.get("iqama", [])
            if len(times) < 6:
                return None

            def fmt(t):
                return str(t).strip()[:5] if t and ":" in str(t) else None
            def fmt_iq(t):
                t = str(t).strip() if t else None
                if not t: return None
                if t.startswith("+"): return t
                return t[:5] if ":" in t else None

            pt = {
                "fajr": {"adhan": fmt(times[0]), "iqama": fmt_iq(iqamas[0]) if len(iqamas)>0 else None},
                "dhuhr": {"adhan": fmt(times[2]), "iqama": fmt_iq(iqamas[1]) if len(iqamas)>1 else None},
                "asr": {"adhan": fmt(times[3]), "iqama": fmt_iq(iqamas[2]) if len(iqamas)>2 else None},
                "maghrib": {"adhan": fmt(times[4]), "iqama": fmt_iq(iqamas[3]) if len(iqamas)>3 else None},
                "isha": {"adhan": fmt(times[5]), "iqama": fmt_iq(iqamas[4]) if len(iqamas)>4 else None},
            }
            jumuah = []
            for jk in ["jumua","jumua2","jumua3"]:
                jt = best.get(jk)
                if jt: jumuah.append({"khutbah_time": None, "prayer_time": fmt(jt), "language": None})

            count = sum(1 for v in pt.values() if v.get("adhan") or v.get("iqama"))
            return {
                "prayer_times": pt, "sunrise": fmt(times[1]),
                "jumuah": jumuah, "prayers_found": count,
                "enrichment": {
                    "has_womens_section": best.get("womenSpace"),
                    "wheelchair_accessible": best.get("handicapAccessibility"),
                    "phone": best.get("phone"), "email": best.get("email"),
                    "address": best.get("localisation"),
                },
                "source": "mawaqit", "source_detail": best.get("slug"),
            }
    except Exception as e:
        logger.debug(f"  Mawaqit failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 1: Iframe widget extraction
# ---------------------------------------------------------------------------

async def step1_iframe_widgets(website: str, name: str) -> Optional[dict]:
    """Find prayer widget iframes and extract data without AI."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.goto(website, wait_until="domcontentloaded", timeout=12000)
            await page.wait_for_timeout(3000)

            iframes = await page.evaluate("""() =>
                Array.from(document.querySelectorAll('iframe'))
                    .map(f => f.src).filter(s => s && s.length > 10)
            """)
            await browser.close()

            prayer_kw = ['prayer','salah','iqama','masjid','athan','adhan','timing','athanplus','masjidal','mawaqit']
            prayer_iframes = [u for u in iframes if any(k in u.lower() for k in prayer_kw)]

            for iframe_url in prayer_iframes[:2]:
                logger.info(f"  🔲 Iframe: {iframe_url[:80]}")
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.get(iframe_url, headers={"User-Agent": "Mozilla/5.0"})
                        if resp.status_code != 200:
                            continue
                    result = _parse_prayer_html(resp.text, name)
                    if result and result["prayers_found"] >= 2:
                        result["source"] = "iframe_widget"
                        result["source_detail"] = iframe_url[:200]
                        return result
                except Exception:
                    continue
            return None
    except Exception as e:
        logger.debug(f"  Iframe scan failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 2: HTML pattern extraction (no AI)
# ---------------------------------------------------------------------------

async def step2_html_extract(website: str, name: str) -> Optional[dict]:
    """Fetch HTML and extract prayer times using patterns/regex."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(website, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            if resp.status_code >= 400:
                return None
            result = _parse_prayer_html(resp.text, name)
            if result and result["prayers_found"] >= 2:
                result["source"] = "html_parse"
                return result

            # Try common subpages
            base = website.rstrip("/")
            for subpage in ["/prayer-times", "/prayers"]:
                try:
                    resp2 = await client.get(f"{base}{subpage}", headers={
                        "User-Agent": "Mozilla/5.0"
                    })
                    if resp2.status_code < 400:
                        result2 = _parse_prayer_html(resp2.text, name)
                        if result2 and result2["prayers_found"] >= 2:
                            result2["source"] = "html_parse"
                            result2["source_detail"] = subpage
                            return result2
                except Exception:
                    continue
            return None
    except Exception as e:
        logger.debug(f"  HTML extract failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 3: Playwright render + pattern extraction
# ---------------------------------------------------------------------------

async def step3_playwright_extract(website: str, name: str) -> Optional[dict]:
    """Render with Playwright, then extract with patterns (no AI)."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.goto(website, wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(3000)

            # Get rendered HTML
            html = await page.content()
            text = await page.evaluate("() => document.body.innerText")
            await browser.close()

            # Try HTML parsing first
            result = _parse_prayer_html(html, name)
            if result and result["prayers_found"] >= 2:
                result["source"] = "playwright_parse"
                return result

            # Try text-based extraction
            result2 = _extract_from_rendered_text(text, name)
            if result2 and result2["prayers_found"] >= 2:
                result2["source"] = "playwright_text"
                return result2

            return None
    except Exception as e:
        logger.debug(f"  Playwright extract failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Core HTML parser (shared by steps 1, 2, 3)
# ---------------------------------------------------------------------------

def _parse_prayer_html(html: str, name: str) -> Optional[dict]:
    """Extract prayer times from HTML using BeautifulSoup + regex. No AI."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n", strip=True)

    prayer_times = {}
    jumuah = []

    # Strategy 1: Find tables with prayer times
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) >= 2:
                cell_text = " ".join(cells).lower()
                for prayer, pattern in PRAYER_NAMES.items():
                    if prayer == "sunrise":
                        continue
                    if re.search(pattern, cell_text):
                        times = []
                        for cell in cells[1:]:
                            match = TIME_PATTERN.search(cell)
                            if match:
                                t = parse_time_12h(match.group(1), match.group(2), match.group(3))
                                if t:
                                    times.append(t)
                            elif "sunset" in cell.lower():
                                times.append("sunset")
                            elif re.match(r'^\+?\d{1,2}\s*(min)?', cell.strip()):
                                m = re.match(r'^\+?(\d{1,2})', cell.strip())
                                if m:
                                    times.append(f"+{m.group(1)}")

                        if times:
                            adhan = times[0] if len(times) >= 1 else None
                            iqama = times[1] if len(times) >= 2 else None
                            if prayer not in prayer_times or len(times) > 1:
                                prayer_times[prayer] = {"adhan": adhan, "iqama": iqama}

    # Strategy 2: Find prayer times in text patterns
    if len(prayer_times) < 3:
        lines = text.split("\n")
        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            for prayer, pattern in PRAYER_NAMES.items():
                if prayer == "sunrise":
                    continue
                if re.search(pattern, line_lower):
                    # Look for times in this line and next 2 lines
                    search_text = " ".join(lines[i:i+3])
                    times_found = []
                    for match in TIME_PATTERN.finditer(search_text):
                        t = parse_time_12h(match.group(1), match.group(2), match.group(3))
                        if t:
                            times_found.append(t)
                    if "sunset" in search_text.lower():
                        times_found.append("sunset")

                    if times_found and prayer not in prayer_times:
                        adhan = times_found[0]
                        iqama = times_found[1] if len(times_found) >= 2 else None
                        prayer_times[prayer] = {"adhan": adhan, "iqama": iqama}

    # Strategy 3: Find jumuah times
    for line in text.split("\n"):
        if JUMUAH_PATTERN.search(line):
            times_in_line = []
            for match in TIME_PATTERN.finditer(line):
                t = parse_time_12h(match.group(1), match.group(2), match.group(3))
                if t:
                    times_in_line.append(t)
            if times_in_line:
                is_khutbah = bool(KHUTBAH_PATTERN.search(line))
                jumuah.append({
                    "khutbah_time": times_in_line[0] if is_khutbah else None,
                    "prayer_time": times_in_line[0] if not is_khutbah else (times_in_line[1] if len(times_in_line) > 1 else None),
                    "language": None,
                })

    # Find sunrise
    sunrise = None
    for line in text.split("\n"):
        if re.search(PRAYER_NAMES["sunrise"], line.lower()):
            match = TIME_PATTERN.search(line)
            if match:
                sunrise = parse_time_12h(match.group(1), match.group(2), match.group(3))

    # Strategy 4: Find special prayers (Eid, Taraweeh, Tahajjud)
    special_prayers = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        context = " ".join(lines[max(0,i-1):min(len(lines),i+3)])

        # Eid prayers
        if EID_PATTERN.search(line):
            times_found = []
            for match in TIME_PATTERN.finditer(context):
                t = parse_time_12h(match.group(1), match.group(2), match.group(3))
                if t: times_found.append(t)

            prayer_type = "eid_fitr" if "fitr" in line.lower() else ("eid_adha" if "adha" in line.lower() else "eid")
            has_takbeer = bool(TAKBEER_PATTERN.search(context))

            if times_found:
                special_prayers.append({
                    "prayer_type": prayer_type,
                    "prayer_time": times_found[-1],  # prayer is usually the last time mentioned
                    "takbeer_time": times_found[0] if has_takbeer and len(times_found) > 1 else None,
                    "special_notes": line.strip()[:200],
                })

        # Taraweeh
        if TARAWEEH_PATTERN.search(line) and not any(sp["prayer_type"] == "taraweeh" for sp in special_prayers):
            times_found = []
            for match in TIME_PATTERN.finditer(context):
                t = parse_time_12h(match.group(1), match.group(2), match.group(3))
                if t: times_found.append(t)
            if times_found:
                special_prayers.append({
                    "prayer_type": "taraweeh",
                    "prayer_time": times_found[0],
                    "special_notes": line.strip()[:200],
                })

        # Tahajjud
        if TAHAJJUD_PATTERN.search(line) and not TARAWEEH_PATTERN.search(line):
            if not any(sp["prayer_type"] == "tahajjud" for sp in special_prayers):
                times_found = []
                for match in TIME_PATTERN.finditer(context):
                    t = parse_time_12h(match.group(1), match.group(2), match.group(3))
                    if t: times_found.append(t)
                if times_found:
                    special_prayers.append({
                        "prayer_type": "tahajjud",
                        "prayer_time": times_found[0],
                        "special_notes": line.strip()[:200],
                    })

    # Strategy 5: Find phone numbers
    phone = None
    for match in PHONE_PATTERN.finditer(text):
        phone = f"({match.group(1)}) {match.group(2)}-{match.group(3)}"
        break  # take first phone number found

    count = sum(1 for v in prayer_times.values() if v.get("adhan") or v.get("iqama"))
    if count == 0 and not special_prayers and not jumuah:
        return None

    return {
        "prayer_times": prayer_times,
        "sunrise": sunrise,
        "jumuah": jumuah,
        "special_prayers": special_prayers,
        "phone": phone,
        "prayers_found": count,
    }


def _extract_from_rendered_text(text: str, name: str) -> Optional[dict]:
    """Extract from plain rendered text (Playwright innerText)."""
    # Reuse the HTML parser but wrap text in minimal HTML
    html = f"<html><body><pre>{text}</pre></body></html>"
    return _parse_prayer_html(html, name)


# ---------------------------------------------------------------------------
# Main scrape function
# ---------------------------------------------------------------------------

async def scrape_mosque(mosque_id: str, name: str, website: str,
                        lat: float = 0, lng: float = 0,
                        dry_run: bool = False) -> dict:
    """Run the free pipeline."""
    start = time.time()

    try:
        # Pre-check
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as c:
                r = await c.head(website, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code in (404, 410, 502, 503, 520, 521, 522, 523, 524):
                    return {"mosque_id": mosque_id, "name": name, "success": False,
                            "error": f"http_{r.status_code}", "elapsed": time.time()-start}
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return {"mosque_id": mosque_id, "name": name, "success": False,
                    "error": "unreachable", "elapsed": time.time()-start}
        except Exception:
            pass

        # Step 0: Mawaqit
        r0 = await step0_mawaqit(name, lat, lng)
        if r0 and r0["prayers_found"] >= 3:
            logger.info(f"  ✅ Mawaqit: {r0['prayers_found']}/5")
            return _ok(mosque_id, name, website, r0, 0, start)

        # Step 1: Iframe widgets
        r1 = await step1_iframe_widgets(website, name)
        if r1 and r1["prayers_found"] >= 2:
            logger.info(f"  ✅ Iframe: {r1['prayers_found']}/5")
            return _ok(mosque_id, name, website, r1, 1, start)

        # Step 2: HTML pattern extraction
        r2 = await step2_html_extract(website, name)
        if r2 and r2["prayers_found"] >= 2:
            logger.info(f"  ✅ HTML: {r2['prayers_found']}/5")
            return _ok(mosque_id, name, website, r2, 2, start)

        # Step 3: Playwright render + patterns
        if time.time() - start < 40:
            r3 = await step3_playwright_extract(website, name)
            if r3 and r3["prayers_found"] >= 2:
                logger.info(f"  ✅ Playwright: {r3['prayers_found']}/5")
                return _ok(mosque_id, name, website, r3, 3, start)

        logger.info(f"  ❌ No data ({time.time()-start:.0f}s)")
        return {"mosque_id": mosque_id, "name": name, "success": False,
                "error": "no_data", "elapsed": time.time()-start}

    except Exception as e:
        logger.error(f"  💥 {type(e).__name__}: {e}")
        return {"mosque_id": mosque_id, "name": name, "success": False,
                "error": f"crash_{type(e).__name__}", "elapsed": time.time()-start}


def _ok(mosque_id, name, website, result, step, start):
    return {
        "mosque_id": mosque_id, "name": name, "website": website,
        "success": True,
        "prayers_found": result["prayers_found"],
        "prayer_times": result["prayer_times"],
        "sunrise": result.get("sunrise"),
        "jumuah": result.get("jumuah", []),
        "enrichment": result.get("enrichment", {}),
        "source": result.get("source", f"step{step}"),
        "source_detail": result.get("source_detail"),
        "step": step,
        "elapsed": time.time() - start,
    }


# ---------------------------------------------------------------------------
# DB saving (reuse from smart_scraper)
# ---------------------------------------------------------------------------

def get_db():
    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    sync_url = db_url.replace("+asyncpg", "+psycopg2")
    if "psycopg2" not in sync_url:
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(sync_url)


# Import save logic from smart_scraper
from pipeline.smart_scraper import save_result


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run(args):
    engine = get_db()
    today = date.today()

    with engine.connect() as conn:
        if args.mosque_id:
            rows = conn.execute(text(
                "SELECT id::text, name, website, lat, lng FROM mosques WHERE id = :id"
            ), {"id": args.mosque_id}).fetchall()
        else:
            limit = args.test or args.batch or 1000
            rows = conn.execute(text("""
                SELECT id::text, name, website, lat, lng FROM mosques
                WHERE is_active = true AND website IS NOT NULL
                  AND website LIKE 'https%%' AND website NOT LIKE '%%facebook%%'
                  AND LENGTH(website) > 10
                ORDER BY random()
                LIMIT :limit
            """), {"limit": limit}).fetchall()

    logger.info(f"Processing {len(rows)} mosques (FREE mode — no AI costs)")

    dry_run = args.test is not None
    ok_p = ok_j = 0
    methods = {}

    for i, row in enumerate(rows):
        mid, name, website = row[0], row[1], row[2]
        lat = float(row[3]) if row[3] else 0
        lng = float(row[4]) if row[4] else 0

        logger.info(f"\n🕌 {name} ({i+1}/{len(rows)})")

        r = await scrape_mosque(mid, name, website, lat=lat, lng=lng, dry_run=dry_run)

        if r.get("success"):
            ok_p += 1
            src = r.get("source", "unknown")
            methods[src] = methods.get(src, 0) + 1
            if r.get("jumuah"):
                ok_j += 1

            if not dry_run:
                try:
                    save_result(engine, r, today)
                except Exception as e:
                    logger.error(f"  DB save failed: {e}")

        await asyncio.sleep(0.3)

    n = len(rows)
    print(f"\n{'='*60}")
    print(f"FREE SCRAPER: {ok_p}/{n} ({ok_p*100//max(n,1)}%) prayers, {ok_j}/{n} jumuah")
    print(f"Methods: {methods}")
    print(f"Cost: $0.00")


def main():
    parser = argparse.ArgumentParser(description="Free mosque scraper (zero AI cost)")
    parser.add_argument("--test", type=int, metavar="N", help="Test N mosques (dry run)")
    parser.add_argument("--batch", type=int, metavar="N", help="Process N mosques (saves to DB)")
    parser.add_argument("--mosque-id", type=str, help="Scrape specific mosque")
    parser.add_argument("--all", action="store_true", help="Process all")
    args = parser.parse_args()

    if not any([args.test, args.batch, args.mosque_id, args.all]):
        parser.print_help()
        sys.exit(1)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
