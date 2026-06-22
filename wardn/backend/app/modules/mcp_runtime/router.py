from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.mcp_runtime import service
from app.modules.mcp_runtime.schemas import (
    MCPRuntimeEventListResponse,
    MCPRuntimeSessionListResponse,
    MCPRuntimeSessionRead,
    MCPRuntimeSummaryResponse,
)
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.organizations.service import (
    require_workspace_admin,
    require_workspace_member,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

router = APIRouter(prefix="/mcp/runtime", tags=["mcp-runtime"])
workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/mcp/runtime",
    tags=["workspace-mcp-runtime"],
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


@router.get(
    "/summary",
    response_model=MCPRuntimeSummaryResponse,
    operation_id="mcp_runtime_get_summary",
)
async def get_mcp_runtime_summary(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPRuntimeSummaryResponse:
    return await service.get_runtime_summary(session)


@router.get(
    "/sessions",
    response_model=MCPRuntimeSessionListResponse,
    operation_id="mcp_runtime_list_sessions",
)
async def list_mcp_runtime_sessions(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> MCPRuntimeSessionListResponse:
    return await service.list_runtime_sessions(session, status=status, limit=limit)


@router.get(
    "/sessions/{runtime_session_id}",
    response_model=MCPRuntimeSessionRead,
    operation_id="mcp_runtime_get_session",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_mcp_runtime_session(
    runtime_session_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPRuntimeSessionRead:
    try:
        return await service.get_runtime_session(session, runtime_session_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="runtime session not found",
        ) from exc


@router.post(
    "/sessions/{runtime_session_id}/stop",
    response_model=MCPRuntimeSessionRead,
    operation_id="mcp_runtime_stop_session",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def stop_mcp_runtime_session(
    runtime_session_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MCPRuntimeSessionRead:
    try:
        response = await service.stop_runtime_session(session, runtime_session_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="runtime session not found",
        ) from exc
    await session.commit()
    return response


@router.get(
    "/sessions/{runtime_session_id}/events",
    response_model=MCPRuntimeEventListResponse,
    operation_id="mcp_runtime_list_session_events",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def list_mcp_runtime_session_events(
    runtime_session_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> MCPRuntimeEventListResponse:
    try:
        return await service.list_runtime_events(session, runtime_session_id, limit=limit)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="runtime session not found",
        ) from exc


@workspace_router.get(
    "/summary",
    response_model=MCPRuntimeSummaryResponse,
    operation_id="workspace_mcp_runtime_get_summary",
)
async def get_workspace_mcp_runtime_summary(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPRuntimeSummaryResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await service.get_runtime_summary(session, workspace_id=workspace_id)


@workspace_router.get(
    "/sessions",
    response_model=MCPRuntimeSessionListResponse,
    operation_id="workspace_mcp_runtime_list_sessions",
)
async def list_workspace_mcp_runtime_sessions(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> MCPRuntimeSessionListResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await service.list_runtime_sessions(
        session,
        workspace_id=workspace_id,
        status=status,
        limit=limit,
    )


@workspace_router.get(
    "/sessions/{runtime_session_id}",
    response_model=MCPRuntimeSessionRead,
    operation_id="workspace_mcp_runtime_get_session",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_workspace_mcp_runtime_session(
    organization_id: UUID,
    workspace_id: UUID,
    runtime_session_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPRuntimeSessionRead:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    try:
        return await service.get_runtime_session(
            session,
            runtime_session_id,
            workspace_id=workspace_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="runtime session not found",
        ) from exc


@workspace_router.post(
    "/sessions/{runtime_session_id}/stop",
    response_model=MCPRuntimeSessionRead,
    operation_id="workspace_mcp_runtime_stop_session",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def stop_workspace_mcp_runtime_session(
    organization_id: UUID,
    workspace_id: UUID,
    runtime_session_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPRuntimeSessionRead:
    await require_workspace_admin_or_404(session, current_user, organization_id, workspace_id)
    try:
        response = await service.stop_runtime_session(
            session,
            runtime_session_id,
            workspace_id=workspace_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="runtime session not found",
        ) from exc
    await session.commit()
    return response


@workspace_router.get(
    "/sessions/{runtime_session_id}/events",
    response_model=MCPRuntimeEventListResponse,
    operation_id="workspace_mcp_runtime_list_session_events",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def list_workspace_mcp_runtime_session_events(
    organization_id: UUID,
    workspace_id: UUID,
    runtime_session_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> MCPRuntimeEventListResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    try:
        return await service.list_runtime_events(
            session,
            runtime_session_id,
            workspace_id=workspace_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="runtime session not found",
        ) from exc
