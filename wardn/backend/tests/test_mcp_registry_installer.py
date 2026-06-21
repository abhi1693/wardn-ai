import json

import pytest

from app.modules.mcp_registry.exceptions import (
    MCPServerInstallationFailedError,
    MCPServerInstallationUnsupportedError,
)
from app.modules.mcp_registry.installer import (
    install_server_runtime,
    parse_mcp_response_body,
    safe_path_component,
)
from app.modules.mcp_registry.models import MCPServerVersion


def server_version(
    *,
    remotes: list[dict] | None = None,
    packages: list[dict] | None = None,
) -> MCPServerVersion:
    server_json = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.github.example/weather",
        "description": "Weather tools for forecasts",
        "version": "1.0.0",
        "remotes": remotes or [],
        "packages": packages or [],
    }
    return MCPServerVersion(
        name="io.github.example/weather",
        title="Weather",
        description="Weather tools for forecasts",
        version="1.0.0",
        server_json=server_json,
        status="active",
        status_message="",
        is_latest=True,
        remotes=remotes or [],
        packages=packages or [],
    )


def test_safe_path_component_removes_path_separators() -> None:
    assert safe_path_component("io.github.example/weather") == "io.github.example__weather"


def test_parse_mcp_response_body_reads_json_and_sse() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}

    assert parse_mcp_response_body(json.dumps(payload)) == payload
    assert parse_mcp_response_body(f"event: message\ndata: {json.dumps(payload)}\n\n") == payload


def test_install_server_runtime_creates_verified_remote_runtime_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        remotes=[{"type": "streamable-http", "url": "https://example.com/mcp"}]
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.verify_remote_mcp_server",
        lambda remote, **kwargs: {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "example"},
            "toolCount": 3,
            "verifiedAt": "2026-06-21T00:00:00Z",
        },
    )

    install = install_server_runtime(server, install_root=tmp_path)

    manifest_path = tmp_path / "io.github.example__weather" / "1.0.0" / "runtime.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert install.install_type == "remote"
    assert install.status == "enabled"
    assert install.runtime_config["kind"] == "remote"
    assert install.runtime_config["verification"]["toolCount"] == 3
    assert manifest["transport"]["url"] == "https://example.com/mcp"


def test_install_server_runtime_requires_prompted_remote_config(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        remotes=[
            {
                "type": "streamable-http",
                "url": "https://example.com/mcp",
                "headers": [
                    {
                        "name": "Authorization",
                        "isRequired": True,
                        "isSecret": True,
                    }
                ],
            }
        ]
    )
    with pytest.raises(MCPServerInstallationUnsupportedError):
        install_server_runtime(server, install_root=tmp_path)


def test_install_server_runtime_uses_prompted_remote_config(tmp_path, monkeypatch) -> None:
    server = server_version(
        remotes=[
            {
                "type": "streamable-http",
                "url": "https://example.com/mcp",
                "headers": [
                    {
                        "name": "Authorization",
                        "isRequired": True,
                        "isSecret": True,
                    }
                ],
            }
        ]
    )
    seen_headers = []
    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.verify_remote_mcp_server",
        lambda remote, **kwargs: seen_headers.append(kwargs["extra_headers"])
        or {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "example"},
            "toolCount": 3,
            "verifiedAt": "2026-06-21T00:00:00Z",
        },
    )

    install = install_server_runtime(
        server,
        config_values={"Authorization": "Bearer token"},
        install_root=tmp_path,
    )

    assert install.status == "enabled"
    assert install.secret_config == {"headers": {"Authorization": "Bearer token"}}
    assert seen_headers == [{"Authorization": "Bearer token"}]
    assert install.runtime_config["transport"]["headers"][0]["configured"] is True


def test_install_server_runtime_uses_optional_remote_config(tmp_path, monkeypatch) -> None:
    server = server_version(
        remotes=[
            {
                "type": "streamable-http",
                "url": "https://example.com/mcp",
                "headers": [
                    {
                        "name": "X-Workspace",
                        "isRequired": False,
                        "isSecret": False,
                    }
                ],
            }
        ]
    )
    seen_headers = []
    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.verify_remote_mcp_server",
        lambda remote, **kwargs: seen_headers.append(kwargs["extra_headers"])
        or {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "example"},
            "toolCount": 3,
            "verifiedAt": "2026-06-21T00:00:00Z",
        },
    )

    install = install_server_runtime(
        server,
        config_values={"X-Workspace": "prod"},
        install_root=tmp_path,
    )

    assert install.secret_config == {"headers": {"X-Workspace": "prod"}}
    assert seen_headers == [{"X-Workspace": "prod"}]
    assert install.runtime_config["transport"]["headers"][0]["configured"] is True


def test_install_server_runtime_uses_custom_remote_header(tmp_path, monkeypatch) -> None:
    server = server_version(
        remotes=[{"type": "streamable-http", "url": "https://example.com/mcp"}]
    )
    seen_headers = []
    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.verify_remote_mcp_server",
        lambda remote, **kwargs: seen_headers.append(kwargs["extra_headers"])
        or {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "example"},
            "toolCount": 3,
            "verifiedAt": "2026-06-21T00:00:00Z",
        },
    )

    install = install_server_runtime(
        server,
        config_values={"headers.Authorization": "Bearer token"},
        install_root=tmp_path,
    )

    assert install.secret_config == {"headers": {"Authorization": "Bearer token"}}
    assert seen_headers == [{"Authorization": "Bearer token"}]
    assert install.runtime_config["transport"]["headers"][0]["configured"] is True
    assert install.runtime_config["transport"]["headers"][0]["custom"] is True


def test_install_server_runtime_fails_when_remote_verification_fails(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        remotes=[{"type": "streamable-http", "url": "https://example.com/mcp"}]
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.verify_remote_mcp_server",
        lambda remote, **kwargs: (_ for _ in ()).throw(
            MCPServerInstallationFailedError("remote MCP initialize failed")
        ),
    )

    with pytest.raises(MCPServerInstallationFailedError):
        install_server_runtime(server, install_root=tmp_path)

    assert not (tmp_path / "io.github.example__weather" / "1.0.0").exists()


def test_install_server_runtime_rejects_unsupported_package_registry(tmp_path) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "oci",
                "identifier": "docker.io/example/weather:1.0.0",
                "version": "1.0.0",
            }
        ]
    )

    with pytest.raises(MCPServerInstallationUnsupportedError):
        install_server_runtime(server, install_root=tmp_path)


def test_install_server_runtime_rewrites_package_tmp_paths(tmp_path, monkeypatch) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "npm",
                "identifier": "weather-mcp",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            }
        ]
    )

    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.run_install_command",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.npm_package_bin",
        lambda install_path, identifier: install_path / "node_modules" / ".bin" / "weather-mcp",
    )

    install = install_server_runtime(server, install_root=tmp_path)

    assert ".tmp" not in install.runtime_config["command"]
    assert ".tmp" not in install.runtime_config["cwd"]
    assert install.runtime_config["command"].startswith(str(install.install_path))
    assert install.runtime_config["cwd"] == install.install_path
