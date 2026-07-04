import json
import os
import platform
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import WebSocketException

from app.modules.agents import repository
from app.modules.agents.exceptions import (
    AgentNotFoundError,
    DuplicateAgentError,
    InvalidAgentScopeError,
    InvalidAgentToolAssignmentError,
)
from app.modules.agents.models import Agent, ConversationMessage, WorkspaceConversation
from app.modules.agents.schemas import (
    TOOL_ASSIGNMENT_WILDCARD,
    AgentAvailableServerRead,
    AgentAvailableToolListResponse,
    AgentAvailableToolRead,
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationResponse,
    AgentCreate,
    AgentListResponse,
    AgentRead,
    AgentServerToolAssignmentRead,
    AgentToolAssignmentUpdate,
    AgentToolListResponse,
    AgentToolRead,
    AgentUpdate,
    ConversationMessageRead,
    WorkspaceConversationRead,
)
from app.modules.llm_providers import repository as llm_provider_repository
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.service import (
    OPENAI_API_KEY_PROVIDER,
    OPENAI_CHATGPT_PROVIDER,
    credential_supports_model,
    list_models_for_credential,
    read_record,
    resolve_credential_secrets,
    user_can_see_credential,
    validate_chatgpt_oauth_credential,
)
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry import repository as mcp_registry_repository
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.mcp_registry.tool_service import refresh_tool_schemas_for_installation
from app.modules.mcp_runtime.providers.kubernetes import KubernetesRuntimeProviderError
from app.modules.mcp_runtime.service import call_tool_with_tracking
from app.modules.organizations.service import (
    require_organization_admin,
    require_organization_member,
    require_workspace_admin,
    require_workspace_member,
)
from app.modules.users.models import User

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
CHATGPT_CODEX_RESPONSES_WS_URL = "wss://chatgpt.com/backend-api/codex/responses"
CHATGPT_CODEX_WEBSOCKET_BETA = "responses_websockets=2026-02-06"
DEFAULT_CODEX_COMPAT_VERSION = "0.142.0"
CODEX_COMPAT_VERSION = os.getenv("WARDN_CODEX_COMPAT_VERSION", DEFAULT_CODEX_COMPAT_VERSION)
CODEX_COMPAT_ORIGINATOR = "codex_cli_rs"
CODEX_COMPAT_USER_AGENT = (
    f"{CODEX_COMPAT_ORIGINATOR}/{CODEX_COMPAT_VERSION} "
    f"({platform.system()} {platform.release()}; {platform.machine()}) wardn"
)
AGENT_CHAT_TIMEOUT_SECONDS = 120.0
CHATGPT_CODEX_INSTRUCTIONS_MAX_CHARS = 32_000
AGENT_CHAT_MAX_TOOL_ROUNDS = 8
AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS = 40_000
QUICK_START_AGENT_NAME = "Workspace Assistant"
QUICK_START_AGENT_DESCRIPTION = "Default assistant for workspace chat."
QUICK_START_AGENT_INSTRUCTIONS = (
    "You are a workspace assistant. Use available tools when they help answer accurately. "
    "Ask before destructive actions."
)


class AgentChatProviderError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AgentRuntimeTool:
    wire_name: str
    assignment_id: uuid.UUID
    tool_schema: MCPServerToolSchema
    installation: MCPServerInstallation
    server: MCPServerVersion


@dataclass(frozen=True)
class AgentToolCall:
    name: str
    call_id: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentChatTextEvent:
    text: str


@dataclass(frozen=True)
class AgentChatToolActivityEvent:
    id: str
    tool_name: str
    status: str
    arguments: dict[str, Any] | None = None
    error: str | None = None


AgentChatStreamEvent = AgentChatTextEvent | AgentChatToolActivityEvent


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
    session: AsyncSession,
    credential: LLMProviderCredential | None,
    model_name: str,
) -> str:
    normalized_model = model_name.strip()
    if credential is None:
        return normalized_model
    if not normalized_model:
        raise InvalidAgentScopeError("model is required when an LLM credential is selected")
    if not await credential_supports_model(session, credential, normalized_model):
        raise InvalidAgentScopeError("model is not available for the selected LLM credential")
    return normalized_model


def agent_response(agent: Agent, *, server_count: int, tool_count: int) -> AgentRead:
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
        serverCount=server_count,
        toolCount=tool_count,
        createdAt=agent.created_at,
        updatedAt=agent.updated_at,
    )


