import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)


def tool_source_hash(tool: dict[str, Any]) -> str:
    payload = json.dumps(tool, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def search_enabled_tool_schemas(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID | None = None,
    server_name: str,
    search: str,
    offset: int,
    limit: int,
) -> tuple[list[MCPServerToolSchema], str]:
    statement = (
        select(MCPServerToolSchema)
        .join(
            MCPServerInstallation,
            and_(
                MCPServerInstallation.server_name == MCPServerToolSchema.server_name,
                MCPServerInstallation.installed_version == MCPServerToolSchema.server_version,
            ),
        )
        .where(
            MCPServerInstallation.status == "enabled",
            MCPServerToolSchema.is_active.is_(True),
        )
        .order_by(
            MCPServerToolSchema.server_name.asc(),
            MCPServerToolSchema.tool_name.asc(),
        )
    )
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)

    if server_name:
        statement = statement.where(MCPServerToolSchema.server_name == server_name)

    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                MCPServerToolSchema.server_name.ilike(pattern),
                MCPServerToolSchema.tool_name.ilike(pattern),
                MCPServerToolSchema.title.ilike(pattern),
                MCPServerToolSchema.description.ilike(pattern),
            )
        )

    result = await session.execute(statement.offset(offset).limit(limit + 1))
    tools = list(result.scalars().all())
    next_cursor = str(offset + limit) if len(tools) > limit else ""
    return tools[:limit], next_cursor


async def get_enabled_tool_schema(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID | None = None,
    server_name: str,
    tool_name: str,
) -> MCPServerToolSchema | None:
    statement = (
        select(MCPServerToolSchema)
        .join(
            MCPServerInstallation,
            and_(
                MCPServerInstallation.server_name == MCPServerToolSchema.server_name,
                MCPServerInstallation.installed_version == MCPServerToolSchema.server_version,
            ),
        )
        .where(
            MCPServerInstallation.status == "enabled",
            MCPServerToolSchema.server_name == server_name,
            MCPServerToolSchema.tool_name == tool_name,
            MCPServerToolSchema.is_active.is_(True),
        )
    )
    if workspace_id is not None:
        statement = statement.where(MCPServerInstallation.workspace_id == workspace_id)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def count_active_tool_schemas(
    session: AsyncSession,
    *,
    server_name: str,
    server_version: str,
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(MCPServerToolSchema)
        .where(
            MCPServerToolSchema.server_name == server_name,
            MCPServerToolSchema.server_version == server_version,
            MCPServerToolSchema.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def list_active_tool_schemas(
    session: AsyncSession,
    *,
    server_name: str,
    server_version: str,
) -> list[MCPServerToolSchema]:
    result = await session.execute(
        select(MCPServerToolSchema)
        .where(
            MCPServerToolSchema.server_name == server_name,
            MCPServerToolSchema.server_version == server_version,
            MCPServerToolSchema.is_active.is_(True),
        )
        .order_by(MCPServerToolSchema.tool_name.asc())
    )
    return list(result.scalars().all())


async def upsert_tool_schemas(
    session: AsyncSession,
    *,
    server: MCPServerVersion,
    tools: list[dict[str, Any]],
) -> int:
    now = datetime.now(UTC)
    seen_tool_names: set[str] = set()

    existing_result = await session.execute(
        select(MCPServerToolSchema).where(
            MCPServerToolSchema.server_name == server.name,
            MCPServerToolSchema.server_version == server.version,
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
