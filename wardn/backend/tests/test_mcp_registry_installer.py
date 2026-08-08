import json
import subprocess
from pathlib import Path

import pytest

from app.core.outbound_http import UnsafeOutboundURLError
from app.modules.mcp_registry.exceptions import (
    MCPServerInstallationFailedError,
    MCPServerInstallationUnsupportedError,
    MCPServerPackageUnavailableError,
)
from app.modules.mcp_registry.installer import (
    MCPRuntimeInstall,
    install_server_runtime,
    parse_mcp_response_body,
    run_install_command,
    safe_path_component,
    selected_install_target,
    send_remote_mcp_request,
    verify_remote_mcp_server,
)
from app.modules.mcp_registry.models import MCPServerVersion
from app.modules.mcp_registry.python_runtime import PythonRuntimeRequirement


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


def test_selected_install_target_prefers_streamable_http_when_available() -> None:
    server = server_version(
        remotes=[
            {"type": "sse", "url": "https://example.com/sse"},
            {"type": "streamable-http", "url": "https://example.com/mcp"},
        ],
        packages=[
            {
                "registryType": "npm",
                "identifier": "@example/weather",
                "version": "1.0.0",
            }
        ],
    )

    assert selected_install_target(server, {}) == "remote:1"

    remote_only_server = server_version(
        remotes=[
            {"type": "sse", "url": "https://example.com/sse"},
            {"type": "streamable-http", "url": "https://example.com/mcp"},
        ],
    )

    assert selected_install_target(remote_only_server, {}) == "remote:1"


def test_install_server_runtime_uses_streamable_http_fallback_target_index(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        remotes=[
            {"type": "sse", "url": "https://example.com/sse"},
            {"type": "streamable-http", "url": "https://example.com/mcp"},
        ],
        packages=[
            {
                "registryType": "npm",
                "identifier": "@example/weather",
                "version": "1.0.0",
            }
        ],
    )

    def build_remote(_server, temporary_path, _config_values, target_index):
        assert target_index == 1
        return MCPRuntimeInstall(
            install_type="remote",
            install_path=str(temporary_path),
            runtime_config={"kind": "remote", "targetIndex": target_index},
            secret_config={},
            status="enabled",
        )

    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.build_remote_install",
        build_remote,
    )

    install = install_server_runtime(server, install_root=tmp_path)

    assert install.install_type == "remote"
    assert install.runtime_config["targetIndex"] == 1


def test_install_commands_receive_minimal_environment(tmp_path, monkeypatch) -> None:
    seen = {}
    monkeypatch.setenv("WARDN_DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("WARDN_SESSION_SECRET", "session-secret")

    def run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.support.subprocess.run",
        run,
    )

    run_install_command(["installer", "package"], cwd=tmp_path)

    environment = seen["kwargs"]["env"]
    assert seen["command"] == ["installer", "package"]
    assert environment["HOME"].startswith(str(tmp_path))
    assert environment["PIP_NO_INPUT"] == "1"
    assert "WARDN_DATABASE_URL" not in environment
    assert "WARDN_SESSION_SECRET" not in environment
    assert not any(name.startswith("WARDN_") for name in environment)


def test_install_command_reports_an_unavailable_package_version(
    tmp_path,
    monkeypatch,
) -> None:
    def run(command, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            command,
            stderr=(
                "ERROR: Could not find a version that satisfies the requirement "
                "example-package==9.9.9\n"
                "ERROR: No matching distribution found for example-package==9.9.9"
            ),
        )

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.support.subprocess.run",
        run,
    )

    with pytest.raises(
        MCPServerPackageUnavailableError,
        match="No matching distribution found",
    ):
        run_install_command(["pip", "install", "example-package==9.9.9"], cwd=tmp_path)


