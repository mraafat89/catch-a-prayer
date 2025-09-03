from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, time
from enum import Enum

class PrayerName(str, Enum):
    FAJR = "fajr"
    DHUHR = "dhuhr"
    ASR = "asr"
    MAGHRIB = "maghrib"
    ISHA = "isha"
    JUMAA = "jumaa"

class Location(BaseModel):
    latitude: float
    longitude: float
    address: Optional[str] = None

class Prayer(BaseModel):
    prayer_name: PrayerName
    adhan_time: str
    iqama_time: Optional[str] = None

class TravelInfo(BaseModel):
    distance_meters: int
    duration_seconds: int
    duration_text: str

class NextPrayer(BaseModel):
    prayer: PrayerName
    can_catch: bool
    travel_time_minutes: int
    time_remaining_minutes: int
    arrival_time: datetime

class Mosque(BaseModel):
    place_id: str
    name: str
    location: Location
    phone_number: Optional[str] = None
    website: Optional[str] = None
    rating: Optional[float] = None
    user_ratings_total: Optional[int] = None
    travel_info: Optional[TravelInfo] = None
    next_prayer: Optional[NextPrayer] = None
    prayers: List[Prayer] = []

class LocationRequest(BaseModel):
    latitude: float
    longitude: float
    radius_km: Optional[int] = 5

class MosqueResponse(BaseModel):
    mosques: List[Mosque]
    user_location: Location

class UserSettings(BaseModel):
    max_search_radius: int = 5
    distance_unit: str = "km"
    prayer_buffer_minutes: int = 10
    show_iqama_times: bool = True
    show_adhan_times: bool = True