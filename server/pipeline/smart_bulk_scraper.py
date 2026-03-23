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

# Build sync DB URL from env vars directly
_db_url = os.environ.get("DATABASE_URL", "")
if not _db_url:
    _db_url = settings.database_url
# Always patch in POSTGRES_PASSWORD if available (docker-compose env bug workaround)
_pg_pass = os.environ.get("POSTGRES_PASSWORD", "")
_pg_user = os.environ.get("POSTGRES_USER", "cap")
_pg_db = os.environ.get("POSTGRES_DB", "catchaprayer")
if _pg_pass:
    DB_URL = f"postgresql+psycopg2://{_pg_user}:{_pg_pass}@db:5432/{_pg_db}"
else:
    DB_URL = _db_url.replace("+asyncpg", "+psycopg2")
    if "psycopg2" not in DB_URL:
        DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg2://")

# ---------------------------------------------------------------------------
# Prayer time extraction patterns (improved)
# ---------------------------------------------------------------------------

PRAYER_NAMES = {
    "fajr": "fajr", "fajar": "fajr", "subh": "fajr", "dawn": "fajr", "fajir": "fajr",
    "sunrise": "sunrise", "shuruq": "sunrise", "ishraq": "sunrise", "shorooq": "sunrise",
    "dhuhr": "dhuhr", "zuhr": "dhuhr", "dhuhur": "dhuhr", "noon": "dhuhr",
    "duhr": "dhuhr", "zohr": "dhuhr", "thuhr": "dhuhr",
    "zohrain": "dhuhr",  # Shia: combined Dhuhr+Asr name
    "zohr/asr": "dhuhr", "zuhr/asr": "dhuhr", "dhuhr/asr": "dhuhr",  # Shia combined
    "asr": "asr", "asar": "asr", "'asr": "asr",
    "maghrib": "maghrib", "magrib": "maghrib", "sunset": "maghrib", "iftar": "maghrib",
    "maghreb": "maghrib", "magreb": "maghrib",
    "maghriban": "maghrib",  # Shia: combined Maghrib+Isha name
    "magrib/isha": "maghrib", "maghrib/isha": "maghrib",  # Shia combined
    "isha": "isha", "ishaa": "isha", "esha": "isha", "'isha": "isha", "isha'a": "isha",
}

JUMUAH_NAMES = {
    "jumuah", "jummah", "jumma", "jumu'ah", "friday", "khutbah", "khutba",
    "jumua'ah", "jum'ah", "jumuaa", "jumah",
}

# Time patterns: 12:30, 12:30 PM, 12:30PM, 1:30pm, 1:30 p.m.
TIME_RE = re.compile(r'\b(\d{1,2}):(\d{2})\s*(am|pm|AM|PM|a\.m\.|p\.m\.)?\b')

# Iqama offset: "+15", "20 min after athan", "30 mins after adhan", "X minutes after"
OFFSET_RE = re.compile(
    r'(?:\+\s*)?(\d{1,3})\s*(?:min(?:ute)?s?\s*(?:after|from)?\s*(?:ath[ae]n|adh[ae]n)?|min\b)',
    re.IGNORECASE
)

# Direct "X min after athan" pattern (no + prefix needed)
RELATIVE_IQAMA_RE = re.compile(
    r'(\d{1,3})\s*(?:min(?:ute)?s?)\s+(?:after|from|past)\s+(?:ath[ae]n|adh[ae]n|azan)',
    re.IGNORECASE
)


# Date patterns for monthly tables
DATE_RE = re.compile(r'\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b')
MONTH_NAMES_RE = re.compile(
    r'\b(january|february|march|april|may|june|july|august|september|october|november|december'
    r'|muharram|safar|rabi.?ul.?awwal|rabi.?ul.?thani|jumada.?ul.?ula|jumada.?ul.?thani'
    r'|rajab|sha.?ban|ramadan|shawwal|dhul.?qa.?dah|dhul.?hijjah)\b',
    re.IGNORECASE
)


