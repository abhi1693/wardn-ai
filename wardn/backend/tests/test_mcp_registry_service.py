from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.mcp_registry import service, tool_service
from app.modules.mcp_registry.exceptions import (
    DuplicateMCPServerVersionError,
    InvalidRegistryCursorError,
    MCPServerInstallationNotFoundError,
    MCPServerVersionInUseError,
)
from app.modules.mcp_registry.installer import MCPRuntimeInstall
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.mcp_registry.schemas import (
    MCPServerBulkUpdateRequest,
    MCPServerCreate,
    MCPServerInstallRequest,
    MCPServerInstallationToolValidationRequest,
)


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flushed = False
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def delete(self, instance: object) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        self.flushed = True

    async def refresh(self, instance) -> None:
        now = datetime(2026, 6, 21, tzinfo=UTC)
        if hasattr(instance, "id") and instance.id is None:
            instance.id = uuid4()
        instance.created_at = now
        instance.updated_at = now
        if hasattr(instance, "published_at"):
            instance.published_at = now
        if hasattr(instance, "status_changed_at"):
            instance.status_changed_at = now
        if hasattr(instance, "installed_at"):
            instance.installed_at = now
        self.refreshed.append(instance)


def registry_payload(version: str = "1.0.0") -> MCPServerCreate:
    return MCPServerCreate(
        **{
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "version": version,
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@example/weather-mcp",
                    "version": version,
                    "transport": {"type": "stdio"},
                }
            ],
        }
    )


def official_registry_payload(version: str, *, is_latest: bool) -> MCPServerCreate:
    return MCPServerCreate(
        **{
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "version": version,
            "_meta": {
                "io.modelcontextprotocol.registry/official": {
                    "status": "active",
                    "statusChangedAt": "2026-06-21T00:00:00Z",
                    "publishedAt": "2026-06-21T00:00:00Z",
                    "updatedAt": "2026-06-21T00:00:00Z",
                    "isLatest": is_latest,
                }
            },
        }
    )


def test_parse_cursor() -> None:
    assert service.parse_cursor(None) == 0
    assert service.parse_cursor("25") == 25

    with pytest.raises(InvalidRegistryCursorError):
        service.parse_cursor("-1")

    with pytest.raises(InvalidRegistryCursorError):
        service.parse_cursor("not-a-cursor")


