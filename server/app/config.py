from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://cap:cap@localhost:5432/catchaprayer"
    mapbox_api_key: str = ""
    anthropic_api_key: str = ""
    google_places_api_key: str = ""

    overpass_api_url: str = "https://overpass-api.de/api/interpreter"
    overpass_backup_url: str = "https://overpass.kumi.systems/api/interpreter"

    playwright_workers: int = 4
    log_level: str = "INFO"

    # Prayer calculation defaults
    congregation_window_minutes: int = 15
    default_search_radius_km: int = 10
    calculation_method: str = "ISNA"


@lru_cache
def get_settings() -> Settings:
    return Settings()
