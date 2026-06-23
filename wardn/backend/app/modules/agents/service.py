import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import repository
from app.modules.agents.exceptions import (
    AgentNotFoundError,
    DuplicateAgentError,
    InvalidAgentScopeError,
    InvalidAgentToolAssignmentError,
)
from app.modules.agents.models import Agent
from app.modules.agents.schemas import (
    AgentCreate,
    AgentListResponse,
    AgentRead,
    AgentToolAssignmentUpdate,
    AgentToolListResponse,
    AgentToolRead,
    AgentUpdate,
)
from app.modules.llm_providers import repository as llm_provider_repository
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.service import credential_supports_model
from app.modules.organizations.service import (
    require_organization_admin,
    require_organization_member,
    require_workspace_admin,
)
from app.modules.users.models import User


def normalize_name(value: str) -> str:
    return " ".join(value.strip().split())


async def require_agent_scope_permission(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    scope: str,
    workspace_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if scope == "organization":
        await require_organization_admin(session, user, organization_id)
        if workspace_id is not None:
            raise InvalidAgentScopeError("organization-scoped agents cannot include a workspace")
        return None
    if scope == "workspace":
        if workspace_id is None:
            raise InvalidAgentScopeError("workspace-scoped agents require a workspace")
        await require_workspace_admin(session, user, organization_id, workspace_id)
        return workspace_id
    raise InvalidAgentScopeError("invalid agent scope")


async def validate_provider_credential(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    agent_workspace_id: uuid.UUID | None,
    provider_credential_id: uuid.UUID | None,
) -> LLMProviderCredential | None:
    if provider_credential_id is None:
        return None
    credential = await llm_provider_repository.get_credential(
        session,
        organization_id=organization_id,
        credential_id=provider_credential_id,
    )
    if credential is None or not credential.is_active:
        raise InvalidAgentScopeError("provider credential is not available")
    if credential.visibility == "user" and credential.user_id != user.id and not user.is_superuser:
        raise InvalidAgentScopeError("provider credential is not available to this user")
    if credential.visibility == "workspace" and credential.workspace_id != agent_workspace_id:
        raise InvalidAgentScopeError("workspace credential must match the agent workspace")
    return credential


async def validate_agent_model(
    credential: LLMProviderCredential | None,
    model_name: str,
) -> str:
    normalized_model = model_name.strip()
    if credential is None:
        return normalized_model
    if not normalized_model:
        raise InvalidAgentScopeError("model is required when an LLM credential is selected")
    if not await credential_supports_model(credential, normalized_model):
        raise InvalidAgentScopeError("model is not available for the selected LLM credential")
    return normalized_model


def agent_response(agent: Agent, *, tool_count: int) -> AgentRead:
    return AgentRead(
        id=agent.id,
        organizationId=agent.organization_id,
        workspaceId=agent.workspace_id,
        createdById=agent.created_by_id,
        providerCredentialId=agent.provider_credential_id,
        name=agent.name,
        description=agent.description,
        instructions=agent.instructions,
        scope=agent.scope,
        modelName=agent.model_name,
        isActive=agent.is_active,
        toolCount=tool_count,
        createdAt=agent.created_at,
        updatedAt=agent.updated_at,
    )


async def list_agents(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
) -> AgentListResponse:
    await require_organization_member(session, user, organization_id)
    rows = await repository.list_agents(
        session,
        organization_id=organization_id,
        user_id=user.id,
        is_superuser=user.is_superuser,
    )
    return AgentListResponse(
        agents=[agent_response(agent, tool_count=tool_count) for agent, tool_count in rows]
    )


async def get_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> AgentRead:
    await require_organization_member(session, user, organization_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    return agent_response(agent, tool_count=await repository.count_agent_tools(session, agent.id))


async def create_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    payload: AgentCreate,
) -> AgentRead:
    name = normalize_name(payload.name)
    workspace_id = await require_agent_scope_permission(
        session,
        user,
        organization_id,
        scope=payload.scope,
        workspace_id=payload.workspace_id,
    )
    if await repository.get_agent_by_name(session, organization_id=organization_id, name=name):
        raise DuplicateAgentError("agent name already exists")
    provider_credential = await validate_provider_credential(
        session,
        user,
        organization_id,
        agent_workspace_id=workspace_id,
        provider_credential_id=payload.provider_credential_id,
    )
    model_name = await validate_agent_model(provider_credential, payload.model_name)
    agent = Agent(
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        provider_credential_id=provider_credential.id if provider_credential else None,
        name=name,
        description=payload.description.strip(),
        instructions=payload.instructions.strip(),
        scope=payload.scope,
        model_name=model_name,
        is_active=True,
    )
    session.add(agent)
    await session.flush()
    await session.refresh(agent)
    return agent_response(agent, tool_count=0)


async def update_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentUpdate,
) -> AgentRead:
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        include_inactive=True,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")

    scope = payload.scope or agent.scope
    workspace_id = (
        payload.workspace_id
        if "workspace_id" in payload.model_fields_set
        else agent.workspace_id
    )
    await require_agent_scope_permission(
        session,
        user,
        organization_id,
        scope=scope,
        workspace_id=workspace_id,
    )

    if payload.name is not None:
        name = normalize_name(payload.name)
        existing = await repository.get_agent_by_name(
            session,
            organization_id=organization_id,
            name=name,
        )
        if existing is not None and existing.id != agent.id:
            raise DuplicateAgentError("agent name already exists")
        agent.name = name
    if payload.description is not None:
        agent.description = payload.description.strip()
    if payload.instructions is not None:
        agent.instructions = payload.instructions.strip()
    if payload.scope is not None or "workspace_id" in payload.model_fields_set:
        agent.scope = scope
        agent.workspace_id = workspace_id
    provider_credential_changed = (
        payload.provider_credential_id is not None
        or "provider_credential_id" in payload.model_fields_set
    )
    scope_changed = payload.scope is not None or "workspace_id" in payload.model_fields_set
    provider_credential = None
    if provider_credential_changed:
        provider_credential = await validate_provider_credential(
            session,
            user,
            organization_id,
            agent_workspace_id=agent.workspace_id,
            provider_credential_id=payload.provider_credential_id,
        )
        agent.provider_credential_id = provider_credential.id if provider_credential else None
    elif (scope_changed or payload.model_name is not None) and agent.provider_credential_id:
        provider_credential = await validate_provider_credential(
            session,
            user,
            organization_id,
            agent_workspace_id=agent.workspace_id,
            provider_credential_id=agent.provider_credential_id,
        )
    if payload.model_name is not None:
        agent.model_name = await validate_agent_model(provider_credential, payload.model_name)
    elif provider_credential_changed and provider_credential is not None:
        agent.model_name = await validate_agent_model(provider_credential, agent.model_name)
    if payload.is_active is not None:
        agent.is_active = payload.is_active

    await session.flush()
    await session.refresh(agent)
    return agent_response(
        agent,
        tool_count=await repository.count_agent_tools(session, agent.id),
    )


