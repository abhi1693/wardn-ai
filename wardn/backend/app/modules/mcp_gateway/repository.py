import uuid

from sqlalchemy import and_, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import InvalidCursorError, decode_cursor, encode_cursor
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion
from app.modules.organizations.models import (
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)

ADMIN_ROLES = ("owner", "admin")


def apply_gateway_scope(statement, scope: GatewayScope, *, workspace_joined: bool = False):
    joined_workspace = workspace_joined

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
    cursor: str | None,
    limit: int,
) -> tuple[list[tuple[MCPServerInstallation, MCPServerVersion]], str]:
    statement = (
        select(MCPServerInstallation, MCPServerVersion)
        .join(Workspace, Workspace.id == MCPServerInstallation.workspace_id)
        .join(
            MCPServerVersion,
            and_(
                MCPServerVersion.name == MCPServerInstallation.server_name,
                MCPServerVersion.version == MCPServerInstallation.installed_version,
                MCPServerVersion.organization_id == Workspace.organization_id,
            ),
        )
        .where(MCPServerInstallation.status == "enabled")
        .order_by(
            MCPServerInstallation.server_name.asc(),
            MCPServerInstallation.id.asc(),
        )
    )
    statement = apply_gateway_scope(statement, scope, workspace_joined=True)

    if search:
        statement = statement.where(
            MCPServerVersion.search_vector.op("@@")(
                func.websearch_to_tsquery(
                    literal_column("'simple'::regconfig"),
                    search.strip(),
                )
            )
        )

    try:
        cursor_values = decode_cursor(cursor, fields=2)
    except InvalidCursorError as exc:
        raise ValueError("invalid cursor") from exc
    if cursor_values is not None:
        after_name, after_id_value = cursor_values
        try:
            after_id = uuid.UUID(after_id_value)
        except ValueError as exc:
            raise ValueError("invalid cursor") from exc
        statement = statement.where(
            or_(
                MCPServerInstallation.server_name > after_name,
                and_(
                    MCPServerInstallation.server_name == after_name,
                    MCPServerInstallation.id > after_id,
                ),
            )
        )
    result = await session.execute(statement.limit(limit + 1))
    rows = [(row[0], row[1]) for row in result.all()]
    page = rows[:limit]
    next_cursor = ""
    if len(rows) > limit and page:
        last_installation = page[-1][0]
        next_cursor = encode_cursor(
            last_installation.server_name,
            str(last_installation.id),
        )
    return page, next_cursor


async def get_enabled_installation(
    session: AsyncSession,
    server_name: str,
    *,
    scope: GatewayScope,
    installation_id: uuid.UUID | None = None,
) -> tuple[MCPServerInstallation, MCPServerVersion] | None:
    statement = (
        select(MCPServerInstallation, MCPServerVersion)
        .join(Workspace, Workspace.id == MCPServerInstallation.workspace_id)
        .join(
            MCPServerVersion,
            and_(
                MCPServerVersion.name == MCPServerInstallation.server_name,
                MCPServerVersion.version == MCPServerInstallation.installed_version,
                MCPServerVersion.organization_id == Workspace.organization_id,
            ),
        )
        .where(
            MCPServerInstallation.server_name == server_name,
            MCPServerInstallation.status == "enabled",
        )
    )
    if installation_id is not None:
        statement = statement.where(MCPServerInstallation.id == installation_id)
    statement = apply_gateway_scope(statement, scope, workspace_joined=True)
    result = await session.execute(statement)
    rows = result.all()
    if len(rows) > 1:
        raise LookupError("enabled MCP server is ambiguous; pass installationId")
    return (rows[0][0], rows[0][1]) if rows else None
