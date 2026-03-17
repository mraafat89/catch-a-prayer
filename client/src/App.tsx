import React, { useEffect, useRef, useState, Suspense, lazy } from 'react';
// MapView is lazy-loaded to defer Leaflet initialization until after mount (fixes iOS/WKWebView startup crash)
import { apiService } from './services/api';
import { useStore, SESSION_ID } from './store';
import { useTheme } from './theme';
import {
  Mosque, PrayerSpot, PrayerTime, JumuahSession,
  STATUS_CONFIG, SPOT_TYPE_LABELS,
  SpotSubmitRequest,
  TravelPairPlan, TravelOption, TravelDestination, TravelStop, GeocodeSuggestion,
  TripItinerary, PairChoice,
} from './types';

const MapView = lazy(() => import('./components/MapView'));

// ─── Helpers ────────────────────────────────────────────────────────────────

/**
 * Parse a Google Maps or Apple Maps share URL and extract lat/lng + place name.
 * Returns null if the URL doesn't contain parseable coordinates.
 */
function parseMapShareUrl(rawUrl: string): { lat: number; lng: number; place_name: string } | null {
  try {
    // Google Maps place URL: /maps/place/Name/@lat,lng,zoom
    const placeMatch = rawUrl.match(/\/maps\/place\/([^/@]+)\/@(-?\d+\.\d+),(-?\d+\.\d+)/);
    if (placeMatch) {
      return {
        place_name: decodeURIComponent(placeMatch[1]).replace(/\+/g, ' '),
        lat: parseFloat(placeMatch[2]),
        lng: parseFloat(placeMatch[3]),
      };
    }

    const u = new URL(rawUrl);

    // Apple Maps: ?ll=lat,lng
    const ll = u.searchParams.get('ll');
    if (ll) {
      const llMatch = ll.match(/(-?\d+\.\d+),(-?\d+\.\d+)/);
      if (llMatch) {
        const name = u.searchParams.get('q') ?? u.searchParams.get('address') ?? 'Shared destination';
        return { lat: parseFloat(llMatch[1]), lng: parseFloat(llMatch[2]), place_name: name };
      }
    }

    // Google Maps: ?q=lat,lng
    const q = u.searchParams.get('q') ?? u.searchParams.get('query');
    if (q) {
      const coordMatch = q.match(/^(-?\d+\.\d+),(-?\d+\.\d+)$/);
      if (coordMatch) {
        return { lat: parseFloat(coordMatch[1]), lng: parseFloat(coordMatch[2]), place_name: 'Shared destination' };
      }
    }
  } catch {}
  return null;
}

