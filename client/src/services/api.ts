import axios from 'axios';
import {
  NearbyResponse, SpotNearbyResponse,
  SpotSubmitRequest, SpotVerifyRequest,
  GeocodeSuggestion, TravelPlan,
  MosqueSuggestionsResponse,
} from '../types';

const API_BASE_URL = process.env.REACT_APP_API_URL || '';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
  },
});

export const apiService = {
  findNearbyMosques: async (
    lat: number, lng: number, radiusKm: number, travelMode = false
  ): Promise<NearbyResponse> => {
    const res = await api.post('/api/mosques/nearby', {
      latitude: lat,
      longitude: lng,
      radius_km: radiusKm,
      client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      client_current_time: new Date().toISOString(),
      travel_mode: travelMode,
    });
    return res.data;
  },

  findNearbySpots: async (
    lat: number, lng: number, radiusKm: number, sessionId?: string
  ): Promise<SpotNearbyResponse> => {
    const res = await api.post('/api/spots/nearby', {
      latitude: lat,
      longitude: lng,
      radius_km: radiusKm,
      session_id: sessionId,
    });
    return res.data;
  },

  submitSpot: async (req: SpotSubmitRequest) => {
    const res = await api.post('/api/spots', req);
    return res.data;
  },

  verifySpot: async (spotId: string, req: SpotVerifyRequest) => {
    const res = await api.post(`/api/spots/${spotId}/verify`, req);
    return res.data;
  },

  geocodeDestination: async (query: string, userLat?: number, userLng?: number): Promise<GeocodeSuggestion[]> => {
    // Try backend proxy first (uses Mapbox if configured, Photon otherwise)
    try {
      const res = await api.get('/api/geocode', { params: { q: query } });
      if (res.data.suggestions?.length > 0) return res.data.suggestions;
    } catch {}

    // Fall back to Nominatim — free, CORS-enabled, supports countrycodes filter
    const res = await axios.get('https://nominatim.openstreetmap.org/search', {
      params: { q: query, countrycodes: 'us,ca', format: 'jsonv2', limit: 5 },
      headers: { 'User-Agent': 'CatchAPrayer/1.0' },
      timeout: 10000,
    });
    return (res.data || []).map((r: any) => {
      // Trim "United States" / "Canada" suffix from display_name for brevity
      const name = r.display_name.replace(/, United States$/, '').replace(/, Canada$/, '');
      return { place_name: name, lat: parseFloat(r.lat), lng: parseFloat(r.lon) };
    });
  },

  reverseGeocode: async (lat: number, lng: number): Promise<string> => {
    const res = await api.get('/api/geocode/reverse', { params: { lat, lng } });
    return res.data.label || '';
  },

  getTravelPlan: async (
    originLat: number, originLng: number,
    destLat: number, destLng: number,
    destName: string,
    originName?: string,
    departureTime?: string,
    tripMode?: string,
    waypoints?: Array<{ lat: number; lng: number; name?: string }>,
    prayedPrayers?: string[],
  ): Promise<TravelPlan> => {
    const res = await api.post('/api/travel/plan', {
      origin_lat: originLat,
      origin_lng: originLng,
      origin_name: originName || null,
      destination_lat: destLat,
      destination_lng: destLng,
      destination_name: destName,
      departure_time: departureTime || null,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      trip_mode: tripMode || 'travel',
      waypoints: waypoints || [],
      prayed_prayers: prayedPrayers || [],
    });
    return res.data;
  },

  // Mosque suggestions (community corrections)
  getMosqueSuggestions: async (mosqueId: string): Promise<MosqueSuggestionsResponse> => {
    const res = await api.get(`/api/mosques/${mosqueId}/suggestions`);
    return res.data;
  },

  submitMosqueSuggestion: async (mosqueId: string, fieldName: string, suggestedValue: string, sessionId: string) => {
    const res = await api.post(`/api/mosques/${mosqueId}/suggestions`, {
      mosque_id: mosqueId,
      field_name: fieldName,
      suggested_value: suggestedValue,
      session_id: sessionId,
    });
    return res.data;
  },

  voteMosqueSuggestion: async (suggestionId: string, sessionId: string, isPositive: boolean) => {
    const res = await api.post(`/api/suggestions/${suggestionId}/vote`, {
      session_id: sessionId,
      is_positive: isPositive,
    });
    return res.data;
  },

  healthCheck: async () => {
    const res = await api.get('/health');
    return res.data;
  },
};

export default api;
