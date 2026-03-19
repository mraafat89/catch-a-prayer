"""
Mosque Suggestions API
======================
Community-submitted corrections for mosque data (iqama times, facilities, contact info).

Endpoints:
  GET  /api/mosques/{id}/suggestions     — list pending suggestions for a mosque
  POST /api/mosques/{id}/suggestions     — submit a correction
  POST /api/suggestions/{id}/vote        — upvote or downvote a suggestion

Design:
- Same anonymous identity model as prayer spots: session_id + sha256(IP)
- Different accept thresholds by field type:
    iqama times:  net +2 (time-sensitive, faster consensus)
    facilities:   net +3
- Iqama suggestions auto-expire after 7 days
- Facility suggestions auto-expire after 90 days
- Nightly scraper auto-closes suggestions when it finds fresh data
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.models import new_uuid
from app.schemas import (
    MosqueSuggestionSubmitRequest, MosqueSuggestionResponse,
    MosqueSuggestionVoteRequest, MosqueSuggestionVoteResponse,
    MosqueSuggestionsListResponse,
    SUGGESTION_IQAMA_FIELDS, SUGGESTION_FACILITY_FIELDS,
)

router = APIRouter(tags=["suggestions"])

# ─── Constants ────────────────────────────────────────────────────────────────

_IQAMA_ACCEPT_THRESHOLD = 2
_FACILITY_ACCEPT_THRESHOLD = 3
_REJECT_THRESHOLD = -2

_IQAMA_EXPIRY_DAYS = 7
_FACILITY_EXPIRY_DAYS = 90

_MAX_SUGGESTIONS_PER_SESSION_24H = 5
_MAX_SUGGESTIONS_PER_IP_24H = 3
_MAX_VOTES_PER_SESSION_24H = 30
_MAX_VOTES_PER_IP_24H = 10

_TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')
_URL_RE = re.compile(r'https?://|www\.', re.IGNORECASE)


def _ip_hash(request: Request) -> str | None:
    ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Real-IP", "").strip()
        or (request.client.host if request.client else None)
    )
    if not ip:
        return None
    return hashlib.sha256(ip.encode()).hexdigest()


def _accept_threshold(field_name: str) -> int:
    return _IQAMA_ACCEPT_THRESHOLD if field_name in SUGGESTION_IQAMA_FIELDS else _FACILITY_ACCEPT_THRESHOLD


def _expiry_days(field_name: str) -> int:
    return _IQAMA_EXPIRY_DAYS if field_name in SUGGESTION_IQAMA_FIELDS else _FACILITY_EXPIRY_DAYS


def _validate_iqama_time(value: str) -> None:
    if not _TIME_RE.match(value):
        raise HTTPException(status_code=422, detail="Iqama time must be in HH:MM format")
    h, m = value.split(':')
    if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
        raise HTTPException(status_code=422, detail="Invalid time value")


def _validate_boolean_field(value: str) -> None:
    if value.lower() not in ('true', 'false'):
        raise HTTPException(status_code=422, detail="Value must be true or false")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/mosques/{mosque_id}/suggestions", response_model=MosqueSuggestionsListResponse)
async def list_suggestions(mosque_id: str, db: AsyncSession = Depends(get_db)):
    """List pending suggestions for a mosque."""
    # Expire old suggestions first
    await db.execute(text("""
        UPDATE mosque_suggestions
        SET status = 'expired', updated_at = NOW()
        WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < NOW()
    """))

    result = await db.execute(text("""
        SELECT
            id::text, mosque_id::text, field_name, suggested_value, current_value,
            status, upvote_count, downvote_count, submitted_by_session, created_at
        FROM mosque_suggestions
        WHERE mosque_id = CAST(:mosque_id AS uuid)
          AND status = 'pending'
        ORDER BY created_at DESC
    """), {"mosque_id": mosque_id})

    suggestions = [
        MosqueSuggestionResponse(
            id=row["id"],
            mosque_id=row["mosque_id"],
            field_name=row["field_name"],
            suggested_value=row["suggested_value"],
            current_value=row["current_value"],
            status=row["status"],
            upvote_count=row["upvote_count"],
            downvote_count=row["downvote_count"],
            submitted_by_session=row["submitted_by_session"],
            created_at=row["created_at"].isoformat(),
        )
        for row in result.mappings()
    ]

    await db.commit()
    return MosqueSuggestionsListResponse(suggestions=suggestions)


@router.post("/mosques/{mosque_id}/suggestions", response_model=MosqueSuggestionResponse, status_code=201)
async def submit_suggestion(
    mosque_id: str,
    req: MosqueSuggestionSubmitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Submit a correction for a mosque field."""
    ip_h = _ip_hash(request)

    # ── 1. Mosque exists ──────────────────────────────────────────────────
    mosque_result = await db.execute(text("""
        SELECT id, phone, website, has_womens_section, has_parking, wheelchair_accessible
        FROM mosques WHERE id = CAST(:id AS uuid)
    """), {"id": mosque_id})
    mosque = mosque_result.mappings().first()
    if not mosque:
        raise HTTPException(status_code=404, detail="Mosque not found")

    # ── 2. Validate value by field type ───────────────────────────────────
    if req.field_name in SUGGESTION_IQAMA_FIELDS:
        _validate_iqama_time(req.suggested_value)
    elif req.field_name in ('has_womens_section', 'has_parking', 'wheelchair_accessible'):
        _validate_boolean_field(req.suggested_value)
    elif req.field_name == 'phone':
        if _URL_RE.search(req.suggested_value):
            raise HTTPException(status_code=422, detail="Phone number must not contain URLs")

    # ── 3. Get current value for comparison ───────────────────────────────
    current_value = None
    if req.field_name in SUGGESTION_IQAMA_FIELDS:
        # Look up from prayer_schedules
        ps_result = await db.execute(text(f"""
            SELECT {req.field_name} FROM prayer_schedules
            WHERE mosque_id = CAST(:id AS uuid) AND date = CURRENT_DATE
            LIMIT 1
        """), {"id": mosque_id})
        ps_row = ps_result.mappings().first()
        if ps_row:
            current_value = ps_row[req.field_name]
    elif req.field_name in ('phone', 'website'):
        current_value = mosque[req.field_name]
    elif req.field_name in ('has_womens_section', 'has_parking', 'wheelchair_accessible'):
        val = mosque[req.field_name]
        current_value = str(val).lower() if val is not None else None

    # Don't accept if suggestion matches current value
    if current_value and str(current_value).strip() == req.suggested_value.strip():
        raise HTTPException(status_code=409, detail="This is already the current value")

    # ── 4. Rate limit: session ────────────────────────────────────────────
    rate_s = await db.execute(text("""
        SELECT COUNT(*) FROM mosque_suggestions
        WHERE submitted_by_session = :session_id
          AND created_at >= NOW() - INTERVAL '24 hours'
    """), {"session_id": req.session_id})
    if (rate_s.scalar() or 0) >= _MAX_SUGGESTIONS_PER_SESSION_24H:
        raise HTTPException(status_code=429, detail="Too many suggestions today. Please try again tomorrow.")

    # ── 5. Rate limit: IP ─────────────────────────────────────────────────
    if ip_h:
        rate_ip = await db.execute(text("""
            SELECT COUNT(*) FROM mosque_suggestions
            WHERE submitted_ip_hash = :ip_hash
              AND created_at >= NOW() - INTERVAL '24 hours'
        """), {"ip_hash": ip_h})
        if (rate_ip.scalar() or 0) >= _MAX_SUGGESTIONS_PER_IP_24H:
            raise HTTPException(status_code=429, detail="Too many suggestions from this device today.")

    # ── 6. Dedup: one active suggestion per field per mosque ──────────────
    dup = await db.execute(text("""
        SELECT id FROM mosque_suggestions
        WHERE mosque_id = CAST(:mosque_id AS uuid)
          AND field_name = :field_name
          AND status = 'pending'
        LIMIT 1
    """), {"mosque_id": mosque_id, "field_name": req.field_name})
    if dup.fetchone():
        raise HTTPException(
            status_code=409,
            detail="There is already a pending suggestion for this field. Please vote on the existing one.",
        )

    # ── 7. Insert ─────────────────────────────────────────────────────────
    suggestion_id = new_uuid()
    expiry_days = _expiry_days(req.field_name)

    await db.execute(text("""
        INSERT INTO mosque_suggestions (
            id, mosque_id, field_name, suggested_value, current_value,
            submitted_by_session, submitted_ip_hash,
            status, upvote_count, downvote_count, expires_at
        ) VALUES (
            :id, CAST(:mosque_id AS uuid), :field_name, :suggested_value, :current_value,
            :session_id, :ip_hash,
            'pending', 0, 0, NOW() + :expiry_interval
        )
    """), {
        "id": suggestion_id,
        "mosque_id": mosque_id,
        "field_name": req.field_name,
        "suggested_value": req.suggested_value,
        "current_value": current_value,
        "session_id": req.session_id,
        "ip_hash": ip_h,
        "expiry_interval": timedelta(days=expiry_days),
    })
    await db.commit()

    return MosqueSuggestionResponse(
        id=suggestion_id,
        mosque_id=mosque_id,
        field_name=req.field_name,
        suggested_value=req.suggested_value,
        current_value=current_value,
        status="pending",
        upvote_count=0,
        downvote_count=0,
        submitted_by_session=req.session_id,
        created_at="",  # just created
    )


