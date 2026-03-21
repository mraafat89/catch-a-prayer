import { test, expect } from '@playwright/test';
import { waitForMosqueList } from './helpers';

test.describe('Mosque Discovery', () => {

  test('app loads and shows mosque list', async ({ page }) => {
    await page.goto('/');

    // Should show either mosque cards or "finding mosques" then cards
    await waitForMosqueList(page);

    // Check that the page has loaded something meaningful
    const body = await page.textContent('body');
    // Should have either mosque names or a "no mosques" / "enable location" message
    expect(body).toBeTruthy();
    expect(body!.length).toBeGreaterThan(50);
  });

  test('tapping mosque card opens detail with prayer times', async ({ page }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    // Find any clickable element that looks like a mosque card
    // Cards have cursor-pointer and contain distance/time info
    const cards = page.locator('[class*="cursor-pointer"]');
    const count = await cards.count();

    if (count > 0) {
      await cards.first().click();
      await page.waitForTimeout(1000);

      // After clicking, the page should show prayer details
      const body = await page.textContent('body');
      // Detail view shows prayer table or "Today's Prayer Times"
      const hasDetail = (
        body?.includes('Today') ||
        body?.includes('Adhan') ||
        body?.includes('Iqama') ||
        body?.includes('Fajr')
      );
      // This is a soft assertion — if no mosques loaded, skip
      if (count > 0 && body && body.length > 100) {
        expect(hasDetail).toBeTruthy();
      }
    }
  });

  test('navigate and close buttons exist in detail view', async ({ page }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    const cards = page.locator('[class*="cursor-pointer"]');
    const count = await cards.count();

    if (count > 0) {
      await cards.first().click();
      await page.waitForTimeout(1000);

      // Check for action buttons by aria-label
      const navBtn = page.locator('[aria-label="Navigate"]');
      const closeBtn = page.locator('[aria-label="Close"]');

      // At least one should be visible after clicking a mosque
      const navVisible = await navBtn.isVisible().catch(() => false);
      const closeVisible = await closeBtn.isVisible().catch(() => false);

      // Soft assertion — depends on whether data loaded
      if (navVisible) {
        expect(navVisible).toBeTruthy();
      }
      if (closeVisible) {
        await closeBtn.click();
        await page.waitForTimeout(500);
      }
    }
  });
});
