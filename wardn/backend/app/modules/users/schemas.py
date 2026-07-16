import uuid
from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, EmailStr, Field, SecretStr

from app.core.schemas import APIModel


class UserRead(APIModel):
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


class UserCreate(APIModel):
    email: EmailStr
    password: SecretStr = Field(min_length=8)
    first_name: str = Field(default="", max_length=150)
    last_name: str = Field(default="", max_length=150)


class BootstrapUserCreate(UserCreate):
    pass


class UserAPITokenCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=200)
    expires_at: datetime | None = None
    organization_ids: list[uuid.UUID] = Field(default_factory=list)
    workspace_ids: list[uuid.UUID] = Field(default_factory=list)


class UserAPITokenUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=200)
    expires_at: datetime | None = None
    organization_ids: list[uuid.UUID] | None = None
    workspace_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None


class UserAPITokenRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str
    token_prefix: str
    organization_ids: list[uuid.UUID]
    workspace_ids: list[uuid.UUID]
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserAPITokenCreated(APIModel):
    token: str
    record: UserAPITokenRead


class UserAPITokenListResponse(APIModel):
    tokens: list[UserAPITokenRead]


class LoginRequest(APIModel):
    email: EmailStr
    password: SecretStr


class AuthConfigRead(APIModel):
    auth_mode: Literal["local", "oidc"]
    local_login_enabled: bool
    oidc_login_enabled: bool
    oidc_provider_name: str
