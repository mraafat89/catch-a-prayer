from __future__ import annotations
import uuid
from datetime import datetime, date, time
from typing import Optional
from sqlalchemy import (
    String, Float, Boolean, Integer, Date, Time, DateTime,
    Text, JSON, ForeignKey, UniqueConstraint, Index, func, ARRAY
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry
from app.database import Base


def new_uuid():
    return str(uuid.uuid4())


class Mosque(Base):
    __tablename__ = "mosques"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)

    # Identity
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    name_arabic: Mapped[Optional[str]] = mapped_column(String(500))

    # Location
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(200))
    state: Mapped[Optional[str]] = mapped_column(String(100))
    zip: Mapped[Optional[str]] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="US")
    timezone: Mapped[Optional[str]] = mapped_column(String(100))  # IANA timezone

    # Contact
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    website: Mapped[Optional[str]] = mapped_column(String(1000))
    email: Mapped[Optional[str]] = mapped_column(String(500))

    # External IDs
    osm_id: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    osm_type: Mapped[Optional[str]] = mapped_column(String(10))  # node / way / relation
    google_place_id: Mapped[Optional[str]] = mapped_column(String(200), unique=True)
    islamicfinder_id: Mapped[Optional[str]] = mapped_column(String(100))

    # Mosque characteristics
    denomination: Mapped[Optional[str]] = mapped_column(String(100))
    denomination_source: Mapped[Optional[str]] = mapped_column(String(30))  # website_scraped / osm / user_submitted
    denomination_enriched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    languages_spoken: Mapped[Optional[list]] = mapped_column(ARRAY(String))
    has_womens_section: Mapped[Optional[bool]] = mapped_column(Boolean)
    has_parking: Mapped[Optional[bool]] = mapped_column(Boolean)
    wheelchair_accessible: Mapped[Optional[bool]] = mapped_column(Boolean)
    capacity: Mapped[Optional[int]] = mapped_column(Integer)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    places_enriched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    prayer_schedules: Mapped[list["PrayerSchedule"]] = relationship(back_populates="mosque", cascade="all, delete-orphan")
    jumuah_sessions: Mapped[list["JumuahSession"]] = relationship(back_populates="mosque", cascade="all, delete-orphan")
    scraping_job: Mapped[Optional["ScrapingJob"]] = relationship(back_populates="mosque", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("mosques_geom_idx", "geom", postgresql_using="gist"),
        Index("mosques_city_state_idx", "city", "state"),
        Index("mosques_country_idx", "country"),
        Index("mosques_active_idx", "is_active"),
    )


