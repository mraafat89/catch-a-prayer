/**
 * Advanced tests for the entire waypoint → plan → route display pipeline.
 * Tests cover: state management, plan caching, stale closures, route geometry keying,
 * and the exact user scenario that triggers the bug.
 */

// ─── Types (mirror the app) ─────────────────────────────────────────────────

interface WaypointRow {
  id: number;
  dest: { lat: number; lng: number; place_name: string } | null;
  query: string;
  sugg: any[];
  loading: boolean;
}

interface TravelPlan {
  route: { route_geometry: [number, number][] };
  itineraries: Array<{ route_geometry: [number, number][] }>;
  departure_time: string;
}

// ─── Helpers (mirror the app logic) ─────────────────────────────────────────

let _wpIdCounter = 0;

function makeRow(name: string, lat: number, lng: number): WaypointRow {
  return { id: ++_wpIdCounter, dest: { lat, lng, place_name: name }, query: name, sugg: [], loading: false };
}

function moveWaypoint(rows: WaypointRow[], index: number, direction: -1 | 1): WaypointRow[] {
  const newIndex = index + direction;
  if (newIndex < 0 || newIndex >= rows.length) return rows;
  const next = [...rows];
  [next[index], next[newIndex]] = [next[newIndex], next[index]];
  return next;
}

function buildWps(rows: WaypointRow[]): Array<{ lat: number; lng: number; name: string }> {
  return rows
    .filter(w => w.dest !== null)
    .map(w => ({ lat: w.dest!.lat, lng: w.dest!.lng, name: w.dest!.place_name }));
}

function planCacheKey(
  mode: string, oLat: number, oLng: number, dLat: number, dLng: number,
  wps: Array<{ lat: number; lng: number }>, dep: string | undefined
): string {
  return `${mode}|${oLat.toFixed(4)},${oLng.toFixed(4)}|${dLat.toFixed(4)},${dLng.toFixed(4)}|${wps.map(w => `${w.lat.toFixed(4)},${w.lng.toFixed(4)}`).join('+')}|${dep || ''}`;
}

function polylineKey(selectedItineraryIndex: number | null, plan: TravelPlan | null, routeGeometry: [number, number][] | null): string {
  if (!routeGeometry || routeGeometry.length < 2) return 'none';
  // Include a hash of all coordinates so reordered waypoints produce different keys
  const geoHash = routeGeometry.map(p => `${p[0].toFixed(4)},${p[1].toFixed(4)}`).join('|');
  return `route-${selectedItineraryIndex}-${plan?.departure_time ?? ''}-${geoHash}`;
}

// Simulate what routeGeometry would be for a given waypoint order
// In reality this comes from the API, but we simulate it by encoding waypoint coords into the geometry
function fakeRouteGeometry(originLat: number, originLng: number, wps: Array<{ lat: number; lng: number }>, destLat: number, destLng: number): [number, number][] {
  const points: [number, number][] = [[originLat, originLng]];
  for (const wp of wps) points.push([wp.lat, wp.lng]);
  points.push([destLat, destLng]);
  return points;
}

function fakePlan(wps: Array<{ lat: number; lng: number }>, originLat: number, originLng: number, destLat: number, destLng: number, depTime: string): TravelPlan {
  const geom = fakeRouteGeometry(originLat, originLng, wps, destLat, destLng);
  return {
    route: { route_geometry: geom },
    itineraries: [{ route_geometry: geom }],
    departure_time: depTime,
  };
}

// ─── Test data ──────────────────────────────────────────────────────────────

const ORIGIN = { lat: 37.3688, lng: -122.0363 }; // Sunnyvale
const DEST = { lat: 34.0522, lng: -118.2437 };    // Los Angeles

beforeEach(() => {
  _wpIdCounter = 0;
});

// ─── Tests ──────────────────────────────────────────────────────────────────

