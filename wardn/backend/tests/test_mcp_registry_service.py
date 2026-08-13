import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.pagination import InvalidCursorError
from app.modules.limits.exceptions import LimitExceededError
from app.modules.mcp_gateway.client import MCPGatewayUnsupportedMethodError
from app.modules.mcp_registry import (
    catalog_service,
    config_service,
    installation_service,
    service,
    tool_repository,
    tool_service,
)
from app.modules.mcp_registry.exceptions import (
    DuplicateMCPServerVersionError,
    InvalidRegistryCursorError,
    MCPServerInstallationFailedError,
    MCPServerInstallationNotFoundError,
    MCPServerInstallationUnsupportedError,
    MCPServerVersionInUseError,
)
from app.modules.mcp_registry.installer import MCPRuntimeInstall
from app.modules.mcp_registry.models import (
    MCPCatalogSource,
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.mcp_registry.schemas import (
    MCPCatalogSourceCreate,
    MCPServerBulkUpdateRequest,
    MCPServerCreate,
    MCPServerInstallationToolValidationRequest,
    MCPServerInstallRequest,
)
from app.modules.mcp_runtime.models import MCPRuntimeSession
from app.modules.secrets.models import SecretHandle
from app.modules.secrets.provider import SecretWriteResult
from app.modules.users.models import User
from tests.database_fakes import EmptyResult

WORKSPACE_ID = uuid4()
ORGANIZATION_ID = uuid4()
USER = User(id=uuid4(), email="owner@example.com", is_superuser=True)


def runtime_session_for_installation(installation: MCPServerInstallation) -> MCPRuntimeSession:
    return MCPRuntimeSession(
        id=uuid4(),
        organization_id=ORGANIZATION_ID,
        workspace_id=installation.workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version=installation.installed_version,
        runtime_provider="kubernetes",
        runtime_kind="package",
        config_fingerprint="fingerprint",
        status="running",
        pod_name="io-github-example-weather-default",
        namespace="wardn-org-example-ws-example",
        endpoint_url="http://io-github-example-weather-default-svc.wardn-org-example.svc/mcp",
    )


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flushed = False
        self.committed = False
        self.commit_count = 0
        self.rollback_count = 0
        self.refreshed: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def delete(self, instance: object) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

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

    async def execute(self, *args, **kwargs) -> EmptyResult:
        return EmptyResult()

    async def get(self, *args, **kwargs) -> None:
        return None


def patch_bulk_sync_dependencies(monkeypatch, *, statuses=None):
    captured = {"cleared": [], "batches": []}

    async def no_op(*args, **kwargs):
        return None

    async def count_versions(*args, **kwargs):
        return 0

    async def get_statuses(*args, **kwargs):
        return statuses or {}

    async def clear_names(session, names, **kwargs):
        captured["cleared"].append(names)

    async def bulk_upsert(session, rows, *, update_published_metadata):
        if rows:
            captured["batches"].append((update_published_metadata, rows))

    monkeypatch.setattr(service.limits_service, "lock_quota_capacity", no_op)
    monkeypatch.setattr(service.limits_service, "require_limit_available", no_op)
    monkeypatch.setattr(
        service.repository,
        "count_server_versions_for_organization",
        count_versions,
    )
    monkeypatch.setattr(service.repository, "get_server_version_statuses", get_statuses)
    monkeypatch.setattr(service.repository, "clear_latest_for_names", clear_names)
    monkeypatch.setattr(service.repository, "bulk_upsert_server_versions", bulk_upsert)
    return captured


class FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self.values)

    def all(self) -> list[object]:
        return self.values


class FakeToolRepositorySession(FakeSession):
    def __init__(self, existing: list[object] | None = None) -> None:
        super().__init__()
        self.existing = existing or []

    async def execute(self, *args, **kwargs) -> FakeScalarResult:
        return FakeScalarResult(self.existing)


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


def catalog_source() -> MCPCatalogSource:
    return MCPCatalogSource(
        id=uuid4(),
        organization_id=ORGANIZATION_ID,
        name="Wardn Hub",
        provider="wardn_hub",
        base_url="https://hub.wardnai.dev",
        auth_secret_handle_id=uuid4(),
        tenant_id="",
        sync_mode="latest_only",
        is_enabled=True,
        last_error="",
    )


def test_install_request_accepts_file_config_values() -> None:
    payload = MCPServerInstallRequest(
        configValues={
            "KUBECONFIG": {
                "type": "file",
                "filename": "config",
                "contentBase64": "YXBpVmVyc2lvbjogdjEK",
            },
            "LOG_LEVEL": "debug",
        }
    )

    assert payload.config_values["LOG_LEVEL"] == "debug"
    file_value = payload.config_values["KUBECONFIG"]
    assert not isinstance(file_value, str)
    assert file_value.filename == "config"
    assert file_value.content_base64 == "YXBpVmVyc2lvbjogdjEK"


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


def pulsemcp_registry_payload(version: str, *, is_latest: bool) -> MCPServerCreate:
    return MCPServerCreate(
        **{
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "version": version,
            "_meta": {
                "com.pulsemcp/server": {
                    "visitorsEstimateMostRecentWeek": 1250,
                    "isOfficial": True,
                },
                "com.pulsemcp/server-version": {
                    "source": "registry.modelcontextprotocol.io",
                    "status": "active",
                    "publishedAt": "2026-06-21T00:00:00Z",
                    "updatedAt": "2026-06-22T00:00:00Z",
                    "isLatest": is_latest,
                },
            },
        }
    )


@pytest.mark.asyncio
async def test_list_servers_translates_invalid_keyset_cursor(monkeypatch) -> None:
    async def invalid_cursor(*args, **kwargs):
        raise InvalidCursorError("invalid cursor")

    monkeypatch.setattr(service.repository, "list_servers", invalid_cursor)

    with pytest.raises(InvalidRegistryCursorError):
        await service.list_servers(
            FakeSession(),
            cursor="invalid",
            limit=50,
            include_deleted=False,
            organization_id=ORGANIZATION_ID,
        )


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
        return server_version("1.0.0", is_latest=True)

    monkeypatch.setattr(service.repository, "get_server_version", existing_server)

    with pytest.raises(DuplicateMCPServerVersionError):
        await service.create_server_version(FakeSession(), registry_payload())


