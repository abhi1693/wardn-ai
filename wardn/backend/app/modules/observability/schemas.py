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


class UsageSummaryWindow(APIModel):
    start_date: date
    end_date: date
    timezone: str
    breakdown_limit: int


class UsageSummaryResponse(APIModel):
    window: UsageSummaryWindow
    summary: UsageSummaryTotals
    by_user: list[UsageSummaryBreakdownRow]
    by_workspace: list[UsageSummaryBreakdownRow]
    by_agent: list[UsageSummaryBreakdownRow]
    by_model: list[UsageSummaryBreakdownRow]
    daily: list[UsageTrendPoint]


class OrganizationDashboardSummary(APIModel):
    health_score: int = Field(ge=0, le=100)
    workspaces: int
    active_workspaces: int
    members: int
    active_members: int
    requests: int
    request_success_rate: float
    failed_requests: int
    total_tokens: int
    cost_usd: Decimal
    projected_monthly_cost_usd: Decimal
    tool_calls: int
    tool_success_rate: float
    average_tool_duration_ms: int | None = None
    agents: int
    active_agents: int
    tools: int
    installed_servers: int
    enabled_servers: int
    servers_needing_attention: int
    server_updates: int
    runtime_sessions: int
    active_runtime_sessions: int
    runtime_sessions_needing_attention: int
    catalog_sources: int
    enabled_catalog_sources: int
    catalog_errors: int
    stale_catalog_sources: int
    provider_credentials: int
    active_provider_credentials: int
    resource_limits: int
    usage_budgets: int
    monthly_budget_usd: Decimal | None = None
    budget_utilization_percent: float | None = None


class OrganizationDashboardWorkspaceRow(APIModel):
    id: UUID
    name: str
    slug: str
    status: str
    requests: int
    failed_requests: int
    total_tokens: int
    cost_usd: Decimal
    tool_calls: int
    failed_tool_calls: int
    agents: int
    active_agents: int
    installations: int
    enabled_installations: int
    servers_needing_attention: int
    server_updates: int
    tool_count: int
    runtime_sessions: int
    active_runtime_sessions: int
    runtime_sessions_needing_attention: int
    latest_activity_at: datetime | None = None


class OrganizationDashboardRuntimeRow(APIModel):
    runtime: str
    label: str
    total: int
    enabled: int
    attention: int


class OrganizationDashboardCatalogHealth(APIModel):
    total: int
    enabled: int
    synced: int
    errors: int
    stale: int


class OrganizationDashboardProviderRow(APIModel):
    provider: str
    total: int
    active: int
    api_key: int
    oauth: int


class OrganizationDashboardToolRow(APIModel):
    id: str
    server_name: str
    tool_name: str
    workspace_id: UUID | None = None
    workspace_name: str
    calls: int
    failed: int
    error_rate: float
    average_duration_ms: int | None = None
    p95_duration_ms: int | None = None
    last_called_at: datetime | None = None


class OrganizationDashboardAttentionItem(APIModel):
    key: str
    label: str
    detail: str
    severity: str


class OrganizationDashboardResponse(APIModel):
    window: UsageSummaryWindow
    summary: OrganizationDashboardSummary
    daily: list[UsageTrendPoint]
    workspaces: list[OrganizationDashboardWorkspaceRow]
    top_models: list[UsageSummaryBreakdownRow]
    top_agents: list[UsageSummaryBreakdownRow]
    top_tools: list[OrganizationDashboardToolRow]
    runtime_mix: list[OrganizationDashboardRuntimeRow]
    catalog: OrganizationDashboardCatalogHealth
    providers: list[OrganizationDashboardProviderRow]
    attention: list[OrganizationDashboardAttentionItem]


class WorkspaceObservabilityDashboardSummary(APIModel):
    health_score: int = Field(ge=0, le=100)
    agent_runs: int
    failed_agent_runs: int
    running_agent_runs: int
    requests: int
    request_success_rate: float
    failed_requests: int
    total_tokens: int
    cost_usd: Decimal
    tool_calls: int
    tool_success_rate: float
    failed_tool_calls: int
    running_tool_calls: int
    average_tool_duration_ms: int | None = None
    p95_tool_duration_ms: int | None = None
    attributed_tool_calls: int
    unattributed_tool_calls: int
    attributed_llm_calls: int
    unattributed_llm_calls: int
    active_runtime_sessions: int
    runtime_sessions_needing_attention: int


class WorkspaceObservabilityTopToolRow(APIModel):
    id: str
    server_name: str
    tool_name: str
    calls: int
    failed: int
    error_rate: float
    average_duration_ms: int | None = None
    p95_duration_ms: int | None = None
    last_called_at: datetime | None = None


class WorkspaceObservabilityAgentRunRow(APIModel):
    id: UUID
    agent_id: UUID
    agent_name: str
    triggered_by_id: UUID | None = None
    triggered_by_email: str
    triggered_by_display_name: str
    trigger_type: str
    status: str
    requests: int
    failed_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal
    tool_calls: int
    failed_tool_calls: int
    trace_id: str
    span_id: str
    started_at: datetime
    finished_at: datetime | None = None
    error: str


class WorkspaceObservabilityAttentionItem(APIModel):
    key: str
    label: str
    detail: str
    severity: str
    href: str = ""


class WorkspaceObservabilityDashboardResponse(APIModel):
    window: UsageSummaryWindow
    summary: WorkspaceObservabilityDashboardSummary
    activity: list[UsageTrendPoint]
    attention: list[WorkspaceObservabilityAttentionItem]
    top_tools: list[WorkspaceObservabilityTopToolRow]
    top_models: list[UsageSummaryBreakdownRow]
    top_agents: list[UsageSummaryBreakdownRow]
    top_users: list[UsageSummaryBreakdownRow]
    recent_runs: list[WorkspaceObservabilityAgentRunRow]


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
