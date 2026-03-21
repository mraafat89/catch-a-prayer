"""
Shared test fixtures for the Catch a Prayer test suite.

Key: We create a FRESH engine inside the test session's event loop, then
monkey-patch app.database to use it. This avoids the "attached to a different
loop" error that occurs when the app's engine was created at import time.
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import app.database as db_module
from app.database import Base, get_db
from app.main import app
from app.models import new_uuid

TABLES_TO_TRUNCATE = [
    "mosque_suggestion_votes", "mosque_suggestions",
    "prayer_spot_verifications", "prayer_spots",
    "prayer_schedules", "jumuah_sessions", "scraping_jobs",
    "mosques",
]

_test_engine = None
_TestSessionLocal = None


@pytest_asyncio.fixture(scope="session")
async def _setup_db():
    """Create a fresh engine in the test event loop and patch the app to use it."""
    global _test_engine, _TestSessionLocal

    # Dispose the old engine's connection pool to avoid stale loop references
    await db_module.engine.dispose()

    _test_engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    _TestSessionLocal = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)

    # Monkey-patch the app's database module so all API handlers use our engine
    db_module.engine = _test_engine
    db_module.AsyncSessionLocal = _TestSessionLocal

    async with _test_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(_setup_db):
    yield
    async with _TestSessionLocal() as session:
        for table in TABLES_TO_TRUNCATE:
            await session.execute(text(f"TRUNCATE {table} CASCADE"))
        await session.commit()


@pytest_asyncio.fixture
async def async_client(_setup_db):
    # Override get_db to use our test session factory
    async def _test_get_db():
        async with _TestSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _test_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session(_setup_db):
    async with _TestSessionLocal() as session:
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
    mosque_id = new_uuid()
    async with _TestSessionLocal() as session:
        await session.execute(text("""
            INSERT INTO mosques (id, name, lat, lng, geom, timezone, country, is_active, verified)
            VALUES (:id, :name, :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                    :tz, 'US', true, false)
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
    spot_id = new_uuid()
    async with _TestSessionLocal() as session:
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


# Backward-compat aliases
async def seed_mosque(session, **kwargs):
    return await seed_mosque_direct(**kwargs)

async def seed_spot(session, **kwargs):
    return await seed_spot_direct(**kwargs)

def get_test_engine():
    return _test_engine, _TestSessionLocal


NYC_SCHEDULE = {
    "fajr_adhan": "05:30", "fajr_iqama": "05:50",
    "dhuhr_adhan": "12:30", "dhuhr_iqama": "13:00",
    "asr_adhan": "16:00", "asr_iqama": "16:15",
    "maghrib_adhan": "19:00", "maghrib_iqama": "19:05",
    "isha_adhan": "20:30", "isha_iqama": "20:45",
    "sunrise": "06:30",
}
