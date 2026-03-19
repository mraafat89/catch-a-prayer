import { useStore } from './store';

// ─── Theme definitions ────────────────────────────────────────────────────────
// Two brand colors from the logo: teal (#0d9488) and dark (#2e3d44).
// Both colors are mixed in EVERY mode. Switching modes swaps their roles.
//
// Muqeem: teal buttons/pins  |  dark route/navigate-bar  |  teal text/borders/badges
// Musafir: dark buttons/pins  |  teal route/navigate-bar  |  teal text/borders/badges
//
// Key: Musafir keeps teal for secondary elements (text, borders, light bg, spinner,
// route) so the UI stays colorful. Only the primary action elements flip to dark.
//
// All class strings must be spelled out in full so Tailwind doesn't purge them.

const MUQEEM = {
  // Primary (teal) — buttons, navigate icon, mode pill
  bg:        'bg-teal-600',
  bgDark:    'bg-teal-700',
  bgLight:   'bg-teal-50',
  bgHover:   'hover:bg-teal-700',
  bgHoverLight: 'hover:bg-teal-50',
  bgHoverMed:   'hover:bg-teal-100',
  // Text — teal shades
  text:       'text-teal-700',
  textDark:   'text-teal-800',
  textDarker: 'text-teal-900',
  textMid:    'text-teal-600',
  textLight:  'text-teal-400',
  textVeryLight: 'text-teal-200',
  textWhite:  'text-teal-100',
  textHover:  'hover:text-teal-700',
  textHoverDark: 'hover:text-teal-800',
  // Borders — teal
  border:       'border-teal-200',
  borderStrong: 'border-teal-400',
  borderHover:  'hover:border-teal-300',
  shadow: 'shadow-teal-100',
  gradient: 'from-teal-700 to-teal-600',
  spinnerTop: 'border-t-teal-600',
  // Accent (dark) — navigate bar, secondary buttons
  bgAccent:      'bg-[#2e3d44]',
  bgAccentHover: 'hover:bg-[#232f35]',
  // Primary hex (buttons, SVG fills, map pins)
  hex:      '#0d9488',
  hexLight: 'rgba(13,148,136,0.12)',
  // Route uses accent color, pins use primary
  polyline: '#2e3d44',
  stopPin:  '#0d9488',
  userDot:  '#0d9488',
};

const MUSAFIR = {
  // Primary (dark) — buttons, navigate icon, mode pill
  bg:        'bg-[#2e3d44]',
  bgDark:    'bg-[#232f35]',
  bgLight:   'bg-teal-50',            // ← teal light bg (colorful badges!)
  bgHover:   'hover:bg-[#232f35]',
  bgHoverLight: 'hover:bg-teal-50',   // ← teal hover
  bgHoverMed:   'hover:bg-teal-100',  // ← teal hover
  // Text — teal shades (keeps it colorful, not gray)
  text:       'text-teal-700',
  textDark:   'text-teal-800',
  textDarker: 'text-teal-900',
  textMid:    'text-teal-600',
  textLight:  'text-teal-400',
  textVeryLight: 'text-teal-200',
  textWhite:  'text-teal-100',
  textHover:  'hover:text-teal-700',
  textHoverDark: 'hover:text-teal-800',
  // Borders — teal (colorful accents)
  border:       'border-teal-200',
  borderStrong: 'border-teal-400',
  borderHover:  'hover:border-teal-300',
  shadow: 'shadow-teal-100',
  gradient: 'from-[#232f35] to-[#2e3d44]',
  spinnerTop: 'border-t-teal-600',    // ← teal spinner
  // Accent (teal) — navigate bar, secondary buttons (FLIPPED)
  bgAccent:      'bg-teal-600',
  bgAccentHover: 'hover:bg-teal-700',
  // Primary hex (buttons, SVG fills, map pins)
  hex:      '#2e3d44',
  hexLight: 'rgba(46,61,68,0.12)',
  // Route uses accent color (teal!), pins use primary (dark)
  polyline: '#0d9488',
  stopPin:  '#2e3d44',
  userDot:  '#2e3d44',
};

export type AppTheme = typeof MUQEEM;

export function getTheme(isMusafir: boolean): AppTheme {
  return isMusafir ? MUSAFIR : MUQEEM;
}

/** Hook — use inside any React component. */
export function useTheme(): AppTheme {
  const travelMode = useStore((s) => s.travelMode);
  return getTheme(travelMode);
}
