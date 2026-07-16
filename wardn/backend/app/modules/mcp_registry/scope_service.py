"""Shared organization/workspace scope resolution for MCP registry services."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_registry.exceptions import MCPServerInstallationNotFoundError
from app.modules.organizations import repository as organization_repository


async def default_workspace_id(session: AsyncSession) -> uuid.UUID:
    workspace = await organization_repository.get_default_workspace(session)
    if workspace is None:
        raise MCPServerInstallationNotFoundError("default workspace is not configured")
    return workspace.id


async def default_organization_id(session: AsyncSession) -> uuid.UUID | None:
    workspace = await organization_repository.get_default_workspace(session)
    return workspace.organization_id if workspace else None


async def catalog_organization_id(
    session: AsyncSession,
    organization_id: uuid.UUID | None,
) -> uuid.UUID | None:
    return organization_id or await default_organization_id(session)


async def organization_id_for_workspace(
    session: AsyncSession,
    workspace_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if workspace_id is None:
        return None
    workspace = await organization_repository.get_workspace_by_id(session, workspace_id)
    return workspace.organization_id if workspace else None
