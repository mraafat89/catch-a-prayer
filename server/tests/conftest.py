"""
Shared test fixtures for the Catch a Prayer test suite.

Provides:
- test_engine: async SQLAlchemy engine pointing at catchaprayer_test DB
- db_session: per-test async session with transaction rollback isolation
- async_client: httpx AsyncClient wired to the FastAPI app with DB override
- seed_mosque: helper to insert a mosque with prayer schedule
- seed_spot: helper to insert a prayer spot
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Override DATABASE_URL before importing app modules
os.environ["DATABASE_URL"] = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://cap:cap@localhost:5432/catchaprayer_test",
)

from app.database import Base, get_db
from app.main import app
from app.models import new_uuid


# ─── Engine & Session ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for all tests."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database engine, set up PostGIS + tables once per session."""
    url = os.environ["DATABASE_URL"]
    engine = create_async_engine(url, echo=False)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test async session wrapped in a transaction that rolls back after the test."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await trans.rollback()
        await session.close()


@pytest_asyncio.fixture
async def async_client(test_engine, db_session) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient wired to the FastAPI app with test DB session."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ─── Seed Helpers ─────────────────────────────────────────────────────────────

async def seed_mosque(
    db: AsyncSession,
    *,
    name: str = "Test Mosque",
    lat: float = 40.7128,
    lng: float = -74.0060,
    timezone_str: str = "America/New_York",
    schedule: dict | None = None,
) -> str:
    """Insert a mosque and optionally a prayer schedule for today. Returns mosque_id."""
    mosque_id = new_uuid()
    await db.execute(text("""
        INSERT INTO mosques (id, name, lat, lng, geom, timezone, country, is_active, verified)
        VALUES (:id, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                :tz, 'US', true, false)
    """), {"id": mosque_id, "name": name, "lat": lat, "lng": lng, "tz": timezone_str})

    if schedule:
        today = date.today()
        params = {
            "id": new_uuid(),
            "mosque_id": mosque_id,
            "date": today,
        }
        # Fill in prayer time fields from schedule dict
        for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
            params[f"{prayer}_adhan"] = schedule.get(f"{prayer}_adhan")
            params[f"{prayer}_iqama"] = schedule.get(f"{prayer}_iqama")
            params[f"{prayer}_adhan_source"] = schedule.get(f"{prayer}_adhan_source", "calculated")
            params[f"{prayer}_iqama_source"] = schedule.get(f"{prayer}_iqama_source", "estimated")
            params[f"{prayer}_adhan_confidence"] = "medium"
            params[f"{prayer}_iqama_confidence"] = "low"
        params["sunrise"] = schedule.get("sunrise", "06:30")
        params["sunrise_source"] = "calculated"

        cols = ", ".join(params.keys())
        vals = ", ".join(f":{k}" for k in params.keys())
        await db.execute(text(f"INSERT INTO prayer_schedules ({cols}) VALUES ({vals})"), params)

    await db.flush()
    return mosque_id


async def seed_spot(
    db: AsyncSession,
    *,
    name: str = "Test Spot",
    lat: float = 40.7128,
    lng: float = -74.0060,
    session_id: str = "test-session-001",
    status: str = "active",
    verification_count: int = 3,
) -> str:
    """Insert a prayer spot. Returns spot_id."""
    spot_id = new_uuid()
    await db.execute(text("""
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
    await db.flush()
    return spot_id


# ─── Common Test Data ─────────────────────────────────────────────────────────

NYC_SCHEDULE = {
    "fajr_adhan": "05:30", "fajr_iqama": "05:50",
    "dhuhr_adhan": "12:30", "dhuhr_iqama": "13:00",
    "asr_adhan": "16:00", "asr_iqama": "16:15",
    "maghrib_adhan": "19:00", "maghrib_iqama": "19:05",
    "isha_adhan": "20:30", "isha_iqama": "20:45",
    "sunrise": "06:30",
}
