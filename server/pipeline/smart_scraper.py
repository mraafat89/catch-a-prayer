"""
Smart Mosque Scraper
====================
3-step prayer time extraction pipeline optimized for accuracy.

Step 1 — Jina + Claude Haiku: quick scan (homepage + find prayer page URL)
Step 2 — Playwright + Claude Haiku: full JS render of prayer page
Step 3 — Playwright + Claude Sonnet: retry with smarter model
Fallback — Calculated prayer times (praytimes library)

Usage:
    python -m pipeline.smart_scraper --test 10
    python -m pipeline.smart_scraper --batch 50
    python -m pipeline.smart_scraper --mosque-id <uuid>
    python -m pipeline.smart_scraper --all
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
from urllib.parse import urljoin, urlparse

import httpx
import anthropic
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JINA_BASE = "https://r.jina.ai/"
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-20250514"

claude_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# Track total token usage across the run
total_input_tokens = 0
total_output_tokens = 0

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

STEP1_PROMPT = """You are extracting mosque prayer information from a website.

PRIORITY: Find prayer times (adhan + iqama) and Jumuah (Friday prayer) info.

Return ONLY valid JSON:
{
  "prayer_times": {
    "fajr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "dhuhr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "asr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "maghrib": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "isha": {"adhan": "HH:MM", "iqama": "HH:MM"}
  },
  "sunrise": "HH:MM or null",
  "jumuah": [
    {
      "khutbah_time": "HH:MM",
      "prayer_time": "HH:MM",
      "language": "English/Arabic/Urdu/etc",
      "imam": "name or null"
    }
  ],
  "prayer_times_url": "URL to dedicated prayer times page if found in nav/links, null if times are on this page",
  "enrichment": {
    "address": "full street address or null",
    "phone": "phone or null",
    "email": "email or null",
    "has_womens_section": true/false/null,
    "wheelchair_accessible": true/false/null,
    "denomination": "sunni/shia/null",
    "languages_spoken": [],
    "facilities": []
  }
}

CRITICAL RULES:
- 24-hour time format ONLY: 1:30 PM → 13:30, 6:15 AM → 06:15, 12:00 PM → 12:00
- null for anything you cannot find — NEVER guess or fabricate
- Iqama must be AFTER adhan (if iqama is before adhan, you mixed them up)

PRAYER NAME VARIATIONS (all mean the same thing):
- Fajr / Fajir / Fajar / Subh / Dawn
- Dhuhr / Zuhr / Zohr / Duhr / Thuhr / Noon
- Asr / Asar / Afternoon
- Maghrib / Magrib / Maghreb / Sunset — if it says "sunset" or "at sunset", use "sunset" as the adhan value
- Isha / Esha / Ishaa / Night

TIME COLUMN VARIATIONS (all mean the same):
- Adhan / Athan / Azan / Azaan / Start / Begins / Time
- Iqama / Iqamah / Jamaat / Jamaah / Congregation / Start Time / Prayer Start

SUNRISE/SHUROOQ:
- Sunrise / Shurooq / Shorooq / Ishraq — extract the time

MAGHRIB SPECIAL CASE:
- If Maghrib shows "sunset", "at sunset", or "SUNSET" → set adhan to "sunset"
- If Maghrib iqama shows "+5 min" or "5 min after sunset" → set iqama to "+5"

JUMUAH/FRIDAY VARIATIONS:
- Jumuah / Jummah / Juma / Friday Prayer / Friday Salah / Friday Congregational
- Khutbah / Khutba / Sermon / Talk
- 1st Jumuah / 2nd Jumuah / Session 1 / Session 2

- Look for prayer time widgets, tables, schedules, sidebars
- Look in navigation/menu for links to "Prayer Times", "Salah", "Iqama", "Schedule"
- Include ALL Jumuah sessions — many mosques have 2-3 Friday prayers
- For Jumuah: khutbah_time = when sermon/khutba starts, prayer_time = when salah starts"""

STEP2_PROMPT = """Extract prayer times and Jumuah info from this mosque page.

Return ONLY valid JSON:
{
  "prayer_times": {
    "fajr": {"adhan": "HH:MM or null", "iqama": "HH:MM or offset like '+20'"},
    "dhuhr": {"adhan": "HH:MM or null", "iqama": "HH:MM or offset like '+15'"},
    "asr": {"adhan": "HH:MM or null", "iqama": "HH:MM or offset like '+10'"},
    "maghrib": {"adhan": "HH:MM or 'sunset'", "iqama": "HH:MM or offset like '+5'"},
    "isha": {"adhan": "HH:MM or null", "iqama": "HH:MM or offset like '+15'"}
  },
  "sunrise": "HH:MM or null",
  "jumuah": [
    {
      "khutbah_time": "HH:MM",
      "prayer_time": "HH:MM",
      "language": "string",
      "imam": "name or null"
    }
  ]
}

RULES:
- 24h format: 1:30 PM → 13:30
- null for unknown — NEVER guess
- Iqama is AFTER adhan — if they look swapped, swap them
- If iqama is shown as offset: "+20 min", "20 min after athan", "SUNSET" → use "+20" or "sunset"
- Maghrib adhan is often "sunset" — that's valid, use "sunset"
- Prayer names: Fajr/Fajir/Subh, Dhuhr/Zuhr/Thuhr/Noon, Asr/Asar, Maghrib/Magrib/Sunset, Isha/Esha
- Column names: Adhan/Athan/Azan/Start/Begins, Iqama/Iqamah/Jamaat/Congregation/Start Time
- Jumuah/Jummah/Juma/Friday: khutbah=Khutba/Sermon/Talk, prayer=Salah/Prayer
- Include ALL Friday sessions (1st, 2nd, 3rd)"""

STEP3_PROMPT = """You are an expert at finding prayer times on mosque websites. This page LIKELY
contains prayer schedule data that a previous extraction attempt missed.