describe('plan cache behavior', () => {
  const A = makeRow('San Jose', 37.3382, -121.8863);
  const B = makeRow('Fresno', 36.7378, -119.7871);

  test('different waypoint orders produce different cache keys', () => {
    const wpsAB = buildWps([A, B]);
    const wpsBA = buildWps([B, A]);

    const keyAB = planCacheKey('travel', ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, wpsAB, undefined);
    const keyBA = planCacheKey('travel', ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, wpsBA, undefined);

    expect(keyAB).not.toBe(keyBA);
  });

  test('same waypoint order produces same cache key', () => {
    const wps1 = buildWps([A, B]);
    const wps2 = buildWps([A, B]);

    const key1 = planCacheKey('travel', ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, wps1, undefined);
    const key2 = planCacheKey('travel', ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, wps2, undefined);

    expect(key1).toBe(key2);
  });

  test('cache returns correct plan for each waypoint order', () => {
    const cache = new Map<string, TravelPlan>();

    const wpsAB = buildWps([A, B]);
    const wpsBA = buildWps([B, A]);

    const planAB = fakePlan(wpsAB, ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, '2026-03-18T12:00:00');
    const planBA = fakePlan(wpsBA, ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, '2026-03-18T12:00:00');

    const keyAB = planCacheKey('travel', ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, wpsAB, undefined);
    const keyBA = planCacheKey('travel', ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, wpsBA, undefined);

    cache.set(keyAB, planAB);
    cache.set(keyBA, planBA);

    // Route geometry should differ — first waypoint in AB is A, first in BA is B
    expect(cache.get(keyAB)!.route.route_geometry[1]).toEqual([A.dest!.lat, A.dest!.lng]);
    expect(cache.get(keyBA)!.route.route_geometry[1]).toEqual([B.dest!.lat, B.dest!.lng]);
  });
});

describe('polyline key uniqueness', () => {
  const A = makeRow('San Jose', 37.3382, -121.8863);
  const B = makeRow('Fresno', 36.7378, -119.7871);

  test('different waypoint orders produce different polyline keys', () => {
    const wpsAB = buildWps([A, B]);
    const wpsBA = buildWps([B, A]);

    const planAB = fakePlan(wpsAB, ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, '2026-03-18T12:00:00');
    const planBA = fakePlan(wpsBA, ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, '2026-03-18T12:00:00');

    const keyAB = polylineKey(0, planAB, planAB.itineraries[0].route_geometry);
    const keyBA = polylineKey(0, planBA, planBA.itineraries[0].route_geometry);

    expect(keyAB).not.toBe(keyBA);
  });

  test('same departure_time with same geometry = same key (cache hit scenario)', () => {
    const wps = buildWps([A, B]);
    const plan1 = fakePlan(wps, ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, '2026-03-18T12:00:00');
    const plan2 = fakePlan(wps, ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, '2026-03-18T12:00:00');

    const key1 = polylineKey(0, plan1, plan1.itineraries[0].route_geometry);
    const key2 = polylineKey(0, plan2, plan2.itineraries[0].route_geometry);

    expect(key1).toBe(key2);
  });

  test('different middle points produce different keys (fixed bug)', () => {
    // Previously this was a bug — same length + endpoints = same key.
    // Now the key includes all coordinate hashes, so different midpoints = different keys.
    const wpsAB = buildWps([A, B]);
    const wpsBA = buildWps([B, A]);

    // Simulate real-world: OSRM returns different number of points for different routes
    // But in edge cases the count could match
    const geomAB: [number, number][] = [
      [ORIGIN.lat, ORIGIN.lng], [37.3, -121.8], [36.7, -119.7], [DEST.lat, DEST.lng]
    ];
    const geomBA: [number, number][] = [
      [ORIGIN.lat, ORIGIN.lng], [36.7, -119.7], [37.3, -121.8], [DEST.lat, DEST.lng]
    ];

    const planAB: TravelPlan = {
      route: { route_geometry: geomAB },
      itineraries: [{ route_geometry: geomAB }],
      departure_time: '2026-03-18T12:00:00',
    };
    const planBA: TravelPlan = {
      route: { route_geometry: geomBA },
      itineraries: [{ route_geometry: geomBA }],
      departure_time: '2026-03-18T12:00:00',
    };

    const keyAB = polylineKey(0, planAB, geomAB);
    const keyBA = polylineKey(0, planBA, geomBA);

    // Fixed: keys now differ because all coordinates are hashed
    expect(keyAB).not.toBe(keyBA);
  });
});

describe('React state simulation: full user scenario', () => {
  test('exact user scenario: add A, B, shuffle multiple times, plan each time', () => {
    _wpIdCounter = 0;
    const A = makeRow('San Jose', 37.3382, -121.8863);
    const B = makeRow('Fresno', 36.7378, -119.7871);

    let rows = [A, B];
    const cache = new Map<string, TravelPlan>();

    // First plan: [A, B]
    let wps = buildWps(rows);
    expect(wps.map(w => w.name)).toEqual(['San Jose', 'Fresno']);
    const plan1 = fakePlan(wps, ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, 'T1');
    const key1 = planCacheKey('travel', ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, wps, undefined);
    cache.set(key1, plan1);

    // Verify route goes through A first
    expect(plan1.route.route_geometry[1]).toEqual([A.dest!.lat, A.dest!.lng]);

    // Move A down → [B, A]
    rows = moveWaypoint(rows, 0, 1);
    expect(rows[0].dest!.place_name).toBe('Fresno');

    // Plan: [B, A]
    wps = buildWps(rows);
    expect(wps.map(w => w.name)).toEqual(['Fresno', 'San Jose']);
    const key2 = planCacheKey('travel', ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, wps, undefined);
    expect(key2).not.toBe(key1); // Different cache key
    expect(cache.has(key2)).toBe(false); // Cache miss
    const plan2 = fakePlan(wps, ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, 'T2');
    cache.set(key2, plan2);

    // Verify route goes through B first
    expect(plan2.route.route_geometry[1]).toEqual([B.dest!.lat, B.dest!.lng]);

    // Move A back up → [A, B]
    rows = moveWaypoint(rows, 1, -1);
    expect(rows[0].dest!.place_name).toBe('San Jose');

    // Plan: [A, B] again — cache HIT
    wps = buildWps(rows);
    const key3 = planCacheKey('travel', ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, wps, undefined);
    expect(key3).toBe(key1); // Same as first plan
    expect(cache.has(key3)).toBe(true); // Cache hit!
    const cachedPlan = cache.get(key3)!;

    // Verify the cached plan has the correct geometry (A first, not B)
    expect(cachedPlan.route.route_geometry[1]).toEqual([A.dest!.lat, A.dest!.lng]);
  });

  test('React batching simulation: setTravelPlan(null) then setTravelPlan(cached) in same tick', () => {
    _wpIdCounter = 0;
    const A = makeRow('San Jose', 37.3382, -121.8863);
    const B = makeRow('Fresno', 36.7378, -119.7871);

    const wps = buildWps([A, B]);
    const plan = fakePlan(wps, ORIGIN.lat, ORIGIN.lng, DEST.lat, DEST.lng, 'T1');

    // Simulate React state batching:
    // When executePlan is called, it does:
    //   setTravelPlan(null)
    //   ... cache hit ...
    //   setTravelPlan(cached)
    // React 18 batches these → only one render with travelPlan = cached
    // The Polyline NEVER unmounts (null state is skipped)

    // State before executePlan
    let travelPlan: TravelPlan | null = plan;
    let routeGeometry = plan.itineraries[0].route_geometry;
    const oldKey = polylineKey(0, travelPlan, routeGeometry);

    // Simulate: setTravelPlan(null) → setTravelPlan(cached)
    // In batched mode, final state is travelPlan = cached (same plan)
    travelPlan = plan; // same reference — cache hit returns same object
    routeGeometry = plan.itineraries[0].route_geometry;
    const newKey = polylineKey(0, travelPlan, routeGeometry);

    // Keys are the same — Polyline won't remount!
    expect(newKey).toBe(oldKey);
    // This is EXPECTED for same-order re-plan — the route hasn't changed
  });

  test('stale closure: executePlan called from useEffect captures old waypointRows', () => {
    _wpIdCounter = 0;
    const A = makeRow('San Jose', 37.3382, -121.8863);
    const B = makeRow('Fresno', 36.7378, -119.7871);

    // Render 1: rows = [A, B], executePlan captures this
    let rowsAtRender1 = [A, B];
    const executePlanClosure1 = () => buildWps(rowsAtRender1);

    // User moves waypoints → triggers re-render
    let rowsAtRender2 = moveWaypoint(rowsAtRender1, 0, 1); // [B, A]

    // If a useEffect fires with the OLD executePlan (from render 1):
    const staleWps = executePlanClosure1();
    expect(staleWps.map(w => w.name)).toEqual(['San Jose', 'Fresno']); // STALE — still [A, B]

    // The CORRECT executePlan should use render 2's rows:
    const freshWps = buildWps(rowsAtRender2);
    expect(freshWps.map(w => w.name)).toEqual(['Fresno', 'San Jose']); // CORRECT — [B, A]
  });
});

