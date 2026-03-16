"""
Prayer Spots API
================
Community-verified non-mosque prayer locations.

Endpoints:
  POST /api/spots/nearby       — find spots near a location
  POST /api/spots              — submit a new spot
  POST /api/spots/{id}/verify  — verify or reject a spot

Safety Model (high-recall: catch all bad spots)
------------------------------------------------
New spots are INVISIBLE to all users except the submitter until they receive
at least one external positive verification. This prevents private addresses
and fake locations from ever reaching users.

Identity: session_id (client localStorage UUID) + sha256(client IP) together.
Neither alone is sufficient — both are checked for rate limits and dedup.
"""
from __future__ import annotations

import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.models import new_uuid
from app.schemas import (
    SpotNearbyRequest, SpotNearbyResponse, SpotResponse,
    SpotSubmitRequest, SpotSubmitResponse,
    SpotVerifyRequest, SpotVerifyResponse,
)

# ─── Abuse-protection constants ──────────────────────────────────────────────

# Geographic bounds: contiguous US + Alaska + Canada (rough bounding box)
_LAT_MIN, _LAT_MAX = 24.0, 72.0
_LNG_MIN, _LNG_MAX = -168.0, -52.0

# Rate limits
_MAX_SUBMITS_PER_SESSION_24H = 3
_MAX_SUBMITS_PER_IP_24H = 2
_MAX_VERIFIES_PER_SESSION_24H = 30
_MAX_VERIFIES_PER_IP_24H = 10

# Nearby-dedup radius: reject new submission if an existing (non-rejected) spot
# sits within this distance.
_DEDUP_RADIUS_M = 50

# Simple content-filter patterns
_URL_RE = re.compile(r'https?://|www\.', re.IGNORECASE)
_ALLCAPS_RE = re.compile(r'\b[A-Z]{5,}\b')


def _check_content(value: str | None, label: str) -> None:
    """Raise 422 if value looks like spam/abuse."""
    if not value:
        return
    if _URL_RE.search(value):
        raise HTTPException(status_code=422, detail=f"{label} must not contain URLs")
    caps_words = _ALLCAPS_RE.findall(value)
    if len(caps_words) >= 3:
        raise HTTPException(status_code=422, detail=f"{label} appears to be spam (excessive caps)")


def _ip_hash(request: Request) -> str | None:
    """Return sha256(client_ip), privacy-preserving — never stores raw IP."""
    ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Real-IP", "").strip()
        or (request.client.host if request.client else None)
    )
    if not ip:
        return None
    return hashlib.sha256(ip.encode()).hexdigest()


router = APIRouter(tags=["spots"])

# Net score thresholds
_ACTIVE_THRESHOLD = 3    # net ≥  3 → active
_REJECT_THRESHOLD = -3   # net ≤ -3 → rejected


def _verification_label(v: int, r: int, status: str) -> str:
    if status == "rejected":
        return "Removed by community"
    net = v - r
    if net <= 0 or v == 0:
        return "Reported — not yet verified"
    if v == 1:
        return "Reported by 1 user — tap to confirm"
    if v < 3:
        return f"Reported by {v} users — tap to confirm"
    if v >= 10:
        return f"Highly verified ({v} users)"
    return f"Verified by {v} users"


def _row_to_response(row, distance_m: float) -> SpotResponse:
    return SpotResponse(
        id=row["id"],
        name=row["name"],
        spot_type=row["spot_type"],
        location={
            "latitude": row["lat"],
            "longitude": row["lng"],
            "address": row["address"],
            "city": row["city"],
            "state": row["state"],
        },
        distance_meters=round(distance_m, 1),
        has_wudu_facilities=row["has_wudu_facilities"],
        gender_access=row["gender_access"],
        is_indoor=row["is_indoor"],
        operating_hours=row["operating_hours"],
        notes=row["notes"],
        status=row["status"],
        verification_count=row["verification_count"],
        rejection_count=row["rejection_count"],
        verification_label=_verification_label(
            row["verification_count"], row["rejection_count"], row["status"]
        ),
        last_verified_at=(
            row["last_verified_at"].isoformat()
            if row["last_verified_at"] else None
        ),
    )


@router.post("/spots/nearby", response_model=SpotNearbyResponse)
async def spots_nearby(req: SpotNearbyRequest, db: AsyncSession = Depends(get_db)):
    """Find prayer spots near a location.

    Visibility rules (high-recall safety model):
    - active spots: always shown
    - pending spots with ≥1 external confirmation: shown with warning label
    - pending spots with 0 external confirmations: shown ONLY to their submitter
      (identified by session_id match)
    - rejected spots: never shown
    """
    radius_m = req.radius_km * 1000
    session_id = req.session_id or ""

    result = await db.execute(text("""
        SELECT
            id::text,
            name,
            spot_type,
            lat,
            lng,
            address,
            city,
            state,
            has_wudu_facilities,
            gender_access,
            is_indoor,
            operating_hours,
            notes,
            status,
            verification_count,
            rejection_count,
            last_verified_at,
            ST_Distance(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
            ) AS distance_m
        FROM prayer_spots
        WHERE
            status != 'rejected'
            AND ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius_m
            )
            AND (
                status = 'active'
                OR verification_count >= 1
                OR submitted_by_session = :session_id
            )
        ORDER BY
            CASE WHEN status = 'active' THEN 0 ELSE 1 END ASC,
            distance_m ASC
        LIMIT 20
    """), {
        "lat": req.latitude,
        "lng": req.longitude,
        "radius_m": radius_m,
        "session_id": session_id,
    })

    spots = [_row_to_response(row, row["distance_m"]) for row in result.mappings()]

    return SpotNearbyResponse(
        spots=spots,
        user_location={"latitude": req.latitude, "longitude": req.longitude},
    )


