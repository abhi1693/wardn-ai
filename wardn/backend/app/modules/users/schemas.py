import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    display_name: str
    is_active: bool
    is_superuser: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=8)
    first_name: str = Field(default="", max_length=150)
    last_name: str = Field(default="", max_length=150)


class BootstrapUserCreate(UserCreate):
    pass


class UserAPITokenCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=200)
    expires_at: datetime | None = None
    organization_ids: list[uuid.UUID] = Field(default_factory=list, alias="organizationIds")
    workspace_ids: list[uuid.UUID] = Field(default_factory=list, alias="workspaceIds")


class UserAPITokenUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=200)
    expires_at: datetime | None = None
    organization_ids: list[uuid.UUID] | None = Field(default=None, alias="organizationIds")
    workspace_ids: list[uuid.UUID] | None = Field(default=None, alias="workspaceIds")
    is_active: bool | None = None


class UserAPITokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str
    token_prefix: str
    organization_ids: list[uuid.UUID] = Field(alias="organizationIds")
    workspace_ids: list[uuid.UUID] = Field(alias="workspaceIds")
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserAPITokenCreated(BaseModel):
    token: str
    record: UserAPITokenRead


class UserAPITokenListResponse(BaseModel):
    tokens: list[UserAPITokenRead]


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr


class AuthConfigRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    auth_mode: Literal["local", "oidc"] = Field(alias="authMode")
    local_login_enabled: bool = Field(alias="localLoginEnabled")
    oidc_login_enabled: bool = Field(alias="oidcLoginEnabled")
    oidc_provider_name: str = Field(alias="oidcProviderName")
