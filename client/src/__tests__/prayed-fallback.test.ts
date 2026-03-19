/**
 * Tests for the "already prayed" fallback logic in MosqueCard.
 * When a user marks a prayer as prayed, the card should show the NEXT
 * prayer in chronological order (not jump to Fajr or skip to Maghrib).
 */

const PRAYER_ORDER = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha'];

interface PrayerTime {
  prayer: string;
  adhan_time: string | null;
  iqama_time: string | null;
}

/**
 * Find the next unprayed prayer that is currently active or upcoming.
 * Must not return prayers whose period has already ended.
 *
 * Algorithm:
 * 1. Build adhan times in minutes for all prayers
 * 2. Find the current prayer period (whose adhan <= now < next adhan)
 * 3. Starting from the current period, find the first unprayed prayer
 * 4. Wrap around is NOT needed (no Fajr after Isha in same day context)
 */
function findNextUnprayedPrayer(
  prayers: PrayerTime[],
  prayedSet: Set<string>,
  nowMinutes: number,
): PrayerTime | null {
  const prayerMap = new Map(prayers.map(p => [p.prayer, p]));

  // Build ordered list with adhan minutes
  const ordered = PRAYER_ORDER
    .map(name => {
      const p = prayerMap.get(name);
      if (!p || !p.adhan_time) return null;
      const [h, m] = p.adhan_time.split(':').map(Number);
      return { ...p, adhanMin: h * 60 + m };
    })
    .filter((p): p is PrayerTime & { adhanMin: number } => p !== null);

  if (ordered.length === 0) return null;

  // Find the index of the current or most recent prayer period.
  // The current period is the last prayer whose adhan has passed.
  let currentIdx = -1;
  for (let i = ordered.length - 1; i >= 0; i--) {
    if (ordered[i].adhanMin <= nowMinutes) {
      currentIdx = i;
      break;
    }
  }

  // If no adhan has passed yet today (before Fajr), start from index 0
  if (currentIdx === -1) currentIdx = 0;

  // Starting from the current prayer, find the first unprayed one
  for (let i = currentIdx; i < ordered.length; i++) {
    if (!prayedSet.has(ordered[i].prayer)) {
      return ordered[i];
    }
  }

  return null; // all remaining prayers today are prayed
}

// Test prayer schedule
const PRAYERS: PrayerTime[] = [
  { prayer: 'fajr',    adhan_time: '05:30', iqama_time: '05:45' },
  { prayer: 'dhuhr',   adhan_time: '12:30', iqama_time: '13:00' },
  { prayer: 'asr',     adhan_time: '15:45', iqama_time: '16:00' },
  { prayer: 'maghrib', adhan_time: '18:15', iqama_time: '18:20' },
  { prayer: 'isha',    adhan_time: '19:45', iqama_time: '20:00' },
];

describe('findNextUnprayedPrayer', () => {
  test('during Dhuhr (13:30), no prayers prayed → returns Dhuhr', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(), 13 * 60 + 30);
    expect(result?.prayer).toBe('dhuhr');
  });

  test('during Dhuhr (13:30), Dhuhr prayed → returns Asr', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(['dhuhr']), 13 * 60 + 30);
    expect(result?.prayer).toBe('asr');
  });

  test('during Dhuhr (13:30), Dhuhr prayed → does NOT return Fajr', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(['dhuhr']), 13 * 60 + 30);
    expect(result?.prayer).not.toBe('fajr');
  });

  test('during Asr (16:00), Dhuhr+Asr prayed → returns Maghrib', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(['dhuhr', 'asr']), 16 * 60);
    expect(result?.prayer).toBe('maghrib');
  });

  test('during Asr (16:00), nothing prayed → returns Asr (not Fajr or Dhuhr)', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(), 16 * 60);
    expect(result?.prayer).toBe('asr');
  });

  test('during Maghrib (18:30), Dhuhr+Asr+Maghrib prayed → returns Isha', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(['dhuhr', 'asr', 'maghrib']), 18 * 60 + 30);
    expect(result?.prayer).toBe('isha');
  });

  test('during Isha (20:00), all prayed → returns null', () => {
    const result = findNextUnprayedPrayer(
      PRAYERS,
      new Set(['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']),
      20 * 60,
    );
    expect(result).toBeNull();
  });

  test('before Fajr (04:00), nothing prayed → returns Fajr', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(), 4 * 60);
    expect(result?.prayer).toBe('fajr');
  });

  test('during Fajr (05:45), Fajr prayed → returns Dhuhr', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(['fajr']), 5 * 60 + 45);
    expect(result?.prayer).toBe('dhuhr');
  });

  test('late Dhuhr (15:30, Asr adhan at 15:45), Dhuhr prayed → returns Asr', () => {
    // This is the exact user scenario: Dhuhr marked prayed just before Asr starts
    const result = findNextUnprayedPrayer(PRAYERS, new Set(['dhuhr']), 15 * 60 + 30);
    expect(result?.prayer).toBe('asr');
  });

  test('after Asr adhan (15:50), Dhuhr prayed → returns Asr (not Maghrib)', () => {
    // Asr adhan has passed, Dhuhr is prayed. Should show Asr, not skip to Maghrib.
    const result = findNextUnprayedPrayer(PRAYERS, new Set(['dhuhr']), 15 * 60 + 50);
    expect(result?.prayer).toBe('asr');
  });

  test('Musafir: Dhuhr+Asr both prayed during Asr time → returns Maghrib', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(['dhuhr', 'asr']), 16 * 60 + 30);
    expect(result?.prayer).toBe('maghrib');
  });

  test('edge: only Fajr prayed, during Dhuhr → returns Dhuhr', () => {
    const result = findNextUnprayedPrayer(PRAYERS, new Set(['fajr']), 13 * 60);
    expect(result?.prayer).toBe('dhuhr');
  });
});