def test_install_swap_restores_previous_artifact_when_finalization_fails(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(remotes=[{"url": "https://mcp.example.com"}])
    install_path = (
        tmp_path / "io.github.example__weather" / "default" / "1.0.0"
    )
    install_path.mkdir(parents=True)
    (install_path / "old-runtime").write_text("old", encoding="utf-8")

    def build_remote(_server, temporary_path, config_values, target_index):
        (temporary_path / "new-runtime").write_text("new", encoding="utf-8")
        return MCPRuntimeInstall(
            install_type="remote",
            install_path=str(temporary_path),
            runtime_config={"kind": "remote"},
            secret_config={},
            status="enabled",
        )

    def fail_final_manifest(path, runtime_config):
        raise OSError("disk full")

    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.build_remote_install",
        build_remote,
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installer.write_runtime_manifest",
        fail_final_manifest,
    )

    with pytest.raises(OSError, match="disk full"):
        install_server_runtime(server, install_root=tmp_path)

    assert (install_path / "old-runtime").read_text(encoding="utf-8") == "old"
    assert not install_path.with_name("1.0.0.backup").exists()


def test_parse_mcp_response_body_reads_json_and_sse() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}

    assert parse_mcp_response_body(json.dumps(payload)) == payload
    assert parse_mcp_response_body(f"event: message\ndata: {json.dumps(payload)}\n\n") == payload


def test_parse_mcp_response_body_skips_sse_progress_notifications() -> None:
    progress = {
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": {"progressToken": "abc123", "progress": 1},
    }
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    body = (
        f"event: message\ndata: {json.dumps(progress)}\n\n"
        f"event: message\ndata: {json.dumps(payload)}\n\n"
    )

    assert parse_mcp_response_body(body) == payload


def test_remote_mcp_request_maps_rejected_url_to_install_error(monkeypatch) -> None:
    def reject_url(*args, **kwargs):
        raise UnsafeOutboundURLError("outbound URL resolves to a non-public address")

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.remote.open_outbound_request",
        reject_url,
    )

    with pytest.raises(MCPServerInstallationFailedError, match="URL was rejected"):
        send_remote_mcp_request(
            "http://169.254.169.254/latest/meta-data",
            {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )


def test_verify_remote_mcp_server_uses_negotiated_protocol_header(monkeypatch) -> None:
    seen: list[dict] = []

    def send_remote_mcp_request(url, payload, **kwargs):
        seen.append({"url": url, "payload": payload, **kwargs})
        if payload["method"] == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"protocolVersion": "2025-06-18", "serverInfo": {}},
            }, "session-1"
        if payload["method"] == "notifications/initialized":
            return {}, None
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {"tools": []},
        }, None

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.remote.send_remote_mcp_request",
        send_remote_mcp_request,
    )

    result = verify_remote_mcp_server({"url": "https://example.com/mcp"})

    assert result["protocolVersion"] == "2025-06-18"
    assert seen[0]["payload"]["params"]["protocolVersion"] == "2025-06-18"
    assert "protocol_version" not in seen[0]
    assert seen[1]["payload"] == {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert seen[1]["protocol_version"] == "2025-06-18"
    assert seen[2]["payload"]["method"] == "tools/list"
    assert seen[2]["protocol_version"] == "2025-06-18"


def test_install_server_runtime_creates_verified_remote_runtime_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        remotes=[{"type": "streamable-http", "url": "https://example.com/mcp"}]
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.remote.verify_remote_mcp_server",
        lambda remote, **kwargs: {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "example"},
            "toolCount": 3,
            "verifiedAt": "2026-06-21T00:00:00Z",
        },
    )

    install = install_server_runtime(server, install_root=tmp_path)

    manifest_path = tmp_path / "io.github.example__weather" / "default" / "1.0.0" / "runtime.json"
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
        "app.modules.mcp_registry.installers.remote.verify_remote_mcp_server",
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


def test_install_server_runtime_preserves_bare_authorization(
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
    seen_headers = []
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.remote.verify_remote_mcp_server",
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
        config_values={"Authorization": "wardn_hub_key.secret"},
        install_root=tmp_path,
    )

    assert install.secret_config == {"headers": {"Authorization": "wardn_hub_key.secret"}}
    assert seen_headers == [{"Authorization": "wardn_hub_key.secret"}]


def test_install_server_runtime_preserves_explicit_authorization_scheme(
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
    seen_headers = []
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.remote.verify_remote_mcp_server",
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
        config_values={"Authorization": "Basic token"},
        install_root=tmp_path,
    )

    assert install.secret_config == {"headers": {"Authorization": "Basic token"}}
    assert seen_headers == [{"Authorization": "Basic token"}]


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
        "app.modules.mcp_registry.installers.remote.verify_remote_mcp_server",
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
        "app.modules.mcp_registry.installers.remote.verify_remote_mcp_server",
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