def extract_monthly_schedule(text_content: str) -> list[dict]:
    """
    Detect monthly prayer schedule tables.
    Returns list of {date: "YYYY-MM-DD", adhan: {...}} for each day found.
    """
    text_content = text_content.replace('\t', '  ')
    text_content = re.sub(r'\*{1,6}', '', text_content)
    text_content = re.sub(r'\b(\d{1,2})\.(\d{2})\s*(am|pm|AM|PM)', r'\1:\2 \3', text_content)
    lines = text_content.split('\n')
    monthly = []

    for line in lines:
        date_match = DATE_RE.search(line)
        if not date_match:
            continue

        times = TIME_RE.findall(line)
        if len(times) < 3:
            continue

        try:
            d1, d2, d3 = date_match.groups()
            if len(d3) == 4:
                year = int(d3)
                if int(d1) > 12:
                    day, month = int(d1), int(d2)
                else:
                    month, day = int(d1), int(d2)
            elif len(d3) == 2:
                year = 2000 + int(d3)
                month, day = int(d1), int(d2)
            else:
                continue

            from datetime import date as date_cls
            try:
                schedule_date = date_cls(year, month, day)
            except ValueError:
                continue

            prayer_order = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
            row = {"date": schedule_date.isoformat(), "adhan": {}}

            for j, (h, m, ampm) in enumerate(times[:6]):
                if j < len(prayer_order):
                    t = _normalize_time(h, m, ampm, prayer=prayer_order[j])
                    if t:
                        row["adhan"][prayer_order[j]] = t

            if len(row["adhan"]) >= 3:
                monthly.append(row)

        except (ValueError, IndexError):
            continue

    return monthly


# Additional label variations for iqama/adhan columns
IQAMA_LABELS = {"iqama", "iqamah", "jamaat", "jammat", "jamat", "congregation", "2nd azan", "jama'at", "iqamaat"}
ADHAN_LABELS = {"azan", "athan", "adhan", "begins", "beginning", "start", "prayer time", "salah", "prayer"}


def extract_times_from_text(text_content: str) -> dict:
    """
    Extract prayer times from rendered page text.
    Uses TWO strategies:
    1. Prayer-name-based: find prayer names and associated times (original)
    2. Cluster-based: find ascending time clusters and map by position (new)
    Returns dict with prayer names as keys and time strings as values.
    """
    # Heavy normalization — strip all formatting
    text_content = text_content.replace('\t', '  ')
    text_content = re.sub(r'\*{1,6}', '', text_content)                    # markdown bold/italic
    text_content = re.sub(r'^#{1,6}\s*', '', text_content, flags=re.MULTILINE)  # markdown headers
    text_content = re.sub(r'\|[\s\-]+\|', '', text_content)                # markdown table separators
    text_content = re.sub(r'^\||\|$', '', text_content, flags=re.MULTILINE)  # table pipes at line edges
    text_content = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text_content)    # markdown italic/underline
    text_content = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', text_content)  # markdown links
    text_content = re.sub(r'!\[.*?\]\(.*?\)', '', text_content)            # markdown images
    text_content = re.sub(r'\b(\d{1,2})\.(\d{2})\s*(am|pm|AM|PM)', r'\1:\2 \3', text_content)  # period times
    lines = text_content.split('\n')
    # Remove empty lines and trim
    lines = [l.strip() for l in lines if l.strip()]
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
                times = TIME_RE.findall(line)
                for h, m, ampm in times:
                    t = _normalize_time(h, m, ampm)
                    if t and 11 <= int(t.split(":")[0]) <= 15:  # Jumuah is around noon
                        results["jumuah"].append(t)
            continue

        # Found a prayer name — look for times on THIS LINE first
        times = TIME_RE.findall(line)
        times_from_next = False
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        next_lower = next_line.lower().strip()

        if not times and next_line:
            times = TIME_RE.findall(next_line)
            times_from_next = True

        # Check iqama context on both this line and the line where times were found
        iqama_words = ["iqama", "iqamah", "iqamaat", "congregation"]
        is_iqama_line = any(w in line_lower for w in iqama_words)
        is_next_iqama = any(w in next_lower for w in iqama_words) if times_from_next else False

        # Also scan the next 2-3 lines for iqama times when prayer name is alone
        # Pattern: "fajr\nIqamah: 6:18 am\nsunrise\nzuhr\nIqamah: 1:30 pm"
        if not times and not is_iqama_line:
            # Look ahead up to 3 lines for a time
            for look in range(1, min(4, len(lines) - i)):
                ahead = lines[i + look]
                ahead_lower = ahead.lower().strip()
                ahead_times = TIME_RE.findall(ahead)
                if ahead_times:
                    times = ahead_times
                    is_next_iqama = any(w in ahead_lower for w in iqama_words)
                    times_from_next = True
                    break
                # Stop lookahead if we hit another prayer name
                if any(p in ahead_lower for p in PRAYER_NAMES):
                    break

        effective_iqama = is_iqama_line or is_next_iqama

        if len(times) >= 2 and not effective_iqama:
            # Two times = adhan + iqama
            results["adhan"][found_prayer] = _normalize_time(*times[0], prayer=found_prayer)
            results["iqama"][found_prayer] = _normalize_time(*times[1], prayer=found_prayer)
        elif len(times) >= 1 and effective_iqama:
            # Time on an iqama-labeled line → store as iqama
            results["iqama"][found_prayer] = _normalize_time(*times[0], prayer=found_prayer)
        elif len(times) == 1 and not effective_iqama:
            results["adhan"][found_prayer] = _normalize_time(*times[0], prayer=found_prayer)
            # Check for iqama offset
            search_text = line + " " + next_line
            rel_match = RELATIVE_IQAMA_RE.search(search_text)
            if rel_match:
                results["iqama"][found_prayer] = f"+{rel_match.group(1)}"
            else:
                offsets = OFFSET_RE.findall(search_text)
                if offsets:
                    results["iqama"][found_prayer] = f"+{offsets[0]}"
        elif len(times) == 0:
            # No time found at all — check for relative iqama
            rel_match = RELATIVE_IQAMA_RE.search(line + " " + next_line)
            if rel_match and found_prayer in results.get("adhan", {}):
                results["iqama"][found_prayer] = f"+{rel_match.group(1)}"

    # Strategy 2: Look for a grid/table pattern (all times in a block)
    if len(results["adhan"]) < 3:
        _extract_from_grid(lines, results)

    # Strategy 3: Cluster-based — find ascending time sequences regardless of format
    if len(results["adhan"]) < 3:
        _extract_from_cluster(lines, results)

    return results


