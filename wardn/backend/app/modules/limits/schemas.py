from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

LimitScopeType = Literal["organization", "workspace"]


class ResourceLimitUpsert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scope_type: LimitScopeType = Field(alias="scopeType")
    scope_id: UUID | None = Field(default=None, alias="scopeId")
    limit_key: str = Field(alias="limitKey", min_length=1, max_length=120)
    value: int = Field(ge=0)


class ResourceLimitRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    scope_type: str = Field(alias="scopeType")
    scope_id: UUID | None = Field(alias="scopeId")
    limit_key: str = Field(alias="limitKey")
    value: int
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ResourceLimitListResponse(BaseModel):
    limits: list[ResourceLimitRead]
