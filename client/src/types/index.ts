// v2 API types — aligned with the FastAPI backend schemas

export interface LatLng {
  latitude: number;
  longitude: number;
}

export interface PrayerTime {
  prayer: string;
  adhan_time: string | null;
  iqama_time: string | null;
  adhan_source: string | null;
  iqama_source: string | null;
  adhan_confidence: string | null;
  iqama_confidence: string | null;
  data_freshness: string | null;
}

export interface NextCatchable {
  prayer: string;
  status: string;
  status_label: string;
  message: string;
  urgency: 'high' | 'normal' | 'low';
  iqama_time: string | null;
  adhan_time: string | null;
  arrival_time: string | null;
  minutes_until_iqama: number | null;
  leave_by: string | null;
  period_ends_at: string | null;
}

export interface MosqueLocation {
  latitude: number;
  longitude: number;
  address: string | null;
  city?: string | null;
  state?: string | null;
}

export interface Mosque {
  id: string;
  name: string;
  location: MosqueLocation;
  timezone: string | null;
  distance_meters: number;
  travel_time_minutes: number | null;
  travel_time_source: string;
  phone: string | null;
  website: string | null;
  has_womens_section: boolean | null;
  wheelchair_accessible: boolean | null;
  denomination: string | null;
  next_catchable: NextCatchable | null;
  catchable_prayers: NextCatchable[];
  travel_combinations: TravelPairPlan[];
  prayers: PrayerTime[];
  sunrise: string | null;
  jumuah_sessions: JumuahSession[];
}

export interface JumuahSession {
  session_number: number;
  khutba_start: string | null;
  prayer_start: string | null;
  imam_name: string | null;
  language: string | null;
  special_notes: string | null;
  booking_required: boolean;
  booking_url: string | null;
}

export interface NearbyResponse {
  mosques: Mosque[];
  user_location: LatLng;
  request_time: string;
}

// Prayer spot types
export interface SpotLocation {
  latitude: number;
  longitude: number;
  address: string | null;
  city?: string | null;
  state?: string | null;
}

export interface PrayerSpot {
  id: string;
  name: string;
  spot_type: string;
  location: SpotLocation;
  distance_meters: number;
  has_wudu_facilities: boolean | null;
  gender_access: string | null;
  is_indoor: boolean | null;
  operating_hours: string | null;
  notes: string | null;
  website: string | null;
  status: 'pending' | 'active' | 'rejected';
  verification_count: number;
  rejection_count: number;
  verification_label: string;
  last_verified_at: string | null;
}

export interface SpotNearbyResponse {
  spots: PrayerSpot[];
  user_location: LatLng;
}

export interface SpotSubmitRequest {
  name: string;
  spot_type: string;
  latitude: number;
  longitude: number;
  address?: string;
  city?: string;
  state?: string;
  has_wudu_facilities?: boolean | null;
  gender_access?: string;
  is_indoor?: boolean | null;
  operating_hours?: string;
  notes?: string;
  website?: string;
  session_id: string;
}

export interface SpotVerifyRequest {
  session_id: string;
  is_positive: boolean;
  attributes: Record<string, unknown>;
}

// Status → display mapping
export const STATUS_CONFIG: Record<string, { dot: string; icon: string; bg: string; text: string; border: string }> = {
  can_catch_with_imam:             { dot: '🟢', icon: '/icons/icon_pray_imam.png',   bg: 'bg-green-50',  text: 'text-green-800',  border: 'border-green-200' },
  can_catch_with_imam_in_progress: { dot: '🟡', icon: '/icons/icon_pray_imam.png',   bg: 'bg-yellow-50', text: 'text-yellow-800', border: 'border-yellow-200' },
  can_pray_solo_at_mosque:         { dot: '🔵', icon: '/icons/icon_pray_solo.png',   bg: 'bg-blue-50',   text: 'text-blue-800',   border: 'border-blue-200' },
  pray_at_nearby_location:         { dot: '🟠', icon: '/icons/icon_pray_nearby.png', bg: 'bg-orange-50', text: 'text-orange-800', border: 'border-orange-200' },
  missed_make_up:                  { dot: '⚪', icon: '/icons/icon_mosque_nav.png',   bg: 'bg-gray-50',   text: 'text-gray-600',   border: 'border-gray-200' },
  upcoming:                        { dot: '⚪', icon: '/icons/icon_mosque_nav.png',   bg: 'bg-gray-50',   text: 'text-gray-600',   border: 'border-gray-200' },
};

export const SPOT_TYPE_LABELS: Record<string, string> = {
  prayer_room:      'Prayer room',
  community_hall:   'Community hall',
  halal_restaurant: 'Halal restaurant',
  campus:           'Campus prayer room',
  rest_area:        'Rest area',
  library:          'Library',
  other:            'Other',
};

// Travel Plan types
export interface GeocodeSuggestion {
  place_name: string;
  lat: number;
  lng: number;
}

export interface TravelStop {
  mosque_id: string;
  mosque_name: string;
  mosque_lat: number;
  mosque_lng: number;
  mosque_address: string | null;
  prayer: string;
  estimated_arrival_time: string;
  minutes_into_trip: number;
  detour_minutes: number;
  status: string;
  iqama_time: string | null;
  adhan_time: string | null;
}

export interface TravelOption {
  option_type: string;
  label: string;
  description: string;
  prayers: string[];
  combination_label: string | null;
  stops: TravelStop[];
  feasible: boolean;
  note: string | null;
}

export interface TravelPairPlan {
  pair: string;
  label: string;
  emoji: string;
  options: TravelOption[];
}

export interface TravelRouteInfo {
  distance_meters: number;
  duration_minutes: number;
  origin_name: string | null;
  destination_name: string;
}

export interface PairChoice {
  pair: string;
  label: string;
  emoji: string;
  option: TravelOption;
}

export interface TripItinerary {
  label: string;
  summary: string;
  pair_choices: PairChoice[];
  total_detour_minutes: number;
  stop_count: number;
  feasible: boolean;
}

export interface TravelPlan {
  route: TravelRouteInfo;
  prayer_pairs: TravelPairPlan[];
  itineraries: TripItinerary[];
  departure_time: string;
  estimated_arrival_time: string;
}

export interface TravelDestination {
  place_name: string;
  lat: number;
  lng: number;
}
