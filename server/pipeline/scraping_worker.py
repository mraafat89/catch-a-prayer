"""
Scraping Worker
===============
5-tier prayer time scraper for mosque prayer schedules.

Tier 1 — IslamicFinder structured lookup
Tier 2 — Static HTML (httpx + BeautifulSoup)
Tier 3 — Playwright JS rendering
Tier 4 — Vision AI for images / pdfplumber for PDFs
Tier 5 — Calculated (praytimes) + estimated iqama offsets

Usage:
    python -m pipeline.scraping_worker                        # process all pending jobs
    python -m pipeline.scraping_worker --mosque-id <uuid>     # scrape one mosque
    python -m pipeline.scraping_worker --batch 50             # process N pending jobs
    python -m pipeline.scraping_worker --dry-run              # parse but don't save
"""

import asyncio
import argparse
import base64
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
import pytz
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRAYER_NAMES = ["fajr", "dhuhr", "asr", "maghrib", "isha"]

# Iqama defaults when not scraped (Tier 5 fallback)
DEFAULT_IQAMA_OFFSETS = {
    "fajr": 20, "dhuhr": 15, "asr": 10, "maghrib": 5, "isha": 15,
}

# Expected adhan time ranges (HH:MM 24h) for validation
PRAYER_TIME_RANGES = {
    "fajr":    ("03:30", "07:30"),
    "dhuhr":   ("11:00", "14:30"),
    "asr":     ("13:00", "19:00"),
    "maghrib": ("16:00", "21:30"),
    "isha":    ("18:00", "24:00"),
}

# OSM aliases to canonical prayer names
PRAYER_ALIASES = {
    "fajr": "fajr", "fajir": "fajr", "subh": "fajr", "subuh": "fajr",
    "dhuhr": "dhuhr", "zuhr": "dhuhr", "zohr": "dhuhr", "dhuhr/zuhr": "dhuhr",
    "asr": "asr", "asar": "asr", "asr/asar": "asr",
    "maghrib": "maghrib", "magrib": "maghrib", "maghrib/sunset": "maghrib",
    "isha": "isha", "isha'a": "isha", "esha": "isha", "ishaa": "isha",
}

PRAYER_SUBPAGE_PATTERNS = [
    "/prayer-times", "/prayers", "/salah", "/schedule", "/timetable",
    "/iqama", "/jamaat", "/monthly", "/daily", "/calendar", "/jumaa",
    "/prayer_times", "/salah-times", "/namaz", "/awqat", "/times",
    "/prayer", "/mosque-schedule", "/prayer-schedule", "/iqama-times",
]

PRAYER_LINK_KEYWORDS = [
    "prayer time", "prayer times", "salah time", "salat time",
    "iqama", "jamaat", "namaz", "schedule", "timetable", "adhan",
    "daily times", "monthly calendar", "prayer schedule",
]

IMAGE_SCHEDULE_KEYWORDS = [
    "schedule", "prayer", "timetable", "iqama", "salah",
    "times", "ramadan", "monthly", "namaz", "salat",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PrayerTimes:
    """Extracted prayer times for a single day."""
    fajr_adhan:    Optional[str] = None
    fajr_iqama:    Optional[str] = None
    dhuhr_adhan:   Optional[str] = None
    dhuhr_iqama:   Optional[str] = None
    asr_adhan:     Optional[str] = None
    asr_iqama:     Optional[str] = None
    maghrib_adhan: Optional[str] = None
    maghrib_iqama: Optional[str] = None
    isha_adhan:    Optional[str] = None
    isha_iqama:    Optional[str] = None
    sunrise:       Optional[str] = None
    source:        str = "unknown"
    confidence:    str = "medium"
    tier:          int = 0
    source_url:    Optional[str] = None

    def adhan_count(self) -> int:
        return sum(1 for p in PRAYER_NAMES if getattr(self, f"{p}_adhan"))

    def iqama_count(self) -> int:
        return sum(1 for p in PRAYER_NAMES if getattr(self, f"{p}_iqama"))

    def is_complete(self) -> bool:
        return self.adhan_count() == 5


@dataclass
class MosqueRecord:
    id: str
    name: str
    website: Optional[str]
    lat: float
    lng: float
    timezone: Optional[str]
    city: Optional[str]
    state: Optional[str]


# ---------------------------------------------------------------------------
# Time utilities
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*(AM|PM|am|pm)?\b")


def normalize_time(raw: Optional[str]) -> Optional[str]:
    """
    Convert any time string to HH:MM (24h). Returns None if unparseable.
    Handles: "3:45 PM", "15:45", "3:45PM", "03:45 am", "3:45\u202fPM".
    """
    if not raw:
        return None
    raw = str(raw).strip()
    # Normalise unicode spaces / non-breaking spaces
    raw = raw.replace("\u202f", " ").replace("\xa0", " ").upper()
    raw = re.sub(r"[.:]+$", "", raw)

    m = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)?$", raw)
    if not m:
        return None

    h, mn, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm == "PM" and h != 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0

    if not (0 <= h <= 23 and 0 <= mn <= 59):
        return None
    return f"{h:02d}:{mn:02d}"


