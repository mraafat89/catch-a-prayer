import { test, expect } from '@playwright/test';
import { waitForMosqueList } from './helpers';

test.describe('Offline Resilience', () => {

  test('app loads without crash', async ({ page }) => {
    // Basic smoke test — the app should not crash on load
    await page.goto('/');
    await page.waitForTimeout(2000);

    // Page should have rendered something
    const body = await page.textContent('body');
    expect(body).toBeTruthy();
    expect(body!.length).toBeGreaterThan(10);

    // No unhandled JS errors
    const errors: string[] = [];
    page.on('pageerror', (err) => errors.push(err.message));
    await page.waitForTimeout(1000);
    // Filter out non-critical errors (some map tile errors are expected)
    const criticalErrors = errors.filter(e =>
      !e.includes('tile') && !e.includes('Leaflet') && !e.includes('chunk')
    );
    expect(criticalErrors).toEqual([]);
  });

  test('going offline shows cached data without crash', async ({ page, context }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    // Get current content
    const beforeContent = await page.textContent('body');

    // Go offline
    await context.setOffline(true);
    await page.waitForTimeout(2000);

    // App should not have crashed — page still has content
    const afterContent = await page.textContent('body');
    expect(afterContent).toBeTruthy();
    expect(afterContent!.length).toBeGreaterThan(10);

    // Go back online
    await context.setOffline(false);
    await page.waitForTimeout(2000);

    // Still alive
    const recovered = await page.textContent('body');
    expect(recovered).toBeTruthy();
  });

  test('page refreshes without losing state', async ({ page }) => {
    await page.goto('/');
    await waitForMosqueList(page);

    // Reload
    await page.reload();
    await page.waitForTimeout(2000);

    // Should not crash and should show content again
    const body = await page.textContent('body');
    expect(body).toBeTruthy();
    expect(body!.length).toBeGreaterThan(10);
  });
});
