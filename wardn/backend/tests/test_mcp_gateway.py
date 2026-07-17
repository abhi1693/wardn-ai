import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.db.session import get_db_session
from app.main import create_app
from app.modules.mcp_gateway import client as gateway_client_module
from app.modules.mcp_gateway import oauth as gateway_oauth
from app.modules.mcp_gateway import repository
from app.modules.mcp_gateway import router as gateway_router
from app.modules.mcp_gateway import service as gateway_service
from app.modules.mcp_gateway.scope import GatewayScope
from app.modules.mcp_registry import tool_repository
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.mcp_runtime import manager as runtime_manager
from app.modules.mcp_runtime.providers.kubernetes import KubernetesMetadataError
from app.modules.users.dependencies import get_current_user
from app.modules.users.models import User, UserAPIToken

TEST_ORGANIZATION_ID = "11111111-1111-4111-8111-111111111111"
TEST_WORKSPACE_ID = "22222222-2222-4222-8222-222222222222"
GATEWAY_PATH = "/api/v1/mcp/gateway"
WORKSPACE_GATEWAY_PATH = (
    f"/api/v1/organizations/{TEST_ORGANIZATION_ID}/workspaces/{TEST_WORKSPACE_ID}/mcp/gateway"
)


class FakeSession:
    committed = False

    async def commit(self):
        self.committed = True


async def fake_session():
    yield FakeSession()


async def fake_current_user():
    return User(id=uuid.uuid4(), email="admin@example.com", is_superuser=True)


async def failing_current_user():
    raise AssertionError("top-level MCP gateway must not require user auth")


async def fake_gateway_api_token(*args, **kwargs):
    user_id = uuid.uuid4()
    return (
        User(id=user_id, email="admin@example.com", is_superuser=True),
        UserAPIToken(
            user_id=user_id,
            token_prefix="test",
            token_hash="hashed",
            organization_ids=[],
            workspace_ids=[],
            is_active=True,
        ),
    )


async def fake_require_workspace_admin(*args, **kwargs):
    return None


async def fake_require_organization_admin(*args, **kwargs):
    return None


async def allow_gateway_tool_guardrails(*args, **kwargs):
    return gateway_service.GuardrailDecision(mode="allow", message="allowed")


def cached_tool(
    *,
    server_name: str = "io.github.example/weather",
    server_version: str = "1.0.0",
    tool_name: str = "get_forecast",
    title: str = "Get forecast",
    description: str = "Get weather forecast",
    input_schema: dict | None = None,
) -> MCPServerToolSchema:
    now = datetime(2026, 6, 21, tzinfo=UTC)
    tool = MCPServerToolSchema(
        server_name=server_name,
        server_version=server_version,
        tool_name=tool_name,
        title=title,
        description=description,
        input_schema=input_schema or {"type": "object"},
        output_schema=None,
        annotations={},
        source_hash="hash",
        is_active=True,
        discovered_at=now,
        last_seen_at=now,
    )
    tool.created_at = now
    tool.updated_at = now
    return tool


def installed_server() -> tuple[MCPServerInstallation, MCPServerVersion]:
    now = datetime(2026, 6, 21, tzinfo=UTC)
    installation = MCPServerInstallation(
        workspace_id=uuid.UUID(TEST_WORKSPACE_ID),
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
        secret_references={"headers": {"Authorization": "Bearer test"}},
    )
    installation.id = uuid.uuid4()
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
    command.parent.mkdir(parents=True, exist_ok=True)
    command.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    command.chmod(0o755)
    installation = MCPServerInstallation(
        workspace_id=uuid.UUID(TEST_WORKSPACE_ID),
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
        secret_references={"environment": {"KUBECONFIG": "/tmp/kubeconfig"}},
    )
    installation.id = uuid.uuid4()
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


def gateway_client(api_token_auth=fake_gateway_api_token) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    app.dependency_overrides[get_current_user] = fake_current_user
    gateway_router.authenticate_api_token = api_token_auth
    gateway_router.require_organization_admin = fake_require_organization_admin
    gateway_router.require_workspace_admin = fake_require_workspace_admin
    return TestClient(app, headers={"Authorization": "Bearer wardn_test.secret"})


