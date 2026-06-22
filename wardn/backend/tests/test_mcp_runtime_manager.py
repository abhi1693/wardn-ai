from app.modules.mcp_registry.models import MCPServerInstallation
import pytest

from app.modules.mcp_runtime.manager import package_runtime, secret_environment


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


def test_package_runtime_allows_path_resolved_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.modules.mcp_runtime.manager.shutil.which", lambda command: "/usr/bin/node")
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": "package",
            "command": "node",
            "args": [str(tmp_path / "node_modules" / ".bin" / "weather-mcp")],
            "cwd": str(tmp_path),
            "transport": {"type": "stdio"},
        },
    )

    command, args, cwd, environment = package_runtime(installation)

    assert command == "node"
    assert args == [str(tmp_path / "node_modules" / ".bin" / "weather-mcp")]
    assert cwd == str(tmp_path)
    assert environment == {}


def test_package_runtime_rejects_missing_path_resolved_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.modules.mcp_runtime.manager.shutil.which", lambda command: None)
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": "package",
            "command": "not-on-path",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": "stdio"},
        },
    )

    with pytest.raises(ValueError, match="not found in PATH"):
        package_runtime(installation)
