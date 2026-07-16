import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.agents import service
from app.modules.agents.exceptions import (
    DuplicateAgentError,
    InvalidAgentScopeError,
    InvalidAgentToolAssignmentError,
)
from app.modules.agents.models import (
    Agent,
    AgentMCPServerAssignment,
    AgentMCPToolAssignment,
    AgentRun,
    WorkspaceConversation,
)
from app.modules.agents.schemas import (
    AgentChatMessage,
    AgentChatRequest,
    AgentCreate,
    AgentToolAssignmentUpdate,
)
from app.modules.guardrails.service import GuardrailDecision
from app.modules.llm_providers.models import LLMProviderCredential
from app.modules.llm_providers.schemas import LLMProviderModelListResponse, LLMProviderModelRead
from app.modules.llm_providers.service import ResolvedLLMCredentialSecrets
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)
from app.modules.organizations.models import Organization, OrganizationMembership, Workspace
from app.modules.users.models import User


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.in_transaction = False

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()
            instance.created_at = now
            instance.updated_at = now

    async def refresh(self, instance: object) -> None:
        now = datetime(2026, 6, 23, tzinfo=UTC)
        if getattr(instance, "id", None) is None:
            instance.id = uuid4()
        instance.created_at = getattr(instance, "created_at", now)
        instance.updated_at = now

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    def begin(self):
        return FakeTransaction(self)


class FakeTransaction:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self):
        self.session.in_transaction = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.session.in_transaction = False
        if exc_type is None:
            self.session.commits += 1


def fake_session_factory(session: FakeSession):
    return lambda: session


class FreshSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeSession:
        session = FakeSession()
        self.sessions.append(session)
        return session


def test_provider_messages_keeps_text_user_and_assistant_messages() -> None:
    messages = [
        AgentChatMessage(role="system", parts=[{"type": "text", "text": "ignored"}]),
        AgentChatMessage(
            role="user",
            parts=[
                {"type": "text", "text": "hello"},
                {"type": "file", "text": "ignored"},
                {"type": "text", "text": "world"},
            ],
        ),
        AgentChatMessage(role="assistant", parts=[{"type": "text", "text": "answer"}]),
        AgentChatMessage(role="user", parts=[{"type": "text", "text": ""}]),
    ]

    assert service.provider_messages(messages) == [
        {"role": "user", "content": "hello\nworld"},
        {"role": "assistant", "content": "answer"},
    ]


def test_sse_payloads_parses_complete_json_blocks_and_preserves_tail() -> None:
    payloads, tail = service.sse_payloads(
        'event: message\ndata: {"type":"response.output_text.delta","delta":"hi"}\n\n'
        "data: [DONE]\n\n"
        'data: {"partial":'
    )

    assert payloads == [{"type": "response.output_text.delta", "delta": "hi"}]
    assert tail == 'data: {"partial":'


def ui_stream_chunks(raw_chunks: list[str]) -> list[dict]:
    chunks = []
    for raw_chunk in raw_chunks:
        for line in raw_chunk.splitlines():
            if line.startswith("data: "):
                chunks.append(json.loads(line.removeprefix("data: ")))
    return chunks


