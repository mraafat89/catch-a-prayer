import { create } from 'zustand';
import { Mosque, PrayerSpot, LatLng, TravelDestination, TravelPlan } from './types';

// Confirmed spots tracker — persisted across sessions (spot confirmation is permanent)
function loadConfirmed(): Set<string> {
  try {
    const raw = localStorage.getItem('cap_confirmed_spots');
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch { return new Set(); }
}
function saveConfirmed(set: Set<string>) {
  localStorage.setItem('cap_confirmed_spots', JSON.stringify(Array.from(set)));
}

// Prayed tracker — keyed by today's date so it auto-resets at midnight
function todayKey(): string {
  return new Date().toISOString().slice(0, 10); // "YYYY-MM-DD"
}
function loadPrayed(): Set<string> {
  try {
    const raw = localStorage.getItem(`cap_prayed_${todayKey()}`);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch { return new Set(); }
}
function savePrayed(set: Set<string>) {
  localStorage.setItem(`cap_prayed_${todayKey()}`, JSON.stringify(Array.from(set)));
}

// Stable anonymous session ID (persisted in localStorage)
function getSessionId(): string {
  const key = 'cap_session_id';
  let id = localStorage.getItem(key);
  if (!id) {
    id = `cap-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(key, id);
  }
  return id;
}

export const SESSION_ID = getSessionId();

type BottomSheet =
  | { type: 'mosque_detail'; mosque: Mosque }
  | { type: 'spot_detail'; spot: PrayerSpot }
  | { type: 'spot_submit' }
  | { type: 'settings' }
  | null;

interface AppState {
  // Location
  userLocation: LatLng | null;
  setUserLocation: (loc: LatLng) => void;

  // Mosques
  mosques: Mosque[];
  setMosques: (m: Mosque[]) => void;
  mosquesLoading: boolean;
  setMosquesLoading: (v: boolean) => void;
  mosquesError: string | null;
  setMosquesError: (e: string | null) => void;

  // Prayer spots
  spots: PrayerSpot[];
  setSpots: (s: PrayerSpot[]) => void;
  spotsLoading: boolean;
  setSpotsLoading: (v: boolean) => void;

  // Settings
  radiusKm: number;
  setRadiusKm: (r: number) => void;
  denominationFilter: 'all' | 'sunni' | 'shia' | 'ismaili';
  setDenominationFilter: (f: 'all' | 'sunni' | 'shia' | 'ismaili') => void;
  showSpots: boolean;
  setShowSpots: (v: boolean) => void;
  travelMode: boolean;
  setTravelMode: (v: boolean) => void;

  // Travel destination + plan (route-based travel mode)
  travelOrigin: TravelDestination | null;        // null = use GPS current location
  setTravelOrigin: (o: TravelDestination | null) => void;
  travelDestination: TravelDestination | null;
  setTravelDestination: (d: TravelDestination | null) => void;
  travelDepartureTime: string | null;            // ISO datetime string; null = now
  setTravelDepartureTime: (t: string | null) => void;
  tripWaypoints: TravelDestination[];            // intermediate stops (0–4)
  setTripWaypoints: (wps: TravelDestination[]) => void;
  travelPlan: TravelPlan | null;
  travelPlanVersion: number;  // increments on each new plan — used to force Polyline remount
  setTravelPlan: (p: TravelPlan | null) => void;
  travelPlanLoading: boolean;
  setTravelPlanLoading: (v: boolean) => void;
  travelPlanError: string | null;
  setTravelPlanError: (e: string | null) => void;

  // Prayed tracker — set<"YYYY-MM-DD:prayer"> persisted in localStorage
  prayedToday: Set<string>;
  togglePrayed: (prayer: string) => void;
  togglePrayedPair: (p1: string, p2: string) => void;

  // Confirmed spots — set<spot_id> persisted permanently in localStorage
  confirmedSpots: Set<string>;
  addConfirmedSpot: (spotId: string) => void;

  // UI
  mapCollapsed: boolean;
  setMapCollapsed: (v: boolean) => void;
  bottomSheetHeight: 'peek' | 'half' | 'full';
  setBottomSheetHeight: (h: 'peek' | 'half' | 'full') => void;
  tripPlannerOpen: boolean;
  setTripPlannerOpen: (v: boolean) => void;
  selectedItineraryIndex: number | null;
  setSelectedItineraryIndex: (i: number | null) => void;
  selectedMosqueId: string | null;
  setSelectedMosqueId: (id: string | null) => void;
  // Focus arbitrary coords on the map (e.g., route stop mosque not in nearby list)
  mapFocusCoords: { lat: number; lng: number } | null;
  setMapFocusCoords: (c: { lat: number; lng: number } | null) => void;
  bottomSheet: BottomSheet;
  openSheet: (sheet: BottomSheet) => void;
  closeSheet: () => void;
  // True while the navigate-to action sheet (Google/Apple/Share) is visible
  navShareOpen: boolean;
  setNavShareOpen: (v: boolean) => void;
  // Single-mosque quick-nav: tap a mosque in the list to see route + Bismillah button
  singleMosqueNav: Mosque | null;
  setSingleMosqueNav: (m: Mosque | null) => void;
}

export const useStore = create<AppState>((set) => ({
  userLocation: null,
  setUserLocation: (loc) => set({ userLocation: loc }),

  mosques: [],
  setMosques: (mosques) => set({ mosques }),
  mosquesLoading: false,
  setMosquesLoading: (mosquesLoading) => set({ mosquesLoading }),
  mosquesError: null,
  setMosquesError: (mosquesError) => set({ mosquesError }),

  spots: [],
  setSpots: (spots) => set({ spots }),
  spotsLoading: false,
  setSpotsLoading: (spotsLoading) => set({ spotsLoading }),

  radiusKm: 10,
  setRadiusKm: (radiusKm) => set({ radiusKm }),
  denominationFilter: 'all',
  setDenominationFilter: (denominationFilter) => set({ denominationFilter }),
  showSpots: true,
  setShowSpots: (showSpots) => set({ showSpots }),
  travelMode: false,
  setTravelMode: (travelMode) => set({ travelMode }),

  travelOrigin: null,
  setTravelOrigin: (travelOrigin) => set({ travelOrigin }),
  travelDestination: null,
  setTravelDestination: (travelDestination) => set({ travelDestination }),
  travelDepartureTime: null,
  setTravelDepartureTime: (travelDepartureTime) => set({ travelDepartureTime }),
  tripWaypoints: [],
  setTripWaypoints: (tripWaypoints) => set({ tripWaypoints }),
  travelPlan: null,
  travelPlanVersion: 0,
  setTravelPlan: (travelPlan) => set((s) => ({ travelPlan, travelPlanVersion: travelPlan ? s.travelPlanVersion + 1 : s.travelPlanVersion })),
  travelPlanLoading: false,
  setTravelPlanLoading: (travelPlanLoading) => set({ travelPlanLoading }),
  travelPlanError: null,
  setTravelPlanError: (travelPlanError) => set({ travelPlanError }),

  prayedToday: loadPrayed(),
  togglePrayed: (prayer) => set((state) => {
    const next = new Set(state.prayedToday);
    if (next.has(prayer)) next.delete(prayer); else next.add(prayer);
    savePrayed(next);
    return { prayedToday: next };
  }),
  togglePrayedPair: (p1, p2) => set((state) => {
    const next = new Set(state.prayedToday);
    const anyPrayed = next.has(p1) || next.has(p2);
    if (anyPrayed) { next.delete(p1); next.delete(p2); }
    else { next.add(p1); next.add(p2); }
    savePrayed(next);
    return { prayedToday: next };
  }),

  confirmedSpots: loadConfirmed(),
  addConfirmedSpot: (spotId) => set((state) => {
    const next = new Set(state.confirmedSpots);
    next.add(spotId);
    saveConfirmed(next);
    return { confirmedSpots: next };
  }),

  mapCollapsed: false,
  setMapCollapsed: (mapCollapsed) => set({ mapCollapsed }),
  bottomSheetHeight: 'peek',
  setBottomSheetHeight: (bottomSheetHeight) => set({ bottomSheetHeight }),
  tripPlannerOpen: false,
  setTripPlannerOpen: (tripPlannerOpen) => set({ tripPlannerOpen }),
  selectedItineraryIndex: null,
  setSelectedItineraryIndex: (selectedItineraryIndex) => set({ selectedItineraryIndex }),
  selectedMosqueId: null,
  setSelectedMosqueId: (selectedMosqueId) => set({ selectedMosqueId }),
  mapFocusCoords: null,
  setMapFocusCoords: (mapFocusCoords) => set({ mapFocusCoords }),
  bottomSheet: null,
  openSheet: (bottomSheet) => set({ bottomSheet }),
  closeSheet: () => set({ bottomSheet: null }),
  navShareOpen: false,
  setNavShareOpen: (navShareOpen) => set({ navShareOpen }),
  singleMosqueNav: null,
  setSingleMosqueNav: (singleMosqueNav) => set({ singleMosqueNav }),
}));
