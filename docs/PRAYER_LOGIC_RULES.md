# Prayer Logic Rules

Definitive rules for prayer catching status, prayer tracking, travel planning, and edge cases. This is the source of truth — code and tests must follow these rules exactly.

---

## 1. Prayer Periods

Five daily prayers in order: **Fajr, Dhuhr, Asr, Maghrib, Isha**.

Each prayer has an **adhan** (start), **iqama** (congregation start), and **period end**:

| Prayer | Period starts at | Congregation window | Period ends at |
|--------|-----------------|-------------------|---------------|
| Fajr | Fajr adhan | Iqama → iqama + 15 min | Sunrise |
| Dhuhr | Dhuhr adhan | Iqama → iqama + 15 min | Asr adhan |
| Asr | Asr adhan | Iqama → iqama + 15 min | Maghrib adhan |
| Maghrib | Maghrib adhan (= sunset) | Iqama → iqama + 15 min | Isha adhan |
| Isha | Isha adhan | Iqama → iqama + 15 min | **Next day's Fajr adhan** |

### Isha Crosses Midnight

Isha is the only prayer whose period crosses midnight. Rules:

- Isha period starts at Isha adhan (~8-10 PM depending on season/location)
- Isha period ends at the **next day's Fajr adhan** (~5-6 AM)
- Praying Isha after midnight is **discouraged (makruh)** but still valid
- The UI should note: "Discouraged after midnight" when displaying Isha status past 12:00 AM
- When displaying `period_ends_at` for Isha, show the time with a "(next day)" suffix if it falls before the current time of day

### When All Prayers Have Passed

After Isha congregation ends but before Fajr:

- The app shows: **"Next: Fajr tomorrow at {time}"** with the leave-by time to catch Fajr with the Imam
- This replaces the current behavior of showing "Isha — make it up"
- The Fajr time comes from tomorrow's prayer schedule (or calculated if not scraped)

---

## 2. Catching Status

Six possible statuses, in priority order:

| Status | Condition | Urgency |
|--------|-----------|---------|
| `can_catch_with_imam` | Arrive before or at iqama | `normal` (or `high` if <15 min) |
| `can_catch_with_imam_in_progress` | Arrive after iqama but within congregation window (iqama + 15 min). **Only returned when current time >= iqama** (congregation has actually started) | `high` |
| `can_pray_solo_at_mosque` | Congregation ended, prayer period still active | `low` |
| `pray_at_nearby_location` | Cannot reach mosque before period ends, period still active | `low` |
| `missed_make_up` | Prayer period has ended | — |
| `upcoming` | Prayer period has not started yet | `low` |

### Upcoming Window

A prayer is shown as `upcoming` only if the **adhan is within 2 hours** from now. This is measured from adhan time, NOT iqama time.

```
show_upcoming = (adhan_minutes - current_minutes) <= 120 AND (adhan_minutes - current_minutes) > 0
```

### Catchable Prayers Array

`catchable_prayers` returns all prayers with an actionable status, ordered by prayer time (Fajr → Isha):

- Include: `can_catch_with_imam`, `can_catch_with_imam_in_progress`, `can_pray_solo_at_mosque`, `pray_at_nearby_location` (always)
- Include: `upcoming` only if adhan is within 2 hours
- Exclude: `missed_make_up`
- Exception: If EVERY prayer has passed, return one `missed_make_up` entry for Isha (plus "Next: Fajr tomorrow" — see section 1)

### Missing Data Handling

- If a mosque has **no adhan time** for a prayer (neither scraped nor calculated): skip that prayer entirely — do not crash, do not return a status
- If a mosque has **iqama but no adhan**: use `iqama - 15 minutes` as estimated adhan
- If a mosque has **adhan but no iqama**: use standard offsets (Fajr +20, Dhuhr +15, Asr +10, Maghrib +5, Isha +15)
- If a mosque has **no prayer schedule at all**: calculate adhan from coordinates, estimate iqama. Show with `source: "calculated"` and `confidence: "low"`