@pytest.mark.asyncio
async def test_persisted_agent_chat_stream_emits_ui_message_chunks_and_persists_parts(
    monkeypatch,
) -> None:
    conversation = WorkspaceConversation(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        created_by_id=uuid4(),
        title="Chat",
        is_active=True,
    )
    persisted: list[dict] = []

    async def append_conversation_message(*args, **kwargs):
        persisted.append(kwargs)

    async def provider_stream():
        yield service.AgentChatToolActivityEvent(
            id="tool-call-1",
            tool_name="resolve-library-id",
            status="running",
            arguments={"query": "Next.js"},
        )
        yield service.AgentChatToolActivityEvent(
            id="tool-call-1",
            tool_name="resolve-library-id",
            status="running",
            message="Resolving library",
            progress=1,
            progress_token="agent-tool:call-1",
            total=2,
        )
        yield service.AgentChatToolActivityEvent(
            id="tool-call-1",
            tool_name="resolve-library-id",
            status="completed",
            result="Resolved /vercel/next.js",
        )
        yield service.AgentChatTextEvent(text="Final answer")

    monkeypatch.setattr(
        service.repository,
        "append_conversation_message",
        append_conversation_message,
    )

    session = FakeSession()
    raw_chunks = [
        chunk
        async for chunk in service.persisted_agent_chat_stream(
            conversation,
            provider_stream(),
            session_factory=fake_session_factory(session),
        )
    ]
    chunks = ui_stream_chunks(raw_chunks)

    assert [chunk["type"] for chunk in chunks] == [
        "start",
        "data-tool-activity",
        "data-tool-activity",
        "data-tool-activity",
        "text-start",
        "text-delta",
        "text-end",
        "finish",
    ]
    assert chunks[1]["data"] == {
        "toolName": "resolve-library-id",
        "status": "running",
        "arguments": {"query": "Next.js"},
    }
    assert chunks[2]["data"] == {
        "toolName": "resolve-library-id",
        "status": "running",
        "message": "Resolving library",
        "progress": 1,
        "progressToken": "agent-tool:call-1",
        "total": 2,
    }
    assert chunks[3]["data"] == {
        "toolName": "resolve-library-id",
        "status": "completed",
        "result": "Resolved /vercel/next.js",
    }
    assert chunks[5]["delta"] == "Final answer"
    assert persisted == [
        {
            "conversation_id": conversation.id,
            "role": "assistant",
            "content": "Final answer",
            "agent_run_id": None,
            "parts": [
                {
                    "type": "data-tool-activity",
                    "id": "tool-call-1",
                    "data": {
                        "toolName": "resolve-library-id",
                        "status": "completed",
                        "result": "Resolved /vercel/next.js",
                    },
                },
                {"type": "text", "text": "Final answer"},
            ],
        }
    ]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_persisted_agent_chat_stream_turns_provider_error_into_message(
    monkeypatch,
) -> None:
    conversation = WorkspaceConversation(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=uuid4(),
        created_by_id=uuid4(),
        title="Chat",
        is_active=True,
    )
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=conversation.organization_id,
        workspace_id=conversation.workspace_id,
        agent_id=conversation.agent_id,
        conversation_id=conversation.id,
        trigger_type="chat",
        status="running",
    )
    persisted: list[dict] = []
    steps: list[dict] = []
    finished: list[dict] = []

    async def append_conversation_message(*args, **kwargs):
        persisted.append(kwargs)

    async def append_agent_run_step(*args, **kwargs):
        steps.append(kwargs)

    async def finish_agent_run(*args, **kwargs):
        finished.append(kwargs)

    async def get_agent_run(*args, **kwargs):
        return agent_run

    async def provider_stream():
        raise service.AgentChatProviderError(
            "LLM provider websocket failed with HTTP 401",
            status_code=401,
        )
        yield service.AgentChatTextEvent(text="unreachable")

    monkeypatch.setattr(
        service.repository,
        "append_conversation_message",
        append_conversation_message,
    )
    monkeypatch.setattr(service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(service.repository, "finish_agent_run", finish_agent_run)
    monkeypatch.setattr(service.repository, "get_agent_run", get_agent_run)

    session = FakeSession()
    chunks = ui_stream_chunks(
        [
            chunk
            async for chunk in service.persisted_agent_chat_stream(
                conversation,
                provider_stream(),
                agent_run,
                session_factory=fake_session_factory(session),
            )
        ]
    )

    text_delta = next(chunk for chunk in chunks if chunk["type"] == "text-delta")
    assert "ChatGPT rejected the stored OAuth token" in text_delta["delta"]
    assert chunks[-1] == {"type": "finish", "finishReason": "error"}
    assert steps[0]["step_type"] == "error"
    assert steps[-1]["status"] == "failed"
    assert finished == [
        {"status": "failed", "error": "LLM provider websocket failed with HTTP 401"}
    ]
    assert persisted[0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_stream_agent_chat_creates_agent_run_without_conversation(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="user@example.com")
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="OpenAI",
        provider=service.OPENAI_API_KEY_PROVIDER,
        visibility="workspace",
        workspace_id=workspace_id,
        auth_method="api_key",
        is_active=True,
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Assistant",
        instructions="Help.",
        scope="workspace",
        provider_credential_id=credential.id,
        model_name="gpt-4o-mini",
        is_active=True,
    )
    agent_run = AgentRun(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        conversation_id=None,
        trigger_type="chat",
        status="running",
    )
    created_runs: list[dict] = []
    steps: list[dict] = []
    finished: list[dict] = []
    seen_provider_run: list[AgentRun | None] = []

    async def get_agent_model_for_run(*args, **kwargs):
        return agent, credential

    async def create_agent_run(*args, **kwargs):
        created_runs.append(kwargs)
        return agent_run

    async def append_agent_run_step(*args, **kwargs):
        steps.append(kwargs)

    async def finish_agent_run(*args, **kwargs):
        finished.append(kwargs)

    async def get_agent_run(*args, **kwargs):
        return agent_run

    async def refresh_wildcard_agent_server_tools(*args, **kwargs):
        return None

    async def list_agent_tool_runtime_rows(*args, **kwargs):
        return []

    async def filter_agent_runtime_tools_for_guardrails(*args, **kwargs):
        return service.AgentRuntimeToolGuardrailFilter(allowed_tools={}, denied_tools={})

    async def run_agent_chat(*args, **kwargs):
        seen_provider_run.append(kwargs["agent_run"])
        yield service.AgentChatTextEvent(text="ok")

    monkeypatch.setattr(service, "get_agent_model_for_run", get_agent_model_for_run)
    monkeypatch.setattr(service.repository, "create_agent_run", create_agent_run)
    monkeypatch.setattr(service.repository, "append_agent_run_step", append_agent_run_step)
    monkeypatch.setattr(service.repository, "finish_agent_run", finish_agent_run)
    monkeypatch.setattr(service.repository, "get_agent_run", get_agent_run)
    monkeypatch.setattr(
        service,
        "refresh_wildcard_agent_server_tools",
        refresh_wildcard_agent_server_tools,
    )
    monkeypatch.setattr(
        service.repository,
        "list_agent_tool_runtime_rows",
        list_agent_tool_runtime_rows,
    )
    monkeypatch.setattr(
        service,
        "filter_agent_runtime_tools_for_guardrails",
        filter_agent_runtime_tools_for_guardrails,
    )
    monkeypatch.setattr(service, "run_agent_chat", run_agent_chat)

    stream = await service.stream_agent_chat(
        FakeSession(),
        user,
        organization_id,
        agent.id,
        AgentChatRequest(
            messages=[
                AgentChatMessage(role="user", parts=[{"type": "text", "text": "hi"}])
            ]
        ),
        workspace_id=workspace_id,
        session_factory=fake_session_factory(FakeSession()),
    )
    chunks = ui_stream_chunks([chunk async for chunk in stream])

    assert created_runs == [
        {
            "organization_id": organization_id,
            "workspace_id": workspace_id,
            "agent_id": agent.id,
            "conversation_id": None,
            "triggered_by_id": user.id,
            "trigger_type": "chat",
        }
    ]
    assert seen_provider_run == [agent_run]
    assert steps[0]["step_type"] == "model_input"
    assert steps[0]["payload"] == {"message": "hi", "messageCount": 1}
    assert steps[-1]["step_type"] == "model_output"
    assert finished == [{"status": "succeeded", "error": ""}]
    assert chunks[-1] == {"type": "finish", "finishReason": "stop"}


@pytest.mark.asyncio
async def test_run_agent_chat_refreshes_chatgpt_oauth_after_websocket_401(monkeypatch) -> None:
    organization_id = uuid4()
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="ChatGPT",
        provider=service.OPENAI_CHATGPT_PROVIDER,
        visibility="organization",
        auth_method="oauth",
        oauth_provider="chatgpt",
        oauth_metadata={"accountId": "account-1"},
        is_active=True,
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        name="Assistant",
        instructions="Help.",
        scope="workspace",
        workspace_id=uuid4(),
        provider_credential_id=credential.id,
        model_name="gpt-5.5",
        is_active=True,
    )
    calls: list[str] = []

    async def resolve_credential_secrets(*args, **kwargs):
        return ResolvedLLMCredentialSecrets(
            oauth_access_token="old-access",
            oauth_refresh_token="refresh-token",
        )

    async def refresh_chatgpt_oauth_credential(*args, **kwargs):
        credential.oauth_metadata = {"accountId": "account-2"}
        return ResolvedLLMCredentialSecrets(
            oauth_access_token="new-access",
            oauth_refresh_token="new-refresh",
        )

    async def get_credential(*args, **kwargs):
        return credential

    async def stream_chatgpt_codex_response_text(*args, **kwargs):
        authorization = kwargs["headers"]["Authorization"]
        calls.append(authorization)
        if authorization == "Bearer old-access":
            raise service.AgentChatProviderError("expired", status_code=401)
        yield service.AgentChatTextEvent(text="ok")

    monkeypatch.setattr(service, "resolve_credential_secrets", resolve_credential_secrets)
    monkeypatch.setattr(service.llm_provider_repository, "get_credential", get_credential)
    monkeypatch.setattr(
        service,
        "refresh_chatgpt_oauth_credential",
        refresh_chatgpt_oauth_credential,
    )
    monkeypatch.setattr(
        service,
        "stream_chatgpt_codex_response_text",
        stream_chatgpt_codex_response_text,
    )

    events = [
        event
        async for event in service.run_agent_chat(
            agent,
            credential,
            AgentChatRequest(
                messages=[
                    AgentChatMessage(
                        role="user",
                        parts=[{"type": "text", "text": "hi"}],
                    )
                ]
            ),
            {},
            session_factory=fake_session_factory(FakeSession()),
        )
    ]

    assert calls == ["Bearer old-access", "Bearer new-access"]
    assert events == [service.AgentChatTextEvent(text="ok")]


