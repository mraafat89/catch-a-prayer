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
- **Travel toggle**: Pill button in header — grey outline when off, solid white with teal text when active. Toggling immediately re-fetches mosques with `travel_mode: true`.
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

In **dead time** (after Fajr ends at sunrise, before Dhuhr starts — roughly 7 AM to 12:30 PM), there is no active current prayer. The card shows only the upcoming Dhuhr row as primary with no secondary row.

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
- The "✓ Prayed" button is only shown when the prayer's adhan has already occurred (cannot pre-mark future prayers)
- Marking hides the prayer row from **all** mosque cards and from the global chip target
- `prayedToday` is stored in `localStorage` keyed by `prayer + date` — resets at midnight
- "Undo" in the global chip restores the row on all cards
- This is **client-side only** — no API call needed

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
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ 🔶  Yahoo Campus Building D              1.2 km away │
│     Campus prayer room · Wudu ✓ · Men & Women        │
│     ⚠️ Reported by 1 user — not yet verified          │
└──────────────────────────────────────────────────────┘
```

**Icons:**
- 🔶 Orange diamond = prayer spot (vs 🟢🟡🔵 circles for mosques)
- Wudu ✓ = bathroom with running water confirmed
- Wudu ? = wudu facilities unknown

**Verification badge styles:**
| Verifications | Badge |
|---|---|
| 0 (pending) | "Reported — not yet verified" (grey, italic) |
| 1–2 | "Reported by N users" (grey) |
| 3–9 | "Verified by N users" (green check) |
| ≥10 | "Highly verified" (green bold) |

Pending/unverified spots are shown with a muted style and a disclaimer. Rejected spots are never shown.

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

**Location entry**: The location defaults to the user's current GPS position (reverse-geocoded to a readable label). The user can override it by typing in the address search box, which uses the same Nominatim geocode lookup as the trip planner — no extra API needed. A `⌖ GPS` button resets back to the current GPS location.

**Trip planner "From" field**: A `⌖` icon button sits to the right of the "From" input. Tapping it re-fetches the current GPS coordinates and reverse-geocodes them to update the origin — useful when the user has moved since the app loaded.

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

The spot system is community-driven, so it must guard against spam, ballot-stuffing, and fake entries without requiring accounts.

#### Submit endpoint (`POST /api/spots`)

| Check | Rule | Error |
|---|---|---|
| **Geographic bounds** | Lat 24–72 / Lng −168 to −52 (US + Canada) | 422 |
| **Content filter** | No URLs in name/notes; no 5+ consecutive all-caps words | 422 |
| **Rate limit** | Max 3 submissions per `session_id` per 24 h | 429 |
| **Deduplication** | Reject if a non-rejected spot exists within 50 m | 409 (with existing spot name shown) |

All spots start as `status = pending` — they are visible but clearly labeled "not yet verified" until they accumulate community verification.

#### Verify endpoint (`POST /api/spots/{id}/verify`)

| Check | Rule | Error |
|---|---|---|
| **Self-vote prevention** | Session that submitted the spot cannot verify it | 403 |
| **Duplicate vote** | Same session cannot vote twice on the same spot | 409 |
| **Rate limit** | Max 30 verify actions per `session_id` per 24 h | 429 |

#### Status transitions

| Net score (verifications − rejections) | Status |
|---|---|
| Newly submitted | `pending` |
| ≥ +3 | `active` (shown normally) |
| ≤ −3 | `rejected` (hidden from all users) |

A spot needs at least 3 net positive votes to become active, so a single bad actor with one session cannot promote their own fake spot. Rejection requires −3 net, so a single user cannot remove a good spot alone.

#### What is NOT collected

The system is deliberately anonymous. No IP addresses, device fingerprints, names, or emails are stored. The `session_id` is a random UUID generated per browser/device install (stored in localStorage), used only to prevent duplicate submissions within a session.

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

**Travel mode** also has a quick-access pill toggle in the header (🚗 Travel / 🚗 Traveling) so the user can toggle it without opening Settings. Both toggles share the same `travelMode` store state.

When travel mode is enabled without a destination, the API receives `travel_mode: true` and may return `travel_combinations` on each mosque — pairs of prayers that can be combined (Dhuhr+Asr, Maghrib+Isha) with a shared window.

When a destination is set, the app switches to Route Mode (see Travel Mode section below).

---

## Travel Mode

### Global ✈️ Musafir Toggle

The global ✈️ **Musafir** toggle (header pill) indicates the user is a traveler (Musafir / Safar) — away from their home city. It controls **whether prayer combining (Jam') is allowed** across the whole app:

| ✈️ Toggle | Effect |
|---|---|
| **OFF** | Normal mode — no combining, nearby mosque list only |
| **ON** | Musafir mode — Jam' Taqdeem / Ta'kheer shown on nearby mosque cards AND as the default for any trip plan |

The toggle does **not** require a destination to be set. When ON without a destination, the user is stationary in another city and sees combination options on mosque cards.

### Trip Planner (Separate from Global Toggle)

Trip planning is available whenever ✈️ is ON or a destination is already set. The trip planner has its own **"✈️ Apply Musafir rules (combine prayers)"** toggle inside the form, which **defaults to the global toggle state** but can be overridden per trip.

| Global ✈️ | Trip form toggle | `trip_mode` sent | Use case |
|---|---|---|---|
| OFF | OFF (default) | `"driving"` | Local commute — route mosques, no combining |
| ON | ON (default) | `"travel"` | Safar road trip — route mosques + combining |
| ON | OFF (user override) | `"driving"` | Driving but chose not to combine for this trip |
| OFF | ON (user override) | `"travel"` | User turned off global toggle but wants combining for this specific trip |

### Mode: Musafir, Static (No Route)

When ✈️ toggle is ON and **no destination is set**, the nearby mosque list shows combination options (Dhuhr+Asr, Maghrib+Isha) as chips on each mosque card:

```
┌──────────────────────────────────────────────────────┐
│ 🟢  Masjid Al-Noor                      12 min away │
│     Dhuhr — Iqama 1:05 PM — catch with Imam now     │
│     ────────────────────────────────────────────     │
│     ✈️ Combination options:                          │
│     🟢 Combine Dhuhr+Asr now (Jam' Taqdeem)         │  ← only if before Asr adhan
│     🔵 Wait for Asr, pray both then (Jam' Ta'kheer) │  ← only if before Asr ends
└──────────────────────────────────────────────────────┘
```

Combination options are computed per mosque from today's schedule:
- **Taqdeem**: feasible before the second prayer's adhan (combine early, during first prayer's window)
- **Ta'kheer**: feasible before the second prayer's period ends (delay first into second's window)

Uses the `travel_combinations` field returned by `/api/nearby` when `travel_mode=true`.

### Trip Planner Form

Shown when ✈️ toggle is ON or a destination is set.

```
┌──────────────────────────────────────────────────────┐
│  PLAN YOUR TRIP                                      │  teal-700 uppercase label
│                                                      │
│  ✈️ Apply Musafir rules (combine prayers)   [● ON]   │  toggle — defaults to global ✈️ state
│  ℹ️ Allows combining Dhuhr+Asr, Maghrib+Isha        │  shown only when toggle ON
│     (Jam' Taqdeem / Ta'kheer).                       │
│                                                      │
│  📍  From: Current location                   [⌖]   │  optional — geocode search
│  🏁  To: Destination *                               │  required — geocode search
│                                                      │
│  🕐  Departs: Mon Mar 16, 3:30 PM                    │  datetime-local, default=now
│                                                      │
│  [ Plan My Prayers ]                                 │  disabled until dest selected
└──────────────────────────────────────────────────────┘
```

- Typing 3+ characters in either field triggers a debounced geocode query (400ms) via `GET /api/geocode?q=...`
- Results appear as a dropdown list below the input, each prefixed with 📍
- Selecting a suggestion sets `travelOrigin` or `travelDestination` in the store
- Origin is optional — if blank, current GPS location is used
- Departure time defaults to current local time (exact, not rounded)
- **"Plan My Prayers"** button is the explicit trigger — no automatic fetch on input change
- Once a plan is active, the form collapses to a compact chip:

```
┌──────────────────────────────────────────────────────┐
│  ✈️ Traveling                                     ✕  │  teal-50 bg, teal-200 border
│  Current location → San Francisco, CA                │
│  Departs Mar 16, 3:30 PM                             │
└──────────────────────────────────────────────────────┘
```

- Tapping **anywhere on the chip** (except ✕) re-opens the full trip planner form for editing — the form is pre-populated with the previous origin, destination, and departure time
- Tapping ✕ clears the destination, plan, origin, and departure time (mosque list reappears)

### Travel Prayer Plan

When "Plan My Prayers" is tapped, `POST /api/travel/plan` is called with:
- `origin_lat/lng`: travelOrigin if set, otherwise user's current GPS location
- `origin_name`: travelOrigin.place_name or "Current location"
- `destination_lat/lng/name`: selected destination
- `departure_time`: ISO 8601 string from datetime picker (defaults to now)
- `timezone`: user's browser timezone (IANA)
- `trip_mode`: `"travel"` or `"driving"`

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

### Plan Output

```
┌──────────────────────────────────────────────────────┐
│  Route: 5h 48min · 381 mi                            │  white card, gray border
└──────────────────────────────────────────────────────┘

[Only pairs relevant to the trip window appear below]

🕌 Dhuhr + Asr              ← shown only if trip spans Dhuhr or Asr time
┌──────────────────────────────────────────────────────┐
│  ✅ Pray Both Before Leaving          [both active]  │  teal-50
│  Both Dhuhr and Asr are currently active...          │
└──────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────┐
│  🟢 Combine Early — Jam' Taqdeem      [Jam' Taqdeem] │  green-50  (Traveling only)
│  Stop at Masjid Al-Noor (12 min detour) — pray both  │
│  Dhuhr + Asr together during Dhuhr time.             │
│  ┌──────────────────────────────────────────────┐    │
│  │ Masjid Al-Noor · Bakersfield, CA             │    │
│  │ Iqama 1:00 PM · +12 min detour               │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────┐
│  🔵 Combine Late — Jam' Ta'kheer      [Jam' Ta'kheer] │  blue-50  (Traveling only)
└──────────────────────────────────────────────────────┘

