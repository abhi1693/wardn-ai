"""MCP installation, tool-discovery, and validation application services."""

import asyncio
import uuid
from datetime import UTC, datetime

from app.core.pagination import CursorPageMetadata
from app.db.domain_types import MCPInstallationStatus
from app.modules.limits import service as limits_service
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry import repository, tool_repository
from app.modules.mcp_registry.catalog_service import server_update_available
from app.modules.mcp_registry.config_service import (
    externalize_install_config_secrets,
    install_config_values_from_secret_references,
    merged_install_config_values,
    persist_install_secret_references,
    public_configured_values,
    resolve_install_config_values,
    secret_references_from_runtime_secret_config,
    validate_package_runtime_install,
)
from app.modules.mcp_registry.exceptions import (
    MCPServerInstallationFailedError,
    MCPServerInstallationNotFoundError,
    MCPServerNotFoundError,
)
from app.modules.mcp_registry.installer import (
    install_server_runtime,
    remove_installation_artifacts,
)
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerVersion,
)
from app.modules.mcp_registry.schemas import (
    MCPServerBulkUpdateRequest,
    MCPServerDocument,
    MCPServerInstallationListResponse,
    MCPServerInstallationRead,
    MCPServerInstallationToolsResponse,
    MCPServerInstallationToolValidationRequest,
    MCPServerInstallationToolValidationResponse,
    MCPServerInstallRequest,
    MCPServerToolRead,
)
from app.modules.mcp_registry.scope_service import (
    default_workspace_id,
    organization_id_for_workspace,
)
from app.modules.mcp_registry.tool_service import refresh_tool_schemas_for_installation
from app.modules.mcp_runtime.service import call_tool_with_isolated_tracking
from app.modules.users.models import User


async def installation_response(
    session,
    installation: MCPServerInstallation,
    organization_id: uuid.UUID | None = None,
    installed: MCPServerVersion | None = None,
    latest: MCPServerVersion | None = None,
) -> MCPServerInstallationRead:
    if installed is None or latest is None:
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


async def list_installations(
    session,
    workspace_id: uuid.UUID | None = None,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> MCPServerInstallationListResponse:
    rows, next_cursor = await repository.list_installation_version_rows(
        session,
        workspace_id,
        cursor=cursor,
        limit=limit,
    )
    return MCPServerInstallationListResponse(
        installations=[
            await installation_response(
                session,
                installation,
                installed=installed,
                latest=latest,
            )
            for installation, installed, latest in rows
        ],
        metadata=CursorPageMetadata(count=len(rows), next_cursor=next_cursor),
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
        result = await call_tool_with_isolated_tracking(
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

    await limits_service.lock_quota_capacity(
        session,
        [
            limits_service.quota_scope(
                limits_service.MCP_SERVER_INSTALLATIONS_PER_WORKSPACE,
                workspace_id,
            )
        ],
    )
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
            status=MCPInstallationStatus(runtime_install.status),
            install_type=runtime_install.install_type,
            install_path=runtime_install.install_path,
            runtime_config=runtime_install.runtime_config,
            secret_references=secret_references,
            install_error=runtime_install.install_error,
        )
        session.add(installation)
    else:
        installation.installed_version = server.version
        installation.status = MCPInstallationStatus(runtime_install.status)
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
            installation.status = MCPInstallationStatus(runtime_install.status)
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

    return MCPServerInstallationListResponse(
        installations=updated,
        metadata=CursorPageMetadata(count=len(updated), next_cursor=""),
    )