@pytest.mark.asyncio
async def test_filter_agent_runtime_tools_omits_denied_tools(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/server",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    server = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=installation.server_name,
        version="1.0.0",
        description="Server",
        server_json={},
        packages=[],
        remotes=[],
        icons=[],
        is_latest=True,
        status="active",
    )
    allowed_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version="1.0.0",
        tool_name="read_docs",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    denied_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=installation.id,
        server_name=installation.server_name,
        server_version="1.0.0",
        tool_name="search_repositories",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Assistant",
        instructions="Help.",
        scope="workspace",
        model_name="gpt-5.5",
        is_active=True,
    )
    user = User(id=uuid4(), email="user@example.com", is_superuser=False)
    tools = {
        "allowed": service.AgentRuntimeTool(
            wire_name="allowed",
            assignment_id=uuid4(),
            tool_schema=allowed_schema,
            installation=installation,
            server=server,
        ),
        "denied": service.AgentRuntimeTool(
            wire_name="denied",
            assignment_id=uuid4(),
            tool_schema=denied_schema,
            installation=installation,
            server=server,
        ),
    }
    contexts = []

    async def evaluate_tool_call_guardrails(*args, **kwargs):
        context = args[1]
        contexts.append(context)
        if context.tool_name == "search_repositories":
            return GuardrailDecision(mode="deny", policy_name="Block search")
        return GuardrailDecision(mode="allow", policy_name="Allow reads")

    monkeypatch.setattr(
        service,
        "evaluate_tool_call_guardrails",
        evaluate_tool_call_guardrails,
    )

    result = await service.filter_agent_runtime_tools_for_guardrails(
        FakeSession(),
        tools,
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent=agent,
    )

    assert list(result.allowed_tools) == ["allowed"]
    assert list(result.denied_tools) == ["denied"]
    assert {context.tool_name for context in contexts} == {"read_docs", "search_repositories"}
    assert all(context.arguments == {} for context in contexts)


@pytest.mark.asyncio
async def test_denied_mcp_request_preflight_blocks_before_model() -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    installation_id = uuid4()
    tool_schema_id = uuid4()
    installation = MCPServerInstallation(
        id=installation_id,
        workspace_id=workspace_id,
        server_name="io.github.github/github-mcp-server",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
        runtime_config={},
        secret_references={},
    )
    server = MCPServerVersion(
        id=uuid4(),
        organization_id=organization_id,
        name=installation.server_name,
        version="1.0.0",
        description="GitHub MCP Server",
        server_json={},
        packages=[],
        remotes=[],
        icons=[],
        is_latest=True,
        status="active",
    )
    tool_schema = MCPServerToolSchema(
        id=tool_schema_id,
        workspace_id=workspace_id,
        installation_id=installation_id,
        server_name=installation.server_name,
        server_version="1.0.0",
        tool_name="search_repositories",
        title="Search repositories",
        description="Search GitHub repositories",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    guardrail_filter = service.AgentRuntimeToolGuardrailFilter(
        allowed_tools={},
        denied_tools={
            "search": (
                service.AgentRuntimeTool(
                    wire_name="search",
                    assignment_id=uuid4(),
                    tool_schema=tool_schema,
                    installation=installation,
                    server=server,
                ),
                GuardrailDecision(
                    mode="deny",
                    policy_name="deny all",
                    message="Tool call blocked by guardrail policy: deny all",
                ),
            )
        },
    )

    assert service.message_requests_denied_mcp_tool(
        AgentChatMessage(
            role="user",
            parts=[{"type": "text", "text": "search git-rank repo in github"}],
        ),
        guardrail_filter,
    )

    events = [event async for event in service.preflight_blocked_tool_stream(guardrail_filter)]

    assert isinstance(events[0], service.AgentChatToolActivityEvent)
    assert events[0].status == "blocked"
    assert events[0].tool_name == "search_repositories"
    assert isinstance(events[1], service.AgentChatTextEvent)
    assert "deny all" in events[1].text


def test_sanitize_run_payload_redacts_sensitive_keys_and_truncates_long_text() -> None:
    payload = {
        "apiKey": "secret-value",
        "nested": {"authorization": "Bearer token", "safe": "visible"},
        "long": "x" * (service.AGENT_RUN_PAYLOAD_STRING_MAX_CHARS + 1),
        "text": "please use token=abc123 and sk-abc123456789xyz",
    }

    sanitized = service.sanitize_run_payload(payload)

    assert sanitized["apiKey"] == "[redacted]"
    assert sanitized["nested"]["authorization"] == "[redacted]"
    assert sanitized["nested"]["safe"] == "visible"
    assert sanitized["long"].endswith("\n[truncated]")
    assert sanitized["text"] == "please use [redacted] and [redacted]"


def test_text_delta_from_openai_event_supports_responses_and_chat_chunks() -> None:
    assert (
        service.text_delta_from_openai_event(
            {"type": "response.output_text.delta", "delta": "hello"}
        )
        == "hello"
    )
    assert (
        service.text_delta_from_openai_event({"choices": [{"delta": {"content": "world"}}]})
        == "world"
    )


def test_text_delta_from_openai_event_ignores_function_call_argument_deltas() -> None:
    assert (
        service.text_delta_from_openai_event(
            {
                "type": "response.function_call_arguments.delta",
                "delta": '{"query":"latest Next.js docs"}',
            }
        )
        == ""
    )
    assert (
        service.text_delta_from_openai_event(
            {
                "type": "response.output_item.delta",
                "item": {"type": "function_call"},
                "delta": '{"query":"latest Next.js docs"}',
            }
        )
        == ""
    )


def test_llm_usage_from_completed_event_parses_response_usage() -> None:
    usage = service.llm_usage_from_completed_event(
        {
            "type": "response.completed",
            "response": {
                "model": "gpt-4o-mini-2024-07-18",
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 300,
                    "total_tokens": 1500,
                    "input_tokens_details": {"cached_tokens": 200},
                },
            },
        }
    )

    assert usage == service.observability_service.LLMTokenUsage(
        input_tokens=1200,
        output_tokens=300,
        total_tokens=1500,
        cache_read_input_tokens=200,
        response_model="gpt-4o-mini-2024-07-18",
    )


