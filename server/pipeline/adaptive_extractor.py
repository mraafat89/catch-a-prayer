"""
Adaptive Extractor
==================
Samples mosque websites that fell through to Tier 5 (calculated) despite having
a website, pre-screens them cheaply (no Claude), then calls Claude ONCE per run
with a batch of stripped prayer-section snippets to generate a new Python
extraction function.

Token budget policy
-------------------
- Claude is called AT MOST ONCE per invocation.
- Only called when >= MIN_SAMPLES sites with prayer content are found.
- HTML is stripped to the smallest element containing prayer keywords (≤1500 chars/site).
- Model: claude-haiku (cheapest).
- Output appended to pipeline/custom_extractors.py for use by scraping_worker.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
import textwrap
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────

MIN_SAMPLES      = 5    # minimum sites with prayer content before calling Claude
MAX_CANDIDATES   = 30   # mosques to query from DB
MAX_BATCH_SIZE   = 5    # snippets per Claude call (token budget)
SNIPPET_MAX_CHARS = 1500
FETCH_TIMEOUT    = 8    # seconds
MIN_PRAYER_KWS   = 3    # keyword hits to consider a page prayer-related

# File that records which domains have already been analyzed (to avoid re-sending)
_HERE = os.path.dirname(os.path.abspath(__file__))
ANALYZED_FILE   = os.path.join(_HERE, "adaptive_analyzed.json")
EXTRACTORS_FILE = os.path.join(_HERE, "custom_extractors.py")

PRAYER_KEYWORDS = [
    "fajr", "dhuhr", "zuhr", "asr", "maghrib", "isha", "iqama", "iqamah",
    "salah", "salat", "prayer time", "jama'at", "jamaat", "jumu", "jumuah",
]

# ─── DB helpers ──────────────────────────────────────────────────────────────

def get_engine():
    settings = get_settings()
    return create_engine(settings.database_url.replace("+asyncpg", ""), echo=False)


def query_failed_sites(engine, limit: int = MAX_CANDIDATES) -> list[dict]:
    """Return mosques with website + tier_reached=5 + ≥2 attempts, worst failures first."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT m.id, m.name, m.website, m.city, m.state
            FROM mosques m
            JOIN scraping_jobs j ON j.mosque_id = m.id
            WHERE m.website IS NOT NULL AND m.website != ''
              AND m.is_active = true
              AND j.tier_reached = 5
              AND j.attempts_count >= 2
            ORDER BY j.consecutive_failures DESC, j.attempts_count DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().fetchall()
    return [dict(r) for r in rows]

# ─── Pre-screening (no Claude) ────────────────────────────────────────────────

def has_prayer_content(html: str) -> bool:
    """Cheap regex check — does this page contain prayer schedule content?"""
    lower = html.lower()
    hits = sum(1 for kw in PRAYER_KEYWORDS if kw in lower)
    return hits >= MIN_PRAYER_KWS


def extract_prayer_section(html: str) -> str:
    """
    Find the single HTML element (table, div, section, article) that contains
    the highest density of prayer keywords, strip it to ≤SNIPPET_MAX_CHARS.
    Falls back to a raw text window if no element stands out.
    """
    soup = BeautifulSoup(html, "html.parser")
    best_el = None
    best_hits = 0

    for tag in soup.find_all(["table", "div", "section", "article", "ul", "dl"]):
        text_content = tag.get_text(" ", strip=True).lower()
        if len(text_content) < 30:
            continue
        hits = sum(text_content.count(kw) for kw in PRAYER_KEYWORDS)
        if hits > best_hits:
            best_hits = hits
            best_el = tag

    if best_el:
        snippet = str(best_el)
        # Collapse whitespace aggressively
        snippet = re.sub(r'\s{2,}', ' ', snippet)
        return snippet[:SNIPPET_MAX_CHARS]

    # Fallback: just take a window of raw text around the first keyword hit
    lower = html.lower()
    for kw in PRAYER_KEYWORDS:
        idx = lower.find(kw)
        if idx != -1:
            start = max(0, idx - 200)
            return html[start : start + SNIPPET_MAX_CHARS]
    return html[:SNIPPET_MAX_CHARS]