Look VERY carefully for:
1. Prayer times in ANY format: tables, lists, sidebars, footers, widgets, images of schedules
2. Times labeled: Athan/Adhan/Azan, Iqama/Iqamah/Jamaat/Congregation/Start
3. Prayer name variations: Fajr/Fajir/Fajar, Zuhr/Dhuhr/Zohr, Asr/Asar, Maghrib/Magrib, Isha/Esha
4. Times in AM/PM that need converting to 24h
5. Jumuah/Jummah/Friday/Juma prayer with khutbah/khutba and prayer/salah times
6. RELATIVE iqama offsets like "20 min after athan" or "iqama: +15 min" — if you see these,
   you cannot compute the absolute time, so set iqama to null but note it in the response

Also check for:
- MasjidNow or IslamicFinder widget data embedded in the page
- JSON-LD or structured data
- Inline JavaScript variables with schedule data
- iframes pointing to prayer time services
- Scattered mentions like "Isha starts at 9:20 PM" or "Taraweeh after Isha at 9:30"
- Monthly schedule PDFs or images linked on the page

Return ONLY valid JSON:
{
  "prayer_times": {
    "fajr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "dhuhr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "asr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "maghrib": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "isha": {"adhan": "HH:MM", "iqama": "HH:MM"}
  },
  "sunrise": "HH:MM or null",
  "jumuah": [{"khutbah_time": "HH:MM", "prayer_time": "HH:MM", "language": "", "imam": ""}],
  "schedule_image_url": "URL to prayer schedule image/PDF if found, null otherwise"
}

24h format. null for unknown. NEVER guess. Even partial data (2-3 prayers) is valuable."""

# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

async def jina_fetch(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch URL through Jina Reader (renders some JS, returns markdown)."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(
                f"{JINA_BASE}{url}",
                headers={"Accept": "text/markdown", "User-Agent": "CatchAPrayer/1.0"},
            )
            if r.status_code == 200 and len(r.text.strip()) > 50:
                return r.text[:15000]
    except Exception as e:
        logger.debug(f"  Jina failed for {url}: {e}")
    return None


async def playwright_fetch(url: str, timeout: int = 20000) -> Optional[str]:
    """Render URL with Playwright headless browser, return cleaned text + prayer-relevant HTML."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("  Playwright not installed, skipping step 2")
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()

            # Capture any prayer-related API calls
            api_responses = []
            async def on_response(response):
                url_lower = response.url.lower()
                if any(w in url_lower for w in ['prayer', 'salah', 'iqama', 'schedule', 'times']):
                    try:
                        body = await response.text()
                        if len(body) < 5000:
                            api_responses.append(f"API: {response.url}\n{body}")
                    except:
                        pass
            page.on("response", on_response)

            await page.goto(url, wait_until="networkidle", timeout=timeout)
            await page.wait_for_timeout(3000)

            # Get clean text content (most important)
            text_content = await page.evaluate("() => document.body.innerText")

            # Also extract structured data: tables, JSON-LD, data attributes
            structured = await page.evaluate("""() => {
                let result = [];

                // Tables (prayer schedules are often in tables)
                document.querySelectorAll('table').forEach(t => {
                    let rows = Array.from(t.rows).map(r =>
                        Array.from(r.cells).map(c => c.innerText.trim()).join(' | ')
                    );
                    if (rows.some(r => /fajr|dhuhr|zuhr|asr|maghrib|isha|iqama|adhan/i.test(r))) {
                        result.push('TABLE:\\n' + rows.join('\\n'));
                    }
                });

                // JSON-LD
                document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                    try {
                        let d = JSON.parse(s.textContent);
                        result.push('JSON-LD: ' + JSON.stringify(d).substring(0, 1000));
                    } catch(e) {}
                });

                // Iframes (prayer widgets)
                document.querySelectorAll('iframe').forEach(f => {
                    if (f.src && /prayer|salah|iqama|masjid/i.test(f.src)) {
                        result.push('IFRAME: ' + f.src);
                    }
                });

                // Images that might be schedules
                document.querySelectorAll('img').forEach(img => {
                    let info = (img.alt || '') + ' ' + (img.src || '');
                    if (/prayer|schedule|iqama|salah|time/i.test(info) && img.naturalWidth > 200) {
                        result.push('SCHEDULE_IMAGE: ' + img.src);
                    }
                });

                return result;
            }""")

            await browser.close()

            if not text_content or len(text_content.strip()) < 30:
                return None

            # Focus on prayer-relevant text to reduce noise for Claude
            lines = [l.strip() for l in text_content.split("\n") if l.strip()]

            # Extract lines with prayer keywords + their surrounding context
            prayer_kw = ['fajr','dhuhr','zuhr','asr','maghrib','isha','iqama','adhan','athan',
                         'sunrise','jumu','friday','khutba','prayer time','salah','salat','namaz']
            relevant_lines = []
            for i, l in enumerate(lines):
                if any(w in l.lower() for w in prayer_kw):
                    # Include 2 lines before and 2 after for context
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    for j in range(start, end):
                        if lines[j] not in relevant_lines:
                            relevant_lines.append(lines[j])

            if relevant_lines:
                # Send focused prayer content
                focused = "\n".join(relevant_lines)
                parts = [f"=== PRAYER-RELATED CONTENT ===\n{focused[:5000]}"]
            else:
                # No prayer keywords found — send full text (maybe times are unlabeled)
                parts = [f"=== PAGE TEXT ===\n{text_content[:8000]}"]

            if structured:
                parts.append(f"\n=== STRUCTURED DATA ===\n" + "\n".join(structured[:5]))
            if api_responses:
                parts.append(f"\n=== API RESPONSES ===\n" + "\n".join(api_responses[:3]))

            return "\n".join(parts)[:12000]

    except Exception as e:
        logger.debug(f"  Playwright failed for {url}: {e}")
    return None