@pytest.mark.asyncio
async def test_create_server_version_marks_new_version_latest(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    async def missing_server(*args, **kwargs):
        return None

    async def clear_latest(*args, **kwargs):
        calls.append(("clear_latest", args[1]))

    monkeypatch.setattr(service.repository, "get_server_version", missing_server)
    monkeypatch.setattr(service.repository, "clear_latest_for_name", clear_latest)
    session = FakeSession()

    response = await service.create_server_version(session, registry_payload())

    assert calls == [("clear_latest", "io.github.example/weather")]
    assert session.flushed is True
    assert session.refreshed == session.added
    assert response.server.name == "io.github.example/weather"
    assert response.server.version == "1.0.0"
    assert response.meta.official.status == "active"
    assert response.meta.official.is_latest is True


@pytest.mark.asyncio
async def test_create_server_version_rejects_duplicate(monkeypatch) -> None:
    async def existing_server(*args, **kwargs):
        return object()

    monkeypatch.setattr(service.repository, "get_server_version", existing_server)

    with pytest.raises(DuplicateMCPServerVersionError):
        await service.create_server_version(FakeSession(), registry_payload())


@pytest.mark.asyncio
async def test_sync_supported_servers_upserts_curated_entries(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def missing_server(*args, **kwargs):
        return None

    async def clear_latest(*args, **kwargs):
        calls.append(("clear_latest", args[1]))

    monkeypatch.setattr(service.repository, "get_server_version", missing_server)
    monkeypatch.setattr(service.repository, "clear_latest_for_name", clear_latest)
    session = FakeSession()

    count = await service.sync_supported_servers(
        session,
        [registry_payload("1.0.0"), registry_payload("1.1.0")],
    )

    assert count == 2
    assert calls == [("clear_latest", "io.github.example/weather")]
    assert session.flushed is True
    assert [server.version for server in session.added] == ["1.0.0", "1.1.0"]
    assert [server.is_latest for server in session.added] == [False, True]


@pytest.mark.asyncio
async def test_sync_supported_servers_uses_official_latest_metadata(monkeypatch) -> None:
    async def missing_server(*args, **kwargs):
        return None

    async def clear_latest(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_server_version", missing_server)
    monkeypatch.setattr(service.repository, "clear_latest_for_name", clear_latest)
    session = FakeSession()

    count = await service.sync_supported_servers(
        session,
        [
            official_registry_payload("1.1.0", is_latest=True),
            official_registry_payload("1.0.0", is_latest=False),
        ],
    )

    assert count == 2
    assert [server.version for server in session.added] == ["1.1.0", "1.0.0"]
    assert [server.is_latest for server in session.added] == [True, False]


def server_version(version: str, *, is_latest: bool = False) -> MCPServerVersion:
    payload = registry_payload(version)
    return MCPServerVersion(
        name=payload.name,
        title=payload.title,
        description=payload.description,
        version=version,
        server_json=payload.model_dump(by_alias=True, exclude_none=True),
        is_latest=is_latest,
        status="active",
        status_message="",
    )


def runtime_install(version: str = "1.0.0") -> MCPRuntimeInstall:
    return MCPRuntimeInstall(
        install_type="remote",
        install_path=f"/tmp/wardn/mcp/weather/{version}",
        runtime_config={
            "kind": "remote",
            "serverName": "io.github.example/weather",
            "version": version,
        },
        secret_config={},
        status="enabled",
    )


def test_public_configured_values_omits_secret_fields() -> None:
    server = MCPServerVersion(
        name="io.github.example/weather",
        title="Weather",
        description="Weather tools for forecasts",
        version="1.0.0",
        server_json={},
        is_latest=True,
        status="active",
        status_message="",
        packages=[
            {
                "environmentVariables": [
                    {"name": "WEATHER_URL"},
                    {"name": "WEATHER_TOKEN", "isSecret": True},
                ],
                "packageArguments": [
                    {"name": "LOG_LEVEL"},
                    {"name": "PRIVATE_FLAG", "isSecret": True},
                ],
            }
        ],
    )
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        secret_config={
            "environment": {
                "WEATHER_URL": "https://weather.example.com",
                "WEATHER_TOKEN": "secret-token",
            },
            "packageArguments": {
                "LOG_LEVEL": "debug",
                "PRIVATE_FLAG": "hidden",
            },
        },
    )

    assert service.public_configured_values(server, installation) == {
        "WEATHER_URL": "https://weather.example.com",
        "LOG_LEVEL": "debug",
    }


@pytest.mark.asyncio
async def test_update_server_version_preserves_latest_marker(monkeypatch) -> None:
    server = server_version("1.0.0", is_latest=True)
    payload = registry_payload("1.0.0")
    payload.title = "Updated Weather"

    async def get_server_version(*args, **kwargs):
        return server

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    session = FakeSession()

    response = await service.update_server_version(
        session,
        "io.github.example/weather",
        "1.0.0",
        payload,
    )

    assert response.server.title == "Updated Weather"
    assert server.title == "Updated Weather"
    assert server.is_latest is True
    assert session.flushed is True


@pytest.mark.asyncio
async def test_delete_server_version_rejects_installed_version(monkeypatch) -> None:
    server = server_version("1.0.0", is_latest=True)
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )

    async def get_server_version(*args, **kwargs):
        return server

    async def list_installations_for_server(*args, **kwargs):
        return [installation]

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(
        service.repository,
        "list_installations_for_server",
        list_installations_for_server,
    )

    with pytest.raises(MCPServerVersionInUseError):
        await service.delete_server_version(
            FakeSession(),
            "io.github.example/weather",
            "1.0.0",
        )


@pytest.mark.asyncio
async def test_delete_server_version_soft_deletes_and_promotes_replacement(monkeypatch) -> None:
    server = server_version("1.1.0", is_latest=True)
    replacement = server_version("1.0.0", is_latest=False)

    async def get_server_version(*args, **kwargs):
        return server

    async def list_installations_for_server(*args, **kwargs):
        return []

    async def get_latest_visible_version(*args, **kwargs):
        return replacement

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(
        service.repository,
        "list_installations_for_server",
        list_installations_for_server,
    )
    monkeypatch.setattr(
        service.repository,
        "get_latest_visible_version",
        get_latest_visible_version,
    )
    session = FakeSession()

    await service.delete_server_version(session, "io.github.example/weather", "1.1.0")

    assert server.status == "deleted"
    assert server.is_latest is False
    assert replacement.is_latest is True
    assert session.flushed is True


@pytest.mark.asyncio
async def test_install_server_version_pins_requested_version(monkeypatch) -> None:
    async def get_server_version(*args, **kwargs):
        return server_version("1.0.0", is_latest=True)

    async def get_installation(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        service,
        "install_server_runtime",
        lambda server, **kwargs: runtime_install(),
    )
    session = FakeSession()

    response = await service.install_server_version(
        session,
        "io.github.example/weather",
        MCPServerInstallRequest(version="latest"),
    )

    assert response.server_name == "io.github.example/weather"
    assert response.config_name == "default"
    assert response.installed_version == "1.0.0"
    assert response.latest_version == "1.0.0"
    assert response.update_available is False
    assert response.install_type == "remote"
    assert response.runtime_config["kind"] == "remote"
    assert session.flushed is True


@pytest.mark.asyncio
async def test_install_server_version_preserves_existing_config_values(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        secret_config={
            "environment": {"WEATHER_TOKEN": "old-token", "WEATHER_URL": "old-url"},
            "packageArguments": {"LOG_LEVEL": "warn", "READ_ONLY": "true"},
        },
    )
    seen = {}

    async def get_server_version(*args, **kwargs):
        return server_version("1.0.0", is_latest=True)

    async def get_installation(*args, **kwargs):
        return installation

    def install_runtime(server, **kwargs):
        seen["config_values"] = kwargs["config_values"]
        return runtime_install()

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(service, "install_server_runtime", install_runtime)
    session = FakeSession()

    await service.install_server_version(
        session,
        "io.github.example/weather",
        MCPServerInstallRequest(
            version="latest",
            configValues={
                "WEATHER_TOKEN": "",
                "WEATHER_URL": "new-url",
                "LOG_LEVEL": "debug",
            },
        ),
    )

    assert seen["config_values"] == {
        "WEATHER_TOKEN": "old-token",
        "WEATHER_URL": "new-url",
        "LOG_LEVEL": "debug",
        "READ_ONLY": "true",
    }


@pytest.mark.asyncio
async def test_uninstall_server_deletes_installation(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )

    async def get_installation(*args, **kwargs):
        return installation

    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(service, "remove_installation_artifacts", lambda path: None)
    session = FakeSession()

    await service.uninstall_server(session, "io.github.example/weather")

    assert session.deleted == [installation]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_uninstall_installation_deletes_selected_config(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        config_name="home",
        installed_version="1.0.0",
        status="enabled",
    )
    installation.id = uuid4()

    async def get_installation_by_id(*args, **kwargs):
        return installation

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(service, "remove_installation_artifacts", lambda path: None)
    session = FakeSession()

    await service.uninstall_installation(session, installation.id)

    assert session.deleted == [installation]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_validate_installation_tool_reports_passed_result(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    installation.id = uuid4()
    server = server_version("1.0.0", is_latest=True)

    async def get_installation_by_id(*args, **kwargs):
        return installation

    async def get_server_version(*args, **kwargs):
        return server

    async def call_tool_with_tracking(*args, **kwargs):
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service, "call_tool_with_tracking", call_tool_with_tracking)

    response = await service.validate_installation_tool(
        FakeSession(),
        installation.id,
        MCPServerInstallationToolValidationRequest(
            toolName="get_forecast",
            arguments={"location": "Delhi"},
        ),
    )

    assert response.status == "passed"
    assert response.is_error is False
    assert response.result == {"content": [{"type": "text", "text": "ok"}], "isError": False}
    assert response.error == ""


@pytest.mark.asyncio
async def test_list_installation_tools_refreshes_empty_cache(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    installation.id = uuid4()
    server = server_version("1.0.0", is_latest=True)
    cached_tool = MCPServerToolSchema(
        server_name="io.github.example/weather",
        server_version="1.0.0",
        tool_name="get_forecast",
        title="Get forecast",
        description="Get weather forecast",
        input_schema={
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
        output_schema=None,
        annotations={},
        source_hash="hash",
        is_active=True,
    )
    refreshed = {}

    async def get_installation_by_id(*args, **kwargs):
        return installation

    async def get_server_version(*args, **kwargs):
        return server

    async def count_active_tool_schemas(*args, **kwargs):
        return 0

    async def refresh_tool_schemas_for_installation(*args, **kwargs):
        refreshed["installation"] = kwargs["installation"]
        refreshed["server"] = kwargs["server"]

    async def list_active_tool_schemas(*args, **kwargs):
        return [cached_tool]

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(
        service.tool_repository,
        "count_active_tool_schemas",
        count_active_tool_schemas,
    )
    monkeypatch.setattr(
        service,
        "refresh_tool_schemas_for_installation",
        refresh_tool_schemas_for_installation,
    )
    monkeypatch.setattr(
        service.tool_repository,
        "list_active_tool_schemas",
        list_active_tool_schemas,
    )

    response = await service.list_installation_tools(FakeSession(), installation.id)

    assert response.server_name == "io.github.example/weather"
    assert response.config_name == "default"
    assert response.server_version == "1.0.0"
    assert response.cache["refreshed"] is True
    assert response.tools[0].tool_name == "get_forecast"
    assert response.tools[0].input_schema["required"] == ["location"]
    assert refreshed == {"installation": installation, "server": server}


@pytest.mark.asyncio
async def test_validate_installation_tool_reports_upstream_tool_error(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    installation.id = uuid4()
    server = server_version("1.0.0", is_latest=True)

    async def get_installation_by_id(*args, **kwargs):
        return installation

    async def get_server_version(*args, **kwargs):
        return server

    async def call_tool_with_tracking(*args, **kwargs):
        return {
            "content": [{"type": "text", "text": "invalid authentication credentials"}],
            "isError": True,
        }

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service, "call_tool_with_tracking", call_tool_with_tracking)

    response = await service.validate_installation_tool(
        FakeSession(),
        installation.id,
        MCPServerInstallationToolValidationRequest(toolName="list_projects"),
    )

    assert response.status == "failed"
    assert response.is_error is True
    assert response.error == "invalid authentication credentials"


@pytest.mark.asyncio
async def test_validate_installation_tool_reports_text_only_invalid_input(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    installation.id = uuid4()
    server = server_version("1.0.0", is_latest=True)

    async def get_installation_by_id(*args, **kwargs):
        return installation

    async def get_server_version(*args, **kwargs):
        return server

    async def call_tool_with_tracking(*args, **kwargs):
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Invalid input: expected string, received undefined",
                }
            ],
        }

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service, "call_tool_with_tracking", call_tool_with_tracking)

    response = await service.validate_installation_tool(
        FakeSession(),
        installation.id,
        MCPServerInstallationToolValidationRequest(toolName="query-docs"),
    )

    assert response.status == "failed"
    assert response.is_error is True
    assert response.error == "Invalid input: expected string, received undefined"


