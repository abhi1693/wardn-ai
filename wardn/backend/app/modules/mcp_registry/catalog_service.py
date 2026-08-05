"""MCP catalog source and server-version application services."""

import asyncio
import gc
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.pagination import InvalidCursorError
from app.db.domain_types import MCPServerStatus as MCPServerStatusEnum
from app.db.errors import is_constraint_violation
from app.modules.limits import service as limits_service
from app.modules.mcp_registry import repository
from app.modules.mcp_registry.exceptions import (
    DuplicateMCPCatalogSourceError,
    DuplicateMCPServerVersionError,
    InvalidRegistryCursorError,
    MCPCatalogSourceNotFoundError,
    MCPServerNotFoundError,
    MCPServerVersionInUseError,
)
from app.modules.mcp_registry.models import (
    MCPCatalogSource,
    MCPServerVersion,
)
from app.modules.mcp_registry.schemas import (
    MCPCatalogSourceCreate,
    MCPCatalogSourceListResponse,
    MCPCatalogSourceRead,
    MCPCatalogSourceSyncResponse,
    MCPCatalogSourceUpdate,
    MCPPulseServerVersionMetadata,
    MCPRegistryListMetadata,
    MCPRegistryOfficialMetadata,
    MCPRegistryResponseMeta,
    MCPRegistryServerListResponse,
    MCPRegistryServerResponse,
    MCPServerCreate,
    MCPServerDocument,
)
from app.modules.mcp_registry.schemas import (
    MCPServerStatus as MCPServerStatusValue,
)
from app.modules.mcp_registry.scope_service import catalog_organization_id
from app.modules.secrets.managed import (
    activate_managed_secret,
    delete_managed_secret_handles,
    owner_managed_secrets,
    queue_managed_secret_cleanup,
)
from app.modules.secrets.schemas import SecretHandleCreate
from app.modules.secrets.service import create_secret_handle, resolve_secret, write_secret_values
from app.modules.users.models import User

OFFICIAL_REGISTRY_META_KEY = "io.modelcontextprotocol.registry/official"
PULSE_SERVER_VERSION_META_KEY = "com.pulsemcp/server-version"
VERSION_PREFIX_PATTERN = re.compile(r"^\s*v?(\d+(?:[._-]\d+)*)", re.IGNORECASE)
CATALOG_SYNC_PAGE_SIZE = 100
WARDN_HUB_CATALOG_PATH = "/api/v1/mcp/catalog"
WARDN_HUB_SERVERS_PATH = "/api/v1/mcp/servers"
CATALOG_SOURCE_TOKEN_KEY = "api_token"
CATALOG_SOURCE_META_KEY = "wardnCatalogSource"
CATALOG_SYNC_BATCH_SIZE = 100
NO_CATALOG_SYNC_BATCH = object()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogSourceTokenHandle:
    handle_id: uuid.UUID | None = None
    managed_secret_id: uuid.UUID | None = None


def official_metadata(payload: MCPServerCreate) -> MCPRegistryOfficialMetadata | None:
    if not payload.meta:
        return None

    raw_metadata = payload.meta.get(OFFICIAL_REGISTRY_META_KEY)
    if not isinstance(raw_metadata, dict):
        return None

    return MCPRegistryOfficialMetadata.model_validate(raw_metadata)


def pulse_metadata(payload: MCPServerCreate) -> MCPRegistryOfficialMetadata | None:
    if not payload.meta:
        return None

    raw_metadata = payload.meta.get(PULSE_SERVER_VERSION_META_KEY)
    if not isinstance(raw_metadata, dict):
        return None

    metadata = MCPPulseServerVersionMetadata.model_validate(raw_metadata)
    published_at = metadata.published_at or metadata.updated_at
    return MCPRegistryOfficialMetadata(
        status=metadata.status,
        status_changed_at=metadata.status_changed_at or metadata.updated_at,
        status_message=metadata.status_message,
        published_at=published_at,
        updated_at=metadata.updated_at,
        is_latest=metadata.is_latest,
    )


def registry_metadata(payload: MCPServerCreate) -> MCPRegistryOfficialMetadata | None:
    return official_metadata(payload) or pulse_metadata(payload)


def comparable_version_parts(version: str) -> tuple[int, ...] | None:
    match = VERSION_PREFIX_PATTERN.match(version)
    if match is None:
        return None
    return tuple(int(part) for part in re.findall(r"\d+", match.group(1)))


def compare_version_numbers(left: str, right: str) -> int | None:
    left_parts = comparable_version_parts(left)
    right_parts = comparable_version_parts(right)
    if left_parts is None or right_parts is None:
        return None

    length = max(len(left_parts), len(right_parts))
    normalized_left = left_parts + (0,) * (length - len(left_parts))
    normalized_right = right_parts + (0,) * (length - len(right_parts))
    if normalized_left < normalized_right:
        return -1
    if normalized_left > normalized_right:
        return 1
    return 0


