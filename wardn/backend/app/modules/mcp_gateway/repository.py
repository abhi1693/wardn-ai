import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion


async def search_enabled_installations(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID | None = None,
    search: str,
    offset: int,
    limit: int,
) -> tuple[list[tuple[MCPServerInstallation, MCPServerVersion]], str]:
    statement = (
        select(MCPServerInstallation, MCPServerVersion)
        .join(
            MCPServerVersion,
            and_(
                MCPServerVersion.name == MCPServerInstallation.server_name,
                MCPServerVersion.version == MCPServerInstallation.installed_version,
            ),
        )
        .where(MCPServerInstallation.status == "enabled")
        .order_by(MCPServerInstallation.server_name.asc())
    )
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)

    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                MCPServerVersion.name.ilike(pattern),
                MCPServerVersion.title.ilike(pattern),
                MCPServerVersion.description.ilike(pattern),
            )
        )

    result = await session.execute(statement.offset(offset).limit(limit + 1))
    rows = list(result.all())
    next_cursor = str(offset + limit) if len(rows) > limit else ""
    return rows[:limit], next_cursor


async def get_enabled_installation(
    session: AsyncSession,
    server_name: str,
    workspace_id: uuid.UUID | None = None,
) -> tuple[MCPServerInstallation, MCPServerVersion] | None:
    statement = (
        select(MCPServerInstallation, MCPServerVersion)
        .join(
            MCPServerVersion,
            and_(
                MCPServerVersion.name == MCPServerInstallation.server_name,
                MCPServerVersion.version == MCPServerInstallation.installed_version,
            ),
        )
        .where(
            MCPServerInstallation.server_name == server_name,
            MCPServerInstallation.status == "enabled",
        )
    )
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)
    result = await session.execute(statement)
    return result.one_or_none()
