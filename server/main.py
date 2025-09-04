from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv

from models import LocationRequest, MosqueResponse, UserSettings, Mosque, Location
from maps_service import GoogleMapsService
from prayer_service import PrayerTimeService

# Load environment variables
load_dotenv()

app = FastAPI(title="Catch a Prayer API", version="2.0.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
try:
    maps_service = GoogleMapsService()
    prayer_service = PrayerTimeService()
except ValueError as e:
    print(f"Service initialization error: {e}")
    maps_service = None
    prayer_service = None

@app.get("/")
async def root():
    return {"message": "Catch a Prayer API v2.0 - Find nearby mosques and prayer times"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "services": {
        "maps": maps_service is not None,
        "prayers": prayer_service is not None
    }}

@app.post("/api/mosques/nearby", response_model=MosqueResponse)
async def find_nearby_mosques(request: LocationRequest):
    print("="*50)
    print(f"CLIENT TIME DEBUG: {request.client_current_time}")
    print(f"CLIENT TIMEZONE DEBUG: {request.client_timezone}")  
    print("="*50)
    """Find mosques near the given location"""
    if not maps_service:
        raise HTTPException(status_code=503, detail="Google Maps service not available")
    
    try:
        # Find nearby mosques
        mosques = await maps_service.find_nearby_mosques(
            request.latitude, 
            request.longitude, 
            request.radius_km or 5
        )
        
        # Get prayer times for each mosque
        for mosque in mosques:
            try:
                prayers = await prayer_service.get_mosque_prayers(mosque)
                mosque.prayers = prayers
                
                # Calculate next prayer info with enhanced status
                if mosque.travel_info and prayers:
                    travel_minutes = mosque.travel_info.duration_seconds // 60
                    next_prayer = prayer_service.get_next_prayer(prayers, travel_minutes, request.client_current_time)
                    mosque.next_prayer = next_prayer
                    
            except Exception as e:
                import traceback
                print(f"Error getting prayers for {mosque.name}: {e}")
                print(f"Full traceback: {traceback.format_exc()}")
                # Continue without prayer times
        
        return MosqueResponse(
            mosques=mosques,
            user_location=Location(
                latitude=request.latitude,
                longitude=request.longitude
            )
        )
        
    except Exception as e:
        print(f"Error finding nearby mosques: {e}")
        raise HTTPException(status_code=500, detail="Failed to find nearby mosques")

@app.get("/api/mosque/{place_id}/next-prayer")
async def get_next_prayer(place_id: str, user_lat: float, user_lng: float):
    """Get next catchable prayer for a specific mosque"""
    if not maps_service or not prayer_service:
        raise HTTPException(status_code=503, detail="Services not available")
    
    try:
        # Create a temporary mosque object to get prayers
        temp_mosque = Mosque(
            place_id=place_id,
            name="",
            location=Location(latitude=0, longitude=0)
        )
        
        prayers = await prayer_service.get_mosque_prayers(temp_mosque)
        
        # Get travel info
        # This is simplified - in practice you'd get the mosque location first
        travel_info = await maps_service._get_travel_info(
            (user_lat, user_lng), 
            (0, 0)  # Would need to get actual mosque coordinates
        )
        
        travel_minutes = travel_info.duration_seconds // 60 if travel_info else 15
        next_prayer = prayer_service.get_next_prayer(prayers, travel_minutes)
        
        return next_prayer
        
    except Exception as e:
        print(f"Error getting next prayer: {e}")
        raise HTTPException(status_code=500, detail="Failed to get next prayer")

@app.get("/api/settings", response_model=UserSettings)
async def get_user_settings():
    """Get user settings (returns defaults for now)"""
    return UserSettings()

@app.put("/api/settings", response_model=UserSettings)
async def update_user_settings(settings: UserSettings):
    """Update user settings (simplified - just returns the input)"""
    return settings

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)