def _extract_from_cluster(lines: list[str], results: dict):
    """
    Find clusters of ascending times that look like a prayer schedule.
    Works regardless of formatting — tables, lists, headings, plain text.
    """
    from pipeline.validation import hhmm_to_minutes

    # Collect ALL times with their line positions
    all_times = []
    for i, line in enumerate(lines):
        for h, m, ampm in TIME_RE.findall(line):
            t = _normalize_time(h, m, ampm)
            if t:
                mins = hhmm_to_minutes(t)
                if mins and 120 <= mins <= 1439:  # 2AM to 11:59PM
                    all_times.append({"line": i, "time": t, "mins": mins, "raw": f"{h}:{m} {ampm}".strip()})

    if len(all_times) < 5:
        return

    # Find the best ascending sequence of 5-6 times (prayer schedule)
    best_seq = []
    for start in range(len(all_times)):
        seq = [all_times[start]]
        for j in range(start + 1, min(start + 30, len(all_times))):
            candidate = all_times[j]
            # Must be ascending and within reasonable line distance
            if candidate["mins"] > seq[-1]["mins"] and candidate["line"] - seq[0]["line"] <= 30:
                seq.append(candidate)
            if len(seq) >= 6:
                break
        if len(seq) >= 5 and len(seq) > len(best_seq):
            best_seq = seq

    if len(best_seq) < 5:
        return

    # Map to prayers by time range (Islamic knowledge)
    prayer_order = []
    for t in best_seq:
        mins = t["mins"]
        if mins < 480 and "fajr" not in [p[0] for p in prayer_order]:          # before 8 AM
            prayer_order.append(("fajr", t))
        elif 480 <= mins < 660 and "sunrise" not in [p[0] for p in prayer_order]:  # 8-11 AM
            prayer_order.append(("sunrise", t))
        elif 660 <= mins < 960 and "dhuhr" not in [p[0] for p in prayer_order]:   # 11 AM - 4 PM
            prayer_order.append(("dhuhr", t))
        elif 780 <= mins < 1140 and "asr" not in [p[0] for p in prayer_order]:    # 1 - 7 PM
            prayer_order.append(("asr", t))
        elif 960 <= mins < 1320 and "maghrib" not in [p[0] for p in prayer_order]: # 4 - 10 PM
            prayer_order.append(("maghrib", t))
        elif mins >= 1020 and "isha" not in [p[0] for p in prayer_order]:          # after 5 PM
            prayer_order.append(("isha", t))

    for prayer, t in prayer_order:
        if prayer not in results["adhan"] and prayer != "sunrise":
            results["adhan"][prayer] = t["time"]