def common_gateway_client(api_token_auth=fake_gateway_api_token) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    app.dependency_overrides[get_current_user] = failing_current_user
    gateway_router.authenticate_api_token = api_token_auth
    return TestClient(app, headers={"Authorization": "Bearer wardn_test.secret"})


def test_mcp_gateway_initialize() -> None:
    response = common_gateway_client().post(
        GATEWAY_PATH,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["protocolVersion"] == "2025-06-18"
    assert payload["result"]["serverInfo"]["name"] == "wardn-mcp-gateway"
    assert payload["result"]["capabilities"] == {"tools": {"listChanged": True}}


def test_mcp_gateway_requires_bearer_token() -> None:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    response = TestClient(app).post(
        GATEWAY_PATH,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "gateway bearer token required"
    assert response.headers["www-authenticate"] == (
        'Bearer resource_metadata="http://testserver/.well-known/oauth-protected-resource", '
        'scope="mcp:tools"'
    )


def test_mcp_gateway_get_advertises_oauth_challenge() -> None:
    response = TestClient(create_app()).get(
        GATEWAY_PATH,
        headers={
            "x-forwarded-host": "app.example.com",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        'Bearer resource_metadata="https://app.example.com/.well-known/oauth-protected-resource", '
        'scope="mcp:tools"'
    )


def test_mcp_oauth_metadata_discovery() -> None:
    client = TestClient(create_app())

    resource_response = client.get("/.well-known/oauth-protected-resource")
    path_resource_response = client.get(
        "/.well-known/oauth-protected-resource/api/v1/mcp/gateway"
    )
    embedded_resource_response = client.get(
        f"{GATEWAY_PATH}/.well-known/oauth-protected-resource"
    )
    auth_response = client.get("/.well-known/oauth-authorization-server")
    path_auth_response = client.get(
        "/.well-known/oauth-authorization-server/api/v1/mcp/gateway"
    )
    openid_response = client.get("/.well-known/openid-configuration/api/v1/mcp/gateway")

    assert resource_response.status_code == 200
    assert resource_response.json() == {
        "resource": "http://testserver/api/v1/mcp/gateway",
        "authorization_servers": ["http://testserver"],
        "scopes_supported": ["mcp:tools"],
        "bearer_methods_supported": ["header"],
    }
    assert path_resource_response.status_code == 200
    assert path_resource_response.json() == resource_response.json()
    assert embedded_resource_response.status_code == 200
    assert embedded_resource_response.json() == resource_response.json()
    assert auth_response.status_code == 200
    auth_metadata = auth_response.json()
    assert auth_metadata["issuer"] == "http://testserver"
    assert auth_metadata["authorization_endpoint"] == (
        "http://testserver/api/v1/oauth/authorize"
    )
    assert auth_metadata["token_endpoint"] == "http://testserver/api/v1/oauth/token"
    assert auth_metadata["registration_endpoint"] == (
        "http://testserver/api/v1/oauth/register"
    )
    assert auth_metadata["code_challenge_methods_supported"] == ["S256"]
    assert auth_metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert path_auth_response.status_code == 200
    assert path_auth_response.json() == auth_metadata
    assert openid_response.status_code == 200
    assert openid_response.json() == auth_metadata


def test_mcp_oauth_metadata_uses_forwarded_public_origin() -> None:
    client = TestClient(create_app())
    headers = {
        "x-forwarded-host": "app.example.com",
        "x-forwarded-proto": "https",
    }

    resource_response = client.get("/.well-known/oauth-protected-resource", headers=headers)
    auth_response = client.get("/.well-known/oauth-authorization-server", headers=headers)

    assert resource_response.json()["resource"] == "https://app.example.com/api/v1/mcp/gateway"
    assert resource_response.json()["authorization_servers"] == ["https://app.example.com"]
    assert auth_response.json()["issuer"] == "https://app.example.com"
    assert auth_response.json()["authorization_endpoint"] == (
        "https://app.example.com/api/v1/oauth/authorize"
    )


def test_mcp_oauth_authorize_accepts_direct_backend_resource_with_forwarded_origin() -> None:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    redirect_uri = "http://127.0.0.1:39123/callback"
    client_id = gateway_oauth.create_client_id(
        {"client_name": "Codex", "redirect_uris": [redirect_uri]}
    )

    response = TestClient(app).get(
        "/api/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": "test-challenge",
            "code_challenge_method": "S256",
            "resource": "http://testserver/api/v1/mcp/gateway",
            "scope": "mcp:tools",
            "state": "client-state",
        },
        headers={
            "x-forwarded-host": "app.example.com",
            "x-forwarded-proto": "https",
        },
        follow_redirects=False,
    )

    assert response.status_code in {200, 302}
    if response.status_code == 302:
        assert "/api/v1/auth/oidc/login" in response.headers["location"]
    else:
        assert "Authorize Wardn MCP" in response.text
        assert "resource does not match this MCP server" not in response.text


def test_mcp_oauth_dynamic_client_registration() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/oauth/register",
        json={
            "client_name": "Codex",
            "redirect_uris": ["http://127.0.0.1:39123/callback"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["client_name"] == "Codex"
    assert payload["redirect_uris"] == ["http://127.0.0.1:39123/callback"]
    metadata = gateway_oauth.client_metadata(payload["client_id"])
    assert metadata["client_name"] == "Codex"
    assert metadata["redirect_uris"] == ["http://127.0.0.1:39123/callback"]


def test_mcp_oauth_authorize_redirects_to_oidc_login(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        auth_mode="oidc",
        frontend_base_url="https://app.example.com",
        public_base_url="https://api.example.com",
        oidc_issuer_url="https://issuer.example.com",
        oidc_client_id="wardn-client",
        oidc_client_secret="wardn-secret",
    )
    monkeypatch.setattr(gateway_oauth, "get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    redirect_uri = "http://127.0.0.1:39123/callback"
    client_id = gateway_oauth.create_client_id(
        {"client_name": "Codex", "redirect_uris": [redirect_uri]}
    )

    response = TestClient(app).get(
        "/api/v1/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": "test-challenge",
            "code_challenge_method": "S256",
            "resource": "http://testserver/api/v1/mcp/gateway",
            "scope": "mcp:tools",
            "state": "client-state",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://api.example.com/api/v1/auth/oidc/login"
    )
    redirect_to = parse_qs(parsed.query)["redirectTo"][0]
    redirect_target = urlparse(redirect_to)
    assert redirect_target.path == "/api/v1/oauth/authorize"
    redirect_query = parse_qs(redirect_target.query)
    assert redirect_query["client_id"] == [client_id]
    assert redirect_query["redirect_uri"] == [redirect_uri]
    assert redirect_query["state"] == ["client-state"]


def test_mcp_oauth_post_without_session_redirects_to_oidc_login(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        auth_mode="oidc",
        frontend_base_url="https://app.example.com",
        public_base_url="https://api.example.com",
        oidc_issuer_url="https://issuer.example.com",
        oidc_client_id="wardn-client",
        oidc_client_secret="wardn-secret",
    )
    monkeypatch.setattr(gateway_oauth, "get_settings", lambda: settings)
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    redirect_uri = "http://127.0.0.1:39123/callback"
    client_id = gateway_oauth.create_client_id(
        {"client_name": "Codex", "redirect_uris": [redirect_uri]}
    )

    response = TestClient(app).post(
        "/api/v1/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": "test-challenge",
            "code_challenge_method": "S256",
            "resource": "http://testserver/api/v1/mcp/gateway",
            "scope": "mcp:tools",
            "state": "client-state",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    parsed = urlparse(response.headers["location"])
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://api.example.com/api/v1/auth/oidc/login"
    )


def test_mcp_oauth_token_exchange_issues_gateway_api_token(monkeypatch) -> None:
    app = create_app()
    app.dependency_overrides[get_db_session] = fake_session
    client = TestClient(app)
    user_id = uuid.uuid4()
    redirect_uri = "http://127.0.0.1:39123/callback"
    client_id = gateway_oauth.create_client_id(
        {"client_name": "Codex", "redirect_uris": [redirect_uri]}
    )
    verifier = "test-verifier"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode(
        "ascii"
    ).rstrip("=")
    user = User(id=user_id, email="admin@example.com", is_superuser=True, is_active=True)
    code = gateway_oauth.authorization_code(
        user,
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "resource": "http://testserver/api/v1/mcp/gateway",
            "scope": "mcp:tools",
        },
        {
            "kind": "workspace",
            "id": TEST_WORKSPACE_ID,
            "name": "Default Workspace",
            "value": f"workspace:{TEST_WORKSPACE_ID}",
            "label": "Default / Default Workspace (workspace)",
        },
    )

    async def get_user_by_id(*args, **kwargs):
        return user

    seen_payloads = []

    async def create_api_token(*args, **kwargs):
        seen_payloads.append(args[2])
        return (
            UserAPIToken(user_id=user_id, token_prefix="new", token_hash="hash"),
            "wardn_new.secret",
        )

    monkeypatch.setattr(gateway_oauth.users_repository, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(gateway_oauth, "create_user_api_token", create_api_token)

    response = client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "resource": "http://testserver/api/v1/mcp/gateway",
        },
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "wardn_new.secret"
    assert response.json()["token_type"] == "Bearer"
    assert seen_payloads[0].organization_ids == []
    assert seen_payloads[0].workspace_ids == [uuid.UUID(TEST_WORKSPACE_ID)]


def test_tool_schema_scope_applies_workspace_token_scope_for_superuser() -> None:
    statement = tool_repository.apply_gateway_scope(
        select(MCPServerToolSchema),
        GatewayScope(
            user_id=uuid.uuid4(),
            is_superuser=True,
            workspace_ids=frozenset({uuid.UUID(TEST_WORKSPACE_ID)}),
        ),
    )

    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert "mcp_server_installations.workspace_id IN" in compiled
    assert uuid.UUID(TEST_WORKSPACE_ID).hex in compiled


def test_mcp_gateway_ping_returns_empty_result() -> None:
    response = common_gateway_client().post(
        GATEWAY_PATH,
        json={"jsonrpc": "2.0", "id": "ping-1", "method": "ping"},
    )

    assert response.status_code == 200
    assert response.json() == {"jsonrpc": "2.0", "id": "ping-1", "result": {}}


def test_workspace_mcp_gateway_ping_returns_empty_result(monkeypatch) -> None:
    async def get_workspace_by_id(*args, **kwargs):
        return type(
            "Workspace",
            (),
            {
                "id": uuid.UUID(TEST_WORKSPACE_ID),
                "organization_id": uuid.UUID(TEST_ORGANIZATION_ID),
            },
        )()

    monkeypatch.setattr(
        gateway_router.organizations_repository,
        "get_workspace_by_id",
        get_workspace_by_id,
    )

    response = gateway_client().post(
        WORKSPACE_GATEWAY_PATH,
        json={"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}},
    )

    assert response.status_code == 200
    assert response.json() == {"jsonrpc": "2.0", "id": 7, "result": {}}


def test_mcp_gateway_tools_list_is_bounded() -> None:
    response = common_gateway_client().post(
        GATEWAY_PATH,
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


def test_mcp_gateway_rejects_invalid_progress_token() -> None:
    response = common_gateway_client().post(
        GATEWAY_PATH,
        json={
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/list",
            "params": {"_meta": {"progressToken": {"bad": "token"}}},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": 8,
        "error": {"code": -32602, "message": "progressToken must be a string or integer"},
    }


def test_send_remote_request_preserves_jsonrpc_http_error(monkeypatch) -> None:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": "Request had invalid authentication credentials.",
                    }
                ],
                "isError": True,
            },
        }
    ).encode("utf-8")

    def open_outbound_request_raises_http_error(*args, **kwargs):
        raise HTTPError(
            "https://example.com/mcp",
            401,
            "Unauthorized",
            {},
            BytesIO(body),
        )

    monkeypatch.setattr(
        gateway_client_module,
        "open_outbound_request",
        open_outbound_request_raises_http_error,
    )

    response, session_id = gateway_client_module.send_remote_request(
        "https://example.com/mcp",
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {}},
    )

    assert session_id is None
    assert response["result"]["isError"] is True
    assert response["result"]["content"][0]["text"] == (
        "Request had invalid authentication credentials."
    )


def test_mcp_gateway_search_servers(monkeypatch) -> None:
    async def search_enabled_installations(*args, **kwargs):
        return [installed_server()], "10"

    monkeypatch.setattr(
        repository,
        "search_enabled_installations",
        search_enabled_installations,
    )

    response = gateway_client().post(
        GATEWAY_PATH,
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
    assert result["structuredContent"]["servers"][0]["installationId"]
    assert result["structuredContent"]["servers"][0]["workspaceId"] == TEST_WORKSPACE_ID
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
        GATEWAY_PATH,
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
    installation, server = installed_server()

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

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

    async def count_active_tool_schemas(*args, **kwargs):
        assert kwargs["installation_id"] == installation.id
        return 0

    async def upsert_tool_schemas(*args, **kwargs):
        return 2

    async def search_enabled_tool_schemas(*args, **kwargs):
        return [
            cached_tool(),
        ], ""

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(gateway_client_module, "list_tools", list_tools)
    monkeypatch.setattr(tool_repository, "count_active_tool_schemas", count_active_tool_schemas)
    monkeypatch.setattr(tool_repository, "upsert_tool_schemas", upsert_tool_schemas)
    monkeypatch.setattr(tool_repository, "search_enabled_tool_schemas", search_enabled_tool_schemas)

    response = gateway_client().post(
        GATEWAY_PATH,
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
    assert result["cache"] == {"mode": "cached-with-refresh", "refreshed": True}
    assert seen == {
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer test"},
    }


def test_mcp_gateway_search_tools_for_package_server(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_manager,
        "get_settings",
        lambda: type("Settings", (), {"mcp_runtime_provider": "local"})(),
    )

    installation, server = installed_package_server(tmp_path)

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

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

    async def count_active_tool_schemas(*args, **kwargs):
        assert kwargs["installation_id"] == installation.id
        return 0

    async def upsert_tool_schemas(*args, **kwargs):
        return 1

    async def search_enabled_tool_schemas(*args, **kwargs):
        return [
            cached_tool(
                server_name="io.github.containers/kubernetes-mcp-server",
                server_version="0.0.62",
                tool_name="list_pods",
                title="List pods",
                description="List Kubernetes pods",
            )
        ], ""

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(gateway_client_module, "list_stdio_tools", list_stdio_tools)
    monkeypatch.setattr(tool_repository, "count_active_tool_schemas", count_active_tool_schemas)
    monkeypatch.setattr(tool_repository, "upsert_tool_schemas", upsert_tool_schemas)
    monkeypatch.setattr(tool_repository, "search_enabled_tool_schemas", search_enabled_tool_schemas)

    response = gateway_client().post(
        GATEWAY_PATH,
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
    installation, server = installed_server()

    async def get_enabled_installation(*args, **kwargs):
        return installation, server

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

    calls = {"get": 0}

    async def get_enabled_tool_schema(*args, **kwargs):
        assert kwargs["installation_id"] == installation.id
        calls["get"] += 1
        if calls["get"] == 1:
            return None
        return cached_tool(
            input_schema={
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            }
        )

    async def upsert_tool_schemas(*args, **kwargs):
        return 1

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(gateway_client_module, "list_tools", list_tools)
    monkeypatch.setattr(tool_repository, "get_enabled_tool_schema", get_enabled_tool_schema)
    monkeypatch.setattr(tool_repository, "upsert_tool_schemas", upsert_tool_schemas)

    response = gateway_client().post(
        GATEWAY_PATH,
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

    async def call_tool_with_tracking(
        session,
        installation,
        server,
        *,
        tool_name,
        arguments,
        user_id=None,
        request_meta=None,
    ):
        seen.update(
            {
                "server_name": installation.server_name,
                "server_version": server.version,
                "tool_name": tool_name,
                "arguments": arguments,
                "request_meta": request_meta,
            }
        )
        return {
            "content": [{"type": "text", "text": "Sunny"}],
            "isError": False,
        }

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(
        gateway_service,
        "evaluate_gateway_tool_guardrails",
        allow_gateway_tool_guardrails,
    )
    monkeypatch.setattr(
        gateway_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    response = gateway_client().post(
        GATEWAY_PATH,
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "run_mcp_tool",
                "_meta": {"progressToken": "progress-1"},
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
        "server_name": "io.github.example/weather",
        "server_version": "1.0.0",
        "tool_name": "get_forecast",
        "arguments": {"location": "Delhi"},
        "request_meta": {"progressToken": "progress-1"},
    }


def test_mcp_gateway_run_tool_returns_tool_error_for_upstream_failure(monkeypatch) -> None:
    async def get_enabled_installation(*args, **kwargs):
        return installed_server()

    async def call_tool_with_tracking(*args, **kwargs):
        raise gateway_client_module.MCPGatewayUpstreamError(
            "upstream tools/call returned no result"
        )

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(
        gateway_service,
        "evaluate_gateway_tool_guardrails",
        allow_gateway_tool_guardrails,
    )
    monkeypatch.setattr(
        gateway_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    response = gateway_client().post(
        GATEWAY_PATH,
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

    payload = response.json()
    assert "error" not in payload
    result = payload["result"]
    assert result["isError"] is True
    assert result["content"] == [
        {"type": "text", "text": "upstream tools/call returned no result"}
    ]
    assert result["structuredContent"] == {
        "serverName": "io.github.example/weather",
        "toolName": "get_forecast",
        "error": "upstream tools/call returned no result",
    }


def test_mcp_gateway_run_tool_returns_tool_error_for_kubernetes_runtime_failure(
    monkeypatch,
) -> None:
    async def get_enabled_installation(*args, **kwargs):
        return installed_server()

    async def call_tool_with_tracking(*args, **kwargs):
        raise KubernetesMetadataError(
            "Kubernetes namespace label value is not a valid Kubernetes label"
        )

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(
        gateway_service,
        "evaluate_gateway_tool_guardrails",
        allow_gateway_tool_guardrails,
    )
    monkeypatch.setattr(
        gateway_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    response = gateway_client().post(
        GATEWAY_PATH,
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

    payload = response.json()
    assert "error" not in payload
    result = payload["result"]
    assert result["isError"] is True
    assert result["content"] == [
        {
            "type": "text",
            "text": "Kubernetes namespace label value is not a valid Kubernetes label",
        }
    ]
    assert result["structuredContent"] == {
        "serverName": "io.github.example/weather",
        "toolName": "get_forecast",
        "error": "Kubernetes namespace label value is not a valid Kubernetes label",
    }


def test_mcp_gateway_run_tool_denies_guardrail_before_runtime(monkeypatch) -> None:
    policy_id = uuid.uuid4()

    async def get_enabled_installation(*args, **kwargs):
        return installed_server()

    async def evaluate_gateway_tool_guardrails(*args, **kwargs):
        return gateway_service.GuardrailDecision(
            mode="deny",
            policy_id=policy_id,
            policy_name="Block weather",
            message="Tool call blocked by guardrail policy: Block weather",
            matched_policy_ids=(policy_id,),
        )

    async def call_tool_with_tracking(*args, **kwargs):
        raise AssertionError("runtime should not be called")

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(
        gateway_service,
        "evaluate_gateway_tool_guardrails",
        evaluate_gateway_tool_guardrails,
    )
    monkeypatch.setattr(
        gateway_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    response = gateway_client().post(
        GATEWAY_PATH,
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
    assert result["isError"] is True
    assert result["structuredContent"]["guardrail"] == {
        "status": "blocked",
        "mode": "deny",
        "policyId": str(policy_id),
        "policyName": "Block weather",
            "message": (
                "Tool call blocked by guardrail policy: Block weather Do not complete this "
                "denied MCP request from cached, prior, or alternate data."
            ),
        "matchedPolicyIds": [str(policy_id)],
    }


def test_mcp_gateway_run_tool_requires_confirmation_before_runtime(monkeypatch) -> None:
    policy_id = uuid.uuid4()

    async def get_enabled_installation(*args, **kwargs):
        return installed_server()

    async def evaluate_gateway_tool_guardrails(*args, **kwargs):
        return gateway_service.GuardrailDecision(
            mode="require_confirmation",
            policy_id=policy_id,
            policy_name="Confirm weather",
            message="Tool call requires confirmation by guardrail policy: Confirm weather",
            matched_policy_ids=(policy_id,),
        )

    async def call_tool_with_tracking(*args, **kwargs):
        raise AssertionError("runtime should not be called")

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(
        gateway_service,
        "evaluate_gateway_tool_guardrails",
        evaluate_gateway_tool_guardrails,
    )
    monkeypatch.setattr(
        gateway_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    response = gateway_client().post(
        GATEWAY_PATH,
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
    assert result["isError"] is True
    assert result["structuredContent"]["guardrail"] == {
        "status": "approval_required",
        "mode": "require_confirmation",
        "policyId": str(policy_id),
        "policyName": "Confirm weather",
        "message": "Tool call requires confirmation by guardrail policy: Confirm weather",
        "matchedPolicyIds": [str(policy_id)],
    }


@pytest.mark.asyncio
async def test_mcp_gateway_guardrail_context_uses_workspace_and_tool_schema(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    installation, server = installed_server()
    tool_schema = cached_tool(
        server_name=installation.server_name,
        server_version=installation.installed_version,
        tool_name="get_forecast",
    )
    tool_schema.id = uuid.uuid4()
    tool_schema.installation_id = installation.id
    tool_schema.workspace_id = installation.workspace_id
    captured = {}

    async def get_workspace_by_id(*args, **kwargs):
        return type(
            "Workspace",
            (),
            {
                "id": installation.workspace_id,
                "organization_id": organization_id,
            },
        )()

    async def get_enabled_tool_schema(*args, **kwargs):
        return tool_schema

    async def evaluate_tool_call_guardrails(*args, **kwargs):
        captured["context"] = args[1]
        captured["kwargs"] = kwargs
        return gateway_service.GuardrailDecision(mode="allow", message="allowed")

    monkeypatch.setattr(
        gateway_service.organizations_repository,
        "get_workspace_by_id",
        get_workspace_by_id,
    )
    monkeypatch.setattr(
        gateway_service.tool_repository,
        "get_enabled_tool_schema",
        get_enabled_tool_schema,
    )
    monkeypatch.setattr(
        gateway_service,
        "evaluate_tool_call_guardrails",
        evaluate_tool_call_guardrails,
    )

    decision = await gateway_service.evaluate_gateway_tool_guardrails(
        FakeSession(),
        installation,
        server,
        tool_name="get_forecast",
        arguments={"location": "Delhi"},
        scope=gateway_service.GatewayScope(user_id=uuid.uuid4(), is_superuser=True),
    )

    context = captured["context"]
    assert decision.mode == "allow"
    assert context.organization_id == organization_id
    assert context.workspace_id == installation.workspace_id
    assert context.installation_id == installation.id
    assert context.tool_schema_id == tool_schema.id
    assert context.server_name == server.name
    assert context.tool_name == "get_forecast"
    assert context.arguments == {"location": "Delhi"}
    assert captured["kwargs"] == {}


def test_mcp_gateway_run_package_tool(tmp_path, monkeypatch) -> None:
    async def get_enabled_installation(*args, **kwargs):
        return installed_package_server(tmp_path)

    seen = {}

    async def call_tool_with_tracking(
        session,
        installation,
        server,
        *,
        tool_name,
        arguments,
        user_id=None,
        request_meta=None,
    ):
        seen.update(
            {
                "server_name": installation.server_name,
                "server_version": server.version,
                "tool_name": tool_name,
                "arguments": arguments,
                "request_meta": request_meta,
            }
        )
        return {
            "content": [{"type": "text", "text": "default/pod-a"}],
            "isError": False,
        }

    monkeypatch.setattr(repository, "get_enabled_installation", get_enabled_installation)
    monkeypatch.setattr(
        gateway_service,
        "evaluate_gateway_tool_guardrails",
        allow_gateway_tool_guardrails,
    )
    monkeypatch.setattr(
        gateway_service,
        "call_tool_with_isolated_tracking",
        call_tool_with_tracking,
    )

    response = gateway_client().post(
        GATEWAY_PATH,
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
    assert seen["server_name"] == "io.github.containers/kubernetes-mcp-server"
    assert seen["tool_name"] == "list_pods"
    assert seen["arguments"] == {"namespace": "default"}


def test_mcp_gateway_initialized_notification_returns_accepted() -> None:
    response = gateway_client().post(
        GATEWAY_PATH,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    assert response.status_code == 202
    assert response.content == b""


def test_top_level_mcp_gateway_ignores_legacy_request_scope(monkeypatch) -> None:
    seen = {}

    async def search_enabled_installations(*args, **kwargs):
        seen["scope"] = kwargs["scope"]
        return [installed_server()], ""

    monkeypatch.setattr(
        repository,
        "search_enabled_installations",
        search_enabled_installations,
    )

    response = gateway_client().post(
        f"{GATEWAY_PATH}?organization_id={TEST_ORGANIZATION_ID}",
        headers={
            "Authorization": "Bearer wardn_test.secret",
            "X-Wardn-Organization-Id": TEST_ORGANIZATION_ID,
            "X-Wardn-Workspace-Id": TEST_WORKSPACE_ID,
        },
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_mcp_servers",
                "arguments": {},
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
    assert seen["scope"].organization_id is None
    assert seen["scope"].workspace_id is None
    assert seen["scope"].organization_ids is None
    assert seen["scope"].workspace_ids is None


def test_top_level_mcp_gateway_uses_token_organization_scope(monkeypatch) -> None:
    seen = {}

    async def scoped_gateway_api_token(*args, **kwargs):
        user_id = uuid.uuid4()
        return (
            User(id=user_id, email="admin@example.com", is_superuser=False),
            UserAPIToken(
                user_id=user_id,
                token_prefix="test",
                token_hash="hashed",
                organization_ids=[TEST_ORGANIZATION_ID],
                workspace_ids=[],
                is_active=True,
            ),
        )

    async def search_enabled_installations(*args, **kwargs):
        scope = kwargs["scope"]
        seen["scope"] = scope
        return [installed_server()], ""

    monkeypatch.setattr(
        repository,
        "search_enabled_installations",
        search_enabled_installations,
    )

    response = gateway_client(api_token_auth=scoped_gateway_api_token).post(
        GATEWAY_PATH,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_mcp_servers",
                "arguments": {},
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
    assert seen["scope"].organization_id is None
    assert seen["scope"].organization_ids == frozenset({uuid.UUID(TEST_ORGANIZATION_ID)})
    assert seen["scope"].workspace_id is None


def test_top_level_mcp_gateway_uses_token_global_scope(monkeypatch) -> None:
    seen = {}

    async def search_enabled_installations(*args, **kwargs):
        seen["scope"] = kwargs["scope"]
        return [installed_server()], ""

    monkeypatch.setattr(
        repository,
        "search_enabled_installations",
        search_enabled_installations,
    )

    response = common_gateway_client().post(
        GATEWAY_PATH,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_mcp_servers",
                "arguments": {},
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
    assert seen["scope"].organization_id is None
    assert seen["scope"].workspace_id is None
    assert seen["scope"].is_superuser is True
    assert seen["scope"].organization_ids is None
    assert seen["scope"].workspace_ids is None
