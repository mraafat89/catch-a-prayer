"""
Travel API
==========
Endpoints for route-based travel prayer planning and geocoding.
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
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
async def travel_plan(req: TravelPlanRequest, db: AsyncSession = Depends(get_db)):
    """Build a route-based travel prayer plan."""
    # Parse optional departure time
    departure_dt = None
    if req.departure_time:
        try:
            departure_dt = datetime.fromisoformat(req.departure_time)
        except ValueError:
            pass

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
    )
    if not result:
        raise HTTPException(status_code=503, detail="Could not build travel plan — routing unavailable")
    return TravelPlanResponse(**result)