def _extract_from_grid(lines: list[str], results: dict):
    """Look for a dense block of 5-6 times that might be a prayer schedule."""
    from pipeline.validation import hhmm_to_minutes

    # Strategy A: Single line with 5+ times (horizontal table row)
    for i, line in enumerate(lines):
        times = TIME_RE.findall(line)
        if len(times) >= 5:
            prayer_order = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
            for j, (h, m, ampm) in enumerate(times[:6]):
                if j < len(prayer_order):
                    t = _normalize_time(h, m, ampm, prayer=prayer_order[j])
                    if t and prayer_order[j] not in results["adhan"]:
                        results["adhan"][prayer_order[j]] = t
            # Check next line for iqama times
            if i + 1 < len(lines):
                iqama_times = TIME_RE.findall(lines[i + 1])
                if len(iqama_times) >= 4:
                    iqama_order = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
                    for j, (h, m, ampm) in enumerate(iqama_times[:5]):
                        if j < len(iqama_order):
                            t = _normalize_time(h, m, ampm, prayer=iqama_order[j])
                            if t:
                                results["iqama"][iqama_order[j]] = t
            return

    # Strategy B: Look for ascending time sequence across consecutive lines
    # (vertical table — each line has 1-2 times, times go from early to late)
    all_times = []
    for i, line in enumerate(lines):
        times = TIME_RE.findall(line)
        for h, m, ampm in times:
            t = _normalize_time(h, m, ampm)
            if t:
                mins = hhmm_to_minutes(t)
                if mins and 120 <= mins <= 1440:  # 2AM to midnight
                    all_times.append((i, t, mins))

    # Find the longest ascending subsequence of 5+ times
    if len(all_times) >= 5:
        best_seq = []
        for start in range(len(all_times)):
            seq = [all_times[start]]
            for j in range(start + 1, min(start + 20, len(all_times))):
                if all_times[j][2] > seq[-1][2] and all_times[j][0] - seq[-1][0] <= 3:
                    seq.append(all_times[j])
            if len(seq) >= 5 and len(seq) > len(best_seq):
                best_seq = seq

        if len(best_seq) >= 5:
            prayer_order = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
            for j, (line_idx, t, mins) in enumerate(best_seq[:6]):
                if j < len(prayer_order) and prayer_order[j] not in results["adhan"]:
                    results["adhan"][prayer_order[j]] = t


def _normalize_time(h: str, m: str, ampm: str | None, prayer: str | None = None) -> str | None:
    """Normalize to 24h HH:MM format. Uses prayer context to infer AM/PM when missing."""
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
    elif hour <= 12 and prayer:
        # No AM/PM — infer from prayer type
        # Fajr/sunrise: always AM (hour 3-8 stays as-is)
        # Dhuhr/Asr: PM if hour <= 7 (1:30 → 13:30, 5:00 → 17:00)
        # Maghrib/Isha: PM if hour <= 10 (7:30 → 19:30, 9:00 → 21:00)
        if prayer in ("dhuhr", "asr") and hour <= 7:
            hour += 12
        elif prayer in ("maghrib", "isha") and hour <= 10:
            hour += 12

    if hour > 23:
        return None

    return f"{hour:02d}:{minute:02d}"


# Strict time ranges for US/Canada (local time)
# These are generous bounds covering all seasons and latitudes
VALID_RANGES = {
    "fajr":    (2, 30,  7, 30),   # 2:30 AM - 7:30 AM
    "sunrise": (4, 30,  8, 30),   # 4:30 AM - 8:30 AM
    "dhuhr":   (11, 0,  14, 30),  # 11:00 AM - 2:30 PM
    "asr":     (13, 0,  19, 0),   # 1:00 PM - 7:00 PM
    "maghrib": (16, 0,  21, 30),  # 4:00 PM - 9:30 PM
    "isha":    (18, 0,  23, 59),  # 6:00 PM - 11:59 PM
}


def _time_in_range(time_str: str, prayer: str) -> bool:
    """Check if a time string is within valid range for a prayer."""
    if not time_str or ":" not in time_str or time_str.startswith("+"):
        return True  # offsets and empty values pass
    try:
        h, m = int(time_str.split(":")[0]), int(time_str.split(":")[1])
    except (ValueError, IndexError):
        return False
    bounds = VALID_RANGES.get(prayer)
    if not bounds:
        return True
    min_h, min_m, max_h, max_m = bounds
    t = h * 60 + m
    return (min_h * 60 + min_m) <= t <= (max_h * 60 + max_m)


def validate_schedule(data: dict) -> bool:
    """Check if extracted data looks like a real prayer schedule."""
    adhan = data.get("adhan", {})
    if len(adhan) < 3:
        return False

    # Every time must be within its valid range
    for prayer, t in adhan.items():
        if not _time_in_range(t, prayer):
            log.debug(f"  Rejected: {prayer} adhan={t} out of range")
            return False

    for prayer, t in data.get("iqama", {}).items():
        if not _time_in_range(t, prayer):
            log.debug(f"  Rejected: {prayer} iqama={t} out of range")
            return False

    # Order check: fajr < dhuhr < asr < maghrib < isha
    order = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
    prev_mins = 0
    for prayer in order:
        t = adhan.get(prayer)
        if not t or ":" not in t or t.startswith("+"):
            continue
        h, m = int(t.split(":")[0]), int(t.split(":")[1])
        mins = h * 60 + m
        if mins <= prev_mins and prev_mins > 0:
            log.debug(f"  Rejected: {prayer}={t} not after previous prayer")
            return False
        prev_mins = mins

    return True


