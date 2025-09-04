from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, time
from dataclasses import dataclass, field
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

class JumaaSession(BaseModel):
    session_time: str  # "12:30 PM"
    imam_name: Optional[str] = None
    imam_title: Optional[str] = None  # "Dr.", "Sheikh", "Imam"
    khutba_topic: Optional[str] = None
    language: Optional[str] = None  # "English", "Arabic", "Mixed"
    duration_minutes: Optional[int] = None
    capacity: Optional[int] = None
    booking_required: bool = False
    special_notes: Optional[str] = None
    series_info: Optional[str] = None  # "Part 2 of 5"

class Prayer(BaseModel):
    prayer_name: PrayerName
    adhan_time: str
    iqama_time: Optional[str] = None
    jumaa_sessions: List[JumaaSession] = []

class TravelInfo(BaseModel):
    distance_meters: int
    duration_seconds: int
    duration_text: str

class PrayerStatus(str, Enum):
    CAN_CATCH_WITH_IMAM = "can_catch_with_imam"
    CAN_CATCH_AFTER_IMAM = "can_catch_after_imam"  
    CAN_CATCH_DELAYED = "can_catch_delayed"  # For Fajr after sunrise
    CANNOT_CATCH = "cannot_catch"
    MISSED = "missed"

class NextPrayer(BaseModel):
    prayer: PrayerName
    status: PrayerStatus
    can_catch: bool  # For backward compatibility
    travel_time_minutes: int
    time_remaining_minutes: int
    arrival_time: datetime
    prayer_time: str  # Actual prayer time (Iqama or Adhan)
    message: str  # User-friendly message
    is_delayed: bool = False  # True for Fajr after sunrise
    time_until_next_prayer: Optional[int] = None  # Minutes until next prayer

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
    client_timezone: Optional[str] = None  # e.g., "America/Los_Angeles"
    client_current_time: Optional[str] = None  # ISO format from client

class MosqueResponse(BaseModel):
    mosques: List[Mosque]
    user_location: Location

class UserSettings(BaseModel):
    max_search_radius: int = 5
    distance_unit: str = "km"
    prayer_buffer_minutes: int = 10
    show_iqama_times: bool = True
    show_adhan_times: bool = True