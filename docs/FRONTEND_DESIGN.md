# Frontend Design

## Design Philosophy

This app is used on a mobile phone, often while standing outside or in a car. The design must be:

- **Glanceable**: The most important information (can I catch this prayer? how long do I have?) must be readable in 2 seconds without tapping anything
- **One-handed**: All key interactions reachable with one thumb
- **Low cognitive load**: Use color + icon to communicate status instantly, not just text
- **Fast**: No spinners on the main view — show stale data immediately, update silently

---

## Layout Structure

### Mobile (primary — single column)

```
┌─────────────────────────────────────────┐
│ [pin] Catch a Prayer  [🚗 Travel] [⚙️]  │  teal gradient header, white text
│       "Can catch Asr at Al-Noor"        │  subtitle: top mosque status
├─────────────────────────────────────────┤
│                                         │
│   Leaflet Map (CartoDB Positron tiles)  │  ~40% viewport height
│   — status-colored teardrop pins        │  collapsible
│   — teal user dot + pulse ring          │
│                                         │
├─────────────────────────────────────────┤
│  ▼ Hide map                             │  subtle text toggle
├─────────────────────────────────────────┤
│  Nearby Mosques [5]                     │  pill count badge
│  ┌─────────────────────────────────────┐│
│  │ Mosque card (rounded-2xl, shadow)  ││  see card design below
│  └─────────────────────────────────────┘│
│  Prayer Spots [2]         [+ Add spot]  │
│  ┌─────────────────────────────────────┐│
│  │ Prayer spot card                   ││
│  └─────────────────────────────────────┘│
│  ┌─────────────────────────────────────┐│
│  │ Last resort card (gray)            ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
```

### Header

The header uses a teal gradient (`from-teal-700 to-teal-600`) with a drop shadow. All text and icons are white.

```
┌──────────────────────────────────────────────────────┐
│  [pin icon]  Catch a Prayer          [🚗 Travel] [⚙]  │
│              Can catch Asr at Al-Noor                 │
└──────────────────────────────────────────────────────┘
```

