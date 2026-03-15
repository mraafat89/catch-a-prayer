import React, { useEffect } from 'react';
import { MapContainer, TileLayer, CircleMarker, useMap } from 'react-leaflet';
import { Mosque } from '../types';
import { useStore } from '../store';

// Color per next_catchable status
const STATUS_COLOR: Record<string, string> = {
  can_catch_with_imam:             '#16a34a', // green-600
  can_catch_with_imam_in_progress: '#ca8a04', // yellow-600
  can_pray_solo_at_mosque:         '#2563eb', // blue-600
  pray_at_nearby_location:         '#ea580c', // orange-600
  missed_make_up:                  '#9ca3af', // gray-400
  upcoming:                        '#9ca3af',
};

function mosqueColor(mosque: Mosque): string {
  if (!mosque.next_catchable) return '#9ca3af';
  return STATUS_COLOR[mosque.next_catchable.status] ?? '#9ca3af';
}

// Re-centers the map when userLocation changes
function MapCenterer({ lat, lng }: { lat: number; lng: number }) {
  const map = useMap();
  useEffect(() => {
    map.setView([lat, lng], map.getZoom());
  }, [lat, lng, map]);
  return null;
}

const MapView: React.FC = () => {
  const userLocation = useStore((s) => s.userLocation);
  const mosques      = useStore((s) => s.mosques);
  const spots        = useStore((s) => s.spots);
  const showSpots    = useStore((s) => s.showSpots);
  const openSheet    = useStore((s) => s.openSheet);

  const center: [number, number] = userLocation
    ? [userLocation.latitude, userLocation.longitude]
    : [37.7749, -122.4194];

  return (
    <MapContainer
      center={center}
      zoom={12}
      style={{ height: '100%', width: '100%' }}
      zoomControl={true}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {userLocation && (
        <>
          <MapCenterer lat={userLocation.latitude} lng={userLocation.longitude} />
          {/* User location pulse */}
          <CircleMarker
            center={[userLocation.latitude, userLocation.longitude]}
            radius={10}
            pathOptions={{ color: '#3b82f6', fillColor: '#3b82f6', fillOpacity: 0.3, weight: 2 }}
          />
          <CircleMarker
            center={[userLocation.latitude, userLocation.longitude]}
            radius={4}
            pathOptions={{ color: '#1d4ed8', fillColor: '#1d4ed8', fillOpacity: 1, weight: 0 }}
          />
        </>
      )}

      {mosques.map((mosque) => (
        <CircleMarker
          key={mosque.id}
          center={[mosque.location.latitude, mosque.location.longitude]}
          radius={8}
          pathOptions={{
            color: mosqueColor(mosque),
            fillColor: mosqueColor(mosque),
            fillOpacity: 0.85,
            weight: 2,
          }}
          eventHandlers={{
            click: () => openSheet({ type: 'mosque_detail', mosque }),
          }}
        />
      ))}

      {showSpots && spots.map((spot) => (
        <CircleMarker
          key={spot.id}
          center={[spot.location.latitude, spot.location.longitude]}
          radius={6}
          pathOptions={{
            color: '#ea580c',
            fillColor: '#fed7aa',
            fillOpacity: 0.8,
            weight: 2,
            dashArray: '4 2',
          }}
          eventHandlers={{
            click: () => openSheet({ type: 'spot_detail', spot }),
          }}
        />
      ))}
    </MapContainer>
  );
};

export default MapView;
