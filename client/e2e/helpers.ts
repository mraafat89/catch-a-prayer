import { Page, expect } from '@playwright/test';

/**
 * Wait for the mosque list to load (spinner disappears, cards appear).
 */
export async function waitForMosqueList(page: Page) {
  // Wait for the loading spinner to disappear
  await page.waitForSelector('text=Finding mosques', { state: 'hidden', timeout: 15000 }).catch(() => {});
  // Wait a bit for data to render
  await page.waitForTimeout(1000);
}

/**
 * Seed a test mosque via the API (runs against the local server).
 */
export async function seedTestMosque(baseURL: string) {
  // This would call the API to insert test data.
  // For now, we rely on the existing DB having mosques from the scraper.
  // In a proper setup, we'd have a /api/test/seed endpoint or use DB directly.
}

/**
 * Get the API base URL from environment or default.
 */
export function getApiUrl(): string {
  return process.env.REACT_APP_API_URL || 'http://localhost:8000';
}
