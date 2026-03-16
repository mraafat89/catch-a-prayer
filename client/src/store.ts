import { create } from 'zustand';
import { Mosque, PrayerSpot, LatLng, TravelDestination, TravelPlan } from './types';

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
  travelPlan: TravelPlan | null;
  setTravelPlan: (p: TravelPlan | null) => void;
  travelPlanLoading: boolean;
  setTravelPlanLoading: (v: boolean) => void;

  // Prayed tracker — set<"YYYY-MM-DD:prayer"> persisted in localStorage
  prayedToday: Set<string>;
  togglePrayed: (prayer: string) => void;

  // UI
  mapCollapsed: boolean;
  setMapCollapsed: (v: boolean) => void;
  selectedMosqueId: string | null;
  setSelectedMosqueId: (id: string | null) => void;
  // Focus arbitrary coords on the map (e.g., route stop mosque not in nearby list)
  mapFocusCoords: { lat: number; lng: number } | null;
  setMapFocusCoords: (c: { lat: number; lng: number } | null) => void;
  bottomSheet: BottomSheet;
  openSheet: (sheet: BottomSheet) => void;
  closeSheet: () => void;
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
  travelPlan: null,
  setTravelPlan: (travelPlan) => set({ travelPlan }),
  travelPlanLoading: false,
  setTravelPlanLoading: (travelPlanLoading) => set({ travelPlanLoading }),

  prayedToday: loadPrayed(),
  togglePrayed: (prayer) => set((state) => {
    const next = new Set(state.prayedToday);
    if (next.has(prayer)) next.delete(prayer); else next.add(prayer);
    savePrayed(next);
    return { prayedToday: next };
  }),

  mapCollapsed: false,
  setMapCollapsed: (mapCollapsed) => set({ mapCollapsed }),
  selectedMosqueId: null,
  setSelectedMosqueId: (selectedMosqueId) => set({ selectedMosqueId }),
  mapFocusCoords: null,
  setMapFocusCoords: (mapFocusCoords) => set({ mapFocusCoords }),
  bottomSheet: null,
  openSheet: (bottomSheet) => set({ bottomSheet }),
  closeSheet: () => set({ bottomSheet: null }),
}));