def conversation_response(conversation: WorkspaceConversation) -> WorkspaceConversationRead:
    return WorkspaceConversationRead(
        id=conversation.id,
        organizationId=conversation.organization_id,
        workspaceId=conversation.workspace_id,
        agentId=conversation.agent_id,
        createdById=conversation.created_by_id,
        title=conversation.title,
        isActive=conversation.is_active,
        createdAt=conversation.created_at,
        updatedAt=conversation.updated_at,
    )


def conversation_message_response(message: ConversationMessage) -> ConversationMessageRead:
    return ConversationMessageRead(
        id=message.id,
        conversationId=message.conversation_id,
        role=message.role,
        content=message.content,
        parts=message.parts or text_parts(message.content),
        sequence=message.sequence,
        createdAt=message.created_at,
        updatedAt=message.updated_at,
    )


def text_parts(content: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": content}]


def ui_message_sse_chunk(chunk: dict[str, Any]) -> str:
    return f"data: {json.dumps(chunk, separators=(',', ':'), default=str)}\n\n"


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
    return agent_response(agent, server_count=0, tool_count=0)


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
    agent = await repository.get_agent_by_name(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=QUICK_START_AGENT_NAME,
    )
    if agent is None:
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


def text_from_chat_message(message: AgentChatMessage) -> str:
    chunks = []
    for part in message.parts:
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def provider_messages(messages: list[AgentChatMessage]) -> list[dict[str, Any]]:
    result = []
    for message in messages:
        if message.role not in {"user", "assistant"}:
            continue
        text = text_from_chat_message(message)
        if not text:
            continue
        result.append({"role": message.role, "content": text})
    return result


def agent_tool_wire_name(tool_schema: MCPServerToolSchema) -> str:
    return f"wardn_{tool_schema.id.hex}"


def agent_runtime_tools(
    rows: list[tuple[Any, MCPServerToolSchema, MCPServerInstallation, MCPServerVersion]],
) -> dict[str, AgentRuntimeTool]:
    tools = {}
    for assignment, tool_schema, installation, server in rows:
        wire_name = agent_tool_wire_name(tool_schema)
        tools[wire_name] = AgentRuntimeTool(
            wire_name=wire_name,
            assignment_id=assignment.id,
            tool_schema=tool_schema,
            installation=installation,
            server=server,
        )
    return tools


def tool_description(tool: AgentRuntimeTool) -> str:
    description = (
        tool.tool_schema.description
        or tool.tool_schema.title
        or tool.tool_schema.tool_name
    )
    return (
        f"{description}\n\n"
        f"Wardn MCP server: {tool.tool_schema.server_name}\n"
        f"MCP tool name: {tool.tool_schema.tool_name}\n"
        f"Workspace ID: {tool.installation.workspace_id}"
    )


def response_function_tools(tools: dict[str, AgentRuntimeTool]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": tool.wire_name,
            "description": tool_description(tool),
            "parameters": tool.tool_schema.input_schema or {"type": "object", "properties": {}},
        }
        for tool in tools.values()
    ]


def parse_tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AgentChatProviderError(
            f"LLM provider emitted invalid tool arguments: {value}"
        ) from exc
    if not isinstance(parsed, dict):
        raise AgentChatProviderError("LLM provider emitted non-object tool arguments")
    return parsed


def tool_calls_from_event(payload: dict[str, Any]) -> list[AgentToolCall]:
    item = read_record(payload.get("item"))
    if payload.get("type") != "response.output_item.done" or item.get("type") != "function_call":
        return []
    name = item.get("name")
    call_id = item.get("call_id")
    if not isinstance(name, str) or not name:
        return []
    if not isinstance(call_id, str) or not call_id:
        return []
    return [
        AgentToolCall(
            name=name,
            call_id=call_id,
            arguments=parse_tool_arguments(item.get("arguments")),
        )
    ]


def response_id_from_event(payload: dict[str, Any]) -> str | None:
    if payload.get("type") != "response.completed":
        return None
    response = read_record(payload.get("response"))
    response_id = response.get("id")
    return response_id if isinstance(response_id, str) and response_id else None


def mcp_result_text(result: dict[str, Any]) -> str:
    text_parts = []
    content = result.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
    if text_parts:
        text = "\n".join(text_parts)
    else:
        text = json.dumps(result, separators=(",", ":"), sort_keys=True, default=str)
    if len(text) > AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS:
        return text[:AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS] + "\n[truncated]"
    return text


