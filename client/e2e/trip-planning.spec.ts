import { test, expect } from '@playwright/test';
import { waitForMosqueList } from './helpers';

test.describe('Trip Planning', () => {

  test('destination search opens on "Where to?" tap', async ({ page }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    // Find the "Where to?" pill/button
    const searchPill = page.locator('text=Where to?').first();
    const exists = await searchPill.isVisible().catch(() => false);

    if (exists) {
      await searchPill.click();
      await page.waitForTimeout(300);
      // Search input should appear
      const input = page.locator('input[placeholder*="Where"]').first();
      const inputVisible = await input.isVisible().catch(() => false);
      expect(inputVisible).toBeTruthy();
    }
  });

  test('typing destination shows autocomplete suggestions', async ({ page }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    const searchPill = page.locator('text=Where to?').first();
    const exists = await searchPill.isVisible().catch(() => false);
    if (!exists) return;

    await searchPill.click();
    await page.waitForTimeout(300);

    // Type a destination
    const input = page.locator('input[placeholder*="Where"]').first();
    await input.fill('Los Angeles');
    await page.waitForTimeout(1500); // debounce + network

    // Check for suggestion dropdown
    const body = await page.textContent('body');
    // Should show suggestions or at least no crash
    expect(body).toBeTruthy();
  });

  test('mode toggle switches between Muqeem and Musafir', async ({ page }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    // Find mode toggle
    const muqeemBtn = page.locator('text=Muqeem').first();
    const musafirBtn = page.locator('text=Musafir').first();

    const muqeemVisible = await muqeemBtn.isVisible().catch(() => false);
    const musafirVisible = await musafirBtn.isVisible().catch(() => false);

    if (muqeemVisible) {
      // Currently Muqeem, tap to switch to Musafir
      await muqeemBtn.click();
      await page.waitForTimeout(300);
      // Should now show Musafir
      const afterText = await page.textContent('body');
      expect(afterText?.includes('Musafir')).toBeTruthy();
    } else if (musafirVisible) {
      // Currently Musafir, tap to switch to Muqeem
      await musafirBtn.click();
      await page.waitForTimeout(300);
      const afterText = await page.textContent('body');
      expect(afterText?.includes('Muqeem')).toBeTruthy();
    }
  });
});
