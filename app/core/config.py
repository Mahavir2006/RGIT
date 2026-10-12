"""Validated application configuration.

Every setting is optional at import time so that the application and its test-suite can start
without provider credentials. Credentials are validated lazily, immediately before a connector
runs, and reported by *name only* — never by value.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings", "settings"]


class Settings(BaseSettings):
    """Application settings loaded from the environment and an optional `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- core
    app_name: str = "urban-sentinel"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    api_v1_prefix: str = "/api/v1"
    timezone_display: str = "Asia/Kolkata"

    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    cors_origins: list[str] = Field(default_factory=list)
    max_payload_bytes: int = 262_144  # 256 KiB

    # Use the checkpoint bundled with this app unless deployment config overrides it.
    xproai_checkpoint: str | None = str(Path(__file__).resolve().parents[1] / "xproai_best.pt")
    c2pa_settings_file: str | None = None

    # ----------------------------------------------------------- database
    database_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_echo: bool = False

    # --------------------------------------------------------------- auth
    auth_enabled: bool = True
    api_write_key: str | None = None
    api_read_key: str | None = None
    api_key_header: str = "X-API-Key"

    # -------------------------------------------------------- http client
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 3
    http_backoff_base_seconds: float = 0.5
    http_backoff_max_seconds: float = 8.0
    http_user_agent: str = "urban-sentinel/0.1"

    # ------------------------------------------------------------ weather
    weather_provider: str = "openweather"
    openweather_api_key: str | None = None
    openweather_base_url: str = "https://api.openweathermap.org/data/2.5"
    openweather_units: Literal["metric", "imperial"] = "metric"
    weather_lat: float | None = None
    weather_lon: float | None = None
    weather_location_name: str | None = None

    # --------------------------------------------------------- air quality
    openaq_api_key: str | None = None
    openaq_base_url: str = "https://api.openaq.org/v3"
    aq_lat: float | None = None
    aq_lon: float | None = None
    aq_radius_m: int = 25_000
    aq_station_id: str | None = None
    aq_pollutants: list[str] = Field(default_factory=lambda: ["pm25", "pm10", "no2", "o3"])
    aq_page_limit: int = 2

    # ------------------------------------------------------------ traffic
    traffic_provider: str = "tomtom"
    tomtom_api_key: str | None = None
    tomtom_base_url: str = "https://api.tomtom.com"
    traffic_lat: float | None = None
    traffic_lon: float | None = None
    traffic_segment_ids: list[str] = Field(default_factory=list)
    traffic_speed_factor: float = 1.0

    # -------------------------------------------------------------- water
    water_provider: str = "dataset"
    water_api_key: str | None = None
    water_base_url: str | None = None
    water_dataset_path: str | None = None
    water_mapping_path: str | None = None
    water_expected_unit: str = "m"

    # ------------------------------------------------------------ citizen
    citizen_max_text_length: int = 2_000
    citizen_max_payload_bytes: int = 8_192

    # ------------------------------------------------------------- replay
    replay_fixtures_dir: str = "./data/samples"
    replay_shuffle_seed: int = 1337
    replay_rebase_to_now: bool = True

    # ---------------------------------------------------------- scheduler
    scheduler_enabled: bool = False  # off by default: never silently burn paid quota
    scheduler_sources: list[str] = Field(default_factory=lambda: ["replay"])
    scheduler_interval_seconds: int = 300

    # --------------------------------------------------------- processing
    # Deterministic processing (validation, dedup, anomalies, candidate matching).
    processing_auto_on_ingest: bool = True
    processing_config_path: str | None = None

    # ------------------------------------------------------- intelligence
    # Mount the multi-agent layer (urban_sentinel/) into this app.
    intelligence_enabled: bool = True
    # Off by default: an LLM-backed run per ingestion cycle could consume paid quota.
    intelligence_auto_trigger: bool = False

    # --------------------------------------------------------- freshness
    default_freshness_sla_seconds: int = 900
    freshness_sla_seconds: dict[str, int] = Field(default_factory=dict)

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug_mode(cls, value: object) -> object:
        """Accept the common release-mode value used by IDE launch environments."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod", "off", "no"}:
                return False
            if normalized in {"debug", "development", "dev", "on", "yes"}:
                return True
        return value

    @field_validator("cors_origins", "aq_pollutants", "traffic_segment_ids", "scheduler_sources",
                     mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept comma-separated strings for list-valued environment variables."""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @field_validator("freshness_sla_seconds", mode="before")
    @classmethod
    def _parse_freshness(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            result: dict[str, int] = {}
            for chunk in text.split(","):
                if "=" in chunk:
                    key, _, val = chunk.partition("=")
                    key, val = key.strip(), val.strip()
                    if key and val.isdigit():
                        result[key] = int(val)
            return result
        return value

    # ------------------------------------------------------------ helpers
    @property
    def is_sqlite(self) -> bool:
        return bool(self.database_url and self.database_url.startswith("sqlite"))

    @property
    def async_database_url(self) -> str:
        """Return the async SQLAlchemy URL, defaulting to a local SQLite file.

        A SQLite fallback keeps the application runnable before PostgreSQL has been provisioned,
        which is useful for the demo and for CI.
        """
        if self.database_url:
            return self.database_url
        return "sqlite+aiosqlite:///./urban_sentinel.db"

    def freshness_for(self, source_id: str) -> int:
        """Freshness SLA in seconds for a source, falling back to the global default."""
        return int(self.freshness_sla_seconds.get(source_id, self.default_freshness_sla_seconds))

    def effective_log_level(self) -> str:
        return "DEBUG" if self.debug else self.log_level.upper()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()


settings = get_settings()
