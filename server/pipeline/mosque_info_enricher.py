"""
Mosque Info Enricher
====================
Scrapes each mosque website for fields beyond prayer times:
  - denomination (sunni / shia / hanafi / shafi'i / maliki / hanbali / salafi / ismaili / ...)
  - has_womens_section
  - wheelchair_accessible
  - languages_spoken  (sermon/khutba languages)
  - jumuah_sessions   (Friday prayer — khutba time, prayer time, language, imam, multiple sessions)

Run standalone:
    python -m pipeline.mosque_info_enricher [--batch N] [--dry-run]

Integrated into run_scraping_loop.sh: called after every scraping batch.

Token policy: zero Claude tokens. All extraction is regex + BeautifulSoup.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import date, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 10
USER_AGENT    = "Mozilla/5.0 (compatible; CatchAPrayerBot/1.0)"

# ─── Denomination keywords ────────────────────────────────────────────────────

_DENOM_PATTERNS: list[tuple[str, list[str]]] = [
    # (denomination value, keywords to search for)
    ("ismaili",       ["ismaili", "jamatkhana", "aga khan"]),
    ("ahmadiyya",     ["ahmadiyya", "ahmadiyah", "ahmadi"]),
    ("shia",          ["shia", "shi'a", "shi'ah", "shiah", "jafari", "ithna ashari",
                       "twelve", "twelfth imam", "hussainiya", "hussainia"]),
    ("salafi",        ["salafi", "salafee", "salafiyyah", "ahle hadith", "ahl al-hadith"]),
    ("deobandi",      ["deobandi", "darul uloom", "darul-uloom"]),
    ("barelvi",       ["barelvi", "barelwi", "raza foundation"]),
    ("hanbali",       ["hanbali"]),
    ("maliki",        ["maliki"]),
    ("shafi",         ["shafi'i", "shafii", "shafi"]),
    ("hanafi",        ["hanafi"]),
    ("sunni",         ["sunni", "ahlus sunnah", "ahl al-sunnah", "sunni muslim"]),
]

def detect_denomination(text: str) -> Optional[str]:
    t = text.lower()
    for denom, kws in _DENOM_PATTERNS:
        if any(kw in t for kw in kws):
            return denom
    return None

# ─── Women's section ─────────────────────────────────────────────────────────

_WOMENS_POSITIVE = [
    "sisters' prayer", "sisters prayer", "women's prayer", "womens prayer",
    "women's section", "womens section", "musallah sisters", "sisters musallah",
    "ladies section", "ladies prayer", "prayer area for women",
    "women's musallah", "sisters area", "female prayer",
]
_WOMENS_NEGATIVE = [
    "no women", "men only", "brothers only", "no sisters",
]

def detect_womens_section(text: str) -> Optional[bool]:
    t = text.lower()
    if any(kw in t for kw in _WOMENS_NEGATIVE):
        return False
    if any(kw in t for kw in _WOMENS_POSITIVE):
        return True
    return None

# ─── Wheelchair accessible ───────────────────────────────────────────────────

_WHEELCHAIR_POSITIVE = [
    "wheelchair accessible", "wheelchair access", "handicap accessible",
    "accessible entrance", "ada accessible", "ada compliant",
    "disability access", "accessible parking",
]

def detect_wheelchair(text: str) -> Optional[bool]:
    t = text.lower()
    if any(kw in t for kw in _WHEELCHAIR_POSITIVE):
        return True
    return None

# ─── Languages ───────────────────────────────────────────────────────────────

_KNOWN_LANGUAGES = [
    "arabic", "english", "urdu", "bengali", "somali", "farsi", "persian",
    "turkish", "french", "spanish", "bosnian", "albanian", "swahili",
    "pashto", "punjabi", "gujarati", "indonesian", "malay", "hausa",
]

def detect_languages(text: str) -> list[str]:
    t = text.lower()
    found = []
    for lang in _KNOWN_LANGUAGES:
        if lang in t:
            found.append(lang.capitalize())
    return found

# ─── Jumuah (Friday prayer) ───────────────────────────────────────────────────

_TIME_PAT = r'(\d{1,2}:\d{2}\s*(?:[aApP][mM])?)'
_TIME_RE  = re.compile(_TIME_PAT)

_KHUTBA_KWS  = ["khutba", "khutbah", "sermon", "first adhan", "1st adhan", "athan 1"]
_PRAYER_KWS  = ["iqama", "iqamah", "jamaat", "prayer", "salah", "second adhan", "2nd adhan"]
_FRIDAY_KWS  = ["friday", "jumu'ah", "jumuah", "jum'ah", "jumua", "jumu"]

def _to_24h(t: str) -> Optional[str]:
    t = t.strip()
    m = re.match(r'^(\d{1,2}):(\d{2})\s*([aApP][mM])?$', t)
    if not m:
        return None
    h, mn, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "").upper()
    if h > 23 or mn > 59:
        return None
    if ampm == "PM" and h != 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mn:02d}"


def next_friday() -> date:
    today = date.today()
    days_ahead = 4 - today.weekday()  # Friday = 4
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def extract_jumuah_sessions(html: str) -> list[dict]:
    """
    Extract Friday prayer sessions from a page.
    Returns list of dicts: {session_number, khutba_start, prayer_start, language, imam_name}.
    Handles multiple sessions (1st Jumu'ah, 2nd Jumu'ah, etc.).
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ")
    text_lower = text.lower()

    # Quick check: does this page mention Friday prayer?
    if not any(kw in text_lower for kw in _FRIDAY_KWS):
        return []

    sessions: list[dict] = []

    # ── Strategy 1: find a table or section that groups Friday prayer info ──
    friday_sections = []
    for el in soup.find_all(["div", "section", "article", "table", "tr", "li"]):
        el_text = el.get_text(" ", strip=True).lower()
        if any(kw in el_text for kw in _FRIDAY_KWS) and any(t in el_text for t in [":", "am", "pm"]):
            friday_sections.append(el)

    # Sort by length descending to try the richest section first
    friday_sections.sort(key=lambda e: len(e.get_text()), reverse=True)

    for section in friday_sections[:3]:
        sec_text = section.get_text(" ")
        times = [_to_24h(t) for t in _TIME_RE.findall(sec_text)]
        times = [t for t in times if t]  # filter None

        if not times:
            continue

        # Detect multiple session markers
        multi = re.findall(
            r'(?i)(\d+(?:st|nd|rd|th)|first|second|third)\s+(?:jumu[\'a]?ah?|prayer|salah)',
            sec_text
        )

        if multi and len(times) >= len(multi) * 2:
            # Pair times into (khutba, iqama) per session
            for i, label in enumerate(multi[:3]):
                base = i * 2
                session = {
                    "session_number": i + 1,
                    "khutba_start": times[base] if base < len(times) else None,
                    "prayer_start": times[base + 1] if base + 1 < len(times) else None,
                }
                sessions.append(session)
        elif len(times) >= 2:
            # Single session: first time = khutba, second = iqama
            sessions.append({
                "session_number": 1,
                "khutba_start": times[0],
                "prayer_start": times[1],
            })
        elif len(times) == 1:
            sessions.append({
                "session_number": 1,
                "khutba_start": None,
                "prayer_start": times[0],
            })

        if sessions:
            break

    # ── Strategy 2: regex on full page text ──
    if not sessions:
        # Pattern: "Jumu'ah / Friday Prayer: 1:00 PM / 1:30 PM"
        pat = re.compile(
            r'(?i)(?:jumu[\'a]?ah?|friday)\s*[:\-]?\s*' + _TIME_PAT + r'(?:\s*/\s*' + _TIME_PAT + r')?'
        )
        for m in pat.finditer(text):
            sessions.append({
                "session_number": len(sessions) + 1,
                "khutba_start": _to_24h(m.group(1)),
                "prayer_start": _to_24h(m.group(2)) if m.group(2) else None,
            })
        if len(sessions) > 3:
            sessions = sessions[:3]

    # ── Detect language per session (or globally) ──
    langs_found = detect_languages(text)
    global_lang = langs_found[0] if langs_found else None
    for s in sessions:
        s.setdefault("language", global_lang)
        s.setdefault("imam_name", None)

    return sessions

