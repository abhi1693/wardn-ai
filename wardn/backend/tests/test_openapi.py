from fastapi.testclient import TestClient

from app.main import create_app


def test_openapi_exposes_expected_paths() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"].startswith("3.")
    assert set(schema["paths"]) == {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/mcp/gateway",
        "/api/v1/mcp/registry/installed-servers",
        "/api/v1/mcp/registry/installed-servers/updates",
        "/api/v1/mcp/registry/installed-servers/{server_name}",
        "/api/v1/mcp/registry/servers",
        "/api/v1/mcp/registry/servers/{server_name}/versions",
        "/api/v1/mcp/registry/servers/{server_name}/versions/{version}",
        "/api/v1/users/bootstrap",
    }


def test_health_openapi_schema_is_specific() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()

    health_response = schema["paths"]["/api/v1/health/live"]["get"]["responses"]["200"]
    assert health_response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthStatus"
    }
    assert schema["components"]["schemas"]["HealthStatus"] == {
        "properties": {"status": {"type": "string", "title": "Status"}},
        "type": "object",
        "required": ["status"],
        "title": "HealthStatus",
    }


def test_bootstrap_openapi_contract() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()
    bootstrap = schema["paths"]["/api/v1/users/bootstrap"]["post"]

    assert bootstrap["operationId"] == "users_bootstrap"
    assert bootstrap["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BootstrapUserCreate"
    }
    assert bootstrap["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserRead"
    }
    assert bootstrap["responses"]["409"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_auth_openapi_contract() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()
    login = schema["paths"]["/api/v1/auth/login"]["post"]
    logout = schema["paths"]["/api/v1/auth/logout"]["post"]

    assert login["operationId"] == "auth_login"
    assert login["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/LoginRequest"
    }
    assert login["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserRead"
    }
    assert login["responses"]["401"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert logout["operationId"] == "auth_logout"
    assert logout["responses"]["204"]["description"] == "Successful Response"


def test_mcp_registry_openapi_contract() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()
    installed = schema["paths"]["/api/v1/mcp/registry/installed-servers"]["get"]
    installation_path = schema["paths"]["/api/v1/mcp/registry/installed-servers/{server_name}"]
    install = installation_path["put"]
    uninstall = installation_path["delete"]
    update = schema["paths"]["/api/v1/mcp/registry/installed-servers/updates"]["post"]
    list_servers = schema["paths"]["/api/v1/mcp/registry/servers"]["get"]
    get_version = schema["paths"][
        "/api/v1/mcp/registry/servers/{server_name}/versions/{version}"
    ]["get"]

    assert set(schema["paths"]["/api/v1/mcp/registry/servers"]) == {"get"}
    assert list_servers["operationId"] == "mcp_registry_list_servers"
    assert list_servers["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MCPRegistryServerListResponse"
    }
    assert installed["operationId"] == "mcp_registry_list_installed_servers"
    assert installed["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MCPServerInstallationListResponse"
    }
    assert install["operationId"] == "mcp_registry_install_server_version"
    assert install["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MCPServerInstallRequest"
    }
    assert uninstall["operationId"] == "mcp_registry_uninstall_server"
    assert uninstall["responses"]["204"]["description"] == "Successful Response"
    assert update["operationId"] == "mcp_registry_update_installed_servers"
    assert update["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MCPServerBulkUpdateRequest"
    }
    assert get_version["operationId"] == "mcp_registry_get_server_version"


def test_mcp_gateway_openapi_contract() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()
    gateway = schema["paths"]["/api/v1/mcp/gateway"]["post"]

    assert gateway["operationId"] == "mcp_gateway_rpc"


def test_user_openapi_schemas_do_not_expose_password_hashes() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()
    user_read_properties = schema["components"]["schemas"]["UserRead"]["properties"]
    user_create_properties = schema["components"]["schemas"]["BootstrapUserCreate"]["properties"]

    assert "password_hash" not in user_read_properties
    assert "local_credentials" not in user_read_properties
    assert "password" in user_create_properties
    assert user_create_properties["password"]["writeOnly"] is True
    assert user_create_properties["password"]["minLength"] == 8
