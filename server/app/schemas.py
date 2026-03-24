from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class NearbyRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(default=10, ge=1, le=50)
    client_timezone: str
    client_current_time: str  # ISO 8601
    travel_mode: bool = False
    travel_destination_lat: Optional[float] = None
    travel_destination_lng: Optional[float] = None
    prayed_prayers: list[str] = []  # prayers already performed today (pair-level in Musafir mode)


class PrayerTime(BaseModel):
    prayer: str
    adhan_time: Optional[str] = None
    iqama_time: Optional[str] = None
    adhan_source: Optional[str] = None
    iqama_source: Optional[str] = None
    adhan_confidence: Optional[str] = None
    iqama_confidence: Optional[str] = None
    data_freshness: Optional[str] = None


class NextCatchable(BaseModel):
    prayer: str
    status: str
    status_label: str
    message: str
    urgency: str
    iqama_time: Optional[str] = None
    adhan_time: Optional[str] = None
    arrival_time: Optional[str] = None
    minutes_until_iqama: Optional[int] = None
    leave_by: Optional[str] = None
    period_ends_at: Optional[str] = None


class SpecialPrayer(BaseModel):
    prayer_type: str  # 'eid_fitr', 'eid_adha', 'taraweeh', 'tahajjud'
    prayer_time: Optional[str] = None
    takbeer_time: Optional[str] = None
    doors_open_time: Optional[str] = None
    session_number: int = 1
    imam_name: Optional[str] = None
    language: Optional[str] = None
    location_notes: Optional[str] = None
    special_notes: Optional[str] = None
    valid_date: Optional[str] = None


class MosqueResponse(BaseModel):
    id: str
    name: str
    location: dict
    timezone: Optional[str]
    distance_meters: float
    travel_time_minutes: Optional[int]
    travel_time_source: str
    phone: Optional[str]
    website: Optional[str]
    has_womens_section: Optional[bool]
    wheelchair_accessible: Optional[bool]
    denomination: Optional[str] = None
    next_catchable: Optional[NextCatchable]
    catchable_prayers: list[NextCatchable] = []
    travel_combinations: list
    prayers: list[PrayerTime]
    sunrise: Optional[str]
    jumuah_sessions: list
    special_prayers: list[SpecialPrayer] = []


class NearbyResponse(BaseModel):
    mosques: list[MosqueResponse]
    user_location: dict
    request_time: str


# ---------------------------------------------------------------------------
# Prayer Spots
# ---------------------------------------------------------------------------

class SpotNearbyRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(default=10, ge=1, le=50)
    session_id: Optional[str] = None


class SpotResponse(BaseModel):
    id: str
    name: str
    spot_type: str
    location: dict                      # lat, lng, address
    distance_meters: float
    has_wudu_facilities: Optional[bool]
    gender_access: Optional[str]
    is_indoor: Optional[bool]
    operating_hours: Optional[str]
    notes: Optional[str]
    status: str                         # pending / active / rejected
    verification_count: int
    rejection_count: int
    verification_label: str             # human-readable badge text
    last_verified_at: Optional[str]


class SpotNearbyResponse(BaseModel):
    spots: list[SpotResponse]
    user_location: dict


class SpotSubmitRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=500)
    spot_type: str = Field(..., pattern="^(prayer_room|multifaith_room|quiet_room|community_hall|halal_restaurant|campus|rest_area|airport|hospital|office|other)$")
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    has_wudu_facilities: Optional[bool] = None
    gender_access: Optional[str] = Field(default="unknown", pattern="^(all|men_only|women_only|separate_spaces|unknown)$")
    is_indoor: Optional[bool] = None
    operating_hours: Optional[str] = None
    notes: Optional[str] = None
    website: Optional[str] = None
    session_id: str = Field(..., min_length=8, max_length=200)


class SpotSubmitResponse(BaseModel):
    spot_id: str
    status: str
    message: str


class SpotVerifyRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=200)
    is_positive: bool
    attributes: dict = Field(default_factory=dict)


class SpotVerifyResponse(BaseModel):
    spot_id: str
    verification_count: int
    rejection_count: int
    status: str
    verification_label: str


# ---------------------------------------------------------------------------
# Mosque Suggestions (community corrections)
# ---------------------------------------------------------------------------