---

## 3. Prayed Tracker

### Storage

- Stored in localStorage keyed by date: `cap_prayed_{YYYY-MM-DD}`
- The key uses the **Islamic prayer day** which runs from Fajr to Fajr:
  - Before Fajr adhan: use yesterday's date key
  - After Fajr adhan: use today's date key
- This means Isha prayed at 11 PM on March 20 and Isha prayed at 1 AM on March 21 both use the key `cap_prayed_2026-03-20`

### Mode-Specific Behavior

**Muqeem mode**: Track individual prayers — Fajr, Dhuhr, Asr, Maghrib, Isha.

**Musafir mode**: Track prayer pairs — Dhuhr+Asr, Maghrib+Isha (and Fajr individually).

### Sequential Inference (applies to BOTH modes)

Prayers are performed in order. If a later prayer is marked as prayed, all earlier prayers in the same pair are implicitly prayed:

- If Asr is marked → Dhuhr is implicitly marked (you cannot pray Asr without having prayed Dhuhr)
- If Isha is marked → Maghrib is implicitly marked
- If Dhuhr is marked → Asr is NOT implicitly marked (Dhuhr comes first)
- If Maghrib is marked → Isha is NOT implicitly marked

### Mode Switching

When switching between Muqeem and Musafir:

**Muqeem → Musafir:**
- The Set of prayed prayers carries over
- Apply sequential inference: if "asr" is in the Set, add "dhuhr". If "isha" is in the Set, add "maghrib"
- Persist the expanded Set to localStorage
- A pair is fully complete only if BOTH prayers are in the Set
- If only the first prayer is marked (e.g., "dhuhr" without "asr"), show the pair as incomplete — the banner should prompt "Did you pray Dhuhr + Asr?"

**Musafir → Muqeem:**
- The Set of prayed prayers carries over as-is (both individual names are in the Set when toggled via `togglePrayedPair`)
- No special handling needed — the individual prayers are already tracked

### After All Prayers Prayed

When all 5 prayers are marked as prayed:
- The PrayedBanner disappears (no more prayers to track)
- Mosque cards show normal status without prayed-state filtering
- After Isha period ends, show "Next: Fajr tomorrow" card

---

## 4. Musafir (Traveler) Mode

### When to Suggest Musafir Mode

- Suggest switching to Musafir when a trip exceeds **80 km** (~48 miles)
- Show distance in **km** for Canadian users, **mi** for US users (auto-detected from device timezone)
- The suggestion is a modal dialog, not automatic — user must explicitly choose

### Prayer Combining (Jam')

