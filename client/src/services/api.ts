import axios from 'axios';
import {
  NearbyResponse, SpotNearbyResponse,
  SpotSubmitRequest, SpotVerifyRequest,
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
    lat: number, lng: number, radiusKm: number
  ): Promise<NearbyResponse> => {
    const res = await api.post('/api/mosques/nearby', {
      latitude: lat,
      longitude: lng,
      radius_km: radiusKm,
      client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      client_current_time: new Date().toISOString(),
    });
    return res.data;
  },

  findNearbySpots: async (
    lat: number, lng: number, radiusKm: number
  ): Promise<SpotNearbyResponse> => {
    const res = await api.post('/api/spots/nearby', {
      latitude: lat,
      longitude: lng,
      radius_km: radiusKm,
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

  healthCheck: async () => {
    const res = await api.get('/health');
    return res.data;
  },
};

export default api;
