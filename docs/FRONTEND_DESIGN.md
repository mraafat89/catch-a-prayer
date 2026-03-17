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
│  [Where to?               ] [🏠 Muqeem] [⚙] │ ← top overlay z-500
│                                             │
│                                             │
│     Leaflet Map (full screen)               │
│     — status-colored mosque pins            │
│     — theme-colored user dot + pulse ring   │
│     — route polyline when trip active       │
│     — prayer spot dashed circles            │
│                                 [↗ recenter]│ ← bottom-right, above sheet
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
| Add spot FAB | 495 | Floating + button |
| Trip planning bar | 500 | Search pill / expanded form |
| Detail sheets | 40–50 (fixed) | Mosque/spot/settings |
| Nav share action sheet | portal | Portaled to document.body |

---

## Two-Mode Theme System

Two complete color schemes, toggled via a single pill button (top right, always visible).

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

### Top Overlay Structure

The entire top bar is a single `absolute top-0 left-0 right-0 z-[500] pointer-events-none` div (`id="top-overlay"`, measured by `ResizeObserver`). Its children use `pointer-events-auto` selectively.

Inside it:
- `DestinationInput` — left-aligned search pill/form with `paddingRight` to avoid overlapping buttons
- `ModeToggle` + `SettingsButton` — `absolute top-3 right-3` inside the overlay, always visible in all form states

A `ResizeObserver` on `#top-overlay` measures `getBoundingClientRect().bottom + 8px` and writes it to the `--top-bar-bottom` CSS variable. Multiple fallback timings (`requestAnimationFrame` + `setTimeout` at 150ms and 500ms) handle iOS deferred safe-area layout.

### TripPlanningBar (DestinationInput)

Floating overlay at `absolute top-0 left-0 right-0 z-[500]`. Uses `paddingRight: 220px` to leave space for ModeToggle + SettingsButton.

**Three states:**

1. **Idle pill** (`formExpanded=false`, no destination):
   ```
   [  Where to?                    ]  [🏠 Muqeem] [⚙]
   ```
   Tap → expands form inline. `tripPlannerOpen` is set to `true` synchronously on click (hides bottom sheet immediately).

2. **Active chip** (destination + plan loaded, not editing):
   ```
   [● Origin → Destination       ✕]  [🏠 Muqeem] [⚙]
   ```
   Tap → re-opens form for editing. ✕ → calls `clearAll()`.

3. **Expanded form card** (tap from idle or chip):
   - `bg-white/97 backdrop-blur rounded-2xl shadow-xl`
   - **No "Plan Trip" header** — form starts directly with destination field
   - Field order: back arrow + Destination → From → waypoints → departure time → Plan button
   - Back button (chevron left) calls `clearAll()` which cancels the trip entirely and re-zooms map to current location
   - "Add stop" button appears after destination is set (up to 4 stops)
   - Plan My Prayers button (disabled while loading)
   - Long-trip Musafir suggestion banner (trips > 160 km in Muqeem mode)

**Form field labels (no emoji icons):**
- Destination: `placeholder="Where to?"` — no prefix label (matches idle pill text)
- Origin: `icon="From:"` text label
- Waypoints: `icon="A:"`, `"B:"`, `"C:"`, `"D:"` — letter labels matching map markers

**`clearAll()` behavior:**
Clears all trip state, sets `tripPlannerOpen(false)` synchronously, resets `selectedMosqueId`/`mapFocusCoords`, snaps sheet to `peek`, triggers `MapCenterer` to re-zoom to user radius.

**Origin auto-populate:**
`useEffect` with `[userLocation, formExpanded]` deps — re-geocodes current location into the "From:" field whenever the form opens, so it always repopulates after `clearAll()`.

### ModeToggle

Single pill button — shows current mode, always positioned `absolute top-3 right-3` inside the top overlay (never shifts between form states):
- `🏠 Muqeem` → teal background
- `✈️ Musafir` → indigo background

### SettingsButton

Standalone button `absolute top-3 right-3` (inside overlay, next to ModeToggle). Gear icon. Opens `settings` bottom sheet.

### MapBottomSheet

Draggable sheet using `position: fixed; top: var(--top-bar-bottom, 140px); bottom: 0; left: 0; right: 0; z-[400]`. The `top` property directly pins the sheet's upper bound below the search bar — no `height: calc()` involved.

**Three snap states:**

| State | Visible height | translateY |
|-------|---------------|------------|
| `peek` | 80px | `offsetHeight - 80` |
| `half` | ~52vh | `offsetHeight - 52vh` |
| `full` | full sheet | `0` |

Drag handle at top activates touch drag. On release, snaps to nearest state using `DOMMatrix` to read current transform.

**`--sheet-visible` CSS variable:**
Updated in real-time during drag (`handleTouchMove`) and on every snap (`useEffect` on `[bottomSheetHeight, tripPlannerOpen]`). Value = sheet `offsetHeight - translateY` (pixels currently visible). Used by FAB and LocationButton to track the sheet without React re-renders. When `tripPlannerOpen=true`, set to `0` (sheet fully off-screen).

**Auto-transitions:**
- `travelPlan` loads → snap to `half` (shows itinerary options)
- Destination cleared → snap to `peek`
- Detail modal closes from `full` → snap to `half` (restores FAB visibility)

**No auto-snap on itinerary selection** — expanding/collapsing a `TravelItineraryCard` just toggles that card in place; the sheet does not snap to peek.

**Hidden while editing:**
When `tripPlannerOpen=true` (form is expanded or chip is open), sheet translates fully off-screen (`translateY = window.innerHeight`). `tripPlannerOpen` is set synchronously on form open and cleared synchronously in `clearAll()`.

