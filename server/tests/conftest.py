"""
Test fixtures for Catch a Prayer.

Each test gets a fresh async engine created in its own event loop.
Tables created once via sync engine (avoids async loop issues).
"""
from __future__ import annotations

import os
from datetime import date

os.environ["DATABASE_URL"] = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://cap:cap@localhost:5432/catchaprayer_test",
)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import Base, get_db, set_engine
from app.main import app
from app.models import new_uuid

TABLES_TO_TRUNCATE = [
    "mosque_suggestion_votes", "mosque_suggestions",
    "prayer_spot_verifications", "prayer_spots",
    "prayer_schedules", "jumuah_sessions", "scraping_jobs",
    "mosques",
]

# One-time sync table creation
_tables_created = False

def _ensure_tables():
    global _tables_created
    if _tables_created:
        return
    sync_url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    eng = create_engine(sync_url)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.drop_all(bind=eng)
    Base.metadata.create_all(bind=eng)
    eng.dispose()
    _tables_created = True


# Per-test engine + factory (created in the test's event loop)
@pytest_asyncio.fixture
async def _test_db():
    _ensure_tables()
    eng = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    set_engine(eng, factory)
    yield eng, factory
    # Cleanup
    async with factory() as session:
        for table in TABLES_TO_TRUNCATE:
            await session.execute(text(f"TRUNCATE {table} CASCADE"))
        await session.commit()
    await eng.dispose()


@pytest_asyncio.fixture
async def async_client(_test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def db_session(_test_db):
    _, factory = _test_db
    async with factory() as session:
        yield session


# ─── Seed Helpers ─────────────────────────────────────────────────────────────

async def seed_mosque_direct(
    *,
    name: str = "Test Mosque",
    lat: float = 40.7128,
    lng: float = -74.0060,
    timezone_str: str = "America/New_York",
    schedule: dict | None = None,
) -> str:
    from app.database import _session_factory
    mosque_id = new_uuid()
    async with _session_factory() as session:
        await session.execute(text("""
            INSERT INTO mosques (id, name, lat, lng, geom, timezone, country, is_active, verified, places_enriched)
            VALUES (:id, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                    :tz, 'US', true, false, false)
        """), {"id": mosque_id, "name": name, "lat": lat, "lng": lng, "tz": timezone_str})

        if schedule:
            today = date.today()
            params = {"id": new_uuid(), "mosque_id": mosque_id, "date": today}
            for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
                params[f"{prayer}_adhan"] = schedule.get(f"{prayer}_adhan")
                params[f"{prayer}_iqama"] = schedule.get(f"{prayer}_iqama")
                params[f"{prayer}_adhan_source"] = "calculated"
                params[f"{prayer}_iqama_source"] = "estimated"
                params[f"{prayer}_adhan_confidence"] = "medium"
                params[f"{prayer}_iqama_confidence"] = "low"
            params["sunrise"] = schedule.get("sunrise", "06:30")
            params["sunrise_source"] = "calculated"
            cols = ", ".join(params.keys())
            vals = ", ".join(f":{k}" for k in params.keys())
            await session.execute(text(f"INSERT INTO prayer_schedules ({cols}) VALUES ({vals})"), params)
        await session.commit()
    return mosque_id


async def seed_spot_direct(
    *,
    name: str = "Test Spot",
    lat: float = 40.7128,
    lng: float = -74.0060,
    session_id: str = "test-session-001",
    status: str = "active",
    verification_count: int = 3,
) -> str:
    from app.database import _session_factory
    spot_id = new_uuid()
    async with _session_factory() as session:
        await session.execute(text("""
            INSERT INTO prayer_spots (
                id, name, spot_type, lat, lng, geom, timezone, country,
                submitted_by_session, status, verification_count, rejection_count
            ) VALUES (
                :id, :name, 'prayer_room', :lat, :lng,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                'America/New_York', 'US',
                :session_id, :status, :vc, 0
            )
        """), {
            "id": spot_id, "name": name, "lat": lat, "lng": lng,
            "session_id": session_id, "status": status, "vc": verification_count,
        })
        await session.commit()
    return spot_id


# Backward-compat
async def seed_mosque(session, **kwargs):
    return await seed_mosque_direct(**kwargs)

async def seed_spot(session, **kwargs):
    return await seed_spot_direct(**kwargs)

def get_test_engine():
    from app.database import _engine, _session_factory
    return _engine, _session_factory


NYC_SCHEDULE = {
    "fajr_adhan": "05:30", "fajr_iqama": "05:50",
    "dhuhr_adhan": "12:30", "dhuhr_iqama": "13:00",
    "asr_adhan": "16:00", "asr_iqama": "16:15",
    "maghrib_adhan": "19:00", "maghrib_iqama": "19:05",
    "isha_adhan": "20:30", "isha_iqama": "20:45",
    "sunrise": "06:30",
}
