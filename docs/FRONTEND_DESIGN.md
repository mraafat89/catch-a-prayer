# Frontend Design

## Design Philosophy

This app is used on a mobile phone, often while standing outside or in a car. The design must be:

- **Glanceable**: The most important information (can I catch this prayer? how long do I have?) must be readable in 2 seconds without tapping anything
- **One-handed**: All key interactions reachable with one thumb
- **Low cognitive load**: Use color + icon to communicate status instantly, not just text
- **Fast**: No spinners on the main view — show stale data immediately, update silently
- **Map-first**: Full-screen map at all times — overlays float above it, nothing scrolls off-screen

---

## Layout Structure

The app is a **full-screen, single-page layout** with no scrolling at the root level. Everything is layered over a full-screen Leaflet map.

```
┌─────────────────────────────────────────────┐
│  [🔍 Where to?            ] [🏠 Muqeem] [⚙] │ ← top overlay z-500
│                                             │
│                                             │
│     Leaflet Map (full screen)               │
│     — status-colored mosque pins            │
│     — theme-colored user dot + pulse ring   │
│     — route polyline when trip active       │
│     — prayer spot dashed circles            │
│                                 [📍 recenter]│ ← bottom-right, above sheet
│                                             │
│  ┌──────────────────────────────────────┐   │
│  │  ▬ drag handle                       │   │ ← bottom sheet z-400
│  │  3 mosques nearby      (peek: 80px)  │   │
│  ├──────────────────────────────────────┤   │
│  │  MosqueCard                          │   │ ← half: ~50vh
│  │  MosqueCard                          │   │
│  │  MosqueCard ...                      │   │
│  └──────────────────────────────────────┘   │
│                                   [+ FAB]   │ ← add spot z-450
│  [بسم الله — Navigate]              z-450   │ ← navigate bar when route
└─────────────────────────────────────────────┘
```

### Z-index layers

| Layer | Z-index | Content |
|-------|---------|---------|
| Map | 0 (base) | Leaflet full-screen |
| Bottom sheet | 400 | Mosque list / trip plan |
| Navigate bar | 450 | Bismillah navigate button |
| Add spot FAB | 450 | Floating + button |
| Trip planning bar | 500 | Search pill / expanded form |
| Detail sheets | 40–50 (fixed) | Mosque/spot/settings |

---

## Two-Mode Theme System

Two complete color schemes, toggled via a single pill button (top right of trip planning bar).

| Key | Muqeem (resident) | Musafir (traveler) |
|-----|-------------------|--------------------|
| Primary bg | `bg-teal-600` | `bg-indigo-600` |
| Dark bg | `bg-teal-700` | `bg-indigo-700` |
| Light bg | `bg-teal-50` | `bg-indigo-50` |
| Hex | `#0d9488` | `#6366f1` |
| Polyline | teal | indigo |
| User dot | teal | indigo |
| Map pins | teal | indigo |
| Spot circles | teal dashed | indigo dashed |

All theme values live in `client/src/theme.ts`. `useTheme()` reads `travelMode` from Zustand and returns the active theme object.

---

## Components

### TripPlanningBar (DestinationInput)

Floating overlay at `absolute top-0 left-0 right-0 z-[500]`.

**Three states:**

1. **Idle pill** (`formExpanded=false`, no destination):
   ```
   [🔍 Where to?                    ] [🏠 Muqeem] [⚙]
   ```
   Tap the pill → expands to full form.

2. **Active chip** (destination + plan loaded, not editing):
   ```
   [● Origin → Destination        ✕] [🏠 Muqeem] [⚙]
   ```
   Tap → re-opens form for editing. ✕ → clears trip.

3. **Expanded form card** (tap from idle or chip):
   - `bg-white/97 backdrop-blur rounded-2xl shadow-xl`
   - Header row: back button + "Plan Trip" label + ModeToggle + Settings
   - Fields: Origin (GPS default) → optional waypoints → Destination → departure time
   - "Add stop" button appears after destination is set (up to 4 stops)
   - Plan My Prayers button (disabled while loading)
   - Long-trip Musafir suggestion banner (trips > 160 km in Muqeem mode)

### ModeToggle

Single pill button — shows current mode with emoji, tap to toggle:
- `🏠 Muqeem` → teal background
- `✈️ Musafir` → indigo background

### MapBottomSheet

Draggable bottom sheet at `fixed bottom-0 left-0 right-0 h-[85vh] z-[400]`.

**Three snap states:**

| State | Visible height | translateY |
|-------|---------------|------------|
| `peek` | 80px | `85vh - 80px` |
| `half` | ~52vh | `85vh - 52vh` |
| `full` | 85vh | `0` |

Drag handle at top activates touch drag. On release, snaps to nearest state using `DOMMatrix` to read current transform.

**Auto-transitions:**
- `travelPlan` loads → snap to `half`
- Itinerary selected → snap to `peek` (route fills map)
- Destination cleared → snap to `half`
- Tap peek label → toggle peek ↔ half

**Content:**
- When `travelDestination` null: mosque list + prayer spots + prayed banner + last resort card
- When `travelDestination` set: `TravelPlanView` (loading spinner or itinerary options)

