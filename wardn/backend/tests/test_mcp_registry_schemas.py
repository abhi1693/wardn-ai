from uuid import UUID

from app.modules.mcp_registry.schemas import MCPServerCreate, MCPServerInstallRequest


def test_mcp_server_document_preserves_official_aliases() -> None:
    payload = MCPServerCreate(
        **{
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/weather",
            "title": "Weather",
            "description": "Weather tools for forecasts",
            "version": "1.0.0",
            "websiteUrl": "https://example.com/weather",
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@example/weather-mcp",
                    "version": "1.0.0",
                    "transport": {"type": "stdio"},
                }
            ],
            "_meta": {
                "io.modelcontextprotocol.registry/publisher-provided": {"category": "weather"}
            },
        }
    )

    serialized = payload.model_dump(by_alias=True, exclude_none=True)

    assert serialized["$schema"].endswith("/server.schema.json")
    assert serialized["websiteUrl"] == "https://example.com/weather"
    assert serialized["_meta"]["io.modelcontextprotocol.registry/publisher-provided"] == {
        "category": "weather"
    }


def test_mcp_server_name_requires_namespace() -> None:
    error = None
    try:
        MCPServerCreate(
            **{
                "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
                "name": "weather",
                "description": "Weather tools for forecasts",
                "version": "1.0.0",
            }
        )
    except ValueError as exc:
        error = exc

    assert error is not None


def test_mcp_server_description_accepts_text_field_length() -> None:
    description = "MCP server for enterprise workflow automation. " * 10

    payload = MCPServerCreate(
        **{
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
            "name": "io.github.example/automation",
            "description": description,
            "version": "1.0.0",
        }
    )

    assert payload.description == description


def test_install_request_accepts_secret_handle_file_content() -> None:
    handle_id = "11111111-1111-4111-8111-111111111111"

    payload = MCPServerInstallRequest(
        configValues={
            "KUBECONFIG": {
                "type": "file",
                "filename": "config",
                "content": {
                    "type": "secret_handle",
                    "secretHandleId": handle_id,
                },
            }
        }
    )

    file_value = payload.config_values["KUBECONFIG"]
    assert not isinstance(file_value, str)
    assert not isinstance(file_value.content, str)
    assert file_value.content.secret_handle_id == UUID(handle_id)
    assert payload.model_dump(mode="json", by_alias=True)["configValues"] == {
        "KUBECONFIG": {
            "type": "file",
            "filename": "config",
            "content": {
                "type": "secret_handle",
                "secretHandleId": handle_id,
            },
            "contentBase64": "",
            "path": "",
        }
    }


def test_install_request_accepts_domain_custom_egress() -> None:
    payload = MCPServerInstallRequest(
        networkPolicy={
            "denyOtherEgress": True,
            "customEgress": [
                {
                    "destinationType": "domain",
                    "label": "vendor-api",
                    "domain": "API.Example.COM.",
                    "ports": [443, 8443, 443],
                },
            ],
        }
    )

    assert payload.model_dump(mode="json", by_alias=True)["networkPolicy"][
        "customEgress"
    ] == [
        {
            "destinationType": "domain",
            "label": "vendor-api",
            "cidr": "",
            "domain": "api.example.com",
            "ports": [443, 8443],
        }
    ]

    error = None
    try:
        MCPServerInstallRequest(
            networkPolicy={
                "denyOtherEgress": True,
                "customEgress": [
                    {
                        "destinationType": "domain",
                        "domain": "192.168.3.1",
                        "ports": [443],
                    },
                ],
            }
        )
    except ValueError as exc:
        error = exc

    assert error is not None


def test_mcp_server_document_rejects_mcpb_packages() -> None:
    error = None
    try:
        MCPServerCreate(
            **{
                "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
                "name": "io.github.example/bundle",
                "description": "Unsupported MCPB package server.",
                "version": "1.0.0",
                "packages": [
                    {
                        "registryType": "mcpb",
                        "identifier": "example.mcpb",
                        "version": "1.0.0",
                    }
                ],
            }
        )
    except ValueError as exc:
        error = exc

    assert error is not None
    assert "MCPB package registry is not supported" in str(error)