# ---------------------------------------------------------------------------
# Claude extraction
# ---------------------------------------------------------------------------

def claude_extract(content: str, prompt: str, mosque_name: str,
                   model: str = HAIKU) -> Optional[dict]:
    """Send content to Claude for structured extraction."""
    global total_input_tokens, total_output_tokens

    try:
        r = claude_client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": f"Website content for {mosque_name}:\n\n{content}\n\n{prompt}",
            }],
        )
        raw = r.content[0].text.strip()

        # Clean markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        if raw.startswith("json"):
            raw = raw[4:]

        total_input_tokens += r.usage.input_tokens
        total_output_tokens += r.usage.output_tokens

        return json.loads(raw.strip())
    except json.JSONDecodeError:
        logger.debug(f"  Claude returned invalid JSON")
        return None
    except Exception as e:
        logger.warning(f"  Claude extraction failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_time(t: Optional[str]) -> Optional[str]:
    """Validate and normalize a time value. Accepts HH:MM, 'sunset', '+N' offset."""
    if not t or not isinstance(t, str):
        return None
    t = t.strip().lower()

    # Special values
    if t in ("sunset", "at sunset"):
        return "sunset"

    # Offset values — must have explicit "+" prefix OR "min/minutes after" keyword
    # Examples: "+20", "+5 min", "20 min after athan", "20 minutes after adhan"
    # NOT matching plain numbers like "6" or "13" (those are hours)
    if t.startswith("+"):
        offset_match = re.match(r'^\+(\d{1,2})\s*(min|minutes|mins)?$', t)
        if offset_match:
            mins = int(offset_match.group(1))
            if 1 <= mins <= 60:
                return f"+{mins}"

    # "20 min after athan" / "15 minutes after adhan"
    offset_match2 = re.match(r'(\d{1,2})\s*(min|minutes|mins)\s*(after|from|past)', t)
    if offset_match2:
        mins = int(offset_match2.group(1))
        if 1 <= mins <= 60:
            return f"+{mins}"

    # Standard HH:MM — handle AM/PM conversion
    if ":" in t:
        try:
            is_pm = "pm" in t or "p.m" in t
            is_am = "am" in t or "a.m" in t
            cleaned = re.sub(r'[apm.\s]', '', t)
            parts = cleaned.split(":")
            h, m = int(parts[0]), int(parts[1][:2])

            # Convert 12h to 24h
            if is_pm and h < 12:
                h += 12
            elif is_am and h == 12:
                h = 0

            # Heuristic: if no AM/PM specified and hour < 8, likely PM for
            # Dhuhr(1-2), Asr(3-5), Maghrib(6-8), Isha(7-9)
            # But we can't know prayer context here, so leave as-is

            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
        except (ValueError, IndexError):
            pass

    return None


def count_prayers(pt: dict) -> int:
    """Count how many prayers have at least adhan or iqama (including special values)."""
    if not pt or not isinstance(pt, dict):
        return 0
    count = 0
    for p in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
        d = pt.get(p, {})
        if isinstance(d, dict):
            adhan = d.get("adhan")
            iqama = d.get("iqama")
            # Count if either has any valid value (time, sunset, or offset)
            if adhan or iqama:
                count += 1
    return count


def validate_result(data: dict) -> dict:
    """Clean and validate extracted data."""
    result = {
        "prayer_times": {},
        "sunrise": validate_time(data.get("sunrise")),
        "jumuah": [],
        "prayer_times_url": data.get("prayer_times_url"),
        "enrichment": data.get("enrichment", {}),
    }

    # Validate prayer times
    pt = data.get("prayer_times") or {}
    if not isinstance(pt, dict):
        pt = {}
    for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
        d = pt.get(prayer, {}) if isinstance(pt.get(prayer), dict) else {}
        adhan = validate_time(d.get("adhan"))
        iqama = validate_time(d.get("iqama"))

        # Sanity: iqama should be after adhan — only check for HH:MM times (not sunset/offset)
        if adhan and iqama and ":" in adhan and ":" in iqama:
            ah, am = map(int, adhan.split(":"))
            ih, im = map(int, iqama.split(":"))
            adhan_min = ah * 60 + am
            iqama_min = ih * 60 + im
            if iqama_min < adhan_min and (adhan_min - iqama_min) < 120:
                adhan, iqama = iqama, adhan

        result["prayer_times"][prayer] = {"adhan": adhan, "iqama": iqama}

    result["prayers_found"] = count_prayers(result["prayer_times"])

    # Validate jumuah
    for j in data.get("jumuah", []):
        if not isinstance(j, dict):
            continue
        entry = {
            "khutbah_time": validate_time(j.get("khutbah_time")),
            "prayer_time": validate_time(j.get("prayer_time")),
            "language": j.get("language") if isinstance(j.get("language"), str) else None,
            "imam": j.get("imam") if isinstance(j.get("imam"), str) else None,
        }
        if entry["khutbah_time"] or entry["prayer_time"]:
            result["jumuah"].append(entry)

    return result


async def _extract_from_iframes(website: str, name: str) -> Optional[dict]:
    """Find prayer widget iframes, fetch their content, extract with Claude."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.goto(website, wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(3000)

            # Find iframes with prayer-related URLs
            iframes = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('iframe'))
                    .map(f => f.src)
                    .filter(s => s && s.length > 10);
            }""")
            await browser.close()

            # Check each iframe for prayer keywords
            prayer_keywords = ['prayer', 'salah', 'iqama', 'masjid', 'athan', 'adhan',
                               'timing', 'athanplus', 'masjidal', 'islamicfinder', 'masjidnow']
            prayer_iframes = [u for u in iframes
                              if any(k in u.lower() for k in prayer_keywords)]

            if not prayer_iframes:
                return None

            logger.info(f"   🔲 Found {len(prayer_iframes)} prayer iframe(s)")

            # Fetch each prayer iframe and try to extract
            for iframe_url in prayer_iframes[:2]:
                logger.info(f"   🔲 Fetching iframe: {iframe_url[:80]}")
                try:
                    async with httpx.AsyncClient(timeout=15) as client:
                        resp = await client.get(iframe_url, headers={"User-Agent": "Mozilla/5.0"})
                        if resp.status_code != 200:
                            continue
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    text = soup.get_text(separator="\n", strip=True)
                    if len(text) < 50:
                        continue

                    logger.info(f"   🔲 Iframe content: {len(text)} chars")
                    data = claude_extract(text[:5000], STEP2_PROMPT, name, model=HAIKU)
                    if data:
                        v = validate_result(data)
                        if v["prayers_found"] >= 2:
                            return v
                except Exception as e:
                    logger.debug(f"   Iframe fetch failed: {e}")

            return None
    except Exception as e:
        logger.debug(f"   Iframe extraction failed: {e}")
        return None