@pytest.mark.asyncio
async def test_run_agent_chat_closes_database_transactions_before_external_stream(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="OpenAI",
        provider=service.OPENAI_API_KEY_PROVIDER,
        visibility="organization",
        auth_method="api_key",
        is_active=True,
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Assistant",
        instructions="Help.",
        scope="workspace",
        provider_credential_id=credential.id,
        model_name="gpt-4o-mini",
        is_active=True,
    )
    session_factory = FreshSessionFactory()
    external_transaction_states: list[list[bool]] = []

    async def resolve_credential_secrets(*args, **kwargs):
        return ResolvedLLMCredentialSecrets(api_key="sk-test")

    async def require_agent_llm_budget_available(*args, **kwargs):
        return None

    async def record_agent_llm_usage(*args, **kwargs):
        return None

    async def stream_response_text(*args, **kwargs):
        external_transaction_states.append(
            [session.in_transaction for session in session_factory.sessions]
        )
        yield "ok"

    monkeypatch.setattr(service, "resolve_credential_secrets", resolve_credential_secrets)
    monkeypatch.setattr(
        service,
        "require_agent_llm_budget_available",
        require_agent_llm_budget_available,
    )
    monkeypatch.setattr(service, "record_agent_llm_usage", record_agent_llm_usage)
    monkeypatch.setattr(service, "stream_response_text", stream_response_text)

    events = [
        event
        async for event in service.run_agent_chat(
            agent,
            credential,
            AgentChatRequest(
                messages=[
                    AgentChatMessage(
                        role="user",
                        parts=[{"type": "text", "text": "hi"}],
                    )
                ]
            ),
            {},
            session_factory=session_factory,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
    ]

    assert events == [service.AgentChatTextEvent(text="ok")]
    assert external_transaction_states == [[False, False]]
    assert len(session_factory.sessions) == 3
    assert all(session.commits == 1 for session in session_factory.sessions)


@pytest.mark.asyncio
async def test_run_agent_chat_records_openai_usage(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="user@example.com")
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="OpenAI",
        provider=service.OPENAI_API_KEY_PROVIDER,
        visibility="organization",
        auth_method="api_key",
        is_active=True,
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Assistant",
        instructions="Help.",
        scope="workspace",
        provider_credential_id=credential.id,
        model_name="gpt-4o-mini",
        is_active=True,
    )
    recorded: list[dict] = []

    async def resolve_credential_secrets(*args, **kwargs):
        return ResolvedLLMCredentialSecrets(api_key="sk-test")

    async def stream_response_text(*args, **kwargs):
        kwargs["usage_callback"](
            service.observability_service.LLMTokenUsage(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                response_model="gpt-4o-mini-2024-07-18",
            )
        )
        yield "ok"

    async def record_agent_llm_usage(*args, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(service, "resolve_credential_secrets", resolve_credential_secrets)
    monkeypatch.setattr(service, "stream_response_text", stream_response_text)
    monkeypatch.setattr(service, "record_agent_llm_usage", record_agent_llm_usage)

    events = [
        event
        async for event in service.run_agent_chat(
            agent,
            credential,
            AgentChatRequest(
                messages=[
                    AgentChatMessage(
                        role="user",
                        parts=[{"type": "text", "text": "hi"}],
                    )
                ]
            ),
            {},
            session_factory=fake_session_factory(FakeSession()),
            user=user,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
    ]

    assert events == [service.AgentChatTextEvent(text="ok")]
    assert len(recorded) == 1
    assert recorded[0]["status"] == "succeeded"
    assert recorded[0]["usage"].input_tokens == 10
    assert recorded[0]["usage"].output_tokens == 5
    assert recorded[0]["organization_id"] == organization_id
    assert recorded[0]["workspace_id"] == workspace_id


def test_chatgpt_codex_request_body_uses_websocket_response_create_shape() -> None:
    agent = Agent(
        id=uuid4(),
        organization_id=uuid4(),
        name="SRE Agent",
        instructions="Use tools carefully.",
        scope="organization",
        model_name="gpt-5.3-codex-spark",
    )

    body = service.chatgpt_codex_request_body(
        agent,
        input_items=service.chatgpt_codex_messages(
            [AgentChatMessage(role="user", parts=[{"type": "text", "text": "hello"}])]
        ),
        tools=[],
    )

    assert body == {
        "type": "response.create",
        "model": "gpt-5.3-codex-spark",
        "instructions": "Use tools carefully.",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            }
        ],
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "reasoning": None,
        "store": False,
        "stream": True,
        "include": [],
    }