In Musafir mode, prayers can be combined in pairs:
- **Dhuhr + Asr** (Jam' Taqdeem: both at Dhuhr time, or Jam' Ta'kheer: both at Asr time)
- **Maghrib + Isha** (Jam' Taqdeem: both at Maghrib time, or Jam' Ta'kheer: both at Isha time)
- **Fajr** is always prayed individually (no combining)

### Display Rules for Combinations

Only show the **first unresolved pair** (ordered: Dhuhr+Asr before Maghrib+Isha):

- If Dhuhr+Asr pair is not fully prayed → show only Dhuhr+Asr options
- Once Dhuhr+Asr pair is fully prayed → show Maghrib+Isha options
- If both pairs are fully prayed → show nothing (or "Next: Fajr tomorrow" after Isha period)

**Taqdeem vs Ta'kheer:**
- Before second prayer's adhan (before Asr adhan / before Isha adhan) → show **Jam' Taqdeem** (combine early)
- After second prayer's adhan, before period ends → show **Jam' Ta'kheer** (combine late)
- After period ends → pair is missed

---

## 5. Travel Planning

### Trip Duration Limits

- **Maximum supported trip: 3 days** (72 hours)
- If a trip exceeds 3 days: show a message "This trip is longer than 3 days. Please break it into shorter segments for accurate prayer planning."
- Trips under 3 days must correctly handle prayers across multiple calendar days

### Multi-Day Trip Rules

For trips spanning multiple days:
- Each calendar day has its own prayer schedule (different sunrise/sunset times)
- The planner must track which DATE each prayer belongs to
- Prayer times come from the schedule for that specific date at that specific location
- Timezone changes during the trip must be accounted for (e.g., driving from Eastern to Central time)

### Timezone Handling

- All prayer times in the backend are in the **mosque's local timezone**
- The `current_time` used for comparisons must be converted to the **mosque's timezone**
- For travel plans crossing timezones:
  - Origin schedule uses origin timezone
  - Destination schedule uses destination timezone
  - En-route mosques use their own timezone
  - `dep_min` and `arr_min` must be converted to each mosque's timezone when comparing against that mosque's schedule

### Deep Links / Shared Destinations

When a destination URL is received via deep link or share:
- Set the destination ONLY — do NOT change the travel mode
- The user's current mode (Muqeem/Musafir) stays unchanged
- If the trip turns out to be >80 km, the long-trip modal will suggest switching (same as manual entry)

---

## 6. Data Source Transparency

Every prayer time displayed must include its source. Labels:

| Source | Display label |
|--------|--------------|
| `mosque_website_html` | "From mosque website" |
| `mosque_website_js` | "From mosque website" |
| `mosque_website_image` | "From mosque schedule (image)" |
| `mosque_website_pdf` | "From mosque schedule (PDF)" |
| `islamicfinder` | "From IslamicFinder" |
| `aladhan_mosque_db` | "From Aladhan database" |
| `user_submitted` | "Community-submitted" |
| `calculated` | "Calculated (astronomical) — verify with mosque" |
| `estimated` | "Estimated — congregation time not confirmed" |

When `data_freshness` is null (calculated times): display "Calculated just now".

---

## 7. Unit System

- **Canada**: metric (km, m) — auto-detected from Canadian IANA timezone
- **US**: imperial (mi, ft) — everything else
- Applies to: search radius slider, distance labels, long-trip modal, route distance

---

## 8. Auto-Refresh

- Mosque data refreshes every **5 minutes** while the app is open
- On network error: **do not retry immediately** — use exponential backoff (5 min → 10 min → 20 min), max 3 retries
- Reset backoff on successful fetch or manual user action
- Do not auto-refresh while trip planner form is open (editing state)

---

## 9. Edge Cases Summary

| Scenario | Expected Behavior |
|----------|-------------------|
| App open across midnight | Prayed state persists (Fajr-to-Fajr key), "Next: Fajr tomorrow" shown |
| All prayers passed (11 PM) | Show "Next: Fajr tomorrow at {time}" with leave-by |
| Isha after midnight | Status: `can_pray_solo_at_mosque`, note "Discouraged after midnight" |
| No mosques found | Show "No mosques within {radius}" with suggestion to increase radius |
| No mosques + spots exist | Show spots list, hide mosque-specific UI |
| Mosque has no prayer data | Calculate from coordinates, show with low confidence |
| Mosque has only iqama (no adhan) | Estimate adhan = iqama - 15 min |
| Trip crosses timezone | Convert all times to mosque's local tz before comparing |
| Trip > 3 days | Show error message, ask user to break into segments |
| Trip > 80 km in Muqeem | Show Musafir suggestion modal |
| Deep link received | Set destination only, do NOT change mode |
| User switches Muqeem → Musafir | Apply sequential inference, persist expanded Set |
| User switches Musafir → Muqeem | Carry over prayed Set as-is |
| DST transition during trip | Use timezone-aware datetimes (ZoneInfo), not naive offsets |
| Network offline | Show stale data, exponential backoff on refresh |
| `next_catchable` is null | Mosque still appears in list, no status badge shown |
| `catchable_prayers` is empty array | Mosque appears, no catching status displayed |