# ─── Analyzed-domains cache ───────────────────────────────────────────────────

def load_analyzed() -> set[str]:
    try:
        with open(ANALYZED_FILE) as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def save_analyzed(domains: set[str]) -> None:
    with open(ANALYZED_FILE, "w") as f:
        json.dump(sorted(domains), f, indent=2)

# ─── Claude call ─────────────────────────────────────────────────────────────

def call_claude(samples: list[dict]) -> Optional[str]:
    """
    One API call to claude-haiku with batched HTML snippets.
    Returns raw Python function code as a string, or None on failure.
    Each sample: {"url": str, "snippet": str}
    """
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed")
        return None

    snippets_text = ""
    for i, s in enumerate(samples, 1):
        snippets_text += f"\n--- Site {i}: {s['url']} ---\n{s['snippet']}\n"

    prompt = (
        "These mosque websites contain prayer schedules but our HTML parser couldn't extract them.\n"
        "Write a Python function:\n\n"
        "    def extract(html: str) -> dict | None:\n\n"
        "Return a dict with keys: fajr_adhan, fajr_iqama, dhuhr_adhan, dhuhr_iqama, "
        "asr_adhan, asr_iqama, maghrib_adhan, maghrib_iqama, isha_adhan, isha_iqama "
        "(24h HH:MM strings or None). Return None if pattern doesn't match.\n"
        "Use: soup = BeautifulSoup(html, 'html.parser') and/or re.\n\n"
        f"HTML snippets:{snippets_text}\n"
        "Respond with ONLY the Python function code, no explanation, no markdown fences."
    )

    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system="You are a Python web scraping expert. Write concise, robust extraction code.",
            messages=[{"role": "user", "content": prompt}],
        )
        code = msg.content[0].text.strip()
        logger.info(f"  Claude generated {len(code)} chars of code")
        return code
    except Exception as e:
        logger.error(f"  Claude call failed: {e}")
        return None

# ─── Validation ───────────────────────────────────────────────────────────────

_TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')

def _is_valid_time(v) -> bool:
    return isinstance(v, str) and bool(_TIME_RE.match(v.strip()))