def test_install_server_runtime_preserves_bare_custom_authorization(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        remotes=[{"type": "streamable-http", "url": "https://example.com/mcp"}]
    )
    seen_headers = []
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.remote.verify_remote_mcp_server",
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
        config_values={"headers.Authorization": "wardn_hub_key.secret"},
        install_root=tmp_path,
    )

    assert install.secret_config == {"headers": {"Authorization": "wardn_hub_key.secret"}}
    assert seen_headers == [{"Authorization": "wardn_hub_key.secret"}]


def test_install_server_runtime_fails_when_remote_verification_fails(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        remotes=[{"type": "streamable-http", "url": "https://example.com/mcp"}]
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.remote.verify_remote_mcp_server",
        lambda remote, **kwargs: (_ for _ in ()).throw(
            MCPServerInstallationFailedError("remote MCP initialize failed")
        ),
    )

    with pytest.raises(MCPServerInstallationFailedError):
        install_server_runtime(server, install_root=tmp_path)

    assert not (tmp_path / "io.github.example__weather" / "default" / "1.0.0").exists()


def test_install_server_runtime_creates_oci_runtime_manifest(tmp_path, monkeypatch) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "oci",
                "identifier": "docker.io/example/weather:1.0.0",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
                "environmentVariables": [
                    {"name": "WEATHER_TOKEN", "isRequired": True, "isSecret": True},
                ],
            }
        ]
    )
    seen_commands = []
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.shutil.which",
        lambda name: "/bin/docker",
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.run_install_command",
        lambda command, **kwargs: seen_commands.append(command),
    )

    install = install_server_runtime(
        server,
        config_values={"WEATHER_TOKEN": "secret"},
        install_root=tmp_path,
    )

    assert seen_commands == [["/bin/docker", "pull", "docker.io/example/weather:1.0.0"]]
    assert install.install_type == "oci"
    assert install.runtime_config["kind"] == "package"
    assert install.runtime_config["registryType"] == "oci"
    assert install.runtime_config["command"] == "/bin/docker"
    assert install.runtime_config["args"] == [
        "run",
        "--rm",
        "-i",
        "-e",
        "WEATHER_TOKEN",
        "docker.io/example/weather:1.0.0",
    ]
    assert install.secret_config == {"environment": {"WEATHER_TOKEN": "secret"}}


def test_install_server_runtime_passes_custom_headers_to_oci_container(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "oci",
                "identifier": "docker.io/example/weather:1.0.0",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            }
        ]
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.shutil.which",
        lambda name: "/bin/docker",
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.run_install_command",
        lambda *args, **kwargs: None,
    )

    install = install_server_runtime(
        server,
        config_values={"headers.X-Workspace": "prod"},
        install_root=tmp_path,
    )

    assert install.runtime_config["args"] == [
        "run",
        "--rm",
        "-i",
        "-e",
        "WARDN_MCP_CUSTOM_HEADERS",
        "docker.io/example/weather:1.0.0",
    ]
    assert install.secret_config == {"headers": {"X-Workspace": "prod"}}
    assert install.runtime_config["package"]["headers"] == [
        {
            "name": "X-Workspace",
            "configured": True,
            "custom": True,
            "isSecret": True,
        }
    ]


