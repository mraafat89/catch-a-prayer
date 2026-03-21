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
    """Lightweight request tracking middleware."""
    start = time.time()
    response = await call_next(request)
    elapsed_ms = (time.time() - start) * 1000

    path = request.url.path
    # Skip health checks and static files from metrics
    if path in ("/health", "/metrics") or path.startswith("/static"):
        return response

    request_metrics["total_requests"] += 1
    request_metrics["latency_sum_ms"] += elapsed_ms
    request_metrics["latency_count"] += 1

    # Normalize endpoint (strip UUIDs and query params)
    endpoint = path.split("?")[0]
    if "/mosques/" in endpoint and len(endpoint) > 20:
        endpoint = "/api/mosques/{id}"
    request_metrics["requests_by_endpoint"][endpoint] += 1

    # Track by hour
    hour = datetime.utcnow().strftime("%Y-%m-%d %H:00")
    request_metrics["requests_by_hour"][hour] += 1

    # Track specific actions
    if "travel/plan" in path:
        request_metrics["routes_planned"] += 1
    if "spots" in path and request.method == "POST":
        request_metrics["spots_submitted"] += 1

    # Track unique locations (bucketed to ~10km grid)
    if "nearby" in path and request.method == "POST":
        try:
            body = await request.body()
            import json
            data = json.loads(body)
            lat = round(data.get("latitude", 0), 1)
            lng = round(data.get("longitude", 0), 1)
            if lat and lng:
                request_metrics["unique_locations"].add(f"{lat},{lng}")
        except Exception:
            pass

    if response.status_code >= 500:
        request_metrics["errors_5xx"] += 1

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
