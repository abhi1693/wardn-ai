import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SecretStoreProviderName = Literal["openbao"]
SecretPurpose = Literal[
    "llm_credential",
    "mcp_header",
    "mcp_env",
    "mcp_file",
    "oauth_token",
    "catalog_source",
    "runtime_config",
    "other",
]


class OpenBaoStoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    base_url: str = Field(alias="baseUrl", min_length=1, max_length=2048)
    kv_mount: str = Field(
        default="secret",
        alias="kvMount",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
    )
    timeout_seconds: float = Field(default=15.0, alias="timeoutSeconds", gt=0, le=60)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("kv_mount")
    @classmethod
    def normalize_kv_mount(cls, value: str) -> str:
        return value.strip().strip("/")


class OpenBaoStoreAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    profile: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SecretStoreCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    provider: SecretStoreProviderName = "openbao"
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    config: OpenBaoStoreConfig
    auth_config: OpenBaoStoreAuthConfig = Field(alias="authConfig")


class SecretStoreUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: OpenBaoStoreConfig | None = None
    auth_config: OpenBaoStoreAuthConfig | None = Field(default=None, alias="authConfig")
    is_active: bool | None = Field(default=None, alias="isActive")


class SecretStoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = Field(default=None, alias="organizationId")
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    created_by_id: uuid.UUID | None = Field(default=None, alias="createdById")
    provider: str
    name: str
    config: dict[str, Any]
    auth_config: dict[str, Any] = Field(alias="authConfig")
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class SecretStoreListResponse(BaseModel):
    stores: list[SecretStoreRead]


class SecretHandleCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    store_id: uuid.UUID = Field(alias="storeId")
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    purpose: SecretPurpose = "other"
    display_name: str = Field(alias="displayName", min_length=1, max_length=100)
    external_ref: str = Field(alias="externalRef", min_length=1, max_length=2048)
    key_name: str = Field(default="", alias="keyName", max_length=255)
    version: str = Field(default="", max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_strings(self) -> "SecretHandleCreate":
        self.display_name = " ".join(self.display_name.strip().split())
        self.external_ref = self.external_ref.strip().strip("/")
        self.key_name = self.key_name.strip()
        self.version = self.version.strip()
        return self


class SecretHandleUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    store_id: uuid.UUID | None = Field(default=None, alias="storeId")
    purpose: SecretPurpose | None = None
    display_name: str | None = Field(
        default=None,
        alias="displayName",
        min_length=1,
        max_length=100,
    )
    external_ref: str | None = Field(
        default=None,
        alias="externalRef",
        min_length=1,
        max_length=2048,
    )
    key_name: str | None = Field(default=None, alias="keyName", max_length=255)
    version: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None


class SecretHandleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID = Field(alias="organizationId")
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    store_id: uuid.UUID = Field(alias="storeId")
    created_by_id: uuid.UUID | None = Field(default=None, alias="createdById")
    purpose: str
    display_name: str = Field(alias="displayName")
    external_ref: str = Field(alias="externalRef")
    key_name: str = Field(alias="keyName")
    version: str
    metadata: dict[str, Any] = Field(alias="handleMetadata")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class SecretHandleListResponse(BaseModel):
    handles: list[SecretHandleRead]


class SecretValidationResponse(BaseModel):
    ok: bool
    message: str = ""