class PrayerSchedule(Base):
    __tablename__ = "prayer_schedules"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    mosque_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("mosques.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)

    # Fajr
    fajr_adhan: Mapped[Optional[str]] = mapped_column(String(5))   # HH:MM
    fajr_iqama: Mapped[Optional[str]] = mapped_column(String(5))
    fajr_adhan_source: Mapped[Optional[str]] = mapped_column(String(50))
    fajr_iqama_source: Mapped[Optional[str]] = mapped_column(String(50))
    fajr_adhan_confidence: Mapped[Optional[str]] = mapped_column(String(10))
    fajr_iqama_confidence: Mapped[Optional[str]] = mapped_column(String(10))

    # Sunrise (Fajr period end)
    sunrise: Mapped[Optional[str]] = mapped_column(String(5))
    sunrise_source: Mapped[Optional[str]] = mapped_column(String(50))

    # Dhuhr
    dhuhr_adhan: Mapped[Optional[str]] = mapped_column(String(5))
    dhuhr_iqama: Mapped[Optional[str]] = mapped_column(String(5))
    dhuhr_adhan_source: Mapped[Optional[str]] = mapped_column(String(50))
    dhuhr_iqama_source: Mapped[Optional[str]] = mapped_column(String(50))
    dhuhr_adhan_confidence: Mapped[Optional[str]] = mapped_column(String(10))
    dhuhr_iqama_confidence: Mapped[Optional[str]] = mapped_column(String(10))

    # Asr
    asr_adhan: Mapped[Optional[str]] = mapped_column(String(5))
    asr_iqama: Mapped[Optional[str]] = mapped_column(String(5))
    asr_adhan_source: Mapped[Optional[str]] = mapped_column(String(50))
    asr_iqama_source: Mapped[Optional[str]] = mapped_column(String(50))
    asr_adhan_confidence: Mapped[Optional[str]] = mapped_column(String(10))
    asr_iqama_confidence: Mapped[Optional[str]] = mapped_column(String(10))

    # Maghrib
    maghrib_adhan: Mapped[Optional[str]] = mapped_column(String(5))
    maghrib_iqama: Mapped[Optional[str]] = mapped_column(String(5))
    maghrib_adhan_source: Mapped[Optional[str]] = mapped_column(String(50))
    maghrib_iqama_source: Mapped[Optional[str]] = mapped_column(String(50))
    maghrib_adhan_confidence: Mapped[Optional[str]] = mapped_column(String(10))
    maghrib_iqama_confidence: Mapped[Optional[str]] = mapped_column(String(10))

    # Isha
    isha_adhan: Mapped[Optional[str]] = mapped_column(String(5))
    isha_iqama: Mapped[Optional[str]] = mapped_column(String(5))
    isha_adhan_source: Mapped[Optional[str]] = mapped_column(String(50))
    isha_iqama_source: Mapped[Optional[str]] = mapped_column(String(50))
    isha_adhan_confidence: Mapped[Optional[str]] = mapped_column(String(10))
    isha_iqama_confidence: Mapped[Optional[str]] = mapped_column(String(10))

    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    mosque: Mapped["Mosque"] = relationship(back_populates="prayer_schedules")

    __table_args__ = (
        UniqueConstraint("mosque_id", "date", name="uq_prayer_schedule_mosque_date"),
        Index("prayer_schedules_mosque_date_idx", "mosque_id", "date"),
        Index("prayer_schedules_date_idx", "date"),
    )


class JumuahSession(Base):
    __tablename__ = "jumuah_sessions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    mosque_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("mosques.id", ondelete="CASCADE"), nullable=False)
    valid_date: Mapped[date] = mapped_column(Date, nullable=False)
    session_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    khutba_start: Mapped[Optional[str]] = mapped_column(String(5))
    prayer_start: Mapped[Optional[str]] = mapped_column(String(5))

    imam_name: Mapped[Optional[str]] = mapped_column(String(200))
    imam_title: Mapped[Optional[str]] = mapped_column(String(50))
    imam_is_guest: Mapped[bool] = mapped_column(Boolean, default=False)

    language: Mapped[Optional[str]] = mapped_column(String(100))
    khutba_topic: Mapped[Optional[str]] = mapped_column(Text)
    khutba_series: Mapped[Optional[str]] = mapped_column(Text)

    capacity: Mapped[Optional[int]] = mapped_column(Integer)
    booking_required: Mapped[bool] = mapped_column(Boolean, default=False)
    booking_url: Mapped[Optional[str]] = mapped_column(String(1000))
    special_notes: Mapped[Optional[str]] = mapped_column(Text)

    source: Mapped[Optional[str]] = mapped_column(String(50))
    confidence: Mapped[Optional[str]] = mapped_column(String(10))
    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mosque: Mapped["Mosque"] = relationship(back_populates="jumuah_sessions")

    __table_args__ = (
        UniqueConstraint("mosque_id", "valid_date", "session_number", name="uq_jumuah_session"),
        Index("jumuah_sessions_mosque_date_idx", "mosque_id", "valid_date"),
        Index("jumuah_sessions_date_idx", "valid_date"),
    )


class SpecialPrayer(Base):
    __tablename__ = "special_prayers"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    mosque_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("mosques.id", ondelete="CASCADE"), nullable=False)

    prayer_type: Mapped[str] = mapped_column(String(50), nullable=False)  # eid_al_fitr / eid_al_adha / taraweeh / tahajjud
    valid_date: Mapped[Optional[date]] = mapped_column(Date)
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_until: Mapped[Optional[date]] = mapped_column(Date)
    session_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    prayer_time: Mapped[Optional[str]] = mapped_column(String(5))
    takbeer_time: Mapped[Optional[str]] = mapped_column(String(5))
    doors_open_time: Mapped[Optional[str]] = mapped_column(String(5))

    imam_name: Mapped[Optional[str]] = mapped_column(String(200))
    language: Mapped[Optional[str]] = mapped_column(String(100))
    location_notes: Mapped[Optional[str]] = mapped_column(Text)
    special_notes: Mapped[Optional[str]] = mapped_column(Text)

    source: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("special_prayers_mosque_date_idx", "mosque_id", "valid_date"),
    )


class ScrapingJob(Base):
    __tablename__ = "scraping_jobs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    mosque_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("mosques.id", ondelete="CASCADE"), nullable=False, unique=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    last_attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    tier_reached: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    raw_html_url: Mapped[Optional[str]] = mapped_column(String(1000))
    raw_extracted_json: Mapped[Optional[dict]] = mapped_column(JSONB)
    image_urls_found: Mapped[Optional[list]] = mapped_column(ARRAY(String))

    dates_covered_from: Mapped[Optional[date]] = mapped_column(Date)
    dates_covered_until: Mapped[Optional[date]] = mapped_column(Date)
    scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    mosque: Mapped["Mosque"] = relationship(back_populates="scraping_job")

    __table_args__ = (
        Index("scraping_jobs_status_next_idx", "status", "next_attempt_at"),
        Index("scraping_jobs_priority_idx", "priority", "next_attempt_at"),
    )