@pytest.mark.asyncio
async def test_create_server_version_reactivates_deleted_version(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    server = server_version("1.0.0", is_latest=False)
    server.status = "deleted"
    server.status_message = "Deleted from Wardn catalog."

    async def existing_server(*args, **kwargs):
        return server

    async def clear_latest(*args, **kwargs):
        calls.append(("clear_latest", args[1]))

    monkeypatch.setattr(service.repository, "get_server_version", existing_server)
    monkeypatch.setattr(service.repository, "clear_latest_for_name", clear_latest)
    session = FakeSession()

    response = await service.create_server_version(session, registry_payload())

    assert calls == [("clear_latest", "io.github.example/weather")]
    assert response.server.name == "io.github.example/weather"
    assert response.meta.official.status == "active"
    assert response.meta.official.is_latest is True
    assert server.status == "active"
    assert server.status_message == ""
    assert server.is_latest is True
    assert session.flushed is True
    assert session.refreshed == [server]


@pytest.mark.asyncio
async def test_sync_supported_servers_upserts_curated_entries(monkeypatch) -> None:
    captured = patch_bulk_sync_dependencies(monkeypatch)
    session = FakeSession()

    count = await service.sync_supported_servers(
        session,
        [registry_payload("1.0.0"), registry_payload("1.1.0")],
        organization_id=ORGANIZATION_ID,
    )

    assert count == 2
    assert captured["cleared"] == [{"io.github.example/weather"}]
    assert session.flushed is True
    assert len(captured["batches"]) == 1
    update_metadata, rows = captured["batches"][0]
    assert update_metadata is False
    assert [row["version"] for row in rows] == ["1.0.0", "1.1.0"]
    assert [row["is_latest"] for row in rows] == [False, True]


@pytest.mark.asyncio
async def test_create_catalog_source_stores_source_url(monkeypatch) -> None:
    handle_id = uuid4()
    calls = {}

    async def missing_source(*args, **kwargs):
        return None

    async def create_catalog_source_token_handle(*args, **kwargs):
        calls["token"] = kwargs
        return service.CatalogSourceTokenHandle(handle_id=handle_id)

    monkeypatch.setattr(service.repository, "get_catalog_source_by_name", missing_source)
    monkeypatch.setattr(service.repository, "get_catalog_source_by_url", missing_source)
    monkeypatch.setattr(
        catalog_service,
        "create_catalog_source_token_handle",
        create_catalog_source_token_handle,
    )
    session = FakeSession()

    response = await service.create_catalog_source(
        session,
        USER,
        ORGANIZATION_ID,
        MCPCatalogSourceCreate(
            name="Wardn Hub",
            baseUrl="https://hub.wardnai.dev/",
            provider="wardn_hub",
            apiTokenSecretStoreId=uuid4(),
            apiToken="hub-token",
        ),
    )

    assert response.name == "Wardn Hub"
    assert response.base_url == "https://hub.wardnai.dev"
    assert response.has_auth_token is True
    assert session.added[0].base_url == "https://hub.wardnai.dev"
    assert session.added[0].auth_secret_handle_id == handle_id
    assert calls["token"]["required"] is True
    assert session.flushed is True


@pytest.mark.asyncio
async def test_sync_catalog_source_fetches_and_writes_server_definitions(monkeypatch) -> None:
    source = catalog_source()
    payload = registry_payload("1.0.0")
    calls = {}

    async def get_catalog_source(*args, **kwargs):
        return source

    async def resolve_secret(*args, **kwargs):
        return SimpleNamespace(value="hub-token")

    def registry_headers(*args, **kwargs):
        return {"x-test": "1"}

    def iter_supported_server_batches_from_registry_url(source_url, **kwargs):
        calls["source_url"] = source_url
        calls["kwargs"] = kwargs
        return iter([[payload]])

    async def sync_supported_servers(*args, **kwargs):
        calls["servers"] = list(args[1])
        calls["organization_id"] = kwargs["organization_id"]
        calls["catalog_source_id"] = kwargs["catalog_source_id"]
        return 1

    from app.modules.mcp_registry import commands

    monkeypatch.setattr(service.repository, "get_catalog_source", get_catalog_source)
    monkeypatch.setattr(catalog_service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(commands, "registry_headers", registry_headers)
    monkeypatch.setattr(
        commands,
        "iter_supported_server_batches_from_registry_url",
        iter_supported_server_batches_from_registry_url,
    )
    monkeypatch.setattr(catalog_service, "sync_supported_servers", sync_supported_servers)
    session = FakeSession()

    response = await service.sync_catalog_source(session, ORGANIZATION_ID, source.id)

    assert response.synced_count == 1
    assert calls["source_url"] == "https://hub.wardnai.dev/api/v1/mcp/servers"
    assert calls["kwargs"]["version"] == "latest"
    assert calls["kwargs"]["pagination"] == "cursor"
    assert calls["kwargs"]["wardn_hub_version_details"] is True
    assert calls["kwargs"]["headers"]["Authorization"] == "Bearer hub-token"
    assert calls["kwargs"]["headers"]["X-API-Key"] == "hub-token"
    assert calls["servers"][0].name == payload.name
    assert calls["servers"][0].meta[service.CATALOG_SOURCE_META_KEY] == {
        "id": str(source.id),
        "name": "Wardn Hub",
        "provider": "wardn_hub",
        "baseUrl": "https://hub.wardnai.dev",
        "sourceUrl": "https://hub.wardnai.dev/api/v1/mcp/servers",
    }
    assert calls["organization_id"] == ORGANIZATION_ID
    assert calls["catalog_source_id"] == source.id
    assert session.commit_count == 1
    assert source.last_success_at is not None
    assert source.last_error == ""


@pytest.mark.asyncio
async def test_sync_catalog_source_fetches_only_wardn_hub_changes_after_watermark(
    monkeypatch,
) -> None:
    source = catalog_source()
    source.last_synced_updated_since = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    payload = registry_payload("1.0.1")
    calls = {}

    async def get_catalog_source(*args, **kwargs):
        return source

    async def resolve_secret(*args, **kwargs):
        return SimpleNamespace(value="hub-token")

    def registry_headers(*args, **kwargs):
        return {"x-test": "1"}

    def iter_supported_server_batches_from_registry_url(source_url, **kwargs):
        calls["source_url"] = source_url
        calls["kwargs"] = kwargs
        return iter([[payload]])

    async def sync_supported_servers(*args, **kwargs):
        calls["servers"] = list(args[1])
        calls["organization_id"] = kwargs["organization_id"]
        calls["catalog_source_id"] = kwargs["catalog_source_id"]
        return 1

    from app.modules.mcp_registry import commands

    monkeypatch.setattr(service.repository, "get_catalog_source", get_catalog_source)
    monkeypatch.setattr(catalog_service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(commands, "registry_headers", registry_headers)
    monkeypatch.setattr(
        commands,
        "iter_supported_server_batches_from_registry_url",
        iter_supported_server_batches_from_registry_url,
    )
    monkeypatch.setattr(catalog_service, "sync_supported_servers", sync_supported_servers)
    session = FakeSession()

    response = await service.sync_catalog_source(session, ORGANIZATION_ID, source.id)

    assert response.synced_count == 1
    assert calls["source_url"] == "https://hub.wardnai.dev/api/v1/mcp/servers"
    assert calls["kwargs"]["updated_since"] == "2026-07-28T12:00:00Z"
    assert calls["kwargs"]["version"] == "latest"
    assert calls["kwargs"]["pagination"] == "cursor"
    assert calls["kwargs"]["wardn_hub_version_details"] is True
    settings = catalog_service.get_settings()
    assert calls["kwargs"]["wardn_hub_version_detail_concurrency"] == (
        settings.mcp_catalog_sync_detail_concurrency
    )
    assert calls["kwargs"]["request_interval_seconds"] == (
        settings.mcp_catalog_sync_request_interval_seconds
    )
    assert calls["kwargs"]["retry_max_attempts"] == (
        settings.mcp_catalog_sync_retry_max_attempts
    )
    assert calls["servers"][0].meta[service.CATALOG_SOURCE_META_KEY]["sourceUrl"] == (
        "https://hub.wardnai.dev/api/v1/mcp/servers"
    )
    assert calls["organization_id"] == ORGANIZATION_ID
    assert calls["catalog_source_id"] == source.id
    assert session.commit_count == 1
    assert source.last_success_at is not None
    assert source.last_synced_updated_since > datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    assert source.last_error == ""


@pytest.mark.asyncio
async def test_sync_catalog_source_failure_uses_cached_source_metadata_after_rollback(
    monkeypatch,
    caplog,
) -> None:
    class ExpiringCatalogSource:
        def __init__(self) -> None:
            self.id = uuid4()
            self.organization_id = ORGANIZATION_ID
            self.provider = "wardn_hub"
            self.base_url = "https://hub.wardnai.dev"
            self.auth_secret_handle_id = uuid4()
            self.tenant_id = ""
            self.sync_mode = "latest_only"
            self.is_enabled = True
            self.last_synced_updated_since = None
            self.last_error = ""
            self.expired = False

        @property
        def name(self) -> str:
            if self.expired:
                raise AssertionError("expired source name accessed")
            return "Wardn Hub"

    class ExpiringSession(FakeSession):
        async def rollback(self) -> None:
            await super().rollback()
            source.expired = True

    class TimeoutIterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise TimeoutError("registry offline")

    source = ExpiringCatalogSource()

    async def get_catalog_source(*args, **kwargs):
        return source

    async def catalog_source_auth_headers(*args, **kwargs):
        return {}

    def registry_headers(*args, **kwargs):
        return {"x-test": "1"}

    def iter_supported_server_batches_from_registry_url(*args, **kwargs):
        return TimeoutIterator()

    from app.modules.mcp_registry import commands

    monkeypatch.setattr(service.repository, "get_catalog_source", get_catalog_source)
    monkeypatch.setattr(
        catalog_service,
        "catalog_source_auth_headers",
        catalog_source_auth_headers,
    )
    monkeypatch.setattr(commands, "registry_headers", registry_headers)
    monkeypatch.setattr(
        commands,
        "iter_supported_server_batches_from_registry_url",
        iter_supported_server_batches_from_registry_url,
    )
    caplog.set_level(logging.WARNING, logger=catalog_service.logger.name)
    session = ExpiringSession()

    with pytest.raises(ValueError) as error:
        await service.sync_catalog_source(session, ORGANIZATION_ID, source.id)

    assert "registry offline" in str(error.value)
    assert "expired source name accessed" not in str(error.value)
    assert "registry offline" in source.last_error
    assert session.rollback_count == 2
    warning_records = [
        record
        for record in caplog.records
        if record.message
        in {
            "MCP catalog source URL failed.",
            "MCP catalog source sync failed.",
        }
    ]
    assert [record.mcp_catalog_source_name for record in warning_records] == [
        "Wardn Hub",
        "Wardn Hub",
    ]


@pytest.mark.asyncio
async def test_sync_catalog_source_commits_and_clears_each_batch(monkeypatch, caplog) -> None:
    source = catalog_source()
    batches = [
        [registry_payload(f"1.0.{index}") for index in range(100)],
        [registry_payload(f"1.1.{index}") for index in range(100)],
        [registry_payload("1.2.0")],
    ]
    calls = {"batch_lengths": []}

    async def get_catalog_source(*args, **kwargs):
        return source

    async def resolve_secret(*args, **kwargs):
        return SimpleNamespace(value="hub-token")

    def registry_headers(*args, **kwargs):
        return {"x-test": "1"}

    def iter_supported_server_batches_from_registry_url(source_url, **kwargs):
        calls["source_url"] = source_url
        calls["kwargs"] = kwargs
        return iter(batches)

    async def sync_supported_servers(*args, **kwargs):
        calls["batch_lengths"].append(len(args[1]))
        return len(args[1])

    from app.modules.mcp_registry import commands

    monkeypatch.setattr(service.repository, "get_catalog_source", get_catalog_source)
    monkeypatch.setattr(catalog_service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(commands, "registry_headers", registry_headers)
    monkeypatch.setattr(
        commands,
        "iter_supported_server_batches_from_registry_url",
        iter_supported_server_batches_from_registry_url,
    )
    monkeypatch.setattr(catalog_service, "sync_supported_servers", sync_supported_servers)
    session = FakeSession()
    caplog.set_level(logging.INFO, logger=catalog_service.logger.name)

    response = await service.sync_catalog_source(session, ORGANIZATION_ID, source.id)

    assert response.synced_count == 201
    assert calls["batch_lengths"] == [100, 100, 1]
    assert calls["kwargs"]["limit"] == 100
    assert session.commit_count == 3
    assert batches == [[], [], []]
    batch_records = [
        record
        for record in caplog.records
        if record.message == "Synced MCP catalog source batch."
    ]
    assert [record.mcp_catalog_batch_size for record in batch_records] == [100, 100, 1]
    assert batch_records[-1].mcp_catalog_synced_count == 201


@pytest.mark.asyncio
async def test_delete_catalog_source_deletes_associated_server_versions(monkeypatch) -> None:
    source = catalog_source()
    server = server_version("1.0.0", is_latest=True)
    replacement = server_version("0.9.0", is_latest=False)
    calls: list[tuple[str, str]] = []

    async def get_catalog_source(*args, **kwargs):
        return source

    async def list_server_versions_for_catalog_source(*args, **kwargs):
        calls.append(("list_source_versions", str(kwargs["source_id"])))
        return [server]

    async def get_latest_visible_version(*args, **kwargs):
        calls.append(("replacement", args[1]))
        return replacement

    monkeypatch.setattr(service.repository, "get_catalog_source", get_catalog_source)
    monkeypatch.setattr(
        service.repository,
        "list_server_versions_for_catalog_source",
        list_server_versions_for_catalog_source,
    )
    monkeypatch.setattr(
        service.repository,
        "get_latest_visible_version",
        get_latest_visible_version,
    )
    session = FakeSession()

    await service.delete_catalog_source(session, ORGANIZATION_ID, source.id)

    assert ("list_source_versions", str(source.id)) in calls
    assert ("replacement", server.name) in calls
    assert server.status == "deleted"
    assert server.status_message == "Deleted with catalog source Wardn Hub."
    assert server.is_latest is False
    assert replacement.is_latest is True
    assert session.deleted == [source]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_delete_catalog_source_deletes_legacy_single_source_catalog_rows(
    monkeypatch,
) -> None:
    source = catalog_source()
    server = server_version("1.0.0", is_latest=True)
    calls: list[str] = []

    async def get_catalog_source(*args, **kwargs):
        return source

    async def list_server_versions_for_catalog_source(*args, **kwargs):
        calls.append("tagged")
        return []

    async def list_catalog_sources(*args, **kwargs):
        calls.append("sources")
        return [source]

    async def list_legacy_catalog_server_versions(*args, **kwargs):
        calls.append("legacy")
        return [server]

    async def get_latest_visible_version(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_catalog_source", get_catalog_source)
    monkeypatch.setattr(
        service.repository,
        "list_server_versions_for_catalog_source",
        list_server_versions_for_catalog_source,
    )
    monkeypatch.setattr(service.repository, "list_catalog_sources", list_catalog_sources)
    monkeypatch.setattr(
        service.repository,
        "list_legacy_catalog_server_versions",
        list_legacy_catalog_server_versions,
    )
    monkeypatch.setattr(
        service.repository,
        "get_latest_visible_version",
        get_latest_visible_version,
    )

    await service.delete_catalog_source(FakeSession(), ORGANIZATION_ID, source.id)

    assert calls == ["tagged", "sources", "legacy"]
    assert server.status == "deleted"
    assert server.is_latest is False


@pytest.mark.asyncio
async def test_sync_supported_servers_uses_official_latest_metadata(monkeypatch) -> None:
    captured = patch_bulk_sync_dependencies(monkeypatch)
    session = FakeSession()

    count = await service.sync_supported_servers(
        session,
        [
            official_registry_payload("1.1.0", is_latest=True),
            official_registry_payload("1.0.0", is_latest=False),
        ],
        organization_id=ORGANIZATION_ID,
    )

    assert count == 2
    _, rows = captured["batches"][0]
    assert [row["version"] for row in rows] == ["1.1.0", "1.0.0"]
    assert [row["is_latest"] for row in rows] == [True, False]


@pytest.mark.asyncio
async def test_sync_supported_servers_uses_pulsemcp_latest_metadata(monkeypatch) -> None:
    captured = patch_bulk_sync_dependencies(monkeypatch)
    session = FakeSession()

    count = await service.sync_supported_servers(
        session,
        [
            pulsemcp_registry_payload("1.1.0", is_latest=True),
            pulsemcp_registry_payload("1.0.0", is_latest=False),
        ],
        organization_id=ORGANIZATION_ID,
    )

    assert count == 2
    _, rows = captured["batches"][0]
    assert [row["version"] for row in rows] == ["1.1.0", "1.0.0"]
    assert [row["is_latest"] for row in rows] == [True, False]
    assert rows[0]["published_at"] == datetime(2026, 6, 21, tzinfo=UTC)
    assert rows[0]["status_changed_at"] == datetime(2026, 6, 22, tzinfo=UTC)
    assert (
        rows[0]["server_json"]["_meta"]["com.pulsemcp/server"]["isOfficial"] is True
    )


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


def patch_runtime_provider(monkeypatch, provider_name: str) -> None:
    monkeypatch.setattr(
        installation_service,
        "get_runtime_manager",
        lambda: SimpleNamespace(provider_name=lambda installation: provider_name),
    )


@pytest.mark.parametrize(
    ("installed_version", "latest_version", "expected"),
    [
        ("1.3.1", "1.3.0", False),
        ("2.0.0", "1.0.31", False),
        ("0.16.0", "v0.16.0", False),
        ("1.0.0", "1.0.1", True),
        ("1.0", "1.0.0", False),
    ],
)
def test_server_update_available_compares_version_numbers(
    installed_version: str,
    latest_version: str,
    expected: bool,
) -> None:
    assert service.server_update_available(installed_version, latest_version) is expected


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
        secret_references={
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


def test_persist_install_secret_references_overwrites_local_manifest(tmp_path) -> None:
    secret_path = tmp_path / "runtime.secrets.json"
    secret_path.write_text('{"environment":{"WEATHER_TOKEN":"raw-token"}}', encoding="utf-8")

    service.persist_install_secret_references(
        str(tmp_path),
        {
            "environment": {
                "WEATHER_TOKEN": {
                    "type": "secret_handle",
                    "secretHandleId": str(uuid4()),
                }
            }
        },
    )

    stored = json.loads(secret_path.read_text(encoding="utf-8"))
    assert stored["environment"]["WEATHER_TOKEN"]["type"] == "secret_handle"


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
async def test_update_server_version_reactivates_deleted_version(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    server = server_version("1.0.0", is_latest=False)
    server.status = "deleted"
    server.status_message = "Deleted from Wardn catalog."
    payload = registry_payload("1.0.0")
    payload.title = "Updated Weather"

    async def get_server_version(*args, **kwargs):
        return server

    async def clear_latest(*args, **kwargs):
        calls.append(("clear_latest", args[1]))

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "clear_latest_for_name", clear_latest)
    session = FakeSession()

    response = await service.update_server_version(
        session,
        "io.github.example/weather",
        "1.0.0",
        payload,
    )

    assert calls == [("clear_latest", "io.github.example/weather")]
    assert response.server.title == "Updated Weather"
    assert response.meta.official.status == "active"
    assert response.meta.official.is_latest is True
    assert server.status == "active"
    assert server.status_message == ""
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
    catalog_server = server_version("1.0.0", is_latest=True)

    async def get_server_version(*args, **kwargs):
        return catalog_server

    async def get_installation(*args, **kwargs):
        return None

    telemetry_calls = []

    def schedule_telemetry(server, *, install_type):
        telemetry_calls.append({"server": server, "install_type": install_type})
        return None

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        installation_service,
        "install_server_runtime",
        lambda server, **kwargs: runtime_install(),
    )
    monkeypatch.setattr(
        installation_service,
        "schedule_mcp_server_install_telemetry",
        schedule_telemetry,
    )
    session = FakeSession()

    response = await service.install_server_version(
        session,
        "io.github.example/weather",
        MCPServerInstallRequest(version="latest"),
        workspace_id=WORKSPACE_ID,
    )

    assert response.server_name == "io.github.example/weather"
    assert response.config_name == "default"
    assert response.workspace_id == WORKSPACE_ID
    assert response.installed_version == "1.0.0"
    assert response.latest_version == "1.0.0"
    assert response.update_available is False
    assert response.install_type == "remote"
    assert response.runtime_config["kind"] == "remote"
    assert session.flushed is True
    assert telemetry_calls == [{"server": catalog_server, "install_type": "remote"}]


@pytest.mark.asyncio
async def test_install_server_version_preserves_existing_config_values(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        secret_references={
            "environment": {"WEATHER_TOKEN": "old-token", "WEATHER_URL": "old-url"},
            "packageArguments": {"LOG_LEVEL": "warn", "READ_ONLY": "true"},
        },
    )
    seen = {}

    async def get_server_version(*args, **kwargs):
        server = server_version("1.0.0", is_latest=True)
        server.remotes = [{"type": "streamable-http", "url": "https://hub.wardnai.dev/mcp"}]
        return server

    async def get_installation(*args, **kwargs):
        return installation

    def install_runtime(server, **kwargs):
        seen["config_values"] = kwargs["config_values"]
        return runtime_install()

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    patch_runtime_provider(monkeypatch, "kubernetes")
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
        workspace_id=WORKSPACE_ID,
    )

    assert seen["config_values"] == {
        "WEATHER_TOKEN": "old-token",
        "WEATHER_URL": "new-url",
        "LOG_LEVEL": "debug",
        "READ_ONLY": "true",
    }


@pytest.mark.asyncio
async def test_install_server_version_preserves_explicit_empty_package_argument(
    monkeypatch,
) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        secret_references={"packageArguments": {"services": "apps"}},
    )
    seen = {}

    async def get_server_version(*args, **kwargs):
        server = server_version("1.0.0", is_latest=True)
        server.packages = [
            {
                "registryType": "npm",
                "identifier": "@digitalocean/mcp",
                "version": "1.0.67",
                "transport": {"type": "stdio"},
                "packageArguments": [
                    {
                        "name": "services",
                        "flag": "--services",
                        "default": "apps",
                    },
                ],
            }
        ]
        return server

    async def get_installation(*args, **kwargs):
        return installation

    def install_runtime(server, **kwargs):
        seen["config_values"] = kwargs["config_values"]
        return runtime_install()

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    patch_runtime_provider(monkeypatch, "kubernetes")

    await service.install_server_version(
        FakeSession(),
        "io.github.example/weather",
        MCPServerInstallRequest(
            version="latest",
            installTarget="package",
            configValues={"services": ""},
        ),
        workspace_id=WORKSPACE_ID,
    )

    assert seen["config_values"]["services"] == ""


@pytest.mark.asyncio
async def test_install_server_version_passes_network_policy_config(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        secret_references={"environment": {"WEATHER_TOKEN": "old-token"}},
        runtime_config={
            "kind": "remote",
            "networkPolicy": {
                "isolationEnabled": True,
                "publicEgress": True,
            },
        },
    )
    seen = {}

    async def get_server_version(*args, **kwargs):
        server = server_version("1.0.0", is_latest=True)
        server.remotes = [{"type": "streamable-http", "url": "https://hub.wardnai.dev/mcp"}]
        return server

    async def get_installation(*args, **kwargs):
        return installation

    def install_runtime(server, **kwargs):
        seen["network_policy"] = kwargs["network_policy"]
        return runtime_install()

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    patch_runtime_provider(monkeypatch, "kubernetes")
    session = FakeSession()

    await service.install_server_version(
        session,
        "io.github.example/weather",
            MCPServerInstallRequest(
                version="latest",
                installTarget="package",
                networkPolicy={
                    "allowKubernetesApi": True,
                    "allowRemoteMcpEgress": True,
                    "denyOtherEgress": True,
                    "customEgress": [
                        {
                            "label": "unifi-access",
                            "cidr": "192.168.3.1/32",
                            "ports": [443],
                        }
                    ],
                },
            ),
        workspace_id=WORKSPACE_ID,
    )

    assert seen["network_policy"] == {
        "mode": "intent",
        "allowKubernetesApi": True,
        "allowRemoteMcpEgress": True,
        "allowRuntimeDependencyEgress": True,
        "denyOtherEgress": True,
        "isolationEnabled": True,
        "publicEgress": False,
        "privateEgress": False,
        "privateEgressPorts": [80, 443],
        "inClusterKubernetesApi": True,
        "customEgress": [
            {
                "destinationType": "cidr",
                "label": "unifi-access",
                "cidr": "192.168.3.1/32",
                "domain": "",
                "ports": [443],
            }
        ],
        "remoteDestinations": [
            {
                "label": "streamable-http",
                "host": "hub.wardnai.dev",
                "port": 443,
            },
        ],
    }


@pytest.mark.asyncio
async def test_install_server_version_keeps_runtime_dependency_egress_without_remote_endpoints(
    monkeypatch,
) -> None:
    seen = {}

    async def get_server_version(*args, **kwargs):
        return server_version("1.0.0", is_latest=True)

    async def get_installation(*args, **kwargs):
        return None

    def install_runtime(server, **kwargs):
        seen["network_policy"] = kwargs["network_policy"]
        return runtime_install()

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    patch_runtime_provider(monkeypatch, "kubernetes")

    await service.install_server_version(
        FakeSession(),
        "io.github.example/weather",
        MCPServerInstallRequest(
            version="latest",
            installTarget="package",
            networkPolicy={
                "allowRemoteMcpEgress": False,
                "allowRuntimeDependencyEgress": True,
                "denyOtherEgress": True,
            },
        ),
        workspace_id=WORKSPACE_ID,
    )

    assert seen["network_policy"]["allowRemoteMcpEgress"] is False
    assert seen["network_policy"]["allowRuntimeDependencyEgress"] is True
    assert seen["network_policy"]["remoteDestinations"] == []


@pytest.mark.asyncio
async def test_install_server_version_rejects_network_policy_without_kubernetes_provider(
    monkeypatch,
) -> None:
    async def get_server_version(*args, **kwargs):
        return server_version("1.0.0", is_latest=True)

    async def get_installation(*args, **kwargs):
        return None

    def install_runtime(*args, **kwargs):
        raise AssertionError("runtime install should not run for unsupported policy")

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    patch_runtime_provider(monkeypatch, "local")

    with pytest.raises(
        MCPServerInstallationUnsupportedError,
        match="Kubernetes runtime provider",
    ):
        await service.install_server_version(
            FakeSession(),
            "io.github.example/weather",
            MCPServerInstallRequest(
                version="latest",
                installTarget="package",
                networkPolicy={"publicEgress": False},
            ),
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_install_server_version_drops_existing_network_policy_without_kubernetes_provider(
    monkeypatch,
) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        secret_references={},
        runtime_config={
            "kind": "package",
            "networkPolicy": {
                "isolationEnabled": True,
                "publicEgress": False,
            },
        },
    )
    seen: dict[str, object] = {}

    async def get_server_version(*args, **kwargs):
        return server_version("1.0.0", is_latest=True)

    async def get_installation(*args, **kwargs):
        return installation

    def install_runtime(*args, **kwargs):
        seen["network_policy"] = kwargs["network_policy"]
        return runtime_install()

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    patch_runtime_provider(monkeypatch, "local")

    await service.install_server_version(
        FakeSession(),
        "io.github.example/weather",
        MCPServerInstallRequest(version="latest", installTarget="package"),
        workspace_id=WORKSPACE_ID,
    )

    assert seen["network_policy"] is None


@pytest.mark.asyncio
async def test_install_server_version_rejects_policy_blocked_by_limit(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        secret_references={},
        runtime_config={"kind": "package"},
    )
    seen = {"limit_keys": []}

    async def get_server_version(*args, **kwargs):
        return server_version("1.0.0", is_latest=True)

    async def get_installation(*args, **kwargs):
        return installation

    async def require_limit_available(*args, **kwargs):
        seen["limit_keys"].append(kwargs["limit_key"])
        if kwargs["limit_key"] == service.limits_service.MCP_RUNTIME_PRIVATE_EGRESS_PER_WORKSPACE:
            raise LimitExceededError("mcp_runtime_private_egress.per_workspace limit exceeded")

    def install_runtime(*args, **kwargs):
        raise AssertionError("runtime install should not run when policy limit blocks the request")

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        service.limits_service,
        "require_limit_available",
        require_limit_available,
    )
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    patch_runtime_provider(monkeypatch, "kubernetes")

    with pytest.raises(LimitExceededError):
        await service.install_server_version(
            FakeSession(),
            "io.github.example/weather",
            MCPServerInstallRequest(
                version="latest",
                installTarget="package",
                networkPolicy={
                    "publicEgress": False,
                    "privateEgress": True,
                },
            ),
            workspace_id=WORKSPACE_ID,
        )

    assert seen["limit_keys"] == [
        service.limits_service.MCP_RUNTIME_PRIVATE_EGRESS_PER_WORKSPACE,
    ]


@pytest.mark.asyncio
async def test_install_server_version_only_requires_disable_limit_when_isolation_is_off(
    monkeypatch,
) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        secret_references={},
        runtime_config={"kind": "package"},
    )
    seen = {"limit_keys": []}

    async def get_server_version(*args, **kwargs):
        return server_version("1.0.0", is_latest=True)

    async def get_installation(*args, **kwargs):
        return installation

    async def require_limit_available(*args, **kwargs):
        seen["limit_keys"].append(kwargs["limit_key"])

    def install_runtime(*args, **kwargs):
        return runtime_install()

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        service.limits_service,
        "require_limit_available",
        require_limit_available,
    )
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    patch_runtime_provider(monkeypatch, "kubernetes")

    await service.install_server_version(
        FakeSession(),
        "io.github.example/weather",
        MCPServerInstallRequest(
            version="latest",
            installTarget="package",
            networkPolicy={
                "isolationEnabled": False,
                "publicEgress": True,
                "privateEgress": True,
                "customEgress": [
                    {"label": "rancher", "cidr": "192.168.3.3", "ports": [443]},
                ],
            },
        ),
        workspace_id=WORKSPACE_ID,
    )

    assert seen["limit_keys"] == [
        service.limits_service.MCP_RUNTIME_NETWORK_ISOLATION_DISABLE_PER_WORKSPACE,
    ]


