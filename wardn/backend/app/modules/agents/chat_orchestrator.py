import json
import re
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import InvalidStatus, WebSocketException

from app.modules.agents import repository
from app.modules.agents.conversations import AgentSessionFactory, agent_stream_unit_of_work
from app.modules.agents.exceptions import InvalidAgentScopeError
from app.modules.agents.mappers import (
    sanitize_run_payload,
    text_parts,
)
from app.modules.agents.models import (
    Agent,
    AgentRun,
    WorkspaceConversation,
)
from app.modules.agents.provider_clients import (
    CHATGPT_CODEX_RESPONSES_WS_URL,
    CODEX_COMPAT_USER_AGENT,
    OPENAI_RESPONSES_URL,
    chatgpt_account_id,
    chatgpt_codex_headers,
    chatgpt_codex_messages,
    chatgpt_codex_request_body,
    llm_usage_from_completed_event,
    provider_messages,
    response_function_tools,
    response_id_from_event,
    stream_response_text,
    text_delta_from_openai_event,
    text_from_chat_message,
    tool_calls_from_event,
    websocket_error_message,
)
from app.modules.agents.schemas import AgentChatMessage, AgentChatRequest
from app.modules.agents.tool_execution import (
    execute_agent_tool_call_with_progress,
    tool_execution_result,
)
from app.modules.agents.types import (
    AgentChatProviderError,
    AgentChatStreamEvent,
    AgentChatTextEvent,
    AgentChatToolActivityEvent,
    AgentRuntimeTool,
    AgentRuntimeToolGuardrailFilter,
    AgentToolCall,
    AgentToolExecutionResult,
)
from app.modules.guardrails.service import (
    GUARDRAIL_MODE_DENY,
    GuardrailDecision,
    GuardrailEvaluationContext,
    evaluate_tool_call_guardrails,
)
from app.modules.limits import service as limits_service
from app.modules.llm_providers import repository as llm_provider_repository
from app.modules.llm_providers.exceptions import InvalidLLMProviderCredentialAuthError
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.service import (
    OPENAI_API_KEY_PROVIDER,
    OPENAI_CHATGPT_PROVIDER,
    ResolvedLLMCredentialSecrets,
    refresh_chatgpt_oauth_credential,
    resolve_credential_secrets,
    validate_chatgpt_oauth_credential,
)
from app.modules.observability import service as observability_service
from app.modules.users.models import User

AGENT_CHAT_MAX_TOOL_ROUNDS = 8
MCP_REQUEST_ACTION_WORDS = {
    "call",
    "check",
    "create",
    "delete",
    "fetch",
    "find",
    "get",
    "list",
    "lookup",
    "read",
    "run",
    "search",
    "update",
    "use",
}

async def persist_chat_turn_user_message(
    session: AsyncSession,
    conversation: WorkspaceConversation,
    payload: AgentChatRequest,
    agent_run: AgentRun | None = None,
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
        agent_run_id=agent_run.id if agent_run else None,
    )


def latest_user_message(messages: list[AgentChatMessage]) -> AgentChatMessage | None:
    return next((message for message in reversed(messages) if message.role == "user"), None)