def sanitize_schedule(data: dict) -> dict:
    """Remove any individual times that are outside valid ranges."""
    for section in ("adhan", "iqama"):
        bad_keys = []
        for prayer, t in data.get(section, {}).items():
            if not _time_in_range(t, prayer):
                bad_keys.append(prayer)
        for k in bad_keys:
            del data[section][k]
    return data


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
    "/prayers-mosques", "/masjid-services", "/salah",
    "/prayer-times-and-iqama", "/iqamah-times",
    "/prayer-timings", "/salah-schedule", "/namaz-times",
    "/iqamah", "/adhan-times", "/daily-schedule",
    "/prayer-timing", "/namaz", "/salaat-times",
    "/prayer-times-iqamah-times", "/daily-prayer-times",
    # French (Quebec mosques)
    "/horaires-de-priere", "/horaires", "/prieres",
    # Non-standard
    "/prayer-schedule", "/salah-time", "/athan-iqamah",
]


async def _extract_from_praytimes_js(page) -> dict | None:
    """Detect PrayTimes.js library and extract times from it."""
    try:
        result = await page.evaluate("""() => {
            // Check if prayTimes object exists
            if (typeof prayTimes !== 'undefined' || typeof PrayTimes !== 'undefined') {
                var pt = typeof prayTimes !== 'undefined' ? prayTimes : new PrayTimes();
                var now = new Date();
                var times = pt.getTimes(now, [document._capLat || 0, document._capLng || 0], 'auto', 0, '24h');
                return times;
            }
            // Check for hardcoded coordinates in scripts
            var scripts = document.querySelectorAll('script');
            for (var s of scripts) {
                var text = s.textContent || '';
                var match = text.match(/getTimes\\s*\\([^,]+,\\s*\\[([\\d.-]+),\\s*([\\d.-]+)\\]/);
                if (match) {
                    return {_coords: [parseFloat(match[1]), parseFloat(match[2])]};
                }
                // Also check for method setting
                var method = text.match(/setMethod\\s*\\(['"](\\w+)['"]/);
                if (method) {
                    return {_method: method[1]};
                }
            }
            return null;
        }""")
        if result and "_coords" not in result:
            # Got actual prayer times from PrayTimes.js
            data = {"adhan": {}, "iqama": {}, "jumuah": []}
            prayer_map = {"fajr": "fajr", "sunrise": "sunrise", "dhuhr": "dhuhr",
                          "asr": "asr", "maghrib": "maghrib", "isha": "isha"}
            for key, canonical in prayer_map.items():
                if key in result and result[key]:
                    data["adhan"][canonical] = result[key]
            return data if len(data["adhan"]) >= 3 else None
    except Exception:
        pass
    return None


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
                # Allow mawaqit.net and themasjidapp.org links (trusted prayer platforms)
                trusted_externals = ["mawaqit.net", "themasjidapp.org"]
                if link_domain and link_domain != base_domain:
                    if not any(t in link_domain for t in trusted_externals):
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
    """Render websites with Playwright and extract prayer times.
    Uses 5 concurrent browser tabs for speed."""
    from playwright.async_api import async_playwright

    stats = {"attempted": 0, "success": 0, "no_data": 0, "error": 0}
    today = date.today()
    sem = asyncio.Semaphore(5)  # 5 concurrent tabs
    completed = [0]  # mutable counter for progress

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        async def scrape_one(w: dict):
            mosque_id = w["id"]
            url = w["website"]
            name = w["name"]
            async with sem:

            try:
                page = await context.new_page()
                log.info(f"[{i+1}/{len(websites)}] {name}: {url}")

                # Intercept network responses for AJAX prayer data
                ajax_texts = []
                async def capture_response(response):
                    try:
                        ct = response.headers.get("content-type", "")
                        if ("json" in ct or "text" in ct) and response.status == 200:
                            body = await response.text()
                            # Only capture responses that mention prayer keywords
                            if len(body) < 10000 and any(w in body.lower() for w in ["fajr", "dhuhr", "zuhr", "maghrib", "isha", "iqama"]):
                                ajax_texts.append(body)
                    except Exception:
                        pass
                page.on("response", capture_response)

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
                await page.wait_for_timeout(5000)

                # Get all visible text from homepage
                text_content = await page.inner_text("body")

                # Also get full HTML — some React/Firebase apps render to DOM
                # but innerText misses content in dynamic containers
                try:
                    html_content = await page.content()
                    # Extract text from HTML tags that might contain times
                    # (td, span, div with time-like content)
                    import re as _re
                    html_times = _re.findall(r'>(\d{1,2}:\d{2}\s*(?:am|pm|AM|PM)?)<', html_content)
                    if html_times and len(html_times) >= 3:
                        # Found times in HTML that innerText might have missed
                        text_content += "\n" + " ".join(html_times)
                except Exception:
                    pass

                # Append any AJAX responses that contained prayer data
                if ajax_texts:
                    log.info(f"  -> Captured {len(ajax_texts)} AJAX responses with prayer data")
                    text_content += "\n" + "\n".join(ajax_texts)

                # Spam/hijack detection — skip compromised domains
                spam_keywords = ["slot deposit", "casino", "gambling", "poker online",
                                 "togel", "judi online", "situs slot", "gacor"]
                text_lower_check = text_content[:2000].lower()
                if any(kw in text_lower_check for kw in spam_keywords):
                    log.info(f"  ! Domain hijacked (gambling spam)")
                    stats["error"] += 1
                    await page.close()
                    # Mark as dead in DB
                    with engine.begin() as conn:
                        conn.execute(text(
                            "UPDATE scraping_jobs SET website_alive = false, status = 'failed' WHERE mosque_id = :mid"
                        ), {"mid": mosque_id})
                    continue

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

                # Try PrayTimes.js detection before closing page
                pt_data = await _extract_from_praytimes_js(page)
                await page.close()

                if pt_data and validate_schedule(pt_data):
                    log.info(f"  ✓ PrayTimes.js detected: {len(pt_data['adhan'])} prayers")
                    if save:
                        _save_to_db(engine, mosque_id, pt_data, today, source="praytimes_js")
                    stats["success"] += 1
                    continue

                # Try monthly schedule first (saves multiple days at once)
                monthly = extract_monthly_schedule(text_content)
                if len(monthly) >= 5:
                    stats["success"] += 1
                    log.info(f"  ✓ Monthly schedule: {len(monthly)} days found")
                    if save:
                        for day_data in monthly:
                            from datetime import date as date_cls
                            day_date = date_cls.fromisoformat(day_data["date"])
                            day_full = {"adhan": day_data["adhan"], "iqama": day_data.get("iqama", {}), "jumuah": []}
                            _save_to_db(engine, mosque_id, day_full, day_date, source="playwright_scrape")
                        # Tag mosque as monthly publisher
                        with engine.begin() as conn:
                            conn.execute(text(
                                "UPDATE scraping_jobs SET scrape_method = 'monthly_schedule' WHERE mosque_id = :mid"
                            ), {"mid": mosque_id})
                    continue

                # Extract today's prayer times
                data = extract_times_from_text(text_content)

                # Sanitize: remove any times outside valid ranges
                data = sanitize_schedule(data)

                if validate_schedule(data):
                    stats["success"] += 1
                    log.info(f"  ✓ Found: {len(data['adhan'])} adhan, {len(data['iqama'])} iqama, {len(data['jumuah'])} jumuah")

                    if save:
                        _save_to_db(engine, mosque_id, data, today, source="playwright_scrape")
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

            completed[0] += 1
            if completed[0] % 50 == 0:
                rate = stats['success'] * 100 // max(stats['attempted'], 1)
                log.info(f"  --- Progress: {completed[0]}/{len(websites)} | {stats['success']} success ({rate}%)")

        # Run all sites concurrently (limited by semaphore)
        log.info(f"Scraping {len(websites)} websites with Playwright (5 concurrent tabs)")
        tasks = [scrape_one(w) for w in websites]
        await asyncio.gather(*tasks, return_exceptions=True)

        await browser.close()

    return stats




