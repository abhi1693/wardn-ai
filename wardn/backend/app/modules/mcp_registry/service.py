import uuid
from datetime import UTC, datetime

from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry import repository, tool_repository
from app.modules.mcp_registry.exceptions import (
    DuplicateMCPServerVersionError,
    InvalidRegistryCursorError,
    MCPServerInstallationNotFoundError,
    MCPServerNotFoundError,
    MCPServerVersionInUseError,
)
from app.modules.mcp_registry.installer import install_server_runtime, remove_installation_artifacts
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.mcp_registry.schemas import (
    MCPRegistryListMetadata,
    MCPRegistryOfficialMetadata,
    MCPRegistryResponseMeta,
    MCPRegistryServerListResponse,
    MCPRegistryServerResponse,
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
from app.modules.mcp_runtime.service import call_tool_with_tracking
from app.modules.organizations import repository as organization_repository


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

    raw_metadata = payload.meta.get("io.modelcontextprotocol.registry/official")
    if not isinstance(raw_metadata, dict):
        return None

    return MCPRegistryOfficialMetadata.model_validate(raw_metadata)


def server_values(payload: MCPServerCreate, *, is_latest: bool) -> dict:
    metadata = official_metadata(payload)
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


def install_config_values_from_secret_config(secret_config: dict | None) -> dict[str, str]:
    if not secret_config:
        return {}
    values = {}
    for namespace in ("headers", "environment", "packageArguments"):
        namespace_values = secret_config.get(namespace)
        if isinstance(namespace_values, dict):
            values.update(
                {
                    str(key): str(value)
                    for key, value in namespace_values.items()
                    if value is not None
                }
            )
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


def public_configured_values(
    server: MCPServerVersion,
    installation: MCPServerInstallation,
) -> dict[str, str]:
    visible_names = visible_config_field_names(server, installation)
    stored_values = install_config_values_from_secret_config(installation.secret_config)
    return {
        key: value
        for key, value in stored_values.items()
        if key in visible_names
    }


def merged_install_config_values(
    existing: MCPServerInstallation | None,
    new_values: dict[str, str],
) -> dict[str, str]:
    merged = install_config_values_from_secret_config(
        existing.secret_config if existing else None
    )
    merged.update({key: value for key, value in new_values.items() if value})
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
        update_available=installation.installed_version != latest.version,
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
    official_latest_by_name = {
        payload.name: payload.version
        for payload in payloads
        if (metadata := official_metadata(payload)) and metadata.is_latest
    }
    latest_by_name = {
        payload.name: official_latest_by_name.get(payload.name, payload.version)
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
    runtime_install = install_server_runtime(
        server,
        config_values=config_values,
        install_target=payload.install_target,
        config_name=payload.config_name,
        workspace_id=str(workspace_id),
    )
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
            secret_config=runtime_install.secret_config,
            install_error=runtime_install.install_error,
        )
        session.add(installation)
    else:
        installation.installed_version = server.version
        installation.status = runtime_install.status
        installation.install_type = runtime_install.install_type
        installation.install_path = runtime_install.install_path
        installation.runtime_config = runtime_install.runtime_config
        installation.secret_config = runtime_install.secret_config
        installation.install_error = runtime_install.install_error

    if previous_install_path and previous_install_path != runtime_install.install_path:
        remove_installation_artifacts(previous_install_path)

    await session.flush()
    await session.refresh(installation)
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
            runtime_install = install_server_runtime(
                latest,
                config_values=install_config_values_from_secret_config(installation.secret_config),
                install_target=install_target,
                config_name=installation.config_name,
                workspace_id=str(workspace_id),
            )
            previous_install_path = installation.install_path
            installation.installed_version = latest.version
            installation.status = runtime_install.status
            installation.install_type = runtime_install.install_type
            installation.install_path = runtime_install.install_path
            installation.runtime_config = runtime_install.runtime_config
            installation.secret_config = runtime_install.secret_config
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