def test_tool_calls_from_response_output_item_done() -> None:
    calls = service.tool_calls_from_event(
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "name": "wardn_abc",
                "call_id": "call_123",
                "arguments": '{"namespace":"media"}',
            },
        }
    )

    assert calls == [
        service.AgentToolCall(
            name="wardn_abc",
            call_id="call_123",
            arguments={"namespace": "media"},
        )
    ]


def test_websocket_error_message_reads_codex_error_events() -> None:
    assert (
        service.websocket_error_message(
            {
                "type": "error",
                "status": 400,
                "error": {"message": "Model does not support this request"},
            }
        )
        == "Model does not support this request"
    )


def test_codex_compat_headers_use_current_default_version() -> None:
    assert service.CODEX_COMPAT_VERSION == service.DEFAULT_CODEX_COMPAT_VERSION
    assert service.CODEX_COMPAT_VERSION == "0.144.0"
    assert service.CODEX_COMPAT_USER_AGENT.startswith("codex_cli_rs/0.144.0 ")


@pytest.mark.asyncio
async def test_refresh_wildcard_agent_server_tools_loads_bound_server_tools(monkeypatch) -> None:
    agent_id = uuid4()
    assignment = AgentMCPServerAssignment(
        id=uuid4(),
        agent_id=agent_id,
        installation_id=uuid4(),
    )
    installation = MCPServerInstallation(
        id=assignment.installation_id,
        workspace_id=uuid4(),
        server_name="io.github.example/server",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    server = MCPServerVersion(
        id=uuid4(),
        name=installation.server_name,
        version=installation.installed_version,
        description="Server",
        server_json={
            "$schema": "https://example.com/schema.json",
            "name": installation.server_name,
            "description": "Server",
            "version": installation.installed_version,
        },
        is_latest=True,
    )
    refreshed = []

    async def list_agent_wildcard_server_version_rows(*args, **kwargs):
        assert kwargs["agent_id"] == agent_id
        return [(assignment, installation, server)]

    async def refresh_tool_schemas_for_installation(*args, **kwargs):
        refreshed.append((kwargs["installation"], kwargs["server"]))

    monkeypatch.setattr(
        service.repository,
        "list_agent_wildcard_server_version_rows",
        list_agent_wildcard_server_version_rows,
    )
    monkeypatch.setattr(
        service,
        "refresh_tool_schemas_for_installation",
        refresh_tool_schemas_for_installation,
    )

    session = FakeSession()
    await service.refresh_wildcard_agent_server_tools(session, agent_id)

    assert refreshed == [(installation, server)]
    assert session.commits == 0


def patch_org_owner(monkeypatch, organization_id, user):
    organization = Organization(
        id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role="owner",
        is_active=True,
    )

    async def get_organization_by_id(*args, **kwargs):
        return organization

    async def get_organization_membership(*args, **kwargs):
        return membership

    org_repository = service.require_organization_admin.__globals__["repository"]
    monkeypatch.setattr(org_repository, "get_organization_by_id", get_organization_by_id)
    monkeypatch.setattr(org_repository, "get_organization_membership", get_organization_membership)


@pytest.mark.asyncio
async def test_get_agent_model_for_run_allows_workspace_member(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="member@example.com", is_superuser=False)
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="OpenAI",
        provider="openai",
        visibility="workspace",
        api_key_secret_handle_id=uuid4(),
        base_url="",
        extra_headers={},
        is_active=True,
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        provider_credential_id=credential.id,
        name="Workspace Agent",
        instructions="Use tools carefully.",
        scope="workspace",
        model_name="gpt-4o-mini",
        is_active=True,
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )
    calls: list[str] = []

    async def require_organization_member(*args, **kwargs):
        calls.append("organization_member")
        return None, None

    async def require_workspace_member(*args, **kwargs):
        calls.append("workspace_member")
        return None, None, None

    async def require_workspace_admin(*args, **kwargs):
        raise AssertionError("running an agent should not require workspace admin access")

    async def get_agent(*args, **kwargs):
        return agent

    async def get_credential(*args, **kwargs):
        return credential

    monkeypatch.setattr(service, "require_organization_member", require_organization_member)
    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_agent", get_agent)
    monkeypatch.setattr(service.llm_provider_repository, "get_credential", get_credential)

    result_agent, result_credential = await service.get_agent_model_for_run(
        FakeSession(),
        user,
        organization_id,
        agent.id,
    )

    assert result_agent is agent
    assert result_credential is credential
    assert calls == ["organization_member", "workspace_member"]


@pytest.mark.asyncio
async def test_create_agent_with_provider_credential(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="OpenAI",
        provider="openai",
        visibility="organization",
        api_key_secret_handle_id=uuid4(),
        base_url="",
        extra_headers={},
        is_active=True,
    )

    patch_org_owner(monkeypatch, organization_id, user)

    async def no_duplicate(*args, **kwargs):
        return None

    async def get_credential(*args, **kwargs):
        return credential

    async def credential_supports_model(*args, **kwargs):
        return True

    monkeypatch.setattr(service.repository, "get_agent_by_name", no_duplicate)
    monkeypatch.setattr(service.llm_provider_repository, "get_credential", get_credential)
    monkeypatch.setattr(service, "credential_supports_model", credential_supports_model)

    session = FakeSession()
    response = await service.create_agent(
        session,
        user,
        organization_id,
        AgentCreate(
            name=" SRE Agent ",
            description=" Runtime helper ",
            instructions="Use tools carefully.",
            providerCredentialId=credential.id,
            modelName="gpt-4o-mini",
        ),
    )

    agent = session.added[0]
    assert isinstance(agent, Agent)
    assert agent.name == "SRE Agent"
    assert agent.provider_credential_id == credential.id
    assert agent.scope == "organization"
    assert response.tool_count == 0


