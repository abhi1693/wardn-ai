from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

MCP_SERVER_NAME_PATTERN = r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$"
MCPServerInstallTarget = str
MCPServerStatus = Literal["active", "deprecated", "deleted"]
MCPServerValidationStatus = Literal["passed", "failed"]
MCPCatalogSourceProvider = Literal["wardn_hub", "official", "pulsemcp", "custom"]
MCPCatalogSyncMode = Literal["latest_only", "all_versions"]
MCPOperationJobStatus = Literal["queued", "running", "succeeded", "failed"]
MCPOperationCleanupStatus = Literal[
    "not_required",
    "pending",
    "running",
    "succeeded",
    "failed",
]


class MCPFileConfigValue(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["file"] = "file"
    filename: str = Field(default="", max_length=255)
    content: str = ""
    content_base64: str = Field(default="", alias="contentBase64")
    path: str = Field(default="", max_length=4096)


class MCPSecretHandleConfigValue(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["secret_handle"] = "secret_handle"
    secret_handle_id: UUID = Field(alias="secretHandleId")


MCPConfigValue = str | MCPFileConfigValue | MCPSecretHandleConfigValue


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


class MCPPulseServerVersionMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: MCPServerStatus = "active"
    status_changed_at: datetime | None = Field(default=None, alias="statusChangedAt")
    status_message: str | None = Field(default=None, alias="statusMessage")
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    updated_at: datetime = Field(alias="updatedAt")
    is_latest: bool = Field(default=False, alias="isLatest")


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
    config_values: dict[str, MCPConfigValue] = Field(default_factory=dict, alias="configValues")
    config_secret_store_id: UUID | None = Field(default=None, alias="configSecretStoreId")
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
    workspace_id: UUID = Field(alias="workspaceId")
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


class MCPOperationJobEventRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    event_type: str = Field(alias="eventType")
    level: str
    message: str
    progress_current: int | None = Field(default=None, alias="progressCurrent")
    progress_total: int | None = Field(default=None, alias="progressTotal")
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(alias="createdAt")


class MCPOperationJobRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: UUID = Field(alias="jobId")
    organization_id: UUID = Field(alias="organizationId")
    workspace_id: UUID | None = Field(default=None, alias="workspaceId")
    operation: str
    resource_key: str = Field(alias="resourceKey")
    status: MCPOperationJobStatus
    progress_current: int = Field(alias="progressCurrent")
    progress_total: int = Field(alias="progressTotal")
    progress_message: str = Field(alias="progressMessage")
    attempt_count: int = Field(alias="attemptCount")
    max_attempts: int = Field(alias="maxAttempts")
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str = Field(default="", alias="errorCode")
    error_message: str = Field(default="", alias="errorMessage")
    cleanup_status: MCPOperationCleanupStatus = Field(alias="cleanupStatus")
    cleanup_attempt_count: int = Field(alias="cleanupAttemptCount")
    cleanup_error: str = Field(default="", alias="cleanupError")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    completed_at: datetime | None = Field(default=None, alias="completedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    events: list[MCPOperationJobEventRead] = Field(default_factory=list)


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


class MCPCatalogSourceCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    provider: MCPCatalogSourceProvider = "wardn_hub"
    base_url: str = Field(alias="baseUrl", min_length=1, max_length=2048)
    tenant_id: str = Field(default="", alias="tenantId", max_length=255)
    sync_mode: MCPCatalogSyncMode = Field(default="latest_only", alias="syncMode")
    is_enabled: bool = Field(default=True, alias="isEnabled")
    api_token_secret_store_id: UUID | None = Field(
        default=None,
        alias="apiTokenSecretStoreId",
    )
    api_token: SecretStr | None = Field(default=None, alias="apiToken")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("Catalog URL must start with http:// or https://")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return value.strip()


class MCPCatalogSourceUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: MCPCatalogSourceProvider | None = None
    base_url: str | None = Field(default=None, alias="baseUrl", min_length=1, max_length=2048)
    tenant_id: str | None = Field(default=None, alias="tenantId", max_length=255)
    sync_mode: MCPCatalogSyncMode | None = Field(default=None, alias="syncMode")
    is_enabled: bool | None = Field(default=None, alias="isEnabled")
    api_token_secret_store_id: UUID | None = Field(
        default=None,
        alias="apiTokenSecretStoreId",
    )
    api_token: SecretStr | None = Field(default=None, alias="apiToken")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("Catalog URL must start with http:// or https://")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class MCPCatalogSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    organization_id: UUID = Field(alias="organizationId")
    name: str
    provider: str
    base_url: str = Field(alias="baseUrl")
    tenant_id: str = Field(alias="tenantId")
    sync_mode: str = Field(alias="syncMode")
    last_success_at: datetime | None = Field(default=None, alias="lastSuccessAt")
    last_synced_updated_since: datetime | None = Field(
        default=None,
        alias="lastSyncedUpdatedSince",
    )
    last_error: str = Field(alias="lastError")
    is_enabled: bool = Field(alias="isEnabled")
    has_auth_token: bool = Field(alias="hasAuthToken")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class MCPCatalogSourceListResponse(BaseModel):
    sources: list[MCPCatalogSourceRead]


class MCPCatalogSourceSyncResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: MCPCatalogSourceRead
    synced_count: int = Field(alias="syncedCount")
