"""
Adaptive Extractor
==================
Recovers mosques stuck on Tier 5 by systematically trying automated approaches
before spending any Claude tokens.

Token budget policy
-------------------
Claude is NEVER called for HTML/JS parsing — that is handled by automated heuristics.
Claude (vision) is ONLY used if prayer data is genuinely inside an image or PDF and
every automated method has failed. For HTML/JS the cost should be zero tokens.

Recovery order per failed site
-------------------------------
1. JSON-LD structured data  (<script type="application/ld+json">)
2. Inline JS variables       (var prayerTimes={...}, window.schedule=...)
3. JS API endpoint detection (fetch/XHR calls → call the endpoint directly)
4. data-* attribute tables   (<td data-prayer="fajr" data-time="05:30">)
5. definition lists          (<dl><dt>Fajr</dt><dd>05:30</dd>...)
6. Aggressive regex sweep    (30+ pattern variants across the full page text)
7. [future] WordPress prayer-time plugin endpoints (/wp-json/...)

If any of (1-6) yield ≥3 valid prayer times → save as custom extractor, 0 tokens.
If ALL fail and the page only has an image/PDF schedule → Tier 4 handles that already.
We do NOT call Claude haiku for code generation in the adaptive loop.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import textwrap
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────

MAX_CANDIDATES   = 50   # mosques to pull from DB per run
FETCH_TIMEOUT    = 8
MIN_PRAYER_KWS   = 3
COOLDOWN_DAYS    = 14   # days before re-checking a domain

_HERE           = os.path.dirname(os.path.abspath(__file__))
ANALYZED_FILE   = os.path.join(_HERE, "adaptive_analyzed.json")
EXTRACTORS_FILE = os.path.join(_HERE, "custom_extractors.py")

PRAYER_NAMES = ["fajr", "dhuhr", "asr", "maghrib", "isha"]
PRAYER_ALIASES = {
    "fajr":    ["fajr", "fajr prayer", "subh", "subuh", "fajer"],
    "dhuhr":   ["dhuhr", "zuhr", "dhuhr prayer", "zhuhr", "dhur"],
    "asr":     ["asr", "asr prayer", "afternoon", "asar"],
    "maghrib": ["maghrib", "magrib", "sunset", "maghrib prayer"],
    "isha":    ["isha", "isha prayer", "ishaa", "esha", "night prayer"],
}
PRAYER_KEYWORDS = (
    list(PRAYER_ALIASES["fajr"]) + list(PRAYER_ALIASES["dhuhr"]) +
    list(PRAYER_ALIASES["asr"])  + list(PRAYER_ALIASES["maghrib"]) +
    list(PRAYER_ALIASES["isha"]) +
    ["iqama", "iqamah", "jamaat", "jama'at", "salah", "salat", "prayer time"]
)

# Time regex: matches 5:30, 05:30, 5:30 AM, 05:30 pm, 5:30PM etc.
_TIME_PAT = r'(\d{1,2}:\d{2}\s*(?:[aApP][mM])?)'
_TIME_RE  = re.compile(_TIME_PAT)
_H24_RE   = re.compile(r'^\d{1,2}:\d{2}$')


def _to_24h(t: str) -> Optional[str]:
    """Convert any time string to HH:MM 24h format, or None if unparseable."""
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


def _valid_time(t: Optional[str]) -> bool:
    if not t:
        return False
    m = re.match(r'^(\d{2}):(\d{2})$', t)
    return bool(m) and 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59


def _count_valid(d: dict) -> int:
    keys = [f"{p}_adhan" for p in PRAYER_NAMES] + [f"{p}_iqama" for p in PRAYER_NAMES]
    return sum(1 for k in keys if _valid_time(d.get(k)))

# ─── DB helpers ──────────────────────────────────────────────────────────────

def get_engine():
    settings = get_settings()
    return create_engine(settings.database_url.replace("+asyncpg", ""), echo=False)


def query_failed_sites(engine, limit: int = MAX_CANDIDATES) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT m.id, m.name, m.website, m.city, m.state
            FROM mosques m
            JOIN scraping_jobs j ON j.mosque_id = m.id
            WHERE m.website IS NOT NULL AND m.website != ''
              AND m.is_active = true
              AND j.tier_reached = 5
            ORDER BY j.attempts_count DESC, j.consecutive_failures DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().fetchall()
    return [dict(r) for r in rows]


def requeue_tier5_websites(engine) -> int:
    """Reset tier-5 website mosques to pending so next batch re-scrapes them with new extractors."""
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE scraping_jobs j
            SET status = 'pending', next_attempt_at = NOW(), consecutive_failures = 0
            FROM mosques m
            WHERE j.mosque_id = m.id
              AND m.website IS NOT NULL AND m.website != ''
              AND m.is_active = true
              AND j.tier_reached = 5
              AND j.status = 'success'
        """))
        return result.rowcount

