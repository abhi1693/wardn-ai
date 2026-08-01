from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.modules.mcp_gateway import repository as gateway_repository
from app.modules.mcp_gateway.client import MCPGatewayUnsupportedMethodError
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry import tool_repository
from app.modules.mcp_registry.hub_tool_proposals import (
    normalized_tools_from_server_json,
    queue_mcp_hub_tool_inventory_proposal,
    server_json_targets_installed_version,
)
from app.modules.mcp_registry.telemetry import hub_source_metadata
from app.modules.mcp_runtime.manager import MCPRuntimeManager, get_runtime_manager
from app.modules.mcp_runtime.service import has_secret_handle_refs, list_tools_with_tracking

SYSTEM_SCOPE_USER_ID = UUID(int=0)


@dataclass(frozen=True)
class MCPToolRefreshResult:
    server_name: str
    server_version: str
    tool_count: int
    source: str = "live-refresh"


async def refresh_tool_schemas(
    session: AsyncSession,
    server_name: str,
    *,
    workspace_id=None,
    runtime_manager: MCPRuntimeManager | None = None,
) -> MCPToolRefreshResult:
    row = await gateway_repository.get_enabled_installation(
        session,
        server_name,
        scope=GatewayScope(
            user_id=SYSTEM_SCOPE_USER_ID,
            is_superuser=True,
            workspace_id=workspace_id,
        ),
    )
    if row is None:
        raise LookupError("enabled MCP server was not found")

    installation, server = row
    return await refresh_tool_schemas_for_installation(
        session,
        installation=installation,
        server=server,
        runtime_manager=runtime_manager,
    )


async def refresh_tool_schemas_for_installation(
    session: AsyncSession,
    *,
    installation,
    server,
    runtime_manager: MCPRuntimeManager | None = None,
    prefer_registry_metadata: bool = True,
) -> MCPToolRefreshResult:
    if prefer_registry_metadata:
        registry_result = await seed_tool_schemas_from_registry_metadata(
            session,
            installation=installation,
            server=server,
        )
        if registry_result is not None:
            return registry_result

    manager = runtime_manager or get_runtime_manager()
    try:
        if has_secret_handle_refs(installation.secret_references):
            tools = await list_tools_with_tracking(
                session,
                installation,
                server,
                manager=manager,
            )
        else:
            try:
                await session.commit()
                tools = await run_in_threadpool(manager.list_tools, installation)
            except NotImplementedError:
                tools = await list_tools_with_tracking(
                    session,
                    installation,
                    server,
                    manager=manager,
                )
    except MCPGatewayUnsupportedMethodError:
        tools = []
    tool_count = await tool_repository.upsert_tool_schemas(
        session,
        installation=installation,
        server=server,
        tools=tools,
    )
    queue_mcp_hub_tool_inventory_proposal(
        session,
        installation=installation,
        server=server,
        tools=tools,
    )
    return MCPToolRefreshResult(
        server_name=server.name,
        server_version=server.version,
        tool_count=tool_count,
        source="live-refresh",
    )


async def seed_tool_schemas_from_registry_metadata(
    session: AsyncSession,
    *,
    installation,
    server,
) -> MCPToolRefreshResult | None:
    if (
        str(installation.server_name or "").strip() != server.name
        or str(installation.installed_version or "").strip() != server.version
        or not server_json_targets_installed_version(server)
    ):
        return None

    tools = normalized_tools_from_server_json(server.server_json)
    if not tools:
        return None

    tool_count = await tool_repository.upsert_tool_schemas(
        session,
        installation=installation,
        server=server,
        tools=tools,
    )
    source = "hub-metadata" if hub_source_metadata(server) is not None else "registry-metadata"
    return MCPToolRefreshResult(
        server_name=server.name,
        server_version=server.version,
        tool_count=tool_count,
        source=source,
    )
