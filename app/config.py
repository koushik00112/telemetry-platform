from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://telemetry:telemetry@localhost:5432/telemetry"
    # Protects device registration. Must be overridden outside local dev.
    admin_token: str = "dev-admin-token"  # noqa: S105 - local-dev default only
    # Readings stamped further than this into the future are rejected (clock skew guard).
    max_future_skew_seconds: int = 300
    max_query_rows: int = 10_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
