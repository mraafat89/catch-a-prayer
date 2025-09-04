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

export enum PrayerStatus {
  CAN_CATCH_WITH_IMAM = "can_catch_with_imam",
  CAN_CATCH_AFTER_IMAM = "can_catch_after_imam",
  CAN_CATCH_DELAYED = "can_catch_delayed",
  CANNOT_CATCH = "cannot_catch",
  MISSED = "missed"
}

export interface NextPrayer {
  prayer: PrayerName;
  status: PrayerStatus;
  can_catch: boolean;
  travel_time_minutes: number;
  time_remaining_minutes: number;
  arrival_time: string;
  prayer_time: string;
  message: string;
  is_delayed?: boolean;
  time_until_next_prayer?: number;
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
  client_timezone?: string;
  client_current_time?: string;
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