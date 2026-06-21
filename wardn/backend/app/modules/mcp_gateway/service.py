import json
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp_gateway import client, repository
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion

PROTOCOL_VERSION = "2025-06-18"
MAX_SEARCH_LIMIT = 25
MAX_SERVER_SCAN_LIMIT = 5


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


def runtime_kind(installation: MCPServerInstallation) -> str:
    runtime_config = installation.runtime_config or {}
    return str(runtime_config.get("kind") or installation.install_type)


def remote_url(installation: MCPServerInstallation) -> str:
    runtime_config = installation.runtime_config or {}
    transport = runtime_config.get("transport")
    if not isinstance(transport, dict):
        return ""
    return str(transport.get("url") or "")


def secret_headers(installation: MCPServerInstallation) -> dict[str, str]:
    secret_config = installation.secret_config or {}
    headers = secret_config.get("headers")
    if not isinstance(headers, dict):
        return {}
    return {str(key): str(value) for key, value in headers.items() if value is not None}


def secret_environment(installation: MCPServerInstallation) -> dict[str, str]:
    secret_config = installation.secret_config or {}
    environment = secret_config.get("environment")
    if not isinstance(environment, dict):
        return {}
    return {str(key): str(value) for key, value in environment.items() if value is not None}


def require_remote_installation(installation: MCPServerInstallation) -> tuple[str, dict[str, str]]:
    if runtime_kind(installation) != "remote":
        raise ValueError("only remote MCP server installations can be proxied right now")
    url = remote_url(installation)
    if not url:
        raise ValueError("remote MCP server URL is missing from installation runtime")
    return url, secret_headers(installation)


def normalize_installed_path(value: Any, installation: MCPServerInstallation) -> Any:
    install_path = installation.install_path or str(
        (installation.runtime_config or {}).get("installPath") or ""
    )
    if not install_path or not isinstance(value, str):
        return value
    tmp_path = f"{install_path}.tmp"
    if value.startswith(tmp_path):
        return f"{install_path}{value[len(tmp_path):]}"
    return value


def package_runtime(
    installation: MCPServerInstallation,
) -> tuple[str, list[str], str, dict[str, str]]:
    if runtime_kind(installation) != "package":
        raise ValueError("installation is not a package MCP server")

    runtime_config = installation.runtime_config or {}
    transport = runtime_config.get("transport")
    if isinstance(transport, dict) and transport.get("type") not in (None, "stdio"):
        raise ValueError("only stdio package MCP server transports can be proxied right now")

    command = str(normalize_installed_path(runtime_config.get("command") or "", installation))
    if not command:
        raise ValueError("package MCP server command is missing from installation runtime")

    raw_args = runtime_config.get("args")
    args = [str(normalize_installed_path(arg, installation)) for arg in raw_args or []]
    raw_cwd = runtime_config.get("cwd") or installation.install_path
    cwd = str(normalize_installed_path(raw_cwd, installation))
    if command and not Path(command).exists():
        raise ValueError(f"package MCP server command does not exist: {command}")
    if cwd and not Path(cwd).exists():
        raise ValueError(f"package MCP server working directory does not exist: {cwd}")
    return command, args, cwd, secret_environment(installation)


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


def tool_matches(tool: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    query = query.casefold()
    return any(
        query in str(tool.get(key) or "").casefold()
        for key in ("name", "title", "description")
    )


def gateway_tool_summary(server_name: str, tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "serverName": server_name,
        "toolName": str(tool.get("name") or ""),
        "title": str(tool.get("title") or tool.get("name") or ""),
        "description": str(tool.get("description") or ""),
        "inputSchema": tool.get("inputSchema", {"type": "object"}),
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


async def list_installation_tools(
    installation: MCPServerInstallation,
) -> list[dict[str, Any]]:
    if runtime_kind(installation) == "remote":
        url, headers = require_remote_installation(installation)
        return client.list_tools(url, headers)
    if runtime_kind(installation) == "package":
        command, args, cwd, environment = package_runtime(installation)
        return client.list_stdio_tools(command, args, cwd=cwd, environment=environment)
    raise ValueError(f"MCP server runtime is not supported yet: {runtime_kind(installation)}")


async def search_mcp_tools(session: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_limit(arguments.get("limit"))
    query = str(arguments.get("query") or "").strip()
    server_name = str(arguments.get("serverName") or "").strip()
    scanned_servers = 0
    tools: list[dict[str, Any]] = []

    if server_name:
        row = await repository.get_enabled_installation(session, server_name)
        if row is None:
            raise LookupError("enabled MCP server was not found")
        installation, _ = row
        scanned_servers = 1
        tools = [
            gateway_tool_summary(server_name, tool)
            for tool in await list_installation_tools(installation)
            if tool_matches(tool, query)
        ][:limit]
    else:
        rows, _ = await repository.search_enabled_installations(
            session,
            search=query,
            offset=0,
            limit=MAX_SERVER_SCAN_LIMIT,
        )
        scanned_servers = len(rows)
        for installation, server in rows:
            try:
                server_tools = await list_installation_tools(installation)
            except ValueError:
                continue
            for tool in server_tools:
                if tool_matches(tool, query):
                    tools.append(gateway_tool_summary(server.name, tool))
                if len(tools) >= limit:
                    break
            if len(tools) >= limit:
                break

    return text_tool_result(
        {
            "tools": tools,
            "scannedServers": scanned_servers,
            "hint": (
                "For broad environments, search servers first and then pass serverName "
                "to search_mcp_tools."
            ),
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
    installation, _ = row
    for tool in await list_installation_tools(installation):
        if tool.get("name") == tool_name:
            return text_tool_result(
                {"tool": gateway_tool_summary(server_name, tool)}
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
    installation, _ = row
    if runtime_kind(installation) == "remote":
        url, headers = require_remote_installation(installation)
        upstream_result = client.call_tool(
            url,
            headers,
            tool_name=tool_name,
            arguments=tool_arguments,
        )
    elif runtime_kind(installation) == "package":
        command, args, cwd, environment = package_runtime(installation)
        upstream_result = client.call_stdio_tool(
            command,
            args,
            cwd=cwd,
            environment=environment,
            tool_name=tool_name,
            arguments=tool_arguments,
        )
    else:
        raise ValueError(f"MCP server runtime is not supported yet: {runtime_kind(installation)}")
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
