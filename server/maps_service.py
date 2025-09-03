import googlemaps
import os
from typing import List, Optional, Tuple
from models import Mosque, Location, TravelInfo

class GoogleMapsService:
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY environment variable not set")
        self.client = googlemaps.Client(key=self.api_key)
    
    async def find_nearby_mosques(self, lat: float, lng: float, radius_km: int = 5) -> List[Mosque]:
        """Find mosques near the given coordinates"""
        try:
            # Search for mosques using multiple queries
            search_queries = [
                "mosque",
                "masjid", 
                "islamic center"
            ]
            
            all_places = []
            for query in search_queries:
                # Use text search for better results
                places_result = self.client.places_nearby(
                    location=(lat, lng),
                    radius=radius_km * 1000,  # Convert km to meters
                    keyword=query,
                    type="place_of_worship"
                )
                all_places.extend(places_result.get('results', []))
            
            # Remove duplicates based on place_id
            unique_places = {}
            for place in all_places:
                place_id = place.get('place_id')
                if place_id and self._is_mosque(place):
                    unique_places[place_id] = place
            
            # Convert to Mosque objects
            mosques = []
            for place in unique_places.values():
                mosque = await self._create_mosque_from_place(place, (lat, lng))
                if mosque:
                    mosques.append(mosque)
            
            # Sort by distance
            mosques.sort(key=lambda m: m.travel_info.distance_meters if m.travel_info else float('inf'))
            
            return mosques[:20]  # Limit to 20 results
            
        except Exception as e:
            print(f"Error finding nearby mosques: {e}")
            return []
    
    def _is_mosque(self, place: dict) -> bool:
        """Check if a place is likely a mosque"""
        name = place.get('name', '').lower()
        types = place.get('types', [])
        
        # Check if name contains mosque-related keywords
        mosque_keywords = ['mosque', 'masjid', 'islamic', 'muslim', 'center', 'community']
        has_mosque_keyword = any(keyword in name for keyword in mosque_keywords)
        
        # Check if it's a place of worship
        is_worship_place = 'place_of_worship' in types
        
        # Exclude non-mosque places
        exclude_keywords = ['school', 'store', 'restaurant', 'hotel', 'hospital']
        has_exclude_keyword = any(keyword in name for keyword in exclude_keywords)
        
        return has_mosque_keyword and is_worship_place and not has_exclude_keyword
    
    async def _create_mosque_from_place(self, place: dict, user_location: Tuple[float, float]) -> Optional[Mosque]:
        """Create a Mosque object from Google Places result"""
        try:
            place_id = place.get('place_id')
            if not place_id:
                return None
            
            # Get detailed place information
            place_details = self.client.place(
                place_id=place_id,
                fields=['formatted_phone_number', 'website', 'rating', 'user_ratings_total']
            )['result']
            
            location = Location(
                latitude=place['geometry']['location']['lat'],
                longitude=place['geometry']['location']['lng'],
                address=place.get('vicinity', '')
            )
            
            # Get travel information
            travel_info = await self._get_travel_info(user_location, (location.latitude, location.longitude))
            
            return Mosque(
                place_id=place_id,
                name=place.get('name', ''),
                location=location,
                phone_number=place_details.get('formatted_phone_number'),
                website=place_details.get('website'),
                rating=place_details.get('rating'),
                user_ratings_total=place_details.get('user_ratings_total'),
                travel_info=travel_info
            )
            
        except Exception as e:
            print(f"Error creating mosque from place: {e}")
            return None
    
    async def _get_travel_info(self, origin: Tuple[float, float], destination: Tuple[float, float]) -> Optional[TravelInfo]:
        """Get travel time and distance"""
        try:
            directions = self.client.directions(
                origin=origin,
                destination=destination,
                mode="driving",
                departure_time="now"
            )
            
            if directions:
                leg = directions[0]['legs'][0]
                return TravelInfo(
                    distance_meters=leg['distance']['value'],
                    duration_seconds=leg['duration']['value'],
                    duration_text=leg['duration']['text']
                )
            
            return None
            
        except Exception as e:
            print(f"Error getting travel info: {e}")
            return None