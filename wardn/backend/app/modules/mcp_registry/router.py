from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry.exceptions import (
    DuplicateMCPServerVersionError,
    InvalidRegistryCursorError,
    MCPServerInstallationFailedError,
    MCPServerInstallationNotFoundError,
    MCPServerInstallationUnsupportedError,
    MCPServerNotFoundError,
    MCPServerVersionInUseError,
)
from app.modules.mcp_registry.schemas import (
    MCPRegistryServerListResponse,
    MCPRegistryServerResponse,
    MCPServerBulkUpdateRequest,
    MCPServerCreate,
    MCPServerInstallationListResponse,
    MCPServerInstallationRead,
    MCPServerInstallationToolsResponse,
    MCPServerInstallationToolValidationRequest,
    MCPServerInstallationToolValidationResponse,
    MCPServerInstallRequest,
)
from app.modules.mcp_registry.service import (
    create_server_version,
    delete_server_version,
    get_version,
    install_server_version,
    list_installation_tools,
    list_installations,
    list_servers,
    list_versions,
    uninstall_installation,
    uninstall_server,
    update_installed_servers,
    update_server_version,
    validate_installation_tool,
)
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.organizations.service import (
    require_organization_admin,
    require_organization_member,
    require_workspace_admin,
    require_workspace_member,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter(prefix="/mcp/registry", tags=["mcp-registry"])
organization_router = APIRouter(
    prefix="/organizations/{organization_id}/mcp/registry",
    tags=["organization-mcp-registry"],
)
workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/mcp/registry",
    tags=["workspace-mcp-registry"],
)


