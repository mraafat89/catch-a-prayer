import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    headless: true,
    viewport: { width: 390, height: 844 }, // iPhone 14 size
    geolocation: { latitude: 40.7128, longitude: -74.006 }, // NYC
    permissions: ['geolocation'],
    locale: 'en-US',
    timezoneId: 'America/New_York',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
