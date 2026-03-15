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
┌─────────────────────────────┐
│  Header: app name           │  sticky, minimal height
│  Next prayer countdown      │  "Asr in 23 min"
├─────────────────────────────┤
│                             │
│   Leaflet Map               │  ~40% viewport height
│   (mosque pins, user dot)   │  collapsible on scroll
│                             │
├─────────────────────────────┤
│  Mosque list (scrollable)   │
│  ┌─────────────────────────┐│
│  │ Mosque card             ││  see card design below
│  └─────────────────────────┘│
│  ┌─────────────────────────┐│
│  │ Mosque card             ││
│  └─────────────────────────┘│
│  ─── Other Prayer Spots ───  │  section divider (only shown if spots exist)
│  ┌─────────────────────────┐│
│  │ Prayer spot card   🔶   ││
│  └─────────────────────────┘│
│  ─── Last Resort ──────────  │  only if no spot reachable before prayer ends
│  ┌─────────────────────────┐│
│  │ Pray anywhere card 🟠   ││
│  └─────────────────────────┘│
│  ...                        │
└─────────────────────────────┘
```

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
│     🤲 Can pray solo — period active until 6:47 PM   │
│     📍 From mosque website                           │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│ ⚪  Masjid Al-Rahman                   35 min away  │
│     Asr: Adhan 4:15 PM · Iqama ~4:25 PM   [Shia]   │  ← denomination badge
│     ❌ Cannot reach before Asr ends                  │
│     📍 Estimated — congregation time not confirmed   │  ← distinct visual style
└──────────────────────────────────────────────────────┘
```

### Denomination Badge

- Shown as a small badge inline on the card (grey text on light background — not prominent, informational only)
- Possible values: `Sunni` / `Shia` / `Ismaili` / `Ahmadiyya`
- Only shown when denomination is confirmed — never shown as blank or "Unknown"
- Sunni badge is shown when confirmed; omitted when unconfirmed (the majority of mosques are Sunni, so absence is not misleading)

### Card Status Colors

| Dot | Status | Meaning |
|---|---|---|
| 🟢 Green | Can catch with Imam | Leave now/soon, will make congregation |
| 🟡 Yellow | Congregation in progress | Hurry, minutes left |
| 🔵 Blue | Can pray solo | Congregation ended, prayer period active |
| 🟠 Orange | Pray nearby | Can't reach mosque, pray where you are |
| ⚪ Grey | Cannot catch | Prayer period ends before arrival |

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
│  Location                                            │
│  [ Use my current location  ▼ ] or tap the map       │
│                                                      │
│  Name  ___________________________________           │
│        "e.g. Safeway quiet corner, Library Room 2B"  │
│                                                      │
│  Type  ☐ Prayer room    ☐ Halal restaurant           │
│        ☐ Campus         ☐ Rest area / gas station    │
│        ☐ Library        ☐ Other                      │
│                                                      │
│  Facilities (check what you know)                    │
│  ☐ Bathroom / running water available for wudu       │
│  ☐ Indoor                                            │
│  ☐ Open to everyone (men & women)                    │
│  ☐ Men only    ☐ Women only   ☐ Separate spaces      │
│                                                      │
│  Hours (optional)  _______________________________   │
│                                                      │
│  Notes (optional)  _______________________________   │
│  "Tip: mention if manager is accommodating, etc."    │
│                                                      │
│  [ Submit Spot ]                                     │
│                                                      │
│  Anonymous — we don't collect your name or email.    │
└──────────────────────────────────────────────────────┘
```

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
│  Dhuhr    12:45 PM adhan  · 12:55 PM iqama          │
│  Asr       4:15 PM adhan  ·  4:25 PM iqama  ← now  │
│  Maghrib   7:22 PM adhan  ·  7:27 PM iqama          │
│  Isha      8:55 PM adhan  ·  9:10 PM iqama          │
│                                                      │
│  Data source: Scraped from mosque website (3d ago)  │
│                                                      │
│  [  🧭 Navigate  ]  [  📞 Call  ]  [  🌐 Website  ] │
│                                                      │
│  [    🔔 Set Prayer Reminders for this Mosque    ]   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Friday / Jumuah View (when it's Friday or user checks Jumuah times)

```
│  Friday Prayer (Jumuah)                             │
│  ──────────────────────────────────────────────────  │
│  Session 1 · 12:30 PM khutba · 1:00 PM prayer      │
│  Imam: Sheikh Ahmed · English                       │
│  Topic: "The Virtue of Patience"                    │
│                                                      │
│  Session 2 · 1:30 PM khutba · 2:00 PM prayer       │
│  Imam: Dr. Hassan · Arabic/English                  │
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

