from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

DEV_ADMIN_TOKEN = "dev-admin-token"  # noqa: S105 - local-dev default only


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "production"] = "local"
    database_url: str = "postgresql+psycopg://telemetry:telemetry@localhost:5432/telemetry"
    # In the cloud the password arrives as its own secret (RDS-managed), so the URL is
    # assembled from parts instead. If DB_HOST is set, these override DATABASE_URL.
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "telemetry"
    db_user: str | None = None
    db_password: str | None = None
    db_sslmode: str = "prefer"

    # Protects device registration and alert admin. Must be overridden outside local dev.
    admin_token: str = DEV_ADMIN_TOKEN
    # Readings stamped further than this into the future are rejected (clock skew guard).
    max_future_skew_seconds: int = 300
    max_query_rows: int = 10_000

    log_level: str = "INFO"
    log_json: bool = True

    @model_validator(mode="after")
    def assemble_and_check(self) -> Self:
        if self.db_host:
            self.database_url = URL.create(
                "postgresql+psycopg",
                username=self.db_user,
                password=self.db_password,
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                query={"sslmode": self.db_sslmode},
            ).render_as_string(hide_password=False)
        if self.environment == "production" and self.admin_token == DEV_ADMIN_TOKEN:
            raise ValueError("ADMIN_TOKEN must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