def hhmm_to_minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def add_minutes(hhmm: str, mins: int) -> str:
    total = (hhmm_to_minutes(hhmm) + mins) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_prayer_times(times: PrayerTimes) -> tuple[bool, str]:
    """Returns (is_valid, reason)."""
    for p in PRAYER_NAMES:
        if not getattr(times, f"{p}_adhan"):
            return False, f"Missing {p} adhan"

    for p in PRAYER_NAMES:
        adhan = getattr(times, f"{p}_adhan")
        lo, hi = PRAYER_TIME_RANGES[p]
        if not (lo <= adhan <= hi):
            return False, f"{p} adhan {adhan} outside range {lo}–{hi}"

    for i in range(len(PRAYER_NAMES) - 1):
        a = getattr(times, f"{PRAYER_NAMES[i]}_adhan")
        b = getattr(times, f"{PRAYER_NAMES[i + 1]}_adhan")
        if a >= b:
            return False, f"{PRAYER_NAMES[i]} ({a}) not before {PRAYER_NAMES[i + 1]} ({b})"

    for p in PRAYER_NAMES:
        adhan = getattr(times, f"{p}_adhan")
        iqama = getattr(times, f"{p}_iqama")
        if adhan and iqama:
            if iqama < adhan:
                return False, f"{p} iqama ({iqama}) before adhan ({adhan})"
            gap = hhmm_to_minutes(iqama) - hhmm_to_minutes(adhan)
            if gap > 45:
                return False, f"{p} iqama gap {gap} min > 45 min max"

    return True, "ok"


# ---------------------------------------------------------------------------
# HTML extraction helpers
# ---------------------------------------------------------------------------

def extract_times_from_table(soup: BeautifulSoup) -> Optional[PrayerTimes]:
    """
    Scan all <table> elements for prayer times.
    Returns the best result (most complete) or None.
    """
    best: Optional[PrayerTimes] = None
    best_count = 0

    for table in soup.find_all("table"):
        table_text = table.get_text(" ").lower()
        if not any(k in table_text for k in ["fajr", "dhuhr", "zuhr", "asr", "maghrib", "isha"]):
            continue

        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Detect column layout from header row
        headers = [cell.get_text(strip=True).lower()
                   for cell in rows[0].find_all(["th", "td"])]

        prayer_col = adhan_col = iqama_col = None
        for i, h in enumerate(headers):
            if any(alias in h for alias in PRAYER_ALIASES):
                prayer_col = i
            elif any(w in h for w in ("adhan", "azan", "athan", "adaan")):
                adhan_col = i
            elif any(w in h for w in ("iqama", "iqamah", "jamaat", "jama'ah", "jamah", "congregation")):
                iqama_col = i

        result = PrayerTimes()
        found = 0

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            texts = [c.get_text(strip=True) for c in cells]

            # Find prayer name in this row
            prayer = None
            first_text = texts[0].lower() if texts else ""
            if prayer_col is not None and prayer_col < len(texts):
                first_text = texts[prayer_col].lower()
            for alias, canonical in PRAYER_ALIASES.items():
                if alias in first_text:
                    prayer = canonical
                    break

            if not prayer:
                continue

            # Extract times
            adhan_t = iqama_t = None
            if adhan_col is not None and adhan_col < len(texts):
                adhan_t = normalize_time(texts[adhan_col])
            if iqama_col is not None and iqama_col < len(texts):
                iqama_t = normalize_time(texts[iqama_col])

            if not adhan_t:
                all_t = [normalize_time(t) for t in texts if normalize_time(t)]
                if all_t:
                    adhan_t = all_t[0]
                    if len(all_t) >= 2:
                        iqama_t = all_t[1]

            if adhan_t and not getattr(result, f"{prayer}_adhan"):
                setattr(result, f"{prayer}_adhan", adhan_t)
                if iqama_t:
                    setattr(result, f"{prayer}_iqama", iqama_t)
                found += 1

        if found > best_count:
            best_count = found
            best = result

    return best if best_count >= 3 else None


def extract_times_from_text(text: str) -> Optional[PrayerTimes]:
    """
    Regex fallback: scan lines for prayer name + adjacent time(s).
    Returns PrayerTimes or None if fewer than 3 prayers found.
    """
    result = PrayerTimes()
    found = 0
    lines = text.split("\n")

    for line in lines:
        line_lower = line.lower()
        for alias, prayer in PRAYER_ALIASES.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", line_lower):
                times_found = _TIME_RE.findall(line)
                normalized = [normalize_time(f"{t[0]} {t[1]}") for t in times_found]
                normalized = [t for t in normalized if t]
                if normalized and not getattr(result, f"{prayer}_adhan"):
                    setattr(result, f"{prayer}_adhan", normalized[0])
                    if len(normalized) >= 2:
                        setattr(result, f"{prayer}_iqama", normalized[1])
                    found += 1
                break

    return result if found >= 3 else None