**Content:**
- When `travelDestination` null: mosque list + prayer spots + prayed banner + last resort card
- When `travelDestination` set: `TravelPlanView` (loading spinner or itinerary options)

### NavigateBar

`fixed bottom-[88px] left-3 right-3 z-[450]` — appears only when an itinerary is selected.

- Single button: **بسم الله — Navigate**
- Tap → action sheet portaled to `document.body` (escapes overlay stacking context): Google Maps / Apple Maps (iOS only) / Share Route
- Opening action sheet sets `navShareOpen=true` in Zustand store
- Waypoints built from selected itinerary's prayer stops in trip order
- Google Maps: `place_id` if available, else mosque name search query
- Apple Maps: `Name@lat,lng` format (coordinates + label)
- Cancel buttons have both `onClick` and `onTouchEnd` handlers for iOS reliability

### AddSpotFAB

`position: fixed; z-[495]` with `bottom: calc(var(--sheet-visible, 125px) + 64px); right: 16px`.
Only shown when `showSpots=true` and no trip destination is set.
**No `transition-all`** — only `active:scale-95` scale transition (prevents lag during sheet drag).
Opens `SpotSubmitSheet`.

### LocationButton (inside MapView)

Rendered via `ReactDOM.createPortal` into `document.body`.

- `position: fixed; bottom: calc(var(--sheet-visible, 125px) + 12px); right: 12px` — tracks sheet via CSS var, no JS polling
- **Gray** when current location is within visible map bounds
- **Theme color** when user has panned away (location is off-screen)
- Tap → `map.flyTo(userLocation, zoom)` to recenter
- **Hidden** when: `bottomSheetHeight === 'full'` OR `bottomSheet !== null` (detail modal open) OR `navShareOpen === true` (nav action sheet showing)

---

## Card Design

### MosqueCard

- `rounded-2xl border shadow-sm` with status-color left border accent
- Status icons (from `STATUS_CONFIG`) with colored header background
- Musafir combining section: shows `{pair.label} — Musafir` text only (no emoji, no plane icon)
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
- Tapping header: toggles expand/collapse + selects itinerary — **does NOT snap sheet to peek**
- Expanded: prayer pair details, mosque stop buttons (tap focuses map pin + snaps sheet to peek)

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
- **Attribution control** disabled (`attributionControl={false}`) — Leaflet footer hidden
- **Mosque pins**: status-colored teardrops; selected pin is larger
- **Prayer spot circles**: dashed circle, theme `hex` stroke, `hexLight` fill
- **User location**: theme-colored dot + pulse ring
- **Route polyline**: theme color, weight 4, opacity 0.7; `key` prop forces remount on plan/itinerary change
- **Route stop pins**: theme-colored teardrops with permanent tooltip (mosque name)
- **Origin/destination markers**: circle badges labeled A (theme) / B (red)
- **FitBoundsController**: auto-fits map to show selected mosque + user, or full trip route
- **MapCenterer**: re-zooms to user's search radius when `travelDestination` is cleared (trip cancelled)

---

## State Management (Zustand)

Key UI state fields:

| Field | Type | Purpose |
|-------|------|---------|
| `travelMode` | `boolean` | Muqeem=false / Musafir=true |
| `bottomSheetHeight` | `'peek'|'half'|'full'` | Bottom sheet snap state |
| `tripPlannerOpen` | `boolean` | Form expanded → sheet off-screen |
| `selectedItineraryIndex` | `number|null` | Which route option is selected |
| `selectedMosqueId` | `string|null` | Which mosque pin is highlighted |
| `mapFocusCoords` | `{lat,lng}|null` | Arbitrary map focus (e.g. route stop) |
| `bottomSheet` | `BottomSheet|null` | Active detail sheet (mosque/spot/settings) |
| `travelPlan` | `TravelPlan|null` | Computed prayer route plan |
| `travelPlanLoading` | `boolean` | Plan button disabled while true |
| `navShareOpen` | `boolean` | Nav action sheet visible → hides LocationButton |

**CSS variables** (written by React, read by CSS):
- `--top-bar-bottom`: px value of top overlay's bottom edge + 8px margin; caps sheet `top`
- `--sheet-visible`: px of sheet currently above fold; drives FAB and LocationButton `bottom`

`mapCollapsed` is kept for backwards-compat but has no visual effect in the current full-screen layout.

---

## Smart Jam' Display (Musafir Mode)

When `travelMode=true`, mosque cards and detail sheets show combining options (Jam' Taqdeem / Ta'kheer) for Dhuhr+Asr and Maghrib+Isha pairs.

**Display rules:**
- Only show the **first unresolved** prayer pair (skip pairs already prayed)
- Show **Taqdeem** if currently before Asr / before Isha
- Show **Ta'kheer** if currently after Asr / after Isha (with "not missed" note)
- If both available (before second prayer): show Taqdeem as primary, Ta'kheer as secondary
- Section header shows `{pair.label} — Musafir` text only — no emojis

---

## Per-Itinerary Route Geometry

Each `TripItinerary` has its own `route_geometry: [lat, lng][]` computed server-side via parallel `asyncio.gather` routing calls through that itinerary's prayer stops in trip order.

`MapView` shows `selectedItinerary.route_geometry` when an itinerary is selected; falls back to `travelPlan.route.route_geometry`.

The `Polyline` component uses `key={route-${selectedItineraryIndex}-${departure_time}}` to force remount and clear old routes when switching itineraries.
