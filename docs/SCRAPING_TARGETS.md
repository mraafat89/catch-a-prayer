# Scraping Targets — High Value Mosques

## Stats (March 21, 2026)
- **621 mosques** with alive websites but no real prayer data
- Prioritized by population density (where users will actually search)
- Already attempted by free scraper (BeautifulSoup) — failed to extract

## Why They Failed
Based on analysis of sample failures:

| Failure Pattern | % of Sites | Solution |
|----------------|-----------|---------|
| Prayer times on subpage, not homepage | ~35% | Nav link discovery + Jina/Playwright on subpage |
| JS-heavy SPA (Wix, React, Squarespace) | ~20% | Longer Playwright wait or Jina with correct URL |
| Prayer times in images/PDFs | ~15% | OCR (future) or Claude Vision |
| Site doesn't publish times at all | ~15% | No solution — need community submissions |
| Bot protection (Cloudflare) | ~10% | Rotate user agents, use residential proxy |
| Domain hijacked/broken | ~5% | Skip (already flagged as dead) |

## Priority Tiers

### Tier 1 — Major Metro (highest user density)
- NYC, LA, Chicago, Houston, Dallas, SF, DC, Dearborn MI
- ~50 mosques

### Tier 2 — Large Muslim Communities
- NJ, Atlanta, Miami, Philadelphia, Toronto, San Diego, Minneapolis
- ~80 mosques

### Tier 3 — All Other States
- Remaining 491 mosques across US + Canada

## Scraping Approach
1. **Playwright nav discovery** → find the actual prayer page URL
2. **Jina Reader** on the discovered URL → get clean text (free, fast, no Chromium)
3. **Regex extraction** → same patterns as smart_bulk_scraper
4. **Validation** → strict time range checks before saving
5. **Claude AI fallback** → for Tier 1 failures only (top ~50 mosques worth the cost)

## When to Re-run
- Weekly: re-scrape all Tier 1 mosques (prayer times change weekly)
- Monthly: re-scrape Tier 2+3
- After Ramadan: many mosques update their schedules
