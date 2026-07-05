from functools import lru_cache
from typing import Literal

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
    auth_mode: Literal["local", "oidc"] = "local"
    session_cookie_name: str = "wardn_session"
    session_secret: str = "dev-session-secret-change-me"
    session_ttl_seconds: int = 60 * 60 * 12
    public_base_url: str = ""
    frontend_base_url: str = "http://localhost:3000"
    oidc_provider_name: str = "External identity provider"
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_state_cookie_name: str = "wardn_oidc_state"
    oidc_allow_unverified_email: bool = False
    oidc_auto_create_users: bool = True
    oidc_allowed_email_domains: list[str] = []
    oidc_superuser_emails: list[str] = []
    mcp_install_root: str = "data/mcp-installations"
    mcp_runtime_provider: str = "local"
    mcp_runtime_namespace: str = "wardn-runtimes"
    mcp_runtime_kubernetes_namespace_prefix: str = "wardn"
    mcp_runtime_kubernetes_allow_kubeconfig: bool = True
    mcp_runtime_kubernetes_kubeconfig_path: str = ""
    mcp_runtime_kubernetes_context: str = ""
    mcp_runtime_kubernetes_gateway_image: str = "supercorp/supergateway"
    mcp_runtime_kubernetes_gateway_uvx_image: str = "supercorp/supergateway:uvx"
    mcp_runtime_kubernetes_gateway_deno_image: str = "supercorp/supergateway:deno"
    mcp_runtime_kubernetes_cpu_request: str = "100m"
    mcp_runtime_kubernetes_cpu_limit: str = "1"
    mcp_runtime_kubernetes_memory_request: str = "256Mi"
    mcp_runtime_kubernetes_memory_limit: str = "1Gi"
    mcp_runtime_kubernetes_service_port: int = 8000
    mcp_runtime_kubernetes_image_pull_secret_name: str = ""
    mcp_runtime_kubernetes_namespace_labels_json: str = "{}"
    mcp_runtime_kubernetes_namespace_annotations_json: str = "{}"
    mcp_runtime_kubernetes_ingress_enabled: bool = False
    mcp_runtime_kubernetes_ingress_base_domain: str = ""
    mcp_runtime_kubernetes_ingress_class_name: str = "traefik"
    mcp_runtime_kubernetes_ingress_scheme: str = "https"
    mcp_runtime_kubernetes_ingress_tls_verify: bool = True
    mcp_runtime_kubernetes_ingress_tls_secret_name: str = ""
    mcp_runtime_kubernetes_ingress_traefik_entrypoints: str = "websecure"
    mcp_runtime_kubernetes_ingress_external_dns_enabled: bool = True
    mcp_runtime_kubernetes_ingress_annotations_json: str = "{}"
    mcp_runtime_kubernetes_probe_enabled: bool = True
    mcp_runtime_kubernetes_probe_period_seconds: int = 10
    mcp_runtime_kubernetes_probe_timeout_seconds: int = 3
    mcp_runtime_kubernetes_readiness_initial_delay_seconds: int = 2
    mcp_runtime_kubernetes_liveness_initial_delay_seconds: int = 30
    mcp_runtime_kubernetes_startup_failure_threshold: int = 180
    mcp_runtime_idle_timeout_seconds: int = 60 * 10
    mcp_runtime_kubernetes_startup_timeout_seconds: int = 30
    mcp_runtime_kubernetes_api_timeout_seconds: int = 10
    mcp_runtime_max_age_seconds: int = 60 * 60
    mcp_runtime_warm_on_startup: bool = True
    mcp_runtime_warm_startup_concurrency: int = 4
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

    @field_validator("oidc_allowed_email_domains", mode="before")
    @classmethod
    def parse_oidc_allowed_email_domains(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [
                domain.strip().casefold().removeprefix("@")
                for domain in value.split(",")
                if domain.strip()
            ]
        return value

    @field_validator("oidc_superuser_emails", mode="before")
    @classmethod
    def parse_oidc_superuser_emails(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [email.strip().casefold() for email in value.split(",") if email.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
