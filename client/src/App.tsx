import React, { useState, useEffect } from 'react';
import MapView from './components/MapView';
import { apiService } from './services/api';
import { Mosque, Location } from './types';

function App() {
  const [mosques, setMosques] = useState<Mosque[]>([]);
  const [userLocation, setUserLocation] = useState<Location | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedMosque, setSelectedMosque] = useState<Mosque | null>(null);

  // Get user's current location
  useEffect(() => {
    if ("geolocation" in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const location = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude
          };
          setUserLocation(location);
          searchMosques(location);
        },
        (error) => {
          console.error("Error getting location:", error);
          setError("Please enable location access to find nearby mosques");
        },
        {
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 300000 // 5 minutes
        }
      );
    } else {
      setError("Geolocation is not supported by this browser");
    }
  }, []);

  const searchMosques = async (location: Location) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await apiService.findNearbyMosques({
        latitude: location.latitude,
        longitude: location.longitude,
        radius_km: 5,
        client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        client_current_time: new Date().toISOString()
      });
      
      setMosques(response.mosques);
      
      if (response.mosques.length === 0) {
        setError("No mosques found nearby. Try increasing the search radius.");
      }
    } catch (err) {
      console.error("Error finding mosques:", err);
      setError("Failed to find nearby mosques. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleMosqueClick = (mosque: Mosque) => {
    setSelectedMosque(mosque);
  };

  const getStatusMessage = () => {
    if (loading) return "🔍 Searching for nearby mosques...";
    if (error) return `❌ ${error}`;
    if (mosques.length === 0) return "📍 Please enable location access to find mosques";
    
    const catchableMosques = mosques.filter(m => m.next_prayer?.can_catch);
    if (catchableMosques.length > 0) {
      const mosque = catchableMosques[0];
      return `✅ You can catch ${mosque.next_prayer?.prayer} at ${mosque.name}`;
    }
    
    return `📍 Found ${mosques.length} mosques nearby`;
  };

  const formatTime = (timeStr: string) => {
    if (!timeStr || typeof timeStr !== 'string') return 'Invalid time';
    
    try {
      const [hours, minutes] = timeStr.split(':').map(Number);
      if (isNaN(hours) || isNaN(minutes)) return 'Invalid time';
      
      const date = new Date();
      date.setHours(hours, minutes, 0, 0);
      return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    } catch (error) {
      return 'Invalid time';
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <h1 className="text-2xl font-bold text-gray-900">🕌 Catch a Prayer</h1>
          <p className="text-sm text-gray-600 mt-1">Find nearby mosques and prayer times</p>
        </div>
      </header>

      {/* Status Banner */}
      <div className="bg-blue-50 border-b border-blue-200 px-4 py-3">
        <div className="max-w-7xl mx-auto">
          <p className="text-sm text-blue-800 font-medium">{getStatusMessage()}</p>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Map */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-lg shadow-sm border h-96 lg:h-[600px]">
              <MapView
                mosques={mosques}
                userLocation={userLocation ? {
                  lat: userLocation.latitude,
                  lng: userLocation.longitude
                } : undefined}
                onMosqueClick={handleMosqueClick}
              />
            </div>
          </div>

          {/* Mosque List */}
          <div className="space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Nearby Mosques</h2>
            
            {loading && (
              <div className="text-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
                <p className="text-gray-600">Loading mosques...</p>
              </div>
            )}

            {error && !loading && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <p className="text-red-800 text-sm">{error}</p>
                {userLocation && (
                  <button
                    onClick={() => searchMosques(userLocation)}
                    className="mt-2 text-red-600 hover:text-red-800 font-medium text-sm underline"
                  >
                    Try Again
                  </button>
                )}
              </div>
            )}

            {!loading && !error && mosques.length === 0 && (
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                <p className="text-gray-600 text-sm">No mosques found nearby</p>
              </div>
            )}

            {/* Mosque Cards */}
            {mosques.map((mosque) => (
              <div
                key={mosque.place_id}
                className={`bg-white border rounded-lg p-4 cursor-pointer transition-colors hover:bg-gray-50 ${
                  selectedMosque?.place_id === mosque.place_id ? 'ring-2 ring-blue-500' : ''
                }`}
                onClick={() => handleMosqueClick(mosque)}
              >
                <h3 className="font-semibold text-gray-900 mb-2">{mosque.name}</h3>
                
                {mosque.travel_info && (
                  <p className="text-sm text-gray-600 mb-2">
                    📍 {mosque.travel_info.duration_text} away
                  </p>
                )}

                {mosque.next_prayer && (
                  <div className={`text-sm font-medium mb-2 ${
                    mosque.next_prayer.can_catch ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {mosque.next_prayer.can_catch ? '✅ Can catch' : '❌ Cannot catch'} {mosque.next_prayer.prayer}
                  </div>
                )}

                {mosque.prayers.length > 0 && (
                  <div className="text-xs text-gray-500 space-y-1">
                    {mosque.prayers.slice(0, 3).map((prayer, idx) => (
                      <div key={idx} className="flex justify-between">
                        <span className="capitalize">{prayer.prayer_name}:</span>
                        <span>{formatTime(prayer.iqama_time || prayer.adhan_time)}</span>
                      </div>
                    ))}
                    {mosque.prayers.length > 3 && (
                      <div className="text-center text-gray-400">
                        +{mosque.prayers.length - 3} more prayers
                      </div>
                    )}
                  </div>
                )}

                {mosque.rating && (
                  <div className="text-xs text-gray-500 mt-2">
                    ⭐ {mosque.rating}/5 ({mosque.user_ratings_total} reviews)
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Selected Mosque Modal */}
      {selectedMosque && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg max-w-md w-full p-6">
            <div className="flex justify-between items-start mb-4">
              <h2 className="text-xl font-bold text-gray-900">{selectedMosque.name}</h2>
              <button
                onClick={() => setSelectedMosque(null)}
                className="text-gray-400 hover:text-gray-600"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {selectedMosque.next_prayer && (
              <div className={`p-3 rounded-lg mb-4 ${
                selectedMosque.next_prayer.can_catch ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'
              }`}>
                <div className={`font-medium ${
                  selectedMosque.next_prayer.can_catch ? 'text-green-800' : 'text-red-800'
                }`}>
                  {selectedMosque.next_prayer.can_catch ? '✅ You can catch' : '❌ You cannot catch'} {selectedMosque.next_prayer.prayer}
                </div>
                <div className="text-sm text-gray-600 mt-1">
                  Travel time: {selectedMosque.next_prayer.travel_time_minutes} minutes
                </div>
              </div>
            )}

            {/* Prayer Times */}
            {selectedMosque.prayers.length > 0 && (
              <div className="mb-4">
                <h3 className="font-semibold text-gray-900 mb-2">Today's Prayer Times</h3>
                <div className="space-y-2">
                  {selectedMosque.prayers.map((prayer, idx) => (
                    <div key={idx} className="flex justify-between items-center py-2 border-b border-gray-100 last:border-0">
                      <span className="capitalize font-medium text-gray-700">{prayer.prayer_name}</span>
                      <div className="text-right">
                        <div className="font-medium text-gray-900">
                          {formatTime(prayer.iqama_time || prayer.adhan_time)}
                        </div>
                        {prayer.iqama_time && prayer.iqama_time !== prayer.adhan_time && (
                          <div className="text-xs text-gray-500">
                            Adhan: {formatTime(prayer.adhan_time)}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="grid grid-cols-2 gap-3">
              {selectedMosque.website && (
                <a
                  href={selectedMosque.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="bg-blue-600 text-white py-2 px-4 rounded-lg text-center font-medium hover:bg-blue-700 transition-colors"
                >
                  📅 Monthly Times
                </a>
              )}
              <a
                href={`https://www.google.com/maps/dir/?api=1&destination=${selectedMosque.location.latitude},${selectedMosque.location.longitude}`}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-green-600 text-white py-2 px-4 rounded-lg text-center font-medium hover:bg-green-700 transition-colors"
              >
                🧭 Directions
              </a>
              {selectedMosque.phone_number && (
                <a
                  href={`tel:${selectedMosque.phone_number}`}
                  className="bg-gray-600 text-white py-2 px-4 rounded-lg text-center font-medium hover:bg-gray-700 transition-colors"
                >
                  📞 Call
                </a>
              )}
              <button
                onClick={() => {
                  const text = `Check out ${selectedMosque.name} - Next prayer: ${selectedMosque.next_prayer?.prayer || 'TBD'} ${selectedMosque.next_prayer?.can_catch ? '✅ Catchable' : '❌ Not catchable'}`;
                  const url = `https://www.google.com/maps/search/?api=1&query=${selectedMosque.location.latitude},${selectedMosque.location.longitude}`;
                  if (navigator.share) {
                    navigator.share({ title: selectedMosque.name, text, url });
                  } else {
                    navigator.clipboard?.writeText(`${text}\n${url}`);
                    alert('Mosque info copied to clipboard!');
                  }
                }}
                className="bg-purple-600 text-white py-2 px-4 rounded-lg text-center font-medium hover:bg-purple-700 transition-colors"
              >
                🔗 Share
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;