def test_install_server_runtime_adds_configured_oci_package_arguments(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "oci",
                "identifier": "docker.io/grafana/mcp-grafana:0.16.0",
                "version": "0.16.0",
                "transport": {"type": "stdio"},
                "environmentVariables": [
                    {"name": "GRAFANA_URL", "isRequired": True},
                    {"name": "GRAFANA_SERVICE_ACCOUNT_TOKEN", "isSecret": True},
                ],
                "packageArguments": [
                    {"value": "-t"},
                    {"value": "stdio"},
                    {
                        "name": "GRAFANA_CLI_DISABLE_WRITE",
                        "flag": "--disable-write",
                        "format": "boolean",
                        "default": "true",
                    },
                    {
                        "name": "GRAFANA_CLI_TLS_SKIP_VERIFY",
                        "flag": "--tls-skip-verify",
                        "format": "boolean",
                    },
                    {
                        "name": "GRAFANA_CLI_LOG_LEVEL",
                        "flag": "--log-level",
                        "format": "select",
                    },
                ],
            }
        ],
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.shutil.which",
        lambda name: "/bin/docker",
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.run_install_command",
        lambda *args, **kwargs: None,
    )

    install = install_server_runtime(
        server,
        config_values={
            "GRAFANA_URL": "https://grafana.example.com",
            "GRAFANA_SERVICE_ACCOUNT_TOKEN": "token",
            "GRAFANA_CLI_TLS_SKIP_VERIFY": "true",
            "GRAFANA_CLI_LOG_LEVEL": "warn",
        },
        install_root=tmp_path,
    )

    assert install.runtime_config["args"] == [
        "run",
        "--rm",
        "-i",
        "-e",
        "GRAFANA_URL",
        "-e",
        "GRAFANA_SERVICE_ACCOUNT_TOKEN",
        "docker.io/grafana/mcp-grafana:0.16.0",
        "-t",
        "stdio",
        "--disable-write",
        "--tls-skip-verify",
        "--log-level",
        "warn",
    ]
    assert install.secret_config["packageArguments"] == {
        "GRAFANA_CLI_TLS_SKIP_VERIFY": "true",
        "GRAFANA_CLI_LOG_LEVEL": "warn",
    }


def test_install_server_runtime_strips_docker_wrapper_args_from_oci_container_args(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "oci",
                "identifier": "ghcr.io/github/github-mcp-server",
                "version": "1.5.0",
                "transport": {
                    "type": "stdio",
                    "command": "docker",
                    "args": [
                        "run",
                        "-i",
                        "--rm",
                        "-p",
                        "127.0.0.1:8085:8085",
                        "-e",
                        "GITHUB_OAUTH_CALLBACK_PORT",
                        "ghcr.io/github/github-mcp-server",
                    ],
                },
                "packageArguments": [
                    {"flag": "run", "includeInLaunch": True},
                    {"flag": "-i", "includeInLaunch": True},
                    {"flag": "--rm", "includeInLaunch": True},
                    {
                        "flag": "-p",
                        "value": "127.0.0.1:8085:8085",
                        "includeInLaunch": True,
                    },
                    {
                        "flag": "-e",
                        "value": "GITHUB_OAUTH_CALLBACK_PORT",
                        "includeInLaunch": True,
                    },
                    {
                        "name": "Docker image",
                        "value": "ghcr.io/github/github-mcp-server",
                        "includeInLaunch": True,
                    },
                    {
                        "name": "list-scopes output format",
                        "flag": "--output",
                        "default": "text",
                        "includeInLaunch": False,
                    },
                ],
            }
        ],
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.shutil.which",
        lambda name: "/bin/docker",
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.run_install_command",
        lambda *args, **kwargs: None,
    )

    install = install_server_runtime(server, install_target="package", install_root=tmp_path)

    assert install.runtime_config["containerArgs"] == []
    assert install.runtime_config["args"] == [
        "run",
        "--rm",
        "-i",
        "ghcr.io/github/github-mcp-server",
    ]


