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
    "fajr": "fajr", "fajir": "fajr", "fajar": "fajr", "fajur": "fajr",
    "subh": "fajr", "subuh": "fajr", "sobh": "fajr",
    "dhuhr": "dhuhr", "zuhr": "dhuhr", "zohr": "dhuhr", "dhuhr/zuhr": "dhuhr",
    "dhuhar": "dhuhr", "dhohr": "dhuhr", "dhur": "dhuhr", "zhuhr": "dhuhr",
    "asr": "asr", "asar": "asr", "asr/asar": "asr", "asor": "asr",
    "maghrib": "maghrib", "magrib": "maghrib", "maghrib/sunset": "maghrib",
    "maghreb": "maghrib", "mughrib": "maghrib",
    "isha": "isha", "isha'a": "isha", "esha": "isha", "ishaa": "isha",
    "ishaa'": "isha", "isha'": "isha",
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
        """True only if we have all 5 adhans AND at least 4 iqamas (mosque-specific data)."""
        return self.adhan_count() == 5 and self.iqama_count() >= 4


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


def normalize_time(raw: Optional[str], prayer: Optional[str] = None) -> Optional[str]:
    """
    Convert any time string to HH:MM (24h). Returns None if unparseable.
    Handles: "3:45 PM", "15:45", "3:45PM", "03:45 am", "3:45\u202fPM".

    When AM/PM is absent and `prayer` is provided, uses expected prayer time ranges
    to disambiguate (e.g. "1:18" for dhuhr → 13:18).
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
    elif ampm is None and prayer:
        # No AM/PM — use prayer ranges to disambiguate 12h vs 24h
        # Prayers that are always PM (never AM): dhuhr, asr, maghrib, isha
        # Fajr is AM; anything 1-9 for PM prayers needs +12
        pm_prayers = {"dhuhr", "asr", "maghrib", "isha"}
        if prayer in pm_prayers and 1 <= h <= 9:
            h += 12  # "1:18" for dhuhr → 13:18
        elif prayer == "isha" and h == 10 or h == 11:
            h += 12  # late isha
        # For fajr with no AM/PM: leave as-is (fajr is naturally < 8)

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
            gap = hhmm_to_minutes(iqama) - hhmm_to_minutes(adhan)
            # Iqama can be before adhan (e.g. Ramadan Fajr iqama before astronomical adhan)
            # but reject if gap is absurdly large in either direction (extraction error)
            if gap < -60:
                return False, f"{p} iqama ({iqama}) is >60 min before adhan ({adhan}) — likely wrong"
            if gap > 90:
                return False, f"{p} iqama gap {gap} min > 90 min — likely wrong"

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
                adhan_t = normalize_time(texts[adhan_col], prayer)
            if iqama_col is not None and iqama_col < len(texts):
                iqama_t = normalize_time(texts[iqama_col], prayer)

            if not adhan_t:
                all_t = [normalize_time(t, prayer) for t in texts if normalize_time(t, prayer)]
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


def extract_times_from_divs(soup: BeautifulSoup) -> Optional[PrayerTimes]:
    """
    Handle div/flex/grid layouts where prayer names and times are in separate elements.
    Looks for a container that has all 5 prayer names in close proximity with time patterns.
    """
    result = PrayerTimes()
    found = 0

    # Strategy: find any element that contains a prayer name, then look at siblings/nearby text for times
    # Walk all elements and build a flat list of (text, element) pairs
    flat: list[str] = []
    for el in soup.find_all(True):
        if el.find(True):  # skip parents, only leaf-like nodes
            continue
        t = el.get_text(strip=True)
        if t:
            flat.append(t)

    # Sliding window: look for prayer name followed within 5 tokens by time(s)
    i = 0
    while i < len(flat):
        token = flat[i].lower()
        matched_prayer = None
        for alias, prayer in PRAYER_ALIASES.items():
            if re.search(r"\b" + re.escape(alias) + r"\b", token):
                matched_prayer = prayer
                break

        if matched_prayer and not getattr(result, f"{matched_prayer}_adhan"):
            # Look at next 5 tokens for times
            times = []
            for j in range(i + 1, min(i + 6, len(flat))):
                m = _TIME_RE.search(flat[j])
                if m:
                    t = normalize_time(f"{m.group(1)} {m.group(2) or ''}")
                    if t:
                        times.append(t)
                # Stop if we hit another prayer name
                if any(re.search(r"\b" + re.escape(a) + r"\b", flat[j].lower())
                       for a in PRAYER_ALIASES):
                    if j > i + 1:
                        break
            if times:
                setattr(result, f"{matched_prayer}_adhan", times[0])
                if len(times) >= 2:
                    setattr(result, f"{matched_prayer}_iqama", times[1])
                found += 1
        i += 1

    return result if found >= 3 else None


def _extract_from_soup(soup: BeautifulSoup) -> Optional[PrayerTimes]:
    """Run table + div + text extraction, return whichever is most complete."""
    table_result = extract_times_from_table(soup)
    div_result = extract_times_from_divs(soup)
    text_result = extract_times_from_text(soup.get_text("\n"))

    candidates = [r for r in [table_result, div_result, text_result] if r]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.adhan_count() * 10 + r.iqama_count())


# Known prayer widget iframe patterns: (url_pattern, label)
IFRAME_WIDGET_PATTERNS = [
    (r"timing\.athanplus\.com", "athanplus"),
    (r"masjidal\.com", "masjidal"),
    (r"salahmate\.com", "salahmate"),
    (r"salattimes\.com", "salattimes"),
    (r"prayer-times.*widget", "generic_widget"),
    (r"muslimpro\.com/embed", "muslimpro"),
    (r"masjid\.us/widget", "masjid_us"),
    (r"mosqueprayertimes\.com/widget", "mosqueprayertimes"),
    (r"prayertimeswidget\.com", "prayertimeswidget"),
    (r"iqamah\.com/widget", "iqamah"),
    (r"masjidbox\.com", "masjidbox"),
    (r"masjidnow\.com", "masjidnow"),
    (r"salahtime\.net", "salahtime"),
    (r"prayerboard\.net", "prayerboard"),
    (r"islamicfinder\.org/embed", "islamicfinder_embed"),
]


def discover_prayer_iframes(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """Return list of (iframe_url, widget_type) for iframes likely containing prayer times."""
    results = []
    base = urlparse(base_url)

    for iframe in soup.find_all("iframe", src=True):
        src = iframe.get("src", "")
        if not src or src.startswith("//"):
            src = "https:" + src if src.startswith("//") else src
        if not src.startswith("http"):
            src = urljoin(f"{base.scheme}://{base.netloc}", src)

        src_lower = src.lower()
        # Skip YouTube, Google Maps, etc.
        if any(skip in src_lower for skip in ["youtube", "maps.google", "facebook.com/plugins",
                                               "twitter", "instagram", "vimeo"]):
            continue

        widget_type = "unknown_iframe"
        for pattern, label in IFRAME_WIDGET_PATTERNS:
            if re.search(pattern, src_lower):
                widget_type = label
                break

        # Include if it's a known widget OR if the surrounding context mentions prayer times
        surrounding = ""
        parent = iframe.parent
        if parent:
            surrounding = parent.get_text(" ", strip=True).lower()

        if widget_type != "unknown_iframe" or any(
            kw in surrounding for kw in ["prayer", "iqama", "salah", "adhan", "namaz"]
        ):
            results.append((src, widget_type))

    return results[:5]


async def fetch_iframe_prayer_times(
    iframe_url: str, widget_type: str, client: httpx.AsyncClient
) -> Optional[PrayerTimes]:
    """Fetch an iframe URL and extract prayer times from its HTML."""
    try:
        resp = await client.get(
            iframe_url, follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Referer": iframe_url,
            },
            timeout=20,
        )
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        result = _extract_from_soup(soup)
        if result and result.adhan_count() >= 3:
            result.source = "mosque_website_html"
            result.confidence = "high" if result.is_complete() else "medium"
            result.source_url = iframe_url
            logger.info(f"    Iframe ({widget_type}): {result.adhan_count()} adhans, "
                        f"{result.iqama_count()} iqamas")
            return result
    except Exception as e:
        logger.debug(f"    Iframe fetch error ({widget_type}): {e}")
    return None


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
        ORDER BY (m.website IS NOT NULL) DESC, j.priority ASC, j.next_attempt_at ASC
        LIMIT :batch_size
    """), {"batch_size": batch_size}).mappings().all()

    return [MosqueRecord(
        id=r["id"], name=r["name"], website=r["website"],
        lat=r["lat"], lng=r["lng"], timezone=r["timezone"],
        city=r["city"], state=r["state"],
    ) for r in rows]


