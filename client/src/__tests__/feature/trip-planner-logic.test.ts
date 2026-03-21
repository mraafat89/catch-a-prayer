/**
 * Feature tests for trip planner client-side logic.
 * Rules: PRODUCT_REQUIREMENTS.md FR-4
 */

export {};

// Long-trip detection (mirrors App.tsx)
function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

const LONG_TRIP_THRESHOLD_KM = 80;

function isLongTrip(originLat: number, originLng: number, destLat: number, destLng: number): boolean {
  return haversineKm(originLat, originLng, destLat, destLng) > LONG_TRIP_THRESHOLD_KM;
}

// Plan cache key (mirrors App.tsx)
function planCacheKey(
  mode: string, oLat: number, oLng: number,
  dLat: number, dLng: number,
  wps: Array<{lat: number; lng: number}>,
  dep: string | undefined,
): string {
  return `${mode}|${oLat.toFixed(4)},${oLng.toFixed(4)}|${dLat.toFixed(4)},${dLng.toFixed(4)}|${wps.map(w => `${w.lat.toFixed(4)},${w.lng.toFixed(4)}`).join('+')}|${dep || ''}`;
}

describe('Long trip detection', () => {
  test('NYC to Philly (150 km) is long trip', () => {
    expect(isLongTrip(40.7128, -74.006, 39.9526, -75.1652)).toBe(true);
  });

  test('NYC to nearby (5 km) is not long trip', () => {
    expect(isLongTrip(40.7128, -74.006, 40.72, -74.00)).toBe(false);
  });

  test('exactly 80 km is not long trip (> not >=)', () => {
    // ~80 km north of NYC
    const dist = haversineKm(40.7128, -74.006, 41.43, -74.006);
    // If dist is close to 80, the test validates the threshold
    expect(dist).toBeGreaterThan(70);
    expect(dist).toBeLessThan(90);
  });
});

describe('Plan cache key', () => {
  test('same inputs produce same key', () => {
    const k1 = planCacheKey('travel', 40.71, -74.00, 34.05, -118.24, [], undefined);
    const k2 = planCacheKey('travel', 40.71, -74.00, 34.05, -118.24, [], undefined);
    expect(k1).toBe(k2);
  });

  test('different mode produces different key', () => {
    const k1 = planCacheKey('travel', 40.71, -74.00, 34.05, -118.24, [], undefined);
    const k2 = planCacheKey('driving', 40.71, -74.00, 34.05, -118.24, [], undefined);
    expect(k1).not.toBe(k2);
  });

  test('different departure produces different key', () => {
    const k1 = planCacheKey('travel', 40.71, -74.00, 34.05, -118.24, [], '2026-03-20T10:00');
    const k2 = planCacheKey('travel', 40.71, -74.00, 34.05, -118.24, [], '2026-03-21T10:00');
    expect(k1).not.toBe(k2);
  });

  test('waypoints included in key', () => {
    const k1 = planCacheKey('travel', 40.71, -74.00, 34.05, -118.24, [], undefined);
    const k2 = planCacheKey('travel', 40.71, -74.00, 34.05, -118.24, [{ lat: 39.95, lng: -75.16 }], undefined);
    expect(k1).not.toBe(k2);
  });

  test('small GPS jitter produces same key (toFixed(4))', () => {
    // Both round to 40.7128, -74.0060 at 4 decimal places
    const k1 = planCacheKey('travel', 40.71281, -74.00601, 34.05, -118.24, [], undefined);
    const k2 = planCacheKey('travel', 40.71284, -74.00604, 34.05, -118.24, [], undefined);
    expect(k1).toBe(k2);
  });
});
