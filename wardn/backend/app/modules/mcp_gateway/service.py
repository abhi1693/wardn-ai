import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_gateway import repository
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry import tool_repository
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.mcp_registry.tool_service import refresh_tool_schemas
from app.modules.mcp_runtime.manager import runtime_kind
from app.modules.mcp_runtime.service import call_tool_with_tracking

PROTOCOL_VERSION = "2025-06-18"
MAX_SEARCH_LIMIT = 25


def parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise ValueError("invalid cursor") from exc
    if offset < 0:
        raise ValueError("invalid cursor")
    return offset


def bounded_limit(value: Any, *, default: int = 10) -> int:
    if value is None:
        return default
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be a number") from exc
    if limit < 1:
        raise ValueError("limit must be greater than 0")
    return min(limit, MAX_SEARCH_LIMIT)


def input_counts(server: MCPServerVersion) -> dict[str, int]:
    headers = [
        item
        for remote in server.remotes or []
        for item in remote.get("headers", [])
        if isinstance(item, dict)
    ]
    environment = [
        item
        for package in server.packages or []
        for item in package.get("environmentVariables", [])
        if isinstance(item, dict)
    ]
    arguments = [
        item
        for package in server.packages or []
        for item in package.get("packageArguments", [])
        if isinstance(item, dict)
    ]
    inputs = [*headers, *environment, *arguments]
    return {
        "total": len(inputs),
        "required": sum(1 for item in inputs if item.get("isRequired")),
        "secret": sum(1 for item in inputs if item.get("isSecret")),
    }


def server_summary(
    installation: MCPServerInstallation,
    server: MCPServerVersion,
) -> dict[str, Any]:
    return {
        "serverName": server.name,
        "title": server.title or server.name,
        "description": server.description,
        "version": server.version,
        "runtime": runtime_kind(installation),
        "status": installation.status,
        "inputCounts": input_counts(server),
    }


def server_detail(
    installation: MCPServerInstallation,
    server: MCPServerVersion,
) -> dict[str, Any]:
    runtime_config = installation.runtime_config or {}
    return {
        **server_summary(installation, server),
        "installedAt": installation.installed_at.isoformat() if installation.installed_at else "",
        "transport": runtime_config.get("transport", {}),
        "package": runtime_config.get("package", {}),
        "verification": runtime_config.get("verification", {}),
        "source": {
            "websiteUrl": server.website_url,
            "repository": server.repository,
        },
    }


def cached_tool_summary(tool: MCPServerToolSchema) -> dict[str, Any]:
    return {
        "serverName": tool.server_name,
        "toolName": tool.tool_name,
        "title": tool.title or tool.tool_name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
    }


def text_tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, separators=(",", ":"), sort_keys=True),
            }
        ],
        "structuredContent": payload,
        "isError": False,
    }


def error_tool_result(message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    structured_content = payload or {}
    return {
        "content": [
            {
                "type": "text",
                "text": message,
            }
        ],
        "structuredContent": structured_content,
        "isError": True,
    }


def gateway_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_mcp_servers",
            "title": "Search enabled MCP servers",
            "description": (
                "Search Wardn's enabled MCP servers. Use this first instead of listing every "
                "server; results are paginated and intentionally compact."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional search text matched against server name, title, "
                            "and description."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                        "default": 10,
                    },
                    "cursor": {
                        "type": "string",
                        "description": "Cursor returned by a previous search_mcp_servers call.",
                    },
                },
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "servers": {"type": "array"},
                    "nextCursor": {"type": "string"},
                },
                "required": ["servers", "nextCursor"],
            },
        },
        {
            "name": "get_mcp_server",
            "title": "Get MCP server details",
            "description": (
                "Fetch detailed metadata for one enabled MCP server by canonical server name."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "serverName": {
                        "type": "string",
                        "description": "Canonical MCP server name, for example namespace/server.",
                    }
                },
                "required": ["serverName"],
            },
        },
        {
            "name": "search_mcp_tools",
            "title": "Search enabled MCP tools",
            "description": (
                "Search tools exposed by enabled MCP servers. Provide serverName after "
                "search_mcp_servers when possible; otherwise Wardn scans only a small "
                "bounded set of matching servers."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "serverName": {
                        "type": "string",
                        "description": "Optional canonical MCP server name to search within.",
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional search text matched against tool name, title, "
                            "and description."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                        "default": 10,
                    },
                },
            },
        },
        {
            "name": "get_mcp_tool",
            "title": "Get MCP tool details",
            "description": "Fetch the schema for one tool from one enabled MCP server.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "serverName": {"type": "string"},
                    "toolName": {"type": "string"},
                },
                "required": ["serverName", "toolName"],
            },
        },
        {
            "name": "run_mcp_tool",
            "title": "Run MCP tool",
            "description": "Invoke one selected tool on one enabled MCP server.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "serverName": {"type": "string"},
                    "toolName": {"type": "string"},
                    "arguments": {
                        "type": "object",
                        "description": "Tool arguments matching the tool input schema.",
                    },
                },
                "required": ["serverName", "toolName"],
            },
        },
    ]


