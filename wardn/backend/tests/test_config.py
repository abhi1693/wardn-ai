import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def make_settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


PRODUCTION_SECRETS = {
    "api_token_secret": "production-api-token-secret-that-is-unique",
    "session_secret": "production-session-secret-that-is-unique",
}


@pytest.mark.parametrize("runtime_provider", ["auto", "local"])
def test_settings_reject_local_process_runtime_outside_local(
    runtime_provider: str,
) -> None:
    with pytest.raises(ValidationError, match="local MCP process runtimes are only allowed"):
        make_settings(environment="production", mcp_runtime_provider=runtime_provider)


def test_settings_allows_local_process_runtime_for_local_development() -> None:
    settings = make_settings(environment="local", mcp_runtime_provider="local")

    assert settings.mcp_runtime_provider == "local"


def test_settings_allows_isolated_runtime_outside_local() -> None:
    settings = make_settings(
        environment="production",
        mcp_runtime_provider="kubernetes",
        **PRODUCTION_SECRETS,
    )

    assert settings.mcp_runtime_provider == "kubernetes"


def test_settings_reject_development_secrets_in_production() -> None:
    with pytest.raises(ValidationError, match="WARDN_API_TOKEN_SECRET"):
        make_settings(environment="production", mcp_runtime_provider="kubernetes")


def test_settings_reject_short_production_secrets() -> None:
    with pytest.raises(ValidationError, match="unique production secret"):
        make_settings(
            environment="production",
            mcp_runtime_provider="kubernetes",
            api_token_secret="too-short-for-production",
            session_secret=PRODUCTION_SECRETS["session_secret"],
        )


def test_settings_hide_secret_values() -> None:
    settings = make_settings(**PRODUCTION_SECRETS)

    assert isinstance(settings.api_token_secret, SecretStr)
    assert PRODUCTION_SECRETS["api_token_secret"] not in repr(settings)
    assert settings.api_token_secret.get_secret_value() == PRODUCTION_SECRETS["api_token_secret"]
    assert "postgresql+asyncpg" not in repr(settings)


def test_settings_require_complete_oidc_config_in_production() -> None:
    with pytest.raises(ValidationError, match="OIDC mode requires"):
        make_settings(
            environment="production",
            mcp_runtime_provider="kubernetes",
            auth_mode="oidc",
            **PRODUCTION_SECRETS,
        )


@pytest.mark.parametrize(
    ("setting_name", "value"),
    [
        ("session_ttl_seconds", 60),
        ("api_token_usage_update_interval_seconds", -1),
        ("mcp_runtime_reaper_batch_size", 0),
        ("mcp_runtime_invocation_stale_seconds", 59),
        ("mcp_runtime_kubernetes_service_port", 70_000),
        ("database_pool_size", 0),
        ("database_pool_timeout_seconds", 0),
    ],
)
def test_settings_reject_out_of_bounds_values(setting_name: str, value: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{setting_name: value})


def test_settings_parse_outbound_http_policy_lists() -> None:
    settings = make_settings(
        outbound_http_allowed_ports="443,8200",
        outbound_http_private_host_allowlist="bao.internal, MCP.EXAMPLE.COM. ",
    )

    assert settings.outbound_http_allowed_ports == [443, 8200]
    assert settings.outbound_http_private_host_allowlist == [
        "bao.internal",
        "mcp.example.com",
    ]


def test_settings_normalize_release_tag_version() -> None:
    settings = make_settings(app_version="v1.2.3")

    assert settings.app_version == "1.2.3"


def test_settings_reject_invalid_outbound_http_port() -> None:
    with pytest.raises(ValidationError, match="between 1 and 65535"):
        make_settings(outbound_http_allowed_ports="0,443")
