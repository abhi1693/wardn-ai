import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.organizations.models import (
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)

ADMIN_ROLES = ("owner", "admin")


def apply_gateway_scope(statement, scope: GatewayScope):
    joined_workspace = False

    def ensure_workspace_join(current_statement):
        nonlocal joined_workspace
        if joined_workspace:
            return current_statement
        joined_workspace = True
        return current_statement.join(
            Workspace,
            Workspace.id == MCPServerInstallation.workspace_id,
        )

    if scope.workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == scope.workspace_id)
    if scope.organization_id is not None:
        statement = ensure_workspace_join(statement).where(
            Workspace.organization_id == scope.organization_id
        )

    token_scope_conditions = []
    if scope.workspace_ids is not None:
        token_scope_conditions.append(MCPServerInstallation.workspace_id.in_(scope.workspace_ids))
    if scope.organization_ids is not None:
        statement = ensure_workspace_join(statement)
        token_scope_conditions.append(Workspace.organization_id.in_(scope.organization_ids))
    if token_scope_conditions:
        statement = statement.where(or_(*token_scope_conditions))

    if scope.is_superuser:
        return statement
    return (
        ensure_workspace_join(statement)
        .outerjoin(
            OrganizationMembership,
            and_(
                OrganizationMembership.organization_id == Workspace.organization_id,
                OrganizationMembership.user_id == scope.user_id,
                OrganizationMembership.is_active.is_(True),
            ),
        )
        .outerjoin(
            WorkspaceMembership,
            and_(
                WorkspaceMembership.workspace_id == Workspace.id,
                WorkspaceMembership.user_id == scope.user_id,
                WorkspaceMembership.is_active.is_(True),
            ),
        )
        .where(
            or_(
                OrganizationMembership.role.in_(ADMIN_ROLES),
                WorkspaceMembership.id.is_not(None),
            )
        )
    )


async def search_enabled_installations(
    session: AsyncSession,
    *,
    scope: GatewayScope,
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
    statement = apply_gateway_scope(statement, scope)

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
    *,
    scope: GatewayScope,
    installation_id: uuid.UUID | None = None,
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
    if installation_id is not None:
        statement = statement.where(MCPServerInstallation.id == installation_id)
    statement = apply_gateway_scope(statement, scope)
    result = await session.execute(statement)
    rows = result.all()
    if len(rows) > 1:
        raise LookupError("enabled MCP server is ambiguous; pass installationId")
    return rows[0] if rows else None