@pytest.mark.asyncio
async def test_install_server_version_preserves_existing_file_config_values(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        secret_references={
            "packageArguments": {"KUBECONFIG": "/old/runtime-files/KUBECONFIG"},
            "files": {
                "KUBECONFIG": {
                    "key": "KUBECONFIG",
                    "filename": "config",
                    "content": "apiVersion: v1\nclusters: []\n",
                    "path": "/old/runtime-files/KUBECONFIG",
                    "mountPath": "/opt/wardn/runtime-files/KUBECONFIG",
                }
            },
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
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)

    await service.install_server_version(
        FakeSession(),
        "io.github.example/weather",
        MCPServerInstallRequest(version="latest", configValues={"LOG_LEVEL": "debug"}),
        workspace_id=WORKSPACE_ID,
    )

    assert seen["config_values"] == {
        "KUBECONFIG": {
            "type": "file",
            "filename": "config",
            "content": "apiVersion: v1\nclusters: []\n",
        },
        "LOG_LEVEL": "debug",
    }


def test_secret_references_preserve_file_runtime_paths() -> None:
    handle_id = uuid4()
    runtime_path = "/tmp/wardn/mcp/weather/1.0.0/runtime-files/K8S_AIOPS_CONFIG"
    mount_path = "/opt/wardn/runtime-files/K8S_AIOPS_CONFIG"

    references = config_service.secret_references_from_runtime_secret_config(
        {
            "environment": {
                "K8S_AIOPS_CONFIG": runtime_path,
                "KUBECONFIG": runtime_path,
            },
            "files": {
                "K8S_AIOPS_CONFIG": {
                    "key": "K8S_AIOPS_CONFIG",
                    "filename": "config.yaml",
                    "content": "apiVersion: v1\nclusters: []\n",
                    "path": runtime_path,
                    "mountPath": mount_path,
                }
            },
        },
        {"K8S_AIOPS_CONFIG": handle_id},
    )

    assert references["environment"] == {
        "K8S_AIOPS_CONFIG": runtime_path,
        "KUBECONFIG": runtime_path,
    }
    assert references["files"]["K8S_AIOPS_CONFIG"]["content"] == {
        "type": "secret_handle",
        "secretHandleId": str(handle_id),
    }


def test_secret_references_still_externalize_non_file_environment_values() -> None:
    handle_id = uuid4()

    references = config_service.secret_references_from_runtime_secret_config(
        {
            "environment": {
                "WEATHER_TOKEN": "raw-token",
                "WEATHER_URL": "https://weather.example.com",
            }
        },
        {"WEATHER_TOKEN": handle_id},
    )

    assert references["environment"] == {
        "WEATHER_TOKEN": {
            "type": "secret_handle",
            "secretHandleId": str(handle_id),
        },
        "WEATHER_URL": "https://weather.example.com",
    }


@pytest.mark.asyncio
async def test_install_server_version_writes_raw_secrets_to_backend(monkeypatch) -> None:
    store_id = uuid4()
    handle_id = uuid4()
    secret_values_by_handle: dict[object, str] = {}
    write_calls: list[dict[str, object]] = []
    handle_calls: list[object] = []
    seen: dict[str, object] = {}

    server = server_version("1.0.0", is_latest=True)
    server.packages = [
        {
            "registryType": "oci",
            "identifier": "ghcr.io/example/weather",
            "environmentVariables": [
                {"name": "WEATHER_TOKEN", "isSecret": True},
                {"name": "WEATHER_URL"},
            ],
        }
    ]

    async def get_server_version(*args, **kwargs):
        return server

    async def get_installation(*args, **kwargs):
        return None

    async def organization_id_for_workspace(*args, **kwargs):
        return ORGANIZATION_ID

    async def write_secret_values(*args, **kwargs):
        write_calls.append({"args": args, "kwargs": kwargs})

    async def create_secret_handle(*args, **kwargs):
        payload = args[3]
        handle_calls.append(payload)
        secret_values_by_handle[handle_id] = "raw-token"
        return SimpleNamespace(id=handle_id)

    async def resolve_secret(*args, **kwargs):
        requested_handle_id = args[2]
        return SimpleNamespace(value=secret_values_by_handle[requested_handle_id])

    def install_runtime(_server, **kwargs):
        seen["config_values"] = kwargs["config_values"]
        return MCPRuntimeInstall(
            install_type="package",
            install_path="/tmp/wardn/mcp/weather/1.0.0",
            runtime_config={"kind": "package"},
            secret_config={
                "environment": {
                    "WEATHER_TOKEN": kwargs["config_values"]["WEATHER_TOKEN"],
                    "WEATHER_URL": kwargs["config_values"]["WEATHER_URL"],
                }
            },
            status="enabled",
        )

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        installation_service,
        "organization_id_for_workspace",
        organization_id_for_workspace,
    )
    monkeypatch.setattr(config_service, "write_secret_values", write_secret_values)
    monkeypatch.setattr(config_service, "create_secret_handle", create_secret_handle)
    monkeypatch.setattr(config_service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    monkeypatch.setattr(
        config_service,
        "get_runtime_manager",
        lambda: SimpleNamespace(provider_name=lambda installation: "local"),
    )
    session = FakeSession()

    await service.install_server_version(
        session,
        "io.github.example/weather",
        MCPServerInstallRequest(
            configSecretStoreId=store_id,
            configValues={
                "WEATHER_TOKEN": "raw-token",
                "WEATHER_URL": "https://weather.example.com",
            },
            installTarget="package",
        ),
        workspace_id=WORKSPACE_ID,
        user=USER,
    )

    assert seen["config_values"] == {
        "WEATHER_TOKEN": "raw-token",
        "WEATHER_URL": "https://weather.example.com",
    }
    assert write_calls[0]["args"][3] == store_id
    assert write_calls[0]["kwargs"]["workspace_id"] == WORKSPACE_ID
    assert write_calls[0]["kwargs"]["values"] == {"WEATHER_TOKEN": "raw-token"}
    assert handle_calls[0].store_id == store_id
    assert handle_calls[0].workspace_id == WORKSPACE_ID
    assert handle_calls[0].purpose == "mcp_env"
    installation = session.added[0]
    assert installation.secret_references == {
        "environment": {
            "WEATHER_TOKEN": {
                "type": "secret_handle",
                "secretHandleId": str(handle_id),
            },
            "WEATHER_URL": "https://weather.example.com",
        }
    }


@pytest.mark.asyncio
async def test_install_server_version_updates_existing_secret_handle_in_place(
    monkeypatch,
) -> None:
    store_id = uuid4()
    handle_id = uuid4()
    write_calls: list[dict[str, object]] = []
    seen: dict[str, object] = {}
    handle = SecretHandle(
        id=handle_id,
        organization_id=ORGANIZATION_ID,
        workspace_id=WORKSPACE_ID,
        store_id=store_id,
        purpose="mcp_env",
        display_name="MCP default WEATHER_TOKEN",
        external_ref="wardn/orgs/acme/mcp/weather/default",
        key_name="WEATHER_TOKEN",
        version="1",
    )
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        secret_references={
            "environment": {
                "WEATHER_TOKEN": {
                    "type": "secret_handle",
                    "secretHandleId": str(handle_id),
                },
                "WEATHER_URL": "https://weather.example.com",
            }
        },
    )
    server = server_version("1.0.0", is_latest=True)
    server.packages = [
        {
            "registryType": "oci",
            "identifier": "ghcr.io/example/weather",
            "environmentVariables": [
                {"name": "WEATHER_TOKEN", "isSecret": True},
                {"name": "WEATHER_URL"},
            ],
        }
    ]

    async def get_server_version(*args, **kwargs):
        return server

    async def get_installation(*args, **kwargs):
        return installation

    async def organization_id_for_workspace(*args, **kwargs):
        return ORGANIZATION_ID

    async def get_handle(*args, **kwargs):
        assert kwargs["organization_id"] == ORGANIZATION_ID
        assert kwargs["handle_id"] == handle_id
        return handle

    async def write_secret_values(*args, **kwargs):
        write_calls.append({"args": args, "kwargs": kwargs})
        return SecretWriteResult(version="2")

    async def create_secret_handle(*args, **kwargs):
        raise AssertionError("existing MCP secret handle should be reused")

    async def resolve_secret(*args, **kwargs):
        requested_handle_id = args[2]
        assert requested_handle_id == handle_id
        return SimpleNamespace(value="new-token")

    def install_runtime(_server, **kwargs):
        seen["config_values"] = kwargs["config_values"]
        return MCPRuntimeInstall(
            install_type="package",
            install_path="/tmp/wardn/mcp/weather/1.0.0",
            runtime_config={"kind": "package"},
            secret_config={
                "environment": {
                    "WEATHER_TOKEN": kwargs["config_values"]["WEATHER_TOKEN"],
                    "WEATHER_URL": kwargs["config_values"]["WEATHER_URL"],
                }
            },
            status="enabled",
        )

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        installation_service,
        "organization_id_for_workspace",
        organization_id_for_workspace,
    )
    monkeypatch.setattr(config_service.secrets_repository, "get_handle", get_handle)
    monkeypatch.setattr(config_service, "write_secret_values", write_secret_values)
    monkeypatch.setattr(config_service, "create_secret_handle", create_secret_handle)
    monkeypatch.setattr(config_service, "resolve_secret", resolve_secret)
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    monkeypatch.setattr(
        config_service,
        "get_runtime_manager",
        lambda: SimpleNamespace(provider_name=lambda installation: "local"),
    )
    session = FakeSession()

    await service.install_server_version(
        session,
        "io.github.example/weather",
        MCPServerInstallRequest(
            configValues={"WEATHER_TOKEN": "new-token"},
            installTarget="package",
        ),
        workspace_id=WORKSPACE_ID,
        user=USER,
    )

    assert seen["config_values"] == {
        "WEATHER_TOKEN": "new-token",
        "WEATHER_URL": "https://weather.example.com",
    }
    assert write_calls[0]["args"][3] == store_id
    assert write_calls[0]["kwargs"]["workspace_id"] == WORKSPACE_ID
    assert write_calls[0]["kwargs"]["external_ref"] == handle.external_ref
    assert write_calls[0]["kwargs"]["values"] == {"WEATHER_TOKEN": "new-token"}
    assert handle.version == "2"
    assert installation.secret_references == {
        "environment": {
            "WEATHER_TOKEN": {
                "type": "secret_handle",
                "secretHandleId": str(handle_id),
            },
            "WEATHER_URL": "https://weather.example.com",
        }
    }