- **Left**: `logo_pin.png` (teal pin, white-inverted) + app name bold + one-line subtitle (top mosque status or mosque count)
- **Right**: Travel mode quick-toggle pill + settings icon button
- **Travel toggle**: Pill button in header showing **current mode** — `🏠 Muqeem` (grey outline, off) or `✈️ Musafir` (solid white with teal text, on). Tap to switch. Toggling immediately re-fetches mosques with `travel_mode: true/false`. "Muqeem" (مقيم) = resident/home mode; "Musafir" (مسافر) = traveler mode that enables prayer combining (Jam').
- **Settings icon**: `icon_settings.png` with `brightness-0 invert` CSS to render white on the teal background

### Desktop (secondary — two column)
Map takes 60% width on the left, mosque list 40% on the right. Same cards.

---

## Mosque Card

The card must communicate everything needed to decide whether to go — without tapping.

```
┌──────────────────────────────────────────────────────┐
│ 🟢  Masjid Al-Noor                      12 min away │
│     Asr: Adhan 4:15 PM · Iqama 4:25 PM              │
│     ✅ Can catch with Imam — leave by 4:13 PM        │  ← colored status
│     📍 From mosque website                           │  ← data source
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ 🟡  Islamic Center of Raleigh           18 min away │
│     Asr: Adhan 4:15 PM · Iqama 4:30 PM              │
│     ⚠️  Hurry — 7 min left to catch Imam             │
│     📍 From mosque website                           │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ 🔵  Al-Farooq Masjid                    8 min away  │
│     Asr: Adhan 4:15 PM · Iqama 4:20 PM   [Ismaili] │  ← denomination badge
│     🤲 Congregation ended — can pray solo until 6:47 PM  │
│     📍 From mosque website                           │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ 🔵  Al-Farooq Masjid                    8 min away  │
│     Fajr: Adhan 5:32 AM · Iqama 6:20 AM             │
│     🤲 Congregation will be over by the time you arrive  │
│        — can still pray solo until 7:15 AM           │
│     📍 From mosque website                           │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ ⚪  Masjid Al-Rahman                   35 min away  │
│     Asr: Adhan 4:15 PM · Iqama ~4:25 PM   [Shia]   │  ← denomination badge
│     ❌ Cannot reach before Asr ends                  │
│     📍 Estimated — congregation time not confirmed   │  ← distinct visual style
└──────────────────────────────────────────────────────┘
```

### Multiple Prayer Statuses per Card

Each mosque card shows **up to two prayer status rows**: the **current** prayer (whose window is active) and the **next** prayer (upcoming). The order of these two rows is time-sensitive — whichever prayer is **more immediately actionable** is shown first (the **primary row**) and receives stronger visual treatment.

#### Prayer Row Ordering

Two states drive which row appears first:

| Phase | Primary row (top, bold) | Secondary row (bottom, muted) |
|---|---|---|
| **Early in current period** | Current prayer | Next prayer (informational) |
| **Late in current period** | Next prayer (act soon) | Current prayer + "mark as prayed" |
| **Dead time** (between Fajr end and Dhuhr start) | Upcoming prayer (Dhuhr) | — |

The **switch point** (early → late) is computed **dynamically from today's actual prayer times at the user's location** — it is never a fixed clock time. Prayer intervals vary significantly by season and latitude (e.g., in summer at high latitudes Asr can be only 1 hour after Dhuhr, while in winter it may be 4+ hours), so any hardcoded threshold would be wrong.

Formula:

```
switch_point(prayer) = adhan_time(prayer) + (period_end_time(prayer) − adhan_time(prayer)) / 2
```

| Current prayer | period_end_time used | Notes |
|---|---|---|
| Fajr | `sunrise` | Window varies from ~45 min (high lat summer) to ~2 h (winter) |
| Dhuhr | `asr_adhan` | Interval narrows dramatically in summer |
| Asr | `maghrib_adhan` | Interval narrows in summer, lengthens in winter |
| Maghrib | `isha_adhan` | Relatively stable but still varies |
| Isha | `fajr_adhan` (next day) | **Override: use midnight (00:00) instead of midpoint** — Isha's window can span 6–10 h depending on season; midnight is the natural UX divide regardless |

In **dead time** (after Fajr ends at sunrise, before Dhuhr starts — roughly 7 AM to 12:30 PM), there is no active current prayer. The card shows only the upcoming Dhuhr row as primary with no secondary row. The backend must return the next upcoming prayer as `next_catchable` in dead time regardless of how far away it is — the 2-hour upcoming window only applies when there is already an active or recently-missed prayer to compete with.

**Example at 12:46 AM** (after Isha adhan ~9 PM, past midnight switch point):
```
┌──────────────────────────────────────────────────────┐
│ 🟢  Masjid Al-Noor                      12 min away │
│                                                      │
│  ── PRIMARY ──────────────────────────────────────── │
│  🌅 Fajr at 5:32 AM · Iqama ~5:52 AM               │  ← next prayer, bold, teal bg
│                                                      │
│  ── secondary ────────────────────────────────────── │
│  🌙 Isha — can pray solo until 5:32 AM    [✓ Prayed] │  ← current, muted, inline button
│                                                      │
│  ✓ From mosque website · today                       │
└──────────────────────────────────────────────────────┘
```

**Example at 1:15 PM** (Dhuhr started at 12:58 PM, switch point not yet reached at ~2:30 PM):
```
┌──────────────────────────────────────────────────────┐
│ 🟢  Masjid Al-Noor                      12 min away │
│                                                      │
│  ── PRIMARY ──────────────────────────────────────── │
│  🕌 Dhuhr · Iqama 1:05 PM — catch with Imam now     │  ← current, bold, teal bg
│  Leave by 1:03 PM                    [✓ Prayed]     │
│                                                      │
│  ── secondary ────────────────────────────────────── │
│  🕌 Asr at 4:28 PM                                  │  ← next, muted, small
│                                                      │
│  ✓ From mosque website · today                       │
└──────────────────────────────────────────────────────┘
```

#### Visual Distinction Between Primary and Secondary Rows

| Property | Primary row | Secondary row |
|---|---|---|
| Background | Colored per status (teal-50, green-50, amber-50…) | `slate-50` / neutral |
| Text weight | `font-semibold` on prayer name | `font-normal`, slate-500 |
| Font size | `text-sm` | `text-xs` |
| Left border accent | 3px solid, matches status color | none |
| "✓ Prayed" button | Shown inline on the **current prayer row** (whether primary or secondary) | — |
| Status icon | Full-size icon (w-8 h-8) | Small dot only |

The primary row should feel like a **call to action card** — immediately scannable. The secondary row is a quiet note.

#### "Mark as Prayed" — Inline + Global

**Inline button** on the current prayer row (small pill, grey-outlined):
```
  🌙 Isha — can pray solo until 5:32 AM    [✓ Prayed]
```

**Global chip** at the top of the mosque list (appears after marking):
```
┌──────────────────────────────────────────────────────┐
│  ✓ I already prayed Isha today    [Undo]             │  ← global chip, floats above list
└──────────────────────────────────────────────────────┘
```

Both the inline button and the global "I already prayed X" chip trigger the same state update. Rules:
- The "✓ Prayed" button is shown when the prayer's adhan has already occurred (cannot pre-mark future prayers) — this includes `missed_make_up` prayers in the detail sheet
- Marking hides the prayer row from **all** mosque cards and from the global chip target
- `prayedToday` is stored in `localStorage` keyed by `prayer + date` — resets at midnight
- "Undo" in the global chip restores the row on all cards
- This is **client-side only** — no API call needed

The "✓ Prayed" button also appears in the **mosque detail sheet** on the status badge when `nc.status === 'missed_make_up'`. This is the primary affordance for "I already prayed Fajr" during dead time.

### Data Source Indicator

Every mosque card and detail sheet shows a one-line data source badge below the status message. It tells the user how trustworthy the times are.

**Source classification** (from `adhan_source` / `iqama_source` fields):

| Source value(s) | Indicator | Style |
|---|---|---|
| `mosque_website_html`, `mosque_website_js` | `✓ From mosque website` | green text, small |
| `islamicfinder` | `From IslamicFinder` | grey text |
| `calculated`, `tier5_calculated`, or any unrecognized | `~ Estimated times` | amber text + tooltip on tap: "Congregation time not confirmed — based on calculated prayer window" |
| Mixed (adhan from website, iqama estimated) | `~ Iqama estimated` | amber text |

**Freshness suffix** (from `data_freshness` field): append `· updated today` / `· 3 days ago` etc. when source is not estimated.

Examples:
- `✓ From mosque website · updated today`
- `✓ From mosque website · 3 days ago`
- `~ Estimated times` (no freshness suffix — not applicable)
- `~ Iqama estimated` (adhan verified but iqama is calculated)

The indicator is shown:
- On the **mosque card** (compact, 1 line, below status message)
- In the **mosque detail bottom sheet** below the prayer times table (slightly more detailed)

### Denomination Badge

- Shown as a small badge inline on the card (grey text on light background — not prominent, informational only)
- Possible values: `Sunni` / `Shia` / `Ismaili` / `Ahmadiyya`
- Only shown when denomination is confirmed — never shown as blank or "Unknown"
- Sunni badge is shown when confirmed; omitted when unconfirmed (the majority of mosques are Sunni, so absence is not misleading)

### Card Status Colors and Icons

Each status has a background color, border, text color, and a **custom PNG icon** (top-right of card):

| Color | Icon file | Status | Meaning |
|---|---|---|---|
| Green | `icon_pray_imam.png` | Can catch with Imam | Leave now/soon |
| Amber | `icon_pray_imam.png` | Congregation in progress | Hurry, minutes left |
| Blue | `icon_pray_solo.png` | Can pray solo | Congregation ended (or will be over before you arrive), period still active |
| Orange | `icon_pray_nearby.png` | Pray nearby | Can't reach mosque in time |
| Grey | `icon_mosque_nav.png` | Cannot catch / Upcoming | Period ends before arrival |

The status icon is displayed at `w-10 h-10` in the top-right corner of every mosque card and inside the status badge in the detail sheet. Dot emojis (🟢🟡🔵🟠⚪) are retained in `STATUS_CONFIG` as a fallback but the icon takes visual precedence.

---

## Prayer Spots (Non-Mosque Prayer Locations)

When a mosque isn't reachable in time, or simply isn't nearby, the app shows community-verified non-mosque prayer spots. These are shown below the mosque list section.

### What counts as a prayer spot

- Dedicated prayer rooms (airports, malls, hospitals, universities)
- Halal restaurants with a prayer area (community-verified first)
- Community halls or Islamic cultural centers (not mosques)
- Highway rest areas
- Library quiet rooms / study rooms
- Any other location the community has verified as suitable

Users can submit new spots directly from the app using the "+ Add Spot" button on the map.

### Prayer Spot Cards

Prayer spot cards look similar to mosque cards but with a distinct icon and verification badge:

```
┌──────────────────────────────────────────────────────┐
│ 🔶  Sunnyvale Library — Quiet Room       0.4 km away │
│     Prayer room · Indoor · Wudu ✓                    │
│     ✅ Verified by 7 users                           │
│     Mon-Sat 10am–9pm                                 │
│     [  ✓ I prayed here  ]                            │  ← quick-confirm button
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ 🔶  Yahoo Campus Building D              1.2 km away │
│     Campus prayer room · Wudu ✓ · Men & Women        │
│     ⚠️ Reported by 1 user — tap to confirm            │
│     [  ✓ I prayed here  ]                            │  ← prominent on unverified spots
└──────────────────────────────────────────────────────┘
```

**Icons:**
- 🔶 Orange diamond = prayer spot (vs 🟢🟡🔵 circles for mosques)
- Wudu ✓ = bathroom with running water confirmed
- Wudu ? = wudu facilities unknown

**Verification badge styles:**
| Condition | Badge | Card style |
|---|---|---|
| 0 external confirms (submitter only) | Not shown to other users | — |
| 1–2 net positive | "Reported by N users — tap to confirm" (grey, italic) | Muted, with confirm button |
| 3–9 net positive | "Verified by N users" (green check) | Normal, with confirm button |
| ≥10 net positive | "Highly verified" (green bold) | Normal, confirm button hidden (already trusted) |

**Quick-confirm button**: A `[✓ I prayed here]` button appears directly on the spot card for spots with fewer than 10 verifications. Tapping it calls `POST /api/spots/{id}/verify` with `is_positive: true` and the user's `session_id`. After confirming, the button changes to `✓ Confirmed` (disabled, stored in `confirmedSpots` in localStorage). No need to open the detail sheet for a basic confirmation.

Rejected spots are never shown.

### Last Resort — "Pray Anywhere" Card

If the prayer period is still active but no mosque AND no prayer spot is reachable in time, the app shows a "Pray anywhere" card at the bottom of the list:

```
┌──────────────────────────────────────────────────────┐
│ 🟠  Pray where you are               Asr — 47 min    │
│     No mosque or prayer spot reachable in time.      │
│     Find a quiet spot: parking lot, gas station,     │
│     or any private corner.                           │
│                                                      │
│     [  🧭 Qibla Direction: 58° NE  ]                 │
│     [ + Add a prayer spot you know ]                 │
└──────────────────────────────────────────────────────┘
```

The Qibla direction is calculated offline from the user's GPS coordinates (no API needed). The "+ Add a prayer spot" deeplinks directly to the spot submission form.

### Spot Submission Form

Accessible from: map "+" button, prayer spot cards "Suggest edit", or "Pray anywhere" card CTA.

```
┌──────────────────────────────────────────────────────┐
│  Add a Prayer Spot                              ✕    │
│                                                      │
│  Location *                                          │
│  ┌──────────────────────────────────────── ⌖ GPS ┐  │  ← green chip: resolved address + GPS refresh btn
│  │ 📍 123 Main St, Sunnyvale, CA                 │  │
│  └───────────────────────────────────────────────┘  │
│  [ Search for an address…              ]             │  ← geocode lookup (same as trip planner)
│    📍 Apple Park, Cupertino, CA                      │  ← dropdown suggestions
│    📍 123 Main St, San Jose, CA                      │
│                                                      │
│  Name *  _________________________________           │
│          "e.g. Safeway quiet corner, Room 2B"        │
│                                                      │
│  Type    [ Prayer room ▼ ]                           │
│                                                      │
│  Wudu?   [ Unknown ▼ ]   Indoor?  [ Yes ▼ ]   Access [ All ▼ ]
│                                                      │
│  Hours (optional)  _______________________________   │
│                                                      │
│  Website (optional)  _____________________________   │
│                                                      │
│  Notes (optional)  _______________________________   │
│                                                      │
│  [ Submit Spot ]                                     │
│                                                      │
│  Anonymous — we don't collect your name or email.    │
└──────────────────────────────────────────────────────┘
```

**Location entry**: A single address search input, pre-populated with the reverse-geocoded GPS address when the form opens. The user can edit or replace it by typing and selecting from autocomplete suggestions. No separate "resolved location" banner is shown above the input — the input itself shows the current location. Coordinates (`spotLat`/`spotLng`) are set from GPS on open, and updated when the user selects from suggestions.

**Trip planner "From" field**: When the input has user-entered text, a small `×` clear button appears at the right edge of the input row. Tapping it clears the typed origin and resets to GPS (shown as placeholder "Current location"). There is no separate GPS icon button to the side — clearing the field is equivalent to "use GPS".

### Spot Verification Flow

When a user taps a prayer spot card, the detail sheet shows a "Verify this spot" section:

```
┌──────────────────────────────────────────────────────┐
│  ━━━━━━  (drag handle)                               │
│                                                      │
│  🔶  Yahoo Campus Building D                         │
│  1.2 km away · Campus prayer room                    │
│                                                      │
│  ⚠️ Reported by 1 user — help verify this spot        │
│                                                      │
│  Have you prayed here?  [ ✅ Yes, it works ]  [ ❌ No, it's gone/wrong ]
│                                                      │
│  If yes, confirm what you found:                     │
│  ☐ There is a space to pray                          │
│  ☐ Bathroom / wudu facilities available              │
│  ☐ Open to everyone (men & women)                    │
│  ☐ It's indoors                                      │
│                                                      │
│  Hours you observed: _____________________           │
│                                                      │
│  [ Submit Verification ]                             │
│                                                      │
│  Verified by 1 person so far.                        │
│  After 3 verifications it will be fully shown.       │
└──────────────────────────────────────────────────────┘
```

### Map Integration

Prayer spots appear on the map with a different marker style:
- Orange diamond marker (vs circular mosque markers)
- Color intensity reflects verification level: light = pending, bold = verified
- Tapping a spot opens the same bottom sheet as tapping a spot card

---

### Abuse Protection

The spot system is community-driven with a **high-recall** safety model: the priority is to never show incorrect or harmful spots (private addresses, fake locations) to users, even at the cost of delaying legitimate spots briefly. A spot must receive at least one external confirmation before any other user sees it.

#### Identity Model

Two complementary identifiers are used together — neither alone is sufficient:

| Identifier | Where stored | Strength | Purpose |
|---|---|---|---|
| **Session ID** | Client `localStorage` (UUID) | Weak — user can clear it | Primary dedup key for submissions and verifications |
| **IP hash** | Server DB (sha256 of client IP) | Medium — VPN bypasses, but adds real friction | Rate limiting and cross-session dedup per spot |

The IP is **never stored in plain text** — only `sha256(IP)` is stored, making it irreversible and privacy-preserving. Together, session + IP hash means a user would need both a new browser session AND a new IP to bypass dedup — a high enough bar for a prayer app.

Phone number OTP would be stronger but adds friction incompatible with the app's anonymous philosophy. The session + IP hash combination is the right trade-off.

#### Submit endpoint (`POST /api/spots`)

| Check | Rule | Error |
|---|---|---|
| **Geographic bounds** | Lat 24–72 / Lng −168 to −52 (US + Canada) | 422 |
| **Content filter** | No URLs in name/notes/hours; no 3+ all-caps words | 422 |
| **Rate limit (session)** | Max 3 submissions per `session_id` per 24 h | 429 |
| **Rate limit (IP)** | Max 2 submissions per `ip_hash` per 24 h | 429 |
| **Deduplication** | Reject if a non-rejected spot exists within 50 m | 409 (with existing spot name shown) |

New spots start as `status = pending` and are **invisible to all other users** until they receive their first external positive verification. The submitter can always see their own pending spot (via `session_id` match in the nearby query).

#### Verify endpoint (`POST /api/spots/{id}/verify`)

| Check | Rule | Error |
|---|---|---|
| **Self-vote prevention** | Session that submitted the spot cannot verify it | 403 |
| **Duplicate vote (session)** | Same session cannot vote twice on the same spot | 409 |
| **Duplicate vote (IP)** | Same IP hash cannot vote twice on the same spot | 409 |
| **Rate limit (session)** | Max 30 verify actions per `session_id` per 24 h | 429 |
| **Rate limit (IP)** | Max 10 verify actions per `ip_hash` per 24 h | 429 |

#### Status transitions and visibility

| Condition | Status | Visible to |
|---|---|---|
| Just submitted, 0 external confirmations | `pending` | **Submitter only** (via session_id match) |
| ≥ 1 net positive from external user | `pending` | All users (with "unverified" warning label + confirm button) |
| ≥ 3 net positive | `active` | All users (normal display) |
| ≤ −3 net | `rejected` | Nobody (permanently hidden) |

The "hidden until confirmed" rule is the main defense against private addresses and fake spots. A bad actor submitting a private home address cannot cause harm — no other user will see it unless a second person independently confirms it, which is unlikely for a fake spot.

Rejection requires −3 net, so a single user cannot silently remove a real spot. Multiple independent negative reports are needed.

#### `confirmedSpots` client state

The frontend maintains a `confirmedSpots: Set<string>` in `localStorage` (keyed by spot_id) to track which spots the current session has already confirmed. This prevents showing the confirm button after the user has already tapped it, without needing an extra API call.

#### What is NOT collected

No plain-text IP addresses, device fingerprints, names, or emails are stored. Only `sha256(client_ip)` is stored server-side to enforce rate limits and prevent ballot-stuffing across sessions. The `session_id` is a random UUID generated per browser install (stored in localStorage).

---

## Mosque Detail Bottom Sheet

Slides up from bottom when user taps a card. Does not navigate away from the map.

```
┌──────────────────────────────────────────────────────┐
│  ━━━━━━  (drag handle)                               │
│                                                      │
│  Masjid Al-Noor                                      │
│  123 Main St, Raleigh, NC · 2.4 km away              │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ ✅ Can catch Asr with Imam                     │  │
│  │    Iqama at 4:25 PM · 12 min travel            │  │
│  │    Leave by 4:13 PM                            │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│  Today's Prayer Times                               │
│  ──────────────────────────────────────────────────  │
│  Fajr      5:31 AM adhan  ·  5:50 AM iqama          │
│  Shorooq   7:19 AM                  (Fajr ends) 🌅   │  ← amber row
│  Dhuhr    12:45 PM adhan  · 12:55 PM iqama          │
│  Asr       4:15 PM adhan  ·  4:25 PM iqama  ← now  │
│  Maghrib   7:16 PM adhan  ·  7:21 PM iqama          │
│  Isha      8:27 PM adhan  ·  8:42 PM iqama          │
│                                                      │
│  Data source: Scraped from mosque website (3d ago)  │
│                                                      │
│  [  🧭 Navigate  ]  [  📞 Call  ]  [  🌐 Website  ] │
│                                                      │
│  [    🔔 Set Prayer Reminders for this Mosque    ]   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Status Badge Behaviour in the Detail Sheet

The status badge at the top of the sheet adapts to the prayer state:

| `nc.status` | Badge style | Extra affordances |
|---|---|---|
| `can_catch_with_imam` / `in_progress` | Green | — |
| `can_pray_solo_at_mosque` | Blue | — |
| `pray_at_nearby_location` | Orange | — |
| `upcoming` | **Teal** (distinct from missed) | Shows "Azan at HH:MM · Iqama HH:MM" on line 2, "Leave by HH:MM to pray with Imam" on line 3 |
| `missed_make_up` | Gray | **[✓ Already prayed Fajr]** button below the message |

When `nc.prayer` is in `prayedToday` (user already marked it), the badge is hidden entirely and the sheet shows the next upcoming prayer from `mosque.prayers` directly, using the same teal upcoming style.

**Shorooq row**: After Fajr, a highlighted row shows the sunrise time labeled "Shorooq", with "Fajr ends" in the Iqama column. It renders with an amber/yellow background to distinguish it from the 5 obligatory prayers. The row is only shown when `mosque.sunrise` is non-null. Maghrib adhan equals the sunset time (no offset) per ISNA calculation.

### Friday / Jumuah View (implemented — shown on Fridays)

Sessions are fetched from the `jumuah_sessions` table and displayed only on Fridays. The section is green-themed in the UI. Each session card shows: session number, khutba start time, prayer start time, imam name, language (if not English), special notes, and booking required + registration URL when applicable.

```
│  Friday Jumu'ah                                     │
│  ──────────────────────────────────────────────────  │
│  ┌ Session 1 ────────────────── Khutba 12:30 · Prayer 1:00 ┐ │
│  │ Imam: Sheikh Ahmed                                      │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌ Session 2 ────────────────── Khutba 1:30 · Prayer 2:00 ┐ │
│  │ Imam: Dr. Hassan · Language: Arabic/English             │ │
│  │ Registration required — [Register link]                 │ │
│  └────────────────────────────────────────────────────────┘ │
```

---

## Navigate Button — Deep Links

When "Navigate" is tapped, show a bottom sheet with map app options:

```
┌──────────────────────────────────────────────────────┐
│  Open in Maps                                        │
│  ──────────────────────────────────────────────────  │
│  🗺  Google Maps                                      │
│  🍎  Apple Maps            (shown first on iOS)       │
│  🔵  Waze                                             │
│  📋  Copy address                                    │
│                    [ Cancel ]                        │
└──────────────────────────────────────────────────────┘
```

**URL construction** (no API needed):

```typescript
const NAVIGATION_LINKS = {
  google: (lat: number, lng: number, name: string) =>
    `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&destination_place_id=${encodeURIComponent(name)}`,

  apple: (lat: number, lng: number, name: string) =>
    `https://maps.apple.com/?daddr=${lat},${lng}&q=${encodeURIComponent(name)}`,

  waze: (lat: number, lng: number) =>
    `https://waze.com/ul?ll=${lat},${lng}&navigate=yes`,
};

// Detect platform to determine default order
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
const isAndroid = /Android/.test(navigator.userAgent);
```

---

## Map — Leaflet + CartoDB Positron

### Tile provider

CartoDB Positron tiles (`https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png`) replace the default OpenStreetMap raster tiles. Positron is a clean, minimal white/grey basemap that reduces visual noise and lets the status-colored mosque pins stand out clearly.

### User location marker

Two overlapping `CircleMarker`s create a teal dot with a subtle pulse ring:
- Outer ring: `radius=14`, `fillOpacity=0.12`, teal (`#0d9488`) — the "pulse" halo
- Inner dot: `radius=5`, solid teal, white stroke

### Mosque markers — custom SVG teardrop pins

Mosque markers use `L.divIcon` with an inline SVG teardrop pin shape (not plain circles). The pin color matches the `next_catchable.status`:

| Color | Hex | Status |
|---|---|---|
| Green | `#16a34a` | Can catch with Imam |
| Amber | `#ca8a04` | Congregation in progress |
| Blue | `#2563eb` | Can pray solo |
| Orange | `#ea580c` | Pray nearby |
| Grey | `#9ca3af` | Cannot catch / Upcoming |

**Normal pin**: 22×30 px. **Selected pin** (mosque chosen from list): 30×40 px, elevated `zIndexOffset: 1000`.

Each pin has a white inner circle and a white stroke border, giving it visual separation from the map tiles.

### Fit-bounds on mosque selection

When the user taps a mosque card in the list:
1. `selectedMosqueId` is set in the store
2. The map is uncollapsed (if hidden)
3. `FitBoundsController` (a `useMap()` child component) detects the change and calls `map.fitBounds()` with a bounding box that includes **both the user's location and the selected mosque**, padded by 52px on all sides, max zoom 15 — so both points are always visible

Clicking a mosque **pin** on the map also sets `selectedMosqueId` and opens the detail sheet.

### Prayer spot markers

Prayer spots use a dashed `CircleMarker` (orange stroke, light orange fill) to visually distinguish them from mosque pins. Tooltips appear on hover for both mosque pins and spot markers.

### Map collapse toggle

A minimal text button below the map ("▼ Hide map" / "▲ Show map") collapses the map to `height: 0` with a CSS transition. The map is automatically un-collapsed when a mosque card is tapped.

---

## State Management (Zustand)

**5-minute auto-refresh**: The app automatically re-fetches mosque data every 5 minutes when the user has a location. The `useEffect` depends on `userLocation`, `radiusKm`, and `travelMode` — so toggling travel mode also triggers an immediate re-fetch.

```typescript
interface AppStore {
  // Location
  userLocation: LatLng | null;
  setUserLocation: (loc: LatLng) => void;

  // Mosques
  mosques: Mosque[];
  setMosques: (m: Mosque[]) => void;
  mosquesLoading: boolean;
  mosquesError: string | null;

  // Prayer spots
  spots: PrayerSpot[];
  spotsLoading: boolean;

  // Settings
  radiusKm: number;               // 1–50 km, default 10
  denominationFilter: 'all' | 'sunni' | 'shia' | 'ismaili';
  showSpots: boolean;             // toggle prayer spots section
  travelMode: boolean;            // enables route-based travel planning

  // Prayed tracker (client-only, localStorage, resets at midnight)
  prayedToday: Set<string>;       // prayer names prayed today
  togglePrayed: (prayer: string) => void;

  // UI
  mapCollapsed: boolean;
  selectedMosqueId: string | null;  // drives FitBoundsController
  bottomSheet:
    | { type: 'mosque_detail'; mosque: Mosque }
    | { type: 'spot_detail'; spot: PrayerSpot }
    | { type: 'spot_submit' }
    | { type: 'settings' }
    | null;
}
```

All state lives in a single Zustand store (`store.ts`). Persisted values (prayed tracker, session ID) use `localStorage` directly.

---

## Settings Screen

Accessible from the ⚙ icon in the header. Opens as a bottom sheet.

```
┌──────────────────────────────────────────────────────┐
│  Settings                                       ✕    │
│                                                      │
│  Search radius: 10 km                                │
│  ├───────────●────────────────────────┤              │
│  1 km                              50 km             │
│                                                      │
│  Denomination                                        │
│  [ All ] [ Sunni ] [ Shia ] [ Ismaili ]              │
│                                                      │
│  🚗 Travel mode                        ● ON          │
│  Shows prayer combining options when traveling       │
│  (Dhuhr+Asr, Maghrib+Isha)                          │
│                                                      │
│  Show prayer spots                     ● ON          │
│  Community-added non-mosque locations                │
└──────────────────────────────────────────────────────┘
```

**Travel mode** also has a quick-access pill toggle in the header (`🏠 Muqeem` when off / `✈️ Musafir` when on) so the user can toggle it without opening Settings. Both toggles share the same `travelMode` store state.

When travel mode is enabled without a destination, the API receives `travel_mode: true` and may return `travel_combinations` on each mosque — pairs of prayers that can be combined (Dhuhr+Asr, Maghrib+Isha) with a shared window.

When a destination is set, the app switches to Route Mode (see Travel Mode section below).

---

## Travel Mode

### Global Muqeem / Musafir Toggle

The header pill shows the **current mode** and taps to switch:

| Pill label | Mode | Effect |
|---|---|---|
| `🏠 Muqeem` | Resident (default) | Normal mode — no combining, nearby mosque list only |
| `✈️ Musafir` | Traveler | Jam' Taqdeem / Ta'kheer shown on nearby mosque cards AND as the default for any trip plan |

**Muqeem** (مقيم) = resident, home. **Musafir** (مسافر) = traveler, safar. The toggle controls whether prayer combining (Jam') is allowed across the whole app.

The toggle works independently of the trip planner:
- **Musafir ON, no destination** — user is stationary away from home; nearby mosque cards show combination options
- **Musafir OFF, no destination** — normal local mode; nearby mosque cards show standard prayer times only

### Trip Planner (Always Accessible, Inherits Global Mode)

Trip planning is **always available** — always shown collapsed as a "🗺 Plan a trip →" tap target at the top of the list regardless of mode. Expanding it opens the form.

The trip planner has **no separate combining toggle** — it always uses the current global mode:

| Global mode | `trip_mode` sent | Trip result |
|---|---|---|
| 🏠 Muqeem | `"driving"` | Route mosques, standard times only |
| ✈️ Musafir | `"travel"` | Route mosques + combining options (Jam') |

The active mode is shown as a badge inside the form header so the user knows which rules apply.

#### Long-trip suggestion (Muqeem + >100 miles)

When "Plan My Prayers" is tapped in Muqeem mode and the trip distance exceeds ~160 km (100 miles), the form shows an inline banner before fetching the plan:

```
┌──────────────────────────────────────────────────────┐
│  ⚠️ Long trip — ~X miles                             │
│  As Musafir you could combine prayers along the      │
│  route (Dhuhr+Asr, Maghrib+Isha).                    │
│  [ Switch to Musafir & Plan ]  [ Plan as Muqeem ]    │
└──────────────────────────────────────────────────────┘
```

- "Switch to Musafir & Plan" → activates global Musafir mode then fetches plan with `trip_mode=travel`
- "Plan as Muqeem" → fetches plan with `trip_mode=driving` (no combining)
- The warning is dismissed once a choice is made

### Mode: Musafir, Static (No Route)

When ✈️ toggle is ON and **no destination is set**, each mosque card gains a combining section below the normal prayer status. The display is **context-sensitive** — exactly one option is shown at a time.

**Pair ordering rule:** Only the **first unresolved pair** is shown. Maghrib+Isha is hidden while Dhuhr+Asr has not been prayed yet and the Asr period has not ended. Once Dhuhr+Asr is fully resolved (both prayed, or Asr period passed), the Maghrib+Isha pair becomes visible. This prevents showing irrelevant future pairs (e.g. no Maghrib+Isha at 8 AM).

**Case A — Before p1 adhan (e.g. 8 AM, Dhuhr at 1 PM):**
```
┌──────────────────────────────────────────────────────┐
│ 🟢  Masjid Al-Noor                      12 min away │
│     Dhuhr in 5h — leave by 12:50 to catch with Imam │
│     ────────────────────────────────────────────     │
│  ✈️ 🕌 Dhuhr + Asr — Musafir combining              │
│  ┌─────────────────────────────────────────────┐    │
│  │ Combine Dhuhr + Asr at Dhuhr time (iqama    │    │
│  │ 1:05 PM) — pray both when you reach mosque. │    │
│  │ [Jam' Taqdeem — Combine Early]              │    │
│  └─────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

**Case B — p1 adhan started, before p2 adhan (Dhuhr started, Asr not yet):**
```
┌──────────────────────────────────────────────────────┐
│ 🟢  Masjid Al-Noor                      12 min away │
│     Dhuhr — Iqama 1:05 PM — catch with Imam now     │
│     ────────────────────────────────────────────     │
│  ✈️ 🕌 Dhuhr + Asr — Musafir combining              │
│  ┌─────────────────────────────────────────────┐    │
│  │ Pray Dhuhr + Asr together now —             │    │
│  │ Dhuhr iqama 1:05 PM.                        │    │
│  │ [Jam' Taqdeem — Combine Early]              │    │
│  └─────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

**Case C — After p2 adhan, before p2 period ends (Asr started, before Maghrib):**
Taqdeem window is closed. Show only Takheer — the first prayer is NOT missed as a Musafir.
```
┌──────────────────────────────────────────────────────┐
│ 🟢  Masjid Al-Noor                      12 min away │
│     ────────────────────────────────────────────     │
│  ✈️ 🕌 Dhuhr + Asr — Musafir combining              │
│  ┌─────────────────────────────────────────────┐    │
│  │ Pray Dhuhr + Asr together now —             │    │
│  │ Asr iqama 4:30 PM.                          │    │
│  │ [Jam' Ta'kheer — Combine Late]              │    │
│  └─────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

The same three cases apply identically to the **Maghrib + Isha** pair once Dhuhr+Asr is resolved.

Key rules:
- **Only one pair shown at a time** — the first unresolved pair in chronological order (Dhuhr+Asr → Maghrib+Isha)
- **Taqdeem only** while before p2 adhan (Asr/Isha hasn't started). Never show both options simultaneously.
- **Takheer only** once p2 adhan has passed — Taqdeem window is closed, but the first prayer is not missed
- **No "now"** in the description before p1 adhan — describe the plan for when the user arrives
- Both use `travel_combinations` from `/api/nearby` when `travel_mode=true`

### Share Route (Open in Maps)

Each trip itinerary card has an **"Open in Maps"** button at the bottom that builds a multi-stop navigation URL and opens it in Google Maps or Apple Maps.

**URL structure:**
- Google Maps: `https://www.google.com/maps/dir/{origin}/{stop1}/{stop2}/{destination}` path format. If a mosque has a `google_place_id`, use `place_id:ChIJ...` as the segment; otherwise use the encoded name+address. Supports unlimited waypoints.
- Apple Maps: `https://maps.apple.com/?saddr={origin}&daddr={stop1}&daddr={stop2}&daddr={destination}` — shown as alternative on iOS devices. Uses `Name@lat,lng` format for labeled pins.

**Origin waypoint rule**: When the user has NOT set an explicit origin (i.e., `travelOrigin === null` — the app is using GPS current location), do NOT include an explicit origin in the URL. Both Google Maps and Apple Maps automatically start routing from the device's current GPS position when no `saddr` / origin segment is provided. Including a lat/lng origin in this case creates a confusing extra dropped-pin waypoint.

- Google Maps with current location: `https://www.google.com/maps/dir//{stop1}/{destination}` (empty origin segment = current location)
- Apple Maps with current location: `https://maps.apple.com/?daddr={stop1}&daddr={destination}&dirflg=d` (no `saddr`)

Stops are collected from the itinerary's `pair_choices[].option.stops`, sorted by `minutes_into_trip`, deduplicated by mosque ID. Destination is always `travelDestination`.

The button is shown in every expanded itinerary card. On devices with the Web Share API (`navigator.share`), tapping "Share Route" invokes the native share sheet so the user can send the link to a friend or save it.

### Trip Planner Form

Always shown at the top of the list. When no trip is active it renders as a small collapsed row:

```
┌──────────────────────────────────────────────────────┐
│  🗺 Plan a trip →                                    │  taps to expand form
└──────────────────────────────────────────────────────┘
```

Tapping it expands the full form:

```
┌──────────────────────────────────────────────────────┐
│  PLAN YOUR TRIP              [🏠 Muqeem / ✈️ Musafir]│  mode badge, read-only — reflects global mode
│                                                      │
│  📍  From: Current location                          │  optional — geocode search
│                                                      │
│  ┌──────────────────────────────────────────────┐    │  ← waypoints (0–4, optional)
│  │ 📌 Chicago, IL                    [↑][↓][✕] │    │
│  │ 📌 Detroit, MI                    [↑][↓][✕] │    │
│  └──────────────────────────────────────────────┘    │
│  [ + Add stop ]                                      │  adds a geocode input above destination
│                                                      │
│  🏁  To: Destination *                               │  required — geocode search
│                                                      │
│  🕐  Departs: Mon Mar 16, 3:30 PM                    │  datetime-local, default=now
│                                                      │
│  [ Plan My Prayers ]                                 │  disabled until dest selected
└──────────────────────────────────────────────────────┘
```

**Multi-stop waypoints:**
- "Add stop" button appears between the From and To fields
- Tapping it inserts a new geocode input above the destination row
- Each waypoint row has: geocode input + ↑ (move up) + ↓ (move down) + ✕ (remove)
- First waypoint's ↑ is disabled; last waypoint's ↓ is disabled; single waypoint has both disabled
- Maximum 4 waypoints (6 total points: origin + 4 waypoints + destination)
- Waypoints are stored in `tripWaypoints: TravelDestination[]` in the store
- Passed to backend as `waypoints: [{lat, lng, name}]` in the request body
- Backend routes through all waypoints in order: origin → wp1 → wp2 → destination
- In the compact trip chip, waypoints appear in the route summary: `Origin → Chicago → Detroit → SF`

- Typing 3+ characters in any field triggers a debounced geocode query (400ms) via `GET /api/geocode?q=...`
- Results appear as a dropdown list below the input, each prefixed with 📍
- Selecting a suggestion sets the corresponding field in the store
- Origin is optional — if blank, current GPS location is used
- Departure time defaults to current local time (exact, not rounded)
- **"Plan My Prayers"** button is the explicit trigger — no automatic fetch on input change
- Once a plan is active, the form collapses to a compact chip:

```
┌──────────────────────────────────────────────────────┐
│  ✈️ Musafir trip                                  ✕  │  teal-50 bg, teal-200 border
│  Current location → Chicago → Detroit → SF           │
│  Departs Mar 16, 3:30 PM                             │
└──────────────────────────────────────────────────────┘
```

- Tapping **anywhere on the chip** (except ✕) re-opens the full trip planner form for editing — the form is pre-populated with the previous origin, waypoints, destination, and departure time
- Tapping ✕ clears the destination, waypoints, plan, origin, and departure time (mosque list reappears)

### Travel Prayer Plan

When "Plan My Prayers" is tapped, `POST /api/travel/plan` is called with:
- `origin_lat/lng`: travelOrigin if set, otherwise user's current GPS location
- `origin_name`: travelOrigin.place_name or "Current location"
- `destination_lat/lng/name`: selected destination
- `departure_time`: ISO 8601 string from datetime picker (defaults to now)
- `timezone`: user's browser timezone (IANA)
- `trip_mode`: `"travel"` or `"driving"`
- `waypoints`: array of `{lat, lng, name}` for intermediate stops (empty array if none)
- `prayed_prayers`: array of prayer names already prayed today (from `prayedToday` store) — backend excludes these from the plan

The backend skips any prayer pair where both prayers are already prayed. For pairs where one prayer is done, it builds a solo-stop plan for the remaining prayer only (see ISLAMIC_PRAYER_RULES.md — Prayed Prayer Exclusion).

### Prayer Pair Relevance — Time-Aware Filtering

**Only prayer pairs that fall within the trip window are shown.** The backend computes:

```
trip_window = [departure_time, arrival_time]
arrival_time = departure_time + route_duration
```

For each potential pair (Fajr standalone, Dhuhr+Asr, Maghrib+Isha), it is only included in the response if **at least one prayer in the pair** has a window that overlaps with the trip window:

- A prayer window is `[adhan_time, period_end_time]`
  (Isha's period wraps midnight: it ends at the next Fajr adhan)
- A prayer is **currently active** if `adhan_time ≤ departure_time ≤ period_end_time`
- A prayer is **upcoming during the trip** if its adhan falls between departure and arrival

**Examples:**
| Departure | Duration | Shown pairs |
|---|---|---|
| 12:46 AM (after Isha) | 1 hour | Isha only (Isha period still active until Fajr) |
| 12:00 PM (Dhuhr time) | 3 hours | Dhuhr+Asr (Dhuhr active at departure, Asr starts during trip) |
| 6:00 PM (pre-Maghrib) | 4 hours | Maghrib+Isha (both occur during trip) |
| 3:00 AM | 4 hours | Fajr (adhan around 5:30 AM falls within trip) |
| 10:00 AM | 8 hours | Dhuhr+Asr, Maghrib (all three occur during trip) |

Pairs where **neither prayer's window touches the trip** are completely omitted from the response — not shown as empty or "no options", just absent.

### Plan Output — Complete Itineraries

The plan shows **3–5 complete trip itineraries**, each covering ALL prayers for the whole journey. The backend generates these by combining one strategy per prayer pair across all relevant pairs (Fajr, Dhuhr+Asr, Maghrib+Isha).

```
┌──────────────────────────────────────────────────────┐
│  Route: 5h 48min · 381 mi                            │
└──────────────────────────────────────────────────────┘

  3 complete prayer plans

┌──────────────────────────────────────────────────────┐
│  OPTION 1                              +27 min  ▲    │  teal label + collapse toggle
│  🕌 Dhuhr+Asr early (Taqdeem) · 🌙 Maghrib+Isha late │
│  ────────────────────────────────────────────────    │
│  🕌 Dhuhr + Asr         [Jam' Taqdeem]               │
│  ⏩ Stop at Masjid Al-Noor (12 min detour) —          │
│     pray both Dhuhr + Asr during Dhuhr time          │
│  ┌──────────────────────────────────────────────┐    │
│  │ Masjid Al-Noor · Bakersfield, CA             │    │  tappable → map focus
│  │ Iqama 1:00 PM · +12 min detour 📍            │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  🌙 Maghrib + Isha       [Jam' Ta'kheer]              │
│  ⏪ Stop at Islamic Center (15 min detour) —          │
│     pray both Maghrib + Isha during Isha time        │
│  ┌──────────────────────────────────────────────┐    │
│  │ Islamic Center · Fresno, CA                  │    │
│  │ Iqama 9:45 PM · +15 min detour 📍            │    │
│  └──────────────────────────────────────────────┘    │
│  ────────────────────────────────────────────────    │
│  [ 🗺 Google Maps ]  [ 📤 ]                          │  share row
└──────────────────────────────────────────────────────┘
```

**Itinerary templates** (backend generates, deduplicates):
1. **All early** — pray_before or Taqdeem for every pair
2. **Early then late** — Taqdeem for first pair, Ta'kheer/destination for last *(classic Musafir road trip)*
3. **All late** — Ta'kheer / at-destination for every pair
4. **All at destination** — no route stops
5. **Separate stops** — one mosque per prayer, no combining

**Musafir mode** (`trip_mode=travel`): all five templates attempted; combining options included.
**Muqeem mode** (`trip_mode=driving`): combining options excluded; only separate/pray_before/at_destination templates survive deduplication.

**`at_destination` redundancy rule**: shown only when there are no route-stop options covering those prayers, to avoid a redundant third card.

**Itinerary card behavior**:
- Tap header to expand / collapse
- Tap a mosque stop → selects mosque in store, focuses map, un-collapses map
- "Open in Maps" row (see Share Route section above) is shown at the bottom of every expanded card

### Mosque Search Along Route

The backend uses:
- **Routing**: OSRM (free) or Mapbox (if key configured) — full route geometry (overview=full) is sampled into dense checkpoints with time interpolated by cumulative distance, ensuring mosques along long straight highway stretches are found and timed correctly
- **Corridor**: mosques within **30 km** of the route bounding box
- **Detour limit**: mosques requiring more than **45 minutes** total detour (drive there + prayer overhead + drive back) are excluded
- **Detour speed**: uses straight-line haversine × 1.4 road factor at 60 km/h highway average

For each mosque: estimated arrival time = departure time + cumulative step duration to nearest checkpoint + drive to mosque. Prayer schedule lookup uses the mosque's **local date at that estimated arrival time** (handles timezone crossings and overnight trips).

### Itinerary Card Design (`TravelItineraryCard`)

Each itinerary card has:
- **Header** (always visible): "OPTION N" label (teal, uppercase) + combined label showing each pair's strategy + total detour minutes + ▲/▼ collapse toggle
- **Body** (expanded): one section per `pair_choice` in trip order:
  - Prayer pair emoji + label + optional Jam' badge
  - Strategy icon + description text
  - Tappable mosque stop rows (name · address · iqama · detour minutes 📍)
  - Optional italic note
- **Share row** (bottom of body): `🗺 Google Maps` button · `🍎 Apple Maps` (iOS only) · `📤` share/copy button

Strategy icons used in descriptions:
| option_type | Icon |
|---|---|
| pray_before | 📍 |
| combine_early | ⏩ |
| combine_late | ⏪ |
| at_destination | 🏁 |
| separate | 🔀 |
| stop_for_fajr | 🌅 |
| no_option | ⚠️ |

### Timezone Crossing

When a trip crosses a timezone boundary (e.g., driving from Eastern to Central time), prayer time lookups for each mosque use the **mosque's local date at estimated arrival time** — not the departure date. This ensures correct prayer schedules for overnight trips and cross-timezone travel.

### State Management Additions

```typescript
// Added to AppState:
travelOrigin: TravelDestination | null;       // null = use GPS current location
setTravelOrigin: (o: TravelDestination | null) => void;
travelDestination: TravelDestination | null;   // required to plan a route
setTravelDestination: (d: TravelDestination | null) => void;
tripWaypoints: TravelDestination[];            // 0–4 intermediate stops between origin and destination
setTripWaypoints: (w: TravelDestination[]) => void;
travelDepartureTime: string | null;            // ISO; null = now
setTravelDepartureTime: (t: string | null) => void;
travelPlan: TravelPlan | null;                 // result from /api/travel/plan
setTravelPlan: (p: TravelPlan | null) => void;
travelPlanLoading: boolean;                    // true while plan is fetching
setTravelPlanLoading: (v: boolean) => void;
```

The plan fetch is triggered **explicitly by the "Plan My Prayers" button** inside `DestinationInput` — not automatically on destination change. A `useEffect` in App watches `travelDestination` only to clear the plan when destination is removed.

### Map Behavior in Route Mode

When a destination is set (with or without a plan), the map shows:

1. **Origin pin** (teal circle labeled "A") — user's current GPS location or custom origin if set
2. **Destination pin** (red circle labeled "B") — travelDestination
3. The map **auto-zooms** to fit both origin and destination at the tightest zoom that shows both
4. **Nearby mosque pins are hidden** — only route stops and endpoint pins are shown during trip planning; nearby mosques reappear when the trip is cleared

When a trip plan is active ("Plan My Prayers" was clicked), the map additionally shows:

5. **Route mosque stop pins** — indigo/purple pins for each unique mosque from the plan's stops (from all feasible options)
6. The map **re-fits** to show all: origin, destination, and all mosque stops

**Mosque name labels** are always visible (permanent tooltips) on all mosque pins — both nearby mosques and route stop mosques.

Tapping a stop card inside a `TravelOptionCard` zooms the map to that mosque and fits it with the user's location.

### Diverse Trip Options

The trip planner returns **up to 3 diverse options per combination type** (Jam' Taqdeem, Jam' Ta'kheer) — each showing a different mosque along the route, sorted by minutes into the trip. This gives users meaningful choice (e.g., stop earlier with a longer detour vs. later with a shorter one). The "Separate Stops" option remains a single best pairing.

---

## Deep Link / Share from Maps Apps

The app supports receiving a shared destination directly from Google Maps, Apple Maps, or other navigation apps — eliminating the need to type a destination manually.

### Web Share Target API (Android PWA)

`manifest.json` declares a share target:

```json
"share_target": {
  "action": "/?share=maps",
  "method": "GET",
  "params": { "title": "title", "text": "text", "url": "url" }
}
```

**User flow on Android:**
1. Open Google Maps or Apple Maps → find destination → tap **Share**
2. Select **Catch a Prayer** from the share sheet
3. App opens in Travel Mode with destination pre-filled (or search pre-populated if only a place name was shared)
4. User selects departure time and taps "Plan My Prayers"

**Parsing shared content:**
- If the shared `url` is a Google Maps place URL (`/maps/place/Name/@lat,lng,zoom`), lat/lng are extracted directly
- If it's an Apple Maps URL with `?ll=lat,lng`, those coordinates are used
- If the URL is a shortened link (maps.app.goo.gl / goo.gl/maps) that can't be parsed, the place `title` is used to pre-fill the destination search field so the user can pick from geocode suggestions

### Direct URL Parameters (Programmatic Deep Link)

Any external source can open the app in travel mode via:

```
https://yourapp.com/?dest_lat=37.7749&dest_lng=-122.4194&dest_name=San+Francisco%2C+CA
```

Parameters:
| Param | Required | Description |
|---|---|---|
| `dest_lat` | Yes | Destination latitude |
| `dest_lng` | Yes | Destination longitude |
| `dest_name` | No | Display name (default: "Shared destination") |

After reading the params, the app cleans the URL with `history.replaceState` so the params don't persist on reload.

### iOS Limitation

iOS does not support the Web Share Target API (as of 2026). On iOS, the user can:
- Copy a Google Maps share URL
- Open the app and paste the URL (future enhancement — clipboard parsing on focus)
- Or type the destination manually in the trip planner

---

---

## Notification Preferences Screen

Per-prayer toggle with timing controls.

```
Prayer Reminders

  Fajr        ●─────────────  ON
    Before adhan:  [ 30 min ▼ ]
    Before iqama:  [ 15 min ▼ ]

  Dhuhr       ●─────────────  ON
    Before adhan:  [ 15 min ▼ ]
    Before iqama:  [ 10 min ▼ ]

  Asr         ●─────────────  ON
  Maghrib     ●─────────────  ON
  Isha        ●─────────────  ON

  Jumuah      ●─────────────  ON
    Before khutba: [ 60 min ▼ ]

  ──────────────────────────────────────
  Quiet Hours
  Do not disturb: 11:00 PM — 4:30 AM
  ☑ Override quiet hours for Fajr

  Travel buffer: 5 min
    "Extra time added for parking/walking"

  Favorite mosque (priority for notifications)
  [ Masjid Al-Noor — Raleigh, NC   ✕ ]
```

---

## PWA Configuration

```json
// public/manifest.json
{
  "name": "Catch a Prayer",
  "short_name": "Catch a Prayer",
  "description": "Find nearby mosques and catch your next prayer",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#FFFFFF",
  "theme_color": "#0d9488",
  "icons": [
    { "src": "/icons/logo192.png",  "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/logo512.png",  "sizes": "512x512", "type": "image/png" },
    { "src": "/icons/logo512.png",  "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

Service worker handles:
- Offline fallback (show last known mosque data)
- Background sync (queue location updates when offline)
- Push notification reception

---

## Responsive Breakpoints

```css
/* Mobile first */
.mosque-list { display: flex; flex-direction: column; }
.map-container { height: 40vh; }

/* Tablet+ */
@media (min-width: 768px) {
  .app-layout { display: grid; grid-template-columns: 1fr 1fr; }
  .map-container { height: 100vh; position: sticky; top: 0; }
}

/* Desktop */
@media (min-width: 1024px) {
  .app-layout { grid-template-columns: 3fr 2fr; }
}
```

---

## Accessibility

- Minimum touch target size: 48×48px for all interactive elements
- Color is never the sole indicator of status — always paired with text/icon
- `aria-label` on all icon-only buttons
- Screen reader: prayer status announced with full text
- High contrast mode support via CSS media query
