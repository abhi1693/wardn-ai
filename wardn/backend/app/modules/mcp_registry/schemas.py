from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, SecretStr, field_validator

from app.core.pagination import CursorPageMetadata
from app.core.schemas import APIModel

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


class MCPFileConfigValue(APIModel):
    type: Literal["file"] = "file"
    filename: str = Field(default="", max_length=255)
    content: str = ""
    content_base64: str = ""
    path: str = Field(default="", max_length=4096)


class MCPSecretHandleConfigValue(APIModel):
    type: Literal["secret_handle"] = "secret_handle"
    secret_handle_id: UUID


MCPConfigValue = str | MCPFileConfigValue | MCPSecretHandleConfigValue


class MCPServerDocument(APIModel):
    model_config = ConfigDict(extra="allow")

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
    website_url: str = Field(default="", max_length=2048)
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


class MCPRegistryOfficialMetadata(APIModel):
    status: MCPServerStatus
    status_changed_at: datetime
    status_message: str | None = None
    published_at: datetime
    updated_at: datetime
    is_latest: bool


class MCPPulseServerVersionMetadata(APIModel):
    status: MCPServerStatus = "active"
    status_changed_at: datetime | None = None
    status_message: str | None = None
    published_at: datetime | None = None
    updated_at: datetime
    is_latest: bool = False


class MCPRegistryResponseMeta(APIModel):
    official: MCPRegistryOfficialMetadata = Field(alias="io.modelcontextprotocol.registry/official")


class MCPRegistryServerResponse(APIModel):
    server: MCPServerDocument
    meta: MCPRegistryResponseMeta = Field(alias="_meta")


class MCPRegistryListMetadata(APIModel):
    count: int
    next_cursor: str = ""


class MCPRegistryServerListResponse(APIModel):
    servers: list[MCPRegistryServerResponse]
    metadata: MCPRegistryListMetadata


class MCPServerInstallRequest(APIModel):
    version: str = Field(default="latest", min_length=1, max_length=255)
    config_name: str = Field(default="default", min_length=1, max_length=100)
    config_values: dict[str, MCPConfigValue] = Field(default_factory=dict)
    config_secret_store_id: UUID | None = None
    install_target: MCPServerInstallTarget | None = Field(
        default=None,
        max_length=50,
        pattern=r"^(remote|package)(:\d+)?$",
    )


class MCPServerBulkUpdateRequest(APIModel):
    server_names: list[str] = Field(min_length=1)


class MCPServerInstallationRead(APIModel):
    id: UUID
    workspace_id: UUID
    server_name: str
    config_name: str
    installed_version: str
    latest_version: str
    update_available: bool
    status: str
    install_type: str
    install_path: str
    runtime_config: dict[str, Any]
    configured_values: dict[str, str] = Field(default_factory=dict)
    install_error: str | None = None
    installed_at: datetime
    updated_at: datetime
    server: MCPServerDocument
    latest_server: MCPServerDocument


class MCPServerInstallationListResponse(APIModel):
    installations: list[MCPServerInstallationRead]
    metadata: CursorPageMetadata


class MCPOperationJobEventRead(APIModel):
    id: UUID
    event_type: str
    level: str
    message: str
    progress_current: int | None = None
    progress_total: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MCPOperationJobRead(APIModel):
    job_id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    operation: str
    resource_key: str
    status: MCPOperationJobStatus
    progress_current: int
    progress_total: int
    progress_message: str
    attempt_count: int
    max_attempts: int
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    cleanup_status: MCPOperationCleanupStatus
    cleanup_attempt_count: int
    cleanup_max_attempts: int
    cleanup_available_at: datetime | None = None
    cleanup_error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    events: list[MCPOperationJobEventRead] = Field(default_factory=list)


class MCPServerInstallationToolValidationRequest(APIModel):
    tool_name: str = Field(min_length=1, max_length=255)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPServerInstallationToolValidationResponse(APIModel):
    server_name: str
    config_name: str
    tool_name: str
    status: MCPServerValidationStatus
    is_error: bool
    error: str = ""
    result: dict[str, Any] | None = None
    validated_at: datetime


class MCPServerToolRead(APIModel):
    server_name: str
    server_version: str
    tool_name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)


class MCPServerInstallationToolsResponse(APIModel):
    server_name: str
    config_name: str
    server_version: str
    tools: list[MCPServerToolRead]
    cache: dict[str, Any] = Field(default_factory=dict)


class MCPCatalogSourceCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    provider: MCPCatalogSourceProvider = "wardn_hub"
    base_url: str = Field(min_length=1, max_length=2048)
    tenant_id: str = Field(default="", max_length=255)
    sync_mode: MCPCatalogSyncMode = "latest_only"
    is_enabled: bool = True
    api_token_secret_store_id: UUID | None = None
    api_token: SecretStr | None = None

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


class MCPCatalogSourceUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: MCPCatalogSourceProvider | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    tenant_id: str | None = Field(default=None, max_length=255)
    sync_mode: MCPCatalogSyncMode | None = None
    is_enabled: bool | None = None
    api_token_secret_store_id: UUID | None = None
    api_token: SecretStr | None = None

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


class MCPCatalogSourceRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    provider: str
    base_url: str
    tenant_id: str
    sync_mode: str
    last_success_at: datetime | None = None
    last_synced_updated_since: datetime | None = None
    last_error: str
    is_enabled: bool
    has_auth_token: bool
    created_at: datetime
    updated_at: datetime


class MCPCatalogSourceListResponse(APIModel):
    sources: list[MCPCatalogSourceRead]


class MCPCatalogSourceSyncResponse(APIModel):
    source: MCPCatalogSourceRead
    synced_count: int
