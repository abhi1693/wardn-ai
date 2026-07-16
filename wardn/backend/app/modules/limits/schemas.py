from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.schemas import APIModel

LimitScopeType = Literal["organization", "workspace"]
UsageBudgetScopeType = Literal["organization", "workspace", "user", "agent"]
UsageBudgetUnit = Literal["cost_usd", "tokens", "requests"]
UsageBudgetPeriod = Literal["hour", "day", "month"]


class ResourceLimitUpsert(APIModel):
    scope_type: LimitScopeType
    scope_id: UUID | None = None
    limit_key: str = Field(min_length=1, max_length=120)
    value: int = Field(ge=0)


class ResourceLimitRead(APIModel):
    id: UUID
    scope_type: str
    scope_id: UUID | None
    limit_key: str
    value: int
    created_at: datetime
    updated_at: datetime


class ResourceLimitListResponse(APIModel):
    limits: list[ResourceLimitRead]


class UsageBudgetUpsert(APIModel):
    scope_type: UsageBudgetScopeType
    scope_id: UUID
    budget_key: str = Field(min_length=1, max_length=120)
    value: Decimal = Field(ge=0)
    unit: UsageBudgetUnit | None = None
    period: UsageBudgetPeriod | None = None
    period_anchor: datetime | None = None
    model_filter: str = Field(default="", max_length=255)


class UsageBudgetRead(APIModel):
    id: UUID
    scope_type: str
    scope_id: UUID
    budget_key: str
    value: Decimal
    unit: str
    period: str
    period_anchor: datetime | None = None
    model_filter: str
    created_at: datetime
    updated_at: datetime


class UsageBudgetListResponse(APIModel):
    budgets: list[UsageBudgetRead]
