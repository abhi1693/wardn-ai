from fastapi.testclient import TestClient

from app.main import create_app


def test_openapi_exposes_expected_paths() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"].startswith("3.")
    assert set(schema["paths"]) == {
        "/api/v1/auth/api-tokens",
        "/api/v1/auth/api-tokens/{token_id}",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/mcp/gateway",
        "/api/v1/organizations",
        "/api/v1/organizations/{organization_id}",
        "/api/v1/organizations/{organization_id}/mcp/registry/servers",
        (
            "/api/v1/organizations/{organization_id}/mcp/registry/servers"
            "/{server_name}/versions"
        ),
        (
            "/api/v1/organizations/{organization_id}/mcp/registry/servers"
            "/{server_name}/versions/{version}"
        ),
        (
            "/api/v1/organizations/{organization_id}/mcp/registry/servers"
            "/{server_name}/versions/{version}/default"
        ),
        "/api/v1/organizations/{organization_id}/workspaces",
        "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}",
        "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/mcp/gateway",
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/sessions"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/sessions/{runtime_session_id}"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/sessions/{runtime_session_id}/events"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/sessions/{runtime_session_id}/health"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/sessions/{runtime_session_id}/stop"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/summary"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-server-configs/{installation_id}"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-server-configs/{installation_id}/tools"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-server-configs/{installation_id}/validate-tool"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-servers"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-servers/updates"
        ),
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-servers/{server_name}"
        ),
        "/api/v1/users/bootstrap",
    }


