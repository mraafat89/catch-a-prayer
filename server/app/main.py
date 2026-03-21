from contextlib import asynccontextmanager
import logging
import time
import traceback
from collections import defaultdict
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import get_settings
from app.database import engine, Base
from app.api import mosques, settings as settings_router, spots as spots_router
from app.api import travel as travel_router, suggestions as suggestions_router
from app.api import admin as admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Catch a Prayer API")
    yield
    await engine.dispose()
    logger.info("Shut down complete")


app = FastAPI(
    title="Catch a Prayer API",
    version="2.0.0",
    description="Find nearby mosques and catch your next prayer",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request metrics — in-memory counters (reset on restart)
# ---------------------------------------------------------------------------

request_metrics = {
    "total_requests": 0,
    "requests_by_endpoint": defaultdict(int),
    "requests_by_hour": defaultdict(int),
    "errors_5xx": 0,
    "latency_sum_ms": 0.0,
    "latency_count": 0,
    "unique_locations": set(),  # approximate unique users by lat/lng bucket
    "routes_planned": 0,
    "spots_submitted": 0,
    "started_at": datetime.utcnow().isoformat(),
}


@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Request tracking — in-memory metrics + persistent DB logging for searches."""
    start_time = time.time()

    # Read body before passing to handler (needed for POST body inspection)
    body_bytes = b""
    if request.method == "POST" and "nearby" in request.url.path:
        body_bytes = await request.body()

    response = await call_next(request)
    elapsed_ms = (time.time() - start_time) * 1000

    path = request.url.path
    if path in ("/health", "/metrics") or path.startswith("/static"):
        return response

    # In-memory counters
    request_metrics["total_requests"] += 1
    request_metrics["latency_sum_ms"] += elapsed_ms
    request_metrics["latency_count"] += 1

    endpoint = path.split("?")[0]
    if "/mosques/" in endpoint and len(endpoint) > 20:
        endpoint = "/api/mosques/{id}"
    request_metrics["requests_by_endpoint"][endpoint] += 1

    hour = datetime.utcnow().strftime("%Y-%m-%d %H:00")
    request_metrics["requests_by_hour"][hour] += 1

    if "travel/plan" in path:
        request_metrics["routes_planned"] += 1
    if "spots" in path and request.method == "POST":
        request_metrics["spots_submitted"] += 1
    if response.status_code >= 500:
        request_metrics["errors_5xx"] += 1

    # Persist search/route requests to DB for heatmaps
    lat = lng = radius = travel_mode = session_id = None
    try:
        if body_bytes and "nearby" in path:
            import json as _json
            data = _json.loads(body_bytes)
            lat = data.get("latitude")
            lng = data.get("longitude")
            radius = data.get("radius_km")
            travel_mode = data.get("travel_mode")
            session_id = request.headers.get("x-session-id")

            if lat and lng:
                request_metrics["unique_locations"].add(f"{round(lat,1)},{round(lng,1)}")

        if "travel/plan" in path and request.method == "POST":
            # Route planning — log origin
            try:
                import json as _json
                route_body = await request.body()
                data = _json.loads(route_body) if route_body else {}
                lat = data.get("origin_lat")
                lng = data.get("origin_lng")
            except Exception:
                pass

        # Log to DB (async, non-blocking)
        if path.startswith("/api/") and path not in ("/api/admin/stats", "/api/admin/dashboard"):
            try:
                from app.database import engine as _engine
                from sqlalchemy import text as _text
                import asyncio
                async def _log():
                    async with _engine.begin() as conn:
                        await conn.execute(_text("""
                            INSERT INTO request_logs (id, endpoint, method, lat, lng, radius_km,
                                travel_mode, response_code, latency_ms, session_id)
                            VALUES (gen_random_uuid(), :ep, :method, :lat, :lng, :radius,
                                :travel, :code, :latency, :sid)
                        """), {
                            "ep": endpoint, "method": request.method,
                            "lat": lat, "lng": lng, "radius": radius,
                            "travel": travel_mode, "code": response.status_code,
                            "latency": round(elapsed_ms, 1), "sid": session_id,
                        })
                asyncio.create_task(_log())
            except Exception:
                pass
    except Exception:
        pass

    return response

app.include_router(mosques.router, prefix="/api")
app.include_router(spots_router.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(travel_router.router, prefix="/api")
app.include_router(suggestions_router.router, prefix="/api")
app.include_router(admin_router.router, prefix="/api")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error("Unhandled exception on %s %s\n%s", request.method, request.url.path, tb)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "2.0.0"}
