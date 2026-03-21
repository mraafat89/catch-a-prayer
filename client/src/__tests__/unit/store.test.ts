/**
 * Unit tests for Zustand store — prayed tracker, mode switching, session ID.
 * Rules: PRAYER_LOGIC_RULES.md §3
 */

// We need to test the store logic without React rendering.
// Import the store creator and test state transitions.

import { useStore, SESSION_ID } from '../../store';

beforeEach(() => {
  // Reset store to defaults between tests
  useStore.setState({
    prayedToday: new Set(),
    travelMode: false,
    confirmedSpots: new Set(),
  });
  localStorage.clear();
});

describe('Session ID', () => {
  test('session ID is a non-empty string', () => {
    expect(SESSION_ID).toBeTruthy();
    expect(typeof SESSION_ID).toBe('string');
  });

  test('session ID starts with cap-', () => {
    expect(SESSION_ID).toMatch(/^cap-/);
  });

  test('session ID is stable across reads', () => {
    expect(SESSION_ID).toBe(SESSION_ID);
  });
});

describe('Prayed Tracker', () => {
  test('togglePrayed adds prayer to set', () => {
    useStore.getState().togglePrayed('dhuhr');
    expect(useStore.getState().prayedToday.has('dhuhr')).toBe(true);
  });

  test('togglePrayed removes on second call (undo)', () => {
    useStore.getState().togglePrayed('dhuhr');
    useStore.getState().togglePrayed('dhuhr');
    expect(useStore.getState().prayedToday.has('dhuhr')).toBe(false);
  });

  test('togglePrayed multiple prayers', () => {
    useStore.getState().togglePrayed('fajr');
    useStore.getState().togglePrayed('dhuhr');
    const set = useStore.getState().prayedToday;
    expect(set.has('fajr')).toBe(true);
    expect(set.has('dhuhr')).toBe(true);
    expect(set.size).toBe(2);
  });

  test('togglePrayedPair adds both prayers', () => {
    useStore.getState().togglePrayedPair('dhuhr', 'asr');
    const set = useStore.getState().prayedToday;
    expect(set.has('dhuhr')).toBe(true);
    expect(set.has('asr')).toBe(true);
  });

  test('togglePrayedPair removes both on second call', () => {
    useStore.getState().togglePrayedPair('dhuhr', 'asr');
    useStore.getState().togglePrayedPair('dhuhr', 'asr');
    const set = useStore.getState().prayedToday;
    expect(set.has('dhuhr')).toBe(false);
    expect(set.has('asr')).toBe(false);
  });

  test('togglePrayedPair removes if either already prayed', () => {
    useStore.getState().togglePrayed('dhuhr'); // mark dhuhr
    useStore.getState().togglePrayedPair('dhuhr', 'asr'); // toggle pair — should remove
    const set = useStore.getState().prayedToday;
    expect(set.has('dhuhr')).toBe(false);
    expect(set.has('asr')).toBe(false);
  });
});

describe('Travel Mode', () => {
  test('default is Muqeem (false)', () => {
    expect(useStore.getState().travelMode).toBe(false);
  });

  test('setTravelMode toggles', () => {
    useStore.getState().setTravelMode(true);
    expect(useStore.getState().travelMode).toBe(true);
    useStore.getState().setTravelMode(false);
    expect(useStore.getState().travelMode).toBe(false);
  });

  test('prayed set persists across mode switch', () => {
    useStore.getState().togglePrayed('fajr');
    useStore.getState().setTravelMode(true);
    expect(useStore.getState().prayedToday.has('fajr')).toBe(true);
    useStore.getState().setTravelMode(false);
    expect(useStore.getState().prayedToday.has('fajr')).toBe(true);
  });
});

describe('Confirmed Spots', () => {
  test('addConfirmedSpot adds to set', () => {
    useStore.getState().addConfirmedSpot('spot-123');
    expect(useStore.getState().confirmedSpots.has('spot-123')).toBe(true);
  });

  test('addConfirmedSpot is idempotent', () => {
    useStore.getState().addConfirmedSpot('spot-123');
    useStore.getState().addConfirmedSpot('spot-123');
    expect(useStore.getState().confirmedSpots.size).toBe(1);
  });
});

describe('Bottom Sheet', () => {
  test('default is null', () => {
    expect(useStore.getState().bottomSheet).toBeNull();
  });

  test('openSheet sets sheet', () => {
    useStore.getState().openSheet({ type: 'settings' });
    expect(useStore.getState().bottomSheet).toEqual({ type: 'settings' });
  });

  test('closeSheet clears sheet', () => {
    useStore.getState().openSheet({ type: 'settings' });
    useStore.getState().closeSheet();
    expect(useStore.getState().bottomSheet).toBeNull();
  });
});