@pytest.mark.asyncio
async def test_uninstall_server_rejects_missing_installation(monkeypatch) -> None:
    async def get_installation(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(service, "remove_installation_artifacts", lambda path: None)

    with pytest.raises(MCPServerInstallationNotFoundError):
        await service.uninstall_server(FakeSession(), "io.github.example/weather")


@pytest.mark.asyncio
async def test_update_installed_servers_moves_selected_servers_to_latest(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )

    async def list_installations_for_server(*args, **kwargs):
        return [installation]

    async def get_server_version(*args, **kwargs):
        version = args[2]
        if version == "latest":
            return server_version("1.1.0", is_latest=True)
        return server_version(version)

    monkeypatch.setattr(
        service.repository,
        "list_installations_for_server",
        list_installations_for_server,
    )
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(
        service,
        "install_server_runtime",
        lambda server, **kwargs: runtime_install("1.1.0"),
    )
    session = FakeSession()

    response = await service.update_installed_servers(
        session,
        MCPServerBulkUpdateRequest(serverNames=["io.github.example/weather"]),
    )

    assert installation.installed_version == "1.1.0"
    assert response.installations[0].installed_version == "1.1.0"
    assert response.installations[0].update_available is False


@pytest.mark.asyncio
async def test_refresh_tool_schemas_uses_runtime_manager(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    seen = {}

    class FakeRuntimeManager:
        def list_tools(self, runtime_installation):
            seen["installation"] = runtime_installation
            return [
                {
                    "name": "get_forecast",
                    "title": "Get forecast",
                    "description": "Get weather forecast",
                    "inputSchema": {"type": "object"},
                }
            ]

        def call_tool(self, *args, **kwargs):
            raise AssertionError("refresh should not call tools")

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

    async def upsert_tool_schemas(*args, **kwargs):
        seen["server"] = kwargs["server"]
        seen["tools"] = kwargs["tools"]
        return len(kwargs["tools"])

    monkeypatch.setattr(
        tool_service.gateway_repository,
        "get_enabled_installation",
        get_enabled_installation,
    )
    monkeypatch.setattr(
        tool_service.tool_repository,
        "upsert_tool_schemas",
        upsert_tool_schemas,
    )

    result = await tool_service.refresh_tool_schemas(
        FakeSession(),
        "io.github.example/weather",
        runtime_manager=FakeRuntimeManager(),
    )

    assert result.server_name == "io.github.example/weather"
    assert result.server_version == "1.0.0"
    assert result.tool_count == 1
    assert seen["installation"] is installation
    assert seen["server"] is server
    assert seen["tools"][0]["name"] == "get_forecast"
