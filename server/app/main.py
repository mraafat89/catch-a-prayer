from contextlib import asynccontextmanager
import logging
import traceback

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
