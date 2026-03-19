"""
Two-pass scraper test:
  Pass 1 — Jina + Claude: enrichment + find prayer times URL
  Pass 2 — Jina on prayer URL (or Playwright fallback) + Claude: prayer times
"""
import asyncio
import json
import time
import httpx
import anthropic
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings
settings = get_settings()

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
JINA = "https://r.jina.ai/"
MODEL = "claude-haiku-4-5-20251001"

PASS1_PROMPT = """You are extracting mosque information from a website. Do TWO things:

1. Extract ALL enrichment data you can find
2. Find the URL that leads to the prayer times / salah schedule / iqama page

Return ONLY valid JSON:
{
  "enrichment": {
    "address": "full address or null",
    "phone": "phone or null",
    "email": "email or null",
    "jumuah": [{"khutbah_time": "HH:MM 24h", "prayer_time": "HH:MM 24h", "language": "", "imam": ""}],
    "has_womens_section": true/false/null,
    "wheelchair_accessible": true/false/null,
    "denomination": "sunni/shia/null",
    "languages_spoken": [],
    "facilities": [],
    "operating_hours": "string or null"
  },
  "prayer_times": {
    "fajr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "dhuhr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "asr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "maghrib": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "isha": {"adhan": "HH:MM", "iqama": "HH:MM"}
  },
  "prayer_times_url": "URL to the prayer times page if found in nav/links, or null",
  "prayer_times_found_on_homepage": true/false
}

RULES:
- 24h time format (1:30 PM → 13:30)
- null for unknown — NEVER guess
- Look at navigation menus, sidebar, footer for prayer/salah/iqama links
- If prayer times ARE on this page, set prayer_times_found_on_homepage: true"""

PASS2_PROMPT = """Extract prayer times from this mosque page. Return ONLY valid JSON:
{
  "prayer_times": {
    "fajr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "dhuhr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "asr": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "maghrib": {"adhan": "HH:MM", "iqama": "HH:MM"},
    "isha": {"adhan": "HH:MM", "iqama": "HH:MM"}
  },
  "jumuah": [{"khutbah_time": "HH:MM", "prayer_time": "HH:MM", "language": ""}]
}
24h format. null for unknown. NEVER guess."""


async def jina_fetch(url):
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{JINA}{url}", headers={"Accept": "text/markdown"})
            if r.status_code == 200 and len(r.text) > 50:
                return r.text[:12000]
    except:
        pass
    return None


def claude_extract(content, prompt, name):
    try:
        r = client.messages.create(
            model=MODEL, max_tokens=1200,
            messages=[{"role": "user", "content": f"Website for {name}:\n\n{content}\n\n{prompt}"}],
        )
        raw = r.content[0].text.strip()
        if raw.startswith("```"): raw = raw.split("\n", 1)[1]
        if raw.endswith("```"): raw = raw[:-3]
        if raw.startswith("json"): raw = raw[4:]
        tokens = r.usage.input_tokens + r.usage.output_tokens
        return json.loads(raw.strip()), tokens
    except Exception as e:
        return None, 0


