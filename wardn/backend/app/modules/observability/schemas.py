from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field, field_validator

from app.core.schemas import APIModel


class LLMModelPriceBase(APIModel):
    provider: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=255)
    input_usd_per_1m_tokens: Decimal = Field(ge=0)
    output_usd_per_1m_tokens: Decimal = Field(ge=0)
    cache_read_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        ge=0,
    )
    cache_write_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        ge=0,
    )

    @field_validator("provider", "model")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped


class LLMModelPriceCreate(LLMModelPriceBase):
    pass


class LLMModelPriceUpdate(APIModel):
    provider: str | None = Field(default=None, min_length=1, max_length=50)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    input_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        ge=0,
    )
    output_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        ge=0,
    )
    cache_read_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        ge=0,
    )
    cache_write_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        ge=0,
    )

    @field_validator("provider", "model")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty")
        return stripped


class LLMModelPriceRead(LLMModelPriceBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class LLMModelPriceListResponse(APIModel):
    prices: list[LLMModelPriceRead]


class LLMModelPricePrefillResponse(APIModel):
    found: bool
    provider: str
    model: str
    input_usd_per_1m_tokens: Decimal | None = None
    output_usd_per_1m_tokens: Decimal | None = None
    cache_read_usd_per_1m_tokens: Decimal | None = None
    cache_write_usd_per_1m_tokens: Decimal | None = None
    source: str = ""
    source_model_id: str = ""
    source_model_name: str = ""


class LLMUsageRead(APIModel):
    id: UUID
    organization_id: UUID
    workspace_id: UUID
    user_id: UUID | None = None
    user_email: str
    user_display_name: str
    agent_id: UUID | None = None
    agent_name: str
    agent_run_id: UUID | None = None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    trace_id: str
    span_id: str
    error: str


class LLMUsageSummary(APIModel):
    total_calls: int
    succeeded: int
    failed: int
    running: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost_usd: Decimal
    attributed: int
    unattributed: int


class LLMUsageListResponse(APIModel):
    summary: LLMUsageSummary
    records: list[LLMUsageRead]


class UsageSummaryTotals(APIModel):
    requests: int
    succeeded: int
    failed: int
    running: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal
    tool_calls: int


class UsageSummaryBreakdownRow(APIModel):
    id: str
    label: str
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal
    tool_calls: int


class UsageTrendPoint(APIModel):
    date: date
    requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal
    tool_calls: int


class UsageSummaryResponse(APIModel):
    summary: UsageSummaryTotals
    by_user: list[UsageSummaryBreakdownRow]
    by_workspace: list[UsageSummaryBreakdownRow]
    by_agent: list[UsageSummaryBreakdownRow]
    by_model: list[UsageSummaryBreakdownRow]
    daily: list[UsageTrendPoint]


class MCPToolUsageRead(APIModel):
    id: UUID
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    runtime_session_id: UUID | None = None
    installation_id: UUID
    user_id: UUID | None = None
    user_email: str
    user_display_name: str
    agent_id: UUID | None = None
    agent_name: str
    agent_run_id: UUID | None = None
    server_name: str
    server_version: str
    tool_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    input_size_bytes: int
    output_size_bytes: int
    is_error: bool
    error: str


class MCPToolUsageSummary(APIModel):
    total: int
    succeeded: int
    failed: int
    running: int
    attributed: int
    unattributed: int
    average_duration_ms: int | None = None


class MCPToolUsageListResponse(APIModel):
    summary: MCPToolUsageSummary
    tool_calls: list[MCPToolUsageRead]
