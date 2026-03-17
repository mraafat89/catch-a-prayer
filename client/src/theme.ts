import { useStore } from './store';

// ─── Theme definitions ────────────────────────────────────────────────────────
// Muqeem (resident) = teal   |   Musafir (traveler) = indigo
// All class strings must be spelled out in full so Tailwind doesn't purge them.

const MUQEEM = {
  // Solid backgrounds
  bg:        'bg-teal-600',
  bgDark:    'bg-teal-700',
  bgLight:   'bg-teal-50',
  bgHover:   'hover:bg-teal-700',
  bgHoverLight: 'hover:bg-teal-50',
  bgHoverMed:   'hover:bg-teal-100',
  // Text
  text:       'text-teal-700',
  textDark:   'text-teal-800',
  textDarker: 'text-teal-900',
  textMid:    'text-teal-600',
  textLight:  'text-teal-400',
  textVeryLight: 'text-teal-200',
  textWhite:  'text-teal-100',
  textHover:  'hover:text-teal-700',
  textHoverDark: 'hover:text-teal-800',
  // Borders
  border:       'border-teal-200',
  borderStrong: 'border-teal-400',
  borderHover:  'hover:border-teal-300',
  // Shadow
  shadow: 'shadow-teal-100',
  // Header gradient
  gradient: 'from-teal-700 to-teal-600',
  // Spinner border-top (for animated spinners)
  spinnerTop: 'border-t-teal-600',
  // Hex values for SVG/canvas (MapView, status colors)
  hex:      '#0d9488',
  hexLight: 'rgba(13,148,136,0.12)',
  polyline: '#0d9488',
  stopPin:  '#0d9488',
  userDot:  '#0d9488',
};

const MUSAFIR = {
  bg:        'bg-indigo-600',
  bgDark:    'bg-indigo-700',
  bgLight:   'bg-indigo-50',
  bgHover:   'hover:bg-indigo-700',
  bgHoverLight: 'hover:bg-indigo-50',
  bgHoverMed:   'hover:bg-indigo-100',
  text:       'text-indigo-700',
  textDark:   'text-indigo-800',
  textDarker: 'text-indigo-900',
  textMid:    'text-indigo-600',
  textLight:  'text-indigo-400',
  textVeryLight: 'text-indigo-200',
  textWhite:  'text-indigo-100',
  textHover:  'hover:text-indigo-700',
  textHoverDark: 'hover:text-indigo-800',
  border:       'border-indigo-200',
  borderStrong: 'border-indigo-400',
  borderHover:  'hover:border-indigo-300',
  shadow: 'shadow-indigo-100',
  gradient: 'from-indigo-700 to-indigo-600',
  spinnerTop: 'border-t-indigo-600',
  hex:      '#6366f1',
  hexLight: 'rgba(99,102,241,0.12)',
  polyline: '#6366f1',
  stopPin:  '#6366f1',
  userDot:  '#6366f1',
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
