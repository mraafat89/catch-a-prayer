"""
Travel API
==========
Endpoints for route-based travel prayer planning and geocoding.
"""
from __future__ import annotations
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import (
    GeocodeResponse, GeocodeSuggestion,
    TravelPlanRequest, TravelPlanResponse,
)
from app.services.travel_planner import geocode_query, reverse_geocode, build_travel_plan

router = APIRouter(tags=["travel"])


@router.get("/geocode", response_model=GeocodeResponse)
async def geocode(q: str = Query(..., min_length=2, max_length=200)):
    """Geocode a free-text destination query. Returns up to 5 suggestions."""
    results = await geocode_query(q)
    return GeocodeResponse(
        suggestions=[GeocodeSuggestion(**r) for r in results]
    )


@router.get("/geocode/reverse")
async def geocode_reverse(lat: float = Query(...), lng: float = Query(...)):
    """Reverse-geocode coordinates to a human-readable address label."""
    label = await reverse_geocode(lat, lng)
    return {"label": label or ""}


@router.post("/travel/plan", response_model=TravelPlanResponse)
async def travel_plan(
    req: TravelPlanRequest,
    db: AsyncSession = Depends(get_db),
    x_session_id: str | None = Header(None),
):
    """Build a route-based travel prayer plan."""
    import logging
    _log = logging.getLogger("travel_debug")
    _log.info(f"TRAVEL REQUEST: mode={req.trip_mode} prayed={req.prayed_prayers} dep={req.departure_time} "
              f"origin=({req.origin_lat},{req.origin_lng}) dest=({req.destination_lat},{req.destination_lng}) "
              f"waypoints={len(req.waypoints)}")
    # Parse optional departure time
    departure_dt = None
    if req.departure_time:
        try:
            departure_dt = datetime.fromisoformat(req.departure_time)
        except ValueError:
            pass

    try:
        result = await build_travel_plan(
            db=db,
            origin_lat=req.origin_lat,
            origin_lng=req.origin_lng,
            dest_lat=req.destination_lat,
            dest_lng=req.destination_lng,
            destination_name=req.destination_name,
            timezone_str=req.timezone,
            origin_name=req.origin_name or "Current location",
            departure_dt=departure_dt,
            trip_mode=req.trip_mode,
            waypoints=req.waypoints,
            prayed_prayers=set(req.prayed_prayers),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not result:
        raise HTTPException(status_code=503, detail="Could not build travel plan — routing unavailable")
    _log.info(f"TRAVEL RESPONSE: pairs={[pp['pair'] for pp in result.get('prayer_pairs',[])]} "
              f"itineraries={len(result.get('itineraries',[]))} "
              f"pair_details={[(pp['pair'], len(pp['options'])) for pp in result.get('prayer_pairs',[])]}")

    # Log coverage gaps — route prayers where no mosque was found
    try:
        from app.database import engine as _engine
        from sqlalchemy import text as _text
        gap_prayers = []
        for pp in result.get("prayer_pairs", []):
            # If ALL options for a prayer pair are no_option, it's a real gap
            if pp.get("options") and all(o["option_type"] == "no_option" for o in pp["options"]):
                for prayer in pp.get("options", [{}])[0].get("prayers", []):
                    gap_prayers.append(prayer)
        if gap_prayers:
            # Use route midpoint as the gap location
            mid_lat = (req.origin_lat + req.destination_lat) / 2
            mid_lng = (req.origin_lng + req.destination_lng) / 2
            async def _log_gaps():
                async with _engine.begin() as conn:
                    for prayer in gap_prayers:
                        await conn.execute(_text("""
                            INSERT INTO coverage_gaps (id, lat, lng, gap_type, prayer, session_id)
                            VALUES (gen_random_uuid(), :lat, :lng, 'route_no_mosque', :prayer, :sid)
                        """), {"lat": mid_lat, "lng": mid_lng, "prayer": prayer, "sid": x_session_id})
            asyncio.create_task(_log_gaps())
    except Exception:
        pass

    return TravelPlanResponse(**result)
