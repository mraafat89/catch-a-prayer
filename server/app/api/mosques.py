from __future__ import annotations

import traceback
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
import logging

from app.database import get_db
from app.models import Mosque
from app.schemas import NearbyRequest, NearbyResponse
from app.services.mosque_search import find_nearby_mosques

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mosques"])


# NOTE: fixed-path routes must come before path-param routes

@router.get("/mosques/stats")
async def get_mosque_stats(db: AsyncSession = Depends(get_db)):
    """Coverage statistics for the mosque database."""
    result = await db.execute(text("""
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE website IS NOT NULL) as with_website,
            COUNT(*) FILTER (WHERE phone IS NOT NULL) as with_phone,
            COUNT(*) FILTER (WHERE timezone IS NOT NULL) as with_timezone,
            COUNT(*) FILTER (WHERE country = 'US') as in_us,
            COUNT(*) FILTER (WHERE country = 'CA') as in_canada,
            COUNT(*) FILTER (WHERE places_enriched = true) as places_enriched
        FROM mosques
        WHERE is_active = true
    """))
    row = result.mappings().first()
    return dict(row)


@router.post("/mosques/nearby", response_model=NearbyResponse)
async def get_nearby_mosques(
    request: NearbyRequest,
    db: AsyncSession = Depends(get_db),
    x_session_id: str | None = Header(None),
):
    """Find mosques near a location and return prayer catching status for each."""
    try:
        current_time = datetime.fromisoformat(
            request.client_current_time.replace("Z", "+00:00")
        )
    except Exception:
        current_time = datetime.now(timezone.utc)

    logger.info(
        "nearby request: lat=%.5f lng=%.5f radius=%.1f tz=%s",
        request.latitude, request.longitude, request.radius_km, request.client_timezone,
    )
    try:
        mosques = await find_nearby_mosques(
            db=db,
            lat=request.latitude,
            lng=request.longitude,
            radius_km=request.radius_km,
            client_timezone=request.client_timezone,
            current_time=current_time,
            travel_mode=request.travel_mode,
            prayed_prayers=set(request.prayed_prayers),
        )
    except Exception as exc:
        logger.error(
            "find_nearby_mosques failed for (%.4f, %.4f):\n%s",
            request.latitude, request.longitude,
            traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Internal error: {type(exc).__name__}: {exc}")

    logger.info("nearby result: found %d mosques", len(mosques) if mosques else 0)
    if not mosques:
        # Log coverage gap when user searched at max radius and found nothing
        if request.radius_km >= 50:
            try:
                from app.database import engine as _engine
                from sqlalchemy import text as _text
                import asyncio
                async def _log_gap():
                    async with _engine.begin() as conn:
                        await conn.execute(_text("""
                            INSERT INTO coverage_gaps (id, lat, lng, gap_type, radius_km, session_id)
                            VALUES (gen_random_uuid(), :lat, :lng, 'no_nearby_mosque', :radius, :sid)
                        """), {
                            "lat": request.latitude, "lng": request.longitude,
                            "radius": request.radius_km,
                            "sid": x_session_id,
                        })
                asyncio.create_task(_log_gap())
            except Exception:
                pass
        raise HTTPException(
            status_code=404,
            detail={
                "error": "no_mosques_found",
                "message": f"No mosques found within {request.radius_km} km",
                "status_code": 404,
            },
        )

    return {
        "mosques": mosques,
        "user_location": {"latitude": request.latitude, "longitude": request.longitude},
        "request_time": current_time.isoformat(),
    }


@router.get("/mosques/{mosque_id}")
async def get_mosque_detail(
    mosque_id: str,
    client_timezone: str = Query(...),
    client_current_time: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Full mosque detail including today's prayer schedule."""
    result = await db.execute(select(Mosque).where(Mosque.id == mosque_id))
    mosque = result.scalar_one_or_none()

    if not mosque:
        raise HTTPException(
            status_code=404,
            detail={"error": "mosque_not_found", "message": f"No mosque found with ID: {mosque_id}"},
        )

    return {
        "id": mosque.id,
        "name": mosque.name,
        "location": {
            "latitude": mosque.lat,
            "longitude": mosque.lng,
            "address": mosque.address,
            "city": mosque.city,
            "state": mosque.state,
        },
        "timezone": mosque.timezone,
        "phone": mosque.phone,
        "website": mosque.website,
        "has_womens_section": mosque.has_womens_section,
        "wheelchair_accessible": mosque.wheelchair_accessible,
        "denomination": mosque.denomination,
    }