@pytest.mark.asyncio
async def test_install_server_version_rejects_raw_secrets_without_backend(monkeypatch) -> None:
    server = server_version("1.0.0", is_latest=True)
    server.packages = [
        {
            "registryType": "oci",
            "identifier": "ghcr.io/example/weather",
            "environmentVariables": [{"name": "WEATHER_TOKEN", "isSecret": True}],
        }
    ]

    async def get_server_version(*args, **kwargs):
        return server

    async def get_installation(*args, **kwargs):
        return None

    async def organization_id_for_workspace(*args, **kwargs):
        return ORGANIZATION_ID

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        installation_service,
        "organization_id_for_workspace",
        organization_id_for_workspace,
    )

    with pytest.raises(MCPServerInstallationUnsupportedError, match="secret backend is required"):
        await service.install_server_version(
            FakeSession(),
            "io.github.example/weather",
            MCPServerInstallRequest(
                configValues={"WEATHER_TOKEN": "raw-token"},
                installTarget="package",
            ),
            workspace_id=WORKSPACE_ID,
            user=USER,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_install_type", ["package", "npm"])
async def test_install_server_version_validates_kubernetes_package_runtime(
    monkeypatch,
    runtime_install_type: str,
) -> None:
    server = server_version("1.0.0", is_latest=True)
    server.packages = [
        {
            "registryType": "oci",
            "identifier": "ghcr.io/example/weather",
            "transport": {"type": "stdio"},
        }
    ]
    seen: dict[str, object] = {}

    class FakeRuntimeManager:
        def provider_name(self, installation):
            seen["provider_installation"] = installation
            return config_service.RUNTIME_PROVIDER_KUBERNETES

    async def get_server_version(*args, **kwargs):
        return server

    async def get_installation(*args, **kwargs):
        return None

    async def organization_id_for_workspace(*args, **kwargs):
        return ORGANIZATION_ID

    async def refresh_tool_schemas_for_installation(*args, **kwargs):
        seen["refresh_session"] = args[0]
        seen["refresh_installation"] = kwargs["installation"]
        seen["refresh_server"] = kwargs["server"]
        seen["refresh_manager"] = kwargs["runtime_manager"]
        seen["refresh_prefer_registry_metadata"] = kwargs["prefer_registry_metadata"]

    def install_runtime(_server, **kwargs):
        return MCPRuntimeInstall(
            install_type=runtime_install_type,
            install_path="/tmp/wardn/mcp/weather/1.0.0",
            runtime_config={"kind": "package"},
            secret_config={},
            status="enabled",
        )

    manager = FakeRuntimeManager()
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        installation_service,
        "organization_id_for_workspace",
        organization_id_for_workspace,
    )
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    monkeypatch.setattr(config_service, "get_runtime_manager", lambda: manager)
    monkeypatch.setattr(
        config_service,
        "refresh_tool_schemas_for_installation",
        refresh_tool_schemas_for_installation,
    )
    session = FakeSession()

    await service.install_server_version(
        session,
        "io.github.example/weather",
        MCPServerInstallRequest(installTarget="package"),
        workspace_id=WORKSPACE_ID,
    )

    installation = session.added[0]
    assert seen["provider_installation"] is installation
    assert seen["refresh_session"] is session
    assert seen["refresh_installation"] is installation
    assert seen["refresh_server"] is server
    assert seen["refresh_manager"] is manager
    assert seen["refresh_prefer_registry_metadata"] is False