## Map — Leaflet + OpenStreetMap

```typescript
// Map initialization
const map = L.map('map').setView([userLat, userLng], 14);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 19,
}).addTo(map);

// User location dot (blue pulsing dot)
const userMarker = L.circleMarker([userLat, userLng], {
  radius: 8,
  fillColor: '#3B82F6',
  color: '#FFFFFF',
  weight: 2,
  fillOpacity: 1,
}).addTo(map);

// Mosque pins — color-coded by catching status
function getMosqueMarkerColor(status: CatchingStatus): string {
  switch (status) {
    case 'can_catch_with_imam':      return '#22C55E';  // green
    case 'can_catch_in_progress':    return '#EAB308';  // yellow
    case 'can_pray_solo':            return '#3B82F6';  // blue
    case 'pray_nearby':              return '#F97316';  // orange
    case 'cannot_catch':             return '#9CA3AF';  // grey
    default:                         return '#9CA3AF';
  }
}
```

Tapping a mosque pin opens the same bottom sheet as tapping the mosque card.

---

## State Management (Zustand)

```typescript
interface AppStore {
  // Location
  userLocation: LatLng | null;
  userTimezone: string;

  // Mosques
  mosques: Mosque[];
  selectedMosque: Mosque | null;
  isLoading: boolean;
  error: string | null;

  // Prayer spots (non-mosque)
  prayerSpots: PrayerSpot[];
  selectedSpot: PrayerSpot | null;
  spotsLoading: boolean;

  // Settings
  searchRadiusKm: number;
  travelBufferMinutes: number;
  travelModeEnabled: boolean;
  travelDestination: LatLng | null;
  denominationFilter: 'all' | 'sunni' | 'shia' | 'ismaili' | null;
  showPrayerSpots: boolean;           // user can toggle spots off in settings

  // Notifications
  notificationsEnabled: boolean;
  notificationPreferences: NotificationPreferences;

  // UI
  mapCollapsed: boolean;
  activeBottomSheet:
    | 'mosque_detail'
    | 'spot_detail'
    | 'spot_submit'
    | 'spot_verify'
    | 'navigate'
    | 'settings'
    | 'notifications'
    | null;
}
```

---

## Settings Screen

Accessible from header icon. Bottom sheet or full-page on mobile.

```
Search Settings
  Radius: [  5 km  ▼ ]  (1, 2, 5, 10, 20, 50 km)
  Travel buffer: [ 5 min ▼ ] (0, 5, 10, 15 min)
    "Added to travel time for parking, walking to entrance"

Denomination Filter
  ☑ All mosques (default)
  ☐ Sunni only
  ☐ Shia only
  ☐ Ismaili only
  Note: mosques with unconfirmed denomination are always shown
  "We never hide a mosque just because we don't have denomination data"

Travel Mode
  ☐ I am traveling (enables prayer combination options)
  Destination: [ Enter destination... ]

Prayer Spots
  ☑ Show community prayer spots
    "Non-mosque locations verified by other users"

Display
  ☑ Show adhan times
  ☑ Show iqama times
  ☑ Show data source on each mosque
```

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
  "theme_color": "#1e3a5f",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
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