# ---------------------------------------------------------------------------
# Jina Reader scraping — lightweight, no Chromium needed
# ---------------------------------------------------------------------------

JINA_BASE = "https://r.jina.ai/"
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")  # Free tier: 1M tokens/month

# Prioritized paths — most common prayer page URLs first
JINA_PATHS = [
    "",  # homepage first
    "/prayer-times", "/prayer-time", "/prayers",
    "/iqama", "/salah-times", "/prayer-schedule",
    "/services/prayer-times", "/schedule",
    "/prayers-mosques", "/iqamah-times", "/salah",
    "/prayer-timings", "/iqamah", "/daily-schedule",
    "/prayer-timing", "/daily-prayer-times",
    "/horaires-de-priere", "/prayer-schedule",
]


async def scrape_with_jina(websites: list[dict], engine, save: bool = True) -> dict:
    """Scrape using Jina Reader — no Chromium, much lighter.
    Rate-limited to avoid 429s: 2 concurrent, 1s delay between requests."""
    stats = {"attempted": 0, "success": 0, "no_data": 0, "error": 0, "rate_limited": 0}
    today = date.today()
    sem = asyncio.Semaphore(2)  # Only 2 concurrent to avoid rate limits

    headers = {"Accept": "text/plain", "X-Return-Format": "text"}
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"

    async def scrape_one(w: dict) -> tuple[str, dict | None]:
        mosque_id, name, url = w["id"], w["name"], w["website"]
        base = url.rstrip("/")

        async with sem:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                for path in JINA_PATHS:
                    target = base + path
                    jina_url = JINA_BASE + target
                    try:
                        resp = await client.get(jina_url, headers=headers)

                        if resp.status_code == 429:
                            # Rate limited — wait and skip this site
                            stats["rate_limited"] += 1
                            await asyncio.sleep(5)
                            return mosque_id, None

                        if resp.status_code != 200:
                            continue

                        text = resp.text
                        if len(text) < 100:
                            continue

                        data = extract_times_from_text(text)
                        data = sanitize_schedule(data)

                        if validate_schedule(data):
                            log.info(f"  ✓ {name}: {len(data['adhan'])} adhan, {len(data['iqama'])} iqama via Jina ({path or '/'})")
                            return mosque_id, data
                    except Exception:
                        continue

                    # Delay between path attempts to avoid rate limits
                    await asyncio.sleep(0.5)

        return mosque_id, None

    log.info(f"Scraping {len(websites)} websites with Jina Reader (2 concurrent, rate-limited)")

    # Process one at a time with delay to respect rate limits
    for i, w in enumerate(websites):
        stats["attempted"] += 1
        mosque_id, data = await scrape_one(w)

        if data:
            stats["success"] += 1
            if save:
                _save_to_db(engine, mosque_id, data, today, source="jina_reader")
        else:
            stats["no_data"] += 1

        # Progress every 20
        if (i + 1) % 20 == 0 or i + 1 == len(websites):
            rate = stats['success'] * 100 // max(stats['attempted'], 1)
            log.info(f"  --- Jina progress: {i+1}/{len(websites)} — {stats['success']} success ({rate}%) [429s: {stats['rate_limited']}]")

        # Small delay between sites
        await asyncio.sleep(1)

    return stats


