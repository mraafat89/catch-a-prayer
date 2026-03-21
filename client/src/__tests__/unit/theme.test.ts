/**
 * Unit tests for the theme system.
 * Rules: FRONTEND_DESIGN.md Two-Mode Theme System
 */

import { getTheme } from '../../theme';

describe('Muqeem Theme (resident)', () => {
  const theme = getTheme(false);

  test('primary bg is teal', () => {
    expect(theme.bg).toContain('teal');
  });

  test('hex is teal color', () => {
    expect(theme.hex).toBe('#0d9488');
  });

  test('polyline is dark (contrasting)', () => {
    expect(theme.polyline).toBe('#2e3d44');
  });

  test('accent bg is dark', () => {
    expect(theme.bgAccent).toContain('2e3d44');
  });
});

describe('Musafir Theme (traveler)', () => {
  const theme = getTheme(true);

  test('primary bg is dark', () => {
    expect(theme.bg).toContain('2e3d44');
  });

  test('hex is dark color', () => {
    expect(theme.hex).toBe('#2e3d44');
  });

  test('polyline is teal (contrasting)', () => {
    expect(theme.polyline).toBe('#0d9488');
  });

  test('accent bg is teal (flipped)', () => {
    expect(theme.bgAccent).toContain('teal');
  });

  test('text stays teal (colorful)', () => {
    expect(theme.text).toContain('teal');
  });

  test('bgLight stays teal (colorful badges)', () => {
    expect(theme.bgLight).toContain('teal');
  });
});

describe('Theme consistency', () => {
  const muqeem = getTheme(false);
  const musafir = getTheme(true);

  test('both have same keys', () => {
    const muqeemKeys = Object.keys(muqeem).sort();
    const musafirKeys = Object.keys(musafir).sort();
    expect(muqeemKeys).toEqual(musafirKeys);
  });

  test('text colors are same in both modes', () => {
    expect(muqeem.text).toBe(musafir.text);
    expect(muqeem.textDark).toBe(musafir.textDark);
  });

  test('border colors are same in both modes', () => {
    expect(muqeem.border).toBe(musafir.border);
  });
});