async def execute_agent_tool_call(
    session: AsyncSession,
    tools: dict[str, AgentRuntimeTool],
    tool_call: AgentToolCall,
) -> str:
    tool = tools.get(tool_call.name)
    if tool is None:
        return f"Tool {tool_call.name} is not assigned to this agent."
    try:
        result = await call_tool_with_tracking(
            session,
            tool.installation,
            tool.server,
            tool_name=tool.tool_schema.tool_name,
            arguments=tool_call.arguments,
        )
        await session.commit()
    except (MCPGatewayUpstreamError, KubernetesRuntimeProviderError) as exc:
        await session.commit()
        return f"Tool {tool.tool_schema.tool_name} failed: {exc}"
    except Exception:
        await session.commit()
        raise
    return mcp_result_text(result)


def chatgpt_codex_messages(messages: list[AgentChatMessage]) -> list[dict[str, Any]]:
    result = []
    for message in messages:
        if message.role not in {"user", "assistant"}:
            continue
        text = text_from_chat_message(message)
        if not text:
            continue
        content_type = "input_text" if message.role == "user" else "output_text"
        result.append(
            {
                "role": message.role,
                "content": [{"type": content_type, "text": text}],
            }
        )
    return result


def chatgpt_codex_request_body(
    agent: Agent,
    *,
    input_items: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    previous_response_id: str | None = None,
) -> dict[str, Any]:
    body = {
        "type": "response.create",
        "model": agent.model_name,
        "instructions": agent.instructions[:CHATGPT_CODEX_INSTRUCTIONS_MAX_CHARS],
        "input": input_items,
        "tools": tools,
        "tool_choice": "auto",
        "parallel_tool_calls": bool(tools),
        "reasoning": None,
        "store": False,
        "stream": True,
        "include": [],
    }
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    return body


def sse_payloads(buffer: str) -> tuple[list[dict[str, Any]], str]:
    payloads = []
    while "\n\n" in buffer:
        block, buffer = buffer.split("\n\n", 1)
        data_lines = []
        for line in block.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        if data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads, buffer


def text_delta_from_openai_event(payload: dict[str, Any]) -> str:
    if payload.get("type") == "response.output_text.delta":
        delta = payload.get("delta")
        return delta if isinstance(delta, str) else ""

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            choice_delta = read_record(first.get("delta"))
            content = choice_delta.get("content")
            if isinstance(content, str):
                return content
    return ""


def chatgpt_account_id(credential: LLMProviderCredential) -> str:
    metadata = credential.oauth_metadata or {}
    account_id = metadata.get("accountId")
    return account_id if isinstance(account_id, str) else ""


