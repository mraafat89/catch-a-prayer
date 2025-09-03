import axios from 'axios';
import { LocationRequest, MosqueResponse, UserSettings } from '../types';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const apiService = {
  // Find nearby mosques
  findNearbyMosques: async (request: LocationRequest): Promise<MosqueResponse> => {
    const response = await api.post('/api/mosques/nearby', request);
    return response.data;
  },

  // Get user settings
  getUserSettings: async (): Promise<UserSettings> => {
    const response = await api.get('/api/settings');
    return response.data;
  },

  // Update user settings
  updateUserSettings: async (settings: UserSettings): Promise<UserSettings> => {
    const response = await api.put('/api/settings', settings);
    return response.data;
  },

  // Health check
  healthCheck: async (): Promise<any> => {
    const response = await api.get('/health');
    return response.data;
  }
};

export default api;