def test_install_server_runtime_materializes_file_package_arguments(
    tmp_path,
    monkeypatch,
) -> None:
    ca_content = "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n"
    server = server_version(
        packages=[
            {
                "registryType": "oci",
                "identifier": "docker.io/grafana/mcp-grafana:0.16.0",
                "version": "0.16.0",
                "transport": {"type": "stdio"},
                "packageArguments": [
                    {
                        "name": "GRAFANA_CLI_TLS_CA_FILE",
                        "flag": "--tls-ca-file",
                        "format": "file",
                    },
                ],
            }
        ],
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.shutil.which",
        lambda name: "/bin/docker",
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.run_install_command",
        lambda *args, **kwargs: None,
    )

    install = install_server_runtime(
        server,
        config_values={
            "GRAFANA_CLI_TLS_CA_FILE": {
                "type": "file",
                "filename": "grafana-ca.pem",
                "content": ca_content,
            },
        },
        install_root=tmp_path / "installs",
    )

    local_path = install.secret_config["files"]["GRAFANA_CLI_TLS_CA_FILE"]["path"]
    mount_path = install.secret_config["files"]["GRAFANA_CLI_TLS_CA_FILE"]["mountPath"]
    assert local_path.startswith(install.install_path)
    assert mount_path == "/opt/wardn/runtime-files/GRAFANA_CLI_TLS_CA_FILE"
    assert install.runtime_config["args"] == [
        "run",
        "--rm",
        "-i",
        "docker.io/grafana/mcp-grafana:0.16.0",
        "--tls-ca-file",
        local_path,
    ]
    assert install.runtime_config["fileMounts"] == [
        {
            "name": "GRAFANA_CLI_TLS_CA_FILE",
            "key": "GRAFANA_CLI_TLS_CA_FILE",
            "path": local_path,
            "mountPath": mount_path,
        }
    ]
    assert install.secret_config["files"]["GRAFANA_CLI_TLS_CA_FILE"]["content"] == (
        "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----\n"
    )
    assert install.secret_config["files"]["GRAFANA_CLI_TLS_CA_FILE"]["filename"] == (
        "grafana-ca.pem"
    )
    assert (tmp_path / "installs").joinpath(
        "io.github.example__weather",
        "default",
        "1.0.0",
        "runtime-files",
        "GRAFANA_CLI_TLS_CA_FILE",
    ).read_text(encoding="utf-8") == ca_content


def test_install_server_runtime_materializes_explicit_file_config_values(
    tmp_path,
    monkeypatch,
) -> None:
    config_content = "apiVersion: v1\nclusters: []\n"
    server = server_version(
        packages=[
            {
                "registryType": "oci",
                "identifier": "docker.io/example/mcp:1.0.0",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
                "environmentVariables": [
                    {
                        "name": "CONFIG_PATH",
                        "format": "string",
                    },
                ],
            }
        ],
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.shutil.which",
        lambda name: "/bin/docker",
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.run_install_command",
        lambda *args, **kwargs: None,
    )

    install = install_server_runtime(
        server,
        config_values={
            "CONFIG_PATH": {
                "type": "file",
                "filename": "config.yaml",
                "content": config_content,
            },
        },
        install_root=tmp_path / "installs",
    )

    local_path = install.secret_config["files"]["CONFIG_PATH"]["path"]
    mount_path = install.secret_config["files"]["CONFIG_PATH"]["mountPath"]
    assert install.secret_config["environment"]["CONFIG_PATH"] == local_path
    assert mount_path == "/opt/wardn/runtime-files/CONFIG_PATH"
    assert install.runtime_config["fileMounts"] == [
        {
            "name": "CONFIG_PATH",
            "key": "CONFIG_PATH",
            "path": local_path,
            "mountPath": mount_path,
        }
    ]
    assert Path(local_path).read_text(encoding="utf-8") == config_content


def test_install_server_runtime_uses_explicit_package_target_when_remote_exists(
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
        ],
        packages=[
            {
                "registryType": "uvx",
                "identifier": "weather-mcp",
                "version": "latest",
                "transport": {"type": "stdio"},
                "environmentVariables": [
                    {"name": "WEATHER_TOKEN", "isRequired": True, "isSecret": True},
                ],
            }
        ],
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.shutil.which",
        lambda name: "/bin/uvx",
    )

    install = install_server_runtime(
        server,
        config_values={"WEATHER_TOKEN": "secret"},
        install_target="package",
        install_root=tmp_path,
    )

    assert install.install_type == "uvx"
    assert install.secret_config == {"environment": {"WEATHER_TOKEN": "secret"}}


def test_install_server_runtime_uses_explicit_package_index(tmp_path, monkeypatch) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "npm",
                "identifier": "weather-mcp",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            },
            {
                "registryType": "oci",
                "identifier": "docker.io/example/weather:1.0.0",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            },
        ],
    )
    seen_commands = []
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.shutil.which",
        lambda name: "/bin/docker",
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.oci.run_install_command",
        lambda command, **kwargs: seen_commands.append(command),
    )

    install = install_server_runtime(
        server,
        install_target="package:1",
        install_root=tmp_path,
    )

    assert install.install_type == "oci"
    assert install.runtime_config["registryType"] == "oci"
    assert (
        install.runtime_config["package"]["identifier"]
        == "docker.io/example/weather:1.0.0"
    )
    assert seen_commands == [["/bin/docker", "pull", "docker.io/example/weather:1.0.0"]]