@pytest.mark.asyncio
async def test_create_agent_rejects_model_unavailable_for_credential(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="OpenAI",
        provider="openai",
        visibility="organization",
        api_key_secret_handle_id=uuid4(),
        base_url="",
        extra_headers={},
        is_active=True,
    )

    patch_org_owner(monkeypatch, organization_id, user)

    async def no_duplicate(*args, **kwargs):
        return None

    async def get_credential(*args, **kwargs):
        return credential

    async def credential_supports_model(*args, **kwargs):
        return False

    monkeypatch.setattr(service.repository, "get_agent_by_name", no_duplicate)
    monkeypatch.setattr(service.llm_provider_repository, "get_credential", get_credential)
    monkeypatch.setattr(service, "credential_supports_model", credential_supports_model)

    session = FakeSession()
    with pytest.raises(InvalidAgentScopeError):
        await service.create_agent(
            session,
            user,
            organization_id,
            AgentCreate(
                name="SRE Agent",
                instructions="Use tools carefully.",
                providerCredentialId=credential.id,
                modelName="not-a-real-model",
            ),
        )

    assert session.added == []


@pytest.mark.asyncio
async def test_create_agent_rejects_duplicate_name(monkeypatch) -> None:
    organization_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    patch_org_owner(monkeypatch, organization_id, user)

    async def duplicate(*args, **kwargs):
        return Agent(
            id=uuid4(),
            organization_id=organization_id,
            name="SRE Agent",
            instructions="Existing",
            scope="organization",
        )

    monkeypatch.setattr(service.repository, "get_agent_by_name", duplicate)

    with pytest.raises(DuplicateAgentError):
        await service.create_agent(
            FakeSession(),
            user,
            organization_id,
            AgentCreate(name="SRE Agent", instructions="Use tools carefully."),
        )


@pytest.mark.asyncio
async def test_create_workspace_agent_allows_same_name_in_different_workspace(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)

    async def require_workspace_admin(*args, **kwargs):
        return None, None, None

    async def existing_by_name(*args, **kwargs):
        assert kwargs["workspace_id"] == workspace_id
        return None

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_agent_by_name", existing_by_name)

    session = FakeSession()
    response = await service.create_workspace_agent(
        session,
        user,
        organization_id,
        workspace_id,
        AgentCreate(name="SRE Agent", instructions="Use tools carefully."),
    )

    agent = session.added[0]
    assert isinstance(agent, Agent)
    assert agent.name == "SRE Agent"
    assert agent.workspace_id == workspace_id
    assert response.workspace_id == workspace_id


@pytest.mark.asyncio
async def test_create_workspace_agent_rejects_duplicate_name_in_same_workspace(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)

    async def require_workspace_admin(*args, **kwargs):
        return None, None, None

    async def duplicate(*args, **kwargs):
        assert kwargs["workspace_id"] == workspace_id
        return Agent(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            name="SRE Agent",
            instructions="Existing",
            scope="workspace",
        )

    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)
    monkeypatch.setattr(service.repository, "get_agent_by_name", duplicate)

    with pytest.raises(DuplicateAgentError):
        await service.create_workspace_agent(
            FakeSession(),
            user,
            organization_id,
            workspace_id,
            AgentCreate(name="SRE Agent", instructions="Use tools carefully."),
        )


@pytest.mark.asyncio
async def test_quick_start_workspace_agent_creates_default_agent(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="member@example.com", is_superuser=False)
    organization_credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="Org OpenAI",
        provider="openai",
        visibility="organization",
        api_key_secret_handle_id=uuid4(),
        base_url="",
        extra_headers={},
        is_active=True,
    )
    workspace_credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name="Workspace OpenAI",
        provider="openai",
        visibility="workspace",
        api_key_secret_handle_id=uuid4(),
        base_url="",
        extra_headers={},
        is_active=True,
    )
    enabled_installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/enabled",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    disabled_installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/disabled",
        config_name="default",
        installed_version="1.0.0",
        status="disabled",
    )
    assigned_servers = []

    async def require_workspace_member(*args, **kwargs):
        return None, None, None

    async def get_agent_by_name(*args, **kwargs):
        assert kwargs["workspace_id"] == workspace_id
        assert kwargs["name"] == service.QUICK_START_AGENT_NAME
        return None

    async def list_credentials(*args, **kwargs):
        return [organization_credential, workspace_credential]

    async def list_models_for_credential(*args, **kwargs):
        credential = args[1]
        assert credential is workspace_credential
        return LLMProviderModelListResponse(
            models=[LLMProviderModelRead(id="gpt-4o-mini", name="GPT-4o mini")]
        )

    async def list_installations(*args, **kwargs):
        assert kwargs["workspace_id"] == workspace_id
        return [disabled_installation, enabled_installation]

    async def replace_agent_tools(*args, **kwargs):
        assigned_servers.extend(kwargs["server_assignments"])

    async def count_agent_tools(*args, **kwargs):
        return 4

    async def count_agent_servers(*args, **kwargs):
        return 1

    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service.repository, "get_agent_by_name", get_agent_by_name)
    monkeypatch.setattr(service.llm_provider_repository, "list_credentials", list_credentials)
    monkeypatch.setattr(service, "list_models_for_credential", list_models_for_credential)
    monkeypatch.setattr(service.mcp_registry_repository, "list_installations", list_installations)
    monkeypatch.setattr(service.repository, "replace_agent_tools", replace_agent_tools)
    monkeypatch.setattr(service.repository, "count_agent_servers", count_agent_servers)
    monkeypatch.setattr(service.repository, "count_agent_tools", count_agent_tools)

    session = FakeSession()
    response = await service.quick_start_workspace_agent(
        session,
        user,
        organization_id,
        workspace_id,
    )

    agent = session.added[0]
    assert isinstance(agent, Agent)
    assert agent.name == service.QUICK_START_AGENT_NAME
    assert agent.workspace_id == workspace_id
    assert agent.provider_credential_id == workspace_credential.id
    assert agent.model_name == "gpt-4o-mini"
    assert response.agent.tool_count == 4
    assert response.agent.server_count == 1
    assert response.agent.id == agent.id
    assert response.conversation.agent_id == agent.id
    assert response.conversation.workspace_id == workspace_id
    assert response.messages == []
    assert assigned_servers == [(enabled_installation, True, [])]