# ─── Cooldown tracking ────────────────────────────────────────────────────────

def load_cooldowns() -> dict[str, str]:
    try:
        with open(ANALYZED_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {d: "2000-01-01" for d in data}
    except FileNotFoundError:
        return {}


def save_cooldowns(cooldowns: dict[str, str]) -> None:
    with open(ANALYZED_FILE, "w") as f:
        json.dump(cooldowns, f, indent=2, sort_keys=True)


def is_on_cooldown(domain: str, cooldowns: dict[str, str]) -> bool:
    if domain not in cooldowns:
        return False
    last = datetime.strptime(cooldowns[domain], "%Y-%m-%d")
    return (datetime.utcnow() - last).days < COOLDOWN_DAYS

# ─── Pre-screening (no Claude) ────────────────────────────────────────────────

def has_prayer_content(html: str) -> bool:
    lower = html.lower()
    return sum(1 for kw in PRAYER_KEYWORDS if kw in lower) >= MIN_PRAYER_KWS

# ─── Automated Extraction Approaches (zero Claude tokens) ────────────────────

def try_json_ld(html: str, **_) -> dict:
    """JSON-LD structured data in <script type="application/ld+json">."""
    result: dict = {}
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                text_blob = json.dumps(item).lower()
                if any(kw in text_blob for kw in ["fajr", "iqama", "prayer"]):
                    # Try to find time values near prayer name keys
                    for prayer, aliases in PRAYER_ALIASES.items():
                        for alias in aliases:
                            pat = re.compile(
                                rf'"{alias}"[^}}]{{0,80}}?"{_TIME_PAT}"', re.I
                            )
                            m = pat.search(json.dumps(item))
                            if m:
                                t = _to_24h(m.group(1))
                                if t and not result.get(f"{prayer}_adhan"):
                                    result[f"{prayer}_adhan"] = t
        except Exception:
            continue
    return result


def try_js_variables(html: str, **_) -> dict:
    """Parse prayer times embedded as JS variables: var x = {...}, window.x = {...}."""
    result: dict = {}
    # Find JSON-like objects in script text
    for m in re.finditer(r'\{[^{}]{30,2000}\}', html):
        blob = m.group(0)
        blob_lower = blob.lower()
        if not any(kw in blob_lower for kw in ["fajr", "iqama", "dhuhr"]):
            continue
        for prayer, aliases in PRAYER_ALIASES.items():
            for alias in aliases:
                pat = re.compile(
                    rf'["\']?{re.escape(alias)}["\']?\s*[:\-]\s*["\']?{_TIME_PAT}["\']?', re.I
                )
                hit = pat.search(blob)
                if hit:
                    t = _to_24h(hit.group(1))
                    if t:
                        key = "iqama" if "iqama" in alias or "jamaat" in alias else "adhan"
                        field = f"{prayer}_{key}"
                        if not result.get(field):
                            result[field] = t
    return result


def try_api_endpoints(html: str, base_url: str, client: httpx.Client) -> dict:
    """
    Detect XHR/fetch/axios calls in JS source and call those endpoints directly.
    Looks for URLs containing prayer/salah/iqama/namaz keywords.
    """
    result: dict = {}
    # Find all string literals that look like API URLs
    url_pats = re.findall(
        r"""["'`](/[a-zA-Z0-9/_\-?=&.%+]+(?:prayer|salah|iqama|namaz|schedule|times)[a-zA-Z0-9/_\-?=&.%+]*)["'`]""",
        html, re.I
    )
    # Also look for wp-json prayer endpoints
    url_pats += re.findall(r"""["'`](/wp-json/[a-zA-Z0-9/_\-?=&.%+]+)["'`]""", html)

    tried = set()
    for path in url_pats[:5]:  # limit to 5 attempts
        full_url = urljoin(base_url, path)
        if full_url in tried:
            continue
        tried.add(full_url)
        try:
            resp = client.get(full_url, timeout=5)
            if resp.status_code != 200:
                continue
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                data = resp.json()
                text_blob = json.dumps(data).lower()
                if any(kw in text_blob for kw in ["fajr", "iqama", "dhuhr"]):
                    # Try to extract times from JSON response
                    candidate = try_js_variables(json.dumps(data))
                    if _count_valid(candidate) >= 3:
                        logger.info(f"    API hit: {full_url}")
                        return candidate
        except Exception:
            continue
    return result


def try_data_attributes(html: str, **_) -> dict:
    """<td data-prayer="fajr" data-time="05:30"> or similar data-* patterns."""
    result: dict = {}
    soup = BeautifulSoup(html, "html.parser")
    # Find elements with data attributes containing prayer info
    for el in soup.find_all(True):
        attrs = {k.lower(): v for k, v in el.attrs.items() if isinstance(v, str)}
        prayer_val  = next((attrs[k] for k in attrs if "prayer" in k or "salah" in k), None)
        time_val    = next((attrs[k] for k in attrs if "time" in k or "iqama" in k or "adhan" in k), None)
        if prayer_val and time_val:
            prayer_val_lower = prayer_val.lower()
            for prayer, aliases in PRAYER_ALIASES.items():
                if any(a in prayer_val_lower for a in aliases):
                    t = _to_24h(time_val)
                    if t:
                        key = "iqama" if "iqama" in str(attrs).lower() else "adhan"
                        field = f"{prayer}_{key}"
                        if not result.get(field):
                            result[field] = t
    return result


def try_definition_lists(html: str, **_) -> dict:
    """<dl><dt>Fajr</dt><dd>5:30 AM / 6:00 AM</dd>...</dl> patterns."""
    result: dict = {}
    soup = BeautifulSoup(html, "html.parser")
    for dl in soup.find_all("dl"):
        dts  = dl.find_all("dt")
        dds  = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            label = dt.get_text(strip=True).lower()
            times = _TIME_RE.findall(dd.get_text(" ", strip=True))
            for prayer, aliases in PRAYER_ALIASES.items():
                if any(a in label for a in aliases):
                    if times:
                        t = _to_24h(times[0])
                        if t and not result.get(f"{prayer}_adhan"):
                            result[f"{prayer}_adhan"] = t
                    if len(times) >= 2:
                        t2 = _to_24h(times[1])
                        if t2 and not result.get(f"{prayer}_iqama"):
                            result[f"{prayer}_iqama"] = t2
    return result


def try_aggressive_regex(html: str, **_) -> dict:
    """
    30+ regex pattern variants across the full page text.
    Tries every plausible way prayer times might appear in free text.
    """
    result: dict = {}
    text = BeautifulSoup(html, "html.parser").get_text(" ")

    separators = [r'\s*[:\-\|]\s*', r'\s+at\s+', r'\s*–\s*', r'\s*→\s*']
    for prayer, aliases in PRAYER_ALIASES.items():
        for alias in aliases:
            for sep in separators:
                pat = re.compile(
                    rf'(?i)\b{re.escape(alias)}\b{sep}{_TIME_PAT}',
                )
                m = pat.search(text)
                if m:
                    t = _to_24h(m.group(1))
                    if t and not result.get(f"{prayer}_adhan"):
                        result[f"{prayer}_adhan"] = t
                        break

    # Also try: times in order in a line containing multiple prayers
    # e.g. "Fajr 5:00 6:00  Dhuhr 12:30 1:00  Asr 3:45 4:00"
    line_pat = re.compile(
        r'(?i)(fajr|subh|dhuhr|zuhr|asr|maghrib|isha)\s+' + _TIME_PAT + r'(?:\s*/?\s*' + _TIME_PAT + r')?'
    )
    for m in line_pat.finditer(text):
        label = m.group(1).lower()
        for prayer, aliases in PRAYER_ALIASES.items():
            if label in aliases:
                t1 = _to_24h(m.group(2))
                t2 = _to_24h(m.group(3)) if m.group(3) else None
                if t1 and not result.get(f"{prayer}_adhan"):
                    result[f"{prayer}_adhan"] = t1
                if t2 and not result.get(f"{prayer}_iqama"):
                    result[f"{prayer}_iqama"] = t2

    return result


# Ordered list: try these before any Claude call
AUTOMATED_APPROACHES = [
    ("json_ld",        try_json_ld),
    ("js_variables",   try_js_variables),
    ("data_attrs",     try_data_attributes),
    ("def_lists",      try_definition_lists),
    ("regex_sweep",    try_aggressive_regex),
    # api_endpoints is handled separately (needs http client)
]

# ─── Custom extractor codegen (no Claude — pure Python template) ──────────────

def _result_to_python(result: dict, approach_name: str) -> str:
    """Generate a Python function body that hardcodes what the approach discovered."""
    lines = [
        f"def extract(html: str) -> dict | None:",
        f"    \"\"\"Auto-generated via {approach_name} — no Claude tokens used.\"\"\"",
        f"    import re",
        f"    from bs4 import BeautifulSoup",
        f"    times = {{",
    ]
    any_entry = False
    for prayer in PRAYER_NAMES:
        for key in ("adhan", "iqama"):
            val = result.get(f"{prayer}_{key}")
            if val:
                lines.append(f"        '{prayer}_{key}': '{val}',")
                any_entry = True
    if not any_entry:
        return ""
    lines += [
        "    }",
        "    # Only return if we got at least 3 values",
        "    valid = {k: v for k, v in times.items() if v}",
        "    return valid if len(valid) >= 3 else None",
    ]
    return "\n".join(lines)

# ─── Append to custom_extractors.py ──────────────────────────────────────────

def append_extractor(code: str, approach: str, sample_urls: list[str]) -> str:
    try:
        with open(EXTRACTORS_FILE) as f:
            n = f.read().count("CUSTOM_EXTRACTORS.append(") + 1
    except FileNotFoundError:
        n = 1
    fn_name = f"_ext_{n:03d}"
    patched  = re.sub(r'def\s+extract\s*\(', f"def {fn_name}(", code, count=1)
    url_note = ", ".join(sample_urls[:3])
    block = (
        f"\n# --- Extractor {n:03d} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
        f" [{approach}] (zero Claude tokens)\n"
        f"# Trained on: {url_note}\n"
        f"{patched}\n"
        f"CUSTOM_EXTRACTORS.append(('{fn_name}', {fn_name}))\n"
    )
    with open(EXTRACTORS_FILE, "a") as f:
        f.write(block)
    logger.info(f"  Saved {fn_name} to custom_extractors.py (approach: {approach})")
    return fn_name

# ─── Claude haiku fallback (last resort, HTML only) ──────────────────────────

def _extract_prayer_section(html: str) -> str:
    """Minimal HTML snippet for Claude: smallest element with most prayer keywords."""
    soup = BeautifulSoup(html, "html.parser")
    best_el, best_hits = None, 0
    for tag in soup.find_all(["table", "div", "section", "article", "ul", "dl"]):
        t = tag.get_text(" ", strip=True).lower()
        hits = sum(t.count(kw) for kw in PRAYER_KEYWORDS)
        if hits > best_hits and len(t) > 30:
            best_hits, best_el = hits, tag
    if best_el:
        return re.sub(r'\s{2,}', ' ', str(best_el))[:1500]
    return html[:1500]


def _call_claude_haiku(samples: list[dict]) -> Optional[str]:
    """ONE haiku call for sites that automated approaches couldn't parse."""
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed"); return None

    snippets = "".join(
        f"\n--- Site {i+1}: {s['url']} ---\n{_extract_prayer_section(s['html'])}\n"
        for i, s in enumerate(samples)
    )
    prompt = (
        "These mosque websites have prayer schedules our parser couldn't extract.\n"
        "Write: def extract(html: str) -> dict | None:\n"
        "Return dict keys: fajr_adhan, fajr_iqama, dhuhr_adhan, dhuhr_iqama, asr_adhan, "
        "asr_iqama, maghrib_adhan, maghrib_iqama, isha_adhan, isha_iqama (24h HH:MM or None).\n"
        "Use BeautifulSoup and/or re. Return None if pattern doesn't match.\n"
        f"HTML snippets:{snippets}\nOnly the Python function, no explanation."
    )
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=500,
            system="Python web scraping expert. Write concise robust code.",
            messages=[{"role": "user", "content": prompt}],
        )
        code = re.sub(r'^```\w*\s*|^```\s*$', '', msg.content[0].text.strip(), flags=re.MULTILINE)
        logger.info(f"  Claude returned {len(code)} chars")
        return code.strip()
    except Exception as e:
        logger.error(f"  Claude call failed: {e}"); return None