@pytest.mark.asyncio
async def test_install_server_version_seeds_registry_tool_metadata(monkeypatch) -> None:
    server = server_version("1.0.0", is_latest=True)
    seen: dict[str, object] = {}

    async def no_op(*args, **kwargs):
        return None

    async def count_installations_for_workspace(*args, **kwargs):
        return 0

    async def get_server_version(*args, **kwargs):
        return server

    async def get_installation(*args, **kwargs):
        return None

    async def organization_id_for_workspace(*args, **kwargs):
        return ORGANIZATION_ID

    def install_runtime(_server, **kwargs):
        return runtime_install("1.0.0")

    async def seed_tool_schemas_from_registry_metadata(*args, **kwargs):
        seen["seed_session"] = args[0]
        seen["seed_installation"] = kwargs["installation"]
        seen["seed_server"] = kwargs["server"]

    monkeypatch.setattr(service.limits_service, "lock_quota_capacity", no_op)
    monkeypatch.setattr(service.limits_service, "require_limit_available", no_op)
    monkeypatch.setattr(
        service.repository,
        "count_installations_for_workspace",
        count_installations_for_workspace,
    )
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        installation_service,
        "organization_id_for_workspace",
        organization_id_for_workspace,
    )
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    monkeypatch.setattr(
        installation_service,
        "seed_tool_schemas_from_registry_metadata",
        seed_tool_schemas_from_registry_metadata,
    )
    session = FakeSession()

    await service.install_server_version(
        session,
        "io.github.example/weather",
        MCPServerInstallRequest(),
        workspace_id=WORKSPACE_ID,
    )

    installation = session.added[0]
    assert seen["seed_session"] is session
    assert seen["seed_installation"] is installation
    assert seen["seed_server"] is server


