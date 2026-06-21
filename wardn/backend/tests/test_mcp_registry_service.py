from datetime import UTC, datetime

import pytest

from app.modules.mcp_registry import service
from app.modules.mcp_registry.exceptions import (
    DuplicateMCPServerVersionError,
    InvalidRegistryCursorError,
    MCPServerInstallationNotFoundError,
)
from app.modules.mcp_registry.installer import MCPRuntimeInstall
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.mcp_registry.schemas import (
    MCPServerBulkUpdateRequest,
    MCPServerCreate,
    MCPServerInstallRequest,
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
    assert response.installed_version == "1.0.0"
    assert response.latest_version == "1.0.0"
    assert response.update_available is False
    assert response.install_type == "remote"
    assert response.runtime_config["kind"] == "remote"
    assert session.flushed is True


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

    async def get_installation(*args, **kwargs):
        return installation

    async def get_server_version(*args, **kwargs):
        version = args[2]
        if version == "latest":
            return server_version("1.1.0", is_latest=True)
        return server_version(version)

    monkeypatch.setattr(service.repository, "get_installation", get_installation)
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
