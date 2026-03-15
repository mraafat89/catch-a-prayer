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
    next_catchable: Optional[NextCatchable]
    catchable_prayers: list[NextCatchable] = []
    travel_combinations: list
    prayers: list[PrayerTime]
    sunrise: Optional[str]
    jumuah_sessions: list


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
    spot_type: str = Field(..., pattern="^(prayer_room|community_hall|halal_restaurant|campus|rest_area|library|other)$")
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
