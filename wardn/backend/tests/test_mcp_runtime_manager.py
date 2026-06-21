from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.manager import secret_environment


def test_secret_environment_includes_custom_headers_json() -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="uvx",
        secret_config={
            "environment": {"WEATHER_TOKEN": "secret"},
            "headers": {"X-Workspace": "prod"},
        },
    )

    assert secret_environment(installation) == {
        "WEATHER_TOKEN": "secret",
        "WARDN_MCP_CUSTOM_HEADERS": '{"X-Workspace":"prod"}',
    }