def _extract_from_soup(soup: BeautifulSoup) -> Optional[PrayerTimes]:
    """Run table + text extraction, return whichever is more complete."""
    table_result = extract_times_from_table(soup)
    text_result = extract_times_from_text(soup.get_text("\n"))

    candidates = [r for r in [table_result, text_result] if r]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.adhan_count() * 10 + r.iqama_count())


def discover_prayer_subpages(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Return up to 5 internal links that likely lead to prayer times pages."""
    base = urlparse(base_url)
    base_domain = f"{base.scheme}://{base.netloc}"
    candidates = []

    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        link_text = a.get_text(strip=True).lower()

        if any(p in href for p in PRAYER_SUBPAGE_PATTERNS) or \
           any(kw in link_text for kw in PRAYER_LINK_KEYWORDS):
            full = urljoin(base_domain, a["href"])
            if urlparse(full).netloc == base.netloc and full not in candidates:
                candidates.append(full)

    return candidates[:5]


def score_image_for_schedule(img_tag, surrounding_text: str = "") -> int:
    src = img_tag.get("src", "").lower()
    alt = (img_tag.get("alt", "") + " " + img_tag.get("title", "")).lower()
    combined = f"{src} {alt}"
    score = 0
    for kw in IMAGE_SCHEDULE_KEYWORDS:
        if kw in combined:
            score += 3
            break
    if any(kw in surrounding_text.lower()
           for kw in ["prayer", "schedule", "iqama", "salah", "times"]):
        score += 2
    if any(ext in src for ext in [".jpg", ".jpeg", ".png", ".webp"]):
        score += 1
    return score


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_sync_engine():
    db_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"
    ).split("?")[0]
    return create_engine(db_url, echo=False)


def get_pending_jobs(session: Session, batch_size: int) -> list[MosqueRecord]:
    rows = session.execute(text("""
        SELECT m.id::text, m.name, m.website, m.lat, m.lng,
               m.timezone, m.city, m.state
        FROM scraping_jobs j
        JOIN mosques m ON m.id = j.mosque_id
        WHERE j.status IN ('pending', 'failed')
          AND j.next_attempt_at <= NOW()
          AND m.is_active = true
          AND m.website IS NOT NULL
        ORDER BY j.priority ASC, j.next_attempt_at ASC
        LIMIT :batch_size
    """), {"batch_size": batch_size}).mappings().all()

    return [MosqueRecord(
        id=r["id"], name=r["name"], website=r["website"],
        lat=r["lat"], lng=r["lng"], timezone=r["timezone"],
        city=r["city"], state=r["state"],
    ) for r in rows]


def save_prayer_times(session: Session, mosque: MosqueRecord,
                      times: PrayerTimes, target_date: date, dry_run: bool = False):
    """Upsert prayer schedule for a mosque on a given date."""
    if dry_run:
        return

    iqama_src = times.source if times.iqama_count() > 0 else "estimated"
    iqama_conf = times.confidence if times.iqama_count() > 0 else "low"

    from app.models import PrayerSchedule, new_uuid

    existing = session.execute(text("""
        SELECT id FROM prayer_schedules
        WHERE mosque_id = CAST(:mid AS uuid) AND date = :d
    """), {"mid": mosque.id, "d": target_date}).fetchone()

    if existing:
        session.execute(text("""
            UPDATE prayer_schedules SET
                fajr_adhan=:fa, fajr_iqama=:fi,
                fajr_adhan_source=:src, fajr_iqama_source=:isrc,
                fajr_adhan_confidence=:conf, fajr_iqama_confidence=:iconf,
                sunrise=:sunrise, sunrise_source=:src,
                dhuhr_adhan=:da, dhuhr_iqama=:di,
                dhuhr_adhan_source=:src, dhuhr_iqama_source=:isrc,
                dhuhr_adhan_confidence=:conf, dhuhr_iqama_confidence=:iconf,
                asr_adhan=:aa, asr_iqama=:ai,
                asr_adhan_source=:src, asr_iqama_source=:isrc,
                asr_adhan_confidence=:conf, asr_iqama_confidence=:iconf,
                maghrib_adhan=:ma, maghrib_iqama=:mi,
                maghrib_adhan_source=:src, maghrib_iqama_source=:isrc,
                maghrib_adhan_confidence=:conf, maghrib_iqama_confidence=:iconf,
                isha_adhan=:ia, isha_iqama=:ii,
                isha_adhan_source=:src, isha_iqama_source=:isrc,
                isha_adhan_confidence=:conf, isha_iqama_confidence=:iconf,
                scraped_at=NOW(), updated_at=NOW()
            WHERE mosque_id = CAST(:mid AS uuid) AND date = :d
        """), _prayer_params(mosque.id, target_date, times, iqama_src, iqama_conf))
    else:
        params = _prayer_params(mosque.id, target_date, times, iqama_src, iqama_conf)
        params["id"] = new_uuid()
        session.execute(text("""
            INSERT INTO prayer_schedules (
                id, mosque_id, date,
                fajr_adhan, fajr_iqama,
                fajr_adhan_source, fajr_iqama_source,
                fajr_adhan_confidence, fajr_iqama_confidence,
                sunrise, sunrise_source,
                dhuhr_adhan, dhuhr_iqama,
                dhuhr_adhan_source, dhuhr_iqama_source,
                dhuhr_adhan_confidence, dhuhr_iqama_confidence,
                asr_adhan, asr_iqama,
                asr_adhan_source, asr_iqama_source,
                asr_adhan_confidence, asr_iqama_confidence,
                maghrib_adhan, maghrib_iqama,
                maghrib_adhan_source, maghrib_iqama_source,
                maghrib_adhan_confidence, maghrib_iqama_confidence,
                isha_adhan, isha_iqama,
                isha_adhan_source, isha_iqama_source,
                isha_adhan_confidence, isha_iqama_confidence,
                scraped_at
            ) VALUES (
                :id, CAST(:mid AS uuid), :d,
                :fa, :fi, :src, :isrc, :conf, :iconf,
                :sunrise, :src,
                :da, :di, :src, :isrc, :conf, :iconf,
                :aa, :ai, :src, :isrc, :conf, :iconf,
                :ma, :mi, :src, :isrc, :conf, :iconf,
                :ia, :ii, :src, :isrc, :conf, :iconf,
                NOW()
            )
        """), params)


def _prayer_params(mosque_id: str, d: date, times: PrayerTimes,
                   iqama_src: str, iqama_conf: str) -> dict:
    return {
        "mid": mosque_id, "d": d,
        "fa": times.fajr_adhan,    "fi": times.fajr_iqama,
        "da": times.dhuhr_adhan,   "di": times.dhuhr_iqama,
        "aa": times.asr_adhan,     "ai": times.asr_iqama,
        "ma": times.maghrib_adhan, "mi": times.maghrib_iqama,
        "ia": times.isha_adhan,    "ii": times.isha_iqama,
        "sunrise": times.sunrise,
        "src": times.source, "isrc": iqama_src,
        "conf": times.confidence, "iconf": iqama_conf,
    }


def update_job_status(session: Session, mosque_id: str, success: bool,
                      tier: int, error: Optional[str],
                      url: Optional[str], raw_json: Optional[dict]):
    now = datetime.utcnow()

    if success:
        next_attempt = now + timedelta(days=7)
        cf_expr = "0"
        status = "success"
    else:
        row = session.execute(text("""
            SELECT consecutive_failures FROM scraping_jobs
            WHERE mosque_id = CAST(:mid AS uuid)
        """), {"mid": mosque_id}).fetchone()
        cf = (row[0] if row else 0) + 1
        if cf == 1:
            next_attempt = now + timedelta(days=1)
        elif cf == 2:
            next_attempt = now + timedelta(days=3)
        elif cf <= 5:
            next_attempt = now + timedelta(days=7)
        else:
            next_attempt = now + timedelta(days=30)
        cf_expr = str(cf)
        status = "failed"

    session.execute(text(f"""
        UPDATE scraping_jobs SET
            status               = :status,
            last_attempted_at    = :now,
            last_success_at      = CASE WHEN :success THEN :now ELSE last_success_at END,
            attempts_count       = attempts_count + 1,
            consecutive_failures = {cf_expr},
            next_attempt_at      = :next_attempt,
            tier_reached         = :tier,
            error_message        = :error,
            raw_html_url         = COALESCE(:url, raw_html_url),
            raw_extracted_json   = COALESCE(CAST(:raw_json AS jsonb), raw_extracted_json),
            updated_at           = :now
        WHERE mosque_id = CAST(:mid AS uuid)
    """), {
        "status": status, "now": now, "success": success,
        "next_attempt": next_attempt, "tier": tier,
        "error": error, "url": url,
        "raw_json": json.dumps(raw_json) if raw_json else None,
        "mid": mosque_id,
    })


# ---------------------------------------------------------------------------
# Tier 1 — IslamicFinder
# ---------------------------------------------------------------------------

async def tier1_islamicfinder(mosque: MosqueRecord) -> Optional[PrayerTimes]:
    """
    Search IslamicFinder for this mosque. If found, extract iqama+adhan times.
    Only accepts the result if name similarity and coordinate distance both pass.
    """
    if not mosque.city:
        return None

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.islamicfinder.org/prayer-times/",
                params={"city": mosque.city, "state": mosque.state or "", "country": "US"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; CatchAPrayer/1.0)"},
            )
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "lxml")
            result = _extract_from_soup(soup)

            if result and result.is_complete():
                result.source = "islamicfinder"
                result.confidence = "high"
                result.tier = 1
                result.source_url = str(resp.url)
                logger.info(f"    Tier 1: {result.adhan_count()} adhans, "
                            f"{result.iqama_count()} iqamas")
                return result
    except Exception as e:
        logger.debug(f"    Tier 1 error: {e}")

    return None


# ---------------------------------------------------------------------------
# Tier 2 — Static HTML
# ---------------------------------------------------------------------------

async def _fetch_soup(url: str, client: httpx.AsyncClient) -> Optional[tuple[BeautifulSoup, str]]:
    try:
        resp = await client.get(
            url, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CatchAPrayer/1.0)"},
        )
        if resp.status_code == 200:
            return BeautifulSoup(resp.text, "lxml"), str(resp.url)
    except Exception:
        pass
    return None


async def tier2_static_html(mosque: MosqueRecord) -> Optional[PrayerTimes]:
    """Fetch mosque website with httpx and extract prayer times."""
    if not mosque.website:
        return None

    url = mosque.website
    if not url.startswith("http"):
        url = f"https://{url}"

    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        parsed = await _fetch_soup(url, client)
        if not parsed:
            return None
        homepage_soup, final_url = parsed

        result = _extract_from_soup(homepage_soup)
        if result and result.is_complete():
            result.source, result.confidence = "mosque_website_html", "high"
            result.tier, result.source_url = 2, final_url
            return result

        # Discover sub-pages with prayer times
        subpages = discover_prayer_subpages(homepage_soup, final_url)
        best = result
        best_count = result.adhan_count() if result else 0

        for sub_url in subpages[:3]:
            sub = await _fetch_soup(sub_url, client)
            if not sub:
                continue
            sub_result = _extract_from_soup(sub[0])
            if sub_result and sub_result.adhan_count() > best_count:
                best_count = sub_result.adhan_count()
                best = sub_result
                best.source_url = sub[1]
                if best.is_complete():
                    break

        if best and best.adhan_count() >= 3:
            best.source = "mosque_website_html"
            best.confidence = "high" if best.is_complete() else "medium"
            best.tier = 2
            logger.info(f"    Tier 2: {best.adhan_count()} adhans, "
                        f"{best.iqama_count()} iqamas from {best.source_url}")
            return best

    return None


# ---------------------------------------------------------------------------
# Tier 3 — Playwright
# ---------------------------------------------------------------------------

_playwright_semaphore: Optional[asyncio.Semaphore] = None
_playwright_instance = None
_playwright_browser = None
_playwright_context = None
_playwright_job_count = 0
_CONTEXT_RECYCLE_AFTER = 50


async def _get_playwright_context():
    """Return a shared Playwright browser context, recycling every 50 jobs."""
    global _playwright_instance, _playwright_browser, _playwright_context
    global _playwright_job_count

    if _playwright_context is None or _playwright_job_count >= _CONTEXT_RECYCLE_AFTER:
        if _playwright_context:
            await _playwright_context.close()
        if _playwright_browser:
            await _playwright_browser.close()

        from playwright.async_api import async_playwright
        if _playwright_instance is None:
            _playwright_instance = await async_playwright().__aenter__()

        _playwright_browser = await _playwright_instance.chromium.launch(headless=True)
        _playwright_context = await _playwright_browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )
        _playwright_job_count = 0

    _playwright_job_count += 1
    return _playwright_context


async def tier3_playwright(mosque: MosqueRecord) -> Optional[PrayerTimes]:
    """Render JS-heavy mosque pages with Playwright."""
    if not mosque.website:
        return None

    global _playwright_semaphore
    if _playwright_semaphore is None:
        _playwright_semaphore = asyncio.Semaphore(settings.playwright_workers)

    url = mosque.website
    if not url.startswith("http"):
        url = f"https://{url}"

    async with _playwright_semaphore:
        try:
            ctx = await _get_playwright_context()
            page = await ctx.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
            except Exception:
                try:
                    await page.goto(url, wait_until="load", timeout=20000)
                except Exception:
                    await page.close()
                    return None

            content = await page.content()
            soup = BeautifulSoup(content, "lxml")
            result = _extract_from_soup(soup)

            if result and result.is_complete():
                await page.close()
                result.source, result.confidence = "mosque_website_js", "high"
                result.tier, result.source_url = 3, url
                return result

            # Try sub-pages
            subpages = discover_prayer_subpages(soup, url)
            best = result
            best_count = result.adhan_count() if result else 0

            for sub_url in subpages[:3]:
                try:
                    await page.goto(sub_url, wait_until="networkidle", timeout=20000)
                    sub_soup = BeautifulSoup(await page.content(), "lxml")
                    sub_result = _extract_from_soup(sub_soup)
                    if sub_result and sub_result.adhan_count() > best_count:
                        best_count = sub_result.adhan_count()
                        best = sub_result
                        best.source_url = sub_url
                        if best.is_complete():
                            break
                except Exception:
                    continue

            await page.close()

            if best and best.adhan_count() >= 3:
                best.source = "mosque_website_js"
                best.confidence = "high" if best.is_complete() else "medium"
                best.tier = 3
                logger.info(f"    Tier 3: {best.adhan_count()} adhans, "
                            f"{best.iqama_count()} iqamas")
                return best

        except Exception as e:
            logger.debug(f"    Tier 3 error: {e}")

    return None


# ---------------------------------------------------------------------------
# Tier 4 — Vision AI + PDF
# ---------------------------------------------------------------------------

async def tier4_vision_and_pdf(mosque: MosqueRecord) -> Optional[PrayerTimes]:
    """
    Score images and PDF links on the mosque homepage.
    High-scoring images → Claude Haiku Vision. PDFs → pdfplumber.
    """
    if not mosque.website:
        return None

    url = mosque.website
    if not url.startswith("http"):
        url = f"https://{url}"

    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            parsed = await _fetch_soup(url, client)
            if not parsed:
                return None
            soup, _ = parsed

            # Score images
            candidates = []
            for img in soup.find_all("img", src=True):
                src = img.get("src", "")
                if src.startswith("data:") or not src:
                    continue
                parent_text = img.parent.get_text(strip=True) if img.parent else ""
                score = score_image_for_schedule(img, parent_text)
                if score >= 4:
                    candidates.append((score, urljoin(url, src)))
            candidates.sort(reverse=True)

            # PDF links
            pdf_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.lower().endswith(".pdf"):
                    text_link = a.get_text(strip=True).lower()
                    if any(kw in text_link or kw in href.lower()
                           for kw in ["prayer", "schedule", "iqama", "salah", "timetable"]):
                        pdf_links.append(urljoin(url, href))

            # Try PDFs first (cheaper than Vision AI)
            for pdf_url in pdf_links[:2]:
                result = await _extract_from_pdf(pdf_url, client)
                if result and result.adhan_count() >= 3:
                    result.tier = 4
                    return result

            # Try images with Vision AI
            if settings.anthropic_api_key:
                for _, img_url in candidates[:3]:
                    result = await _extract_from_image(img_url, client)
                    if result and result.adhan_count() >= 3:
                        result.source_url = img_url
                        result.tier = 4
                        return result

    except Exception as e:
        logger.debug(f"    Tier 4 error: {e}")

    return None


async def _extract_from_pdf(pdf_url: str, client: httpx.AsyncClient) -> Optional[PrayerTimes]:
    try:
        import io
        import pdfplumber

        resp = await client.get(pdf_url, timeout=30)
        if resp.status_code != 200:
            return None

        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            all_text = "\n".join(p.extract_text() or "" for p in pdf.pages[:5])

        result = extract_times_from_text(all_text)
        if result and result.adhan_count() >= 3:
            result.source = "mosque_website_pdf"
            result.confidence = "high"
            result.source_url = pdf_url
            logger.info(f"    Tier 4 (PDF): {result.adhan_count()} adhans, "
                        f"{result.iqama_count()} iqamas")
            return result
    except Exception as e:
        logger.debug(f"    PDF error {pdf_url}: {e}")
    return None


_VISION_PROMPT = """You are extracting prayer times from a mosque website image.

Analyze this image and return ONLY valid JSON:
{
  "is_prayer_schedule": true/false,
  "prayers": {
    "fajr":    { "adhan": "HH:MM or null", "iqama": "HH:MM or null" },
    "dhuhr":   { "adhan": "HH:MM or null", "iqama": "HH:MM or null" },
    "asr":     { "adhan": "HH:MM or null", "iqama": "HH:MM or null" },
    "maghrib": { "adhan": "HH:MM or null", "iqama": "HH:MM or null" },
    "isha":    { "adhan": "HH:MM or null", "iqama": "HH:MM or null" }
  },
  "sunrise": "HH:MM or null"
}

Use 24-hour time. Use null for fields not visible.
If this is not a prayer schedule, return {"is_prayer_schedule": false}.
Handle Arabic numerals and mixed Arabic/English text."""


async def _extract_from_image(img_url: str, client: httpx.AsyncClient) -> Optional[PrayerTimes]:
    try:
        resp = await client.get(img_url, timeout=20)
        if resp.status_code != 200:
            return None

        ct = resp.headers.get("content-type", "image/jpeg").lower()
        if "png" in ct:
            media_type = "image/png"
        elif "webp" in ct:
            media_type = "image/webp"
        elif "gif" in ct:
            media_type = "image/gif"
        else:
            media_type = "image/jpeg"

        img_b64 = base64.standard_b64encode(resp.content).decode()

        import anthropic
        ai_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        message = ai_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": img_b64,
                    }},
                    {"type": "text", "text": _VISION_PROMPT},
                ],
            }],
        )

        text_resp = message.content[0].text.strip()
        json_match = re.search(r"\{.*\}", text_resp, re.DOTALL)
        if not json_match:
            return None

        data = json.loads(json_match.group())
        if not data.get("is_prayer_schedule"):
            return None

        prayers = data.get("prayers", {})
        result = PrayerTimes(
            fajr_adhan=normalize_time(prayers.get("fajr", {}).get("adhan")),
            fajr_iqama=normalize_time(prayers.get("fajr", {}).get("iqama")),
            dhuhr_adhan=normalize_time(prayers.get("dhuhr", {}).get("adhan")),
            dhuhr_iqama=normalize_time(prayers.get("dhuhr", {}).get("iqama")),
            asr_adhan=normalize_time(prayers.get("asr", {}).get("adhan")),
            asr_iqama=normalize_time(prayers.get("asr", {}).get("iqama")),
            maghrib_adhan=normalize_time(prayers.get("maghrib", {}).get("adhan")),
            maghrib_iqama=normalize_time(prayers.get("maghrib", {}).get("iqama")),
            isha_adhan=normalize_time(prayers.get("isha", {}).get("adhan")),
            isha_iqama=normalize_time(prayers.get("isha", {}).get("iqama")),
            sunrise=normalize_time(data.get("sunrise")),
            source="mosque_website_image",
            confidence="high",
        )
        logger.info(f"    Tier 4 (Vision): {result.adhan_count()} adhans, "
                    f"{result.iqama_count()} iqamas")
        return result

    except Exception as e:
        logger.debug(f"    Vision AI error {img_url}: {e}")
    return None


# ---------------------------------------------------------------------------
# Tier 5 — Calculated fallback
# ---------------------------------------------------------------------------

def tier5_calculated(mosque: MosqueRecord, target_date: date) -> PrayerTimes:
    """
    Calculate adhan times via praytimes (ISNA). Estimate iqama with fixed offsets.
    Always succeeds — last resort.
    """
    from praytimes import PrayTimes

    tz_name = mosque.timezone or "UTC"
    tz = pytz.timezone(tz_name)
    dt_aware = tz.localize(datetime.combine(target_date, datetime.min.time()))
    utc_offset = dt_aware.utcoffset().total_seconds() / 3600

    pt = PrayTimes(settings.calculation_method)
    raw = pt.getTimes(
        (target_date.year, target_date.month, target_date.day),
        [mosque.lat, mosque.lng],
        utc_offset,
    )

    def g(key: str) -> Optional[str]:
        v = raw.get(key, "")
        return normalize_time(v) if v and "----" not in v else None

    fa = g("fajr");  da = g("dhuhr"); aa = g("asr")
    ma = g("maghrib"); ia = g("isha"); sr = g("sunrise")

    def est_iqama(adhan: Optional[str], p: str) -> Optional[str]:
        return add_minutes(adhan, DEFAULT_IQAMA_OFFSETS[p]) if adhan else None

    result = PrayerTimes(
        fajr_adhan=fa,    fajr_iqama=est_iqama(fa, "fajr"),
        dhuhr_adhan=da,   dhuhr_iqama=est_iqama(da, "dhuhr"),
        asr_adhan=aa,     asr_iqama=est_iqama(aa, "asr"),
        maghrib_adhan=ma, maghrib_iqama=est_iqama(ma, "maghrib"),
        isha_adhan=ia,    isha_iqama=est_iqama(ia, "isha"),
        sunrise=sr,
        source="calculated",
        confidence="medium",
        tier=5,
    )
    logger.info(f"    Tier 5 (calculated): {result.adhan_count()} adhans (iqama estimated)")
    return result


# ---------------------------------------------------------------------------
# Main scrape function
# ---------------------------------------------------------------------------

async def scrape_mosque(mosque: MosqueRecord, target_date: date,
                        dry_run: bool = False) -> tuple[bool, int, Optional[str]]:
    """
    Run all tiers for a mosque. Returns (success, tier_reached, error).
    Saves result to database on success unless dry_run.
    """
    logger.info(f"\nScraping: {mosque.name} ({mosque.city}, {mosque.state})")
    logger.info(f"  URL: {mosque.website}")

    result: Optional[PrayerTimes] = None
    tier_reached = 0

    # Tier 1
    try:
        result = await tier1_islamicfinder(mosque)
        tier_reached = 1
    except Exception as e:
        logger.debug(f"  Tier 1 exception: {e}")

    # Tier 2
    if not (result and result.is_complete()):
        try:
            t2 = await tier2_static_html(mosque)
            if t2 and t2.adhan_count() > (result.adhan_count() if result else 0):
                result = t2
            tier_reached = 2
        except Exception as e:
            logger.debug(f"  Tier 2 exception: {e}")

    # Tier 3
    if not (result and result.is_complete()):
        try:
            t3 = await tier3_playwright(mosque)
            if t3 and t3.adhan_count() > (result.adhan_count() if result else 0):
                result = t3
            tier_reached = 3
        except Exception as e:
            logger.debug(f"  Tier 3 exception: {e}")

    # Tier 4
    if not (result and result.is_complete()):
        try:
            t4 = await tier4_vision_and_pdf(mosque)
            if t4 and t4.adhan_count() > (result.adhan_count() if result else 0):
                result = t4
            tier_reached = 4
        except Exception as e:
            logger.debug(f"  Tier 4 exception: {e}")

    # Tier 5 — always fills gaps
    if not result or result.adhan_count() < 5:
        try:
            t5 = tier5_calculated(mosque, target_date)
            if result is None:
                result = t5
            else:
                # Fill any missing adhan/iqama from Tier 5 (mark as calculated/estimated)
                for p in PRAYER_NAMES:
                    if not getattr(result, f"{p}_adhan"):
                        setattr(result, f"{p}_adhan", getattr(t5, f"{p}_adhan"))
                    if not getattr(result, f"{p}_iqama"):
                        setattr(result, f"{p}_iqama", getattr(t5, f"{p}_iqama"))
                if not result.sunrise:
                    result.sunrise = t5.sunrise
            tier_reached = 5
        except Exception as e:
            return False, tier_reached, f"Tier 5 failed: {e}"

    if not result:
        return False, tier_reached, "All tiers failed"

    # Validate — on failure always fall back to a clean Tier 5 calculation
    # (avoids mixed-source corruption where scraped iqama < scraped adhan)
    is_valid, reason = validate_prayer_times(result)
    if not is_valid:
        logger.warning(f"  Validation failed ({reason}), falling back to clean Tier 5")
        try:
            result = tier5_calculated(mosque, target_date)
            tier_reached = 5
            is_valid, reason = validate_prayer_times(result)
        except Exception as e:
            return False, tier_reached, f"Tier 5 fallback failed: {e}"
        if not is_valid:
            return False, tier_reached, f"Validation failed even after Tier 5: {reason}"

    # Persist
    engine = get_sync_engine()
    with Session(engine) as session:
        try:
            save_prayer_times(session, mosque, result, target_date, dry_run)
            update_job_status(
                session, mosque.id, True, tier_reached, None,
                result.source_url,
                {"tier": tier_reached, "source": result.source,
                 "adhans": result.adhan_count(), "iqamas": result.iqama_count()},
            )
            session.commit()
            logger.info(f"  ✓ Saved tier={tier_reached} src={result.source} "
                        f"adhans={result.adhan_count()} iqamas={result.iqama_count()}")
        except Exception as e:
            session.rollback()
            return False, tier_reached, str(e)

    return True, tier_reached, None


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

async def run_worker(batch_size: int = 50, dry_run: bool = False):
    """Pull pending jobs from the DB and scrape them in sequence."""
    engine = get_sync_engine()
    target_date = date.today()

    with Session(engine) as session:
        jobs = get_pending_jobs(session, batch_size)

    if not jobs:
        logger.info("No pending jobs.")
        return

    logger.info(f"Processing {len(jobs)} jobs (dry_run={dry_run})...")
    stats = {"success": 0, "failed": 0}
    tier_counts: dict[int, int] = {}

    for mosque in jobs:
        success, tier, error = await scrape_mosque(mosque, target_date, dry_run)

        if success:
            stats["success"] += 1
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        else:
            stats["failed"] += 1
            logger.warning(f"  FAIL: {mosque.name}: {error}")
            if not dry_run:
                with Session(engine) as session:
                    update_job_status(session, mosque.id, False, tier, error, None, None)
                    session.commit()

    logger.info("=" * 60)
    logger.info(f"Batch done — success: {stats['success']}, failed: {stats['failed']}")
    logger.info(f"Tier distribution: { {f'tier{k}': v for k, v in sorted(tier_counts.items())} }")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Scrape mosque prayer times")
    parser.add_argument("--mosque-id", help="Scrape a single mosque by UUID")
    parser.add_argument("--batch", type=int, default=50,
                        help="Number of jobs per batch (default: 50)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and log but do not write to database")
    args = parser.parse_args()

    if args.mosque_id:
        engine = get_sync_engine()
        with Session(engine) as session:
            row = session.execute(text("""
                SELECT id::text, name, website, lat, lng, timezone, city, state
                FROM mosques WHERE id = CAST(:id AS uuid)
            """), {"id": args.mosque_id}).mappings().first()

        if not row:
            logger.error(f"Mosque {args.mosque_id} not found")
            return

        mosque = MosqueRecord(**dict(row))
        success, tier, error = await scrape_mosque(mosque, date.today(), args.dry_run)
        if not success:
            logger.error(f"Failed (tier {tier}): {error}")
    else:
        await run_worker(args.batch, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
