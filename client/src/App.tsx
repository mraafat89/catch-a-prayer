import React, { useEffect, useState } from 'react';
import MapView from './components/MapView';
import { apiService } from './services/api';
import { useStore, SESSION_ID } from './store';
import {
  Mosque, PrayerSpot, PrayerTime,
  STATUS_CONFIG, SPOT_TYPE_LABELS,
  SpotSubmitRequest,
} from './types';

// ─── Helpers ────────────────────────────────────────────────────────────────

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

function distLabel(meters: number): string {
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(1)} km`;
}

// ─── Mosque Card ────────────────────────────────────────────────────────────

const ACTIVE_STATUSES = new Set([
  'can_catch_with_imam', 'can_catch_with_imam_in_progress',
  'can_pray_solo_at_mosque', 'pray_at_nearby_location',
]);

function MosqueCard({ mosque }: { mosque: Mosque }) {
  const openSheet   = useStore((s) => s.openSheet);
  const prayedToday = useStore((s) => s.prayedToday);
  const badge       = dataSourceBadge(mosque.prayers);
  const catchable   = (mosque.catchable_prayers?.length ? mosque.catchable_prayers : (mosque.next_catchable ? [mosque.next_catchable] : []));

  // Hide prayers the user has already marked as done
  const visible = catchable.filter(p => !prayedToday.has(p.prayer));
  if (visible.length === 0) return null;

  const topPrayer = visible[0];
  const cfg = STATUS_CONFIG[topPrayer.status] ?? STATUS_CONFIG['upcoming'];

  return (
    <div
      className={`rounded-xl border p-3 hover:shadow-md transition-shadow ${cfg.bg} ${cfg.border}`}
    >
      <div
        className="flex items-start justify-between gap-2 cursor-pointer"
        onClick={() => openSheet({ type: 'mosque_detail', mosque })}
      >
        <div className="min-w-0">
          <p className="font-semibold text-gray-900 text-sm leading-tight truncate">{mosque.name}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {distLabel(mosque.distance_meters)}
            {mosque.travel_time_minutes ? ` · ${mosque.travel_time_minutes} min drive` : ''}
          </p>
        </div>
        <span className="text-lg flex-shrink-0">{cfg.dot}</span>
      </div>

      <div className="mt-2 space-y-1">
        {visible.map((p) => {
          const pcfg = STATUS_CONFIG[p.status] ?? STATUS_CONFIG['upcoming'];
          return (
            <p key={p.prayer} className={`text-xs font-medium ${pcfg.text}`}>
              {pcfg.dot} {p.message}
            </p>
          );
        })}
      </div>

      <p className={`text-xs mt-1.5 ${badge.color}`} title={badge.title}>{badge.label}</p>
    </div>
  );
}

// ─── Prayer Spot Card ────────────────────────────────────────────────────────

function SpotCard({ spot }: { spot: PrayerSpot }) {
  const openSheet = useStore((s) => s.openSheet);
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
      <div className="flex gap-2 mt-1.5 text-xs text-gray-500">
        {spot.has_wudu_facilities === true && <span>🚿 Wudu</span>}
        {spot.is_indoor === true && <span>🏠 Indoor</span>}
        {spot.gender_access && spot.gender_access !== 'all' && (
          <span>{spot.gender_access === 'men_only' ? '♂ Men' : '♀ Women'}</span>
        )}
      </div>
    </div>
  );
}

// ─── Mosque Detail Sheet ────────────────────────────────────────────────────

function MosqueDetailSheet({ mosque }: { mosque: Mosque }) {
  const closeSheet = useStore((s) => s.closeSheet);
  const nc = mosque.next_catchable;
  const cfg = nc ? (STATUS_CONFIG[nc.status] ?? STATUS_CONFIG['upcoming']) : STATUS_CONFIG['upcoming'];
  const badge = dataSourceBadge(mosque.prayers);

  return (
    <div>
      <div className="flex items-start justify-between mb-3">
        <h2 className="text-lg font-bold text-gray-900 pr-4 leading-tight">{mosque.name}</h2>
        <button onClick={closeSheet} className="text-gray-400 hover:text-gray-600 flex-shrink-0 mt-0.5">✕</button>
      </div>

      {mosque.location.address && (
        <p className="text-sm text-gray-500 mb-3">{mosque.location.address}</p>
      )}

      {nc && (
        <div className={`rounded-lg border px-3 py-2 mb-4 ${cfg.bg} ${cfg.border}`}>
          <p className={`text-sm font-semibold ${cfg.text}`}>{cfg.dot} {nc.status_label}</p>
          <p className={`text-sm mt-0.5 ${cfg.text}`}>{nc.message}</p>
          {nc.iqama_time && (
            <p className="text-xs text-gray-500 mt-1">Iqama: {fmtTime(nc.iqama_time)}</p>
          )}
          {nc.leave_by && (
            <p className="text-xs text-gray-500">Leave by: {fmtTime(nc.leave_by)}</p>
          )}
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
                  <tr key={i} className="border-t border-gray-100">
                    <td className="px-3 py-2 font-medium text-gray-800 capitalize">{p.prayer}</td>
                    <td className="px-3 py-2 text-right text-gray-600">{fmtTime(p.adhan_time)}</td>
                    <td className="px-3 py-2 text-right text-gray-700 font-medium">{fmtTime(p.iqama_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Data source */}
      <p className={`text-xs mb-4 ${badge.color}`} title={badge.title}>{badge.label}</p>

      {/* Action buttons */}
      <div className="grid grid-cols-3 gap-2">
        <a
          href={`https://www.google.com/maps/dir/?api=1&destination=${mosque.location.latitude},${mosque.location.longitude}`}
          target="_blank"
          rel="noopener noreferrer"
          className="bg-green-600 text-white text-xs py-2 px-2 rounded-lg text-center font-medium hover:bg-green-700"
        >
          🧭 Directions
        </a>
        {mosque.phone && (
          <a
            href={`tel:${mosque.phone}`}
            className="bg-gray-600 text-white text-xs py-2 px-2 rounded-lg text-center font-medium hover:bg-gray-700"
          >
            📞 Call
          </a>
        )}
        {mosque.website && (
          <a
            href={mosque.website}
            target="_blank"
            rel="noopener noreferrer"
            className="bg-blue-600 text-white text-xs py-2 px-2 rounded-lg text-center font-medium hover:bg-blue-700"
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
        <button onClick={closeSheet} className="text-gray-400 hover:text-gray-600 flex-shrink-0">✕</button>
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
  const closeSheet    = useStore((s) => s.closeSheet);
  const userLocation  = useStore((s) => s.userLocation);
  const [form, setForm] = useState<Partial<SpotSubmitRequest>>({
    spot_type: 'prayer_room',
    gender_access: 'all',
    is_indoor: true,
    has_wudu_facilities: null,
  });
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone]             = useState(false);
  const [error, setError]           = useState<string | null>(null);

  const set = (k: keyof SpotSubmitRequest, v: unknown) =>
    setForm((f) => ({ ...f, [k]: v }));

  const handleSubmit = async () => {
    if (!form.name?.trim() || !userLocation) return;
    setSubmitting(true);
    setError(null);
    try {
      await apiService.submitSpot({
        name: form.name!,
        spot_type: form.spot_type!,
        latitude: userLocation.latitude,
        longitude: userLocation.longitude,
        address: form.address,
        has_wudu_facilities: form.has_wudu_facilities ?? null,
        gender_access: form.gender_access,
        is_indoor: form.is_indoor ?? null,
        operating_hours: form.operating_hours,
        notes: form.notes,
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
        <div className="text-4xl mb-3">🕌</div>
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
        <button onClick={closeSheet} className="text-gray-400 hover:text-gray-600">✕</button>
      </div>

      <div className="space-y-3">
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

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Address (optional)</label>
          <input
            type="text"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
            placeholder="Street address"
            value={form.address ?? ''}
            onChange={(e) => set('address', e.target.value)}
          />
        </div>

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
          disabled={submitting || !form.name?.trim() || !userLocation}
          className="w-full bg-green-600 text-white py-2.5 rounded-lg font-medium text-sm hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Submitting…' : 'Submit Spot'}
        </button>

        {!userLocation && (
          <p className="text-xs text-gray-500 text-center">Location permission required to submit a spot.</p>
        )}
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

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold text-gray-900">Settings</h2>
        <button onClick={closeSheet} className="text-gray-400 hover:text-gray-600">✕</button>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Search radius: <span className="text-green-700 font-semibold">{radiusKm} km</span>
          </label>
          <input
            type="range" min={1} max={50} step={1}
            value={radiusKm}
            onChange={(e) => setRadiusKm(Number(e.target.value))}
            className="w-full accent-green-600"
          />
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>1 km</span><span>50 km</span>
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

        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-gray-700">Show prayer spots</p>
            <p className="text-xs text-gray-500">Community-added non-mosque locations</p>
          </div>
          <button
            onClick={() => setShowSpots(!showSpots)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
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
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black bg-opacity-30 z-40"
        onClick={useStore.getState().closeSheet}
      />
      {/* Sheet */}
      <div className="fixed bottom-0 left-0 right-0 bg-white rounded-t-2xl shadow-2xl z-50 max-h-[85vh] overflow-y-auto">
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
            <span>{prayed ? `✓ Already prayed ${prayer.charAt(0).toUpperCase() + prayer.slice(1)} today` : `${prayer.charAt(0).toUpperCase() + prayer.slice(1)} time — did you already pray?`}</span>
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

  // Fetch when location or radius changes
  useEffect(() => {
    if (!userLocation) return;
    fetchData(userLocation.latitude, userLocation.longitude);
  }, [userLocation, radiusKm]); // eslint-disable-line react-hooks/exhaustive-deps

  async function fetchData(lat: number, lng: number) {
    setMosquesLoading(true);
    setMosquesError(null);
    try {
      const res = await apiService.findNearbyMosques(lat, lng, radiusKm);
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
      setMosquesError(typeof detail === 'string' ? detail : 'Failed to load mosques.');
    } finally {
      setMosquesLoading(false);
    }

    if (showSpots) {
      setSpotsLoading(true);
      try {
        const res2 = await apiService.findNearbySpots(lat, lng, radiusKm);
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
    <div className="min-h-screen bg-gray-100 flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between z-10">
        <div>
          <h1 className="text-lg font-bold text-gray-900">🕌 Catch a Prayer</h1>
          {topMosque && topMosque.next_catchable && (
            <p className="text-xs text-green-700 font-medium leading-tight">{topMosque.next_catchable.message}</p>
          )}
          {!topMosque && userLocation && !mosquesLoading && (
            <p className="text-xs text-gray-500 leading-tight">{mosques.length} mosques nearby</p>
          )}
        </div>
        <button
          onClick={() => openSheet({ type: 'settings' })}
          className="text-gray-500 hover:text-gray-800 p-1"
          aria-label="Settings"
        >
          ⚙️
        </button>
      </header>

      {/* Map */}
      <div
        className="relative bg-gray-200 transition-all duration-300"
        style={{ height: mapCollapsed ? '0' : '40vh' }}
      >
        {!mapCollapsed && <MapView />}
        {/* Collapse toggle */}
        <button
          onClick={() => setMapCollapsed(!mapCollapsed)}
          className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 bg-white border border-gray-300 rounded-full px-4 py-1 text-xs text-gray-600 shadow z-10 hover:bg-gray-50"
        >
          {mapCollapsed ? '▲ Show map' : '▼ Hide map'}
        </button>
      </div>

      {/* Scrollable list */}
      <div className="flex-1 overflow-y-auto px-3 pt-5 pb-24 space-y-3">

        {/* Loading */}
        {mosquesLoading && (
          <div className="text-center py-8 text-gray-500 text-sm">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-600 mx-auto mb-2" />
            Finding mosques nearby…
          </div>
        )}

        {/* Error */}
        {mosquesError && !mosquesLoading && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
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
          <div className="text-center py-12 text-gray-500 text-sm">
            📍 Waiting for location…
          </div>
        )}

        {/* Global prayed banner */}
        {userLocation && !mosquesLoading && <PrayedBanner mosques={mosques} />}

        {/* Mosque cards */}
        {mosques.length > 0 && (
          <section>
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 px-1">
              Mosques ({mosques.length})
            </h2>
            <div className="space-y-2">
              {mosques.map((m) => <MosqueCard key={m.id} mosque={m} />)}
            </div>
          </section>
        )}

        {/* Prayer spots */}
        {showSpots && (
          <section>
            <div className="flex items-center justify-between mb-2 px-1">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Prayer Spots {spots.length > 0 ? `(${spots.length})` : ''}
              </h2>
              <button
                onClick={() => openSheet({ type: 'spot_submit' })}
                className="text-xs bg-orange-500 text-white px-2 py-1 rounded-full font-medium hover:bg-orange-600"
              >
                + Add spot
              </button>
            </div>

            {spotsLoading && (
              <p className="text-xs text-gray-400 px-1">Loading spots…</p>
            )}

            {!spotsLoading && spots.length === 0 && userLocation && (
              <p className="text-xs text-gray-400 px-1">No community prayer spots found nearby yet.</p>
            )}

            <div className="space-y-2">
              {spots.map((s) => <SpotCard key={s.id} spot={s} />)}
            </div>
          </section>
        )}

        {/* Last resort */}
        {userLocation && !mosquesLoading && (
          <section>
            <LastResortCard />
          </section>
        )}
      </div>

      {/* Bottom Sheet */}
      <BottomSheet />
    </div>
  );
}

export default App;
