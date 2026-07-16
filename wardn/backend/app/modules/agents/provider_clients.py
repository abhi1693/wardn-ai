import json
import os
import platform
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.exceptions import InvalidAgentScopeError
from app.modules.agents.models import Agent
from app.modules.agents.schemas import AgentChatMessage
from app.modules.agents.types import AgentChatProviderError, AgentRuntimeTool, AgentToolCall
from app.modules.llm_providers import repository as llm_provider_repository
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.service import credential_supports_model, read_record
from app.modules.mcp_registry.models import MCPServerToolSchema
from app.modules.observability import service as observability_service
from app.modules.users.models import User

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
CHATGPT_CODEX_RESPONSES_WS_URL = "wss://chatgpt.com/backend-api/codex/responses"
CHATGPT_CODEX_WEBSOCKET_BETA = "responses_websockets=2026-02-06"
DEFAULT_CODEX_COMPAT_VERSION = "0.144.0"
CODEX_COMPAT_VERSION = os.getenv("WARDN_CODEX_COMPAT_VERSION", DEFAULT_CODEX_COMPAT_VERSION)
CODEX_COMPAT_ORIGINATOR = "codex_cli_rs"
CODEX_COMPAT_USER_AGENT = (
    f"{CODEX_COMPAT_ORIGINATOR}/{CODEX_COMPAT_VERSION} "
    f"({platform.system()} {platform.release()}; {platform.machine()}) wardn"
)
AGENT_CHAT_TIMEOUT_SECONDS = 120.0
CHATGPT_CODEX_INSTRUCTIONS_MAX_CHARS = 32_000


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


def agent_tool_wire_name(tool_schema: MCPServerToolSchema) -> str:
    return f"wardn_{tool_schema.id.hex}"


def agent_runtime_tools(rows: list[tuple[Any, ...]]) -> dict[str, AgentRuntimeTool]:
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
        tool.tool_schema.description or tool.tool_schema.title or tool.tool_schema.tool_name
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


def int_token_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0


def llm_usage_from_response(response: dict[str, Any]) -> observability_service.LLMTokenUsage:
    usage = read_record(response.get("usage"))
    input_tokens = int_token_value(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_tokens = int_token_value(
        usage.get("output_tokens") or usage.get("completion_tokens")
    )
    total_tokens = int_token_value(usage.get("total_tokens"))
    input_details = read_record(
        usage.get("input_tokens_details") or usage.get("prompt_tokens_details")
    )
    cache_creation = read_record(
        usage.get("cache_creation_input_tokens_details") or input_details.get("cache_creation")
    )
    cache_write_tokens = int_token_value(
        usage.get("cache_creation_input_tokens")
        or input_details.get("cache_creation_input_tokens")
        or cache_creation.get("input_tokens")
    )
    response_model = response.get("model")
    return observability_service.LLMTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens or input_tokens + output_tokens,
        cache_read_input_tokens=int_token_value(
            usage.get("cache_read_input_tokens")
            or input_details.get("cached_tokens")
            or input_details.get("cache_read_input_tokens")
        ),
        cache_write_input_tokens=cache_write_tokens,
        response_model=response_model if isinstance(response_model, str) else "",
    )


def llm_usage_from_completed_event(
    payload: dict[str, Any],
) -> observability_service.LLMTokenUsage | None:
    if payload.get("type") != "response.completed":
        return None
    return llm_usage_from_response(read_record(payload.get("response")))


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
        data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
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
            content = read_record(first.get("delta")).get("content")
            if isinstance(content, str):
                return content
    return ""


def chatgpt_account_id(credential: LLMProviderCredential) -> str:
    account_id = (credential.oauth_metadata or {}).get("accountId")
    return account_id if isinstance(account_id, str) else ""


def chatgpt_codex_headers(access_token: str, account_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "ChatGPT-Account-ID": account_id,
        "OpenAI-Beta": CHATGPT_CODEX_WEBSOCKET_BETA,
        "originator": CODEX_COMPAT_ORIGINATOR,
        "version": CODEX_COMPAT_VERSION,
    }


async def stream_response_text(
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    usage_callback=None,
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
                    usage = llm_usage_from_completed_event(payload)
                    if usage is not None and usage_callback is not None:
                        usage_callback(usage)
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
