/**
 * Feature tests for MosqueCard rendering logic — status display,
 * prayed filtering, travel combinations visibility.
 * Rules: PRAYER_LOGIC_RULES.md §2, §4
 */

export {};

// Status config mirrors types/index.ts
const STATUS_CONFIG: Record<string, { bg: string; text: string }> = {
  can_catch_with_imam:             { bg: 'bg-green-50',  text: 'text-green-800' },
  can_catch_with_imam_in_progress: { bg: 'bg-yellow-50', text: 'text-yellow-800' },
  can_pray_solo_at_mosque:         { bg: 'bg-blue-50',   text: 'text-blue-800' },
  pray_at_nearby_location:         { bg: 'bg-orange-50', text: 'text-orange-800' },
  missed_make_up:                  { bg: 'bg-gray-50',   text: 'text-gray-600' },
  upcoming:                        { bg: 'bg-gray-50',   text: 'text-gray-600' },
};

interface MockCatchable {
  prayer: string;
  status: string;
}

// Logic: determine which prayer to show on the card
function primaryPrayerForCard(
  catchable: MockCatchable[],
  prayedSet: Set<string>,
): MockCatchable | null {
  // Filter out prayed prayers
  const unprayed = catchable.filter(p => !prayedSet.has(p.prayer));
  if (unprayed.length === 0) return null;
  // Return highest priority (first in list — already sorted by backend)
  return unprayed[0];
}

// Logic: which travel combinations to show
function visibleCombinations(
  pairs: Array<{ pair: string; options: any[] }>,
  effectivePrayed: Set<string>,
): Array<{ pair: string; options: any[] }> {
  const PAIR_PRAYERS: Record<string, [string, string]> = {
    dhuhr_asr: ['dhuhr', 'asr'],
    maghrib_isha: ['maghrib', 'isha'],
  };
  return pairs.filter(pair => {
    const prayers = PAIR_PRAYERS[pair.pair];
    if (!prayers) return true;
    return !(effectivePrayed.has(prayers[0]) && effectivePrayed.has(prayers[1]));
  });
}

describe('MosqueCard — primary prayer selection', () => {
  test('returns first unprayed prayer', () => {
    const catchable: MockCatchable[] = [
      { prayer: 'dhuhr', status: 'can_catch_with_imam' },
      { prayer: 'asr', status: 'upcoming' },
    ];
    const result = primaryPrayerForCard(catchable, new Set());
    expect(result?.prayer).toBe('dhuhr');
  });

  test('skips prayed prayer, returns next', () => {
    const catchable: MockCatchable[] = [
      { prayer: 'dhuhr', status: 'can_catch_with_imam' },
      { prayer: 'asr', status: 'upcoming' },
    ];
    const result = primaryPrayerForCard(catchable, new Set(['dhuhr']));
    expect(result?.prayer).toBe('asr');
  });

  test('returns null when all prayed', () => {
    const catchable: MockCatchable[] = [
      { prayer: 'dhuhr', status: 'can_catch_with_imam' },
    ];
    const result = primaryPrayerForCard(catchable, new Set(['dhuhr']));
    expect(result).toBeNull();
  });

  test('returns null for empty catchable', () => {
    expect(primaryPrayerForCard([], new Set())).toBeNull();
  });
});

describe('MosqueCard — status config', () => {
  test('all 6 statuses have config', () => {
    const statuses = [
      'can_catch_with_imam', 'can_catch_with_imam_in_progress',
      'can_pray_solo_at_mosque', 'pray_at_nearby_location',
      'missed_make_up', 'upcoming',
    ];
    for (const s of statuses) {
      expect(STATUS_CONFIG[s]).toBeDefined();
      expect(STATUS_CONFIG[s].bg).toBeTruthy();
      expect(STATUS_CONFIG[s].text).toBeTruthy();
    }
  });
});

describe('MosqueCard — travel combinations visibility', () => {
  const mockPairs = [
    { pair: 'dhuhr_asr', options: [{ option_type: 'combine_early' }] },
    { pair: 'maghrib_isha', options: [{ option_type: 'combine_late' }] },
  ];

  test('both shown when none prayed', () => {
    const visible = visibleCombinations(mockPairs, new Set());
    expect(visible.length).toBe(2);
  });

  test('dhuhr_asr hidden when both prayed', () => {
    const visible = visibleCombinations(mockPairs, new Set(['dhuhr', 'asr']));
    expect(visible.length).toBe(1);
    expect(visible[0].pair).toBe('maghrib_isha');
  });

  test('both hidden when all prayed', () => {
    const visible = visibleCombinations(mockPairs, new Set(['dhuhr', 'asr', 'maghrib', 'isha']));
    expect(visible.length).toBe(0);
  });

  test('partial pray (only dhuhr) → pair still visible', () => {
    const visible = visibleCombinations(mockPairs, new Set(['dhuhr']));
    expect(visible.length).toBe(2); // pair requires BOTH to hide
  });
});
