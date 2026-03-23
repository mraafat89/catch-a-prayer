# Static Info Enrichment System — Design

## Goal
Every mosque has accurate metadata that rarely changes: denomination, facilities, contact info.

## Implementation: `pipeline/enrich_from_google.py`

### Modes
- `--all`: Enrich mosques missing website or phone
- `--refresh`: Refresh ALL mosques (update stale data)
- `--batch N`: Limit to N mosques
- `--dry-run`: Estimate cost only

### What it does
1. Fetches Google Place Details for each mosque with google_place_id
2. Saves: website, phone, formatted_address, wheelchair, city, state, timezone, country
3. Detects closed mosques via `business_status = CLOSED_PERMANENTLY`
4. Uses COALESCE — fills gaps without overwriting existing data
5. Parses state/timezone from formatted_address via `geo_utils.py`

### Schedule
- Every 6 months: `--refresh` (update all mosques)
- After discovery: `--all` (enrich new mosques)

### Cost
~$0.017 per call. ~3,800 mosques = ~$65 (within $200 free monthly credit).