# ─── Link scoring ────────────────────────────────────────────────────────────

# Keywords that suggest a page is relevant, with scores
_LINK_SCORES: list[tuple[int, list[str]]] = [
    (10, ["prayer", "salah", "salat", "iqama", "iqamah", "namaz", "times", "schedule"]),
    (10, ["friday", "jumuah", "jumu", "juma", "jumah", "khutba", "khutbah"]),
    (5,  ["about", "who we are", "who-we-are", "mission", "our-story", "overview"]),
    (5,  ["services", "facilities", "programs", "activities", "community"]),
    (3,  ["contact", "info", "information", "welcome", "home"]),
]

_SKIP_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".mp3", ".mp4", ".zip"}

def _score_link(href: str, anchor_text: str) -> int:
    combined = (href + " " + anchor_text).lower()
    # Skip non-page links
    if any(combined.endswith(ext) for ext in _SKIP_EXTENSIONS):
        return -1
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return -1
    score = 0
    for points, keywords in _LINK_SCORES:
        if any(kw in combined for kw in keywords):
            score += points
    return score


def _extract_ranked_links(homepage_html: str, base_url: str, top_n: int = 5) -> list[str]:
    """Extract internal links from homepage, ranked by relevance. Returns top N URLs."""
    from urllib.parse import urljoin, urlparse
    soup = BeautifulSoup(homepage_html, "html.parser")
    base_domain = urlparse(base_url).netloc

    seen: set[str] = set()
    scored: list[tuple[int, str]] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        anchor = a.get_text(" ", strip=True)
        full_url = urljoin(base_url, href)

        # Only follow internal links
        if urlparse(full_url).netloc != base_domain:
            continue
        # Deduplicate
        path = urlparse(full_url).path.rstrip("/")
        if path in seen or not path or path == urlparse(base_url).path.rstrip("/"):
            continue
        seen.add(path)

        score = _score_link(full_url, anchor)
        if score > 0:
            scored.append((score, full_url))

    scored.sort(key=lambda x: -x[0])
    return [url for _, url in scored[:top_n]]