async def stream_response_text(
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> AsyncGenerator[str, None]:
    timeout = httpx.Timeout(AGENT_CHAT_TIMEOUT_SECONDS, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if not response.is_success:
                response_body = await response.aread()
                detail = response_body.decode("utf-8", errors="replace").strip()
                raise AgentChatProviderError(
                    f"LLM provider returned HTTP {response.status_code}: {detail}",
                    status_code=response.status_code,
                )
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                payloads, buffer = sse_payloads(buffer)
                for payload in payloads:
                    text = text_delta_from_openai_event(payload)
                    if text:
                        yield text


def websocket_error_message(payload: dict[str, Any]) -> str | None:
    if payload.get("type") != "error":
        return None
    error = read_record(payload.get("error"))
    message = error.get("message") or payload.get("message") or payload.get("detail")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return json.dumps(payload, separators=(",", ":"))


async def stream_chatgpt_codex_response_text(
    session: AsyncSession,
    agent: Agent,
    *,
    headers: dict[str, str],
    messages: list[AgentChatMessage],
    tools: dict[str, AgentRuntimeTool],
) -> AsyncGenerator[AgentChatStreamEvent, None]:
    try:
        async with websocket_connect(
            CHATGPT_CODEX_RESPONSES_WS_URL,
            additional_headers=headers,
            user_agent_header=CODEX_COMPAT_USER_AGENT,
            open_timeout=30.0,
            ping_interval=20.0,
            ping_timeout=20.0,
            max_size=None,
        ) as websocket:
            previous_response_id = None
            input_items = chatgpt_codex_messages(messages)
            function_tools = response_function_tools(tools)

            for _round_index in range(AGENT_CHAT_MAX_TOOL_ROUNDS):
                body = chatgpt_codex_request_body(
                    agent,
                    input_items=input_items,
                    tools=function_tools,
                    previous_response_id=previous_response_id,
                )
                await websocket.send(json.dumps(body, separators=(",", ":")))
                tool_calls: list[AgentToolCall] = []

                async for raw_message in websocket:
                    if isinstance(raw_message, bytes):
                        raw_message = raw_message.decode("utf-8", errors="replace")
                    try:
                        payload = json.loads(raw_message)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    error_message = websocket_error_message(payload)
                    if error_message:
                        status = payload.get("status") or payload.get("status_code")
                        status_code = status if isinstance(status, int) else 502
                        raise AgentChatProviderError(
                            f"LLM provider returned HTTP {status_code}: {error_message}",
                            status_code=status_code,
                        )
                    text = text_delta_from_openai_event(payload)
                    if text:
                        yield AgentChatTextEvent(text=text)
                    tool_calls.extend(tool_calls_from_event(payload))
                    response_id = response_id_from_event(payload)
                    if response_id:
                        previous_response_id = response_id
                    if payload.get("type") == "response.completed":
                        break

                if not tool_calls:
                    return

                input_items = []
                for tool_call in tool_calls:
                    tool = tools.get(tool_call.name)
                    tool_name = (
                        tool.tool_schema.tool_name
                        if tool is not None
                        else tool_call.name
                    )
                    activity_id = f"tool-{tool_call.call_id}"
                    yield AgentChatToolActivityEvent(
                        id=activity_id,
                        tool_name=tool_name,
                        status="running",
                        arguments=tool_call.arguments,
                    )
                    output = await execute_agent_tool_call(session, tools, tool_call)
                    failed_prefix = f"Tool {tool_name} failed:"
                    yield AgentChatToolActivityEvent(
                        id=activity_id,
                        tool_name=tool_name,
                        status="failed" if output.startswith(failed_prefix) else "completed",
                        error=output if output.startswith(failed_prefix) else None,
                    )
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "output": output,
                        }
                    )

            yield AgentChatTextEvent(text="\n\nStopped after reaching the tool call limit.")
    except AgentChatProviderError:
        raise
    except WebSocketException as exc:
        raise AgentChatProviderError(f"LLM provider websocket failed: {exc}") from exc
    except TimeoutError as exc:
        raise AgentChatProviderError("LLM provider websocket timed out") from exc


async def run_agent_chat(
    session: AsyncSession,
    agent: Agent,
    credential: LLMProviderCredential,
    payload: AgentChatRequest,
    tools: dict[str, AgentRuntimeTool],
) -> AsyncGenerator[AgentChatStreamEvent, None]:
    messages = provider_messages(payload.messages)
    if not messages:
        raise InvalidAgentScopeError("chat requires at least one user message")

    body = {
        "model": agent.model_name,
        "instructions": agent.instructions,
        "input": messages,
        "stream": True,
    }
    credential_secrets = await resolve_credential_secrets(session, credential)

    if credential.provider == OPENAI_API_KEY_PROVIDER and credential.auth_method == "api_key":
        async for text in stream_response_text(
            url=OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {credential_secrets.api_key}",
                "Content-Type": "application/json",
            },
            body=body,
        ):
            yield AgentChatTextEvent(text=text)
        return

    if (
        credential.provider == OPENAI_CHATGPT_PROVIDER
        and credential.auth_method == "oauth"
        and credential.oauth_provider == "chatgpt"
    ):
        validate_chatgpt_oauth_credential(
            oauth_access_token=credential_secrets.oauth_access_token,
            oauth_refresh_token=credential_secrets.oauth_refresh_token,
            oauth_expires_at=credential.oauth_expires_at,
        )
        account_id = chatgpt_account_id(credential)
        if not account_id:
            raise InvalidAgentScopeError("ChatGPT OAuth credential is missing account metadata")
        async for text in stream_chatgpt_codex_response_text(
            session,
            agent,
            headers={
                "Authorization": f"Bearer {credential_secrets.oauth_access_token}",
                "ChatGPT-Account-ID": account_id,
                "OpenAI-Beta": CHATGPT_CODEX_WEBSOCKET_BETA,
                "originator": CODEX_COMPAT_ORIGINATOR,
                "version": CODEX_COMPAT_VERSION,
            },
            messages=payload.messages,
            tools=tools,
        ):
            yield text
        return

    raise InvalidAgentScopeError("agent credential provider is not supported for chat")


def conversation_id_from_payload(payload: AgentChatRequest) -> uuid.UUID | None:
    if not payload.id:
        return None
    try:
        return uuid.UUID(str(payload.id))
    except ValueError as exc:
        raise InvalidAgentScopeError("chat conversation id is invalid") from exc


