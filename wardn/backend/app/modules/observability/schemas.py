from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMModelPriceBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=255)
    input_usd_per_1m_tokens: Decimal = Field(alias="inputUsdPer1mTokens", ge=0)
    output_usd_per_1m_tokens: Decimal = Field(alias="outputUsdPer1mTokens", ge=0)
    cache_read_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        alias="cacheReadUsdPer1mTokens",
        ge=0,
    )
    cache_write_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        alias="cacheWriteUsdPer1mTokens",
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


class LLMModelPriceUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str | None = Field(default=None, min_length=1, max_length=50)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    input_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        alias="inputUsdPer1mTokens",
        ge=0,
    )
    output_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        alias="outputUsdPer1mTokens",
        ge=0,
    )
    cache_read_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        alias="cacheReadUsdPer1mTokens",
        ge=0,
    )
    cache_write_usd_per_1m_tokens: Decimal | None = Field(
        default=None,
        alias="cacheWriteUsdPer1mTokens",
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
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class LLMModelPriceListResponse(BaseModel):
    prices: list[LLMModelPriceRead]


class LLMUsageRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    organization_id: UUID = Field(alias="organizationId")
    workspace_id: UUID = Field(alias="workspaceId")
    user_id: UUID | None = Field(default=None, alias="userId")
    user_email: str = Field(alias="userEmail")
    user_display_name: str = Field(alias="userDisplayName")
    agent_id: UUID | None = Field(default=None, alias="agentId")
    agent_name: str = Field(alias="agentName")
    agent_run_id: UUID | None = Field(default=None, alias="agentRunId")
    provider: str
    model: str
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")
    total_tokens: int = Field(alias="totalTokens")
    cost_usd: Decimal = Field(alias="costUsd")
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    status: str
    trace_id: str = Field(alias="traceId")
    span_id: str = Field(alias="spanId")
    error: str


class LLMUsageSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_calls: int = Field(alias="totalCalls")
    succeeded: int
    failed: int
    running: int
    input_tokens: int = Field(alias="inputTokens")
    output_tokens: int = Field(alias="outputTokens")
    total_tokens: int = Field(alias="totalTokens")
    total_cost_usd: Decimal = Field(alias="totalCostUsd")
    attributed: int
    unattributed: int


class LLMUsageListResponse(BaseModel):
    summary: LLMUsageSummary
    records: list[LLMUsageRead]


class MCPToolUsageRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    organization_id: UUID | None = Field(default=None, alias="organizationId")
    workspace_id: UUID | None = Field(default=None, alias="workspaceId")
    runtime_session_id: UUID | None = Field(default=None, alias="runtimeSessionId")
    installation_id: UUID = Field(alias="installationId")
    user_id: UUID | None = Field(default=None, alias="userId")
    user_email: str = Field(alias="userEmail")
    user_display_name: str = Field(alias="userDisplayName")
    agent_id: UUID | None = Field(default=None, alias="agentId")
    agent_name: str = Field(alias="agentName")
    agent_run_id: UUID | None = Field(default=None, alias="agentRunId")
    server_name: str = Field(alias="serverName")
    server_version: str = Field(alias="serverVersion")
    tool_name: str = Field(alias="toolName")
    status: str
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    input_size_bytes: int = Field(alias="inputSizeBytes")
    output_size_bytes: int = Field(alias="outputSizeBytes")
    is_error: bool = Field(alias="isError")
    error: str


class MCPToolUsageSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total: int
    succeeded: int
    failed: int
    running: int
    attributed: int
    unattributed: int
    average_duration_ms: int | None = Field(default=None, alias="averageDurationMs")


class MCPToolUsageListResponse(BaseModel):
    summary: MCPToolUsageSummary
    tool_calls: list[MCPToolUsageRead] = Field(alias="toolCalls")