def _fetch(client: httpx.Client, url: str) -> Optional[str]:
    try:
        r = client.get(url, timeout=FETCH_TIMEOUT)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None

# ─── Per-mosque enrichment ───────────────────────────────────────────────────

def enrich_mosque(mosque: dict, client: httpx.Client) -> dict:
    """
    Fetch mosque website and extract info fields.
    Fetches homepage, extracts + ranks all internal links by relevance,
    then visits only the top 5 most relevant pages — no hardcoded URL guessing.
    """
    url = mosque["website"]
    result: dict = {
        "denomination": None, "denomination_source": None,
        "has_womens_section": None, "wheelchair_accessible": None,
        "languages_spoken": None, "jumuah_sessions": [],
    }

    homepage_html = _fetch(client, url) or ""
    if not homepage_html.strip():
        return result

    # Rank internal links by relevance and fetch top 5
    ranked_urls = _extract_ranked_links(homepage_html, url, top_n=5)
    logger.debug(f"    ranked links: {ranked_urls}")

    all_html = homepage_html
    subpage_htmls: list[str] = []
    for sub_url in ranked_urls:
        sub_html = _fetch(client, sub_url)
        if sub_html:
            all_html += " " + sub_html
            subpage_htmls.append(sub_html)

    full_text = BeautifulSoup(all_html, "html.parser").get_text(" ")

    result["denomination"]          = detect_denomination(full_text)
    result["denomination_source"]   = "website_scraped" if result["denomination"] else None
    result["has_womens_section"]    = detect_womens_section(full_text)
    result["wheelchair_accessible"] = detect_wheelchair(full_text)
    langs = detect_languages(full_text)
    result["languages_spoken"]      = langs if langs else None

    # Jumuah: try homepage first, then any fetched subpages
    sessions = extract_jumuah_sessions(homepage_html)
    if not sessions:
        for sub_html in subpage_htmls:
            sessions = extract_jumuah_sessions(sub_html)
            if sessions:
                break
    result["jumuah_sessions"] = sessions

    return result

# ─── DB save ─────────────────────────────────────────────────────────────────

