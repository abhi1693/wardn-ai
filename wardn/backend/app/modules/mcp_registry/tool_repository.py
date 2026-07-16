import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import InvalidCursorError, decode_cursor, encode_cursor
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.organizations.models import (
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)

ADMIN_ROLES = ("owner", "admin")


def tool_source_hash(tool: dict[str, Any]) -> str:
    payload = json.dumps(tool, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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

    statement = statement.join(
        MCPServerInstallation,
        MCPServerInstallation.id == MCPServerToolSchema.installation_id,
    ).where(MCPServerInstallation.status == "enabled")

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


async def search_enabled_tool_schemas(
    session: AsyncSession,
    *,
    scope: GatewayScope,
    server_name: str,
    search: str,
    cursor: str | None,
    limit: int,
) -> tuple[list[MCPServerToolSchema], str]:
    statement = select(MCPServerToolSchema).where(MCPServerToolSchema.is_active.is_(True))
    statement = apply_gateway_scope(statement, scope)

    statement = statement.order_by(
        MCPServerToolSchema.server_name.asc(),
        MCPServerToolSchema.tool_name.asc(),
        MCPServerToolSchema.id.asc(),
    )

    if server_name:
        statement = statement.where(MCPServerToolSchema.server_name == server_name)

    if search:
        statement = statement.where(
            MCPServerToolSchema.search_vector.op("@@")(
                func.websearch_to_tsquery(
                    literal_column("'simple'::regconfig"),
                    search.strip(),
                )
            )
        )

    try:
        cursor_values = decode_cursor(cursor, fields=3)
    except InvalidCursorError as exc:
        raise ValueError("invalid cursor") from exc
    if cursor_values is not None:
        after_server_name, after_tool_name, after_id_value = cursor_values
        try:
            after_id = uuid.UUID(after_id_value)
        except ValueError as exc:
            raise ValueError("invalid cursor") from exc
        statement = statement.where(
            or_(
                MCPServerToolSchema.server_name > after_server_name,
                and_(
                    MCPServerToolSchema.server_name == after_server_name,
                    MCPServerToolSchema.tool_name > after_tool_name,
                ),
                and_(
                    MCPServerToolSchema.server_name == after_server_name,
                    MCPServerToolSchema.tool_name == after_tool_name,
                    MCPServerToolSchema.id > after_id,
                ),
            )
        )
    result = await session.execute(statement.limit(limit + 1))
    tools = list(result.scalars().all())
    page = tools[:limit]
    next_cursor = ""
    if len(tools) > limit and page:
        last_tool = page[-1]
        next_cursor = encode_cursor(
            last_tool.server_name,
            last_tool.tool_name,
            str(last_tool.id),
        )
    return page, next_cursor


async def get_enabled_tool_schema(
    session: AsyncSession,
    *,
    scope: GatewayScope,
    installation_id: uuid.UUID | None = None,
    server_name: str,
    tool_name: str,
) -> MCPServerToolSchema | None:
    statement = select(MCPServerToolSchema).where(
        MCPServerToolSchema.server_name == server_name,
        MCPServerToolSchema.tool_name == tool_name,
        MCPServerToolSchema.is_active.is_(True),
    )
    if installation_id is not None:
        statement = statement.where(MCPServerToolSchema.installation_id == installation_id)
    statement = apply_gateway_scope(statement, scope)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def count_active_tool_schemas(
    session: AsyncSession,
    *,
    installation_id: uuid.UUID | None = None,
    server_name: str,
    server_version: str,
) -> int:
    statement = (
        select(func.count())
        .select_from(MCPServerToolSchema)
        .where(MCPServerToolSchema.is_active.is_(True))
    )
    if installation_id is not None:
        statement = statement.where(MCPServerToolSchema.installation_id == installation_id)
    else:
        statement = statement.where(
            MCPServerToolSchema.server_name == server_name,
            MCPServerToolSchema.server_version == server_version,
        )
    result = await session.execute(statement)
    return int(result.scalar_one())


async def list_active_tool_schemas(
    session: AsyncSession,
    *,
    installation_id: uuid.UUID | None = None,
    server_name: str,
    server_version: str,
) -> list[MCPServerToolSchema]:
    statement = select(MCPServerToolSchema).where(MCPServerToolSchema.is_active.is_(True))
    if installation_id is not None:
        statement = statement.where(MCPServerToolSchema.installation_id == installation_id)
    else:
        statement = statement.where(
            MCPServerToolSchema.server_name == server_name,
            MCPServerToolSchema.server_version == server_version,
        )
    result = await session.execute(statement.order_by(MCPServerToolSchema.tool_name.asc()))
    return list(result.scalars().all())


async def upsert_tool_schemas(
    session: AsyncSession,
    *,
    installation: MCPServerInstallation,
    server: MCPServerVersion,
    tools: list[dict[str, Any]],
) -> int:
    now = datetime.now(UTC)
    seen_tool_names: set[str] = set()

    existing_result = await session.execute(
        select(MCPServerToolSchema).where(
            MCPServerToolSchema.installation_id == installation.id,
        )
    )
    existing = {tool.tool_name: tool for tool in existing_result.scalars()}

    for raw_tool in tools:
        tool_name = str(raw_tool.get("name") or "").strip()
        if not tool_name:
            continue
        seen_tool_names.add(tool_name)
        title = str(raw_tool.get("title") or raw_tool.get("name") or "")
        description = str(raw_tool.get("description") or "")
        input_schema = raw_tool.get("inputSchema")
        output_schema = raw_tool.get("outputSchema")
        annotations = raw_tool.get("annotations")
        values = {
            "workspace_id": installation.workspace_id,
            "installation_id": installation.id,
            "title": title,
            "description": description,
            "input_schema": input_schema if isinstance(input_schema, dict) else {"type": "object"},
            "output_schema": output_schema if isinstance(output_schema, dict) else None,
            "annotations": annotations if isinstance(annotations, dict) else {},
            "source_hash": tool_source_hash(raw_tool),
            "is_active": True,
            "last_seen_at": now,
        }

        if tool_name in existing:
            cached_tool = existing[tool_name]
            for key, value in values.items():
                setattr(cached_tool, key, value)
        else:
            session.add(
                MCPServerToolSchema(
                    server_name=server.name,
                    server_version=server.version,
                    tool_name=tool_name,
                    discovered_at=now,
                    **values,
                )
            )

    for tool_name, cached_tool in existing.items():
        if tool_name not in seen_tool_names:
            cached_tool.is_active = False

    await session.flush()
    return len(seen_tool_names)