async def persisted_agent_chat_stream(
    conversation: WorkspaceConversation | None,
    stream: AsyncGenerator[AgentChatStreamEvent, None],
    agent_run: AgentRun | None = None,
    *,
    session_factory: AgentSessionFactory | None = None,
) -> AsyncGenerator[str, None]:
    message_id = str(uuid.uuid4())
    text_id = f"text-{message_id}"
    chunks: list[str] = []
    text_started = False
    stream_error: str | None = None
    paused_for_confirmation = False
    activity_parts: dict[str, dict[str, Any]] = {}
    yield ui_message_sse_chunk({"type": "start", "messageId": message_id})
    try:
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
            if event.status == "requires_confirmation":
                paused_for_confirmation = True
            if event.arguments is not None:
                data["arguments"] = sanitize_run_payload(event.arguments)
            if event.error:
                data["error"] = event.error
            if event.message:
                data["message"] = event.message
            if event.progress is not None:
                data["progress"] = event.progress
            if event.progress_token is not None:
                data["progressToken"] = event.progress_token
            if event.result:
                data["result"] = sanitize_run_payload(event.result)
            if event.total is not None:
                data["total"] = event.total
            if event.approval:
                data["approval"] = sanitize_run_payload(event.approval)
            activity_part = {
                "type": "data-tool-activity",
                "id": event.id,
                "data": data,
            }
            activity_parts[event.id] = activity_part
            is_progress_update = event.progress is not None or event.message is not None
            if agent_run is not None and not is_progress_update:
                async with agent_stream_unit_of_work(session_factory) as session:
                    await repository.append_agent_run_step(
                        session,
                        agent_run_id=agent_run.id,
                        step_type="tool_call"
                        if event.status == "running"
                        else "tool_result",
                        status=event.status,
                        title=event.tool_name,
                        payload=sanitize_run_payload(data),
                    )
            yield ui_message_sse_chunk(activity_part)
    except Exception as exc:
        stream_error = str(exc)
        error_text = chat_stream_error_text(exc)
        if not text_started:
            text_started = True
            yield ui_message_sse_chunk({"type": "text-start", "id": text_id})
        chunks.append(error_text)
        yield ui_message_sse_chunk(
            {"type": "text-delta", "id": text_id, "delta": error_text}
        )
        if agent_run is not None:
            async with agent_stream_unit_of_work(session_factory) as session:
                await repository.append_agent_run_step(
                    session,
                    agent_run_id=agent_run.id,
                    step_type="error",
                    status="failed",
                    title=exc.__class__.__name__,
                    payload={"message": str(exc)},
                )
    if text_started:
        yield ui_message_sse_chunk({"type": "text-end", "id": text_id})
    yield ui_message_sse_chunk(
        {"type": "finish", "finishReason": "error" if stream_error else "stop"}
    )
    content = "".join(chunks).strip()
    parts = list(activity_parts.values())
    if content:
        parts.append({"type": "text", "text": content})
    async with agent_stream_unit_of_work(session_factory) as session:
        if agent_run is not None and content:
            await repository.append_agent_run_step(
                session,
                agent_run_id=agent_run.id,
                step_type="model_output",
                status="failed" if stream_error else "succeeded",
                title="Assistant response" if stream_error is None else "Assistant error",
                payload={"content": sanitize_run_payload(content)},
            )
        if conversation is not None and parts:
            await repository.append_conversation_message(
                session,
                conversation_id=conversation.id,
                role="assistant",
                content=content,
                parts=parts,
                agent_run_id=agent_run.id if agent_run else None,
            )
        if agent_run is not None:
            run_status = "failed" if stream_error else "succeeded"
            run_error = stream_error or ""
            if paused_for_confirmation and stream_error is None:
                run_status = "waiting_confirmation"
                run_error = ""
            stored_run = await repository.get_agent_run(
                session,
                organization_id=agent_run.organization_id,
                workspace_id=agent_run.workspace_id,
                agent_run_id=agent_run.id,
            )
            if stored_run is not None:
                await repository.finish_agent_run(
                    session,
                    stored_run,
                    status=run_status,
                    error=run_error,
                )


async def preflight_blocked_tool_stream(
    guardrail_filter: AgentRuntimeToolGuardrailFilter,
) -> AsyncGenerator[AgentChatStreamEvent, None]:
    first_tool, first_decision = next(iter(guardrail_filter.denied_tools.values()))
    policy_name = first_decision.policy_name or "workspace guardrail"
    message = (
        f"I can't run that MCP request because it is blocked by guardrail policy: "
        f"{policy_name}."
    )
    yield AgentChatToolActivityEvent(
        id=f"guardrail-{uuid.uuid4()}",
        tool_name=first_tool.tool_schema.tool_name,
        status="blocked",
        error=first_decision.message or message,
    )
    yield AgentChatTextEvent(text=message)