def latest_user_message(messages: list[AgentChatMessage]) -> AgentChatMessage | None:
    return next((message for message in reversed(messages) if message.role == "user"), None)


async def persist_chat_turn_user_message(
    session: AsyncSession,
    conversation: WorkspaceConversation,
    payload: AgentChatRequest,
) -> None:
    message = latest_user_message(payload.messages)
    if message is None:
        return
    content = text_from_chat_message(message)
    if not content:
        return
    await repository.append_conversation_message(
        session,
        conversation_id=conversation.id,
        role="user",
        content=content,
        parts=text_parts(content),
    )
    await session.commit()


async def persisted_agent_chat_stream(
    session: AsyncSession,
    conversation: WorkspaceConversation | None,
    stream: AsyncGenerator[AgentChatStreamEvent, None],
) -> AsyncGenerator[str, None]:
    message_id = str(uuid.uuid4())
    text_id = f"text-{message_id}"
    chunks: list[str] = []
    text_started = False
    activity_parts: dict[str, dict[str, Any]] = {}
    yield ui_message_sse_chunk({"type": "start", "messageId": message_id})
    async for event in stream:
        if isinstance(event, AgentChatTextEvent):
            if not event.text:
                continue
            if not text_started:
                text_started = True
                yield ui_message_sse_chunk({"type": "text-start", "id": text_id})
            chunks.append(event.text)
            yield ui_message_sse_chunk(
                {"type": "text-delta", "id": text_id, "delta": event.text}
            )
            continue
        data: dict[str, Any] = {
            "toolName": event.tool_name,
            "status": event.status,
        }
        if event.arguments is not None:
            data["arguments"] = event.arguments
        if event.error:
            data["error"] = event.error
        activity_part = {
            "type": "data-tool-activity",
            "id": event.id,
            "data": data,
        }
        activity_parts[event.id] = activity_part
        yield ui_message_sse_chunk(activity_part)
    if text_started:
        yield ui_message_sse_chunk({"type": "text-end", "id": text_id})
    yield ui_message_sse_chunk({"type": "finish", "finishReason": "stop"})
    if conversation is None:
        return
    content = "".join(chunks).strip()
    parts = list(activity_parts.values())
    if content:
        parts.append({"type": "text", "text": content})
    if not parts:
        return
    await repository.append_conversation_message(
        session,
        conversation_id=conversation.id,
        role="assistant",
        content=content,
        parts=parts,
    )
    await session.commit()


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
    if rows:
        await session.commit()


async def stream_agent_chat(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentChatRequest,
    workspace_id: uuid.UUID | None = None,
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
    conversation = None
    conversation_id = conversation_id_from_payload(payload)
    if conversation_id is not None:
        if workspace_id is None:
            raise InvalidAgentScopeError("conversation chat requires a workspace")
        conversation = await repository.get_workspace_conversation(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
        )
        if conversation is None or conversation.agent_id != agent.id:
            raise AgentNotFoundError("conversation not found")
        await persist_chat_turn_user_message(session, conversation, payload)
    await refresh_wildcard_agent_server_tools(session, agent.id)
    tools = agent_runtime_tools(
        await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
    )
    stream = run_agent_chat(
        session,
        agent,
        credential,
        AgentChatRequest(id=payload.id, messages=payload.messages),
        tools,
    )
    return persisted_agent_chat_stream(session, conversation, stream)


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

    await session.flush()
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


def assigned_tool_response(row) -> AgentToolRead:
    assignment, tool_schema, installation = row
    if tool_schema.workspace_id is None:
        raise InvalidAgentToolAssignmentError("assigned tool has no workspace")
    return AgentToolRead(
        id=tool_schema.id,
        agentId=assignment.agent_id,
        toolSchemaId=tool_schema.id,
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


def server_assignment_responses(rows) -> list[AgentServerToolAssignmentRead]:
    assignments: dict[uuid.UUID, list[uuid.UUID | str]] = {}
    for server_assignment, tool_assignment in rows:
        selected = assignments.setdefault(server_assignment.installation_id, [])
        if tool_assignment.wildcard:
            selected[:] = [TOOL_ASSIGNMENT_WILDCARD]
        elif TOOL_ASSIGNMENT_WILDCARD not in selected and tool_assignment.tool_schema_id:
            selected.append(tool_assignment.tool_schema_id)
    return [
        AgentServerToolAssignmentRead(
            installationId=installation_id,
            toolSchemaIds=tool_schema_ids,
        )
        for installation_id, tool_schema_ids in assignments.items()
    ]


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