def save_prayer_times(session: Session, mosque: MosqueRecord,
                      times: PrayerTimes, target_date: date, dry_run: bool = False):
    """Upsert prayer schedule for a mosque on a given date.
    Uses INSERT ... ON CONFLICT DO UPDATE to avoid race-condition UniqueViolation errors.
    """
    if dry_run:
        return

    iqama_src = times.source if times.iqama_count() > 0 else "estimated"
    iqama_conf = times.confidence if times.iqama_count() > 0 else "low"

    from app.models import new_uuid

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
        ON CONFLICT (mosque_id, date) DO UPDATE SET
            fajr_adhan=EXCLUDED.fajr_adhan, fajr_iqama=EXCLUDED.fajr_iqama,
            fajr_adhan_source=EXCLUDED.fajr_adhan_source,
            fajr_iqama_source=EXCLUDED.fajr_iqama_source,
            fajr_adhan_confidence=EXCLUDED.fajr_adhan_confidence,
            fajr_iqama_confidence=EXCLUDED.fajr_iqama_confidence,
            sunrise=EXCLUDED.sunrise, sunrise_source=EXCLUDED.sunrise_source,
            dhuhr_adhan=EXCLUDED.dhuhr_adhan, dhuhr_iqama=EXCLUDED.dhuhr_iqama,
            dhuhr_adhan_source=EXCLUDED.dhuhr_adhan_source,
            dhuhr_iqama_source=EXCLUDED.dhuhr_iqama_source,
            dhuhr_adhan_confidence=EXCLUDED.dhuhr_adhan_confidence,
            dhuhr_iqama_confidence=EXCLUDED.dhuhr_iqama_confidence,
            asr_adhan=EXCLUDED.asr_adhan, asr_iqama=EXCLUDED.asr_iqama,
            asr_adhan_source=EXCLUDED.asr_adhan_source,
            asr_iqama_source=EXCLUDED.asr_iqama_source,
            asr_adhan_confidence=EXCLUDED.asr_adhan_confidence,
            asr_iqama_confidence=EXCLUDED.asr_iqama_confidence,
            maghrib_adhan=EXCLUDED.maghrib_adhan, maghrib_iqama=EXCLUDED.maghrib_iqama,
            maghrib_adhan_source=EXCLUDED.maghrib_adhan_source,
            maghrib_iqama_source=EXCLUDED.maghrib_iqama_source,
            maghrib_adhan_confidence=EXCLUDED.maghrib_adhan_confidence,
            maghrib_iqama_confidence=EXCLUDED.maghrib_iqama_confidence,
            isha_adhan=EXCLUDED.isha_adhan, isha_iqama=EXCLUDED.isha_iqama,
            isha_adhan_source=EXCLUDED.isha_adhan_source,
            isha_iqama_source=EXCLUDED.isha_iqama_source,
            isha_adhan_confidence=EXCLUDED.isha_adhan_confidence,
            isha_iqama_confidence=EXCLUDED.isha_iqama_confidence,
            scraped_at=NOW(), updated_at=NOW()
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
# Tier 1b — Aladhan.com mosque search
# ---------------------------------------------------------------------------

