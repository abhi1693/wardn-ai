import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.pagination import CursorPageMetadata
from app.core.schemas import APIModel
from app.modules.agents.skills import normalize_agent_skill_ids

AgentScope = Literal["organization", "workspace"]


class AgentCreate(APIModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(min_length=1, max_length=50000)
    scope: AgentScope = "organization"
    workspace_id: uuid.UUID | None = None
    provider_credential_id: uuid.UUID | None = None
    model_name: str = Field(default="", max_length=255)
    skill_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("skill_ids")
    @classmethod
    def validate_skill_ids(cls, value: list[str]) -> list[str]:
        return normalize_agent_skill_ids(value)

    @model_validator(mode="after")
    def validate_scope(self) -> "AgentCreate":
        if self.scope == "workspace" and self.workspace_id is None:
            raise ValueError("workspaceId is required for workspace-scoped agents")
        if self.scope != "workspace" and self.workspace_id is not None:
            raise ValueError("workspaceId is only valid for workspace-scoped agents")
        return self


class AgentUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, min_length=1, max_length=50000)
    scope: AgentScope | None = None
    workspace_id: uuid.UUID | None = None
    provider_credential_id: uuid.UUID | None = None
    model_name: str | None = Field(default=None, max_length=255)
    skill_ids: list[str] | None = Field(default=None, max_length=8)
    is_active: bool | None = None

    @field_validator("skill_ids")
    @classmethod
    def validate_skill_ids(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_agent_skill_ids(value)


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


TOOL_ASSIGNMENT_WILDCARD = "*"
ToolAssignmentSelection = uuid.UUID | Literal["*"]


class AgentServerToolAssignmentUpdate(APIModel):
    installation_id: uuid.UUID
    tool_schema_ids: list[ToolAssignmentSelection] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tool_selection(self) -> "AgentServerToolAssignmentUpdate":
        has_wildcard = TOOL_ASSIGNMENT_WILDCARD in self.tool_schema_ids
        if not self.tool_schema_ids:
            raise ValueError("toolSchemaIds must include at least one tool or '*'")
        if has_wildcard and len(self.tool_schema_ids) > 1:
            raise ValueError("'*' cannot be combined with individual tool IDs")
        return self


class AgentToolAssignmentUpdate(APIModel):
    servers: list[AgentServerToolAssignmentUpdate] = Field(default_factory=list)


class AgentToolRead(APIModel):
    id: uuid.UUID
    agent_id: uuid.UUID
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
    created_at: datetime


class AgentServerToolAssignmentRead(APIModel):
    installation_id: uuid.UUID
    tool_schema_ids: list[ToolAssignmentSelection]


class AgentToolListResponse(APIModel):
    tools: list[AgentToolRead]
    servers: list[AgentServerToolAssignmentRead] = Field(default_factory=list)


class AgentToolApprovalDecisionRequest(APIModel):
    decision: Literal["approve", "deny"]


class AgentToolApprovalDecisionResponse(APIModel):
    approval_id: uuid.UUID
    status: str
    tool_name: str
    result: str = ""
    error: str = ""
    assistant_message: ConversationMessageRead | None = None


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


class AgentSkillCatalogResponse(APIModel):
    skills: list[AgentSkillRead] = Field(default_factory=list)
    agents: list[AgentSkillAgentRead] = Field(default_factory=list)
    recommendations: list[AgentSkillRecommendationRead] = Field(default_factory=list)
    guided_workflows: list[AgentSkillWorkflowRead] = Field(default_factory=list)


class AgentCapabilityDiagnosisSummary(APIModel):
    installed: int
    assigned: int
    allowed: int
    blocked_by_policy: int
    healthy: int
    runnable: int


class AgentCapabilityDiagnosisToolRead(APIModel):
    tool_schema_id: uuid.UUID
    installation_id: uuid.UUID
    workspace_id: uuid.UUID
    server_name: str
    config_name: str
    tool_name: str
    title: str
    description: str
    installed: bool
    assigned: bool
    allowed: bool
    healthy: bool
    can_run: bool
    status: str
    reason_code: str
    reason: str
    policy: dict[str, Any] | None = None
    runtime: dict[str, Any] = Field(default_factory=dict)


class AgentCapabilityDiagnosisResponse(APIModel):
    agent_id: uuid.UUID
    workspace_id: uuid.UUID
    query: str = ""
    summary: AgentCapabilityDiagnosisSummary
    tools: list[AgentCapabilityDiagnosisToolRead]


class AgentChatMessage(APIModel):
    role: Literal["system", "user", "assistant"]
    parts: list[dict[str, Any]] = Field(default_factory=list)


class AgentChatRequest(APIModel):
    id: str | None = None
    messages: list[AgentChatMessage] = Field(default_factory=list)
