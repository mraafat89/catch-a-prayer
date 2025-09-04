import React, { useEffect, useRef, useState } from 'react';
import { Loader } from '@googlemaps/js-api-loader';
import { Mosque } from '../types';

interface MapViewProps {
  mosques: Mosque[];
  userLocation?: { lat: number; lng: number };
  onMosqueClick?: (mosque: Mosque) => void;
}

const GOOGLE_MAPS_API_KEY = process.env.REACT_APP_GOOGLE_MAPS_API_KEY;

const MapView: React.FC<MapViewProps> = ({ mosques, userLocation, onMosqueClick }) => {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<google.maps.Map | null>(null);
  const markersRef = useRef<google.maps.Marker[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const initMap = async () => {
      if (!GOOGLE_MAPS_API_KEY) {
        console.error('Google Maps API key is not configured. Please set REACT_APP_GOOGLE_MAPS_API_KEY in .env file');
        setError('Google Maps API key is not configured');
        return;
      }

      try {
        const loader = new Loader({
          apiKey: GOOGLE_MAPS_API_KEY,
          version: 'weekly',
          libraries: ['places']
        });

        await loader.load();

        if (mapRef.current && !mapInstanceRef.current) {
          const defaultCenter = userLocation || { lat: 37.7749, lng: -122.4194 }; // Default to SF
          
          mapInstanceRef.current = new google.maps.Map(mapRef.current, {
            center: defaultCenter,
            zoom: 9, // Fixed zoom level - not too zoomed in (was 13, now 9 = zoomed out 4 times)
            styles: [
              {
                featureType: 'poi',
                elementType: 'labels',
                stylers: [{ visibility: 'off' }]
              }
            ]
          });

          setIsLoaded(true);
        }
      } catch (error) {
        console.error('Error loading Google Maps:', error);
        setError('Failed to load Google Maps');
      }
    };

    initMap();
  }, [userLocation]);

  useEffect(() => {
    if (!mapInstanceRef.current || !isLoaded) return;

    // Clear existing markers
    markersRef.current.forEach(marker => marker.setMap(null));
    markersRef.current = [];

    // Add user location marker
    if (userLocation) {
      const userMarker = new google.maps.Marker({
        position: userLocation,
        map: mapInstanceRef.current,
        title: 'Your Location',
        icon: {
          url: 'data:image/svg+xml;base64,' + btoa(`
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <circle cx="12" cy="12" r="3" fill="#3b82f6"/>
            </svg>
          `),
          scaledSize: new google.maps.Size(24, 24),
          anchor: new google.maps.Point(12, 12)
        }
      });
      markersRef.current.push(userMarker);
    }

    // Add mosque markers
    mosques.forEach(mosque => {
      const canCatch = mosque.next_prayer?.can_catch;
      const markerColor = canCatch === true ? '#22c55e' : canCatch === false ? '#ef4444' : '#6b7280';
      
      const marker = new google.maps.Marker({
        position: {
          lat: mosque.location.latitude,
          lng: mosque.location.longitude
        },
        map: mapInstanceRef.current,
        title: mosque.name,
        icon: {
          url: 'data:image/svg+xml;base64,' + btoa(`
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="${markerColor}">
              <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
            </svg>
          `),
          scaledSize: new google.maps.Size(32, 32),
          anchor: new google.maps.Point(16, 32)
        }
      });

      // Add click listener
      marker.addListener('click', () => {
        if (onMosqueClick) {
          onMosqueClick(mosque);
        }
      });

      // Add info window
      const infoWindow = new google.maps.InfoWindow({
        content: `
          <div style="padding: 8px; min-width: 200px;">
            <h3 style="margin: 0 0 8px 0; font-weight: bold; color: #1f2937;">${mosque.name}</h3>
            ${mosque.travel_info ? `<p style="margin: 0 0 4px 0; color: #6b7280; font-size: 14px;">📍 ${mosque.travel_info.duration_text} away</p>` : ''}
            ${mosque.next_prayer ? `
              <p style="margin: 0; font-size: 14px; color: ${canCatch ? '#22c55e' : '#ef4444'}; font-weight: 600;">
                ${canCatch ? '✅ Can catch' : '❌ Cannot catch'} ${mosque.next_prayer.prayer}
              </p>
            ` : ''}
            ${mosque.rating ? `<p style="margin: 4px 0 0 0; color: #6b7280; font-size: 14px;">⭐ ${mosque.rating}/5 (${mosque.user_ratings_total} reviews)</p>` : ''}
          </div>
        `
      });

      marker.addListener('click', () => {
        // Close any open info windows
        markersRef.current.forEach(m => {
          if ((m as any).infoWindow) {
            (m as any).infoWindow.close();
          }
        });
        
        infoWindow.open(mapInstanceRef.current, marker);
        (marker as any).infoWindow = infoWindow;
      });

      markersRef.current.push(marker);
    });

    // Auto-fit bounds to show all markers
    if (markersRef.current.length > 0) {
      const bounds = new google.maps.LatLngBounds();
      markersRef.current.forEach(marker => {
        const position = marker.getPosition();
        if (position) bounds.extend(position);
      });
      mapInstanceRef.current.fitBounds(bounds);
      
      // Ensure minimum zoom level (not too zoomed out)
      google.maps.event.addListenerOnce(mapInstanceRef.current, 'bounds_changed', () => {
        if (mapInstanceRef.current && mapInstanceRef.current.getZoom()! > 15) {
          mapInstanceRef.current.setZoom(15);
        }
      });
    }

  }, [mosques, userLocation, isLoaded, onMosqueClick]);

  return (
    <div className="w-full h-full relative">
      <div ref={mapRef} className="w-full h-full rounded-lg" />
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-red-50 rounded-lg border border-red-200">
          <div className="text-center">
            <div className="text-red-500 mb-2">❌</div>
            <p className="text-red-700 font-medium">{error}</p>
            <p className="text-red-600 text-sm mt-1">Check your environment configuration</p>
          </div>
        </div>
      )}
      {!isLoaded && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-100 rounded-lg">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
            <p className="text-gray-600">Loading map...</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default MapView;