@pytest.mark.asyncio
async def test_install_server_version_surfaces_kubernetes_package_validation_error(
    monkeypatch,
) -> None:
    server = server_version("1.0.0", is_latest=True)
    server.packages = [
        {
            "registryType": "oci",
            "identifier": "ghcr.io/example/weather",
            "transport": {"type": "stdio"},
        }
    ]
    removed_paths: list[str] = []

    class FakeRuntimeManager:
        def provider_name(self, installation):
            return config_service.RUNTIME_PROVIDER_KUBERNETES

    async def get_server_version(*args, **kwargs):
        return server

    async def get_installation(*args, **kwargs):
        return None

    async def organization_id_for_workspace(*args, **kwargs):
        return ORGANIZATION_ID

    async def refresh_tool_schemas_for_installation(*args, **kwargs):
        raise RuntimeError("pod crashed: missing executable github-mcp-server")

    def install_runtime(_server, **kwargs):
        return MCPRuntimeInstall(
            install_type="package",
            install_path="/tmp/wardn/mcp/weather/1.0.0",
            runtime_config={"kind": "package"},
            secret_config={},
            status="enabled",
        )

    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        installation_service,
        "organization_id_for_workspace",
        organization_id_for_workspace,
    )
    monkeypatch.setattr(installation_service, "install_server_runtime", install_runtime)
    monkeypatch.setattr(
        config_service,
        "get_runtime_manager",
        lambda: FakeRuntimeManager(),
    )
    monkeypatch.setattr(
        config_service,
        "refresh_tool_schemas_for_installation",
        refresh_tool_schemas_for_installation,
    )
    monkeypatch.setattr(installation_service, "remove_installation_artifacts", removed_paths.append)

    with pytest.raises(
        MCPServerInstallationFailedError,
        match="pod crashed: missing executable github-mcp-server",
    ):
        await service.install_server_version(
            FakeSession(),
            "io.github.example/weather",
            MCPServerInstallRequest(installTarget="package"),
            workspace_id=WORKSPACE_ID,
        )

    assert removed_paths == ["/tmp/wardn/mcp/weather/1.0.0"]


@pytest.mark.asyncio
async def test_uninstall_server_deletes_installation(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        installed_version="1.0.0",
        status="enabled",
        install_type="package",
        runtime_config={"kind": "package"},
    )

    async def get_installation(*args, **kwargs):
        return installation

    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(installation_service, "remove_installation_artifacts", lambda path: None)
    session = FakeSession()

    await service.uninstall_server(session, "io.github.example/weather", workspace_id=WORKSPACE_ID)

    assert session.deleted == [installation]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_uninstall_server_deletes_runtime_resources_before_installation(monkeypatch) -> None:
    installation = MCPServerInstallation(
        id=uuid4(),
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        installed_version="1.0.0",
        status="enabled",
    )
    runtime_session = runtime_session_for_installation(installation)
    stopped: list[tuple[MCPRuntimeSession, bool]] = []

    async def get_installation(*args, **kwargs):
        return installation

    async def list_runtime_sessions_for_installation(*args, **kwargs):
        assert args[1] == installation.id
        return [runtime_session]

    class FakeRuntimeManager:
        def stop_runtime(self, runtime_session_arg, *, delete_resources=False):
            stopped.append((runtime_session_arg, delete_resources))

    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(
        installation_service.runtime_repository,
        "list_runtime_sessions_for_installation",
        list_runtime_sessions_for_installation,
    )
    monkeypatch.setattr(
        installation_service,
        "get_runtime_manager",
        lambda: FakeRuntimeManager(),
    )
    monkeypatch.setattr(installation_service, "remove_installation_artifacts", lambda path: None)
    session = FakeSession()

    await service.uninstall_server(session, "io.github.example/weather", workspace_id=WORKSPACE_ID)

    assert stopped == [(runtime_session, True)]
    assert session.commit_count == 1
    assert session.deleted == [installation]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_uninstall_installation_deletes_selected_config(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="home",
        installed_version="1.0.0",
        status="enabled",
    )
    installation.id = uuid4()

    async def get_installation_by_id(*args, **kwargs):
        return installation

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(installation_service, "remove_installation_artifacts", lambda path: None)
    session = FakeSession()

    await service.uninstall_installation(session, installation.id, workspace_id=WORKSPACE_ID)

    assert session.deleted == [installation]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_uninstall_installation_deletes_runtime_resources_before_config(
    monkeypatch,
) -> None:
    installation = MCPServerInstallation(
        id=uuid4(),
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="home",
        installed_version="1.0.0",
        status="enabled",
    )
    runtime_session = runtime_session_for_installation(installation)
    stopped: list[tuple[MCPRuntimeSession, bool]] = []

    async def get_installation_by_id(*args, **kwargs):
        return installation

    async def list_runtime_sessions_for_installation(*args, **kwargs):
        assert args[1] == installation.id
        return [runtime_session]

    class FakeRuntimeManager:
        def stop_runtime(self, runtime_session_arg, *, delete_resources=False):
            stopped.append((runtime_session_arg, delete_resources))

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(
        installation_service.runtime_repository,
        "list_runtime_sessions_for_installation",
        list_runtime_sessions_for_installation,
    )
    monkeypatch.setattr(
        installation_service,
        "get_runtime_manager",
        lambda: FakeRuntimeManager(),
    )
    monkeypatch.setattr(installation_service, "remove_installation_artifacts", lambda path: None)
    session = FakeSession()

    await service.uninstall_installation(session, installation.id, workspace_id=WORKSPACE_ID)

    assert stopped == [(runtime_session, True)]
    assert session.commit_count == 1
    assert session.deleted == [installation]
    assert session.flushed is True