def save_mosque_info(conn, mosque_id: str, info: dict, dry_run: bool) -> None:
    if dry_run:
        return

    # Update mosque row
    fields: dict = {}
    if info["denomination"]:
        fields["denomination"] = info["denomination"]
        fields["denomination_source"] = info["denomination_source"]
        fields["denomination_enriched_at"] = "NOW()"
    if info["has_womens_section"] is not None:
        fields["has_womens_section"] = info["has_womens_section"]
    if info["wheelchair_accessible"] is not None:
        fields["wheelchair_accessible"] = info["wheelchair_accessible"]
    if info["languages_spoken"]:
        fields["languages_spoken"] = info["languages_spoken"]

    if fields:
        set_parts = []
        params: dict = {"mosque_id": mosque_id}
        for k, v in fields.items():
            if v == "NOW()":
                set_parts.append(f"{k} = NOW()")
            else:
                set_parts.append(f"{k} = :{k}")
                params[k] = v
        conn.execute(
            text(f"UPDATE mosques SET {', '.join(set_parts)}, updated_at=NOW() WHERE id=CAST(:mosque_id AS uuid)"),
            params,
        )

    # Upsert jumuah sessions
    if info["jumuah_sessions"]:
        friday = next_friday()
        for s in info["jumuah_sessions"]:
            conn.execute(text("""
                INSERT INTO jumuah_sessions
                    (id, mosque_id, valid_date, session_number,
                     khutba_start, prayer_start, language, imam_name,
                     booking_required, created_at)
                VALUES
                    (gen_random_uuid(), CAST(:mosque_id AS uuid), :valid_date, :session_number,
                     :khutba_start, :prayer_start, :language, :imam_name,
                     false, NOW())
                ON CONFLICT (mosque_id, valid_date, session_number) DO UPDATE SET
                    khutba_start = EXCLUDED.khutba_start,
                    prayer_start = EXCLUDED.prayer_start,
                    language     = EXCLUDED.language,
                    imam_name    = EXCLUDED.imam_name
            """), {
                "mosque_id":      mosque_id,
                "valid_date":     friday.isoformat(),
                "session_number": s.get("session_number", 1),
                "khutba_start":   s.get("khutba_start"),
                "prayer_start":   s.get("prayer_start"),
                "language":       s.get("language"),
                "imam_name":      s.get("imam_name"),
            })

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enrich mosque info from websites")
    parser.add_argument("--batch",   type=int, default=30, help="mosques per run")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logger.info(f"=== Mosque Info Enricher (batch={args.batch}, dry_run={args.dry_run}) ===")
    settings = get_settings()
    engine   = create_engine(settings.database_url.replace("+asyncpg", ""), echo=False)

    with engine.connect() as conn:
        # Prioritise: has website + not recently enriched + missing info fields
        rows = conn.execute(text("""
            SELECT m.id, m.name, m.website, m.city, m.state
            FROM mosques m
            WHERE m.website IS NOT NULL AND m.website != ''
              AND m.is_active = true
              AND (
                  m.denomination IS NULL
                  OR m.has_womens_section IS NULL
                  OR m.denomination_enriched_at IS NULL
                  OR m.denomination_enriched_at < NOW() - INTERVAL '30 days'
              )
            ORDER BY
                CASE WHEN m.denomination IS NULL THEN 0 ELSE 1 END,  -- unenriched first
                m.created_at DESC
            LIMIT :batch
        """), {"batch": args.batch}).mappings().fetchall()
    mosques = [dict(r) for r in rows]
    logger.info(f"  Mosques to enrich: {len(mosques)}")

    enriched = 0
    with httpx.Client(
        timeout=FETCH_TIMEOUT, follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for mosque in mosques:
            logger.info(f"  {mosque['name']} — {mosque['website']}")
            try:
                info = enrich_mosque(mosque, client)
                denom   = info["denomination"] or "-"
                women   = info["has_womens_section"]
                wheel   = info["wheelchair_accessible"]
                langs   = ", ".join(info["languages_spoken"] or []) or "-"
                juma_n  = len(info["jumuah_sessions"])
                logger.info(f"    denom={denom}  women={women}  wheel={wheel}  langs={langs}  juma={juma_n}")

                has_data = any([
                    info["denomination"],
                    info["has_womens_section"] is not None,
                    info["wheelchair_accessible"] is not None,
                    info["languages_spoken"],
                    info["jumuah_sessions"],
                ])
                if has_data:
                    with engine.begin() as conn:
                        save_mosque_info(conn, mosque["id"], info, args.dry_run)
                    enriched += 1
                else:
                    # Mark as checked so we don't re-fetch too often
                    if not args.dry_run:
                        with engine.begin() as conn:
                            conn.execute(text(
                                "UPDATE mosques SET denomination_enriched_at=NOW() WHERE id=CAST(:id AS uuid)"
                            ), {"id": mosque["id"]})

            except Exception as e:
                logger.warning(f"    error: {e}")

    logger.info(f"=== Enriched {enriched}/{len(mosques)} mosques ===")


if __name__ == "__main__":
    main()
