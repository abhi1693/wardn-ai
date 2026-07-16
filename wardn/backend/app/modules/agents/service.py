import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.errors import is_constraint_violation
from app.modules.agents import repository
from app.modules.agents.approvals import (
    approval_continuation_prompt as approval_continuation_prompt,
)
from app.modules.agents.approvals import (
    conversation_message_to_chat_message as conversation_message_to_chat_message,
)
from app.modules.agents.approvals import (
    decide_agent_tool_approval as decide_agent_tool_approval,
)
from app.modules.agents.approvals import (
    generate_approval_continuation_message as generate_approval_continuation_message,
)
from app.modules.agents.chat_orchestrator import (
    chat_stream_error_text as chat_stream_error_text,
)
from app.modules.agents.chat_orchestrator import (
    conversation_id_from_payload as conversation_id_from_payload,
)
from app.modules.agents.chat_orchestrator import (
    filter_agent_runtime_tools_for_guardrails,
    latest_user_message,
    message_requests_denied_mcp_tool,
    persisted_agent_chat_stream,
    preflight_blocked_tool_stream,
)
from app.modules.agents.chat_orchestrator import (
    persist_chat_turn_user_message as persist_chat_turn_user_message,
)
from app.modules.agents.chat_orchestrator import (
    record_agent_llm_usage as record_agent_llm_usage,
)
from app.modules.agents.chat_orchestrator import (
    refresh_agent_chat_credential as refresh_agent_chat_credential,
)
from app.modules.agents.chat_orchestrator import (
    require_agent_llm_budget_available as require_agent_llm_budget_available,
)
from app.modules.agents.chat_orchestrator import (
    run_agent_chat as run_agent_chat,
)
from app.modules.agents.chat_orchestrator import (
    stream_chatgpt_codex_response_text as stream_chatgpt_codex_response_text,
)
from app.modules.agents.chat_orchestrator import (
    ui_message_sse_chunk as ui_message_sse_chunk,
)
from app.modules.agents.conversations import AgentSessionFactory
from app.modules.agents.exceptions import (
    AgentNotFoundError,
    DuplicateAgentError,
    InvalidAgentScopeError,
    InvalidAgentToolAssignmentError,
)
from app.modules.agents.mappers import (
    AGENT_RUN_PAYLOAD_STRING_MAX_CHARS as AGENT_RUN_PAYLOAD_STRING_MAX_CHARS,
)
from app.modules.agents.mappers import (
    agent_response,
    agent_run_response,
    agent_run_step_response,
    assigned_tool_response,
    conversation_message_response,
    conversation_response,
    sanitize_run_payload,
    server_assignment_responses,
)
from app.modules.agents.models import (
    Agent,
)
from app.modules.agents.provider_clients import (
    CODEX_COMPAT_USER_AGENT as CODEX_COMPAT_USER_AGENT,
)
from app.modules.agents.provider_clients import (
    CODEX_COMPAT_VERSION as CODEX_COMPAT_VERSION,
)
from app.modules.agents.provider_clients import (
    DEFAULT_CODEX_COMPAT_VERSION as DEFAULT_CODEX_COMPAT_VERSION,
)
from app.modules.agents.provider_clients import (
    agent_runtime_tools,
    provider_messages,
    text_from_chat_message,
)
from app.modules.agents.provider_clients import (
    chatgpt_codex_messages as chatgpt_codex_messages,
)
from app.modules.agents.provider_clients import (
    chatgpt_codex_request_body as chatgpt_codex_request_body,
)
from app.modules.agents.provider_clients import (
    llm_usage_from_completed_event as llm_usage_from_completed_event,
)
from app.modules.agents.provider_clients import (
    sse_payloads as sse_payloads,
)
from app.modules.agents.provider_clients import (
    text_delta_from_openai_event as text_delta_from_openai_event,
)
from app.modules.agents.provider_clients import (
    tool_calls_from_event as tool_calls_from_event,
)
from app.modules.agents.provider_clients import (
    validate_agent_model as validate_agent_model,
)
from app.modules.agents.provider_clients import (
    validate_provider_credential as validate_provider_credential,
)
from app.modules.agents.provider_clients import (
    websocket_error_message as websocket_error_message,
)
from app.modules.agents.schemas import (
    TOOL_ASSIGNMENT_WILDCARD,
    AgentAvailableServerRead,
    AgentAvailableToolListResponse,
    AgentAvailableToolRead,
    AgentChatRequest,
    AgentConversationResponse,
    AgentCreate,
    AgentListResponse,
    AgentRead,
    AgentRunDetailResponse,
    AgentRunListResponse,
    AgentToolAssignmentUpdate,
    AgentToolListResponse,
    AgentUpdate,
)
from app.modules.agents.tool_execution import (
    AGENT_TOOL_BLOCKED_PREFIX as AGENT_TOOL_BLOCKED_PREFIX,
)
from app.modules.agents.tool_execution import (
    AGENT_TOOL_CONFIRMATION_PREFIX as AGENT_TOOL_CONFIRMATION_PREFIX,
)
from app.modules.agents.tool_execution import (
    execute_agent_tool_call as execute_agent_tool_call,
)
from app.modules.agents.types import AgentChatProviderError as AgentChatProviderError
from app.modules.agents.types import AgentChatTextEvent as AgentChatTextEvent
from app.modules.agents.types import (
    AgentChatToolActivityEvent as AgentChatToolActivityEvent,
)
from app.modules.agents.types import AgentRuntimeTool as AgentRuntimeTool
from app.modules.agents.types import (
    AgentRuntimeToolGuardrailFilter as AgentRuntimeToolGuardrailFilter,
)
from app.modules.agents.types import AgentToolCall as AgentToolCall
from app.modules.limits import service as limits_service
from app.modules.llm_providers import repository as llm_provider_repository
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.service import OPENAI_API_KEY_PROVIDER as OPENAI_API_KEY_PROVIDER
from app.modules.llm_providers.service import OPENAI_CHATGPT_PROVIDER as OPENAI_CHATGPT_PROVIDER
from app.modules.llm_providers.service import list_models_for_credential, user_can_see_credential
from app.modules.mcp_registry import repository as mcp_registry_repository
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
)
from app.modules.mcp_registry.tool_service import refresh_tool_schemas_for_installation
from app.modules.observability import service as observability_service
from app.modules.organizations.service import (
    require_organization_admin,
    require_organization_member,
    require_workspace_admin,
    require_workspace_member,
)
from app.modules.users.models import User

