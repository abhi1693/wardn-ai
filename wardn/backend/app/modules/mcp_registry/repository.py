import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, func, literal_column, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.pagination import InvalidCursorError, decode_cursor, encode_cursor
from app.modules.mcp_registry.models import (
    MCPCatalogSource,
    MCPServerInstallation,
    MCPServerVersion,
)
from app.modules.organizations.models import Workspace

SYNC_QUERY_BATCH_SIZE = 500


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
    organization_id: uuid.UUID | None = None,
) -> MCPServerVersion | None:
    statement = _visible_query(include_deleted).where(MCPServerVersion.name == name)
    if organization_id is not None:
        statement = statement.where(MCPServerVersion.organization_id == organization_id)
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
    organization_id: uuid.UUID | None = None,
) -> list[MCPServerVersion]:
    statement = (
        _visible_query(include_deleted)
        .where(MCPServerVersion.name == name)
        .order_by(MCPServerVersion.published_at.desc(), MCPServerVersion.version.desc())
    )
    if organization_id is not None:
        statement = statement.where(MCPServerVersion.organization_id == organization_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_servers(
    session: AsyncSession,
    *,
    cursor: str | None,
    limit: int,
    include_deleted: bool,
    search: str | None = None,
    updated_since: datetime | None = None,
    version: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> tuple[list[MCPServerVersion], str]:
    statement = _visible_query(include_deleted or updated_since is not None)
    if organization_id is not None:
        statement = statement.where(MCPServerVersion.organization_id == organization_id)
    normalized_search = search.strip() if search else ""
    if normalized_search:
        statement = statement.where(
            MCPServerVersion.search_vector.op("@@")(
                func.websearch_to_tsquery(
                    literal_column("'simple'::regconfig"),
                    normalized_search,
                )
            )
        )
    if updated_since:
        statement = statement.where(MCPServerVersion.updated_at >= updated_since)
    if version == "latest" or version is None:
        statement = statement.where(MCPServerVersion.is_latest.is_(True))
    else:
        statement = statement.where(MCPServerVersion.version == version)

    statement = statement.order_by(
        MCPServerVersion.name.asc(),
        MCPServerVersion.version.asc(),
        MCPServerVersion.id.asc(),
    )
    cursor_values = decode_cursor(cursor, fields=3)
    if cursor_values is not None:
        after_name, after_version, after_id_value = cursor_values
        try:
            after_id = uuid.UUID(after_id_value)
        except ValueError as exc:
            raise InvalidCursorError("invalid cursor") from exc
        statement = statement.where(
            tuple_(
                MCPServerVersion.name,
                MCPServerVersion.version,
                MCPServerVersion.id,
            )
            > tuple_(after_name, after_version, after_id)
        )
    result = await session.execute(statement.limit(limit + 1))
    rows = list(result.scalars().all())
    page = rows[:limit]
    next_cursor = ""
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = encode_cursor(last.name, last.version, str(last.id))
    return page, next_cursor


async def count_versions_for_name(
    session: AsyncSession,
    name: str,
    organization_id: uuid.UUID | None = None,
) -> int:
    statement = (
        select(func.count())
        .select_from(MCPServerVersion)
        .where(MCPServerVersion.name == name)
    )
    if organization_id is not None:
        statement = statement.where(MCPServerVersion.organization_id == organization_id)
    result = await session.execute(statement)
    return result.scalar_one()


async def count_server_versions_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(MCPServerVersion).where(
            MCPServerVersion.organization_id == organization_id,
            MCPServerVersion.status != "deleted",
        )
    )
    return int(result.scalar_one())


async def get_latest_visible_version(
    session: AsyncSession,
    name: str,
    organization_id: uuid.UUID | None = None,
) -> MCPServerVersion | None:
    statement = (
        _visible_query(False)
        .where(MCPServerVersion.name == name)
        .order_by(MCPServerVersion.published_at.desc(), MCPServerVersion.version.desc())
        .limit(1)
    )
    if organization_id is not None:
        statement = statement.where(MCPServerVersion.organization_id == organization_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def list_server_versions_for_catalog_source(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    source_id: uuid.UUID,
) -> list[MCPServerVersion]:
    statement = _visible_query(False).where(
        MCPServerVersion.organization_id == organization_id,
        MCPServerVersion.catalog_source_id == source_id,
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_legacy_catalog_server_versions(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
) -> list[MCPServerVersion]:
    statement = _visible_query(False).where(
        MCPServerVersion.organization_id == organization_id,
        MCPServerVersion.catalog_source_id.is_(None),
        or_(
            MCPServerVersion.server_json.contains(
                {"_meta": {"io.modelcontextprotocol.registry/official": {}}}
            ),
            MCPServerVersion.server_json.contains(
                {"_meta": {"com.pulsemcp/server-version": {}}}
            ),
        ),
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def clear_latest_for_name(
    session: AsyncSession,
    name: str,
    organization_id: uuid.UUID | None = None,
) -> None:
    statement = update(MCPServerVersion).where(MCPServerVersion.name == name)
    if organization_id is not None:
        statement = statement.where(MCPServerVersion.organization_id == organization_id)
    await session.execute(statement.values(is_latest=False))


async def clear_latest_for_names(
    session: AsyncSession,
    names: set[str],
    *,
    organization_id: uuid.UUID,
) -> None:
    if not names:
        return
    ordered_names = sorted(names)
    for start in range(0, len(ordered_names), SYNC_QUERY_BATCH_SIZE):
        await session.execute(
            update(MCPServerVersion)
            .where(
                MCPServerVersion.organization_id == organization_id,
                MCPServerVersion.name.in_(
                    ordered_names[start : start + SYNC_QUERY_BATCH_SIZE]
                ),
                MCPServerVersion.is_latest.is_(True),
            )
            .values(is_latest=False)
        )


async def get_server_version_statuses(
    session: AsyncSession,
    keys: set[tuple[str, str]],
    *,
    organization_id: uuid.UUID,
) -> dict[tuple[str, str], str]:
    if not keys:
        return {}
    statuses: dict[tuple[str, str], str] = {}
    ordered_keys = sorted(keys)
    for start in range(0, len(ordered_keys), SYNC_QUERY_BATCH_SIZE):
        result = await session.execute(
            select(
                MCPServerVersion.name,
                MCPServerVersion.version,
                MCPServerVersion.status,
            ).where(
                MCPServerVersion.organization_id == organization_id,
                tuple_(MCPServerVersion.name, MCPServerVersion.version).in_(
                    ordered_keys[start : start + SYNC_QUERY_BATCH_SIZE]
                ),
            )
        )
        statuses.update(
            {(name, version): status for name, version, status in result.all()}
        )
    return statuses


def bulk_upsert_server_versions_statement(
    rows: list[dict[str, Any]],
    *,
    update_published_metadata: bool,
):
    statement = postgresql_insert(MCPServerVersion).values(rows)
    excluded = statement.excluded
    update_values = {
        "catalog_source_id": excluded.catalog_source_id,
        "title": excluded.title,
        "description": excluded.description,
        "website_url": excluded.website_url,
        "repository": excluded.repository,
        "packages": excluded.packages,
        "remotes": excluded.remotes,
        "icons": excluded.icons,
        "server_json": excluded.server_json,
        "status": excluded.status,
        "status_message": excluded.status_message,
        "is_latest": excluded.is_latest,
        "updated_at": func.now(),
    }
    if update_published_metadata:
        update_values.update(
            published_at=excluded.published_at,
            status_changed_at=excluded.status_changed_at,
        )
    return statement.on_conflict_do_update(
        constraint="uq_mcp_server_versions_org_name_version",
        set_=update_values,
    )


async def bulk_upsert_server_versions(
    session: AsyncSession,
    rows: list[dict[str, Any]],
    *,
    update_published_metadata: bool,
) -> None:
    if not rows:
        return
    for start in range(0, len(rows), SYNC_QUERY_BATCH_SIZE):
        await session.execute(
            bulk_upsert_server_versions_statement(
                rows[start : start + SYNC_QUERY_BATCH_SIZE],
                update_published_metadata=update_published_metadata,
            )
        )


async def get_installation(
    session: AsyncSession,
    server_name: str,
    config_name: str = "default",
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallation | None:
    statement = select(MCPServerInstallation).where(
        MCPServerInstallation.server_name == server_name,
        MCPServerInstallation.config_name == config_name,
    )
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_installation_by_id(
    session: AsyncSession,
    installation_id,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallation | None:
    statement = select(MCPServerInstallation).where(MCPServerInstallation.id == installation_id)
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_first_installation_for_server(
    session: AsyncSession,
    server_name: str,
    workspace_id: uuid.UUID | None = None,
) -> MCPServerInstallation | None:
    statement = (
        select(MCPServerInstallation)
        .where(MCPServerInstallation.server_name == server_name)
        .order_by(MCPServerInstallation.config_name.asc())
        .limit(1)
    )
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def list_installations_for_server(
    session: AsyncSession,
    server_name: str,
    workspace_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
) -> list[MCPServerInstallation]:
    statement = (
        select(MCPServerInstallation)
        .where(MCPServerInstallation.server_name == server_name)
        .order_by(MCPServerInstallation.config_name.asc())
    )
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)
    if organization_id is not None:
        statement = statement.join(
            Workspace,
            Workspace.id == MCPServerInstallation.workspace_id,
        ).where(
            Workspace.organization_id == organization_id,
        )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_installations(
    session: AsyncSession,
    workspace_id: uuid.UUID | None = None,
) -> list[MCPServerInstallation]:
    statement = (
        select(MCPServerInstallation).order_by(
            MCPServerInstallation.server_name.asc(),
            MCPServerInstallation.config_name.asc(),
        )
    )
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


async def list_installation_version_rows(
    session: AsyncSession,
    workspace_id: uuid.UUID | None = None,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[
    list[tuple[MCPServerInstallation, MCPServerVersion, MCPServerVersion]],
    str,
]:
    installed_version = aliased(MCPServerVersion, name="installed_version")
    latest_version = aliased(MCPServerVersion, name="latest_version")
    statement = (
        select(MCPServerInstallation, installed_version, latest_version)
        .join(Workspace, Workspace.id == MCPServerInstallation.workspace_id)
        .join(
            installed_version,
            (installed_version.organization_id == Workspace.organization_id)
            & (installed_version.name == MCPServerInstallation.server_name)
            & (installed_version.version == MCPServerInstallation.installed_version),
        )
        .join(
            latest_version,
            (latest_version.organization_id == Workspace.organization_id)
            & (latest_version.name == MCPServerInstallation.server_name)
            & latest_version.is_latest.is_(True)
            & (latest_version.status != "deleted"),
        )
        .order_by(
            MCPServerInstallation.server_name.asc(),
            MCPServerInstallation.config_name.asc(),
            MCPServerInstallation.id.asc(),
        )
    )
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)
    cursor_values = decode_cursor(cursor, fields=3)
    if cursor_values is not None:
        after_server_name, after_config_name, after_id_value = cursor_values
        try:
            after_id = uuid.UUID(after_id_value)
        except ValueError as exc:
            raise InvalidCursorError("invalid cursor") from exc
        statement = statement.where(
            or_(
                MCPServerInstallation.server_name > after_server_name,
                and_(
                    MCPServerInstallation.server_name == after_server_name,
                    MCPServerInstallation.config_name > after_config_name,
                ),
                and_(
                    MCPServerInstallation.server_name == after_server_name,
                    MCPServerInstallation.config_name == after_config_name,
                    MCPServerInstallation.id > after_id,
                ),
            )
        )
    result = await session.execute(statement.limit(limit + 1))
    rows = [
        (installation, installed, latest)
        for installation, installed, latest in result.all()
    ]
    page = rows[:limit]
    next_cursor = ""
    if len(rows) > limit and page:
        last_installation = page[-1][0]
        next_cursor = encode_cursor(
            last_installation.server_name,
            last_installation.config_name,
            str(last_installation.id),
        )
    return page, next_cursor


async def count_installations_for_workspace(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(MCPServerInstallation).where(
            MCPServerInstallation.workspace_id == workspace_id,
        )
    )
    return int(result.scalar_one())


async def delete_installation(session: AsyncSession, installation: MCPServerInstallation) -> None:
    await session.delete(installation)


async def list_catalog_sources(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> list[MCPCatalogSource]:
    statement = (
        select(MCPCatalogSource)
        .where(MCPCatalogSource.organization_id == organization_id)
        .order_by(MCPCatalogSource.name.asc())
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def count_catalog_sources_for_organization(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.count()).select_from(MCPCatalogSource).where(
            MCPCatalogSource.organization_id == organization_id,
        )
    )
    return int(result.scalar_one())


async def get_catalog_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    organization_id: uuid.UUID,
) -> MCPCatalogSource | None:
    statement = select(MCPCatalogSource).where(
        MCPCatalogSource.id == source_id,
        MCPCatalogSource.organization_id == organization_id,
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_catalog_source_by_name(
    session: AsyncSession,
    organization_id: uuid.UUID,
    name: str,
) -> MCPCatalogSource | None:
    statement = select(MCPCatalogSource).where(
        MCPCatalogSource.organization_id == organization_id,
        MCPCatalogSource.name == name,
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_catalog_source_by_url(
    session: AsyncSession,
    organization_id: uuid.UUID,
    base_url: str,
) -> MCPCatalogSource | None:
    statement = select(MCPCatalogSource).where(
        MCPCatalogSource.organization_id == organization_id,
        MCPCatalogSource.base_url == base_url,
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()
