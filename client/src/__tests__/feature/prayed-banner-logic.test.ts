/**
 * Feature tests for PrayedBanner logic — what prayers are shown,
 * pair grouping in Musafir mode, undo behavior.
 * Tests the logic that drives the banner, not the rendering.
 * Rules: PRAYER_LOGIC_RULES.md §3
 */

import { useStore } from '../../store';

// Mirrors the logic in PrayedBanner
const ACTIVE_STATUSES = new Set([
  'can_catch_with_imam', 'can_catch_with_imam_in_progress',
  'can_pray_solo_at_mosque', 'pray_at_nearby_location',
]);

const MUSAFIR_PAIRS: Record<string, { p1: string; p2: string; label: string }> = {
  dhuhr:   { p1: 'dhuhr', p2: 'asr', label: 'Dhuhr + Asr' },
  asr:     { p1: 'dhuhr', p2: 'asr', label: 'Dhuhr + Asr' },
  maghrib: { p1: 'maghrib', p2: 'isha', label: 'Maghrib + Isha' },
  isha:    { p1: 'maghrib', p2: 'isha', label: 'Maghrib + Isha' },
};

function computeBannerItems(activePrayers: Set<string>, travelMode: boolean) {
  type Item = { kind: 'solo'; prayer: string } | { kind: 'pair'; p1: string; p2: string; label: string };
  const items: Item[] = [];
  const seen = new Set<string>();

  for (const prayer of Array.from(activePrayers)) {
    if (seen.has(prayer)) continue;
    if (travelMode && MUSAFIR_PAIRS[prayer]) {
      const { p1, p2, label } = MUSAFIR_PAIRS[prayer];
      items.push({ kind: 'pair', p1, p2, label });
      seen.add(p1); seen.add(p2);
    } else {
      items.push({ kind: 'solo', prayer });
      seen.add(prayer);
    }
  }
  return items;
}

function applyInference(prayedSet: Set<string>, travelMode: boolean): Set<string> {
  const effective = new Set(prayedSet);
  if (travelMode) {
    if (effective.has('asr')) effective.add('dhuhr');
    if (effective.has('isha')) effective.add('maghrib');
  }
  return effective;
}

beforeEach(() => {
  useStore.setState({ prayedToday: new Set(), travelMode: false });
  localStorage.clear();
});

describe('PrayedBanner — Muqeem mode', () => {
  test('shows individual prayers when active', () => {
    const items = computeBannerItems(new Set(['dhuhr', 'asr']), false);
    expect(items).toEqual([
      { kind: 'solo', prayer: 'dhuhr' },
      { kind: 'solo', prayer: 'asr' },
    ]);
  });

  test('no items when no active prayers', () => {
    const items = computeBannerItems(new Set(), false);
    expect(items).toEqual([]);
  });

  test('marking prayer toggles in store', () => {
    useStore.getState().togglePrayed('dhuhr');
    expect(useStore.getState().prayedToday.has('dhuhr')).toBe(true);
    // Undo
    useStore.getState().togglePrayed('dhuhr');
    expect(useStore.getState().prayedToday.has('dhuhr')).toBe(false);
  });
});

describe('PrayedBanner — Musafir mode', () => {
  test('groups Dhuhr+Asr into pair', () => {
    const items = computeBannerItems(new Set(['dhuhr', 'asr']), true);
    expect(items).toEqual([
      { kind: 'pair', p1: 'dhuhr', p2: 'asr', label: 'Dhuhr + Asr' },
    ]);
  });

  test('groups Maghrib+Isha into pair', () => {
    const items = computeBannerItems(new Set(['maghrib', 'isha']), true);
    expect(items).toEqual([
      { kind: 'pair', p1: 'maghrib', p2: 'isha', label: 'Maghrib + Isha' },
    ]);
  });

  test('Fajr stays solo in Musafir mode', () => {
    const items = computeBannerItems(new Set(['fajr', 'dhuhr', 'asr']), true);
    expect(items[0]).toEqual({ kind: 'solo', prayer: 'fajr' });
    expect(items[1]).toEqual({ kind: 'pair', p1: 'dhuhr', p2: 'asr', label: 'Dhuhr + Asr' });
  });

  test('pair shows as prayed when both marked', () => {
    const prayed = new Set(['dhuhr', 'asr']);
    const effective = applyInference(prayed, true);
    expect(effective.has('dhuhr') && effective.has('asr')).toBe(true);
  });

  test('Asr alone → pair prayed via inference', () => {
    const prayed = new Set(['asr']);
    const effective = applyInference(prayed, true);
    expect(effective.has('dhuhr')).toBe(true);
    expect(effective.has('asr')).toBe(true);
  });

  test('Dhuhr alone → pair NOT prayed (no reverse inference)', () => {
    const prayed = new Set(['dhuhr']);
    const effective = applyInference(prayed, true);
    expect(effective.has('dhuhr')).toBe(true);
    expect(effective.has('asr')).toBe(false);
  });

  test('togglePrayedPair marks both', () => {
    useStore.getState().togglePrayedPair('dhuhr', 'asr');
    const set = useStore.getState().prayedToday;
    expect(set.has('dhuhr')).toBe(true);
    expect(set.has('asr')).toBe(true);
  });

  test('togglePrayedPair undo removes both', () => {
    useStore.getState().togglePrayedPair('dhuhr', 'asr');
    useStore.getState().togglePrayedPair('dhuhr', 'asr');
    const set = useStore.getState().prayedToday;
    expect(set.has('dhuhr')).toBe(false);
    expect(set.has('asr')).toBe(false);
  });
});

describe('PrayedBanner — dedup', () => {
  test('same prayer from multiple mosques shown once', () => {
    // If dhuhr appears in activePrayers only once (Set), it gets one banner item
    const items = computeBannerItems(new Set(['dhuhr']), false);
    expect(items.length).toBe(1);
  });

  test('pair dedup — both Dhuhr and Asr active → one pair item', () => {
    const items = computeBannerItems(new Set(['dhuhr', 'asr']), true);
    expect(items.length).toBe(1);
    expect(items[0].kind).toBe('pair');
  });
});