async def require_workspace_member_or_404(
    session: AsyncSession,
    current_user: User,
    organization_id: UUID,
    workspace_id: UUID,
) -> None:
    try:
        await require_workspace_member(session, current_user, organization_id, workspace_id)
    except (OrganizationNotFoundError, WorkspaceNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (OrganizationAccessDeniedError, WorkspaceAccessDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


async def require_workspace_admin_or_404(
    session: AsyncSession,
    current_user: User,
    organization_id: UUID,
    workspace_id: UUID,
) -> None:
    try:
        await require_workspace_admin(session, current_user, organization_id, workspace_id)
    except (OrganizationNotFoundError, WorkspaceNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (OrganizationAccessDeniedError, WorkspaceAccessDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


async def require_organization_member_or_404(
    session: AsyncSession,
    current_user: User,
    organization_id: UUID,
) -> None:
    try:
        await require_organization_member(session, current_user, organization_id)
    except OrganizationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


async def require_organization_admin_or_404(
    session: AsyncSession,
    current_user: User,
    organization_id: UUID,
) -> None:
    try:
        await require_organization_admin(session, current_user, organization_id)
    except OrganizationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@organization_router.get(
    "/servers",
    response_model=MCPRegistryServerListResponse,
    operation_id="organization_mcp_registry_list_servers",
)
async def list_organization_mcp_servers(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    search: str | None = None,
    updated_since: datetime | None = None,
    version: str | None = "latest",
    include_deleted: bool = False,
) -> MCPRegistryServerListResponse:
    await require_organization_member_or_404(session, current_user, organization_id)
    try:
        return await list_servers(
            session,
            cursor=cursor,
            limit=limit,
            include_deleted=include_deleted,
            search=search,
            updated_since=updated_since,
            version=version,
            organization_id=organization_id,
        )
    except InvalidRegistryCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid cursor",
        ) from exc


@organization_router.post(
    "/servers",
    response_model=MCPRegistryServerResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="organization_mcp_registry_create_server_version",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def create_organization_mcp_server_version(
    organization_id: UUID,
    payload: MCPServerCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPRegistryServerResponse:
    await require_organization_admin_or_404(session, current_user, organization_id)
    try:
        response = await create_server_version(session, payload, organization_id=organization_id)
    except DuplicateMCPServerVersionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="server version already exists",
        ) from exc
    await session.commit()
    return response


@organization_router.get(
    "/servers/{server_name:path}/versions",
    response_model=MCPRegistryServerListResponse,
    operation_id="organization_mcp_registry_list_server_versions",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def list_organization_mcp_server_versions(
    organization_id: UUID,
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    include_deleted: bool = False,
) -> MCPRegistryServerListResponse:
    await require_organization_member_or_404(session, current_user, organization_id)
    try:
        return await list_versions(
            session,
            server_name,
            include_deleted=include_deleted,
            organization_id=organization_id,
        )
    except MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server not found",
        ) from exc


@organization_router.get(
    "/servers/{server_name:path}/versions/{version}",
    response_model=MCPRegistryServerResponse,
    operation_id="organization_mcp_registry_get_server_version",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_organization_mcp_server_version(
    organization_id: UUID,
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    include_deleted: bool = False,
) -> MCPRegistryServerResponse:
    await require_organization_member_or_404(session, current_user, organization_id)
    try:
        return await get_version(
            session,
            server_name,
            version,
            include_deleted=include_deleted,
            organization_id=organization_id,
        )
    except MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server version not found",
        ) from exc


@organization_router.put(
    "/servers/{server_name:path}/versions/{version}",
    response_model=MCPRegistryServerResponse,
    operation_id="organization_mcp_registry_update_server_version",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def update_organization_mcp_server_version(
    organization_id: UUID,
    server_name: str,
    version: str,
    payload: MCPServerCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPRegistryServerResponse:
    await require_organization_admin_or_404(session, current_user, organization_id)
    try:
        response = await update_server_version(
            session,
            server_name,
            version,
            payload,
            organization_id=organization_id,
        )
    except MCPServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    return response


@organization_router.delete(
    "/servers/{server_name:path}/versions/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="organization_mcp_registry_delete_server_version",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def delete_organization_mcp_server_version(
    organization_id: UUID,
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await require_organization_admin_or_404(session, current_user, organization_id)
    try:
        await delete_server_version(session, server_name, version, organization_id=organization_id)
    except MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server version not found",
        ) from exc
    except MCPServerVersionInUseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()


@workspace_router.get(
    "/installed-servers",
    response_model=MCPServerInstallationListResponse,
    operation_id="workspace_mcp_registry_list_installed_servers",
)
async def list_workspace_installed_mcp_servers(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPServerInstallationListResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await list_installations(session, workspace_id)


@workspace_router.post(
    "/installed-servers/updates",
    response_model=MCPServerInstallationListResponse,
    operation_id="workspace_mcp_registry_update_installed_servers",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def update_workspace_installed_mcp_servers(
    organization_id: UUID,
    workspace_id: UUID,
    payload: MCPServerBulkUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPServerInstallationListResponse:
    await require_workspace_admin_or_404(session, current_user, organization_id, workspace_id)
    try:
        response = await update_installed_servers(session, payload, workspace_id)
    except (MCPServerInstallationNotFoundError, MCPServerNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MCPServerInstallationUnsupportedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MCPServerInstallationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"server installation failed: {exc}",
        ) from exc
    await session.commit()
    return response


@workspace_router.put(
    "/installed-servers/{server_name:path}",
    response_model=MCPServerInstallationRead,
    operation_id="workspace_mcp_registry_install_server_version",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse},
    },
)
async def install_workspace_mcp_server_version(
    organization_id: UUID,
    workspace_id: UUID,
    server_name: str,
    payload: MCPServerInstallRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPServerInstallationRead:
    await require_workspace_admin_or_404(session, current_user, organization_id, workspace_id)
    try:
        response = await install_server_version(session, server_name, payload, workspace_id)
    except MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server version not found",
        ) from exc
    except MCPServerInstallationUnsupportedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MCPServerInstallationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"server installation failed: {exc}",
        ) from exc
    await session.commit()
    return response


@workspace_router.delete(
    "/installed-server-configs/{installation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="workspace_mcp_registry_uninstall_server_config",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def uninstall_workspace_mcp_server_config(
    organization_id: UUID,
    workspace_id: UUID,
    installation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await require_workspace_admin_or_404(session, current_user, organization_id, workspace_id)
    try:
        await uninstall_installation(session, installation_id, workspace_id)
    except MCPServerInstallationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server configuration is not installed",
        ) from exc
    await session.commit()


@workspace_router.get(
    "/installed-server-configs/{installation_id}/tools",
    response_model=MCPServerInstallationToolsResponse,
    operation_id="workspace_mcp_registry_list_installed_server_tools",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ErrorResponse},
    },
)
async def list_workspace_installed_mcp_server_tools(
    organization_id: UUID,
    workspace_id: UUID,
    installation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPServerInstallationToolsResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    try:
        response = await list_installation_tools(session, installation_id, workspace_id)
    except (MCPServerInstallationNotFoundError, MCPServerNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MCPGatewayUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"installed MCP server could not list tools: {exc}",
        ) from exc
    if response.cache.get("refreshed"):
        await session.commit()
    return response


@workspace_router.post(
    "/installed-server-configs/{installation_id}/validate-tool",
    response_model=MCPServerInstallationToolValidationResponse,
    operation_id="workspace_mcp_registry_validate_installed_server_tool",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def validate_workspace_installed_mcp_server_tool(
    organization_id: UUID,
    workspace_id: UUID,
    installation_id: UUID,
    payload: MCPServerInstallationToolValidationRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPServerInstallationToolValidationResponse:
    await require_workspace_admin_or_404(session, current_user, organization_id, workspace_id)
    try:
        response = await validate_installation_tool(session, installation_id, payload, workspace_id)
    except (MCPServerInstallationNotFoundError, MCPServerNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    return response


@workspace_router.delete(
    "/installed-servers/{server_name:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="workspace_mcp_registry_uninstall_server",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def uninstall_workspace_mcp_server(
    organization_id: UUID,
    workspace_id: UUID,
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await require_workspace_admin_or_404(session, current_user, organization_id, workspace_id)
    try:
        await uninstall_server(session, server_name, workspace_id=workspace_id)
    except MCPServerInstallationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server is not installed",
        ) from exc
    await session.commit()


@router.get(
    "/installed-servers",
    response_model=MCPServerInstallationListResponse,
    operation_id="mcp_registry_list_installed_servers",
)
async def list_installed_mcp_servers(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPServerInstallationListResponse:
    return await list_installations(session)


@router.post(
    "/installed-servers/updates",
    response_model=MCPServerInstallationListResponse,
    operation_id="mcp_registry_update_installed_servers",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "One of the selected servers is not installed or has no latest version.",
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "One of the selected servers cannot be installed by this Wardn runtime.",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "One of the selected server installations failed.",
        },
    },
)
async def update_installed_mcp_servers(
    payload: MCPServerBulkUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPServerInstallationListResponse:
    try:
        response = await update_installed_servers(session, payload)
    except (MCPServerInstallationNotFoundError, MCPServerNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MCPServerInstallationUnsupportedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MCPServerInstallationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"server installation failed: {exc}",
        ) from exc
    await session.commit()
    return response


@router.put(
    "/installed-servers/{server_name:path}",
    response_model=MCPServerInstallationRead,
    operation_id="mcp_registry_install_server_version",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The requested server version was not found.",
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The requested server cannot be installed by this Wardn runtime.",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "The server installation failed.",
        },
    },
)
async def install_mcp_server_version(
    server_name: str,
    payload: MCPServerInstallRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPServerInstallationRead:
    try:
        response = await install_server_version(session, server_name, payload)
    except MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server version not found",
        ) from exc
    except MCPServerInstallationUnsupportedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MCPServerInstallationFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"server installation failed: {exc}",
        ) from exc
    await session.commit()
    return response


@router.delete(
    "/installed-server-configs/{installation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="mcp_registry_uninstall_server_config",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The requested server configuration is not installed.",
        },
    },
)
async def uninstall_mcp_server_config(
    installation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    try:
        await uninstall_installation(session, installation_id)
    except MCPServerInstallationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server configuration is not installed",
        ) from exc
    await session.commit()


@router.get(
    "/installed-server-configs/{installation_id}/tools",
    response_model=MCPServerInstallationToolsResponse,
    operation_id="mcp_registry_list_installed_server_tools",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The requested server configuration is not installed.",
        },
        status.HTTP_502_BAD_GATEWAY: {
            "model": ErrorResponse,
            "description": "The installed MCP server could not provide its tool list.",
        },
    },
)
async def list_installed_mcp_server_tools(
    installation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPServerInstallationToolsResponse:
    try:
        response = await list_installation_tools(session, installation_id)
    except (MCPServerInstallationNotFoundError, MCPServerNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except MCPGatewayUpstreamError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"installed MCP server could not list tools: {exc}",
        ) from exc
    if response.cache.get("refreshed"):
        await session.commit()
    return response


@router.post(
    "/installed-server-configs/{installation_id}/validate-tool",
    response_model=MCPServerInstallationToolValidationResponse,
    operation_id="mcp_registry_validate_installed_server_tool",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The requested server configuration is not installed.",
        },
    },
)
async def validate_installed_mcp_server_tool(
    installation_id: UUID,
    payload: MCPServerInstallationToolValidationRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPServerInstallationToolValidationResponse:
    try:
        response = await validate_installation_tool(session, installation_id, payload)
    except (MCPServerInstallationNotFoundError, MCPServerNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await session.commit()
    return response


@router.delete(
    "/installed-servers/{server_name:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="mcp_registry_uninstall_server",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The requested server is not installed.",
        },
    },
)
async def uninstall_mcp_server(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    try:
        await uninstall_server(session, server_name)
    except MCPServerInstallationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server is not installed",
        ) from exc
    await session.commit()


