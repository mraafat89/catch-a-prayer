import React, { useEffect, useRef, useState } from 'react';
import MapView from './components/MapView';
import { apiService } from './services/api';
import { useStore, SESSION_ID } from './store';
import {
  Mosque, PrayerSpot, PrayerTime, JumuahSession,
  STATUS_CONFIG, SPOT_TYPE_LABELS,
  SpotSubmitRequest,
  TravelPlan, TravelPairPlan, TravelOption, TravelDestination, TravelStop, GeocodeSuggestion,
  TripItinerary, PairChoice,
} from './types';

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

const WEBSITE_SOURCES = new Set([
  'mosque_website_html', 'mosque_website_js', 'mosque_website',
  'static_html', 'playwright_html', 'vision_ai',
]);

const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

function buildGoogleMapsUrl(points: Array<[number, number]>): string {
  return 'https://www.google.com/maps/dir/' + points.map(([lat, lng]) => `${lat},${lng}`).join('/');
}

function buildAppleMapsUrl(points: Array<[number, number]>): string {
  const [origin, ...rest] = points;
  const destPoints = rest.map(([lat, lng]) => `daddr=${lat},${lng}`).join('&');
  return `https://maps.apple.com/?saddr=${origin[0]},${origin[1]}&${destPoints}&dirflg=d`;
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
  const setMapCollapsed     = useStore((s) => s.setMapCollapsed);
  const prayedToday         = useStore((s) => s.prayedToday);
  const togglePrayed        = useStore((s) => s.togglePrayed);
  const travelMode          = useStore((s) => s.travelMode);
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
    setMapCollapsed(false);
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
            className="mt-1.5 text-xs font-medium px-2 py-0.5 rounded-full border border-green-400 text-green-700 bg-white hover:bg-green-50 transition-colors"
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
        <div className="px-3 pt-2 pb-3 bg-indigo-50 border-t border-indigo-100 space-y-2">
          {mosque.travel_combinations.map((pair: TravelPairPlan) => {
            const taqdeem = pair.options.find((o: TravelOption) => o.option_type === 'combine_early');
            const takheer = pair.options.find((o: TravelOption) => o.option_type === 'combine_late');
            const takheerOnly = !taqdeem && !!takheer;
            return (
              <div key={pair.pair}>
                <p className="text-xs font-semibold text-indigo-700 mb-1.5">
                  ✈️ {pair.emoji} {pair.label} — Musafir
                </p>

                {/* Ta'kheer only: p1 time passed but NOT missed */}
                {takheerOnly && (
                  <div className="bg-white rounded-lg border border-blue-200 px-2.5 py-2 space-y-1">
                    <p className="text-xs font-semibold text-blue-800">{pair.label.split(' + ')[0]} is not missed ✓</p>
                    <p className="text-xs text-blue-700">{takheer!.description}</p>
                    <span className="inline-block text-xs bg-blue-50 text-blue-700 border border-blue-200 px-1.5 py-0.5 rounded-full">
                      Jam' Ta'kheer
                    </span>
                  </div>
                )}

                {/* Taqdeem — primary when both available or only Taqdeem */}
                {taqdeem && (
                  <div className={`bg-white rounded-lg border border-green-200 px-2.5 py-2 space-y-1 ${takheer ? 'mb-1.5' : ''}`}>
                    <p className="text-xs text-green-800">{taqdeem.description}</p>
                    <span className="inline-block text-xs bg-green-50 text-green-700 border border-green-200 px-1.5 py-0.5 rounded-full">
                      Jam' Taqdeem — pray now
                    </span>
                  </div>
                )}

                {/* Ta'kheer as secondary when Taqdeem also available */}
                {taqdeem && takheer && (
                  <div className="bg-white rounded-lg border border-blue-100 px-2.5 py-2 space-y-1">
                    <p className="text-xs text-blue-700">{takheer.description}</p>
                    <span className="inline-block text-xs bg-blue-50 text-blue-600 border border-blue-200 px-1.5 py-0.5 rounded-full">
                      Jam' Ta'kheer — or wait
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
      className="rounded-xl border border-orange-200 bg-orange-50 p-3 cursor-pointer hover:shadow-md transition-shadow"
      onClick={() => openSheet({ type: 'spot_detail', spot })}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold text-gray-900 text-sm leading-tight truncate">{spot.name}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {SPOT_TYPE_LABELS[spot.spot_type] ?? spot.spot_type} · {distLabel(spot.distance_meters)}
          </p>
        </div>
        <span className="text-xs bg-orange-100 border border-orange-300 text-orange-700 px-1.5 py-0.5 rounded-full flex-shrink-0">
          {spot.verification_label}
        </span>
      </div>
      <div className="flex items-center justify-between mt-2 gap-2">
        <div className="flex gap-2 text-xs text-gray-500">
          {spot.has_wudu_facilities === true && <span>🚿 Wudu</span>}
          {spot.is_indoor === true && <span>🏠 Indoor</span>}
          {spot.gender_access && spot.gender_access !== 'all' && (
            <span>{spot.gender_access === 'men_only' ? '♂ Men' : '♀ Women'}</span>
          )}
        </div>
        <button
          onClick={handleConfirm}
          disabled={isConfirmed || confirming}
          className={`flex-shrink-0 text-xs px-2.5 py-1 rounded-full font-medium border transition-colors ${
            isConfirmed
              ? 'bg-green-50 border-green-300 text-green-700 cursor-default'
              : 'bg-white border-orange-400 text-orange-700 hover:bg-orange-100 active:bg-orange-200'
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

  const nc = mosque.next_catchable;
  const isMissed    = nc?.status === 'missed_make_up';
  const isUpcoming  = nc?.status === 'upcoming';
  const isNcPrayed  = nc ? prayedToday.has(nc.prayer) : false;

  // When nc is already prayed, find the next future prayer from the table
  const nowMin = new Date().getHours() * 60 + new Date().getMinutes();
  const nextFromTable = isNcPrayed
    ? mosque.prayers.find(p => {
        if (!p.adhan_time) return false;
        const [h, m] = p.adhan_time.split(':').map(Number);
        return h * 60 + m > nowMin;
      })
    : null;

  const badge = dataSourceBadge(mosque.prayers);

  // Badge config: upcoming gets teal (distinct from gray missed)
  const cfg = nc && !isNcPrayed
    ? (isUpcoming
        ? { bg: 'bg-teal-50', border: 'border-teal-200', text: 'text-teal-800', icon: STATUS_CONFIG['upcoming'].icon }
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
        <div className="rounded-lg border border-teal-200 bg-teal-50 px-3 py-2.5 mb-4">
          <p className="text-sm font-semibold text-teal-800 capitalize">Next: {nextFromTable.prayer}</p>
          <div className="mt-1 space-y-0.5 text-sm text-teal-700">
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
              <div key={s.session_number} className="rounded-lg border border-green-200 bg-green-50 px-3 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-green-900">
                    {mosque.jumuah_sessions.length > 1 ? `Session ${s.session_number}` : 'Jumu\'ah Prayer'}
                  </span>
                  <div className="text-right text-sm text-green-800">
                    {s.khutba_start && <span>Khutba {fmtTime(s.khutba_start)}</span>}
                    {s.khutba_start && s.prayer_start && <span className="mx-1">·</span>}
                    {s.prayer_start && <span className="font-medium">Prayer {fmtTime(s.prayer_start)}</span>}
                  </div>
                </div>
                {s.imam_name && (
                  <p className="text-xs text-green-700 mt-0.5">{s.imam_name}</p>
                )}
                {s.language && s.language.toLowerCase() !== 'english' && (
                  <p className="text-xs text-green-600 mt-0.5">Language: {s.language}</p>
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
          className="flex-1 bg-green-600 text-white text-xs py-2 px-2 rounded-lg text-center font-medium hover:bg-green-700"
        >
          🧭 Directions
        </a>
        {mosque.phone && (
          <a
            href={`tel:${mosque.phone}`}
            className="flex-1 bg-gray-600 text-white text-xs py-2 px-2 rounded-lg text-center font-medium hover:bg-gray-700"
          >
            📞 Call
          </a>
        )}
        {mosque.website && (
          <a
            href={mosque.website}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 bg-blue-600 text-white text-xs py-2 px-2 rounded-lg text-center font-medium hover:bg-blue-700"
          >
            🌐 Website
          </a>
        )}
      </div>
    </div>
  );
}

// ─── Spot Detail Sheet ───────────────────────────────────────────────────────

function SpotDetailSheet({ spot }: { spot: PrayerSpot }) {
  const closeSheet = useStore((s) => s.closeSheet);
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
          <span className="bg-blue-50 border border-blue-200 text-blue-700 text-xs px-2 py-1 rounded-full">🚿 Wudu facilities</span>
        )}
        {spot.is_indoor === true && (
          <span className="bg-gray-50 border border-gray-200 text-gray-700 text-xs px-2 py-1 rounded-full">🏠 Indoor</span>
        )}
        {spot.gender_access === 'men_only' && (
          <span className="bg-gray-50 border border-gray-200 text-gray-700 text-xs px-2 py-1 rounded-full">♂ Men only</span>
        )}
        {spot.gender_access === 'women_only' && (
          <span className="bg-gray-50 border border-gray-200 text-gray-700 text-xs px-2 py-1 rounded-full">♀ Women only</span>
        )}
        {spot.operating_hours && (
          <span className="bg-gray-50 border border-gray-200 text-gray-700 text-xs px-2 py-1 rounded-full">🕐 {spot.operating_hours}</span>
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
              className="bg-green-600 text-white py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
            >
              👍 Yes, confirm
            </button>
            <button
              onClick={() => handleVerify(false)}
              disabled={submitting}
              className="bg-red-100 text-red-700 border border-red-200 py-2 rounded-lg text-sm font-medium hover:bg-red-200 disabled:opacity-50"
            >
              👎 No longer valid
            </button>
          </div>
        </div>
      )}

      <a
        href={`https://www.google.com/maps/dir/?api=1&destination=${spot.location.latitude},${spot.location.longitude}`}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-3 block bg-gray-800 text-white text-sm py-2 rounded-lg text-center font-medium hover:bg-gray-900"
      >
        🧭 Get Directions
      </a>
    </div>
  );
}

// ─── Spot Submit Sheet ───────────────────────────────────────────────────────

function SpotSubmitSheet() {
  const closeSheet   = useStore((s) => s.closeSheet);
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
        <button onClick={closeSheet} className="bg-green-600 text-white px-6 py-2 rounded-lg font-medium">
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
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
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
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
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
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
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
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
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
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
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
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 resize-none"
            placeholder="Any helpful details for other musallees..."
            value={form.notes ?? ''}
            onChange={(e) => set('notes', e.target.value)}
          />
        </div>

        {error && <p className="text-xs text-red-600">{error}</p>}

        <button
          onClick={handleSubmit}
          disabled={submitting || !form.name?.trim() || spotLat === null}
          className="w-full bg-green-600 text-white py-2.5 rounded-lg font-medium text-sm hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
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
            Search radius: <span className="text-green-700 font-semibold">
              {USE_METRIC ? `${radiusKm} km` : `${Math.round(radiusKm / 1.60934)} mi`}
            </span>
          </label>
          <input
            type="range" min={1} max={50} step={1}
            value={radiusKm}
            onChange={(e) => setRadiusKm(Number(e.target.value))}
            className="w-full accent-green-600"
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
                    ? 'bg-green-600 text-white border-green-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:border-green-400'
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
            <p className="text-sm font-medium text-gray-700">
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
              travelMode ? 'bg-teal-600' : 'bg-gray-300'
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
              showSpots ? 'bg-green-600' : 'bg-gray-300'
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

function PrayedBanner({ mosques }: { mosques: Mosque[] }) {
  const prayedToday  = useStore((s) => s.prayedToday);
  const togglePrayed = useStore((s) => s.togglePrayed);

  // Collect active (non-upcoming) prayers across all mosques
  const activePrayers = new Set<string>();
  for (const mosque of mosques) {
    const catchable = mosque.catchable_prayers ?? (mosque.next_catchable ? [mosque.next_catchable] : []);
    for (const p of catchable) {
      if (ACTIVE_STATUSES.has(p.status)) activePrayers.add(p.prayer);
    }
  }

  if (activePrayers.size === 0) return null;

  return (
    <div className="space-y-1.5">
      {Array.from(activePrayers).map((prayer) => {
        const prayed = prayedToday.has(prayer);
        return (
          <div
            key={prayer}
            className={`flex items-center justify-between rounded-xl px-3 py-2 border text-sm ${
              prayed
                ? 'bg-green-50 border-green-200 text-green-800'
                : 'bg-white border-gray-200 text-gray-700'
            }`}
          >
            <span className="flex items-center gap-1.5">
              {prayed && <img src="/icons/icon_prayed.png" alt="" className="w-7 h-7 object-contain" />}
              {prayed ? `Already prayed ${prayer.charAt(0).toUpperCase() + prayer.slice(1)} today` : `${prayer.charAt(0).toUpperCase() + prayer.slice(1)} time — did you already pray?`}
            </span>
            <button
              onClick={() => togglePrayed(prayer)}
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
  return (
    <div className="relative">
      <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-2.5 py-2">
        <span className="text-sm">{icon}</span>
        <input
          type="text"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1 text-sm outline-none bg-transparent text-gray-800 placeholder-gray-400 min-w-0"
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
              className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-teal-50 border-b border-gray-100 last:border-0 truncate">
              <span className="text-gray-400 mr-1">📍</span>{s.place_name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function DestinationInput() {
  const userLocation    = useStore((s) => s.userLocation);
  const travelDestination = useStore((s) => s.travelDestination);
  const setTravelDestination = useStore((s) => s.setTravelDestination);
  const travelOrigin    = useStore((s) => s.travelOrigin);
  const setTravelOrigin = useStore((s) => s.setTravelOrigin);
  const travelDepartureTime = useStore((s) => s.travelDepartureTime);
  const setTravelDepartureTime = useStore((s) => s.setTravelDepartureTime);
  const setTravelPlan   = useStore((s) => s.setTravelPlan);
  const setTravelPlanLoading = useStore((s) => s.setTravelPlanLoading);
  const travelModeStore = useStore((s) => s.travelMode);

  const [destQuery, setDestQuery]   = useState(travelDestination?.place_name ?? '');
  const [destSugg, setDestSugg]     = useState<GeocodeSuggestion[]>([]);
  const [destLoading, setDestLoading] = useState(false);
  const [originQuery, setOriginQuery] = useState(travelOrigin?.place_name ?? '');
  const [originSugg, setOriginSugg]  = useState<GeocodeSuggestion[]>([]);
  const [originLoading, setOriginLoading] = useState(false);
  // Trip mode always follows global Muqeem/Musafir toggle — no per-trip override
  const tripMode = travelModeStore ? 'travel' : 'driving';

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

  function clearAll() {
    setTravelDestination(null);
    setTravelOrigin(null);
    setTravelDepartureTime(null);
    setTravelPlan(null);
    setDestQuery(''); setDestSugg([]);
    setOriginQuery(''); setOriginSugg([]);
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
    try {
      const plan = await apiService.getTravelPlan(
        originLat, originLng,
        travelDestination.lat, travelDestination.lng,
        travelDestination.place_name,
        travelOrigin?.place_name,
        depIso,
        mode,
      );
      setTravelPlan(plan);
    } catch {
      setTravelPlan(null);
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

  // Compact chip when plan is active and not expanded for editing
  if (travelDestination && useStore.getState().travelPlan && !chipExpanded) {
    const modeLabel = travelModeStore ? '✈️ Musafir trip' : '🚗 Muqeem trip';
    const originLabel = travelOrigin?.place_name ?? 'Current location';
    return (
      <div
        className="mx-3 mb-2 bg-teal-50 border border-teal-200 rounded-xl px-3 py-2 flex items-center justify-between gap-2 cursor-pointer hover:bg-teal-100 transition-colors"
        onClick={() => setChipExpanded(true)}
      >
        <div className="min-w-0">
          <p className="text-xs font-semibold text-teal-700">{modeLabel} <span className="text-teal-400 font-normal text-xs">· tap to edit</span></p>
          <p className="text-xs text-teal-900 truncate">
            <span className="font-medium">{originLabel}</span>
            <span className="mx-1 text-teal-400">→</span>
            <span className="font-medium">{travelDestination.place_name}</span>
          </p>
          {travelDepartureTime && (
            <p className="text-xs text-teal-600 mt-0.5">
              Departs {new Date(travelDepartureTime).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
            </p>
          )}
        </div>
        <button onClick={(e) => { e.stopPropagation(); clearAll(); }} className="text-teal-400 hover:text-teal-700 text-lg leading-none flex-shrink-0">✕</button>
      </div>
    );
  }

  // Collapsed "Plan a trip" entry row
  if (!formExpanded && !travelDestination) {
    return (
      <button
        onClick={() => setFormExpanded(true)}
        className="mx-3 mb-2 w-[calc(100%-1.5rem)] flex items-center justify-between bg-white border border-gray-200 rounded-xl px-3 py-2.5 text-sm text-gray-500 hover:border-teal-300 hover:text-teal-700 transition-colors shadow-sm"
      >
        <span>🗺 Plan a trip</span>
        <span className="text-xs text-gray-400">→</span>
      </button>
    );
  }

  return (
    <div className="mx-3 mb-2 bg-white border border-teal-200 rounded-xl p-3 shadow-sm space-y-2">
      {/* Header with mode badge and cancel */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-bold text-teal-700 uppercase tracking-wider">Plan Your Trip</p>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${travelModeStore ? 'bg-teal-100 text-teal-700' : 'bg-gray-100 text-gray-600'}`}>
            {travelModeStore ? '✈️ Musafir' : '🏠 Muqeem'}
          </span>
          <button
            onClick={() => setFormExpanded(false)}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            title="Close trip planner"
          >✕</button>
        </div>
      </div>
      {travelModeStore && (
        <p className="text-xs text-teal-600">Prayer combining (Jam') enabled along route</p>
      )}

      {/* From */}
      <div className="relative">
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
      </div>

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

      {/* Departure time */}
      <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1.5">
        <span className="text-sm">🕐</span>
        <input
          type="datetime-local"
          value={departureInput}
          onChange={(e) => setDepartureInput(e.target.value)}
          className="flex-1 text-sm outline-none bg-transparent text-gray-700 min-w-0"
        />
      </div>

      {/* Long-trip Musafir suggestion */}
      {longTripKm !== null && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-2">
          <p className="text-xs font-semibold text-amber-800">
            Long trip — ~{Math.round(longTripKm / 1.609)} miles
          </p>
          <p className="text-xs text-amber-700">
            As Musafir you can combine prayers along the route (Dhuhr+Asr, Maghrib+Isha).
            Consider switching to Musafir mode.
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => { setTravelMode(true); executePlan('travel'); }}
              className="flex-1 bg-teal-600 text-white text-xs font-semibold py-1.5 rounded-lg hover:bg-teal-700 transition-colors"
            >
              ✈️ Switch to Musafir
            </button>
            <button
              onClick={() => executePlan('driving')}
              className="flex-1 bg-white border border-gray-300 text-gray-600 text-xs font-semibold py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Plan as Muqeem
            </button>
          </div>
        </div>
      )}

      {longTripKm === null && (
        <button
          onClick={handlePlan}
          disabled={!travelDestination}
          className="w-full bg-teal-600 text-white text-sm font-semibold py-2 rounded-lg hover:bg-teal-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          Plan My Prayers
        </button>
      )}
    </div>
  );
}

// ─── Travel Plan View ────────────────────────────────────────────────────────

function TravelItineraryCard({ itinerary, index }: { itinerary: TripItinerary; index: number }) {
  const setSelectedMosqueId = useStore((s) => s.setSelectedMosqueId);
  const setMapCollapsed     = useStore((s) => s.setMapCollapsed);
  const setMapFocusCoords   = useStore((s) => s.setMapFocusCoords);
  const travelOrigin        = useStore((s) => s.travelOrigin);
  const travelDestination   = useStore((s) => s.travelDestination);
  const userLocation        = useStore((s) => s.userLocation);
  const [expanded, setExpanded] = useState(true);
  const [copied, setCopied] = useState(false);

  const optionIcons: Record<string, string> = {
    pray_before:    '📍',
    combine_early:  '⏩',
    combine_late:   '⏪',
    at_destination: '🏁',
    separate:       '🔀',
    stop_for_fajr:  '🌅',
    no_option:      '⚠️',
  };

  return (
    <div className={`mx-3 bg-white border rounded-xl shadow-sm ${itinerary.feasible ? 'border-gray-200' : 'border-gray-200 opacity-60'}`}>
      {/* Header — tap to expand/collapse */}
      <button
        className="w-full text-left px-3 pt-3 pb-2"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs font-bold text-teal-700 uppercase tracking-wide">Option {index + 1}</p>
            <p className="text-sm font-semibold text-gray-800 mt-0.5 leading-snug">{itinerary.label}</p>
          </div>
          <div className="text-right shrink-0">
            {itinerary.total_detour_minutes > 0 && (
              <p className="text-xs text-gray-500">+{itinerary.total_detour_minutes} min</p>
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
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-sm">{pc.emoji}</span>
                  <span className="text-xs font-semibold text-gray-700">{pc.label}</span>
                  {pc.option.combination_label && (
                    <span className="text-xs bg-teal-50 text-teal-700 border border-teal-200 px-1.5 py-0.5 rounded-full">
                      {pc.option.combination_label}
                    </span>
                  )}
                </div>
                {/* Description */}
                <p className="text-xs text-gray-500 mb-1">{icon} {pc.option.description}</p>
                {/* Mosque stops — tappable */}
                {pc.option.stops.map((stop: TravelStop, j: number) => (
                  <button
                    key={j}
                    className="w-full text-left text-xs bg-gray-50 rounded-lg px-2.5 py-1.5 mt-1 border border-gray-100 hover:border-teal-300 hover:bg-teal-50 transition-colors"
                    onClick={() => {
                      setSelectedMosqueId(stop.mosque_id);
                      setMapFocusCoords({ lat: stop.mosque_lat, lng: stop.mosque_lng });
                      setMapCollapsed(false);
                    }}
                  >
                    <span className="font-medium text-gray-800">{stop.mosque_name}</span>
                    {stop.mosque_address ? <span className="text-gray-500"> · {stop.mosque_address}</span> : null}
                    {stop.iqama_time ? <span className="text-gray-600"> · Iqama {fmtTime(stop.iqama_time)}</span> : null}
                    <span className="ml-1 text-teal-600"> +{stop.detour_minutes} min detour 📍</span>
                  </button>
                ))}
                {pc.option.note && (
                  <p className="text-xs text-gray-400 mt-1 italic">{pc.option.note}</p>
                )}
              </div>
            );
          })}

          {/* Open in Maps — builds multi-stop route */}
          {(() => {
            const originLat = travelOrigin?.lat ?? userLocation?.latitude;
            const originLng = travelOrigin?.lng ?? userLocation?.longitude;
            const destLat   = travelDestination?.lat;
            const destLng   = travelDestination?.lng;
            if (!originLat || !originLng || !destLat || !destLng) return null;

            // Collect all mosque stops sorted by position in trip, deduplicated by mosque_id
            const seenIds = new Set<string>();
            const waystops = itinerary.pair_choices
              .flatMap((pc: PairChoice) => pc.option.stops)
              .sort((a: TravelStop, b: TravelStop) => a.minutes_into_trip - b.minutes_into_trip)
              .filter((s: TravelStop) => {
                if (seenIds.has(s.mosque_id)) return false;
                seenIds.add(s.mosque_id);
                return true;
              });

            const points: Array<[number, number]> = [
              [originLat, originLng],
              ...waystops.map((s: TravelStop) => [s.mosque_lat, s.mosque_lng] as [number, number]),
              [destLat, destLng],
            ];

            const googleUrl = buildGoogleMapsUrl(points);
            const appleUrl  = buildAppleMapsUrl(points);

            const shareTitle = `Prayer route — Option ${index + 1}`;
            const shareText  = itinerary.summary;

            async function handleShare() {
              if (navigator.share) {
                try {
                  await navigator.share({ title: shareTitle, text: shareText, url: googleUrl });
                  return;
                } catch { /* user cancelled */ }
              }
              // Fallback: copy to clipboard
              try {
                await navigator.clipboard.writeText(googleUrl);
                setCopied(true);
                setTimeout(() => setCopied(false), 2500);
              } catch {
                window.open(googleUrl, '_blank');
              }
            }

            return (
              <div className="flex gap-2 pt-2 border-t border-gray-100">
                <button
                  onClick={() => window.open(googleUrl, '_blank')}
                  className="flex-1 flex items-center justify-center gap-1.5 text-xs font-semibold text-white bg-teal-600 hover:bg-teal-700 rounded-lg py-2 transition-colors"
                >
                  🗺 Google Maps
                </button>
                {IS_IOS && (
                  <button
                    onClick={() => window.open(appleUrl, '_blank')}
                    className="flex-1 flex items-center justify-center gap-1.5 text-xs font-semibold text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg py-2 transition-colors"
                  >
                    🍎 Apple Maps
                  </button>
                )}
                <button
                  onClick={handleShare}
                  className="flex items-center justify-center gap-1 text-xs font-semibold text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-lg px-3 py-2 transition-colors"
                  title="Share route link"
                >
                  {copied ? '✓ Copied' : '📤'}
                </button>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

function TravelPlanView() {
  const travelPlan        = useStore((s) => s.travelPlan);
  const travelPlanLoading = useStore((s) => s.travelPlanLoading);
  const travelDestination = useStore((s) => s.travelDestination);

  if (!travelDestination) return null;

  if (travelPlanLoading) {
    return (
      <div className="mx-3 text-center py-8 text-gray-400 text-sm">
        Planning your prayer route…
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

// ─── Main App ────────────────────────────────────────────────────────────────

function App() {
  const userLocation  = useStore((s) => s.userLocation);
  const setUserLocation = useStore((s) => s.setUserLocation);
  const mosques       = useStore((s) => s.mosques);
  const setMosques    = useStore((s) => s.setMosques);
  const mosquesLoading = useStore((s) => s.mosquesLoading);
  const setMosquesLoading = useStore((s) => s.setMosquesLoading);
  const mosquesError  = useStore((s) => s.mosquesError);
  const setMosquesError = useStore((s) => s.setMosquesError);
  const spots         = useStore((s) => s.spots);
  const setSpots      = useStore((s) => s.setSpots);
  const spotsLoading  = useStore((s) => s.spotsLoading);
  const setSpotsLoading = useStore((s) => s.setSpotsLoading);
  const radiusKm      = useStore((s) => s.radiusKm);
  const denominationFilter = useStore((s) => s.denominationFilter);
  const showSpots     = useStore((s) => s.showSpots);
  const mapCollapsed  = useStore((s) => s.mapCollapsed);
  const setMapCollapsed = useStore((s) => s.setMapCollapsed);
  const travelModeStore = useStore((s) => s.travelMode);
  const travelDestination = useStore((s) => s.travelDestination);
  const setTravelPlan = useStore((s) => s.setTravelPlan);
  const openSheet     = useStore((s) => s.openSheet);

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
    if (!travelDestination) setTravelPlan(null);
  }, [travelDestination]); // eslint-disable-line react-hooks/exhaustive-deps

  async function fetchData(lat: number, lng: number) {
    setMosquesLoading(true);
    setMosquesError(null);
    console.log('[fetchData] lat:', lat, 'lng:', lng, 'radius:', radiusKm, 'travel:', travelModeStore);
    try {
      const res = await apiService.findNearbyMosques(lat, lng, radiusKm, travelModeStore);
      console.log('[fetchData] response:', res);
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

  const topMosque = mosques.find(
    (m) => m.next_catchable && ['can_catch_with_imam', 'can_catch_with_imam_in_progress'].includes(m.next_catchable.status)
  );

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      {/* Header */}
      <header className="bg-gradient-to-r from-teal-700 to-teal-600 px-4 py-0 flex items-stretch justify-between z-10 shadow-md" style={{ minHeight: '52px' }}>
        {/* Left: logo + title */}
        <div className="flex items-center gap-2 min-w-0 py-2">
          <img src="/icons/logo_pin.png" alt="" className="h-8 w-auto object-contain flex-shrink-0 brightness-0 invert opacity-90" />
          <div className="min-w-0">
            <p className="text-sm font-bold text-white leading-tight tracking-tight">Catch a Prayer</p>
            {topMosque && topMosque.next_catchable && (
              <p className="text-xs text-teal-100 font-medium leading-tight truncate max-w-[160px]">{topMosque.next_catchable.message}</p>
            )}
            {!topMosque && userLocation && !mosquesLoading && (
              <p className="text-xs text-teal-200 leading-tight">{mosques.length} mosques nearby</p>
            )}
          </div>
        </div>
        {/* Right: travel toggle + settings — vertically centered */}
        <div className="flex items-center gap-2 flex-shrink-0 py-2">
          <button
            onClick={() => useStore.getState().setTravelMode(!travelModeStore)}
            className={`flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full border transition-colors leading-none ${
              travelModeStore
                ? 'bg-white text-teal-700 border-white'
                : 'bg-transparent text-teal-100 border-teal-400 hover:border-white hover:text-white'
            }`}
            title={travelModeStore
              ? 'Musafir mode ON — prayer combining enabled. Tap to switch to Muqeem (resident) mode.'
              : 'Muqeem mode — tap to activate Musafir (traveler) mode and enable prayer combining (Dhuhr+Asr, Maghrib+Isha)'}
          >
            {travelModeStore ? '✈️ Musafir' : '🏠 Muqeem'}
          </button>
          <button
            onClick={() => openSheet({ type: 'settings' })}
            className="flex items-center justify-center w-8 h-8 hover:bg-teal-600 rounded-lg transition-colors flex-shrink-0"
            aria-label="Settings"
          >
            <img src="/icons/icon_settings.png" alt="Settings" className="w-7 h-7 object-contain brightness-0 invert" />
          </button>
        </div>
      </header>

      {/* Map */}
      <div
        className="relative isolate bg-slate-200 transition-all duration-300"
        style={{ height: mapCollapsed ? '0' : '40vh' }}
      >
        {!mapCollapsed && <MapView />}
      </div>

      {/* Map toggle */}
      <div className="flex justify-center py-1 bg-white border-b border-slate-100 shadow-sm">
        <button
          onClick={() => setMapCollapsed(!mapCollapsed)}
          className="flex items-center gap-1 text-xs text-slate-500 hover:text-teal-700 font-medium transition-colors py-0.5 px-3"
        >
          <span>{mapCollapsed ? '▼' : '▲'}</span>
          <span>{mapCollapsed ? 'Show map' : 'Hide map'}</span>
        </button>
      </div>

      {/* Scrollable list */}
      <div className="flex-1 overflow-y-auto px-3 pt-4 pb-24 space-y-4">

        {/* Trip planner — always shown (collapsed by default) */}
        <DestinationInput />

        {/* Loading */}
        {mosquesLoading && (
          <div className="flex flex-col items-center py-10 gap-3 text-slate-400">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-slate-200 border-t-teal-600" />
            <p className="text-sm">Finding mosques nearby…</p>
          </div>
        )}

        {/* Error */}
        {mosquesError && !mosquesLoading && (
          <div className="bg-red-50 border border-red-200 rounded-2xl p-4 text-sm text-red-700">
            {mosquesError}
            {userLocation && (
              <button
                onClick={() => fetchData(userLocation.latitude, userLocation.longitude)}
                className="mt-2 block text-red-600 underline font-medium"
              >
                Try again
              </button>
            )}
          </div>
        )}

        {/* No location yet */}
        {!userLocation && !mosquesLoading && !mosquesError && (
          <div className="flex flex-col items-center py-16 gap-2 text-slate-400">
            <span className="text-3xl">📍</span>
            <p className="text-sm font-medium">Waiting for your location…</p>
          </div>
        )}

        {/* Global prayed banner */}
        {userLocation && !mosquesLoading && <PrayedBanner mosques={mosques} />}

        {/* Travel Prayer Plan — replaces mosque list when a destination is set (any mode) */}
        {travelDestination ? (
          <TravelPlanView />
        ) : (
          /* Mosque cards */
          mosques.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-2.5 px-1">
                <h2 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Nearby Mosques</h2>
                <span className="text-xs bg-slate-200 text-slate-500 font-semibold px-1.5 py-0.5 rounded-full">{mosques.length}</span>
              </div>
              <div className="space-y-2.5">
                {mosques.map((m) => <MosqueCard key={m.id} mosque={m} />)}
              </div>
            </section>
          )
        )}

        {/* Prayer spots */}
        {showSpots && (
          <section>
            <div className="flex items-center justify-between mb-2.5 px-1">
              <div className="flex items-center gap-2">
                <h2 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Prayer Spots</h2>
                {spots.length > 0 && (
                  <span className="text-xs bg-slate-200 text-slate-500 font-semibold px-1.5 py-0.5 rounded-full">{spots.length}</span>
                )}
              </div>
              <button
                onClick={() => openSheet({ type: 'spot_submit' })}
                className="text-xs bg-orange-500 text-white px-3 py-1.5 rounded-full font-semibold hover:bg-orange-600 shadow-sm active:scale-95 transition-all"
              >
                + Add spot
              </button>
            </div>

            {spotsLoading && (
              <p className="text-xs text-slate-400 px-1">Loading spots…</p>
            )}

            {!spotsLoading && spots.length === 0 && userLocation && (
              <p className="text-xs text-slate-400 px-1">No community prayer spots found nearby yet.</p>
            )}

            <div className="space-y-2">
              {spots.map((s) => <SpotCard key={s.id} spot={s} />)}
            </div>
          </section>
        )}

        {/* Last resort — only when no mosque or spot offers a catchable prayer */}
        {userLocation && !mosquesLoading && !spotsLoading && (() => {
          const CATCHABLE = new Set([
            'can_catch_with_imam', 'can_catch_with_imam_in_progress',
            'can_pray_solo_at_mosque', 'upcoming',
          ]);
          const hasCatchableMosque = mosques.some(
            (m) => m.next_catchable && CATCHABLE.has(m.next_catchable.status)
          );
          const hasActiveSpot = spots.some((s) => s.status === 'active');
          if (hasCatchableMosque || hasActiveSpot) return null;
          return (
            <section>
              <LastResortCard />
            </section>
          );
        })()}
      </div>

      {/* Bottom Sheet */}
      <BottomSheet />
    </div>
  );
}

export default App;
