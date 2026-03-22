/**
 * Unit tests for API service layer — verify correct payloads are sent.
 * Mocks axios to avoid network calls.
 */

import axios from 'axios';
import { apiService } from '../../services/api';

jest.mock('axios', () => {
  const mockInstance = {
    post: jest.fn().mockResolvedValue({ data: {} }),
    get: jest.fn().mockResolvedValue({ data: {} }),
  };
  return {
    create: jest.fn(() => mockInstance),
    get: jest.fn().mockResolvedValue({ data: [] }),
    __mockInstance: mockInstance,
  };
});

const mockApi = (axios as any).__mockInstance;

beforeEach(() => {
  jest.clearAllMocks();
});

describe('axios instance config', () => {
  test('x-session-id header is set on axios instance', () => {
    // Re-import to capture the create() call after mock is in place
    jest.isolateModules(() => {
      const axiosMod = require('axios');
      require('../../services/api');
      const calls = axiosMod.create.mock.calls;
      expect(calls.length).toBeGreaterThan(0);
      const config = calls[calls.length - 1][0];
      expect(config.headers['x-session-id']).toBeTruthy();
      expect(config.headers['x-session-id']).toMatch(/^cap-/);
    });
  });
});

describe('findNearbyMosques', () => {
  test('sends correct payload', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { mosques: [], user_location: {}, request_time: '' } });
    await apiService.findNearbyMosques(40.71, -74.00, 10, false);
    expect(mockApi.post).toHaveBeenCalledWith('/api/mosques/nearby', expect.objectContaining({
      latitude: 40.71,
      longitude: -74.00,
      radius_km: 10,
      travel_mode: false,
    }));
  });

  test('includes client_timezone', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { mosques: [], user_location: {}, request_time: '' } });
    await apiService.findNearbyMosques(40.71, -74.00, 10);
    const payload = mockApi.post.mock.calls[0][1];
    expect(payload.client_timezone).toBeTruthy();
  });

  test('includes client_current_time as ISO string', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { mosques: [], user_location: {}, request_time: '' } });
    await apiService.findNearbyMosques(40.71, -74.00, 10);
    const payload = mockApi.post.mock.calls[0][1];
    expect(payload.client_current_time).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});

describe('findNearbySpots', () => {
  test('sends correct payload with session_id', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { spots: [], user_location: {} } });
    await apiService.findNearbySpots(40.71, -74.00, 5, 'test-session');
    expect(mockApi.post).toHaveBeenCalledWith('/api/spots/nearby', expect.objectContaining({
      latitude: 40.71,
      longitude: -74.00,
      radius_km: 5,
      session_id: 'test-session',
    }));
  });
});

describe('submitSpot', () => {
  test('posts to correct endpoint', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { spot_id: '123', status: 'pending', message: 'ok' } });
    await apiService.submitSpot({
      name: 'Test',
      spot_type: 'prayer_room',
      latitude: 40.71,
      longitude: -74.00,
      session_id: 'sess-123',
    });
    expect(mockApi.post).toHaveBeenCalledWith('/api/spots', expect.objectContaining({
      name: 'Test',
      spot_type: 'prayer_room',
    }));
  });
});

describe('getMosqueSuggestions', () => {
  test('calls correct endpoint', async () => {
    mockApi.get.mockResolvedValueOnce({ data: { suggestions: [] } });
    await apiService.getMosqueSuggestions('mosque-123');
    expect(mockApi.get).toHaveBeenCalledWith('/api/mosques/mosque-123/suggestions');
  });
});

describe('submitMosqueSuggestion', () => {
  test('sends correct payload', async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await apiService.submitMosqueSuggestion('mosque-123', 'dhuhr_iqama', '13:15', 'sess-123');
    expect(mockApi.post).toHaveBeenCalledWith('/api/mosques/mosque-123/suggestions', expect.objectContaining({
      mosque_id: 'mosque-123',
      field_name: 'dhuhr_iqama',
      suggested_value: '13:15',
      session_id: 'sess-123',
    }));
  });
});

describe('voteMosqueSuggestion', () => {
  test('sends correct payload', async () => {
    mockApi.post.mockResolvedValueOnce({ data: {} });
    await apiService.voteMosqueSuggestion('sugg-123', 'sess-456', true);
    expect(mockApi.post).toHaveBeenCalledWith('/api/suggestions/sugg-123/vote', expect.objectContaining({
      session_id: 'sess-456',
      is_positive: true,
    }));
  });
});