@router.post("/suggestions/{suggestion_id}/vote", response_model=MosqueSuggestionVoteResponse)
async def vote_suggestion(
    suggestion_id: str,
    req: MosqueSuggestionVoteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Upvote or downvote a mosque suggestion."""
    ip_h = _ip_hash(request)

    # Fetch suggestion
    s_result = await db.execute(text("""
        SELECT id, mosque_id::text, field_name, suggested_value, status,
               upvote_count, downvote_count, submitted_by_session
        FROM mosque_suggestions
        WHERE id = CAST(:id AS uuid)
    """), {"id": suggestion_id})
    suggestion = s_result.mappings().first()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion["status"] != "pending":
        raise HTTPException(status_code=410, detail="This suggestion is no longer active")

    # Self-vote prevention
    if suggestion["submitted_by_session"] == req.session_id:
        raise HTTPException(status_code=403, detail="You cannot vote on your own suggestion")

    # Duplicate vote: session
    dup_s = await db.execute(text("""
        SELECT id FROM mosque_suggestion_votes
        WHERE suggestion_id = CAST(:sid AS uuid) AND session_id = :session_id
    """), {"sid": suggestion_id, "session_id": req.session_id})
    if dup_s.fetchone():
        raise HTTPException(status_code=409, detail="You have already voted on this suggestion")

    # Duplicate vote: IP
    if ip_h:
        dup_ip = await db.execute(text("""
            SELECT id FROM mosque_suggestion_votes
            WHERE suggestion_id = CAST(:sid AS uuid) AND ip_hash = :ip_hash
        """), {"sid": suggestion_id, "ip_hash": ip_h})
        if dup_ip.fetchone():
            raise HTTPException(status_code=409, detail="You have already voted on this suggestion")

    # Rate limit: session
    rate_s = await db.execute(text("""
        SELECT COUNT(*) FROM mosque_suggestion_votes
        WHERE session_id = :session_id AND created_at >= NOW() - INTERVAL '24 hours'
    """), {"session_id": req.session_id})
    if (rate_s.scalar() or 0) >= _MAX_VOTES_PER_SESSION_24H:
        raise HTTPException(status_code=429, detail="Too many votes today.")

    # Rate limit: IP
    if ip_h:
        rate_ip = await db.execute(text("""
            SELECT COUNT(*) FROM mosque_suggestion_votes
            WHERE ip_hash = :ip_hash AND created_at >= NOW() - INTERVAL '24 hours'
        """), {"ip_hash": ip_h})
        if (rate_ip.scalar() or 0) >= _MAX_VOTES_PER_IP_24H:
            raise HTTPException(status_code=429, detail="Too many votes from this device today.")

    # Insert vote
    await db.execute(text("""
        INSERT INTO mosque_suggestion_votes (id, suggestion_id, session_id, ip_hash, is_positive)
        VALUES (:id, CAST(:sid AS uuid), :session_id, :ip_hash, :positive)
    """), {
        "id": new_uuid(),
        "sid": suggestion_id,
        "session_id": req.session_id,
        "ip_hash": ip_h,
        "positive": req.is_positive,
    })

    # Update counts
    count_col = "upvote_count" if req.is_positive else "downvote_count"
    await db.execute(text(f"""
        UPDATE mosque_suggestions SET {count_col} = {count_col} + 1, updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
    """), {"id": suggestion_id})

    # Check thresholds
    updated = await db.execute(text("""
        SELECT upvote_count, downvote_count, field_name, mosque_id::text, suggested_value
        FROM mosque_suggestions WHERE id = CAST(:id AS uuid)
    """), {"id": suggestion_id})
    row = updated.mappings().first()
    up = row["upvote_count"]
    down = row["downvote_count"]
    net = up - down
    field = row["field_name"]
    threshold = _accept_threshold(field)

    new_status = "pending"
    if net >= threshold:
        new_status = "accepted"
        # Apply the correction to the mosque/prayer_schedule
        await _apply_suggestion(db, row["mosque_id"], field, row["suggested_value"])
    elif net <= _REJECT_THRESHOLD:
        new_status = "rejected"

    if new_status != "pending":
        await db.execute(text("""
            UPDATE mosque_suggestions SET status = :status, updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
        """), {"status": new_status, "id": suggestion_id})

    await db.commit()

    return MosqueSuggestionVoteResponse(
        suggestion_id=suggestion_id,
        upvote_count=up,
        downvote_count=down,
        status=new_status,
    )


async def _apply_suggestion(db: AsyncSession, mosque_id: str, field_name: str, value: str) -> None:
    """Apply an accepted suggestion to the actual mosque data."""
    if field_name in SUGGESTION_IQAMA_FIELDS:
        # Update today's prayer schedule
        await db.execute(text(f"""
            UPDATE prayer_schedules
            SET {field_name} = :value,
                {field_name}_source = 'user_submitted',
                {field_name.replace('_iqama', '_iqama_confidence')} = 'medium',
                updated_at = NOW()
            WHERE mosque_id = CAST(:mosque_id AS uuid) AND date = CURRENT_DATE
        """), {"value": value, "mosque_id": mosque_id})
    elif field_name in ('phone', 'website'):
        await db.execute(text(f"""
            UPDATE mosques SET {field_name} = :value, updated_at = NOW()
            WHERE id = CAST(:mosque_id AS uuid)
        """), {"value": value, "mosque_id": mosque_id})
    elif field_name in ('has_womens_section', 'has_parking', 'wheelchair_accessible'):
        bool_val = value.lower() == 'true'
        await db.execute(text(f"""
            UPDATE mosques SET {field_name} = :value, updated_at = NOW()
            WHERE id = CAST(:mosque_id AS uuid)
        """), {"value": bool_val, "mosque_id": mosque_id})