def validate_extractor(code: str, samples: list[dict]) -> bool:
    """
    Exec the generated function and test against each sample.
    Accept if it returns ≥2 valid prayer times for ≥2 samples.
    """
    namespace: dict = {}
    try:
        # Provide common imports inside the exec namespace
        exec(
            "from bs4 import BeautifulSoup\nimport re\n" + code,
            namespace,
        )
    except SyntaxError as e:
        logger.warning(f"  Validation: syntax error in generated code: {e}")
        return False

    fn = namespace.get("extract")
    if not callable(fn):
        logger.warning("  Validation: no 'extract' function found in generated code")
        return False

    PRAYER_KEYS = [
        "fajr_adhan", "fajr_iqama", "dhuhr_adhan", "dhuhr_iqama",
        "asr_adhan", "asr_iqama", "maghrib_adhan", "maghrib_iqama",
        "isha_adhan", "isha_iqama",
    ]
    successes = 0
    for s in samples:
        try:
            result = fn(s["html"])  # use full HTML for validation (not stripped snippet)
            if isinstance(result, dict):
                valid_count = sum(1 for k in PRAYER_KEYS if _is_valid_time(result.get(k)))
                if valid_count >= 2:
                    successes += 1
                    logger.info(f"    ✓ {s['url']}: {valid_count} valid prayer times")
                else:
                    logger.info(f"    ✗ {s['url']}: only {valid_count} valid times")
            else:
                logger.info(f"    ✗ {s['url']}: returned None")
        except Exception as e:
            logger.info(f"    ✗ {s['url']}: exception {e}")

    min_successes = max(1, len(samples) // 3)  # accept if ≥1/3 of samples work
    ok = successes >= min_successes
    logger.info(f"  Validation: {successes}/{len(samples)} samples ok (need {min_successes}) → {'ACCEPT' if ok else 'REJECT'}")
    return ok

# ─── Append to custom_extractors.py ──────────────────────────────────────────

def append_extractor(code: str, sample_urls: list[str]) -> str:
    """
    Append a new extractor to custom_extractors.py.
    Renames the function to _ext_NNN_... to avoid collisions.
    Returns the new function name.
    """
    # Determine next extractor number
    try:
        with open(EXTRACTORS_FILE) as f:
            existing = f.read()
        existing_count = existing.count("CUSTOM_EXTRACTORS.append(")
    except FileNotFoundError:
        existing_count = 0

    n = existing_count + 1
    fn_name = f"_ext_{n:03d}"

    # Rename the function in the generated code
    patched = re.sub(r'def\s+extract\s*\(', f"def {fn_name}(", code, count=1)

    url_comment = ", ".join(sample_urls[:3])
    block = (
        f"\n# --- Extractor {n:03d} — generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n"
        f"# Trained on: {url_comment}\n"
        f"{patched}\n"
        f"CUSTOM_EXTRACTORS.append(('{fn_name}', {fn_name}))\n"
    )

    with open(EXTRACTORS_FILE, "a") as f:
        f.write(block)

    logger.info(f"  Appended {fn_name} to custom_extractors.py")
    return fn_name

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info("=== Adaptive Extractor ===")
    engine = get_engine()

    analyzed_domains = load_analyzed()
    logger.info(f"  Already analyzed domains: {len(analyzed_domains)}")

    failed = query_failed_sites(engine)
    logger.info(f"  Failed (tier=5) sites in DB: {len(failed)}")

    # Pre-screen: fetch pages, check for prayer content, extract snippets
    candidates: list[dict] = []
    new_domains: set[str] = set()

    for mosque in failed:
        url = mosque["website"]
        domain = urlparse(url).netloc.lower()

        if domain in analyzed_domains:
            logger.debug(f"  Skip (already analyzed): {domain}")
            continue

        logger.info(f"  Fetching: {mosque['name']} — {url}")
        try:
            with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = client.get(url)
                html = resp.text
        except Exception as e:
            logger.info(f"    fetch failed: {e}")
            new_domains.add(domain)  # mark as tried so we don't retry next time
            continue

        if not has_prayer_content(html):
            logger.info(f"    no prayer content detected — skipping")
            new_domains.add(domain)
            continue

        snippet = extract_prayer_section(html)
        candidates.append({
            "url": url,
            "domain": domain,
            "html": html,      # full HTML for validation
            "snippet": snippet, # stripped snippet for Claude
        })
        logger.info(f"    ✓ prayer content found, snippet {len(snippet)} chars")

        if len(candidates) >= MAX_BATCH_SIZE * 2:
            break  # enough to work with

    # Deduplicate by domain (take one per domain) and cap at MAX_BATCH_SIZE
    seen = set()
    batch = []
    for c in candidates:
        if c["domain"] not in seen:
            seen.add(c["domain"])
            batch.append(c)
        if len(batch) >= MAX_BATCH_SIZE:
            break

    if len(batch) < MIN_SAMPLES:
        logger.info(
            f"  Only {len(batch)} fresh candidates found (need {MIN_SAMPLES}) "
            f"— skipping Claude call (no tokens used)"
        )
        # Still mark fetched domains as analyzed to avoid re-fetching next time
        save_analyzed(analyzed_domains | new_domains | {c["domain"] for c in batch})
        return

    logger.info(f"  Sending {len(batch)} snippets to Claude (haiku)...")
    code = call_claude([{"url": c["url"], "snippet": c["snippet"]} for c in batch])

    if not code:
        logger.warning("  No code returned from Claude")
        return

    logger.info("  Validating generated extractor...")
    if not validate_extractor(code, batch):
        logger.warning("  Extractor failed validation — discarding")
        # Mark domains as analyzed anyway (don't waste tokens on them again)
        save_analyzed(analyzed_domains | new_domains | {c["domain"] for c in batch})
        return

    fn_name = append_extractor(code, [c["url"] for c in batch])
    logger.info(f"  New extractor saved: {fn_name}")

    # Mark all processed domains as analyzed
    processed = analyzed_domains | new_domains | {c["domain"] for c in batch}
    save_analyzed(processed)
    logger.info(f"  Total analyzed domains: {len(processed)}")


if __name__ == "__main__":
    main()