class PrayerSpot(Base):
    __tablename__ = "prayer_spots"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)

    # Identity
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    spot_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # prayer_room / multifaith_room / quiet_room / community_hall / halal_restaurant /
    # campus / rest_area / airport / hospital / office / other

    # Location
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(String(200))
    state: Mapped[Optional[str]] = mapped_column(String(100))
    zip: Mapped[Optional[str]] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="US")
    timezone: Mapped[Optional[str]] = mapped_column(String(100))
    google_place_id: Mapped[Optional[str]] = mapped_column(String(200))

    # Facilities
    has_wudu_facilities: Mapped[Optional[bool]] = mapped_column(Boolean)
    gender_access: Mapped[Optional[str]] = mapped_column(String(30), default="unknown")
    # all / men_only / women_only / separate_spaces / unknown
    is_indoor: Mapped[Optional[bool]] = mapped_column(Boolean)
    operating_hours: Mapped[Optional[str]] = mapped_column(String(200))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    website: Mapped[Optional[str]] = mapped_column(String(1000))

    # Submission tracking (anonymous)
    submitted_by_session: Mapped[Optional[str]] = mapped_column(String(200))
    submitted_ip_hash: Mapped[Optional[str]] = mapped_column(String(64))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Community verification state
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending / active / rejected
    verification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    verifications: Mapped[list["PrayerSpotVerification"]] = relationship(
        back_populates="spot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("prayer_spots_geom_idx", "geom", postgresql_using="gist"),
        Index("prayer_spots_status_idx", "status"),
        Index("prayer_spots_city_state_idx", "city", "state"),
    )


class PrayerSpotVerification(Base):
    __tablename__ = "prayer_spot_verifications"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    spot_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("prayer_spots.id", ondelete="CASCADE"), nullable=False)

    session_id: Mapped[str] = mapped_column(String(200), nullable=False)
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64))
    is_positive: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Checklist of confirmed attributes (flexible JSONB)
    attributes: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    spot: Mapped["PrayerSpot"] = relationship(back_populates="verifications")

    __table_args__ = (
        UniqueConstraint("spot_id", "session_id", name="uq_spot_verification"),
        Index("spot_verifications_spot_idx", "spot_id"),
    )


class MosqueSuggestion(Base):
    __tablename__ = "mosque_suggestions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    mosque_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("mosques.id", ondelete="CASCADE"), nullable=False)

    # What is being suggested
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    # Iqama fields: fajr_iqama, dhuhr_iqama, asr_iqama, maghrib_iqama, isha_iqama
    # Facility fields: phone, website, has_womens_section, has_parking, wheelchair_accessible
    suggested_value: Mapped[str] = mapped_column(Text, nullable=False)
    current_value: Mapped[Optional[str]] = mapped_column(Text)

    # Submission tracking (anonymous)
    submitted_by_session: Mapped[str] = mapped_column(String(200), nullable=False)
    submitted_ip_hash: Mapped[Optional[str]] = mapped_column(String(64))

    # Community consensus
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending / accepted / rejected / expired
    upvote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    downvote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Auto-expiry for time-sensitive data
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    votes: Mapped[list["MosqueSuggestionVote"]] = relationship(
        back_populates="suggestion", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("mosque_suggestions_mosque_idx", "mosque_id"),
        Index("mosque_suggestions_status_idx", "status"),
    )


class MosqueSuggestionVote(Base):
    __tablename__ = "mosque_suggestion_votes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    suggestion_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("mosque_suggestions.id", ondelete="CASCADE"), nullable=False)

    session_id: Mapped[str] = mapped_column(String(200), nullable=False)
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64))
    is_positive: Mapped[bool] = mapped_column(Boolean, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    suggestion: Mapped["MosqueSuggestion"] = relationship(back_populates="votes")

    __table_args__ = (
        UniqueConstraint("suggestion_id", "session_id", name="uq_suggestion_vote_session"),
        Index("suggestion_votes_suggestion_idx", "suggestion_id"),
    )


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)

    push_token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    push_platform: Mapped[str] = mapped_column(String(20), nullable=False)  # fcm / webpush
    vapid_endpoint: Mapped[Optional[str]] = mapped_column(Text)
    vapid_p256dh: Mapped[Optional[str]] = mapped_column(Text)
    vapid_auth: Mapped[Optional[str]] = mapped_column(Text)

    location_lat: Mapped[Optional[float]] = mapped_column(Float)
    location_lng: Mapped[Optional[float]] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)

    favorite_mosque_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("mosques.id", ondelete="SET NULL"))

    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=lambda: {
        "fajr":    {"enabled": True,  "before_adhan_min": 30, "before_iqama_min": 15},
        "dhuhr":   {"enabled": True,  "before_adhan_min": 15, "before_iqama_min": 10},
        "asr":     {"enabled": True,  "before_adhan_min": 15, "before_iqama_min": 10},
        "maghrib": {"enabled": True,  "before_adhan_min": 15, "before_iqama_min": 5},
        "isha":    {"enabled": True,  "before_adhan_min": 15, "before_iqama_min": 10},
        "jumuah":  {"enabled": True,  "before_khutba_min": 60},
        "quiet_hours_start": "23:00",
        "quiet_hours_end":   "04:30",
        "fajr_override_quiet": True,
        "travel_buffer_min": 5,
    })

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("push_subscriptions_active_idx", "is_active"),
        Index("push_subscriptions_timezone_idx", "timezone"),
    )
