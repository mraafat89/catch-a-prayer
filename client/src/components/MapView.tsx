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

  // Teardrop path: circle top, pointy bottom
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

// ─── Fit bounds when a mosque is selected ────────────────────────────────────

function FitBoundsController() {
  const map              = useMap();
  const selectedMosqueId = useStore((s) => s.selectedMosqueId);
  const mapFocusCoords   = useStore((s) => s.mapFocusCoords);
  const mosques          = useStore((s) => s.mosques);
  const userLocation     = useStore((s) => s.userLocation);

  useEffect(() => {
    if (!userLocation) return;
    // Prefer mosque from nearby list; fall back to explicit focus coords
    const mosque = selectedMosqueId ? mosques.find((m) => m.id === selectedMosqueId) : null;
    const focusLat = mosque ? mosque.location.latitude : mapFocusCoords?.lat;
    const focusLng = mosque ? mosque.location.longitude : mapFocusCoords?.lng;
    if (!focusLat || !focusLng) return;

    const bounds = L.latLngBounds([
      [userLocation.latitude, userLocation.longitude],
      [focusLat, focusLng],
    ]);
    map.fitBounds(bounds, { padding: [52, 52], maxZoom: 15, animate: true });
  }, [selectedMosqueId, mapFocusCoords]); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

// ─── Re-center on first location fix ─────────────────────────────────────────

function MapCenterer({ lat, lng }: { lat: number; lng: number }) {
  const map              = useMap();
  const selectedMosqueId = useStore((s) => s.selectedMosqueId);

  useEffect(() => {
    // Don't override a mosque-focused fitBounds
    if (selectedMosqueId) return;
    map.setView([lat, lng], map.getZoom());
  }, [lat, lng, map]); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

// ─── MapView ──────────────────────────────────────────────────────────────────

const MapView: React.FC = () => {
  const userLocation     = useStore((s) => s.userLocation);
  const mosques          = useStore((s) => s.mosques);
  const spots            = useStore((s) => s.spots);
  const showSpots        = useStore((s) => s.showSpots);
  const openSheet        = useStore((s) => s.openSheet);
  const selectedMosqueId = useStore((s) => s.selectedMosqueId);
  const setSelectedMosqueId = useStore((s) => s.setSelectedMosqueId);

  const center: [number, number] = userLocation
    ? [userLocation.latitude, userLocation.longitude]
    : [37.7749, -122.4194];

  return (
    <MapContainer
      center={center}
      zoom={13}
      style={{ height: '100%', width: '100%' }}
      zoomControl={true}
    >
      {/* CartoDB Positron — clean, minimal, elegant */}
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

      {mosques.map((mosque) => {
        const color    = mosqueColor(mosque);
        const selected = mosque.id === selectedMosqueId;
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
            <Tooltip direction="top" offset={[0, -28]} opacity={0.92}>
              <span className="text-xs font-medium">{mosque.name}</span>
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
