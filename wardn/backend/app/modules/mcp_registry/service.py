from app.modules.mcp_registry import repository
from app.modules.mcp_registry.exceptions import (
    DuplicateMCPServerVersionError,
    InvalidRegistryCursorError,
    MCPServerInstallationNotFoundError,
    MCPServerNotFoundError,
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
    MCPServerInstallRequest,
)


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
    for namespace in ("headers", "environment"):
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
) -> MCPServerInstallationRead:
    installed = await repository.get_server_version(
        session,
        installation.server_name,
        installation.installed_version,
        include_deleted=True,
    )
    latest = await repository.get_server_version(
        session,
        installation.server_name,
        "latest",
        include_deleted=False,
    )
    if installed is None or latest is None:
        raise MCPServerNotFoundError("installed server version not found")

    return MCPServerInstallationRead(
        server_name=installation.server_name,
        installed_version=installation.installed_version,
        latest_version=latest.version,
        update_available=installation.installed_version != latest.version,
        status=installation.status,
        install_type=installation.install_type,
        install_path=installation.install_path,
        runtime_config=installation.runtime_config,
        install_error=installation.install_error or None,
        installed_at=installation.installed_at,
        updated_at=installation.updated_at,
        server=MCPServerDocument.model_validate(installed.server_json),
        latest_server=MCPServerDocument.model_validate(latest.server_json),
    )


async def create_server_version(session, payload: MCPServerCreate) -> MCPRegistryServerResponse:
    existing = await repository.get_server_version(
        session,
        payload.name,
        payload.version,
        include_deleted=True,
    )
    if existing is not None:
        raise DuplicateMCPServerVersionError("server version already exists")

    await repository.clear_latest_for_name(session, payload.name)
    server = MCPServerVersion(
        **server_values(payload, is_latest=True),
    )
    session.add(server)
    await session.flush()
    await session.refresh(server)
    return server_response(server)


async def sync_supported_servers(session, payloads: list[MCPServerCreate]) -> int:
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
            await repository.clear_latest_for_name(session, payload.name)
            cleared_names.add(payload.name)

        existing = await repository.get_server_version(
            session,
            payload.name,
            payload.version,
            include_deleted=True,
        )
        values = server_values(
            payload,
            is_latest=latest_by_name[payload.name] == payload.version,
        )
        if existing is None:
            session.add(MCPServerVersion(**values))
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
) -> MCPRegistryServerListResponse:
    offset = parse_cursor(cursor)
    servers, next_cursor = await repository.list_servers(
        session,
        offset=offset,
        limit=limit,
        include_deleted=include_deleted,
        search=search,
        updated_since=updated_since,
        version=version,
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
) -> MCPRegistryServerListResponse:
    servers = await repository.list_server_versions(
        session,
        name,
        include_deleted=include_deleted,
    )
    if not servers and await repository.count_versions_for_name(session, name) == 0:
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
) -> MCPRegistryServerResponse:
    server = await repository.get_server_version(
        session,
        name,
        version,
        include_deleted=include_deleted,
    )
    if server is None:
        raise MCPServerNotFoundError("server version not found")
    return server_response(server)


async def list_installations(session) -> MCPServerInstallationListResponse:
    installations = await repository.list_installations(session)
    return MCPServerInstallationListResponse(
        installations=[
            await installation_response(session, installation)
            for installation in installations
        ]
    )


async def install_server_version(
    session,
    name: str,
    payload: MCPServerInstallRequest,
) -> MCPServerInstallationRead:
    server = await repository.get_server_version(
        session,
        name,
        payload.version,
        include_deleted=False,
    )
    if server is None:
        raise MCPServerNotFoundError("server version not found")

    runtime_install = install_server_runtime(server, config_values=payload.config_values)
    installation = await repository.get_installation(session, name)
    previous_install_path = installation.install_path if installation else ""
    if installation is None:
        installation = MCPServerInstallation(
            server_name=name,
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
    return await installation_response(session, installation)


async def uninstall_server(session, name: str) -> None:
    installation = await repository.get_installation(session, name)
    if installation is None:
        raise MCPServerInstallationNotFoundError("server is not installed")

    remove_installation_artifacts(installation.install_path)
    await repository.delete_installation(session, installation)
    await session.flush()


async def update_installed_servers(
    session,
    payload: MCPServerBulkUpdateRequest,
) -> MCPServerInstallationListResponse:
    updated: list[MCPServerInstallationRead] = []
    for server_name in payload.server_names:
        installation = await repository.get_installation(session, server_name)
        if installation is None:
            raise MCPServerInstallationNotFoundError("server is not installed")
        latest = await repository.get_server_version(
            session,
            server_name,
            "latest",
            include_deleted=False,
        )
        if latest is None:
            raise MCPServerNotFoundError("latest server version not found")
        runtime_install = install_server_runtime(
            latest,
            config_values=install_config_values_from_secret_config(installation.secret_config),
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
        updated.append(await installation_response(session, installation))

    return MCPServerInstallationListResponse(installations=updated)