async def _find_prayer_links_playwright(website: str) -> list[str]:
    """Use Playwright to scan navigation for prayer-related links."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.goto(website, wait_until="domcontentloaded", timeout=12000)
            await page.wait_for_timeout(1000)

            links = await page.evaluate("""() => {
                let keywords = ['prayer', 'salah', 'iqama', 'schedule', 'namaz', 'salat', 'times'];
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => ({text: a.innerText.trim().toLowerCase(), href: a.href}))
                    .filter(l => l.text.length > 0 && l.text.length < 50
                        && keywords.some(k => l.text.includes(k) || l.href.toLowerCase().includes(k)))
                    .map(l => l.href);
            }""")
            await browser.close()
            # Deduplicate and filter out external links
            seen = set()
            result = []
            base = urlparse(website).netloc
            for link in links:
                parsed = urlparse(link)
                if parsed.netloc == base and link not in seen:
                    seen.add(link)
                    result.append(link)
            return result[:3]
    except Exception as e:
        logger.debug(f"  Nav scan failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Main scrape function
# ---------------------------------------------------------------------------

async def scrape_mosque(mosque_id: str, name: str, website: str,
                        lat: float = 0.0, lng: float = 0.0,
                        dry_run: bool = False) -> dict:
    """Run the 3-step pipeline for a single mosque."""
    logger.info(f"\n{'='*70}")
    logger.info(f"🕌 {name}")
    logger.info(f"   {website}")

    start = time.time()
    try:
        return await _scrape_mosque_impl(mosque_id, name, website, lat, lng, dry_run, start)
    except Exception as e:
        logger.error(f"   💥 Unexpected error: {type(e).__name__}: {e}")
        return _fail(mosque_id, name, website, f"crash_{type(e).__name__}", start)


async def _try_mawaqit(name: str, lat: float, lng: float) -> Optional[dict]:
    """Search Mawaqit API for this mosque. Returns validated result or None."""
    try:
        # Search by name
        search_name = name.split("(")[0].strip()[:40]  # clean up name
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

            # Find the closest match (within 50km)
            from math import radians, sin, cos, sqrt, atan2
            def haversine(lat1, lng1, lat2, lng2):
                R = 6371
                dlat = radians(lat2 - lat1)
                dlng = radians(lng2 - lng1)
                a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
                return R * 2 * atan2(sqrt(a), sqrt(1-a))

            best = None
            best_dist = 50  # max 50km
            for m in mosques:
                dist = haversine(lat, lng, m.get("latitude", 0), m.get("longitude", 0))
                if dist < best_dist:
                    best_dist = dist
                    best = m

            if not best:
                return None

            # Parse Mawaqit response
            times = best.get("times", [])  # [fajr, sunrise, dhuhr, asr, maghrib, isha]
            iqamas = best.get("iqama", [])  # can be HH:MM or "+N"

            if len(times) < 6:
                return None

            def fmt_time(t):
                if not t:
                    return None
                t = str(t).strip()
                if ":" in t and len(t) >= 4:
                    return t[:5]
                return None

            def fmt_iqama(iq):
                if not iq:
                    return None
                iq = str(iq).strip()
                if iq.startswith("+"):
                    return iq
                if ":" in iq:
                    return iq[:5]
                return None

            prayer_times = {
                "fajr": {"adhan": fmt_time(times[0]), "iqama": fmt_iqama(iqamas[0]) if len(iqamas) > 0 else None},
                "dhuhr": {"adhan": fmt_time(times[2]), "iqama": fmt_iqama(iqamas[1]) if len(iqamas) > 1 else None},
                "asr": {"adhan": fmt_time(times[3]), "iqama": fmt_iqama(iqamas[2]) if len(iqamas) > 2 else None},
                "maghrib": {"adhan": fmt_time(times[4]), "iqama": fmt_iqama(iqamas[3]) if len(iqamas) > 3 else None},
                "isha": {"adhan": fmt_time(times[5]), "iqama": fmt_iqama(iqamas[4]) if len(iqamas) > 4 else None},
            }

            jumuah = []
            for jkey in ["jumua", "jumua2", "jumua3"]:
                jt = best.get(jkey)
                if jt:
                    jumuah.append({"khutbah_time": None, "prayer_time": fmt_time(jt), "language": None, "imam": None})

            enrichment = {
                "has_womens_section": best.get("womenSpace"),
                "wheelchair_accessible": best.get("handicapAccessibility"),
                "address": best.get("localisation"),
                "phone": best.get("phone"),
                "email": best.get("email"),
            }

            prayers_found = sum(1 for p in prayer_times.values()
                                if p.get("adhan") or p.get("iqama"))

            logger.info(f"   🌐 Mawaqit: {best['name']} ({best_dist:.1f}km) — "
                         f"{prayers_found}/5 prayers, {len(jumuah)} jumuah")

            return {
                "prayer_times": prayer_times,
                "sunrise": fmt_time(times[1]),
                "jumuah": jumuah,
                "prayers_found": prayers_found,
                "enrichment": enrichment,
                "mawaqit_uuid": best.get("uuid"),
                "mawaqit_slug": best.get("slug"),
            }
    except Exception as e:
        logger.debug(f"   Mawaqit search failed: {e}")
        return None


async def _scrape_mosque_impl(mosque_id: str, name: str, website: str,
                               lat: float, lng: float,
                               dry_run: bool, start: float) -> dict:
    """Internal implementation — wrapped by scrape_mosque for error handling."""
    final_result = None
    final_step = 0
    enrichment = {}

    # ── STEP 0: Mawaqit API (free, instant, most reliable) ────────────────
    if lat and lng:
        mawaqit = await _try_mawaqit(name, lat, lng)
        if mawaqit and mawaqit["prayers_found"] >= 3:
            logger.info(f"   ✅ Mawaqit: {mawaqit['prayers_found']}/5 prayers!")
            return {
                "mosque_id": mosque_id, "name": name, "website": website,
                "success": True,
                "prayers_found": mawaqit["prayers_found"],
                "prayer_times": mawaqit["prayer_times"],
                "sunrise": mawaqit.get("sunrise"),
                "jumuah": mawaqit["jumuah"],
                "enrichment": mawaqit.get("enrichment", {}),
                "source": "mawaqit",
                "source_detail": mawaqit.get("mawaqit_slug"),
                "step": 0,
                "elapsed": time.time() - start,
            }

    # ── Pre-check: is the website even responding? ─────────────────────────
    # Only reject on clear failures (connection refused, DNS fail, timeout).
    # Don't reject on 403/405/406 — some servers block HEAD or non-browser agents
    # but the actual scraper (Jina/Playwright) may still work.
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
            head = await client.head(website, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            if head.status_code in (404, 410, 502, 503, 520, 521, 522, 523, 524):
                logger.info(f"   ❌ Website returned {head.status_code}")
                return _fail(mosque_id, name, website, f"http_{head.status_code}", start)
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        logger.info(f"   ❌ Website unreachable: {type(e).__name__}")
        return _fail(mosque_id, name, website, "unreachable", start)
    except Exception:
        pass  # Other errors (403, 406, etc.) — let the scraper try

    # ── STEP 1: Jina + Haiku (quick scan) ──────────────────────────────────

    md = await jina_fetch(website)
    if not md:
        # Jina failed — try Playwright directly as step 1 fallback
        logger.info(f"   ⚠️ Step 1: Jina failed, trying Playwright directly")
        md = await playwright_fetch(website)
        if not md:
            logger.info(f"   ❌ Both Jina and Playwright failed to fetch")
            return _fail(mosque_id, name, website, "fetch_failed", start)

    logger.info(f"   Step 1 (Jina homepage): {len(md)} chars")
    data1 = claude_extract(md, STEP1_PROMPT, name, model=HAIKU)

    if data1:
        v1 = validate_result(data1)
        enrichment = v1.get("enrichment", {})
        prayer_url = v1.get("prayer_times_url")

        # Log enrichment findings
        jumuah = v1["jumuah"]
        women = enrichment.get("has_womens_section")
        denom = enrichment.get("denomination")
        langs = enrichment.get("languages_spoken", [])
        if jumuah or women is not None or denom or langs:
            logger.info(f"   📋 Enrichment: jumuah={len(jumuah)} women={women} denom={denom} langs={langs}")

        if v1["prayers_found"] >= 2:
            logger.info(f"   ✅ Step 1: Found {v1['prayers_found']}/5 prayers on homepage!")
            _log_prayers(v1)
            _log_jumuah(v1)
            return _success(mosque_id, name, website, v1, enrichment, 1, start)

        # Try finding prayer page link via Playwright nav scan
        if v1["prayers_found"] == 0 and not prayer_url:
            nav_links = await _find_prayer_links_playwright(website)
            if nav_links:
                prayer_url = nav_links[0]
                logger.info(f"   🔍 Found prayer link via nav scan: {prayer_url}")

        # If Claude found a prayer page URL, try it with Jina first
        if prayer_url:
            # Resolve relative URLs
            if prayer_url.startswith("/"):
                parsed = urlparse(website)
                prayer_url = f"{parsed.scheme}://{parsed.netloc}{prayer_url}"

            logger.info(f"   🔗 Step 1b: Found prayer URL → {prayer_url}")
            md_prayer = await jina_fetch(prayer_url)
            if md_prayer and len(md_prayer) > 100:
                data1b = claude_extract(md_prayer, STEP2_PROMPT, name, model=HAIKU)
                if data1b:
                    v1b = validate_result(data1b)
                    if v1b["prayers_found"] >= 2:
                        logger.info(f"   ✅ Step 1b: Found {v1b['prayers_found']}/5 prayers on prayer page!")
                        _log_prayers(v1b)
                        # Merge jumuah from both
                        v1b["jumuah"] = v1b["jumuah"] or jumuah
                        _log_jumuah(v1b)
                        return _success(mosque_id, name, website, v1b, enrichment, 1, start)

    else:
        prayer_url = None

    # ── IFRAME CHECK (runs even if data1 failed) ──────────────────────────
    prayers_so_far = (v1["prayers_found"] if data1 else 0)
    if prayers_so_far == 0:
        iframe_result = await _extract_from_iframes(website, name)
        if iframe_result and iframe_result["prayers_found"] >= 2:
            logger.info(f"   ✅ Iframe widget: Found {iframe_result['prayers_found']}/5 prayers!")
            _log_prayers(iframe_result)
            iframe_result["jumuah"] = iframe_result.get("jumuah", []) or (v1["jumuah"] if data1 else [])
            _log_jumuah(iframe_result)
            return _success(mosque_id, name, website, iframe_result, enrichment, 1, start)

    # ── STEP 2: Playwright + Haiku ─────────────────────────────────────────

    # If we found a prayer URL, try it first with Playwright (more reliable than Jina for subpages)
    render_url = prayer_url or website
    if prayer_url:
        logger.info(f"   Step 2 (Playwright): rendering prayer page {render_url}")
    else:
        logger.info(f"   Step 2 (Playwright): rendering homepage {render_url}")

    rendered = await playwright_fetch(render_url)
    if not rendered:
        logger.info(f"   ⚠️ Step 2: Playwright failed")
    else:
        logger.info(f"   Step 2: {len(rendered)} chars rendered")
        data2 = claude_extract(rendered, STEP2_PROMPT, name, model=HAIKU)
        if data2:
            v2 = validate_result(data2)
            if v2["prayers_found"] >= 2:
                logger.info(f"   ✅ Step 2: Found {v2['prayers_found']}/5 prayers!")
                _log_prayers(v2)
                v2["jumuah"] = v2["jumuah"] or (v1["jumuah"] if data1 else [])
                _log_jumuah(v2)
                return _success(mosque_id, name, website, v2, enrichment, 2, start)

        # ── STEP 3: Playwright + Sonnet (smarter model) ────────────────────

        logger.info(f"   Step 3 (Sonnet retry): same content, smarter model")
        data3 = claude_extract(rendered, STEP3_PROMPT, name, model=SONNET)
        if data3:
            v3 = validate_result(data3)
            if v3["prayers_found"] >= 2:
                logger.info(f"   ✅ Step 3: Found {v3['prayers_found']}/5 prayers with Sonnet!")
                _log_prayers(v3)
                v3["jumuah"] = v3["jumuah"] or (v1["jumuah"] if data1 else [])
                _log_jumuah(v3)
                return _success(mosque_id, name, website, v3, enrichment, 3, start)

    # ── STEP 2b: Try top 3 prayer subpages with Playwright ──────────────────
    # But only if we haven't spent too long already (time budget: 45s)
    elapsed_so_far = time.time() - start
    if not prayer_url and elapsed_so_far < 50:
        base_url = website.rstrip("/")
        for subpage in ["/prayer-times", "/prayers", "/salah"]:
            if time.time() - start > 50:
                logger.info(f"   ⏱ Time budget exceeded, skipping remaining subpages")
                break
            sub_url = f"{base_url}{subpage}"
            logger.info(f"   Step 2b: Trying Playwright on {subpage}")
            sub_rendered = await playwright_fetch(sub_url, timeout=8000)
            if sub_rendered and len(sub_rendered) > 200:
                sub_data = claude_extract(sub_rendered, STEP2_PROMPT, name, model=HAIKU)
                if sub_data:
                    sub_v = validate_result(sub_data)
                    if sub_v["prayers_found"] >= 2:
                        logger.info(f"   ✅ Step 2b: Found {sub_v['prayers_found']}/5 prayers on {subpage}!")
                        _log_prayers(sub_v)
                        sub_v["jumuah"] = sub_v["jumuah"] or (v1["jumuah"] if data1 else [])
                        _log_jumuah(sub_v)
                        return _success(mosque_id, name, website, sub_v, enrichment, 2, start)

    # ── No prayer times found ──────────────────────────────────────────────

    elapsed = time.time() - start
    jumuah_from_step1 = v1["jumuah"] if data1 else []
    logger.info(f"   ⚠️ No prayer times found ({elapsed:.1f}s)")
    logger.info(f"   Enrichment + {len(jumuah_from_step1)} jumuah saved")

    return {
        "mosque_id": mosque_id, "name": name, "website": website,
        "success": True,  # enrichment still counts
        "prayers_found": 0, "jumuah": jumuah_from_step1,
        "enrichment": enrichment,
        "source": "none", "step": 0, "elapsed": elapsed,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fail(mosque_id, name, website, error, start):
    return {
        "mosque_id": mosque_id, "name": name, "website": website,
        "success": False, "error": error, "elapsed": time.time() - start,
    }

def _success(mosque_id, name, website, validated, enrichment, step, start):
    return {
        "mosque_id": mosque_id, "name": name, "website": website,
        "success": True,
        "prayers_found": validated["prayers_found"],
        "prayer_times": validated["prayer_times"],
        "sunrise": validated.get("sunrise"),
        "jumuah": validated["jumuah"],
        "enrichment": enrichment,
        "source": f"step{step}",
        "step": step,
        "elapsed": time.time() - start,
    }

def _log_prayers(v):
    for p in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
        d = v["prayer_times"].get(p, {})
        if d.get("adhan") or d.get("iqama"):
            logger.info(f"      {p}: adhan={d.get('adhan')} iqama={d.get('iqama')}")

def _log_jumuah(v):
    for j in v.get("jumuah", []):
        logger.info(f"      Jumuah: khutbah={j.get('khutbah_time')} prayer={j.get('prayer_time')} "
                     f"lang={j.get('language')} imam={j.get('imam')}")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    db_url = os.environ.get("DATABASE_URL", settings.database_url)
    sync_url = db_url.replace("+asyncpg", "+psycopg2")
    if "psycopg2" not in sync_url:
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://")
    return create_engine(sync_url)


SOURCE_MAP = {
    "mawaqit": ("mawaqit_api", "high"),
    "step1": ("claude_jina", "medium"),
    "step2": ("claude_playwright", "medium"),
    "step3": ("claude_sonnet", "medium"),
    "iframe": ("iframe_widget", "high"),
}


def save_result(engine, result: dict, target_date: date):
    """Save scrape result to prayer_schedules, scraping_jobs, mosques, and jumuah_sessions."""
    mosque_id = result["mosque_id"]
    source = result.get("source", "none")
    source_label, confidence = SOURCE_MAP.get(source, (source, "low"))

    with engine.begin() as conn:
        # ── 1. Update scraping_jobs ────────────────────────────────────────
        now = datetime.utcnow()
        scrape_method = source_label
        extraction_url = result.get("source_detail")
        website_alive = result.get("success", False) or result.get("error") not in ("unreachable", "fetch_failed")

        conn.execute(text("""
            UPDATE scraping_jobs SET
                status = :status,
                last_attempted_at = :now,
                last_success_at = CASE WHEN :success THEN :now ELSE last_success_at END,
                attempts_count = attempts_count + 1,
                consecutive_failures = CASE WHEN :success THEN 0 ELSE consecutive_failures + 1 END,
                tier_reached = :step,
                scrape_method = :method,
                extraction_url = :extraction_url,
                website_alive = :alive,
                website_checked_at = :now,
                error_message = :error,
                raw_extracted_json = :raw_json,
                scraped_at = :now,
                updated_at = :now
            WHERE mosque_id = :mid
        """), {
            "mid": mosque_id, "status": "success" if result.get("success") else "failed",
            "now": now, "success": result.get("success", False),
            "step": result.get("step", 0), "method": scrape_method,
            "extraction_url": extraction_url, "alive": website_alive,
            "error": result.get("error"),
            "raw_json": json.dumps({
                "prayers_found": result.get("prayers_found", 0),
                "source": source, "step": result.get("step", 0),
            }),
        })

        if not result.get("success") or result.get("prayers_found", 0) == 0:
            # Still save enrichment even on prayer failure
            _save_enrichment(conn, mosque_id, result.get("enrichment", {}))
            _save_jumuah(conn, mosque_id, result.get("jumuah", []), target_date, source_label, confidence)
            return

        # ── 2. Save prayer_schedules ───────────────────────────────────────
        pt = result.get("prayer_times", {})

        values = {"mid": mosque_id, "date": target_date, "now": now}
        set_clauses = []

        for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
            d = pt.get(prayer, {})
            adhan = d.get("adhan") if isinstance(d, dict) else None
            iqama = d.get("iqama") if isinstance(d, dict) else None

            # Only overwrite if we have real data
            if adhan:
                values[f"{prayer}_adhan"] = adhan
                values[f"{prayer}_adhan_source"] = source_label
                values[f"{prayer}_adhan_confidence"] = confidence
                set_clauses.append(f"{prayer}_adhan = :{prayer}_adhan")
                set_clauses.append(f"{prayer}_adhan_source = :{prayer}_adhan_source")
                set_clauses.append(f"{prayer}_adhan_confidence = :{prayer}_adhan_confidence")

            if iqama:
                values[f"{prayer}_iqama"] = iqama
                values[f"{prayer}_iqama_source"] = source_label
                values[f"{prayer}_iqama_confidence"] = confidence
                set_clauses.append(f"{prayer}_iqama = :{prayer}_iqama")
                set_clauses.append(f"{prayer}_iqama_source = :{prayer}_iqama_source")
                set_clauses.append(f"{prayer}_iqama_confidence = :{prayer}_iqama_confidence")

        sunrise = result.get("sunrise")
        if sunrise:
            values["sunrise"] = sunrise
            values["sunrise_source"] = source_label
            set_clauses.append("sunrise = :sunrise")
            set_clauses.append("sunrise_source = :sunrise_source")

        if set_clauses:
            set_clauses.append("scraped_at = :now")
            set_clauses.append("updated_at = :now")

            # Upsert: insert or update
            conn.execute(text(f"""
                INSERT INTO prayer_schedules (id, mosque_id, date, {', '.join(k for k in values if k not in ('mid','date','now'))}, scraped_at, created_at, updated_at)
                VALUES (gen_random_uuid(), :mid, :date, {', '.join(':'+k for k in values if k not in ('mid','date','now'))}, :now, :now, :now)
                ON CONFLICT (mosque_id, date)
                DO UPDATE SET {', '.join(set_clauses)}
            """), values)

            logger.info(f"   💾 Saved prayer schedule ({source_label})")

        # ── 3. Save enrichment ─────────────────────────────────────────────
        _save_enrichment(conn, mosque_id, result.get("enrichment", {}))

        # ── 4. Save jumuah ─────────────────────────────────────────────────
        _save_jumuah(conn, mosque_id, result.get("jumuah", []), target_date, source_label, confidence)


def _save_enrichment(conn, mosque_id: str, enrichment: dict):
    """Update mosque enrichment fields (only non-null values)."""
    if not enrichment:
        return

    updates = []
    values = {"mid": mosque_id}

    for field, col in [
        ("has_womens_section", "has_womens_section"),
        ("wheelchair_accessible", "wheelchair_accessible"),
        ("denomination", "denomination"),
        ("phone", "phone"),
        ("email", "email"),
    ]:
        v = enrichment.get(field)
        if v is not None:
            updates.append(f"{col} = :{col}")
            values[col] = v

    langs = enrichment.get("languages_spoken")
    if langs and isinstance(langs, list) and len(langs) > 0:
        updates.append("languages_spoken = :langs")
        values["langs"] = langs

    if updates:
        updates.append("updated_at = now()")
        conn.execute(text(f"UPDATE mosques SET {', '.join(updates)} WHERE id = :mid"), values)
        logger.info(f"   💾 Saved enrichment ({len(updates)-1} fields)")


def _save_jumuah(conn, mosque_id: str, jumuah: list, target_date: date,
                  source_label: str, confidence: str):
    """Save jumuah sessions — replace existing for this date."""
    if not jumuah:
        return

    # Delete existing for this date
    conn.execute(text(
        "DELETE FROM jumuah_sessions WHERE mosque_id = :mid AND valid_date = :date"
    ), {"mid": mosque_id, "date": target_date})

    for i, j in enumerate(jumuah):
        if not isinstance(j, dict):
            continue
        kh = j.get("khutbah_time")
        pr = j.get("prayer_time")
        if not kh and not pr:
            continue

        conn.execute(text("""
            INSERT INTO jumuah_sessions (id, mosque_id, valid_date, session_number, khutba_start, prayer_start,
                                         imam_name, language, source, confidence, scraped_at, created_at)
            VALUES (gen_random_uuid(), :mid, :date, :num, :kh, :pr, :imam, :lang, :source, :conf, now(), now())
        """), {
            "mid": mosque_id, "date": target_date, "num": i + 1,
            "kh": kh, "pr": pr, "imam": j.get("imam"), "lang": j.get("language"),
            "source": source_label, "conf": confidence,
        })

    logger.info(f"   💾 Saved {len(jumuah)} jumuah session(s)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def run(args):
    global total_input_tokens, total_output_tokens
    total_input_tokens = 0
    total_output_tokens = 0

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
                  AND website NOT LIKE '%%facebook.com%%'
                  AND LENGTH(website) > 10
                ORDER BY random()
                LIMIT :limit
            """), {"limit": limit}).fetchall()

    logger.info(f"Processing {len(rows)} mosques")

    results = []
    dry_run = args.test is not None or args.dry_run

    for i, row in enumerate(rows):
        mosque_id, name, website = row[0], row[1], row[2]
        lat = float(row[3]) if row[3] else 0.0
        lng = float(row[4]) if row[4] else 0.0

        r = await scrape_mosque(mosque_id, name, website, lat=lat, lng=lng, dry_run=dry_run)
        results.append(r)

        # Save to DB (unless test/dry-run mode)
        if not dry_run:
            try:
                save_result(engine, r, today)
            except Exception as e:
                logger.error(f"   💾 DB save failed: {e}")

        if i < len(rows) - 1:
            await asyncio.sleep(1)

    # ── Summary ────────────────────────────────────────────────────────────

    print(f"\n{'='*70}")
    print(f"📊 RESULTS — {len(results)} mosques")
    print(f"{'='*70}")

    fetched = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    with_prayers = [r for r in fetched if r.get("prayers_found", 0) >= 1]
    with_jumuah = [r for r in fetched if len(r.get("jumuah", [])) > 0]
    with_enrichment = [r for r in fetched if r.get("enrichment")]

    print(f"\n  Fetched:        {len(fetched)}/{len(results)}")
    print(f"  Prayer times:   {len(with_prayers)}/{len(results)} ({len(with_prayers)*100//max(len(results),1)}%)")
    for r in with_prayers:
        print(f"    ✅ {r['name']}: {r['prayers_found']}/5 (step {r['step']})")
    print(f"  Jumuah:         {len(with_jumuah)}/{len(results)} ({len(with_jumuah)*100//max(len(results),1)}%)")
    for r in with_jumuah:
        print(f"    🕋 {r['name']}: {len(r['jumuah'])} session(s)")
    print(f"  Enrichment:     {len(with_enrichment)}/{len(results)}")
    print(f"  Failed:         {len(failed)}/{len(results)}")
    for r in failed:
        print(f"    ❌ {r['name']}: {r.get('error')}")

    # Step breakdown
    step_counts = {}
    for r in with_prayers:
        s = r.get("step", 0)
        step_counts[s] = step_counts.get(s, 0) + 1
    if step_counts:
        print(f"\n  Step breakdown:")
        for s in sorted(step_counts):
            label = {1: "Jina+Haiku", 2: "Playwright+Haiku", 3: "Playwright+Sonnet"}.get(s, f"step{s}")
            print(f"    Step {s} ({label}): {step_counts[s]} mosques")

    # Cost
    haiku_cost = total_input_tokens * 1.0 / 1_000_000 + total_output_tokens * 5.0 / 1_000_000
    print(f"\n  Tokens: {total_input_tokens:,} in / {total_output_tokens:,} out")
    print(f"  Estimated cost: ${haiku_cost:.4f}")
    print(f"  Projected for 1,000 mosques: ${haiku_cost * 1000 / max(len(results), 1):.2f}")

    total_time = sum(r.get("elapsed", 0) for r in results)
    print(f"  Total time: {total_time:.0f}s ({total_time/max(len(results),1):.1f}s avg)")

    return results


def main():
    parser = argparse.ArgumentParser(description="Smart mosque scraper (3-step pipeline)")
    parser.add_argument("--test", type=int, metavar="N", help="Test N random mosques")
    parser.add_argument("--batch", type=int, metavar="N", help="Process N mosques")
    parser.add_argument("--mosque-id", type=str, help="Scrape specific mosque UUID")
    parser.add_argument("--all", action="store_true", help="Process all mosques with websites")
    parser.add_argument("--dry-run", action="store_true", help="Don't save to database")
    args = parser.parse_args()

    if not any([args.test, args.batch, args.mosque_id, args.all]):
        parser.print_help()
        sys.exit(1)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