🌙 Maghrib + Isha            ← shown only if trip spans Maghrib or Isha time
...

🌅 Fajr                      ← shown only if Fajr adhan falls within trip window
...
```

**Driving mode**: `combine_early` and `combine_late` options are omitted. Only `separate`, `pray_before`, `at_destination`, and `stop_for_fajr` appear.

**`at_destination` redundancy rule**: The `at_destination` option is only shown when there are **no route-stop options** (no `combine_early`, `combine_late`, or `separate`) covering the prayers in that pair. If a mosque stop along the route already handles those prayers, `at_destination` is omitted to avoid the confusing "third card" for the same prayer.

**Travel option card — map zoom**: Tapping a mosque stop card inside a `TravelOptionCard` sets that mosque as the selected mosque in the store, un-collapses the map, and fits the map view to show both the user's current location and the mosque. This uses the same `selectedMosqueId` mechanism as tapping a mosque card in the list.

### Mosque Search Along Route

The backend uses:
- **Routing**: OSRM (free) or Mapbox (if key configured) — returns turn-by-turn steps used as route checkpoints
- **Corridor**: mosques within **30 km** of the route bounding box
- **Detour limit**: mosques requiring more than **45 minutes** total detour (drive there + prayer overhead + drive back) are excluded
- **Detour speed**: uses straight-line haversine × 1.4 road factor at 60 km/h highway average

For each mosque: estimated arrival time = departure time + cumulative step duration to nearest checkpoint + drive to mosque. Prayer schedule lookup uses the mosque's **local date at that estimated arrival time** (handles timezone crossings and overnight trips).

### Option Card Design

Each option card (`TravelOptionCard`) has:
- **Color**: determined by `option_type`
  - `pray_before` → teal-50 / teal border
  - `combine_early` → green-50 / green border *(Traveling mode only)*
  - `combine_late` → blue-50 / blue border *(Traveling mode only)*
  - `separate` → purple-50 / purple border
  - `at_destination` → orange-50 / orange border
  - `stop_for_fajr` → yellow-50 / yellow border
  - `no_option` → gray-50 / gray border, opacity-60
- **Header row**: icon + label (bold) + optional combination_label badge (pill)
- **Description**: one-line summary of what to do
- **Stop cards** (if any): mosque name · address · iqama time · detour in minutes
- **Note** (italic, light gray): context hint like "~90 min into your trip"

### Timezone Crossing

When a trip crosses a timezone boundary (e.g., driving from Eastern to Central time), prayer time lookups for each mosque use the **mosque's local date at estimated arrival time** — not the departure date. This ensures correct prayer schedules for overnight trips and cross-timezone travel.

### State Management Additions

```typescript
// Added to AppState:
travelOrigin: TravelDestination | null;       // null = use GPS current location
setTravelOrigin: (o: TravelDestination | null) => void;
travelDestination: TravelDestination | null;   // required to plan a route
setTravelDestination: (d: TravelDestination | null) => void;
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

When a trip plan is active ("Plan My Prayers" was clicked), the map additionally shows:

4. **Route mosque stop pins** — indigo/purple pins for each unique mosque from the plan's stops (from all feasible options)
5. The map **re-fits** to show all: origin, destination, and all mosque stops

**Mosque name labels** are always visible (permanent tooltips) on all mosque pins — both nearby mosques and route stop mosques.

Tapping a stop card inside a `TravelOptionCard` zooms the map to that mosque and fits it with the user's location.

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
