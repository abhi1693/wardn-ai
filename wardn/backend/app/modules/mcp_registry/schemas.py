from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MCP_SERVER_NAME_PATTERN = r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$"
MCPServerInstallTarget = str
MCPServerStatus = Literal["active", "deprecated", "deleted"]
MCPServerValidationStatus = Literal["passed", "failed"]


class MCPServerDocument(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_uri: str = Field(
        alias="$schema",
        min_length=1,
        examples=["https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"],
    )
    name: str = Field(min_length=3, max_length=200, pattern=MCP_SERVER_NAME_PATTERN)
    description: str = Field(min_length=1)
    title: str = Field(default="", max_length=100)
    repository: dict[str, Any] | None = None
    version: str = Field(min_length=1, max_length=255)
    website_url: str = Field(default="", alias="websiteUrl", max_length=2048)
    icons: list[dict[str, Any]] = Field(default_factory=list)
    packages: list[dict[str, Any]] = Field(default_factory=list)
    remotes: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")

    @field_validator("packages")
    @classmethod
    def reject_unsupported_packages(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unsupported = [
            str(package.get("registryType") or "")
            for package in value
            if isinstance(package, dict)
            and str(package.get("registryType") or "").casefold() == "mcpb"
        ]
        if unsupported:
            raise ValueError("MCPB package registry is not supported")
        return value


class MCPServerCreate(MCPServerDocument):
    pass


class MCPRegistryOfficialMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: MCPServerStatus
    status_changed_at: datetime = Field(alias="statusChangedAt")
    status_message: str | None = Field(default=None, alias="statusMessage")
    published_at: datetime = Field(alias="publishedAt")
    updated_at: datetime = Field(alias="updatedAt")
    is_latest: bool = Field(alias="isLatest")


class MCPRegistryResponseMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    official: MCPRegistryOfficialMetadata = Field(
        alias="io.modelcontextprotocol.registry/official"
    )


class MCPRegistryServerResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server: MCPServerDocument
    meta: MCPRegistryResponseMeta = Field(alias="_meta")


class MCPRegistryListMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    count: int
    next_cursor: str = Field(default="", alias="nextCursor")


class MCPRegistryServerListResponse(BaseModel):
    servers: list[MCPRegistryServerResponse]
    metadata: MCPRegistryListMetadata


class MCPServerInstallRequest(BaseModel):
    version: str = Field(default="latest", min_length=1, max_length=255)
    config_name: str = Field(default="default", alias="configName", min_length=1, max_length=100)
    config_values: dict[str, str] = Field(default_factory=dict, alias="configValues")
    install_target: MCPServerInstallTarget | None = Field(
        default=None,
        alias="installTarget",
        max_length=50,
        pattern=r"^(remote|package)(:\d+)?$",
    )


class MCPServerBulkUpdateRequest(BaseModel):
    server_names: list[str] = Field(alias="serverNames", min_length=1)


class MCPServerInstallationRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    server_name: str = Field(alias="serverName")
    config_name: str = Field(alias="configName")
    installed_version: str = Field(alias="installedVersion")
    latest_version: str = Field(alias="latestVersion")
    update_available: bool = Field(alias="updateAvailable")
    status: str
    install_type: str = Field(alias="installType")
    install_path: str = Field(alias="installPath")
    runtime_config: dict[str, Any] = Field(alias="runtimeConfig")
    configured_values: dict[str, str] = Field(default_factory=dict, alias="configuredValues")
    install_error: str | None = Field(default=None, alias="installError")
    installed_at: datetime = Field(alias="installedAt")
    updated_at: datetime = Field(alias="updatedAt")
    server: MCPServerDocument
    latest_server: MCPServerDocument = Field(alias="latestServer")


class MCPServerInstallationListResponse(BaseModel):
    installations: list[MCPServerInstallationRead]


class MCPServerInstallationToolValidationRequest(BaseModel):
    tool_name: str = Field(alias="toolName", min_length=1, max_length=255)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPServerInstallationToolValidationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server_name: str = Field(alias="serverName")
    config_name: str = Field(alias="configName")
    tool_name: str = Field(alias="toolName")
    status: MCPServerValidationStatus
    is_error: bool = Field(alias="isError")
    error: str = ""
    result: dict[str, Any] | None = None
    validated_at: datetime = Field(alias="validatedAt")


class MCPServerToolRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server_name: str = Field(alias="serverName")
    server_version: str = Field(alias="serverVersion")
    tool_name: str = Field(alias="toolName")
    title: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")
    annotations: dict[str, Any] = Field(default_factory=dict)


class MCPServerInstallationToolsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server_name: str = Field(alias="serverName")
    config_name: str = Field(alias="configName")
    server_version: str = Field(alias="serverVersion")
    tools: list[MCPServerToolRead]
    cache: dict[str, Any] = Field(default_factory=dict)