async def test_mosque(name, website):
    print(f"\n{'='*70}")
    print(f"🕌 {name}")
    print(f"   {website}")

    total_tokens = 0
    start = time.time()

    # === PASS 1: Homepage ===
    md = await jina_fetch(website)
    if not md:
        print(f"   ❌ Jina failed to fetch homepage")
        return {"name": name, "success": False, "error": "jina_failed"}

    print(f"   Pass 1 (homepage): {len(md)} chars")
    data, tokens = claude_extract(md, PASS1_PROMPT, name)
    total_tokens += tokens

    if not data:
        print(f"   ❌ Claude extraction failed")
        return {"name": name, "success": False, "error": "claude_failed"}

    # Show enrichment
    enr = data.get("enrichment", {})
    jumuah = enr.get("jumuah", [])
    women = enr.get("has_womens_section")
    denom = enr.get("denomination")
    langs = enr.get("languages_spoken", [])
    facs = enr.get("facilities", [])

    print(f"   📋 Enrichment: jumuah={len(jumuah)}, women={women}, denom={denom}")
    if langs: print(f"      Languages: {langs}")
    if facs: print(f"      Facilities: {facs[:5]}{'...' if len(facs) > 5 else ''}")
    if jumuah: print(f"      Jumuah: {jumuah}")

    # Check prayer times from homepage
    pt = data.get("prayer_times", {})
    homepage_prayers = sum(1 for p in ["fajr","dhuhr","asr","maghrib","isha"]
                          if isinstance(pt.get(p), dict) and (pt[p].get("adhan") or pt[p].get("iqama")))

    prayer_url = data.get("prayer_times_url")

    if homepage_prayers > 0:
        print(f"   ✅ Pass 1: Found {homepage_prayers}/5 prayers on homepage!")
        for p in ["fajr","dhuhr","asr","maghrib","isha"]:
            pd = pt.get(p, {})
            if isinstance(pd, dict) and (pd.get("adhan") or pd.get("iqama")):
                print(f"      {p}: adhan={pd.get('adhan')} iqama={pd.get('iqama')}")
        elapsed = time.time() - start
        print(f"   ⏱  {elapsed:.1f}s, {total_tokens} tokens")
        return {"name": name, "success": True, "prayers": homepage_prayers,
                "jumuah": len(jumuah), "enrichment": True, "pass": 1,
                "tokens": total_tokens, "time": elapsed}

    # === PASS 2: Follow prayer times URL ===
    if prayer_url:
        print(f"   🔗 Pass 2: Following prayer URL → {prayer_url}")
        md2 = await jina_fetch(prayer_url)
        if md2 and len(md2) > 100:
            data2, tokens2 = claude_extract(md2, PASS2_PROMPT, name)
            total_tokens += tokens2
            if data2:
                pt2 = data2.get("prayer_times", {})
                prayers2 = sum(1 for p in ["fajr","dhuhr","asr","maghrib","isha"]
                               if isinstance(pt2.get(p), dict) and (pt2[p].get("adhan") or pt2[p].get("iqama")))
                if prayers2 > 0:
                    print(f"   ✅ Pass 2: Found {prayers2}/5 prayers on prayer page!")
                    for p in ["fajr","dhuhr","asr","maghrib","isha"]:
                        pd = pt2.get(p, {})
                        if isinstance(pd, dict) and (pd.get("adhan") or pd.get("iqama")):
                            print(f"      {p}: adhan={pd.get('adhan')} iqama={pd.get('iqama')}")
                    elapsed = time.time() - start
                    print(f"   ⏱  {elapsed:.1f}s, {total_tokens} tokens")
                    return {"name": name, "success": True, "prayers": prayers2,
                            "jumuah": len(jumuah), "enrichment": True, "pass": 2,
                            "tokens": total_tokens, "time": elapsed}
                else:
                    print(f"   ⚠️  Pass 2: Prayer page found but no times extracted (JS-rendered?)")
        else:
            print(f"   ⚠️  Pass 2: Prayer URL fetch failed")
    else:
        print(f"   ⚠️  No prayer times URL found in navigation")

    elapsed = time.time() - start
    print(f"   📋 Enrichment only (no prayer times) — {elapsed:.1f}s, {total_tokens} tokens")
    return {"name": name, "success": True, "prayers": 0, "jumuah": len(jumuah),
            "enrichment": True, "pass": 0, "tokens": total_tokens, "time": elapsed}


async def main():
    mosques = [
        ("Farmington Valley American Muslim Center", "https://www.fvamc.org/"),
        ("Abu Bakr Al-Siddiq Masjid", "https://iasmoosejaw.com/"),
        ("Masjid Al-Farooq", "https://www.isocs.org"),
        ("Islamic Center of Marietta", "https://www.icmga.org"),
        ("Islamic Society of Tampa Bay Area", "https://www.istaba.org"),
        ("Masjid Uqbah", "https://www.uqbah.org"),
        ("Islamic Center of Lake Hiawatha", "https://www.iclh.org"),
        ("Islamic Center of Pittsburgh", "https://www.icp-pgh.org/"),
        ("North Bronx Islamic Center", "https://nbicny.org"),
        ("Masjid Omar Ibn El-Khattab", "https://www.masjidomarohio.org/"),
    ]

    results = []
    for name, url in mosques:
        r = await test_mosque(name, url)
        results.append(r)
        await asyncio.sleep(1)  # rate limit

    # Summary
    print(f"\n{'='*70}")
    print(f"📊 SUMMARY — {len(results)} mosques tested")
    print(f"{'='*70}")

    fetched = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    with_prayers = [r for r in fetched if r.get("prayers", 0) > 0]
    with_enrichment = [r for r in fetched if r.get("enrichment")]
    with_jumuah = [r for r in fetched if r.get("jumuah", 0) > 0]

    print(f"  Fetched successfully: {len(fetched)}/{len(results)}")
    print(f"  Prayer times found:   {len(with_prayers)}/{len(results)}")
    for r in with_prayers:
        print(f"    ✅ {r['name']}: {r['prayers']}/5 (pass {r['pass']})")
    print(f"  Enrichment data:      {len(with_enrichment)}/{len(results)}")
    print(f"  Jumuah found:         {len(with_jumuah)}/{len(results)}")
    print(f"  Failed to fetch:      {len(failed)}/{len(results)}")
    for r in failed:
        print(f"    ❌ {r['name']}: {r.get('error')}")

    total_tokens = sum(r.get("tokens", 0) for r in results)
    total_time = sum(r.get("time", 0) for r in results)
    print(f"\n  Total tokens: {total_tokens:,}")
    print(f"  Estimated cost: ${total_tokens * 0.001 / 1000:.4f} (Haiku)")
    print(f"  Total time: {total_time:.0f}s ({total_time/len(results):.1f}s avg)")


if __name__ == "__main__":
    asyncio.run(main())
