/**
 * Tests for the Fajr-to-Fajr day boundary in prayed tracker.
 * Rules: PRAYER_LOGIC_RULES.md §3.5
 *
 * The prayed tracker must use the same day key at 11 PM and 1 AM
 * (both are within the same Isha prayer period).
 */

import { useStore } from '../../store';

function setTime(isoString: string) {
  jest.useFakeTimers();
  jest.setSystemTime(new Date(isoString));
}

function findPrayedKey(): string | null {
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key?.startsWith('cap_prayed_')) return key;
  }
  return null;
}

afterEach(() => {
  jest.useRealTimers();
  localStorage.clear();
  useStore.setState({ prayedToday: new Set() });
});

describe('Prayed tracker day boundary', () => {
  test('Isha at 11 PM and 1 AM write to the SAME localStorage key', () => {
    // Mark at 11 PM
    setTime('2026-03-20T23:00:00');
    useStore.getState().togglePrayed('isha');
    const key11pm = findPrayedKey();
    expect(key11pm).toBeTruthy();

    localStorage.clear();
    useStore.setState({ prayedToday: new Set() });

    // Mark at 1 AM next calendar day
    jest.setSystemTime(new Date('2026-03-21T01:00:00'));
    useStore.getState().togglePrayed('isha');
    const key1am = findPrayedKey();
    expect(key1am).toBeTruthy();

    // Both should use the same key (same prayer day)
    expect(key11pm).toBe(key1am);
  });

  test('3:59 AM and 4:00 AM write to DIFFERENT keys (day boundary)', () => {
    // 3:59 AM — still previous prayer day
    setTime('2026-03-21T03:59:00');
    useStore.getState().togglePrayed('fajr');
    const key359 = findPrayedKey();

    localStorage.clear();
    useStore.setState({ prayedToday: new Set() });

    // 4:00 AM — new prayer day
    jest.setSystemTime(new Date('2026-03-21T04:00:00'));
    useStore.getState().togglePrayed('fajr');
    const key400 = findPrayedKey();

    expect(key359).not.toBe(key400);
  });

  test('noon March 20 and noon March 21 write to different keys', () => {
    setTime('2026-03-20T12:00:00');
    useStore.getState().togglePrayed('dhuhr');
    const keyDay1 = findPrayedKey();

    localStorage.clear();
    useStore.setState({ prayedToday: new Set() });

    jest.setSystemTime(new Date('2026-03-21T12:00:00'));
    useStore.getState().togglePrayed('dhuhr');
    const keyDay2 = findPrayedKey();

    expect(keyDay1).not.toBe(keyDay2);
  });
});