def server_update_available(installed_version: str, latest_version: str) -> bool:
    comparison = compare_version_numbers(installed_version, latest_version)
    if comparison is not None:
        return comparison < 0

    return installed_version.strip().casefold() != latest_version.strip().casefold()


def server_values(
    payload: MCPServerCreate,
    *,
    is_latest: bool,
    catalog_source_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    metadata = registry_metadata(payload)
    server_json = payload.model_dump(by_alias=True, exclude_none=True)
    values: dict[str, Any] = {
        "name": payload.name,
        "catalog_source_id": catalog_source_id,
        "title": payload.title,
        "description": payload.description,
        "version": payload.version,
        "website_url": payload.website_url,
        "repository": payload.repository,
        "packages": payload.packages,
        "remotes": payload.remotes,
        "icons": payload.icons,
        "server_json": server_json,
        "status": metadata.status if metadata else "active",
        "status_message": metadata.status_message if metadata and metadata.status_message else "",
        "is_latest": is_latest,
    }
    if metadata:
        values["published_at"] = metadata.published_at
        values["status_changed_at"] = metadata.status_changed_at
    return values


def catalog_source_metadata(source: MCPCatalogSource, *, source_url: str) -> dict[str, str]:
    return {
        "id": str(source.id),
        "name": source.name,
        "provider": source.provider,
        "baseUrl": source.base_url,
        "sourceUrl": source_url,
    }


def catalog_source_payload(
    payload: MCPServerCreate,
    *,
    source: MCPCatalogSource,
    source_url: str,
) -> MCPServerCreate:
    document = payload.model_dump(by_alias=True, exclude_none=True)
    metadata = dict(document.get("_meta") or {})
    metadata[CATALOG_SOURCE_META_KEY] = catalog_source_metadata(source, source_url=source_url)
    document["_meta"] = metadata
    return MCPServerCreate.model_validate(document)


def server_response(server: MCPServerVersion) -> MCPRegistryServerResponse:
    status_message = server.status_message or None
    return MCPRegistryServerResponse(
        server=MCPServerDocument.model_validate(server.server_json),
        _meta=MCPRegistryResponseMeta.model_validate(
            {
                OFFICIAL_REGISTRY_META_KEY: MCPRegistryOfficialMetadata(
                    status=cast(MCPServerStatusValue, str(server.status)),
                    status_changed_at=server.status_changed_at,
                    status_message=status_message,
                    published_at=server.published_at,
                    updated_at=server.updated_at,
                    is_latest=server.is_latest,
                )
            }
        ),
    )


def catalog_source_response(source: MCPCatalogSource) -> MCPCatalogSourceRead:
    return MCPCatalogSourceRead(
        id=source.id,
        organization_id=source.organization_id,
        name=source.name,
        provider=source.provider,
        base_url=source.base_url,
        tenant_id=source.tenant_id,
        sync_mode=source.sync_mode,
        last_success_at=source.last_success_at,
        last_synced_updated_since=source.last_synced_updated_since,
        last_error=source.last_error,
        is_enabled=source.is_enabled,
        has_auth_token=source.auth_secret_handle_id is not None,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


async def list_catalog_sources(
    session,
    organization_id: uuid.UUID,
) -> MCPCatalogSourceListResponse:
    sources = await repository.list_catalog_sources(session, organization_id)
    return MCPCatalogSourceListResponse(
        sources=[catalog_source_response(source) for source in sources]
    )


async def create_catalog_source(
    session,
    user: User,
    organization_id: uuid.UUID,
    payload: MCPCatalogSourceCreate,
) -> MCPCatalogSourceRead:
    base_url = catalog_source_stored_base_url(payload.provider, payload.base_url)
    if await repository.get_catalog_source_by_name(session, organization_id, payload.name):
        raise DuplicateMCPCatalogSourceError("catalog source name already exists")
    if await repository.get_catalog_source_by_url(session, organization_id, base_url):
        raise DuplicateMCPCatalogSourceError("catalog source URL already exists")
    await limits_service.lock_quota_capacity(
        session,
        [
            limits_service.quota_scope(
                limits_service.MCP_CATALOG_SOURCES_PER_ORGANIZATION,
                organization_id,
            )
        ],
    )
    source_count = await repository.count_catalog_sources_for_organization(
        session,
        organization_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.MCP_CATALOG_SOURCES_PER_ORGANIZATION,
        scope_chain=[
            ("organization", organization_id),
        ],
        current_count=source_count,
    )
    source_id = uuid.uuid4()
    token_result = await create_catalog_source_token_handle(
        session,
        user,
        organization_id,
        name=payload.name,
        api_token=payload.api_token,
        secret_store_id=payload.api_token_secret_store_id,
        required=payload.provider == "wardn_hub",
        owner_id=source_id,
    )
    auth_secret_handle_id = token_result.handle_id
    managed_secret_id = token_result.managed_secret_id

    source = MCPCatalogSource(
        id=source_id,
        organization_id=organization_id,
        name=payload.name,
        provider=payload.provider,
        base_url=base_url,
        tenant_id=payload.tenant_id,
        sync_mode=payload.sync_mode,
        auth_secret_handle_id=auth_secret_handle_id,
        is_enabled=payload.is_enabled,
        last_error="",
    )
    session.add(source)
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(
            exc,
            {
                "uq_mcp_catalog_sources_org_name",
                "uq_mcp_catalog_sources_org_base_url",
            },
        ):
            raise DuplicateMCPCatalogSourceError("catalog source already exists") from exc
        raise
    await session.refresh(source)
    await activate_managed_secret(session, managed_secret_id)
    logger.info(
        "Created MCP catalog source.",
        extra={
            "organization_id": str(organization_id),
            "mcp_catalog_source_id": str(source.id),
            "mcp_catalog_source_name": source.name,
            "mcp_catalog_provider": source.provider,
            "mcp_catalog_sync_mode": source.sync_mode,
            "mcp_catalog_enabled": source.is_enabled,
            "mcp_catalog_auth_secret_handle_id": (
                str(source.auth_secret_handle_id) if source.auth_secret_handle_id else None
            ),
            "user_id": str(user.id),
        },
    )
    return catalog_source_response(source)


async def get_catalog_source(
    session,
    organization_id: uuid.UUID,
    source_id: uuid.UUID,
) -> MCPCatalogSourceRead:
    source = await repository.get_catalog_source(
        session,
        source_id,
        organization_id=organization_id,
    )
    if source is None:
        raise MCPCatalogSourceNotFoundError("catalog source not found")
    return catalog_source_response(source)


async def update_catalog_source(
    session,
    user: User,
    organization_id: uuid.UUID,
    source_id: uuid.UUID,
    payload: MCPCatalogSourceUpdate,
) -> MCPCatalogSourceRead:
    source = await repository.get_catalog_source(
        session,
        source_id,
        organization_id=organization_id,
    )
    if source is None:
        raise MCPCatalogSourceNotFoundError("catalog source not found")

    values = payload.model_dump(exclude_unset=True, by_alias=False)
    next_provider = values.get("provider", source.provider)
    if "base_url" in values:
        values["base_url"] = catalog_source_stored_base_url(
            next_provider,
            values["base_url"],
        )
    next_name = values.get("name")
    if next_name and next_name != source.name:
        existing = await repository.get_catalog_source_by_name(
            session,
            organization_id,
            next_name,
        )
        if existing is not None and existing.id != source.id:
            raise DuplicateMCPCatalogSourceError("catalog source name already exists")
    next_url = values.get("base_url")
    if next_url and next_url != source.base_url:
        existing = await repository.get_catalog_source_by_url(
            session,
            organization_id,
            next_url,
        )
        if existing is not None and existing.id != source.id:
            raise DuplicateMCPCatalogSourceError("catalog source URL already exists")
    existing_managed_secrets = await owner_managed_secrets(
        session,
        owner_type="mcp_catalog_source",
        owner_id=source.id,
    )
    token_result = await create_catalog_source_token_handle(
        session,
        user,
        organization_id,
        name=values.get("name", source.name),
        api_token=payload.api_token,
        secret_store_id=payload.api_token_secret_store_id,
        required=next_provider == "wardn_hub" and source.auth_secret_handle_id is None,
        owner_id=source.id,
    )
    token_handle_id = token_result.handle_id
    managed_secret_id = token_result.managed_secret_id

    for key, value in values.items():
        if key in {"api_token", "api_token_secret_store_id"}:
            continue
        setattr(source, key, value)
    if token_handle_id is not None:
        source.auth_secret_handle_id = token_handle_id

    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(
            exc,
            {
                "uq_mcp_catalog_sources_org_name",
                "uq_mcp_catalog_sources_org_base_url",
            },
        ):
            raise DuplicateMCPCatalogSourceError("catalog source already exists") from exc
        raise
    await session.refresh(source)
    if managed_secret_id is not None:
        replaced_managed_secret_ids = {
            managed_secret.id
            for managed_secret in existing_managed_secrets
            if managed_secret.id != managed_secret_id
        }
        await delete_managed_secret_handles(session, replaced_managed_secret_ids)
        await queue_managed_secret_cleanup(session, replaced_managed_secret_ids)
        await activate_managed_secret(session, managed_secret_id)
    logger.info(
        "Updated MCP catalog source.",
        extra={
            "organization_id": str(organization_id),
            "mcp_catalog_source_id": str(source.id),
            "mcp_catalog_source_name": source.name,
            "mcp_catalog_provider": source.provider,
            "mcp_catalog_sync_mode": source.sync_mode,
            "mcp_catalog_enabled": source.is_enabled,
            "mcp_catalog_updated_fields": sorted(values.keys()),
            "mcp_catalog_auth_secret_handle_id": (
                str(source.auth_secret_handle_id) if source.auth_secret_handle_id else None
            ),
            "mcp_catalog_replaced_managed_secret_count": (
                len(replaced_managed_secret_ids) if managed_secret_id is not None else 0
            ),
            "user_id": str(user.id),
        },
    )
    return catalog_source_response(source)


async def delete_catalog_source(
    session,
    organization_id: uuid.UUID,
    source_id: uuid.UUID,
) -> None:
    source = await repository.get_catalog_source(
        session,
        source_id,
        organization_id=organization_id,
    )
    if source is None:
        raise MCPCatalogSourceNotFoundError("catalog source not found")
    managed_secrets = await owner_managed_secrets(
        session,
        owner_type="mcp_catalog_source",
        owner_id=source.id,
    )
    managed_secret_ids = {managed_secret.id for managed_secret in managed_secrets}
    servers = await repository.list_server_versions_for_catalog_source(
        session,
        organization_id=organization_id,
        source_id=source_id,
    )
    if not servers:
        sources = await repository.list_catalog_sources(session, organization_id)
        if len(sources) == 1 and sources[0].id == source.id:
            servers = await repository.list_legacy_catalog_server_versions(
                session,
                organization_id=organization_id,
            )
    server_names = {server.name for server in servers}
    for server in servers:
        server.status = MCPServerStatusEnum.DELETED
        server.status_message = f"Deleted with catalog source {source.name}."
        server.is_latest = False

    await session.flush()
    for server_name in server_names:
        replacement = await repository.get_latest_visible_version(
            session,
            server_name,
            organization_id=organization_id,
        )
        if replacement:
            replacement.is_latest = True
    await session.delete(source)
    await session.flush()
    await delete_managed_secret_handles(session, managed_secret_ids)
    await queue_managed_secret_cleanup(session, managed_secret_ids)
    logger.info(
        "Deleted MCP catalog source.",
        extra={
            "organization_id": str(organization_id),
            "mcp_catalog_source_id": str(source.id),
            "mcp_catalog_source_name": source.name,
            "mcp_catalog_provider": source.provider,
            "mcp_catalog_soft_deleted_version_count": len(servers),
            "mcp_catalog_affected_server_count": len(server_names),
            "managed_secret_count": len(managed_secret_ids),
        },
    )


def registry_source_type(provider: str) -> str:
    if provider == "pulsemcp":
        return "pulsemcp"
    if provider == "official":
        return "official"
    return "custom"


def catalog_source_urls(source: MCPCatalogSource) -> list[str]:
    if source.provider != "wardn_hub":
        return [source.base_url.rstrip("/")]
    return [wardn_hub_catalog_url(source.base_url)]


def catalog_source_stored_base_url(provider: str, base_url: str) -> str:
    base_url = base_url.strip().rstrip("/")
    if provider != "wardn_hub":
        return base_url
    split_url = urlsplit(base_url)
    return f"{split_url.scheme}://{split_url.netloc}"


def wardn_hub_catalog_url(base_url: str) -> str:
    split_url = urlsplit(base_url.strip().rstrip("/"))
    return f"{split_url.scheme}://{split_url.netloc}{WARDN_HUB_CATALOG_PATH}"


def wardn_hub_servers_url(base_url: str) -> str:
    split_url = urlsplit(base_url.strip().rstrip("/"))
    return f"{split_url.scheme}://{split_url.netloc}{WARDN_HUB_SERVERS_PATH}"


def catalog_source_updated_since(source: MCPCatalogSource) -> str | None:
    if source.provider != "wardn_hub" or source.sync_mode != "latest_only":
        return None
    if source.last_synced_updated_since is None:
        return None
    value = source.last_synced_updated_since
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def catalog_source_token_path(
    *,
    organization_id: uuid.UUID,
    name: str,
    run_id: str,
) -> str:
    name_part = "-".join(
        part
        for part in "".join(
            character.lower() if character.isalnum() else "-"
            for character in name.strip()
        ).split("-")
        if part
    ) or "catalog-source"
    return f"wardn/orgs/{organization_id}/catalog/{name_part}-{run_id}"


def catalog_source_token_display_name(name: str, run_id: str) -> str:
    base = " ".join(name.strip().split()) or "Catalog source"
    suffix = f" API token {run_id}"
    value = f"{base}{suffix}"
    if len(value) <= 100:
        return value
    return f"{base[: 100 - len(suffix)].rstrip()}{suffix}"


async def create_catalog_source_token_handle(
    session,
    user: User,
    organization_id: uuid.UUID,
    *,
    name: str,
    api_token,
    secret_store_id: uuid.UUID | None,
    required: bool,
    owner_id: uuid.UUID,
) -> CatalogSourceTokenHandle:
    token = api_token.get_secret_value().strip() if api_token is not None else ""
    if not token:
        if required:
            raise ValueError("Wardn Hub catalog sources require an API token")
        return CatalogSourceTokenHandle()
    if secret_store_id is None:
        raise ValueError("API token secret backend is required")

    run_id = uuid.uuid4().hex[:8]
    external_ref = catalog_source_token_path(
        organization_id=organization_id,
        name=name,
        run_id=run_id,
    )
    write_result = await write_secret_values(
        session,
        user,
        organization_id,
        secret_store_id,
        workspace_id=None,
        external_ref=external_ref,
        values={CATALOG_SOURCE_TOKEN_KEY: token},
        purpose="catalog_source",
        owner_type="mcp_catalog_source",
        owner_id=owner_id,
    )
    managed_secret_id = getattr(write_result, "managed_secret_id", None)
    handle = await create_secret_handle(
        session,
        user,
        organization_id,
        SecretHandleCreate(
            store_id=secret_store_id,
            workspace_id=None,
            purpose="catalog_source",
            display_name=catalog_source_token_display_name(name, run_id),
            external_ref=external_ref,
            key_name=CATALOG_SOURCE_TOKEN_KEY,
            metadata={"provider": "mcp_catalog", "catalogSourceName": name},
        ),
        managed_secret_id=managed_secret_id,
    )
    logger.info(
        "Created MCP catalog source token handle.",
        extra={
            "organization_id": str(organization_id),
            "mcp_catalog_source_id": str(owner_id),
            "secret_store_id": str(secret_store_id),
            "secret_handle_id": str(handle.id),
            "managed_secret_id": str(managed_secret_id) if managed_secret_id else None,
        },
    )
    return CatalogSourceTokenHandle(
        handle_id=handle.id,
        managed_secret_id=managed_secret_id,
    )


async def catalog_source_auth_headers(
    session,
    organization_id: uuid.UUID,
    source: MCPCatalogSource,
) -> dict[str, str]:
    if source.auth_secret_handle_id is None:
        if source.provider == "wardn_hub":
            raise ValueError("Wardn Hub catalog source API token is not configured")
        return {}
    secret = await resolve_secret(session, organization_id, source.auth_secret_handle_id)
    token = secret.value.strip()
    if not token:
        raise ValueError("catalog source API token is empty")
    return {
        "Authorization": f"Bearer {token}",
        "X-API-Key": token,
    }


def next_catalog_sync_batch(iterator):
    return next(iterator, NO_CATALOG_SYNC_BATCH)


def release_catalog_sync_batch_memory(*batches: list) -> None:
    for batch in batches:
        batch.clear()
    gc.collect()


async def sync_catalog_source(
    session,
    organization_id: uuid.UUID,
    source_id: uuid.UUID,
) -> MCPCatalogSourceSyncResponse:
    source = await repository.get_catalog_source(
        session,
        source_id,
        organization_id=organization_id,
    )
    if source is None:
        raise MCPCatalogSourceNotFoundError("catalog source not found")
    if not source.is_enabled:
        raise ValueError("catalog source is disabled")

    source_id_value = source.id
    source_name = source.name
    source_provider = source.provider
    source_sync_mode = source.sync_mode
    source_base_url = source.base_url
    source_tenant_id = source.tenant_id

    from app.modules.mcp_registry.commands import (
        iter_supported_server_batches_from_registry_url,
        registry_headers,
    )

    source_type = registry_source_type(source_provider)
    version = "latest" if source_sync_mode == "latest_only" else None
    updated_since = catalog_source_updated_since(source)
    is_wardn_hub_source = source_provider == "wardn_hub"
    source_urls = (
        [wardn_hub_servers_url(source_base_url)]
        if is_wardn_hub_source
        else catalog_source_urls(source)
    )
    pagination = "cursor"
    sync_started_at = datetime.now(UTC)
    logger.info(
        "Starting MCP catalog source sync.",
        extra={
            "organization_id": str(organization_id),
            "mcp_catalog_source_id": str(source_id_value),
            "mcp_catalog_source_name": source_name,
            "mcp_catalog_provider": source_provider,
            "mcp_catalog_sync_mode": source_sync_mode,
            "mcp_catalog_updated_since": updated_since,
            "mcp_catalog_pagination": pagination,
            "mcp_catalog_source_url_count": len(source_urls),
        },
    )

    try:
        headers = registry_headers(source_type, api_key=None, tenant_id=source_tenant_id or None)
        headers.update(await catalog_source_auth_headers(session, organization_id, source))
        last_error: Exception | None = None
        synced_count = 0
        loaded_source = False
        for source_url in source_urls:
            source_batch_count = 0
            batch_index = 0
            try:
                logger.info(
                    "Fetching MCP catalog source URL.",
                    extra={
                        "organization_id": str(organization_id),
                        "mcp_catalog_source_id": str(source_id_value),
                        "mcp_catalog_source_name": source_name,
                        "mcp_catalog_provider": source_provider,
                        "mcp_catalog_source_url": source_url,
                        "mcp_catalog_updated_since": updated_since,
                        "mcp_catalog_batch_size": CATALOG_SYNC_BATCH_SIZE,
                    },
                )
                batch_iterator = iter_supported_server_batches_from_registry_url(
                    source_url,
                    limit=CATALOG_SYNC_BATCH_SIZE,
                    max_pages=None,
                    headers=headers,
                    updated_since=updated_since,
                    version=version,
                    pagination=pagination,
                    wardn_hub_version_details=is_wardn_hub_source,
                    wardn_hub_version_detail_concurrency=(
                        get_settings().mcp_catalog_sync_detail_concurrency
                    ),
                )
                while True:
                    batch = await asyncio.to_thread(next_catalog_sync_batch, batch_iterator)
                    if batch is NO_CATALOG_SYNC_BATCH:
                        break
                    batch_index += 1
                    source_batch_count += len(batch)
                    sourced_servers: list[MCPServerCreate] = []
                    try:
                        sourced_servers = [
                            catalog_source_payload(server, source=source, source_url=source_url)
                            for server in batch
                        ]
                        synced_batch_count = await sync_supported_servers(
                            session,
                            sourced_servers,
                            organization_id=organization_id,
                            catalog_source_id=source_id_value,
                        )
                        synced_count += synced_batch_count
                        await session.commit()
                        logger.info(
                            "Synced MCP catalog source batch.",
                            extra={
                                "organization_id": str(organization_id),
                                "mcp_catalog_source_id": str(source_id_value),
                                "mcp_catalog_source_name": source_name,
                                "mcp_catalog_provider": source_provider,
                                "mcp_catalog_source_url": source_url,
                                "mcp_catalog_batch_index": batch_index,
                                "mcp_catalog_batch_size": len(batch),
                                "mcp_catalog_batch_synced_count": synced_batch_count,
                                "mcp_catalog_synced_count": synced_count,
                            },
                        )
                    finally:
                        release_catalog_sync_batch_memory(batch, sourced_servers)
                loaded_source = True
                logger.info(
                    "Finished MCP catalog source URL.",
                    extra={
                        "organization_id": str(organization_id),
                        "mcp_catalog_source_id": str(source_id_value),
                        "mcp_catalog_source_name": source_name,
                        "mcp_catalog_provider": source_provider,
                        "mcp_catalog_source_url": source_url,
                        "mcp_catalog_source_count": source_batch_count,
                        "mcp_catalog_batch_count": batch_index,
                    },
                )
                break
            except Exception as exc:
                last_error = exc
                await session.rollback()
                logger.warning(
                    "MCP catalog source URL failed.",
                    extra={
                        "organization_id": str(organization_id),
                        "mcp_catalog_source_id": str(source_id_value),
                        "mcp_catalog_source_name": source_name,
                        "mcp_catalog_provider": source_provider,
                        "mcp_catalog_source_url": source_url,
                        "mcp_catalog_source_count": source_batch_count,
                        "mcp_catalog_batch_count": batch_index,
                        "error_type": exc.__class__.__name__,
                    },
                )
                if source_batch_count > 0:
                    raise
        if not loaded_source:
            raise ValueError(
                f"no supported catalog API found at {source_base_url}: {last_error}"
            )
    except Exception as exc:
        await session.rollback()
        logger.warning(
            "MCP catalog source sync failed.",
            extra={
                "organization_id": str(organization_id),
                "mcp_catalog_source_id": str(source_id),
                "mcp_catalog_source_name": source_name,
                "mcp_catalog_provider": source_provider,
                "error_type": exc.__class__.__name__,
            },
        )
        source = await repository.get_catalog_source(
            session,
            source_id,
            organization_id=organization_id,
        )
        if source is None:
            raise MCPCatalogSourceNotFoundError("catalog source not found") from exc
        source.last_error = str(exc)
        await session.flush()
        raise ValueError(f"catalog sync failed: {exc}") from exc

    now = datetime.now(UTC)
    source.last_success_at = now
    source.last_synced_updated_since = sync_started_at
    source.last_error = ""
    await session.flush()
    await session.refresh(source)
    logger.info(
        "Completed MCP catalog source sync.",
        extra={
            "organization_id": str(organization_id),
            "mcp_catalog_source_id": str(source.id),
            "mcp_catalog_source_name": source.name,
            "mcp_catalog_provider": source.provider,
            "mcp_catalog_sync_mode": source.sync_mode,
            "mcp_catalog_synced_count": synced_count,
            "mcp_catalog_updated_since": updated_since,
        },
    )
    return MCPCatalogSourceSyncResponse(
        source=catalog_source_response(source),
        synced_count=synced_count,
    )


async def create_server_version(
    session,
    payload: MCPServerCreate,
    organization_id: uuid.UUID | None = None,
) -> MCPRegistryServerResponse:
    organization_id = await catalog_organization_id(session, organization_id)
    if organization_id is not None:
        await limits_service.lock_quota_capacity(
            session,
            [
                limits_service.quota_scope(
                    limits_service.MCP_SERVER_VERSIONS_PER_ORGANIZATION,
                    organization_id,
                )
            ],
        )
    existing = await repository.get_server_version(
        session,
        payload.name,
        payload.version,
        include_deleted=True,
        organization_id=organization_id,
    )
    if existing is not None:
        if existing.status == "deleted":
            await repository.clear_latest_for_name(
                session,
                payload.name,
                organization_id=organization_id,
            )
            values = server_values(payload, is_latest=True)
            for key, value in values.items():
                setattr(existing, key, value)
            await session.flush()
            await session.refresh(existing)
            logger.info(
                "Reactivated MCP server version.",
                extra={
                    "organization_id": str(organization_id) if organization_id else None,
                    "mcp_server_name": existing.name,
                    "mcp_server_version": existing.version,
                    "mcp_server_version_id": str(existing.id),
                    "mcp_catalog_source_id": (
                        str(existing.catalog_source_id) if existing.catalog_source_id else None
                    ),
                },
            )
            return server_response(existing)
        raise DuplicateMCPServerVersionError("server version already exists")

    if organization_id is not None:
        version_count = await repository.count_server_versions_for_organization(
            session,
            organization_id,
        )
        await limits_service.require_limit_available(
            session,
            limit_key=limits_service.MCP_SERVER_VERSIONS_PER_ORGANIZATION,
            scope_chain=[
                ("organization", organization_id),
            ],
            current_count=version_count,
        )

    await repository.clear_latest_for_name(session, payload.name, organization_id=organization_id)
    server = MCPServerVersion(
        organization_id=organization_id,
        **server_values(payload, is_latest=True),
    )
    session.add(server)
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(
            exc,
            {"uq_mcp_server_versions_org_name_version"},
        ):
            raise DuplicateMCPServerVersionError("server version already exists") from exc
        raise
    await session.refresh(server)
    logger.info(
        "Created MCP server version.",
        extra={
            "organization_id": str(organization_id) if organization_id else None,
            "mcp_server_name": server.name,
            "mcp_server_version": server.version,
            "mcp_server_version_id": str(server.id),
            "mcp_server_is_latest": server.is_latest,
            "mcp_catalog_source_id": (
                str(server.catalog_source_id) if server.catalog_source_id else None
            ),
        },
    )
    return server_response(server)


async def update_server_version(
    session,
    name: str,
    version: str,
    payload: MCPServerCreate,
    organization_id: uuid.UUID | None = None,
) -> MCPRegistryServerResponse:
    organization_id = await catalog_organization_id(session, organization_id)
    if payload.name != name or payload.version != version:
        raise MCPServerNotFoundError("server version does not match request path")

    server = await repository.get_server_version(
        session,
        name,
        version,
        include_deleted=True,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("server version not found")

    was_deleted = server.status == "deleted"
    was_latest = server.is_latest
    if was_deleted:
        await repository.clear_latest_for_name(session, name, organization_id=organization_id)
    values = server_values(
        payload,
        is_latest=was_latest or was_deleted,
        catalog_source_id=server.catalog_source_id,
    )
    for key, value in values.items():
        setattr(server, key, value)

    await session.flush()
    await session.refresh(server)
    logger.info(
        "Updated MCP server version.",
        extra={
            "organization_id": str(organization_id) if organization_id else None,
            "mcp_server_name": server.name,
            "mcp_server_version": server.version,
            "mcp_server_version_id": str(server.id),
            "mcp_server_was_deleted": was_deleted,
            "mcp_server_is_latest": server.is_latest,
            "mcp_catalog_source_id": (
                str(server.catalog_source_id) if server.catalog_source_id else None
            ),
        },
    )
    return server_response(server)


async def delete_server_version(
    session,
    name: str,
    version: str,
    organization_id: uuid.UUID | None = None,
) -> None:
    organization_id = await catalog_organization_id(session, organization_id)
    server = await repository.get_server_version(
        session,
        name,
        version,
        include_deleted=True,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("server version not found")

    installations = await repository.list_installations_for_server(
        session,
        name,
        organization_id=organization_id,
    )
    if any(installation.installed_version == version for installation in installations):
        raise MCPServerVersionInUseError("server version is installed")

    was_latest = server.is_latest
    server.status = MCPServerStatusEnum.DELETED
    server.status_message = "Deleted from Wardn catalog."
    server.is_latest = False

    if was_latest:
        replacement = await repository.get_latest_visible_version(
            session,
            name,
            organization_id=organization_id,
        )
        if replacement:
            replacement.is_latest = True

    await session.flush()
    logger.info(
        "Deleted MCP server version.",
        extra={
            "organization_id": str(organization_id) if organization_id else None,
            "mcp_server_name": server.name,
            "mcp_server_version": server.version,
            "mcp_server_version_id": str(server.id),
            "mcp_server_was_latest": was_latest,
        },
    )


async def sync_supported_servers(
    session,
    payloads: list[MCPServerCreate],
    organization_id: uuid.UUID | None = None,
    *,
    catalog_source_id: uuid.UUID | None = None,
) -> int:
    organization_id = await catalog_organization_id(session, organization_id)
    if organization_id is None:
        raise ValueError("catalog organization is not configured")
    unique_payloads = list(
        {
            (payload.name, payload.version): payload
            for payload in payloads
        }.values()
    )
    duplicate_count = len(payloads) - len(unique_payloads)
    current_version_count = 0
    await limits_service.lock_quota_capacity(
        session,
        [
            limits_service.quota_scope(
                limits_service.MCP_SERVER_VERSIONS_PER_ORGANIZATION,
                organization_id,
            )
        ],
    )
    current_version_count = await repository.count_server_versions_for_organization(
        session,
        organization_id,
    )
    upstream_latest_by_name = {
        payload.name: payload.version
        for payload in unique_payloads
        if (metadata := registry_metadata(payload)) and metadata.is_latest
    }
    latest_by_name = {
        payload.name: upstream_latest_by_name.get(payload.name, payload.version)
        for payload in unique_payloads
    }
    keys = {(payload.name, payload.version) for payload in unique_payloads}
    existing_statuses = await repository.get_server_version_statuses(
        session,
        keys,
        organization_id=organization_id,
    )
    rows_with_metadata: list[dict] = []
    rows_without_metadata: list[dict] = []
    now = datetime.now(UTC)
    activated_version_count = 0
    for payload in unique_payloads:
        values = server_values(
            payload,
            is_latest=latest_by_name[payload.name] == payload.version,
            catalog_source_id=catalog_source_id,
        )
        key = (payload.name, payload.version)
        if values["status"] != "deleted" and existing_statuses.get(key) in (None, "deleted"):
            activated_version_count += 1
        values.update(id=uuid.uuid4(), organization_id=organization_id)
        if registry_metadata(payload) is not None:
            rows_with_metadata.append(values)
        else:
            values.update(published_at=now, status_changed_at=now)
            rows_without_metadata.append(values)

    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.MCP_SERVER_VERSIONS_PER_ORGANIZATION,
        scope_chain=[("organization", organization_id)],
        current_count=current_version_count,
        requested=activated_version_count,
    )
    await repository.clear_latest_for_names(
        session,
        {payload.name for payload in unique_payloads},
        organization_id=organization_id,
    )
    await repository.bulk_upsert_server_versions(
        session,
        rows_with_metadata,
        update_published_metadata=True,
    )
    await repository.bulk_upsert_server_versions(
        session,
        rows_without_metadata,
        update_published_metadata=False,
    )
    await session.flush()
    logger.info(
        "Upserted MCP catalog server batch.",
        extra={
            "organization_id": str(organization_id),
            "mcp_catalog_source_id": str(catalog_source_id) if catalog_source_id else None,
            "mcp_catalog_payload_count": len(payloads),
            "mcp_catalog_unique_count": len(unique_payloads),
            "mcp_catalog_duplicate_count": duplicate_count,
            "mcp_catalog_activated_count": activated_version_count,
            "mcp_catalog_metadata_count": len(rows_with_metadata),
            "mcp_catalog_without_metadata_count": len(rows_without_metadata),
        },
    )
    return len(unique_payloads)


async def list_servers(
    session,
    *,
    cursor: str | None,
    limit: int,
    include_deleted: bool,
    search: str | None = None,
    updated_since=None,
    version: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> MCPRegistryServerListResponse:
    organization_id = await catalog_organization_id(session, organization_id)
    try:
        servers, next_cursor = await repository.list_servers(
            session,
            cursor=cursor,
            limit=limit,
            include_deleted=include_deleted,
            search=search,
            updated_since=updated_since,
            version=version,
            organization_id=organization_id,
        )
    except InvalidCursorError as exc:
        raise InvalidRegistryCursorError("invalid registry cursor") from exc
    return MCPRegistryServerListResponse(
        servers=[server_response(server) for server in servers],
        metadata=MCPRegistryListMetadata(count=len(servers), next_cursor=next_cursor),
    )


async def list_versions(
    session,
    name: str,
    *,
    include_deleted: bool,
    organization_id: uuid.UUID | None = None,
) -> MCPRegistryServerListResponse:
    organization_id = await catalog_organization_id(session, organization_id)
    servers = await repository.list_server_versions(
        session,
        name,
        include_deleted=include_deleted,
        organization_id=organization_id,
    )
    if (
        not servers
        and await repository.count_versions_for_name(session, name, organization_id) == 0
    ):
        raise MCPServerNotFoundError("server not found")
    return MCPRegistryServerListResponse(
        servers=[server_response(server) for server in servers],
        metadata=MCPRegistryListMetadata(count=len(servers)),
    )


async def get_version(
    session,
    name: str,
    version: str,
    *,
    include_deleted: bool,
    organization_id: uuid.UUID | None = None,
) -> MCPRegistryServerResponse:
    organization_id = await catalog_organization_id(session, organization_id)
    server = await repository.get_server_version(
        session,
        name,
        version,
        include_deleted=include_deleted,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("server version not found")
    return server_response(server)


async def set_default_server_version(
    session,
    name: str,
    version: str,
    *,
    organization_id: uuid.UUID | None = None,
) -> MCPRegistryServerResponse:
    organization_id = await catalog_organization_id(session, organization_id)
    server = await repository.get_server_version(
        session,
        name,
        version,
        include_deleted=False,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("server version not found")

    await repository.clear_latest_for_name(session, name, organization_id=organization_id)
    server.is_latest = True
    await session.flush()
    await session.refresh(server)
    logger.info(
        "Set default MCP server version.",
        extra={
            "organization_id": str(organization_id) if organization_id else None,
            "mcp_server_name": server.name,
            "mcp_server_version": server.version,
            "mcp_server_version_id": str(server.id),
        },
    )
    return server_response(server)
