import React, { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import L from 'leaflet';
import { MapContainer, TileLayer, Marker, CircleMarker, Polyline, useMap, Tooltip } from 'react-leaflet';
import { Mosque } from '../types';
import { useStore } from '../store';
import { useTheme } from '../theme';

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

// Origin / destination circle badges
function createEndpointIcon(label: string, bg: string): L.DivIcon {
  const html = `<div style="background:${bg};color:white;border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;border:2.5px solid white;box-shadow:0 2px 5px rgba(0,0,0,0.35);line-height:1">${label}</div>`;
  return L.divIcon({ html, className: '', iconSize: [28, 28], iconAnchor: [14, 14] });
}

// ─── Fit bounds controller ────────────────────────────────────────────────────

/** Compute sheet visible height directly from React state — avoids CSS var race condition */
function sheetVisiblePx(height: 'peek' | 'half' | 'full'): number {
  if (height === 'full') return window.innerHeight;
  if (height === 'half') return Math.round(window.innerHeight * 0.55);
  return 125; // peek
}

function FitBoundsController() {
  const map                    = useMap();
  const selectedMosqueId       = useStore((s) => s.selectedMosqueId);
  const mapFocusCoords         = useStore((s) => s.mapFocusCoords);
  const mosques                = useStore((s) => s.mosques);
  const userLocation           = useStore((s) => s.userLocation);
  const travelDestination      = useStore((s) => s.travelDestination);
  const travelOrigin           = useStore((s) => s.travelOrigin);
  const travelPlan             = useStore((s) => s.travelPlan);
  const tripWaypoints          = useStore((s) => s.tripWaypoints);
  const tripPlannerOpen        = useStore((s) => s.tripPlannerOpen);
  const selectedItineraryIndex = useStore((s) => s.selectedItineraryIndex);
  const bottomSheetHeight      = useStore((s) => s.bottomSheetHeight);

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
    const root = document.documentElement;
    const topBarBottom = parseFloat(root.style.getPropertyValue('--top-bar-bottom') || getComputedStyle(root).getPropertyValue('--top-bar-bottom')) || 80;
    map.fitBounds(bounds, {
      paddingTopLeft: [40, topBarBottom + 20],
      paddingBottomRight: [40, sheetVisiblePx('half') + 20],
      maxZoom: 15,
      animate: true,
    });
  }, [selectedMosqueId, mapFocusCoords, bottomSheetHeight]); // eslint-disable-line react-hooks/exhaustive-deps

  // 2) Itinerary selected (or sheet height changes, or edit panel closes) — fit route in VISIBLE map area
  useEffect(() => {
    if (tripPlannerOpen) return; // editing in progress — wait for panel to close
    if (selectedItineraryIndex === null || !travelPlan) return;
    const itinerary = travelPlan.itineraries?.[selectedItineraryIndex];
    const root = document.documentElement;
    const topBarBottom = parseFloat(root.style.getPropertyValue('--top-bar-bottom') || getComputedStyle(root).getPropertyValue('--top-bar-bottom')) || 80;
    const sheetVisible = sheetVisiblePx(bottomSheetHeight);

    // Use itinerary route geometry if available; otherwise fall back to all stop coords
    let points: [number, number][] = [];
    if (itinerary?.route_geometry?.length) {
      points = itinerary.route_geometry as [number, number][];
    } else if (itinerary?.pair_choices?.length) {
      for (const pc of itinerary.pair_choices) {
        for (const stop of pc.option.stops) {
          points.push([stop.mosque_lat, stop.mosque_lng]);
        }
      }
    }
    if (points.length < 2) return;
    const bounds = L.latLngBounds(points);
    map.fitBounds(bounds, {
      paddingTopLeft: [40, topBarBottom + 20],
      paddingBottomRight: [40, sheetVisible + 20],
      animate: true,
    });
  }, [selectedItineraryIndex, bottomSheetHeight, tripPlannerOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  // 2) Destination preview: fly to destination when selected (before plan loads)
  useEffect(() => {
    if (!travelDestination || travelPlan) return;
    const zoom = 14;
    const sheetVisible = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue('--sheet-visible')
    ) || 80;
    const offset = sheetVisible / 2;
    const p = map.project([travelDestination.lat, travelDestination.lng], zoom);
    map.flyTo(map.unproject(p.subtract([0, offset]), zoom), zoom, { animate: true, duration: 0.8 });
  }, [travelDestination]); // eslint-disable-line react-hooks/exhaustive-deps

  // 3) Edit mode: fit to show all configured points, accounting for the expanded edit panel height
  useEffect(() => {
    if (!tripPlannerOpen || !travelDestination) return;
    const points: [number, number][] = [];
    const originLat = travelOrigin?.lat ?? userLocation?.latitude;
    const originLng = travelOrigin?.lng ?? userLocation?.longitude;
    if (originLat != null && originLng != null) points.push([originLat, originLng]);
    for (const wp of tripWaypoints) points.push([wp.lat, wp.lng]);
    points.push([travelDestination.lat, travelDestination.lng]);
    if (points.length < 2) return;
    // Delay reading --top-bar-bottom so ResizeObserver has time to measure the expanded edit panel
    const timer = setTimeout(() => {
      const topBarBottom = parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue('--top-bar-bottom')
      ) || 80;
      map.fitBounds(L.latLngBounds(points), {
        paddingTopLeft: [40, topBarBottom + 20],
        paddingBottomRight: [40, 40],
        animate: true,
      });
    }, 350);
    return () => clearTimeout(timer);
  }, [travelDestination, travelOrigin, tripWaypoints, tripPlannerOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  // 4) Trip plan loaded (or edit panel closes) — fit to full route in visible map area
  useEffect(() => {
    if (tripPlannerOpen) return; // editing in progress — wait for panel to close
    if (!travelDestination || !travelPlan) return;

    const root = document.documentElement;
    const topBarBottom = parseFloat(root.style.getPropertyValue('--top-bar-bottom') || getComputedStyle(root).getPropertyValue('--top-bar-bottom')) || 80;
    const sheetVisible = sheetVisiblePx(bottomSheetHeight);

    const points: [number, number][] = [];
    const originLat = travelOrigin?.lat ?? userLocation?.latitude;
    const originLng = travelOrigin?.lng ?? userLocation?.longitude;
    if (originLat != null && originLng != null) points.push([originLat, originLng]);
    points.push([travelDestination.lat, travelDestination.lng]);

    const seen = new Set<string>();
    for (const pair of travelPlan.prayer_pairs) {
      for (const opt of pair.options) {
        if (!opt.feasible) continue;
        for (const stop of opt.stops) {
          const key = `${stop.mosque_lat},${stop.mosque_lng}`;
          if (!seen.has(key)) { seen.add(key); points.push([stop.mosque_lat, stop.mosque_lng]); }
        }
      }
    }

    if (points.length < 2) return;
    map.fitBounds(L.latLngBounds(points), {
      paddingTopLeft: [40, topBarBottom + 20],
      paddingBottomRight: [40, sheetVisible + 20],
      animate: true,
    });
  }, [travelDestination, travelPlan, tripPlannerOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

// ─── Re-center on first location fix ─────────────────────────────────────────

function MapCenterer({ lat, lng }: { lat: number; lng: number }) {
  const map              = useMap();
  const selectedMosqueId = useStore((s) => s.selectedMosqueId);
  const travelDestination = useStore((s) => s.travelDestination);
  const radiusKm          = useStore((s) => s.radiusKm);

  useEffect(() => {
    if (selectedMosqueId || travelDestination) return;
    // Fit to search radius so all nearby mosques are visible
    // Fires on first location fix AND when a trip is cancelled (travelDestination → null)
    const deg = (radiusKm / 111) * 1.1; // ~1.1× for padding
    map.fitBounds(
      [[lat - deg, lng - deg], [lat + deg, lng + deg]],
      { animate: true }
    );
  }, [lat, lng, travelDestination]); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

// ─── Location recenter button (portal — avoids Leaflet z-index conflicts) ─────

function LocationButton() {
  const map               = useMap();
  const userLocation      = useStore((s) => s.userLocation);
  const bottomSheetHeight = useStore((s) => s.bottomSheetHeight);
  const bottomSheet       = useStore((s) => s.bottomSheet); // any modal open (mosque/spot/settings)
  const navShareOpen      = useStore((s) => s.navShareOpen); // navigate action sheet is visible
  const travelPlanLoading = useStore((s) => s.travelPlanLoading);
  const th                = useTheme();
  const [inView, setInView] = useState(true);

  useEffect(() => {
    if (!userLocation) return;
    function check() {
      const bounds = map.getBounds();
      setInView(bounds.contains([userLocation!.latitude, userLocation!.longitude]));
    }
    check();
    map.on('moveend', check);
    return () => { map.off('moveend', check); };
  }, [map, userLocation]); // eslint-disable-line react-hooks/exhaustive-deps

  // Hide when sheet is maximized, any modal is open, nav-share action sheet is showing, or route is loading
  if (!userLocation || bottomSheetHeight === 'full' || bottomSheet !== null || navShareOpen || travelPlanLoading) return null;

  return ReactDOM.createPortal(
    <button
      onClick={() => {
        const targetZoom = Math.max(map.getZoom(), 14);
        const sheetVisible = parseFloat(
          getComputedStyle(document.documentElement).getPropertyValue('--sheet-visible')
        ) || 0;
        // Shift target upward by half the sheet height so the pin lands in the
        // center of the visible map area (above the sheet), not the screen center.
        const offset = sheetVisible / 2;
        const targetPoint = map.project([userLocation.latitude, userLocation.longitude], targetZoom);
        const adjustedLatLng = map.unproject(targetPoint.subtract([0, offset]), targetZoom);
        map.flyTo(adjustedLatLng, targetZoom, { animate: true, duration: 0.8 });
      }}
      title="Go to my location"
      style={{
        position: 'fixed',
        bottom: 'calc(var(--sheet-visible, 125px) + 12px)',
        right: '16px', zIndex: 490,
        background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(8px)',
        border: 'none', borderRadius: '12px', width: '40px', height: '40px',
        boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
      }}
    >
      <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill={inView ? '#9ca3af' : th.hex}>
        <path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z"/>
      </svg>
    </button>,
    document.body
  );
}

// ─── MapView ──────────────────────────────────────────────────────────────────

const MapView: React.FC = () => {
  const th                = useTheme();
  const userLocation      = useStore((s) => s.userLocation);
  const mosques           = useStore((s) => s.mosques);
  const spots             = useStore((s) => s.spots);
  const showSpots         = useStore((s) => s.showSpots);
  const openSheet         = useStore((s) => s.openSheet);
  const setSelectedMosqueId = useStore((s) => s.setSelectedMosqueId);
  const currentSelectedId   = useStore((s) => s.selectedMosqueId);
  const travelDestination        = useStore((s) => s.travelDestination);
  const travelOrigin             = useStore((s) => s.travelOrigin);
  const travelPlan               = useStore((s) => s.travelPlan);
  const selectedItineraryIndex   = useStore((s) => s.selectedItineraryIndex);
  const tripWaypoints            = useStore((s) => s.tripWaypoints);
  const tripPlannerOpen          = useStore((s) => s.tripPlannerOpen);
  const singleMosqueNav          = useStore((s) => s.singleMosqueNav);

  // Fetch real road route from OSRM when a mosque is selected
  const [singleMosqueRoute, setSingleMosqueRoute] = useState<[number, number][] | null>(null);
  useEffect(() => {
    if (!singleMosqueNav || !userLocation) { setSingleMosqueRoute(null); return; }
    let cancelled = false;
    const { latitude: fromLat, longitude: fromLng } = userLocation;
    const { latitude: toLat, longitude: toLng } = singleMosqueNav.location;
    fetch(
      `https://router.project-osrm.org/route/v1/driving/${fromLng},${fromLat};${toLng},${toLat}?overview=full&geometries=geojson`
    )
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        const coords: [number, number][] = data?.routes?.[0]?.geometry?.coordinates;
        if (coords) setSingleMosqueRoute(coords.map(([lng, lat]) => [lat, lng]));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [singleMosqueNav?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const center: [number, number] = userLocation
    ? [userLocation.latitude, userLocation.longitude]
    : [37.7749, -122.4194];

  // In edit mode (tripPlannerOpen), hide route and stops — show only origin/waypoints/destination pins
  const showRoute = !tripPlannerOpen;

  // Show stops from the selected itinerary only; fall back to all feasible stops
  const routeStops: { id: string; lat: number; lng: number; name: string }[] = [];
  if (travelPlan && showRoute) {
    const seen = new Set<string>();
    const itinerary = selectedItineraryIndex != null
      ? travelPlan.itineraries?.[selectedItineraryIndex]
      : null;

    if (itinerary) {
      for (const pc of itinerary.pair_choices) {
        for (const stop of pc.option.stops) {
          if (!seen.has(stop.mosque_id)) {
            seen.add(stop.mosque_id);
            routeStops.push({ id: stop.mosque_id, lat: stop.mosque_lat, lng: stop.mosque_lng, name: stop.mosque_name });
          }
        }
      }
    } else {
      for (const pair of travelPlan.prayer_pairs) {
        for (const opt of pair.options) {
          if (!opt.feasible) continue;
          for (const stop of opt.stops) {
            if (!seen.has(stop.mosque_id)) {
              seen.add(stop.mosque_id);
              routeStops.push({ id: stop.mosque_id, lat: stop.mosque_lat, lng: stop.mosque_lng, name: stop.mosque_name });
            }
          }
        }
      }
    }
  }

  // Use the selected itinerary's route (goes through its prayer stops); fall back to base route
  // Hidden when editing (showRoute=false) or no trip destination
  const selectedItinerary = selectedItineraryIndex != null
    ? travelPlan?.itineraries?.[selectedItineraryIndex]
    : null;
  const routeGeometry = (showRoute && travelDestination)
    ? ((selectedItinerary?.route_geometry?.length ?? 0) > 1
        ? selectedItinerary!.route_geometry!
        : travelPlan?.route?.route_geometry ?? null)
    : null;

  // Theme-colored icons (created per-render so they pick up mode changes)
  const originIcon      = createPinIcon(th.hex, false);
  const destinationIcon = createPinIcon('#dc2626', false);

  // Nearby mosques that are NOT already shown as route stops (avoid duplicate pins)
  const routeStopIds = new Set(routeStops.map((s) => s.id));

  return (
    <MapContainer
      center={center}
      zoom={13}
      style={{ height: '100%', width: '100%' }}
      zoomControl={false}
      attributionControl={false}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
      />

      <FitBoundsController />
      <LocationButton />

      {/* Trip route polyline */}
      {routeGeometry && routeGeometry.length > 1 && (
        <Polyline
          key={`route-${selectedItineraryIndex}-${travelPlan?.departure_time ?? ''}`}
          positions={routeGeometry}
          pathOptions={{ color: th.hex, weight: 4, opacity: 0.7, dashArray: undefined }}
        />
      )}

      {/* Single-mosque route — real road geometry from OSRM */}
      {singleMosqueRoute && !travelDestination && (
        <Polyline
          key={`singlenav-${singleMosqueNav?.id}`}
          positions={singleMosqueRoute}
          pathOptions={{ color: th.hex, weight: 4, opacity: 0.75 }}
        />
      )}

      {userLocation && (
        <>
          <MapCenterer lat={userLocation.latitude} lng={userLocation.longitude} />
          {/* User pulse ring */}
          <CircleMarker
            center={[userLocation.latitude, userLocation.longitude]}
            radius={14}
            pathOptions={{ color: th.hex, fillColor: th.hex, fillOpacity: 0.12, weight: 1.5 }}
          />
          {/* User dot */}
          <CircleMarker
            center={[userLocation.latitude, userLocation.longitude]}
            radius={5}
            pathOptions={{ color: '#fff', fillColor: th.hex, fillOpacity: 1, weight: 2 }}
          />
        </>
      )}

      {/* Origin pin — only when a custom origin is set (not using GPS) */}
      {travelOrigin && (
        <Marker position={[travelOrigin.lat, travelOrigin.lng]} icon={originIcon}>
          <Tooltip permanent direction="top" offset={[0, -30]} opacity={0.95}>
            <span className="text-xs font-semibold">From: {travelOrigin.place_name}</span>
          </Tooltip>
        </Marker>
      )}

      {/* Waypoint pins (A, B, C...) */}
      {tripWaypoints.map((wp, i) => (
        <Marker
          key={`wp-${i}`}
          position={[wp.lat, wp.lng]}
          icon={createEndpointIcon(String.fromCharCode(65 + i), '#64748b')}
        >
          <Tooltip permanent direction="top" offset={[0, -18]} opacity={0.95}>
            <span className="text-xs font-semibold">{String.fromCharCode(65 + i)}: {wp.place_name}</span>
          </Tooltip>
        </Marker>
      ))}

      {/* Destination pin */}
      {travelDestination && (
        <Marker position={[travelDestination.lat, travelDestination.lng]} icon={destinationIcon}>
          <Tooltip permanent direction="top" offset={[0, -30]} opacity={0.95}>
            <span className="text-xs font-semibold">{travelDestination.place_name}</span>
          </Tooltip>
        </Marker>
      )}

      {/* Route mosque stop pins — hidden while editing */}
      {showRoute && routeStops.map((stop) => (
        <Marker
          key={`route-${stop.id}`}
          position={[stop.lat, stop.lng]}
          icon={createPinIcon(th.hex, false)}
          zIndexOffset={500}
        >
          <Tooltip permanent direction="top" offset={[0, -24]} opacity={0.95}>
            <span className={`text-xs font-semibold ${th.text}`}>{stop.name}</span>
          </Tooltip>
        </Marker>
      ))}

      {/* Nearby mosque pins — hidden during trip planning (route stop pins take over) */}
      {!travelDestination && mosques.filter((m) => !routeStopIds.has(m.id)).map((mosque) => {
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
                useStore.getState().setSingleMosqueNav(mosque);
                useStore.getState().setBottomSheetHeight('peek');
              },
            }}
          >
            <Tooltip permanent direction="top" offset={[0, -28]} opacity={0.92}>
              <span className="text-xs font-semibold">{mosque.name}</span>
            </Tooltip>
          </Marker>
        );
      })}

      {showSpots && !travelDestination && spots.map((spot) => (
        <CircleMarker
          key={spot.id}
          center={[spot.location.latitude, spot.location.longitude]}
          radius={6}
          pathOptions={{
            color: th.hex,
            fillColor: th.hexLight,
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