@pytest.mark.asyncio
async def test_validate_installation_tool_reports_passed_result(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
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
    monkeypatch.setattr(
        installation_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

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
        workspace_id=WORKSPACE_ID,
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
        return SimpleNamespace(source="hub-metadata")

    async def list_active_tool_schemas(*args, **kwargs):
        assert kwargs["installation_id"] == installation.id
        return [cached_tool]

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(
        service.tool_repository,
        "count_active_tool_schemas",
        count_active_tool_schemas,
    )
    monkeypatch.setattr(
        installation_service,
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
    assert response.cache["mode"] == "hub-metadata"
    assert response.tools[0].tool_name == "get_forecast"
    assert response.tools[0].input_schema["required"] == ["location"]
    assert refreshed == {"installation": installation, "server": server}


@pytest.mark.asyncio
async def test_list_installation_tools_refreshes_existing_cache(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    installation.id = uuid4()
    server = server_version("1.0.0", is_latest=True)
    cached_tool = MCPServerToolSchema(
        server_name="io.github.example/weather",
        server_version="1.0.0",
        tool_name="list_servers",
        title="List servers",
        description="List compute servers",
        input_schema={"type": "object"},
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

    async def refresh_tool_schemas_for_installation(*args, **kwargs):
        refreshed["installation"] = kwargs["installation"]
        refreshed["server"] = kwargs["server"]

    async def list_active_tool_schemas(*args, **kwargs):
        assert kwargs["installation_id"] == installation.id
        return [cached_tool]

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(
        installation_service,
        "refresh_tool_schemas_for_installation",
        refresh_tool_schemas_for_installation,
    )
    monkeypatch.setattr(
        service.tool_repository,
        "list_active_tool_schemas",
        list_active_tool_schemas,
    )

    response = await service.list_installation_tools(FakeSession(), installation.id)

    assert response.cache == {"mode": "live-refresh", "refreshed": True}
    assert response.tools[0].tool_name == "list_servers"
    assert refreshed == {"installation": installation, "server": server}


@pytest.mark.asyncio
async def test_upsert_tool_schemas_creates_installation_scoped_tool() -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    installation.id = uuid4()
    server = server_version("1.0.0", is_latest=True)
    session = FakeToolRepositorySession()

    count = await tool_repository.upsert_tool_schemas(
        session,
        installation=installation,
        server=server,
        tools=[
            {
                "name": "get_forecast",
                "title": "Get forecast",
                "description": "Get weather forecast",
                "inputSchema": {"type": "object"},
            }
        ],
    )

    assert count == 1
    assert session.flushed is True
    assert len(session.added) == 1
    cached_tool = session.added[0]
    assert isinstance(cached_tool, MCPServerToolSchema)
    assert cached_tool.workspace_id == WORKSPACE_ID
    assert cached_tool.installation_id == installation.id
    assert cached_tool.tool_name == "get_forecast"


@pytest.mark.asyncio
async def test_validate_installation_tool_reports_upstream_tool_error(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
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
    monkeypatch.setattr(
        installation_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

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
    monkeypatch.setattr(
        installation_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    response = await service.validate_installation_tool(
        FakeSession(),
        installation.id,
        MCPServerInstallationToolValidationRequest(toolName="query-docs"),
    )

    assert response.status == "failed"
    assert response.is_error is True
    assert response.error == "Invalid input: expected string, received undefined"


@pytest.mark.asyncio
async def test_validate_installation_tool_reports_json_text_error(monkeypatch) -> None:
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
                    "text": json.dumps(
                        {
                            "error": "Could not load config file.",
                            "hint": "Upload the required config file.",
                        }
                    ),
                }
            ],
            "isError": False,
        }

    monkeypatch.setattr(service.repository, "get_installation_by_id", get_installation_by_id)
    monkeypatch.setattr(service.repository, "get_server_version", get_server_version)
    monkeypatch.setattr(
        installation_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    response = await service.validate_installation_tool(
        FakeSession(),
        installation.id,
        MCPServerInstallationToolValidationRequest(toolName="status_check"),
    )

    assert response.status == "failed"
    assert response.is_error is True
    assert response.error == "Could not load config file."


@pytest.mark.asyncio
async def test_uninstall_server_rejects_missing_installation(monkeypatch) -> None:
    async def get_installation(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_installation", get_installation)
    monkeypatch.setattr(installation_service, "remove_installation_artifacts", lambda path: None)

    with pytest.raises(MCPServerInstallationNotFoundError):
        await service.uninstall_server(
            FakeSession(),
            "io.github.example/weather",
            workspace_id=WORKSPACE_ID,
        )


@pytest.mark.asyncio
async def test_update_installed_servers_moves_selected_servers_to_latest(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        workspace_id=WORKSPACE_ID,
        installed_version="1.0.0",
        status="enabled",
        install_type="package",
        runtime_config={"kind": "package"},
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
        installation_service,
        "install_server_runtime",
        lambda server, **kwargs: runtime_install("1.1.0"),
    )
    session = FakeSession()

    response = await service.update_installed_servers(
        session,
        MCPServerBulkUpdateRequest(serverNames=["io.github.example/weather"]),
        workspace_id=WORKSPACE_ID,
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
        seen["upsert_installation"] = kwargs["installation"]
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
    assert seen["upsert_installation"] is installation
    assert seen["server"] is server
    assert seen["tools"][0]["name"] == "get_forecast"


@pytest.mark.asyncio
async def test_refresh_tool_schemas_uses_hub_metadata_before_runtime(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    server.server_json["introspection"] = {
        "tools/list": {
            "tools": [
                {
                    "name": "get_forecast",
                    "description": "Get weather forecast",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                }
            ]
        }
    }
    server.server_json["_meta"] = {
        "wardnCatalogSource": {
            "provider": "wardn_hub",
            "baseUrl": "https://hub.wardnai.dev",
        }
    }
    seen = {}

    class FakeRuntimeManager:
        def list_tools(self, runtime_installation):
            raise AssertionError("registry metadata should avoid runtime discovery")

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

    async def upsert_tool_schemas(*args, **kwargs):
        seen["upsert_installation"] = kwargs["installation"]
        seen["server"] = kwargs["server"]
        seen["tools"] = kwargs["tools"]
        return len(kwargs["tools"])

    def queue_tool_inventory_proposal(*args, **kwargs):
        raise AssertionError("registry metadata should not create a Hub proposal")

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
    monkeypatch.setattr(
        tool_service,
        "queue_mcp_hub_tool_inventory_proposal",
        queue_tool_inventory_proposal,
    )
    session = FakeSession()

    result = await tool_service.refresh_tool_schemas(
        session,
        "io.github.example/weather",
        runtime_manager=FakeRuntimeManager(),
    )

    assert result.server_name == "io.github.example/weather"
    assert result.server_version == "1.0.0"
    assert result.tool_count == 1
    assert result.source == "hub-metadata"
    assert session.commit_count == 0
    assert seen["upsert_installation"] is installation
    assert seen["server"] is server
    assert seen["tools"][0]["name"] == "get_forecast"
    assert seen["tools"][0]["inputSchema"]["properties"]["location"]["type"] == "string"


@pytest.mark.asyncio
async def test_refresh_tool_schemas_uses_live_hub_metadata_when_local_metadata_has_no_tools(
    monkeypatch,
) -> None:
    source_id = uuid4()
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    server.organization_id = ORGANIZATION_ID
    server.catalog_source_id = source_id
    server.server_json["introspection"] = {"tools/list": {"tools": []}}
    server.server_json["_meta"] = {
        "wardnCatalogSource": {
            "id": str(source_id),
            "provider": "wardn_hub",
            "baseUrl": "https://hub.wardnai.dev",
        }
    }
    seen = {}

    class FakeRuntimeManager:
        def list_tools(self, runtime_installation):
            raise AssertionError("live Hub metadata should avoid runtime discovery")

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

    async def get_catalog_source(*args, **kwargs):
        seen["catalog_source_id"] = args[1]
        seen["catalog_organization_id"] = kwargs["organization_id"]
        return MCPCatalogSource(
            id=source_id,
            organization_id=ORGANIZATION_ID,
            name="Wardn Hub",
            provider="wardn_hub",
            base_url="https://hub.wardnai.dev",
            sync_mode="latest_only",
            is_enabled=True,
        )

    async def catalog_source_auth_headers(*args, **kwargs):
        seen["auth_source"] = args[2]
        return {"Authorization": "Bearer test-token"}

    def fetch_hub_version_detail_payload(url, *, headers, timeout_seconds):
        seen["hub_url"] = url
        seen["hub_headers"] = headers
        seen["hub_timeout_seconds"] = timeout_seconds
        return {
            "server": {
                "name": "io.github.example/weather",
                "title": "Weather",
                "description": "Weather tools",
            },
            "version": {
                "id": str(uuid4()),
                "version": "1.0.0",
                "serverJson": {
                    "name": "io.github.example/weather",
                    "version": "1.0.0",
                    "introspection": {
                        "tools/list": {
                            "tools": [
                                {
                                    "name": "hub_forecast",
                                    "description": "Hub forecast metadata",
                                    "inputSchema": {"type": "object"},
                                }
                            ]
                        }
                    },
                },
            },
        }

    async def upsert_tool_schemas(*args, **kwargs):
        seen["tools"] = kwargs["tools"]
        return len(kwargs["tools"])

    def queue_tool_inventory_proposal(*args, **kwargs):
        raise AssertionError("Hub metadata should not create a Hub proposal")

    monkeypatch.setattr(
        tool_service.gateway_repository,
        "get_enabled_installation",
        get_enabled_installation,
    )
    monkeypatch.setattr(tool_service.repository, "get_catalog_source", get_catalog_source)
    monkeypatch.setattr(
        tool_service,
        "catalog_source_auth_headers",
        catalog_source_auth_headers,
    )
    monkeypatch.setattr(
        tool_service,
        "fetch_hub_version_detail_payload",
        fetch_hub_version_detail_payload,
    )
    monkeypatch.setattr(
        tool_service.tool_repository,
        "upsert_tool_schemas",
        upsert_tool_schemas,
    )
    monkeypatch.setattr(
        tool_service,
        "queue_mcp_hub_tool_inventory_proposal",
        queue_tool_inventory_proposal,
    )
    session = FakeSession()

    result = await tool_service.refresh_tool_schemas(
        session,
        "io.github.example/weather",
        runtime_manager=FakeRuntimeManager(),
    )

    assert result.tool_count == 1
    assert result.source == "hub-metadata"
    assert session.commit_count == 0
    assert seen["catalog_source_id"] == source_id
    assert seen["catalog_organization_id"] == ORGANIZATION_ID
    assert seen["auth_source"].id == source_id
    assert seen["hub_url"] == (
        "https://hub.wardnai.dev/api/v1/mcp/servers/"
        "io.github.example/weather/versions/1.0.0"
    )
    assert seen["hub_headers"] == {"Authorization": "Bearer test-token"}
    assert seen["hub_timeout_seconds"] == tool_service.WARDN_HUB_TOOL_METADATA_TIMEOUT_SECONDS
    assert seen["tools"][0]["name"] == "hub_forecast"


@pytest.mark.asyncio
async def test_refresh_tool_schemas_ignores_mismatched_live_hub_metadata(
    monkeypatch,
) -> None:
    source_id = uuid4()
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    server.organization_id = ORGANIZATION_ID
    server.catalog_source_id = source_id
    server.server_json["introspection"] = {"tools/list": {"tools": []}}
    server.server_json["_meta"] = {
        "wardnCatalogSource": {
            "id": str(source_id),
            "provider": "wardn_hub",
            "baseUrl": "https://hub.wardnai.dev",
            "sourceUrl": "https://hub.wardnai.dev/api/v1/mcp/servers",
        }
    }
    seen = {}

    class FakeRuntimeManager:
        def list_tools(self, runtime_installation):
            seen["runtime_installation"] = runtime_installation
            return [
                {
                    "name": "live_forecast",
                    "description": "Runtime forecast metadata",
                    "inputSchema": {"type": "object"},
                }
            ]

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

    async def get_catalog_source(*args, **kwargs):
        return None

    def fetch_hub_version_detail_payload(url, *, headers, timeout_seconds):
        return {
            "server": {"name": "io.github.example/weather"},
            "version": {
                "version": "2.0.0",
                "serverJson": {
                    "name": "io.github.example/weather",
                    "version": "2.0.0",
                    "tools": [{"name": "wrong_version_tool", "inputSchema": {"type": "object"}}],
                },
            },
        }

    async def upsert_tool_schemas(*args, **kwargs):
        seen["tools"] = kwargs["tools"]
        return len(kwargs["tools"])

    def queue_tool_inventory_proposal(*args, **kwargs):
        seen["proposal_tools"] = kwargs["tools"]
        return True

    monkeypatch.setattr(
        tool_service.gateway_repository,
        "get_enabled_installation",
        get_enabled_installation,
    )
    monkeypatch.setattr(tool_service.repository, "get_catalog_source", get_catalog_source)
    monkeypatch.setattr(
        tool_service,
        "fetch_hub_version_detail_payload",
        fetch_hub_version_detail_payload,
    )
    monkeypatch.setattr(
        tool_service.tool_repository,
        "upsert_tool_schemas",
        upsert_tool_schemas,
    )
    monkeypatch.setattr(
        tool_service,
        "queue_mcp_hub_tool_inventory_proposal",
        queue_tool_inventory_proposal,
    )
    session = FakeSession()

    result = await tool_service.refresh_tool_schemas(
        session,
        "io.github.example/weather",
        runtime_manager=FakeRuntimeManager(),
    )

    assert result.tool_count == 1
    assert result.source == "live-refresh"
    assert session.commit_count == 1
    assert seen["runtime_installation"] is installation
    assert seen["tools"][0]["name"] == "live_forecast"
    assert seen["proposal_tools"][0]["name"] == "live_forecast"


@pytest.mark.asyncio
async def test_refresh_tool_schemas_falls_back_when_registry_metadata_has_no_tools(
    monkeypatch,
) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/context",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    server.name = "io.github.example/context"
    server.server_json["introspection"] = {"tools/list": {"tools": []}}
    seen = {}

    class FakeRuntimeManager:
        def list_tools(self, runtime_installation):
            seen["runtime_installation"] = runtime_installation
            return [
                {
                    "name": "live_context",
                    "description": "Runtime context metadata",
                    "inputSchema": {"type": "object"},
                }
            ]

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

    async def upsert_tool_schemas(*args, **kwargs):
        seen["tools"] = kwargs["tools"]
        seen["installation_for_upsert"] = kwargs["installation"]
        return len(kwargs["tools"])

    def queue_tool_inventory_proposal(*args, **kwargs):
        seen["proposal_tools"] = kwargs["tools"]
        return True

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
    monkeypatch.setattr(
        tool_service,
        "queue_mcp_hub_tool_inventory_proposal",
        queue_tool_inventory_proposal,
    )
    session = FakeSession()

    result = await tool_service.refresh_tool_schemas(
        session,
        "io.github.example/context",
        runtime_manager=FakeRuntimeManager(),
    )

    assert result.server_name == "io.github.example/context"
    assert result.server_version == "1.0.0"
    assert result.tool_count == 1
    assert result.source == "live-refresh"
    assert session.commit_count == 1
    assert seen["runtime_installation"] is installation
    assert seen["installation_for_upsert"] is installation
    assert seen["tools"][0]["name"] == "live_context"
    assert seen["proposal_tools"][0]["name"] == "live_context"


@pytest.mark.asyncio
async def test_refresh_tool_schemas_ignores_mismatched_registry_metadata(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    server.server_json["version"] = "1.1.0"
    server.server_json["introspection"] = {
        "tools/list": {
            "tools": [
                {
                    "name": "registry_forecast",
                    "description": "Mismatched published metadata",
                    "inputSchema": {"type": "object"},
                }
            ]
        }
    }
    seen = {}

    class FakeRuntimeManager:
        def list_tools(self, runtime_installation):
            seen["runtime_installation"] = runtime_installation
            return [
                {
                    "name": "live_forecast",
                    "description": "Runtime forecast metadata",
                    "inputSchema": {"type": "object"},
                }
            ]

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

    async def upsert_tool_schemas(*args, **kwargs):
        seen["tools"] = kwargs["tools"]
        return len(kwargs["tools"])

    def queue_tool_inventory_proposal(*args, **kwargs):
        seen["proposal_tools"] = kwargs["tools"]
        return True

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
    monkeypatch.setattr(
        tool_service,
        "queue_mcp_hub_tool_inventory_proposal",
        queue_tool_inventory_proposal,
    )
    session = FakeSession()

    result = await tool_service.refresh_tool_schemas(
        session,
        "io.github.example/weather",
        runtime_manager=FakeRuntimeManager(),
    )

    assert result.tool_count == 1
    assert result.source == "live-refresh"
    assert session.commit_count == 1
    assert seen["runtime_installation"] is installation
    assert seen["tools"][0]["name"] == "live_forecast"
    assert seen["proposal_tools"][0]["name"] == "live_forecast"


@pytest.mark.asyncio
async def test_refresh_tool_schemas_can_force_runtime_discovery(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    server.server_json["tools"] = [
        {
            "name": "registry_forecast",
            "description": "Published forecast metadata",
            "inputSchema": {"type": "object"},
        }
    ]
    seen = {}

    class FakeRuntimeManager:
        def list_tools(self, runtime_installation):
            seen["runtime_installation"] = runtime_installation
            return [
                {
                    "name": "live_forecast",
                    "description": "Runtime forecast metadata",
                    "inputSchema": {"type": "object"},
                }
            ]

    async def upsert_tool_schemas(*args, **kwargs):
        seen["tools"] = kwargs["tools"]
        return len(kwargs["tools"])

    def queue_tool_inventory_proposal(*args, **kwargs):
        seen["proposal_tools"] = kwargs["tools"]
        return True

    monkeypatch.setattr(
        tool_service.tool_repository,
        "upsert_tool_schemas",
        upsert_tool_schemas,
    )
    monkeypatch.setattr(
        tool_service,
        "queue_mcp_hub_tool_inventory_proposal",
        queue_tool_inventory_proposal,
    )
    session = FakeSession()

    result = await tool_service.refresh_tool_schemas_for_installation(
        session,
        installation=installation,
        server=server,
        runtime_manager=FakeRuntimeManager(),
        prefer_registry_metadata=False,
    )

    assert result.tool_count == 1
    assert session.commit_count == 1
    assert seen["runtime_installation"] is installation
    assert seen["tools"][0]["name"] == "live_forecast"
    assert seen["proposal_tools"][0]["name"] == "live_forecast"


@pytest.mark.asyncio
async def test_refresh_tool_schemas_queues_hub_tool_inventory_proposal(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    seen = {}

    class FakeRuntimeManager:
        def list_tools(self, runtime_installation):
            return [
                {
                    "name": "get_forecast",
                    "description": "Get weather forecast",
                    "inputSchema": {"type": "object"},
                }
            ]

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

    async def upsert_tool_schemas(*args, **kwargs):
        return len(kwargs["tools"])

    def queue_tool_inventory_proposal(*args, **kwargs):
        seen["session"] = args[0]
        seen["installation"] = kwargs["installation"]
        seen["server"] = kwargs["server"]
        seen["tools"] = kwargs["tools"]
        return True

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
    monkeypatch.setattr(
        tool_service,
        "queue_mcp_hub_tool_inventory_proposal",
        queue_tool_inventory_proposal,
    )
    session = FakeSession()

    result = await tool_service.refresh_tool_schemas(
        session,
        "io.github.example/weather",
        runtime_manager=FakeRuntimeManager(),
    )

    assert result.tool_count == 1
    assert seen["session"] is session
    assert seen["installation"] is installation
    assert seen["server"] is server
    assert seen["tools"][0]["name"] == "get_forecast"


@pytest.mark.asyncio
async def test_refresh_tool_schemas_falls_back_to_tracked_discovery(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    seen = {}

    class SessionRequiredRuntimeManager:
        def list_tools(self, runtime_installation):
            seen["stateless_installation"] = runtime_installation
            raise NotImplementedError("runtime session required")

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

    async def list_tools_with_tracking(*args, **kwargs):
        seen["tracked_args"] = args
        seen["tracked_manager"] = kwargs["manager"]
        return [
            {
                "name": "get_forecast",
                "description": "Get weather forecast",
                "inputSchema": {"type": "object"},
            }
        ]

    async def upsert_tool_schemas(*args, **kwargs):
        seen["tools"] = kwargs["tools"]
        return len(kwargs["tools"])

    monkeypatch.setattr(
        tool_service.gateway_repository,
        "get_enabled_installation",
        get_enabled_installation,
    )
    monkeypatch.setattr(
        tool_service,
        "list_tools_with_tracking",
        list_tools_with_tracking,
    )
    monkeypatch.setattr(
        tool_service.tool_repository,
        "upsert_tool_schemas",
        upsert_tool_schemas,
    )

    manager = SessionRequiredRuntimeManager()
    result = await tool_service.refresh_tool_schemas(
        FakeSession(),
        "io.github.example/weather",
        runtime_manager=manager,
    )

    assert result.tool_count == 1
    assert seen["stateless_installation"] is installation
    assert seen["tracked_args"][1] is installation
    assert seen["tracked_args"][2] is server
    assert seen["tracked_manager"] is manager
    assert seen["tools"][0]["name"] == "get_forecast"


@pytest.mark.asyncio
async def test_refresh_tool_schemas_treats_missing_tools_list_as_empty(monkeypatch) -> None:
    installation = MCPServerInstallation(
        server_name="io.github.example/context",
        installed_version="1.0.0",
        status="enabled",
    )
    server = server_version("1.0.0")
    server.name = "io.github.example/context"
    seen = {}

    class MissingToolsListRuntimeManager:
        def list_tools(self, runtime_installation):
            seen["installation"] = runtime_installation
            raise MCPGatewayUnsupportedMethodError(
                "tools/list",
                {"code": -32601, "message": "Method not found"},
            )

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

    async def upsert_tool_schemas(*args, **kwargs):
        seen["tools"] = kwargs["tools"]
        seen["installation_for_upsert"] = kwargs["installation"]
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
        "io.github.example/context",
        runtime_manager=MissingToolsListRuntimeManager(),
    )

    assert result.server_name == "io.github.example/context"
    assert result.server_version == "1.0.0"
    assert result.tool_count == 0
    assert seen["installation"] is installation
    assert seen["installation_for_upsert"] is installation
    assert seen["tools"] == []
