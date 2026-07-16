import asyncio
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from app.modules.limits import service as limits_service
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry import repository, tool_repository
from app.modules.mcp_registry.exceptions import (
    DuplicateMCPCatalogSourceError,
    DuplicateMCPServerVersionError,
    InvalidRegistryCursorError,
    MCPCatalogSourceNotFoundError,
    MCPServerInstallationFailedError,
    MCPServerInstallationNotFoundError,
    MCPServerInstallationUnsupportedError,
    MCPServerNotFoundError,
    MCPServerVersionInUseError,
)
from app.modules.mcp_registry.installer import (
    ConfigValues,
    config_file_content,
    config_value_mapping,
    config_value_present,
    config_value_text,
    file_config_definition,
    install_server_runtime,
    remove_installation_artifacts,
    safe_path_component,
    selected_install_target,
    write_secret_manifest,
)
from app.modules.mcp_registry.models import (
    MCPCatalogSource,
    MCPServerInstallation,
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
    MCPSecretHandleConfigValue,
    MCPServerBulkUpdateRequest,
    MCPServerCreate,
    MCPServerDocument,
    MCPServerInstallationListResponse,
    MCPServerInstallationRead,
    MCPServerInstallationToolsResponse,
    MCPServerInstallationToolValidationRequest,
    MCPServerInstallationToolValidationResponse,
    MCPServerInstallRequest,
    MCPServerToolRead,
)
from app.modules.mcp_registry.tool_service import refresh_tool_schemas_for_installation
from app.modules.mcp_runtime.manager import RUNTIME_PROVIDER_KUBERNETES, get_runtime_manager
from app.modules.mcp_runtime.service import call_tool_with_tracking
from app.modules.organizations import repository as organization_repository
from app.modules.secrets.exceptions import SecretsError
from app.modules.secrets.schemas import SecretHandleCreate
from app.modules.secrets.service import create_secret_handle, resolve_secret, write_secret_values
from app.modules.users.models import User

OFFICIAL_REGISTRY_META_KEY = "io.modelcontextprotocol.registry/official"
PULSE_SERVER_VERSION_META_KEY = "com.pulsemcp/server-version"
VERSION_PREFIX_PATTERN = re.compile(r"^\s*v?(\d+(?:[._-]\d+)*)", re.IGNORECASE)
CATALOG_SYNC_PAGE_SIZE = 100
WARDN_HUB_CATALOG_PATH = "/api/v1/mcp/catalog"
CATALOG_SOURCE_TOKEN_KEY = "api_token"
CATALOG_SOURCE_META_KEY = "wardnCatalogSource"
MCP_INSTALL_SECRET_VALUE_KEY_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


async def default_workspace_id(session) -> uuid.UUID:
    workspace = await organization_repository.get_default_workspace(session)
    if workspace is None:
        raise MCPServerInstallationNotFoundError("default workspace is not configured")
    return workspace.id


async def default_organization_id(session) -> uuid.UUID | None:
    if not hasattr(session, "get"):
        return None
    workspace = await organization_repository.get_default_workspace(session)
    return workspace.organization_id if workspace else None


async def catalog_organization_id(
    session,
    organization_id: uuid.UUID | None,
) -> uuid.UUID | None:
    return organization_id or await default_organization_id(session)