// Musafir combination display tests
describe('Musafir pair display after praying', () => {
  const MUSAFIR_PAIR_MAP: Record<string, { p1: string; p2: string; label: string }> = {
    dhuhr:   { p1: 'dhuhr', p2: 'asr',  label: 'Dhuhr + Asr' },
    asr:     { p1: 'dhuhr', p2: 'asr',  label: 'Dhuhr + Asr' },
    maghrib: { p1: 'maghrib', p2: 'isha', label: 'Maghrib + Isha' },
    isha:    { p1: 'maghrib', p2: 'isha', label: 'Maghrib + Isha' },
  };

  function getMusafirDisplay(
    activePrayer: string,
    prayedSet: Set<string>,
  ): { kind: 'pair'; p1: string; p2: string } | { kind: 'solo'; prayer: string } | null {
    const pair = MUSAFIR_PAIR_MAP[activePrayer];
    if (!pair) return { kind: 'solo', prayer: activePrayer };

    const p1Prayed = prayedSet.has(pair.p1);
    const p2Prayed = prayedSet.has(pair.p2);

    if (p1Prayed && p2Prayed) return null; // both done
    if (!p1Prayed && !p2Prayed) return { kind: 'pair', p1: pair.p1, p2: pair.p2 };
    // One prayed: show the remaining as solo
    return { kind: 'solo', prayer: p1Prayed ? pair.p2 : pair.p1 };
  }

  test('Dhuhr time, nothing prayed → show pair Dhuhr+Asr', () => {
    const result = getMusafirDisplay('dhuhr', new Set());
    expect(result).toEqual({ kind: 'pair', p1: 'dhuhr', p2: 'asr' });
  });

  test('Dhuhr time, Dhuhr prayed → show solo Asr', () => {
    const result = getMusafirDisplay('dhuhr', new Set(['dhuhr']));
    expect(result).toEqual({ kind: 'solo', prayer: 'asr' });
  });

  test('Asr time, Dhuhr prayed → show solo Asr', () => {
    const result = getMusafirDisplay('asr', new Set(['dhuhr']));
    expect(result).toEqual({ kind: 'solo', prayer: 'asr' });
  });

  test('Dhuhr+Asr both prayed → null (done)', () => {
    const result = getMusafirDisplay('dhuhr', new Set(['dhuhr', 'asr']));
    expect(result).toBeNull();
  });

  test('Maghrib time, nothing prayed → show pair Maghrib+Isha', () => {
    const result = getMusafirDisplay('maghrib', new Set());
    expect(result).toEqual({ kind: 'pair', p1: 'maghrib', p2: 'isha' });
  });

  test('Maghrib prayed → show solo Isha', () => {
    const result = getMusafirDisplay('isha', new Set(['maghrib']));
    expect(result).toEqual({ kind: 'solo', prayer: 'isha' });
  });
});
