from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.db.session import get_db_session
from app.main import create_app
from app.modules.mcp_gateway import client as gateway_client_module
from app.modules.mcp_gateway import repository
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerVersion


async def fake_session():
    yield object()


def installed_server() -> tuple[MCPServerInstallation, MCPServerVersion]:
    now = datetime(2026, 6, 21, tzinfo=UTC)
    installation = MCPServerInstallation(
        server_name="io.github.example/weather",
        installed_version="1.0.0",
        status="enabled",
        install_type="remote",
        install_path="/tmp/weather",
        runtime_config={
            "kind": "remote",
            "transport": {"type": "streamable-http", "url": "https://example.com/mcp"},
            "verification": {"toolCount": 3},
        },
        secret_config={"headers": {"Authorization": "Bearer test"}},
    )
    installation.installed_at = now
    server = MCPServerVersion(
        name="io.github.example/weather",
        title="Weather",
        description="Weather tools for forecasts",
        version="1.0.0",
        website_url="https://example.com/weather",
        repository={"source": "github", "url": "https://github.com/example/weather"},
        packages=[],
        remotes=[
            {
                "type": "streamable-http",
                "url": "https://example.com/mcp",
                "headers": [
                    {"name": "X-API-Key", "isRequired": True, "isSecret": True}
                ],
            }
        ],
        icons=[],
        server_json={
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "version": "1.0.0",
        },
        status="active",
        status_message="",
        is_latest=True,
    )
    server.published_at = now
    server.status_changed_at = now
    return installation, server


def installed_package_server(tmp_path: Path) -> tuple[MCPServerInstallation, MCPServerVersion]:
    now = datetime(2026, 6, 21, tzinfo=UTC)
    install_path = tmp_path / "kubernetes"
    command = install_path / "node_modules" / ".bin" / "kubernetes-mcp-server"
    command.parent.mkdir(parents=True)
    command.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    command.chmod(0o755)
    installation = MCPServerInstallation(
        server_name="io.github.containers/kubernetes-mcp-server",
        installed_version="0.0.62",
        status="enabled",
        install_type="npm",
        install_path=str(install_path),
        runtime_config={
            "kind": "package",
            "registryType": "npm",
            "transport": {"type": "stdio"},
            "command": f"{install_path}.tmp/node_modules/.bin/kubernetes-mcp-server",
            "args": [],
            "cwd": f"{install_path}.tmp",
        },
        secret_config={"environment": {"KUBECONFIG": "/tmp/kubeconfig"}},
    )
    installation.installed_at = now
    server = MCPServerVersion(
        name="io.github.containers/kubernetes-mcp-server",
        title="Kubernetes",
        description="A Model Context Protocol server for Kubernetes",
        version="0.0.62",
        website_url="",
        repository=None,
        packages=[
            {
                "registryType": "npm",
                "identifier": "kubernetes-mcp-server",
                "version": "0.0.62",
                "transport": {"type": "stdio"},
            }
        ],
        remotes=[],
        icons=[],
        server_json={
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.containers/kubernetes-mcp-server",
            "title": "Kubernetes",
            "description": "A Model Context Protocol server for Kubernetes",
            "version": "0.0.62",
        },
        status="active",
        status_message="",
        is_latest=True,
    )
    server.published_at = now
    server.status_changed_at = now
    return installation, server


def gateway_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    return TestClient(app)


def test_mcp_gateway_initialize() -> None:
    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["serverInfo"]["name"] == "wardn-mcp-gateway"
    assert payload["result"]["capabilities"] == {"tools": {"listChanged": True}}


def test_mcp_gateway_tools_list_is_bounded() -> None:
    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    tool_names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert tool_names == [
        "search_mcp_servers",
        "get_mcp_server",
        "search_mcp_tools",
        "get_mcp_tool",
        "run_mcp_tool",
    ]


def test_mcp_gateway_search_servers(monkeypatch) -> None:
    async def search_enabled_installations(*args, **kwargs):
        return [installed_server()], "10"

    monkeypatch.setattr(
        repository,
        "search_enabled_installations",
        search_enabled_installations,
    )

    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_mcp_servers",
                "arguments": {"query": "weather", "limit": 5},
            },
        },
    )

    result = response.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["nextCursor"] == "10"
    assert result["structuredContent"]["servers"][0]["serverName"] == "io.github.example/weather"
    assert result["structuredContent"]["servers"][0]["inputCounts"] == {
        "total": 1,
        "required": 1,
        "secret": 1,
    }


def test_mcp_gateway_get_server(monkeypatch) -> None:
    async def get_enabled_installation(*args, **kwargs):
        return installed_server()

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)

    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_mcp_server",
                "arguments": {"serverName": "io.github.example/weather"},
            },
        },
    )

    server = response.json()["result"]["structuredContent"]["server"]
    assert server["serverName"] == "io.github.example/weather"
    assert server["transport"]["url"] == "https://example.com/mcp"
    assert server["verification"]["toolCount"] == 3


