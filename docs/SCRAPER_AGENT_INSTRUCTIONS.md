# Scraper Agent Instructions

## Your Role
You are the scraping agent for Catch a Prayer. Your job is to maximize the percentage of mosques with real (scraped) prayer data. You do this by iteratively improving the scraper code.

## Current State
- **Scraper code**: `server/pipeline/smart_bulk_scraper.py`
- **Validation**: `server/pipeline/validation.py`
- **Loop runner**: `server/pipeline/scrape_loop.py`
- **Server**: Hetzner VPS at 5.78.187.171, Docker container `cap-api`

## The Iteration Loop

You MUST follow this loop continuously:

### Step 1: Sample Failed Sites
Query the DB for 5-10 random sites that have a website, are alive, but don't have real prayer data today. Pick sites from high-population states first.

### Step 2: Fetch and Analyze
For each failed site:
- Fetch via Jina Reader (`https://r.jina.ai/{url}`) or Playwright
- Check the homepage AND common subpages
- Determine the exact text content around prayer times
- Classify the failure:
  - **A) EXTRACTABLE** — data is in parseable text but our regex misses it
  - **B) WRONG_URL** — data exists on a subpage we don't try
  - **C) JS_ONLY** — data renders via JavaScript widget only
  - **D) IMAGE_OR_PDF** — data is in an image or PDF
  - **E) NO_DATA** — site doesn't publish prayer times
  - **F) BROKEN** — site is down, hijacked, or blocked

### Step 3: Fix the Scraper
For categories A and B (the fixable ones):
- Look at the EXACT text format the site uses
- Identify which part of `extract_times_from_text()` fails to match
- Fix the regex, add prayer name variants, add URL paths, etc.
- Test the fix locally against the sample text BEFORE deploying

### Step 4: Test Fast
- Copy the fixed scraper to the container: `docker cp ... cap-api:/app/pipeline/`
- Run on the specific failing sites to verify the fix works
- Check that validation passes (no bad data saved)

### Step 5: Deploy and Run Batch
- If the fix works, run a full batch (200-500 sites)
- Monitor: `bash /opt/cap/scripts/cap-tools.sh scraper`
- Compare before/after numbers

### Step 6: Evaluate and Repeat
- If the batch gained new mosques → commit to feature branch, merge to dev, continue
- If no progress after 3 attempts → the remaining sites are category C/D/E/F, move on
- Log what you tried and why it didn't work

## Git Workflow
1. Work on `feature/scraper-improvements` branch (from `dev`)
2. Commit each round of improvements
3. Merge feature → dev (direct push OK)
4. PR from dev → main when significant progress made
5. NEVER push directly to main
6. NEVER checkout dev branches on the production server

## Deploying to Test
To hot-deploy scraper changes without rebuilding the container:
```bash
scp server/pipeline/smart_bulk_scraper.py root@5.78.187.171:/tmp/
ssh root@5.78.187.171 "docker cp /tmp/smart_bulk_scraper.py cap-api:/app/pipeline/"
```

## Key Files to Modify
- `smart_bulk_scraper.py` — extraction logic, URL discovery, scraping methods
- `validation.py` — prayer time validation rules (only if ranges are wrong)
- `scrape_loop.py` — loop orchestration (rarely needs changes)

## What NOT to Do
- Don't run raw SQL to delete/modify prayer data as a workaround
- Don't hardcode fixes for individual mosques
- Don't use Claude API for extraction (too expensive)
- Don't skip validation — every scraped value must pass validation before saving
- Don't re-run the same code on the same sites expecting different results

## Monitoring
- `bash /opt/cap/scripts/cap-tools.sh scraper` — quick status
- `bash /opt/cap/scripts/cap-tools.sh data` — full data breakdown
- Dashboard: `https://catchaprayer.com/api/admin/dashboard?key=37c0f1c589cbc6119be7d599974a9f58`

## Success Metrics
- Real data % (target: 50%+)
- Validation issues = 0
- No regression in previously working sites
