import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import (
    require_organization_admin_or_404,
    require_organization_member_or_404,
    require_workspace_admin_or_404,
    require_workspace_member_or_404,
)
from app.core.config import get_settings
from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry.catalog_jobs import enqueue_catalog_source_sync
from app.modules.mcp_registry.catalog_service import (
    create_catalog_source,
    create_server_version,
    delete_catalog_source,
    delete_server_version,
    get_catalog_source,
    get_version,
    list_catalog_sources,
    list_servers,
    list_versions,
    set_default_server_version,
    update_catalog_source,
    update_server_version,
)
from app.modules.mcp_registry.installation_jobs import (
    enqueue_installed_server_updates,
    enqueue_server_installation,
)
from app.modules.mcp_registry.installation_service import (
    list_installation_tools,
    list_installations,
    uninstall_installation,
    uninstall_server,
    validate_installation_tool,
)
from app.modules.mcp_registry.job_service import get_operation_job
from app.modules.mcp_registry.schemas import (
    MCPCatalogSourceCreate,
    MCPCatalogSourceListResponse,
    MCPCatalogSourceRead,
    MCPCatalogSourceUpdate,
    MCPOperationJobRead,
    MCPRegistryServerListResponse,
    MCPRegistryServerResponse,
    MCPRepositoryMetadataImportRequest,
    MCPRepositoryMetadataImportResponse,
    MCPServerBulkUpdateRequest,
    MCPServerCreate,
    MCPServerInstallationListResponse,
    MCPServerInstallationToolsResponse,
    MCPServerInstallationToolValidationRequest,
    MCPServerInstallationToolValidationResponse,
    MCPServerInstallRequest,
)
from app.modules.mcp_registry.source_metadata import (
    GitHubRepositoryNotFoundError,
    InvalidGitHubRepositoryURLError,
    import_repository_metadata,
)
from app.modules.mcp_registry.source_metadata_rate_limit import (
    consume_repository_metadata_rate_limit,
)
from app.modules.secrets.exceptions import SecretsError
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

logger = logging.getLogger(__name__)

organization_router = APIRouter(
    prefix="/organizations/{organization_id}/mcp/registry",
    tags=["organization-mcp-registry"],
)
organization_catalog_router = APIRouter(
    prefix="/organizations/{organization_id}/mcp/catalog",
    tags=["organization-mcp-catalog"],
)
workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/mcp/registry",
    tags=["workspace-mcp-registry"],
)


