import json
import sys
import uuid
from pathlib import Path

import pytest

from app.modules.mcp_registry.models import MCPServerInstallation
from app.modules.mcp_runtime.manager import (
    RUNTIME_KIND_PACKAGE,
    RUNTIME_KIND_REMOTE,
    RUNTIME_PROVIDER_KUBERNETES,
    RUNTIME_PROVIDER_REMOTE,
    RUNTIME_TRANSPORT_STDIO,
    WARDN_CUSTOM_HEADERS_ENV,
    DefaultMCPRuntimeManager,
    package_runtime,
    secret_environment,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.mcp_runtime.providers.local_process import (
    RUNTIME_TRANSPORT_ADAPTER,
    LocalProcessRuntimeProvider,
    ManagedStdioSession,
)


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
        WARDN_CUSTOM_HEADERS_ENV: '{"X-Workspace":"prod"}',
    }


def test_package_runtime_allows_path_resolved_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.manager.shutil.which",
        lambda command: "/usr/bin/node",
    )
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        install_path=str(tmp_path),
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [str(tmp_path / "node_modules" / ".bin" / "weather-mcp")],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
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
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "not-on-path",
            "args": [],
            "cwd": str(tmp_path),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )

    with pytest.raises(ValueError, match="not found in PATH"):
        package_runtime(installation)


def test_runtime_manager_selects_remote_provider_even_when_kubernetes_configured(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.manager.get_settings",
        lambda: type("Settings", (), {"mcp_runtime_provider": RUNTIME_PROVIDER_KUBERNETES})(),
    )
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type=RUNTIME_KIND_REMOTE,
        runtime_config={
            "kind": RUNTIME_KIND_REMOTE,
            "transport": {"url": "https://example.test/mcp"},
        },
    )

    assert DefaultMCPRuntimeManager().provider_name(installation) == RUNTIME_PROVIDER_REMOTE


def test_runtime_manager_rejects_kubernetes_package_provider_until_implemented(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.manager.get_settings",
        lambda: type("Settings", (), {"mcp_runtime_provider": RUNTIME_PROVIDER_KUBERNETES})(),
    )
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": "node",
            "args": [],
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )

    with pytest.raises(ValueError, match="kubernetes MCP runtime provider is not implemented"):
        DefaultMCPRuntimeManager().provider_name(installation)


def test_runtime_fingerprint_changes_when_secret_config_changes() -> None:
    installation_id = uuid.uuid4()
    first = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type=RUNTIME_KIND_REMOTE,
        runtime_config={
            "kind": RUNTIME_KIND_REMOTE,
            "transport": {"url": "https://example.test/mcp"},
        },
        secret_config={"headers": {"Authorization": "Bearer first-secret"}},
    )
    first.id = installation_id
    second = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type=RUNTIME_KIND_REMOTE,
        runtime_config={
            "kind": RUNTIME_KIND_REMOTE,
            "transport": {"url": "https://example.test/mcp"},
        },
        secret_config={"headers": {"Authorization": "Bearer second-secret"}},
    )
    second.id = installation_id
    manager = DefaultMCPRuntimeManager()

    first_fingerprint = manager.runtime_fingerprint(first)
    second_fingerprint = manager.runtime_fingerprint(second)

    assert first_fingerprint != second_fingerprint
    assert len(first_fingerprint) == 64
    assert "secret" not in first_fingerprint


def test_local_process_provider_stop_runtime_is_idempotent(monkeypatch) -> None:
    closed_sessions = []

    def close_stdio_session(session):
        closed_sessions.append(session)

    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.local_process.client.close_stdio_session",
        close_stdio_session,
    )
    provider = LocalProcessRuntimeProvider()
    stdio_session = object()
    provider._stdio_sessions["runtime-fingerprint"] = ManagedStdioSession(stdio_session)
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )

    provider.stop_runtime(runtime_session)
    provider.stop_runtime(runtime_session)

    assert closed_sessions == [stdio_session]
    assert provider._stdio_sessions == {}


def test_local_process_provider_health_reports_missing_process() -> None:
    provider = LocalProcessRuntimeProvider()
    runtime_session = MCPRuntimeSession(
        installation_id=uuid.uuid4(),
        server_name="io.github.example/weather",
        server_version="1.0.0",
        runtime_provider="local",
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint="runtime-fingerprint",
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )

    health = provider.health(runtime_session)

    assert health.status == "not_ready"
    assert health.healthy is False
    assert health.ready is False
    assert health.message == "Local runtime process is not present in this backend process."


def test_local_process_provider_can_call_tool_through_runtime_adapter(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.mcp_runtime.providers.local_process.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "mcp_runtime_local_transport": "adapter",
                "mcp_runtime_adapter_startup_timeout_seconds": 5,
                "mcp_runtime_adapter_request_timeout_seconds": 5,
            },
        )(),
    )
    repo_root = Path(__file__).resolve().parents[3]
    fake_server = (
        repo_root
        / "wardn"
        / "runtime-adapter"
        / "tests"
        / "fixtures"
        / "fake_mcp_server.py"
    )
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="npm",
        runtime_config={
            "kind": RUNTIME_KIND_PACKAGE,
            "command": sys.executable,
            "args": [str(fake_server)],
            "cwd": str(repo_root),
            "transport": {"type": RUNTIME_TRANSPORT_STDIO},
        },
    )
    installation.id = uuid.uuid4()
    provider = LocalProcessRuntimeProvider()
    runtime_spec = provider.runtime_spec(installation)
    runtime_session = MCPRuntimeSession(
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider="local",
        runtime_kind=RUNTIME_KIND_PACKAGE,
        config_fingerprint=runtime_spec.fingerprint(),
        status="idle",
        pod_name="",
        namespace="wardn-runtimes",
        endpoint_url="",
        failure_count=0,
        last_error="",
    )

    try:
        tools = provider.list_tools(installation)
        result = provider.call_tool(
            installation,
            tool_name="echo",
            arguments={"value": "ok"},
            runtime_session=runtime_session,
        )
        health = provider.health(runtime_session)
    finally:
        provider.stop_all()

    assert runtime_spec.transport == RUNTIME_TRANSPORT_ADAPTER
    assert tools[0]["name"] == "echo"
    assert runtime_session.endpoint_url.startswith("http://127.0.0.1:")
    assert health.status == "ready"
    assert health.healthy is True
    assert health.ready is True
    assert health.details["transport"] == RUNTIME_TRANSPORT_ADAPTER
    payload = json.loads(result["content"][0]["text"])
    assert payload == {
        "arguments": {"value": "ok"},
        "initialized": True,
        "name": "echo",
    }