async def delete_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> None:
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        include_inactive=True,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    await require_agent_scope_permission(
        session,
        user,
        organization_id,
        scope=agent.scope,
        workspace_id=agent.workspace_id,
    )
    agent.is_active = False
    await session.flush()


def assigned_tool_response(row) -> AgentToolRead:
    assignment, tool_schema, installation = row
    if tool_schema.workspace_id is None:
        raise InvalidAgentToolAssignmentError("assigned tool has no workspace")
    return AgentToolRead(
        id=assignment.id,
        agentId=assignment.agent_id,
        toolSchemaId=assignment.tool_schema_id,
        installationId=assignment.installation_id,
        workspaceId=tool_schema.workspace_id,
        serverName=tool_schema.server_name,
        configName=installation.config_name,
        toolName=tool_schema.tool_name,
        title=tool_schema.title,
        description=tool_schema.description,
        inputSchema=tool_schema.input_schema,
        outputSchema=tool_schema.output_schema,
        annotations=tool_schema.annotations,
        createdAt=assignment.created_at,
    )


async def list_agent_tools(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> AgentToolListResponse:
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    await require_agent_scope_permission(
        session,
        user,
        organization_id,
        scope=agent.scope,
        workspace_id=agent.workspace_id,
    )
    return AgentToolListResponse(
        tools=[
            assigned_tool_response(row)
            for row in await repository.list_agent_tools(session, agent_id=agent.id)
        ]
    )


async def replace_agent_tools(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentToolAssignmentUpdate,
) -> AgentToolListResponse:
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    await require_agent_scope_permission(
        session,
        user,
        organization_id,
        scope=agent.scope,
        workspace_id=agent.workspace_id,
    )

    unique_tool_ids = sorted(set(payload.tool_schema_ids), key=str)
    tool_rows = await repository.get_tool_schemas_by_ids(session, unique_tool_ids)
    found_tool_ids = {tool_schema.id for tool_schema, _installation, _workspace in tool_rows}
    missing = [tool_id for tool_id in unique_tool_ids if tool_id not in found_tool_ids]
    if missing:
        raise InvalidAgentToolAssignmentError("one or more tools are not available")

    for tool_schema, _installation, workspace in tool_rows:
        if workspace.organization_id != organization_id:
            raise InvalidAgentToolAssignmentError("tool is outside the agent organization")
        if agent.workspace_id is not None and tool_schema.workspace_id != agent.workspace_id:
            raise InvalidAgentToolAssignmentError("tool must belong to the agent workspace")

    await repository.replace_agent_tools(session, agent_id=agent.id, tool_rows=tool_rows)
    return AgentToolListResponse(
        tools=[
            assigned_tool_response(row)
            for row in await repository.list_agent_tools(session, agent_id=agent.id)
        ]
    )