def test_install_server_runtime_rejects_missing_package_index(tmp_path) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "npm",
                "identifier": "weather-mcp",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            },
        ],
    )

    with pytest.raises(
        MCPServerInstallationUnsupportedError,
        match="package installation target 2",
    ):
        install_server_runtime(server, install_target="package:2", install_root=tmp_path)


def test_install_server_runtime_creates_uvx_runtime_manifest(tmp_path, monkeypatch) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "uvx",
                "identifier": "mcp-grafana",
                "version": "latest",
                "transport": {"type": "stdio"},
                "environmentVariables": [
                    {"name": "GRAFANA_URL", "isRequired": True},
                    {
                        "name": "GRAFANA_SERVICE_ACCOUNT_TOKEN",
                        "isRequired": True,
                        "isSecret": True,
                    },
                ],
            }
        ]
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.shutil.which",
        lambda name: "/bin/uvx",
    )

    install = install_server_runtime(
        server,
        config_values={
            "GRAFANA_URL": "https://grafana.example.com",
            "GRAFANA_SERVICE_ACCOUNT_TOKEN": "token",
        },
        install_root=tmp_path,
    )

    assert install.install_type == "uvx"
    assert install.runtime_config["kind"] == "package"
    assert install.runtime_config["registryType"] == "uvx"
    assert install.runtime_config["command"] == "/bin/uvx"
    assert install.runtime_config["args"] == ["mcp-grafana"]
    assert install.secret_config == {
        "environment": {
            "GRAFANA_URL": "https://grafana.example.com",
            "GRAFANA_SERVICE_ACCOUNT_TOKEN": "token",
        }
    }


def test_install_server_runtime_creates_uvx_source_runtime_manifest(tmp_path, monkeypatch) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "uvx",
                "identifier": "git+https://github.com/netboxlabs/netbox-mcp-server@v1.2.1",
                "version": "1.2.1",
                "transport": {"type": "stdio"},
                "packageArguments": [{"value": "netbox-mcp-server"}],
                "environmentVariables": [
                    {"name": "NETBOX_URL", "isRequired": True},
                    {"name": "NETBOX_TOKEN", "isRequired": True, "isSecret": True},
                ],
            }
        ]
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.shutil.which",
        lambda name: "/bin/uvx",
    )

    install = install_server_runtime(
        server,
        config_values={
            "NETBOX_URL": "https://netbox.example.com",
            "NETBOX_TOKEN": "token",
        },
        install_root=tmp_path,
    )

    assert install.install_type == "uvx"
    assert install.runtime_config["command"] == "/bin/uvx"
    assert install.runtime_config["args"] == [
        "--from",
        "git+https://github.com/netboxlabs/netbox-mcp-server@v1.2.1",
        "netbox-mcp-server",
    ]


def test_install_server_runtime_stores_custom_package_headers(tmp_path, monkeypatch) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "uvx",
                "identifier": "weather-mcp",
                "version": "latest",
                "transport": {"type": "stdio"},
            }
        ]
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.shutil.which",
        lambda name: "/bin/uvx",
    )

    install = install_server_runtime(
        server,
        config_values={"headers.X-Workspace": "prod"},
        install_root=tmp_path,
    )

    assert install.secret_config == {"headers": {"X-Workspace": "prod"}}
    assert install.runtime_config["package"]["headers"] == [
        {
            "name": "X-Workspace",
            "configured": True,
            "custom": True,
            "isSecret": True,
        }
    ]


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
        "app.modules.mcp_registry.installers.npm.run_install_command",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.npm.npm_package_bin",
        lambda install_path, identifier: install_path / "node_modules" / ".bin" / "weather-mcp",
    )

    install = install_server_runtime(server, install_root=tmp_path)

    assert ".tmp" not in install.runtime_config["command"]
    assert ".tmp" not in install.runtime_config["cwd"]
    assert install.runtime_config["command"].startswith(str(install.install_path))
    assert install.runtime_config["cwd"] == install.install_path


