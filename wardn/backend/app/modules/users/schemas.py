import uuid
from datetime import datetime

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
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=200)
    expires_at: datetime | None = None


class UserAPITokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str
    token_prefix: str
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserAPITokenCreated(BaseModel):
    token: str
    record: UserAPITokenRead


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr
