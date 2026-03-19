/**
 * Tests for waypoint reorder logic in TripPlanningBar.
 * Verifies that moveWaypoint correctly swaps items and that
 * executePlan reads waypoints in the correct order.
 */

interface WaypointRow {
  dest: { lat: number; lng: number; place_name: string } | null;
  query: string;
  sugg: any[];
  loading: boolean;
}

function makeRow(name: string, lat: number, lng: number): WaypointRow {
  return { dest: { lat, lng, place_name: name }, query: name, sugg: [], loading: false };
}

// Simulate React's functional state updater
function applyUpdater(state: WaypointRow[], updater: (rows: WaypointRow[]) => WaypointRow[]): WaypointRow[] {
  return updater(state);
}

// Extracted moveWaypoint logic (mirrors the React component)
function moveWaypoint(
  rows: WaypointRow[],
  index: number,
  direction: -1 | 1
): WaypointRow[] {
  const newIndex = index + direction;
  if (newIndex < 0 || newIndex >= rows.length) return rows;
  const next = [...rows];
  [next[index], next[newIndex]] = [next[newIndex], next[index]];
  return next;
}

// Extracted wps builder (mirrors executePlan)
function buildWps(rows: WaypointRow[]): Array<{ lat: number; lng: number; name: string }> {
  return rows
    .filter(w => w.dest !== null)
    .map(w => ({ lat: w.dest!.lat, lng: w.dest!.lng, name: w.dest!.place_name }));
}

describe('waypoint reorder', () => {
  const A = makeRow('San Jose', 37.3382, -121.8863);
  const B = makeRow('Fresno', 36.7378, -119.7871);
  const C = makeRow('Bakersfield', 35.3733, -119.0187);

  test('initial order: A, B → wps = [A, B]', () => {
    const rows = [A, B];
    const wps = buildWps(rows);
    expect(wps[0].name).toBe('San Jose');
    expect(wps[1].name).toBe('Fresno');
  });

  test('move A down: [A, B] → [B, A]', () => {
    let rows = [A, B];
    rows = moveWaypoint(rows, 0, 1);
    expect(rows[0].dest!.place_name).toBe('Fresno');
    expect(rows[1].dest!.place_name).toBe('San Jose');
    const wps = buildWps(rows);
    expect(wps[0].name).toBe('Fresno');
    expect(wps[1].name).toBe('San Jose');
  });

  test('move A down then back up: [A, B] → [B, A] → [A, B]', () => {
    let rows = [A, B];
    rows = moveWaypoint(rows, 0, 1);   // A down → [B, A]
    rows = moveWaypoint(rows, 1, -1);   // A (now at 1) up → [A, B]
    const wps = buildWps(rows);
    expect(wps[0].name).toBe('San Jose');
    expect(wps[1].name).toBe('Fresno');
  });

  test('multiple swaps return to original: [A, B] → ... → [A, B]', () => {
    let rows = [A, B];
    rows = moveWaypoint(rows, 0, 1);   // [B, A]
    rows = moveWaypoint(rows, 0, 1);   // [A, B] — B moves down from 0
    const wps = buildWps(rows);
    expect(wps[0].name).toBe('San Jose');
    expect(wps[1].name).toBe('Fresno');
  });

  test('three waypoints: move C to top', () => {
    let rows = [A, B, C];
    rows = moveWaypoint(rows, 2, -1);  // C up → [A, C, B]
    rows = moveWaypoint(rows, 1, -1);  // C up → [C, A, B]
    const wps = buildWps(rows);
    expect(wps[0].name).toBe('Bakersfield');
    expect(wps[1].name).toBe('San Jose');
    expect(wps[2].name).toBe('Fresno');
  });

  test('three waypoints: reverse order then restore', () => {
    let rows = [A, B, C];
    // Reverse: [A,B,C] → [A,C,B] → [C,A,B] → [C,B,A]
    rows = moveWaypoint(rows, 2, -1);  // [A, C, B]
    rows = moveWaypoint(rows, 1, -1);  // [C, A, B]
    rows = moveWaypoint(rows, 2, -1);  // [C, B, A]
    expect(buildWps(rows).map(w => w.name)).toEqual(['Bakersfield', 'Fresno', 'San Jose']);

    // Restore: [C,B,A] → [B,C,A] → [B,A,C] → [A,B,C]
    rows = moveWaypoint(rows, 0, 1);   // [B, C, A]
    rows = moveWaypoint(rows, 1, 1);   // [B, A, C]
    rows = moveWaypoint(rows, 0, 1);   // [A, B, C]
    expect(buildWps(rows).map(w => w.name)).toEqual(['San Jose', 'Fresno', 'Bakersfield']);
  });

  test('bounds check: move first item up is no-op', () => {
    let rows = [A, B];
    rows = moveWaypoint(rows, 0, -1);
    expect(buildWps(rows).map(w => w.name)).toEqual(['San Jose', 'Fresno']);
  });

  test('bounds check: move last item down is no-op', () => {
    let rows = [A, B];
    rows = moveWaypoint(rows, 1, 1);
    expect(buildWps(rows).map(w => w.name)).toEqual(['San Jose', 'Fresno']);
  });

  test('with null dest rows: only confirmed waypoints in wps', () => {
    const empty: WaypointRow = { dest: null, query: '', sugg: [], loading: false };
    let rows = [A, empty, B];
    rows = moveWaypoint(rows, 0, 1);  // swap 0↔1 → [empty, A, B]
    const wps = buildWps(rows);
    expect(wps.length).toBe(2);
    expect(wps[0].name).toBe('San Jose');
    expect(wps[1].name).toBe('Fresno');
  });

  // Simulate the exact user scenario: add A, add B, move around, return, plan
  test('user scenario: add A, add B, shuffle, return to original, plan', () => {
    let rows = [A, B];

    // Move A down
    rows = moveWaypoint(rows, 0, 1);   // [B, A]
    expect(rows[0].dest!.place_name).toBe('Fresno');

    // Move A (at index 1) back up
    rows = moveWaypoint(rows, 1, -1);  // [A, B]
    expect(rows[0].dest!.place_name).toBe('San Jose');

    // Move B (at index 1) up
    rows = moveWaypoint(rows, 1, -1);  // [B, A]
    expect(rows[0].dest!.place_name).toBe('Fresno');

    // Move B (at index 0) back down
    rows = moveWaypoint(rows, 0, 1);   // [A, B]
    expect(rows[0].dest!.place_name).toBe('San Jose');

    // Final plan: should be A then B
    const wps = buildWps(rows);
    expect(wps[0].name).toBe('San Jose');
    expect(wps[1].name).toBe('Fresno');
  });
});