@pytest.mark.asyncio
async def test_quick_start_workspace_agent_reuses_existing_agent(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="member@example.com", is_superuser=False)
    credential = LLMProviderCredential(
        id=uuid4(),
        organization_id=organization_id,
        name="OpenAI",
        provider="openai",
        visibility="organization",
        api_key_secret_handle_id=uuid4(),
        base_url="",
        extra_headers={},
        is_active=True,
    )
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        provider_credential_id=credential.id,
        name=service.QUICK_START_AGENT_NAME,
        description="Existing assistant",
        instructions="Existing instructions.",
        scope="workspace",
        model_name="gpt-4o-mini",
        is_active=True,
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )
    sync_calls = []

    async def require_workspace_member(*args, **kwargs):
        return None, None, None

    async def get_agent_by_name(*args, **kwargs):
        return agent

    async def get_credential(*args, **kwargs):
        return credential

    async def credential_supports_model(*args, **kwargs):
        return True

    async def list_installations(*args, **kwargs):
        return []

    async def replace_agent_tools(*args, **kwargs):
        sync_calls.append(kwargs["agent_id"])

    async def count_agent_tools(*args, **kwargs):
        return 0

    async def count_agent_servers(*args, **kwargs):
        return 0

    async def list_credentials(*args, **kwargs):
        raise AssertionError("valid existing quick-start agent should keep its credential")

    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service.repository, "get_agent_by_name", get_agent_by_name)
    monkeypatch.setattr(service.llm_provider_repository, "get_credential", get_credential)
    monkeypatch.setattr(service, "credential_supports_model", credential_supports_model)
    monkeypatch.setattr(service.llm_provider_repository, "list_credentials", list_credentials)
    monkeypatch.setattr(service.mcp_registry_repository, "list_installations", list_installations)
    monkeypatch.setattr(service.repository, "replace_agent_tools", replace_agent_tools)
    monkeypatch.setattr(service.repository, "count_agent_servers", count_agent_servers)
    monkeypatch.setattr(service.repository, "count_agent_tools", count_agent_tools)

    session = FakeSession()
    response = await service.quick_start_workspace_agent(
        session,
        user,
        organization_id,
        workspace_id,
    )

    assert response.agent.id == agent.id
    assert response.agent.provider_credential_id == credential.id
    assert response.agent.model_name == "gpt-4o-mini"
    assert isinstance(session.added[0], WorkspaceConversation)
    assert response.conversation.agent_id == agent.id
    assert response.messages == []
    assert sync_calls == [agent.id]


@pytest.mark.asyncio
async def test_list_available_agent_tools_includes_enabled_servers_without_tools(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="member@example.com", is_superuser=False)
    enabled_installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/enabled",
        config_name="personal",
        installed_version="1.0.0",
        status="enabled",
    )
    disabled_installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/disabled",
        config_name="default",
        installed_version="1.0.0",
        status="disabled",
    )

    async def require_workspace_member(*args, **kwargs):
        return None, None, None

    async def list_installations(*args, **kwargs):
        assert kwargs["workspace_id"] == workspace_id
        return [disabled_installation, enabled_installation]

    async def list_workspace_available_tools(*args, **kwargs):
        assert kwargs["workspace_id"] == workspace_id
        return []

    monkeypatch.setattr(service, "require_workspace_member", require_workspace_member)
    monkeypatch.setattr(service.mcp_registry_repository, "list_installations", list_installations)
    monkeypatch.setattr(
        service.repository,
        "list_workspace_available_tools",
        list_workspace_available_tools,
    )

    response = await service.list_available_agent_tools(
        FakeSession(),
        user,
        organization_id,
        workspace_id,
    )

    assert response.tools == []
    assert len(response.servers) == 1
    assert response.servers[0].installation_id == enabled_installation.id
    assert response.servers[0].config_name == "personal"


@pytest.mark.asyncio
async def test_replace_agent_tools_rejects_tool_outside_workspace(monkeypatch) -> None:
    organization_id = uuid4()
    agent_workspace_id = uuid4()
    other_workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=False)
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=agent_workspace_id,
        created_by_id=user.id,
        name="Workspace Agent",
        instructions="Use tools carefully.",
        scope="workspace",
        is_active=True,
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=other_workspace_id,
        installation_id=uuid4(),
        server_name="io.github.example/server",
        server_version="1.0.0",
        tool_name="list_things",
        title="List things",
        description="",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    installation = MCPServerInstallation(
        id=tool_schema.installation_id,
        workspace_id=other_workspace_id,
        server_name=tool_schema.server_name,
        installed_version="1.0.0",
        status="enabled",
    )
    workspace = Workspace(
        id=other_workspace_id,
        organization_id=organization_id,
        name="Other",
        slug="other",
        status="active",
    )

    async def get_agent(*args, **kwargs):
        return agent

    async def get_tool_schemas_by_ids(*args, **kwargs):
        return [(tool_schema, installation, workspace)]

    async def get_installations_by_ids(*args, **kwargs):
        return [(installation, workspace)]

    async def require_workspace_admin(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_agent", get_agent)
    monkeypatch.setattr(service.repository, "get_installations_by_ids", get_installations_by_ids)
    monkeypatch.setattr(service.repository, "get_tool_schemas_by_ids", get_tool_schemas_by_ids)
    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)

    with pytest.raises(InvalidAgentToolAssignmentError):
        await service.replace_agent_tools(
            FakeSession(),
            user,
            organization_id,
            agent.id,
            AgentToolAssignmentUpdate(
                servers=[
                    {
                        "installationId": installation.id,
                        "toolSchemaIds": [tool_schema.id],
                    }
                ]
            ),
        )


