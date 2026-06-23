from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_gateway import repository as gateway_repository
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry import tool_repository
from app.modules.mcp_runtime.manager import MCPRuntimeManager, get_runtime_manager
from app.modules.mcp_runtime.service import list_tools_with_tracking

SYSTEM_SCOPE_USER_ID = UUID(int=0)


@dataclass(frozen=True)
class MCPToolRefreshResult:
    server_name: str
    server_version: str
    tool_count: int


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
) -> MCPToolRefreshResult:
    manager = runtime_manager or get_runtime_manager()
    try:
        tools = manager.list_tools(installation)
    except NotImplementedError:
        tools = await list_tools_with_tracking(
            session,
            installation,
            server,
            manager=manager,
        )
    tool_count = await tool_repository.upsert_tool_schemas(
        session,
        installation=installation,
        server=server,
        tools=tools,
    )
    return MCPToolRefreshResult(
        server_name=server.name,
        server_version=server.version,
        tool_count=tool_count,
    )
