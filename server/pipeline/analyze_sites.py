"""Quick analysis: what % of remaining sites have extractable prayer data via Jina?"""
import httpx, asyncio, re, os, sys
from sqlalchemy import create_engine, text

TIME_PAT = re.compile(r"\d{1,2}:\d{2}")
PRAYER_PAT = re.compile(
    r"fajr|dhuhr|zuhr|asr|maghrib|isha|iqama|salah|prayer.time|athan|adhan",
    re.IGNORECASE,
)

pg_pass = os.environ.get("POSTGRES_PASSWORD", "cap")
engine = create_engine(f"postgresql+psycopg2://cap:{pg_pass}@db:5432/catchaprayer")

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 50

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT m.website FROM mosques m
        JOIN scraping_jobs sj ON sj.mosque_id = m.id AND sj.website_alive = true
        WHERE m.is_active AND m.website IS NOT NULL
          AND m.website NOT LIKE '%facebook%' AND m.website NOT LIKE '%instagram%'
          AND m.website NOT LIKE '%youtube%' AND m.website NOT LIKE '%yelp%'
          AND m.website NOT LIKE '%x.com%'
          AND m.id NOT IN (SELECT mosque_id FROM prayer_schedules
                           WHERE date = CURRENT_DATE AND fajr_adhan_source NOT IN ('calculated'))
        ORDER BY random() LIMIT :lim
    """), {"lim": LIMIT}).fetchall()
urls = [r[0] for r in rows]
print(f"Analyzing {len(urls)} sites via Jina Reader...")


async def analyze():
    cats = {
        "homepage_data": [],
        "subpage_data": [],
        "prayer_words_few_times": [],
        "no_prayer_content": [],
        "jina_blocked": [],
    }
    sem = asyncio.Semaphore(5)

    async def check(url):
        base = url.rstrip("/")
        async with sem:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                try:
                    r = await c.get(
                        f"https://r.jina.ai/{url}",
                        headers={"Accept": "text/plain"},
                    )
                    if r.status_code != 200:
                        return "jina_blocked", url, f"HTTP {r.status_code}"
                    txt = r.text
                    times_count = len(TIME_PAT.findall(txt))
                    has_prayer = bool(PRAYER_PAT.search(txt))

                    if times_count >= 5 and has_prayer:
                        return "homepage_data", url, f"{times_count} times"

                    # Try subpages
                    for path in [
                        "/prayer-times", "/prayer-time", "/prayers",
                        "/iqama", "/salah-times", "/prayer-schedule",
                        "/schedule", "/services/prayer-times",
                    ]:
                        try:
                            r2 = await c.get(
                                f"https://r.jina.ai/{base}{path}",
                                headers={"Accept": "text/plain"},
                            )
                            if r2.status_code == 200 and len(r2.text) > 200:
                                tc = len(TIME_PAT.findall(r2.text))
                                hp = bool(PRAYER_PAT.search(r2.text))
                                if tc >= 5 and hp:
                                    return "subpage_data", url, f"{path} ({tc} times)"
                        except Exception:
                            continue

                    if has_prayer:
                        return "prayer_words_few_times", url, f"{times_count} time patterns"
                    return "no_prayer_content", url, ""
                except Exception as e:
                    return "jina_blocked", url, str(e)[:60]

    results = await asyncio.gather(*[check(u) for u in urls])
    for cat, url, detail in results:
        cats[cat].append((url, detail))

    print()
    for cat in [
        "homepage_data", "subpage_data",
        "prayer_words_few_times", "no_prayer_content", "jina_blocked",
    ]:
        items = cats[cat]
        pct = len(items) * 100 // max(len(urls), 1)
        print(f"{cat}: {len(items)} ({pct}%)")
        for url, detail in items[:5]:
            print(f"  {url}  {detail}")


asyncio.run(analyze())
