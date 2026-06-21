from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_gateway import repository as gateway_repository
from app.modules.mcp_registry import tool_repository
from app.modules.mcp_runtime.manager import MCPRuntimeManager, get_runtime_manager


@dataclass(frozen=True)
class MCPToolRefreshResult:
    server_name: str
    server_version: str
    tool_count: int


async def refresh_tool_schemas(
    session: AsyncSession,
    server_name: str,
    *,
    runtime_manager: MCPRuntimeManager | None = None,
) -> MCPToolRefreshResult:
    row = await gateway_repository.get_enabled_installation(session, server_name)
    if row is None:
        raise LookupError("enabled MCP server was not found")

    installation, server = row
    manager = runtime_manager or get_runtime_manager()
    tools = manager.list_tools(installation)
    tool_count = await tool_repository.upsert_tool_schemas(
        session,
        server=server,
        tools=tools,
    )
    return MCPToolRefreshResult(
        server_name=server.name,
        server_version=server.version,
        tool_count=tool_count,
    )