def _save_to_db(engine, mosque_id: str, data: dict, today: date, source: str = "playwright_scrape", lat: float = None):
    """Validate and save extracted prayer schedule to DB.
    Runs full Islamic logic validation before writing anything."""
    from pipeline.validation import validate_prayer_schedule, validate_jumuah

    # Convert from {adhan: {fajr: "05:30"}} to {fajr_adhan: "05:30"} for validation
    flat = {}
    for prayer, t in data.get("adhan", {}).items():
        col = {"fajr": "fajr_adhan", "dhuhr": "dhuhr_adhan", "asr": "asr_adhan",
               "maghrib": "maghrib_adhan", "isha": "isha_adhan", "sunrise": "sunrise"}.get(prayer)
        if col and t:
            flat[col] = t
    for prayer, t in data.get("iqama", {}).items():
        col = {"fajr": "fajr_iqama", "dhuhr": "dhuhr_iqama", "asr": "asr_iqama",
               "maghrib": "maghrib_iqama", "isha": "isha_iqama"}.get(prayer)
        if col and t:
            flat[col] = t

    # Run validation
    vr = validate_prayer_schedule(flat, lat=lat)

    # Log validation issues to DB
    if vr.issues:
        _log_validation_issues(engine, mosque_id, today, vr.issues)

    # If validation failed entirely, don't save — let daily_calculated fill the gap
    if not vr.valid:
        log.info(f"  ⚠ Validation failed: {vr.issues[0]['issue'] if vr.issues else 'unknown'}")
        return

    cleaned = vr.cleaned

    with engine.begin() as conn:
        values = {"mosque_id": mosque_id, "date": today}

        source_col_map = {
            "fajr_adhan": "fajr_adhan_source", "dhuhr_adhan": "dhuhr_adhan_source",
            "asr_adhan": "asr_adhan_source", "maghrib_adhan": "maghrib_adhan_source",
            "isha_adhan": "isha_adhan_source", "sunrise": "sunrise_source",
            "fajr_iqama": "fajr_iqama_source", "dhuhr_iqama": "dhuhr_iqama_source",
            "asr_iqama": "asr_iqama_source", "maghrib_iqama": "maghrib_iqama_source",
            "isha_iqama": "isha_iqama_source",
        }

        for col, val in cleaned.items():
            if val is not None and col in source_col_map:
                values[col] = val
                values[source_col_map[col]] = source

        if len(values) <= 2:
            return

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

        conn.execute(text("""
            UPDATE scraping_jobs
            SET status = 'success', scraped_at = now(), scrape_method = :method
            WHERE mosque_id = :mid
        """), {"mid": mosque_id, "method": source})

        # Validate and save jumuah
        jumuah_times = data.get("jumuah", [])
        if jumuah_times:
            jr = validate_jumuah(jumuah_times, cleaned.get("dhuhr_adhan"))
            if jr.issues:
                _log_validation_issues(engine, mosque_id, today, jr.issues)
            for i, jtime in enumerate(jr.cleaned.get("jumuah", [])[:3]):
                try:
                    conn.execute(text("""
                        INSERT INTO jumuah_sessions (id, mosque_id, prayer_start, session_number, source, valid_date)
                        VALUES (gen_random_uuid(), CAST(:mid AS uuid), :time, :num, :src, CURRENT_DATE)
                        ON CONFLICT DO NOTHING
                    """), {"mid": mosque_id, "time": jtime, "num": i + 1, "src": source})
                except Exception:
                    pass


