import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.core.pagination import CursorPageMetadata
from app.core.schemas import APIModel

AgentScope = Literal["workspace"]


class WorkspaceAgentModelUpdate(APIModel):
    provider_credential_id: uuid.UUID
    model_name: str = Field(min_length=1, max_length=255)


class AgentSkillUpdateRequest(APIModel):
    skill_ids: list[str] = Field(default_factory=list)


class AgentRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    created_by_id: uuid.UUID | None = None
    provider_credential_id: uuid.UUID | None = None
    name: str
    description: str
    instructions: str
    scope: AgentScope
    model_name: str
    skill_ids: list[str] = Field(default_factory=list)
    is_active: bool
    server_count: int
    tool_count: int
    created_at: datetime
    updated_at: datetime


class AgentListResponse(APIModel):
    agents: list[AgentRead]
    metadata: CursorPageMetadata


class WorkspaceConversationRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    created_by_id: uuid.UUID | None = None
    title: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ConversationMessageRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    agent_run_id: uuid.UUID | None = None
    role: Literal["system", "user", "assistant"]
    content: str
    parts: list[dict[str, Any]] = Field(default_factory=list)
    sequence: int
    created_at: datetime
    updated_at: datetime


class AgentConversationResponse(APIModel):
    agent: AgentRead
    conversation: WorkspaceConversationRead
    messages: list[ConversationMessageRead] = Field(default_factory=list)


class AgentRunRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    triggered_by_id: uuid.UUID | None = None
    trigger_type: str
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Decimal = Field(default=Decimal("0"))
    tool_calls: int = 0
    trace_id: str = ""
    span_id: str = ""
    started_at: datetime
    finished_at: datetime | None = None
    error: str
    created_at: datetime
    updated_at: datetime


class AgentRunStepRead(APIModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_run_id: uuid.UUID
    mcp_tool_invocation_id: uuid.UUID | None = None
    sequence: int
    step_type: str
    status: str
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AgentRunListResponse(APIModel):
    runs: list[AgentRunRead]


class AgentRunDetailResponse(APIModel):
    run: AgentRunRead
    steps: list[AgentRunStepRead]


class AgentToolApprovalDecisionRequest(APIModel):
    decision: Literal["approve", "deny"]


class AgentToolApprovalDecisionResponse(APIModel):
    approval_id: uuid.UUID
    status: str
    tool_name: str
    result: str = ""
    error: str = ""
    assistant_message: ConversationMessageRead | None = None


class AgentToolApprovalRead(APIModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    requested_by_id: uuid.UUID | None = None
    decided_by_id: uuid.UUID | None = None
    installation_id: uuid.UUID
    tool_schema_id: uuid.UUID
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: str
    result: str = ""
    error: str = ""
    approval_url: str
    action_review: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class AgentAvailableToolRead(APIModel):
    tool_schema_id: uuid.UUID
    installation_id: uuid.UUID
    workspace_id: uuid.UUID
    server_name: str
    config_name: str
    tool_name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)


class AgentAvailableServerRead(APIModel):
    installation_id: uuid.UUID
    workspace_id: uuid.UUID
    server_name: str
    config_name: str
    installed_version: str
    status: str


class AgentAvailableToolListResponse(APIModel):
    servers: list[AgentAvailableServerRead] = Field(default_factory=list)
    tools: list[AgentAvailableToolRead]


class AgentSkillAgentRead(APIModel):
    id: uuid.UUID
    name: str
    enabled_skill_ids: list[str] = Field(default_factory=list)
    available_skill_count: int = 0
    observed_skill_ids: list[str] = Field(default_factory=list)
    calls_last_7d: int = 0
    searches_last_7d: int = 0
    fetches_last_7d: int = 0
    failures_last_7d: int = 0
    recent_run_id: uuid.UUID | None = None
    last_used_at: datetime | None = None


class AgentSkillPermissionRead(APIModel):
    key: str
    label: str
    description: str


class AgentSkillRead(APIModel):
    id: str
    name: str
    description: str
    url: str
    source: str
    source_url: str | None = None
    source_owner: str = ""
    source_name: str = ""
    audit_status: str = "unknown"
    audit_score: int | None = None
    audit_rank: str | None = None
    audit_summary: str = ""
    permissions: list[AgentSkillPermissionRead] = Field(default_factory=list)
    installed: bool
    temporary: bool
    enabled_agent_ids: list[uuid.UUID] = Field(default_factory=list)
    enabled_agent_names: list[str] = Field(default_factory=list)
    health_status: Literal["healthy", "unhealthy", "unknown"] = "unknown"
    health_detail: str = ""


class AgentSkillSearchResultRead(APIModel):
    id: str
    name: str
    description: str
    url: str
    source: str
    source_owner: str = ""
    source_name: str = ""
    is_official: bool = False
    installs: int = 0
    audit_status: str | None = None
    audit_score: int | None = None
    audit_rank: str | None = None
    installed: bool = False
    temporary: bool = True
    permissions: list[AgentSkillPermissionRead] = Field(default_factory=list)


class AgentSkillSearchResponse(APIModel):
    query: str
    count: int
    results: list[AgentSkillSearchResultRead] = Field(default_factory=list)


class AgentSkillRecommendationRead(APIModel):
    id: str
    title: str
    description: str
    query: str
    connection_ids: list[uuid.UUID] = Field(default_factory=list)
    connection_names: list[str] = Field(default_factory=list)
    workflow_ids: list[str] = Field(default_factory=list)


class AgentSkillWorkflowRead(APIModel):
    id: str
    title: str
    description: str
    query: str
    required_connection_hints: list[str] = Field(default_factory=list)


class AgentSkillUsageSummaryRead(APIModel):
    active_skills: int = 0
    total_agents: int = 0
    enabled_agents: int = 0
    skill_events_last_7d: int = 0
    skill_runs_last_7d: int = 0
    searches_last_7d: int = 0
    fetches_last_7d: int = 0
    failures_last_7d: int = 0
    last_used_at: datetime | None = None


class AgentSkillActivityRead(APIModel):
    id: uuid.UUID
    agent_run_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    skill_id: str = ""
    skill_name: str = ""
    tool_name: str = ""
    event_type: Literal["selected", "search", "fetch", "activity"] = "activity"
    status: str = ""
    query: str = ""
    result_count: int | None = None
    fetched_skill_id: str = ""
    audit_status: str = ""
    source: str = ""
    summary: str = ""
    created_at: datetime


class AgentSkillCatalogResponse(APIModel):
    skills: list[AgentSkillRead] = Field(default_factory=list)
    agents: list[AgentSkillAgentRead] = Field(default_factory=list)
    recommendations: list[AgentSkillRecommendationRead] = Field(default_factory=list)
    guided_workflows: list[AgentSkillWorkflowRead] = Field(default_factory=list)
    usage_summary: AgentSkillUsageSummaryRead = Field(
        default_factory=AgentSkillUsageSummaryRead
    )
    recent_activity: list[AgentSkillActivityRead] = Field(default_factory=list)


class AgentChatMessage(APIModel):
    role: Literal["system", "user", "assistant"]
    parts: list[dict[str, Any]] = Field(default_factory=list)


class AgentChatRequest(APIModel):
    id: str | None = None
    messages: list[AgentChatMessage] = Field(default_factory=list)
