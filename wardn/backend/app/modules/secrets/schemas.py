import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.schemas import APIModel

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


class OpenBaoStoreConfig(APIModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1, max_length=2048)
    kv_mount: str = Field(
        default="secret",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
    )
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("kv_mount")
    @classmethod
    def normalize_kv_mount(cls, value: str) -> str:
        return value.strip().strip("/")


class OpenBaoStoreAuthConfig(APIModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SecretStoreCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    provider: SecretStoreProviderName = "openbao"
    workspace_id: uuid.UUID | None = None
    config: OpenBaoStoreConfig
    auth_config: OpenBaoStoreAuthConfig


class SecretStoreUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: OpenBaoStoreConfig | None = None
    auth_config: OpenBaoStoreAuthConfig | None = None
    is_active: bool | None = None


class SecretStoreRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    created_by_id: uuid.UUID | None = None
    provider: str
    name: str
    config: dict[str, Any]
    auth_config: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SecretStoreListResponse(APIModel):
    stores: list[SecretStoreRead]


class SecretHandleCreate(APIModel):
    store_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    purpose: SecretPurpose = "other"
    display_name: str = Field(min_length=1, max_length=100)
    external_ref: str = Field(min_length=1, max_length=2048)
    key_name: str = Field(default="", max_length=255)
    version: str = Field(default="", max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_strings(self) -> "SecretHandleCreate":
        self.display_name = " ".join(self.display_name.strip().split())
        self.external_ref = self.external_ref.strip().strip("/")
        self.key_name = self.key_name.strip()
        self.version = self.version.strip()
        return self


class SecretHandleUpdate(APIModel):
    store_id: uuid.UUID | None = None
    purpose: SecretPurpose | None = None
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    external_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
    )
    key_name: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None


class SecretHandleRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    store_id: uuid.UUID
    created_by_id: uuid.UUID | None = None
    purpose: str
    display_name: str
    external_ref: str
    key_name: str
    version: str
    metadata: dict[str, Any] = Field(alias="handleMetadata")
    created_at: datetime
    updated_at: datetime


class SecretHandleListResponse(APIModel):
    handles: list[SecretHandleRead]


class SecretValidationResponse(APIModel):
    ok: bool
    message: str = ""