def test_mcp_gateway_search_tools_for_server(monkeypatch) -> None:
    async def get_enabled_installation(*args, **kwargs):
        return installed_server()

    seen = {}

    def list_tools(url, headers):
        seen["url"] = url
        seen["headers"] = headers
        return [
            {
                "name": "get_forecast",
                "title": "Get forecast",
                "description": "Get weather forecast",
                "inputSchema": {"type": "object"},
            },
            {
                "name": "archive_weather",
                "description": "Archive weather report",
                "inputSchema": {"type": "object"},
            },
        ]

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(gateway_client_module, "list_tools", list_tools)

    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "search_mcp_tools",
                "arguments": {
                    "serverName": "io.github.example/weather",
                    "query": "forecast",
                },
            },
        },
    )

    result = response.json()["result"]["structuredContent"]
    assert result["tools"][0]["toolName"] == "get_forecast"
    assert result["tools"][0]["serverName"] == "io.github.example/weather"
    assert seen == {
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer test"},
    }


def test_mcp_gateway_search_tools_for_package_server(tmp_path, monkeypatch) -> None:
    async def get_enabled_installation(*args, **kwargs):
        return installed_package_server(tmp_path)

    seen = {}

    def list_stdio_tools(command, args, *, cwd, environment):
        seen.update(
            {
                "command": command,
                "args": args,
                "cwd": cwd,
                "environment": environment,
            }
        )
        return [
            {
                "name": "list_pods",
                "title": "List pods",
                "description": "List Kubernetes pods",
                "inputSchema": {"type": "object"},
            }
        ]

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(gateway_client_module, "list_stdio_tools", list_stdio_tools)

    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "search_mcp_tools",
                "arguments": {
                    "serverName": "io.github.containers/kubernetes-mcp-server",
                    "query": "pods",
                },
            },
        },
    )

    result = response.json()["result"]["structuredContent"]
    assert result["tools"][0]["toolName"] == "list_pods"
    assert seen["command"].endswith("/kubernetes/node_modules/.bin/kubernetes-mcp-server")
    assert seen["cwd"].endswith("/kubernetes")
    assert seen["environment"] == {"KUBECONFIG": "/tmp/kubeconfig"}


def test_mcp_gateway_get_tool(monkeypatch) -> None:
    async def get_enabled_installation(*args, **kwargs):
        return installed_server()

    def list_tools(*args, **kwargs):
        return [
            {
                "name": "get_forecast",
                "title": "Get forecast",
                "description": "Get weather forecast",
                "inputSchema": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            }
        ]

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(gateway_client_module, "list_tools", list_tools)

    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_mcp_tool",
                "arguments": {
                    "serverName": "io.github.example/weather",
                    "toolName": "get_forecast",
                },
            },
        },
    )

    tool = response.json()["result"]["structuredContent"]["tool"]
    assert tool["toolName"] == "get_forecast"
    assert tool["inputSchema"]["required"] == ["location"]


def test_mcp_gateway_run_tool(monkeypatch) -> None:
    async def get_enabled_installation(*args, **kwargs):
        return installed_server()

    seen = {}

    def call_tool(url, headers, *, tool_name, arguments):
        seen.update(
            {
                "url": url,
                "headers": headers,
                "tool_name": tool_name,
                "arguments": arguments,
            }
        )
        return {
            "content": [{"type": "text", "text": "Sunny"}],
            "isError": False,
        }

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(gateway_client_module, "call_tool", call_tool)

    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "run_mcp_tool",
                "arguments": {
                    "serverName": "io.github.example/weather",
                    "toolName": "get_forecast",
                    "arguments": {"location": "Delhi"},
                },
            },
        },
    )

    result = response.json()["result"]
    assert result["content"] == [{"type": "text", "text": "Sunny"}]
    assert result["structuredContent"]["serverName"] == "io.github.example/weather"
    assert seen == {
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer test"},
        "tool_name": "get_forecast",
        "arguments": {"location": "Delhi"},
    }


def test_mcp_gateway_run_package_tool(tmp_path, monkeypatch) -> None:
    async def get_enabled_installation(*args, **kwargs):
        return installed_package_server(tmp_path)

    seen = {}

    def call_stdio_tool(command, args, *, cwd, environment, tool_name, arguments):
        seen.update(
            {
                "command": command,
                "args": args,
                "cwd": cwd,
                "environment": environment,
                "tool_name": tool_name,
                "arguments": arguments,
            }
        )
        return {
            "content": [{"type": "text", "text": "default/pod-a"}],
            "isError": False,
        }

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(gateway_client_module, "call_stdio_tool", call_stdio_tool)

    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "run_mcp_tool",
                "arguments": {
                    "serverName": "io.github.containers/kubernetes-mcp-server",
                    "toolName": "list_pods",
                    "arguments": {"namespace": "default"},
                },
            },
        },
    )

    result = response.json()["result"]
    assert result["content"] == [{"type": "text", "text": "default/pod-a"}]
    assert result["structuredContent"]["serverName"] == "io.github.containers/kubernetes-mcp-server"
    assert seen["tool_name"] == "list_pods"
    assert seen["arguments"] == {"namespace": "default"}


def test_mcp_gateway_initialized_notification_returns_accepted() -> None:
    response = gateway_client().post(
        "/api/v1/mcp/gateway",
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    )

    assert response.status_code == 202
    assert response.content == b""