def test_only_top_level_mcp_gateway_route_is_mounted() -> None:
    client = TestClient(create_app())

    assert client.post("/api/v1/mcp/gateway", json={}).status_code == 401
    assert client.get("/api/v1/mcp/runtime/sessions").status_code == 404
    assert client.get("/api/v1/mcp/registry/servers").status_code == 404
    assert client.get("/api/v1/mcp/registry/installed-servers").status_code == 404


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
    api_tokens = schema["paths"]["/api/v1/auth/api-tokens"]
    api_token = schema["paths"]["/api/v1/auth/api-tokens/{token_id}"]
    login = schema["paths"]["/api/v1/auth/login"]["post"]
    logout = schema["paths"]["/api/v1/auth/logout"]["post"]

    assert api_tokens["get"]["operationId"] == "auth_list_api_tokens"
    assert api_tokens["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserAPITokenListResponse"
    }
    assert api_tokens["post"]["operationId"] == "auth_create_api_token"
    assert api_tokens["post"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserAPITokenCreate"
    }
    assert api_tokens["post"]["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserAPITokenCreated"
    }
    assert api_token["patch"]["operationId"] == "auth_update_api_token"
    assert api_token["patch"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserAPITokenUpdate"
    }
    assert api_token["patch"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserAPITokenRead"
    }
    assert api_token["delete"]["operationId"] == "auth_delete_api_token"
    assert api_token["delete"]["responses"]["204"]["description"] == "Successful Response"
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
    organization_servers_path = schema["paths"][
        "/api/v1/organizations/{organization_id}/mcp/registry/servers"
    ]
    organization_version_path = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/mcp/registry/servers"
            "/{server_name}/versions/{version}"
        )
    ]
    organization_default_version_path = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/mcp/registry/servers"
            "/{server_name}/versions/{version}/default"
        )
    ]
    workspace_installed = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-servers"
        )
    ]["get"]
    workspace_installed_config_path = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-server-configs/{installation_id}"
        )
    ]
    workspace_installed_config_validation = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-server-configs/{installation_id}/validate-tool"
        )
    ]["post"]
    workspace_installed_config_tools = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-server-configs/{installation_id}/tools"
        )
    ]["get"]
    workspace_installation_path = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-servers/{server_name}"
        )
    ]
    workspace_install = workspace_installation_path["put"]
    workspace_uninstall = workspace_installation_path["delete"]
    workspace_update = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/registry/installed-servers/updates"
        )
    ]["post"]

    assert not any(path.startswith("/api/v1/mcp/registry") for path in schema["paths"])
    assert (
        organization_servers_path["get"]["operationId"]
        == "organization_mcp_registry_list_servers"
    )
    assert (
        organization_servers_path["post"]["operationId"]
        == "organization_mcp_registry_create_server_version"
    )
    assert (
        organization_version_path["get"]["operationId"]
        == "organization_mcp_registry_get_server_version"
    )
    assert (
        organization_version_path["put"]["operationId"]
        == "organization_mcp_registry_update_server_version"
    )
    assert (
        organization_version_path["delete"]["operationId"]
        == "organization_mcp_registry_delete_server_version"
    )
    assert (
        organization_default_version_path["post"]["operationId"]
        == "organization_mcp_registry_set_default_server_version"
    )
    assert workspace_installed["operationId"] == "workspace_mcp_registry_list_installed_servers"
    assert workspace_installed["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MCPServerInstallationListResponse"
    }
    assert workspace_install["operationId"] == "workspace_mcp_registry_install_server_version"
    assert workspace_install["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MCPServerInstallRequest"
    }
    assert workspace_uninstall["operationId"] == "workspace_mcp_registry_uninstall_server"
    assert workspace_uninstall["responses"]["204"]["description"] == "Successful Response"
    assert (
        workspace_installed_config_path["delete"]["operationId"]
        == "workspace_mcp_registry_uninstall_server_config"
    )
    assert (
        workspace_installed_config_path["delete"]["responses"]["204"]["description"]
        == "Successful Response"
    )
    assert (
        workspace_installed_config_validation["operationId"]
        == "workspace_mcp_registry_validate_installed_server_tool"
    )
    assert (
        workspace_installed_config_validation["requestBody"]["content"]["application/json"][
            "schema"
        ]
        == {"$ref": "#/components/schemas/MCPServerInstallationToolValidationRequest"}
    )
    assert (
        workspace_installed_config_validation["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        == {"$ref": "#/components/schemas/MCPServerInstallationToolValidationResponse"}
    )
    assert (
        workspace_installed_config_tools["operationId"]
        == "workspace_mcp_registry_list_installed_server_tools"
    )
    assert (
        workspace_installed_config_tools["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        == {"$ref": "#/components/schemas/MCPServerInstallationToolsResponse"}
    )
    assert (
        workspace_installed_config_tools["responses"]["502"]["content"]["application/json"][
            "schema"
        ]
        == {"$ref": "#/components/schemas/ErrorResponse"}
    )
    assert workspace_update["operationId"] == "workspace_mcp_registry_update_installed_servers"
    assert workspace_update["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MCPServerBulkUpdateRequest"
    }


def test_mcp_gateway_openapi_contract() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()
    top_level_gateway = schema["paths"]["/api/v1/mcp/gateway"]["post"]
    gateway = schema["paths"][
        "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/mcp/gateway"
    ]["post"]

    assert top_level_gateway["operationId"] == "mcp_gateway_rpc"
    assert [param["name"] for param in top_level_gateway["parameters"]] == [
        "authorization",
    ]
    assert gateway["operationId"] == "workspace_mcp_gateway_rpc"


def test_mcp_runtime_openapi_contract() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()
    workspace_sessions_path = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/sessions"
        )
    ]
    workspace_stop_path = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/sessions/{runtime_session_id}/stop"
        )
    ]
    workspace_events_path = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/sessions/{runtime_session_id}/events"
        )
    ]
    workspace_summary_path = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/workspaces/{workspace_id}"
            "/mcp/runtime/summary"
        )
    ]

    assert not any(path.startswith("/api/v1/mcp/runtime") for path in schema["paths"])
    assert (
        workspace_sessions_path["get"]["operationId"]
        == "workspace_mcp_runtime_list_sessions"
    )
    assert workspace_stop_path["post"]["operationId"] == "workspace_mcp_runtime_stop_session"
    assert (
        workspace_events_path["get"]["operationId"]
        == "workspace_mcp_runtime_list_session_events"
    )
    assert (
        workspace_summary_path["get"]["operationId"]
        == "workspace_mcp_runtime_get_summary"
    )


def test_user_openapi_schemas_do_not_expose_password_hashes() -> None:
    schema = TestClient(create_app()).get("/api/v1/openapi.json").json()
    user_read_properties = schema["components"]["schemas"]["UserRead"]["properties"]
    user_create_properties = schema["components"]["schemas"]["BootstrapUserCreate"]["properties"]

    assert "password_hash" not in user_read_properties
    assert "local_credentials" not in user_read_properties
    assert "password" in user_create_properties
    assert user_create_properties["password"]["writeOnly"] is True
    assert user_create_properties["password"]["minLength"] == 8
