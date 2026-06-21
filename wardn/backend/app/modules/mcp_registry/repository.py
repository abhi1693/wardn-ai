from datetime import datetime

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion


def _visible_query(include_deleted: bool) -> Select[tuple[MCPServerVersion]]:
    statement = select(MCPServerVersion)
    if not include_deleted:
        statement = statement.where(MCPServerVersion.status != "deleted")
    return statement


async def get_server_version(
    session: AsyncSession,
    name: str,
    version: str,
    *,
    include_deleted: bool = False,
) -> MCPServerVersion | None:
    statement = _visible_query(include_deleted).where(MCPServerVersion.name == name)
    if version == "latest":
        statement = statement.where(MCPServerVersion.is_latest.is_(True))
    else:
        statement = statement.where(MCPServerVersion.version == version)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def list_server_versions(
    session: AsyncSession,
    name: str,
    *,
    include_deleted: bool = False,
) -> list[MCPServerVersion]:
    statement = (
        _visible_query(include_deleted)
        .where(MCPServerVersion.name == name)
        .order_by(MCPServerVersion.published_at.desc(), MCPServerVersion.version.desc())
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_servers(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    include_deleted: bool,
    search: str | None = None,
    updated_since: datetime | None = None,
    version: str | None = None,
) -> tuple[list[MCPServerVersion], str]:
    statement = _visible_query(include_deleted or updated_since is not None)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                MCPServerVersion.name.ilike(pattern),
                MCPServerVersion.title.ilike(pattern),
                MCPServerVersion.description.ilike(pattern),
            )
        )
    if updated_since:
        statement = statement.where(MCPServerVersion.updated_at >= updated_since)
    if version == "latest" or version is None:
        statement = statement.where(MCPServerVersion.is_latest.is_(True))
    else:
        statement = statement.where(MCPServerVersion.version == version)

    statement = statement.order_by(MCPServerVersion.name.asc(), MCPServerVersion.version.asc())
    result = await session.execute(statement.offset(offset).limit(limit + 1))
    rows = list(result.scalars().all())
    next_cursor = str(offset + limit) if len(rows) > limit else ""
    return rows[:limit], next_cursor


async def count_versions_for_name(session: AsyncSession, name: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(MCPServerVersion).where(MCPServerVersion.name == name)
    )
    return result.scalar_one()


async def get_latest_visible_version(
    session: AsyncSession,
    name: str,
) -> MCPServerVersion | None:
    result = await session.execute(
        _visible_query(False)
        .where(MCPServerVersion.name == name)
        .order_by(MCPServerVersion.published_at.desc(), MCPServerVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def clear_latest_for_name(session: AsyncSession, name: str) -> None:
    await session.execute(
        update(MCPServerVersion)
        .where(MCPServerVersion.name == name)
        .values(is_latest=False)
    )


async def get_installation(
    session: AsyncSession,
    server_name: str,
    config_name: str = "default",
) -> MCPServerInstallation | None:
    result = await session.execute(
        select(MCPServerInstallation).where(
            MCPServerInstallation.server_name == server_name,
            MCPServerInstallation.config_name == config_name,
        )
    )
    return result.scalar_one_or_none()


async def get_installation_by_id(
    session: AsyncSession,
    installation_id,
) -> MCPServerInstallation | None:
    result = await session.execute(
        select(MCPServerInstallation).where(MCPServerInstallation.id == installation_id)
    )
    return result.scalar_one_or_none()


async def get_first_installation_for_server(
    session: AsyncSession,
    server_name: str,
) -> MCPServerInstallation | None:
    result = await session.execute(
        select(MCPServerInstallation)
        .where(MCPServerInstallation.server_name == server_name)
        .order_by(MCPServerInstallation.config_name.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_installations_for_server(
    session: AsyncSession,
    server_name: str,
) -> list[MCPServerInstallation]:
    result = await session.execute(
        select(MCPServerInstallation)
        .where(MCPServerInstallation.server_name == server_name)
        .order_by(MCPServerInstallation.config_name.asc())
    )
    return list(result.scalars().all())


async def list_installations(session: AsyncSession) -> list[MCPServerInstallation]:
    result = await session.execute(
        select(MCPServerInstallation).order_by(
            MCPServerInstallation.server_name.asc(),
            MCPServerInstallation.config_name.asc(),
        )
    )
    return list(result.scalars().all())


async def delete_installation(session: AsyncSession, installation: MCPServerInstallation) -> None:
    await session.delete(installation)