describe('id-based matching vs index-based matching', () => {
  test('index-based: selecting after swap updates WRONG row', () => {
    _wpIdCounter = 0;
    const A = makeRow('San Jose', 37.3382, -121.8863);
    const B = makeRow('Fresno', 36.7378, -119.7871);
    let rows = [A, B];

    // Capture onSelect callback for row index 0 (currently A)
    const capturedIndex = 0;
    const indexBasedSelect = (s: any) => {
      rows = rows.map((r, ri) => ri === capturedIndex ? { ...r, dest: s } : r);
    };

    // Swap: [A, B] → [B, A]
    rows = moveWaypoint(rows, 0, 1);

    // Now a stale callback fires for "index 0" — but index 0 is now B!
    indexBasedSelect({ lat: 99, lng: 99, place_name: 'WRONG TARGET' });

    // Bug: B got updated instead of A
    expect(rows[0].dest!.place_name).toBe('WRONG TARGET'); // B was corrupted
    expect(rows[1].dest!.place_name).toBe('San Jose'); // A untouched
  });

  test('id-based: selecting after swap updates CORRECT row', () => {
    _wpIdCounter = 0;
    const A = makeRow('San Jose', 37.3382, -121.8863);
    const B = makeRow('Fresno', 36.7378, -119.7871);
    let rows = [A, B];

    // Capture onSelect callback for row id (A's id)
    const capturedId = A.id;
    const idBasedSelect = (s: any) => {
      rows = rows.map(r => r.id === capturedId ? { ...r, dest: s } : r);
    };

    // Swap: [A, B] → [B, A]
    rows = moveWaypoint(rows, 0, 1);

    // Callback fires for A's id — correctly targets A regardless of position
    idBasedSelect({ lat: 99, lng: 99, place_name: 'CORRECT TARGET' });

    expect(rows[0].dest!.place_name).toBe('Fresno'); // B untouched
    expect(rows[1].dest!.place_name).toBe('CORRECT TARGET'); // A updated
  });
});

describe('polyline key edge cases', () => {
  test('routes with same endpoints but different middle create DIFFERENT keys (fixed)', () => {
    // Route A→B: origin, A, B, dest (4 points)
    // Route B→A: origin, B, A, dest (4 points)
    // Both start at origin, end at dest, have length 4 — but different midpoints
    const geomAB: [number, number][] = [
      [ORIGIN.lat, ORIGIN.lng], [37.3, -121.8], [36.7, -119.7], [DEST.lat, DEST.lng]
    ];
    const geomBA: [number, number][] = [
      [ORIGIN.lat, ORIGIN.lng], [36.7, -119.7], [37.3, -121.8], [DEST.lat, DEST.lng]
    ];

    const plan1: TravelPlan = { route: { route_geometry: geomAB }, itineraries: [{ route_geometry: geomAB }], departure_time: 'T1' };
    const plan2: TravelPlan = { route: { route_geometry: geomBA }, itineraries: [{ route_geometry: geomBA }], departure_time: 'T1' };

    const key1 = polylineKey(0, plan1, geomAB);
    const key2 = polylineKey(0, plan2, geomBA);

    // Fixed: keys now differ — polyline remounts with correct route
    expect(key1).not.toBe(key2);
  });
});