### NavigateBar

`fixed bottom-[88px] left-3 right-3 z-[450]` — appears only when an itinerary is selected.

- Single button: **بسم الله — Navigate**
- Tap → action sheet: Google Maps / Apple Maps (iOS only) / Share Route
- Waypoints built from selected itinerary's prayer stops in trip order
- Google Maps: `place_id` if available, else mosque name search query
- Apple Maps: `Name@lat,lng` format (coordinates + label)

### AddSpotFAB

`fixed right-4 bottom-[100px] z-[450]` — circular theme-colored `+` button.
Only shown when `showSpots=true` and no trip destination is set.
Opens `SpotSubmitSheet`.

### LocationButton (inside MapView)

`leaflet-bottom leaflet-right` positioned above the bottom sheet peek.

- Arrow/navigation icon
- **Gray** when current location is within visible map bounds
- **Theme color** when user has panned away (location is off-screen)
- Tap → `map.flyTo(userLocation, zoom)` to recenter

---

## Card Design

### MosqueCard

- `rounded-2xl border shadow-sm` with status-color left border accent
- Status icons (from `STATUS_CONFIG`) with colored header background
- "Already prayed" inline button: neutral `border-gray-200 text-gray-500`
- Tap → opens `MosqueDetailSheet` + selects map pin

### SpotCard

- `rounded-xl border bg-white` with theme `border` color
- Verification badge: `th.bgLight th.text` pill
- Facilities: clean slate pills (`bg-slate-100 text-slate-600`), no emojis
- "I prayed here" button: theme border + text, confirmed state uses theme light bg

### TravelItineraryCard

- `rounded-xl border shadow-sm`; selected card: `th.borderStrong th.shadow`
- Header: Option N label in theme color, itinerary label, detour duration
- Expanded: prayer pair details, mosque stop buttons (tap to focus map pin)
- Tapping header: selects itinerary + snaps bottom sheet to `peek`

### MosqueDetailSheet / SpotDetailSheet

- Clean white background, `rounded-2xl`
- Jumu'ah card: `th.bgLight th.border` theme-tinted
- Action buttons: Directions = `th.bg`, Call/Website = `bg-slate-700`
- Spot badges: slate pills (no emojis), wudu badge uses theme light
- Confirm / Get Directions: `th.bg th.bgHover`

### SpotSubmitSheet

- Submit and Done buttons: `th.bg th.bgHover`
- Focus rings: `focus:ring-current`
- Range slider: `style={{ accentColor: th.hex }}`

---

## Map Behavior

- **Full-screen** — fills `fixed inset-0`, no height constraint
- **Zoom controls** disabled (mobile users pinch-zoom)
- **Mosque pins**: status-colored teardrops; selected pin is larger
- **Prayer spot circles**: dashed circle, theme `hex` stroke, `hexLight` fill
- **User location**: theme-colored dot + pulse ring
- **Route polyline**: theme color, weight 4, opacity 0.7; `key` prop forces remount on plan/itinerary change
- **Route stop pins**: theme-colored teardrops with permanent tooltip (mosque name)
- **Origin/destination markers**: circle badges labeled A (theme) / B (red)
- **FitBoundsController**: auto-fits map to show selected mosque + user, or full trip route

---

## State Management (Zustand)

Key UI state fields:

| Field | Type | Purpose |
|-------|------|---------|
| `travelMode` | `boolean` | Muqeem=false / Musafir=true |
| `bottomSheetHeight` | `'peek'|'half'|'full'` | Bottom sheet snap state |
| `selectedItineraryIndex` | `number|null` | Which route option is selected |
| `selectedMosqueId` | `string|null` | Which mosque pin is highlighted |
| `mapFocusCoords` | `{lat,lng}|null` | Arbitrary map focus (e.g. route stop) |
| `bottomSheet` | `BottomSheet|null` | Active detail sheet (mosque/spot/settings) |
| `travelPlan` | `TravelPlan|null` | Computed prayer route plan |
| `travelPlanLoading` | `boolean` | Plan button disabled while true |

`mapCollapsed` is kept for backwards-compat but has no visual effect in the new full-screen layout.

---

## Smart Jam' Display (Musafir Mode)

When `travelMode=true`, mosque cards and detail sheets show combining options (Jam' Taqdeem / Ta'kheer) for Dhuhr+Asr and Maghrib+Isha pairs.

**Display rules:**
- Only show the **first unresolved** prayer pair (skip pairs already prayed)
- Show **Taqdeem** if currently before Asr / before Isha
- Show **Ta'kheer** if currently after Asr / after Isha (with "not missed" note)
- If both available (before second prayer): show Taqdeem as primary, Ta'kheer as secondary

---

## Per-Itinerary Route Geometry

Each `TripItinerary` has its own `route_geometry: [lat, lng][]` computed server-side via parallel `asyncio.gather` routing calls through that itinerary's prayer stops in trip order.

`MapView` shows `selectedItinerary.route_geometry` when an itinerary is selected; falls back to `travelPlan.route.route_geometry`.

The `Polyline` component uses `key={route-${selectedItineraryIndex}-${departure_time}}` to force remount and clear old routes when switching itineraries.