async def tier1_aladhan(mosque: MosqueRecord) -> Optional[PrayerTimes]:
    """
    Search Aladhan.com's mosque directory for mosque-specific prayer times.
    Free API, no authentication required.
    Only used when no other source is available (no website).
    Returns mosque-specific iqama times if found — much better than estimates.
    """
    if not mosque.city or not mosque.name:
        return None

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # Search Aladhan mosque directory by name + city
            resp = await client.get(
                "https://api.aladhan.com/v1/mosque/search",
                params={"q": mosque.name, "city": mosque.city, "country": "US"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; CatchAPrayer/1.0)"},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            if not data.get("data") or not data["data"].get("data"):
                return None

            # Find closest match by coordinates
            best_match = None
            best_dist = float("inf")
            for entry in data["data"]["data"][:5]:
                try:
                    mlat = float(entry.get("latitude", 0))
                    mlng = float(entry.get("longitude", 0))
                    dist = ((mlat - mosque.lat) ** 2 + (mlng - mosque.lng) ** 2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_match = entry
                except Exception:
                    continue

            # Accept only if within ~5km (0.05 degrees ≈ 5.5km)
            if not best_match or best_dist > 0.05:
                return None

            timings = best_match.get("timings", {})
            if not timings:
                return None

            def _parse(key: str, prayer: str) -> Optional[str]:
                v = timings.get(key, "")
                # Aladhan returns "HH:MM (timezone)" — strip timezone suffix
                v = re.sub(r"\s*\(.*\)$", "", str(v)).strip()
                return normalize_time(v, prayer)

            pt = PrayerTimes(
                fajr_adhan=_parse("Fajr", "fajr"),
                dhuhr_adhan=_parse("Dhuhr", "dhuhr"),
                asr_adhan=_parse("Asr", "asr"),
                maghrib_adhan=_parse("Maghrib", "maghrib"),
                isha_adhan=_parse("Isha", "isha"),
                sunrise=_parse("Sunrise", "sunrise"),
                # Aladhan mosque API also returns iqama times for some mosques
                fajr_iqama=_parse("Fajr_Iqama", "fajr"),
                dhuhr_iqama=_parse("Dhuhr_Iqama", "dhuhr"),
                asr_iqama=_parse("Asr_Iqama", "asr"),
                maghrib_iqama=_parse("Maghrib_Iqama", "maghrib"),
                isha_iqama=_parse("Isha_Iqama", "isha"),
                source="aladhan_mosque_db",
                confidence="high" if timings.get("Fajr_Iqama") else "medium",
                tier=1,
                source_url=f"https://api.aladhan.com/v1/mosque/search?q={mosque.name}",
            )

            if pt.adhan_count() >= 5:
                logger.info(f"    Tier 1b (Aladhan): {pt.adhan_count()} adhans, "
                            f"{pt.iqama_count()} iqamas (dist={best_dist:.4f}°)")
                return pt

    except Exception as e:
        logger.debug(f"    Tier 1b (Aladhan) error: {e}")

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


async def _try_google_sheets(html_source: str, client: httpx.AsyncClient,
                             base_url: str) -> Optional[PrayerTimes]:
    """
    Detect Google Sheets-backed prayer time widgets (e.g. iccpaz.com Masjid-Tools).
    Looks for googleSheetUrl or direct spreadsheet links in the page source,
    then fetches the sheet as CSV and parses it.
    """
    import csv, io

    # Pattern 1: explicit googleSheetUrl config (Masjid-Tools widget)
    m = re.search(
        r'googleSheetUrl["\s]*:\s*["\']([^"\']+docs\.google\.com/spreadsheets[^"\']+)["\']',
        html_source,
    )
    sheet_url = m.group(1) if m else None

    # Pattern 2: direct spreadsheet embed/export link anywhere on the page
    if not sheet_url:
        m2 = re.search(
            r'(https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+[^"\'<>\s]*)',
            html_source,
        )
        if m2:
            sheet_url = m2.group(1)

    if not sheet_url:
        return None

    # Normalise to CSV export URL
    id_match = re.search(r'/spreadsheets/d/([A-Za-z0-9_-]+)', sheet_url)
    gid_match = re.search(r'gid=(\d+)', sheet_url)
    if not id_match:
        return None

    sheet_id = id_match.group(1)
    gid = gid_match.group(1) if gid_match else None
    # Try with gid first (if found), then without (defaults to first sheet)
    csv_urls = []
    if gid:
        csv_urls.append(f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}")
    csv_urls.append(f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv")

    for csv_url in csv_urls:
        try:
            resp = await client.get(csv_url, timeout=15, follow_redirects=True)
            if resp.status_code != 200:
                continue
            reader = csv.reader(io.StringIO(resp.text))
            rows = list(reader)
            if not rows:
                continue

            # Build a plain-text block from the CSV and run our text extractor
            text_blob = "\n".join(" ".join(row) for row in rows)
            result = _extract_from_text(text_blob)
            if result and result.adhan_count() >= 3:
                result.source = "mosque_website_html"
                result.confidence = "high" if result.is_complete() else "medium"
                result.source_url = csv_url
                logger.info(f"    Google Sheets: {result.adhan_count()} adhans, "
                            f"{result.iqama_count()} iqamas from {csv_url}")
                return result
        except Exception as e:
            logger.debug(f"    Google Sheets fetch error ({csv_url}): {e}")

    return None


async def _try_masjidal_direct(html_source: str, client: httpx.AsyncClient,
                                target_date: date) -> Optional[PrayerTimes]:
    """
    Detect Masjidal widget config in page HTML and call the Masjidal API directly.
    The widget sets a <div class="masjidalContainer" data-id="..."> or similar.
    API: https://api.masjidal.com/API/v1/prayer/times?masjid_id={id}&date=YYYY-MM-DD
    """
    # Look for data-id / data-masjid-id inside masjidal widget markup
    patterns = [
        r'masjidalContainer[^>]*data-id=["\']([A-Za-z0-9_-]+)["\']',
        r'data-masjid(?:-id)?=["\']([A-Za-z0-9_-]+)["\']',
        r'masjidal[^>]*id=["\']([A-Za-z0-9_-]+)["\']',
        r'masjid_id["\s]*[:=]["\s]*["\']([A-Za-z0-9_-]+)["\']',
    ]
    masjid_id = None
    for pat in patterns:
        m = re.search(pat, html_source, re.IGNORECASE)
        if m:
            masjid_id = m.group(1)
            break

    if not masjid_id:
        return None

    date_str = target_date.strftime("%Y-%m-%d")
    api_url = (f"https://api.masjidal.com/API/v1/prayer/times"
               f"?masjid_id={masjid_id}&date={date_str}")
    try:
        resp = await client.get(api_url, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = _parse_athanplus_response(data, target_date)  # Masjidal shares AthanPlus format
        if not result:
            # Try direct field mapping
            pt = PrayerTimes()
            prayer_map = {"fajr": "fajr", "dhuhr": "dhuhr", "asr": "asr",
                          "maghrib": "maghrib", "isha": "isha"}
            found = 0
            for key, prayer in prayer_map.items():
                entry = data.get(key) or data.get(key.capitalize())
                if isinstance(entry, dict):
                    adhan = normalize_time(entry.get("adhan") or entry.get("azan"), prayer)
                    iqama = normalize_time(entry.get("iqama") or entry.get("iqamah"), prayer)
                elif isinstance(entry, str):
                    adhan = normalize_time(entry, prayer)
                    iqama = None
                else:
                    continue
                if adhan:
                    setattr(pt, f"{prayer}_adhan", adhan)
                    if iqama:
                        setattr(pt, f"{prayer}_iqama", iqama)
                    found += 1
            result = pt if found >= 3 else None

        if result and result.adhan_count() >= 3:
            result.source = "mosque_website_js"
            result.confidence = "high"
            result.source_url = api_url
            logger.info(f"    Masjidal direct API: {result.adhan_count()} adhans, "
                        f"{result.iqama_count()} iqamas (id={masjid_id})")
            return result
    except Exception as e:
        logger.debug(f"    Masjidal direct API error (id={masjid_id}): {e}")

    return None


async def tier2_static_html(mosque: MosqueRecord) -> Optional[PrayerTimes]:
    """Fetch mosque website with httpx and extract prayer times.
    Also checks iframes (AthanPlus, Masjidal, etc.) and prayer sub-pages.
    """
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

        best = result
        best_count = result.adhan_count() if result else 0

        # Check iframes (catches AthanPlus, Masjidal, custom prayer widgets)
        iframes = discover_prayer_iframes(homepage_soup, final_url)
        for iframe_url, widget_type in iframes:
            iframe_result = await fetch_iframe_prayer_times(iframe_url, widget_type, client)
            if iframe_result and iframe_result.adhan_count() > best_count:
                best_count = iframe_result.adhan_count()
                best = iframe_result
                if best.is_complete():
                    break

        if best and best.is_complete():
            best.source = "mosque_website_html"
            best.confidence = "high"
            best.tier = 2
            logger.info(f"    Tier 2 (iframe): {best.adhan_count()} adhans, "
                        f"{best.iqama_count()} iqamas")
            return best

        # Discover sub-pages with prayer times
        subpages = discover_prayer_subpages(homepage_soup, final_url)
        for sub_url in subpages[:4]:
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

            # Also check iframes on sub-pages
            if not (best and best.is_complete()):
                sub_iframes = discover_prayer_iframes(sub[0], sub[1])
                for iframe_url, widget_type in sub_iframes:
                    iframe_result = await fetch_iframe_prayer_times(
                        iframe_url, widget_type, client
                    )
                    if iframe_result and iframe_result.adhan_count() > best_count:
                        best_count = iframe_result.adhan_count()
                        best = iframe_result
                        if best.is_complete():
                            break

        # Google Sheets widget detection (e.g. Masjid-Tools / IqamaWidgetConfig)
        if not (best and best.is_complete()):
            homepage_html = str(homepage_soup)
            gs_result = await _try_google_sheets(homepage_html, client, final_url)
            if gs_result and gs_result.adhan_count() > best_count:
                best_count = gs_result.adhan_count()
                best = gs_result

        # Masjidal direct API detection
        if not (best and best.is_complete()):
            today = date.today()
            homepage_html = str(homepage_soup)
            masjidal_result = await _try_masjidal_direct(homepage_html, client, today)
            if masjidal_result and masjidal_result.adhan_count() > best_count:
                best_count = masjidal_result.adhan_count()
                best = masjidal_result

        if best and best.adhan_count() >= 3:
            best.source = best.source or "mosque_website_html"
            best.confidence = "high" if best.is_complete() else "medium"
            best.tier = 2
            logger.info(f"    Tier 2: {best.adhan_count()} adhans, "
                        f"{best.iqama_count()} iqamas from {best.source_url}")
            return best

    return None


# ---------------------------------------------------------------------------
# Tier 2b — Facebook page scraping
# ---------------------------------------------------------------------------

def _facebook_mobile_url(url: str) -> Optional[str]:
    """Convert any facebook.com URL to mbasic.facebook.com for plain-HTML access."""
    import re
    m = re.search(r'facebook\.com/(.+)', url)
    if not m:
        return None
    path = m.group(1).rstrip("/")
    return f"https://mbasic.facebook.com/{path}"


async def tier2_facebook(mosque: MosqueRecord) -> Optional[PrayerTimes]:
    """
    Scrape a Facebook page for prayer times.
    Uses mbasic.facebook.com (plain HTML, no JS required) first.
    Looks in About section text and recent posts for prayer time patterns.
    """
    url = mosque.website or ""
    if "facebook.com" not in url.lower():
        return None

    mobile_url = _facebook_mobile_url(url)
    if not mobile_url:
        return None

    pages_to_try = [
        mobile_url,
        mobile_url.rstrip("/") + "/about",
    ]

    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                  headers={"User-Agent": (
                                      "Mozilla/5.0 (Linux; Android 10) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/120.0.0.0 Mobile Safari/537.36"
                                  )}) as client:
        for page_url in pages_to_try:
            parsed = await _fetch_soup(page_url, client)
            if not parsed:
                continue
            soup, _ = parsed
            full_text = soup.get_text(" ", strip=True)

            # Try structured extraction first
            result = _extract_from_soup(soup)
            if result and result.adhan_count() >= 3:
                result.source = "mosque_website_facebook"
                result.confidence = "medium"
                result.tier = 2
                result.source_url = page_url
                logger.info(f"    Tier 2 (FB structured): {result.adhan_count()} adhans, "
                            f"{result.iqama_count()} iqamas")
                return result

            # Fallback: regex scan of raw text for prayer-time lines
            result = _extract_from_text(full_text)
            if result and result.adhan_count() >= 3:
                result.source = "mosque_website_facebook"
                result.confidence = "medium"
                result.tier = 2
                result.source_url = page_url
                logger.info(f"    Tier 2 (FB text): {result.adhan_count()} adhans, "
                            f"{result.iqama_count()} iqamas")
                return result

        # Also scan recent posts on the timeline — prayer times are often posted weekly
        try:
            posts_parsed = await _fetch_soup(mobile_url, client)
            if posts_parsed:
                posts_soup, _ = posts_parsed
                # mbasic posts are in <div id="recent"> or article/div with story content
                all_text_blocks = []
                for el in posts_soup.find_all(["article", "div"], id=re.compile(r"recent|posts|feed", re.I)):
                    all_text_blocks.append(el.get_text("\n", strip=True))
                # Also grab all story-body text elements
                for el in posts_soup.find_all("div", attrs={"data-ft": True}):
                    all_text_blocks.append(el.get_text("\n", strip=True))

                combined = "\n".join(all_text_blocks)
                if combined:
                    result = _extract_from_text(combined)
                    if result and result.adhan_count() >= 3:
                        result.source = "mosque_website_facebook"
                        result.confidence = "medium"
                        result.tier = 2
                        result.source_url = mobile_url + " (posts)"
                        logger.info(f"    Tier 2 (FB posts): {result.adhan_count()} adhans, "
                                    f"{result.iqama_count()} iqamas")
                        return result
        except Exception as e:
            logger.debug(f"    FB posts scan error: {e}")

    return None


def _extract_from_text(text: str) -> Optional[PrayerTimes]:
    """
    Regex scan of a plain-text blob for prayer-time lines.
    Handles formats like:
      Fajr  5:30  6:00
      Dhuhr: 1:15 PM / 1:30 PM
      Asr – 4:45
    """
    pt = PrayerTimes()
    found = 0
    text_lower = text.lower()

    for prayer, aliases in [
        ("fajr",    ["fajr", "fajir", "subh"]),
        ("dhuhr",   ["dhuhr", "zuhr", "zohr", "duhr"]),
        ("asr",     ["asr", "asar"]),
        ("maghrib", ["maghrib", "magrib", "sunset"]),
        ("isha",    ["isha", "esha", "ishaa", "isha'"]),
    ]:
        for alias in aliases:
            # Find the alias and grab up to 2 time tokens following it on the same line
            pattern = re.compile(
                rf'{alias}[^\n]{{0,60}}?(\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm)?)'
                rf'(?:[^\n]{{0,30}}?(\d{{1,2}}:\d{{2}}\s*(?:AM|PM|am|pm)?))?',
                re.IGNORECASE,
            )
            m = pattern.search(text)
            if m:
                t1 = normalize_time(m.group(1), prayer)
                t2 = normalize_time(m.group(2), prayer) if m.group(2) else None
                if t1:
                    setattr(pt, f"{prayer}_adhan", t1)
                    found += 1
                    if t2 and t2 != t1:
                        setattr(pt, f"{prayer}_iqama", t2)
                break  # found this prayer, move to next

    return pt if found >= 3 else None


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


# ---------------------------------------------------------------------------
# Network API interception helpers (used by Tier 3)
# ---------------------------------------------------------------------------

# URL substrings that identify prayer time JSON API calls we want to capture
_PRAYER_API_PATTERNS = [
    "api.masjidbox.com",
    "timing.athanplus.com",
    "api.aladhan.com",
    "prayertimes.app",
    "salahmate.com/api",
    "muslimpro.com/api",
    "masjidal.com/api",
    "api.masjidal.com",
    "athan.pro/api",
    "masjidnow.com/api",
    "api.masjidnow.com",
    "salahtime.net/api",
    "prayerboard.net/api",
]


def _parse_masjidbox_response(data: dict, target_date: date) -> Optional[PrayerTimes]:
    """Parse MasjidBox widget API response into PrayerTimes."""
    try:
        widget = data.get("widget") or data
        # The API returns a list of days under "widget.days" or top-level "days"
        days = widget.get("days") or data.get("days") or []
        if not days:
            # Some endpoints return a single day directly
            days = [widget]

        date_str = target_date.strftime("%Y-%m-%d")
        day_data = None
        for d in days:
            if d.get("date", "").startswith(date_str):
                day_data = d
                break
        if day_data is None and days:
            day_data = days[0]  # fallback: use first available day

        if not day_data:
            return None

        pt = PrayerTimes()
        # MasjidBox field names vary; try both camelCase and snake_case
        mapping = {
            "fajr":    ["fajr",    "Fajr"],
            "dhuhr":   ["dhuhr",   "Dhuhr",   "zuhr",   "Zuhr"],
            "asr":     ["asr",     "Asr"],
            "maghrib": ["maghrib", "Maghrib"],
            "isha":    ["isha",    "Isha"],
        }
        found = 0
        for prayer, keys in mapping.items():
            for key in keys:
                entry = day_data.get(key)
                if not entry:
                    continue
                # Entry can be a dict {adhan, iqama} or a plain time string
                if isinstance(entry, dict):
                    adhan = normalize_time(entry.get("adhan") or entry.get("time"), prayer)
                    iqama = normalize_time(entry.get("iqama") or entry.get("iqamah"), prayer)
                elif isinstance(entry, str):
                    adhan = normalize_time(entry, prayer)
                    iqama = None
                else:
                    continue
                if adhan:
                    setattr(pt, f"{prayer}_adhan", adhan)
                    found += 1
                if iqama:
                    setattr(pt, f"{prayer}_iqama", iqama)
                break

        if found >= 3:
            pt.source = "masjidbox_api"
            pt.confidence = "high"
            pt.tier = 3
            return pt
    except Exception as e:
        logger.debug(f"    MasjidBox parse error: {e}")
    return None


def _parse_athanplus_response(data: dict, target_date: date) -> Optional[PrayerTimes]:
    """Parse AthanPlus timing API response into PrayerTimes."""
    try:
        # AthanPlus returns {data: [{date, fajr, sunrise, dhuhr, asr, maghrib, isha, ...}]}
        entries = data.get("data") or (data if isinstance(data, list) else [data])
        if not entries:
            return None

        date_str = target_date.strftime("%Y-%m-%d")
        day_data = None
        for entry in entries:
            if str(entry.get("date", "")).startswith(date_str):
                day_data = entry
                break
        if day_data is None:
            day_data = entries[0]

        pt = PrayerTimes()
        found = 0
        for prayer in PRAYER_NAMES:
            adhan_raw = day_data.get(prayer) or day_data.get(prayer.capitalize())
            iqama_raw = day_data.get(f"{prayer}_iqama") or day_data.get(f"{prayer}Iqama")
            adhan = normalize_time(adhan_raw, prayer) if adhan_raw else None
            iqama = normalize_time(iqama_raw, prayer) if iqama_raw else None
            if adhan:
                setattr(pt, f"{prayer}_adhan", adhan)
                found += 1
            if iqama:
                setattr(pt, f"{prayer}_iqama", iqama)

        if found >= 3:
            pt.source = "athanplus_api"
            pt.confidence = "high"
            pt.tier = 3
            return pt
    except Exception as e:
        logger.debug(f"    AthanPlus parse error: {e}")
    return None


def _parse_intercepted_response(url: str, body: str, target_date: date) -> Optional[PrayerTimes]:
    """Dispatch intercepted network response to the right parser."""
    try:
        data = json.loads(body)
    except Exception:
        return None

    if "masjidbox.com" in url:
        return _parse_masjidbox_response(data, target_date)
    if "athanplus.com" in url:
        return _parse_athanplus_response(data, target_date)
    # Generic fallback: try both parsers
    for parser in [_parse_masjidbox_response, _parse_athanplus_response]:
        result = parser(data, target_date)
        if result:
            return result
    return None


async def tier3_playwright(mosque: MosqueRecord, target_date: Optional[date] = None) -> Optional[PrayerTimes]:
    """Render JS-heavy mosque pages with Playwright, intercepting prayer API calls."""
    if not mosque.website:
        return None

    if target_date is None:
        target_date = date.today()

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

            # Capture prayer API JSON responses during page load
            intercepted_result: list[PrayerTimes] = []

            async def _on_response(response):
                if intercepted_result:
                    return  # already got one
                resp_url = response.url
                if not any(pat in resp_url for pat in _PRAYER_API_PATTERNS):
                    return
                try:
                    body = await response.text()
                    parsed = _parse_intercepted_response(resp_url, body, target_date)
                    if parsed and parsed.adhan_count() >= 3:
                        intercepted_result.append(parsed)
                        logger.info(f"    Tier 3 API intercept ({resp_url[:60]}): "
                                    f"{parsed.adhan_count()} adhans")
                except Exception:
                    pass

            page.on("response", _on_response)

            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
            except Exception:
                try:
                    await page.goto(url, wait_until="load", timeout=20000)
                except Exception:
                    await page.close()
                    return None

            # If we captured a complete result via API interception, return it immediately
            if intercepted_result:
                api_result = intercepted_result[0]
                api_result.source_url = url
                await page.close()
                return api_result

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
                    # Also check for API interception on sub-pages
                    if intercepted_result:
                        api_result = intercepted_result[0]
                        api_result.source_url = sub_url
                        await page.close()
                        return api_result
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
    # The praytimes library sometimes inherits wrong defaults from other methods
    # (e.g. Jafari's maghrib:4°, midnight:'Jafari').  Explicitly enforce ISNA values:
    #   fajr 15°, isha 15°, maghrib at sunset (0 min), standard midnight.
    pt.adjust({"maghrib": "0 min", "midnight": "Standard", "fajr": 15, "isha": 15})
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
    # Track the best result that passed validation at each tier — used as fallback
    # if a later tier returns bad data that corrupts the final result.
    last_valid_result: Optional[PrayerTimes] = None
    last_valid_tier: int = 0

    def _accept(candidate: Optional[PrayerTimes], tier: int) -> bool:
        """Accept candidate if it improves adhan count AND the present times look valid.
        For tiers 2-4 (real data), partial results (3+ adhans) are accepted even without
        all 5 prayers — Tier 5 gap-filling will supply the missing ones afterward.
        """
        nonlocal result, tier_reached, last_valid_result, last_valid_tier
        if not candidate or candidate.adhan_count() <= (result.adhan_count() if result else 0):
            return False

        # Partial real-data acceptance (tiers 2-4): require only 3+ valid adhans
        if tier in (2, 3, 4) and candidate.adhan_count() >= 3:
            # Validate only the present adhans (ranges + ordering)
            partial_ok = True
            present = [(p, getattr(candidate, f"{p}_adhan"))
                       for p in PRAYER_NAMES if getattr(candidate, f"{p}_adhan")]
            for p, t in present:
                lo, hi = PRAYER_TIME_RANGES[p]
                if not (lo <= t <= hi):
                    partial_ok = False
                    logger.debug(f"  Tier {tier} {p} adhan {t} outside range — skipping")
                    break
            if partial_ok:
                result = candidate
                tier_reached = tier
                last_valid_result = candidate
                last_valid_tier = tier
                return True

        ok, reason = validate_prayer_times(candidate)
        if not ok:
            logger.debug(f"  Tier {tier} result invalid ({reason}), skipping")
            return False
        result = candidate
        tier_reached = tier
        last_valid_result = candidate
        last_valid_tier = tier
        return True

    # Tier 1 — IslamicFinder (only for mosques without a website)
    if not mosque.website:
        try:
            t1 = await tier1_islamicfinder(mosque)
            _accept(t1, 1)
        except Exception as e:
            logger.info(f"  Tier 1 (IF) exception: {e}")

    # Tier 1b — Aladhan mosque search (for no-website mosques, tries mosque-specific data)
    if not mosque.website and not (result and result.is_complete()):
        try:
            t1b = await tier1_aladhan(mosque)
            _accept(t1b, 1)
        except Exception as e:
            logger.info(f"  Tier 1b (Aladhan) exception: {e}")

    # Tier 2 — Facebook pages get special handling
    if not (result and result.is_complete()) and mosque.website:
        if "facebook.com" in (mosque.website or "").lower():
            try:
                t2fb = await tier2_facebook(mosque)
                _accept(t2fb, 2)
            except Exception as e:
                logger.info(f"  Tier 2 (FB) exception: {e}")

    # Tier 2 — Static HTML for all non-Facebook websites
    if not (result and result.is_complete()) and mosque.website and \
            "facebook.com" not in (mosque.website or "").lower():
        try:
            t2 = await tier2_static_html(mosque)
            _accept(t2, 2)
        except Exception as e:
            logger.info(f"  Tier 2 exception: {e}")

    # Tier 3 — Playwright (JS-heavy sites, including Facebook fallback)
    if not (result and result.is_complete()) and mosque.website:
        try:
            t3 = await tier3_playwright(mosque, target_date)
            _accept(t3, 3)
        except Exception as e:
            logger.info(f"  Tier 3 exception: {e}")

    # Tier 4
    if not (result and result.is_complete()):
        try:
            t4 = await tier4_vision_and_pdf(mosque)
            _accept(t4, 4)
        except Exception as e:
            logger.info(f"  Tier 4 exception: {e}")

    # Tier 5 — fills gaps; tier_reached only set to 5 when it's the primary source
    try:
        t5 = tier5_calculated(mosque, target_date)
        if result is None:
            result = t5
            tier_reached = 5
        else:
            # Fill any missing adhan/iqama from Tier 5
            for p in PRAYER_NAMES:
                if not getattr(result, f"{p}_adhan"):
                    setattr(result, f"{p}_adhan", getattr(t5, f"{p}_adhan"))
                if not getattr(result, f"{p}_iqama"):
                    setattr(result, f"{p}_iqama", getattr(t5, f"{p}_iqama"))
            if not result.sunrise:
                result.sunrise = t5.sunrise
            # Only move tier_reached to 5 if we had nothing real before
            if tier_reached == 0:
                tier_reached = 5
    except Exception as e:
        if result is None:
            return False, tier_reached, f"Tier 5 failed: {e}"

    if not result:
        return False, tier_reached, "All tiers failed"

    # Final validation — filling Tier 5 gaps might create ordering issues
    # (e.g. real iqama earlier than Tier 5's adhan). Use last_valid_result as fallback.
    is_valid, reason = validate_prayer_times(result)
    if not is_valid:
        if last_valid_result:
            logger.warning(f"  Final validation failed ({reason}), "
                           f"reverting to last valid result (tier {last_valid_tier})")
            # Re-fill gaps from Tier 5 into the last_valid_result
            try:
                t5 = tier5_calculated(mosque, target_date)
                for p in PRAYER_NAMES:
                    if not getattr(last_valid_result, f"{p}_adhan"):
                        setattr(last_valid_result, f"{p}_adhan", getattr(t5, f"{p}_adhan"))
                    if not getattr(last_valid_result, f"{p}_iqama"):
                        setattr(last_valid_result, f"{p}_iqama", getattr(t5, f"{p}_iqama"))
                if not last_valid_result.sunrise:
                    last_valid_result.sunrise = t5.sunrise
            except Exception:
                pass
            result = last_valid_result
            tier_reached = last_valid_tier
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
