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
from app.modules.agents.models import Agent
from app.modules.agents.schemas import (
    AgentChatMessage,
    AgentChatRequest,
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
from app.modules.llm_providers.service import (
    OPENAI_API_KEY_PROVIDER,
    OPENAI_CHATGPT_PROVIDER,
    credential_supports_model,
    read_record,
    validate_chatgpt_oauth_credential,
)
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
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


async def get_agent_model_for_run(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> tuple[Agent, LLMProviderCredential]:
    await require_organization_member(session, user, organization_id)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
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
    delta = payload.get("delta")
    if isinstance(delta, str):
        return delta

    if payload.get("type") == "response.output_text.delta":
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
) -> AsyncGenerator[str, None]:
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
                        yield text
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
                    label = tool.tool_schema.tool_name if tool else tool_call.name
                    yield f"\n\n[Running {label}]\n\n"
                    output = await execute_agent_tool_call(session, tools, tool_call)
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "output": output,
                        }
                    )

            yield "\n\nStopped after reaching the tool call limit."
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
) -> AsyncGenerator[str, None]:
    messages = provider_messages(payload.messages)
    if not messages:
        raise InvalidAgentScopeError("chat requires at least one user message")

    body = {
        "model": agent.model_name,
        "instructions": agent.instructions,
        "input": messages,
        "stream": True,
    }

    if credential.provider == OPENAI_API_KEY_PROVIDER and credential.auth_method == "api_key":
        async for text in stream_response_text(
            url=OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {credential.secret_value}",
                "Content-Type": "application/json",
            },
            body=body,
        ):
            yield text
        return

    if (
        credential.provider == OPENAI_CHATGPT_PROVIDER
        and credential.auth_method == "oauth"
        and credential.oauth_provider == "chatgpt"
    ):
        validate_chatgpt_oauth_credential(
            oauth_access_token=credential.oauth_access_token,
            oauth_refresh_token=credential.oauth_refresh_token,
            oauth_expires_at=credential.oauth_expires_at,
        )
        account_id = chatgpt_account_id(credential)
        if not account_id:
            raise InvalidAgentScopeError("ChatGPT OAuth credential is missing account metadata")
        async for text in stream_chatgpt_codex_response_text(
            session,
            agent,
            headers={
                "Authorization": f"Bearer {credential.oauth_access_token}",
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


async def stream_agent_chat(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    payload: AgentChatRequest,
) -> AsyncGenerator[str, None]:
    agent, credential = await get_agent_model_for_run(
        session,
        user,
        organization_id,
        agent_id,
    )
    messages = provider_messages(payload.messages)
    if not messages:
        raise InvalidAgentScopeError("chat requires at least one user message")
    tools = agent_runtime_tools(
        await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
    )
    return run_agent_chat(
        session,
        agent,
        credential,
        AgentChatRequest(id=payload.id, messages=payload.messages),
        tools,
    )


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