@router.get(
    "/servers",
    response_model=MCPRegistryServerListResponse,
    operation_id="mcp_registry_list_servers",
)
async def list_mcp_servers(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    search: str | None = None,
    updated_since: datetime | None = None,
    version: str | None = "latest",
    include_deleted: bool = False,
) -> MCPRegistryServerListResponse:
    try:
        return await list_servers(
            session,
            cursor=cursor,
            limit=limit,
            include_deleted=include_deleted,
            search=search,
            updated_since=updated_since,
            version=version,
        )
    except InvalidRegistryCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid cursor",
        ) from exc


@router.post(
    "/servers",
    response_model=MCPRegistryServerResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="mcp_registry_create_server_version",
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The requested server version already exists.",
        },
    },
)
async def create_mcp_server_version(
    payload: MCPServerCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPRegistryServerResponse:
    try:
        response = await create_server_version(session, payload)
    except DuplicateMCPServerVersionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="server version already exists",
        ) from exc
    await session.commit()
    return response


@router.get(
    "/servers/{server_name:path}/versions",
    response_model=MCPRegistryServerListResponse,
    operation_id="mcp_registry_list_server_versions",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The server was not found.",
        },
    },
)
async def list_mcp_server_versions(
    server_name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    include_deleted: bool = False,
) -> MCPRegistryServerListResponse:
    try:
        return await list_versions(session, server_name, include_deleted=include_deleted)
    except MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server not found",
        ) from exc


@router.put(
    "/servers/{server_name:path}/versions/{version}",
    response_model=MCPRegistryServerResponse,
    operation_id="mcp_registry_update_server_version",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The server version was not found.",
        },
    },
)
async def update_mcp_server_version(
    server_name: str,
    version: str,
    payload: MCPServerCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPRegistryServerResponse:
    try:
        response = await update_server_version(session, server_name, version, payload)
    except MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    await session.commit()
    return response


@router.delete(
    "/servers/{server_name:path}/versions/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="mcp_registry_delete_server_version",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The server version was not found.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The server version is currently installed.",
        },
    },
)
async def delete_mcp_server_version(
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    try:
        await delete_server_version(session, server_name, version)
    except MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server version not found",
        ) from exc
    except MCPServerVersionInUseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()


@router.get(
    "/servers/{server_name:path}/versions/{version}",
    response_model=MCPRegistryServerResponse,
    operation_id="mcp_registry_get_server_version",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "The server version was not found.",
        },
    },
)
async def get_mcp_server_version(
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    include_deleted: bool = False,
) -> MCPRegistryServerResponse:
    try:
        return await get_version(
            session,
            server_name,
            version,
            include_deleted=include_deleted,
        )
    except MCPServerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="server version not found",
        ) from exc