@router.post("/spots", response_model=SpotSubmitResponse, status_code=201)
async def submit_spot(
    req: SpotSubmitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Submit a new community prayer spot."""
    ip_h = _ip_hash(request)

    # ── 1. Geographic bounds ────────────────────────────────────────────────
    if not (_LAT_MIN <= req.latitude <= _LAT_MAX and _LNG_MIN <= req.longitude <= _LNG_MAX):
        raise HTTPException(
            status_code=422,
            detail="Location must be within the United States or Canada",
        )

    # ── 2. Content filter ───────────────────────────────────────────────────
    _check_content(req.name, "Name")
    _check_content(req.notes, "Notes")
    _check_content(req.operating_hours, "Operating hours")
    # Website field may be a URL — only block if it has extra content beyond a URL
    if req.notes and _URL_RE.search(req.notes):
        raise HTTPException(status_code=422, detail="Notes must not contain URLs")

    # ── 3. Rate limit: session ───────────────────────────────────────────────
    rate_result = await db.execute(text("""
        SELECT COUNT(*) AS cnt
        FROM prayer_spots
        WHERE submitted_by_session = :session_id
          AND created_at >= NOW() - INTERVAL '24 hours'
    """), {"session_id": req.session_id})
    if (rate_result.scalar() or 0) >= _MAX_SUBMITS_PER_SESSION_24H:
        raise HTTPException(
            status_code=429,
            detail="You have submitted too many spots today. Please try again tomorrow.",
        )

    # ── 4. Rate limit: IP ────────────────────────────────────────────────────
    if ip_h:
        ip_rate = await db.execute(text("""
            SELECT COUNT(*) AS cnt
            FROM prayer_spots
            WHERE submitted_ip_hash = :ip_hash
              AND created_at >= NOW() - INTERVAL '24 hours'
        """), {"ip_hash": ip_h})
        if (ip_rate.scalar() or 0) >= _MAX_SUBMITS_PER_IP_24H:
            raise HTTPException(
                status_code=429,
                detail="Too many spots submitted from this device today. Please try again tomorrow.",
            )

    # ── 5. Dedup: reject if an existing spot sits within 50 m ───────────────
    dedup_result = await db.execute(text("""
        SELECT id, name FROM prayer_spots
        WHERE status != 'rejected'
          AND ST_DWithin(
              geom::geography,
              ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
              :radius_m
          )
        LIMIT 1
    """), {"lat": req.latitude, "lng": req.longitude, "radius_m": _DEDUP_RADIUS_M})
    existing = dedup_result.mappings().first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A prayer spot already exists at this location: \"{existing['name']}\". "
                   "If it has incorrect information, use the verify/report flow instead.",
        )

    # ── 6. Insert ────────────────────────────────────────────────────────────
    from timezonefinder import TimezoneFinder
    tz = TimezoneFinder().timezone_at(lat=req.latitude, lng=req.longitude) or "UTC"

    spot_id = new_uuid()

    await db.execute(text("""
        INSERT INTO prayer_spots (
            id, name, spot_type,
            lat, lng, geom,
            address, city, state, zip,
            country, timezone,
            has_wudu_facilities, gender_access,
            is_indoor, operating_hours, notes, website,
            submitted_by_session, submitted_ip_hash, status,
            verification_count, rejection_count
        ) VALUES (
            :id, :name, :spot_type,
            :lat, :lng, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
            :address, :city, :state, :zip,
            'US', :timezone,
            :wudu, :gender,
            :indoor, :hours, :notes, :website,
            :session_id, :ip_hash, 'pending',
            0, 0
        )
    """), {
        "id": spot_id,
        "name": req.name,
        "spot_type": req.spot_type,
        "lat": req.latitude,
        "lng": req.longitude,
        "address": req.address,
        "city": req.city,
        "state": req.state,
        "zip": req.zip,
        "timezone": tz,
        "wudu": req.has_wudu_facilities,
        "gender": req.gender_access or "unknown",
        "indoor": req.is_indoor,
        "hours": req.operating_hours,
        "notes": req.notes,
        "website": req.website,
        "session_id": req.session_id,
        "ip_hash": ip_h,
    })
    await db.commit()

    return SpotSubmitResponse(
        spot_id=spot_id,
        status="pending",
        message="Thank you! Your spot has been submitted. "
                "It will appear to others once another user confirms it.",
    )


@router.post("/spots/{spot_id}/verify", response_model=SpotVerifyResponse)
async def verify_spot(
    spot_id: str,
    req: SpotVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Submit a confirmation (positive) or report (negative) for a prayer spot."""
    ip_h = _ip_hash(request)

    # Fetch spot
    spot_result = await db.execute(text("""
        SELECT id, status, verification_count, rejection_count, submitted_by_session
        FROM prayer_spots
        WHERE id = CAST(:id AS uuid)
    """), {"id": spot_id})
    spot = spot_result.mappings().first()

    if not spot:
        raise HTTPException(status_code=404, detail="Spot not found")
    if spot["status"] == "rejected":
        raise HTTPException(status_code=410, detail="This spot has been removed by the community")

    # ── Self-vote prevention ─────────────────────────────────────────────────
    if spot["submitted_by_session"] == req.session_id:
        raise HTTPException(
            status_code=403,
            detail="You cannot verify a spot you submitted",
        )

    # ── Duplicate vote: session ──────────────────────────────────────────────
    dup_session = await db.execute(text("""
        SELECT id FROM prayer_spot_verifications
        WHERE spot_id = CAST(:spot_id AS uuid) AND session_id = :session_id
    """), {"spot_id": spot_id, "session_id": req.session_id})
    if dup_session.fetchone():
        raise HTTPException(status_code=409, detail="You have already verified this spot")

    # ── Duplicate vote: IP ───────────────────────────────────────────────────
    if ip_h:
        dup_ip = await db.execute(text("""
            SELECT id FROM prayer_spot_verifications
            WHERE spot_id = CAST(:spot_id AS uuid) AND ip_hash = :ip_hash
        """), {"spot_id": spot_id, "ip_hash": ip_h})
        if dup_ip.fetchone():
            raise HTTPException(
                status_code=409,
                detail="You have already verified this spot",
            )

    # ── Rate limit: session ──────────────────────────────────────────────────
    verify_rate_s = await db.execute(text("""
        SELECT COUNT(*) AS cnt FROM prayer_spot_verifications
        WHERE session_id = :session_id
          AND created_at >= NOW() - INTERVAL '24 hours'
    """), {"session_id": req.session_id})
    if (verify_rate_s.scalar() or 0) >= _MAX_VERIFIES_PER_SESSION_24H:
        raise HTTPException(
            status_code=429,
            detail="You have submitted too many verifications today. Please try again tomorrow.",
        )

    # ── Rate limit: IP ───────────────────────────────────────────────────────
    if ip_h:
        verify_rate_ip = await db.execute(text("""
            SELECT COUNT(*) AS cnt FROM prayer_spot_verifications
            WHERE ip_hash = :ip_hash
              AND created_at >= NOW() - INTERVAL '24 hours'
        """), {"ip_hash": ip_h})
        if (verify_rate_ip.scalar() or 0) >= _MAX_VERIFIES_PER_IP_24H:
            raise HTTPException(
                status_code=429,
                detail="Too many verifications from this device today. Please try again tomorrow.",
            )

    # ── Insert verification record ───────────────────────────────────────────
    await db.execute(text("""
        INSERT INTO prayer_spot_verifications
            (id, spot_id, session_id, ip_hash, is_positive, attributes)
        VALUES
            (:id, CAST(:spot_id AS uuid), :session_id, :ip_hash, :positive, CAST(:attrs AS jsonb))
    """), {
        "id": new_uuid(),
        "spot_id": spot_id,
        "session_id": req.session_id,
        "ip_hash": ip_h,
        "positive": req.is_positive,
        "attrs": json.dumps(req.attributes),
    })

    # ── Update counts and status ─────────────────────────────────────────────
    count_col = "verification_count" if req.is_positive else "rejection_count"
    await db.execute(text(f"""
        UPDATE prayer_spots
        SET {count_col} = {count_col} + 1,
            last_verified_at = NOW(),
            updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
    """), {"id": spot_id})

    updated = await db.execute(text("""
        SELECT verification_count, rejection_count
        FROM prayer_spots WHERE id = CAST(:id AS uuid)
    """), {"id": spot_id})
    row = updated.mappings().first()
    v_count = row["verification_count"]
    r_count = row["rejection_count"]
    net = v_count - r_count

    new_status = spot["status"]
    if net >= _ACTIVE_THRESHOLD:
        new_status = "active"
    elif net <= _REJECT_THRESHOLD:
        new_status = "rejected"

    if new_status != spot["status"]:
        await db.execute(text("""
            UPDATE prayer_spots SET status = :status, updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
        """), {"status": new_status, "id": spot_id})

    await db.commit()

    return SpotVerifyResponse(
        spot_id=spot_id,
        verification_count=v_count,
        rejection_count=r_count,
        status=new_status,
        verification_label=_verification_label(v_count, r_count, new_status),
    )
