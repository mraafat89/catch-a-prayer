# Dynamic Prayer Scraper — Redesign

## Two Problems

### 1. Speed: 6.3 hours → target 20 minutes
- Current: sequential (1 site at a time, 10s each)
- Fix: 5 concurrent Playwright browser tabs + 10 concurrent Jina requests
- Math: 2,300 sites ÷ 5 tabs × 8s average = ~37 minutes Playwright
- With Jina handling static sites in parallel: ~20 minutes total

### 2. Extraction: too rigid, misses many formats
The extractor looks for specific patterns and fails on anything slightly different.

#### Formats we miss

**H1-per-line (iccmw.org):**
```
# Fajr
# 5:38 AM
# 6:00 AM
# Dhuhr
# 1:02 PM
# 1:15 PM
```
Each value is its own markdown heading. No table, no separators.

**Bullet list with italics (masjidmanhattan.com):**
```
* Fajr 5:39 AM _Iqamah: 5:54 am_
* Zuhr 1:03 PM _Iqamah: 1:18 pm_
```

**Column header variations:**
- "BEGINNING" instead of "Adhan"/"Azan"
- "JAMMAT" / "JAMAT" instead of "Iqama"/"Iqamah"
- "Salah" as column header
- "Prayer" as column header
- "Starts" / "Start Time"

**Label variations (all mean the same thing):**
- Adhan: "Azan", "Athan", "Adhan", "Begins", "Beginning", "Start", "Prayer Time"
- Iqama: "Iqamah", "Iqama", "Jamaat", "Jammat", "Jamat", "Congregation", "2nd Azan"

---

## Extraction Redesign

### Current approach: pattern matching
Look for prayer name + time on same/nearby line. Fails when format is unexpected.

### New approach: semantic extraction
1. **Strip ALL formatting** — remove markdown (#, *, _, |, ---), HTML tags, emojis, images
2. **Find ALL times** in the text (any HH:MM pattern with optional AM/PM)
3. **Find ALL prayer names** near those times (within 3 lines)
4. **Associate times to prayers** using proximity + order
5. **Determine adhan vs iqama** from context (column headers, labels, position)
6. **Validate** using Islamic logic (ranges, chronological order)

### Key insight: times cluster together
On ANY mosque website, the 5 daily prayer times appear as a CLUSTER of times in ascending order. Whether it's a table, a list, H1 headings, or plain text — the times are always grouped together and go from early morning to late night.

Algorithm:
```
1. Extract every time pattern from the page: [(line_num, time_str, minutes)]
2. Find clusters of 5+ ascending times within 20 lines of each other
3. Map cluster to prayers by position: [fajr, sunrise?, dhuhr, asr, maghrib, isha]
4. If cluster has 10+ times, it's likely adhan + iqama pairs
5. Validate against Islamic ranges per prayer
```

### Concurrency implementation

```python
async def scrape_batch(websites: list, engine):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        sem = asyncio.Semaphore(5)  # 5 concurrent tabs

        async def scrape_one(mosque):
            async with sem:
                page = await browser.new_page()
                try:
                    # ... navigate, wait, extract, validate, save
                finally:
                    await page.close()

        tasks = [scrape_one(m) for m in websites]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

### Classification-based scheduling

After first successful scrape, classify each mosque:
- **MONTHLY**: Posts full month schedule → scrape 1st of each month
- **WEEKLY**: Changes iqama weekly → scrape every Monday
- **SEASONAL**: Same iqama for months → scrape every 2 weeks
- **STATIC**: Never changes → scrape monthly
- **MAWAQIT**: Uses Mawaqit API → daily API call (free, fast)
- **UNSCRAPEABLE**: Image/PDF/no website → never scrape, use calculated

### Daily cron schedule (after redesign)

```
1:00 AM  Monthly pre-calculation (1st of month only)
1:05 AM  Mawaqit API scrape (fast, ~2 min)
1:10 AM  Concurrent Playwright + Jina scrape (~20 min)
         - Prioritize: WEEKLY class on Mondays
         - SEASONAL class every 2 weeks
         - NEW/unclassified mosques daily
1:30 AM  Validation audit
4:00 AM  Database backup
```