@organization_router.post(
    "/source-metadata",
    response_model=MCPRepositoryMetadataImportResponse,
    operation_id="organization_mcp_registry_import_repository_metadata",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
    },
)
async def import_organization_mcp_repository_metadata(
    organization_id: UUID,
    payload: MCPRepositoryMetadataImportRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPRepositoryMetadataImportResponse:
    await require_organization_admin_or_404(session, current_user, organization_id)
    settings = get_settings()
    rate_limit = await consume_repository_metadata_rate_limit(
        session,
        organization_id,
        limit=settings.github_metadata_import_rate_limit,
        window_seconds=settings.github_metadata_import_rate_window_seconds,
    )
    # Persist the shared rate-limit bucket and release the connection before outbound I/O.
    await session.commit()
    if not rate_limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Repository metadata import rate limit exceeded.",
            headers={"Retry-After": str(rate_limit.retry_after_seconds)},
        )
    try:
        return await import_repository_metadata(payload.repository_url)
    except InvalidGitHubRepositoryURLError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except GitHubRepositoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@organization_catalog_router.get(
    "/jobs/{job_id}",
    response_model=MCPOperationJobRead,
    operation_id="organization_mcp_catalog_get_operation_job",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_organization_mcp_catalog_operation_job(
    organization_id: UUID,
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPOperationJobRead:
    await require_organization_member_or_404(session, current_user, organization_id)
    return await get_operation_job(
        session,
        job_id,
        organization_id=organization_id,
        workspace_id=None,
    )


@organization_catalog_router.get(
    "/sources",
    response_model=MCPCatalogSourceListResponse,
    operation_id="organization_mcp_catalog_list_sources",
)
async def list_organization_mcp_catalog_sources(
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPCatalogSourceListResponse:
    await require_organization_member_or_404(session, current_user, organization_id)
    return await list_catalog_sources(session, organization_id)


@organization_catalog_router.post(
    "/sources",
    response_model=MCPCatalogSourceRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="organization_mcp_catalog_create_source",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
async def create_organization_mcp_catalog_source(
    organization_id: UUID,
    payload: MCPCatalogSourceCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPCatalogSourceRead:
    await require_organization_admin_or_404(session, current_user, organization_id)
    try:
        response = await create_catalog_source(session, current_user, organization_id, payload)
    except (SecretsError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return response


@organization_catalog_router.get(
    "/sources/{source_id}",
    response_model=MCPCatalogSourceRead,
    operation_id="organization_mcp_catalog_get_source",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_organization_mcp_catalog_source(
    organization_id: UUID,
    source_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPCatalogSourceRead:
    await require_organization_member_or_404(session, current_user, organization_id)
    return await get_catalog_source(session, organization_id, source_id)


@organization_catalog_router.patch(
    "/sources/{source_id}",
    response_model=MCPCatalogSourceRead,
    operation_id="organization_mcp_catalog_update_source",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def update_organization_mcp_catalog_source(
    organization_id: UUID,
    source_id: UUID,
    payload: MCPCatalogSourceUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPCatalogSourceRead:
    await require_organization_admin_or_404(session, current_user, organization_id)
    try:
        response = await update_catalog_source(
            session,
            current_user,
            organization_id,
            source_id,
            payload,
        )
    except (SecretsError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return response


@organization_catalog_router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="organization_mcp_catalog_delete_source",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def delete_organization_mcp_catalog_source(
    organization_id: UUID,
    source_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await require_organization_admin_or_404(session, current_user, organization_id)
    await delete_catalog_source(session, organization_id, source_id)


@organization_catalog_router.post(
    "/sources/{source_id}/sync",
    response_model=MCPOperationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="organization_mcp_catalog_sync_source",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def sync_organization_mcp_catalog_source(
    organization_id: UUID,
    source_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPOperationJobRead:
    await require_organization_admin_or_404(session, current_user, organization_id)
    try:
        response = await enqueue_catalog_source_sync(
            session,
            organization_id=organization_id,
            source_id=source_id,
            user=current_user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return response


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
    return await create_server_version(session, payload, organization_id=organization_id)


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
    return await list_versions(
        session,
        server_name,
        include_deleted=include_deleted,
        organization_id=organization_id,
    )


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
    return await get_version(
        session,
        server_name,
        version,
        include_deleted=include_deleted,
        organization_id=organization_id,
    )


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
    return await update_server_version(
        session,
        server_name,
        version,
        payload,
        organization_id=organization_id,
    )


@organization_router.post(
    "/servers/{server_name:path}/versions/{version}/default",
    response_model=MCPRegistryServerResponse,
    operation_id="organization_mcp_registry_set_default_server_version",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def set_default_organization_mcp_server_version(
    organization_id: UUID,
    server_name: str,
    version: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPRegistryServerResponse:
    await require_organization_admin_or_404(session, current_user, organization_id)
    return await set_default_server_version(
        session,
        server_name,
        version,
        organization_id=organization_id,
    )


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
    await delete_server_version(session, server_name, version, organization_id=organization_id)


@workspace_router.get(
    "/jobs/{job_id}",
    response_model=MCPOperationJobRead,
    operation_id="workspace_mcp_registry_get_operation_job",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_workspace_mcp_operation_job(
    organization_id: UUID,
    workspace_id: UUID,
    job_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPOperationJobRead:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await get_operation_job(
        session,
        job_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


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
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MCPServerInstallationListResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await list_installations(
        session,
        workspace_id,
        cursor=cursor,
        limit=limit,
    )


@workspace_router.post(
    "/installed-servers/updates",
    response_model=MCPOperationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="workspace_mcp_registry_update_installed_servers",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
    },
)
async def update_workspace_installed_mcp_servers(
    organization_id: UUID,
    workspace_id: UUID,
    payload: MCPServerBulkUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPOperationJobRead:
    await require_workspace_admin_or_404(session, current_user, organization_id, workspace_id)
    return await enqueue_installed_server_updates(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user=current_user,
        payload=payload,
    )


@workspace_router.put(
    "/installed-servers/{server_name:path}",
    response_model=MCPOperationJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="workspace_mcp_registry_install_server_version",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
    },
)
async def install_workspace_mcp_server_version(
    organization_id: UUID,
    workspace_id: UUID,
    server_name: str,
    payload: MCPServerInstallRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPOperationJobRead:
    await require_workspace_admin_or_404(session, current_user, organization_id, workspace_id)
    return await enqueue_server_installation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user=current_user,
        server_name=server_name,
        payload=payload,
    )


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
    await uninstall_installation(session, installation_id, workspace_id)


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
    except MCPGatewayUpstreamError as exc:
        logger.warning(
            "Installed MCP server tool discovery failed",
            extra={
                "installation_id": str(installation_id),
                "organization_id": str(organization_id),
                "workspace_id": str(workspace_id),
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"installed MCP server could not list tools: {exc}",
        ) from exc
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
    return await validate_installation_tool(session, installation_id, payload, workspace_id)


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
    await uninstall_server(session, server_name, workspace_id=workspace_id)
