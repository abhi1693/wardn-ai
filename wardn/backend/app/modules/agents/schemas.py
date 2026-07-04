import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentScope = Literal["organization", "workspace"]


class AgentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(min_length=1, max_length=50000)
    scope: AgentScope = "organization"
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    provider_credential_id: uuid.UUID | None = Field(
        default=None,
        alias="providerCredentialId",
    )
    model_name: str = Field(default="", alias="modelName", max_length=255)

    @model_validator(mode="after")
    def validate_scope(self) -> "AgentCreate":
        if self.scope == "workspace" and self.workspace_id is None:
            raise ValueError("workspaceId is required for workspace-scoped agents")
        if self.scope != "workspace" and self.workspace_id is not None:
            raise ValueError("workspaceId is only valid for workspace-scoped agents")
        return self


class AgentUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, min_length=1, max_length=50000)
    scope: AgentScope | None = None
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    provider_credential_id: uuid.UUID | None = Field(
        default=None,
        alias="providerCredentialId",
    )
    model_name: str | None = Field(default=None, alias="modelName", max_length=255)
    is_active: bool | None = Field(default=None, alias="isActive")


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID = Field(alias="organizationId")
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    created_by_id: uuid.UUID | None = Field(default=None, alias="createdById")
    provider_credential_id: uuid.UUID | None = Field(
        default=None,
        alias="providerCredentialId",
    )
    name: str
    description: str
    instructions: str
    scope: AgentScope
    model_name: str = Field(alias="modelName")
    is_active: bool = Field(alias="isActive")
    server_count: int = Field(alias="serverCount")
    tool_count: int = Field(alias="toolCount")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class AgentListResponse(BaseModel):
    agents: list[AgentRead]


class WorkspaceConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID = Field(alias="organizationId")
    workspace_id: uuid.UUID = Field(alias="workspaceId")
    agent_id: uuid.UUID = Field(alias="agentId")
    created_by_id: uuid.UUID | None = Field(default=None, alias="createdById")
    title: str
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class ConversationMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    conversation_id: uuid.UUID = Field(alias="conversationId")
    role: Literal["system", "user", "assistant"]
    content: str
    parts: list[dict[str, Any]] = Field(default_factory=list)
    sequence: int
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class AgentConversationResponse(BaseModel):
    agent: AgentRead
    conversation: WorkspaceConversationRead
    messages: list[ConversationMessageRead] = Field(default_factory=list)


TOOL_ASSIGNMENT_WILDCARD = "*"
ToolAssignmentSelection = uuid.UUID | Literal["*"]


class AgentServerToolAssignmentUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    installation_id: uuid.UUID = Field(alias="installationId")
    tool_schema_ids: list[ToolAssignmentSelection] = Field(
        default_factory=list,
        alias="toolSchemaIds",
    )

    @model_validator(mode="after")
    def validate_tool_selection(self) -> "AgentServerToolAssignmentUpdate":
        has_wildcard = TOOL_ASSIGNMENT_WILDCARD in self.tool_schema_ids
        if not self.tool_schema_ids:
            raise ValueError("toolSchemaIds must include at least one tool or '*'")
        if has_wildcard and len(self.tool_schema_ids) > 1:
            raise ValueError("'*' cannot be combined with individual tool IDs")
        return self


class AgentToolAssignmentUpdate(BaseModel):
    servers: list[AgentServerToolAssignmentUpdate] = Field(default_factory=list)


class AgentToolRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    agent_id: uuid.UUID = Field(alias="agentId")
    tool_schema_id: uuid.UUID = Field(alias="toolSchemaId")
    installation_id: uuid.UUID = Field(alias="installationId")
    workspace_id: uuid.UUID = Field(alias="workspaceId")
    server_name: str = Field(alias="serverName")
    config_name: str = Field(alias="configName")
    tool_name: str = Field(alias="toolName")
    title: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")
    annotations: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(alias="createdAt")


class AgentServerToolAssignmentRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    installation_id: uuid.UUID = Field(alias="installationId")
    tool_schema_ids: list[ToolAssignmentSelection] = Field(alias="toolSchemaIds")


class AgentToolListResponse(BaseModel):
    tools: list[AgentToolRead]
    servers: list[AgentServerToolAssignmentRead] = Field(default_factory=list)


class AgentAvailableToolRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tool_schema_id: uuid.UUID = Field(alias="toolSchemaId")
    installation_id: uuid.UUID = Field(alias="installationId")
    workspace_id: uuid.UUID = Field(alias="workspaceId")
    server_name: str = Field(alias="serverName")
    config_name: str = Field(alias="configName")
    tool_name: str = Field(alias="toolName")
    title: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")
    annotations: dict[str, Any] = Field(default_factory=dict)


class AgentAvailableServerRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    installation_id: uuid.UUID = Field(alias="installationId")
    workspace_id: uuid.UUID = Field(alias="workspaceId")
    server_name: str = Field(alias="serverName")
    config_name: str = Field(alias="configName")
    installed_version: str = Field(alias="installedVersion")
    status: str


class AgentAvailableToolListResponse(BaseModel):
    servers: list[AgentAvailableServerRead] = Field(default_factory=list)
    tools: list[AgentAvailableToolRead]


class AgentChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    parts: list[dict[str, Any]] = Field(default_factory=list)


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    messages: list[AgentChatMessage] = Field(default_factory=list)
