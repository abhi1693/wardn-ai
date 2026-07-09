from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

LimitScopeType = Literal["organization", "workspace"]
UsageBudgetScopeType = Literal["organization", "workspace", "user", "agent"]
UsageBudgetUnit = Literal["cost_usd", "tokens", "requests"]
UsageBudgetPeriod = Literal["hour", "day", "month"]


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


class UsageBudgetUpsert(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    scope_type: UsageBudgetScopeType = Field(alias="scopeType")
    scope_id: UUID = Field(alias="scopeId")
    budget_key: str = Field(alias="budgetKey", min_length=1, max_length=120)
    value: Decimal = Field(ge=0)
    unit: UsageBudgetUnit | None = None
    period: UsageBudgetPeriod | None = None
    period_anchor: datetime | None = Field(default=None, alias="periodAnchor")
    model_filter: str = Field(default="", alias="modelFilter", max_length=255)


class UsageBudgetRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    scope_type: str = Field(alias="scopeType")
    scope_id: UUID = Field(alias="scopeId")
    budget_key: str = Field(alias="budgetKey")
    value: Decimal
    unit: str
    period: str
    period_anchor: datetime | None = Field(default=None, alias="periodAnchor")
    model_filter: str = Field(alias="modelFilter")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class UsageBudgetListResponse(BaseModel):
    budgets: list[UsageBudgetRead]
