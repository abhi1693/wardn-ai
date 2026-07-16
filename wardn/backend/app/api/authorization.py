"""HTTP authorization boundaries shared by organization-scoped API routers."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations import service as organization_service
from app.modules.organizations.exceptions import (
    OrganizationAccessDeniedError,
    OrganizationNotFoundError,
    WorkspaceAccessDeniedError,
    WorkspaceNotFoundError,
)
from app.modules.users.models import User


async def require_organization_member_or_404(
    session: AsyncSession,
    current_user: User,
    organization_id: UUID,
) -> None:
    try:
        await organization_service.require_organization_member(
            session,
            current_user,
            organization_id,
        )
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
        await organization_service.require_organization_admin(
            session,
            current_user,
            organization_id,
        )
    except OrganizationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrganizationAccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


async def require_workspace_member_or_404(
    session: AsyncSession,
    current_user: User,
    organization_id: UUID,
    workspace_id: UUID,
) -> None:
    try:
        await organization_service.require_workspace_member(
            session,
            current_user,
            organization_id,
            workspace_id,
        )
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
        await organization_service.require_workspace_admin(
            session,
            current_user,
            organization_id,
            workspace_id,
        )
    except (OrganizationNotFoundError, WorkspaceNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (OrganizationAccessDeniedError, WorkspaceAccessDeniedError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