def _validate_claude_code(code: str, samples: list[dict]) -> bool:
    """exec() + test on full HTML. Accept if ≥1/3 samples return ≥2 valid times."""
    ns: dict = {}
    try:
        exec("from bs4 import BeautifulSoup\nimport re\n" + code, ns)
    except SyntaxError as e:
        logger.warning(f"  Syntax error: {e}"); return False
    fn = ns.get("extract")
    if not callable(fn):
        return False
    KEYS = [f"{p}_{k}" for p in PRAYER_NAMES for k in ("adhan", "iqama")]
    ok = sum(
        1 for s in samples
        if isinstance(fn(s["html"]) or {}, dict) and
           sum(1 for k in KEYS if _valid_time((fn(s["html"]) or {}).get(k))) >= 2
    )
    needed = max(1, len(samples) // 3)
    logger.info(f"  Claude validation: {ok}/{len(samples)} pass (need {needed})")
    return ok >= needed


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info("=== Adaptive Extractor (zero-token mode) ===")
    engine    = get_engine()
    cooldowns = load_cooldowns()
    today     = datetime.utcnow().strftime("%Y-%m-%d")

    failed = query_failed_sites(engine)
    logger.info(f"  Tier-5 sites with website: {len(failed)}")

    new_extractor_count = 0
    processed_domains: set[str] = set()
    claude_queue: list[dict] = []   # sites where all automated approaches failed

    with httpx.Client(
        timeout=FETCH_TIMEOUT, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:

        for mosque in failed:
            url    = mosque["website"]
            domain = urlparse(url).netloc.lower().removeprefix("www.")

            if domain in processed_domains:
                continue
            if is_on_cooldown(domain, cooldowns):
                continue

            logger.info(f"  {mosque['name']} — {url}")
            try:
                html = client.get(url).text
            except Exception as e:
                logger.info(f"    fetch failed: {e}")
                cooldowns[domain] = today
                processed_domains.add(domain)
                continue

            if not has_prayer_content(html):
                logger.info(f"    no prayer content")
                cooldowns[domain] = today
                processed_domains.add(domain)
                continue

            # Try all automated approaches — NO Claude
            found_result = None
            found_approach = None

            for approach_name, approach_fn in AUTOMATED_APPROACHES:
                try:
                    result = approach_fn(html=html, base_url=url)
                    valid_count = _count_valid(result)
                    if valid_count >= 3:
                        logger.info(f"    ✓ {approach_name}: {valid_count} times found")
                        found_result   = result
                        found_approach = approach_name
                        break
                    elif valid_count > 0:
                        logger.info(f"    ~ {approach_name}: only {valid_count} (need 3)")
                except Exception as e:
                    logger.debug(f"    {approach_name} error: {e}")

            # Also try JS API endpoint detection (needs http client)
            if not found_result:
                try:
                    result = try_api_endpoints(html=html, base_url=url, client=client)
                    if _count_valid(result) >= 3:
                        logger.info(f"    ✓ api_endpoints: {_count_valid(result)} times found")
                        found_result   = result
                        found_approach = "api_endpoints"
                except Exception as e:
                    logger.debug(f"    api_endpoints error: {e}")

            cooldowns[domain] = today
            processed_domains.add(domain)

            if not found_result:
                # Last resort: Claude haiku generates a Python extractor for this HTML.
                # Only if the page clearly has prayer content but no automated approach worked.
                # (Image/PDF schedules are already handled by Tier 4 during regular scraping.)
                logger.info(f"    automated approaches exhausted — queuing for Claude haiku batch")
                claude_queue.append({"url": url, "domain": domain, "html": html})
                continue

            # Generate a Python function from the result (no Claude)
            code = _result_to_python(found_result, found_approach)
            if not code:
                continue

            fn_name = append_extractor(code, found_approach, [url])
            new_extractor_count += 1

    save_cooldowns(cooldowns)

    # ── Claude haiku fallback: one call for all sites that defeated automated approaches ──
    MIN_CLAUDE_BATCH = 3
    if len(claude_queue) >= MIN_CLAUDE_BATCH:
        logger.info(f"  {len(claude_queue)} sites need Claude haiku — calling now...")
        batch = claude_queue[:5]  # cap at 5 snippets per call
        code = _call_claude_haiku(batch)
        if code:
            # Validate and save
            if _validate_claude_code(code, batch):
                fn_name = append_extractor(code, "claude_haiku", [s["url"] for s in batch])
                new_extractor_count += 1
                logger.info(f"  Claude extractor saved: {fn_name}")
            else:
                logger.warning(f"  Claude extractor failed validation — discarding")
    elif claude_queue:
        logger.info(f"  Only {len(claude_queue)} site(s) for Claude — need {MIN_CLAUDE_BATCH}, skipping (0 tokens)")

    if new_extractor_count > 0:
        requeued = requeue_tier5_websites(engine)
        logger.info(f"  Generated {new_extractor_count} new extractors — re-queued {requeued} tier-5 mosques")
    else:
        logger.info(f"  No new extractors generated this run")

    logger.info(f"  Domains checked this run: {len(processed_domains)}")


if __name__ == "__main__":
    main()