SUGGESTION_IQAMA_FIELDS = {
    "fajr_iqama", "dhuhr_iqama", "asr_iqama", "maghrib_iqama", "isha_iqama",
}
SUGGESTION_FACILITY_FIELDS = {
    "phone", "website", "has_womens_section", "has_parking", "wheelchair_accessible",
}
SUGGESTION_ALLOWED_FIELDS = SUGGESTION_IQAMA_FIELDS | SUGGESTION_FACILITY_FIELDS


class MosqueSuggestionSubmitRequest(BaseModel):
    mosque_id: str
    field_name: str = Field(..., pattern="^(fajr_iqama|dhuhr_iqama|asr_iqama|maghrib_iqama|isha_iqama|phone|website|has_womens_section|has_parking|wheelchair_accessible)$")
    suggested_value: str = Field(..., min_length=1, max_length=500)
    session_id: str = Field(..., min_length=8, max_length=200)


class MosqueSuggestionResponse(BaseModel):
    id: str
    mosque_id: str
    field_name: str
    suggested_value: str
    current_value: Optional[str]
    status: str
    upvote_count: int
    downvote_count: int
    submitted_by_session: str
    created_at: str


class MosqueSuggestionVoteRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=200)
    is_positive: bool


class MosqueSuggestionVoteResponse(BaseModel):
    suggestion_id: str
    upvote_count: int
    downvote_count: int
    status: str


class MosqueSuggestionsListResponse(BaseModel):
    suggestions: list[MosqueSuggestionResponse]


# ---------------------------------------------------------------------------
# Travel Plan
# ---------------------------------------------------------------------------

class GeocodeRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)

class GeocodeSuggestion(BaseModel):
    place_name: str
    lat: float
    lng: float

class GeocodeResponse(BaseModel):
    suggestions: list[GeocodeSuggestion]

class TravelPlanRequest(BaseModel):
    origin_lat: float
    origin_lng: float
    origin_name: Optional[str] = None          # None = "Current location"
    destination_lat: float
    destination_lng: float
    destination_name: str
    departure_time: Optional[str] = None       # ISO 8601; None = now
    timezone: str = "UTC"
    trip_mode: str = "travel"                  # "travel" (combining allowed) or "driving" (single prayers only)
    waypoints: list[dict] = []                 # [{lat, lng, name}] intermediate stops in order
    prayed_prayers: list[str] = []             # prayers already performed today — excluded from plan

class TravelStop(BaseModel):
    mosque_id: str
    mosque_name: str
    mosque_lat: float
    mosque_lng: float
    mosque_address: Optional[str]
    prayer: str
    estimated_arrival_time: str      # "HH:MM" local time
    minutes_into_trip: int
    detour_minutes: int
    status: str                       # can_catch_with_imam / can_pray_solo_at_mosque
    iqama_time: Optional[str]
    adhan_time: Optional[str]
    google_place_id: Optional[str] = None
    is_prayer_spot: bool = False
    spot_type: Optional[str] = None
    has_wudu: Optional[bool] = None
    is_indoor: Optional[bool] = None

class TravelOption(BaseModel):
    option_type: str  # combine_early / combine_late / separate / pray_before / at_destination
    label: str
    description: str
    prayers: list[str]
    combination_label: Optional[str]  # "Jam' Taqdeem" / "Jam' Ta'kheer" / None
    stops: list[TravelStop]
    feasible: bool
    note: Optional[str]

class TravelPairPlan(BaseModel):
    pair: str        # dhuhr_asr / maghrib_isha / fajr
    label: str       # "Dhuhr + Asr" / "Maghrib + Isha" / "Fajr"
    emoji: str
    options: list[TravelOption]

class RouteInfo(BaseModel):
    distance_meters: float
    duration_minutes: int
    origin_name: str        # "Current location" or user-provided name
    destination_name: str
    route_geometry: list[list[float]] = []  # [[lat, lng], ...] for Leaflet polyline

class PairChoice(BaseModel):
    pair: str
    label: str
    emoji: str
    option: TravelOption

class TripItinerary(BaseModel):
    label: str
    summary: str
    pair_choices: list[PairChoice]
    total_detour_minutes: int
    stop_count: int
    feasible: bool
    route_geometry: list[list[float]] = []  # [[lat, lng], ...] through prayer stops

class TravelPlanResponse(BaseModel):
    route: RouteInfo
    prayer_pairs: list[TravelPairPlan]
    itineraries: list[TripItinerary]
    departure_time: str   # ISO
    estimated_arrival_time: str  # ISO