def test_install_server_runtime_uses_latest_for_npm_placeholder_version(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "npm",
                "identifier": "kubernetes-mcp-server",
                "version": "0.0.0",
                "transport": {"type": "stdio"},
            }
        ]
    )
    seen = {}

    def run_install_command(command, *, cwd):
        seen["package_json"] = json.loads((cwd / "package.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.npm.run_install_command",
        run_install_command,
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.npm.npm_package_bin",
        lambda install_path, identifier: (
            install_path / "node_modules" / ".bin" / "kubernetes-mcp-server"
        ),
    )

    install_server_runtime(server, install_root=tmp_path)

    assert seen["package_json"]["dependencies"] == {"kubernetes-mcp-server": "latest"}


def test_install_server_runtime_runs_npm_streamable_http_start_script(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "npm",
                "identifier": "@weatherai/mcp-server",
                "version": "1.0.0",
                "transport": {
                    "type": "streamable-http",
                    "command": "npm",
                    "args": ["start"],
                },
                "environmentVariables": [
                    {"name": "WEATHERAI_API_KEY", "isRequired": True, "isSecret": True},
                ],
            }
        ]
    )

    def run_install_command(command, *, cwd):
        package_path = cwd / "node_modules" / "@weatherai" / "mcp-server"
        package_path.mkdir(parents=True, exist_ok=True)
        (package_path / "package.json").write_text(
            json.dumps({"scripts": {"start": "node dist/index.js"}}),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.npm.run_install_command",
        run_install_command,
    )

    install = install_server_runtime(
        server,
        config_values={"WEATHERAI_API_KEY": "secret"},
        install_root=tmp_path,
    )

    assert install.install_type == "npm"
    assert install.runtime_config["command"] == "npm"
    assert install.runtime_config["args"] == ["start"]
    assert install.runtime_config["cwd"].endswith(
        "node_modules/@weatherai/mcp-server"
    )
    assert install.secret_config == {
        "environment": {"WEATHERAI_API_KEY": "secret"}
    }


def test_install_server_runtime_runs_npm_js_bin_without_shebang_with_node(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "npm",
                "identifier": "alertmanager-mcp",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            }
        ]
    )

    def run_install_command(command, *, cwd):
        package_path = cwd / "node_modules" / "alertmanager-mcp"
        package_path.mkdir(parents=True, exist_ok=True)
        (package_path / "package.json").write_text(
            json.dumps({"bin": {"alertmanager-mcp": "./build/index.js"}}),
            encoding="utf-8",
        )
        bin_path = package_path / "build" / "index.js"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text(
            "import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';\n",
            encoding="utf-8",
        )
        bin_link = cwd / "node_modules" / ".bin" / "alertmanager-mcp"
        bin_link.parent.mkdir(parents=True, exist_ok=True)
        bin_link.symlink_to("../alertmanager-mcp/build/index.js")

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.npm.run_install_command",
        run_install_command,
    )

    install = install_server_runtime(server, install_root=tmp_path)

    assert install.runtime_config["command"] == "node"
    assert install.runtime_config["args"][0].endswith("node_modules/.bin/alertmanager-mcp")


def test_install_server_runtime_runs_npm_shebang_bin_directly(
    tmp_path,
    monkeypatch,
) -> None:
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

    def run_install_command(command, *, cwd):
        package_path = cwd / "node_modules" / "weather-mcp"
        package_path.mkdir(parents=True, exist_ok=True)
        (package_path / "package.json").write_text(
            json.dumps({"bin": {"weather-mcp": "./dist/index.js"}}),
            encoding="utf-8",
        )
        bin_path = package_path / "dist" / "index.js"
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text("#!/usr/bin/env node\nconsole.log('ok');\n", encoding="utf-8")
        bin_link = cwd / "node_modules" / ".bin" / "weather-mcp"
        bin_link.parent.mkdir(parents=True, exist_ok=True)
        bin_link.symlink_to("../weather-mcp/dist/index.js")

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.npm.run_install_command",
        run_install_command,
    )

    install = install_server_runtime(server, install_root=tmp_path)

    assert install.runtime_config["command"].endswith("node_modules/.bin/weather-mcp")
    assert install.runtime_config["args"] == []


