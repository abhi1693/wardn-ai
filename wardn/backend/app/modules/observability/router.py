from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import ErrorResponse
from app.db.session import get_db_session
from app.modules.observability import service
from app.modules.observability.schemas import MCPToolUsageListResponse
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.organizations.service import require_workspace_member
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User

workspace_router = APIRouter(
    prefix="/organizations/{organization_id}/workspaces/{workspace_id}/observability",
    tags=["workspace-observability"],
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


@workspace_router.get(
    "/mcp-tool-usage",
    response_model=MCPToolUsageListResponse,
    operation_id="workspace_observability_list_mcp_tool_usage",
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
)
async def list_workspace_mcp_tool_usage_route(
    organization_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> MCPToolUsageListResponse:
    await require_workspace_member_or_404(session, current_user, organization_id, workspace_id)
    return await service.list_workspace_mcp_tool_usage(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=limit,
    )