@pytest.mark.asyncio
async def test_replace_agent_tools_persists_unique_assignments(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        name="Workspace Agent",
        instructions="Use tools carefully.",
        scope="workspace",
        is_active=True,
    )
    tool_schema = MCPServerToolSchema(
        id=uuid4(),
        workspace_id=workspace_id,
        installation_id=uuid4(),
        server_name="io.github.example/server",
        server_version="1.0.0",
        tool_name="list_things",
        title="List things",
        description="",
        input_schema={"type": "object"},
        annotations={},
        is_active=True,
    )
    installation = MCPServerInstallation(
        id=tool_schema.installation_id,
        workspace_id=workspace_id,
        server_name=tool_schema.server_name,
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    workspace = Workspace(
        id=workspace_id,
        organization_id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )

    async def get_agent(*args, **kwargs):
        return agent

    async def get_tool_schemas_by_ids(*args, **kwargs):
        return [(tool_schema, installation, workspace)]

    async def get_installations_by_ids(*args, **kwargs):
        return [(installation, workspace)]

    async def replace_agent_tools(*args, **kwargs):
        return None

    async def list_agent_tools(*args, **kwargs):
        assignment = AgentMCPServerAssignment(
            id=uuid4(),
            agent_id=agent.id,
            installation_id=installation.id,
            created_at=datetime(2026, 6, 23, tzinfo=UTC),
        )
        return [(assignment, tool_schema, installation)]

    async def list_agent_server_assignments(*args, **kwargs):
        server_assignment = AgentMCPServerAssignment(
            id=uuid4(),
            agent_id=agent.id,
            installation_id=installation.id,
            created_at=datetime(2026, 6, 23, tzinfo=UTC),
        )
        tool_assignment = AgentMCPToolAssignment(
            id=uuid4(),
            server_assignment_id=server_assignment.id,
            tool_schema_id=tool_schema.id,
            wildcard=False,
            created_at=datetime(2026, 6, 23, tzinfo=UTC),
        )
        return [(server_assignment, tool_assignment)]

    async def require_workspace_admin(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_agent", get_agent)
    monkeypatch.setattr(service.repository, "get_installations_by_ids", get_installations_by_ids)
    monkeypatch.setattr(service.repository, "get_tool_schemas_by_ids", get_tool_schemas_by_ids)
    monkeypatch.setattr(service.repository, "replace_agent_tools", replace_agent_tools)
    monkeypatch.setattr(service.repository, "list_agent_tools", list_agent_tools)
    monkeypatch.setattr(
        service.repository,
        "list_agent_server_assignments",
        list_agent_server_assignments,
    )
    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)

    response = await service.replace_agent_tools(
        FakeSession(),
        user,
        organization_id,
        agent.id,
        AgentToolAssignmentUpdate(
            servers=[
                {
                    "installationId": installation.id,
                    "toolSchemaIds": [tool_schema.id, tool_schema.id],
                }
            ]
        ),
    )

    assert len(response.tools) == 1
    assert response.tools[0].tool_schema_id == tool_schema.id
    assert response.tools[0].installation_id == installation.id
    assert response.servers[0].installation_id == installation.id
    assert response.servers[0].tool_schema_ids == [tool_schema.id]


@pytest.mark.asyncio
async def test_replace_agent_tools_persists_wildcard_server_assignment(monkeypatch) -> None:
    organization_id = uuid4()
    workspace_id = uuid4()
    user = User(id=uuid4(), email="owner@example.com", is_superuser=True)
    agent = Agent(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        created_by_id=user.id,
        name="Workspace Agent",
        instructions="Use tools carefully.",
        scope="workspace",
        is_active=True,
    )
    installation = MCPServerInstallation(
        id=uuid4(),
        workspace_id=workspace_id,
        server_name="io.github.example/server",
        config_name="default",
        installed_version="1.0.0",
        status="enabled",
    )
    workspace = Workspace(
        id=workspace_id,
        organization_id=organization_id,
        name="Default",
        slug="default",
        status="active",
    )
    captured_assignments = []

    async def get_agent(*args, **kwargs):
        return agent

    async def get_installations_by_ids(*args, **kwargs):
        return [(installation, workspace)]

    async def get_tool_schemas_by_ids(*args, **kwargs):
        return []

    async def replace_agent_tools(*args, **kwargs):
        captured_assignments.extend(kwargs["server_assignments"])

    async def list_agent_tools(*args, **kwargs):
        return []

    async def list_agent_server_assignments(*args, **kwargs):
        server_assignment = AgentMCPServerAssignment(
            id=uuid4(),
            agent_id=agent.id,
            installation_id=installation.id,
            created_at=datetime(2026, 6, 23, tzinfo=UTC),
        )
        tool_assignment = AgentMCPToolAssignment(
            id=uuid4(),
            server_assignment_id=server_assignment.id,
            tool_schema_id=None,
            wildcard=True,
            created_at=datetime(2026, 6, 23, tzinfo=UTC),
        )
        return [(server_assignment, tool_assignment)]

    async def require_workspace_admin(*args, **kwargs):
        return None

    monkeypatch.setattr(service.repository, "get_agent", get_agent)
    monkeypatch.setattr(service.repository, "get_installations_by_ids", get_installations_by_ids)
    monkeypatch.setattr(service.repository, "get_tool_schemas_by_ids", get_tool_schemas_by_ids)
    monkeypatch.setattr(service.repository, "replace_agent_tools", replace_agent_tools)
    monkeypatch.setattr(service.repository, "list_agent_tools", list_agent_tools)
    monkeypatch.setattr(
        service.repository,
        "list_agent_server_assignments",
        list_agent_server_assignments,
    )
    monkeypatch.setattr(service, "require_workspace_admin", require_workspace_admin)

    response = await service.replace_agent_tools(
        FakeSession(),
        user,
        organization_id,
        agent.id,
        AgentToolAssignmentUpdate(
            servers=[
                {
                    "installationId": installation.id,
                    "toolSchemaIds": ["*"],
                }
            ]
        ),
    )

    assert captured_assignments == [(installation, True, [])]
    assert response.servers[0].installation_id == installation.id
    assert response.servers[0].tool_schema_ids == ["*"]
