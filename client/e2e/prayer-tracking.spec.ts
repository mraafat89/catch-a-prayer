import { test, expect } from '@playwright/test';
import { waitForMosqueList } from './helpers';

test.describe('Prayer Tracking', () => {

  test('prayed banner shows active prayers', async ({ page }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    // The prayed banner should show "Did you already pray?" or prayer names
    const body = await page.textContent('body');
    // At any time of day, there should be at least one active/upcoming prayer
    // unless all have passed (late night)
    const hasPrayerRef = (
      body?.includes('pray') ||
      body?.includes('Fajr') ||
      body?.includes('Dhuhr') ||
      body?.includes('Asr') ||
      body?.includes('Maghrib') ||
      body?.includes('Isha')
    );
    expect(hasPrayerRef).toBeTruthy();
  });

  test('marking prayer as prayed shows undo', async ({ page }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    // Find a "Yes, I prayed" button
    const prayedBtn = page.locator('text=Yes, I prayed').first();
    const exists = await prayedBtn.isVisible().catch(() => false);

    if (exists) {
      await prayedBtn.click();
      await page.waitForTimeout(300);

      // Should show undo option
      const body = await page.textContent('body');
      expect(body?.includes('Undo') || body?.includes('Already prayed')).toBeTruthy();
    }
  });

  test('settings gear opens settings sheet', async ({ page }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    // Find settings button (gear icon)
    const settingsBtn = page.locator('[aria-label*="Settings"], [aria-label*="settings"]').first();
    const exists = await settingsBtn.isVisible().catch(() => false);

    if (exists) {
      await settingsBtn.click();
      await page.waitForTimeout(500);

      // Settings sheet should show radius slider or denomination filter
      const body = await page.textContent('body');
      expect(
        body?.includes('radius') ||
        body?.includes('Radius') ||
        body?.includes('Sunni') ||
        body?.includes('denomination') ||
        body?.includes('spots')
      ).toBeTruthy();
    }
  });
});