async def search_mcp_servers(session: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    offset = parse_cursor(arguments.get("cursor"))
    limit = bounded_limit(arguments.get("limit"))
    query = str(arguments.get("query") or "").strip()
    rows, next_cursor = await repository.search_enabled_installations(
        session,
        search=query,
        offset=offset,
        limit=limit,
    )
    return text_tool_result(
        {
            "servers": [
                server_summary(installation, server)
                for installation, server in rows
            ],
            "nextCursor": next_cursor,
        }
    )


async def get_mcp_server(session: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    server_name = str(arguments.get("serverName") or "").strip()
    if not server_name:
        raise ValueError("serverName is required")
    row = await repository.get_enabled_installation(session, server_name)
    if row is None:
        raise LookupError("enabled MCP server was not found")
    installation, server = row
    return text_tool_result({"server": server_detail(installation, server)})


async def search_mcp_tools(session: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    offset = parse_cursor(arguments.get("cursor"))
    limit = bounded_limit(arguments.get("limit"))
    query = str(arguments.get("query") or "").strip()
    server_name = str(arguments.get("serverName") or "").strip()
    refreshed = False

    if server_name:
        row = await repository.get_enabled_installation(session, server_name)
        if row is None:
            raise LookupError("enabled MCP server was not found")
        _installation, server = row
        tool_count = await tool_repository.count_active_tool_schemas(
            session,
            server_name=server.name,
            server_version=server.version,
        )
        if tool_count == 0:
            await refresh_tool_schemas(session, server_name)
            await session.commit()
            refreshed = True

    tools, next_cursor = await tool_repository.search_enabled_tool_schemas(
        session,
        server_name=server_name,
        search=query,
        offset=offset,
        limit=limit,
    )

    return text_tool_result(
        {
            "tools": [cached_tool_summary(tool) for tool in tools],
            "nextCursor": next_cursor,
            "cache": {
                "mode": "cached-with-refresh" if refreshed else "cached",
                "refreshed": refreshed,
            },
        }
    )


async def get_mcp_tool(session: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    server_name = str(arguments.get("serverName") or "").strip()
    tool_name = str(arguments.get("toolName") or "").strip()
    if not server_name:
        raise ValueError("serverName is required")
    if not tool_name:
        raise ValueError("toolName is required")

    row = await repository.get_enabled_installation(session, server_name)
    if row is None:
        raise LookupError("enabled MCP server was not found")
    _installation, _server = row
    cached_tool = await tool_repository.get_enabled_tool_schema(
        session,
        server_name=server_name,
        tool_name=tool_name,
    )
    refreshed = False
    if cached_tool is None:
        await refresh_tool_schemas(session, server_name)
        await session.commit()
        refreshed = True
        cached_tool = await tool_repository.get_enabled_tool_schema(
            session,
            server_name=server_name,
            tool_name=tool_name,
        )
    if cached_tool is not None:
        return text_tool_result(
            {
                "tool": cached_tool_summary(cached_tool),
                "cache": {
                    "mode": "cached-with-refresh" if refreshed else "cached",
                    "refreshed": refreshed,
                },
            }
        )
    raise LookupError("MCP tool was not found")


async def run_mcp_tool(session: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    server_name = str(arguments.get("serverName") or "").strip()
    tool_name = str(arguments.get("toolName") or "").strip()
    tool_arguments = arguments.get("arguments")
    if not server_name:
        raise ValueError("serverName is required")
    if not tool_name:
        raise ValueError("toolName is required")
    if tool_arguments is None:
        tool_arguments = {}
    if not isinstance(tool_arguments, dict):
        raise ValueError("arguments must be an object")

    row = await repository.get_enabled_installation(session, server_name)
    if row is None:
        raise LookupError("enabled MCP server was not found")
    installation, server = row
    try:
        upstream_result = await call_tool_with_tracking(
            session,
            installation,
            server,
            tool_name=tool_name,
            arguments=tool_arguments,
        )
        await session.commit()
    except MCPGatewayUpstreamError as exc:
        await session.commit()
        return error_tool_result(
            str(exc),
            {
                "serverName": server_name,
                "toolName": tool_name,
                "error": str(exc),
            },
        )
    except Exception:
        await session.commit()
        raise
    return {
        **upstream_result,
        "structuredContent": {
            "serverName": server_name,
            "toolName": tool_name,
            "upstreamResult": upstream_result,
        },
    }


def initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": "wardn-mcp-gateway", "version": "0.1.0"},
    }


async def call_tool(
    session: AsyncSession,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if name == "search_mcp_servers":
        return await search_mcp_servers(session, arguments)
    if name == "get_mcp_server":
        return await get_mcp_server(session, arguments)
    if name == "search_mcp_tools":
        return await search_mcp_tools(session, arguments)
    if name == "get_mcp_tool":
        return await get_mcp_tool(session, arguments)
    if name == "run_mcp_tool":
        return await run_mcp_tool(session, arguments)
    raise LookupError(f"unknown gateway tool: {name}")
