# Launch Plan — Catch a Prayer

## Vision

The most reliable Muslim prayer app for US & Canada. Users trust it because:
1. Prayer times are real (scraped from mosques), not just calculated
2. Coverage is comprehensive (every mosque in US/CA)
3. Data stays fresh (automated updates)

---

## Scraper Intelligence

### Scrape Frequency by Data Type

Not all mosques need daily scraping. Classify by what their website provides:

| Website Type | Scrape Frequency | Why | Est. Count |
|-------------|-----------------|-----|-----------|
| **Monthly schedule** (Ramadan, Sha'ban calendars) | Monthly | Full month of times posted at once | ~200 |
| **Weekly schedule** (different iqama each week) | Weekly | Times change on Fridays | ~150 |
| **Daily widget** (MasjidNow, Masjidal, calculated) | Weekly | Widget auto-updates, we just read it | ~300 |
| **Static iqama** (same iqama all season) | Monthly | Only changes seasonally (2-4x/year) | ~100 |
| **No website / no data** | Never (use calculated) | Nothing to scrape | ~1,400 |

**Cost impact**: Instead of scraping 922 sites daily (~55min), scrape monthly sites once/month, weekly sites once/week. Total weekly scrape time: ~20 min.

### Mosque Discovery — Closing Coverage Gaps

**Current sources**: OSM Overpass, Hartford Institute, MosqueList.top → 2,448 mosques

**New source: Google Places API grid search**

Strategy: Overlay a grid of search circles across US/Canada population centers.

```
Grid parameters:
- Search radius: 25 km per circle
- Query: "mosque" OR "masjid" OR "islamic center"
- Grid density: Only in Census-designated urban areas (saves queries)
- US urban areas: ~500 circles needed
- Canada urban areas: ~100 circles needed
- Total: ~600 API calls
```

| Item | Cost |
|------|------|
| Google Places Nearby Search | $0.032 per call |
| 600 circles × 1 call each | ~$20 one-time |
| Monthly re-check (new mosques) | ~$5/month (fewer circles, only changed areas) |

**Expected yield**: 500-1,000 additional mosques not in OSM/Hartford/MosqueList. Google Maps has the most comprehensive mosque data because mosque admins claim their Google Business listings.

**Data from Google Places**:
- Name, address, phone, website, Google Place ID
- Opening hours (sometimes includes prayer times)
- User ratings, photos
- Wheelchair accessibility (sometimes)

### Alternative discovery methods (free):
- **Yelp API** — free tier, mosques listed as "Religious Organizations"
- **Facebook Graph API** — many mosques have Facebook pages
- **State non-profit registries** — mosques are 501(c)(3) organizations
- **Muslim directory websites** — salatomatic.com, islamicfinder.org mosque directory

---

## Release Tiers

### Pre-Alpha (Current State — v0.9.0)
- [x] App works on iOS
- [x] 2,448 mosques in DB
- [x] ~280 mosques with real scraped prayer data
- [x] Production server live (catchaprayer.com)
- [x] Trip planning with route-based prayer stops
- [x] Muqeem/Musafir mode with Jam' display

---

### Tier 1 — Internal Beta (v0.9.x) — Target: 1 week

**Goal**: App is reliable enough for you + 10 friends to use daily.

#### Data
- [ ] Daily cron: regenerate calculated times for all 2,448 mosques (ensures every mosque shows times)
- [ ] Weekly cron: run free scraper on all 922 websites
- [ ] Monthly cron: run free scraper + Claude AI on hard cases (when credits available)
- [ ] Classify websites by scrape frequency (monthly/weekly/static)
- [ ] Manually verify top 20 mosques in CA, NY, TX (spot check accuracy)
- [ ] Label data source in the app: "Scraped from mosque website" vs "Estimated — help us get real times"

#### Server
- [ ] Set up all cron jobs on production
- [ ] Daily DB backup cron
- [ ] Basic health monitoring (uptime check script)
- [ ] Server restart resilience (Docker auto-restart confirmed)

#### App
- [ ] Fix any remaining UI bugs from client agent
- [ ] Test full user flow: open app → find mosque → navigate → mark prayed
- [ ] Test trip planning flow end-to-end on production

#### Legal
- [ ] Privacy policy page at catchaprayer.com/privacy
- [ ] Terms of service page at catchaprayer.com/terms

**Release**: TestFlight to 10 friends for 1 week of feedback.

---

### Tier 2 — Public Beta (v0.9.5) — Target: 2-3 weeks after Tier 1

**Goal**: App is ready for strangers to use. Submit to App Store.

#### Data
- [ ] Google Places grid search — discover missing mosques (~$20)
- [ ] Merge new mosques into DB (deduplicate against existing)
- [ ] Run scraper on all new mosque websites
- [ ] Target: 3,000+ mosques with 500+ having real prayer data
- [ ] Jumuah data for top 200 mosques
- [ ] At least 1 mosque with real data in every US state

#### Community Features
- [ ] "Report wrong times" button on mosque card → sends to admin queue
- [ ] "Submit prayer times" form for mosques with no data
- [ ] Submission validation + trust scoring
- [ ] Admin review queue (simple — just you reviewing submissions)

#### App Quality
- [ ] App Store screenshots (6.7" and 6.5" sizes)
- [ ] App Store description, keywords, categories
- [ ] App icon finalized (already done)
- [ ] Onboarding flow? (location permission, mode selection)
- [ ] Crash-free for 7 days on TestFlight

#### Server
- [ ] OpenClaw WhatsApp monitoring working
- [ ] Weekly data quality alerts
- [ ] Automated scraper failure alerts

**Release**: Submit to Apple App Store + Google Play for review.

---

### v1.0.0 — Public Launch — Target: 1-2 weeks after Tier 2

**Goal**: App Store approved, open to all US/Canada users.

- [ ] App Store listing live
- [ ] Google Play listing live
- [ ] Landing page at catchaprayer.com (currently serves the web app)
- [ ] Social media presence (Instagram, Twitter/X)
- [ ] Share with local mosque communities for organic growth

---

### v1.1.0 — First Major Update — Target: 1 month after launch

#### Features
- [ ] **Favorites**: Save your regular mosques
- [ ] **Push notifications**: "Fajr in 15 minutes" (optional)
- [ ] **Mosque admin portal**: Mosque managers can claim & update their listing
- [ ] **Community verified badge**: Mosques with 3+ user-verified schedules

#### Data
- [ ] 4,000+ mosques
- [ ] 1,000+ with real prayer data
- [ ] Coverage in every US state + Canadian province

---

### v1.2.0 — Growth Update — Target: 3 months after launch

#### Features
- [ ] **Ramadan mode**: Iftar countdown, Taraweeh locations, Suhoor alerts
- [ ] **Qibla compass**
- [ ] **Prayer tracker**: Personal prayer log with streaks
- [ ] **Multi-language**: Arabic, Urdu, French (Canada), Turkish

#### Data
- [ ] 5,000+ mosques
- [ ] 2,000+ with real prayer data
- [ ] AI-powered schedule extraction from images/PDFs
- [ ] Mosque photos from Google Places

---

## Timeline

```
Week 0 (now):       Tier 1 work begins
Week 1:             Tier 1 complete → TestFlight to 10 friends
Week 2-3:           Tier 2 work + incorporate feedback
Week 3-4:           Submit to App Store
Week 4-5:           v1.0.0 public launch
Week 6-8:           v1.1.0 development
Month 3:            v1.2.0 (Ramadan features if timing aligns)
```

---

## Cost Budget

### Monthly Operating Costs
| Item | Cost |
|------|------|
| Hetzner VPS (4GB) | $7/mo |
| Domain (catchaprayer.com) | $1/mo (amortized) |
| Anthropic API (monthly Claude scraping) | $10-20/mo |
| Apple Developer Program | $8/mo (amortized) |
| Google Play (one-time $25) | $0/mo |
| **Total** | **~$30/mo** |

### One-Time Costs
| Item | Cost |
|------|------|
| Google Places mosque discovery | $20 |
| Apple Developer enrollment | $99 |
| Google Play enrollment | $25 |
| **Total** | **~$145** |