async def run_agent_chat(
    agent: Agent,
    credential: LLMProviderCredential,
    payload: AgentChatRequest,
    tools: dict[str, AgentRuntimeTool],
    *,
    session_factory: AgentSessionFactory | None = None,
    user: User | None = None,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    conversation: WorkspaceConversation | None = None,
    agent_run: AgentRun | None = None,
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
    async with agent_stream_unit_of_work(session_factory) as session:
        credential_secrets = await resolve_credential_secrets(session, credential)

    if credential.provider == OPENAI_API_KEY_PROVIDER and credential.auth_method == "api_key":
        call_started_at = datetime.now(UTC)
        call_usage: observability_service.LLMTokenUsage | None = None
        async with agent_stream_unit_of_work(session_factory) as session:
            await require_agent_llm_budget_available(
                session,
                agent=agent,
                user=user,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )

        def capture_usage(usage: observability_service.LLMTokenUsage) -> None:
            nonlocal call_usage
            call_usage = usage

        try:
            async for text in stream_response_text(
                url=OPENAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {credential_secrets.api_key}",
                    "Content-Type": "application/json",
                },
                body=body,
                usage_callback=capture_usage,
            ):
                yield AgentChatTextEvent(text=text)
        except Exception as exc:
            async with agent_stream_unit_of_work(session_factory) as session:
                await record_agent_llm_usage(
                    session,
                    credential=credential,
                    agent=agent,
                    user=user,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    agent_run=agent_run,
                    usage=call_usage,
                    started_at=call_started_at,
                    finished_at=datetime.now(UTC),
                    status="failed",
                    error=str(exc),
                )
            raise
        async with agent_stream_unit_of_work(session_factory) as session:
            await record_agent_llm_usage(
                session,
                credential=credential,
                agent=agent,
                user=user,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agent_run=agent_run,
                usage=call_usage,
                started_at=call_started_at,
                finished_at=datetime.now(UTC),
                status="succeeded",
            )
        return

    if (
        credential.provider == OPENAI_CHATGPT_PROVIDER
        and credential.auth_method == "oauth"
        and credential.oauth_provider == "chatgpt"
    ):
        try:
            validate_chatgpt_oauth_credential(
                oauth_access_token=credential_secrets.oauth_access_token,
                oauth_refresh_token=credential_secrets.oauth_refresh_token,
                oauth_expires_at=credential.oauth_expires_at,
            )
        except InvalidLLMProviderCredentialAuthError as exc:
            if "expired" not in str(exc).casefold():
                raise
            credential_secrets, account_id = await refresh_agent_chat_credential(
                credential,
                credential_secrets,
                session_factory=session_factory,
            )
        else:
            account_id = chatgpt_account_id(credential)
        if not account_id:
            raise InvalidAgentScopeError("ChatGPT OAuth credential is missing account metadata")
        try:
            async for text in stream_chatgpt_codex_response_text(
                agent,
                credential,
                session_factory=session_factory,
                user=user,
                organization_id=organization_id,
                workspace_id=workspace_id,
                conversation=conversation,
                agent_run=agent_run,
                headers=chatgpt_codex_headers(
                    credential_secrets.oauth_access_token,
                    account_id,
                ),
                messages=payload.messages,
                tools=tools,
            ):
                yield text
        except AgentChatProviderError as exc:
            if exc.status_code != 401:
                raise
            credential_secrets, account_id = await refresh_agent_chat_credential(
                credential,
                credential_secrets,
                session_factory=session_factory,
            )
            if not account_id:
                raise InvalidAgentScopeError(
                    "ChatGPT OAuth credential is missing account metadata"
                ) from exc
            async for text in stream_chatgpt_codex_response_text(
                agent,
                credential,
                session_factory=session_factory,
                user=user,
                organization_id=organization_id,
                workspace_id=workspace_id,
                conversation=conversation,
                agent_run=agent_run,
                headers=chatgpt_codex_headers(
                    credential_secrets.oauth_access_token,
                    account_id,
                ),
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


def ui_message_sse_chunk(chunk: dict[str, Any]) -> str:
    return f"data: {json.dumps(chunk, separators=(',', ':'), default=str)}\n\n"


def normalize_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


async def stream_chatgpt_codex_response_text(
    agent: Agent,
    credential: LLMProviderCredential,
    *,
    session_factory: AgentSessionFactory | None = None,
    user: User | None = None,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    conversation: WorkspaceConversation | None = None,
    agent_run: AgentRun | None = None,
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
                call_started_at = datetime.now(UTC)
                call_usage: observability_service.LLMTokenUsage | None = None
                tool_calls: list[AgentToolCall] = []
                async with agent_stream_unit_of_work(session_factory) as session:
                    await require_agent_llm_budget_available(
                        session,
                        agent=agent,
                        user=user,
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                    )

                try:
                    await websocket.send(json.dumps(body, separators=(",", ":")))
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
                        usage = llm_usage_from_completed_event(payload)
                        if usage is not None:
                            call_usage = usage
                        text = text_delta_from_openai_event(payload)
                        if text:
                            yield AgentChatTextEvent(text=text)
                        tool_calls.extend(tool_calls_from_event(payload))
                        response_id = response_id_from_event(payload)
                        if response_id:
                            previous_response_id = response_id
                        if payload.get("type") == "response.completed":
                            break
                except Exception as exc:
                    async with agent_stream_unit_of_work(session_factory) as session:
                        await record_agent_llm_usage(
                            session,
                            credential=credential,
                            agent=agent,
                            user=user,
                            organization_id=organization_id,
                            workspace_id=workspace_id,
                            agent_run=agent_run,
                            usage=call_usage,
                            started_at=call_started_at,
                            finished_at=datetime.now(UTC),
                            status="failed",
                            error=str(exc),
                        )
                    raise

                async with agent_stream_unit_of_work(session_factory) as session:
                    await record_agent_llm_usage(
                        session,
                        credential=credential,
                        agent=agent,
                        user=user,
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        agent_run=agent_run,
                        usage=call_usage,
                        started_at=call_started_at,
                        finished_at=datetime.now(UTC),
                        status="succeeded",
                    )

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
                    execution: AgentToolExecutionResult | None = None
                    async for update in execute_agent_tool_call_with_progress(
                        tools,
                        tool_call,
                        session_factory=session_factory,
                        activity_id=activity_id,
                        tool_name=tool_name,
                        user=user,
                        organization_id=organization_id,
                        workspace_id=workspace_id,
                        agent=agent,
                        conversation=conversation,
                        agent_run=agent_run,
                    ):
                        if isinstance(update, AgentChatToolActivityEvent):
                            yield update
                        else:
                            execution = update
                    if execution is None:
                        execution = tool_execution_result(
                            tool_name,
                            f"Tool {tool_name} failed: no tool result was returned",
                        )
                    yield AgentChatToolActivityEvent(
                        id=activity_id,
                        tool_name=tool_name,
                        status=execution.status,
                        error=execution.error,
                        result=execution.result,
                        approval=execution.approval,
                    )
                    if execution.status == "requires_confirmation":
                        return
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "output": execution.output,
                        }
                    )

            yield AgentChatTextEvent(text="\n\nStopped after reaching the tool call limit.")
    except AgentChatProviderError:
        raise
    except InvalidStatus as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if not isinstance(status_code, int):
            status_code = 502
        raise AgentChatProviderError(
            f"LLM provider websocket failed with HTTP {status_code}",
            status_code=status_code,
        ) from exc
    except WebSocketException as exc:
        raise AgentChatProviderError(f"LLM provider websocket failed: {exc}") from exc
    except TimeoutError as exc:
        raise AgentChatProviderError("LLM provider websocket timed out") from exc


