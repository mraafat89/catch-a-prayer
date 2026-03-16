import React, { useEffect } from 'react';
import L from 'leaflet';
import { MapContainer, TileLayer, Marker, CircleMarker, useMap, Tooltip } from 'react-leaflet';
import { Mosque } from '../types';
import { useStore } from '../store';

// ─── Status colors ────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  can_catch_with_imam:             '#16a34a', // green
  can_catch_with_imam_in_progress: '#ca8a04', // amber
  can_pray_solo_at_mosque:         '#2563eb', // blue
  pray_at_nearby_location:         '#ea580c', // orange
  missed_make_up:                  '#9ca3af', // gray
  upcoming:                        '#9ca3af',
};

function mosqueColor(mosque: Mosque): string {
  if (!mosque.next_catchable) return '#9ca3af';
  return STATUS_COLOR[mosque.next_catchable.status] ?? '#9ca3af';
}

// ─── Custom SVG pin icon ──────────────────────────────────────────────────────

function createPinIcon(color: string, selected: boolean): L.DivIcon {
  const w = selected ? 30 : 22;
  const h = selected ? 40 : 30;
  const cx = w / 2;
  const cy = Math.round(w * 0.47);
  const r  = Math.round(w * 0.24);

  const path = selected
    ? `M15 0C6.716 0 0 6.716 0 15c0 11.25 15 25 15 25S30 26.25 30 15C30 6.716 23.284 0 15 0z`
    : `M11 0C4.925 0 0 4.925 0 11c0 8.25 11 19 11 19S22 19.25 22 11C22 4.925 17.075 0 11 0z`;

  const shadow = selected ? 'drop-shadow(0 2px 3px rgba(0,0,0,0.35))' : 'drop-shadow(0 1px 2px rgba(0,0,0,0.3))';
  const stroke = selected ? 2 : 1.5;

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="filter:${shadow}">
    <path d="${path}" fill="${color}" stroke="white" stroke-width="${stroke}"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="white" fill-opacity="0.92"/>
  </svg>`;

  return L.divIcon({
    html: svg,
    className: '',
    iconSize:   [w, h],
    iconAnchor: [w / 2, h],
  });
}

// Route mosque stop pin (smaller, indigo)
function createRoutePinIcon(): L.DivIcon {
  return createPinIcon('#6366f1', false);
}

// Origin / destination circle badges
function createEndpointIcon(label: string, bg: string): L.DivIcon {
  const html = `<div style="background:${bg};color:white;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;border:2.5px solid white;box-shadow:0 2px 5px rgba(0,0,0,0.35);line-height:1">${label}</div>`;
  return L.divIcon({ html, className: '', iconSize: [28, 28], iconAnchor: [14, 14] });
}

const originIcon      = createEndpointIcon('A', '#0d9488');
const destinationIcon = createEndpointIcon('B', '#dc2626');

// ─── Fit bounds controller ────────────────────────────────────────────────────

function FitBoundsController() {
  const map               = useMap();
  const selectedMosqueId  = useStore((s) => s.selectedMosqueId);
  const mapFocusCoords    = useStore((s) => s.mapFocusCoords);
  const mosques           = useStore((s) => s.mosques);
  const userLocation      = useStore((s) => s.userLocation);
  const travelDestination = useStore((s) => s.travelDestination);
  const travelOrigin      = useStore((s) => s.travelOrigin);
  const travelPlan        = useStore((s) => s.travelPlan);

  // 1) Single mosque selected (from list or route stop card tap)
  useEffect(() => {
    if (!userLocation || (!selectedMosqueId && !mapFocusCoords)) return;
    const mosque = selectedMosqueId ? mosques.find((m) => m.id === selectedMosqueId) : null;
    const focusLat = mosque ? mosque.location.latitude  : mapFocusCoords?.lat;
    const focusLng = mosque ? mosque.location.longitude : mapFocusCoords?.lng;
    if (!focusLat || !focusLng) return;
    const bounds = L.latLngBounds([
      [userLocation.latitude, userLocation.longitude],
      [focusLat, focusLng],
    ]);
    map.fitBounds(bounds, { padding: [52, 52], maxZoom: 15, animate: true });
  }, [selectedMosqueId, mapFocusCoords]); // eslint-disable-line react-hooks/exhaustive-deps

  // 2) Trip: fit to origin + destination (+ all route stops if plan is loaded)
  useEffect(() => {
    if (!travelDestination) return;

    const points: [number, number][] = [];

    const originLat = travelOrigin?.lat ?? userLocation?.latitude;
    const originLng = travelOrigin?.lng ?? userLocation?.longitude;
    if (originLat != null && originLng != null) points.push([originLat, originLng]);
    points.push([travelDestination.lat, travelDestination.lng]);

    if (travelPlan) {
      const seen = new Set<string>();
      for (const pair of travelPlan.prayer_pairs) {
        for (const opt of pair.options) {
          if (!opt.feasible) continue;
          for (const stop of opt.stops) {
            const key = `${stop.mosque_lat},${stop.mosque_lng}`;
            if (!seen.has(key)) {
              seen.add(key);
              points.push([stop.mosque_lat, stop.mosque_lng]);
            }
          }
        }
      }
    }

    if (points.length < 2) return;
    const bounds = L.latLngBounds(points);
    map.fitBounds(bounds, { padding: [60, 60], animate: true });
  }, [travelDestination, travelPlan]); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

// ─── Re-center on first location fix ─────────────────────────────────────────

function MapCenterer({ lat, lng }: { lat: number; lng: number }) {
  const map              = useMap();
  const selectedMosqueId = useStore((s) => s.selectedMosqueId);
  const travelDestination = useStore((s) => s.travelDestination);

  useEffect(() => {
    if (selectedMosqueId || travelDestination) return;
    map.setView([lat, lng], map.getZoom());
  }, [lat, lng, map]); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

// ─── MapView ──────────────────────────────────────────────────────────────────

const MapView: React.FC = () => {
  const userLocation      = useStore((s) => s.userLocation);
  const mosques           = useStore((s) => s.mosques);
  const spots             = useStore((s) => s.spots);
  const showSpots         = useStore((s) => s.showSpots);
  const openSheet         = useStore((s) => s.openSheet);
  const setSelectedMosqueId = useStore((s) => s.setSelectedMosqueId);
  const currentSelectedId   = useStore((s) => s.selectedMosqueId);
  const travelDestination   = useStore((s) => s.travelDestination);
  const travelOrigin        = useStore((s) => s.travelOrigin);
  const travelPlan          = useStore((s) => s.travelPlan);

  const center: [number, number] = userLocation
    ? [userLocation.latitude, userLocation.longitude]
    : [37.7749, -122.4194];

  // Collect unique route mosque stops from the travel plan
  const routeStops: { id: string; lat: number; lng: number; name: string }[] = [];
  if (travelPlan) {
    const seen = new Set<string>();
    for (const pair of travelPlan.prayer_pairs) {
      for (const opt of pair.options) {
        if (!opt.feasible) continue;
        for (const stop of opt.stops) {
          if (!seen.has(stop.mosque_id)) {
            seen.add(stop.mosque_id);
            routeStops.push({
              id: stop.mosque_id,
              lat: stop.mosque_lat,
              lng: stop.mosque_lng,
              name: stop.mosque_name,
            });
          }
        }
      }
    }
  }

  // Nearby mosques that are NOT already shown as route stops (avoid duplicate pins)
  const routeStopIds = new Set(routeStops.map((s) => s.id));

  return (
    <MapContainer
      center={center}
      zoom={13}
      style={{ height: '100%', width: '100%' }}
      zoomControl={true}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
      />

      <FitBoundsController />

      {userLocation && (
        <>
          <MapCenterer lat={userLocation.latitude} lng={userLocation.longitude} />
          {/* User pulse ring */}
          <CircleMarker
            center={[userLocation.latitude, userLocation.longitude]}
            radius={14}
            pathOptions={{ color: '#0d9488', fillColor: '#0d9488', fillOpacity: 0.12, weight: 1.5 }}
          />
          {/* User dot */}
          <CircleMarker
            center={[userLocation.latitude, userLocation.longitude]}
            radius={5}
            pathOptions={{ color: '#fff', fillColor: '#0d9488', fillOpacity: 1, weight: 2 }}
          />
        </>
      )}

      {/* Origin pin — only when a custom origin is set (not using GPS) */}
      {travelOrigin && (
        <Marker position={[travelOrigin.lat, travelOrigin.lng]} icon={originIcon}>
          <Tooltip permanent direction="top" offset={[0, -18]} opacity={0.95}>
            <span className="text-xs font-semibold">From: {travelOrigin.place_name}</span>
          </Tooltip>
        </Marker>
      )}

      {/* Destination pin */}
      {travelDestination && (
        <Marker position={[travelDestination.lat, travelDestination.lng]} icon={destinationIcon}>
          <Tooltip permanent direction="top" offset={[0, -18]} opacity={0.95}>
            <span className="text-xs font-semibold">To: {travelDestination.place_name}</span>
          </Tooltip>
        </Marker>
      )}

      {/* Route mosque stop pins (indigo) */}
      {routeStops.map((stop) => (
        <Marker
          key={`route-${stop.id}`}
          position={[stop.lat, stop.lng]}
          icon={createRoutePinIcon()}
          zIndexOffset={500}
        >
          <Tooltip permanent direction="top" offset={[0, -24]} opacity={0.95}>
            <span className="text-xs font-semibold text-indigo-700">🕌 {stop.name}</span>
          </Tooltip>
        </Marker>
      ))}

      {/* Nearby mosque pins — skip any already shown as route stops */}
      {mosques.filter((m) => !routeStopIds.has(m.id)).map((mosque) => {
        const color    = mosqueColor(mosque);
        const selected = mosque.id === currentSelectedId;
        return (
          <Marker
            key={mosque.id}
            position={[mosque.location.latitude, mosque.location.longitude]}
            icon={createPinIcon(color, selected)}
            zIndexOffset={selected ? 1000 : 0}
            eventHandlers={{
              click: () => {
                setSelectedMosqueId(mosque.id);
                openSheet({ type: 'mosque_detail', mosque });
              },
            }}
          >
            <Tooltip permanent direction="top" offset={[0, -28]} opacity={0.92}>
              <span className="text-xs font-semibold">{mosque.name}</span>
            </Tooltip>
          </Marker>
        );
      })}

      {showSpots && spots.map((spot) => (
        <CircleMarker
          key={spot.id}
          center={[spot.location.latitude, spot.location.longitude]}
          radius={6}
          pathOptions={{
            color: '#ea580c',
            fillColor: '#fed7aa',
            fillOpacity: 0.85,
            weight: 2,
            dashArray: '4 2',
          }}
          eventHandlers={{
            click: () => openSheet({ type: 'spot_detail', spot }),
          }}
        >
          <Tooltip direction="top" offset={[0, -10]} opacity={0.92}>
            <span className="text-xs font-medium">{spot.name}</span>
          </Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
};

export default MapView;
