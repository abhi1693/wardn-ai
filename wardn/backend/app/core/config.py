from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WARDN_",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    app_name: str = "Wardn AI API"
    app_version: str = "0.1.0"
    environment: str = "local"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    api_token_secret: str = "dev-token-secret-change-me"
    api_token_prefix: str = "wardn"
    session_cookie_name: str = "wardn_session"
    session_secret: str = "dev-session-secret-change-me"
    session_ttl_seconds: int = 60 * 60 * 12
    mcp_install_root: str = "data/mcp-installations"
    mcp_runtime_provider: str = "local"
    mcp_runtime_namespace: str = "wardn-runtimes"
    mcp_runtime_idle_timeout_seconds: int = 60 * 10
    mcp_runtime_max_age_seconds: int = 60 * 60
    mcp_runtime_reaper_interval_seconds: int = 60
    mcp_runtime_reaper_batch_size: int = 100
    mcp_runtime_event_retention_days: int = 14
    mcp_runtime_invocation_retention_days: int = 30
    mcp_gateway_stdio_response_timeout_seconds: int = 300
    database_url: str = Field(
        default="postgresql+asyncpg://wardn:wardn@localhost:5432/wardn",
        description="Async SQLAlchemy database URL.",
    )
    cors_origins: list[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