def message_requests_denied_mcp_tool(
    message: AgentChatMessage | None,
    guardrail_filter: AgentRuntimeToolGuardrailFilter,
) -> bool:
    if message is None or not guardrail_filter.denied_tools:
        return False
    text = normalize_match_text(text_from_chat_message(message))
    if not text:
        return False
    words = set(text.split())
    has_action = bool(words & MCP_REQUEST_ACTION_WORDS)
    for tool, _decision in guardrail_filter.denied_tools.values():
        if any(term and term in text for term in denied_tool_match_terms(tool)):
            return True
    return has_action and not guardrail_filter.allowed_tools


async def refresh_agent_chat_credential(
    credential: LLMProviderCredential,
    secrets: ResolvedLLMCredentialSecrets,
    *,
    session_factory: AgentSessionFactory | None = None,
) -> tuple[ResolvedLLMCredentialSecrets, str]:
    async with agent_stream_unit_of_work(session_factory) as session:
        stored_credential = await llm_provider_repository.get_credential(
            session,
            organization_id=credential.organization_id,
            credential_id=credential.id,
        )
        if stored_credential is None:
            raise InvalidAgentScopeError("agent credential is no longer available")
        refreshed = await refresh_chatgpt_oauth_credential(
            session,
            stored_credential,
            secrets,
        )
        return refreshed, chatgpt_account_id(stored_credential)


