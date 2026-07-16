from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.authorization import (
    require_workspace_admin_or_404,
    require_workspace_member_or_404,
)
from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.mcp_runtime import service
from app.modules.mcp_runtime.schemas import (
    MCPRuntimeEventListResponse,
    MCPRuntimeSessionHealthResponse,
    MCPRuntimeSessionListResponse,
    MCPRuntimeSessionRead,
    MCPRuntimeSummaryResponse,
)
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/mcp/runtime",
    tags=["workspace-mcp-runtime"],
)

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
    return await service.get_runtime_session(
        session,
        runtime_session_id,
        workspace_id=workspace_id,
    )


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
    return await service.stop_runtime_session(
        session,
        runtime_session_id,
        workspace_id=workspace_id,
    )


@workspace_router.get(
    "/sessions/{runtime_session_id}/health",
    response_model=MCPRuntimeSessionHealthResponse,
    operation_id="workspace_mcp_runtime_get_session_health",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_workspace_mcp_runtime_session_health(
    organization_id: UUID,
    workspace_id: UUID,
    runtime_session_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MCPRuntimeSessionHealthResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await service.get_runtime_session_health(
        session,
        runtime_session_id,
        workspace_id=workspace_id,
    )


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
    return await service.list_runtime_events(
        session,
        runtime_session_id,
        workspace_id=workspace_id,
        limit=limit,
    )
