/**
 * Unit tests for prayer logic — sequential inference, mode switching, period rules.
 * Rules: PRAYER_LOGIC_RULES.md §1-4
 */

export {}; // make this a module

// ─── Sequential Inference Helper ─────────────────────────────────────────────
// Mirrors the logic in App.tsx PrayedBanner and MosqueCard

function applySequentialInference(prayedSet: Set<string>): Set<string> {
  const result = new Set(prayedSet);
  // Asr prayed → Dhuhr implicitly done
  if (result.has('asr')) result.add('dhuhr');
  // Isha prayed → Maghrib implicitly done
  if (result.has('isha')) result.add('maghrib');
  return result;
}

function isPairComplete(effective: Set<string>, p1: string, p2: string): boolean {
  return effective.has(p1) && effective.has(p2);
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('Sequential Inference', () => {
  test('asr prayed → dhuhr implicitly marked', () => {
    const result = applySequentialInference(new Set(['asr']));
    expect(result.has('dhuhr')).toBe(true);
    expect(result.has('asr')).toBe(true);
  });

  test('dhuhr prayed → asr NOT implicitly marked', () => {
    const result = applySequentialInference(new Set(['dhuhr']));
    expect(result.has('dhuhr')).toBe(true);
    expect(result.has('asr')).toBe(false);
  });

  test('isha prayed → maghrib implicitly marked', () => {
    const result = applySequentialInference(new Set(['isha']));
    expect(result.has('maghrib')).toBe(true);
    expect(result.has('isha')).toBe(true);
  });

  test('maghrib prayed → isha NOT implicitly marked', () => {
    const result = applySequentialInference(new Set(['maghrib']));
    expect(result.has('maghrib')).toBe(true);
    expect(result.has('isha')).toBe(false);
  });

  test('fajr is standalone — no inference', () => {
    const result = applySequentialInference(new Set(['fajr']));
    expect(result.size).toBe(1);
    expect(result.has('fajr')).toBe(true);
  });

  test('all prayers → all marked', () => {
    const result = applySequentialInference(new Set(['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']));
    expect(result.size).toBe(5);
  });

  test('empty set → empty result', () => {
    const result = applySequentialInference(new Set());
    expect(result.size).toBe(0);
  });
});

describe('Pair Completion', () => {
  test('both marked → pair complete', () => {
    const effective = applySequentialInference(new Set(['dhuhr', 'asr']));
    expect(isPairComplete(effective, 'dhuhr', 'asr')).toBe(true);
  });

  test('asr only (inferred dhuhr) → pair complete', () => {
    const effective = applySequentialInference(new Set(['asr']));
    expect(isPairComplete(effective, 'dhuhr', 'asr')).toBe(true);
  });

  test('dhuhr only → pair incomplete', () => {
    const effective = applySequentialInference(new Set(['dhuhr']));
    expect(isPairComplete(effective, 'dhuhr', 'asr')).toBe(false);
  });

  test('neither marked → pair incomplete', () => {
    const effective = applySequentialInference(new Set());
    expect(isPairComplete(effective, 'dhuhr', 'asr')).toBe(false);
  });

  test('isha only → maghrib+isha pair complete', () => {
    const effective = applySequentialInference(new Set(['isha']));
    expect(isPairComplete(effective, 'maghrib', 'isha')).toBe(true);
  });
});

describe('Mode Switching (Muqeem → Musafir)', () => {
  test('muqeem asr prayed → musafir should have both dhuhr+asr', () => {
    // User marks asr in Muqeem, switches to Musafir
    const muqeemSet = new Set(['asr']);
    const musafirSet = applySequentialInference(muqeemSet);
    expect(musafirSet.has('dhuhr')).toBe(true);
    expect(musafirSet.has('asr')).toBe(true);
  });

  test('muqeem dhuhr only → musafir pair still incomplete', () => {
    const muqeemSet = new Set(['dhuhr']);
    const musafirSet = applySequentialInference(muqeemSet);
    expect(isPairComplete(musafirSet, 'dhuhr', 'asr')).toBe(false);
  });
});

describe('Prayer Period Order', () => {
  const PRAYER_ORDER = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha'];

  test('prayer order is chronological', () => {
    expect(PRAYER_ORDER).toEqual(['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']);
  });

  test('pairs are correct', () => {
    // Dhuhr+Asr pair
    expect(PRAYER_ORDER.indexOf('dhuhr')).toBeLessThan(PRAYER_ORDER.indexOf('asr'));
    // Maghrib+Isha pair
    expect(PRAYER_ORDER.indexOf('maghrib')).toBeLessThan(PRAYER_ORDER.indexOf('isha'));
  });
});