function fmtTime(t: string | null): string {
  if (!t) return '—';
  try {
    // Handle plain "HH:MM" or "HH:MM:SS" from the backend
    if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(t)) {
      const [h, m] = t.split(':').map(Number);
      const d = new Date();
      d.setHours(h, m, 0, 0);
      return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    // Fall back to ISO string parsing
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

const WEBSITE_SOURCES = new Set([
  'mosque_website_html', 'mosque_website_js', 'mosque_website',
  'static_html', 'playwright_html', 'vision_ai',
]);

const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

interface MapPoint {
  lat: number;
  lng: number;
  name?: string;
  place_id?: string | null;
  is_gps?: boolean;  // true = use device current location instead of explicit coords
}

function buildGoogleMapsUrl(points: MapPoint[]): string {
  // Use the directions URL format: /maps/dir/origin/.../destination
  // Empty first segment when origin is GPS — Google uses current device location
  // Use place_id when available; fall back to name+address search query for a named pin
  const segments = points.map(p => {
    if (p.is_gps) return '';
    if (p.place_id) return `place_id:${p.place_id}`;
    if (p.name) return encodeURIComponent(p.name);
    return `${p.lat},${p.lng}`;
  });
  return 'https://www.google.com/maps/dir/' + segments.join('/');
}

function buildAppleMapsUrl(points: MapPoint[]): string {
  // Apple Maps: saddr=Name@lat,lng  daddr=Name@lat,lng (repeated)
  // Omit saddr when origin is GPS — Apple Maps uses current device location
  function applePoint(p: MapPoint): string {
    if (p.name) return `${encodeURIComponent(p.name)}@${p.lat},${p.lng}`;
    return `${p.lat},${p.lng}`;
  }
  const [origin, ...rest] = points;
  const destParts = rest.map(p => `daddr=${applePoint(p)}`).join('&');
  if (origin.is_gps) {
    return `https://maps.apple.com/?${destParts}&dirflg=d`;
  }
  return `https://maps.apple.com/?saddr=${applePoint(origin)}&${destParts}&dirflg=d`;
}

function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function dataSourceBadge(prayers: { adhan_source?: string | null; iqama_source?: string | null; data_freshness?: string | null }[]): {
  label: string; color: string; title?: string;
} {
  if (!prayers.length) return { label: '~ Estimated times', color: 'text-amber-600' };
  // Look at non-fajr prayers for source info (fajr often has different sources)
  const relevant = prayers.filter(p => !['fajr'].includes((p as any).prayer));
  const sample = relevant.length ? relevant[0] : prayers[0];
  const adhanSrc = (sample as any).adhan_source ?? '';
  const iqamaSrc = (sample as any).iqama_source ?? '';
  const freshness = (sample as any).data_freshness ?? null;

  const adhanVerified = WEBSITE_SOURCES.has(adhanSrc);
  const iqamaVerified = WEBSITE_SOURCES.has(iqamaSrc);
  const freshSuffix = freshness ? ` · ${freshness}` : '';

  if (adhanVerified && iqamaVerified) {
    return { label: `✓ From mosque website${freshSuffix}`, color: 'text-green-700' };
  }
  if (adhanSrc === 'islamicfinder' || iqamaSrc === 'islamicfinder') {
    return { label: `From IslamicFinder${freshSuffix}`, color: 'text-gray-500' };
  }
  if (adhanVerified && !iqamaVerified) {
    return {
      label: '~ Iqama estimated',
      color: 'text-amber-600',
      title: 'Adhan time from mosque website, iqama time is estimated',
    };
  }
  return {
    label: '~ Estimated times',
    color: 'text-amber-600',
    title: 'Congregation time not confirmed — based on calculated prayer window',
  };
}

// Canadian IANA timezone IDs — everything else is treated as US (miles)
const CANADIAN_TIMEZONES = new Set([
  'America/Toronto', 'America/Vancouver', 'America/Edmonton', 'America/Winnipeg',
  'America/Halifax', 'America/St_Johns', 'America/Moncton', 'America/Regina',
  'America/Glace_Bay', 'America/Goose_Bay', 'America/Blanc-Sablon',
  'America/Nipigon', 'America/Thunder_Bay', 'America/Rainy_River',
  'America/Cambridge_Bay', 'America/Iqaluit', 'America/Rankin_Inlet',
  'America/Resolute', 'America/Creston', 'America/Dawson', 'America/Dawson_Creek',
  'America/Fort_Nelson', 'America/Inuvik', 'America/Whitehorse', 'America/Pangnirtung',
]);

const USE_METRIC = CANADIAN_TIMEZONES.has(Intl.DateTimeFormat().resolvedOptions().timeZone);

function distLabel(meters: number): string {
  if (USE_METRIC) {
    if (meters < 1000) return `${Math.round(meters)} m`;
    return `${(meters / 1000).toFixed(1)} km`;
  } else {
    const miles = meters / 1609.344;
    if (miles < 0.1) return `${Math.round(meters)} ft`.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    if (miles < 10) return `${miles.toFixed(1)} mi`;
    return `${Math.round(miles)} mi`;
  }
}

// ─── Prayer row ordering helpers ────────────────────────────────────────────

const ACTIVE_STATUSES = new Set([
  'can_catch_with_imam', 'can_catch_with_imam_in_progress',
  'can_pray_solo_at_mosque', 'pray_at_nearby_location',
]);

/** Parse "HH:MM" → minutes since midnight, or null. */
function hhmmToMin(t: string | null | undefined): number | null {
  if (!t) return null;
  const m = t.match(/^(\d{1,2}):(\d{2})/);
  if (!m) return null;
  return parseInt(m[1]) * 60 + parseInt(m[2]);
}

/**
 * Returns true if we are past the switch point for the active prayer —
 * meaning the NEXT prayer should be shown as primary (more urgent).
 *
 * Switch point = midpoint of [adhan_time, period_ends_at] for the active prayer,
 * computed dynamically from today's actual times (varies by season and location).
 * Exception: Isha uses midnight (00:00) instead of the geometric midpoint.
 */
function isPastSwitchPoint(active: { prayer: string; adhan_time: string | null; period_ends_at: string | null }): boolean {
  const adhan = hhmmToMin(active.adhan_time);
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();

  if (adhan === null) return false;

  // Isha: switch at midnight — "past midnight" means nowMin < adhan (we crossed midnight)
  if (active.prayer === 'isha') return nowMin < adhan;

  let periodEnd = hhmmToMin(active.period_ends_at);
  if (periodEnd === null) return false;
  if (periodEnd < adhan) periodEnd += 1440; // midnight wrap

  const switchPoint = (adhan + periodEnd) / 2;

  // Normalize nowMin: if before adhan, we're in the "next-day" portion → add 1440
  const nowNorm = nowMin >= adhan ? nowMin : nowMin + 1440;
  return nowNorm > switchPoint;
}

// ─── Mosque Card ────────────────────────────────────────────────────────────

function MosqueCard({ mosque }: { mosque: Mosque }) {
  const openSheet           = useStore((s) => s.openSheet);
  const setSelectedMosqueId = useStore((s) => s.setSelectedMosqueId);
  const prayedToday         = useStore((s) => s.prayedToday);
  const togglePrayed        = useStore((s) => s.togglePrayed);
  const travelMode          = useStore((s) => s.travelMode);
  const th                  = useTheme();
  const badge               = dataSourceBadge(mosque.prayers);

  const catchable = (mosque.catchable_prayers?.length
    ? mosque.catchable_prayers
    : mosque.next_catchable ? [mosque.next_catchable] : []);

  // Remove prayers the user already marked as prayed
  const visible = catchable.filter(p => !prayedToday.has(p.prayer));
  if (visible.length === 0) return null;

  // Separate into active (current prayer window) and upcoming
  const active   = visible.find(p => ACTIVE_STATUSES.has(p.status)) ?? null;
  const upcoming = visible.find(p => p.status === 'upcoming') ?? null;

  // Determine display order: show most actionable prayer first
  // If past the switch point for the active prayer, next prayer is more urgent → show it first
  const showNextFirst = active !== null && upcoming !== null && isPastSwitchPoint(active);
  const primary   = showNextFirst ? upcoming! : (active ?? upcoming!);
  const secondary = showNextFirst ? active    : upcoming;

  const cfg = STATUS_CONFIG[primary.status] ?? STATUS_CONFIG['upcoming'];

  function handleClick() {
    setSelectedMosqueId(mosque.id);
    openSheet({ type: 'mosque_detail', mosque });
  }

  return (
    <div
      className={`rounded-2xl border shadow-sm hover:shadow-md active:scale-[0.99] transition-all cursor-pointer overflow-hidden ${cfg.border}`}
      onClick={handleClick}
    >
      {/* Header */}
      <div className={`flex items-start justify-between gap-2 p-3 pb-2 ${cfg.bg}`}>
        <div className="min-w-0 flex-1">
          <p className="font-bold text-gray-900 text-sm leading-snug truncate">{mosque.name}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {distLabel(mosque.distance_meters)}
            {mosque.travel_time_minutes ? ` · ${mosque.travel_time_minutes} min` : ''}
          </p>
        </div>
        <img src={cfg.icon} alt="" className="w-10 h-10 flex-shrink-0 object-contain mt-0.5" />
      </div>

      {/* Primary row — bold, colored, with left accent border */}
      <div className={`px-3 py-2 border-l-4 ${cfg.bg} ${cfg.border}`}>
        <p className={`text-sm font-semibold ${cfg.text} leading-snug`}>{primary.message}</p>
        {primary.leave_by && (
          <p className={`text-xs mt-0.5 ${cfg.text} opacity-80`}>Leave by {fmtTime(primary.leave_by)}</p>
        )}
        {/* Inline "Prayed" button on the current (active) prayer row when it's primary */}
        {active && primary === active && ACTIVE_STATUSES.has(active.status) && (
          <button
            className="mt-1.5 text-xs font-medium px-2 py-0.5 rounded-full border border-gray-200 text-gray-500 bg-white hover:bg-gray-50 transition-colors"
            onClick={(e) => { e.stopPropagation(); togglePrayed(active.prayer); }}
          >
            ✓ Already prayed
          </button>
        )}
      </div>

      {/* Secondary row — muted, smaller, no left border */}
      {secondary && (
        <div className="px-3 py-1.5 bg-slate-50 flex items-center justify-between gap-2">
          <p className="text-xs text-slate-500">
            {secondary.status === 'upcoming'
              ? `${secondary.prayer.charAt(0).toUpperCase() + secondary.prayer.slice(1)} at ${fmtTime(secondary.adhan_time)}`
              : secondary.message}
          </p>
          {/* Inline "Prayed" button on the current prayer row when it's secondary */}
          {active && secondary === active && ACTIVE_STATUSES.has(active.status) && (
            <button
              className="text-xs font-medium px-2 py-0.5 rounded-full border border-green-400 text-green-700 bg-white hover:bg-green-50 transition-colors flex-shrink-0"
              onClick={(e) => { e.stopPropagation(); togglePrayed(active.prayer); }}
            >
              ✓ Prayed
            </button>
          )}
        </div>
      )}

      {/* Combination options (Musafir mode, no route) */}
      {travelMode && mosque.travel_combinations.length > 0 && (
        <div className={`px-3 pt-2 pb-3 border-t space-y-2 ${th.bgLight} ${th.border}`}>
          {mosque.travel_combinations.map((pair: TravelPairPlan) => {
            const taqdeem = pair.options.find((o: TravelOption) => o.option_type === 'combine_early');
            const takheer = pair.options.find((o: TravelOption) => o.option_type === 'combine_late');
            const takheerOnly = !taqdeem && !!takheer;
            return (
              <div key={pair.pair}>
                <p className={`text-xs font-semibold mb-1.5 ${th.text}`}>
                  ✈️ {pair.emoji} {pair.label} — Musafir
                </p>

                {/* Ta'kheer only: p1 time passed but NOT missed */}
                {takheerOnly && (
                  <div className="bg-white rounded-lg border border-blue-200 px-2.5 py-2 space-y-1">
                    <p className="text-xs font-semibold text-blue-800">{pair.label.split(' + ')[0]} is not missed ✓</p>
                    <p className="text-xs text-blue-700">{takheer!.description}</p>
                    <span className="inline-block text-xs bg-blue-50 text-blue-700 border border-blue-200 px-1.5 py-0.5 rounded-full">
                      Jam' Ta'kheer — Combine Late
                    </span>
                  </div>
                )}

                {/* Taqdeem — primary when both available or only Taqdeem */}
                {taqdeem && (
                  <div className={`bg-white rounded-lg border border-green-200 px-2.5 py-2 space-y-1 ${takheer ? 'mb-1.5' : ''}`}>
                    <p className="text-xs text-green-800">{taqdeem.description}</p>
                    <span className="inline-block text-xs bg-green-50 text-green-700 border border-green-200 px-1.5 py-0.5 rounded-full">
                      Jam' Taqdeem — Combine Early
                    </span>
                  </div>
                )}

                {/* Ta'kheer as secondary when Taqdeem also available */}
                {taqdeem && takheer && (
                  <div className="bg-white rounded-lg border border-blue-100 px-2.5 py-2 space-y-1">
                    <p className="text-xs text-blue-700">{takheer.description}</p>
                    <span className="inline-block text-xs bg-blue-50 text-blue-600 border border-blue-200 px-1.5 py-0.5 rounded-full">
                      Jam' Ta'kheer — Combine Late
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Source badge */}
      <div className={`px-3 py-1.5 border-t ${cfg.border} bg-white`}>
        <p className={`text-xs ${badge.color}`} title={badge.title}>{badge.label}</p>
      </div>
    </div>
  );
}

// ─── Prayer Spot Card ────────────────────────────────────────────────────────

function SpotCard({ spot }: { spot: PrayerSpot }) {
  const openSheet       = useStore((s) => s.openSheet);
  const confirmedSpots  = useStore((s) => s.confirmedSpots);
  const addConfirmedSpot = useStore((s) => s.addConfirmedSpot);
  const th              = useTheme();
  const [confirming, setConfirming] = useState(false);

  const isConfirmed = confirmedSpots.has(spot.id);

  const handleConfirm = async (e: React.MouseEvent) => {
    e.stopPropagation(); // don't open the detail sheet
    if (isConfirmed || confirming) return;
    setConfirming(true);
    try {
      await apiService.verifySpot(spot.id, {
        session_id: SESSION_ID,
        is_positive: true,
        attributes: {},
      });
      addConfirmedSpot(spot.id);
    } catch {
      // 409 = already voted — mark confirmed anyway so the button updates
      addConfirmedSpot(spot.id);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div
      className={`rounded-xl border bg-white p-3 cursor-pointer hover:shadow-md active:scale-[0.99] transition-all ${th.border}`}
      onClick={() => openSheet({ type: 'spot_detail', spot })}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold text-gray-900 text-sm leading-tight truncate">{spot.name}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {SPOT_TYPE_LABELS[spot.spot_type] ?? spot.spot_type} · {distLabel(spot.distance_meters)}
          </p>
        </div>
        <span className={`text-xs px-1.5 py-0.5 rounded-full flex-shrink-0 ${th.bgLight} ${th.text}`}>
          {spot.verification_label}
        </span>
      </div>
      <div className="flex items-center justify-between mt-2 gap-2">
        <div className="flex gap-2 flex-wrap">
          {spot.has_wudu_facilities === true && <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full">Wudu</span>}
          {spot.is_indoor === true && <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full">Indoor</span>}
          {spot.gender_access === 'men_only' && <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full">Men only</span>}
          {spot.gender_access === 'women_only' && <span className="text-xs bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full">Women only</span>}
        </div>
        <button
          onClick={handleConfirm}
          disabled={isConfirmed || confirming}
          className={`flex-shrink-0 text-xs px-2.5 py-1 rounded-full font-medium border transition-colors ${
            isConfirmed
              ? `${th.bgLight} ${th.border} ${th.text} cursor-default`
              : `bg-white ${th.borderStrong} ${th.text} ${th.bgHoverLight}`
          }`}
        >
          {isConfirmed ? '✓ Confirmed' : confirming ? '…' : '✓ I prayed here'}
        </button>
      </div>
    </div>
  );
}

// ─── Mosque Detail Sheet ────────────────────────────────────────────────────

function MosqueDetailSheet({ mosque }: { mosque: Mosque }) {
  const closeSheet    = useStore((s) => s.closeSheet);
  const prayedToday   = useStore((s) => s.prayedToday);
  const togglePrayed  = useStore((s) => s.togglePrayed);
  const th            = useTheme();

  const nc = mosque.next_catchable;
  const isMissed    = nc?.status === 'missed_make_up';
  const isUpcoming  = nc?.status === 'upcoming';
  const isNcPrayed  = nc ? prayedToday.has(nc.prayer) : false;

  // When nc is already prayed, find the next future prayer from the table
  const nowMin = new Date().getHours() * 60 + new Date().getMinutes();
  const nextFromTable = isNcPrayed
    ? (mosque.prayers ?? []).find(p => {
        if (!p.adhan_time) return false;
        const [h, m] = p.adhan_time.split(':').map(Number);
        return h * 60 + m > nowMin;
      })
    : null;

  const badge = dataSourceBadge(mosque.prayers);

  // Badge config: upcoming gets theme color (distinct from gray missed)
  const cfg = nc && !isNcPrayed
    ? (isUpcoming
        ? { bg: th.bgLight, border: th.border, text: th.textDark, icon: STATUS_CONFIG['upcoming'].icon }
        : (STATUS_CONFIG[nc.status] ?? STATUS_CONFIG['upcoming']))
    : null;

  return (
    <div>
      <div className="flex items-start justify-between mb-3">
        <h2 className="text-lg font-bold text-gray-900 pr-4 leading-tight">{mosque.name}</h2>
        <button onClick={closeSheet} className="w-9 h-9 flex items-center justify-center rounded-full bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700 text-lg flex-shrink-0 transition-colors">✕</button>
      </div>

      {mosque.location.address && (
        <p className="text-sm text-gray-500 mb-3">{mosque.location.address}</p>
      )}

      {/* Status badge — hidden when nc prayer is already marked as prayed */}
      {nc && cfg && (
        <div className={`rounded-lg border px-3 py-2.5 mb-4 ${cfg.bg} ${cfg.border}`}>
          <div className={`flex items-center gap-2 text-sm font-semibold ${cfg.text}`}>
            <img src={cfg.icon} alt="" className="w-10 h-10 object-contain flex-shrink-0" />
            <span className="capitalize">{isUpcoming ? `Next: ${nc.prayer}` : nc.status_label}</span>
          </div>

          {/* Upcoming: structured time display */}
          {isUpcoming ? (
            <div className={`mt-1.5 space-y-0.5 text-sm ${cfg.text}`}>
              <p>Azan at <span className="font-semibold">{fmtTime(nc.adhan_time)}</span>
                {nc.iqama_time && <span className="text-xs font-normal opacity-75"> · Iqama {fmtTime(nc.iqama_time)}</span>}
              </p>
              {nc.leave_by && (
                <p>Leave by <span className="font-semibold">{fmtTime(nc.leave_by)}</span> to pray with Imam</p>
              )}
            </div>
          ) : (
            <>
              <p className={`text-sm mt-0.5 ${cfg.text}`}>{nc.message}</p>
              {nc.iqama_time && !isMissed && (
                <p className="text-xs text-gray-500 mt-1">Iqama: {fmtTime(nc.iqama_time)}</p>
              )}
              {nc.leave_by && !isMissed && (
                <p className="text-xs text-gray-500">Leave by: {fmtTime(nc.leave_by)}</p>
              )}
            </>
          )}

          {/* Mark as prayed button — only for missed prayers */}
          {isMissed && (
            <button
              onClick={() => togglePrayed(nc.prayer)}
              className="mt-2 text-xs px-3 py-1 rounded-full border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 active:bg-gray-100"
            >
              ✓ I already prayed {nc.prayer.charAt(0).toUpperCase() + nc.prayer.slice(1)}
            </button>
          )}
        </div>
      )}

      {/* Show next prayer when nc is already marked as prayed */}
      {isNcPrayed && nextFromTable && (
        <div className={`rounded-lg border px-3 py-2.5 mb-4 ${th.border} ${th.bgLight}`}>
          <p className={`text-sm font-semibold capitalize ${th.textDark}`}>Next: {nextFromTable.prayer}</p>
          <div className={`mt-1 space-y-0.5 text-sm ${th.text}`}>
            <p>Azan at <span className="font-semibold">{fmtTime(nextFromTable.adhan_time)}</span>
              {nextFromTable.iqama_time && <span className="text-xs font-normal opacity-75"> · Iqama {fmtTime(nextFromTable.iqama_time)}</span>}
            </p>
            {nextFromTable.iqama_time && mosque.travel_time_minutes && (() => {
              const [h, m] = nextFromTable.iqama_time!.split(':').map(Number);
              const leaveMin = h * 60 + m - mosque.travel_time_minutes;
              const lh = Math.floor(((leaveMin % 1440) + 1440) % 1440 / 60);
              const lm = ((leaveMin % 1440) + 1440) % 1440 % 60;
              const suffix = lh >= 12 ? 'PM' : 'AM';
              const fh = lh > 12 ? lh - 12 : lh === 0 ? 12 : lh;
              return <p>Leave by <span className="font-semibold">{fh}:{String(lm).padStart(2,'0')} {suffix}</span> to pray with Imam</p>;
            })()}
          </div>
        </div>
      )}

      {/* Prayer times table */}
      {mosque.prayers.length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Today's Prayer Times</h3>
          <div className="rounded-lg border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50">
                  <th className="text-left px-3 py-2 text-gray-600 font-medium">Prayer</th>
                  <th className="text-right px-3 py-2 text-gray-600 font-medium">Adhan</th>
                  <th className="text-right px-3 py-2 text-gray-600 font-medium">Iqama</th>
                </tr>
              </thead>
              <tbody>
                {mosque.prayers.map((p: PrayerTime, i) => (
                  <React.Fragment key={i}>
                    <tr className="border-t border-gray-100">
                      <td className="px-3 py-2 font-medium text-gray-800 capitalize">{p.prayer}</td>
                      <td className="px-3 py-2 text-right text-gray-600">{fmtTime(p.adhan_time)}</td>
                      <td className="px-3 py-2 text-right text-gray-700 font-medium">{fmtTime(p.iqama_time)}</td>
                    </tr>
                    {/* Shorooq (sunrise) row after Fajr */}
                    {p.prayer === 'fajr' && mosque.sunrise && (
                      <tr className="border-t border-gray-100 bg-amber-50">
                        <td className="px-3 py-2 text-amber-700 font-medium">Shorooq</td>
                        <td className="px-3 py-2 text-right text-amber-600">{fmtTime(mosque.sunrise)}</td>
                        <td className="px-3 py-2 text-right text-gray-400 text-xs italic">Fajr ends</td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Friday Jumu'ah sessions */}
      {mosque.jumuah_sessions.length > 0 && (
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Friday Jumu'ah</h3>
          <div className="space-y-2">
            {mosque.jumuah_sessions.map((s: JumuahSession) => (
              <div key={s.session_number} className={`rounded-lg border px-3 py-2 ${th.bgLight} ${th.border}`}>
                <div className="flex items-center justify-between">
                  <span className={`text-sm font-medium ${th.textDark}`}>
                    {mosque.jumuah_sessions.length > 1 ? `Session ${s.session_number}` : 'Jumu\'ah Prayer'}
                  </span>
                  <div className={`text-right text-sm ${th.textDark}`}>
                    {s.khutba_start && <span>Khutba {fmtTime(s.khutba_start)}</span>}
                    {s.khutba_start && s.prayer_start && <span className="mx-1">·</span>}
                    {s.prayer_start && <span className="font-medium">Prayer {fmtTime(s.prayer_start)}</span>}
                  </div>
                </div>
                {s.imam_name && (
                  <p className={`text-xs ${th.text} mt-0.5`}>{s.imam_name}</p>
                )}
                {s.language && s.language.toLowerCase() !== 'english' && (
                  <p className={`text-xs ${th.text} mt-0.5`}>Language: {s.language}</p>
                )}
                {s.special_notes && (
                  <p className="text-xs text-gray-600 mt-1 italic">{s.special_notes}</p>
                )}
                {s.booking_required && (
                  <p className="text-xs text-amber-700 mt-1">
                    Registration required
                    {s.booking_url && (
                      <a href={s.booking_url} target="_blank" rel="noopener noreferrer" className="ml-1 underline">
                        Register
                      </a>
                    )}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Data source */}
      <p className={`text-xs mb-4 ${badge.color}`} title={badge.title}>{badge.label}</p>

      {/* Action buttons */}
      <div className="flex gap-2">
        <a
          href={`https://www.google.com/maps/dir/?api=1&destination=${mosque.location.latitude},${mosque.location.longitude}`}
          target="_blank"
          rel="noopener noreferrer"
          className={`flex-1 ${th.bg} ${th.bgHover} text-white text-xs py-2 px-2 rounded-lg text-center font-medium`}
        >
          Directions
        </a>
        {mosque.phone && (
          <a
            href={`tel:${mosque.phone}`}
            className="flex-1 bg-slate-700 hover:bg-slate-800 text-white text-xs py-2 px-2 rounded-lg text-center font-medium"
          >
            Call
          </a>
        )}
        {mosque.website && (
          <a
            href={mosque.website}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 bg-slate-700 hover:bg-slate-800 text-white text-xs py-2 px-2 rounded-lg text-center font-medium"
          >
            Website
          </a>
        )}
      </div>
    </div>
  );
}

// ─── Spot Detail Sheet ───────────────────────────────────────────────────────

function SpotDetailSheet({ spot }: { spot: PrayerSpot }) {
  const closeSheet = useStore((s) => s.closeSheet);
  const th         = useTheme();
  const [submitting, setSubmitting] = useState(false);
  const [voted, setVoted]           = useState<boolean | null>(null);

  const handleVerify = async (isPositive: boolean) => {
    if (submitting) return;
    setSubmitting(true);
    try {
      await apiService.verifySpot(spot.id, {
        session_id: SESSION_ID,
        is_positive: isPositive,
        attributes: {},
      });
      setVoted(isPositive);
    } catch (e) {
      // silently ignore duplicate vote errors
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div className="flex items-start justify-between mb-3">
        <h2 className="text-lg font-bold text-gray-900 pr-4 leading-tight">{spot.name}</h2>
        <button onClick={closeSheet} className="w-9 h-9 flex items-center justify-center rounded-full bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700 text-lg flex-shrink-0 transition-colors">✕</button>
      </div>

      <p className="text-sm text-gray-500 mb-3">
        {SPOT_TYPE_LABELS[spot.spot_type] ?? spot.spot_type}
        {spot.location.address ? ` · ${spot.location.address}` : ''}
      </p>

      <div className="flex flex-wrap gap-2 mb-3">
        {spot.has_wudu_facilities === true && (
          <span className={`text-xs px-2 py-1 rounded-full border ${th.bgLight} ${th.border} ${th.text}`}>Wudu facilities</span>
        )}
        {spot.is_indoor === true && (
          <span className="bg-slate-100 border border-slate-200 text-slate-600 text-xs px-2 py-1 rounded-full">Indoor</span>
        )}
        {spot.gender_access === 'men_only' && (
          <span className="bg-slate-100 border border-slate-200 text-slate-600 text-xs px-2 py-1 rounded-full">Men only</span>
        )}
        {spot.gender_access === 'women_only' && (
          <span className="bg-slate-100 border border-slate-200 text-slate-600 text-xs px-2 py-1 rounded-full">Women only</span>
        )}
        {spot.operating_hours && (
          <span className="bg-slate-100 border border-slate-200 text-slate-600 text-xs px-2 py-1 rounded-full">{spot.operating_hours}</span>
        )}
      </div>

      {spot.notes && (
        <p className="text-sm text-gray-600 mb-3 italic">"{spot.notes}"</p>
      )}

      <div className="bg-gray-50 rounded-lg p-3 mb-4 text-sm text-gray-600">
        <span className="font-medium">{spot.verification_label}</span>
        {spot.last_verified_at && (
          <span className="ml-2 text-xs text-gray-400">
            · last verified {new Date(spot.last_verified_at).toLocaleDateString()}
          </span>
        )}
      </div>

      {voted !== null ? (
        <p className="text-center text-sm text-gray-600 py-2">
          {voted ? '👍 Thanks for confirming!' : '👎 Thanks for the feedback!'}
        </p>
      ) : (
        <div>
          <p className="text-xs text-gray-500 mb-2 text-center">Has this place a prayer area?</p>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => handleVerify(true)}
              disabled={submitting}
              className={`${th.bg} ${th.bgHover} text-white py-2 rounded-lg text-sm font-medium disabled:opacity-50`}
            >
              Yes, confirm
            </button>
            <button
              onClick={() => handleVerify(false)}
              disabled={submitting}
              className="bg-slate-100 text-slate-600 border border-slate-200 py-2 rounded-lg text-sm font-medium hover:bg-slate-200 disabled:opacity-50"
            >
              No longer valid
            </button>
          </div>
        </div>
      )}

      <a
        href={`https://www.google.com/maps/dir/?api=1&destination=${spot.location.latitude},${spot.location.longitude}`}
        target="_blank"
        rel="noopener noreferrer"
        className={`mt-3 block ${th.bg} ${th.bgHover} text-white text-sm py-2 rounded-lg text-center font-medium`}
      >
        Get Directions
      </a>
    </div>
  );
}

// ─── Spot Submit Sheet ───────────────────────────────────────────────────────

function SpotSubmitSheet() {
  const closeSheet   = useStore((s) => s.closeSheet);
  const th           = useTheme();
  const userLocation = useStore((s) => s.userLocation);

  // Resolved lat/lng for the spot (starts as GPS, can be overridden by address search)
  const [spotLat, setSpotLat] = useState<number | null>(userLocation?.latitude ?? null);
  const [spotLng, setSpotLng] = useState<number | null>(userLocation?.longitude ?? null);
  const [locationQuery, setLocationQuery] = useState('');
  const [locationSugg, setLocationSugg]   = useState<GeocodeSuggestion[]>([]);
  const [locationLoading, setLocationLoading] = useState(false);
  const locationDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [form, setForm] = useState<Partial<SpotSubmitRequest>>({
    spot_type: 'prayer_room',
    gender_access: 'all',
    is_indoor: true,
    has_wudu_facilities: null,
  });
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone]             = useState(false);
  const [error, setError]           = useState<string | null>(null);

  // Pre-fill address input with reverse-geocoded GPS address on open
  useEffect(() => {
    if (!userLocation) return;
    setSpotLat(userLocation.latitude);
    setSpotLng(userLocation.longitude);
    apiService.reverseGeocode(userLocation.latitude, userLocation.longitude)
      .then((lbl) => { if (lbl) setLocationQuery(lbl); })
      .catch(() => {});
  }, [userLocation]); // eslint-disable-line react-hooks/exhaustive-deps

  function onLocationInput(val: string) {
    setLocationQuery(val);
    if (locationDebounce.current) clearTimeout(locationDebounce.current);
    if (val.length < 3) { setLocationSugg([]); return; }
    locationDebounce.current = setTimeout(async () => {
      setLocationLoading(true);
      try { setLocationSugg(await apiService.geocodeDestination(val, userLocation?.latitude, userLocation?.longitude)); }
      catch { setLocationSugg([]); }
      finally { setLocationLoading(false); }
    }, 400);
  }

  const set = (k: keyof SpotSubmitRequest, v: unknown) =>
    setForm((f) => ({ ...f, [k]: v }));

  const handleSubmit = async () => {
    if (!form.name?.trim() || spotLat === null || spotLng === null) return;
    setSubmitting(true);
    setError(null);
    try {
      await apiService.submitSpot({
        name: form.name!,
        spot_type: form.spot_type!,
        latitude: spotLat,
        longitude: spotLng,
        address: form.address,
        has_wudu_facilities: form.has_wudu_facilities ?? null,
        gender_access: form.gender_access,
        is_indoor: form.is_indoor ?? null,
        operating_hours: form.operating_hours,
        notes: form.notes,
        website: form.website,
        session_id: SESSION_ID,
      });
      setDone(true);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to submit. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="text-center py-6">
        <img src="/icons/icon_mosque_nav.png" alt="" className="w-16 h-16 object-contain mx-auto mb-3" />
        <h3 className="text-lg font-bold text-gray-900 mb-2">Spot Submitted!</h3>
        <p className="text-sm text-gray-600 mb-4">
          Your spot is pending community verification. Once 3 users confirm it, it will become active.
        </p>
        <button onClick={closeSheet} className={`${th.bg} text-white px-6 py-2 rounded-lg font-medium`}>
          Done
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold text-gray-900">Add Prayer Spot</h2>
        <button onClick={closeSheet} className="w-9 h-9 flex items-center justify-center rounded-full bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700 text-lg flex-shrink-0 transition-colors">✕</button>
      </div>

      <div className="space-y-3">
        {/* Name */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Name *</label>
          <input
            type="text"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-current"
            placeholder="e.g. Whole Foods Prayer Room"
            value={form.name ?? ''}
            onChange={(e) => set('name', e.target.value)}
          />
        </div>

        {/* Location — GPS or address search */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Location *</label>
          <div className="relative">
            <input
              type="text"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-current"
              placeholder="Search for an address…"
              value={locationQuery}
              onChange={(e) => onLocationInput(e.target.value)}
            />
            {locationLoading && (
              <span className="absolute right-2.5 top-2.5 text-gray-400 text-xs">…</span>
            )}
            {locationSugg.length > 0 && (
              <div className="absolute z-10 w-full bg-white border border-gray-200 rounded-lg shadow-lg mt-1 max-h-48 overflow-y-auto">
                {locationSugg.map((s, i) => (
                  <button
                    key={i}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 border-b border-gray-100 last:border-0"
                    onClick={() => {
                      setSpotLat(s.lat);
                      setSpotLng(s.lng);
                      setLocationQuery(s.place_name);
                      setLocationSugg([]);
                    }}
                  >
                    📍 {s.place_name}
                  </button>
                ))}
              </div>
            )}
          </div>
          {spotLat === null && (
            <p className="text-xs text-amber-600 mt-1">Search for an address or allow location access to place this spot.</p>
          )}
        </div>

        {/* Type */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Type</label>
          <select
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-current"
            value={form.spot_type}
            onChange={(e) => set('spot_type', e.target.value)}
          >
            {Object.entries(SPOT_TYPE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>

        {/* Facilities */}
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Wudu?</label>
            <select
              className="w-full border border-gray-300 rounded-lg px-2 py-2 text-sm focus:outline-none"
              value={form.has_wudu_facilities === null ? 'unknown' : form.has_wudu_facilities ? 'yes' : 'no'}
              onChange={(e) => set('has_wudu_facilities', e.target.value === 'yes' ? true : e.target.value === 'no' ? false : null)}
            >
              <option value="unknown">Unknown</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Indoor?</label>
            <select
              className="w-full border border-gray-300 rounded-lg px-2 py-2 text-sm focus:outline-none"
              value={form.is_indoor === null ? 'unknown' : form.is_indoor ? 'yes' : 'no'}
              onChange={(e) => set('is_indoor', e.target.value === 'yes' ? true : e.target.value === 'no' ? false : null)}
            >
              <option value="unknown">Unknown</option>
              <option value="yes">Yes</option>
              <option value="no">No (outdoor)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Access</label>
            <select
              className="w-full border border-gray-300 rounded-lg px-2 py-2 text-sm focus:outline-none"
              value={form.gender_access ?? 'all'}
              onChange={(e) => set('gender_access', e.target.value)}
            >
              <option value="all">All</option>
              <option value="men_only">Men</option>
              <option value="women_only">Women</option>
            </select>
          </div>
        </div>

        {/* Hours */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Hours (optional)</label>
          <input
            type="text"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-current"
            placeholder="e.g. Mon–Fri 9am–6pm"
            value={form.operating_hours ?? ''}
            onChange={(e) => set('operating_hours', e.target.value)}
          />
        </div>

        {/* Website */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Website (optional)</label>
          <input
            type="url"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-current"
            placeholder="https://..."
            value={form.website ?? ''}
            onChange={(e) => set('website', e.target.value)}
          />
        </div>

        {/* Notes */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Notes (optional)</label>
          <textarea
            rows={2}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-current resize-none"
            placeholder="Any helpful details for other musallees..."
            value={form.notes ?? ''}
            onChange={(e) => set('notes', e.target.value)}
          />
        </div>

        {error && <p className="text-xs text-red-600">{error}</p>}

        <button
          onClick={handleSubmit}
          disabled={submitting || !form.name?.trim() || spotLat === null}
          className={`w-full ${th.bg} ${th.bgHover} text-white py-2.5 rounded-lg font-medium text-sm disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          {submitting ? 'Submitting…' : 'Submit Spot'}
        </button>
      </div>
    </div>
  );
}

// ─── Settings Sheet ──────────────────────────────────────────────────────────

function SettingsSheet() {
  const closeSheet          = useStore((s) => s.closeSheet);
  const th                  = useTheme();
  const radiusKm            = useStore((s) => s.radiusKm);
  const setRadiusKm         = useStore((s) => s.setRadiusKm);
  const denominationFilter  = useStore((s) => s.denominationFilter);
  const setDenominationFilter = useStore((s) => s.setDenominationFilter);
  const showSpots           = useStore((s) => s.showSpots);
  const setShowSpots        = useStore((s) => s.setShowSpots);
  const travelMode          = useStore((s) => s.travelMode);
  const setTravelMode       = useStore((s) => s.setTravelMode);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold text-gray-900">Settings</h2>
        <button onClick={closeSheet} className="w-9 h-9 flex items-center justify-center rounded-full bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700 text-lg flex-shrink-0 transition-colors">✕</button>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Search radius: <span className={`${th.text} font-semibold`}>
              {USE_METRIC ? `${radiusKm} km` : `${Math.round(radiusKm / 1.60934)} mi`}
            </span>
          </label>
          <input
            type="range" min={1} max={50} step={1}
            value={radiusKm}
            onChange={(e) => setRadiusKm(Number(e.target.value))}
            className="w-full"
            style={{ accentColor: th.hex }}
          />
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            {USE_METRIC
              ? <><span>1 km</span><span>50 km</span></>
              : <><span>1 mi</span><span>31 mi</span></>}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Denomination</label>
          <div className="grid grid-cols-2 gap-2">
            {(['all', 'sunni', 'shia', 'ismaili'] as const).map((d) => (
              <button
                key={d}
                onClick={() => setDenominationFilter(d)}
                className={`py-2 rounded-lg text-sm font-medium border transition-colors ${
                  denominationFilter === d
                    ? `${th.bg} text-white ${th.borderStrong}`
                    : `bg-white text-gray-700 border-gray-300 ${th.borderHover}`
                }`}
              >
                {d.charAt(0).toUpperCase() + d.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Travel mode */}
        <div className="flex items-center justify-between">
          <div>
            <p className={`text-sm font-medium ${travelMode ? th.text : 'text-gray-700'}`}>
              {travelMode ? '✈️ Musafir mode' : '🏠 Muqeem mode'}
            </p>
            <p className="text-xs text-gray-500">
              {travelMode
                ? 'You are a traveler (Musafir / Safar). Prayer combining options (Dhuhr+Asr, Maghrib+Isha) are shown on mosque cards.'
                : 'You are a resident (Muqeem). Tap to activate Musafir mode when you are away from home.'}
            </p>
          </div>
          <button
            onClick={() => setTravelMode(!travelMode)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors flex-shrink-0 ml-3 ${
              travelMode ? th.bg : 'bg-gray-300'
            }`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              travelMode ? 'translate-x-6' : 'translate-x-1'
            }`} />
          </button>
        </div>

        {/* Show spots */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-700">Show prayer spots</p>
            <p className="text-xs text-gray-500">Community-added non-mosque locations</p>
          </div>
          <button
            onClick={() => setShowSpots(!showSpots)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors flex-shrink-0 ml-3 ${
              showSpots ? th.bg : 'bg-gray-300'
            }`}
          >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              showSpots ? 'translate-x-6' : 'translate-x-1'
            }`} />
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Bottom Sheet ────────────────────────────────────────────────────────────

function BottomSheet() {
  const sheet = useStore((s) => s.bottomSheet);
  if (!sheet) return null;

  return (
    <>
      {/* Backdrop — absorb all touch/pointer events so the map underneath doesn't pan */}
      <div
        className="fixed inset-0 bg-black bg-opacity-30 z-40"
        onClick={useStore.getState().closeSheet}
        onTouchMove={(e) => e.preventDefault()}
      />
      {/* Sheet — stop propagation so scroll inside the sheet doesn't reach the map */}
      <div
        className="fixed bottom-0 left-0 right-0 bg-white rounded-t-2xl shadow-2xl z-50 max-h-[85vh] overflow-y-auto"
        onTouchMove={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 bg-gray-300 rounded-full" />
        </div>
        <div className="px-4 pb-8 pt-1">
          {sheet.type === 'mosque_detail' && <MosqueDetailSheet mosque={sheet.mosque} />}
          {sheet.type === 'spot_detail'   && <SpotDetailSheet   spot={sheet.spot} />}
          {sheet.type === 'spot_submit'   && <SpotSubmitSheet />}
          {sheet.type === 'settings'      && <SettingsSheet />}
        </div>
      </div>
    </>
  );
}

// ─── Global Prayed Banner ────────────────────────────────────────────────────

// Musafir pair mapping: if one of these prayers is active, show the pair instead
const MUSAFIR_PAIR_MAP: Record<string, { p1: string; p2: string; label: string }> = {
  isha:    { p1: 'maghrib', p2: 'isha', label: 'Maghrib + Isha' },
  maghrib: { p1: 'maghrib', p2: 'isha', label: 'Maghrib + Isha' },
  asr:     { p1: 'dhuhr',   p2: 'asr',  label: 'Dhuhr + Asr'   },
  dhuhr:   { p1: 'dhuhr',   p2: 'asr',  label: 'Dhuhr + Asr'   },
};

function PrayedBanner({ mosques }: { mosques: Mosque[] }) {
  const prayedToday      = useStore((s) => s.prayedToday);
  const togglePrayed     = useStore((s) => s.togglePrayed);
  const togglePrayedPair = useStore((s) => s.togglePrayedPair);
  const travelMode       = useStore((s) => s.travelMode);

  // Collect active (non-upcoming) prayers across all mosques
  const activePrayers = new Set<string>();
  for (const mosque of mosques) {
    const catchable = mosque.catchable_prayers ?? (mosque.next_catchable ? [mosque.next_catchable] : []);
    for (const p of catchable) {
      if (ACTIVE_STATUSES.has(p.status)) activePrayers.add(p.prayer);
    }
  }

  if (activePrayers.size === 0) return null;

  // In Musafir mode, group Dhuhr+Asr and Maghrib+Isha into pairs
  type BannerItem =
    | { kind: 'solo';  prayer: string }
    | { kind: 'pair';  p1: string; p2: string; label: string };

  const items: BannerItem[] = [];
  const seen = new Set<string>();

  for (const prayer of Array.from(activePrayers)) {
    if (seen.has(prayer)) continue;
    if (travelMode && MUSAFIR_PAIR_MAP[prayer]) {
      const { p1, p2, label } = MUSAFIR_PAIR_MAP[prayer];
      // Only show the pair if neither p1 nor p2 has been individually prayed
      if (!prayedToday.has(p1) && !prayedToday.has(p2)) {
        items.push({ kind: 'pair', p1, p2, label });
        seen.add(p1); seen.add(p2);
      }
      // If one of the pair is already prayed, fall through to individual handling
    } else {
      items.push({ kind: 'solo', prayer });
      seen.add(prayer);
    }
  }

  return (
    <div className="space-y-1.5">
      {items.map((item) => {
        if (item.kind === 'pair') {
          const prayed = prayedToday.has(item.p1) && prayedToday.has(item.p2);
          return (
            <div
              key={item.label}
              className={`flex items-center justify-between rounded-xl px-3 py-2 border text-sm ${
                prayed ? 'bg-green-50 border-green-200 text-green-800' : 'bg-white border-gray-200 text-gray-700'
              }`}
            >
              <span className="flex items-center gap-1.5">
                {prayed && <img src="/icons/icon_prayed.png" alt="" className="w-7 h-7 object-contain" />}
                {prayed
                  ? `Already prayed ${item.label} today`
                  : `${item.label} — did you already pray both?`}
              </span>
              <button
                onClick={() => togglePrayedPair(item.p1, item.p2)}
                className={`ml-3 text-xs font-medium px-2 py-1 rounded-full border transition-colors ${
                  prayed
                    ? 'border-green-300 text-green-700 hover:bg-green-100'
                    : 'bg-green-600 border-green-600 text-white hover:bg-green-700'
                }`}
              >
                {prayed ? 'Undo' : 'Yes, I prayed'}
              </button>
            </div>
          );
        }
        const prayed = prayedToday.has(item.prayer);
        return (
          <div
            key={item.prayer}
            className={`flex items-center justify-between rounded-xl px-3 py-2 border text-sm ${
              prayed ? 'bg-green-50 border-green-200 text-green-800' : 'bg-white border-gray-200 text-gray-700'
            }`}
          >
            <span className="flex items-center gap-1.5">
              {prayed && <img src="/icons/icon_prayed.png" alt="" className="w-7 h-7 object-contain" />}
              {prayed
                ? `Already prayed ${item.prayer.charAt(0).toUpperCase() + item.prayer.slice(1)} today`
                : `${item.prayer.charAt(0).toUpperCase() + item.prayer.slice(1)} time — did you already pray?`}
            </span>
            <button
              onClick={() => togglePrayed(item.prayer)}
              className={`ml-3 text-xs font-medium px-2 py-1 rounded-full border transition-colors ${
                prayed
                  ? 'border-green-300 text-green-700 hover:bg-green-100'
                  : 'bg-green-600 border-green-600 text-white hover:bg-green-700'
              }`}
            >
              {prayed ? 'Undo' : 'Yes, I prayed'}
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ─── Last Resort Card ────────────────────────────────────────────────────────

function LastResortCard() {
  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
      <p className="text-sm font-semibold text-gray-700 mb-1">🚗 No nearby spots?</p>
      <p className="text-xs text-gray-500">
        Look for a quiet corner in a parking lot, a gas station, or any clean outdoor area.
        Face the qibla and make tayammum if water isn't available.
      </p>
    </div>
  );
}

// ─── Destination Input ───────────────────────────────────────────────────────

function GeoInput({
  placeholder, icon, value, onChange, suggestions, onSelect, loading, onClear,
}: {
  placeholder: string; icon: string; value: string;
  onChange: (v: string) => void;
  suggestions: GeocodeSuggestion[]; onSelect: (s: GeocodeSuggestion) => void;
  loading: boolean;
  onClear?: () => void;
}) {
  const th = useTheme();
  return (
    <div className="relative">
      <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-2.5 py-2">
        <span className="text-sm">{icon}</span>
        <input
          type="text"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1 outline-none bg-transparent text-gray-800 placeholder-gray-400 min-w-0"
          style={{ fontSize: 16 }}
        />
        {loading && <span className="text-xs text-gray-300">…</span>}
        {onClear && !loading && (
          <button
            onClick={onClear}
            className="flex-shrink-0 w-5 h-5 flex items-center justify-center rounded-full bg-gray-200 hover:bg-gray-300 text-gray-500 text-xs leading-none"
            title="Clear — use current location"
          >
            ×
          </button>
        )}
      </div>
      {suggestions.length > 0 && (
        <div className="absolute z-50 top-full left-0 right-0 mt-0.5 bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden">
          {suggestions.map((s, i) => (
            <button key={i} onClick={() => onSelect(s)}
              className={`w-full text-left px-3 py-2 text-xs text-gray-700 border-b border-gray-100 last:border-0 truncate ${th.bgHoverLight}`}>
              <span className="text-gray-400 mr-1">📍</span>{s.place_name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Waypoint row state (local — not persisted between form open/close)
interface WaypointRow {
  dest: TravelDestination | null;
  query: string;
  sugg: GeocodeSuggestion[];
  loading: boolean;
}

function DestinationInput() {
  const th              = useTheme();
  const userLocation    = useStore((s) => s.userLocation);
  const travelDestination = useStore((s) => s.travelDestination);
  const setTravelDestination = useStore((s) => s.setTravelDestination);
  const travelOrigin    = useStore((s) => s.travelOrigin);
  const setTravelOrigin = useStore((s) => s.setTravelOrigin);
  const travelDepartureTime = useStore((s) => s.travelDepartureTime);
  const setTravelDepartureTime = useStore((s) => s.setTravelDepartureTime);
  const travelPlan      = useStore((s) => s.travelPlan);
  const setTravelPlan        = useStore((s) => s.setTravelPlan);
  const travelPlanLoading    = useStore((s) => s.travelPlanLoading);
  const setTravelPlanLoading = useStore((s) => s.setTravelPlanLoading);
  const travelModeStore = useStore((s) => s.travelMode);
  const prayedToday     = useStore((s) => s.prayedToday);

  const [destQuery, setDestQuery]   = useState(travelDestination?.place_name ?? '');
  const [destSugg, setDestSugg]     = useState<GeocodeSuggestion[]>([]);
  const [destLoading, setDestLoading] = useState(false);
  const [originQuery, setOriginQuery] = useState(travelOrigin?.place_name ?? '');
  const [originSugg, setOriginSugg]  = useState<GeocodeSuggestion[]>([]);
  const [originLoading, setOriginLoading] = useState(false);
  // Trip mode always follows global Muqeem/Musafir toggle — no per-trip override
  const tripMode = travelModeStore ? 'travel' : 'driving';

  // Intermediate waypoint rows (0–4 stops between origin and destination)
  const [waypointRows, setWaypointRows] = useState<WaypointRow[]>([]);
  const wpDebounces = useRef<Array<ReturnType<typeof setTimeout> | null>>([]);

  // Whether the trip planner form is expanded (starts collapsed unless a destination/plan exists)
  const [formExpanded, setFormExpanded] = useState(() => !!travelDestination);

  // Default departure time = right now in local time (datetime-local needs YYYY-MM-DDTHH:mm)
  const defaultDeparture = (() => {
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  })();
  const [departureInput, setDepartureInput] = useState(defaultDeparture);

  const destDebounce  = useRef<ReturnType<typeof setTimeout> | null>(null);
  const originDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Consume any pending destination from the deep-link share handler
  useEffect(() => {
    const pending = sessionStorage.getItem('cap_pending_dest');
    if (pending) {
      sessionStorage.removeItem('cap_pending_dest');
      setDestQuery(pending);
      debounceGeocode(pending, destDebounce, setDestLoading, setDestSugg);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-populate "From" field with current location address
  useEffect(() => {
    if (!userLocation || travelOrigin || originQuery) return;
    apiService.reverseGeocode(userLocation.latitude, userLocation.longitude)
      .then((label) => { if (label) setOriginQuery(label); })
      .catch(() => {});
  }, [userLocation]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto re-plan when prayed prayers change while a plan is active
  const prevPrayedRef = useRef<Set<string>>(prayedToday);
  useEffect(() => {
    if (travelPlan && prevPrayedRef.current !== prayedToday && travelDestination) {
      prevPrayedRef.current = prayedToday;
      executePlan(tripMode);
    }
  }, [prayedToday]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-plan when Muqeem/Musafir mode switches while a plan is active
  const prevTripModeRef = useRef(tripMode);
  useEffect(() => {
    if (prevTripModeRef.current === tripMode) return;
    prevTripModeRef.current = tripMode;
    if (travelPlan && travelDestination) {
      executePlan(tripMode);
    }
  }, [tripMode]); // eslint-disable-line react-hooks/exhaustive-deps

  function debounceGeocode(
    val: string,
    ref: React.MutableRefObject<ReturnType<typeof setTimeout> | null>,
    setLoading: (v: boolean) => void,
    setSugg: (s: GeocodeSuggestion[]) => void,
  ) {
    if (ref.current) clearTimeout(ref.current);
    if (val.length < 3) { setSugg([]); return; }
    ref.current = setTimeout(async () => {
      setLoading(true);
      try { setSugg(await apiService.geocodeDestination(val, userLocation?.latitude, userLocation?.longitude)); }
      catch { setSugg([]); }
      finally { setLoading(false); }
    }, 400);
  }

  function debounceGeocodeWp(index: number, val: string) {
    if (wpDebounces.current[index]) clearTimeout(wpDebounces.current[index]!);
    setWaypointRows(rows => rows.map((r, i) => i === index ? { ...r, query: val, sugg: val.length < 3 ? [] : r.sugg } : r));
    if (val.length < 3) return;
    wpDebounces.current[index] = setTimeout(async () => {
      setWaypointRows(rows => rows.map((r, i) => i === index ? { ...r, loading: true } : r));
      try {
        const sugg = await apiService.geocodeDestination(val, userLocation?.latitude, userLocation?.longitude);
        setWaypointRows(rows => rows.map((r, i) => i === index ? { ...r, sugg, loading: false } : r));
      } catch {
        setWaypointRows(rows => rows.map((r, i) => i === index ? { ...r, sugg: [], loading: false } : r));
      }
    }, 400);
  }

  function addWaypoint() {
    if (waypointRows.length >= 4) return;
    setWaypointRows(rows => [...rows, { dest: null, query: '', sugg: [], loading: false }]);
    wpDebounces.current.push(null);
  }

  function removeWaypoint(index: number) {
    if (wpDebounces.current[index]) clearTimeout(wpDebounces.current[index]!);
    setWaypointRows(rows => rows.filter((_, i) => i !== index));
    wpDebounces.current.splice(index, 1);
  }

  function moveWaypoint(index: number, direction: -1 | 1) {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= waypointRows.length) return;
    setWaypointRows(rows => {
      const next = [...rows];
      [next[index], next[newIndex]] = [next[newIndex], next[index]];
      return next;
    });
    const tmp = wpDebounces.current[index];
    wpDebounces.current[index] = wpDebounces.current[newIndex];
    wpDebounces.current[newIndex] = tmp;
  }

  function clearAll() {
    setTravelDestination(null);
    setTravelOrigin(null);
    setTravelDepartureTime(null);
    setTravelPlan(null);
    setDestQuery(''); setDestSugg([]);
    setOriginQuery(''); setOriginSugg([]);
    setWaypointRows([]);
    wpDebounces.current = [];
    setDepartureInput(defaultDeparture);
    setFormExpanded(false);
  }

  const [chipExpanded, setChipExpanded] = useState(false);
  // Non-null = long-trip warning is showing; value = distance in km
  const [longTripKm, setLongTripKm] = useState<number | null>(null);
  const setTravelMode = useStore((s) => s.setTravelMode);

  async function executePlan(mode: 'travel' | 'driving') {
    if (!travelDestination) return;
    const originLat = travelOrigin?.lat ?? userLocation?.latitude;
    const originLng = travelOrigin?.lng ?? userLocation?.longitude;
    if (!originLat || !originLng) return;

    setLongTripKm(null);
    const depIso = departureInput ? new Date(departureInput).toISOString() : undefined;
    setTravelDepartureTime(depIso || null);
    setTravelPlanLoading(true);
    setTravelPlan(null);
    setChipExpanded(false);

    // Build waypoints list from confirmed rows only
    const wps = waypointRows
      .filter(w => w.dest !== null)
      .map(w => ({ lat: w.dest!.lat, lng: w.dest!.lng, name: w.dest!.place_name }));

    try {
      const plan = await apiService.getTravelPlan(
        originLat, originLng,
        travelDestination.lat, travelDestination.lng,
        travelDestination.place_name,
        travelOrigin?.place_name,
        depIso,
        mode,
        wps,
        Array.from(prayedToday),
      );
      setTravelPlan(plan);
      useStore.getState().setSelectedItineraryIndex(0);
    } catch {
      setTravelPlan(null);
      useStore.getState().setSelectedItineraryIndex(null);
    } finally {
      setTravelPlanLoading(false);
    }
  }

  function handlePlan() {
    if (!travelDestination) return;
    const originLat = travelOrigin?.lat ?? userLocation?.latitude;
    const originLng = travelOrigin?.lng ?? userLocation?.longitude;
    if (!originLat || !originLng) return;

    // Long-trip check: >160 km (~100 miles) in Muqeem mode → prompt
    const distKm = haversineKm(originLat, originLng, travelDestination.lat, travelDestination.lng);
    if (distKm > 160 && !travelModeStore) {
      setLongTripKm(Math.round(distKm));
      return;
    }

    executePlan(tripMode);
  }

  const openSheet = useStore((s) => s.openSheet);
  const originLabel = travelOrigin?.place_name ?? 'Current location';
  const isExpanded = formExpanded || chipExpanded || (!travelDestination && formExpanded);

  // Shared settings button (inline to avoid hook-in-callback issues)
  const settingsBtn = (
    <button
      onClick={() => openSheet({ type: 'settings' })}
      className="w-10 h-10 flex items-center justify-center bg-white/95 backdrop-blur-sm rounded-xl shadow-lg flex-shrink-0"
      aria-label="Settings"
    >
      <img src="/icons/icon_settings.png" alt="" className="w-5 h-5 object-contain opacity-50" />
    </button>
  );

  // EXPANDED form card
  if (isExpanded) {
    return (
      <div className="p-3">
        <div className="bg-white/97 backdrop-blur rounded-2xl shadow-xl overflow-hidden">
          {/* Card header */}
          <div className="flex items-center gap-2 px-3 pt-3 pb-2 border-b border-gray-100">
            <button
              onClick={() => { setFormExpanded(false); setChipExpanded(false); }}
              className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 text-gray-500 transition-colors flex-shrink-0"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M15 18l-6-6 6-6"/></svg>
            </button>
            <p className={`text-xs font-bold uppercase tracking-wider flex-1 ${th.text}`}>Plan Trip</p>
            <ModeToggle />
            {settingsBtn}
          </div>

          {/* Form fields */}
          <div className="px-3 pb-3 pt-2 space-y-2">
            {/* From */}
            <GeoInput
              placeholder="From: Current location"
              icon="📍"
              value={originQuery}
              onChange={(v) => { setOriginQuery(v); debounceGeocode(v, originDebounce, setOriginLoading, setOriginSugg); }}
              suggestions={originSugg}
              onSelect={(s) => { setTravelOrigin(s); setOriginQuery(s.place_name); setOriginSugg([]); }}
              loading={originLoading}
              onClear={originQuery ? () => { setTravelOrigin(null); setOriginQuery(''); setOriginSugg([]); } : undefined}
            />

            {/* Intermediate waypoints */}
            {waypointRows.map((wp, i) => (
              <div key={i} className="flex items-start gap-1">
                <div className="flex flex-col gap-0.5 pt-1.5">
                  <button onClick={() => moveWaypoint(i, -1)} disabled={i === 0} className="text-gray-400 hover:text-gray-600 disabled:opacity-20 text-xs leading-none px-0.5">▲</button>
                  <button onClick={() => moveWaypoint(i, 1)} disabled={i === waypointRows.length - 1} className="text-gray-400 hover:text-gray-600 disabled:opacity-20 text-xs leading-none px-0.5">▼</button>
                </div>
                <div className="flex-1 min-w-0">
                  <GeoInput
                    placeholder={`Stop ${i + 1}`}
                    icon="📌"
                    value={wp.query}
                    onChange={(v) => debounceGeocodeWp(i, v)}
                    suggestions={wp.sugg}
                    onSelect={(s) => setWaypointRows(rows => rows.map((r, ri) => ri === i ? { ...r, dest: s, query: s.place_name, sugg: [] } : r))}
                    loading={wp.loading}
                    onClear={() => setWaypointRows(rows => rows.map((r, ri) => ri === i ? { ...r, dest: null, query: '', sugg: [] } : r))}
                  />
                </div>
                <button onClick={() => removeWaypoint(i)} className="text-gray-400 hover:text-red-500 text-base leading-none pt-2 px-1 flex-shrink-0">✕</button>
              </div>
            ))}

            {/* To */}
            <GeoInput
              placeholder="To: Destination *"
              icon="🏁"
              value={destQuery}
              onChange={(v) => { setDestQuery(v); debounceGeocode(v, destDebounce, setDestLoading, setDestSugg); }}
              suggestions={destSugg}
              onSelect={(s) => { setTravelDestination(s); setDestQuery(s.place_name); setDestSugg([]); }}
              loading={destLoading}
            />

            {/* Add stop */}
            {travelDestination && waypointRows.length < 4 && (
              <button onClick={addWaypoint} className={`text-xs flex items-center gap-1 pl-1 ${th.textMid} ${th.textHoverDark}`}>
                <span className="text-sm font-bold">+</span> Add stop
              </button>
            )}

            {/* Departure time */}
            <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1.5">
              <input
                type="datetime-local"
                value={departureInput}
                onChange={(e) => setDepartureInput(e.target.value)}
                className="flex-1 text-sm outline-none bg-transparent text-gray-700 min-w-0"
              />
            </div>

            {/* Long-trip suggestion */}
            {longTripKm !== null && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-2">
                <p className="text-xs font-semibold text-amber-800">Long trip — ~{Math.round(longTripKm / 1.609)} mi</p>
                <p className="text-xs text-amber-700">As Musafir you can combine prayers (Dhuhr+Asr, Maghrib+Isha).</p>
                <div className="flex gap-2">
                  <button onClick={() => { setTravelMode(true); executePlan('travel'); }} className={`flex-1 text-white text-xs font-semibold py-1.5 rounded-lg ${th.bg} ${th.bgHover}`}>✈️ Switch to Musafir</button>
                  <button onClick={() => executePlan('driving')} className="flex-1 bg-white border border-gray-300 text-gray-600 text-xs font-semibold py-1.5 rounded-lg hover:bg-gray-50">Plan as Muqeem</button>
                </div>
              </div>
            )}

            {longTripKm === null && (
              <button
                onClick={handlePlan}
                disabled={!travelDestination || travelPlanLoading}
                className={`w-full text-white text-sm font-semibold py-2.5 rounded-xl disabled:opacity-40 disabled:cursor-not-allowed transition-colors ${th.bg} ${th.bgHover}`}
              >
                {travelPlanLoading ? 'Planning…' : 'Plan My Prayers'}
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // COLLAPSED — plan active chip
  if (travelDestination && travelPlan) {
    return (
      <div className="p-3">
        <div className="flex items-center gap-2">
          <div
            onClick={() => setChipExpanded(true)}
            className="flex-1 flex items-center gap-3 bg-white/95 backdrop-blur-sm rounded-2xl shadow-lg px-4 py-3 cursor-pointer"
          >
            <div className={`w-2 h-2 rounded-full flex-shrink-0 ${th.bg}`} />
            <div className="flex-1 min-w-0">
              <p className="text-xs text-gray-500 truncate">{originLabel}</p>
              <p className="text-sm font-semibold text-gray-800 truncate">{travelDestination.place_name}</p>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); clearAll(); }}
              className="text-gray-400 hover:text-gray-600 text-lg leading-none flex-shrink-0"
            >✕</button>
          </div>
          <ModeToggle />
          {settingsBtn}
        </div>
      </div>
    );
  }

  // COLLAPSED — idle search pill
  return (
    <div className="p-3">
      <div className="flex items-center gap-2">
        <button
          onClick={() => setFormExpanded(true)}
          className="flex-1 flex items-center gap-3 bg-white/95 backdrop-blur-sm rounded-2xl shadow-lg px-4 py-3.5 text-left"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          <span className="text-gray-400 text-sm font-medium">Where to?</span>
        </button>
        <ModeToggle />
        {settingsBtn}
      </div>
    </div>
  );
}

// ─── Travel Plan View ────────────────────────────────────────────────────────

function TravelItineraryCard({ itinerary, index }: { itinerary: TripItinerary; index: number }) {
  const setSelectedMosqueId       = useStore((s) => s.setSelectedMosqueId);
  const setBottomSheetHeight      = useStore((s) => s.setBottomSheetHeight);
  const setMapFocusCoords         = useStore((s) => s.setMapFocusCoords);
  const selectedItineraryIndex    = useStore((s) => s.selectedItineraryIndex);
  const setSelectedItineraryIndex = useStore((s) => s.setSelectedItineraryIndex);
  const th                        = useTheme();
  const [expanded, setExpanded]   = useState(index === 0);

  const optionIcons: Record<string, string> = {
    pray_before:    '📍',
    combine_early:  '⏩',
    combine_late:   '⏪',
    at_destination: '🏁',
    separate:       '🔀',
    solo_stop:      '🕌',
    stop_for_fajr:  '🌅',
    no_option:      '⚠️',
  };

  const isSelected = selectedItineraryIndex === index;

  return (
    <div className={`mx-3 bg-white border rounded-xl shadow-sm transition-all ${isSelected ? `${th.borderStrong} ${th.shadow}` : itinerary.feasible ? 'border-gray-200' : 'border-gray-200 opacity-60'}`}>
      {/* Header — tap to expand/collapse + select on map */}
      <button
        className="w-full text-left px-3 pt-3 pb-2"
        onClick={() => {
          setExpanded((e) => !e);
          setSelectedItineraryIndex(index);
          setBottomSheetHeight('peek');
        }}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className={`text-xs font-bold uppercase tracking-wide ${isSelected ? th.textMid : th.text}`}>
              {isSelected ? '▶ ' : ''}Option {index + 1}
            </p>
            <p className="text-sm font-semibold text-gray-800 mt-0.5 leading-snug">{itinerary.label}</p>
          </div>
          <div className="text-right shrink-0">
            {itinerary.total_detour_minutes > 0 && (
              <p className="text-xs text-gray-500">+{fmtDuration(itinerary.total_detour_minutes)} detour</p>
            )}
            <p className="text-xs text-gray-400 mt-0.5">{expanded ? '▲' : '▼'}</p>
          </div>
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-3 border-t border-gray-100 pt-2">
          {itinerary.pair_choices.map((pc: PairChoice, i: number) => {
            const icon = optionIcons[pc.option.option_type] ?? '•';
            return (
              <div key={i}>
                {/* Prayer pair header */}
                <div className="flex items-center gap-1.5 mb-1 min-w-0 overflow-hidden">
                  <span className="text-sm flex-shrink-0">{pc.emoji}</span>
                  <span className="text-xs font-semibold text-gray-700 truncate">{pc.label}</span>
                  {pc.option.combination_label && (
                    <span className={`text-xs px-1.5 py-0.5 rounded-full flex-shrink-0 border ${th.bgLight} ${th.text} ${th.border}`}>
                      {pc.option.combination_label}
                    </span>
                  )}
                </div>
                {/* Description */}
                <p className="text-xs text-gray-500 mb-1 break-words">{icon} {pc.option.description}</p>
                {/* Mosque stops — tappable */}
                {pc.option.stops.map((stop: TravelStop, j: number) => (
                  <button
                    key={j}
                    className={`w-full text-left text-xs bg-gray-50 rounded-lg px-2.5 py-1.5 mt-1 border border-gray-100 transition-colors overflow-hidden ${th.borderHover} ${th.bgHoverLight}`}
                    onClick={() => {
                      setSelectedMosqueId(stop.mosque_id);
                      setMapFocusCoords({ lat: stop.mosque_lat, lng: stop.mosque_lng });
                      setBottomSheetHeight('peek');
                    }}
                  >
                    <span className="font-medium text-gray-800">{stop.mosque_name}</span>
                    {stop.mosque_address ? <span className="text-gray-500"> · {stop.mosque_address}</span> : null}
                    {stop.iqama_time ? <span className="text-gray-600"> · Iqama {fmtTime(stop.iqama_time)}</span> : null}
                    <span className={`ml-1 ${th.textMid}`}> +{fmtDuration(stop.detour_minutes)} detour 📍</span>
                  </button>
                ))}
                {pc.option.note && (
                  <p className="text-xs text-gray-400 mt-1 italic">{pc.option.note}</p>
                )}
              </div>
            );
          })}

        </div>
      )}
    </div>
  );
}

// ─── Navigate Bar (floats over the map when an itinerary is selected) ────────

function NavigateBar() {
  const th                     = useTheme();
  const selectedItineraryIndex = useStore((s) => s.selectedItineraryIndex);
  const travelPlan        = useStore((s) => s.travelPlan);
  const travelOrigin      = useStore((s) => s.travelOrigin);
  const travelDestination = useStore((s) => s.travelDestination);
  const userLocation      = useStore((s) => s.userLocation);
  const [sheetOpen, setSheetOpen] = useState(false);

  if (selectedItineraryIndex == null || !travelPlan || !travelDestination) return null;

  const itinerary = travelPlan.itineraries?.[selectedItineraryIndex];
  if (!itinerary) return null;

  const originLat = travelOrigin?.lat ?? userLocation?.latitude;
  const originLng = travelOrigin?.lng ?? userLocation?.longitude;
  if (!originLat || !originLng) return null;

  const seenIds = new Set<string>();
  const waystops = itinerary.pair_choices
    .flatMap((pc: PairChoice) => pc.option.stops)
    .sort((a: TravelStop, b: TravelStop) => a.minutes_into_trip - b.minutes_into_trip)
    .filter((s: TravelStop) => { if (seenIds.has(s.mosque_id)) return false; seenIds.add(s.mosque_id); return true; });

  const points: MapPoint[] = [
    { lat: originLat, lng: originLng, name: travelOrigin?.place_name, is_gps: !travelOrigin },
    ...waystops.map((s: TravelStop) => ({
      lat: s.mosque_lat, lng: s.mosque_lng,
      name: s.mosque_address ? `${s.mosque_name}, ${s.mosque_address}` : s.mosque_name,
      place_id: s.google_place_id,
    })),
    { lat: travelDestination.lat, lng: travelDestination.lng, name: travelDestination.place_name },
  ];

  const googleUrl = buildGoogleMapsUrl(points);
  const appleUrl  = buildAppleMapsUrl(points);

  async function handleShare() {
    if (navigator.share) {
      try { await navigator.share({ title: `Prayer route — Option ${selectedItineraryIndex! + 1}`, text: itinerary.summary, url: googleUrl }); return; }
      catch { /* cancelled */ }
    }
    try { await navigator.clipboard.writeText(googleUrl); } catch { window.open(googleUrl, '_blank'); }
  }

  return (
    <>
      {/* Floats above the bottom-sheet peek (80px) + gap */}
      <div className="fixed bottom-[88px] left-3 right-3 z-[450]">
        <button
          onClick={() => setSheetOpen(true)}
          className={`w-full flex items-center justify-center gap-2 active:scale-95 text-white text-sm font-semibold rounded-xl py-3 shadow-lg transition-all ${th.bg} ${th.bgHover}`}
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5A2.5 2.5 0 1 1 12 6a2.5 2.5 0 0 1 0 5.5z"/>
          </svg>
          بسم الله — Navigate
        </button>
      </div>

      {/* Full-screen action sheet */}
      {sheetOpen && (
        <div className="fixed inset-0 z-[1000] flex items-end" onClick={() => setSheetOpen(false)}>
          <div className="w-full bg-white rounded-t-2xl shadow-2xl pb-8 px-4 pt-3" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-center mb-4">
              <div className="w-10 h-1 bg-gray-300 rounded-full" />
            </div>
            <p className="text-sm font-semibold text-gray-800 mb-0.5">Option {selectedItineraryIndex! + 1}: {itinerary.label}</p>
            <p className="text-xs text-gray-400 mb-4">{itinerary.summary}</p>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Open route in…</p>
            <div className="space-y-2">
              <button
                onClick={() => { window.open(googleUrl, '_blank'); setSheetOpen(false); }}
                className="w-full flex items-center gap-3 px-4 py-3.5 rounded-xl bg-gray-50 active:bg-gray-100 text-sm font-medium text-gray-800 transition-colors"
              >
                <img src="https://www.google.com/favicon.ico" alt="" className="w-5 h-5 rounded" />
                Google Maps
              </button>
              {IS_IOS && (
                <button
                  onClick={() => { window.open(appleUrl, '_blank'); setSheetOpen(false); }}
                  className="w-full flex items-center gap-3 px-4 py-3.5 rounded-xl bg-gray-50 active:bg-gray-100 text-sm font-medium text-gray-800 transition-colors"
                >
                  {/* Apple logo SVG */}
                  <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" viewBox="0 0 814 1000" fill="currentColor">
                    <path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76 0-103.7 40.8-165.9 40.8s-105-42.8-155.5-127.5c-43.5-74.2-77.5-188.6-77.5-297.5 0-179 116.7-273.8 231.5-273.8 61.5 0 112.8 40.8 150.7 40.8 36.2 0 93.8-43.4 162.8-43.4 26.2 0 108.2 2.6 168.3 92.8zm-107-99.4C720.8 168 743.1 111.8 743.1 55c0-5.8-.6-11.6-1.9-16.5-57.3 2.6-124.9 38.9-166.2 89.7-36.2 43.4-70.1 113.1-70.1 182.7 0 6.4 1.3 12.8 1.9 15.5 3.9.6 10.2 1.3 16.5 1.3 50.6 0 113.5-33.9 157.8-86.1z"/>
                  </svg>
                  Apple Maps
                </button>
              )}
              <button
                onClick={async () => { await handleShare(); setSheetOpen(false); }}
                className="w-full flex items-center gap-3 px-4 py-3.5 rounded-xl bg-gray-50 active:bg-gray-100 text-sm font-medium text-gray-800 transition-colors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
                  <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
                </svg>
                Share Route
              </button>
            </div>
            <button
              onClick={() => setSheetOpen(false)}
              className="w-full mt-3 py-3 text-sm font-semibold text-gray-400 active:text-gray-600"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </>
  );
}

function TravelPlanView() {
  const th                = useTheme();
  const travelPlan        = useStore((s) => s.travelPlan);
  const travelPlanLoading = useStore((s) => s.travelPlanLoading);
  const travelDestination = useStore((s) => s.travelDestination);

  if (!travelDestination) return null;

  if (travelPlanLoading) {
    return (
      <div className="mx-3 py-10 flex flex-col items-center gap-3">
        <svg className={`animate-spin h-7 w-7 ${th.textMid}`} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
        </svg>
        <p className="text-sm text-gray-400">Planning your prayer route…</p>
      </div>
    );
  }

  if (!travelPlan) return null;

  const { route, itineraries } = travelPlan;
  const durationHrs  = Math.floor(route.duration_minutes / 60);
  const durationMins = route.duration_minutes % 60;
  const distDisplay  = USE_METRIC
    ? `${(route.distance_meters / 1000).toFixed(0)} km`
    : `${Math.round(route.distance_meters / 1609.344)} mi`;

  return (
    <div className="space-y-3 pb-4">
      {/* Route summary */}
      <div className="mx-3 bg-white border border-gray-200 rounded-xl px-3 py-2.5 text-sm text-gray-600">
        <span className="font-semibold text-gray-800">Route: </span>
        {durationHrs > 0 ? `${durationHrs}h ` : ''}{durationMins}min · {distDisplay}
      </div>

      {/* Itinerary count label */}
      {itineraries && itineraries.length > 0 && (
        <p className="mx-3 text-xs font-bold text-gray-400 uppercase tracking-wider">
          {itineraries.length} complete prayer plan{itineraries.length !== 1 ? 's' : ''}
        </p>
      )}

      {/* Complete trip itineraries */}
      {(itineraries ?? []).map((it: TripItinerary, i: number) => (
        <TravelItineraryCard key={i} itinerary={it} index={i} />
      ))}

      {(!itineraries || itineraries.length === 0) && (
        <div className="mx-3 text-center py-6 text-gray-400 text-sm">
          No prayer stops found along this route.
        </div>
      )}
    </div>
  );
}

// ─── Mode Toggle ─────────────────────────────────────────────────────────────

function ModeToggle() {
  const travelMode    = useStore((s) => s.travelMode);
  const setTravelMode = useStore((s) => s.setTravelMode);
  const th            = useTheme();
  return (
    <button
      onClick={() => setTravelMode(!travelMode)}
      title={travelMode ? 'Musafir mode — tap to switch to Muqeem' : 'Muqeem mode — tap to switch to Musafir'}
      className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-white shadow-lg transition-colors flex-shrink-0 ${th.bg} ${th.bgHover}`}
    >
      <span>{travelMode ? '✈️' : '🏠'}</span>
      <span>{travelMode ? 'Musafir' : 'Muqeem'}</span>
    </button>
  );
}

// ─── Add Spot FAB ─────────────────────────────────────────────────────────────

function AddSpotFAB() {
  const openSheet     = useStore((s) => s.openSheet);
  const showSpots     = useStore((s) => s.showSpots);
  const travelDestination = useStore((s) => s.travelDestination);
  const th            = useTheme();
  if (!showSpots || travelDestination) return null;
  return (
    <button
      onClick={() => openSheet({ type: 'spot_submit' })}
      title="Add a prayer spot"
      className={`fixed right-4 bottom-[100px] z-[450] w-12 h-12 rounded-full ${th.bg} ${th.bgHover} text-white shadow-xl flex items-center justify-center text-xl font-light transition-colors active:scale-95`}
    >
      +
    </button>
  );
}

// ─── Map Bottom Sheet ─────────────────────────────────────────────────────────

function MapBottomSheet() {
  const th                  = useTheme();
  const bottomSheetHeight   = useStore((s) => s.bottomSheetHeight);
  const setBottomSheetHeight = useStore((s) => s.setBottomSheetHeight);
  const travelDestination   = useStore((s) => s.travelDestination);
  const travelPlan          = useStore((s) => s.travelPlan);
  const travelPlanLoading   = useStore((s) => s.travelPlanLoading);
  const selectedItineraryIndex = useStore((s) => s.selectedItineraryIndex);
  const mosquesLoading      = useStore((s) => s.mosquesLoading);
  const mosquesError        = useStore((s) => s.mosquesError);
  const mosques             = useStore((s) => s.mosques);
  const spots               = useStore((s) => s.spots);
  const spotsLoading        = useStore((s) => s.spotsLoading);
  const showSpots           = useStore((s) => s.showSpots);
  const userLocation        = useStore((s) => s.userLocation);

  const sheetRef        = useRef<HTMLDivElement>(null);
  const dragStartY      = useRef<number | null>(null);
  const dragStartOffset = useRef(0);

  function getSnappedY(state: 'peek' | 'half' | 'full'): number {
    const h = window.innerHeight;
    const sheetH = h * 0.85;
    if (state === 'full') return 0;
    if (state === 'half') return Math.max(0, sheetH - h * 0.52);
    return sheetH - 80;
  }

  // Animate sheet when state changes
  useEffect(() => {
    if (!sheetRef.current) return;
    sheetRef.current.style.transition = 'transform 0.35s cubic-bezier(0.32, 0.72, 0, 1)';
    sheetRef.current.style.transform = `translateY(${getSnappedY(bottomSheetHeight)}px)`;
  }, [bottomSheetHeight]);

  // Auto-transitions
  const prevItineraryRef = useRef(selectedItineraryIndex);
  useEffect(() => {
    if (selectedItineraryIndex !== null && prevItineraryRef.current !== selectedItineraryIndex) {
      setBottomSheetHeight('peek');
    }
    prevItineraryRef.current = selectedItineraryIndex;
  }, [selectedItineraryIndex]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (travelPlan) setBottomSheetHeight('half');
  }, [travelPlan]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!travelDestination) setBottomSheetHeight('half');
  }, [travelDestination]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleTouchStart(e: React.TouchEvent) {
    dragStartY.current = e.touches[0].clientY;
    if (sheetRef.current) {
      const m = new DOMMatrix(getComputedStyle(sheetRef.current).transform);
      dragStartOffset.current = m.m42;
      sheetRef.current.style.transition = 'none';
    }
  }

  function handleTouchMove(e: React.TouchEvent) {
    if (dragStartY.current === null || !sheetRef.current) return;
    const delta = e.touches[0].clientY - dragStartY.current;
    const newY = Math.max(0, Math.min(dragStartOffset.current + delta, getSnappedY('peek')));
    sheetRef.current.style.transform = `translateY(${newY}px)`;
  }

  function handleTouchEnd() {
    if (dragStartY.current === null || !sheetRef.current) return;
    dragStartY.current = null;
    const m = new DOMMatrix(getComputedStyle(sheetRef.current).transform);
    const currentY = m.m42;
    const states: Array<'peek' | 'half' | 'full'> = ['peek', 'half', 'full'];
    const nearest = states.reduce((a, b) =>
      Math.abs(getSnappedY(a) - currentY) < Math.abs(getSnappedY(b) - currentY) ? a : b
    );
    setBottomSheetHeight(nearest);
  }

  // Peek label
  let peekLabel = '';
  if (selectedItineraryIndex !== null && travelPlan?.itineraries?.[selectedItineraryIndex]) {
    const it = travelPlan.itineraries[selectedItineraryIndex];
    peekLabel = `Option ${selectedItineraryIndex + 1} · ${it.label}`;
  } else if (travelPlanLoading) {
    peekLabel = 'Finding prayer routes…';
  } else if (travelPlan?.itineraries?.length) {
    peekLabel = `${travelPlan.itineraries.length} prayer route${travelPlan.itineraries.length > 1 ? 's' : ''}`;
  } else if (travelDestination) {
    peekLabel = `Route to ${travelDestination.place_name}`;
  } else if (mosquesLoading) {
    peekLabel = 'Finding mosques nearby…';
  } else {
    peekLabel = mosques.length > 0 ? `${mosques.length} mosques nearby` : 'Nearby prayer places';
  }

  return (
    <div
      ref={sheetRef}
      className="fixed bottom-0 left-0 right-0 bg-white rounded-t-3xl shadow-2xl z-[400] overflow-hidden"
      style={{ height: '85vh', transform: `translateY(${getSnappedY('half')}px)` }}
    >
      {/* Drag handle area */}
      <div
        className="pt-2.5 pb-0 touch-none cursor-grab active:cursor-grabbing"
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        <div className="w-10 h-1 bg-gray-300 rounded-full mx-auto" />
      </div>

      {/* Peek label — tappable to toggle half/peek */}
      <button
        className="w-full px-4 py-2.5 text-left active:bg-gray-50"
        onClick={() => setBottomSheetHeight(bottomSheetHeight === 'peek' ? 'half' : 'peek')}
      >
        <p className="text-sm font-semibold text-gray-800 leading-tight truncate">{peekLabel}</p>
      </button>

      {/* Scrollable content — below peek area */}
      <div className="overflow-y-auto" style={{ height: 'calc(85vh - 64px)' }}>

        {/* Trip plan view */}
        {travelDestination ? (
          <TravelPlanView />
        ) : (
          <>
            {/* Loading mosques */}
            {mosquesLoading && (
              <div className="flex flex-col items-center py-12 gap-3 text-slate-400">
                <div className={`animate-spin rounded-full h-7 w-7 border-2 border-slate-200 ${th.spinnerTop}`} />
                <p className="text-sm">Finding mosques nearby…</p>
              </div>
            )}

            {/* Error */}
            {mosquesError && !mosquesLoading && (
              <div className="mx-4 mt-2 bg-red-50 border border-red-200 rounded-2xl p-4 text-sm text-red-700">
                {mosquesError}
              </div>
            )}

            {/* No location */}
            {!userLocation && !mosquesLoading && !mosquesError && (
              <div className="flex flex-col items-center py-16 gap-2 text-slate-400">
                <p className="text-3xl">📍</p>
                <p className="text-sm font-medium">Waiting for your location…</p>
              </div>
            )}

            {/* Prayed banner */}
            {userLocation && !mosquesLoading && <PrayedBanner mosques={mosques} />}

            {/* Mosque list */}
            {!mosquesLoading && mosques.length > 0 && (
              <div className="px-3 pt-1 pb-3 space-y-2.5">
                {mosques.map((m) => <MosqueCard key={m.id} mosque={m} />)}
              </div>
            )}

            {/* Prayer spots */}
            {showSpots && !travelDestination && (
              <div className="px-3 pb-6">
                {spotsLoading && <p className="text-xs text-slate-400 px-1 py-2">Loading spots…</p>}
                {!spotsLoading && spots.length > 0 && (
                  <>
                    <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2 mt-1 px-1">Prayer Spots</p>
                    <div className="space-y-2">
                      {spots.map((s) => <SpotCard key={s.id} spot={s} />)}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Last resort */}
            {userLocation && !mosquesLoading && !spotsLoading && (() => {
              const CATCHABLE = new Set(['can_catch_with_imam','can_catch_with_imam_in_progress','can_pray_solo_at_mosque','upcoming']);
              if (mosques.some(m => m.next_catchable && CATCHABLE.has(m.next_catchable.status))) return null;
              if (spots.some(s => s.status === 'active')) return null;
              return <div className="px-3 pb-4"><LastResortCard /></div>;
            })()}
          </>
        )}
      </div>
    </div>
  );
}

// ─── Main App ────────────────────────────────────────────────────────────────

function App() {
  const userLocation  = useStore((s) => s.userLocation);
  const setUserLocation = useStore((s) => s.setUserLocation);
  const setMosques    = useStore((s) => s.setMosques);
  const setMosquesLoading = useStore((s) => s.setMosquesLoading);
  const setMosquesError = useStore((s) => s.setMosquesError);
  const setSpots      = useStore((s) => s.setSpots);
  const setSpotsLoading = useStore((s) => s.setSpotsLoading);
  const radiusKm      = useStore((s) => s.radiusKm);
  const denominationFilter = useStore((s) => s.denominationFilter);
  const showSpots     = useStore((s) => s.showSpots);
  const travelModeStore = useStore((s) => s.travelMode);
  const travelDestination = useStore((s) => s.travelDestination);
  const setTravelPlan = useStore((s) => s.setTravelPlan);

  // Geolocation on mount
  useEffect(() => {
    if (!('geolocation' in navigator)) {
      setMosquesError('Geolocation is not supported by this browser.');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setUserLocation({ latitude: pos.coords.latitude, longitude: pos.coords.longitude });
      },
      () => setMosquesError('Please enable location access to find nearby mosques.'),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 300000 }
    );
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Deep link / Web Share Target handler — runs once on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    let handled = false;

    // Direct params: ?dest_lat=X&dest_lng=Y&dest_name=Z (programmatic deep link)
    const destLat  = params.get('dest_lat');
    const destLng  = params.get('dest_lng');
    const destName = params.get('dest_name');
    if (destLat && destLng) {
      useStore.getState().setTravelMode(true);
      useStore.getState().setTravelDestination({
        lat: parseFloat(destLat),
        lng: parseFloat(destLng),
        place_name: destName ?? 'Shared destination',
      });
      handled = true;
    } else if (params.get('share') === 'maps') {
      // Web Share Target: URL shared from Google Maps / Apple Maps
      const sharedUrl   = params.get('url')   ?? '';
      const sharedTitle = params.get('title') ?? params.get('text') ?? '';
      const parsed = parseMapShareUrl(sharedUrl);
      if (parsed) {
        useStore.getState().setTravelMode(true);
        useStore.getState().setTravelDestination(parsed);
      } else if (sharedTitle) {
        // Shortened URL (goo.gl/maps.app.goo.gl) — pre-fill search with title
        useStore.getState().setTravelMode(true);
        sessionStorage.setItem('cap_pending_dest', sharedTitle);
      }
      handled = true;
    }

    if (handled) {
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch when location, radius, or travel mode changes, and auto-refresh every 5 minutes
  useEffect(() => {
    if (!userLocation) return;
    fetchData(userLocation.latitude, userLocation.longitude);
    const interval = setInterval(
      () => fetchData(userLocation.latitude, userLocation.longitude),
      5 * 60 * 1000
    );
    return () => clearInterval(interval);
  }, [userLocation, radiusKm, travelModeStore]); // eslint-disable-line react-hooks/exhaustive-deps

  // Clear travel plan when destination is removed
  useEffect(() => {
    if (!travelDestination) { setTravelPlan(null); useStore.getState().setSelectedItineraryIndex(null); }
  }, [travelDestination]); // eslint-disable-line react-hooks/exhaustive-deps

  async function fetchData(lat: number, lng: number) {
    setMosquesLoading(true);
    setMosquesError(null);
    console.log('[fetchData] lat:', lat, 'lng:', lng, 'radius:', radiusKm, 'travel:', travelModeStore);
    try {
      const res = await apiService.findNearbyMosques(lat, lng, radiusKm, travelModeStore);
      if (!res || !Array.isArray(res.mosques)) {
        throw new Error('Invalid response from server — is REACT_APP_API_URL set?');
      }
      let filtered = res.mosques;
      if (denominationFilter !== 'all') {
        filtered = filtered.filter(
          (m) => m.denomination?.toLowerCase().includes(denominationFilter)
        );
      }
      setMosques(filtered);
    } catch (e: any) {
      console.error('[fetchData] error:', e?.message, e?.code, e?.response?.status, e?.response?.data, e);
      const detail = e?.response?.data?.detail;
      if (detail && typeof detail === 'object' && detail.error === 'no_mosques_found') {
        setMosquesError(`No mosques found within ${USE_METRIC ? `${radiusKm} km` : `${Math.round(radiusKm / 1.60934)} mi`}. Try increasing the search radius in Settings.`);
      } else {
        setMosquesError(typeof detail === 'string' ? detail : 'Failed to load mosques.');
      }
    } finally {
      setMosquesLoading(false);
    }

    if (showSpots) {
      setSpotsLoading(true);
      try {
        const res2 = await apiService.findNearbySpots(lat, lng, radiusKm, SESSION_ID);
        setSpots(res2.spots);
      } catch {
        setSpots([]);
      } finally {
        setSpotsLoading(false);
      }
    }
  }

  return (
    <div className="fixed inset-0 overflow-hidden bg-slate-200">
      {/* Layer 0: Full-screen map */}
      <div className="absolute inset-0">
        <Suspense fallback={<div className="h-full bg-slate-200" />}>
          <MapView />
        </Suspense>
      </div>

      {/* Layer 1: Top overlay — trip planning bar */}
      <div className="absolute top-0 left-0 right-0 z-[500]" style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}>
        <DestinationInput />
      </div>

      {/* Layer 2: Navigate bar — above bottom sheet peek */}
      <NavigateBar />

      {/* Layer 3: Add spot FAB */}
      <AddSpotFAB />

      {/* Layer 4: Bottom sheet — mosque list / trip plan */}
      <MapBottomSheet />

      {/* Layer 5: Detail sheets (mosque, spot, settings) */}
      <BottomSheet />
    </div>
  );
}

export default App;
