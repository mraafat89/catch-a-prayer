export enum PrayerName {
  FAJR = "fajr",
  DHUHR = "dhuhr", 
  ASR = "asr",
  MAGHRIB = "maghrib",
  ISHA = "isha",
  JUMAA = "jumaa"
}

export interface Location {
  latitude: number;
  longitude: number;
  address?: string;
}

export interface Prayer {
  prayer_name: PrayerName;
  adhan_time: string;
  iqama_time?: string;
}

export interface TravelInfo {
  distance_meters: number;
  duration_seconds: number;
  duration_text: string;
}

export interface NextPrayer {
  prayer: PrayerName;
  can_catch: boolean;
  travel_time_minutes: number;
  time_remaining_minutes: number;
  arrival_time: string;
}

export interface Mosque {
  place_id: string;
  name: string;
  location: Location;
  phone_number?: string;
  website?: string;
  rating?: number;
  user_ratings_total?: number;
  travel_info?: TravelInfo;
  next_prayer?: NextPrayer;
  prayers: Prayer[];
}

export interface LocationRequest {
  latitude: number;
  longitude: number;
  radius_km?: number;
}

export interface MosqueResponse {
  mosques: Mosque[];
  user_location: Location;
}

export interface UserSettings {
  max_search_radius: number;
  distance_unit: string;
  prayer_buffer_minutes: number;
  show_iqama_times: boolean;
  show_adhan_times: boolean;
}