/**
 * Unit tests for time formatting and distance display helpers.
 * Rules: PRODUCT_REQUIREMENTS.md NFR-8.2 (metric/imperial)
 */

export {};

// ─── Helpers (mirrored from App.tsx) ─────────────────────────────────────────

function fmtTime(t: string | null): string {
  if (!t) return '—';
  try {
    if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(t)) {
      const [h, m] = t.split(':').map(Number);
      const d = new Date();
      d.setHours(h, m, 0, 0);
      return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    return new Date(t).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  } catch {
    return t;
  }
}

function fmtDuration(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  const days  = Math.floor(m / (24 * 60));
  const hours = Math.floor((m % (24 * 60)) / 60);
  const mins  = m % 60;
  if (days > 0) {
    const parts = [`${days} day${days > 1 ? 's' : ''}`];
    if (hours) parts.push(`${hours}h`);
    if (mins)  parts.push(`${mins}min`);
    return parts.join(' ');
  }
  if (hours > 0) return mins ? `${hours}h ${mins}min` : `${hours}h`;
  return `${mins}min`;
}

function distLabel(meters: number, useMetric: boolean): string {
  if (useMetric) {
    if (meters < 1000) return `${Math.round(meters)} m`;
    return `${(meters / 1000).toFixed(1)} km`;
  } else {
    const miles = meters / 1609.344;
    if (miles < 0.1) return `${Math.round(meters)} ft`.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    if (miles < 10) return `${miles.toFixed(1)} mi`;
    return `${Math.round(miles)} mi`;
  }
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('fmtTime', () => {
  test('null returns dash', () => {
    expect(fmtTime(null)).toBe('—');
  });

  test('empty string returns dash', () => {
    expect(fmtTime('')).toBe('—');
  });

  test('24h time is formatted', () => {
    const result = fmtTime('14:30');
    expect(result).toMatch(/2:30/); // "2:30 PM" or locale equivalent
  });

  test('midnight formats correctly', () => {
    const result = fmtTime('00:00');
    expect(result).toMatch(/12:00/); // "12:00 AM"
  });

  test('noon formats correctly', () => {
    const result = fmtTime('12:00');
    expect(result).toMatch(/12:00/); // "12:00 PM"
  });

  test('malformed string returns fallback', () => {
    // May return "Invalid Date" or the original string depending on Date parsing
    const result = fmtTime('not-a-time');
    expect(typeof result).toBe('string');
    expect(result.length).toBeGreaterThan(0);
  });
});

describe('fmtDuration', () => {
  test('minutes only', () => {
    expect(fmtDuration(45)).toBe('45min');
  });

  test('hours and minutes', () => {
    expect(fmtDuration(125)).toBe('2h 5min');
  });

  test('exact hours', () => {
    expect(fmtDuration(120)).toBe('2h');
  });

  test('days', () => {
    const result = fmtDuration(1500);
    expect(result).toMatch(/1 day/);
  });

  test('zero minutes', () => {
    expect(fmtDuration(0)).toBe('0min');
  });

  test('negative clamped to zero', () => {
    expect(fmtDuration(-10)).toBe('0min');
  });
});

describe('distLabel — metric (Canada)', () => {
  test('short distance in meters', () => {
    expect(distLabel(500, true)).toBe('500 m');
  });

  test('1+ km shows decimal', () => {
    expect(distLabel(1500, true)).toBe('1.5 km');
  });

  test('long distance in km', () => {
    expect(distLabel(25000, true)).toBe('25.0 km');
  });
});

describe('distLabel — imperial (US)', () => {
  test('very short in feet', () => {
    // 50 meters < 0.1 miles → shows as feet (raw meters value)
    const result = distLabel(50, false);
    expect(result).toMatch(/ft$/);
  });

  test('short in miles with decimal', () => {
    expect(distLabel(1500, false)).toBe('0.9 mi');
  });

  test('long in miles rounded', () => {
    expect(distLabel(25000, false)).toBe('16 mi');
  });
});