def _log_validation_issues(engine, mosque_id: str, scrape_date: date, issues: list[dict]):
    """Log validation issues to scraping_validation_log table."""
    try:
        with engine.begin() as conn:
            for issue in issues:
                conn.execute(text("""
                    INSERT INTO scraping_validation_log
                        (mosque_id, scrape_date, field_name, scraped_value, expected_range, issue_description, action_taken)
                    VALUES (CAST(:mid AS uuid), :dt, :field, :val, :expected, :issue, :action)
                """), {
                    "mid": mosque_id, "dt": scrape_date,
                    "field": issue.get("field", ""),
                    "val": issue.get("value"),
                    "expected": issue.get("expected", ""),
                    "issue": issue.get("issue", ""),
                    "action": issue.get("action", ""),
                })
    except Exception as e:
        log.debug(f"Failed to log validation issue: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# Priority states for ordering (highest user density first)
HIGH_PRIORITY_STATES = "('NY','CA','TX','IL','NJ','FL','MI','PA','MD','VA','GA','OH','DC','ON','QC','BC','AB')"


def main():
    parser = argparse.ArgumentParser(description="Smart bulk scraper with Playwright + Jina")
    parser.add_argument("--check-alive", action="store_true", help="Phase 1: check which websites are alive")
    parser.add_argument("--scrape", action="store_true", help="Phase 2+3: Playwright render and extract")
    parser.add_argument("--jina", action="store_true", help="Scrape using Jina Reader (lighter, no Chromium)")
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

    if args.scrape or args.jina:
        limit = None if args.all else args.limit

        with engine.connect() as conn:
            # Get alive websites that don't have real data today
            # Prioritize high-population states first
            q = f"""
                SELECT m.id::text, m.name, m.website
                FROM mosques m
                JOIN scraping_jobs sj ON sj.mosque_id = m.id AND sj.website_alive = true
                WHERE m.is_active AND m.website IS NOT NULL
                  AND m.website NOT LIKE '%%facebook%%'
                  AND m.website NOT LIKE '%%instagram%%'
                  AND m.website NOT LIKE '%%youtube%%'
                  AND m.website NOT LIKE '%%yelp%%'
                  AND m.website NOT LIKE '%%x.com%%'
                  AND m.website NOT LIKE '%%twitter%%'
                  AND m.id NOT IN (
                      SELECT mosque_id FROM prayer_schedules
                      WHERE date = CURRENT_DATE AND fajr_adhan_source NOT IN ('calculated')
                  )
                ORDER BY
                    CASE WHEN m.state IN {HIGH_PRIORITY_STATES} THEN 0 ELSE 1 END,
                    m.state, random()
            """
            if limit:
                q += f" LIMIT {limit}"
            rows = conn.execute(text(q)).fetchall()
            websites = [{"id": r[0], "name": r[1], "website": r[2]} for r in rows]

        if args.jina:
            log.info(f"Scraping {len(websites)} websites with Jina Reader")
            stats = asyncio.run(scrape_with_jina(websites, engine, save=not args.no_save))
        else:
            log.info(f"Scraping {len(websites)} websites with Playwright")
            stats = asyncio.run(scrape_with_playwright(websites, engine, save=not args.no_save))

        log.info(f"\nSCRAPE COMPLETE: {stats}")
        rate = stats['success'] * 100 // max(stats['attempted'], 1)
        log.info(f"Success rate: {rate}%")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