AGENT_CHAT_MAX_TOOL_ROUNDS = 8
AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS = 40_000
QUICK_START_AGENT_NAME = "Workspace Assistant"
QUICK_START_AGENT_DESCRIPTION = "Default assistant for workspace chat."
QUICK_START_AGENT_INSTRUCTIONS = (
    "You are a workspace assistant. Use available tools when they help answer accurately. "
    "Ask before destructive actions."
)

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


async def require_agent_run_permission(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    *,
    scope: str,
    workspace_id: uuid.UUID | None,
) -> None:
    if scope == "organization":
        await require_organization_member(session, user, organization_id)
        if workspace_id is not None:
            raise InvalidAgentScopeError("organization-scoped agents cannot include a workspace")
        return
    if scope == "workspace":
        if workspace_id is None:
            raise InvalidAgentScopeError("workspace-scoped agents require a workspace")
        await require_workspace_member(session, user, organization_id, workspace_id)
        return
    raise InvalidAgentScopeError("invalid agent scope")


async def list_agents(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> AgentListResponse:
    if workspace_id is None:
        await require_organization_member(session, user, organization_id)
    else:
        await require_workspace_member(session, user, organization_id, workspace_id)
    rows = await repository.list_agents(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user.id,
        is_superuser=user.is_superuser,
    )
    return AgentListResponse(
        agents=[
            agent_response(agent, server_count=server_count, tool_count=tool_count)
            for agent, server_count, tool_count in rows
        ]
    )


async def get_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> AgentRead:
    if workspace_id is None:
        await require_organization_member(session, user, organization_id)
    else:
        await require_workspace_member(session, user, organization_id, workspace_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    return agent_response(
        agent,
        server_count=await repository.count_agent_servers(session, agent.id),
        tool_count=await repository.count_agent_tools(session, agent.id),
    )


async def get_agent_model_for_run(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> tuple[Agent, LLMProviderCredential]:
    if workspace_id is None:
        await require_organization_member(session, user, organization_id)
    else:
        await require_workspace_member(session, user, organization_id, workspace_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    await require_agent_run_permission(
        session,
        user,
        organization_id,
        scope=agent.scope,
        workspace_id=agent.workspace_id,
    )
    if agent.provider_credential_id is None:
        raise InvalidAgentScopeError("agent requires an LLM credential before chat")
    if not agent.model_name:
        raise InvalidAgentScopeError("agent requires a model before chat")
    credential = await validate_provider_credential(
        session,
        user,
        organization_id,
        agent_workspace_id=agent.workspace_id,
        provider_credential_id=agent.provider_credential_id,
    )
    if credential is None:
        raise InvalidAgentScopeError("agent requires an LLM credential before chat")
    return agent, credential


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
    if await repository.get_agent_by_name(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=name,
    ):
        raise DuplicateAgentError("agent name already exists")
    provider_credential = await validate_provider_credential(
        session,
        user,
        organization_id,
        agent_workspace_id=workspace_id,
        provider_credential_id=payload.provider_credential_id,
    )
    model_name = await validate_agent_model(session, provider_credential, payload.model_name)
    await require_agent_create_limit(session, user, organization_id, workspace_id)
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
    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(
            exc,
            {"uq_agents_org_name", "uq_agents_workspace_name"},
        ):
            raise DuplicateAgentError("agent name already exists") from exc
        raise
    await session.refresh(agent)
    return agent_response(agent, server_count=0, tool_count=0)


async def require_agent_create_limit(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
) -> None:
    quota_scopes = agent_quota_scopes(user, organization_id, workspace_id)
    await limits_service.lock_quota_capacity(session, quota_scopes)
    organization_agent_count = await repository.count_active_agents_for_organization(
        session,
        organization_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.AGENTS_PER_ORGANIZATION,
        scope_chain=[
            ("organization", organization_id),
        ],
        current_count=organization_agent_count,
    )
    if workspace_id is None:
        return

    workspace_agent_count = await repository.count_active_agents_for_workspace(
        session,
        workspace_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.AGENTS_PER_WORKSPACE,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=workspace_agent_count,
    )
    user_workspace_agent_count = (
        await repository.count_active_agents_created_by_user_for_workspace(
            session,
            workspace_id=workspace_id,
            user_id=user.id,
        )
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.AGENTS_PER_WORKSPACE_PER_USER,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=user_workspace_agent_count,
    )


def agent_quota_scopes(
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID | None,
) -> list[limits_service.QuotaScope]:
    scopes = [
        limits_service.quota_scope(
            limits_service.AGENTS_PER_ORGANIZATION,
            organization_id,
        )
    ]
    if workspace_id is not None:
        scopes.extend(
            [
                limits_service.quota_scope(
                    limits_service.AGENTS_PER_WORKSPACE,
                    workspace_id,
                ),
                limits_service.quota_scope(
                    limits_service.AGENTS_PER_WORKSPACE_PER_USER,
                    workspace_id,
                    user.id,
                ),
            ]
        )
    return scopes


async def create_workspace_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    payload: AgentCreate,
) -> AgentRead:
    return await create_agent(
        session,
        user,
        organization_id,
        payload.model_copy(update={"scope": "workspace", "workspace_id": workspace_id}),
    )


def credential_visible_for_workspace_quick_start(
    user: User,
    credential: LLMProviderCredential,
    workspace_id: uuid.UUID,
) -> bool:
    if not credential.is_active or not user_can_see_credential(user, credential):
        return False
    if credential.visibility == "workspace":
        return credential.workspace_id == workspace_id
    return credential.workspace_id is None


def quick_start_credential_sort_key(credential: LLMProviderCredential) -> tuple[int, str, str]:
    scope_rank = {"workspace": 0, "organization": 1, "user": 2}.get(credential.visibility, 3)
    return (scope_rank, credential.provider, credential.name.casefold())


async def select_quick_start_credential_and_model(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> tuple[LLMProviderCredential, str]:
    credentials = await llm_provider_repository.list_credentials(
        session,
        organization_id=organization_id,
    )
    candidates = sorted(
        (
            credential
            for credential in credentials
            if credential_visible_for_workspace_quick_start(user, credential, workspace_id)
        ),
        key=quick_start_credential_sort_key,
    )
    for credential in candidates:
        try:
            models = await list_models_for_credential(session, credential)
        except Exception:
            continue
        first_model = next((model for model in models.models if model.id.strip()), None)
        if first_model is not None:
            return credential, first_model.id
    raise InvalidAgentScopeError("no usable LLM credential is available for workspace chat")


async def quick_start_agent_needs_model_selection(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent: Agent,
) -> bool:
    if agent.provider_credential_id is None or not agent.model_name:
        return True
    try:
        credential = await validate_provider_credential(
            session,
            user,
            organization_id,
            agent_workspace_id=agent.workspace_id,
            provider_credential_id=agent.provider_credential_id,
        )
        await validate_agent_model(session, credential, agent.model_name)
    except InvalidAgentScopeError:
        return True
    return False


async def sync_quick_start_agent_tools(
    session: AsyncSession,
    agent: Agent,
    workspace_id: uuid.UUID,
) -> None:
    installations = await mcp_registry_repository.list_installations(
        session,
        workspace_id=workspace_id,
    )
    enabled_installations = [
        installation for installation in installations if installation.status == "enabled"
    ]
    await repository.replace_agent_tools(
        session,
        agent_id=agent.id,
        server_assignments=[(installation, True, []) for installation in enabled_installations],
    )


async def quick_start_workspace_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> AgentConversationResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    await limits_service.lock_quota_capacity(
        session,
        agent_quota_scopes(user, organization_id, workspace_id),
    )
    agent = await repository.get_agent_by_name(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=QUICK_START_AGENT_NAME,
    )
    if agent is None:
        await require_agent_create_limit(session, user, organization_id, workspace_id)
        credential, model_name = await select_quick_start_credential_and_model(
            session,
            user,
            organization_id,
            workspace_id,
        )
        agent = Agent(
            organization_id=organization_id,
            workspace_id=workspace_id,
            created_by_id=user.id,
            provider_credential_id=credential.id,
            name=QUICK_START_AGENT_NAME,
            description=QUICK_START_AGENT_DESCRIPTION,
            instructions=QUICK_START_AGENT_INSTRUCTIONS,
            scope="workspace",
            model_name=model_name,
            is_active=True,
        )
        session.add(agent)
        await session.flush()
        await session.refresh(agent)
    else:
        changed = False
        if await quick_start_agent_needs_model_selection(
            session,
            user,
            organization_id,
            agent,
        ):
            credential, model_name = await select_quick_start_credential_and_model(
                session,
                user,
                organization_id,
                workspace_id,
            )
            agent.provider_credential_id = credential.id
            agent.model_name = model_name
            changed = True
        if not agent.instructions.strip():
            agent.instructions = QUICK_START_AGENT_INSTRUCTIONS
            changed = True
        if not agent.is_active:
            agent.is_active = True
            changed = True
        if changed:
            await session.flush()
            await session.refresh(agent)
    await sync_quick_start_agent_tools(session, agent, workspace_id)
    server_count = await repository.count_agent_servers(session, agent.id)
    tool_count = await repository.count_agent_tools(session, agent.id)
    await require_workspace_conversation_create_limit(session, user, organization_id, workspace_id)
    conversation = await repository.create_workspace_conversation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        created_by_id=user.id,
    )
    return AgentConversationResponse(
        agent=agent_response(agent, server_count=server_count, tool_count=tool_count),
        conversation=conversation_response(conversation),
        messages=[],
    )


async def require_workspace_conversation_create_limit(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    await limits_service.lock_quota_capacity(
        session,
        [
            limits_service.quota_scope(
                limits_service.WORKSPACE_CONVERSATIONS_PER_WORKSPACE,
                workspace_id,
            ),
            limits_service.quota_scope(
                limits_service.WORKSPACE_CONVERSATIONS_PER_WORKSPACE_PER_USER,
                workspace_id,
                user.id,
            ),
        ],
    )
    workspace_conversation_count = await repository.count_active_workspace_conversations(
        session,
        workspace_id,
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.WORKSPACE_CONVERSATIONS_PER_WORKSPACE,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=workspace_conversation_count,
    )
    user_workspace_conversation_count = (
        await repository.count_active_workspace_conversations_created_by_user(
            session,
            workspace_id=workspace_id,
            user_id=user.id,
        )
    )
    await limits_service.require_limit_available(
        session,
        limit_key=limits_service.WORKSPACE_CONVERSATIONS_PER_WORKSPACE_PER_USER,
        scope_chain=[
            ("workspace", workspace_id),
            ("organization", organization_id),
        ],
        current_count=user_workspace_conversation_count,
    )


async def get_workspace_conversation(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> AgentConversationResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    conversation = await repository.get_workspace_conversation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise AgentNotFoundError("conversation not found")
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=conversation.agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    messages = await repository.list_conversation_messages(
        session,
        conversation_id=conversation.id,
    )
    return AgentConversationResponse(
        agent=agent_response(
            agent,
            server_count=await repository.count_agent_servers(session, agent.id),
            tool_count=await repository.count_agent_tools(session, agent.id),
        ),
        conversation=conversation_response(conversation),
        messages=[conversation_message_response(message) for message in messages],
    )


async def list_workspace_agent_runs(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> AgentRunListResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    runs = await repository.list_agent_runs(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return AgentRunListResponse(runs=[agent_run_response(agent_run) for agent_run in runs])


async def get_workspace_agent_run(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_run_id: uuid.UUID,
) -> AgentRunDetailResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    agent_run = await repository.get_agent_run(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_run_id=agent_run_id,
    )
    if agent_run is None:
        raise AgentNotFoundError("agent run not found")
    steps = await repository.list_agent_run_steps(session, agent_run_id=agent_run.id)
    usage_summary = await observability_service.agent_run_usage_summary(
        session,
        agent_run_id=agent_run.id,
    )
    trace_id, span_id = await observability_service.agent_run_trace_ids(
        session,
        agent_run_id=agent_run.id,
    )
    return AgentRunDetailResponse(
        run=agent_run_response(
            agent_run,
            usage_summary,
            trace_id=trace_id,
            span_id=span_id,
        ),
        steps=[agent_run_step_response(step) for step in steps],
    )


def available_tool_response(
    tool_schema: MCPServerToolSchema,
    installation: MCPServerInstallation,
) -> AgentAvailableToolRead:
    if tool_schema.workspace_id is None or tool_schema.installation_id is None:
        raise InvalidAgentToolAssignmentError("tool is not workspace assignable")
    return AgentAvailableToolRead(
        toolSchemaId=tool_schema.id,
        installationId=installation.id,
        workspaceId=tool_schema.workspace_id,
        serverName=tool_schema.server_name,
        configName=installation.config_name,
        toolName=tool_schema.tool_name,
        title=tool_schema.title,
        description=tool_schema.description,
        inputSchema=tool_schema.input_schema,
        outputSchema=tool_schema.output_schema,
        annotations=tool_schema.annotations,
    )


def available_server_response(installation: MCPServerInstallation) -> AgentAvailableServerRead:
    return AgentAvailableServerRead(
        installationId=installation.id,
        workspaceId=installation.workspace_id,
        serverName=installation.server_name,
        configName=installation.config_name,
        installedVersion=installation.installed_version,
        status=installation.status,
    )


async def list_available_agent_tools(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> AgentAvailableToolListResponse:
    await require_workspace_member(session, user, organization_id, workspace_id)
    installations = await mcp_registry_repository.list_installations(
        session,
        workspace_id=workspace_id,
    )
    rows = await repository.list_workspace_available_tools(session, workspace_id=workspace_id)
    return AgentAvailableToolListResponse(
        servers=[
            available_server_response(installation)
            for installation in installations
            if installation.status == "enabled"
        ],
        tools=[
            available_tool_response(tool_schema, installation)
            for tool_schema, installation in rows
        ]
    )




async def refresh_wildcard_agent_server_tools(
    session: AsyncSession,
    agent_id: uuid.UUID,
) -> None:
    rows = await repository.list_agent_wildcard_server_version_rows(session, agent_id=agent_id)
    for _assignment, installation, server in rows:
        try:
            await refresh_tool_schemas_for_installation(
                session,
                installation=installation,
                server=server,
            )
        except Exception as exc:
            raise InvalidAgentScopeError(
                f"MCP server tools could not be loaded for {installation.config_name}: {exc}"
            ) from exc
async def stream_agent_chat(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentChatRequest,
    workspace_id: uuid.UUID | None = None,
    *,
    session_factory: AgentSessionFactory | None = None,
) -> AsyncGenerator[str, None]:
    agent, credential = await get_agent_model_for_run(
        session,
        user,
        organization_id,
        agent_id,
        workspace_id=workspace_id,
    )
    messages = provider_messages(payload.messages)
    if not messages:
        raise InvalidAgentScopeError("chat requires at least one user message")
    if workspace_id is None:
        raise InvalidAgentScopeError("agent chat requires a workspace")
    conversation = None
    conversation_id = conversation_id_from_payload(payload)
    if conversation_id is not None:
        conversation = await repository.get_workspace_conversation(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
        )
        if conversation is None or conversation.agent_id != agent.id:
            raise AgentNotFoundError("conversation not found")
    agent_run = await repository.create_agent_run(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        conversation_id=conversation.id if conversation is not None else None,
        triggered_by_id=user.id,
        trigger_type="chat",
    )
    latest_message = latest_user_message(payload.messages)
    await repository.append_agent_run_step(
        session,
        agent_run_id=agent_run.id,
        step_type="model_input",
        status="submitted",
        title="User message",
        payload={
            "message": sanitize_run_payload(text_from_chat_message(latest_message))
            if latest_message
            else "",
            "messageCount": len(payload.messages),
        },
    )
    if conversation is not None:
        await persist_chat_turn_user_message(session, conversation, payload, agent_run)
    await refresh_wildcard_agent_server_tools(session, agent.id)
    tools = agent_runtime_tools(
        await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
    )
    guardrail_filter = await filter_agent_runtime_tools_for_guardrails(
        session,
        tools,
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent=agent,
    )
    latest_message = latest_user_message(payload.messages)
    if message_requests_denied_mcp_tool(latest_message, guardrail_filter):
        stream = preflight_blocked_tool_stream(guardrail_filter)
    else:
        stream = run_agent_chat(
            agent,
            credential,
            AgentChatRequest(id=payload.id, messages=payload.messages),
            guardrail_filter.allowed_tools,
            session_factory=session_factory,
            user=user,
            organization_id=organization_id,
            workspace_id=workspace_id,
            conversation=conversation,
            agent_run=agent_run,
        )
    return persisted_agent_chat_stream(
        conversation,
        stream,
        agent_run,
        session_factory=session_factory,
    )


async def update_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    workspace_id: uuid.UUID | None = None,
) -> AgentRead:
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
        include_inactive=True,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")

    scope = "workspace" if workspace_id is not None else payload.scope or agent.scope
    target_workspace_id = (
        workspace_id
        if workspace_id is not None
        else payload.workspace_id
        if "workspace_id" in payload.model_fields_set
        else agent.workspace_id
    )
    await require_agent_scope_permission(
        session,
        user,
        organization_id,
        scope=scope,
        workspace_id=target_workspace_id,
    )

    if payload.name is not None:
        name = normalize_name(payload.name)
        existing = await repository.get_agent_by_name(
            session,
            organization_id=organization_id,
            workspace_id=target_workspace_id,
            name=name,
        )
        if existing is not None and existing.id != agent.id:
            raise DuplicateAgentError("agent name already exists")
        agent.name = name
    if payload.description is not None:
        agent.description = payload.description.strip()
    if payload.instructions is not None:
        agent.instructions = payload.instructions.strip()
    if (
        workspace_id is not None
        or payload.scope is not None
        or "workspace_id" in payload.model_fields_set
    ):
        agent.scope = scope
        agent.workspace_id = target_workspace_id
    provider_credential_changed = (
        payload.provider_credential_id is not None
        or "provider_credential_id" in payload.model_fields_set
    )
    scope_changed = (
        workspace_id is not None
        or payload.scope is not None
        or "workspace_id" in payload.model_fields_set
    )
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
        agent.model_name = await validate_agent_model(
            session,
            provider_credential,
            payload.model_name,
        )
    elif provider_credential_changed and provider_credential is not None:
        agent.model_name = await validate_agent_model(
            session,
            provider_credential,
            agent.model_name,
        )
    if payload.is_active is not None:
        agent.is_active = payload.is_active

    try:
        await session.flush()
    except IntegrityError as exc:
        if is_constraint_violation(
            exc,
            {"uq_agents_org_name", "uq_agents_workspace_name"},
        ):
            raise DuplicateAgentError("agent name already exists") from exc
        raise
    await session.refresh(agent)
    return agent_response(
        agent,
        server_count=await repository.count_agent_servers(session, agent.id),
        tool_count=await repository.count_agent_tools(session, agent.id),
    )


async def delete_agent(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> None:
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
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


async def list_agent_tools(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> AgentToolListResponse:
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
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
        ],
        servers=server_assignment_responses(
            await repository.list_agent_server_assignments(session, agent_id=agent.id)
        ),
    )


async def replace_agent_tools(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentToolAssignmentUpdate,
    workspace_id: uuid.UUID | None = None,
) -> AgentToolListResponse:
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        workspace_id=workspace_id,
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

    requested_installation_ids = [server.installation_id for server in payload.servers]
    if len(set(requested_installation_ids)) != len(requested_installation_ids):
        raise InvalidAgentToolAssignmentError("server assignments must be unique")

    installation_rows = await repository.get_installations_by_ids(
        session,
        requested_installation_ids,
    )
    installations = {
        installation.id: (installation, workspace)
        for installation, workspace in installation_rows
    }
    if len(installations) != len(set(requested_installation_ids)):
        raise InvalidAgentToolAssignmentError(
            "one or more MCP server installations are not available"
        )

    unique_tool_ids = sorted(
        {
            tool_id
            for server in payload.servers
            for tool_id in server.tool_schema_ids
            if tool_id != TOOL_ASSIGNMENT_WILDCARD
        },
        key=str,
    )
    tool_rows = await repository.get_tool_schemas_by_ids(session, unique_tool_ids)
    tools_by_id = {
        tool_schema.id: (tool_schema, installation, workspace)
        for tool_schema, installation, workspace in tool_rows
    }
    if len(tools_by_id) != len(unique_tool_ids):
        raise InvalidAgentToolAssignmentError("one or more tools are not available")

    server_assignments: list[tuple[MCPServerInstallation, bool, list[MCPServerToolSchema]]] = []
    for server in payload.servers:
        installation, workspace = installations[server.installation_id]
        if workspace.organization_id != organization_id:
            raise InvalidAgentToolAssignmentError("MCP server is outside the agent organization")
        if agent.workspace_id is not None and installation.workspace_id != agent.workspace_id:
            raise InvalidAgentToolAssignmentError("MCP server must belong to the agent workspace")

        wildcard = server.tool_schema_ids == [TOOL_ASSIGNMENT_WILDCARD]
        if wildcard:
            server_assignments.append((installation, True, []))
            continue

        selected_tools: list[MCPServerToolSchema] = []
        seen_tool_ids: set[uuid.UUID] = set()
        for tool_id in server.tool_schema_ids:
            if tool_id == TOOL_ASSIGNMENT_WILDCARD:
                raise InvalidAgentToolAssignmentError(
                    "'*' cannot be combined with individual tool IDs"
                )
            if tool_id in seen_tool_ids:
                continue
            seen_tool_ids.add(tool_id)
            tool_schema, _tool_installation, tool_workspace = tools_by_id[tool_id]
            if tool_workspace.organization_id != organization_id:
                raise InvalidAgentToolAssignmentError("tool is outside the agent organization")
            if tool_schema.installation_id != installation.id:
                raise InvalidAgentToolAssignmentError(
                    "tool must belong to the assigned MCP server"
                )
            if agent.workspace_id is not None and tool_schema.workspace_id != agent.workspace_id:
                raise InvalidAgentToolAssignmentError("tool must belong to the agent workspace")
            selected_tools.append(tool_schema)
        server_assignments.append((installation, False, selected_tools))

    await repository.replace_agent_tools(
        session,
        agent_id=agent.id,
        server_assignments=server_assignments,
    )
    return AgentToolListResponse(
        tools=[
            assigned_tool_response(row)
            for row in await repository.list_agent_tools(session, agent_id=agent.id)
        ],
        servers=server_assignment_responses(
            await repository.list_agent_server_assignments(session, agent_id=agent.id)
        ),
    )
