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
│     — OSRM route to mosque when selected    │
│     — prayer spot dashed circles            │
│                                 [↗ recenter]│ ← bottom-right, above sheet
│                                             │
│  ┌──────────────────────────────────────┐   │
│  │  ▬ drag handle                       │   │ ← bottom sheet z-400
│  │  3 mosques nearby      (peek: 125px) │   │
│  ├──────────────────────────────────────┤   │
│  │  MosqueCard                          │   │ ← half: ~55vh
│  │  MosqueCard                          │   │
│  │  MosqueCard ...                      │   │
│  └──────────────────────────────────────┘   │
│                                   [+ FAB]   │ ← add spot z-450
│  [بسم الله — Navigate]              z-450   │ ← navigate bar when itinerary
└─────────────────────────────────────────────┘
```

### Z-index layers

| Layer | Z-index | Content |
|-------|---------|---------|
| Map | 0 (base) | Leaflet full-screen |
| Bottom sheet | 400 | Mosque list / mosque detail / trip plan |
| Navigate bar | 450 | Bismillah navigate button (trip itinerary only) |
| Add spot FAB | 495 | Floating + button |
| Trip planning bar | 500 | Search pill / expanded form |
| Spot/Settings sheets | 40–50 (fixed) | Spot detail / settings modal overlays |
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

All elements (pill, search bar, chip, form) are standardized to `h-12` (48px) to keep the top bar height consistent across all states.

**Five states:**

1. **Idle pill** (no destination):
   ```
   [  Where to?                    ]  [🏠 Muqeem] [⚙]
   ```
   Tap → opens destination autocomplete (STATE 2). `tripPlannerOpen` set to `true` synchronously (hides bottom sheet).

2. **Search mode** (destination autocomplete open, no destination confirmed yet):
   - Text input with geocode suggestions dropdown
   - Tapping a suggestion confirms destination → moves to STATE 3

3. **Preview** (destination confirmed, plan not yet loaded):
   ```
   [● Destination name            ✕]  [🏠 Muqeem] [⚙]
   ```
   - Shows "Pray on Route →" CTA button to trigger planning
   - ✕ → `clearAll()`

4. **Chip** (destination + plan loaded, not editing):
   ```
   [● Origin → Destination        ✕]  [🏠 Muqeem] [⚙]
   ```
   Tap → re-opens edit form (STATE 5). ✕ → `clearAll()`.

5. **Edit mode** (expanded from/to/stops form):
   - `bg-white/97 backdrop-blur rounded-2xl shadow-xl`
   - Back button (chevron left, top-left only) → calls `clearAll()` which cancels the trip entirely
   - Field order: Destination → From (with GPS reset button) → waypoints → departure time → Plan button
   - "Add stop" button between From and destination (up to 4 stops)
   - Plan My Prayers button (disabled while loading)
   - Long-trip Musafir suggestion: trips > 160 km in Muqeem mode → modal dialog (not inline banner)

**Form field labels (no emoji icons):**
- Destination: `placeholder="Where to?"` — no prefix label
- Origin: `"From:"` text label + GPS reset button (nav arrow icon)
- Waypoints: `"A:"`, `"B:"`, `"C:"`, `"D:"` — letter labels matching map markers

**`clearAll()` behavior:**
Clears all trip state, sets `tripPlannerOpen(false)` synchronously, resets `selectedMosqueId` / `mapFocusCoords` / `selectedItineraryIndex` / `singleMosqueNav`, snaps sheet to `peek`, triggers `MapCenterer` to re-zoom to user radius. Also clears the plan cache.

**Origin auto-populate:**
`useEffect` with `[userLocation, editMode]` deps — re-geocodes current location into the "From:" field whenever the form opens, so it always repopulates after `clearAll()`.

**Plan caching:**
`planCacheRef` (Map) keyed by `mode|origin|dest|waypoints|departure`. Auto-replans on Muqeem ↔ Musafir toggle using cache. Cache is cleared on `clearAll()`.

**Long-trip modal:**
When a trip > 160 km is planned in Muqeem mode, a centered modal dialog appears asking the user to switch to Musafir or continue as Muqeem — does NOT open the edit form.

### ModeToggle

Single pill button — shows current mode, always positioned `absolute top-3 right-3` inside the top overlay (never shifts between form states):
- `🏠 Muqeem` → teal background
- `✈️ Musafir` → indigo background

### SettingsButton

Standalone button next to ModeToggle. Gear icon. Opens `settings` bottom sheet via the modal overlay system.

### MapBottomSheet

Draggable sheet using `position: fixed; top: var(--top-bar-bottom, 140px); bottom: 0; left: 0; right: 0; z-[400]`. The `top` property directly pins the sheet's upper bound below the search bar — no `height: calc()` involved.

**Three snap states:**

| State | Visible height | translateY |
|-------|---------------|------------|
| `peek` | 125px | `offsetHeight - 125` |
| `half` | ~55vh | `offsetHeight - 55vh` |
| `full` | full sheet | `0` |

Drag handle at top activates touch drag. On release, snaps to nearest state using `DOMMatrix` to read current transform.

**`--sheet-visible` CSS variable:**
Updated in real-time during drag (`handleTouchMove`) and on every snap (`useEffect` on `[bottomSheetHeight, tripPlannerOpen]`). Value = sheet `offsetHeight - translateY` (pixels currently visible). Used by FAB and LocationButton to track the sheet without React re-renders. When `tripPlannerOpen=true`, set to `0` (sheet fully off-screen).

**Auto-transitions:**
- `travelPlan` loads → snap to `half` (shows itinerary options)
- `travelDestination` cleared → snap to `peek`
- `singleMosqueNav` set → snap to `half` (shows mosque detail)
- Detail modal (spot/settings) closes from `full` → snap to `half` (restores FAB visibility)

**No auto-snap on itinerary selection** — expanding/collapsing a `TravelItineraryCard` just toggles that card in place; the sheet does not snap to peek.

**Hidden while editing:**
When `tripPlannerOpen=true` (form is expanded), sheet translates fully off-screen (`translateY = window.innerHeight`).

**Mosque detail dismissal:**
Tapping the ✕ button (top-right of the mosque detail header) calls `onDismiss`: clears `singleMosqueNav` + `selectedMosqueId`, snaps to `peek`, mosque list returns. The sheet itself snaps normally (peek/half/full) — no special drag-past-peek behavior in mosque mode.

**Content (in priority order):**
1. `singleMosqueNav && !travelDestination` → `MosqueDetailSheet` (mosque detail, inline)
2. `travelDestination` → `TravelPlanView` (loading spinner or itinerary options)
3. default → mosque list + prayer spots + prayed banner + last resort card

### MosqueCard

- `rounded-2xl border shadow-sm` with status-color left border accent
- Status icons (from `STATUS_CONFIG`) with colored header background
- Musafir combining section: shows `{pair.label} — Musafir` text only (no emoji)
- "Already prayed" inline button: neutral `border-gray-200 text-gray-500`
- **Tap** → sets `singleMosqueNav(mosque)` + `setSelectedMosqueId` + snaps sheet to `half`; does NOT open a modal overlay

### MosqueDetailSheet

Rendered **inline inside `MapBottomSheet`** when `singleMosqueNav` is set (no longer a floating modal overlay for mosque details).

**Header row** (`flex items-center justify-between`):
- Left: mosque address (small gray text) — or empty space if no address
- Right (top-right icon buttons):
  - **Globe icon** — links to mosque website (shown only if `mosque.website` exists); `bg-gray-100` rounded circle
  - **Directions diamond-arrow icon** (Google Maps style) — theme-colored rounded circle; opens navigate action sheet

**No bottom action bar** — all actions are in the top-right icons.

**✕ close button** — top-right of the header row; calls `onDismiss` to return to the mosque list.

**Navigate action sheet** — portaled to `document.body`; Google Maps / Apple Maps (iOS only) / Share options.

**`onDismiss` prop** — passed from `MapBottomSheet`; calls `setSingleMosqueNav(null)` + `setSelectedMosqueId(null)` + `setBottomSheetHeight('peek')`.

### NavigateBar

`fixed` inside the top overlay's pointer-events strip — appears **only when a trip itinerary is selected** (not for single-mosque quick-nav, which uses the in-sheet directions icon).

- Single button: **بسم الله — Navigate**
- Tap → action sheet portaled to `document.body`: Google Maps / Apple Maps (iOS only) / Share Route
- Opening action sheet sets `navShareOpen=true` in Zustand store (hides LocationButton)
- Waypoints built from selected itinerary's prayer stops in trip order
- Google Maps: `place_id` if available, else `lat,lng`
- Apple Maps: `Name@lat,lng` format
- Cancel buttons have both `onClick` and `onTouchEnd` handlers for iOS reliability
- **Hidden** when `tripPlannerOpen=true`

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
- Tap → `map.flyTo(userLocation, zoom)` adjusted by half the sheet height so the pin lands in the visible area above the sheet
- **Hidden** when: `bottomSheetHeight === 'full'` OR `bottomSheet !== null` (spot/settings modal open) OR `navShareOpen === true` OR `travelPlanLoading === true`

---

## Map Behavior

- **Full-screen** — fills `fixed inset-0`, no height constraint
- **Zoom controls** disabled (mobile users pinch-zoom)
- **Attribution control** disabled (`attributionControl={false}`) — Leaflet footer hidden
- **Mosque pins**: status-colored teardrops; selected pin is larger
- **Prayer spot circles**: dashed circle, theme `hex` stroke, `hexLight` fill
- **User location**: theme-colored dot + pulse ring
- **Trip route polyline**: theme color, weight 4, opacity 0.7; `key` prop forces remount on plan/itinerary change; only shown when `travelDestination` is set
- **Single-mosque route polyline**: real road geometry fetched from OSRM (`router.project-osrm.org`) when a mosque is selected; theme color, weight 4, opacity 0.75; cleared when `singleMosqueNav` is null
- **Route stop pins**: theme-colored teardrops with permanent tooltip (mosque name)
- **Origin/destination markers**: circle badges labeled A (theme) / B (red)
- **FitBoundsController**: four effects for different fit scenarios (see below)
- **MapCenterer**: re-zooms to user's search radius when `travelDestination` is cleared (trip cancelled) and no mosque is selected

### FitBoundsController Effects

| # | Trigger | Behavior |
|---|---------|----------|
| 1 | `selectedMosqueId` or `mapFocusCoords` changes | Fit user + mosque with asymmetric padding: `paddingTopLeft=[40, topBarBottom+20]`, `paddingBottomRight=[40, sheetVisiblePx('half')+20]`, `maxZoom:15` |
| 2 | `selectedItineraryIndex`, `bottomSheetHeight`, or `tripPlannerOpen` changes | Fit itinerary route geometry (or stop coords fallback) in visible area; skipped while `tripPlannerOpen=true` |
| 3 | `travelDestination`, `travelOrigin`, `tripWaypoints`, or `tripPlannerOpen` changes | In edit mode: fit all configured points with 350ms delay to let ResizeObserver update `--top-bar-bottom` |
| 4 | `travelDestination`, `travelPlan`, or `tripPlannerOpen` changes | Fit full trip route on plan load or when edit panel closes; skipped while `tripPlannerOpen=true` |

**`sheetVisiblePx(height)`** helper — computes sheet visible height from React state directly (avoids CSS var race conditions): `full` → `window.innerHeight`, `half` → `window.innerHeight * 0.55`, `peek` → `125`.

---

## State Management (Zustand)

Key UI state fields:

| Field | Type | Purpose |
|-------|------|---------|
| `travelMode` | `boolean` | Muqeem=false / Musafir=true |
| `bottomSheetHeight` | `'peek'\|'half'\|'full'` | Bottom sheet snap state |
| `tripPlannerOpen` | `boolean` | Form expanded → sheet off-screen |
| `selectedItineraryIndex` | `number\|null` | Which route option is selected |
| `selectedMosqueId` | `string\|null` | Which mosque pin is highlighted |
| `mapFocusCoords` | `{lat,lng}\|null` | Arbitrary map focus (e.g. route stop) |
| `singleMosqueNav` | `Mosque\|null` | Mosque selected for quick-nav (shows detail in sheet + OSRM route on map) |
| `bottomSheet` | `BottomSheet\|null` | Active modal overlay (spot\_detail / settings only) |
| `travelPlan` | `TravelPlan\|null` | Computed prayer route plan |
| `travelPlanLoading` | `boolean` | Plan button disabled while true; hides LocationButton |
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

`MapView` shows `selectedItinerary.route_geometry` when an itinerary is selected; falls back to `travelPlan.route.route_geometry`. Route is only rendered when `travelDestination` is set (guards against stale geometry after `clearAll()`).

The `Polyline` component uses `key={route-${selectedItineraryIndex}-${departure_time}}` to force remount and clear old routes when switching itineraries.

---

## Single-Mosque Quick Navigation

When a user taps any mosque (from the nearby list or directly on the map pin):

1. `singleMosqueNav` is set to the `Mosque` object
2. `selectedMosqueId` is set (enlarges the map pin)
3. `MapBottomSheet` snaps to `half` and renders `MosqueDetailSheet` inline
4. `MapView` fetches the real road route from OSRM and renders it as a solid polyline
5. `FitBoundsController` fits the map to show user + mosque with half-sheet padding
6. The mosque detail shows: address, prayer times table, status badge, Jumu'ah times, data source
7. Top-right icons: globe (website) + directions diamond-arrow (opens Google/Apple Maps action sheet) + ✕ (dismiss)
8. Dismiss: tap ✕ → clears `singleMosqueNav` + `selectedMosqueId`, snaps sheet to `peek`, mosque list reappears
