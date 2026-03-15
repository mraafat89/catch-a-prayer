from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.database import engine, Base
from app.api import mosques, settings as settings_router, spots as spots_router
import logging

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


@app.get("/health")
async def health():
    return {"status": "healthy", "version": "2.0.0"}
