import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make_settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


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
    settings = make_settings(environment="production", mcp_runtime_provider="kubernetes")

    assert settings.mcp_runtime_provider == "kubernetes"


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


def test_settings_reject_invalid_outbound_http_port() -> None:
    with pytest.raises(ValidationError, match="between 1 and 65535"):
        make_settings(outbound_http_allowed_ports="0,443")