async def organization_id_for_workspace(
    session,
    workspace_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if workspace_id is None or not hasattr(session, "get"):
        return None
    workspace = await organization_repository.get_workspace_by_id(session, workspace_id)
    return workspace.organization_id if workspace else None


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
        statusChangedAt=metadata.status_changed_at or metadata.updated_at,
        statusMessage=metadata.status_message,
        publishedAt=published_at,
        updatedAt=metadata.updated_at,
        isLatest=metadata.is_latest,
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


def server_values(payload: MCPServerCreate, *, is_latest: bool) -> dict:
    metadata = registry_metadata(payload)
    server_json = payload.model_dump(by_alias=True, exclude_none=True)
    values = {
        "name": payload.name,
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


SECRET_HANDLE_REF_TYPE = "secret_handle"


def secret_handle_ref(handle_id: uuid.UUID | str) -> dict[str, str]:
    return {"type": SECRET_HANDLE_REF_TYPE, "secretHandleId": str(handle_id)}


def secret_handle_id_from_value(value) -> uuid.UUID | None:
    if isinstance(value, MCPSecretHandleConfigValue):
        return value.secret_handle_id
    mapping = config_value_mapping(value)
    if mapping.get("type") != SECRET_HANDLE_REF_TYPE:
        return None
    raw_handle_id = mapping.get("secretHandleId") or mapping.get("secret_handle_id")
    if not raw_handle_id:
        return None
    return uuid.UUID(str(raw_handle_id))


def parse_install_target_value(
    server: MCPServerVersion,
    install_target: str | None,
    config_values: ConfigValues,
) -> tuple[str, int]:
    raw_target = install_target or selected_install_target(server, config_values)
    kind, _, raw_index = raw_target.partition(":")
    kind = kind if kind in {"remote", "package"} else "package"
    try:
        index = int(raw_index or "0")
    except ValueError:
        index = 0
    return kind, max(index, 0)


def install_secret_key_name(field_name: str) -> str:
    key = MCP_INSTALL_SECRET_VALUE_KEY_PATTERN.sub("_", field_name.strip()).strip("._-")
    return key[:120] or "value"


def install_secret_display_name(config_name: str, field_name: str, run_id: str) -> str:
    label = field_name.removeprefix("headers.").replace("_", " ").strip()
    display_name = f"MCP {config_name} {label} {run_id}"
    return display_name[:100].strip()


def install_secret_path(
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    server_name: str,
    config_name: str,
    run_id: str,
) -> str:
    return "/".join(
        [
            "wardn",
            "organizations",
            str(organization_id),
            "workspaces",
            str(workspace_id),
            "mcp",
            safe_path_component(server_name),
            f"{safe_path_component(config_name)}-{run_id}",
        ]
    )


def selected_install_secret_fields(
    server: MCPServerVersion,
    install_target: str | None,
    config_values: ConfigValues,
) -> dict[str, str]:
    kind, index = parse_install_target_value(server, install_target, config_values)
    fields: dict[str, str] = {}

    if kind == "remote":
        remote = (server.remotes or [])[index] if index < len(server.remotes or []) else {}
        headers = remote.get("headers") if isinstance(remote, dict) else None
        if isinstance(headers, list):
            for header in headers:
                if not isinstance(header, dict) or not header.get("isSecret"):
                    continue
                name = str(header.get("name") or "").strip()
                if name:
                    fields[name] = "mcp_header"
    else:
        package = (server.packages or [])[index] if index < len(server.packages or []) else {}
        environment = package.get("environmentVariables") if isinstance(package, dict) else None
        if isinstance(environment, list):
            for env_var in environment:
                if not isinstance(env_var, dict) or not env_var.get("isSecret"):
                    continue
                name = str(env_var.get("name") or "").strip()
                if name:
                    fields[name] = "mcp_env"
        package_arguments = package.get("packageArguments") if isinstance(package, dict) else None
        if isinstance(package_arguments, list):
            for argument in package_arguments:
                if not isinstance(argument, dict):
                    continue
                name = str(argument.get("name") or "").strip()
                if not name:
                    continue
                if file_config_definition(argument):
                    fields[name] = "mcp_file"
                elif argument.get("isSecret"):
                    fields[name] = "runtime_config"

    for key, value in config_values.items():
        if str(key).startswith("headers."):
            fields[str(key)] = "mcp_header"
        elif config_value_mapping(value).get("type") == "file":
            fields[str(key)] = "mcp_file"
    return fields


def install_secret_value(value) -> tuple[str, dict | None]:
    mapping = config_value_mapping(value)
    if mapping.get("type") != "file":
        return config_value_text(value), None

    content = config_file_content(value)
    replacement = {
        key: item
        for key, item in mapping.items()
        if key not in {"content", "contentBase64", "content_base64", "path"}
    }
    replacement["type"] = "file"
    replacement.setdefault("filename", "")
    return content, replacement


async def externalize_install_config_secrets(
    session,
    user: User | None,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    server: MCPServerVersion,
    payload: MCPServerInstallRequest,
    config_values: ConfigValues,
) -> ConfigValues:
    secret_fields = selected_install_secret_fields(server, payload.install_target, config_values)
    raw_values: dict[str, str] = {}
    replacements: dict[str, dict | None] = {}
    field_key_names: dict[str, str] = {}

    for field_name in secret_fields:
        value = config_values.get(field_name)
        if not config_value_present(value) or secret_handle_id_from_value(value):
            continue
        mapping = config_value_mapping(value)
        if mapping.get("type") == "file" and secret_handle_id_from_value(mapping.get("content")):
            continue
        secret_value, replacement = install_secret_value(value)
        if not secret_value:
            continue
        key_name = install_secret_key_name(field_name)
        candidate = key_name
        counter = 2
        while candidate in raw_values:
            candidate = f"{key_name}_{counter}"
            counter += 1
        raw_values[candidate] = secret_value
        replacements[field_name] = replacement
        field_key_names[field_name] = candidate

    if not raw_values:
        return config_values
    if payload.config_secret_store_id is None:
        raise MCPServerInstallationUnsupportedError("secret backend is required for MCP secrets")
    if user is None:
        raise MCPServerInstallationUnsupportedError(
            "authenticated user is required for MCP secrets"
        )

    run_id = uuid.uuid4().hex[:8]
    external_ref = install_secret_path(
        organization_id,
        workspace_id,
        server.name,
        payload.config_name,
        run_id,
    )
    primary_purpose = next(iter(secret_fields.values()), "other")
    try:
        await write_secret_values(
            session,
            user,
            organization_id,
            payload.config_secret_store_id,
            workspace_id=workspace_id,
            external_ref=external_ref,
            values=raw_values,
            purpose=primary_purpose,
        )
    except SecretsError as exc:
        raise MCPServerInstallationUnsupportedError(str(exc)) from exc

    updated = dict(config_values)
    for field_name, key_name in field_key_names.items():
        purpose = secret_fields[field_name]
        try:
            handle = await create_secret_handle(
                session,
                user,
                organization_id,
                SecretHandleCreate(
                    storeId=payload.config_secret_store_id,
                    workspaceId=workspace_id,
                    purpose=purpose,
                    displayName=install_secret_display_name(
                        payload.config_name,
                        field_name,
                        run_id,
                    ),
                    externalRef=external_ref,
                    keyName=key_name,
                    metadata={
                        "serverName": server.name,
                        "configName": payload.config_name,
                        "configField": field_name,
                        "installTarget": payload.install_target or "",
                    },
                ),
            )
        except SecretsError as exc:
            raise MCPServerInstallationUnsupportedError(str(exc)) from exc

        replacement = replacements[field_name]
        if replacement is not None:
            updated[field_name] = {**replacement, "content": secret_handle_ref(handle.id)}
        else:
            updated[field_name] = secret_handle_ref(handle.id)
    return updated


async def resolve_install_config_values(
    session,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    config_values: ConfigValues,
) -> tuple[ConfigValues, dict[str, uuid.UUID]]:
    resolved: ConfigValues = {}
    handle_refs: dict[str, uuid.UUID] = {}
    for key, value in config_values.items():
        handle_id = secret_handle_id_from_value(value)
        mapping = config_value_mapping(value)
        content_handle_id = None
        if handle_id is None and mapping.get("type") == "file":
            content_handle_id = secret_handle_id_from_value(mapping.get("content"))
        if handle_id is None and content_handle_id is None:
            resolved[key] = value
            continue
        if content_handle_id is not None:
            handle_id = content_handle_id
        try:
            secret = await resolve_secret(
                session,
                organization_id,
                handle_id,
                workspace_id=workspace_id,
            )
        except SecretsError as exc:
            raise MCPServerInstallationNotFoundError(str(exc)) from exc
        if content_handle_id is not None:
            resolved[key] = {**mapping, "content": secret.value}
        else:
            resolved[key] = secret.value
        handle_refs[key] = handle_id
    return resolved, handle_refs


def secret_references_from_runtime_secret_config(
    secret_config: dict | None,
    handle_refs: dict[str, uuid.UUID],
) -> dict:
    if not secret_config:
        return {}
    references = deepcopy(secret_config)
    for namespace in ("headers", "environment", "packageArguments"):
        namespace_values = references.get(namespace)
        if not isinstance(namespace_values, dict):
            continue
        for key in list(namespace_values):
            if key in handle_refs:
                namespace_values[key] = secret_handle_ref(handle_refs[key])
            elif namespace == "headers" and f"headers.{key}" in handle_refs:
                namespace_values[key] = secret_handle_ref(handle_refs[f"headers.{key}"])
    files = references.get("files")
    if isinstance(files, dict):
        for key, detail in files.items():
            if key in handle_refs and isinstance(detail, dict):
                detail["content"] = secret_handle_ref(handle_refs[key])
    return references


def persist_install_secret_references(install_path: str, secret_references: dict) -> None:
    if not secret_references or not install_path:
        return
    path = Path(install_path)
    if path.exists():
        write_secret_manifest(path, secret_references)


async def validate_package_runtime_install(
    session,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
) -> None:
    if installation.install_type != "package":
        return
    manager = get_runtime_manager()
    try:
        provider_name = manager.provider_name(installation)
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        raise MCPServerInstallationFailedError(detail) from exc
    if provider_name != RUNTIME_PROVIDER_KUBERNETES:
        return

    try:
        await refresh_tool_schemas_for_installation(
            session,
            installation=installation,
            server=server,
            runtime_manager=manager,
        )
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        raise MCPServerInstallationFailedError(detail) from exc


def install_config_values_from_secret_references(secret_references: dict | None) -> ConfigValues:
    if not secret_references:
        return {}
    values: ConfigValues = {}
    for namespace in ("headers", "environment", "packageArguments"):
        namespace_values = secret_references.get(namespace)
        if isinstance(namespace_values, dict):
            values.update(
                {
                    str(key): value
                    for key, value in namespace_values.items()
                    if value is not None
                }
            )
    files = secret_references.get("files")
    if isinstance(files, dict):
        for name, detail in files.items():
            if not isinstance(detail, dict):
                continue
            content = detail.get("content")
            if content is None:
                continue
            values[str(name)] = {
                "type": "file",
                "filename": str(detail.get("filename") or ""),
                "content": content,
            }
    return values


def visible_config_field_names(
    server: MCPServerVersion,
    installation: MCPServerInstallation,
) -> set[str]:
    runtime_config = installation.runtime_config or {}
    package = runtime_config.get("package")
    transport = runtime_config.get("transport")
    definitions = []

    for package_definition in server.packages or []:
        definitions.extend(package_definition.get("environmentVariables", []))
        definitions.extend(package_definition.get("packageArguments", []))
    for remote in server.remotes or []:
        definitions.extend(remote.get("headers", []))

    if isinstance(package, dict):
        definitions.extend(package.get("environmentVariables", []))
        definitions.extend(package.get("packageArguments", []))
    if isinstance(transport, dict):
        definitions.extend(transport.get("headers", []))

    return {
        str(definition.get("name"))
        for definition in definitions
        if isinstance(definition, dict)
        and definition.get("name")
        and not definition.get("isSecret")
    }


def public_config_value(value) -> str:
    mapping = config_value_mapping(value)
    if not mapping:
        return config_value_text(value)
    return str(mapping.get("filename") or "configured")


def public_configured_values(
    server: MCPServerVersion,
    installation: MCPServerInstallation,
) -> dict[str, str]:
    visible_names = visible_config_field_names(server, installation)
    stored_values = install_config_values_from_secret_references(installation.secret_references)
    return {
        key: public_config_value(value)
        for key, value in stored_values.items()
        if key in visible_names
    }


def merged_install_config_values(
    existing: MCPServerInstallation | None,
    new_values: ConfigValues,
) -> ConfigValues:
    merged = install_config_values_from_secret_references(
        existing.secret_references if existing else None
    )
    merged.update({key: value for key, value in new_values.items() if config_value_present(value)})
    return merged


def parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise InvalidRegistryCursorError("invalid registry cursor") from exc
    if offset < 0:
        raise InvalidRegistryCursorError("invalid registry cursor")
    return offset


def server_response(server: MCPServerVersion) -> MCPRegistryServerResponse:
    status_message = server.status_message or None
    return MCPRegistryServerResponse(
        server=MCPServerDocument.model_validate(server.server_json),
        meta=MCPRegistryResponseMeta(
            official=MCPRegistryOfficialMetadata(
                status=server.status,
                status_changed_at=server.status_changed_at,
                status_message=status_message,
                published_at=server.published_at,
                updated_at=server.updated_at,
                is_latest=server.is_latest,
            )
        ),
    )


def catalog_source_response(source: MCPCatalogSource) -> MCPCatalogSourceRead:
    return MCPCatalogSourceRead(
        id=source.id,
        organizationId=source.organization_id,
        name=source.name,
        provider=source.provider,
        baseUrl=source.base_url,
        tenantId=source.tenant_id,
        syncMode=source.sync_mode,
        lastSuccessAt=source.last_success_at,
        lastSyncedUpdatedSince=source.last_synced_updated_since,
        lastError=source.last_error,
        isEnabled=source.is_enabled,
        hasAuthToken=source.auth_secret_handle_id is not None,
        createdAt=source.created_at,
        updatedAt=source.updated_at,
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
    auth_secret_handle_id = await create_catalog_source_token_handle(
        session,
        user,
        organization_id,
        name=payload.name,
        api_token=payload.api_token,
        secret_store_id=payload.api_token_secret_store_id,
        required=payload.provider == "wardn_hub",
    )

    source = MCPCatalogSource(
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
    await session.flush()
    await session.refresh(source)
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
    token_handle_id = await create_catalog_source_token_handle(
        session,
        user,
        organization_id,
        name=values.get("name", source.name),
        api_token=payload.api_token,
        secret_store_id=payload.api_token_secret_store_id,
        required=next_provider == "wardn_hub" and source.auth_secret_handle_id is None,
    )

    for key, value in values.items():
        if key in {"api_token", "api_token_secret_store_id"}:
            continue
        setattr(source, key, value)
    if token_handle_id is not None:
        source.auth_secret_handle_id = token_handle_id

    await session.flush()
    await session.refresh(source)
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
        server.status = "deleted"
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
) -> uuid.UUID | None:
    token = api_token.get_secret_value().strip() if api_token is not None else ""
    if not token:
        if required:
            raise ValueError("Wardn Hub catalog sources require an API token")
        return None
    if secret_store_id is None:
        raise ValueError("API token secret backend is required")

    run_id = uuid.uuid4().hex[:8]
    external_ref = catalog_source_token_path(
        organization_id=organization_id,
        name=name,
        run_id=run_id,
    )
    await write_secret_values(
        session,
        user,
        organization_id,
        secret_store_id,
        workspace_id=None,
        external_ref=external_ref,
        values={CATALOG_SOURCE_TOKEN_KEY: token},
        purpose="catalog_source",
    )
    handle = await create_secret_handle(
        session,
        user,
        organization_id,
        SecretHandleCreate(
            storeId=secret_store_id,
            workspaceId=None,
            purpose="catalog_source",
            displayName=catalog_source_token_display_name(name, run_id),
            externalRef=external_ref,
            keyName=CATALOG_SOURCE_TOKEN_KEY,
            metadata={"provider": "mcp_catalog", "catalogSourceName": name},
        ),
    )
    return handle.id


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

    from app.modules.mcp_registry.commands import (
        load_supported_servers_from_registry_url,
        registry_headers,
    )

    source_type = registry_source_type(source.provider)
    version = "latest" if source.sync_mode == "latest_only" else None

    try:
        headers = registry_headers(source_type, api_key=None, tenant_id=source.tenant_id or None)
        headers.update(await catalog_source_auth_headers(session, organization_id, source))
        last_error: Exception | None = None
        servers = None
        synced_source_url = ""
        for source_url in catalog_source_urls(source):
            try:
                servers = await asyncio.to_thread(
                    load_supported_servers_from_registry_url,
                    source_url,
                    limit=CATALOG_SYNC_PAGE_SIZE,
                    max_pages=None,
                    headers=headers,
                    version=version,
                    pagination="page" if source.provider == "wardn_hub" else "cursor",
                )
                synced_source_url = source_url
                break
            except Exception as exc:
                last_error = exc
        if servers is None:
            raise ValueError(
                f"no supported catalog API found at {source.base_url}: {last_error}"
            )
        sourced_servers = [
            catalog_source_payload(server, source=source, source_url=synced_source_url)
            for server in servers
        ]
        count = await sync_supported_servers(
            session,
            sourced_servers,
            organization_id=organization_id,
        )
    except Exception as exc:
        source.last_error = str(exc)
        await session.flush()
        raise ValueError(f"catalog sync failed: {exc}") from exc

    now = datetime.now(UTC)
    source.last_success_at = now
    source.last_synced_updated_since = now
    source.last_error = ""
    await session.flush()
    await session.refresh(source)
    return MCPCatalogSourceSyncResponse(
        source=catalog_source_response(source),
        syncedCount=count,
    )


async def installation_response(
    session,
    installation: MCPServerInstallation,
    organization_id: uuid.UUID | None = None,
) -> MCPServerInstallationRead:
    organization_id = organization_id or await organization_id_for_workspace(
        session,
        installation.workspace_id,
    )
    installed = await repository.get_server_version(
        session,
        installation.server_name,
        installation.installed_version,
        include_deleted=True,
        organization_id=organization_id,
    )
    latest = await repository.get_server_version(
        session,
        installation.server_name,
        "latest",
        include_deleted=False,
        organization_id=organization_id,
    )
    if installed is None or latest is None:
        raise MCPServerNotFoundError("installed server version not found")

    return MCPServerInstallationRead(
        id=installation.id,
        workspace_id=installation.workspace_id,
        server_name=installation.server_name,
        config_name=installation.config_name or "default",
        installed_version=installation.installed_version,
        latest_version=latest.version,
        update_available=server_update_available(installation.installed_version, latest.version),
        status=installation.status,
        install_type=installation.install_type,
        install_path=installation.install_path,
        runtime_config=installation.runtime_config,
        configured_values=public_configured_values(installed, installation),
        install_error=installation.install_error or None,
        installed_at=installation.installed_at,
        updated_at=installation.updated_at,
        server=MCPServerDocument.model_validate(installed.server_json),
        latest_server=MCPServerDocument.model_validate(latest.server_json),
    )


async def create_server_version(
    session,
    payload: MCPServerCreate,
    organization_id: uuid.UUID | None = None,
) -> MCPRegistryServerResponse:
    organization_id = await catalog_organization_id(session, organization_id)
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
    await session.flush()
    await session.refresh(server)
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
    values = server_values(payload, is_latest=was_latest or was_deleted)
    for key, value in values.items():
        setattr(server, key, value)

    await session.flush()
    await session.refresh(server)
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
    server.status = "deleted"
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


async def sync_supported_servers(
    session,
    payloads: list[MCPServerCreate],
    organization_id: uuid.UUID | None = None,
) -> int:
    organization_id = await catalog_organization_id(session, organization_id)
    upstream_latest_by_name = {
        payload.name: payload.version
        for payload in payloads
        if (metadata := registry_metadata(payload)) and metadata.is_latest
    }
    latest_by_name = {
        payload.name: upstream_latest_by_name.get(payload.name, payload.version)
        for payload in payloads
    }
    cleared_names: set[str] = set()

    for payload in payloads:
        if payload.name not in cleared_names:
            await repository.clear_latest_for_name(
                session,
                payload.name,
                organization_id=organization_id,
            )
            cleared_names.add(payload.name)

        existing = await repository.get_server_version(
            session,
            payload.name,
            payload.version,
            include_deleted=True,
            organization_id=organization_id,
        )
        values = server_values(
            payload,
            is_latest=latest_by_name[payload.name] == payload.version,
        )
        if existing is None:
            session.add(MCPServerVersion(organization_id=organization_id, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)

    await session.flush()
    return len(payloads)


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
    offset = parse_cursor(cursor)
    servers, next_cursor = await repository.list_servers(
        session,
        offset=offset,
        limit=limit,
        include_deleted=include_deleted,
        search=search,
        updated_since=updated_since,
        version=version,
        organization_id=organization_id,
    )
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
    return server_response(server)


async def list_installations(
    session,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallationListResponse:
    installations = await repository.list_installations(session, workspace_id)
    return MCPServerInstallationListResponse(
        installations=[
            await installation_response(session, installation)
            for installation in installations
        ]
    )


def tool_schema_response(tool) -> MCPServerToolRead:
    return MCPServerToolRead(
        server_name=tool.server_name,
        server_version=tool.server_version,
        tool_name=tool.tool_name,
        title=tool.title or tool.tool_name,
        description=tool.description or "",
        input_schema=tool.input_schema or {"type": "object"},
        output_schema=tool.output_schema,
        annotations=tool.annotations or {},
    )


def first_text_content(result: dict | None) -> str:
    if not result:
        return ""
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return str(first.get("text") or "")
    return ""


def validation_error_from_result(result: dict | None) -> str:
    text = first_text_content(result)
    if not result:
        return ""
    if result.get("isError"):
        return text

    normalized = text.strip().casefold()
    if normalized.startswith(("invalid input", "invalid request", "error:")):
        return text
    return ""


async def list_installation_tools(
    session,
    installation_id,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallationToolsResponse:
    installation = await repository.get_installation_by_id(
        session,
        installation_id,
        workspace_id,
    )
    if installation is None:
        raise MCPServerInstallationNotFoundError("server configuration is not installed")

    organization_id = await organization_id_for_workspace(session, installation.workspace_id)
    server = await repository.get_server_version(
        session,
        installation.server_name,
        installation.installed_version,
        include_deleted=True,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("installed server version not found")

    await refresh_tool_schemas_for_installation(
        session,
        installation=installation,
        server=server,
    )

    tools = await tool_repository.list_active_tool_schemas(
        session,
        installation_id=installation.id,
        server_name=server.name,
        server_version=server.version,
    )
    return MCPServerInstallationToolsResponse(
        server_name=installation.server_name,
        config_name=installation.config_name or "default",
        server_version=server.version,
        tools=[tool_schema_response(tool) for tool in tools],
        cache={
            "mode": "live-refresh",
            "refreshed": True,
        },
    )


async def validate_installation_tool(
    session,
    installation_id,
    payload: MCPServerInstallationToolValidationRequest,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallationToolValidationResponse:
    installation = await repository.get_installation_by_id(
        session,
        installation_id,
        workspace_id,
    )
    if installation is None:
        raise MCPServerInstallationNotFoundError("server configuration is not installed")

    organization_id = await organization_id_for_workspace(session, installation.workspace_id)
    server = await repository.get_server_version(
        session,
        installation.server_name,
        installation.installed_version,
        include_deleted=True,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("installed server version not found")

    error = ""
    result = None
    try:
        result = await call_tool_with_tracking(
            session,
            installation,
            server,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
        )
        error = validation_error_from_result(result)
        is_error = bool(error)
    except (MCPGatewayUpstreamError, ValueError) as exc:
        is_error = True
        error = str(exc)

    return MCPServerInstallationToolValidationResponse(
        server_name=installation.server_name,
        config_name=installation.config_name or "default",
        tool_name=payload.tool_name,
        status="failed" if is_error else "passed",
        is_error=is_error,
        error=error,
        result=result,
        validated_at=datetime.now(UTC),
    )


async def install_server_version(
    session,
    name: str,
    payload: MCPServerInstallRequest,
    workspace_id: uuid.UUID | None = None,
    user: User | None = None,
) -> MCPServerInstallationRead:
    workspace_id = workspace_id or await default_workspace_id(session)
    organization_id = await organization_id_for_workspace(session, workspace_id)
    server = await repository.get_server_version(
        session,
        name,
        payload.version,
        include_deleted=False,
        organization_id=organization_id,
    )
    if server is None:
        raise MCPServerNotFoundError("server version not found")

    installation = await repository.get_installation(
        session,
        name,
        payload.config_name,
        workspace_id,
    )
    config_values = merged_install_config_values(installation, payload.config_values)
    is_new_installation = installation is None
    if is_new_installation:
        installation_count = await repository.count_installations_for_workspace(
            session,
            workspace_id,
        )
        scope_chain = [("workspace", workspace_id)]
        if organization_id is not None:
            scope_chain.insert(1, ("organization", organization_id))
        await limits_service.require_limit_available(
            session,
            limit_key=limits_service.MCP_SERVER_INSTALLATIONS_PER_WORKSPACE,
            scope_chain=scope_chain,
            current_count=installation_count,
        )
    if organization_id is not None:
        config_values = await externalize_install_config_secrets(
            session,
            user,
            organization_id,
            workspace_id,
            server,
            payload,
            config_values,
        )
    resolved_config_values, handle_refs = await resolve_install_config_values(
        session,
        organization_id,
        workspace_id,
        config_values,
    )
    runtime_install = await asyncio.to_thread(
        install_server_runtime,
        server,
        config_values=resolved_config_values,
        install_target=payload.install_target,
        config_name=payload.config_name,
        workspace_id=str(workspace_id),
    )
    secret_references = secret_references_from_runtime_secret_config(
        runtime_install.secret_config,
        handle_refs,
    )
    persist_install_secret_references(runtime_install.install_path, secret_references)
    previous_install_path = installation.install_path if installation else ""
    if installation is None:
        installation = MCPServerInstallation(
            workspace_id=workspace_id,
            server_name=name,
            config_name=payload.config_name,
            installed_version=server.version,
            status=runtime_install.status,
            install_type=runtime_install.install_type,
            install_path=runtime_install.install_path,
            runtime_config=runtime_install.runtime_config,
            secret_references=secret_references,
            install_error=runtime_install.install_error,
        )
        session.add(installation)
    else:
        installation.installed_version = server.version
        installation.status = runtime_install.status
        installation.install_type = runtime_install.install_type
        installation.install_path = runtime_install.install_path
        installation.runtime_config = runtime_install.runtime_config
        installation.secret_references = secret_references
        installation.install_error = runtime_install.install_error

    await session.flush()
    await session.refresh(installation)
    try:
        await validate_package_runtime_install(session, installation, server)
    except MCPServerInstallationFailedError:
        if is_new_installation or previous_install_path != runtime_install.install_path:
            remove_installation_artifacts(runtime_install.install_path)
        raise

    if previous_install_path and previous_install_path != runtime_install.install_path:
        remove_installation_artifacts(previous_install_path)

    return await installation_response(session, installation, organization_id=organization_id)


async def uninstall_server(
    session,
    name: str,
    config_name: str = "default",
    workspace_id: uuid.UUID | None = None,
) -> None:
    workspace_id = workspace_id or await default_workspace_id(session)
    installation = await repository.get_installation(session, name, config_name, workspace_id)
    if installation is None:
        raise MCPServerInstallationNotFoundError("server is not installed")

    remove_installation_artifacts(installation.install_path)
    await repository.delete_installation(session, installation)
    await session.flush()


async def uninstall_installation(
    session,
    installation_id,
    workspace_id: uuid.UUID | None = None,
) -> None:
    installation = await repository.get_installation_by_id(session, installation_id, workspace_id)
    if installation is None:
        raise MCPServerInstallationNotFoundError("server configuration is not installed")

    remove_installation_artifacts(installation.install_path)
    await repository.delete_installation(session, installation)
    await session.flush()


async def update_installed_servers(
    session,
    payload: MCPServerBulkUpdateRequest,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallationListResponse:
    workspace_id = workspace_id or await default_workspace_id(session)
    organization_id = await organization_id_for_workspace(session, workspace_id)
    updated: list[MCPServerInstallationRead] = []
    for server_name in payload.server_names:
        installations = await repository.list_installations_for_server(
            session,
            server_name,
            workspace_id,
        )
        if not installations:
            raise MCPServerInstallationNotFoundError("server is not installed")
        latest = await repository.get_server_version(
            session,
            server_name,
            "latest",
            include_deleted=False,
            organization_id=organization_id,
        )
        if latest is None:
            raise MCPServerNotFoundError("latest server version not found")
        for installation in installations:
            install_target = "remote" if installation.install_type == "remote" else "package"
            config_values = install_config_values_from_secret_references(
                installation.secret_references
            )
            resolved_config_values, handle_refs = await resolve_install_config_values(
                session,
                organization_id,
                workspace_id,
                config_values,
            )
            runtime_install = await asyncio.to_thread(
                install_server_runtime,
                latest,
                config_values=resolved_config_values,
                install_target=install_target,
                config_name=installation.config_name,
                workspace_id=str(workspace_id),
            )
            secret_references = secret_references_from_runtime_secret_config(
                runtime_install.secret_config,
                handle_refs,
            )
            persist_install_secret_references(runtime_install.install_path, secret_references)
            previous_install_path = installation.install_path
            installation.installed_version = latest.version
            installation.status = runtime_install.status
            installation.install_type = runtime_install.install_type
            installation.install_path = runtime_install.install_path
            installation.runtime_config = runtime_install.runtime_config
            installation.secret_references = secret_references
            installation.install_error = runtime_install.install_error
            if previous_install_path and previous_install_path != runtime_install.install_path:
                remove_installation_artifacts(previous_install_path)
            await session.flush()
            await session.refresh(installation)
            updated.append(
                await installation_response(
                    session,
                    installation,
                    organization_id=organization_id,
                )
            )

    return MCPServerInstallationListResponse(installations=updated)