async def record_agent_llm_usage(
    session: AsyncSession,
    *,
    credential: LLMProviderCredential,
    agent: Agent,
    user: User | None,
    organization_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None,
    agent_run: AgentRun | None,
    usage: observability_service.LLMTokenUsage | None,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    error: str = "",
) -> None:
    if organization_id is None or workspace_id is None:
        return
    usage = usage or observability_service.LLMTokenUsage()
    await observability_service.record_llm_usage(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        user_id=user.id if user else None,
        agent_id=agent.id,
        agent_run_id=agent_run.id if agent_run else None,
        provider=credential.provider,
        model=usage.response_model or agent.model_name,
        usage=usage,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        error=error,
    )


def chat_stream_error_text(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    if isinstance(exc, AgentChatProviderError) and exc.status_code == 401:
        return (
            "ChatGPT rejected the stored OAuth token. I tried refreshing it once, but the "
            "credential still could not be used. Reconnect or validate the LLM credential."
        )
    return f"I couldn't complete the response: {message}"


async def filter_agent_runtime_tools_for_guardrails(
    session: AsyncSession,
    tools: dict[str, AgentRuntimeTool],
    *,
    user: User | None,
    organization_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None,
    agent: Agent,
) -> AgentRuntimeToolGuardrailFilter:
    if organization_id is None:
        return AgentRuntimeToolGuardrailFilter(allowed_tools=tools, denied_tools={})
    filtered_tools: dict[str, AgentRuntimeTool] = {}
    denied_tools: dict[str, tuple[AgentRuntimeTool, GuardrailDecision]] = {}
    for wire_name, tool in tools.items():
        decision = await evaluate_tool_call_guardrails(
            session,
            GuardrailEvaluationContext(
                organization_id=organization_id,
                workspace_id=workspace_id or tool.installation.workspace_id,
                user_id=user.id if user else None,
                agent_id=agent.id,
                conversation_id=None,
                agent_run_id=None,
                installation_id=tool.installation.id,
                tool_schema_id=tool.tool_schema.id,
                server_name=tool.server.name,
                tool_name=tool.tool_schema.tool_name,
                arguments={},
            ),
        )
        if decision.mode == GUARDRAIL_MODE_DENY:
            denied_tools[wire_name] = (tool, decision)
            continue
        filtered_tools[wire_name] = tool
    return AgentRuntimeToolGuardrailFilter(
        allowed_tools=filtered_tools,
        denied_tools=denied_tools,
    )


async def require_agent_llm_budget_available(
    session: AsyncSession,
    *,
    agent: Agent,
    user: User | None,
    organization_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None,
) -> None:
    if organization_id is None or workspace_id is None:
        return
    await limits_service.require_llm_budget_available(
        session,
        limits_service.LLMBudgetContext(
            organization_id=organization_id,
            workspace_id=workspace_id,
            user_id=user.id if user else None,
            agent_id=agent.id,
            model=agent.model_name,
        ),
    )


def denied_tool_match_terms(tool: AgentRuntimeTool) -> set[str]:
    values = [
        tool.tool_schema.tool_name,
        tool.tool_schema.title or "",
        tool.tool_schema.description or "",
        tool.tool_schema.server_name,
        tool.server.name,
        tool.server.description or "",
        tool.installation.config_name,
    ]
    terms: set[str] = set()
    for value in values:
        normalized = normalize_match_text(value)
        if normalized:
            terms.add(normalized)
            terms.update(part for part in normalized.split() if len(part) >= 4)
    return terms
