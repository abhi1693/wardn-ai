from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_PACKAGE_NAME = "wardn-api"
DEVELOPMENT_API_TOKEN_SECRET = "dev-token-secret-change-me"
DEVELOPMENT_SESSION_SECRET = "dev-session-secret-change-me"
MINIMUM_PRODUCTION_SECRET_LENGTH = 32


def package_version() -> str:
    try:
        return version(APP_PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WARDN_",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    app_name: str = Field(default="Wardn AI API", min_length=1, max_length=100)
    app_version: str = Field(default_factory=package_version, min_length=1, max_length=64)
    environment: Literal["local", "development", "test", "staging", "production"] = "local"
    api_prefix: str = Field(default="/api/v1", pattern=r"^/[A-Za-z0-9/_-]*$")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_token_secret: SecretStr = Field(
        default=SecretStr(DEVELOPMENT_API_TOKEN_SECRET),
        min_length=16,
        max_length=1024,
    )
    api_token_prefix: str = Field(
        default="wardn",
        min_length=1,
        max_length=24,
        pattern=r"^[a-z0-9]+$",
    )
    auth_mode: Literal["local", "oidc"] = "local"
    session_cookie_name: str = Field(default="wardn_session", min_length=1, max_length=64)
    session_secret: SecretStr = Field(
        default=SecretStr(DEVELOPMENT_SESSION_SECRET),
        min_length=16,
        max_length=1024,
    )
    session_ttl_seconds: int = Field(default=60 * 60 * 12, ge=300, le=60 * 60 * 24 * 31)
    public_base_url: str = Field(default="", max_length=2048)
    frontend_base_url: str = Field(default="http://localhost:3000", min_length=1, max_length=2048)
    oidc_provider_name: str = Field(
        default="External identity provider",
        min_length=1,
        max_length=100,
    )
    oidc_issuer_url: str = Field(default="", max_length=2048)
    oidc_client_id: str = Field(default="", max_length=512)
    oidc_client_secret: SecretStr = Field(default=SecretStr(""), max_length=2048)
    oidc_redirect_uri: str = Field(default="", max_length=2048)
    oidc_scopes: str = Field(default="openid email profile", min_length=1, max_length=512)
    oidc_state_cookie_name: str = Field(default="wardn_oidc_state", min_length=1, max_length=64)
    oidc_allow_unverified_email: bool = False
    oidc_auto_create_users: bool = True
    oidc_allowed_email_domains: list[str] = []
    oidc_superuser_emails: list[str] = []
    openbao_auth_file_root: str = Field(default="/var/run/secrets", min_length=1, max_length=4096)
    openbao_auth_profiles_json: str = Field(default="{}", max_length=65_536)
    outbound_http_allow_http: bool = False
    outbound_http_allowed_ports: list[int] = [443]
    outbound_http_private_host_allowlist: list[str] = []
    mcp_install_root: str = Field(default="data/mcp-installations", min_length=1, max_length=4096)
    mcp_job_worker_isolation: Literal["process", "container"] = "process"
    mcp_job_worker_poll_interval_seconds: float = Field(default=2.0, gt=0, le=60)
    mcp_job_worker_lease_seconds: int = Field(default=120, ge=10, le=3600)
    mcp_job_worker_heartbeat_seconds: int = Field(default=30, ge=1, le=600)
    mcp_job_worker_retry_base_seconds: int = Field(default=15, ge=1, le=3600)
    mcp_job_worker_retry_max_seconds: int = Field(default=15 * 60, ge=1, le=86_400)
    mcp_runtime_provider: Literal["auto", "local", "kubernetes", "remote"] = "local"
    mcp_runtime_namespace: str = Field(default="wardn-runtimes", min_length=1, max_length=63)
    mcp_runtime_kubernetes_namespace_prefix: str = Field(
        default="wardn",
        min_length=1,
        max_length=40,
    )
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
    mcp_runtime_kubernetes_service_port: int = Field(default=8000, ge=1, le=65_535)
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
    mcp_runtime_kubernetes_probe_period_seconds: int = Field(default=10, ge=1, le=300)
    mcp_runtime_kubernetes_probe_timeout_seconds: int = Field(default=3, ge=1, le=60)
    mcp_runtime_kubernetes_readiness_initial_delay_seconds: int = Field(default=2, ge=0, le=3600)
    mcp_runtime_kubernetes_liveness_initial_delay_seconds: int = Field(default=30, ge=0, le=3600)
    mcp_runtime_kubernetes_startup_failure_threshold: int = Field(default=180, ge=1, le=3600)
    mcp_runtime_idle_timeout_seconds: int = Field(default=60 * 10, ge=0, le=86_400)
    mcp_runtime_kubernetes_startup_timeout_seconds: int = Field(default=30, ge=1, le=3600)
    mcp_runtime_kubernetes_api_timeout_seconds: int = Field(default=10, ge=1, le=300)
    mcp_runtime_max_age_seconds: int = Field(default=60 * 60, ge=60, le=604_800)
    mcp_runtime_warm_on_startup: bool = True
    mcp_runtime_warm_startup_concurrency: int = Field(default=4, ge=1, le=100)
    mcp_runtime_reaper_interval_seconds: int = Field(default=60, ge=1, le=3600)
    mcp_runtime_reaper_batch_size: int = Field(default=100, ge=1, le=10_000)
    mcp_runtime_event_retention_days: int = Field(default=14, ge=1, le=3650)
    mcp_runtime_invocation_retention_days: int = Field(default=30, ge=1, le=3650)
    mcp_gateway_stdio_response_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    database_url: SecretStr = Field(
        default=SecretStr("postgresql+asyncpg://wardn:wardn@localhost:5432/wardn"),
        min_length=1,
        max_length=4096,
        description="Async SQLAlchemy database URL.",
    )
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86_400)
    database_pool_pre_ping: bool = True
    database_pool_use_lifo: bool = True
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

    @field_validator("outbound_http_allowed_ports", mode="before")
    @classmethod
    def parse_outbound_http_allowed_ports(cls, value: str | list[int]) -> list[int]:
        if isinstance(value, str):
            return [int(port.strip()) for port in value.split(",") if port.strip()]
        return value

    @field_validator("outbound_http_allowed_ports")
    @classmethod
    def validate_outbound_http_allowed_ports(cls, value: list[int]) -> list[int]:
        if not value or any(port < 1 or port > 65535 for port in value):
            raise ValueError("outbound HTTP allowed ports must be between 1 and 65535")
        return value

    @field_validator("outbound_http_private_host_allowlist", mode="before")
    @classmethod
    def parse_outbound_http_private_host_allowlist(
        cls,
        value: str | list[str],
    ) -> list[str]:
        if isinstance(value, str):
            return [
                host.strip().casefold().rstrip(".")
                for host in value.split(",")
                if host.strip()
            ]
        return value

    @model_validator(mode="after")
    def require_isolated_mcp_runtime_outside_local(self) -> "Settings":
        environment = self.environment
        runtime_provider = self.mcp_runtime_provider
        if environment != "local" and runtime_provider in {"auto", "local"}:
            raise ValueError(
                "local MCP process runtimes are only allowed when WARDN_ENVIRONMENT=local; "
                "configure WARDN_MCP_RUNTIME_PROVIDER=kubernetes or remote"
            )
        if self.mcp_job_worker_heartbeat_seconds >= self.mcp_job_worker_lease_seconds:
            raise ValueError("MCP job worker heartbeat must be shorter than its lease")
        if self.mcp_job_worker_retry_base_seconds > self.mcp_job_worker_retry_max_seconds:
            raise ValueError("MCP job worker retry base must not exceed its maximum")
        if environment == "production":
            production_secrets = {
                "WARDN_API_TOKEN_SECRET": self.api_token_secret.get_secret_value(),
                "WARDN_SESSION_SECRET": self.session_secret.get_secret_value(),
            }
            for setting_name, secret in production_secrets.items():
                if (
                    len(secret) < MINIMUM_PRODUCTION_SECRET_LENGTH
                    or secret in {DEVELOPMENT_API_TOKEN_SECRET, DEVELOPMENT_SESSION_SECRET}
                ):
                    raise ValueError(
                        f"{setting_name} must be a unique production secret with at least "
                        f"{MINIMUM_PRODUCTION_SECRET_LENGTH} characters"
                    )
            if self.auth_mode == "oidc" and not all(
                (
                    self.oidc_issuer_url.strip(),
                    self.oidc_client_id.strip(),
                    self.oidc_client_secret.get_secret_value().strip(),
                )
            ):
                raise ValueError("OIDC mode requires issuer, client ID, and client secret")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
