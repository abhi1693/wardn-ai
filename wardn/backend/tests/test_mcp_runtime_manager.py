import uuid

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


def test_runtime_manager_selects_kubernetes_package_provider_when_configured(
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

    assert DefaultMCPRuntimeManager().provider_name(installation) == RUNTIME_PROVIDER_KUBERNETES


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

