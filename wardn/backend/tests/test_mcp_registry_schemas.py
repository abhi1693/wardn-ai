from app.modules.mcp_registry.schemas import MCPServerCreate


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