def test_install_server_runtime_omits_latest_pin_for_pypi_placeholder_version(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "pypi",
                "identifier": "openstackmcp-server",
                "version": "0.0.0",
                "transport": {"type": "stdio"},
            }
        ]
    )
    commands = []

    def run_install_command(command, *, cwd):
        commands.append(command)

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.run_install_command",
        run_install_command,
    )

    install_server_runtime(server, install_root=tmp_path)

    assert commands[1][-1] == "openstackmcp-server"


def test_install_server_runtime_uses_pypi_declared_console_script(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "pypi",
                "identifier": "mcp-google-search-console",
                "version": "2.0.2",
                "transport": {
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["mcp-google-search-console"],
                },
                "packageArguments": [
                    {
                        "name": "site-url",
                        "flag": "--site-url",
                    }
                ],
            }
        ]
    )
    commands = []

    def run_install_command(command, *, cwd):
        commands.append(command)

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.run_install_command",
        run_install_command,
    )

    install = install_server_runtime(
        server,
        config_values={"site-url": "https://example.com/"},
        install_root=tmp_path,
    )

    assert commands[1][-2:] == ["mcp-google-search-console==2.0.2", "mcp<2"]
    assert install.install_type == "pypi"
    assert install.runtime_config["pythonDependencies"] == ["mcp<2"]
    assert install.runtime_config["package"]["pythonDependencies"] == ["mcp<2"]
    assert install.runtime_config["command"].endswith(
        "/venv/bin/mcp-google-search-console"
    )
    assert install.runtime_config["args"] == ["--site-url", "https://example.com/"]


def test_install_server_runtime_retries_pypi_with_requires_python_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "pypi",
                "identifier": "unifi-access-mcp",
                "version": "0.5.2",
                "transport": {
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["unifi-access-mcp"],
                },
            }
        ]
    )
    commands = []
    pip_attempts = 0

    def resolve_python_runtime_requirement(*args, **kwargs):
        if kwargs.get("fetch_pypi_metadata"):
            return PythonRuntimeRequirement(
                requires_python=">=3.13",
                python_version="3.13",
            )
        return PythonRuntimeRequirement()

    def run_install_command(command, *, cwd):
        nonlocal pip_attempts
        commands.append(command)
        if Path(command[0]).name == "pip":
            pip_attempts += 1
            if pip_attempts == 1:
                raise MCPServerPackageUnavailableError(
                    "No matching distribution found for unifi-access-mcp==0.5.2"
                )

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.resolve_python_runtime_requirement",
        resolve_python_runtime_requirement,
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.shutil.which",
        lambda name: "/bin/uv" if name == "uv" else None,
    )
    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.run_install_command",
        run_install_command,
    )

    install = install_server_runtime(server, install_root=tmp_path)

    assert commands[0][1:3] == ["-m", "venv"]
    assert commands[1][-1] == "unifi-access-mcp==0.5.2"
    assert commands[2] == [
        "/bin/uv",
        "venv",
        "--seed",
        "--python",
        "3.13",
        str(tmp_path / "io.github.example__weather" / "default" / "1.0.0.tmp" / "venv"),
    ]
    assert commands[3][-1] == "unifi-access-mcp==0.5.2"
    assert install.runtime_config["pythonVersion"] == "3.13"
    assert install.runtime_config["package"]["requiresPython"] == ">=3.13"
    assert install.runtime_config["package"]["pythonVersion"] == "3.13"


def test_install_server_runtime_installs_pypi_runtime_dependencies(
    tmp_path,
    monkeypatch,
) -> None:
    server = server_version(
        packages=[
            {
                "registryType": "pypi",
                "identifier": "mcp-google-search-console",
                "version": "2.0.2",
                "pythonDependencies": ["mcp<2"],
                "transport": {
                    "type": "stdio",
                    "command": "uvx",
                    "args": ["mcp-google-search-console"],
                },
            }
        ]
    )
    commands = []

    def run_install_command(command, *, cwd):
        commands.append(command)

    monkeypatch.setattr(
        "app.modules.mcp_registry.installers.python.run_install_command",
        run_install_command,
    )

    install = install_server_runtime(server, install_root=tmp_path)

    assert commands[1][-2:] == ["mcp-google-search-console==2.0.2", "mcp<2"]
    assert install.runtime_config["pythonDependencies"] == ["mcp<2"]
    assert install.runtime_config["package"]["pythonDependencies"] == ["mcp<2"]
